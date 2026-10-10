import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid
import subprocess
from unittest.mock import patch

from skyrim_autotest.voice_inbox import Inbox, atomic, locked
from skyrim_autotest.voice_operator import Operator
from skyrim_autotest.voice_listener import Session


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.thread = str(uuid.uuid4())
        self.session = self.root / 'session'
        self.session.mkdir()
        self.heard = self.session / 'heard.jsonl'
        self.heard.touch()
        self.box = Inbox(self.root / 'inbox', self.thread, lock_wait=.25)
        self.box.init(self.heard, 0, buffered=True)
        self.ident = {'pid': 1234, 'birth': 123456789, 'path': 'C:/Python/python.exe'}
        self.lock = self.root / 'listen.lock'
        atomic(self.lock, {'pid': 1234, 'identity': self.ident, 'protocol': 'whole-utterance-v2'})
        atomic(self.session / 'health.json', {'pid': 1234, 'ok': True, 'captureActive': True,
               'replay': False, 'checkedAt': time.time(), 'heard': str(self.heard)})
        self.op = Operator({'threadId': self.thread, 'runtime': str(self.root / 'operator'),
            'listenLock': str(self.lock), 'existing': {'pid': 1234, 'session': str(self.session),
            'inbox': str(self.box.folder)}, 'asrConfig': str(self.root / 'asr.json'), 'device': 'headset'})
        self.pid_patch = patch('skyrim_autotest.voice_operator.process_identity', return_value=self.ident)
        self.pid_patch.start()
        self.addCleanup(self.pid_patch.stop)

    def append(self, seq, **extra):
        with self.heard.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'seq': seq, 'text': 'owner speech', 'at': '2026-10-10T00:00:00Z',
                                'audioComplete': True, 'final': True, 'executable': True, **extra}) + '\n')

    def test_receive_is_once_and_preserves_uncertain_completion(self):
        self.append(1)
        first = self.box.receive_local()
        self.assertEqual(first['status'], 'delivered')
        again = self.box.receive_local()
        self.assertEqual(again['status'], 'pending_review')
        self.assertNotIn('records', again)
        self.assertEqual(again['pending'][0]['id'], first['id'])
        self.append(2)
        second = self.box.receive_local()
        self.assertEqual(second['firstSeq'], 2)
        self.box.ack(second['id'], second['recordsSha256'], 'done2')
        self.assertEqual(self.box.status()['cursor'], 0)
        self.box.ack(first['id'], first['recordsSha256'], 'done1')
        self.assertEqual(self.box.status()['cursor'], 2)

    def test_direct_poll_does_not_resend_previous_host_dispatch(self):
        self.append(1)
        first = self.box.admit()
        self.box.dispatch(first['id'], first['recordsSha256'])
        self.assertEqual(self.box.receive_local()['status'], 'pending_review')
        self.append(2)
        self.assertEqual(self.box.receive_local()['firstSeq'], 2)
        self.assertEqual(self.box.status()['deliveries'][0]['phase'], 'dispatching')

    def test_provisional_and_rewritten_queue_remain_blocked(self):
        self.append(1, final=False)
        with self.assertRaises(ValueError):
            self.box.receive_local()
        self.assertEqual(self.box.state()['cursor'], 0)
        self.heard.write_text('')
        self.append(1)
        self.box.receive_local()
        self.heard.write_text('')
        self.append(1, text='changed')
        with self.assertRaises(ValueError):
            self.box.receive_local()

    def test_visible_reply_time_not_invented_or_replaced(self):
        self.append(1)
        item = self.box.receive_local()
        self.box.reply(item['id'], item['recordsSha256'], 'actual-message-ref')
        row = self.box.status()['deliveries'][0]
        self.assertIsNone(row['firstVisibleReplyAt'])
        self.assertEqual(row['replyRecordedAt'], row['firstReplyAt'])
        with self.assertRaises(ValueError):
            self.box.reply(item['id'], item['recordsSha256'], 'actual-message-ref', time.time())

    def test_actual_reply_timestamp_requires_dispatch_order(self):
        self.append(1)
        item = self.box.receive_local()
        with self.assertRaises(ValueError):
            self.box.reply(item['id'], item['recordsSha256'], 'actual-message-ref', 1)
        visible = time.time()
        self.box.reply(item['id'], item['recordsSha256'], 'actual-message-ref', visible)
        self.assertEqual(self.box.status()['deliveries'][0]['firstVisibleReplyAt'], visible)

    def test_attach_reuses_listener_and_exact_old_cursor_without_spawn(self):
        self.append(1)
        item = self.box.receive_local()
        self.box.ack(item['id'], item['recordsSha256'], 'done')
        with patch('skyrim_autotest.voice_operator.subprocess.Popen') as spawn:
            result = self.op.ensure('owner-message-id')
            self.assertEqual(result['status'], 'ready')
            self.assertEqual(result['conversation']['status'], 'legacy_listener_requires_ordinary_address')
            self.assertEqual(self.op.ensure('next-start-message')['status'], 'reused')
            spawn.assert_not_called()
        self.assertEqual(self.box.status()['cursor'], 1)

    def test_operator_receives_in_own_call_without_app_bridge(self):
        self.op.ensure('owner-message')
        self.append(1)
        result = self.op.poll()
        self.assertEqual(result['records'][0]['text'], 'owner speech')
        self.assertEqual(result['deliveryTransport'], 'operator-poll')
        self.assertEqual(result['threadId'], self.thread)
        self.assertEqual(self.op.poll()['status'], 'pending_review')

    def test_unknown_live_singleton_never_taken_over(self):
        self.op.config.pop('existing')
        original = self.lock.read_bytes()
        with patch('skyrim_autotest.voice_operator.subprocess.Popen') as spawn:
            with self.assertRaises(ValueError):
                self.op.ensure('owner-message')
            spawn.assert_not_called()
        self.assertEqual(self.lock.read_bytes(), original)

    def test_changed_identity_or_stale_health_not_ready(self):
        atomic(self.lock, {'pid': 1234, 'identity': {**self.ident, 'birth': 9},
                          'protocol': 'whole-utterance-v2'})
        with self.assertRaises(ValueError):
            self.op.ensure('owner-message')
        atomic(self.lock, {'pid': 1234, 'identity': self.ident, 'protocol': 'whole-utterance-v2'})
        h = json.loads((self.session / 'health.json').read_text())
        h['checkedAt'] = time.time() - 10
        atomic(self.session / 'health.json', h)
        with self.assertRaises(ValueError):
            self.op.ensure('owner-message')

    def test_foreign_inbox_or_operator_binding_blocked(self):
        d = self.box.state()
        d['threadId'] = str(uuid.uuid4())
        atomic(self.box.path, d)
        with self.assertRaises(ValueError):
            self.op.ensure('owner-message')
        self.assertFalse(self.op.binding.exists())

    def test_wait_and_owner_scope_validation_before_actions(self):
        with self.assertRaises(ValueError):
            self.op.ensure('')
        for wait in (float('nan'), 31, -1):
            with self.assertRaises(ValueError):
                self.op.poll(wait)
        with locked(self.box.folder):
            with self.assertRaises(OSError):
                self.box.receive_local()

    def test_dead_singleton_archived_then_single_new_listener_started(self):
        self.op.config.pop('existing')
        previous = self.lock.read_bytes()
        new_ident = {**self.ident, 'pid': 5678, 'birth': 999999999}
        def lookup(pid):
            return new_ident if pid == 5678 else None
        def spawn(argv, **kwargs):
            session = Path(argv[argv.index('--session') + 1])
            session.mkdir()
            (session / 'heard.jsonl').touch()
            atomic(self.lock, {'pid': 5678, 'identity': new_ident, 'protocol': 'whole-utterance-v2'})
            atomic(session / 'health.json', {'pid': 5678, 'ok': True, 'captureActive': True,
                'capturedSamples': 3200, 'replay': False, 'checkedAt': time.time(),
                'heard': str(session / 'heard.jsonl')})
            class Child:
                pid = 5678
                def poll(self): return None
            return Child()
        with patch('skyrim_autotest.voice_operator.process_identity', side_effect=lookup), \
             patch('skyrim_autotest.voice_operator.subprocess.Popen', side_effect=spawn) as start:
            result = self.op.ensure('direct-owner-start')
            self.assertEqual(result['identity'], new_ident)
            self.assertEqual(self.op.ensure('another-owner-start')['status'], 'reused')
            self.assertEqual(start.call_count, 1)
            self.assertEqual(start.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
        archives = list(self.op.root.glob('dead-singleton-*.json'))
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_bytes(), previous)
        self.assertTrue(self.box.path.exists())

    def test_inspection_error_cannot_clear_lock_or_spawn(self):
        original = self.lock.read_bytes()
        with patch('skyrim_autotest.voice_operator.process_identity', side_effect=PermissionError('denied')), \
             patch('skyrim_autotest.voice_operator.subprocess.Popen') as start:
            with self.assertRaises(OSError): self.op.ensure('owner-start')
            start.assert_not_called()
        self.assertEqual(self.lock.read_bytes(), original)

    def test_local_stdout_uncertainty_is_not_automatic_redelivery(self):
        self.append(1)
        from skyrim_autotest import voice_inbox
        real = voice_inbox.atomic
        def failing_after_write(path, value):
            real(path, value)
            if value['deliveries'][0]['phase'] == 'delivered':
                raise OSError('interrupted after durable receipt')
        with patch.object(voice_inbox, 'atomic', side_effect=failing_after_write):
            with self.assertRaises(OSError): self.box.receive_local()
        self.assertEqual(self.box.receive_local()['status'], 'pending_review')


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.thread = str(uuid.uuid4())
        self.session = Session(Path(self.tmp.name) / 'session', {'cli': 'unused', 'model': 'unused'},
                               operator_thread=self.thread)
        self.addCleanup(self.session.close)

    def control(self, **extra):
        d = {'id': uuid.uuid4().hex, 'threadId': self.thread, 'ownerRef': 'human-start-message',
             'seconds': 1800, 'at': time.time(), **extra}
        atomic(self.session.folder / 'conversation-request.json', d)
        self.session.apply_control()
        return d

    def test_owner_start_opens_dialog_without_required_test_phrase(self):
        d = self.control()
        self.assertGreater(self.session.until, time.monotonic())
        self.assertEqual(self.session.health['conversationControlId'], d['id'])
        self.control(seconds=0)
        self.assertLessEqual(self.session.until, time.monotonic())
        self.assertIsNone(self.session.error)

    def test_invalid_foreign_and_stale_controls_do_not_kill_capture(self):
        for extra in ({'threadId': str(uuid.uuid4())}, {'at': time.time() - 20}, {'at': 'bad'},
                      {'seconds': 14401}, {'event': 'speech.final'}):
            self.control(**extra)
            self.assertEqual(self.session.until, 0)
            self.assertIsNone(self.session.error)
        path = self.session.folder / 'conversation-request.json'
        path.write_text('broken')
        self.session.apply_control()
        before = self.session.events.read_bytes()
        self.session.apply_control()
        self.assertEqual(self.session.events.read_bytes(), before)

    def test_control_accepts_only_fresh_audio_and_known_visible_timestamp(self):
        self.control()
        def asr(argv, **kwargs):
            output = argv[argv.index('-of') + 1] + '.json'
            Path(output).write_text(json.dumps({'transcription': [{'text': 'обычная новая команда'}]}))
            return subprocess.CompletedProcess(argv, 0)
        source = self.session.folder / 'stub.wav'
        source.write_bytes(b'not-used-by-mock')
        def audio(identity, captured):
            return {'utteranceId': identity, 'wav': str(source), 'captureStartedAt': captured,
                    'audioComplete': True, 'final': True}
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=asr):
            self.session.transcribe(audio('old', self.session.control_started_at - 1))
            self.assertEqual(self.session.seq, 0)
            self.session.transcribe(audio('fresh', time.time()))
            self.assertEqual(self.session.seq, 1)
            self.control(seconds=0)
            self.session.transcribe(audio('closed', time.time()))
            self.assertEqual(self.session.seq, 1)

    def test_active_owner_dialog_survives_ordinary_idle_window(self):
        self.control(seconds=14400)
        def asr(argv, **kwargs):
            Path(argv[argv.index('-of') + 1] + '.json').write_text(
                json.dumps({'transcription': [{'text': 'обычный вопрос'}]}))
            return subprocess.CompletedProcess(argv, 0)
        source = self.session.folder / 'stub.wav'
        source.write_bytes(b'mock')
        now = time.monotonic()
        self.session.until = now - 1
        self.session.woke = now - 1900
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=asr):
            self.session.transcribe({'utteranceId': 'after-idle', 'wav': str(source),
                'captureStartedAt': time.time(), 'audioComplete': True, 'final': True})
        self.assertEqual(self.session.seq, 1)


if __name__ == '__main__':
    unittest.main()
