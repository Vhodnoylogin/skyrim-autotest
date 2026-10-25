import contextlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import config, editions, runner, cli


class EditionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        before = config.P.snapshot()
        self.addCleanup(lambda: runner.configure(before) if len(before) > 2 else setattr(config.P, 'value', before))
        self.value = config.template('se')
        for key in config.REQUIRED - {'openvr_paths'}:
            self.value[key] = str(self.root / key)
        self.value['fixture_dir'] = None
        runner.configure(self.value)
        for key in ('game', 'mo2', 'mods', 'profiles', 'overwrite', 'skse_logs'):
            Path(config.P.value[key]).mkdir(parents=True, exist_ok=True)
        for file in (config.P.mo2_exe, config.P.game / 'SkyrimSE.exe', config.P.game / 'skse64_loader.exe'):
            file.write_bytes(b'executable placeholder, never run')
        config.P.mo2_ini.write_text('[General]\nselected_profile=@ByteArray(Source)\n[customExecutables]\n'
            '1\\title=SKSE\n1\\binary=' + str(config.P.game / 'skse64_loader.exe') +
            '\n1\\workingDirectory=' + str(config.P.game) + '\n1\\arguments=\n')
        self.source = config.P.profiles / 'Source'
        self.source.mkdir()
        (self.source / 'modlist.txt').write_text('+DevBench\n')
        (self.source / 'SkyrimPrefs.ini').write_text('[Main]\nbSaveOnTravel=1\n')

    def preflight(self):
        with patch.object(runner.native, 'processes', return_value=[{'pid':4,'parent':0,'name':'System'}]):
            return runner.preflight('Source')

    def test_se_preflight_requires_neither_openvr_nor_driver_nor_vrik_higgs(self):
        info = self.preflight()
        self.assertEqual(info['gameEdition'], 'se')
        self.assertIsNone(info['runtime'])
        self.assertIsNone(info['stockOpenVR'])
        self.assertEqual(config.P.required_mods, ['DevBench'])
        self.assertNotIn('openvr_paths', config.P.value)

    def test_vr_default_and_discovery_paths_remain_separate(self):
        self.assertEqual(editions.target({})['executable'], 'SkyrimVR.exe')
        for edition in ('se', 'vr'):
            result = editions.runtime_candidates(dict(game_edition=edition, overwrite=str(self.root)))
            self.assertIn('/devbench/' + edition + '/runtime.json', result[0].as_posix())
        explicit = [str(self.root / 'pinned-runtime.json')]
        self.assertEqual(editions.runtime_candidates(dict(devbench_runtime_files=explicit)), [Path(explicit[0])])

    def test_wrong_edition_vr_configuration_and_probe_are_rejected(self):
        for value in (dict(self.value, game_edition='ae'), dict(self.value, allow_background_physical_vr=True),
                      dict(self.value, allow_steam_client_restart=True)):
            with self.assertRaises(config.ConfigurationError): config.configure(value)
        for scenario in ({'kind': 'vr-hand-probe'}, {'steps': [{'tool': 'driver'}]}, {'startMode': 'new-game'}):
            with self.assertRaises(ValueError): editions.validate_scenario(self.value, scenario, 'none', 'devbench')

    def test_se_rejects_foreign_vr_session_and_ambiguous_root_builder(self):
        with patch.object(runner.native, 'processes', return_value=[{'name': 'SkyrimVR.exe', 'pid': 1}]):
            with self.assertRaisesRegex(runner.Blocked, 'Existing'): runner.preflight('Source')
        (config.P.mo2 / 'plugins/data/RootBuilder').mkdir(parents=True)
        with self.assertRaisesRegex(runner.Blocked, 'Root Builder'): self.preflight()

    def test_stale_other_game_loader_and_unqualified_reused_or_root_paths_are_rejected(self):
        config.P.mo2_ini.write_text(config.P.mo2_ini.read_text().replace('skse64_loader.exe', 'sksevr_loader.exe'))
        with self.assertRaisesRegex(runner.Blocked, 'Registered SKSE'): self.preflight()
        for change in ({'reuse_test_profile': True}, {'root_builder_data': str(self.root / 'VR')}):
            with self.assertRaises(config.ConfigurationError): config.configure(dict(self.value, **change))

    def test_se_setup_restores_and_archives_without_vr_write_or_driver_download(self):
        source_ini = '[General]\nsLanguage=ENGLISH'
        source_custom = '[General]\nbAlwaysActive=0\n'
        (self.source / 'Skyrim.ini').write_text(source_ini)
        (self.source / 'SkyrimCustom.ini').write_text(source_custom)
        info = self.preflight()
        directory = runner.RUNS / 'se-offline'
        directory.mkdir(parents=True)
        state = dict(id='se-offline', runner=None, snapshots=[], owned=[], launchIntents={},
                     checks=[], preflight=info, configuration=config.P.snapshot(), scenario={},
                     driverBackend='none', inputBackend='devbench', restored=False)
        session = runner.Session(directory, state)
        original = config.P.mo2_ini.read_bytes()
        with patch.object(runner, 'verified_driver_build', side_effect=AssertionError('VR driver accessed')), \
             patch.object(runner.urllib.request, 'urlopen', side_effect=AssertionError('download attempted')):
            session.setup()
        paths = [p['path'] for p in state['snapshots']]
        self.assertFalse(any('openvr' in p.lower() or 'steamvr' in p.lower() for p in paths))
        self.assertTrue(Path(state['testProfile']).is_dir())
        copied = Path(state['testProfile'])
        self.assertIn('bAlwaysActive=1', (copied / 'Skyrim.ini').read_text())
        self.assertIn('sLanguage=ENGLISH', (copied / 'Skyrim.ini').read_text())
        self.assertIn('bAlwaysActive=1', (copied / 'SkyrimCustom.ini').read_text())
        self.assertEqual(len(state['seBackgroundPreparation']['files']), 2)
        with patch.object(runner.native, 'processes', return_value=[{'pid':4,'parent':0,'name':'System'}]), patch.object(session, 'collect', return_value=True):
            session.cleanup()
        self.assertTrue(state['restored'])
        self.assertEqual(config.P.mo2_ini.read_bytes(), original)
        self.assertFalse(Path(state['testProfile']).exists())
        self.assertTrue((directory / 'test-profile/modlist.txt').exists())
        self.assertEqual((self.source / 'SkyrimPrefs.ini').read_text(), '[Main]\nbSaveOnTravel=1\n')
        self.assertEqual((self.source / 'Skyrim.ini').read_text(), source_ini)
        self.assertEqual((self.source / 'SkyrimCustom.ini').read_text(), source_custom)
        self.assertIn('bAlwaysActive=1', (directory / 'test-profile/SkyrimCustom.ini').read_text())

    def test_missing_ini_key_preserves_last_value_without_terminal_newline(self):
        for newline in ('\n', '\r\n'):
            with self.subTest(newline=repr(newline)):
                original = '[General]' + newline + 'sLanguage=ENGLISH'
                actual = runner.set_ini(original, 'General', 'bAlwaysActive', '1')
                self.assertEqual(actual, original + newline + 'bAlwaysActive=1' + newline)

    def test_se_collection_does_not_require_steamvr_metadata(self):
        info = self.preflight()
        directory = runner.RUNS / 'se-collect'; directory.mkdir(parents=True)
        session = runner.Session(directory, dict(id='se-collect', configuration=config.P.snapshot(),
            preflight=info, launchIntents={}, owned=[], snapshots=[]))
        self.assertTrue(session.collect())
        manifest = runner.read_json(directory / 'evidence/manifest.json')
        self.assertFalse(any(p.get('kind') == 'steamvr-log' for p in manifest))

    def test_se_init_does_not_supply_vr_probe_examples(self):
        dest = self.root / 'init'
        self.assertEqual(cli.main(['init', '--edition', 'se', '--directory', str(dest)]), 0)
        value = json.loads((dest / 'config.json').read_text())
        self.assertEqual(value['game_edition'], 'se')
        self.assertNotIn('openvr_paths', value)
        self.assertEqual(sorted(p.name for p in dest.glob('*.json')), ['config.json', 'se-world-smoke.json'])
