"""Runner exit telemetry integration; no process, game or network is started."""
from contextlib import ExitStack, contextmanager
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import editions, native, process_exit, runner, se_startup


class RunnerProcessExitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.game = {'pid': 771, 'birth': 134000000000000001,
                     'path': str(self.directory / 'SkyrimSE.exe')}
        state = {'id': 'exit-integration', 'snapshots': [], 'owned': [],
                 'launchIntents': {}, 'checks': [], 'preflight': {'profile': 'Fixture'}}
        # Session construction must not inspect any real process or recover a
        # different runtime. All following process boundaries are mocked too.
        with patch.object(native, 'alive', return_value=True):
            self.session = runner.Session(self.directory, state)
        self.addCleanup(self.session.close_game_exit_tracker)
        self.original = self.directory / 'owned-settings.ini'
        self.original.write_bytes(b'original configuration\r\n')

    def tracker(self, identity=None, status='running', code=None):
        identity = copy.deepcopy(identity or self.game)
        tracker = Mock()
        tracker.status, tracker.code = status, code

        def snapshot():
            exited = tracker.status == 'exited'
            return {'schemaVersion': 1, 'status': tracker.status,
                    'identityVerified': True, 'identity': copy.deepcopy(identity),
                    'expectedIdentity': copy.deepcopy(identity),
                    'capturedAtUtc': '2026-10-26T12:00:00.000Z',
                    'observedAtUtc': '2026-10-26T12:00:01.000Z',
                    'firstExitObservedAtUtc': '2026-10-26T12:00:01.000Z' if exited else None,
                    'exitCode': tracker.code if exited else None,
                    'exitCodeHex': f'0x{tracker.code:08X}' if exited and tracker.code is not None else None,
                    'exitCodeAvailable': exited and tracker.code is not None,
                    'handleRetained': True, 'diagnostic': None}

        tracker.snapshot.side_effect = snapshot
        tracker.close.return_value = {'closed': True, 'closeAttempted': True,
                                      'closeConfirmed': True, 'diagnostic': None}
        return tracker

    def attach(self, tracker):
        self.session.state['game'] = copy.deepcopy(self.game)
        self.session.state['owned'] = [{'role': 'game', 'identity': copy.deepcopy(self.game)}]
        with patch.object(process_exit, 'capture', return_value=tracker) as capture:
            self.session.observe_game_exit('matching-game-attached')
        capture.assert_called_once_with(self.game)

    @contextmanager
    def offline_cleanup(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(native, 'alive', return_value=False))
            stack.enter_context(patch.object(native, 'processes', return_value=[
                {'pid': 4, 'parent': 0, 'name': 'System'}]))
            close = stack.enter_context(patch.object(native, 'close'))
            terminate = stack.enter_context(patch.object(native, 'terminate'))
            stack.enter_context(patch.object(self.session, 'collect', side_effect=lambda:
                self.session.state.update(collectionComplete=True)))
            yield
            close.assert_not_called()
            terminate.assert_not_called()

    def stage_file_change(self):
        self.session.write(self.original, b'temporary run configuration')

    def assert_restored(self):
        self.assertTrue(self.session.state['restored'])
        self.assertEqual(self.original.read_bytes(), b'original configuration\r\n')
        self.assertEqual(self.session.state['restoreErrors'], [])

    def test_launch_captures_only_matching_owned_game_before_readiness_once(self):
        runtime = self.directory / 'devbench-runtime.json'
        runner.atomic_json(runtime, {'port': 17819})
        token = self.directory / 'bridge-token'
        token.write_text('offline-test', encoding='utf-8')
        ini = self.directory / 'ModOrganizer.ini'
        ini.write_text('offline test', encoding='utf-8')
        policy = SimpleNamespace(snapshot=lambda: {'game_edition': 'se'},
            mo2_ini=ini, mo2=self.directory, mo2_exe=self.directory / 'ModOrganizer.exe',
            bridge_token=token, bridge_port=17818, mods=self.directory / 'mods',
            game=self.directory)
        contract = {'verified': 'offline-contract'}
        self.session.state['preflight']['loaderContract'] = contract
        self.session.state['testProfileName'] = 'Autotest-exit-integration'
        self.session.state['owned'] = [{'role': 'game', 'identity': copy.deepcopy(self.game)}]
        events = []
        health = iter([{'pid': 999, 'frame': 1}, {'pid': self.game['pid'], 'frame': 1},
                       {'pid': self.game['pid'], 'frame': 2}])
        tracker = self.tracker()

        def request(port, route, body=None, **kwargs):
            if route == 'ping':
                return {'profile': self.session.state['testProfileName'],
                        'game': editions.target({'game_edition': 'se'})['bridgeGame'],
                        'modsPath': str(policy.mods)}
            if route == 'run':
                return {'started': True}
            self.assertEqual((port, route), (17819, 'api/health'))
            value = next(health)
            events.append(('health', value['pid'], value['frame']))
            return value

        def capture(identity):
            events.append(('capture', copy.deepcopy(identity)))
            return tracker

        with patch.object(runner, 'P', policy), \
             patch.object(editions, 'validate_mo2_loader', return_value=contract), \
             patch.object(editions, 'runtime_candidates', return_value=[runtime]), \
             patch.object(runner, 'request', side_effect=request), \
             patch.object(runner.time, 'sleep'), \
             patch.object(native, 'alive', side_effect=lambda value: value == self.game), \
             patch.object(native, 'focus_owned', return_value={'available': False}), \
             patch.object(self.session, 'spawn') as spawn, \
             patch.object(self.session, 'discover'), \
             patch.object(self.session, 'wait_task_queue'), \
             patch.object(se_startup, 'wait_main_menu', side_effect=lambda session:
                          events.append(('readiness',))), \
             patch.object(process_exit, 'capture', side_effect=capture) as factory:
            self.session.launch()

        factory.assert_called_once_with(self.game)
        spawn.assert_called_once()  # Intercepted; no executable is opened.
        self.assertEqual(events, [('health', 999, 1), ('health', self.game['pid'], 1),
                                 ('capture', self.game), ('health', self.game['pid'], 2),
                                 ('readiness',)])
        self.assertEqual(self.session.state['gameProcessObservations'][0]['stage'],
                         'matching-game-attached')
        tracker.close.assert_not_called()

    def test_retained_handle_observes_later_exit_through_restore_and_closes_once(self):
        tracker = self.tracker()
        self.attach(tracker)
        self.stage_file_change()
        tracker.status, tracker.code = 'exited', 7
        with self.offline_cleanup(), patch.object(process_exit, 'capture') as capture:
            self.session.cleanup()
        capture.assert_not_called()
        self.assert_restored()
        observations = self.session.state['gameProcessObservations']
        self.assertEqual([item['stage'] for item in observations],
                         ['matching-game-attached', 'before-cleanup',
                          'owned-processes-ended', 'cleanup-finally'])
        self.assertEqual(observations[0]['status'], 'running')
        self.assertTrue(all(item['exitCode'] == 7 for item in observations[1:]))
        self.session.close_game_exit_tracker()
        tracker.close.assert_called_once_with()

    def test_same_pid_new_birth_retires_previous_handle_before_new_capture(self):
        first = self.tracker()
        self.attach(first)
        replacement = dict(self.game, birth=self.game['birth'] + 1)
        second = self.tracker(replacement)
        # In-place changes must not mutate the identity retained by the runner.
        self.session.state['game']['birth'] = replacement['birth']
        with patch.object(process_exit, 'capture', return_value=second) as capture:
            self.session.observe_game_exit('replacement-game-attached')
            self.session.observe_game_exit('replacement-still-attached')
        capture.assert_called_once_with(replacement)
        first.close.assert_called_once_with()
        self.assertEqual(self.session.state['gameProcessObservations'][1]['stage'],
                         'before-game-rebind')
        self.assertEqual(self.session.state['gameProcessObservations'][1]['identity'], self.game)
        self.assertEqual(self.session.state['gameProcessObservations'][-1]['identity'], replacement)
        self.session.close_game_exit_tracker()
        self.session.close_game_exit_tracker()
        first.close.assert_called_once_with()
        second.close.assert_called_once_with()

    def test_capture_failure_is_diagnostic_and_does_not_prevent_restoration(self):
        self.session.state['game'] = copy.deepcopy(self.game)
        self.stage_file_change()
        with self.offline_cleanup(), patch.object(process_exit, 'capture',
                                                  side_effect=OSError('observer unavailable')):
            self.session.cleanup()
        self.assert_restored()
        self.assertEqual(self.session.state['gameProcessObservationError'], 'OSError')
        self.session.report()
        self.assertEqual(runner.read_json(self.directory / 'result.json')
                         ['gameProcessObservationError'], 'OSError')

    def test_snapshot_or_observation_logging_failure_cannot_block_restore(self):
        for failure in ('snapshot', 'log'):
            with self.subTest(failure=failure):
                tracker = self.tracker()
                self.attach(tracker)
                self.stage_file_change()
                if failure == 'snapshot':
                    tracker.snapshot.side_effect = OSError('lost diagnostic')
                original_log = self.session.log

                def log(kind, **details):
                    if failure == 'log' and kind.startswith('game-process-observation'):
                        raise OSError('diagnostic log unavailable')
                    return original_log(kind, **details)

                with self.offline_cleanup(), patch.object(self.session, 'log', side_effect=log):
                    self.session.cleanup()
                self.assert_restored()
                tracker.close.assert_called_once_with()

    def test_cleanup_failure_still_records_final_snapshot_and_closes_once(self):
        tracker = self.tracker()
        self.attach(tracker)
        self.stage_file_change()
        with patch.object(self.session, 'discover', side_effect=RuntimeError('inventory unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'inventory unavailable'):
                self.session.cleanup()
        self.assertFalse(self.session.state.get('restored', False))
        self.assertEqual(self.original.read_bytes(), b'temporary run configuration')
        self.assertEqual(self.session.state['gameProcessObservations'][-1]['stage'], 'cleanup-finally')
        self.session.close_game_exit_tracker()
        tracker.close.assert_called_once_with()

    def test_close_failure_does_not_replace_cleanup_failure_or_retry_handle(self):
        tracker = self.tracker()
        self.attach(tracker)
        tracker.close.side_effect = OSError('CloseHandle diagnostic failure')
        with patch.object(self.session, 'discover', side_effect=RuntimeError('restore boundary failed')):
            with self.assertRaisesRegex(RuntimeError, 'restore boundary failed'):
                self.session.cleanup()
        self.session.close_game_exit_tracker()
        tracker.close.assert_called_once_with()
        self.assertIsNone(self.session._game_exit_tracker)

    def test_foreign_game_shutdown_refusal_closes_observer_without_restoring(self):
        tracker = self.tracker()
        self.attach(tracker)
        self.stage_file_change()
        foreign = dict(self.game, pid=999, birth=self.game['birth'] + 1)
        with patch.object(self.session, 'discover'), \
             patch.object(native, 'processes', return_value=[
                 {'pid': foreign['pid'], 'parent': 0, 'name': 'SkyrimSE.exe'}]), \
             patch.object(native, 'identity', return_value=foreign), \
             patch.object(native, 'close') as close, patch.object(native, 'terminate') as terminate, \
             patch.object(self.session, 'restore_file') as restore:
            with self.assertRaisesRegex(RuntimeError, 'shared runtime preserved'):
                self.session.cleanup()
        close.assert_not_called()
        terminate.assert_not_called()
        restore.assert_not_called()
        self.assertFalse(self.session.state.get('restored', False))
        tracker.close.assert_called_once_with()

    def test_report_preserves_unsigned_exit_code_in_state_steps_and_result_json(self):
        code = 0xC0000005
        tracker = self.tracker(status='exited', code=code)
        self.attach(tracker)
        self.session.state['result'] = 'failed'
        self.session.state['reason'] = 'Owned game exited; cause unclassified'
        with self.offline_cleanup():
            self.session.cleanup()
        self.session.report()
        result = runner.read_json(self.directory / 'result.json')
        state = runner.read_json(self.directory / 'state.json')
        steps = [json.loads(line) for line in
                 (self.directory / 'steps.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(result['gameProcessObservations'], state['gameProcessObservations'])
        for item in result['gameProcessObservations']:
            self.assertEqual((item['exitCode'], item['exitCodeHex']), (3221225477, '0xC0000005'))
        recorded = [item for item in steps if item['kind'] == 'game-process-observation']
        self.assertEqual(len(recorded), len(result['gameProcessObservations']))
        self.assertTrue(all(item['exitCode'] == code for item in recorded))
        self.assertEqual((result['result'], result['restored']), ('failed', True))

    def test_recovery_preserves_prior_exit_when_new_observer_cannot_open_dead_game(self):
        tracker = self.tracker(status='exited', code=0xC0000005)
        self.attach(tracker)
        self.stage_file_change()
        prior = copy.deepcopy(self.session.state['gameProcessObservations'])
        self.session.close_game_exit_tracker()
        # A later executor cannot inherit the original Windows handle. Reopen
        # durable session state and exercise the real observer's unavailable
        # receipt without touching a real process or replacing prior evidence.
        with patch.object(native, 'alive', return_value=False):
            self.session = runner.Session(self.directory)
        self.addCleanup(self.session.close_game_exit_tracker)
        api = Mock()
        api.open.side_effect = OSError('original process already exited')
        actual_capture = process_exit.capture
        with self.offline_cleanup(), patch.object(process_exit, 'capture',
                side_effect=lambda identity: actual_capture(identity, api=api)) as factory:
            self.session.cleanup()
        factory.assert_called_once_with(self.game)
        api.open.assert_called_once_with(self.game['pid'])
        api.identity.assert_not_called()
        api.close.assert_not_called()
        self.assert_restored()
        self.session.report()
        observations = runner.read_json(self.directory / 'result.json')['gameProcessObservations']
        self.assertEqual(observations[:len(prior)], prior)
        self.assertTrue(all(item['status'] == 'unavailable' and item['exitCode'] is None
                            for item in observations[len(prior):]))


if __name__ == '__main__':
    unittest.main()
