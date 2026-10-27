"""Guardian races use the actual observer without launching or stopping processes."""
import copy
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import runner, runner_monitor


class GuardianDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.owner = {'pid': 10, 'birth': 100, 'path': 'C:/Python/python.exe'}
        self.game = {'pid': 20, 'birth': 200, 'path': 'C:/Game/SkyrimSE.exe'}
        self.state = {'id': 'guardian-race', 'runner': self.owner, 'game': self.game,
                      'port': 8920, 'phase': 'wait-task-queue', 'deadline': time.time()+90,
                      'heartbeat': time.time(), 'done': False}
        self.health = {'pid': 20, 'frame': 275, 'lastTaskFrame': 167, 'pendingTasks': 0}
        self.write_state()

    def write_state(self):
        runner.atomic_json(self.root/'state.json', self.state)

    def pulse(self, **changes):
        value = runner_monitor.snapshot(self.state)
        value.update(changes)
        runner.atomic_json(self.root/'heartbeat.json', value)

    def recheck(self, *, health=None, marker=(167, -1), changed=None, failed=None):
        with patch.object(runner.native, 'alive', return_value=True), \
             patch.object(runner, 'request', return_value=self.health if health is None else health):
            return runner._guardian_recheck(self.root, copy.deepcopy(self.state), marker,
                time.monotonic()-25 if changed is None else changed, failed)

    def test_false_then_true_owner_lookup_never_terminates_healthy_worker(self):
        """Old two independent alive calls reached terminate with expired=False."""
        self.state['heartbeat'] = time.time()-28
        self.write_state()
        self.pulse()
        owner_calls = []
        def alive(identity):
            if identity == self.owner:
                owner_calls.append(identity)
                return len(owner_calls) > 1
            return True
        def request(port, route, **kwargs):
            return self.health if route == 'api/health' else {'events': []}
        def sleep(_):
            self.state['done'] = True
            self.write_state()
        terminate = Mock(side_effect=AssertionError('Healthy worker must not be killed'))
        with patch.object(runner.native, 'alive', side_effect=alive), \
             patch.object(runner.native, 'terminate', terminate), \
             patch.object(runner.native, 'SessionMutex', side_effect=AssertionError('No recovery claim')), \
             patch.object(runner, 'request', side_effect=request), \
             patch.object(runner.time, 'sleep', side_effect=sleep):
            runner.guardian(self.root)
        terminate.assert_not_called()
        records = [json.loads(line) for line in (self.root/'guardian-decisions.jsonl').read_text().splitlines()]
        self.assertFalse(records[0]['ownerAlive'])
        self.assertFalse(records[0]['expired'])
        self.assertTrue(records[1]['ownerAlive'])
        self.assertEqual(records[1]['action'], 'cancelled')
        self.assertFalse(records[1]['expired'])

    def test_recovered_frames_and_drained_queue_cancel_stall_candidate(self):
        result = self.recheck()
        self.assertFalse(result['expired'])
        self.assertEqual(result['health']['frame'], 275)

    def test_actual_pending_stall_still_requires_recovery(self):
        result = self.recheck(health=dict(self.health, frame=167, lastTaskFrame=-1, pendingTasks=5))
        self.assertTrue(result['expired'])
        self.assertIn('pending-task-stall', result['reasons'])
        self.assertIn('stalled', result['reason'])

    def test_stale_full_state_uses_fresh_bound_sidecar_before_kill(self):
        self.state['heartbeat'] = time.time()-100
        self.write_state()
        self.pulse()
        self.assertFalse(self.recheck()['expired'])
        self.pulse(runner=dict(self.owner, birth=101))
        self.assertIn('runner-heartbeat-expired', self.recheck()['reasons'])

    def test_real_deadline_and_heartbeat_failure_are_not_disabled(self):
        self.state['deadline'] = time.time()-16
        self.write_state()
        self.assertIn('phase-deadline-exceeded', self.recheck()['reasons'])
        self.state['deadline'] = time.time()+90
        self.write_state()
        self.pulse(healthy=False, error={'message': 'monitor failure'})
        self.assertIn('heartbeat-reported-failure', self.recheck()['reasons'])

    def test_phase_change_during_health_request_cancels_old_decision(self):
        previous = copy.deepcopy(self.state)
        def request(*args, **kwargs):
            self.state.update(phase='gameplay-ready', deadline=time.time()+90)
            self.write_state()
            return self.health
        with patch.object(runner.native, 'alive', return_value=True), \
             patch.object(runner, 'request', side_effect=request):
            result = runner._guardian_recheck(self.root, previous, (167, -1), time.monotonic()-25, None)
        self.assertEqual(result['cancelled'], 'state-changed-during-recheck')
        self.assertFalse(result['reasons'])

    def test_done_or_changed_owner_never_becomes_a_new_termination_target(self):
        previous = copy.deepcopy(self.state)
        for changes, reason in (({'done': True}, 'runner-completed'),
                                ({'runner': dict(self.owner, birth=101)}, 'ownership-binding-changed'),
                                ({'game': dict(self.game, birth=201)}, 'ownership-binding-changed')):
            with self.subTest(changes=changes):
                runner.atomic_json(self.root/'state.json', dict(previous, **changes))
                with patch.object(runner.native, 'alive', side_effect=AssertionError('No process query')):
                    result = runner._guardian_recheck(self.root, previous, None, 0, None)
                self.assertEqual(result['cancelled'], reason)

    def test_connection_recovered_and_wrong_pid_are_distinct(self):
        failed = time.monotonic()-25
        self.assertFalse(self.recheck(failed=failed)['expired'])
        result = self.recheck(health=dict(self.health, pid=999), failed=failed)
        self.assertIn('devbench-identity-changed', result['reasons'])

    def test_sustained_connection_loss_still_arms_fresh_recovery(self):
        with patch.object(runner.native, 'alive', return_value=True), \
             patch.object(runner, 'request', side_effect=OSError('listener unavailable')):
            result = runner._guardian_recheck(self.root, self.state, (167, -1),
                                              time.monotonic()-25, time.monotonic()-25)
        self.assertIn('devbench-connection-lost', result['reasons'])

    def test_real_expiry_is_audited_before_exact_owner_termination_and_recovery(self):
        self.state['deadline'] = time.time()-16
        self.write_state()
        session = Mock()
        session.state = copy.deepcopy(self.state)
        session.cleanup.side_effect = lambda: session.state.update(restored=True)
        def terminate(identity):
            self.assertEqual(identity, self.owner)
            decision = json.loads((self.root/'guardian-decisions.jsonl').read_text().splitlines()[-1])
            self.assertEqual(decision['action'], 'terminate-expired-owner')
            self.assertTrue(decision['expired'])
            self.assertIn('phase-deadline-exceeded', decision['reasons'])
        with patch.object(runner.native, 'alive', return_value=True), \
             patch.object(runner.native, 'terminate', side_effect=terminate) as stop, \
             patch.object(runner.native, 'SessionMutex', side_effect=nullcontext), \
             patch.object(runner, 'Session', return_value=session), \
             patch.object(runner, 'request', side_effect=lambda port, route, **kw:
                          self.health if route == 'api/health' else {'events': []}):
            runner.guardian(self.root)
        stop.assert_called_once_with(self.owner)
        session.cleanup.assert_called_once_with()
        self.assertTrue(session.state['done'])
        self.assertEqual(session.state['guardianRecovery']['decision']['action'], 'terminate-expired-owner')


