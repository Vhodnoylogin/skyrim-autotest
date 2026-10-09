import json
from pathlib import Path
import tempfile
import unittest
import uuid

from skyrim_autotest.voice_inbox import Inbox


class BufferedVoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.heard = self.root / 'heard.jsonl'
        self.heard.touch()
        self.box = Inbox(self.root / 'inbox', str(uuid.uuid4()))
        self.box.init(self.heard, 0, buffered=True)

    def append(self, seq, **fields):
        with self.heard.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(seq=seq, at='2026-10-09T00:00:00Z',
                                         text='Полигон, проверка', **fields)) + '\n')

    def admit(self, seq):
        self.append(seq)
        return self.box.admit()

    def dispatch(self, item):
        self.box.dispatch(item['id'], item['recordsSha256'])

    def complete(self, item):
        return self.box.ack(item['id'], item['recordsSha256'], 'reply-' + item['id'])

    def test_later_speech_delivered_without_earlier_completion(self):
        first = self.admit(1)
        self.dispatch(first)
        second = self.admit(2)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(second['firstSeq'], 2)
        self.assertEqual(second['cursor'], 0)
        self.assertEqual(second['admittedCursor'], 2)
        self.dispatch(second)
        self.complete(second)
        self.assertEqual(self.box.status()['cursor'], 0)
        self.assertEqual(self.complete(first)['cursor'], 2)

    def test_dispatch_uncertainty_never_replays_but_preserves_new_input(self):
        first = self.admit(1)
        self.dispatch(first)
        with self.assertRaises(ValueError):
            self.dispatch(first)
        self.assertEqual(self.box.admit()['status'], 'quiet')
        self.assertEqual(self.admit(2)['firstSeq'], 2)
        restarted = Inbox(self.box.folder, self.box.thread)
        self.assertEqual(restarted.status()['deliveries'][0]['phase'], 'dispatching')

    def test_receipt_does_not_complete_request_or_advance_processed_cursor(self):
        item = self.admit(1)
        self.dispatch(item)
        self.box.dispatch(item['id'], item['recordsSha256'], 'host.json')
        self.box.reply(item['id'], item['recordsSha256'], 'actual-first-text')
        state = self.box.status()
        self.assertEqual(state['cursor'], 0)
        self.assertEqual(state['deliveries'][0]['phase'], 'delivered')
        self.assertIn('firstReplyAt', state['deliveries'][0])
        self.complete(item)
        self.assertEqual(self.complete(item)['status'], 'already_acknowledged')

    def test_fast_operator_completion_before_host_receipt_is_preserved(self):
        item = self.admit(1)
        self.dispatch(item)
        self.complete(item)
        self.box.dispatch(item['id'], item['recordsSha256'], 'late-host.json')
        self.assertEqual(self.box.status()['deliveries'][0]['phase'], 'completed')

    def test_unattempted_or_wrong_hash_cannot_be_completed(self):
        item = self.admit(1)
        with self.assertRaises(ValueError):
            self.complete(item)
        with self.assertRaises(ValueError):
            self.box.dispatch(item['id'], 'wrong')

    def test_all_admitted_records_verified_after_restart(self):
        item = self.admit(1)
        self.dispatch(item)
        self.admit(2)
        rows = [json.loads(r) for r in self.heard.read_text(encoding='utf-8').splitlines()]
        rows[0]['text'] = 'changed'
        self.heard.write_text(''.join(json.dumps(r) + '\n' for r in rows), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.box.admit()

    def test_upgrade_never_discards_pending_legacy_request(self):
        legacy = Inbox(self.root / 'old', self.box.thread)
        legacy.init(self.heard, 0)
        self.append(1)
        claim = legacy.claim()
        with self.assertRaises(ValueError):
            legacy.upgrade()
        legacy.ack(claim['id'], claim['recordsSha256'], 'old-reply')
        legacy.upgrade()
        self.append(2)
        self.assertEqual(legacy.admit()['firstSeq'], 2)
        with self.assertRaises(ValueError):
            legacy.claim()
        with self.assertRaises(ValueError):
            legacy.init(self.heard, 2)

    def test_provisional_incomplete_or_nonexecutable_record_blocks(self):
        for field in ('final', 'audioComplete', 'executable'):
            self.heard.write_text('')
            self.append(1, **{field: False})
            with self.assertRaises(ValueError):
                self.box.admit()
        self.heard.write_text('')
        self.append(1, final=True, audioComplete=True, executable=True)
        self.assertEqual(self.box.admit()['status'], 'received')
