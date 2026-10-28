"""Temporary-directory checks for explicit copied-profile composition reduction."""
import copy
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from skyrim_autotest import copied_profile


class Session:
    def __init__(self, root):
        self.state = {'id': 'one', 'preflight': {'profile': 'Owner'},
                      'testProfile': str(root / 'profiles' / 'Autotest-one'),
                      'testProfileName': 'Autotest-one', 'launchIntents': {}, 'owned': []}
        self.logs = []
        self.saves = 0

    def save(self):
        self.saves += 1

    def log(self, event, **data):
        self.logs.append((event, data))


class CopiedProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'profiles' / 'Owner'
        self.source.mkdir(parents=True)
        (self.source / 'modlist.txt').write_bytes(b'\xef\xbb\xbf# original order\r\n+Tools_separator\r\n+DevBench\r\n+RaceMenu\r\n-Disabled\r\n+Realm\r\n')
        (self.source / 'plugins.txt').write_bytes(b'# generated\r\n*Skyrim.esm\r\n*skee.esp\r\n*Realm.esp\r\nDisabled.esp\r\n')
        (self.source / 'loadorder.txt').write_bytes(b'# load order\nSkyrim.esm\nskee.esp\nRealm.esp\nDisabled.esp\n')
        (self.source / 'settings.ini').write_bytes(b'owner settings')
        self.target = self.source.parent / 'Autotest-one'
        shutil.copytree(self.source, self.target)
        self.session = Session(self.root)
        self.configuration = {'game_edition': 'se', 'profiles': str(self.source.parent),
                              'copied_profile_mods': {'enabledMods': ['DevBench', 'Realm'],
                              'enabledPlugins': ['Skyrim.esm', 'Update.esm', 'Realm.esp'],
                              'reason': 'Basic tooling fixture excludes unrelated body providers'}}

    def inventory(self, path):
        return {p.name: p.read_bytes() for p in path.iterdir() if p.is_file()}

    def test_exact_reduction_preserves_source_comments_order_markers_and_implicit_masters(self):
        before = self.inventory(self.source)
        result = copied_profile.apply(self.session, self.configuration)
        self.assertEqual(self.inventory(self.source), before)
        self.assertEqual((self.target / 'modlist.txt').read_bytes(), before['modlist.txt'].replace(b'+RaceMenu', b'-RaceMenu'))
        self.assertEqual((self.target / 'plugins.txt').read_bytes(), b'# generated\r\n*Skyrim.esm\r\n*Realm.esp\r\n')
        self.assertEqual((self.target / 'loadorder.txt').read_bytes(), b'# load order\nSkyrim.esm\nRealm.esp\n')
        self.assertEqual((self.target / 'settings.ini').read_bytes(), b'owner settings')
        self.assertEqual(result['enabledMods'], ['DevBench', 'Realm'])
        self.assertTrue(result['sourceProfileUnchanged'])
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(result['files']), 3)
        for row in result['files']:
            self.assertEqual(row['sourceBeforeSha256'], row['sourceAfterSha256'])
        self.assertEqual([name for name, _ in self.session.logs], ['copied-profile-mods-intent', 'copied-profile-mods-prepared'])

    def test_rejects_missing_disabled_or_case_mismatched_mod_before_any_write(self):
        before = self.inventory(self.target)
        for name in ('Absent', 'Disabled', 'devbench'):
            with self.subTest(name=name):
                configuration = copy.deepcopy(self.configuration)
                configuration['copied_profile_mods']['enabledMods'] = [name]
                with self.assertRaisesRegex(ValueError, 'already be enabled'):
                    copied_profile.apply(self.session, configuration)
                self.assertEqual(self.inventory(self.target), before)
        self.assertEqual(self.session.saves, 0)

    def test_policy_rejects_duplicate_path_separator_and_plugin_names(self):
        for field, names in [('enabledMods', ['DevBench', 'devbench']),
                             ('enabledMods', ['../DevBench']), ('enabledMods', ['Tools_separator']),
                             ('enabledMods', ['D:\\DevBench']), ('enabledMods', ['Mod\nOther']),
                             ('enabledMods', []), ('enabledPlugins', ['Realm.dll']),
                             ('enabledPlugins', ['Realm.esp', 'realm.ESP'])]:
            with self.subTest(field=field, names=names):
                policy = copy.deepcopy(self.configuration['copied_profile_mods'])
                policy[field] = names
                with self.assertRaises(ValueError):
                    copied_profile.validate(policy)
        for reason in ('', '   ', None):
            policy = dict(self.configuration['copied_profile_mods'], reason=reason)
            with self.assertRaises(ValueError): copied_profile.validate(policy)

    def test_foreign_or_source_target_never_writes(self):
        before = self.inventory(self.source)
        foreign = self.root / 'Autotest-one'
        shutil.copytree(self.source, foreign)
        for path in (self.source, foreign):
            self.session.state['testProfile'] = str(path)
            with self.assertRaises(ValueError): copied_profile.apply(self.session, self.configuration)
        self.assertEqual(self.inventory(self.source), before)
        self.assertEqual(self.inventory(foreign), before)

    def test_borrowed_reused_live_and_second_application_refuse(self):
        for update in ({'borrowedMO2': {'pid': 2}}, {'reusableProfile': {'name': 'cached'}},
                       {'game': {'pid': 3}}, {'launchIntents': {'game': {'at': 1}}},
                       {'owned': [{'role': 'game'}]}, {'done': True}):
            with self.subTest(update=update):
                session = Session(self.root)
                session.state.update(update)
                with self.assertRaisesRegex(ValueError, 'fresh owned SE'):
                    copied_profile.apply(session, self.configuration)
        for configuration in (dict(self.configuration, game_edition='vr'),
                              dict(self.configuration, reuse_test_profile=True)):
            with self.assertRaises(ValueError): copied_profile.apply(Session(self.root), configuration)
        copied_profile.apply(self.session, self.configuration)
        with self.assertRaises(ValueError): copied_profile.apply(self.session, self.configuration)

    def test_symlink_refuses_without_mutating_link_target(self):
        outside = self.root / 'outside.txt'
        outside.write_bytes((self.target / 'modlist.txt').read_bytes())
        (self.target / 'modlist.txt').unlink()
        try:
            (self.target / 'modlist.txt').symlink_to(outside)
        except OSError as error:
            self.skipTest('OS does not permit symlink creation: ' + str(error))
        original = outside.read_bytes()
        with self.assertRaises((ValueError, RuntimeError)):
            copied_profile.apply(self.session, self.configuration)
        self.assertEqual(outside.read_bytes(), original)

    def test_atomic_replacement_does_not_modify_hardlinked_source(self):
        original = (self.source / 'modlist.txt').read_bytes()
        (self.target / 'modlist.txt').unlink()
        os.link(self.source / 'modlist.txt', self.target / 'modlist.txt')
        copied_profile.apply(self.session, self.configuration)
        self.assertEqual((self.source / 'modlist.txt').read_bytes(), original)
        self.assertIn(b'-RaceMenu', (self.target / 'modlist.txt').read_bytes())

    def test_changed_copy_order_and_duplicate_rows_refuse_before_any_write(self):
        for content in (b'+DevBench\n+Realm\n+RaceMenu\n-Disabled\n', b'+DevBench\n+devbench\n+Realm\n'):
            (self.target / 'modlist.txt').write_bytes(content)
            before = self.inventory(self.target)
            with self.assertRaises(ValueError): copied_profile.apply(self.session, self.configuration)
            self.assertEqual(self.inventory(self.target), before)

    def test_unconfigured_policy_is_noop(self):
        self.assertIsNone(copied_profile.apply(self.session, {}))
        self.assertEqual(self.session.saves, 0)

    def test_standard_unmanaged_dlc_and_creation_club_rows_are_preserved_and_reported(self):
        unmanaged=b'*Creation Club: _ResourcePack\r\n*Creation Club: ccBGSSSE001-Fish\r\n*DLC: Dawnguard\r\n*Unmanaged: loose_assets\r\n'
        for folder in (self.source,self.target):
            p=folder/'modlist.txt'
            p.write_bytes(p.read_bytes()+unmanaged)
        before=self.inventory(self.source)
        result=copied_profile.apply(self.session,self.configuration)
        self.assertEqual(self.inventory(self.source),before)
        self.assertTrue((self.target/'modlist.txt').read_bytes().endswith(unmanaged))
        self.assertEqual(result['enabledMods'],['DevBench','Realm'])
        self.assertEqual(result['unmanagedEntries'],['Creation Club: _ResourcePack','Creation Club: ccBGSSSE001-Fish','DLC: Dawnguard','Unmanaged: loose_assets'])

    def test_unknown_or_pathlike_unmanaged_rows_reject_before_writes(self):
        original=(self.source/'modlist.txt').read_bytes()
        for row in (b'*RaceMenu\n',b'*DLC: ../outside\n',b'*Creation Club: \n'):
            for folder in (self.source,self.target):(folder/'modlist.txt').write_bytes(original+row)
            before=self.inventory(self.target)
            with self.assertRaises(ValueError):copied_profile.apply(self.session,self.configuration)
            self.assertEqual(self.inventory(self.target),before)


if __name__ == '__main__':
    unittest.main()
