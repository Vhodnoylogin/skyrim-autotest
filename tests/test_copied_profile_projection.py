from hashlib import sha256
import unittest

from skyrim_autotest.copied_profile import project_additive


SOURCE = {
    'modlist.txt': b'\xef\xbb\xbf# mod order\r\n*DLC: Dragonborn\r\n+Existing\r\n-Second Tool\r\n-First Tool\r\n-Unused\r\n-Folders_separator\r\n',
    'plugins.txt': b'# active plugins\r\n*Existing.esp\r\nDormant.esp\r\n',
    'loadorder.txt': b'# load order\r\nSkyrim.esm\r\nExisting.esp\r\nOrderOnly.esl',
}


def project(source=SOURCE, *, mods=('First Tool','Second Tool'), plugins=('First.esp','Second.esm'), source_sha256=None):
    pins = {name: sha256(raw).hexdigest() for name,raw in source.items()} if source_sha256 is None else source_sha256
    return project_additive(source,source_sha256=pins,mods=mods,plugins=plugins)


class AdditiveProfileProjectionTests(unittest.TestCase):
    def test_only_exact_disabled_mods_are_enabled_and_plugins_append_in_explicit_order(self):
        self.assertEqual(project(), {
            'modlist.txt': b'# mod order\n*DLC: Dragonborn\n+Existing\n+Second Tool\n+First Tool\n-Unused\n-Folders_separator\n',
            'plugins.txt': b'# active plugins\n*Existing.esp\nDormant.esp\n*First.esp\n*Second.esm\n',
            'loadorder.txt': b'# load order\nSkyrim.esm\nExisting.esp\nOrderOnly.esl\nFirst.esp\nSecond.esm\n',
        })

    def test_raw_bytes_must_match_pins_before_canonicalization(self):
        pins = {name: sha256(raw).hexdigest() for name,raw in SOURCE.items()}
        changed = {**SOURCE,'modlist.txt': SOURCE['modlist.txt'][3:]}
        self.assertEqual(project(changed),project())
        with self.assertRaisesRegex(ValueError,'SHA-256-pinned'):
            project(changed,source_sha256=pins)
        with self.assertRaisesRegex(ValueError,'SHA-256-pinned'):
            project(source_sha256={**pins,'lockedorder.txt':'0'*64})
        with self.assertRaisesRegex(ValueError,'SHA-256-pinned'):
            project({**SOURCE,'loadorder.txt':bytearray(SOURCE['loadorder.txt'])},source_sha256=pins)

    def test_managed_disabled_identity_is_case_exact_and_cannot_be_a_separator(self):
        for name in ('first tool','Existing','Missing','Dragonborn','Folders_separator'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                project(mods=[name])

    def test_case_insensitive_collisions_include_both_order_files_and_disabled_rows(self):
        for name in ('existing.ESP','dormant.esp','orderonly.ESL','skyrim.ESM'):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError,'both original order files'):
                project(plugins=[name])

    def test_refuses_duplicate_or_invalid_requests_and_source_rows(self):
        with self.assertRaisesRegex(ValueError,'unique ignoring case'):
            project(mods=('First Tool','FIRST TOOL'))
        with self.assertRaisesRegex(ValueError,'unique ignoring case'):
            project(plugins=('First.esp','FIRST.ESP'))
        with self.assertRaisesRegex(ValueError,'line breaks'):
            project(plugins=('First\u2028Injected.esp',))
        with self.assertRaisesRegex(ValueError,'Duplicate copied/source'):
            project({**SOURCE,'modlist.txt':SOURCE['modlist.txt']+b'+first tool\r\n'})
        with self.assertRaisesRegex(ValueError,'Duplicate copied/source'):
            project({**SOURCE,'plugins.txt':SOURCE['plugins.txt']+b'existing.ESP\r\n'})
        with self.assertRaisesRegex(ValueError,'unmarked plugin rows'):
            project({**SOURCE,'loadorder.txt':b'*Existing.esp\n'})

    def test_resource_only_mod_and_staged_plugin_append_are_independent(self):
        resources = project(plugins=[])
        staged = project(mods=[],plugins=['Fixture.esp'])
        self.assertIn(b'+First Tool\n',resources['modlist.txt'])
        self.assertNotIn(b'First.esp',resources['plugins.txt'])
        self.assertIn(b'-First Tool\n',staged['modlist.txt'])
        self.assertTrue(staged['plugins.txt'].endswith(b'*Fixture.esp\n'))
        with self.assertRaisesRegex(ValueError,'a mod or plugin addition'):
            project(mods=[],plugins=[])
