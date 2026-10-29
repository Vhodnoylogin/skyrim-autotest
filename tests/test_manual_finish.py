"""The native runner's ordinary finalization keeps unresolved manual outcomes blocked."""
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import runner


class ManualFinishTests(unittest.TestCase):
    def test_owner_finish_with_uncertain_actions_is_not_passed(self):
        for uncertain in ([], ['uncertain-action']):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                root = Path(temporary)
                scenario = root / 'scenario.json'
                scenario.write_text(json.dumps({'schemaVersion': 1, 'cell': 'QASmoke', 'steps': []}), encoding='utf-8')
                sessions = []
                class FakeSession:
                    def __init__(self, directory, state):
                        self.state, self.dir = state, directory
                        self.cleaned = False
                        sessions.append(self)
                    def save(self): pass
                    def log(self, *args, **kwargs): pass
                    def heartbeat(self): pass
                    def setup(self): pass
                    def launch(self): pass
                    def cleanup(self):
                        self.cleaned = True
                        self.state['restored'] = True
                    def finish_heartbeat(self, thread): thread.join(1)
                    def report(self): pass
                    def reopen_mo2(self): pass
                settings = {'timeoutPolicy': 'preserve-manual'}
                stack.enter_context(patch.object(runner.P, 'value', {
                    'schemaVersion': 1, 'game_edition': 'se', 'interactive_session': settings,
                    'runtime': str(root / 'runtime')}))
                for target in ('configure', 'recover'):
                    stack.enter_context(patch.object(runner, target))
                stack.enter_context(patch.object(runner.native, 'SessionMutex', return_value=nullcontext()))
                stack.enter_context(patch.object(runner.native, 'identity', return_value={'pid': 123}))
                stack.enter_context(patch.object(runner, 'preflight', return_value={}))
                stack.enter_context(patch.object(runner, 'RUNS', root / 'runs'))
                stack.enter_context(patch.object(runner, 'Session', FakeSession))
                stack.enter_context(patch.object(runner.subprocess, 'Popen'))
                stack.enter_context(patch('skyrim_autotest.command_endpoint.managed_endpoint', return_value=nullcontext()))
                for target in ('skyrim_autotest.scenarios.validate', 'skyrim_autotest.editions.validate_scenario',
                               'skyrim_autotest.bootstrap.prepare_gameplay', 'skyrim_autotest.platform.initialize_controllers',
                               'skyrim_autotest.scenarios.execute'):
                    stack.enter_context(patch(target))
                held = stack.enter_context(patch('skyrim_autotest.interactive.run', return_value={
                    'reason': 'owner-finished', 'uncertainCommandIds': uncertain}))
                captures = stack.enter_context(patch('skyrim_autotest.actor_scene.finish_captures'))
                stack.enter_context(patch('builtins.print'))
                code = runner.run('Fixture', scenario)
                self.assertEqual(code, 1 if uncertain else 0)
                session = sessions[0]
                held.assert_called_once_with(session, settings)
                self.assertTrue(session.cleaned)
                self.assertTrue(session.state['done'])
                self.assertTrue(session.state['restored'])
                self.assertEqual(session.state['result'], 'blocked' if uncertain else 'passed')
                if uncertain:
                    captures.assert_not_called()
                    self.assertIn('uncertain command outcomes', session.state['reason'])
                    self.assertIn('no replay', session.state['reason'])
                else:
                    captures.assert_called_once_with(session)


if __name__ == '__main__': unittest.main()
