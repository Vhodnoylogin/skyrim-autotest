from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from skyrim_autotest.run_review import summarize


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

    def test_known_clean_run_does_not_manufacture_a_suggestion(self):
        self.append({'kind': 'mo2-launch', 'result': {'started': True, 'applied': True}})
        normal = dict(self.exit, exitCode=0, exitCodeHex='0x00000000')
        review = summarize({'game': self.game, 'gameProcessObservations': [normal], 'result': 'passed',
                            'collectionComplete': True, 'restored': True}, self.ledger)
        self.assertEqual(review['nativeExit']['code'], 0)
        self.assertEqual(review['execution']['bridgeStartAcknowledgements'], 1)
        self.assertEqual(review['improvementCandidates'], [])

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
        self.assertEqual(review['execution']['gatewayDispositions'], {'abandonedBeforeStart': 1, 'unresolved': 2})
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
        self.assertEqual(log['gatewayDispositions'], {'abandonedBeforeStart': 0, 'unresolved': 1})

    def test_missing_or_damaged_log_and_foreign_exit_remain_distinct(self):
        passport = {'game': dict(self.game, pid=99), 'gameProcessObservations': [self.exit]}
        missing = summarize(passport, self.ledger)
        self.assertFalse(missing['execution']['available'])
        self.assertIsNone(missing['nativeExit'])
        self.ledger.write_text('invalid\n42\n', encoding='utf-8')
        damaged = summarize(dict(passport, restored=False), self.ledger)
        self.assertEqual(damaged['execution']['malformedRows'], 2)
        self.assertEqual({row['area'] for row in damaged['improvementCandidates']}, {'evidence', 'recovery'})
