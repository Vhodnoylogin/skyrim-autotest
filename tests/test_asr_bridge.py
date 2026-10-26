"""Protocol forwarding tests use a real temporary bus and injected HTTP peer."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import asr_bridge
from skyrim_autotest.command_bus import CommandBus


class Client:
    def __init__(self, bus):
        self.bus, self.requests, self.calls = bus, [], []
        self.lose_ack, self.offline = False, False
    def call(self, operation, arguments):
        self.calls.append((operation, copy.deepcopy(arguments)))
        if self.offline: raise OSError('receiver offline')
        return self.bus.status(**arguments)
    def submit(self, arguments):
        self.requests.append(copy.deepcopy(arguments))
        if self.offline: raise OSError('receiver offline')
        result = self.bus.submit(**arguments)
        if self.lose_ack:
            self.lose_ack = False
            raise OSError('ACK lost after durable receipt')
        return result


class ASRBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.state, self.channel = [self.root / name for name in ('heard.jsonl', 'own-cursor.json', 'channel.json')]
        self.source.touch()
        self.channel.write_text(json.dumps({'schemaVersion': 1, 'database': str(self.root / 'commands.sqlite3'),
            'tokenFile': str(self.root / 'private.token')}), encoding='utf-8')
        self.bus = CommandBus(self.root / 'commands.sqlite3')
        self.binding = {'provider': 'actual-host', 'conversationId': 'actual-chat-id', 'agentId': 'operator'}
        self.bus.create_session('owner-conversation')
        self.bus.bind('owner-conversation', self.binding)
        self.client = Client(self.bus)
    def tearDown(self):
        self.temp.cleanup()
    def row(self, seq, text='PRIVATE_OWNER_PHRASE'):
        return {'seq': seq, 'event': 'speech.final', 'revision': 2, 'text': text,
            'accepted': True, 'executable': True, 'final': True, 'audioComplete': True, 'endpointReason': 'pause',
            'utteranceId': f'{seq:032x}', 'audioSha256': 'a' * 64,
            'wav': str(self.root / 'NEVER-OPEN-THIS-AUDIO.wav'), 'at': '2026-10-26T00:00:00Z'}
    def raw(self, row):
        return json.dumps(row, ensure_ascii=False).encode('utf-8') + b'\n'
    def write(self, *rows):
        self.source.write_bytes(b''.join(self.raw(row) for row in rows))
    def bridge(self, after=None, **changes):
        args = dict(channel_config=self.channel, source=self.source, state=self.state,
                    session='owner-conversation', source_id='external.voice', after=after, client=self.client)
        args.update(changes)
        return asr_bridge.ASRBridge(**args)
    def poll(self, bridge):
        with asr_bridge.locked(bridge.lock): return bridge.once()
    def cursor(self):
        return json.loads(self.state.read_text())['cursor']

    def test_finals_enqueue_while_operator_busy_without_touching_source_or_shared_cursor(self):
        self.bus.submit('owner-conversation', 'typed.owner', 'busy', 'text', 'existing owner action')
        current = self.bus.next('owner-conversation', self.binding)['command']
        self.bus.delivered('owner-conversation', current['id'], current['claimId'], self.binding)
        shared = self.root / 'voice-shared-cursor.json'
        shared.write_text('existing shared voice state')
        self.write(self.row(1), self.row(2, 'Текст владельца'))
        source_before, shared_before = self.source.read_bytes(), shared.read_bytes()
        result = self.poll(self.bridge(after=0))
        self.assertEqual(result, {'forwarded': 2, 'cursor': 2, 'partialTail': False})
        self.assertEqual(self.bus.status('owner-conversation')['commands'], {'delivered': 1, 'received': 2})
        self.assertEqual((self.source.read_bytes(), shared.read_bytes()), (source_before, shared_before))
        self.assertTrue(all(item['kind'] == 'asr.final' for item in self.client.requests))
        self.assertTrue(all(item['sourceEventId'].endswith(':' + item['metadata']['utteranceId']) for item in self.client.requests))
        self.assertNotIn('PRIVATE_OWNER_PHRASE', self.state.read_text())

    def test_lost_ack_restarts_with_same_event_and_no_duplicate_command(self):
        self.write(self.row(1))
        self.client.lose_ack = True
        with self.assertRaises(asr_bridge.ReceiverUnavailable): self.poll(self.bridge(after=0))
        self.assertEqual(self.cursor(), 0)
        self.assertEqual(self.poll(self.bridge())['cursor'], 1)
        self.assertEqual(self.client.requests[0], self.client.requests[1])
        self.assertEqual(self.bus.status('owner-conversation')['commands'], {'received': 1})

    def test_crash_after_ack_before_cursor_commit_reuses_exact_identity(self):
        self.write(self.row(1))
        bridge = self.bridge(after=0)
        original = bridge._save
        def fail_commit(*args, **kwargs):
            if bridge.state['cursor'] == 1: raise OSError('cursor disk failure after ACK')
            return original(*args, **kwargs)
        with patch.object(bridge, '_save', side_effect=fail_commit):
            with self.assertRaisesRegex(OSError, 'after ACK'): self.poll(bridge)
        self.assertEqual(self.cursor(), 0)
        self.assertEqual(self.poll(self.bridge())['forwarded'], 1)
        self.assertEqual(self.client.requests[0], self.client.requests[1])
        self.assertEqual(self.bus.status('owner-conversation')['commands'], {'received': 1})

    def test_repeated_words_are_distinct_final_utterances(self):
        self.write(self.row(1, 'same words'), self.row(2, 'same words'))
        self.assertEqual(self.poll(self.bridge(after=0))['forwarded'], 2)
        self.assertNotEqual(self.client.requests[0]['sourceEventId'], self.client.requests[1]['sourceEventId'])

    def test_provisional_interrupted_rejected_and_unknown_shapes_never_forward(self):
        for change in ({'event': 'speech.partial'}, {'revision': 1}, {'audioComplete': False}, {'accepted': False},
                       {'endpointReason': 'capture_interrupted'}, {'interrupted': True}, {'executable': 1}):
            self.write(dict(self.row(1), **change))
            with self.subTest(change=change), self.assertRaises(ValueError): self.poll(self.bridge(after=0))
            self.assertFalse(self.state.exists())
        self.assertEqual(self.client.requests, [])

    def test_gap_sequence_duplicate_and_utterance_duplicate_stop_without_skipping(self):
        cases = [(self.row(2),), (self.row(1), self.row(1)),
                 (self.row(1), dict(self.row(2), utteranceId=self.row(1)['utteranceId']))]
        for rows in cases:
            self.write(*rows)
            with self.subTest(rows=rows), self.assertRaises(ValueError): self.poll(self.bridge(after=0))
        self.assertEqual(self.client.requests, [])

    def test_partial_tail_waits_until_complete_newline_then_forwards(self):
        self.source.write_bytes(self.raw(self.row(1)) + self.raw(self.row(2))[:-1])
        bridge = self.bridge(after=0)
        self.assertEqual(self.poll(bridge), {'forwarded': 1, 'cursor': 1, 'partialTail': True})
        with self.source.open('ab') as stream: stream.write(b'\n')
        self.assertEqual(self.poll(bridge), {'forwarded': 1, 'cursor': 2, 'partialTail': False})

    def test_malformed_complete_line_stops_and_partial_rewrite_is_detected(self):
        self.source.write_bytes(b'{bad complete json}\n')
        with self.assertRaises(ValueError): self.poll(self.bridge(after=0))
        self.source.write_bytes(self.raw(self.row(1))[:-1])
        bridge = self.bridge(after=0)
        self.assertEqual(self.poll(bridge)['forwarded'], 0)
        self.write(self.row(1, 'rewritten partial utterance'))
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'changed/truncated'): self.poll(bridge)
        self.assertEqual(self.client.requests, [])

    def test_acknowledged_prefix_rewrite_and_truncate_stop_without_more_submits(self):
        self.write(self.row(1))
        self.poll(self.bridge(after=0))
        self.write(self.row(1, 'changed source'), self.row(2))
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'changed/truncated'): self.poll(self.bridge())
        self.source.write_bytes(b'')
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'changed/truncated'): self.poll(self.bridge())
        self.assertEqual(len(self.client.requests), 1)

    def test_new_baseline_is_explicit_existing_cursor_cannot_reset(self):
        self.write(self.row(1), self.row(2))
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'explicit reviewed --after'): self.poll(self.bridge())
        self.assertEqual(self.poll(self.bridge(after=2))['forwarded'], 0)
        before = self.state.read_bytes()
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'never reset'): self.poll(self.bridge(after=0))
        self.assertEqual(self.state.read_bytes(), before)
        with self.source.open('ab') as stream: stream.write(self.raw(self.row(3)))
        self.assertEqual(self.poll(self.bridge())['forwarded'], 1)
        self.assertEqual(self.client.requests[0]['metadata']['seq'], 3)

    def test_receiver_unavailable_retains_cursor_and_recovers_without_rebaseline(self):
        self.write(self.row(1))
        self.client.offline = True
        bridge = self.bridge(after=0)
        with self.assertRaises(asr_bridge.ReceiverUnavailable): self.poll(bridge)
        self.assertEqual(self.cursor(), 0)
        self.client.offline = False
        self.assertEqual(self.poll(bridge)['cursor'], 1)

    def test_operator_session_source_and_namespace_identity_cannot_change(self):
        self.poll(self.bridge(after=0))
        for change in ({'session': 'other-session'}, {'source_id': 'other.voice'}):
            with self.subTest(change=change), self.assertRaisesRegex(asr_bridge.BridgeError, 'identity'):
                self.poll(self.bridge(**change))
        value = json.loads(self.state.read_text()); value['namespace'] = 'b' * 64
        self.state.write_text(json.dumps(value))
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'identity'): self.poll(self.bridge())
        self.assertEqual(self.client.requests, [])

    def test_rebinding_operator_session_stops_future_forwarding(self):
        self.write(self.row(1)); self.poll(self.bridge(after=0))
        current = self.bus.next('owner-conversation', self.binding)['command']
        self.bus.delivered('owner-conversation', current['id'], current['claimId'], self.binding)
        self.bus.complete('owner-conversation', current['id'], current['claimId'], self.binding)
        self.bus.bind('owner-conversation', dict(self.binding, agentId='different-agent'))
        with self.source.open('ab') as stream: stream.write(self.raw(self.row(2)))
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'binding changed'): self.poll(self.bridge())
        self.assertEqual(self.cursor(), 1)
        self.assertEqual(len(self.client.requests), 1)

    def test_lock_contention_does_not_take_source_or_shared_consumer_lock(self):
        bridge = self.bridge(after=0)
        with asr_bridge.locked(bridge.lock):
            with self.assertRaisesRegex(asr_bridge.BridgeError, 'Another forwarder'):
                with asr_bridge.locked(bridge.lock): pass
        with asr_bridge.locked(bridge.lock): pass
        self.assertFalse((self.root / 'consumer.lock').exists())

    def test_path_aliases_and_git_output_are_refused_without_modifying_source(self):
        before = self.source.read_bytes()
        with self.assertRaisesRegex(asr_bridge.BridgeError, 'separate'): self.bridge(after=0, state=self.source)
        checkout = self.root / 'checkout'; checkout.mkdir(); (checkout / '.git').mkdir()
        with self.assertRaises(ValueError): self.bridge(after=0, state=checkout / 'cursor.json')
        self.assertEqual(self.source.read_bytes(), before)

    def test_source_byte_bound_precedes_parsing_and_state_creation(self):
        self.source.write_bytes(b'x' * 257)
        with patch.object(asr_bridge, 'LIMIT', 256):
            with self.assertRaisesRegex(asr_bridge.BridgeError, '32MiB'): self.poll(self.bridge(after=0))
        self.assertFalse(self.state.exists())

    def test_serve_waits_for_new_source_without_creating_it_or_losing_first_utterance(self):
        self.source.unlink()
        args = ['--channel-config', str(self.channel), '--source', str(self.source), '--state', str(self.state),
                '--session', 'owner-conversation', '--source-id', 'external.voice', '--after', '0', '--serve']
        sleeps = []
        def poll_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1:
                self.assertFalse(self.source.exists())
                self.assertFalse(self.state.exists())
                self.write(self.row(1))  # Only the external producer creates this file.
            else: raise KeyboardInterrupt
        output = io.StringIO()
        with patch.object(asr_bridge, 'CommandHTTPClient', return_value=self.client), \
             patch.object(asr_bridge.time, 'sleep', side_effect=poll_sleep), contextlib.redirect_stdout(output):
            self.assertEqual(asr_bridge.main(args), 0)
        self.assertEqual(self.cursor(), 1)
        self.assertEqual(len(self.client.requests), 1)
        self.assertEqual(self.client.requests[0]['metadata']['seq'], 1)
        self.assertIn('source-pending', output.getvalue())
        self.source.unlink()
        with self.assertRaises(FileNotFoundError): self.poll(self.bridge())

    def test_initial_unbound_operator_waits_with_cursor_retained_then_forwards(self):
        self.bus.create_session('not-yet-bound')
        self.write(self.row(1))
        bridge = self.bridge(after=0, session='not-yet-bound')
        with self.assertRaisesRegex(asr_bridge.ReceiverUnavailable, 'not bound yet'): self.poll(bridge)
        self.assertEqual(self.cursor(), 0)
        self.assertEqual(self.client.requests, [])
        self.bus.bind('not-yet-bound', self.binding)
        self.assertEqual(self.poll(bridge)['cursor'], 1)
        self.assertEqual(len(self.client.requests), 1)

    def test_once_and_serve_emit_only_counts_or_safe_errors_not_phrases_or_tokens(self):
        self.write(self.row(1)); (self.root / 'private.token').write_text('PRIVATE_TOKEN_CONTENTS')
        args = ['--channel-config', str(self.channel), '--source', str(self.source), '--state', str(self.state),
                '--session', 'owner-conversation', '--source-id', 'external.voice', '--after', '0', '--serve']
        self.client.offline = True
        sleeps = []
        def poll_sleep(seconds):
            sleeps.append(seconds)
            if len(sleeps) == 1: self.client.offline = False
            else: raise KeyboardInterrupt
        output = io.StringIO()
        with patch.object(asr_bridge, 'CommandHTTPClient', return_value=self.client), \
             patch.object(asr_bridge.time, 'sleep', side_effect=poll_sleep), contextlib.redirect_stdout(output):
            self.assertEqual(asr_bridge.main(args), 0)
        self.assertEqual(self.cursor(), 1)
        self.assertTrue(all(seconds == .5 for seconds in sleeps))
        self.assertNotIn('PRIVATE_OWNER_PHRASE', output.getvalue())
        self.assertNotIn('PRIVATE_TOKEN_CONTENTS', output.getvalue())
        self.assertIn('receiver-unavailable', output.getvalue())


if __name__ == '__main__': unittest.main()
