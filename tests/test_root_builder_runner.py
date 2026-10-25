"""Owned Root Builder orchestration using synthetic trees and mocked transports."""
import copy
import hashlib
import json
import os
from pathlib import Path
import zipfile
import unittest
from unittest import mock

from skyrim_autotest import config, native, root_builder as rb, runner
import test_root_builder as fixtures


class RootBuilderRunnerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RootBuilderTests(methodName='runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        previous = copy.deepcopy(config.P.value)
        previous_root, previous_runs = runner.ROOT, runner.RUNS
        self.addCleanup(lambda: setattr(config.P, 'value', previous))
        self.addCleanup(lambda: setattr(runner, 'ROOT', previous_root))
        self.addCleanup(lambda: setattr(runner, 'RUNS', previous_runs))
        self.value = config.template('vr')
        self.value.update(copy.deepcopy(self.fixture.config))
        self.value.update(runtime=str(self.root / 'runtime'), fixture_dir=None,
                          bridge_token=str(self.root / 'bridge-token.txt'),
                          openvr_paths=str(self.root / 'openvr.json'),
                          skse_logs=str(self.root / 'skse-logs'),
                          required_mods=[self.fixture.loader_mod])
        Path(self.value['bridge_token']).write_text('synthetic-token')
        runtime = self.root / 'steamvr'
        inputs = runtime / 'drivers/htc/resources/input'
        inputs.mkdir(parents=True)
        (inputs / 'vive_controller_profile.json').write_text('{}')
        settings = self.root / 'steamvr-config'
        settings.mkdir()
        (settings / 'steamvr.vrsettings').write_text('{}')
        Path(self.value['openvr_paths']).write_text(json.dumps({
            'runtime': [str(runtime)], 'config': [str(settings)], 'external_drivers': []}))
        (self.fixture.data / 'Backup/openvr_api.dll').write_bytes(b'synthetic stock OpenVR')
        (self.fixture.profile / 'plugins.txt').write_text('*synthetic.esm\n')
        self.fixture.ini.write_text('[General]\nselected_profile=@ByteArray(Source)\n' + self.fixture.ini.read_text())
        runner.configure(self.value)
        archive = runner.ROOT / 'dependencies/driver-dedb8ab.zip'
        archive.parent.mkdir(parents=True)
        driver = b'synthetic null driver, never loaded'
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('null/bin/win64/driver_null.dll', driver)
        for patch in (mock.patch.object(runner, 'DRIVER_ZIP_HASH', runner.sha(archive)),
                      mock.patch.object(runner, 'DRIVER_DLL_HASH', hashlib.sha256(driver).hexdigest()),
                      mock.patch.object(runner.urllib.request, 'urlopen', side_effect=AssertionError('network forbidden')),
                      mock.patch.dict(os.environ, {'PROGRAMDATA': str(self.root / 'program-data')}),
                      mock.patch.object(native, 'alive', side_effect=lambda identity: bool(
                          identity and self.fixture.identities.get(identity['pid']) == identity))):
            patch.start()
            self.addCleanup(patch.stop)
        self.number = 0

    def preflight(self):
        return runner.preflight('Source')

    def session(self, info=None, *, run_id=None):
        self.number += 1
        run_id = run_id or 'orchestration-' + str(self.number)
        directory = runner.RUNS / run_id
        directory.mkdir(parents=True)
        owner = {'pid': 1, 'birth': 10, 'path': str(self.root / 'python.exe')}
        self.fixture.identities[1] = owner
        state = dict(id=run_id, runner=owner, snapshots=[], owned=[], launchIntents={},
                     checks=[], preflight=info if info is not None else self.preflight(),
                     configuration=config.P.snapshot(), scenario={}, driverBackend='devbench',
                     inputBackend='devbench', restored=False, result='passed')
        return runner.Session(directory, state)

    def stage(self, destination='Root/new-root-input.ini'):
        source = self.root / 'stage.ini'
        source.write_bytes(b'explicit staged Root input')
        self.value['staged_plugins'] = [{'source': str(source), 'destination': destination,
            'sha256': runner.sha(source)}]
        runner.configure(self.value)
        return config.P.overwrite / destination

    def test_configuration_requires_explicit_data_vr_and_cold_owned_mode(self):
        normalized = config.configure(self.value)
        self.assertEqual(normalized['root_builder_data'], str(self.fixture.data.resolve()))
        for change in ({'root_builder_data': None}, {'game_edition': 'se'}, {'reuse_test_profile': True}):
            with self.subTest(change=change), self.assertRaises(config.ConfigurationError):
                config.configure(dict(self.value, **change))

    def test_preflight_uses_exact_contract_and_does_not_waive_missing_loader_without_policy(self):
        other = config.P.mo2 / 'plugins/data/RootBuilder/unrelated/Backup'
        other.mkdir(parents=True)
        (other / 'openvr_api.dll').write_bytes(b'unrelated backup cannot select the instance')
        info = self.preflight()
        self.assertFalse((config.P.game / 'sksevr_loader.exe').exists())
        self.assertEqual(info['rootBuilderData'], str(self.fixture.data))
        self.assertEqual(info['stockOpenVR'], str(self.fixture.data / 'Backup/openvr_api.dll'))
        self.assertEqual(info['rootBuilder']['paths']['root_builder_data'], str(self.fixture.data))
        without_policy = dict(self.value)
        without_policy.pop('root_builder')
        runner.configure(without_policy)
        with self.assertRaisesRegex(runner.Blocked, 'Missing required file.*sksevr_loader'):
            self.preflight()

    def test_setup_closes_idle_mo2_then_prepares_before_staging_and_preserves_new_build_metadata(self):
        staged = self.stage()
        info = self.preflight()
        idle = {'pid': 11, 'birth': 100, 'path': str(config.P.mo2_exe)}
        self.fixture.identities[11] = idle
        info['idleMO2'] = idle
        session = self.session(info)
        events = []
        actual = rb.prepare
        def close(identity, **kwargs):
            self.assertEqual(identity, idle)
            self.assertTrue(kwargs['system_command'])
            events.append('close')
            self.fixture.identities.pop(identity['pid'])
        def prepare(owned, contract):
            self.assertFalse(native.alive(idle))
            self.assertFalse(staged.exists())
            events.append('prepare')
            actual(owned, contract)
            (self.fixture.data / 'BuildData.json').write_text('synthetic later build metadata')
        with mock.patch.object(native, 'close', side_effect=close), mock.patch.object(rb, 'prepare', side_effect=prepare):
            session.setup()
        self.assertEqual(events, ['close', 'prepare'])
        self.assertEqual(staged.read_bytes(), b'explicit staged Root input')
        self.assertEqual((self.fixture.data / 'BuildData.json').read_text(), 'synthetic later build metadata')
        paths = [entry['path'].casefold() for entry in session.state['snapshots']]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual((Path(session.state['testProfile']) / 'modlist.txt').read_text(),
                         '+SKSEVR fixture\n-' + self.fixture.ocu + '\n-disabled source\n')

    def test_setup_revalidates_closed_profile_settings_package_and_metadata_before_writes(self):
        staged = self.stage()
        cases = [
            (self.fixture.ini, lambda text: text.replace('autobuild=true', 'autobuild=false')),
            (self.fixture.ini, lambda text: text.replace('1\\arguments=', '1\\arguments=--unexpected')),
            (self.fixture.plugin / 'synthetic.py', lambda text: text + '# changed package\n'),
            (self.fixture.profile / 'modlist.txt', lambda text: text + '# changed profile\n'),
            (self.fixture.profile / 'plugins.txt', lambda text: text + '*changed.esm\n'),
        ]
        for path, changed in cases:
            with self.subTest(path=path.name):
                info = self.preflight()
                session = self.session(info)
                original = path.read_bytes()
                path.write_text(changed(path.read_text()))
                try:
                    with self.assertRaises((ValueError, runner.Blocked)):
                        session.setup()
                    self.assertNotIn('rootBuilder', session.state)
                    self.assertNotIn('testProfile', session.state)
                    self.assertFalse(staged.exists())
                    self.assertEqual(session.state['snapshots'], [])
                finally:
                    path.write_bytes(original)

    def test_close_persisted_settings_and_new_version_metadata_refuse_prepare(self):
        session = self.session()
        idle = {'pid': 11, 'birth': 100, 'path': str(config.P.mo2_exe)}
        self.fixture.identities[11] = idle
        session.state['preflight']['idleMO2'] = idle
        original = self.fixture.ini.read_bytes()
        def close(identity, **kwargs):
            self.fixture.identities.pop(identity['pid'])
            self.fixture.ini.write_text(self.fixture.ini.read_text().replace('autobuild=true', 'autobuild=false'))
        with mock.patch.object(native, 'close', side_effect=close), mock.patch.object(rb, 'prepare') as prepare:
            with self.assertRaisesRegex(ValueError, 'autobuild'):
                session.setup()
        prepare.assert_not_called()
        self.assertEqual(session.state['snapshots'], [])
        self.fixture.ini.write_bytes(original)
        session = self.session()
        manifest = Path(session.state['preflight']['rootBuilder']['versionManifest'])
        manifest.write_text('{"synthetic":"new metadata after preflight"}')
        with mock.patch.object(rb, 'prepare') as prepare:
            with self.assertRaisesRegex(runner.Blocked, 'changed while closing'):
                session.setup()
        prepare.assert_not_called()
        self.assertEqual(session.state['snapshots'], [])

    def test_generic_snapshot_and_write_reject_immutable_game_executable_and_inode_alias(self):
        alias = self.root / 'external-shared-game.exe'
        os.link(self.fixture.game / 'SkyrimVR.exe', alias)
        session = self.session()
        rb.prepare(session, session.state['preflight']['rootBuilder'])
        count = len(session.state['snapshots'])
        for path in (self.fixture.game / 'SkyrimVR.exe', alias):
            with self.subTest(path=path), self.assertRaisesRegex(runner.Blocked, 'immutable hard-linked'):
                session.snapshot(path)
            with self.subTest(write=path), self.assertRaisesRegex(runner.Blocked, 'immutable hard-linked'):
                session.write(path, b'forbidden replacement')
        self.assertEqual(len(session.state['snapshots']), count)
        self.assertEqual(alias.read_bytes(), b'synthetic game')
        self.assertTrue(alias.samefile(self.fixture.game / 'SkyrimVR.exe'))

    def launch_transport(self, session, *, changed_session=None, changed_ping=None, changed_receipt=None):
        session.state.update(testProfileName='Autotest-' + session.state['id'])
        runtime_file = self.root / 'devbench-runtime.json'
        runtime_file.write_text(json.dumps({'port': 17777}))
        mo2 = {'pid': 11, 'birth': 100, 'path': str(config.P.mo2_exe)}
        game = {'pid': 13, 'birth': 102, 'path': str(config.P.game / 'SkyrimVR.exe')}
        ping = {'profile': session.state['testProfileName'], 'game': 'SkyrimVR', 'modsPath': str(config.P.mods)}
        identity = {'serverBootId': 'boot-1', 'instanceId': 'instance-1', 'mo2Pid': 11,
                    'profilesPath': str(config.P.profiles)}
        receipt = {'serverBootId': 'boot-1', 'started': True, 'applied': True, 'processHandleOwned': True,
                   'pid': 12, 'key': 'boot-1:p1', 'process': {'pid': 12, 'creationTime': 101,
                   'exitTime': None, 'path': str(config.P.game / 'sksevr_loader.exe'), 'role': 'loader'}}
        ping.update(changed_ping or {})
        identity.update(changed_session or {})
        receipt.update(changed_receipt or {})
        calls = []
        frames = iter((5, 6))
        def spawn(command, role, cwd=None):
            if role == 'mo2':
                self.fixture.identities[11] = mo2
                session.state['owned'].append({'role': 'mo2', 'identity': mo2})
        def discover():
            if session.state['launchIntents'].get('game') and not any(row['role'] == 'game' for row in session.state['owned']):
                self.fixture.identities[13] = game
                session.state['owned'].append({'role': 'game', 'identity': game})
        def request(port, route, body=None, **kwargs):
            calls.append((port, route, copy.deepcopy(body)))
            if route == 'ping': return copy.deepcopy(ping)
            if route == 'session': return copy.deepcopy(identity)
            if route == 'run': return copy.deepcopy(receipt)
            if route == 'api/health': return {'pid': 13, 'frame': next(frames)}
            raise AssertionError('Unexpected transport route: ' + route)
        patches = [mock.patch.object(session, 'spawn', side_effect=spawn),
                   mock.patch.object(session, 'discover', side_effect=discover),
                   mock.patch.object(session, 'own', side_effect=AssertionError('PID-only ownership forbidden')),
                   mock.patch.object(session, 'wait_task_queue'),
                   mock.patch.object(runner, 'request', side_effect=request),
                   mock.patch.object(native, 'processes', return_value=[{'pid': 21, 'parent': 20, 'name': 'vrcompositor.exe'}]),
                   mock.patch('skyrim_autotest.editions.runtime_candidates', return_value=[runtime_file]),
                   mock.patch.object(runner.time, 'sleep')]
        return calls, patches

    def test_launch_uses_session_identity_and_expected_guards_with_handle_backed_exited_loader(self):
        session = self.session()
        rb.prepare(session, session.state['preflight']['rootBuilder'])
        calls, patches = self.launch_transport(session)
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        session.launch()
        self.assertEqual([route for _, route, _ in calls], ['ping', 'session', 'run', 'api/health', 'api/health'])
        launch = next(body for _, route, body in calls if route == 'run')
        self.assertEqual({key: launch[key] for key in ('expectedServerBootId', 'expectedInstance', 'expectedProfile')},
                         {'expectedServerBootId': 'boot-1', 'expectedInstance': 'instance-1',
                          'expectedProfile': session.state['testProfileName']})
        receipt = session.state['rootBuilder']['loaderReceipt']
        self.assertEqual(receipt['identity'], {'pid': 12, 'birth': 101, 'path': str(config.P.game / 'sksevr_loader.exe')})
        self.assertIsNone(native.identity(12))
        self.assertEqual(session.state['game']['pid'], 13)
        session.wait_task_queue.assert_called_once_with()

    def test_foreign_or_missing_bridge_session_identity_refuses_launch_before_run(self):
        changes = [{'mo2Pid': 999}, {'profilesPath': str(self.root / 'foreign-profiles')},
                   {'serverBootId': ''}, {'instanceId': ''}]
        for change in changes:
            with self.subTest(change=change):
                session = self.session()
                session.state['rootBuilder'] = {'phase': 'prepared'}
                calls, patches = self.launch_transport(session, changed_session=change)
                try:
                    for patch in patches: patch.start()
                    with self.assertRaisesRegex(runner.Blocked, 'exact live owned MO2'):
                        session.launch()
                    self.assertNotIn('run', [route for _, route, _ in calls])
                finally:
                    for patch in reversed(patches): patch.stop()
                    self.fixture.identities.pop(11, None)

    def deployed_session(self, *, existing_stage=False):
        if existing_stage:
            target = self.fixture.overwrite / 'Root/new-root-input.ini'
            target.parent.mkdir()
            target.write_bytes(b'owner Root source')
        staged = self.stage()
        session = self.session(run_id='run-1')
        rb.prepare(session, session.state['preflight']['rootBuilder'])
        session.write(staged, b'explicit staged Root input')
        self.fixture.session = session
        self.fixture.launch()
        self.fixture.deploy(session.state['rootBuilder']['contract'])
        rb.verify_started(session)
        self.fixture.ended()
        return session, staged

    def test_cleanup_excludes_helper_scope_removes_new_stage_first_and_recovery_is_idempotent(self):
        session, staged = self.deployed_session()
        protected = set(session.state['rootBuilder']['snapshotPaths'])
        actual_restore, actual_file = rb.restore, session.restore_file
        in_helper = False
        counts = {'helperFiles': 0}
        def file(entry):
            if entry['path'] in protected:
                self.assertTrue(in_helper, 'generic restoration wrote helper-managed snapshot')
                counts['helperFiles'] += 1
            actual_file(entry)
        def restore(owned):
            nonlocal in_helper
            self.assertFalse(staged.exists())
            self.assertTrue(owned.state['rootBuilderMO2Finished']['verified'])
            in_helper = True
            try: actual_restore(owned)
            finally: in_helper = False
        with mock.patch.object(session, 'discover'), mock.patch.object(session, 'collect') as collect, \
             mock.patch.object(session, 'restore_file', side_effect=file), mock.patch.object(rb, 'restore', side_effect=restore):
            session.cleanup()
            first = counts['helperFiles']
            session.cleanup()
        self.assertTrue(session.state['restored'])
        self.assertGreater(first, 0)
        self.assertEqual(counts['helperFiles'], first)
        collect.assert_called_once_with()
        self.assertFalse((self.fixture.overwrite / 'Root').exists())
        self.assertFalse((self.fixture.game / 'sksevr_loader.exe').exists())

    def test_cleanup_existing_staged_root_source_is_restored_only_by_helper(self):
        session, staged = self.deployed_session(existing_stage=True)
        actual_restore, actual_file = rb.restore, session.restore_file
        in_helper = False
        observed = []
        def file(entry):
            if Path(entry['path']) == staged:
                self.assertTrue(in_helper)
                observed.append(entry['path'])
            actual_file(entry)
        def restore(owned):
            nonlocal in_helper
            self.assertEqual(staged.read_bytes(), b'explicit staged Root input')
            in_helper = True
            try: actual_restore(owned)
            finally: in_helper = False
        with mock.patch.object(session, 'discover'), mock.patch.object(session, 'collect'), \
             mock.patch.object(session, 'restore_file', side_effect=file), mock.patch.object(rb, 'restore', side_effect=restore):
            session.cleanup()
        self.assertEqual(staged.read_bytes(), b'owner Root source')
        self.assertEqual(len(observed), 1)
        self.assertTrue(session.state['restored'])

    def test_helper_failure_leaves_restored_false_then_resumes_durable_intent(self):
        session, staged = self.deployed_session()
        actual_save = session.save
        stopped = False
        def save():
            nonlocal stopped
            actual_save()
            if not stopped and session.state['rootBuilder']['phase'] == 'restoring':
                stopped = True
                raise OSError('synthetic interruption after durable restoration intent')
        with mock.patch.object(session, 'discover'), mock.patch.object(session, 'collect') as collect, \
             mock.patch.object(session, 'save', side_effect=save):
            with self.assertRaisesRegex(OSError, 'durable restoration intent'):
                session.cleanup()
            self.assertFalse(session.state['restored'])
            self.assertEqual(session.state['restoreErrors'][0]['path'], 'root-builder-managed-view')
            self.assertFalse(staged.exists())
            self.assertTrue(Path(session.state['testProfile']).is_dir())
            self.assertIsNotNone(session.state['rootBuilder']['restoreIntent'])
            session.cleanup()
        collect.assert_called_once_with()
        self.assertTrue(session.state['restored'])
        self.assertEqual(session.state['rootBuilder']['phase'], 'restored')

    def test_foreign_process_blocks_all_file_restoration_and_finished_marker(self):
        session, staged = self.deployed_session()
        foreign = [{'pid': 99, 'parent': 0, 'name': 'ModOrganizer.exe'}]
        with mock.patch.object(session, 'discover'), mock.patch.object(session, 'collect'), \
             mock.patch.object(native, 'processes', return_value=foreign), \
             mock.patch.object(session, 'restore_file') as restore_file, mock.patch.object(rb, 'restore') as restore:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected session'):
                session.cleanup()
        restore_file.assert_not_called()
        restore.assert_not_called()
        self.assertFalse(session.state['restored'])
        self.assertEqual(staged.read_bytes(), b'explicit staged Root input')
        # The fixture's earlier marker is not an authorization to bypass a fresh busy guard.
        self.assertEqual(session.state['rootBuilderMO2Finished']['at'], 123.0)


if __name__ == '__main__':
    unittest.main()
