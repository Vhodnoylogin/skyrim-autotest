"""Fault boundaries found by the2026-10-07 audit. No native program is launched."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import runner, native, scenarios, platform, profile_cache as cache


class CollectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); logs=self.root/'skse'; logs.mkdir()
        self.steam=self.root/'steam'; self.steam.mkdir()
        vrpaths=self.root/'vrpaths.json'; vrpaths.write_text(json.dumps({'log':[str(self.steam)]}))
        self.config=SimpleNamespace(skse_logs=logs,mo2=self.root/'mo2',overwrite=self.root/'overwrite',value={})
        self.directory=self.root/'run'; self.directory.mkdir()
        self.session=runner.Session(self.directory,{'id':'audit-test','owned':[], 'snapshots':[],
            'checks':[],'launchIntents':{},'preflight':{'profile':'Owner','vrpaths':str(vrpaths)}})
        self.file=self.root/'original.ini'; self.file.write_bytes(b'original')
        self.session.write(self.file,b'modified')
        self.patcher=patch.object(runner,'P',self.config); self.patcher.start(); self.addCleanup(self.patcher.stop)
        self.processes=patch.object(native,'processes',return_value=[]); self.processes.start(); self.addCleanup(self.processes.stop)

    def test_log_sharing_violation_retains_error_but_restores_files(self):
        (self.steam/'vrserver.txt').write_text('diagnostic')
        real=runner.shutil.copy2
        def copy(source,target,*a,**kw):
            if Path(source)==self.steam/'vrserver.txt': raise PermissionError('sharing violation')
            return real(source,target,*a,**kw)
        with patch.object(runner.shutil,'copy2',side_effect=copy): self.session.cleanup()
        self.assertEqual(self.file.read_bytes(),b'original')
        self.assertTrue(self.session.state['restored'])
        self.assertFalse(self.session.state['collectionComplete'])
        self.assertEqual(self.session.state['result'],'failed')
        self.assertIn('sharing violation',self.session.state['collectionErrors'][0]['error'])
        self.session.report()
        self.assertFalse(runner.read_json(self.directory/'result.json')['collectionComplete'])

    def test_unexpected_collector_failure_still_restores_files(self):
        with patch.object(self.session,'collect',side_effect=RuntimeError('unexpected collector fault')):
            self.session.cleanup()
        self.assertEqual(self.file.read_bytes(),b'original')
        self.assertTrue(self.session.state['restored'])
        self.assertFalse(self.session.state['collectionComplete'])

    def test_declared_output_captured_before_restore_without_exposing_unselected_files(self):
        output=self.root/'output.json'; output.write_bytes(b'old')
        self.session.write(output,b'{"measurement":12345}')
        self.config.value['collected_files']=[str(output)]
        self.session.cleanup()
        self.assertEqual(output.read_bytes(),b'old')
        entries=runner.read_json(self.directory/'evidence/manifest.json')
        selected=next(p for p in entries if p['kind']=='declared-output')
        self.assertEqual((self.directory/'evidence'/selected['name']).read_bytes(),b'{"measurement":12345}')
        self.assertEqual(selected['sha256'],runner.sha(self.directory/'evidence'/selected['name']))
        self.assertNotIn(str(self.file),[p['source'] for p in entries])
        self.assertTrue(self.session.state['collectionComplete'])

    def test_missing_required_output_is_not_empty_success_and_restoration_completes(self):
        self.config.value['collected_files']=[str(self.root/'missing.json')]
        self.session.cleanup()
        self.assertTrue(self.session.state['restored'])
        self.assertFalse(self.session.state['collectionComplete'])
        self.assertEqual(self.session.state['result'],'failed')

    def test_bridge_steam_and_restart_artifacts_are_all_manifest_pinned(self):
        (self.steam/'vrserver.txt').write_bytes(b'before restart')
        bridge=self.config.mo2/'plugins/mo2aibridge/mo2aibridge.log'
        bridge.parent.mkdir(parents=True); bridge.write_bytes(b'bridge')
        self.assertTrue(self.session.collect('before-restart-1'))
        (self.steam/'vrserver.txt').write_bytes(b'after restart')
        self.assertTrue(self.session.collect())
        entries=runner.read_json(self.directory/'evidence/manifest.json')
        names={p['name'] for p in entries}
        self.assertTrue({'vrserver.txt','mo2aibridge.log','before-restart-1--vrserver.txt',
                         'before-restart-1--mo2aibridge.log'} <= names)
        for p in entries:self.assertEqual(runner.sha(self.directory/'evidence'/p['name']),p['sha256'])
        self.assertEqual((self.directory/'evidence/before-restart-1--vrserver.txt').read_bytes(),b'before restart')

    def test_foreign_game_still_blocks_restore_after_collection_error(self):
        with patch.object(native,'processes',return_value=[{'pid':5,'name':'SkyrimVR.exe','parent':1}]), \
                patch.object(self.session,'collect',side_effect=RuntimeError('collection failed')):
            with self.assertRaisesRegex(RuntimeError,'Unexpected session'):self.session.cleanup()
        self.assertEqual(self.file.read_bytes(),b'modified')


class AcquisitionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.profiles=self.root/'profiles'
        self.source=self.profiles/'Owner'; self.source.mkdir(parents=True)
        (self.source/'modlist.txt').write_text('+Mod\n')
        self.runtime=self.root/'runtime'; self.key,self.name=cache.identity(self.source,self.profiles)
        self.home,self.target=cache.paths(self.runtime,self.profiles,self.key,self.name)
    def acquire(self,owner='owner'):return cache.acquire(self.runtime,self.profiles,self.key,self.name,owner,runner.atomic_json)
    def release(self,owner='owner'):return cache.release(self.runtime,self.profiles,self.key,self.name,owner,self.root/(owner+'-evidence'),runner.atomic_json)
    def test_interrupt_before_first_mkdir_archives_only_exact_empty_intent(self):
        real=Path.mkdir
        def mkdir(path,*a,**kw):
            if path==self.target:raise OSError('interrupted mkdir')
            return real(path,*a,**kw)
        with patch.object(Path,'mkdir',mkdir):
            with self.assertRaises(OSError):self.acquire()
        self.release()
        self.assertFalse(self.target.exists())
        self.assertEqual(cache.digest(self.home/'profile'),{})
        self.acquire('next')
        self.release('next')
    def test_interrupt_before_existing_archive_move_preserves_previous_files(self):
        target,_=self.acquire('first'); cache.reset(target,self.source,self.root/'prior'); self.release('first')
        before=cache.digest(self.home/'profile')
        with patch.object(cache.shutil,'move',side_effect=OSError('interrupted move')):
            with self.assertRaises(OSError):self.acquire()
        self.release()
        self.assertEqual(cache.digest(self.home/'profile'),before)
        self.assertEqual(cache.digest(self.root/'owner-evidence'),before)
        self.assertTrue(runner.read_json(self.home/'record.json')['acquisitionNeverMounted'])
    def test_interrupt_after_mount_before_lease_commit_is_recoverable(self):
        def write(path,value):
            if value.get('state')=='leased':raise OSError('interrupted lease commit')
            runner.atomic_json(path,value)
        with self.assertRaises(OSError):cache.acquire(self.runtime,self.profiles,self.key,self.name,'owner',write)
        self.release();self.assertFalse(self.target.exists())
        self.assertEqual(runner.read_json(self.home/'record.json')['state'],'archived')
    def test_unexpected_files_or_foreign_owner_are_not_silently_accepted(self):
        self.home.mkdir(parents=True)
        runner.atomic_json(self.home/'record.json',{'schemaVersion':2,'state':'preparing',
            'run':'owner','archiveBefore':None})
        self.target.mkdir();(self.target/'foreign.txt').write_text('foreign')
        with self.assertRaisesRegex(RuntimeError,'identity mismatch'):self.release()
        with self.assertRaisesRegex(RuntimeError,'another run'):self.release('foreign')


class DeadlineAndSchemaTests(unittest.TestCase):
    def test_health_exhausting_budget_never_dispatches_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            s=runner.Session(Path(tmp),{'id':'bounded','checks':[],'port':1,'game':{'pid':10}})
            now=[0.];routes=[]
            def request(port,route,body=None,token=None,timeout=12):
                routes.append(route);now[0]+=2;return {'pid':10}
            scenario={'steps':[{'name':'mutation','tool':'console','args':{'action':'exec','command':'fixture'},
                'timeout':1,'assert':[{'path':'completed','equals':True}]}]}
            with patch.object(runner,'request',side_effect=request),patch.object(native,'alive',return_value=True), \
                    patch.object(runner.time,'monotonic',side_effect=lambda:now[0]):
                with self.assertRaises(TimeoutError):scenarios.execute(s,scenario)
            self.assertEqual(routes,['api/health'])
            self.assertEqual(s.state['checks'][0]['result'],'failed')
    def test_json_boolean_equality_is_typed_recursively_but_numbers_remain_numbers(self):
        for actual,expected in [(1,True),(0,False),({'flag':1},{'flag':True}),([0],[False])]:
            self.assertFalse(scenarios.check({'x':actual},{'path':'x','equals':expected}))
        self.assertTrue(scenarios.check({'x':1},{'path':'x','equals':1.0}))
        self.assertTrue(scenarios.check({'x':{'flag':True}},{'path':'x','equals':{'flag':True}}))
    def test_documented_exists_nullness_contract_is_preserved(self):
        self.assertTrue(scenarios.check({'x':None},{'path':'x','exists':False}))
        with self.assertRaises(KeyError):scenarios.check({}, {'path':'x','exists':False})
    def test_readiness_rejects_bad_cell_identity_and_retains_menu_gate(self):
        s=SimpleNamespace(state={'gameplayBootstrap':{'completed':True}})
        menus={'messageBoxOpen':False,'openMenus':[],'menuStates':[]}
        for cell,expected in [('',False),(False,False),(123,False),('VRPlayroom01',False),('QASmoke',True)]:
            with patch.object(platform.Backend,'call',side_effect=[{'playerLoaded':True,'cell':{'editorId':cell}},menus]):
                self.assertIs(platform.execute(s,{'operation':'state.read'},999)['world']['ready'],expected)
        with patch.object(platform.Backend,'call',side_effect=[{'playerLoaded':True,'cell':{'editorId':'QASmoke'}},{**menus,'messageBoxOpen':True}]):
            self.assertFalse(platform.execute(s,{'operation':'state.read'},999)['world']['ready'])
