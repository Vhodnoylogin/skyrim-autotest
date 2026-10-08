import copy
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from skyrim_autotest import boundary_collection as bc, config, runner, scenarios


def scenario():
    return {'schemaVersion': 1, 'steps': [
        {'name': 'settled', 'tool': 'inspect', 'args': {'kind': 'scene'},
         'assert': [{'path': 'ready', 'equals': True}]},
        {'name': 'next', 'tool': 'inspect', 'args': {'kind': 'scene'},
         'assert': [{'path': 'ready', 'equals': True}]}]}


def plan(count=2):
    steps = scenario()['steps']
    return {'schemaVersion': 1, 'scenarioSha256': 'a'*64, 'boundaryBudgetSeconds': 10,
        'requests': [{'id': 'SUP-'+str(i),
            'after': {'index': 0, 'name': steps[0]['name'], 'stepSha256': bc.digest(steps[0])},
            'before': {'index': 1, 'name': steps[1]['name'], 'stepSha256': bc.digest(steps[1])},
            'review': {'settled': True, 'reason': 'No active motion or callback timing assertion'},
            'args': {'operation': 'player.read'}, 'timeout': 5} for i in range(count)]}


class Session:
    def __init__(self, directory, p):
        self.dir = directory
        self.state = {'id': 'run-a', 'game': {'pid': 1, 'birth': 9},
                      'ownedWorldGeneration': 2, 'scenario': scenario(), 'scenarioHash': 'a'*64,
                      'configuration': {'boundary_collection': p}, 'checks': []}
        self.calls = []
        self.logs = []
        self.response = {'available': False, 'reason': 'No native domain'}
    def save(self): pass
    def phase(self, *args): pass
    def log(self, *args, **kwargs): self.logs.append((args, kwargs))
    def tool(self, tool, args, **kwargs):
        self.calls.append((tool, args))
        return copy.deepcopy(self.response)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.session = Session(self.path, plan())
        bc.initialize(self.session, plan())
        self.guard = patch('skyrim_autotest.platform.Backend.guard_world')
        self.guard.start()
    def tearDown(self):
        self.guard.stop()
        self.temp.cleanup()
    def run_boundary(self):
        bc.after_step(self.session, 0, scenario()['steps'][0])
    def records(self): return self.session.state['boundaryCollection']['requests']

    def test_response_availability_preserved_without_assertions_or_native_clock_claim(self):
        self.run_boundary()
        self.assertEqual([r['status'] for r in self.records()], ['response_recorded']*2)
        raw = json.loads((self.path/self.records()[0]['evidence']['name']).read_text())
        self.assertFalse(raw['response']['available'])
        self.assertEqual(raw['before']['game'], {'pid': 1, 'birth': 9})
        self.assertIn('not mapped', raw['hostClock']['basis'])
        self.assertEqual(self.session.state['checks'], [])
        self.assertEqual(len(self.session.calls), 2)

    def test_replay_never_dispatches_again(self):
        self.run_boundary()
        with self.assertRaisesRegex(ValueError, 'replayed'): self.run_boundary()
        self.assertEqual(len(self.session.calls), 2)
        with self.assertRaisesRegex(ValueError, 'reinitialized'): bc.initialize(self.session, plan())

    def test_changed_step_or_main_pin_refuses_before_any_call(self):
        self.session.state['scenario']['steps'][1]['args']['extra'] = True
        with self.assertRaisesRegex(ValueError, 'checkpoint'): self.run_boundary()
        self.assertEqual(self.session.calls, [])
        self.session.state['scenario'] = scenario()
        self.session.state['scenarioHash'] = 'b'*64
        with self.assertRaisesRegex(ValueError, 'pin mismatch'): self.run_boundary()
        self.assertEqual(self.session.calls, [])

    def test_game_world_change_during_read_is_unavailable_and_terminal(self):
        def call(*args, **kwargs):
            self.session.state['ownedWorldGeneration'] += 1
            return {'x': 7}
        self.session.tool = call
        with self.assertRaisesRegex(ValueError, 'identity changed'): self.run_boundary()
        self.assertEqual([r['status'] for r in self.records()], ['unavailable', 'not_run'])
        self.assertTrue((self.path/self.records()[0]['evidence']['name']).exists())

    def test_mutable_config_cannot_change_durably_pinned_request(self):
        p = self.session.state['configuration']['boundary_collection']
        p['requests'][0]['timeout'] = 4
        with self.assertRaisesRegex(ValueError, 'durable plan'): self.run_boundary()
        self.assertEqual(self.session.calls, [])

    def test_native_guard_failure_is_recorded_without_tool_request(self):
        with patch('skyrim_autotest.platform.Backend.guard_world', side_effect=ValueError('cursor gap')):
            with self.assertRaisesRegex(ValueError, 'cursor gap'): self.run_boundary()
        self.assertEqual(self.session.calls, [])
        self.assertEqual(self.records()[0]['status'], 'unavailable')

    def test_tool_error_retains_raw_and_does_not_retry_or_continue(self):
        def call(*args, **kwargs): raise runner.ToolError('inspect', {}, {'error': 'native unavailable'})
        self.session.tool = call
        with self.assertRaises(runner.ToolError): self.run_boundary()
        raw = json.loads((self.path/self.records()[0]['evidence']['name']).read_text())
        self.assertEqual(raw['error']['providerResponse'], {'error': 'native unavailable'})
        self.assertEqual(self.records()[1]['status'], 'not_run')

    def test_shared_deadline_does_not_dispatch_missed_requests(self):
        with patch.object(bc.time, 'monotonic', side_effect=[0, 20, 20]): self.run_boundary()
        self.assertEqual(self.session.calls, [])
        self.assertTrue(all(r['status'] == 'not_run' and 'exhausted' in r['reason'] for r in self.records()))

    def test_late_response_never_accepted(self):
        def call(*args, **kwargs):
            time.sleep(.025)
            return {'observed': True}
        p = self.session.state['configuration']['boundary_collection']
        p['requests'][0]['timeout'] = .01
        self.session.state['boundaryCollection']['planSha256'] = bc.digest(p)
        self.session.tool = call
        with self.assertRaises(TimeoutError): self.run_boundary()
        self.assertEqual(self.records()[0]['status'], 'unavailable')

    def test_finalize_keeps_never_reached_and_preserves_orphan_without_false_success(self):
        self.records()[0]['status'] = 'started'
        (self.path/'boundary-SUP-0.json').write_text('{"response":{"x":7}}')
        bc.finalize(self.session)
        self.assertEqual(self.records()[0]['status'], 'unavailable')
        self.assertIn('uncommitted', self.records()[0]['reason'])
        self.assertIn('sha256', self.records()[0]['evidence'])
        self.assertEqual(self.records()[1]['status'], 'not_run')

    def test_execution_orders_capture_between_successful_steps_without_main_check_inflation(self):
        events = []
        def call(tool, args, **kwargs):
            events.append(tool)
            return {'ready': True} if tool == 'inspect' else {'available': True}
        self.session.tool = call
        scenarios.execute(self.session, scenario())
        self.assertEqual(events, ['inspect', 'platform', 'platform', 'inspect'])
        self.assertEqual(len(self.session.state['checks']), 2)

    def test_failed_checkpoint_never_runs_capture(self):
        self.session.response = {'ready': False}
        with self.assertRaises(AssertionError): scenarios.execute(self.session, scenario())
        self.assertTrue(all(r['status'] == 'not_run' for r in self.records()))

    def test_reject_mutation_unknown_domain_timed_window_and_bad_boundaries(self):
        changes = [
            {'args': {'operation': 'object.perform', 'request': {'action': 'save_game'}}},
            {'args': {'operation': 'world.read', 'request': {'observation': 'invented'}}},
            {'args': {'operation': 'world.read', 'request': {'observation': 'hand.held_item',
                'hand': 'right', 'continuityWindowSeconds': 1}}},
            {'review': {'settled': False, 'reason': 'during queued task'}},
            {'timeout': float('nan')}, {'timeout': True}, {'args': {'operation': 'player.read', 'request': None}}]
        for change in changes:
            p = plan()
            p['requests'][0].update(change)
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                bc.validate(p, scenario(), 'a'*64)
        p = plan(); p['requests'][1]['id'] = p['requests'][0]['id']
        with self.assertRaisesRegex(ValueError, 'unique'): bc.validate(p)
        p = plan(); p['requests'][0]['before']['index'] = 2
        with self.assertRaisesRegex(ValueError, 'adjacent'): bc.validate(p)

    def test_invalid_config_refuses_before_recovery_or_setup(self):
        old = config.P.snapshot()
        try:
            config.P.value['boundary_collection'] = plan()
            path = self.path/'scenario.json'; path.write_text(json.dumps(scenario()))
            with patch.object(runner, 'recover') as recover:
                with self.assertRaisesRegex(ValueError, 'pin mismatch'): runner.run('profile', path)
                recover.assert_not_called()
            value = config.template(); value['boundary_collection'] = {'schemaVersion': 1}
            with self.assertRaises(config.ConfigurationError): config.configure(value)
        finally: config.P.value = old

    def test_final_collection_pins_plan_accounting_and_every_response(self):
        from skyrim_autotest.collection import collect
        self.run_boundary()
        old = config.P.snapshot()
        logs = self.path/'logs'; logs.mkdir()
        vrpaths = self.path/'vrpaths.json'; vrpaths.write_text(json.dumps({'log': [str(logs)]}))
        self.session.state['preflight'] = {'vrpaths': str(vrpaths)}
        try:
            config.P.value = dict(old, skse_logs=str(logs), mo2=str(self.path/'mo2'),
                                  overwrite=str(self.path/'overwrite'), collected_files=[])
            self.assertTrue(collect(self.session))
            manifest = json.loads((self.path/'evidence/manifest.json').read_text())
            self.assertEqual(len(manifest), 4)
            by_name = {e['name']: e for e in manifest}
            for r in self.records():
                self.assertEqual(by_name[r['evidence']['name']]['sha256'], r['evidence']['sha256'])
            self.assertTrue(self.session.state['collectionComplete'])
            (self.path/self.records()[0]['evidence']['name']).write_text('{"changed":true}')
            self.assertFalse(collect(self.session))
            self.assertTrue(any('digest mismatch' in e['error'] for e in self.session.state['collectionErrors']))
        finally: config.P.value = old


if __name__ == '__main__': unittest.main()
