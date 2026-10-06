"""Readiness failures must not repeat mutations, hide errors or reset deadlines."""
import io
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from skyrim_autotest import runner, vr_probe


class Clock:
    def __init__(self):
        self.now = 0
    def monotonic(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Session:
    def __init__(self, clock, replies):
        self.clock = clock
        self.replies = iter(replies)
        self.calls, self.logs = [], []
    def tool(self, name, args, **kwargs):
        if name == 'menu':
            return {'messageBoxOpen': False, 'openMenus': ['HUD Menu']}
        self.calls.append((name, args, kwargs))
        reply = next(self.replies, {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}})
        if callable(reply):
            reply = reply()
        if isinstance(reply, Exception):
            raise reply
        return reply
    def log(self, kind, **details):
        self.logs.append((kind, details))


class SceneReadinessTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.time_patch = patch.object(vr_probe.time, 'monotonic', self.clock.monotonic)
        self.sleep_patch = patch.object(vr_probe.time, 'sleep', self.clock.sleep)
        self.time_patch.start()
        self.sleep_patch.start()
        self.addCleanup(self.time_patch.stop)
        self.addCleanup(self.sleep_patch.stop)

    def test_candidate_http_failures_then_stable_scene_preserve_each_body(self):
        errors = [runner.HTTPResponseError(code, 'api/tool/inspect', 'details-' + str(code))
                  for code in (500, 502, 503, 504)]
        session = Session(self.clock, errors)
        self.assertEqual(vr_probe.wait_test_cell(session, 'QASmoke'),
                         {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}})
        retries = [data for kind, data in session.logs if kind == 'bootstrap-scene-retry']
        self.assertEqual([data['status'] for data in retries], [500, 502, 503, 504])
        self.assertEqual(retries[0]['body'], 'details-500')
        self.assertEqual(session.logs[-1][1]['retries'], 4)
        self.assertTrue(all(name == 'inspect' and args == {'kind': 'scene'}
                            and options['deadline'] == 90 for name, args, options in session.calls))

    def test_persistent_500_stops_after_three_reads_without_false_success(self):
        error = runner.HTTPResponseError(500, 'api/tool/inspect', '')
        session = Session(self.clock, [error] * 100)
        with self.assertRaises(runner.HTTPResponseError):
            vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(self.clock.now, 2)
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(session.logs[-1][1]['reason'], 'persistent-server-error')
        self.assertFalse(any(kind == 'bootstrap-scene-ready' for kind, _ in session.logs))

    def test_error_or_wrong_cell_resets_continuous_stability(self):
        for interruption in (runner.HTTPResponseError(500, 'api/tool/inspect', ''),
                             {'playerLoaded': True, 'cell': {'editorId': 'OtherCell'}}):
            with self.subTest(interruption=interruption):
                self.clock.now = 0
                session = Session(self.clock, [{'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}] * 4 + [interruption])
                vr_probe.wait_test_cell(session, 'QASmoke')
                self.assertEqual(self.clock.now, 10)

    def test_matching_text_only_in_error_is_not_readiness(self):
        session = Session(self.clock, [runner.HTTPResponseError(500, 'api/tool/inspect', 'QASmoke')] * 100)
        with self.assertRaises(runner.HTTPResponseError):
            vr_probe.wait_test_cell(session, 'QASmoke')

    def test_wrong_cell_until_deadline_never_passes(self):
        session = Session(self.clock, [{'playerLoaded': True, 'cell': {'editorId': 'OtherCell'}}] * 100)
        with self.assertRaises(AssertionError):
            vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(self.clock.now, 90)

    def test_unknown_health_client_transport_and_started_errors_are_terminal(self):
        errors = [runner.Blocked('identity mismatch'),
                  runner.HTTPResponseError(500, 'api/health', 'not scene'),
                  runner.HTTPResponseError(400, 'api/tool/inspect', 'invalid args'),
                  RuntimeError('HTTP 500 api/tool/inspect: untyped'),
                  ConnectionError('transport lost'), ValueError('malformed JSON'),
                  runner.ToolError('inspect', {'kind': 'scene'},
                                   {'ok': False, 'error': 'busy', 'outcome': 'read_started_result_unavailable'})]
        for error in errors:
            with self.subTest(error=str(error)):
                session = Session(self.clock, [error])
                with self.assertRaises(type(error)):
                    vr_probe.wait_test_cell(session, 'QASmoke')
                self.assertEqual(len(session.calls), 1)

    def test_only_structured_not_started_scene_read_is_retryable(self):
        error = runner.ToolError('inspect', {'kind': 'scene'},
                                 {'ok': False, 'error': 'busy', 'outcome': 'abandoned_before_start'})
        session = Session(self.clock, [error])
        vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(session.logs[0][1]['result'], error.result)
        other_read = runner.ToolError('inspect', {'kind': 'state'}, error.result)
        with self.assertRaises(runner.ToolError):
            vr_probe.wait_test_cell(Session(self.clock, [other_read]), 'QASmoke')

    def test_late_success_never_passes(self):
        def late_scene():
            self.clock.now = 91
            return {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}
        session = Session(self.clock, [late_scene])
        with self.assertRaisesRegex(TimeoutError, 'after readiness deadline'):
            vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(session.logs[-1][1]['reason'], 'response-after-deadline')

    def test_bootstrap_retry_does_not_repeat_load_or_coc(self):
        clock = self.clock
        class FixtureSession(Session):
            def __init__(self):
                super().__init__(clock, [runner.HTTPResponseError(500, 'api/tool/inspect', '')])
                self.state = {'port': 1, 'checks': []}
                self.mutations = []
            def phase(self, *args): pass
            def save(self): pass
            def tool(self, name, args, **options):
                if name == 'inspect' and args['kind'] == 'scene':
                    return super().tool(name, args, **options)
                if name == 'inspect': return {'frame': 100}
                if name == 'menu': return {'messageBoxOpen': False}
                self.mutations.append((name, args))
                return {'queued': True}
        session = FixtureSession()
        lifecycle = {'events': [{'topic': 'lifecycle', 'event': 'postLoadGame', 'frame': 101}]}
        with patch.object(runner, 'request', return_value=lifecycle), \
             patch.object(vr_probe, 'ensure_owned_focus', side_effect=runner.Blocked('stop after readiness')):
            with self.assertRaisesRegex(runner.Blocked, 'stop after readiness'):
                vr_probe.execute(session, {'fixture': {'saveStem': 'pinned'}, 'cell': 'QASmoke'})
        self.assertEqual(session.mutations, [('game', {'action': 'load', 'name': 'pinned'}),
                                             ('console', {'action': 'exec', 'command': 'coc QASmoke'})])
        self.assertEqual(session.state['checks'][0]['name'], 'test cell loaded')

    def test_http_exception_keeps_status_route_and_exact_body(self):
        error = urllib.error.HTTPError('http://127.0.0.1:1', 500, 'server failure', {},
                                       io.BytesIO(b'{"error":"busy"}'))
        with patch.object(runner.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(runner.HTTPResponseError) as raised:
                runner.request(1, 'api/tool/inspect', {'kind': 'scene'})
        self.assertEqual((raised.exception.status, raised.exception.route, raised.exception.body),
                         (500, 'api/tool/inspect', '{"error":"busy"}'))

    def test_owned_health_is_checked_on_each_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            session = runner.Session(directory, {'port': 1, 'game': {'pid': 42}})
            replies = [{'pid': 42}, {'messageBoxOpen': False}, {'pid': 42},
                       runner.HTTPResponseError(500, 'api/tool/inspect', ''), {'pid': 99}]
            with patch.object(runner, 'request', side_effect=replies) as request, \
                 patch.object(runner.native, 'alive', return_value=True):
                with self.assertRaisesRegex(runner.Blocked, 'identity'):
                    vr_probe.wait_test_cell(session, 'QASmoke')
            self.assertEqual([call.args[1] for call in request.call_args_list],
                             ['api/health', 'api/tool/menu', 'api/health', 'api/tool/inspect', 'api/health'])
            self.assertIn('bootstrap-scene-retry', (Path(directory) / 'steps.jsonl').read_text())

    def test_actual_utf8_serialization_error_is_terminal_after_one_read(self):
        error = runner.HTTPResponseError(500, 'api/tool/inspect',
            '[json.exception.type_error.316] incomplete UTF-8 string; last byte: 0xC7')
        session = Session(self.clock, [error])
        with self.assertRaises(runner.HTTPResponseError):
            vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(self.clock.now, 0)
        self.assertEqual(session.logs[-1][1]['reason'], 'provider-text-serialization')

    def test_cell_name_in_unrelated_text_and_no_player_3d_cannot_pass(self):
        for scene in ({'playerLoaded': True, 'cell': {'editorId': 'Other'}, 'note': 'QASmoke'},
                      {'playerLoaded': False, 'cell': {'editorId': 'QASmoke'}},
                      {'playerLoaded': True, 'cell': {'editorId': 'QASmokeExtended'}}):
            self.clock.now = 0
            with self.subTest(scene=scene), self.assertRaises(AssertionError):
                vr_probe.wait_test_cell(Session(self.clock, [scene] * 100), 'QASmoke')

    def test_late_known_modal_during_cell_wait_is_handled_before_scene_stability(self):
        clock = self.clock
        class LateSession(Session):
            def __init__(self):
                super().__init__(clock, [])
                self.open = False
                self.menu_reads = 0
            def tool(self, name, args, **options):
                if name == 'menu':
                    self.menu_reads += 1
                    if self.menu_reads == 3: self.open = True
                    return {'messageBoxOpen': self.open}
                return super().tool(name, args, **options)
        session = LateSession()
        def clear(actual):
            self.assertIs(actual, session)
            session.open = False
        with patch.object(vr_probe, 'guard_fixture_modal', side_effect=clear) as guard:
            vr_probe.wait_test_cell(session, 'QASmoke')
        self.assertEqual(guard.call_count, 1)
        self.assertEqual(self.clock.now, 7)

    def test_unknown_modal_prevents_scene_and_subject_actions(self):
        class Unknown(Session):
            def tool(self, name, args, **options):
                if name == 'menu' and args['action'] == 'list':
                    return {'messageBoxOpen': True}
                if name == 'menu':
                    return {'bodyText': 'Unknown choice', 'buttons': ['Yes', 'No']}
                raise AssertionError('No scene or mutations may follow unknown modal')
        session = Unknown(self.clock, [])
        with self.assertRaisesRegex(AssertionError, 'unclassified modal'):
            vr_probe.wait_test_cell(session, 'QASmoke')

    def test_encoding_diagnostics_do_not_hide_unavailable_cell_identity(self):
        good = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke', 'name': None},
                'textEncodingDiagnostics': {'invalidStringCount': 1}}
        session = Session(self.clock, [good] * 20)
        self.assertEqual(vr_probe.wait_test_cell(session, 'QASmoke'), good)
        self.clock.now = 0
        bad = {**good, 'cell': {'editorId': None, 'name': 'QASmoke'}}
        with self.assertRaises(AssertionError):
            vr_probe.wait_test_cell(Session(self.clock, [bad] * 100), 'QASmoke')

    def test_deadline_accounts_for_health_and_does_not_start_late_scene_read(self):
        for health_duration in (2.5, 3):
            with self.subTest(health_duration=health_duration), tempfile.TemporaryDirectory() as directory:
                self.clock.now = 0
                session = runner.Session(directory, {'port': 1, 'game': {'pid': 42}})
                def request(port, route, *args, **options):
                    if route == 'api/health':
                        self.clock.now += health_duration
                        return {'pid': 42}
                    self.assertEqual(options['timeout'], .5)
                    return {'cell': 'QASmoke'}
                with patch.object(runner, 'request', side_effect=request) as mocked, \
                     patch.object(runner.native, 'alive', return_value=True):
                    if health_duration == 3:
                        with self.assertRaises(TimeoutError):
                            session.tool('inspect', {'kind': 'scene'}, deadline=3)
                        self.assertEqual(mocked.call_count, 1)
                    else:
                        session.tool('inspect', {'kind': 'scene'}, deadline=3)
                        self.assertEqual(mocked.call_count, 2)


if __name__ == '__main__':
    unittest.main()
