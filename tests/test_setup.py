"""Offline setup contracts; fixtures never launch MO2, Skyrim or a microphone."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skyrim_autotest import config, setup


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def pe():
    value = bytearray(128)
    value[:2] = b'MZ'
    struct.pack_into('<I', value, 60, 64)
    value[64:68] = b'PE\0\0'
    struct.pack_into('<H', value, 68, 0x8664)
    struct.pack_into('<H', value, 88, 0x20b)
    return bytes(value)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.old = config.P.snapshot()
        self.spec_path = self.root / 'setup-spec.json'
        self.secret = 'PRIVATE_TOKEN_MUST_NEVER_APPEAR'

    def tearDown(self):
        config.P.value = self.old
        self.temp.cleanup()

    def make(self, edition='se'):
        directories = {key: self.root / key for key in ('runtime', 'mo2', 'game', 'mods', 'profiles', 'overwrite', 'skse_logs')}
        for key, path in directories.items():
            if key != 'runtime':
                path.mkdir(exist_ok=True)
        paths = {key: str(path) for key, path in directories.items()}
        paths.update(mo2_exe=str(directories['mo2'] / 'ModOrganizer.exe'),
                     mo2_ini=str(directories['mo2'] / 'ModOrganizer.ini'),
                     bridge_token=str(self.root / 'private-token.txt'))
        Path(paths['bridge_token']).write_text(self.secret, encoding='utf-8')
        (directories['mods'] / 'DevBench').mkdir(exist_ok=True)
        selected = setup.target({'game_edition': edition})
        game = directories['game'] / selected['executable']
        loader = directories['game'] / selected['loader']
        deps = []
        for name, path in [('game', game), ('skse', loader), ('mo2', Path(paths['mo2_exe'])),
                           ('devbench', self.root / 'devbench.dll'), ('mo2-api-bridge', self.root / 'bridge.py'),
                           ('address-library', self.root / 'versionlib.bin')]:
            path.write_bytes(pe() if name in ('game', 'skse', 'mo2', 'devbench') else b'pinned dependency')
            deps.append({'id': name, 'path': str(path), 'sha256': digest(path),
                         'source': 'https://example.org/' + name})
        Path(paths['mo2_ini']).write_text('[customExecutables]\n1\\title=SKSE\n1\\binary=' + str(loader) +
            '\n1\\workingDirectory=' + str(directories['game']) + '\n1\\arguments=\n[Settings]\nmod_directory=' + paths['mods'] + '\n', encoding='utf-8')
        provider_config = self.root / 'actual-devbench-config.json'
        provider_config.write_text(json.dumps({'alwaysActive': False, 'port': 8080, 'preserve': {'nested': True}}), encoding='utf-8')
        caps = self.root / 'capabilities.json'
        caps.write_text(json.dumps({'schemaVersion': 1, 'game_edition': edition,
            'providerSha256': next(item['sha256'] for item in deps if item['id'] == 'devbench'),
            'capabilities': ['native-menu-flags', 'devbench-startup-ui/1']}), encoding='utf-8')
        def pin(path):
            return {'path': str(path), 'sha256': digest(path), 'source': 'https://example.org/build'}
        if edition == 'vr':
            vr_runtime = self.root / 'steamvr'
            vr_runtime.mkdir(exist_ok=True)
            vr_config = self.root / 'steamvr-config'
            vr_config.mkdir(exist_ok=True)
            openvr = self.root / 'openvrpaths.vrpath'
            openvr.write_text(json.dumps({'runtime': [str(vr_runtime)], 'config': [str(vr_config)]}), encoding='utf-8')
            paths['openvr_paths'] = str(openvr)
            for name in ('steamvr', 'physical-driver', 'openvr-header'):
                path = self.root / (name + '.bin')
                path.write_bytes(b'#pragma once\n' if name == 'openvr-header' else pe())
                deps.append(dict(pin(path), id=name, kind='header' if name == 'openvr-header' else 'pe'))
        self.spec = {'schemaVersion': 1, 'game_edition': edition, 'config_directory': str(self.root / 'prepared'),
            'paths': paths, 'bridge_port': 8951, 'required_mods': ['DevBench'], 'dependencies': deps,
            'provider': {'artifact': 'devbench', 'configuration': pin(provider_config), 'capability_manifest': pin(caps)},
            'destination_allowlist': [setup.PROVIDER_DESTINATION]}
        self.save()
        return self.spec

    def save(self):
        self.spec_path.write_text(json.dumps(self.spec), encoding='utf-8')

    def output(self):
        return Path(self.spec['config_directory'])

    def test_se_fills_actual_paths_and_preserves_full_provider_settings(self):
        self.make()
        result = setup.install(self.spec_path)
        self.assertTrue(result['preparationReady'], result)
        self.assertFalse(result['liveQualified'])
        value = config.load(self.output() / 'config.json')
        self.assertEqual(value['game_edition'], 'se')
        self.assertEqual(value['bridge_port'], 8951)
        self.assertEqual(value['skse_logs'], self.spec['paths']['skse_logs'])
        self.assertNotIn('openvr_paths', value)
        self.assertNotIn('REPLACE', (self.output() / 'config.json').read_text())
        prepared = json.loads((self.output() / 'prepared-devbench-config.json').read_text())
        self.assertEqual(prepared, {'alwaysActive': True, 'port': 8080, 'preserve': {'nested': True}})
        self.assertFalse(json.loads(Path(self.spec['provider']['configuration']['path']).read_text())['alwaysActive'])
        self.assertEqual(value['staged_plugins'][-1]['destination'], setup.PROVIDER_DESTINATION)
        manifest = json.loads((self.output() / 'setup-manifest.json').read_text())
        self.assertEqual(manifest['source']['version'], setup.__version__)
        self.assertEqual(manifest['specification']['sha256'], digest(self.spec_path))
        self.assertFalse(Path(self.spec['paths']['runtime']).exists())

    def test_vr_uses_correct_executable_and_explicit_openvr(self):
        self.make('vr')
        result = setup.install(self.spec_path)
        self.assertTrue(result['preparationReady'], result)
        self.assertEqual(config.load(self.output() / 'config.json')['openvr_paths'], self.spec['paths']['openvr_paths'])
        (Path(self.spec['paths']['game']) / 'SkyrimVR.exe').unlink()
        result = setup.doctor(self.spec_path)
        self.assertFalse(result['preparationReady'])
        self.assertEqual(next(row for row in result['checks'] if row['id'] == 'executable.game')['status'], 'missing-or-invalid')

    def test_explicit_vr_root_builder_checks_pinned_source_before_deployment(self):
        from skyrim_autotest import root_builder
        self.make('vr')
        loader = Path(self.spec['paths']['game']) / 'sksevr_loader.exe'
        loader.unlink()
        source = Path(self.spec['paths']['mods']) / 'SKSEVR pinned' / 'Root'
        source.mkdir(parents=True)
        bundle = {}
        for name in ('sksevr_loader.exe', 'sksevr_1_4_15.dll', 'sksevr_steam_loader.dll'):
            (source / name).write_bytes(pe())
            bundle[name] = digest(source / name)
        game_key = self.spec['paths']['game'].replace(' ', '_').replace('.', '_')
        for character in '<>:|*\\/?"':
            game_key = game_key.replace(character, '')
        data = Path(self.spec['paths']['mo2']) / 'plugins/data/RootBuilder' / game_key / '1_4_15_0'
        (data / 'Backup').mkdir(parents=True)
        (data / 'GameData.json').write_text('{}')
        self.spec['paths']['root_builder_data'] = str(data)
        self.spec['configuration'] = {'root_builder': {'mode': 'copy-5.1.1',
            'pluginTreeSha256': root_builder.SUPPORTED_PLUGIN_SHA256,
            'loaderMod': 'SKSEVR pinned', 'bundleSha256': bundle}}
        entry = next(item for item in self.spec['dependencies'] if item['id'] == 'skse')
        entry.update(path=str(source / 'sksevr_loader.exe'), sha256=bundle['sksevr_loader.exe'])
        self.save()
        with patch.object(root_builder, 'plugin_fingerprint', return_value=root_builder.SUPPORTED_PLUGIN_SHA256):
            result = setup.install(self.spec_path)
            self.assertTrue(result['preparationReady'], result)
            self.assertTrue(result['rootBuilder']['sourceReady'])
            self.assertEqual(result['rootBuilder']['deployment'], 'pending-owned-autobuild')
            self.assertFalse(result['rootBuilder']['sourceProfileChecked'])
            self.assertFalse(loader.exists())
            (source / 'sksevr_steam_loader.dll').write_bytes(b'changed source')
            self.assertFalse(setup.doctor(self.spec_path)['preparationReady'])
        # The same missing game-root loader is refused without explicit policy.
        del self.spec['configuration']
        del self.spec['paths']['root_builder_data']
        self.spec['config_directory'] = str(self.root / 'ordinary-vr')
        self.save()
        rows = {row['id']: row for row in setup.doctor(self.spec_path)['checks']}
        self.assertEqual(rows['executable.skse']['status'], 'missing-or-invalid')
        self.assertEqual(rows['dependency.skse']['status'], 'missing-or-invalid')

    def test_missing_dependencies_are_actionable_and_config_still_prepared(self):
        self.make()
        self.spec['dependencies'] = [item for item in self.spec['dependencies'] if item['id'] != 'address-library']
        Path(next(item['path'] for item in self.spec['dependencies'] if item['id'] == 'mo2-api-bridge')).unlink()
        self.save()
        result = setup.install(self.spec_path)
        self.assertFalse(result['preparationReady'])
        self.assertTrue((self.output() / 'config.json').is_file())
        rows = {row['id']: row for row in result['checks']}
        self.assertIn('official HTTPS', rows['dependency.address-library']['action'])
        self.assertIn('No download', rows['dependency.mo2-api-bridge']['action'])

    def test_repeat_verifies_outputs_and_actual_dependencies(self):
        self.make()
        setup.install(self.spec_path)
        before = {p.name: p.read_bytes() for p in self.output().iterdir()}
        again = setup.install(self.spec_path)
        self.assertTrue(again['idempotent'])
        self.assertTrue(again['preparationReady'], again)
        path = Path(next(item['path'] for item in self.spec['dependencies'] if item['id'] == 'devbench'))
        path.write_bytes(b'changed binary')
        again = setup.install(self.spec_path)
        self.assertFalse(again['preparationReady'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.output().iterdir()})

    def test_changed_inputs_and_outputs_are_refused_without_overwrite(self):
        self.make()
        setup.install(self.spec_path)
        original = (self.output() / 'config.json').read_bytes()
        self.spec['bridge_port'] = 8952
        self.save()
        with self.assertRaisesRegex(setup.SetupError, 'inputs/source changed'):
            setup.install(self.spec_path)
        self.assertEqual(original, (self.output() / 'config.json').read_bytes())
        self.spec['bridge_port'] = 8951
        self.save()
        (self.output() / 'config.json').write_text('{}')
        with self.assertRaisesRegex(setup.SetupError, 'output changed'):
            setup.doctor(self.spec_path)
        self.assertEqual((self.output() / 'config.json').read_text(), '{}')

    def test_partial_write_failure_rolls_back_and_releases_owned_lock(self):
        self.make()
        with patch.object(setup.os, 'fsync', side_effect=OSError('injected disk failure')):
            with self.assertRaisesRegex(OSError, 'injected'):
                setup.install(self.spec_path)
        self.assertFalse(self.output().exists())
        self.assertFalse(list(self.root.glob('.prepared.setup*')))
        self.assertTrue(setup.install(self.spec_path)['preparationReady'])

    def test_existing_config_and_foreign_lock_are_preserved(self):
        self.make()
        self.output().mkdir()
        existing = self.output() / 'config.json'
        existing.write_text('owner config')
        with self.assertRaisesRegex(setup.SetupError, 'existing files were preserved'):
            setup.install(self.spec_path)
        self.assertEqual(existing.read_text(), 'owner config')
        existing.unlink()
        self.output().rmdir()
        lock = self.root / '.prepared.setup.lock'
        lock.write_text('foreign owner')
        with self.assertRaises(FileExistsError):
            setup.install(self.spec_path)
        self.assertEqual(lock.read_text(), 'foreign owner')

    def test_runtime_and_output_reject_git_live_and_relative_paths(self):
        self.make()
        original = json.loads(json.dumps(self.spec))
        for key, value in [('runtime', str(Path(self.spec['paths']['game']) / 'runs')), ('runtime', 'relative/runs')]:
            self.spec = json.loads(json.dumps(original))
            self.spec['paths'][key] = value
            self.save()
            with self.assertRaises(setup.SetupError):
                setup.install(self.spec_path)
        self.spec = json.loads(json.dumps(original))
        self.spec['config_directory'] = str(Path(self.spec['paths']['mo2']) / 'config')
        self.save()
        with self.assertRaises(setup.SetupError):
            setup.install(self.spec_path)
        self.spec = original
        (self.root / '.git').mkdir()
        self.save()
        with self.assertRaisesRegex(setup.SetupError, 'Git'):
            setup.install(self.spec_path)

    def test_symlink_input_and_output_refused(self):
        self.make()
        link = self.root / 'linked'
        try:
            link.symlink_to(self.root / 'game', target_is_directory=True)
        except OSError:
            self.skipTest('Creating symbolic links is not available to this account')
        self.spec['paths']['game'] = str(link)
        self.save()
        with self.assertRaisesRegex(setup.SetupError, 'Symlink'):
            setup.install(self.spec_path)
        self.spec['paths']['game'] = str(self.root / 'game')
        self.spec['config_directory'] = str(link / 'new')
        self.save()
        with self.assertRaisesRegex(setup.SetupError, 'Symlink'):
            setup.install(self.spec_path)

    def test_windows_reparse_point_is_refused_without_link_privileges(self):
        self.make()
        game = Path(self.spec['paths']['game'])
        original = Path.lstat
        def reparse(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == game:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', reparse):
            with self.assertRaisesRegex(setup.SetupError, 'reparse-point'):
                setup.install(self.spec_path)
        self.assertFalse(self.output().exists())

    def test_existing_readonly_artifacts_inside_git_can_be_pinned_without_writes(self):
        self.make()
        checkout = self.root / 'downloaded-tool-checkout'
        checkout.mkdir()
        (checkout / '.git').write_text('gitdir: somewhere')
        artifact = checkout / 'devbench.dll'
        artifact.write_bytes(pe())
        entry = next(item for item in self.spec['dependencies'] if item['id'] == 'devbench')
        entry.update(path=str(artifact), sha256=digest(artifact))
        self.save()
        before = artifact.read_bytes()
        self.assertTrue(setup.install(self.spec_path)['preparationReady'])
        self.assertEqual(artifact.read_bytes(), before)
        self.assertFalse(self.output().is_relative_to(checkout))

    def test_staged_plugins_need_exact_allowlist_and_safe_destination(self):
        self.make()
        source = self.root / 'owned-plugin.dll'
        source.write_bytes(pe())
        for destination in ('../escape.dll', 'SKSE/Plugins/not-approved.dll', 'C:/escape.dll'):
            self.spec['staged_plugins'] = [{'source': str(source), 'destination': destination, 'sha256': digest(source)}]
            self.save()
            with self.assertRaises(setup.SetupError):
                setup.install(self.spec_path)
        self.spec['destination_allowlist'].append('SKSE/Plugins/owned.dll')
        self.spec['staged_plugins'][0]['destination'] = 'SKSE/Plugins/owned.dll'
        self.save()
        self.assertTrue(setup.install(self.spec_path)['preparationReady'])
        self.assertFalse((Path(self.spec['paths']['overwrite']) / 'SKSE/Plugins/owned.dll').exists())

    def test_native_startup_requires_exact_capability_and_provider_hash(self):
        self.make()
        self.spec['configuration'] = {'se_new_game_ui': True}
        caps = Path(self.spec['provider']['capability_manifest']['path'])
        value = json.loads(caps.read_text())
        value['capabilities'] = ['native-menu-flags']
        caps.write_text(json.dumps(value))
        self.spec['provider']['capability_manifest']['sha256'] = digest(caps)
        self.save()
        result = setup.doctor(self.spec_path)
        row = next(row for row in result['checks'] if row['id'] == 'provider.capabilities')
        self.assertIn('devbench-startup-ui/1', row['detail'])
        value['capabilities'].append('devbench-startup-ui/1')
        value['providerSha256'] = '0' * 64
        caps.write_text(json.dumps(value))
        self.spec['provider']['capability_manifest']['sha256'] = digest(caps)
        self.save()
        self.assertFalse(setup.doctor(self.spec_path)['preparationReady'])

    def test_pe_header_and_sdk_header_are_validated_after_hash(self):
        self.make('vr')
        for name in ('game', 'openvr-header'):
            entry = next(item for item in self.spec['dependencies'] if item['id'] == name)
            Path(entry['path']).write_bytes(b'not the declared executable or header')
            entry['sha256'] = digest(entry['path'])
        self.save()
        rows = {row['id']: row for row in setup.doctor(self.spec_path)['checks']}
        self.assertIn('PE', rows['dependency.game']['detail'])
        self.assertIn('SDK header', rows['dependency.openvr-header']['detail'])

    def test_secret_contents_never_read_or_printed_and_bus_is_reference_only(self):
        self.make()
        bus_token = self.root / 'bus-token.txt'
        bus_token.write_text(self.secret)
        self.spec['command_bus'] = {'api_url': 'http://127.0.0.1:8777/v1', 'token_path': str(bus_token)}
        self.save()
        real_read = Path.read_bytes
        def guarded_read(path):
            self.assertNotIn(path, (Path(self.spec['paths']['bridge_token']), bus_token))
            return real_read(path)
        stream = io.StringIO()
        with patch.object(Path, 'read_bytes', guarded_read), contextlib.redirect_stdout(stream):
            self.assertEqual(setup.main(['install', '--spec', str(self.spec_path)]), 0)
            self.assertEqual(setup.main(['doctor', '--spec', str(self.spec_path)]), 0)
        self.assertNotIn(self.secret, stream.getvalue())
        for path in self.output().iterdir():
            self.assertNotIn(self.secret, path.read_text())
        reference = json.loads((self.output() / 'command-bus.json').read_text())
        self.assertEqual(reference['adapter'], 'external')
        self.assertNotIn('microphone', reference.keys())
        from skyrim_autotest.command_bus import load_config
        channel = load_config(self.output() / 'command-channel.json')
        self.assertEqual(channel['database'], str(Path(self.spec['paths']['runtime']) / 'command-channel/commands.sqlite3'))
        self.assertEqual(channel['tokenFile'], str(bus_token))
        self.assertEqual((channel['host'], channel['port']), ('127.0.0.1', 8777))
        self.assertFalse(Path(channel['database']).exists())
        self.assertFalse(Path(self.spec['paths']['runtime']).exists())
        before = (self.output() / 'command-channel.json').read_bytes()
        self.assertTrue(setup.install(self.spec_path)['idempotent'])
        self.assertEqual(before, (self.output() / 'command-channel.json').read_bytes())

    def test_command_channel_rejects_remote_ambiguous_or_secret_target_alias(self):
        self.make()
        for url in ('https://remote.example.org/v1', 'http://localhost:8777/v1', 'http://127.0.0.1/v1'):
            self.spec['command_bus'] = {'api_url': url, 'token_path': str(self.root / 'channel-token.txt')}
            self.save()
            with self.assertRaisesRegex(setup.SetupError, 'explicit port'):
                setup.install(self.spec_path)
        self.spec['command_bus'] = {'api_url': 'http://127.0.0.1:8777/v1',
            'token_path': str(Path(self.spec['paths']['runtime']) / 'command-channel/commands.sqlite3')}
        self.save()
        with self.assertRaisesRegex(setup.SetupError, 'separate'):
            setup.install(self.spec_path)

    def test_missing_provider_source_fails_before_publishing_any_config(self):
        self.make()
        Path(self.spec['provider']['configuration']['path']).unlink()
        with self.assertRaisesRegex(setup.SetupError, 'Missing pinned'):
            setup.install(self.spec_path)
        self.assertFalse(self.output().exists())
        self.assertFalse(list(self.root.glob('.prepared.setup*')))

    def test_cold_owned_bridge_token_is_deferred_only_with_verified_installed_plugin(self):
        self.make('vr')
        token = Path(self.spec['paths']['bridge_token'])
        token.unlink()
        installed = Path(self.spec['paths']['mo2']) / 'plugins/mo2aibridge/runtime.py'
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b'pinned installed bridge lifecycle')
        entry = next(item for item in self.spec['dependencies'] if item['id'] == 'mo2-api-bridge')
        entry.update(path=str(installed), sha256=digest(installed))
        self.save()
        result = setup.install(self.spec_path)
        self.assertTrue(result['preparationReady'], result)
        token_check = next(row for row in result['checks'] if row['id'] == 'file.bridge_token')
        self.assertEqual(token_check['status'], 'deferred-to-owned-mo2-start')
        self.assertFalse(token.exists())
        self.assertFalse(result['liveQualified'])
        self.spec['configuration'] = {'reuse_test_profile': True}
        self.spec['config_directory'] = str(self.root / 'borrowed-config')
        self.save()
        result = setup.doctor(self.spec_path)
        self.assertFalse(result['preparationReady'])
        self.assertEqual(next(row for row in result['checks'] if row['id'] == 'file.bridge_token')['status'], 'missing-or-invalid')
        del self.spec['configuration']
        installed.write_bytes(b'changed unverified plugin')
        self.save()
        result = setup.doctor(self.spec_path)
        self.assertFalse(result['preparationReady'])
        self.assertEqual(next(row for row in result['checks'] if row['id'] == 'file.bridge_token')['status'], 'missing-or-invalid')

    def test_wrong_registered_edition_and_required_mod_are_not_preparation_ready(self):
        self.make()
        ini = Path(self.spec['paths']['mo2_ini'])
        ini.write_text(ini.read_text().replace('skse64_loader.exe', 'sksevr_loader.exe'))
        (Path(self.spec['paths']['mods']) / 'DevBench').rmdir()
        rows = {row['id']: row for row in setup.doctor(self.spec_path)['checks']}
        self.assertEqual(rows['mo2.instance']['status'], 'missing-or-invalid')
        self.assertEqual(rows['required-mod.DevBench']['status'], 'missing-or-invalid')


if __name__ == '__main__':
    unittest.main()
