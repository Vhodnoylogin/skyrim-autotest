"""Synthetic passive lifecycle, no installed MO2/game/settings are touched."""
import copy
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skyrim_autotest import root_builder as rb, root_builder_passive as subject, native, config


class PassiveRootBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mo2, self.game, self.mods = [self.root/name for name in ('mo2', 'game', 'mods')]
        self.profile = self.root/'profiles/Source'
        self.overwrite = self.root/'overwrite'
        self.plugin = self.mo2/'plugins/rootbuilder'
        self.data = self.mo2/'plugins/data/RootBuilder'
        self.ini = self.mo2/'ModOrganizer.ini'
        for directory in (self.mo2, self.game/'Data', self.mods, self.profile, self.overwrite, self.plugin, self.data):
            directory.mkdir(parents=True, exist_ok=True)
        (self.plugin/'source.py').write_text('# synthetic package, never executed\n')
        package = rb.plugin_fingerprint(self.plugin)
        p = patch.object(rb, 'SUPPORTED_PLUGIN_SHA256', package);p.start();self.addCleanup(p.stop)
        (self.mo2/'portable.txt').write_bytes(b'')
        (self.mo2/'ModOrganizer.exe').write_bytes(b'synthetic manager')
        (self.game/'SkyrimSE.exe').write_bytes(b'synthetic game')
        loader = self.game/'skse64_loader.exe';loader.write_bytes(b'synthetic physical loader')
        (self.data/'VersionManifest.json').write_bytes(b'{"Version":"5.1.1"}')
        (self.data/'OtherGame/Backup/CreationKit').mkdir(parents=True)
        (self.data/'OtherGame/Backup/CreationKit/tool.dll').write_bytes(b'untouched backup')
        (self.profile/'modlist.txt').write_text('+Ordinary Mod\n-Disabled Root\n')
        (self.mods/'Disabled Root/Root').mkdir(parents=True)
        self.ini.write_text('[General]\nselected_profile=@ByteArray(Source)\n[Plugins]\nRootBuilder\\migrated=true\nRootBuilder\\copyfiles=**\nRootBuilder\\linkfiles=\nRootBuilder\\usvfsfiles=\nRootBuilder\\redirect=true\n')
        self.original = self.ini.read_bytes()
        self.value = {'game_edition':'se','mo2':str(self.mo2),'mo2_ini':str(self.ini),'mo2_exe':str(self.mo2/'ModOrganizer.exe'),
                      'mods':str(self.mods),'game':str(self.game),'profiles':str(self.profile.parent),'overwrite':str(self.overwrite),'extra_files':[],
                      'root_builder_passive':{'mode':subject.MODE,'pluginTreeSha256':package,'dataTreeSha256':rb._digest(rb._tree(self.data)),
                                              'mo2ExeSha256':rb._hash(self.mo2/'ModOrganizer.exe')['sha256'],
                                              'loaderSha256':rb._hash(loader)['sha256'],'settingsProof':subject.PROOF,'mutableGameFiles':[]}}
        self.processes, self.identities = [{'pid':4,'name':'System'}], {}
        for p in (patch.object(native,'processes',lambda:copy.deepcopy(self.processes)),patch.object(native,'identity',lambda pid:copy.deepcopy(self.identities.get(pid)))):
            p.start();self.addCleanup(p.stop)
        run = self.root/'run';run.mkdir()
        self.session = SimpleNamespace(dir=run,state={'id':'run','configuration':copy.deepcopy(self.value),'snapshots':[],'owned':[],
                                                     'testProfile':str(self.profile)},durable=[],writes=[])
        self.session.save = lambda:self.session.durable.append(copy.deepcopy(self.session.state))
        def snapshot(path):
            path = Path(path).resolve()
            if any(row['path']==str(path)for row in self.session.state['snapshots']):return
            row={'path':str(path),'exists':path.is_file()}
            if path.is_file():
                backup=run/str(len(self.session.state['snapshots']));shutil.copy2(path,backup)
                row.update(backup=str(backup),sha256=rb._hash(backup)['sha256'])
            self.session.state['snapshots'].append(row);self.session.save()
        def write(path,text):
            snapshot(path)
            self.session.writes.append(str(path));Path(path).write_text(text)
        self.session.snapshot, self.session.write = snapshot, write

    def plan(self):return subject.preflight(self.value,self.profile)

    def prepare(self):
        contract=self.plan();self.session.snapshot(self.ini);subject.prepare(self.session,contract);return contract

    def restore_ordinary(self):
        protected=set(self.session.state['rootBuilderPassive']['snapshotPaths'])
        for row in self.session.state['snapshots']:
            if row['path'] in protected:continue
            path=Path(row['path'])
            if row['exists']:shutil.copy2(row['backup'],path)
            elif path.exists():path.unlink()

    def test_cold_stage_after_snapshot_then_restore_original_bytes(self):
        contract=self.prepare()
        subject._off(self.ini)
        self.assertNotEqual(self.ini.read_bytes(),self.original)
        self.assertEqual(self.session.writes,[str(self.ini)])
        self.assertEqual(rb._tree(self.data),contract['data'])
        self.restore_ordinary();subject.restore(self.session)
        self.assertEqual(self.ini.read_bytes(),self.original)
        self.assertEqual(self.session.state['rootBuilderPassive']['phase'],'restored-unchanged')

    def test_missing_snapshot_and_save_failure_never_stage_settings(self):
        contract=self.plan()
        with self.assertRaisesRegex(ValueError,'snapshot'):subject.prepare(self.session,contract)
        self.assertEqual(self.ini.read_bytes(),self.original)
        self.session.snapshot(self.ini)
        self.session.save=lambda:(_ for _ in ()).throw(OSError('lost durable storage'))
        with self.assertRaises(OSError):subject.prepare(self.session,contract)
        self.assertEqual(self.ini.read_bytes(),self.original)
        self.assertEqual(self.session.writes,[])

    def test_enabled_root_overwrite_root_and_staged_root_refuse(self):
        (self.profile/'modlist.txt').write_text('+Disabled Root\n')
        with self.assertRaisesRegex(ValueError,'enabled Root'):self.plan()
        (self.profile/'modlist.txt').write_text('-Disabled Root\n')
        (self.overwrite/'Root').mkdir();(self.overwrite/'Root/a.dll').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError,'overwrite Root'):self.plan()
        (self.overwrite/'Root/a.dll').unlink()
        self.value['staged_plugins']=[{'destination':'Root/a.dll'}]
        with self.assertRaisesRegex(ValueError,'staged Root'):self.plan()

    def test_no_mo2_game_vr_takeover_and_no_nonportable_proof(self):
        for name in ('ModOrganizer.exe','SkyrimSE.exe','skse64_loader.exe','vrcompositor.exe'):
            self.processes=[{'name':name,'pid':1}]
            with self.assertRaisesRegex(ValueError,'existing'):self.plan()
        self.processes=[];(self.mo2/'portable.txt').unlink()
        with self.assertRaisesRegex(ValueError,'portable'):self.plan()

    def test_empty_native_process_inventory_does_not_prove_cold_absence(self):
        self.processes=[]
        with self.assertRaisesRegex(ValueError,'inventory unavailable'):self.plan()

    def test_no_active_build_or_unmigrated_startup(self):
        (self.data/'OtherGame/BuildData.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'BuildData'):self.plan()
        (self.data/'OtherGame/BuildData.json').unlink()
        self.ini.write_bytes(self.original.replace(b'migrated=true',b'migrated=false'))
        with self.assertRaisesRegex(ValueError,'migrated'):self.plan()

    def test_loader_package_and_data_pins_cannot_drift(self):
        for key in ('pluginTreeSha256','dataTreeSha256','loaderSha256','mo2ExeSha256'):
            previous=self.value['root_builder_passive'][key];self.value['root_builder_passive'][key]='0'*64
            with self.assertRaises(ValueError):self.plan()
            self.value['root_builder_passive'][key]=previous

    def test_explicit_mutable_root_log_uses_ordinary_snapshot_and_static_root_drift_refuses(self):
        log=self.game/'Debug.log';log.write_bytes(b'old log')
        self.value['root_builder_passive']['mutableGameFiles']=['Debug.log']
        with self.assertRaisesRegex(ValueError,'extra_files'):self.plan()
        self.value['extra_files']=[str(log)];self.session.state['configuration']=copy.deepcopy(self.value)
        self.session.snapshot(log);self.prepare();log.write_bytes(b'ordinary game output')
        self.restore_ordinary();subject.restore(self.session);self.assertEqual(log.read_bytes(),b'old log')
        (self.game/'unknown.dll').write_bytes(b'root drift')
        with self.assertRaisesRegex(ValueError,'drift'):subject.restore(self.session)
        self.assertTrue((self.game/'unknown.dll').exists())

    def test_protected_data_or_static_executable_cannot_enter_generic_extra_files(self):
        for path in (self.data/'VersionManifest.json',self.game/'SkyrimSE.exe',self.plugin/'source.py'):
            self.value['extra_files']=[str(path)]
            with self.assertRaises(ValueError):self.plan()

    def test_data_drift_does_not_auto_clear_build_or_restore_foreign_data(self):
        self.prepare();unexpected=self.data/'BuildData.json';unexpected.write_bytes(b'new unknown build')
        self.restore_ordinary()
        with self.assertRaisesRegex(ValueError,'BuildData'):subject.restore(self.session)
        self.assertEqual(unexpected.read_bytes(),b'new unknown build')
        self.assertEqual(self.ini.read_bytes(),self.original)

    def test_cold_owned_bridge_proof_requires_birth_ini_and_instance_identity(self):
        self.prepare();subject.before_launch(self.session)
        minimum=self.session.state['rootBuilderPassive']['coldStartProof']['minimumProcessBirth']
        owned={'pid':100,'path':str(self.mo2/'ModOrganizer.exe'),'birth':minimum+10}
        self.session.state['owned']=[{'role':'mo2','identity':owned}];self.identities[100]=owned
        bridge={'mo2Pid':100,'serverBootId':'boot','instanceId':'portable','profilesPath':str(self.profile.parent)}
        with self.assertRaisesRegex(ValueError,'Bridge instance'):subject.verify_boot(self.session,{**bridge,'mo2Pid':200})
        self.identities[100]={**owned,'birth':minimum-10}
        with self.assertRaises(ValueError):subject.verify_boot(self.session,bridge)
        self.identities[100]=owned
        subject.verify_boot(self.session,bridge)
        self.assertEqual(self.session.state['rootBuilderPassive']['phase'],'verified-before-game')
        with self.assertRaises(ValueError):subject.verify_boot(self.session,bridge)

    def test_ini_change_after_cold_proof_refuses_before_game(self):
        self.prepare();subject.before_launch(self.session)
        minimum=self.session.state['rootBuilderPassive']['coldStartProof']['minimumProcessBirth']
        owned={'pid':100,'path':str(self.mo2/'ModOrganizer.exe'),'birth':minimum+1};self.identities[100]=owned
        self.session.state['owned']=[{'role':'mo2','identity':owned}]
        self.ini.write_text(self.ini.read_text()+'\nOther=changed\n')
        with self.assertRaisesRegex(ValueError,'INI changed'):
            subject.verify_boot(self.session,{'mo2Pid':100,'serverBootId':'boot','instanceId':'portable','profilesPath':str(self.profile.parent)})

    def test_policy_unknown_fields_mutable_globs_and_vr_or_reuse_refuse(self):
        policy=self.value['root_builder_passive']
        for change in ({'mode':'copy-5.1.1'},{'settingsProof':'assume'},{'mutableGameFiles':['*.log']},{'mutableGameFiles':['SkyrimSE.exe']},{'unknown':True}):
            with self.assertRaises(ValueError):subject.configuration({**policy,**change})
        for change in ({'game_edition':'vr'},{'reuse_test_profile':True},{'root_builder_data':'x'}):
            with self.assertRaises(ValueError):subject.preflight({**self.value,**change},self.profile)

    def test_default_inheritance_cannot_fake_native_plugin_settings(self):
        self.ini.write_text('[DEFAULT]\nRootBuilder\\autobuild=false\nRootBuilder\\redirect=false\n'+self.original.decode())
        with self.assertRaisesRegex(ValueError,'Inherited DEFAULT'):self.plan()
        self.assertEqual(self.session.writes,[])

    def test_staging_changes_only_local_plugins_not_other_sections(self):
        text=self.original.decode()+'\n[Other]\nRootBuilder\\autobuild=true\nRootBuilder\\redirect=true\n'
        self.ini.write_text(text);self.prepare()
        subject._off(self.ini)
        self.assertEqual(self.ini.read_text().split('[Other]')[1],text.split('[Other]')[1])

    def test_postgame_mutable_log_hardlink_refuses_before_generic_restore(self):
        log=self.game/'Debug.log';log.write_bytes(b'old log')
        self.value['root_builder_passive']['mutableGameFiles']=['Debug.log'];self.value['extra_files']=[str(log)]
        self.session.state['configuration']=copy.deepcopy(self.value)
        self.session.snapshot(log);self.prepare()
        foreign=self.root/'foreign.log';foreign.write_bytes(b'foreign protected bytes')
        log.unlink();os.link(foreign,log)
        with self.assertRaises(ValueError):subject.restore_precheck(self.session)
        self.assertEqual(foreign.read_bytes(),b'foreign protected bytes')

    def test_staged_destination_hardlink_cannot_change_static_root_before_late_prepare(self):
        destination=self.overwrite/'SKSE/Plugins/probe.dll';destination.parent.mkdir(parents=True)
        os.link(self.game/'SkyrimSE.exe',destination)
        self.value['staged_plugins']=[{'destination':'SKSE/Plugins/probe.dll'}]
        with self.assertRaises(ValueError):self.plan()
        self.assertEqual((self.game/'SkyrimSE.exe').read_bytes(),b'synthetic game')

    def test_hidden_static_root_member_is_not_silently_excluded(self):
        hidden=self.game/'.sentinel';hidden.write_bytes(b'original')
        self.prepare();hidden.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'drift'):subject.restore_precheck(self.session)


