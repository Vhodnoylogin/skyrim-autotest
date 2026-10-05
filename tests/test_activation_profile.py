import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from skyrim_autotest import runner, scenarios


class ActivationProfileTests(unittest.TestCase):
    def test_only_owned_copy_changes_and_original_setting_bytes_are_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            profiles=Path(folder);source=profiles/'original';source.mkdir()
            owned=profiles/'Autotest-one';owned.mkdir()
            original=b'[VRInput]\nbActivateWithBothWands=0\n[Main]\nOther=7\n'
            (source/'Skyrim.ini').write_bytes(original)
            (owned/'Skyrim.ini').write_bytes(original)
            with patch.object(runner,'P',SimpleNamespace(profiles=profiles)):
                entries=runner.prepare_activation_profile(owned,{'activationHandStartupFixture':True},source,'one')
            self.assertEqual((source/'Skyrim.ini').read_bytes(),original)
            self.assertEqual(len(entries),2)
            self.assertIn('bActivateWithBothWands=1',(owned/'Skyrim.ini').read_text())
            self.assertIn('Other=7',(owned/'Skyrim.ini').read_text())
            self.assertTrue(all(runner.sha(e['path'])==e['sha256'] for e in entries))

    def test_disabled_fixture_does_nothing_and_foreign_or_source_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            profiles=Path(folder);source=profiles/'source';source.mkdir()
            with patch.object(runner,'P',SimpleNamespace(profiles=profiles)):
                self.assertEqual(runner.prepare_activation_profile(source,{},source,'one'),[])
                for target in (source,profiles/'Autotest-another',profiles.parent/'foreign'):
                    with self.assertRaises(runner.Blocked):
                        runner.prepare_activation_profile(target,{'activationHandStartupFixture':True},source,'one')
            self.assertEqual(list(source.iterdir()),[])

    def test_startup_fixture_requires_an_explicit_self_test_fixture(self):
        value={'schemaVersion':1,'kind':'vr-mobility-probe','cell':'RealmLorkhan',
               'activationHandStartupFixture':True}
        with self.assertRaisesRegex(ValueError,'requires explicit'):
            scenarios.validate(value)
        value['activationHandFixture']=True
        scenarios.validate(value)
