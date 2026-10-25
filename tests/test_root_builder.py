"""Synthetic Root Builder trees and retained-handle receipts; no native launches."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from skyrim_autotest import root_builder as rb
from skyrim_autotest import native


class RootBuilderTests(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory()
        self.addCleanup(self.box.cleanup)
        self.root = Path(self.box.name)
        self.game = self.root / 'game'
        self.mo2 = self.root / 'mo2'
        self.mods = self.root / 'mods'
        self.overwrite = self.root / 'overwrite'
        self.profiles = self.root / 'profiles'
        self.profile = self.profiles / 'Source'
        self.plugin = self.mo2 / 'plugins/rootbuilder'
        for directory in (self.game / 'Data/empty-original', self.mo2, self.mods,
                          self.overwrite, self.profile, self.plugin):
            directory.mkdir(parents=True, exist_ok=True)
        (self.plugin / 'synthetic.py').write_text('# synthetic package fixture, no MO2 code\n')
        pin = rb.plugin_fingerprint(self.plugin)
        patch = mock.patch.object(rb, 'SUPPORTED_PLUGIN_SHA256', pin)
        patch.start()
        self.addCleanup(patch.stop)
        (self.mo2 / 'ModOrganizer.exe').write_bytes(b'synthetic mo2')
        (self.game / 'SkyrimVR.exe').write_bytes(b'synthetic game')
        (self.game / 'Data/stock.bsa').write_bytes(b'excluded BSA content')
        (self.game / 'empty-managed').mkdir()
        self.loader_mod = 'SKSEVR fixture'
        self.source = self.mods / self.loader_mod / 'Root'
        self.source.mkdir(parents=True)
        bundle = {}
        for name in sorted(rb._BUNDLE):
            (self.source / name).write_bytes(('synthetic ' + name).encode())
            bundle[name] = hashlib.sha256((self.source / name).read_bytes()).hexdigest()
        disabled = self.mods / 'disabled source' / 'Root'
        disabled.mkdir(parents=True)
        (disabled / 'disabled.ini').write_bytes(b'old disabled source')
        self.ocu = next(iter(sorted(rb._DISABLED)))
        ocu_root = self.mods / self.ocu / 'Root'
        ocu_root.mkdir(parents=True)
        (ocu_root / 'openvr_api.dll').write_bytes(b'disabled by the declared SteamVR fixture')
        (self.profile / 'modlist.txt').write_text(f'+{self.loader_mod}\n+{self.ocu}\n-disabled source\n')
        safe = str(self.game).replace(' ', '_').replace('.', '_')
        for character in '<>:|*\\/?"':
            safe = safe.replace(character, '')
        self.data = self.mo2 / 'plugins/data/RootBuilder' / safe / '1_4_15_0'
        (self.data / 'Backup').mkdir(parents=True)
        cache = {'skyrimvr.exe': {'Relative': 'SkyrimVR.exe', 'Hash': '0' * 32, 'Modified': 1.0,
                                  'Size': (self.game / 'SkyrimVR.exe').stat().st_size}}
        (self.data / 'GameData.json').write_text(json.dumps(cache))
        self.ini = self.mo2 / 'ModOrganizer.ini'
        self.ini.write_text('[customExecutables]\n1\\title=SKSE\n1\\binary=' + str(self.game / 'sksevr_loader.exe') +
                            '\n1\\workingDirectory=' + str(self.game) + '\n1\\arguments=\n[Plugins]\n' +
                            '\n'.join('RootBuilder\\' + key + '=' + value for key, value in {
                                'copyfiles': '**', 'linkfiles': '', 'usvfsfiles': '', 'autobuild': 'true',
                                'hash': 'true', 'backup': 'true', 'cache': 'true', 'migrated': 'true',
                                'exclusions': 'Saves,Morrowind.ini,Data,Data Files'}.items()))
        self.config = {'game_edition': 'vr', 'game': str(self.game), 'mo2': str(self.mo2),
                       'mo2_ini': str(self.ini), 'mo2_exe': str(self.mo2 / 'ModOrganizer.exe'),
                       'mods': str(self.mods), 'overwrite': str(self.overwrite), 'profiles': str(self.profiles),
                       'root_builder_data': str(self.data), 'staged_plugins': [],
                       'root_builder': {'mode': 'copy-5.1.1', 'pluginTreeSha256': pin,
                                        'loaderMod': self.loader_mod, 'bundleSha256': bundle}}
        journal = self.root / 'external-runtime/run-1'
        journal.mkdir(parents=True)
        self.session = SimpleNamespace(dir=journal, state={'id': 'run-1', 'snapshots': [], 'owned': [],
                                       'configuration': copy.deepcopy(self.config)}, saves=0)
        def save():
            self.session.saves += 1
        self.session.save = save
        def snapshot(path):
            path = Path(path).resolve()
            if any(entry['path'] == str(path) for entry in self.session.state['snapshots']):
                return
            entry = {'path': str(path), 'exists': path.is_file()}
            if path.is_file():
                backup = journal / 'backups' / str(len(self.session.state['snapshots']))
                backup.parent.mkdir(exist_ok=True)
                shutil.copy2(path, backup)
                entry.update(backup=str(backup), sha256=hashlib.sha256(backup.read_bytes()).hexdigest())
            self.session.state['snapshots'].append(entry)
            save()
        self.session.snapshot = snapshot
        def restore_file(entry):
            path = Path(entry['path'])
            if entry['exists']:
                backup = Path(entry['backup'])
                if hashlib.sha256(backup.read_bytes()).hexdigest() != entry['sha256']:
                    raise ValueError('corrupt backup fixture')
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup, path)
            elif path.exists():
                path.unlink()
        self.session.restore_file = restore_file
        self.identities = {}
        self.process_rows = []
        for patch in (mock.patch.object(native, 'identity', lambda pid: copy.deepcopy(self.identities.get(pid))),
                      mock.patch.object(native, 'alive', lambda identity: self.identities.get(identity['pid']) == identity),
                      mock.patch.object(native, 'processes', lambda: list(self.process_rows))):
            patch.start()
            self.addCleanup(patch.stop)

    def prepare(self):
        contract = rb.preflight(self.config, self.profile)
        rb.prepare(self.session, contract)
        return contract

    def launch(self, *, live_loader=False):
        mo2 = {'pid': 11, 'birth': 100, 'path': str(self.mo2 / 'ModOrganizer.exe')}
        self.identities[11] = mo2
        self.session.state['owned'].append({'role': 'mo2', 'identity': mo2})
        process = {'pid': 12, 'creationTime': 101, 'exitTime': None,
                   'path': str(self.game / 'sksevr_loader.exe'), 'role': 'loader'}
        if live_loader:
            self.identities[12] = {'pid': 12, 'birth': 101, 'path': process['path']}
        launch = {'serverBootId': 'boot-1', 'started': True, 'applied': True,
                  'processHandleOwned': True, 'pid': 12, 'process': process, 'key': 'boot-1:p1'}
        ping = {'serverBootId': 'boot-1', 'mo2Pid': 11}
        rb.record_launch(self.session, launch, ping)
        return launch, ping

    def deploy(self, contract):
        copied = {}
        for key, winner in contract['winners'].items():
            target = self.game / winner['relative']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(winner['source'], target)
            copied[key] = {'Source': winner['source'], 'Relative': winner['relative'], 'Hash': '0' * 32}
        (self.data / 'BuildData.json').write_text(json.dumps({'Copy': copied, 'Link': {}, 'USVFS': {}}))
        test = self.profiles / 'Autotest-run-1'
        test.mkdir(exist_ok=True)
        text = (self.profile / 'modlist.txt').read_text()
        text = '\n'.join('-' + line[1:] if line.startswith('+') and line[1:] in rb._DISABLED else line
                         for line in text.splitlines()) + '\n'
        (test / 'modlist.txt').write_text(text)
        self.session.state['testProfile'] = str(test)
        game = {'pid': 13, 'birth': 102, 'path': str(self.game / 'SkyrimVR.exe')}
        self.identities[13] = game
        self.session.state['game'] = game
        self.session.state['owned'].append({'role': 'game', 'identity': game})

    def ended(self):
        self.identities.clear()
        self.session.state['rootBuilderMO2Finished'] = {'verified': True, 'game': self.session.state.get('game'),
            'ownedMO2': [row['identity'] for row in self.session.state['owned'] if row['role'] == 'mo2'], 'at': 123.0}

    def test_read_only_plan_accepts_absent_physical_loader_without_hashing_data(self):
        original = rb._hash
        def bounded(path, **kwargs):
            self.assertNotIn('stock.bsa', str(path))
            return original(path, **kwargs)
        with mock.patch.object(rb, '_hash', bounded):
            contract = rb.preflight(self.config, self.profile)
        self.assertFalse((self.game / 'sksevr_loader.exe').exists())
        self.assertEqual(set(contract['winners']), rb._BUNDLE)
        self.assertEqual(contract['disabledMods'], [self.ocu])
        self.assertFalse(self.session.state.get('rootBuilder'))

    def test_rejects_unsupported_settings_plugin_paths_and_stale_build(self):
        for old, new in (('copyfiles=**', 'copyfiles=*.exe'), ('autobuild=true', 'autobuild=false'),
                         ('linkfiles=', 'linkfiles=*.dll'), ('cache=true', 'cache=false'),
                         ('Data,Data Files', 'Data,other')):
            text = self.ini.read_text()
            self.ini.write_text(text.replace(old, new))
            with self.assertRaises(ValueError):
                rb.preflight(self.config, self.profile)
            self.ini.write_text(text)
        (self.data / 'BuildData.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'clean inactive'):
            rb.preflight(self.config, self.profile)
        (self.data / 'BuildData.json').unlink()
        (self.plugin / 'synthetic.py').write_text('changed package')
        with self.assertRaisesRegex(ValueError, 'fingerprint changed'):
            rb.preflight(self.config, self.profile)

    def test_rejects_reuse_wrong_registered_loader_and_ambiguous_sources(self):
        self.config['reuse_test_profile'] = True
        with self.assertRaises(ValueError):
            rb.preflight(self.config, self.profile)
        self.config.pop('reuse_test_profile')
        text = self.ini.read_text()
        self.ini.write_text(text.replace(str(self.game / 'sksevr_loader.exe'), str(self.source / 'sksevr_loader.exe')))
        with self.assertRaisesRegex(ValueError, 'Registered SKSE'):
            rb.preflight(self.config, self.profile)
        self.ini.write_text(text)
        root = self.overwrite / 'Root'
        root.mkdir()
        (root / 'sksevr_loader.exe').write_bytes((self.source / 'sksevr_loader.exe').read_bytes())
        with self.assertRaisesRegex(ValueError, 'shadowed'):
            rb.preflight(self.config, self.profile)

    def test_prepare_records_before_mutation_and_rejects_preflight_drift(self):
        contract = rb.preflight(self.config, self.profile)
        (self.source / 'sksevr_loader.exe').write_bytes(b'changed after plan')
        with self.assertRaisesRegex(ValueError, 'changed after preflight'):
            rb.prepare(self.session, contract)
        self.assertNotIn('rootBuilder', self.session.state)

    def test_retained_handle_receipt_captures_short_lived_loader_without_pid_guessing(self):
        self.prepare()
        self.launch()
        receipt = self.session.state['rootBuilder']['loaderReceipt']
        self.assertEqual(receipt['identity']['birth'], 101)
        self.assertIsNone(receipt['exitTime'])
        self.assertTrue(any(row['role'] == 'loader' for row in self.session.state['owned']))

    def test_rejects_false_or_foreign_loader_receipt(self):
        self.prepare()
        launch, ping = self.launch()
        self.session.state['rootBuilder'].pop('loaderReceipt')
        for field, value in (('serverBootId', 'other'), ('processHandleOwned', False), ('applied', False), ('pid', 999)):
            changed = copy.deepcopy(launch)
            changed[field] = value
            with self.assertRaises(ValueError):
                rb.record_launch(self.session, changed, ping)
        self.identities[12] = {'pid': 12, 'birth': 999, 'path': str(self.game / 'sksevr_loader.exe')}
        with self.assertRaisesRegex(ValueError, 'reused'):
            rb.record_launch(self.session, launch, ping)

    def test_actual_mapping_deployed_hash_and_owned_game_are_required(self):
        contract = self.prepare()
        self.launch()
        self.deploy(contract)
        (self.game / 'sksevr_1_4_15.dll').write_bytes(b'wrong deployed image')
        with self.assertRaisesRegex(ValueError, 'Deployed SKSEVR'):
            rb.verify_started(self.session)
        shutil.copy2(self.source / 'sksevr_1_4_15.dll', self.game / 'sksevr_1_4_15.dll')
        rb.verify_started(self.session)
        self.assertEqual(self.session.state['rootBuilder']['phase'], 'started')

    def test_manifest_cannot_escape_or_ignore_effective_profile(self):
        contract = self.prepare()
        self.launch()
        self.deploy(contract)
        path = self.data / 'BuildData.json'
        manifest = json.loads(path.read_text())
        original = copy.deepcopy(manifest)
        manifest['Copy']['sksevr_loader.exe']['Relative'] = '../escape.exe'
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'escapes'):
            rb.verify_started(self.session)
        path.write_text(json.dumps(original))
        (Path(self.session.state['testProfile']) / 'modlist.txt').write_text((self.profile / 'modlist.txt').read_text())
        with self.assertRaisesRegex(ValueError, 'copied profile'):
            rb.verify_started(self.session)

    def test_full_restore_recreates_original_empty_data_dirs_and_removes_only_owned_new_members(self):
        contract = self.prepare()
        self.launch()
        self.deploy(contract)
        rb.verify_started(self.session)
        (self.source / 'sksevr_loader.exe').write_bytes(b'sync-back changed source')
        (self.mods / 'disabled source/Root/disabled.ini').write_bytes(b'changed disabled source')
        root = self.overwrite / 'Root/generated'
        root.mkdir(parents=True)
        (root / 'new.log').write_bytes(b'rootbuilder-harvested log')
        (self.game / 'generated').mkdir()
        (self.game / 'generated/new.log').write_bytes(b'new root log')
        (self.game / 'Data/empty-original').rmdir()
        (self.game / 'empty-managed').rmdir()
        (self.data / 'Backup/new-owned.ini').write_bytes(b'new backup membership')
        self.ended()
        rb.restore(self.session)
        self.assertEqual(self.session.state['rootBuilder']['phase'], 'restored')
        self.assertTrue((self.game / 'Data/empty-original').is_dir())
        self.assertTrue((self.game / 'empty-managed').is_dir())
        self.assertFalse((self.overwrite / 'Root').exists())
        self.assertFalse((self.game / 'sksevr_loader.exe').exists())
        self.assertFalse((self.data / 'BuildData.json').exists())
        self.assertEqual((self.mods / 'disabled source/Root/disabled.ini').read_bytes(), b'old disabled source')
        rb.restore(self.session)  # A completed restoration is idempotent.

    def test_restore_refuses_live_unknown_mo2_and_requires_finished_marker(self):
        self.prepare()
        self.launch(live_loader=True)
        with self.assertRaisesRegex(ValueError, 'MO2-finished'):
            rb.restore(self.session)
        self.ended()
        identity = {'pid': 99, 'birth': 999, 'path': str(self.mo2 / 'ModOrganizer.exe')}
        self.identities[99] = identity
        self.process_rows = [{'pid': 99, 'name': 'ModOrganizer.exe'}]
        with self.assertRaisesRegex(ValueError, 'Unknown or active'):
            rb.restore(self.session)

    def test_links_and_cache_path_escape_are_refused_without_writes(self):
        cache = {'escape': {'Relative': '../escape.bsa', 'Hash': 'x', 'Modified': 1, 'Size': 1}}
        (self.data / 'GameData.json').write_text(json.dumps(cache))
        with self.assertRaisesRegex(ValueError, 'escapes'):
            rb.preflight(self.config, self.profile)
        for value in ('../x', 'a/../../x', 'C:/escape', 'stream:ads', '/absolute'):
            with self.assertRaises(ValueError):
                rb._relative(value)

    def test_staged_overwrite_root_is_planned_and_restored_without_changing_source_priority(self):
        external = self.root / 'external-staged.ini'
        external.write_bytes(b'explicit staged Root input')
        self.config['staged_plugins'] = [{'source': str(external), 'destination': 'Root/overlay.ini',
                                         'sha256': hashlib.sha256(external.read_bytes()).hexdigest()}]
        contract = self.prepare()
        stage = self.overwrite / 'Root/overlay.ini'
        stage.parent.mkdir()
        shutil.copy2(external, stage)
        self.launch()
        self.deploy(contract)
        rb.verify_started(self.session)
        self.ended()
        rb.restore(self.session)
        self.assertFalse((self.overwrite / 'Root').exists())
        self.assertFalse((self.game / 'overlay.ini').exists())

    def test_restore_resumes_its_durable_intent_but_refuses_later_unowned_changes(self):
        self.prepare()
        new_file = self.game / 'owned-created.log'
        new_file.write_bytes(b'recorded owned output')
        self.ended()
        original_save = self.session.save
        def pause_after_intent():
            original_save()
            if self.session.state['rootBuilder']['restoreIntent'] is not None:
                raise OSError('simulated stop after durable intent')
        self.session.save = pause_after_intent
        with self.assertRaisesRegex(OSError, 'durable intent'):
            rb.restore(self.session)
        self.session.save = original_save
        new_file.write_bytes(b'changed after the restoration plan')
        with self.assertRaisesRegex(ValueError, 'changed during restoration'):
            rb.restore(self.session)
        self.assertEqual(new_file.read_bytes(), b'changed after the restoration plan')

    def test_unregistered_restore_anchors_and_snapshot_paths_are_refused(self):
        self.prepare()
        outside = self.root / 'outside.txt'
        outside.write_bytes(b'preserve outside scope')
        self.ended()
        record = self.session.state['rootBuilder']
        record['restoreIntent'] = {'createdFiles': [{'anchor': str(self.root), 'relative': 'outside.txt',
            **rb._hash(outside)}], 'createdDirectories': [], 'removedFiles': [], 'removedDirectories': []}
        record['phase'] = 'restoring'
        with self.assertRaisesRegex(ValueError, 'escaped'):
            rb.restore(self.session)
        self.assertEqual(outside.read_bytes(), b'preserve outside scope')
        record['restoreIntent']['createdFiles'] = []
        record['snapshotPaths'].append(str(outside))
        with self.assertRaisesRegex(ValueError, 'snapshot paths escaped'):
            rb.restore(self.session)
        self.assertEqual(outside.read_bytes(), b'preserve outside scope')

    def test_hardlinks_in_mutable_root_sources_are_refused(self):
        alias = self.root / 'shared-source-alias.dll'
        os.link(self.source / 'sksevr_1_4_15.dll', alias)
        with self.assertRaisesRegex(ValueError, 'hard-linked'):
            rb.preflight(self.config, self.profile)

    def test_immutable_game_executable_link_is_checked_but_never_snapshotted_or_written(self):
        alias = self.root / 'external-game-alias.exe'
        os.link(self.game / 'SkyrimVR.exe', alias)
        contract = self.prepare()
        self.assertTrue(any(tree['immutableFiles'] for tree in contract['trees']))
        self.assertFalse(any(Path(item['path']) == self.game / 'SkyrimVR.exe' for item in self.session.state['snapshots']))
        self.ended()
        rb.restore(self.session)
        self.assertEqual(alias.read_bytes(), b'synthetic game')
        self.assertTrue(alias.samefile(self.game / 'SkyrimVR.exe'))

    def test_changed_missing_or_recreated_immutable_executable_causes_uncertainty_without_repair(self):
        alias = self.root / 'external-game-alias.exe'
        os.link(self.game / 'SkyrimVR.exe', alias)
        self.prepare()
        self.ended()
        alias.write_bytes(b'changed through an external alias')
        with self.assertRaises(rb.RootBuilderUncertainty):
            rb.restore(self.session)
        self.assertEqual(alias.read_bytes(), b'changed through an external alias')
        (self.game / 'SkyrimVR.exe').unlink()
        with self.assertRaisesRegex(rb.RootBuilderUncertainty, 'missing'):
            rb.restore(self.session)
        (self.game / 'SkyrimVR.exe').write_bytes(b'synthetic game')
        with self.assertRaisesRegex(rb.RootBuilderUncertainty, 'reappeared'):
            rb.restore(self.session)
        self.assertEqual((self.game / 'SkyrimVR.exe').read_bytes(), b'synthetic game')

    def test_immutable_hardlink_cannot_be_a_root_staged_or_extra_write_target(self):
        alias = self.root / 'external-game-alias.exe'
        os.link(self.game / 'SkyrimVR.exe', alias)
        declared = self.mods / 'disabled source/Root/SkyrimVR.exe'
        declared.write_bytes(b'possible root payload')
        with self.assertRaisesRegex(ValueError, 'reviewed immutable'):
            rb.preflight(self.config, self.profile)
        declared.unlink()
        self.config['extra_files'] = [str(self.game / 'SkyrimVR.exe')]
        with self.assertRaisesRegex(ValueError, 'reviewed immutable'):
            rb.preflight(self.config, self.profile)
        self.config['extra_files'] = []
        source = self.root / 'staged-game.exe'
        source.write_bytes(b'possible staged payload')
        self.config['staged_plugins'] = [{'source': str(source), 'destination': 'Root/SkyrimVR.exe',
                                         'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}]
        with self.assertRaisesRegex(ValueError, 'reviewed immutable'):
            rb.preflight(self.config, self.profile)


if __name__ == '__main__':
    unittest.main()
