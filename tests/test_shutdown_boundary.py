"""Process-exit snapshot races and guardian handoff; no game is launched."""
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import native, runner, runner_monitor


class ShutdownBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.game = {'pid': 42, 'birth': 102, 'path': 'game/SkyrimSE.exe'}
        self.row = {'pid': 42, 'parent': 7, 'name': 'SkyrimSE.exe'}
        self.system = {'pid': 4, 'parent': 0, 'name': 'System'}
        self.state = {'id': 'shutdown', 'owned': [{'role': 'game', 'identity': self.game}],
                      'snapshots': [], 'checks': [], 'preflight': {'profile': 'fixture'}}
        self.session = runner.Session(self.root, self.state)

    def test_exited_owned_snapshot_row_requires_fresh_complete_inventory_before_action(self):
        observations = iter([[self.system, self.row], [self.system]])
        with patch.object(native, 'processes', side_effect=lambda: next(observations)), \
             patch.object(native, 'identity', return_value=None), \
             patch.object(runner.time, 'sleep'), \
             patch.object(native, 'close') as close, patch.object(native, 'terminate') as terminate:
            self.session.guard_shutdown()
        close.assert_not_called(); terminate.assert_not_called()
        events = [json.loads(x) for x in (self.root/'steps.jsonl').read_text().splitlines()]
        self.assertEqual([e['kind'] for e in events], ['shutdown-identity-pending', 'shutdown-identity-settled'])
        self.assertNotIn('foreignGameShutdownRefused', self.state)

    def test_only_exact_identity_can_resolve_a_still_listed_process(self):
        with patch.object(native, 'processes', return_value=[self.system, self.row]), \
             patch.object(native, 'identity', side_effect=[None, self.game]), patch.object(runner.time, 'sleep'):
            self.session.guard_shutdown()
        self.assertEqual(self.state['owned'], [{'role': 'game', 'identity': self.game}])

    def test_same_pid_reuse_is_refused_after_pending_observation(self):
        foreign = dict(self.game, birth=103)
        with patch.object(native, 'processes', return_value=[self.system, self.row]), \
             patch.object(native, 'identity', side_effect=[None, foreign]), patch.object(runner.time, 'sleep'), \
             patch.object(native, 'close') as close, patch.object(native, 'terminate') as terminate:
            with self.assertRaisesRegex(RuntimeError, 'shared runtime preserved'):
                self.session.guard_shutdown()
        self.assertEqual(self.state['foreignGameShutdownRefused'][0]['identity'], foreign)
        close.assert_not_called(); terminate.assert_not_called()

    def test_unknown_foreign_pid_is_not_given_an_owned_exit_exception(self):
        with patch.object(native, 'processes', return_value=[dict(self.row, pid=999)]), \
             patch.object(native, 'identity', return_value=None), patch.object(runner.time, 'sleep') as sleep:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected session'):
                self.session.guard_shutdown()
        sleep.assert_not_called()

    def test_unknown_owned_pid_stays_blocked_with_finite_observation_bound(self):
        with patch.object(native, 'processes', return_value=[self.system, self.row]) as processes, \
             patch.object(native, 'identity', return_value=None), patch.object(runner.time, 'sleep'), \
             patch.object(runner.time, 'monotonic', return_value=0):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected session'):
                self.session.guard_shutdown()
        self.assertEqual(processes.call_count, 41)
        self.assertIsNone(self.state['foreignGameShutdownRefused'][0]['identity'])

    def test_incomplete_reobservation_never_proves_process_disappearance(self):
        for inventory in ([], None, {}):
            with self.subTest(inventory=inventory), \
                 patch.object(native, 'processes', side_effect=[[self.system, self.row], inventory]), \
                 patch.object(native, 'identity', return_value=None), patch.object(runner.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'inventory unavailable'):
                    self.session.guard_shutdown()

    def test_foreign_process_appearing_while_owned_exit_settles_retains_barrier(self):
        stranger = {'pid': 99, 'birth': 999, 'path': 'foreign/SkyrimVR.exe'}
        with patch.object(native, 'processes', side_effect=[[self.system, self.row],
                           [self.system, {'pid': 99, 'parent': 98, 'name': 'SkyrimVR.exe'}]]), \
             patch.object(native, 'identity', side_effect=[None, stranger]), patch.object(runner.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected session'):
                self.session.guard_shutdown()

    def guardian_fixture(self, current):
        initial = {'id': 'handoff', 'runner': {'pid': 1, 'birth': 100, 'path': 'C:/Python/python.exe'},
                   'game': dict(self.game), 'done': False,
                   'phase': 'stop-and-restore', 'deadline': time.time()+100}
        # A later Session read keeps the same run/process ownership. Tests may
        # override a binding explicitly when exercising a refused handoff.
        current = dict(initial, **current)
        recovered = Mock(); recovered.state = current
        recovered.cleanup.side_effect = lambda: current.update(restored=True)
        return initial, recovered

    def test_guardian_rechecks_completed_state_after_claiming_mutex(self):
        initial, recovered = self.guardian_fixture({'done': True, 'result': 'passed'})
        with patch.object(runner, 'read_json', return_value=initial), \
             patch.object(runner_monitor, 'observed_at', return_value=(time.time(), None)), \
             patch.object(native, 'alive', return_value=False), \
             patch.object(native, 'SessionMutex', return_value=nullcontext()), \
             patch.object(runner, 'Session', return_value=recovered):
            runner.guardian(self.root)
        recovered.cleanup.assert_not_called(); recovered.report.assert_not_called()
        self.assertEqual(recovered.state['result'], 'passed')

    def test_guardian_preserves_original_cleanup_failure_and_records_separate_recovery_trigger(self):
        original = 'cleanup: owned game identity unavailable'
        initial, recovered = self.guardian_fixture({'done': False, 'result': 'failed',
                                                  'reason': original, 'phase': 'stop-and-restore'})
        with patch.object(runner, 'read_json', return_value=initial), \
             patch.object(runner_monitor, 'observed_at', return_value=(time.time(), None)), \
             patch.object(native, 'alive', return_value=False), \
             patch.object(native, 'SessionMutex', return_value=nullcontext()), \
             patch.object(runner, 'Session', return_value=recovered):
            runner.guardian(self.root)
        self.assertEqual(recovered.state['guardianRecovery']['prior']['reason'], original)
        self.assertTrue(recovered.state['reason'].startswith(original+'; '))
        self.assertEqual(recovered.state['result'], 'failed')
        self.assertTrue(recovered.state['done']); recovered.report.assert_called_once()
        self.assertEqual(recovered.state['guardianRecovery']['decision']['action'], 'claim-recovery-mutex')

    def test_guardian_refuses_changed_run_or_process_binding_after_mutex_claim(self):
        for change in ({'id': 'another-run'},
                       {'runner': {'pid': 1, 'birth': 101, 'path': 'C:/Python/python.exe'}},
                       {'game': dict(self.game, birth=103)}):
            with self.subTest(change=change):
                initial, recovered = self.guardian_fixture(dict(done=False, result='failed', **change))
                with patch.object(runner, 'read_json', return_value=initial), \
                     patch.object(runner_monitor, 'observed_at', return_value=(time.time(), None)), \
                     patch.object(native, 'alive', return_value=False), \
                     patch.object(native, 'terminate') as terminate, \
                     patch.object(native, 'SessionMutex', return_value=nullcontext()), \
                     patch.object(runner, 'Session', return_value=recovered):
                    runner.guardian(self.root)
                terminate.assert_not_called()
                recovered.cleanup.assert_not_called()
                recovered.save.assert_not_called()
                recovered.report.assert_not_called()
                self.assertNotIn('guardianRecovery', recovered.state)
                audit = [json.loads(row) for row in (self.root/'guardian-decisions.jsonl').read_text().splitlines()]
                self.assertEqual(audit[-1]['reason'], 'ownership-binding-changed-before-mutex-claim')


if __name__ == '__main__': unittest.main()
