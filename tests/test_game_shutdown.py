"""Owned exit grace and truthful telemetry classification without OS actions."""
import copy
from contextlib import ExitStack
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import game_shutdown as shutdown


GAME = {'pid': 42, 'birth': 1234, 'path': 'D:/Game/SkyrimSE.exe'}


class Clock:
    def __init__(self): self.now, self.sleeps = 0., []
    def monotonic(self): return self.now
    def sleep(self, seconds): self.sleeps.append(seconds); self.now += seconds


class Session:
    def __init__(self):
        self.state = {'game': copy.deepcopy(GAME), 'owned': [{'role': 'game', 'identity': copy.deepcopy(GAME)}],
                      'checks': [{'name': 'gameplay', 'result': 'passed'}]}
        self.saved, self.events = [], []
        self.guard_shutdown = Mock()
        self.tool = Mock(side_effect=self.request)
        self.observe_game_exit = Mock(side_effect=self.observe)
    def save(self): self.saved.append(copy.deepcopy(self.state))
    def log(self, event, **fields): self.events.append((event, fields))
    def request(self, tool, args, **kwargs):
        assert self.saved[-1]['gracefulGameExit']['status'] == 'request-intent'
        return {'queued': True}
    def observe(self, stage, *, status=None):
        running = shutdown.native.alive(self.state['game']) if status is None else status == 'running'
        self.state.setdefault('gameProcessObservations', []).append({
            'identity': copy.deepcopy(self.state['game']), 'expectedIdentity': copy.deepcopy(self.state['game']),
            'identityVerified': True, 'handleRetained': True, 'stage': stage,
            'status': status or ('running' if running else 'exited'),
            'exitCodeAvailable': not running and status != 'unavailable',
            'exitCode': 0 if not running and status != 'unavailable' else None})


