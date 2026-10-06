"""Explicit background mode cannot silently replace the physical outcome contract."""
import json
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
            self.state={'game':{'pid':123},'inputBackend':backend,'driverBackend':'file'}
            self.logs=[]
        def log(self,kind,**values):self.logs.append((kind,values))
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
            focus.assert_called_with(session.state['game'])
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
