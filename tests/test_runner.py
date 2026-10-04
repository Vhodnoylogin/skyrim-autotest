"""Regression checks for session isolation and recovery. Never launches Skyrim."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import native
from skyrim_autotest import runner
from skyrim_autotest.scenarios import check, validate


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.file = self.dir / 'original.ini'
        self.file.write_bytes(b'original\r\n')
        state = {'id': 'test', 'snapshots': [], 'owned': [], 'launchIntents': {}, 'checks': [],
                 'preflight': {'profile': 'fixture'}}
        self.session = runner.Session(self.dir, state)

    def tearDown(self):
        self.temp.cleanup()

    def test_repeated_write_keeps_first_backup_and_recovers(self):
        self.session.write(self.file, b'changed once')
        self.session.write(self.file, b'changed twice')
        with patch.object(native, 'processes', return_value=[]), patch.object(self.session, 'collect'):
            self.session.cleanup()
        self.assertEqual(self.file.read_bytes(), b'original\r\n')
        self.assertTrue(self.session.state['restored'])
        self.assertEqual(len(self.session.state['snapshots']), 1)

    def test_unrelated_game_blocks_restore(self):
        self.session.write(self.file, b'test state')
        unrelated = [{'pid': 999, 'parent': 1, 'name': 'SkyrimVR.exe'}]
        with patch.object(native, 'processes', return_value=unrelated), patch.object(self.session, 'collect'):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected session'):
                self.session.cleanup()
        self.assertEqual(self.file.read_bytes(), b'test state')

    def test_corrupt_backup_is_not_restored(self):
        self.session.write(self.file, b'test state')
        Path(self.session.state['snapshots'][0]['backup']).write_bytes(b'corrupt')
        with patch.object(native, 'processes', return_value=[]), patch.object(self.session, 'collect'):
            with self.assertRaisesRegex(RuntimeError, 'Restoration incomplete'):
                self.session.cleanup()
        self.assertFalse(self.session.state['restored'])
        self.assertEqual(self.file.read_bytes(), b'test state')

    def test_new_file_removed_without_touching_neighbors(self):
        new = self.dir / 'new.ini'
        self.session.write(new, b'test state')
        with patch.object(native, 'processes', return_value=[]), patch.object(self.session, 'collect'):
            self.session.cleanup()
        self.assertFalse(new.exists())
        self.assertEqual(self.file.read_bytes(), b'original\r\n')

    def test_pid_reuse_does_not_qualify_as_owned(self):
        old = {'pid': 1, 'birth': 100, 'path': 'old.exe'}
        with patch.object(native, 'identity', return_value={'pid': 1, 'birth': 101, 'path': 'old.exe'}):
            self.assertFalse(native.alive(old))
            with patch.object(native.K, 'OpenProcess') as open_process:
                native.terminate(old)
                open_process.assert_not_called()

    def test_assertions_use_returned_state_not_request_success(self):
        self.assertFalse(check({'returned': None}, {'path': 'returned', 'exists': True}))
        self.assertTrue(check({'returned': {'formId': '0xFF1'}}, {'path': 'returned.formId', 'equals': '0xFF1'}))

    def test_later_foreign_launch_is_not_discovered_as_owned(self):
        directory = self.dir.resolve()
        owned = {'pid': 5, 'birth': 134000000000000000, 'path': str(directory / 'sksevr_loader.exe')}
        ours = {'pid': 6, 'birth': owned['birth'] + 10, 'path': str(directory / 'SkyrimVR.exe')}
        foreign = {**ours, 'pid': 7}
        self.session.state['owned'] = [{'role': 'loader', 'identity': owned}]
        self.session.state['launchIntents'] = {'game': {'at': 0, 'directory': str(directory)}}
        items = [{'pid': 6, 'parent': 5, 'name': 'SkyrimVR.exe'}, {'pid': 7, 'parent': 100, 'name': 'SkyrimVR.exe'}]
        identities = {6: ours, 7: foreign}
        with patch.object(native, 'processes', return_value=items), patch.object(native, 'identity', side_effect=lambda pid: identities.get(pid)):
            self.session.discover()
        self.assertIn(ours, [p['identity'] for p in self.session.state['owned']])
        self.assertNotIn(foreign, [p['identity'] for p in self.session.state['owned']])

    def test_reused_parent_pid_does_not_qualify_as_ancestry(self):
        directory = self.dir.resolve()
        old = {'pid': 5, 'birth': 134000000000000000, 'path': str(directory / 'sksevr_loader.exe')}
        child = {'pid': 6, 'birth': old['birth'] + 100, 'path': str(directory / 'SkyrimVR.exe')}
        self.session.state['owned'] = [{'role': 'loader', 'identity': old}]
        self.session.state['launchIntents'] = {'game': {'at': 0, 'directory': str(directory)}}
        identities = {5: {**old, 'birth': old['birth'] + 50}, 6: child}
        with patch.object(native, 'processes', return_value=[{'pid': 6, 'parent': 5, 'name': 'SkyrimVR.exe'}]), patch.object(native, 'identity', side_effect=lambda pid: identities.get(pid)):
            self.session.discover()
        self.assertEqual(len(self.session.state['owned']), 1)


class ScenarioTests(unittest.TestCase):
    def test_observation_only_and_invalid_timeout_are_rejected(self):
        base = {'schemaVersion': 1, 'steps': [{'name': 'Observe', 'tool': 'inspect', 'observe': True}]}
        with self.assertRaisesRegex(ValueError, 'Observation-only'):
            validate(base)
        base['steps'][0]['assert'] = [{'exists': True}]
        for timeout in (0, -1, float('nan'), float('inf'), 181):
            base['steps'][0]['timeout'] = timeout
            with self.assertRaisesRegex(ValueError, 'timeout'):
                validate(base)

    def test_polling_mutation_cannot_be_hidden_behind_assertions(self):
        scenario = {'schemaVersion': 1, 'steps': [{'name': 'Mutate', 'tool': 'console', 'args': {'command': 'player.additem'}, 'poll': True, 'assert': [{'exists': True}]}]}
        with self.assertRaisesRegex(ValueError, 'read-only'):
            validate(scenario)
        scenario['steps'][0].update(tool='inspect', args={'kind': 'scene'})
        validate(scenario)


class MutexTests(unittest.TestCase):
    def test_second_process_cannot_own_session(self):
        # Real Windows mutex, isolated from any concurrent owner's game run.
        import uuid
        name = 'Local\\SkyrimVRAutotestRegression-' + uuid.uuid4().hex
        original = native.K.CreateMutexW
        with patch.object(native.K, 'CreateMutexW', side_effect=lambda attributes, owner, _: original(attributes, owner, name)):
            with native.SessionMutex():
                command = "import sys; sys.path.insert(0,sys.argv[1]); from skyrim_autotest import native; original=native.K.CreateMutexW; native.K.CreateMutexW=lambda a,b,c:original(a,b,sys.argv[2]); native.SessionMutex().__enter__()"
                child = subprocess.run([sys.executable, '-c', command, str(Path(__file__).parent.parent), name], capture_output=True, text=True)
                self.assertNotEqual(child.returncode, 0)
                self.assertIn('Another test runner', child.stderr)



class HardwareTests(unittest.TestCase):
    def test_rotation_rejects_reflection_and_degenerate_basis(self):
        from skyrim_autotest.hardware import quaternion
        self.assertEqual(quaternion([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]), [1, 0, 0, 0])
        for x in (0, -1):
            with self.assertRaises(ValueError):
                quaternion([x, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0])

    def test_invalid_controller_frame_does_not_write_file(self):
        from skyrim_autotest import hardware
        frame = hardware.neutral()
        frame['right']['controller']['axes'][0][0] = float('nan')
        with patch.object(hardware.PATH.__class__, 'write_text') as write:
            with self.assertRaises(ValueError):
                hardware.publish(frame)
            write.assert_not_called()


if __name__ == '__main__':
    unittest.main()
