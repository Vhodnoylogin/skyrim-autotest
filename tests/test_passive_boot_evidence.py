import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from skyrim_autotest import editions, native, root_builder, root_builder_passive as passive


class PassiveBootEvidenceTests(unittest.TestCase):
    def test_modlist_changes_remain_blocking_and_keep_both_exact_inputs(self):
        before = b'# MO2 inventory\r\n+Required\r\n'
        changed = b'# MO2 inventory\r\n-New disabled catalog row\r\n+Required\r\n'
        for after in (before, changed):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                profile = root / 'profile'
                profile.mkdir()
                modlist = profile / 'modlist.txt'
                modlist.write_bytes(before)
                ini = root / 'ModOrganizer.ini'
                ini.write_bytes(b'[Plugins]\r\n')
                contract = {'loaderContract': {}, 'paths': {'mo2_exe': str(root / 'ModOrganizer.exe')}}
                record = {'runId': 'example', 'phase': 'prepared', 'contract': contract,
                          'contractSha256': root_builder._digest(contract)}
                state = {'id': 'example', 'rootBuilderPassive': record, 'testProfile': str(profile),
                         'configuration': {'mo2_ini': str(ini), 'profiles': str(root)}, 'owned': []}
                session = SimpleNamespace(dir=root, state=state, save=Mock())
                bridge = {'mo2Pid': 12, 'serverBootId': 'boot', 'instanceId': 'instance', 'profilesPath': str(root)}
                with (patch.object(passive, 'cold_idle'), patch.object(passive, '_unchanged'),
                      patch.object(passive, '_no_root'), patch.object(passive, '_off', return_value={}),
                      patch.object(editions, 'validate_mo2_loader', return_value={}),
                      patch.object(native, 'identity') as identity):
                    passive.before_launch(session)
                    process = {'pid': 12, 'path': contract['paths']['mo2_exe'],
                               'birth': record['coldStartProof']['minimumProcessBirth'] + 1}
                    identity.return_value = process
                    state['owned'] = [{'role': 'mo2', 'identity': process}]
                    modlist.write_bytes(after)
                    if after == before:
                        passive.verify_boot(session, bridge)
                        self.assertEqual(record['phase'], 'verified-before-game')
                    else:
                        with self.assertRaisesRegex(ValueError, 'compare retained modlist evidence'):
                            passive.verify_boot(session, bridge)
                        self.assertEqual(record['phase'], 'cold-start-proof')
                for stage, expected in (('cold-staged', before), ('post-boot', after)):
                    evidence = record['modlistEvidence'][stage]
                    self.assertEqual(Path(evidence['path']).read_bytes(), expected)
                    self.assertEqual(root_builder._hash(evidence['path'])['sha256'], evidence['sha256'])