class StartupQueuePlacementTests(unittest.TestCase):
    def session(self, explicit=True, admission=True):
        session = Mock()
        game = {'pid': 20, 'birth': 200, 'path': 'C:/Game/SkyrimSE.exe'}
        session.state = {'configuration': {'se_new_game_ui': explicit}, 'game': game}
        if admission:
            session.state['seStartupAdmission'] = {'completed': True, 'game': dict(game), 'cursor': 12}
        return session

    def test_explicit_admitted_se_new_game_defers_ordinary_queue(self):
        session = self.session()
        runner.Session.complete_startup_admission(session, {'edition': 'se'})
        session.wait_task_queue.assert_not_called()
        self.assertEqual(session.log.call_args.kwargs['until'], 'native-new-game-transition')

    def test_vr_and_ordinary_se_keep_existing_queue_gate(self):
        for edition, explicit in (('vr', True), ('se', False)):
            with self.subTest(edition=edition):
                session = self.session(explicit=explicit)
                runner.Session.complete_startup_admission(session, {'edition': edition})
                session.wait_task_queue.assert_called_once_with()

    def test_explicit_se_missing_or_foreign_admission_refuses(self):
        for admission in (None, {'completed': True, 'game': {'pid': 999}}):
            with self.subTest(admission=admission):
                session = self.session(admission=False)
                if admission: session.state['seStartupAdmission'] = admission
                with self.assertRaises(runner.Blocked):
                    runner.Session.complete_startup_admission(session, {'edition': 'se'})
                session.wait_task_queue.assert_not_called()


if __name__ == '__main__': unittest.main()
