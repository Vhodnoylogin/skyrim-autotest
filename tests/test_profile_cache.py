"""Non-game coverage for reusable profile identity, archive and recovery."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import profile_cache as cache, runner, native


class ProfileCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profiles = self.root / 'profiles'
        self.source = self.profiles / 'Owner'
        self.source.mkdir(parents=True)
        (self.source / 'modlist.txt').write_text('+Mod\n')
        (self.source / 'settings.ini').write_text('[General]\nLocalSaves=false\n')
        (self.source / 'saves').mkdir()
        (self.source / 'saves' / 'owner.ess').write_bytes(b'owner save')
        self.runtime = self.root / 'runtime'
        self.key, self.name = cache.identity(self.source, self.profiles)

    def acquire(self, run):
        return cache.acquire(self.runtime, self.profiles, self.key, self.name, run, runner.atomic_json)

    def release(self, run):
        cache.release(self.runtime, self.profiles, self.key, self.name, run,
                      self.root / (run + '-evidence'), runner.atomic_json)

    def test_reuses_directory_and_resets_saves_without_touching_owner(self):
        target, reused = self.acquire('one')
        self.assertFalse(reused)
        cache.reset(target, self.source, self.root / 'previous-one')
        (target / 'saves' / 'test.ess').write_bytes(b'changed')
        (target / 'settings.ini').write_text('changed')
        self.release('one')
        self.assertFalse(target.exists())
        target2, reused = self.acquire('two')
        self.assertTrue(reused)
        self.assertEqual(target, target2)
        cache.reset(target2, self.source, self.root / 'previous-two')
        self.assertEqual(list((target2 / 'saves').iterdir()), [])
        self.assertIn('LocalSaves=false', (target2 / 'settings.ini').read_text())
        self.assertEqual((self.source / 'saves' / 'owner.ess').read_bytes(), b'owner save')
        self.assertEqual((self.root / 'one-evidence' / 'saves' / 'test.ess').read_bytes(), b'changed')
        self.release('two')

    def test_source_composition_change_gets_another_identity(self):
        (self.source / 'modlist.txt').write_text('+Other\n')
        self.assertNotEqual(cache.identity(self.source, self.profiles)[0], self.key)

    def test_refuses_unresolved_owner_and_tampered_archive(self):
        target, _ = self.acquire('one')
        with self.assertRaisesRegex(RuntimeError, 'still mounted'):
            self.acquire('two')
        cache.reset(target, self.source, self.root / 'previous')
        self.release('one')
        home, _ = cache.paths(self.runtime, self.profiles, self.key, self.name)
        (home / 'profile' / 'settings.ini').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError, 'integrity'):
            self.acquire('two')

    def test_release_is_idempotent_but_rejects_foreign_run(self):
        self.acquire('one')
        self.release('one')
        self.release('one')
        with self.assertRaisesRegex(RuntimeError, 'another run'):
            self.release('two')

    def test_recovers_death_after_archive_move(self):
        target, _ = self.acquire('one')
        cache.reset(target, self.source, self.root / 'previous')
        self.release('one')
        home, _ = cache.paths(self.runtime, self.profiles, self.key, self.name)
        record = json.loads((home / 'record.json').read_text())
        record['state'] = 'leased'
        runner.atomic_json(home / 'record.json', record)
        self.release('one')
        self.assertEqual(json.loads((home / 'record.json').read_text())['state'], 'archived')


class BorrowedMO2RecoveryTests(unittest.TestCase):
    def test_keeps_borrowed_mo2_alive_and_restores_profile_via_bridge(self):
        with tempfile.TemporaryDirectory() as tmp:
            idle = {'pid': 17, 'birth': 123, 'path': str(Path(tmp) / 'ModOrganizer.exe')}
            state = {'id': 'test', 'snapshots': [], 'owned': [], 'launchIntents': {},
                     'borrowedMO2': idle, 'preflight': {'originalBridgeProfile': 'Owner'}}
            session = runner.Session(Path(tmp), state)
            with patch.object(native, 'processes', return_value=[{'pid': 17, 'name': 'ModOrganizer.exe', 'parent': 1}]), \
                    patch.object(native, 'alive', return_value=True), patch.object(native, 'identity', return_value=idle), \
                    patch.object(session, 'collect'), patch.object(session, 'bridge_profile') as switch, \
                    patch.object(native, 'close') as close, patch.object(native, 'terminate') as kill:
                session.cleanup()
            switch.assert_called_once_with('Owner', restoring=True)
            close.assert_not_called()
            kill.assert_not_called()
            self.assertTrue(state['restored'])

    def test_changed_bridge_identity_never_selects_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / 'token'
            token.write_text('secret')
            state = {'borrowedMO2': {'pid': 17}, 'preflight': {'bridgeSession': {'mo2Pid': 17}}}
            session = runner.Session(Path(tmp), state)
            with patch.dict(runner.P.value, {'bridge_token': str(token), 'bridge_port': 1}), \
                    patch.object(native, 'alive', return_value=True), \
                    patch.object(runner, 'request', return_value={'mo2Pid': 18}) as request:
                with self.assertRaisesRegex(runner.Blocked, 'session changed'):
                    session.bridge_profile('Owner')
            self.assertEqual(request.call_count, 1)

    def test_bridge_selection_is_identity_bound_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            token = Path(tmp) / 'token'
            token.write_text('secret')
            bridge = {'mo2Pid': 17, 'serverBootId': 'boot', 'instanceId': 'instance', 'profilesPath': tmp}
            state = {'borrowedMO2': {'pid': 17}, 'preflight': {
                'bridgeSession': bridge, 'originalBridgeProfile': 'Owner'}, 'testProfileName': 'Test'}
            session = runner.Session(Path(tmp), state)
            responses = [bridge, {}, {'profile': 'Owner'}, {'applied': True, 'current': 'Test'}, {'profile': 'Test'}]
            with patch.dict(runner.P.value, {'bridge_token': str(token), 'bridge_port': 1}), \
                    patch.object(native, 'alive', return_value=True), \
                    patch.object(runner, 'request', side_effect=responses) as request:
                session.bridge_profile('Test')
            body = request.call_args_list[3].args[2]
            self.assertEqual(body['expectedProfile'], 'Owner')
            self.assertEqual(body['expectedServerBootId'], 'boot')
            self.assertEqual(body['expectedInstance'], 'instance')
            self.assertEqual(request.call_args_list[-1].args[1], 'ping')

    def test_foreign_game_blocks_even_bridge_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            idle = {'pid': 17}
            state = {'id': 'test', 'snapshots': [], 'owned': [], 'launchIntents': {},
                     'borrowedMO2': idle, 'preflight': {'originalBridgeProfile': 'Owner'}}
            session = runner.Session(Path(tmp), state)
            processes = [{'pid': 17, 'name': 'ModOrganizer.exe', 'parent': 1},
                         {'pid': 22, 'name': 'SkyrimVR.exe', 'parent': 1}]
            with patch.object(native, 'processes', return_value=processes), \
                    patch.object(native, 'alive', return_value=True), patch.object(native, 'identity', return_value=idle), \
                    patch.object(session, 'collect'), patch.object(session, 'bridge_profile') as switch:
                with self.assertRaisesRegex(RuntimeError, 'Unexpected session before Bridge'):
                    session.cleanup()
            switch.assert_not_called()
