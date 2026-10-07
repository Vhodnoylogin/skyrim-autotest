"""A missed startup edge must not abort immediately or leak input into a world."""
import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap
from skyrim_autotest.readiness_reads import ReadinessSession

class Clock:
    now=0
    def monotonic(self): return self.now
    def sleep(self,seconds): self.now+=seconds

class Session:
    def __init__(self,success=2,changed_cell=False,unknown=False):
        self.state={'inputBackend':'driver','driverBackend':'file'}
        self.calls=[];self.logs=[];self.frames=[]
        self.success=success;self.changed_cell=changed_cell;self.unknown=unknown
    def phase(self,*args): self.phase_args=args
    def log(self,kind,**kwargs): self.logs.append((kind,kwargs))
    def tool(self,name,args,**kwargs):
        self.calls.append((name,args))
        if name=='menu':
            names=['HUD Menu'] if len(self.frames)>=self.success else ['CalibrationOptionMenu','HUD Menu']
            if self.unknown and self.frames: names.append('InventoryMenu')
            return {'openMenus':names,'messageBoxOpen':False}
        if name=='inspect':
            return {'cell':{'editorId':'QASmoke' if self.changed_cell and self.frames else 'VRPlayroom01'}}
        if name=='driver':
            if args['action']=='publish': self.frames.append(args['frame'])
            return {'acknowledgedByDriver':False,'gameConsumptionProven':False}
        raise AssertionError(name)

class CalibrationRecoveryTests(unittest.TestCase):
    def run_case(self,session,clock=None,wrapper_deadline=None):
        clock=clock or Clock()
        with patch.object(bootstrap.time,'monotonic',clock.monotonic),patch.object(bootstrap.time,'sleep',clock.sleep):
            return bootstrap.advance_calibration(ReadinessSession(session,wrapper_deadline) if wrapper_deadline is not None else session)

    def test_first_ignored_edge_uses_other_hand_after_observed_same_screen(self):
        s=Session(success=2)
        self.assertTrue(self.run_case(s))
        self.assertEqual(len(s.frames),2)
        self.assertEqual(s.frames[0]['right']['controller']['pressed'],1<<33)
        self.assertEqual(s.frames[1]['left']['controller']['pressed'],1<<33)
        self.assertEqual(sum(a['action']=='release' for n,a in s.calls if n=='driver'),2)
        self.assertEqual([x[1]['attempt'] for x in s.logs if x[0]=='gameplay-startup-screen'],[1,2])

    def test_four_candidates_and_single_deadline_stop_without_world_mutation(self):
        s=Session(success=99);clock=Clock()
        with self.assertRaisesRegex(AssertionError,'bounded observed'):
            self.run_case(s,clock)
        self.assertEqual(len(s.frames),4)
        self.assertEqual(s.frames[2]['right']['controller']['pressed'],1<<2)
        self.assertEqual(s.frames[3]['left']['controller']['pressed'],1<<2)
        self.assertLess(clock.now,20)
        self.assertEqual(s.phase_args,('gameplay-startup-calibration-button',25))
        self.assertFalse(any(n in ('console','game','papyrus') for n,a in s.calls))

    def test_changed_world_prevents_second_candidate(self):
        s=Session(success=99,changed_cell=True)
        with self.assertRaisesRegex(AssertionError,'identity changed'): self.run_case(s)
        self.assertEqual(len(s.frames),1)

    def test_unexpected_menu_prevents_second_candidate(self):
        s=Session(success=99,unknown=True)
        with self.assertRaisesRegex(AssertionError,'identity changed'): self.run_case(s)
        self.assertEqual(len(s.frames),1)

    def test_actual_closure_stops_even_without_driver_ack(self):
        s=Session(success=1)
        self.assertTrue(self.run_case(s));self.assertEqual(len(s.frames),1)

    def test_expired_outer_deadline_still_releases_local_input(self):
        s=Session(success=99)
        with self.assertRaises(TimeoutError): self.run_case(s,wrapper_deadline=.2)
        self.assertEqual(len(s.frames),1)
        self.assertEqual([a['action'] for n,a in s.calls if n=='driver'],['publish','release'])

    def test_driver_status_failure_still_releases_and_is_not_retried(self):
        s=Session();original=s.tool
        def tool(name,args,**kwargs):
            if name=='driver' and args['action']=='status': raise RuntimeError('identity lost')
            return original(name,args,**kwargs)
        s.tool=tool
        with self.assertRaisesRegex(RuntimeError,'identity lost'): self.run_case(s)
        self.assertEqual([a['action'] for n,a in s.calls if n=='driver'],['publish','release'])

    def test_late_unknown_message_is_terminal_without_second_candidate(self):
        s=Session(success=99);original=s.tool
        def tool(name,args,**kwargs):
            value=original(name,args,**kwargs)
            if name=='menu' and s.frames:value['messageBoxOpen']=True
            return value
        s.tool=tool
        with patch.object(bootstrap.vr_probe,'guard_fixture_modal',side_effect=AssertionError('unknown modal')):
            with self.assertRaisesRegex(AssertionError,'unknown modal'): self.run_case(s)
        self.assertEqual(len(s.frames),1)

if __name__=='__main__':unittest.main()
