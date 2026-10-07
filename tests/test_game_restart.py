import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from skyrim_autotest import game_restart, native, runner
from skyrim_autotest import restart_budget


class RestartTests(unittest.TestCase):
    def test_offline_fixture_callback_runs_after_exit_before_exact_single_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=self.backend(Path(tmp))
            def prepare():
                self.assertFalse(self.old_live)
                self.assertFalse(any(route=='run' for route,args in self.calls))
                self.calls.append(('fixture-write',None))
            with patch.object(native,'alive',side_effect=lambda i:self.old_live if i['pid']==17 else True), \
                 patch.object(native,'processes',return_value=[]),patch.object(runner,'request',side_effect=request):
                game_restart.start(b,before_launch=prepare)
            routes=[route for route,args in self.calls]
            self.assertEqual(routes.count('fixture-write'),1)
            self.assertLess(routes.index('console'),routes.index('fixture-write'))
            self.assertLess(routes.index('fixture-write'),routes.index('run'))

    def test_fixture_write_fault_prevents_relaunch_and_preserves_failed_owned_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=self.backend(Path(tmp))
            with patch.object(native,'alive',side_effect=lambda i:self.old_live if i['pid']==17 else True), \
                 patch.object(native,'processes',return_value=[]),patch.object(runner,'request',side_effect=request):
                with self.assertRaisesRegex(ValueError,'fixture failed'):
                    game_restart.start(b,before_launch=lambda:(_ for _ in ()).throw(ValueError('fixture failed')))
            self.assertFalse(any(route=='run' for route,args in self.calls))
            self.assertFalse(b.s.state['gameRestartTransition']['completed'])

    def state(self):
        old={'pid':17,'birth':1,'path':'SkyrimVR.exe'}
        return {'configuration':{'allow_owned_save_load':True},'game':old,
                'owned':[{'role':'game','identity':old}],
                'gameRestartTransition':{'completed':False,'stage':'stopping','beforeGame':old,
                                         'startedAt':100,'expiresAt':150}}

    def test_guardian_restart_exception_is_exact_owned_bounded_and_never_cleanup(self):
        state=self.state();self.assertTrue(game_restart.expected_restart(state,120))
        cases=[lambda s:s.update(owned=[]),lambda s:s['gameRestartTransition'].update(expiresAt=400),
               lambda s:s['gameRestartTransition'].update(completed=True),
               lambda s:s.update(phase='stop-and-restore'),
               lambda s:s['configuration'].update(allow_owned_save_load=False)]
        for change in cases:
            s=copy.deepcopy(state);change(s)
            with self.subTest(state=s):self.assertFalse(game_restart.expected_restart(s,120))
        self.assertFalse(game_restart.expected_restart(state,151))

    def backend(self, directory):
        state=self.state();state.pop('gameRestartTransition')
        state.update(testProfileName='Autotest-unit',launchIntents={})
        step={'name':'restart','tool':'platform','args':{'operation':'input.perform',
              'request':{'action':'restart_game','saveTag':'fixture','scope':'owned-disposable-profile'}}}
        state['scenario']={'schemaVersion':1,'steps':[step]}
        state['ownedGameRestartBudget']=restart_budget.plan(state['scenario'])
        state['activeScenarioStep']=restart_budget.step_identity('steps',0,step)
        token=directory/'private-token';token.write_text('unit-only')
        runtime=directory/'runtime.json';runtime.write_text('{"port":999}')
        state['configuration'].update(bridge_token=str(token),bridge_port=8930,
                                       mods=str(directory/'mods'),game=str(directory),devbench_runtime_files=[str(runtime)])
        self.old_live=True;self.calls=[];self.segments=[]
        new={'pid':19,'birth':2,'path':'SkyrimVR.exe'}
        session=SimpleNamespace(state=state,save=lambda:None,log=lambda *a,**k:None,
                                collect=lambda segment=None:self.segments.append(segment),own=lambda *a:None)
        def discover():
            if not any(p['identity']==new for p in state['owned']):state['owned'].append({'role':'game','identity':new})
        session.discover=discover
        b=SimpleNamespace(s=session,end=time.monotonic()+30,remaining=lambda:30,pause=lambda t:None)
        def call(tool,args):
            self.calls.append((tool,args))
            if tool=='console':self.old_live=False
            return {}
        b.call=call
        session.tool=lambda name,args,timeout=12,deadline=None:call(name,args)
        self.frames=iter([3,4])
        def request(port,route,body=None,**kwargs):
            self.calls.append((route,body))
            if route=='ping':return {'profile':state['testProfileName'],'game':'SkyrimVR','modsPath':state['configuration']['mods']}
            if route=='run':return {'started':True,'pid':18}
            if route=='api/health':return {'pid':19,'frame':next(self.frames)}
            raise AssertionError(route)
        return b,new,request

    def test_restart_one_owned_exit_and_one_launch_waits_for_fresh_matching_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=self.backend(Path(tmp))
            with patch.object(native,'alive',side_effect=lambda i:self.old_live if i['pid']==17 else True), \
                 patch.object(native,'processes',return_value=[]),patch.object(runner,'request',side_effect=request), \
                 patch.object(native,'terminate') as terminate:
                game_restart.start(b)
            self.assertEqual(b.s.state['game'],new)
            self.assertEqual(b.s.state['gameRestartTransition']['stage'],'loading')
            self.assertEqual(sum(route=='run' for route,args in self.calls),1)
            self.assertEqual(sum(route=='console' for route,args in self.calls),1)
            self.assertEqual(self.segments,['before-restart-1'])
            terminate.assert_not_called()

    def test_foreign_game_refuses_before_any_exit_or_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=self.backend(Path(tmp))
            with patch.object(native,'alive',return_value=True), \
                 patch.object(native,'processes',return_value=[{'name':'SkyrimVR.exe','pid':999}]), \
                 patch.object(native,'identity',return_value={'pid':999,'birth':9,'path':'SkyrimVR.exe'}), \
                 patch.object(runner,'request') as req:
                with self.assertRaisesRegex(ValueError,'Foreign game'):game_restart.start(b)
            self.assertEqual(self.calls,[]);req.assert_not_called()

    def test_old_process_health_cannot_be_adopted_as_restarted_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            b,new,request=self.backend(Path(tmp))
            def stale(port,route,body=None,**kwargs):
                if route=='api/health':return {'pid':17,'frame':999}
                return request(port,route,body,**kwargs)
            b.pause=lambda t:(_ for _ in ()).throw(TimeoutError('bounded stop'))
            with patch.object(native,'alive',side_effect=lambda i:self.old_live if i['pid']==17 else True), \
                 patch.object(native,'processes',return_value=[]),patch.object(runner,'request',side_effect=stale):
                with self.assertRaises(TimeoutError):game_restart.start(b)
            self.assertNotIn('game',b.s.state)
            self.assertFalse(b.s.state['gameRestartTransition']['completed'])

    def loader_backend(self):
        ident = dict(pid=18, birth=2, path='sksevr_loader.exe')
        self.clock = 0
        def pause(seconds): self.clock += seconds
        session = SimpleNamespace(state={'owned':[dict(role='loader',identity=ident)]},
                                  log=lambda *args,**kwargs:None)
        return SimpleNamespace(s=session,end=30,pause=pause),ident

    def test_owned_loader_natural_exit_is_waited_without_termination(self):
        b,ident=self.loader_backend()
        def processes(): return [dict(pid=18,name='sksevr_loader.exe')] if self.clock<.4 else []
        with patch.object(native,'processes',side_effect=processes), \
             patch.object(native,'identity',return_value=ident), \
             patch.object(game_restart.time,'monotonic',side_effect=lambda:self.clock), \
             patch.object(native,'close') as close, patch.object(native,'terminate') as terminate:
            game_restart.settle_owned_loaders(b)
        self.assertGreaterEqual(self.clock,.4)
        close.assert_not_called();terminate.assert_not_called()

    def test_stuck_exact_owned_loader_has_one_close_then_one_termination(self):
        b,ident=self.loader_backend(); self.loader_live=True
        def processes(): return [dict(pid=18,name='sksevr_loader.exe')] if self.loader_live else []
        def terminate(value): self.assertEqual(value,ident);self.loader_live=False
        with patch.object(native,'processes',side_effect=processes), \
             patch.object(native,'identity',return_value=ident), \
             patch.object(game_restart.time,'monotonic',side_effect=lambda:self.clock), \
             patch.object(native,'close') as close, patch.object(native,'terminate',side_effect=terminate) as stop:
            game_restart.settle_owned_loaders(b)
        close.assert_called_once_with(ident);stop.assert_called_once_with(ident)
        self.assertLess(self.clock,16)

    def test_foreign_or_reused_loader_never_closed_or_terminated(self):
        for actual in (None,dict(pid=18,birth=99,path='sksevr_loader.exe')):
            b,ident=self.loader_backend()
            with self.subTest(actual=actual), \
                 patch.object(native,'processes',return_value=[dict(pid=18,name='sksevr_loader.exe')]), \
                 patch.object(native,'identity',return_value=actual), \
                 patch.object(game_restart.time,'monotonic',side_effect=lambda:self.clock), \
                 patch.object(native,'close') as close, patch.object(native,'terminate') as stop:
                with self.assertRaisesRegex(ValueError,'Foreign|Unidentified'):
                    game_restart.settle_owned_loaders(b)
            close.assert_not_called();stop.assert_not_called()

    def test_exited_game_snapshot_without_identity_is_resampled_until_absent(self):
        b,ident=self.loader_backend()
        def processes():return [dict(pid=17,name='SkyrimVR.exe')] if self.clock<.4 else []
        with patch.object(native,'processes',side_effect=processes), \
             patch.object(native,'identity',return_value=None), \
             patch.object(game_restart.time,'monotonic',side_effect=lambda:self.clock), \
             patch.object(native,'close') as close, patch.object(native,'terminate') as stop:
            game_restart.settle_owned_loaders(b)
        self.assertGreaterEqual(self.clock,.4)
        close.assert_not_called();stop.assert_not_called()

    def test_unknown_snapshot_replaced_by_foreign_reused_pid_blocks_before_mutation(self):
        b,ident=self.loader_backend()
        with patch.object(native,'processes',return_value=[dict(pid=17,name='SkyrimVR.exe')]), \
             patch.object(native,'identity',side_effect=[None,dict(pid=17,birth=99,path='SkyrimVR.exe')]), \
             patch.object(game_restart.time,'monotonic',side_effect=lambda:self.clock), \
             patch.object(native,'close') as close, patch.object(native,'terminate') as stop:
            with self.assertRaisesRegex(ValueError,'Foreign'):game_restart.settle_owned_loaders(b)
        self.assertLess(self.clock,1)
        close.assert_not_called();stop.assert_not_called()


if __name__=='__main__':unittest.main()
