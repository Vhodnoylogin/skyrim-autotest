"""Finite native policy composes with the real scenario/platform/morph dispatch."""
import copy
from contextlib import ExitStack, nullcontext
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import config, interactive_bindings, native_session, platform, runner
if __package__:
    from . import test_morph_session as fixtures
else:
    import test_morph_session as fixtures


def finite_configuration(root):
    value = config.template('se')
    for key in config.PATH_KEYS:
        if value.get(key):
            value[key] = str(root / key)
    value['native_session'] = copy.deepcopy(fixtures.Session().state['configuration']['interactive_session'])
    return value


class NativeSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        previous = copy.deepcopy(config.P.value)
        previous_root, previous_runs = runner.ROOT, runner.RUNS
        self.addCleanup(lambda: setattr(config.P, 'value', previous))
        self.addCleanup(lambda: setattr(runner, 'ROOT', previous_root))
        self.addCleanup(lambda: setattr(runner, 'RUNS', previous_runs))

    def test_finite_configuration_requires_exact_native_policy_and_no_manual_fields(self):
        value = finite_configuration(self.root)
        accepted = config.configure(value)
        self.assertNotIn('interactive_session', accepted)
        self.assertEqual(native_session.settings(accepted)['nativeBindings'], fixtures.policy())
        for settings in ({}, {'nativeBindings': None}, {'nativeBindings': {}},
                         {**value['native_session'], 'npcPersistence': 1},
                         {**value['native_session'], 'channelConfig': str(self.root / 'channel.json')},
                         {**value['native_session'], 'maximumSeconds': 30}):
            with self.subTest(settings=settings), self.assertRaises(config.ConfigurationError):
                config.configure(dict(value, native_session=settings))
        wrong = copy.deepcopy(value)
        wrong['native_session']['morphSession']['bindings']['status'] = 'clear'
        with self.assertRaises(config.ConfigurationError): config.configure(wrong)

    def test_ambiguity_never_falls_back_and_frozen_binding_mismatch_still_refuses(self):
        value = finite_configuration(self.root)
        ambiguous = dict(value, interactive_session={})
        with self.assertRaisesRegex(config.ConfigurationError, 'mutually exclusive'): config.configure(ambiguous)
        with self.assertRaisesRegex(ValueError, 'mutually exclusive'): native_session.settings(ambiguous)
        session = fixtures.Session()
        session.state['configuration'] = config.configure(value)
        changed = fixtures.policy()
        changed['allowedRaceForms'] = [fixtures.HUMAN]
        with self.assertRaisesRegex(ValueError, 'frozen run configuration'):
            interactive_bindings.frozen_policy(session, changed)
        del session.state['configuration']['native_session']
        with self.assertRaisesRegex(ValueError, 'disabled'):
            interactive_bindings.frozen_policy(session, fixtures.policy())

    def run_finite(self, *, bad_identity=False, lost_response=False):
        """Only native lifecycle/transport boundaries are synthetic; domain code runs."""
        sessions = []
        request = {'domain': 'human-preset', 'action': 'unassign', 'actor': {'fixtureTag': 'Fixture'}}
        scenario = {'schemaVersion': 1, 'cell': 'QASmoke', 'steps': [
            {'name': 'unassign once', 'tool': 'platform', 'timeout': 10,
             'assert': [{'path': 'request.assignmentAccepted', 'equals': True}],
             'args': {'operation': 'object.perform', 'request': request}},
            {'name': 'read actual provider state', 'tool': 'platform', 'timeout': 10,
             'assert': [{'path': 'human.assignedPreset', 'equals': ''}],
             'args': {'operation': 'world.read', 'request': {
                 'domain': 'human-preset-state', 'actor': {'fixtureTag': 'Fixture'}}}}]}
        path = self.root / 'scenario.json'
        path.write_text(json.dumps(scenario), encoding='utf-8')

        class OwnedFixtureSession(fixtures.Session):
            def __init__(self, directory, state):
                super().__init__()
                native_state = self.state
                for key, value in native_state.items():
                    if key not in ('id', 'configuration', 'activeSemanticCommandId'):
                        state[key] = copy.deepcopy(value)
                self.state, self.dir = state, directory
                for fixture in state['interactiveActorFixtures'].values():
                    fixture['runId'] = fixture['creationWitness']['runId'] = state['id']
                state['port'] = 1
                state['initialWorldTransition'] = {'completed': True, 'afterGame': copy.deepcopy(state['game']),
                    'worldGeneration': state['ownedWorldGeneration'], 'cursor': 0}
                self.unsafe_guard, self.fail_mutation = bad_identity, lost_response
                self.cleaned = False
                sessions.append(self)
            def phase(self, name, seconds=120): self.state['phase'] = name
            def heartbeat(self): pass
            def setup(self): pass
            def launch(self): pass
            def cleanup(self): self.cleaned = self.state['restored'] = True
            def finish_heartbeat(self, thread): thread.join(1)
            def report(self): pass
            def reopen_mo2(self): pass
            def tool(self, tool, args, timeout=12, deadline=None):
                if tool == 'platform': return platform.execute(self, args, deadline)
                return super().tool(tool, args, timeout, deadline)

        runner.configure(finite_configuration(self.root))
        previous_runs = runner.RUNS
        with ExitStack() as stack:
            stack.enter_context(patch.object(runner, 'RUNS', self.root / 'runs'))
            stack.enter_context(patch.object(runner, 'recover'))
            stack.enter_context(patch.object(runner, 'preflight', return_value={}))
            stack.enter_context(patch.object(runner, 'Session', OwnedFixtureSession))
            stack.enter_context(patch.object(runner.native, 'SessionMutex', return_value=nullcontext()))
            stack.enter_context(patch.object(runner.native, 'identity', return_value={'pid': 1}))
            stack.enter_context(patch.object(runner.native, 'alive', return_value=True))
            stack.enter_context(patch.object(runner, 'request', return_value={'events': [], 'headSeq': 0}))
            stack.enter_context(patch.object(runner.subprocess, 'Popen'))
            stack.enter_context(patch('skyrim_autotest.bootstrap.prepare_gameplay'))
            held = stack.enter_context(patch('skyrim_autotest.interactive.run'))
            channel = stack.enter_context(patch('skyrim_autotest.command_endpoint.load_config'))
            stack.enter_context(patch('builtins.print'))
            code = runner.run('Fixture', path)
            held.assert_not_called()
            channel.assert_not_called()
        self.assertEqual(runner.RUNS, previous_runs)
        session = sessions[0]
        self.assertTrue(session.cleaned and session.state['done'] and session.state['restored'])
        self.assertNotIn('activeSemanticCommandId', session.state)
        return code, session, request

    def test_real_finite_runner_native_morph_dispatch_terminates_and_cleanup_runs(self):
        code, session, request = self.run_finite()
        self.assertEqual(code, 0, session.state.get('reason'))
        self.assertEqual(session.state['result'], 'passed')
        self.assertEqual(len(session.state['checks']), 2)
        self.assertEqual(session.state['morphSession']['mutations'][0]['request'], request)
        calls = [args for tool, args in session.calls if tool == 'morph_provider' and args['action'] == 'unassign_preset']
        self.assertEqual(len(calls), 1)
        # Reusing the same frozen ordinary step cannot obtain a fresh mutation ID.
        from skyrim_autotest.scenarios import scenario_platform_call
        from skyrim_autotest.restart_budget import step_identity
        step = session.state['scenario']['steps'][0]
        session.state['activeScenarioStep'] = step_identity('steps', 0, step)
        with patch.object(runner.native, 'alive', return_value=True), \
             patch.object(runner, 'request', return_value={'events': [], 'headSeq': 0}), \
             self.assertRaisesRegex(ValueError, 'already attempted'):
            scenario_platform_call(session, step, 10, time.monotonic() + 10)
        self.assertEqual(sum(tool == 'morph_provider' and args['action'] == 'unassign_preset' for tool, args in session.calls), 1)

    def test_bad_identity_and_lost_response_do_not_become_success_or_retry(self):
        for bad_identity, lost_response in ((True, False), (False, True)):
            with self.subTest(bad_identity=bad_identity, lost_response=lost_response):
                code, session, _ = self.run_finite(bad_identity=bad_identity, lost_response=lost_response)
                self.assertEqual(code, 1)
                self.assertEqual(session.state['result'], 'failed')
                calls = [args for tool, args in session.calls if tool == 'morph_provider' and args['action'] == 'unassign_preset']
                self.assertEqual(len(calls), int(lost_response))


if __name__ == '__main__': unittest.main()
