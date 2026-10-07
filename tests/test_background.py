"""Explicit background mode cannot silently replace the physical outcome contract."""
import json
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import runner, native
from skyrim_autotest.vr_probe import ensure_owned_focus
from skyrim_autotest.scenarios import validate

class BackgroundTests(unittest.TestCase):
    class Session:
        def __init__(self,backend='driver'):
            self.state={'game':{'pid':123},'inputBackend':backend,'driverBackend':'file','deadline':time.time()+.01}
            self.logs=[]
        def log(self,kind,**values):self.logs.append((kind,values))
        def pause_focus_input(self):
            self.state['focusInputPaused']=True
            return self.state.get('activeInput',False)
        def resume_focus_input(self):self.state['focusInputPaused']=False
    def test_default_focus_denial_still_fails(self):
        session=self.Session()
        with patch.object(native,'focus_owned',return_value={'requested':False,'focused':False}):
            with self.assertRaisesRegex(AssertionError,'did not grant foreground'):
                ensure_owned_focus(session,{},'before-grip')
        self.assertFalse(any(kind=='background-vr-attempt' for kind,values in session.logs))
    def test_platform_optin_observes_focus_but_startup_remains_strict(self):
        session=self.Session()
        session.state['configuration']={'allow_background_physical_vr':True}
        with patch.object(native,'focus_owned',return_value={'requested':False,'focused':False}) as focus:
            ensure_owned_focus(session,{},'platform-controller-owned-focus')
            focus.assert_called_with(session.state['game'],activate=False)
            with self.assertRaisesRegex(AssertionError,'did not grant foreground'):
                ensure_owned_focus(session,{},'startup-confirmation')
            self.assertEqual(focus.call_args.args,(session.state['game'],))
    def test_optin_logs_attempt_without_treating_foreground_as_input_proof(self):
        session=self.Session()
        focus={'requested':False,'focused':False,'foreground':{'pid':999}}
        with patch.object(native,'focus_owned',return_value=focus):
            result=ensure_owned_focus(session,{'allowBackgroundVR':True},'before-grip')
        self.assertEqual(result,focus)
        self.assertEqual(session.logs[-1][0],'background-vr-attempt')
        self.assertTrue(session.logs[-1][1]['physicalAssertionsRequired'])
        self.assertFalse(session.logs[-1][1]['acceptedAsInputProof'])
    def test_injection_backend_cannot_opt_into_physical_background_mode(self):
        session=self.Session(backend='devbench')
        with patch.object(native,'focus_owned') as focus:
            with self.assertRaisesRegex(ValueError,'physical file-adapter'):
                ensure_owned_focus(session,{'allowBackgroundVR':True},'before-grip')
            focus.assert_not_called()
    def test_runner_rejects_wrong_backend_before_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            file=Path(directory)/'scenario.json'
            file.write_text(json.dumps({'schemaVersion':1,'kind':'vr-hand-probe','cell':'QASmoke','allowBackgroundVR':True}),encoding='utf-8')
            with patch.object(runner,'recover') as recover:
                with self.assertRaisesRegex(runner.Blocked,'physical file-adapter'):
                    runner.run('Test',file,input_backend='devbench')
                recover.assert_not_called()
    def test_background_option_requires_boolean_and_physical_probe(self):
        for kind,value in [('vr-hand-probe',1),('vr-hand-probe','true'),('generic',True)]:
            with self.subTest(kind=kind,value=value),self.assertRaisesRegex(ValueError,'allowBackgroundVR'):
                validate({'schemaVersion':1,'kind':kind,'cell':'QASmoke','allowBackgroundVR':value})

if __name__=='__main__':unittest.main()


class FocusRecoveryTests(unittest.TestCase):
    Session=BackgroundTests.Session
    def test_temporary_denial_pauses_then_recovers_without_replay(self):
        session=self.Session();session.state['deadline']=time.time()+10
        with patch.object(native,'focus_owned',side_effect=[{'focused':False},{'focused':True}]) as focus, patch('skyrim_autotest.vr_probe.time.sleep'):
            ensure_owned_focus(session,{},'startup-confirmation')
        self.assertEqual(focus.call_args_list[0].kwargs,{'activate':False})
        self.assertIn('timeout',focus.call_args_list[1].kwargs)
        self.assertFalse(session.state['focusInputPaused'])
        self.assertTrue(any(k=='focus-recovered' for k,v in session.logs))

    def test_released_active_input_is_not_replayed_after_recovery(self):
        session=self.Session();session.state.update(deadline=time.time()+10,activeInput=True)
        with patch.object(native,'focus_owned',side_effect=[{'focused':False},{'focused':True}]), patch('skyrim_autotest.vr_probe.time.sleep'):
            with self.assertRaisesRegex(AssertionError,'action not replayed'):
                ensure_owned_focus(session,{},'before-grip')
        self.assertFalse(session.state['focusInputPaused'])

    def test_action_deadline_caps_focus_wait_and_retains_pause(self):
        session=self.Session();session.state['deadline']=time.time()+60
        with patch.object(native,'focus_owned',return_value={'focused':False}):
            with self.assertRaisesRegex(AssertionError,'focus deadline'):
                ensure_owned_focus(session,{},'before-grip',deadline=time.monotonic()+.01)
        self.assertTrue(session.state['focusInputPaused'])


class FocusInputPauseTests(unittest.TestCase):
    def test_real_session_releases_once_blocks_publication_and_pauses_heartbeat(self):
        from skyrim_autotest import hardware
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            frame=hardware.neutral();frame['right']['controller']['pressed']=4
            session=runner.Session(directory,{'inputBackend':'driver','driverBackend':'file','hardwareFrame':frame})
            with patch.object(hardware,'publish') as publish:
                self.assertTrue(session.pause_focus_input())
                self.assertEqual(frame['right']['controller']['pressed'],0)
                publish.assert_called_once()
                with self.assertRaisesRegex(runner.Blocked,'paused'):
                    session.driver_tool({'action':'publish','frame':hardware.neutral(),'holdSeconds':1})
                session.finished=Mock();session.finished.wait.side_effect=[False,True]
                session.discover=Mock()
                session.heartbeat()
                publish.assert_called_once()
                session.resume_focus_input()
                self.assertFalse(session.state['focusInputPaused'])
                self.assertEqual(frame['right']['controller']['pressed'],0)