class GraceTests(unittest.TestCase):
    def setUp(self):
        self.session, self.clock, self.stack = Session(), Clock(), ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(shutdown.time, 'monotonic', self.clock.monotonic))
        self.stack.enter_context(patch.object(shutdown.time, 'sleep', self.clock.sleep))
        self.identity = self.stack.enter_context(patch.object(shutdown.native, 'identity', return_value=copy.deepcopy(GAME)))
        self.alive = self.stack.enter_context(patch.object(shutdown.native, 'alive', return_value=True))
        self.close = self.stack.enter_context(patch.object(shutdown.native, 'close'))
        self.terminate = self.stack.enter_context(patch.object(shutdown.native, 'terminate'))
        self.addCleanup(self.assert_no_native_actions)
    def assert_no_native_actions(self):
        self.close.assert_not_called(); self.terminate.assert_not_called()
    def gone_after(self, seconds):
        self.alive.side_effect = lambda game: self.clock.now < seconds
        self.identity.side_effect = lambda pid: copy.deepcopy(GAME) if self.clock.now < seconds else None
    def test_success_waits_for_actual_owned_exit_before_any_fallback(self):
        self.gone_after(.6)
        self.assertTrue(shutdown.request_and_wait(self.session))
        self.assertGreaterEqual(self.clock.now, .6)
        self.session.tool.assert_called_once_with('console', {'action': 'exec', 'command': 'qqq'}, timeout=4, deadline=10.)
        record = self.session.state['gracefulGameExit']
        self.assertTrue(record['observedGone']); self.assertTrue(record['requestAttempted'])
        self.assertEqual(record['deadlineMonotonic'], 10.)
        self.assertEqual(self.session.state['checks'], [{'name': 'gameplay', 'result': 'passed'}])
        self.assertEqual([event for event, _ in self.session.events],
                         ['graceful-game-exit-request', 'graceful-game-exit-wait-finished'])
        self.assertTrue(all(0 < duration <= .2 for duration in self.clock.sleeps))
        self.session.observe_game_exit.assert_called_once_with('graceful-game-exit-observed')
    def test_false_return_only_after_original_deadline_and_recovery_never_renews(self):
        self.assertFalse(shutdown.request_and_wait(self.session, seconds=1))
        self.assertAlmostEqual(self.clock.now, 1)
        sleeps = list(self.clock.sleeps)
        self.assertFalse(shutdown.request_and_wait(self.session, seconds=30))
        self.assertEqual(self.clock.sleeps, sleeps)
        self.assertEqual(self.session.state['gracefulGameExit']['deadlineMonotonic'], 1.)
        self.assertEqual(self.session.tool.call_count, 1)
    def test_uncertain_request_still_gets_original_grace_and_is_never_replayed(self):
        self.session.tool.side_effect = OSError('unknown qqq response')
        self.gone_after(.8)
        self.assertTrue(shutdown.request_and_wait(self.session, seconds=2))
        record = self.session.state['gracefulGameExit']
        self.assertEqual(record['requestError']['message'], 'unknown qqq response')
        self.assertEqual(record['deadlineMonotonic'], 2.)
        self.assertTrue(shutdown.request_and_wait(self.session, seconds=10))
        self.assertEqual(self.session.tool.call_count, 1)
        self.assertGreaterEqual(self.clock.now, .8)
    def test_recovery_with_intent_before_callback_does_not_dispatch(self):
        self.session.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq',
            'status': 'request-intent', 'startedMonotonic': 0., 'deadlineMonotonic': .4,
            'requestAttempted': False}
        self.assertFalse(shutdown.request_and_wait(self.session))
        self.session.tool.assert_not_called()
        self.assertAlmostEqual(self.clock.now, .4)
    def test_dead_prior_boot_identity_is_noop_without_new_deadline(self):
        self.alive.return_value = False; self.identity.return_value = None
        self.session.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq',
            'startedMonotonic': 500000., 'deadlineMonotonic': 500010., 'requestAttempted': True}
        self.assertTrue(shutdown.request_and_wait(self.session))
        self.assertEqual(self.clock.now, 0.)
        self.assertEqual(self.session.state['gracefulGameExit']['deadlineMonotonic'], 500010.)
        self.session.tool.assert_not_called()
    def test_already_dead_without_intent_never_creates_one(self):
        self.alive.return_value = False; self.identity.return_value = None
        self.assertTrue(shutdown.request_and_wait(self.session))
        self.assertNotIn('gracefulGameExit', self.session.state)
        self.session.tool.assert_not_called()
    def test_changed_pid_identity_is_denial_not_disappearance(self):
        self.identity.return_value = dict(GAME, birth=GAME['birth'] + 1)
        self.alive.return_value = False
        with self.assertRaisesRegex(RuntimeError, 'different process'): shutdown.request_and_wait(self.session)
        self.session.tool.assert_not_called()
    def test_changed_session_game_during_guard_is_denied_before_input(self):
        self.session.guard_shutdown.side_effect = lambda: self.session.state['game'].update(birth=9999)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'): shutdown.request_and_wait(self.session)
        self.session.tool.assert_not_called()
    def test_before_request_foreign_shutdown_barrier_still_refuses_input(self):
        self.session.guard_shutdown.side_effect = RuntimeError('foreign game blocks mutation')
        with self.assertRaisesRegex(RuntimeError, 'foreign game'): shutdown.request_and_wait(self.session)
        self.session.tool.assert_not_called()
        self.session.observe_game_exit.assert_not_called()
    def test_readonly_wait_ignores_transient_foreign_barrier_and_captures_live_exit(self):
        self.gone_after(.6)
        original_request = self.session.request
        def request(*args, **kwargs):
            result = original_request(*args, **kwargs)
            # Simulate an unknown ephemeral Skyrim process row after our qqq.
            # Such a row must still block the caller's next process mutation,
            # but cannot interrupt read-only observation of this exact game.
            self.session.guard_shutdown.side_effect = RuntimeError('unidentified child snapshot row')
            return result
        self.session.tool.side_effect = request
        observed = []
        def capture(stage):
            observed.append((stage, self.clock.now)); self.session.observe(stage)
        self.session.observe_game_exit.side_effect = capture
        self.assertTrue(shutdown.request_and_wait(self.session))
        self.assertEqual(self.session.guard_shutdown.call_count, 2)
        self.assertEqual([stage for stage, _ in observed], ['graceful-game-exit-observed'])
        self.assertAlmostEqual(observed[0][1], .6)
        with self.assertRaisesRegex(RuntimeError, 'unidentified child'): self.session.guard_shutdown()
        self.assertEqual(self.session.tool.call_count, 1)
    def test_recovery_wait_never_calls_mutation_barrier_or_renews_deadline(self):
        self.session.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq',
            'status': 'waiting', 'startedMonotonic': 0., 'deadlineMonotonic': .4,
            'requestAttempted': True}
        self.session.guard_shutdown.side_effect = RuntimeError('unknown process blocks mutations only')
        self.gone_after(.2)
        self.assertTrue(shutdown.request_and_wait(self.session, seconds=30))
        self.session.guard_shutdown.assert_not_called(); self.session.tool.assert_not_called()
        self.assertEqual(self.session.state['gracefulGameExit']['deadlineMonotonic'], .4)
        self.session.observe_game_exit.assert_called_once_with('graceful-game-exit-observed')
    def test_exit_capture_precedes_persistence_or_caller_failure(self):
        self.gone_after(.2)
        captured = []
        def capture(stage):
            captured.append(stage); self.session.observe(stage)
        self.session.observe_game_exit.side_effect = capture
        original_save = self.session.save
        def save():
            if self.clock.now >= .2: raise OSError('later persistence failure')
            original_save()
        self.session.save = save
        with self.assertRaisesRegex(OSError, 'persistence failure'): shutdown.request_and_wait(self.session)
        self.assertEqual(captured, ['graceful-game-exit-observed'])
    def test_unavailable_live_identity_waits_for_retained_running_then_actual_exit(self):
        def request(*args, **kwargs):
            response = self.session.request(*args, **kwargs)
            self.alive.return_value = False; self.identity.return_value = None
            return response
        self.session.tool.side_effect = request
        statuses = iter(['running', 'exited'])
        snapshots = []
        def capture(stage):
            status = next(statuses); snapshots.append((status, self.clock.now))
            self.session.observe(stage, status=status)
        self.session.observe_game_exit.side_effect = capture
        self.assertTrue(shutdown.request_and_wait(self.session, seconds=1))
        self.assertEqual(snapshots[0], ('running', 0.))
        self.assertEqual(snapshots[1], ('exited', .2))
        self.assertEqual(self.session.state['gracefulGameExit']['deadlineMonotonic'], 1.)
        self.assertEqual(self.session.tool.call_count, 1)
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'normal_close')
    def test_unavailable_retained_telemetry_cannot_prove_exit_or_extend_grace(self):
        def request(*args, **kwargs):
            response = self.session.request(*args, **kwargs)
            self.alive.return_value = False; self.identity.return_value = None
            return response
        self.session.tool.side_effect = request
        self.session.observe_game_exit.side_effect = lambda stage: self.session.observe(stage, status='unavailable')
        self.assertFalse(shutdown.request_and_wait(self.session, seconds=.4))
        self.assertAlmostEqual(self.clock.now, .4)
        self.assertFalse(self.session.state['gracefulGameExit']['observedGone'])
        self.assertEqual(self.session.state['gracefulGameExit']['deadlineMonotonic'], .4)
        self.assertFalse(shutdown.request_and_wait(self.session, seconds=10))
        self.assertAlmostEqual(self.clock.now, .4)
        self.assertEqual(self.session.tool.call_count, 1)
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'unknown')
    def test_identity_change_while_waiting_never_sends_another_quit(self):
        def sleep(seconds):
            self.clock.sleep(seconds)
            self.session.state['game'] = dict(GAME, birth=9999)
        with patch.object(shutdown.time, 'sleep', sleep):
            with self.assertRaisesRegex(RuntimeError, 'identity changed'): shutdown.request_and_wait(self.session)
        self.assertEqual(self.session.tool.call_count, 1)
    def test_no_owned_game_or_mismatching_prior_intent_refuses(self):
        self.session.state['owned'] = []
        with self.assertRaisesRegex(RuntimeError, 'exact owned game'): shutdown.request_and_wait(self.session)
        self.session.state['owned'] = [{'role': 'game', 'identity': copy.deepcopy(GAME)}]
        self.session.state['gracefulGameExit'] = {'game': dict(GAME, birth=9999)}
        with self.assertRaisesRegex(RuntimeError, 'another game'): shutdown.request_and_wait(self.session)
        self.session.tool.assert_not_called()
    def test_malformed_original_deadline_never_causes_replay(self):
        self.session.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq',
                                                 'startedMonotonic': 0., 'deadlineMonotonic': float('nan')}
        with self.assertRaisesRegex(RuntimeError, 'deadline is unavailable'): shutdown.request_and_wait(self.session)
        self.session.tool.assert_not_called()


