"""Concurrent state growth, durable pulse recovery and failed-heartbeat outcomes."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import Mock,patch
import unittest
from skyrim_autotest import runner,runner_monitor as monitor,hardware,native


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ident={'pid':10,'birth':100,'path':'C:/Python/python.exe'}
        self.state={'id':'monitor-test','runner':self.ident,'heartbeat':0,'owned':[],
                    'snapshots':[],'checks':[],'launchIntents':{},'preflight':{'profile':'Owner'}}
        self.session=runner.Session(self.root,self.state)

    def write_pulse(self,pulse):runner.atomic_json(self.root/'heartbeat.json',pulse)

    def test_background_save_never_traverses_main_owned_mutable_lifecycle(self):
        class UnserializableLifecycle:
            def __deepcopy__(self,memo):raise AssertionError('Cannot traverse mutable lifecycle')
        self.session.state['lifecycle']=UnserializableLifecycle()
        def heartbeat_save():
            self.session.heartbeat_thread_id=threading.get_ident()
            for _ in range(20):self.session.save()
        worker=threading.Thread(target=heartbeat_save);worker.start();worker.join(3)
        self.assertFalse(worker.is_alive())
        pulse=monitor.read(self.root,self.state);self.assertTrue(pulse['healthy'])
        self.assertNotIn('lifecycle',pulse['recovery']);self.assertFalse((self.root/'state.json').exists())

    def test_concurrent_dictionary_growth_does_not_kill_actual_heartbeat(self):
        self.session.state['lifecycle']={}
        self.session.finished=Mock();self.session.finished.wait.side_effect=[False]*20+[True]
        self.session.discover=Mock()
        writer_done=threading.Event()
        def grow():
            i=0
            while not writer_done.is_set():
                self.session.state['lifecycle'][str(i)]=i;i+=1
                if i%100==0:time.sleep(.0001)
        writer=threading.Thread(target=grow);writer.start()
        try:self.session.heartbeat()
        finally:writer_done.set();writer.join(3)
        self.assertFalse(self.session.heartbeat_failed.is_set())
        self.assertTrue(monitor.read(self.root,self.state)['healthy'])
        self.assertIsNone(self.session.heartbeat_thread_id)

    def test_failure_durable_and_blocks_subject_actions_and_marks_final_result_failed(self):
        self.session.state['result']='passed'
        self.session.finished=Mock();self.session.finished.wait.return_value=False
        self.session.discover=Mock(side_effect=RuntimeError('monitor fixture fault'))
        self.session.heartbeat()
        self.assertTrue(self.session.heartbeat_failed.is_set())
        pulse=monitor.read(self.root,self.state);self.assertFalse(pulse['healthy'])
        self.assertIn('monitor fixture fault',(self.root/'heartbeat-error.json').read_text())
        with self.assertRaisesRegex(runner.Blocked,'heartbeat failed'):self.session.tool('console',{'action':'exec','command':'coc QASmoke'})
        thread=Mock();thread.is_alive.return_value=False
        health=self.session.finish_heartbeat(thread)
        self.assertFalse(health['healthy']);self.assertEqual(self.state['result'],'failed')
        self.session.report();self.assertFalse(runner.read_json(self.root/'result.json')['heartbeatHealth']['healthy'])

    def test_failure_marker_write_failure_still_reaches_main_result(self):
        self.session.finished=Mock();self.session.finished.wait.return_value=False
        self.session.discover=Mock(side_effect=RuntimeError('fault'))
        with patch.object(runner,'atomic_json',side_effect=PermissionError('disk unavailable')):self.session.heartbeat()
        self.assertTrue(self.session.heartbeat_failed.is_set())
        thread=Mock();thread.is_alive.return_value=False
        self.assertFalse(self.session.finish_heartbeat(thread)['healthy'])

    def test_fresh_exact_pulse_keeps_guardian_alive_while_stale_state_does_not(self):
        self.write_pulse(monitor.snapshot(self.state))
        at,pulse=monitor.observed_at(self.root,self.state)
        self.assertGreater(at,time.time()-2);self.assertTrue(pulse['healthy'])
        for change in [{'id':'different'},{'runner':dict(self.ident,birth=101)},{'at':float('nan')},{'at':time.time()+100}]:
            with self.subTest(change=change):
                value=monitor.snapshot(self.state);value.update(change);self.write_pulse(value)
                self.assertIsNone(monitor.read(self.root,self.state))

    def test_new_owned_identity_and_input_frame_survive_abandoned_state_recovery(self):
        pulse=monitor.snapshot(self.state)
        pulse['recovery']['owned']=[{'role':'vr','identity':{'pid':20,'birth':200,'path':'C:/SteamVR/vrserver.exe'}}]
        pulse['recovery'].update(hardwareFrame=hardware.neutral(),hardwareOwner='owner-token',hardwareHoldUntilTickMs=123)
        self.write_pulse(pulse)
        recovered=copy.deepcopy(self.state);monitor.restore(self.root,recovered)
        self.assertEqual(recovered['owned'],pulse['recovery']['owned'])
        self.assertEqual(recovered['hardwareHoldUntilTickMs'],123)
        monitor.restore(self.root,recovered);self.assertEqual(len(recovered['owned']),1)

    def test_old_pulse_cannot_overwrite_newer_durable_input(self):
        pulse=monitor.snapshot(self.state);pulse['recovery']['hardwareOwner']='old';self.write_pulse(pulse)
        self.state.update(stateSavedAt=time.time()+.01,hardwareOwner='new')
        monitor.restore(self.root,self.state);self.assertEqual(self.state['hardwareOwner'],'new')

    def test_invalid_pulse_owned_role_is_rejected_without_takeover(self):
        pulse=monitor.snapshot(self.state);pulse['recovery']['owned']=[{'role':'steam','identity':self.ident}]
        self.write_pulse(pulse);self.assertIsNone(monitor.read(self.root,self.state))


if __name__=='__main__':unittest.main()
