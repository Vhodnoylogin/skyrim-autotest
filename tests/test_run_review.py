from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from skyrim_autotest.run_review import summarize


def inspect_abandonment_error():
    message = ('main-thread task did not start within 5000ms; queued task abandoned '
               '(169 frames elapsed -- main thread busy)')
    return ('HTTP 504 api/tool/inspect: ' + json.dumps({'code': 504, 'error': message})
            + ' {"Content-Type": "application/json"}')


class RunReviewTests(unittest.TestCase):
    def setUp(self):
        self.scratch = TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.ledger = Path(self.scratch.name) / 'steps.jsonl'
        self.game = {'pid': 47, 'birth': 123, 'path': 'SkyrimVR.exe'}
        self.exit = {'schemaVersion': 1, 'status': 'exited', 'handleRetained': True,
                     'exitCodeAvailable': True, 'identityVerified': True, 'identity': self.game,
                     'expectedIdentity': self.game, 'exitCode': 0xC0000005, 'exitCodeHex': '0xC0000005',
                     'stage': 'owned-processes-ended'}

    def append(self, *rows):
        with self.ledger.open('a', encoding='utf-8') as stream:
            for row in rows:
                stream.write(json.dumps(row) + '\n')

    def test_exit_cannot_override_the_preserved_scenario_result(self):
        self.ledger.touch()
        review = summarize({'id': 'run', 'game': self.game, 'result': 'failed', 'scenarioResult': 'passed',
                            'checks': [{'result': 'passed'}], 'gameProcessObservations': [self.exit],
                            'collectionComplete': True, 'restored': True}, self.ledger)
        self.assertEqual((review['scenarioResult'], review['result']), ('passed', 'failed'))
        self.assertEqual(review['nativeExit']['hex'], '0xC0000005')
        self.assertEqual(review['checks'], {'passed': 1})
        self.assertEqual([row['area'] for row in review['improvementCandidates']], ['shutdown'])

    def test_failed_checks_identify_scenario_assertions_without_raw_observations(self):
        self.ledger.touch()
        review = summarize({'checks': [
            {'name': 'Relocation', 'result': 'failed', 'observation': 'raw-data'},
            {'name': 'World ready', 'result': 'passed'},
            {'result': 'failed'},
            {'name': 'Provider response', 'result': 'failed', 'reason': 'raw-reason'},
        ]}, self.ledger)
        self.assertEqual(review['checks'], {'failed': 3, 'passed': 1})
        self.assertEqual(review['failedChecks'], ['Relocation', 'Provider response'])
        self.assertNotIn('raw-', json.dumps(review))

    def test_shutdown_summary_distinguishes_queue_receipt_window_close_and_exit(self):
        self.append({'kind': 'owned-game-window-close', 'requested': True, 'accepted': True,
                     'private': 'window details'})
        grace = {'game': self.game, 'command': 'qqq', 'requestAttempted': True, 'observedGone': False,
                 'requestAcknowledgement': {'queued': True, 'command': 'qqq', 'private': 'raw output'}}
        state = {'game': self.game, 'gracefulGameExit': grace, 'gameProcessObservations': [self.exit]}
        review = summarize(state, self.ledger)
        self.assertEqual(review['gracefulExit'], {'route': 'qqq', 'requestAttempted': True,
                                                'queueAcknowledged': True, 'observedGone': False,
                                                'waitObservation': None})
        self.assertEqual(review['execution']['ownedGameWindowClose'], [{'requested': True, 'accepted': True}])
        self.assertEqual(review['nativeExit']['code'], 0xC0000005)
        self.assertNotIn('private', json.dumps(review))
        grace['requestAcknowledgement']['command'] = 'other'
        self.assertIsNone(summarize(state, self.ledger)['gracefulExit']['queueAcknowledged'])
        grace['game'] = dict(self.game, birth=999)
        self.assertIsNone(summarize(state, self.ledger)['gracefulExit'])

    def test_archived_shutdown_console_receipt_preserves_scenario_exit_and_restoration(self):
        self.append({'kind': 'phase', 'name': 'stop-and-restore'},
                    {'kind': 'tool', 'tool': 'console', 'args': {'action': 'exec', 'command': 'qqq'},
                     'result': {'capturing': False, 'command': 'qqq', 'queued': True, 'raw': 'private-data'}})
        state = {'game': self.game, 'result': 'failed', 'scenarioResult': 'passed',
                 'gameProcessObservations': [self.exit], 'restored': True}
        review = summarize(state, self.ledger)
        self.assertEqual(review['execution']['shutdownConsoleRequests'],
                         {'acknowledged': 1, 'notQueued': 0, 'unknown': 0})
        self.assertIsNone(review['gracefulExit'])
        self.assertEqual((review['result'], review['scenarioResult'], review['restored']), ('failed', 'passed', True))
        self.assertEqual(review['nativeExit']['hex'], '0xC0000005')
        self.assertNotIn('private-data', json.dumps(review))

    def test_shutdown_console_receipts_require_exact_request_phase_and_typed_response(self):
        args = {'action': 'exec', 'command': 'qqq'}
        request = {'kind': 'tool', 'tool': 'console', 'args': args}
        receipt = {'command': 'qqq', 'queued': True}
        self.append({**request, 'result': receipt},
                    {'kind': 'phase', 'name': 'stop-and-restore'},
                    {**request, 'args': {**args, 'command': 'other'}, 'result': receipt},
                    {**request, 'args': {**args, 'action': 'help'}, 'result': receipt},
                    {**request, 'result': {'command': 'qqq', 'queued': False}},
                    {**request, 'result': {'command': 'qqq', 'queued': 1}},
                    {**request, 'result': {'command': 'other', 'queued': True}},
                    {**request, 'result': {**receipt, 'isError': True}},
                    {**request, 'kind': 'tool-error', 'error': 'HTTP 504', 'result': receipt},
                    {'kind': 'phase', 'name': 'archive'},
                    {**request, 'result': receipt})
        self.assertEqual(summarize({}, self.ledger)['execution']['shutdownConsoleRequests'],
                         {'acknowledged': 0, 'notQueued': 1, 'unknown': 4})

    def test_quit_wait_duration_requires_a_consistent_finished_bracket(self):
        self.ledger.touch()
        grace = {'game': self.game, 'command': 'qqq', 'requestAttempted': True, 'observedGone': True,
                 'startedMonotonic': 100, 'deadlineMonotonic': 110, 'waitFinishedMonotonic': 106.5}
        state = {'game': self.game, 'gracefulGameExit': grace}
        def observation():
            return summarize(state, self.ledger)['gracefulExit']['waitObservation']

        self.assertEqual(observation(), {'elapsedSeconds': 6.5, 'graceSeconds': 10,
                                         'processGoneByDeadline': True})
        grace['waitFinishedMonotonic'] = 111.0
        self.assertFalse(observation()['processGoneByDeadline'])
        grace['waitFinishedMonotonic'] = 99.0
        self.assertIsNone(observation())

    def test_payloads_stay_in_raw_log_and_error_counts_use_observed_phase(self):
        self.append({'kind': 'phase', 'name': 'wait-devbench'},
                    {'kind': 'tool-error', 'tool': 'inspect', 'args': {'private': 'payload'},
                     'error': 'HTTP 504 api/tool/inspect: private-response'},
                    {'kind': 'tool-error', 'tool': 'inspect', 'error': 'HTTP 504 retry'},
                    {'kind': 'phase', 'name': 'stop-and-restore'},
                    {'kind': 'mo2-launch', 'result': {'started': False, 'token': 'private-token'}})
        review = summarize({'configuration': {'game_edition': 'se'}, 'restored': True}, self.ledger)
        self.assertEqual(review['gameEdition'], 'se')
        self.assertEqual(review['execution']['toolErrors'], [
            {'tool': 'inspect', 'phase': 'wait-devbench', 'httpStatus': 504, 'count': 2},
        ])
        self.assertEqual({row['area'] for row in review['improvementCandidates']}, {'transport', 'launch'})
        self.assertNotIn('private-', json.dumps(review))

    def test_execution_failure_retains_phase_without_trace_or_cleanup(self):
        self.append({'kind': 'phase', 'name': 'subject-measurement'},
                    {'kind': 'exception', 'exceptionType': 'RuntimeError', 'trace': 'private-result'},
                    {'kind': 'phase', 'name': 'stop-and-restore'},
                    {'kind': 'cleanup-error', 'trace': 'private-cleanup'})
        review = summarize({'result': 'failed', 'scenarioResult': 'failed', 'restored': True}, self.ledger)
        self.assertEqual(review['execution']['failures'], [
            {'phase': 'subject-measurement', 'disposition': 'failed', 'exceptionType': 'RuntimeError'},
        ])
        self.assertNotIn('private-', json.dumps(review))

    def test_old_exception_and_new_block_keep_independent_observations(self):
        self.append({'kind': 'exception', 'trace': 'private-result'},
                    {'kind': 'phase', 'name': 'wait-devbench'},
                    {'kind': 'execution-blocked', 'exceptionType': 'Blocked'})
        self.assertEqual(summarize({}, self.ledger)['execution']['failures'], [
            {'phase': None, 'disposition': 'failed', 'exceptionType': None},
            {'phase': 'wait-devbench', 'disposition': 'blocked', 'exceptionType': 'Blocked'},
        ])

    def test_scenario_gate_keeps_reason_and_phase_without_changing_any_verdict(self):
        gate = {'kind': 'scenario-gate', 'name': 'active-force-admission', 'disposition': 'blocked',
                'reasonCode': 'passive-baseline-not-stationary', 'required': True}
        self.append({'kind': 'phase', 'name': 'subject'}, {**gate, 'raw': 'private-data'},
                    {'kind': 'phase', 'name': 'stop-and-restore'},
                    {**gate, 'name': 'retirement', 'disposition': 'passed', 'reasonCode': 'retired', 'required': False})
        clean = {**self.exit, 'exitCode': 0, 'exitCodeHex': '0x00000000'}
        state = {'game': self.game, 'result': 'failed', 'scenarioResult': 'failed', 'restored': True,
                 'collectionComplete': True, 'gameProcessObservations': [clean]}
        review = summarize(state, self.ledger)
        self.assertEqual(review['execution']['scenarioGates'], [
            {'phase': 'subject', 'name': 'active-force-admission', 'disposition': 'blocked',
             'reasonCode': 'passive-baseline-not-stationary', 'required': True},
            {'phase': 'stop-and-restore', 'name': 'retirement', 'disposition': 'passed',
             'reasonCode': 'retired', 'required': False},
        ])
        self.assertEqual((review['result'], review['scenarioResult'], review['restored']), ('failed', 'failed', True))
        self.assertEqual(review['nativeExit']['code'], 0)
        self.assertIsNone(summarize({'result': 'failed'}, self.ledger)['scenarioResult'])
        self.assertNotIn('private-data', json.dumps(review))

    def test_scenario_gate_requires_typed_disposition_reason_and_required_flag(self):
        gate = {'kind': 'scenario-gate', 'name': 'admission', 'disposition': 'unavailable',
                'reasonCode': 'missing-observation', 'required': False}
        self.append(gate, *({**gate, **invalid} for invalid in (
            {'required': 1}, {'disposition': 'unexpected'}, {'reasonCode': 'detail with spaces'},
            {'reasonCode': None}, {'name': ''}, {'name': 'a' * 97},
        )))
        self.assertEqual(summarize({}, self.ledger)['execution']['scenarioGates'], [
            {'phase': None, 'name': 'admission', 'disposition': 'unavailable',
             'reasonCode': 'missing-observation', 'required': False},
        ])

    def test_observer_availability_keeps_source_domain_separate_from_successful_snapshot(self):
        args = {'kind': 'world_observer', 'action': 'snapshot'}
        unavailable = {'status': 'unavailable', 'reason': 'private-data'}
        result = {'schemaVersion': 1, 'ok': True, 'phase': 'skse_main_thread_task', 'quality': 'complete',
                  'physics': unavailable, 'render': unavailable}
        receipt = {'kind': 'tool', 'tool': 'inspect', 'args': args, 'result': result}
        self.append({'kind': 'phase', 'name': 'world'}, receipt, receipt,
                    {**receipt, 'args': {'kind': 'world_observer', 'physics': {'refs': ['0x14']}},
                     'result': {**result, 'quality': 'partial', 'physics': {'status': 'partial'}}},
                    {'kind': 'phase', 'name': 'subject'}, receipt)
        state = {'result': 'passed', 'scenarioResult': 'passed', 'restored': True}
        review = summarize(state, self.ledger)
        self.assertEqual(review['execution']['worldObserverAvailability'], [
            {'phase': 'world', 'domain': 'physics', 'status': 'unavailable', 'requested': False, 'count': 2},
            {'phase': 'world', 'domain': 'render', 'status': 'unavailable', 'requested': False, 'count': 3},
            {'phase': 'world', 'domain': 'physics', 'status': 'partial', 'requested': True, 'count': 1},
            {'phase': 'subject', 'domain': 'physics', 'status': 'unavailable', 'requested': False, 'count': 1},
            {'phase': 'subject', 'domain': 'render', 'status': 'unavailable', 'requested': False, 'count': 1},
        ])
        self.assertEqual((review['result'], review['scenarioResult']), ('passed', 'passed'))
        self.assertEqual(review['improvementCandidates'], [])
        self.assertNotIn('private-data', json.dumps(review))

    def test_observer_availability_accepts_only_typed_successful_snapshot_domains(self):
        args = {'kind': 'world_observer', 'physics': {'refs': ['0x14']}}
        result = {'schemaVersion': 1, 'ok': True, 'phase': 'skse_main_thread_task',
                  'physics': {'status': 'available'}, 'render': {'status': 'wrong'}}
        receipt = {'kind': 'tool', 'tool': 'inspect', 'args': args, 'result': result}
        self.append(receipt, {**receipt, 'kind': 'tool-error'}, {**receipt, 'tool': 'papyrus'},
                    {**receipt, 'args': {**args, 'action': 'capabilities'}},
                    *({**receipt, 'result': {**result, **invalid}} for invalid in (
                        {'schemaVersion': True}, {'schemaVersion': 2}, {'ok': 1}, {'ok': False},
                        {'phase': 'unverified_phase'}, {'physics': []},
                    )))
        self.assertEqual(summarize({}, self.ledger)['execution']['worldObserverAvailability'], [
            {'phase': None, 'domain': 'physics', 'status': 'available', 'requested': True, 'count': 1},
        ])

    def test_capture_receipts_preserve_flags_without_disclosing_names_or_certifying_images(self):
        args = {'kind': 'native', 'checkpointId': 'private-checkpoint'}
        native = {'kind': 'screenshot', 'provider': 'native', 'checkpointId': 'private-checkpoint',
                  'ok': True, 'sceneMismatch': False, 'inconclusive': True, 'uiExcluded': False,
                  'captureElapsedMs': 277, 'frame': 9379, 'path': 'private-path.png'}
        receipt = {'kind': 'tool', 'tool': 'capture', 'args': args, 'result': native}
        extension = {**native, 'provider': 'private-provider', 'sceneMismatch': True,
                     'uiExcluded': True, 'captureElapsedMs': False}
        self.append({'kind': 'phase', 'name': 'photos'}, receipt,
                    {'kind': 'phase', 'name': 'comparison'},
                    {**receipt, 'args': {**args, 'kind': 'private-provider'}, 'result': extension})
        review = summarize({'result': 'failed', 'scenarioResult': 'passed'}, self.ledger)
        self.assertEqual(review['execution']['captureReceipts'], [
            {'phase': 'photos', 'method': 'native', 'ok': True, 'sceneMismatch': False,
             'inconclusive': True, 'uiExcluded': False, 'captureElapsedMs': 277},
            {'phase': 'comparison', 'method': 'extension', 'ok': True, 'sceneMismatch': True,
             'inconclusive': True, 'uiExcluded': True, 'captureElapsedMs': None},
        ])
        self.assertEqual((review['result'], review['scenarioResult']), ('failed', 'passed'))
        self.assertNotIn('private-', json.dumps(review))
        self.assertNotIn('9379', json.dumps(review))

    def test_capture_receipts_require_matching_typed_single_image_reply(self):
        result = {'kind': 'screenshot', 'provider': 'native', 'checkpointId': 'capture',
                  'ok': True, 'sceneMismatch': False, 'inconclusive': True, 'uiExcluded': False}
        receipt = {'kind': 'tool', 'tool': 'capture', 'args': {'kind': 'native'}, 'result': result}
        self.append({**receipt, 'args': {'kind': 'auto', 'allowNative': True}},
                    {**receipt, 'kind': 'tool-error'}, {**receipt, 'tool': 'inspect'},
                    *({**receipt, 'args': args} for args in (
                        {'kind': 'native', 'action': 'status'}, {'kind': 'auto'},
                        {'kind': 'providers'}, {'kind': 'native', 'checkpointId': 'different'},
                    )),
                    *({**receipt, 'result': {**result, **invalid}} for invalid in (
                        {'ok': False}, {'ok': 1}, {'kind': 'burst'}, {'sceneMismatch': 0},
                        {'provider': 'different-provider'}, {'checkpointId': None},
                    )))
        self.assertEqual(summarize({}, self.ledger)['execution']['captureReceipts'], [
            {'phase': None, 'method': 'native', 'ok': True, 'sceneMismatch': False,
             'inconclusive': True, 'uiExcluded': False, 'captureElapsedMs': None},
        ])

    def test_file_driver_receipts_follow_commands_and_keep_frames_private(self):
        a, b = 'a' * 32, 'b' * 32
        def event(action, **result):
            return {'kind': 'driver', 'action': action, 'frame': {'left': 'private-geometry'},
                    'result': {'protocolVersion': 2, **result}}

        self.append({'kind': 'phase', 'name': 'near'},
                    event('publish', published=True, publication={'version': 2, 'command': a, 'sequence': 11}),
                    event('status', command=a, sequence=10, acknowledgedByDriver=True),
                    event('status', command=a, sequence=11, acknowledgedByDriver=False),
                    {'kind': 'phase', 'name': 'far'},
                    event('release', published=True, publication={'version': 2, 'command': b, 'sequence': 16}),
                    event('status', command=b, sequence=15, acknowledgedByDriver=True),
                    event('status', command=a, sequence=12, acknowledgedByDriver=True),
                    event('status', command=a, sequence=13, acknowledgedByDriver=True))
        review = summarize({}, self.ledger)
        self.assertEqual(review['execution']['driver'], [
            {'phase': 'near', 'operation': 'publish', 'count': 1},
            {'phase': 'near', 'operation': 'status', 'count': 2},
            {'phase': 'far', 'operation': 'release', 'count': 1},
            {'phase': 'far', 'operation': 'status', 'count': 3},
            {'phase': 'near', 'operation': 'acknowledged', 'count': 1},
            {'phase': 'far', 'operation': 'acknowledgement-unobserved', 'count': 1},
        ])
        self.assertEqual(review['execution']['driverAcknowledgementTiming'], [])
        for private in (a, b, 'private-geometry'):
            self.assertNotIn(private, json.dumps(review))

    def test_driver_uses_first_timed_receipt_and_separates_ambiguous_writes(self):
        good, duplicate = 'a' * 32, 'b' * 32

        def write(command, sequence):
            return {'kind': 'driver', 'action': 'publish', 'result': {
                'protocolVersion': 2, 'published': True, 'publication': {
                    'version': 2, 'command': command, 'sequence': sequence, 'publishedTickMs': 100}}}

        def acknowledge(command, sequence, tick):
            return {'kind': 'driver', 'action': 'status', 'result': {
                'protocolVersion': 2, 'command': command, 'sequence': sequence,
                'acknowledgedByDriver': True, 'observedTickMs': tick}}

        self.append({'kind': 'phase', 'name': 'tracking'}, write(good, 10),
                    acknowledge(good, 9, 105), acknowledge(good, 10, 99),
                    acknowledge(good, 10, 114), acknowledge(good, 11, 125),
                    write(duplicate, 12), acknowledge(duplicate, 12, 130), write(duplicate, 13),
                    write('invalid', 14), write('c' * 32, 15), acknowledge('c' * 32, 16, 883))
        log = summarize({}, self.ledger)['execution']
        self.assertEqual(log['driver'], [
            {'phase': 'tracking', 'operation': 'publish', 'count': 5},
            {'phase': 'tracking', 'operation': 'status', 'count': 6},
            {'phase': 'tracking', 'operation': 'uncorrelated', 'count': 3},
            {'phase': 'tracking', 'operation': 'acknowledged', 'count': 2},
        ])
        self.assertEqual(log['driverAcknowledgementTiming'], [
            {'phase': 'tracking', 'exactSequence': True, 'samples': 1, 'minMs': 14, 'maxMs': 14},
            {'phase': 'tracking', 'exactSequence': False, 'samples': 1, 'minMs': 783, 'maxMs': 783},
        ])

    def test_known_clean_run_does_not_manufacture_a_suggestion(self):
        self.append({'kind': 'mo2-launch', 'result': {'started': True, 'applied': True}})
        normal = dict(self.exit, exitCode=0, exitCodeHex='0x00000000')
        review = summarize({'game': self.game, 'gameProcessObservations': [normal], 'result': 'passed',
                            'collectionComplete': True, 'restored': True}, self.ledger)
        self.assertEqual(review['nativeExit']['code'], 0)
        self.assertEqual(review['execution']['bridgeStartAcknowledgements'], 1)
        self.assertEqual(review['improvementCandidates'], [])

    def bridge_receipts(self):
        boot, launch_id = 'private-boot', 'private-boot:private-launch'
        start = {'kind': 'mo2-launch', 'result': {'started': True, 'applied': True,
                                                 'serverBootId': boot, 'operationRecordId': launch_id}}
        child = {'pid': self.game['pid'], 'creationTime': self.game['birth'], 'path': self.game['path'],
                 'alive': True, 'exit': None}
        launch = {'operationRecordId': launch_id, 'gameChildren': [child],
                  'gameAlive': True, 'gameExitStatus': 'running', 'gameExit': None}
        operation = {'route': '/run', 'id': launch_id, 'serverBootId': boot,
                     'state': 'succeeded', 'terminal': True, 'launch': launch}
        observation = {'kind': 'private-vr-bridge-observation', 'at': 1795250649.8944087,
                       'location': 'game-ended-manager-still-available',
                       'observation': {'serverBootId': boot, 'game': self.game, 'operation': operation}}
        return start, observation

    def test_bridge_child_status_and_clock_are_independent_of_launch_and_native_exit(self):
        start, running = self.bridge_receipts()
        self.append(start, {'kind': 'phase', 'name': 'stop-and-restore'}, running)
        exit_row = {**self.exit, 'firstExitObservedAtUtc': '2026-11-21T08:44:12.514Z',
                    'observedAtUtc': '2026-11-21T08:44:22.722Z'}
        state = {'game': self.game, 'gameProcessObservations': [exit_row]}
        review = summarize(state, self.ledger)
        expected = {'phase': 'stop-and-restore', 'operationState': 'succeeded', 'operationTerminal': True,
                    'gameExitStatus': 'running', 'gameExitCode': None, 'msFromFirstNativeExitObservation': -2620}
        self.assertEqual(review['execution']['bridgeGameObservations'], [expected])
        self.assertEqual(review['nativeExit']['code'], 0xC0000005)
        self.assertNotIn('private-', json.dumps(review))
        self.assertNotIn(running['location'], json.dumps(review))
        self.assertEqual(review['improvementCandidates'][0]['trigger'], 'verified-nonzero-exit')

        running.update(kind='mo2-bridge-observation', at=1795250653.014)
        launch = running['observation']['operation']['launch']
        launch.update(gameExitStatus='observed', gameAlive=False, gameExit=0)
        launch['gameChildren'][0].update(alive=False, exit=0)
        self.append(running)
        review = summarize(state, self.ledger)
        self.assertEqual(review['execution']['bridgeGameObservations'], [expected, {
            **expected, 'gameExitStatus': 'observed', 'gameExitCode': 0, 'msFromFirstNativeExitObservation': 500}])
        self.assertEqual(review['nativeExit']['code'], 0xC0000005)
        observations = summarize({'game': self.game}, self.ledger)['execution']['bridgeGameObservations']
        self.assertIsNone(observations[0]['msFromFirstNativeExitObservation'])

    def test_bridge_child_projection_requires_linked_launch_and_exact_child(self):
        start, row = self.bridge_receipts()
        self.append(row, start)
        observation = row['observation']
        operation, boot = observation['operation'], observation['serverBootId']
        observation['serverBootId'] = 'other-boot'
        self.append(row)
        observation['serverBootId'] = boot
        launch = operation['launch']
        child = launch['gameChildren'][0]
        for key, invalid in (('pid', self.game['pid'] + 1), ('creationTime', float(self.game['birth'])),
                             ('path', 'Other.exe'), ('alive', 1)):
            original = child[key]
            child[key] = invalid
            self.append(row)
            child[key] = original
        launch['gameChildren'].append(child)
        self.append(row)
        self.assertEqual(summarize({'game': self.game}, self.ledger)['execution']['bridgeGameObservations'], [])

    def test_native_window_retains_producer_shortfall_and_gap_independently(self):
        result = {'kind': 'native-sampling-window', 'name': 'contact-dwell', 'samples': 8,
                  'producerSpanNs': 1_499_969_400, 'minSpanNs': 1_500_000_000,
                  'maxGapNs': 235_876_700, 'maxAllowedGapNs': 900_000_000, 'raw': 'private-pose'}
        self.append({'kind': 'phase', 'name': 'subject'}, result,
                    {**result, 'producerSpanNs': 1_500_000_000},
                    {**result, 'producerSpanNs': 1_700_000_000, 'maxGapNs': 901_000_000},
                    {**result, 'samples': True}, {**result, 'maxGapNs': 9_000_000_000})
        review = summarize({'scenarioResult': 'failed'}, self.ledger)
        windows = review['execution']['nativeSamplingWindows']
        self.assertEqual([row['meetsDeclaredTiming'] for row in windows], [False, True, False])
        self.assertEqual(windows[0]['minSpanNs'] - windows[0]['producerSpanNs'], 30_600)
        self.assertEqual(windows[0]['phase'], 'subject')
        self.assertEqual(review['scenarioResult'], 'failed')
        self.assertEqual(review['improvementCandidates'][0]['trigger'], 'declared-native-window-timing-missed')
        self.assertNotIn('private-pose', json.dumps(review))

    def test_task_queue_recovery_and_declared_abandonment_use_recorded_events(self):
        self.append({'kind': 'phase', 'name': 'wait-task-queue'},
                    {'kind': 'task-queue-not-ready'}, {'kind': 'task-queue-not-ready'},
                    {'kind': 'task-queue-ready'},
                    {'kind': 'phase', 'name': 'gameplay-new-game-menu'},
                    {'kind': 'tool-error', 'tool': 'gfx', 'error': 'HTTP 504 timeout'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'gfx', 'args': {'private': 'payload'}})
        log = summarize({}, self.ledger)['execution']
        self.assertEqual(log['taskQueue'], {'waitingObservations': 2, 'readyObservations': 1, 'recoveredWaits': 1})
        self.assertEqual(log['abandonedStartupReads'], [
            {'phase': 'gameplay-new-game-menu', 'tool': 'gfx', 'count': 1},
        ])

    def test_new_phase_does_not_confirm_recovery_for_an_unrelated_wait(self):
        self.append({'kind': 'phase', 'name': 'old'}, {'kind': 'task-queue-not-ready'},
                    {'kind': 'phase', 'name': 'new'}, {'kind': 'task-queue-ready'})
        self.assertEqual(summarize({}, self.ledger)['execution']['taskQueue']['recoveredWaits'], 0)

    def test_only_explicit_same_request_links_a_gateway_disposition(self):
        self.append({'kind': 'phase', 'name': 'menu'},
                    {'kind': 'tool-error', 'tool': 'gfx', 'error': 'HTTP 504', 'clientRequestId': 'a'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'gfx', 'clientRequestId': 'a'},
                    {'kind': 'tool-error', 'tool': 'gfx', 'error': 'HTTP 504', 'clientRequestId': 'b'},
                    {'kind': 'phase', 'name': 'other'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'gfx', 'clientRequestId': 'b'},
                    {'kind': 'tool-error', 'tool': 'gfx', 'error': 'HTTP 504'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'gfx'})
        review = summarize({}, self.ledger)
        self.assertEqual(review['execution']['gatewayDispositions'],
                         {'abandonedBeforeStart': 1, 'dispatchedCompletionUnknown': 0, 'unresolved': 2})
        self.assertEqual(review['improvementCandidates'][0]['area'], 'transport')

    def test_known_disposition_needs_no_generic_gateway_suggestion(self):
        self.append({'kind': 'tool-error', 'tool': 'gfx', 'error': 'HTTP 504', 'clientRequestId': 'a'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'gfx', 'clientRequestId': 'a'})
        self.assertEqual(summarize({}, self.ledger)['improvementCandidates'], [])

    def test_forwarded_platform_error_does_not_count_as_an_extra_gateway_request(self):
        error = 'HTTP 504 api/tool/inspect: engine busy'
        self.append({'kind': 'tool-error', 'tool': 'inspect', 'error': error, 'clientRequestId': 'leaf'},
                    {'kind': 'tool-error', 'tool': 'platform', 'error': error})
        log = summarize({}, self.ledger)['execution']
        self.assertEqual(len(log['toolErrors']), 2)
        self.assertEqual(log['gatewayDispositions'],
                         {'abandonedBeforeStart': 0, 'dispatchedCompletionUnknown': 0, 'unresolved': 1})

    def test_direct_inspect_abandonment_and_queue_recovery_have_separate_counts(self):
        error = inspect_abandonment_error()
        self.append({'kind': 'phase', 'name': 'wait-task-queue'},
                    {'kind': 'tool-error', 'tool': 'inspect', 'args': {'kind': 'state'}, 'error': error},
                    {'kind': 'task-queue-not-ready', 'error': error},
                    {'kind': 'task-queue-ready'})
        review = summarize({}, self.ledger)
        self.assertEqual(review['execution']['gatewayDispositions'],
                         {'abandonedBeforeStart': 1, 'dispatchedCompletionUnknown': 0, 'unresolved': 0})
        self.assertEqual(review['execution']['taskQueue']['recoveredWaits'], 1)
        self.assertEqual(review['execution']['abandonedStartupReads'], [])
        self.assertEqual(review['improvementCandidates'], [])

    def test_direct_inspect_abandonment_counts_once_with_matching_decision_and_forwarded_error(self):
        error = inspect_abandonment_error()
        self.append({'kind': 'phase', 'name': 'menu'},
                    {'kind': 'tool-error', 'tool': 'inspect', 'args': {'kind': 'scene'},
                     'error': error, 'clientRequestId': 'same'},
                    {'kind': 'common-readiness-abandoned-read', 'tool': 'inspect', 'clientRequestId': 'same'},
                    {'kind': 'tool-error', 'tool': 'platform', 'error': error})
        log = summarize({}, self.ledger)['execution']
        self.assertEqual(log['gatewayDispositions'],
                         {'abandonedBeforeStart': 1, 'dispatchedCompletionUnknown': 0, 'unresolved': 0})
        self.assertEqual(log['abandonedStartupReads'], [{'phase': 'menu', 'tool': 'inspect', 'count': 1}])
        self.assertEqual(len(log['toolErrors']), 2)

    def test_inspect_errors_require_the_direct_provider_receipt_and_known_request(self):
        known = inspect_abandonment_error()
        for args, error in (
            ({'kind': 'state'}, 'HTTP 504 api/tool/inspect: generic timeout'),
            ({'kind': 'state'}, known.replace('api/tool/inspect:', '')),
            ({'kind': 'state'}, known.replace('"code": 504', '"code": 500')),
            ({'kind': 'state'}, known.replace('did not start', 'did not finish')),
            ({'kind': 'refs'}, known),
        ):
            self.append({'kind': 'tool-error', 'tool': 'inspect', 'args': args, 'error': error})
        self.assertEqual(summarize({}, self.ledger)['execution']['gatewayDispositions'],
                         {'abandonedBeforeStart': 0, 'dispatchedCompletionUnknown': 0, 'unresolved': 5})

    def test_one_confirmed_dispatch_preserves_unknown_completion_and_payload_privacy(self):
        args = {'action': 'call', 'script': 'PRIVATE_SCRIPT', 'function': 'Begin', 'timeoutMs': 2600}
        message = ("papyrus call 'PRIVATE_SCRIPT.Begin' was dispatched but did not complete within 2600ms "
                   "(latent call or VM stalled?); it may still run, so check its effect before calling again"
                   "; omitted args filled: PRIVATE_PAYLOAD")
        error = 'HTTP 504 api/tool/papyrus: ' + json.dumps({'code': 504, 'error': message})
        self.append({'kind': 'phase', 'name': 'scenario'},
                    {'kind': 'tool-error', 'tool': 'papyrus', 'error': error + ' {"PRIVATE_HEADER": "private"}',
                     'args': args, 'clientRequestId': 'leaf'},
                    {'kind': 'tool-error', 'tool': 'platform', 'error': error})
        review = summarize({'result': 'failed', 'scenarioResult': 'failed', 'restored': True}, self.ledger)
        self.assertEqual(review['execution']['gatewayDispositions'],
                         {'abandonedBeforeStart': 0, 'dispatchedCompletionUnknown': 1, 'unresolved': 0})
        self.assertEqual([row['trigger'] for row in review['improvementCandidates']],
                         ['dispatched-tool-completion-unknown'])
        self.assertNotIn('PRIVATE_', json.dumps(review))

    def test_unproven_or_foreign_dispatch_stays_unresolved(self):
        args = {'action': 'call', 'script': 'Other', 'function': 'Begin'}
        known = ("papyrus call 'Other.Begin' was dispatched but did not complete within 3000ms "
                 "(latent call or VM stalled?); it may still run, so check its effect before calling again")
        for message, request in (
            ("papyrus call 'Other.Begin' was not dispatched within 3000ms "
             "(main thread busy?); it may still be dispatched later", args),
            (known.replace("'Other.Begin'", "'Different.Begin'"), args),
            (known, {**args, 'timeoutMs': 2600}),
            (known, {**args, 'action': 'describe'}),
        ):
            self.append({'kind': 'tool-error', 'tool': 'papyrus',
                         'error': 'HTTP 504 api/tool/papyrus: ' + json.dumps({'code': 504, 'error': message}),
                         'args': request})
        self.assertEqual(summarize({}, self.ledger)['execution']['gatewayDispositions'],
                         {'abandonedBeforeStart': 0, 'dispatchedCompletionUnknown': 0, 'unresolved': 4})

    def test_missing_or_damaged_log_and_foreign_exit_remain_distinct(self):
        passport = {'game': dict(self.game, pid=99), 'gameProcessObservations': [self.exit]}
        missing = summarize(passport, self.ledger)
        self.assertFalse(missing['execution']['available'])
        self.assertIsNone(missing['execution']['captureReceipts'])
        self.assertIsNone(missing['execution']['worldObserverAvailability'])
        self.assertIsNone(missing['execution']['scenarioGates'])
        self.assertIsNone(missing['execution']['bridgeGameObservations'])
        self.assertIsNone(missing['execution']['shutdownConsoleRequests'])
        self.assertIsNone(missing['nativeExit'])
        self.ledger.write_text('invalid\n42\n', encoding='utf-8')
        damaged = summarize(dict(passport, restored=False), self.ledger)
        self.assertEqual(damaged['execution']['malformedRows'], 2)
        self.assertEqual({row['area'] for row in damaged['improvementCandidates']}, {'evidence', 'recovery'})
