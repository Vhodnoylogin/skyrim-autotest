import json
import contextlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
import uuid

from skyrim_autotest.voice_inbox import Inbox, locked, main


class VoiceInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.heard = self.root / "heard.jsonl"
        self.heard.write_text('', encoding='utf-8')
        self.thread = str(uuid.uuid4())
        self.box = Inbox(self.root / 'inbox', self.thread)
        self.box.init(self.heard, 0)

    def append(self, seq, text='Полигон, проверка'):
        with self.heard.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(seq=seq, at='2026-10-08T22:00:00', text=text)) + '\n')

    def test_unacked_replayed_for_review_not_new_claim(self):
        self.append(1)
        claim = self.box.claim()
        self.assertEqual(claim['status'], 'claimed')
        self.append(2)
        repeated = self.box.claim()
        self.assertEqual(repeated['status'], 'pending_review')
        self.assertEqual(repeated['id'], claim['id'])
        self.box.ack(claim['id'], claim['recordsSha256'], 'reply1')
        self.assertEqual(self.box.claim()['firstSeq'], 2)

    def test_ack_is_idempotent_but_conflicts_fail(self):
        self.append(1)
        claim = self.box.claim()
        args = (claim['id'], claim['recordsSha256'], 'reply1')
        self.box.ack(*args)
        self.assertEqual(self.box.ack(*args)['status'], 'already_acknowledged')
        with self.assertRaises(ValueError):
            self.box.ack(args[0], args[1], 'other')
        self.assertEqual(self.box.claim()['status'], 'quiet')

    def test_partial_append_waits_then_is_delivered(self):
        self.heard.write_bytes(b'{"seq":1')
        self.assertEqual(self.box.claim()['status'], 'quiet')
        self.heard.write_text('', encoding='utf-8')
        self.append(1)
        self.assertEqual(self.box.claim()['firstSeq'], 1)

    def test_malformed_complete_line_blocks(self):
        self.heard.write_text('broken\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.box.claim()

    def test_duplicate_gap_and_reset_block(self):
        self.append(1)
        claim = self.box.claim()
        self.box.ack(claim['id'], claim['recordsSha256'], 'reply1')
        self.heard.write_text('', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.box.claim()
        self.append(1)
        self.append(3)
        with self.assertRaises(ValueError):
            self.box.claim()

    def test_rewritten_pending_and_anchor_block(self):
        self.append(1)
        claim = self.box.claim()
        self.heard.write_text('', encoding='utf-8')
        self.append(1, 'changed')
        with self.assertRaises(ValueError):
            self.box.ack(claim['id'], claim['recordsSha256'], 'reply1')
        with self.assertRaises(ValueError):
            self.box.claim()

    def test_private_consumer_does_not_touch_other_cursor(self):
        cursor = self.root / 'cursor'
        cursor.write_text('999')
        self.append(1)
        self.box.claim()
        self.assertEqual(cursor.read_text(), '999')
        other = Inbox(self.root / 'other', str(uuid.uuid4()))
        other.init(self.heard, 0)
        self.assertEqual(other.claim()['firstSeq'], 1)

    def test_wrong_chat_and_baseline_reinit_cannot_skip_pending(self):
        self.append(1)
        claim = self.box.claim()
        self.box.init(self.heard, 1)
        self.assertEqual(self.box.claim()['id'], claim['id'])
        with self.assertRaises(ValueError):
            Inbox(self.box.folder, str(uuid.uuid4())).claim()

    def test_single_consumer_lock(self):
        with locked(self.box.folder):
            with self.assertRaises(OSError):
                self.box.claim()

    def test_bounded_batch_preserves_remainder(self):
        for seq in range(1, 67):
            self.append(seq)
        claim = self.box.claim()
        self.assertEqual(len(claim['records']), 64)
        self.box.ack(claim['id'], claim['recordsSha256'], 'reply1')
        self.assertEqual(self.box.claim()['lastSeq'], 66)

    def test_wait_returns_promptly_on_new_record_and_rejects_long_wait(self):
        timer = threading.Timer(.1, self.append, args=(1,))
        timer.start()
        self.addCleanup(timer.join)
        output = io.StringIO()
        started = time.monotonic()
        args = ['--inbox', str(self.box.folder), '--thread', self.thread, 'claim']
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(args + ['--wait', '3']), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'claimed')
        self.assertLess(time.monotonic() - started, 2)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ['--wait', '31']), 2)


if __name__ == '__main__':
    unittest.main()
