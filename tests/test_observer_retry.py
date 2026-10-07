"""Only structured, not-started observer reads may retry within their step bound."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import runner, scenarios

class ObserverRetryTests(unittest.TestCase):
    class Session:
        def __init__(self, directory, replies):
            self.dir = Path(directory)
            self.state = {'checks': []}
            self.replies = iter(replies)
            self.calls = []
            self.logs = []
        def phase(self, *args): pass
        def save(self): pass
        def log(self, *args, **kwargs): self.logs.append((args, kwargs))
        def tool(self, name, args, timeout, deadline=None):
            self.calls.append((name, args, timeout))
            reply = next(self.replies)
            if isinstance(reply, Exception): raise reply
            return reply
    def scenario(self, **changes):
        step = {'name': 'world after load', 'tool': 'inspect',
                'args': {'kind': 'world_observer'}, 'poll': True, 'timeout': 5,
                'assert': [{'path': 'ok', 'equals': True}]}
        step.update(changes)
        return {'steps': [step]}
    def abandoned(self, tool='inspect', args=None, outcome='abandoned_before_start'):
        return runner.ToolError(tool, args or {'kind': 'world_observer'},
                                {'ok': False, 'error': 'queued read expired', 'outcome': outcome})
    def test_known_readonly_abandonment_retries_and_retains_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.Session(directory, [self.abandoned(), {'ok': True}])
            with patch.object(scenarios.time, 'sleep'):
                scenarios.execute(session, self.scenario())
            self.assertEqual(len(session.calls), 2)
            self.assertEqual(session.logs[0][1]['result']['outcome'], 'abandoned_before_start')
            self.assertEqual(session.state['checks'][0]['result'], 'passed')
    def test_mutation_capabilities_and_nonpoll_reads_are_never_retried(self):
        cases = [{'tool': 'game', 'args': {'action': 'load'}},
                 {'args': {'kind': 'world_observer', 'action': 'capabilities'}},
                 {'poll': False}]
        for changes in cases:
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as directory:
                scenario = self.scenario(**changes)
                step = scenario['steps'][0]
                session = self.Session(directory, [self.abandoned(step['tool'], step['args'])])
                with self.assertRaises(runner.ToolError): scenarios.execute(session, scenario)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(session.state['checks'][0]['result'], 'failed')
    def test_unknown_structured_and_unstructured_failures_are_never_retried(self):
        for error in (self.abandoned(outcome='read_started_result_unavailable'),
                      self.abandoned(outcome='rejected'), RuntimeError('abandoned_before_start')):
            with self.subTest(error=str(error)), tempfile.TemporaryDirectory() as directory:
                session = self.Session(directory, [error])
                with self.assertRaises(RuntimeError): scenarios.execute(session, self.scenario())
                self.assertEqual(len(session.calls), 1)
    def test_abandonment_at_deadline_does_not_start_a_second_call(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.Session(directory, [self.abandoned()])
            with patch.object(scenarios.time, 'monotonic', side_effect=[0, 0, 5]):
                with self.assertRaises(TimeoutError): scenarios.execute(session, self.scenario())
            self.assertEqual(len(session.calls), 1)
            self.assertEqual(session.state['checks'][0]['observation']['outcome'], 'abandoned_before_start')
    def test_success_after_retry_arriving_late_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            session = self.Session(directory, [self.abandoned(), {'ok': True}])
            with patch.object(scenarios.time, 'monotonic', side_effect=[0, 0, 1, 2, 6]), patch.object(scenarios.time, 'sleep'):
                with self.assertRaisesRegex(TimeoutError, 'after deadline'):
                    scenarios.execute(session, self.scenario())
            self.assertEqual(len(session.calls), 2)
            self.assertEqual(session.state['checks'][0]['result'], 'failed')
    def test_tool_error_preserves_structured_owned_response_after_identity_check(self):
        with tempfile.TemporaryDirectory() as directory:
            session = runner.Session(directory, {'port': 1, 'game': {'pid': 42}})
            result = {'ok': False, 'error': 'queued read expired', 'outcome': 'abandoned_before_start'}
            with patch.object(runner, 'request', side_effect=[{'pid': 42}, result]), patch.object(runner.native, 'alive', return_value=True):
                with self.assertRaises(runner.ToolError) as raised:
                    session.tool('inspect', {'kind': 'world_observer'})
            self.assertEqual(raised.exception.result, result)
            self.assertEqual(raised.exception.tool, 'inspect')
            self.assertIn('abandoned_before_start', (Path(directory)/'steps.jsonl').read_text(encoding='utf-8'))

if __name__ == '__main__': unittest.main()
