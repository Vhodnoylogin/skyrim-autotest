import copy
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from skyrim_autotest import game_restart, native, runner


class RestartTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
