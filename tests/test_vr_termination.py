"""Trusted VR exit codes affect the run while preserving the scenario."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import runner


FIXTURE = json.loads((Path(__file__).parent / 'fixtures/vr13b-exit-observations.json').read_bytes())
ABNORMAL = 0xC0000005


class VrTerminationTests(unittest.TestCase):
    def setUp(self):
        self.session = runner.Session.__new__(runner.Session)
        self.session.save = Mock()
        self.session.log = Mock()
        self.identity = deepcopy(FIXTURE['game'])
        self.zero = next(deepcopy(row) for row in FIXTURE['gameProcessObservations'] if row['status'] == 'exited')
        self.nonzero = {**self.zero, 'exitCode': ABNORMAL, 'exitCodeHex': '0xC0000005', 'stage': 'cleanup-finally'}
        self.unavailable = deepcopy(FIXTURE['gameProcessObservations'][-1])
        self.checks = [{'name': 'Fitted capsule callbacks', 'result': 'passed'}]
        self.session.state = self.state()

    def state(self, **overrides):
        return {'id': 'vr-termination-fixture', 'configuration': {'game_edition': 'vr'},
                'preflight': {'profile': 'fixture'}, 'game': self.identity,
                'owned': [{'role': 'game', 'identity': self.identity}],
                'result': 'passed', 'checks': deepcopy(self.checks), **overrides}

    def cleanup(self, observations, finish=None):
        def observe(session, stage):
            if stage == 'cleanup-finally':
                session.state['gameProcessObservations'] = deepcopy(observations)

        def complete(session):
            session.state.update(restored=True, collectionComplete=True)
            if finish is not None:
                finish(session.state)

        with patch.object(runner.Session, 'observe_game_exit', observe), \
             patch.object(runner.Session, '_cleanup', complete), \
             patch.object(runner.Session, 'close_game_exit_tracker') as close:
            self.session.cleanup()
            close.assert_called_once_with(self.session)

    def test_final_nonzero_fails_a_successful_scenario_and_keeps_checks(self):
        self.cleanup([self.nonzero, self.unavailable])
        state = self.session.state
        self.assertEqual(state['result'], 'failed')
        self.assertEqual(state['scenarioResult'], 'passed')
        self.assertIsNone(state['scenarioReason'])
        self.assertEqual(state['checks'], self.checks)
        self.assertEqual(state['gameTermination']['kind'], 'abnormal_exit')
        self.assertEqual(state['gameTermination']['exitCode'], ABNORMAL)
        self.assertTrue(state['restored'])
        self.assertTrue(state['collectionComplete'])
        self.assertIn('0xC0000005', state['reason'])
        self.assertNotIn('crash', state['reason'])
        with TemporaryDirectory() as temp:
            self.session.dir = Path(temp)
            self.session.report()
            result = json.loads((self.session.dir / 'result.json').read_bytes())
            self.assertEqual(result['scenarioResult'], 'passed')
            self.assertEqual(result['result'], 'failed')
            self.assertEqual(result['checks'], self.checks)
            self.assertIn('Scenario result: **passed**', (self.session.dir / 'report.md').read_text())
            self.assertTrue((self.session.dir / 'run-review.json').is_file())

    def test_an_earlier_failure_and_collection_reason_are_preserved(self):
        self.session.state.update(result='failed', reason='Subject assertion failed')
        self.cleanup([self.nonzero], finish=lambda state: state.update(
            reason='Subject assertion failed. Evidence collection incomplete.', collectionComplete=False))
        self.assertEqual(self.session.state['scenarioResult'], 'failed')
        self.assertEqual(self.session.state['scenarioReason'], 'Subject assertion failed')
        self.assertIn('Evidence collection incomplete', self.session.state['reason'])
        self.assertIn('0xC0000005', self.session.state['reason'])

    def test_zero_missing_foreign_unretained_and_conflicting_codes_stay_legacy(self):
        foreign = {**self.identity, 'birth': self.identity['birth'] + 1}
        for rows in ([self.zero], [], [self.unavailable], [self.nonzero, self.zero],
                     [{**self.nonzero, 'identity': foreign, 'expectedIdentity': foreign}],
                     [{**self.nonzero, 'handleRetained': False}]):
            with self.subTest(rows=rows):
                self.session.state = self.state()
                self.cleanup(rows)
                self.assertEqual(self.session.state['result'], 'passed')
                self.assertNotIn('scenarioResult', self.session.state)
                self.assertNotIn('gameTermination', self.session.state)

    def test_vr_policy_requires_owned_game_and_leaves_se_unchanged(self):
        for overrides in ({'owned': []}, {'configuration': {'game_edition': 'se'}}):
            with self.subTest(overrides=overrides):
                self.session.state = self.state(**overrides)
                self.cleanup([self.nonzero])
                self.assertEqual(self.session.state['result'], 'passed')
                self.assertNotIn('scenarioResult', self.session.state)

    def test_known_tool_forced_stop_preserves_its_label_and_recovery_is_idempotent(self):
        self.session.state.update(forcedGameStop=True)
        self.cleanup([self.nonzero])
        self.cleanup([self.nonzero])
        self.assertEqual(self.session.state['scenarioResult'], 'passed')
        self.assertEqual(self.session.state['gameTermination']['kind'], 'forced_stop')
        self.assertEqual(self.session.state['reason'].count('0xC0000005'), 1)
