"""Exercise native startup dispatch, not just the generic read retry predicate."""
import json
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from skyrim_autotest import bootstrap, runner, startup_ui
from skyrim_autotest.readiness_reads import ReadinessSession
from tests import test_startup_ui as base


SNAPSHOT = {'action': 'startup', 'startupOperation': 'snapshot'}


def abandoned(frames=90, *, route='api/tool/menu', text=None, code=504):
    return runner.HTTPResponseError(code, route, json.dumps({'code': code, 'error': text or
        f'main-thread task did not start within 5000ms; queued task abandoned ({frames} frames elapsed -- main thread busy)'}))


class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, value): self.now += value


class StartupSession(base.Session):
    def __init__(self, clock, failures):
        super().__init__()
        self.clock, self.failures, self.options = clock, list(failures), []

    def tool(self, name, args, **options):
        self.options.append((dict(args), options))
        failure = self.failures.pop(0) if self.failures else None
        if failure:
            self.calls.append((name, dict(args)))
            self.clock.now += min(5.0, options.get('timeout', 5.0))
            raise failure
        return super().tool(name, args)


class StartupReadinessTests(TestCase):
    def run_start(self, session):
        with ExitStack() as stack:
            stack.enter_context(patch.object(startup_ui.time, 'monotonic', session.clock.monotonic))
            stack.enter_context(patch.object(startup_ui.time, 'sleep', session.clock.sleep))
            def listener(port, route, **options):
                if route == 'api/health' and session.data['state'] == 'MainConfirm':
                    session.clock.now += getattr(session, 'second_baseline_delay', 0)
                return base.StartupUITests.listener(port, route, **options)
            stack.enter_context(patch.object(runner, 'request', side_effect=listener))
            stack.enter_context(patch.object(runner.native, 'alive', return_value=True))
            wait = stack.enter_context(patch.object(bootstrap, 'wait_new_game_transition'))
            startup_ui.start_new_game(session, 'QASmoke')
            return wait

    def operations(self, session): return [args['startupOperation'] for _, args in session.calls]

    def test_both_retained_first_read_errors_recover_without_replaying_mutations(self):
        for frames in (87, 90):
            with self.subTest(frames=frames):
                session = StartupSession(Clock(), [abandoned(frames)])
                wait = self.run_start(session)
                self.assertEqual(self.operations(session),
                    ['snapshot', 'snapshot', 'select-new', 'snapshot', 'confirm-new'])
                self.assertEqual(session.options[0][1], {'timeout': 12, 'deadline': 20})
                self.assertEqual(session.options[1][1], {'timeout': 12, 'deadline': 20})
                self.assertEqual(session.options[2][1], {'timeout': 12, 'deadline': 20})
                self.assertEqual(session.options[3][1]['deadline'], 15.25)
                self.assertEqual(session.options[4][1], {'timeout': 10, 'deadline': 15.25})
                self.assertEqual(len([x for x in session.logs if x[0] == 'common-readiness-abandoned-read']), 1)
                self.assertEqual(wait.call_count, 1)
                self.assertNotIn('newGameStarted', session.state)

    def test_confirmation_read_retries_but_new_selection_happens_once(self):
        session = StartupSession(Clock(), [None, None, abandoned(), None])
        self.run_start(session)
        self.assertEqual(self.operations(session),
            ['snapshot', 'select-new', 'snapshot', 'snapshot', 'confirm-new'])
        self.assertEqual([options['deadline'] for args, options in session.options if args == SNAPSHOT], [20, 10, 10])

    def test_structured_exact_unstarted_snapshot_uses_same_bounded_policy(self):
        error = runner.ToolError('menu', dict(SNAPSHOT), {'ok': False, 'outcome': 'abandoned_before_start'})
        session = StartupSession(Clock(), [error])
        self.run_start(session)
        self.assertEqual(self.operations(session), ['snapshot', 'snapshot', 'select-new', 'snapshot', 'confirm-new'])

    def test_structured_started_mismatched_or_success_claim_cannot_retry(self):
        cases = [runner.ToolError('menu', dict(SNAPSHOT), {'ok': False, 'outcome': 'read_started_result_unavailable'}),
                 runner.ToolError('inspect', dict(SNAPSHOT), {'ok': False, 'outcome': 'abandoned_before_start'}),
                 runner.ToolError('menu', {'action': 'startup', 'startupOperation': 'select-new'}, {'ok': False, 'outcome': 'abandoned_before_start'}),
                 runner.ToolError('menu', dict(SNAPSHOT), {'ok': True, 'outcome': 'abandoned_before_start'})]
        for error in cases:
            with self.subTest(error=error):
                session = StartupSession(Clock(), [error])
                with self.assertRaises(runner.ToolError): self.run_start(session)
                self.assertEqual(self.operations(session), ['snapshot'])

    def test_persistent_unstarted_reads_exhaust_original_twenty_seconds_without_new(self):
        session = StartupSession(Clock(), [abandoned()] * 10)
        with self.assertRaisesRegex(TimeoutError, 'read deadline exhausted'): self.run_start(session)
        self.assertEqual(session.clock.now, 20)
        self.assertEqual(self.operations(session), ['snapshot'] * 4)
        self.assertEqual([options['deadline'] for _, options in session.options], [20] * 4)
        self.assertEqual([options['timeout'] for _, options in session.options], [12, 12, 9.5, 4.25])

    def test_persistent_confirmation_reads_never_repeat_selection_or_confirm(self):
        session = StartupSession(Clock(), [None, None] + [abandoned()] * 5)
        with self.assertRaises(TimeoutError): self.run_start(session)
        self.assertEqual(session.clock.now, 10)
        self.assertEqual(self.operations(session), ['snapshot', 'select-new', 'snapshot', 'snapshot'])

    def test_started_unknown_route_transport_and_unrecognised504_remain_terminal(self):
        cases = [abandoned(text='main-thread task did not finish within 5000ms; it already started and may still complete'),
                 abandoned(text='gateway timeout'), abandoned(route='api/tool/inspect'), abandoned(code=503),
                 runner.HTTPResponseError(504, 'api/tool/menu', 'not JSON'),
                 runner.HTTPResponseError(504, 'api/tool/menu', '[]'),
                 runner.HTTPResponseError(504, 'api/tool/menu', '{"code":"504","error":"abandoned_before_start"}'),
                 abandoned(text='main-thread task did not start within 5000ms; queued task abandoned and the game frame counter has not advanced -- main thread hung or the game is fully paused; if no pause menu is open, only a process restart recovers'),
                 ConnectionResetError('receipt lost'), TimeoutError('HTTP read uncertain')]
        for error in cases:
            with self.subTest(error=error):
                session = StartupSession(Clock(), [error])
                with self.assertRaises(type(error)): self.run_start(session)
                self.assertEqual(self.operations(session), ['snapshot'])
                self.assertFalse(any(x[0] == 'common-readiness-abandoned-read' for x in session.logs))

    def test_explicit_unstarted_select_and_confirm_errors_never_replayed(self):
        for prior in ([None], [None, None, None]):
            with self.subTest(prior=len(prior)):
                session = StartupSession(Clock(), prior + [abandoned()])
                with self.assertRaises(runner.HTTPResponseError): self.run_start(session)
                operations = self.operations(session)
                self.assertEqual(operations.count('select-new'), 1)
                self.assertEqual(operations.count('confirm-new'), int(len(prior) == 3))
                self.assertEqual(len(operations), len(prior) + 1)

    def test_successful_response_after_original_deadline_cannot_start_new(self):
        session = StartupSession(Clock(), [])
        original = session.tool
        def late(*args, **options):
            value = original(*args, **options)
            session.clock.now = 20
            return value
        session.tool = late
        with self.assertRaisesRegex(TimeoutError, 'response arrived after deadline'): self.run_start(session)
        self.assertEqual(self.operations(session), ['snapshot'])

    def test_listener_cannot_refresh_expired_confirmation_stage_after_read_recovery(self):
        session = StartupSession(Clock(), [None, None, abandoned(), None])
        session.second_baseline_delay = 5
        with self.assertRaisesRegex(TimeoutError, 'stage deadline exhausted'): self.run_start(session)
        self.assertEqual(session.clock.now, 10.25)
        self.assertEqual(self.operations(session), ['snapshot', 'select-new', 'snapshot', 'snapshot'])

    def test_slow_preselection_logging_cannot_start_new_after_original_stage(self):
        session = StartupSession(Clock(), [abandoned()])
        original = session.log
        def log(name, **fields):
            original(name, **fields)
            if name == 'new-game-native-menu': session.clock.now = 20
        session.log = log
        with self.assertRaisesRegex(TimeoutError, 'stage deadline exhausted'): self.run_start(session)
        self.assertEqual(self.operations(session), ['snapshot', 'snapshot'])

    def test_late_selection_receipt_is_logged_but_never_followed_by_confirmation(self):
        session = StartupSession(Clock(), [])
        original = session.tool
        def late(name, args, **options):
            value = original(name, args, **options)
            if args.get('startupOperation') == 'select-new': session.clock.now = 20
            return value
        session.tool = late
        with self.assertRaisesRegex(TimeoutError, 'invocation returned after original stage deadline'): self.run_start(session)
        self.assertEqual(self.operations(session), ['snapshot', 'select-new'])
        self.assertEqual(len([entry for entry in session.logs if entry[0] == 'startup-ui-invocation']), 1)

    def test_real_session_health_delay_prevents_dispatch_after_original_stage(self):
        clock, routes = Clock(), []
        session = SimpleNamespace(state={'phase': 'gameplay-new-game-menu', 'port': 99, 'game': {'pid': 12}},
            heartbeat_failed=SimpleNamespace(is_set=lambda: False), log=lambda *args, **kwargs: None)
        session.tool = lambda *args, **kwargs: runner.Session.tool(session, *args, **kwargs)
        def request(port, route, **options):
            routes.append(route)
            self.assertEqual(route, 'api/health')
            clock.now = 20
            return {'pid': 12}
        with patch.object(startup_ui.time, 'monotonic', clock.monotonic), \
             patch.object(runner, 'request', side_effect=request), \
             patch.object(runner.native, 'alive', return_value=True), \
             self.assertRaises(TimeoutError):
            startup_ui.mutate(session, 'select-new', 20)
        self.assertEqual(routes, ['api/health'])

    def test_snapshot_with_extra_operation_fields_is_not_retryable(self):
        session = StartupSession(Clock(), [abandoned()])
        with patch.object(startup_ui.time, 'monotonic', session.clock.monotonic), self.assertRaises(runner.HTTPResponseError):
            ReadinessSession(session, 20).tool('menu', {**SNAPSHOT, 'name': 'other'})
        self.assertEqual(len(session.calls), 1)

    def test_retry_does_not_mask_changed_ownership_or_wrong_native_menu(self):
        for invalid in (runner.Blocked('DevBench identity no longer matches the owned game'), None):
            with self.subTest(invalid=invalid):
                session = StartupSession(Clock(), [abandoned(), invalid])
                if invalid is None: session.data['contract'] = 'foreign'
                with self.assertRaises(type(invalid) if invalid else ValueError): self.run_start(session)
                self.assertEqual(self.operations(session), ['snapshot', 'snapshot'])

    def test_successful_unsettled_reads_share_deadline_and_stop_before_mutation(self):
        session = StartupSession(Clock(), [abandoned()])
        session.data['state'] = 'MainStartAnim'
        with self.assertRaises(TimeoutError): self.run_start(session)
        self.assertEqual(session.clock.now, 20)
        self.assertEqual(set(self.operations(session)), {'snapshot'})
        self.assertEqual(set(options['deadline'] for _, options in session.options), {20})