class PassiveRunnerIntegrationTests(unittest.TestCase):
    def setUp(self):
        import test_editions as edition_tests
        from skyrim_autotest import runner
        self.runner=runner
        self.base=edition_tests.EditionTests('test_se_preflight_requires_neither_openvr_nor_driver_nor_vrik_higgs')
        self.base.setUp();self.addCleanup(self.base.doCleanups)
        p=config.P
        plugin=p.mo2/'plugins/rootbuilder';plugin.mkdir(parents=True);(plugin/'source.py').write_bytes(b'synthetic source')
        pin=rb.plugin_fingerprint(plugin)
        scope=patch.object(rb,'SUPPORTED_PLUGIN_SHA256',pin);scope.start();self.addCleanup(scope.stop)
        (p.mo2/'portable.txt').write_bytes(b'')
        data=p.mo2/'plugins/data/RootBuilder';data.mkdir(parents=True);(data/'VersionManifest.json').write_bytes(b'{}')
        with p.mo2_ini.open('a') as f:f.write('[Plugins]\nRootBuilder\\migrated=true\nRootBuilder\\copyfiles=**\nRootBuilder\\linkfiles=\nRootBuilder\\usvfsfiles=\n')
        value=p.snapshot();value['root_builder_passive']={'mode':subject.MODE,'settingsProof':subject.PROOF,'pluginTreeSha256':pin,
            'dataTreeSha256':rb._digest(rb._tree(data)),'loaderSha256':rb._hash(p.game/'skse64_loader.exe')['sha256'],
            'mo2ExeSha256':rb._hash(p.mo2_exe)['sha256'],'mutableGameFiles':[]}
        runner.configure(value)

    def session(self):
        runner=self.runner;info=self.base.preflight();directory=runner.RUNS/'passive-offline';directory.mkdir(parents=True)
        state=dict(id='passive-offline',runner=None,snapshots=[],owned=[],launchIntents={},checks=[],preflight=info,
                   configuration=config.P.snapshot(),scenario={},driverBackend='none',inputBackend='devbench',restored=False)
        return runner.Session(directory,state)

    def test_runner_setup_and_ordinary_cleanup_restore_ini_without_root_deployment(self):
        original=config.P.mo2_ini.read_bytes();session=self.session()
        processes=[{'pid':4,'parent':0,'name':'System'}]
        with patch.object(native,'processes',return_value=processes):session.setup()
        subject._off(config.P.mo2_ini)
        self.assertEqual(session.state['rootBuilderPassive']['phase'],'prepared')
        self.assertTrue(session.state['rootBuilderPassiveWriteBarrier'])
        with patch.object(native,'processes',return_value=processes),patch.object(session,'collect',return_value=True):session.cleanup()
        self.assertTrue(session.state['restored'])
        self.assertEqual(config.P.mo2_ini.read_bytes(),original)
        self.assertEqual(session.state['rootBuilderPassive']['phase'],'restored-unchanged')

    def test_snapshot_guard_rejects_staged_alias_before_any_write(self):
        session=self.session();destination=config.P.overwrite/'SKSE/Plugins/probe.dll';destination.parent.mkdir(parents=True)
        os.link(config.P.game/'SkyrimSE.exe',destination)
        with self.assertRaises(ValueError):session.write(destination,b'should never be written')
        self.assertEqual((config.P.game/'SkyrimSE.exe').read_bytes(),b'executable placeholder, never run')

    def test_partial_setup_before_prepare_retains_full_recovery_barrier(self):
        runner=self.runner
        source=self.base.root/'candidate.dll';source.write_bytes(b'synthetic staged bytes')
        value=config.P.snapshot();value['staged_plugins']=[{'source':str(source),'sha256':rb._hash(source)['sha256'],
                                                          'destination':'SKSE/Plugins/candidate.dll'}]
        runner.configure(value);session=self.session()
        data=config.P.mo2/'plugins/data/RootBuilder/VersionManifest.json'
        def fail(*args):
            data.write_bytes(b'unknown data drift')
            raise ValueError('fault before passive.prepare')
        processes=[{'pid':4,'parent':0,'name':'System'}]
        with patch.object(native,'processes',return_value=processes),patch.object(subject,'prepare',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'fault before'):session.setup()
        staged=config.P.overwrite/'SKSE/Plugins/candidate.dll'
        self.assertTrue(staged.is_file())
        self.assertEqual(session.state['rootBuilderPassive']['phase'],'write-barrier')
        with patch.object(native,'processes',return_value=processes),patch.object(session,'collect',return_value=True):
            with self.assertRaisesRegex(ValueError,'data tree changed'):session.cleanup()
        self.assertFalse(session.state['restored'])
        self.assertEqual(staged.read_bytes(),b'synthetic staged bytes')
        self.assertEqual(data.read_bytes(),b'unknown data drift')


if __name__=='__main__':unittest.main()
