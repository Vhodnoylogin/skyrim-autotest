import tempfile
import unittest
from pathlib import Path

from skyrim_autotest import scenarios, morph_session


class Session:
    def __init__(self, directory, fail=False):
        self.dir = Path(directory)
        self.state = {'checks': []}
        self.calls, self.persisted = [], []
        self.fail = fail

    def phase(self, *_): pass
    def save(self): self.persisted.append(self.state.get('activeSemanticCommandId'))
    def log(self, *_args, **_kwargs): pass

    def tool(self, name, args, **kwargs):
        command = self.state['activeSemanticCommandId']
        self.calls.append(command)
        morph_session._begin(self, args['request'])
        if self.fail: raise TimeoutError('uncertain original mutation')
        return {'action': {'completed': True}}


class SemanticScenarioTests(unittest.TestCase):
    def plan(self):
        return {'schemaVersion': 1, 'steps': [{'name': 'change-once', 'tool': 'platform',
            'args': {'operation': 'object.perform', 'request': {'domain': 'actor-race'}},
            'assert': [{'path': 'action.completed', 'equals': True}]}]}

    def test_standard_scenario_persists_identity_and_cleans_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory)
            scenarios.execute(session, self.plan())
            self.assertTrue(session.calls[0].startswith('scenario-'))
            self.assertIn(session.calls[0], session.persisted)
            self.assertNotIn('activeSemanticCommandId', session.state)
            self.assertEqual(session.state['checks'][0]['result'], 'passed')

    def test_uncertain_step_does_not_gain_fresh_identity_on_reentry(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory, fail=True)
            with self.assertRaises(TimeoutError): scenarios.execute(session, self.plan())
            self.assertNotIn('activeSemanticCommandId', session.state)
            session.fail = False
            with self.assertRaisesRegex(ValueError, 'already attempted'):
                scenarios.execute(session, self.plan())
            self.assertEqual(session.calls[0], session.calls[1])
            self.assertEqual(len(session.state['morphSession']['mutations']), 1)

    def test_existing_operator_command_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory)
            session.state['activeSemanticCommandId'] = 'existing-operator-command'
            with self.assertRaisesRegex(ValueError, 'replace'):
                scenarios.execute(session, self.plan())
            self.assertEqual(session.state['activeSemanticCommandId'], 'existing-operator-command')
            self.assertEqual(session.calls, [])

    def test_cleanup_disk_failure_preserves_original_uncertain_mutation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(directory, fail=True)
            def save():
                session.persisted.append(session.state.get('activeSemanticCommandId'))
                if len(session.persisted) >= 3:
                    raise OSError('cleanup disk full')
            session.save = save
            from skyrim_autotest.restart_budget import step_identity
            import time
            step = self.plan()['steps'][0]
            session.state['activeScenarioStep'] = step_identity('steps', 0, step)
            with self.assertRaisesRegex(TimeoutError, 'uncertain original mutation') as failure:
                scenarios.scenario_platform_call(session, step, 5, time.monotonic() + 5)
            self.assertIn('cleanup disk full', str(failure.exception.__notes__))
            self.assertNotIn('activeSemanticCommandId', session.state)
            self.assertEqual(len(session.state['morphSession']['mutations']), 1)