class ClassificationTests(unittest.TestCase):
    def setUp(self): self.session = Session()
    def observation(self, code, **fields):
        return {'identity': copy.deepcopy(GAME), 'expectedIdentity': copy.deepcopy(GAME),
                'identityVerified': True, 'status': 'exited', 'exitCodeAvailable': True,
                'exitCode': code, 'stage': 'cleanup-finally', **fields}
    def quit_request(self):
        self.session.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq', 'requestAttempted': True}
    def test_normal_requires_zero_actual_code_and_owned_quit_request(self):
        self.session.state['gameProcessObservations'] = [self.observation(0)]
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'unknown')
        self.quit_request()
        result = shutdown.classify_exit(self.session)
        self.assertEqual(result['kind'], 'normal_close'); self.assertEqual(result['exitCodeHex'], '0x00000000')
    def test_nonzero_is_abnormal_even_when_all_gameplay_checks_pass(self):
        self.quit_request(); self.session.state['gameProcessObservations'] = [self.observation(0xC0000409)]
        result = shutdown.classify_exit(self.session)
        self.assertEqual(result['kind'], 'abnormal_exit'); self.assertEqual(result['exitCode'], 0xC0000409)
        self.assertEqual(result['exitCodeHex'], '0xC0000409')
        self.assertEqual(self.session.state['checks'], [{'name': 'gameplay', 'result': 'passed'}])
    def test_forced_stop_dominates_zero_code_and_missing_telemetry(self):
        self.quit_request(); self.session.state['forcedGameStop'] = True
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'forced_stop')
        self.session.state['gameProcessObservations'] = [self.observation(0)]
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'forced_stop')
    def test_only_latest_exact_identity_verified_observation_is_used(self):
        self.quit_request()
        self.session.state['gameProcessObservations'] = [self.observation(7),
            self.observation(0, identity=dict(GAME, birth=9999)), self.observation(0, identityVerified=False)]
        self.assertEqual(shutdown.classify_exit(self.session)['exitCode'], 7)
        self.session.state['gameProcessObservations'].append(self.observation(None, status='unavailable', exitCodeAvailable=False))
        result = shutdown.classify_exit(self.session)
        self.assertEqual(result['kind'], 'unknown'); self.assertIsNone(result['exitCode'])
    def test_intent_without_actual_request_and_foreign_quit_never_prove_normal(self):
        self.session.state['gameProcessObservations'] = [self.observation(0)]
        for row in ({'game': GAME, 'command': 'qqq', 'requestAttempted': False},
                    {'game': dict(GAME, birth=9999), 'command': 'qqq', 'requestAttempted': True}):
            self.session.state['gracefulGameExit'] = row
            self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'unknown')
    def test_running_259_and_malformed_codes_are_never_normal(self):
        self.quit_request()
        for row in (self.observation(0, status='running'), self.observation(False),
                    self.observation(0, exitCodeAvailable=False), self.observation(-1)):
            self.session.state['gameProcessObservations'] = [row]
            self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'unknown')
        self.session.state['gameProcessObservations'] = [self.observation(259)]
        self.assertEqual(shutdown.classify_exit(self.session)['kind'], 'abnormal_exit')


if __name__ == '__main__': unittest.main()
