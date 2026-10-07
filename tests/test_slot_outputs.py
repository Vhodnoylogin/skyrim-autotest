import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from skyrim_autotest import config, runner, slot_outputs as output, subject_state as subject


class SlotOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.target = self.root/'slots.ini'
        self.written = b'; retain comment\r\n[Slots]\r\nallowSmallSlot14 = 1\r\nvisibleSlot14 = 1\r\nposX14 = -3.7267840\r\nrotA14 = -0.7024480\r\n'
        self.target.write_bytes(self.written)
        self.record = {'path': str(self.target), 'sha256': output.digest(self.written),
                       'writtenSha256': output.digest(self.written), 'writtenBytesHex': self.written.hex(),
                       'writeOrdinal': 2, 'slotSubject': 'Subject'}
        self.game = {'pid': 17, 'birth': 123}
        self.state = {'game': copy.deepcopy(self.game), 'snapshots': [{'path': str(self.target), 'exists': False}],
                      'ownedLoadTransition': {'completed': True, 'afterGame': copy.deepcopy(self.game)},
                      'fixtureSettingsWrites': {str(self.target): self.record}}
        self.backend = Mock(); self.backend.s.state = self.state
        self.values = {'posX14': -5.1288495, 'rotA14': -0.7105380}
        self.backend.pap_read_batch.side_effect = lambda rows: [self.values[row['args'][0]] for row in rows]
        self.actual = self.written.replace(b'-3.7267840', b'-5.1288495').replace(b'-0.7024480', b'-0.7105380')

    def test_native_pose_output_allows_next_owned_write_without_changing_original_backup(self):
        self.target.write_bytes(self.actual)
        sample = output.capture(self.backend, self.target, 'Subject')
        output.reconcile(self.backend, self.target, 'Subject', sample)
        self.assertEqual(subject.bytes_for(self.backend, self.target), self.actual)
        self.assertEqual(self.record['writtenBytesHex'], self.written.hex())
        self.assertEqual(self.record['writtenSha256'], output.digest(self.written))
        self.assertFalse(self.state['snapshots'][0]['exists'])
        history = self.state['fixtureSettingsOutputHistory']
        self.assertEqual(history[0]['changedKeys'], ['posX14', 'rotA14'])
        self.assertEqual(history[0]['writerIdentity'], 'unknown')
        self.assertEqual(sample['game'], self.game)

    def test_exit_save_may_be_corroborated_by_same_pre_exit_sample_without_live_reads(self):
        sample = output.capture(self.backend, self.target, 'Subject')
        self.state['ownedLoadTransition'] = {'completed': False}
        self.target.write_bytes(self.actual)
        self.backend.pap_read_batch.reset_mock()
        output.reconcile(self.backend, self.target, 'Subject', sample)
        self.backend.pap_read_batch.assert_not_called()
        self.assertEqual(self.record['sha256'], output.digest(self.actual))

    def test_flag_unknown_comment_duplicate_and_nonfinite_edits_cannot_be_adopted(self):
        sample = output.capture(self.backend, self.target, 'Subject')
        for changed in (self.actual.replace(b'visibleSlot14 = 1', b'visibleSlot14 = 0'),
                        self.actual + b'foreign = 1\r\n', self.actual.replace(b'retain comment', b'foreign comment'),
                        self.actual + b'posX14 = -5.1288495\r\n', self.actual.replace(b'-5.1288495', b'NaN')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.target.write_bytes(changed)
                output.reconcile(self.backend, self.target, 'Subject', sample)
            self.assertEqual(self.record['sha256'], output.digest(self.written))
        self.assertNotIn('fixtureSettingsOutputHistory', self.state)

    def test_unmatched_native_pose_or_changed_process_write_identity_never_adopted(self):
        sample = output.capture(self.backend, self.target, 'Subject'); self.target.write_bytes(self.actual)
        for key, change in (('values', dict(sample['values'], posX14=-9)), ('game', {'pid': 17, 'birth': 999}),
                            ('writeOrdinal', 3), ('writtenSha256', '0'*64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                output.reconcile(self.backend, self.target, 'Subject', dict(sample, **{key: change}))
        self.assertEqual(self.record['sha256'], output.digest(self.written))

    def test_native_sample_must_be_stable_finite_current_and_complete(self):
        for values in ([1], [float('nan'), 0], [False, 0]):
            with self.subTest(values=values), patch.object(self.backend, 'pap_read_batch', return_value=values), self.assertRaises(ValueError):
                output.capture(self.backend, self.target, 'Subject')
        with patch.object(self.backend, 'pap_read_batch', side_effect=[[1, 0], [2, 0]]), self.assertRaisesRegex(ValueError, 'changed'):
            output.capture(self.backend, self.target, 'Subject')
        self.state['ownedLoadTransition']['completed'] = False
        with self.assertRaisesRegex(ValueError, 'completed owned load'):
            output.capture(self.backend, self.target, 'Subject')

    def test_unowned_or_legacy_file_retains_strict_guard(self):
        self.record.pop('slotSubject'); self.target.write_bytes(self.actual)
        self.assertIsNone(output.capture(self.backend, self.target, 'Subject'))
        with self.assertRaisesRegex(ValueError, 'last verified bytes'):
            subject.bytes_for(self.backend, self.target)

    def test_numeric_tolerance_does_not_accept_nonpose_structure_changes(self):
        sample = output.capture(self.backend, self.target, 'Subject')
        self.target.write_bytes(self.actual.replace(b'-0.7105380', b'-0.71053798'))
        output.reconcile(self.backend, self.target, 'Subject', sample)
        self.assertEqual(self.record['sha256'], output.digest(self.target.read_bytes()))


if __name__ == '__main__': unittest.main()
