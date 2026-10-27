import copy
import json
from pathlib import Path
import runpy
import tempfile
import unittest

from skyrim_autotest import scenarios, semantic_companion as bridge
from tools import prepare_semantic_companion as prepare
from tests import test_subject_companion as transport_fixture


def spec(steps=None):
    steps = copy.deepcopy(steps or [
        {'name': 'fixture-ready', 'tool': 'platform', 'args': {'operation': 'state.read'}, 'timeout': 3,
         'assert': [{'path': 'world.ready', 'equals': True}]},
        {'name': 'first-subject-read', 'tool': 'platform', 'args': {'operation': 'world.read', 'request': {'domain': 'actor-fixture-identity', 'actor': {'fixtureTag': 'NPC'}}},
         'timeout': 3, 'poll': True, 'assert': [{'path': 'actor.sex', 'equals': 'female'}]},
        {'name': 'owned-action', 'tool': 'platform', 'args': {'operation': 'object.perform', 'request': {'domain': 'morph-link', 'action': 'clear-own', 'actor': {'fixtureTag': 'NPC'}}},
         'timeout': 3, 'observe': True, 'assert': []}])
    return {'schemaVersion': 1, 'interface': bridge.INTERFACE, 'subjectOrderSha256': 'a' * 64,
        'originalTesting': {'start': {'kind': 'check', 'name': steps[1]['name']},
            'checks': [{'name': step['name'], 'role': 'subject' if index == 1 else 'fixture'} for index, step in enumerate(steps)]},
        'scenario': {'schemaVersion': 1, 'cell': 'QASmoke', 'startMode': 'new-game', 'steps': steps},
        'bounds': {'maximumSeconds': 20, 'maximumCommands': 32}, 'provenance': {'sourcePlanSha256': 'b' * 64}}


class Clock:
    def __init__(self): self.now = 0
    def __call__(self): return self.now
    def pause(self, duration): self.now += duration


class InterpreterTests(unittest.TestCase):
    def test_native_assertion_semantics_match_nested_json_bool_numbers_and_unknowns(self):
        cases = [({'value': True}, {'path': 'value', 'equals': 1}),
                 ({'value': {'x': [False, 3]}}, {'path': 'value', 'equals': {'x': [0, 3]}}),
                 ({'value': {'x': [2, 3]}}, {'path': 'value', 'equals': {'x': [2.0, 3]}}),
                 ({'value': None}, {'path': 'value', 'max': .0001}),
                 ({'value': None}, {'path': 'value', 'exists': False}),
                 ({'value': [1, 2]}, {'path': 'value', 'type': 'number[]'}),
                 ({'value': 'Unicode имя'}, {'path': 'value', 'contains': 'имя'}),
                 ({'value': -2}, {'path': 'value', 'min': -3})]
        for raw, rule in cases:
            with self.subTest(raw=raw, rule=rule): self.assertEqual(bridge.check(raw, rule), scenarios.check(raw, rule))
        unavailable = bridge.assertion_results({}, [{'path': 'missing', 'exists': False}])[0]
        self.assertFalse(unavailable['passed']); self.assertFalse(unavailable['available'])

    def test_read_polling_preserves_original_roles_and_emits_final_assertions_only(self):
        selected = spec(); clock = Clock(); calls, events = [], []; reads = 0
        def exchange(envelope):
            nonlocal reads
            calls.append(copy.deepcopy(envelope))
            if envelope['operation'] == 'finish': return {'outcome': 'owner-finished'}
            operation = envelope['args']['operation']
            if operation == 'state.read': return {'world': {'ready': True}}
            if operation == 'world.read':
                reads += 1
                return {'actor': {'sex': None if reads == 1 else 'female'}}
            return {'request': {'admitted': True}}
        result = bridge.run_plan(selected, exchange, events.append, clock=clock, pause=clock.pause)
        self.assertEqual(result['originalTesting'], selected['originalTesting'])
        self.assertEqual([step['result'] for step in result['steps']], ['passed', 'passed', 'observed'])
        self.assertEqual(result['steps'][1]['attempts'], 2)
        self.assertFalse(result['steps'][0]['originalSubjectStart']); self.assertTrue(result['steps'][1]['originalSubjectStart'])
        self.assertEqual(sum(call['args']['operation'] == 'object.perform' for call in calls if call['operation'] == 'tool'), 1)
        self.assertEqual(sum(call['operation'] == 'finish' for call in calls), 1)
        self.assertEqual({event['kind'] for event in events}, {'check-start', 'measurement', 'assertion', 'check-result'})
        subject_assertions = [event for event in events if event['kind'] == 'assertion' and event['caseId'] == 'first-subject-read']
        self.assertEqual(len(subject_assertions), 1); self.assertEqual(subject_assertions[0]['outcome'], 'passed')
        observed = next(event for event in events if event['kind'] == 'check-result' and event['caseId'] == 'owned-action')
        self.assertEqual(observed['semanticResult'], 'observed')
        self.assertTrue(any(event.get('assertionRole') == 'transport' for event in events))

    def test_known_mismatch_finishes_once_and_never_executes_remaining_mutation(self):
        calls, events = [], []; clock = Clock()
        def exchange(envelope):
            calls.append(envelope)
            return {'outcome': 'owner-finished'} if envelope['operation'] == 'finish' else {'world': {'ready': False}}
        result = bridge.run_plan(spec(), exchange, events.append, clock=clock, pause=clock.pause)
        self.assertEqual(result['outcome'], 'mismatch')
        self.assertEqual([step['result'] for step in result['steps']], ['failed', 'not_run', 'not_run'])
        self.assertEqual(len(calls), 2); self.assertEqual(calls[-1]['operation'], 'finish')

    def test_uncertain_mutation_stops_without_replay_or_finish(self):
        selected = spec(); selected['scenario']['steps'][1].update(poll=False, **{'assert': []}, observe=True)
        selected['scenario']['steps'][1]['args'] = copy.deepcopy(selected['scenario']['steps'][2]['args'])
        calls, events = [], []; clock = Clock()
        def exchange(envelope):
            calls.append(copy.deepcopy(envelope))
            if envelope['args']['operation'] == 'object.perform': raise TimeoutError('Unknown delivered mutation')
            return {'world': {'ready': True}}
        with self.assertRaisesRegex(TimeoutError, 'Unknown delivered'):
            bridge.run_plan(selected, exchange, events.append, clock=clock, pause=clock.pause)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(call['operation'] == 'finish' for call in calls))
        self.assertTrue(any(event.get('semanticResult') == 'unavailable' for event in events))
        self.assertTrue(any(event.get('semanticResult') == 'not_run' for event in events))

    def test_absolute_read_deadline_and_late_response_do_not_retry(self):
        selected = spec(); clock = Clock(); calls = []
        def exchange(envelope):
            calls.append(envelope); clock.now += 4
            return {'world': {'ready': True}}
        with self.assertRaisesRegex(TimeoutError, 'original absolute deadline'):
            bridge.run_plan(selected, exchange, lambda event: None, clock=clock, pause=clock.pause)
        self.assertEqual(len(calls), 1)

    def test_mutation_poll_startup_tool_and_unresolved_state_are_refused(self):
        for mutate in (lambda value: value['scenario']['steps'][2].update(poll=True),
                       lambda value: value['scenario']['steps'][0].update(tool='console'),
                       lambda value: value['scenario']['steps'][0]['args'].update(request={'$state': 'oldNPC'})):
            selected = spec(); mutate(selected)
            with self.assertRaises(ValueError): bridge.validate_spec(selected)

    def test_render_is_deterministic_and_standalone_without_new_runtime_imports(self):
        selected = spec()
        self.assertEqual(bridge.render(selected), bridge.render(copy.deepcopy(selected)))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sequencer.py'; path.write_text(bridge.render(selected), encoding='utf-8')
            loaded = runpy.run_path(str(path))
            self.assertEqual(json.loads(loaded['_SEMANTIC_SPEC_JSON']), selected)
            self.assertTrue(callable(loaded['run']))

    def test_frozen_generic_companion_accepts_all_standard_wrapper_records(self):
        selected = spec(); selected['scenario']['steps'][0].pop('assert'); selected['scenario']['steps'][0]['observe'] = True
        selected['scenario']['steps'][1]['assert'] = [{'path': 'world.ready', 'equals': True}]
        selected['scenario']['steps'][1]['args'] = {'operation': 'state.read'}
        selected['scenario']['steps'] = selected['scenario']['steps'][:2]
        selected['originalTesting']['checks'] = selected['originalTesting']['checks'][:2]
        with tempfile.TemporaryDirectory() as folder:
            fixture = transport_fixture.Fixture(Path(folder), cases=tuple(step['name'] for step in selected['scenario']['steps']))
            fixture.plan.write_bytes(transport_fixture.tool.encoded({'checks': [{'name': row['name'], 'role': 'subject'} for row in selected['scenario']['steps']],
                'bounds': selected['bounds'], 'fixture': {'cell': 'QASmoke'}, 'semantic': selected}))
            fixture.sequencer.write_text(bridge.render(selected), encoding='utf-8')
            fixture.client.result = {'world': {'ready': True}}
            client = fixture.companion(ready=False)
            self.assertEqual(client.execute(), 0)
            self.assertTrue(client.report['completed'])
            self.assertEqual(client.report['subjectStart']['caseId'], 'fixture-ready')  # Explicit technical boundary only.
            original = transport_fixture.tool.decoded(Path(client.report['originResult']['path']).read_bytes())
            self.assertEqual(original['originalTesting']['start']['name'], 'first-subject-read')
            self.assertEqual(original['steps'][0]['result'], 'observed')
            self.assertFalse(original['originAcceptanceClaimed'])


class PreparationTests(unittest.TestCase):
    def test_preparation_keeps_original_bytes_and_rejects_changed_compilation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); order_path = root / 'order.json'; mapping_path = root / 'mapping.json'; compiled_path = root / 'compiled.json'
            order = {'schemaVersion': 2, 'id': 'original', 'subjectPlan': {'interface': 'polygon-actions/1', 'fixture': {'cell': 'QASmoke', 'startMode': 'new-game'},
                'steps': [{'name': 'fixture-ready', 'operation': 'state.read', 'assert': [{'field': 'world.ready', 'equals': True}]},
                          {'name': 'subject-ready', 'operation': 'state.read', 'assert': [{'field': 'world.ready', 'equals': True}]}]},
                'testing': {'start': {'kind': 'check', 'name': 'subject-ready'}, 'checks': [{'name': 'fixture-ready', 'role': 'fixture'}, {'name': 'subject-ready', 'role': 'subject'}]}}
            mapping = {'operations': {'state.read': {'tool': 'platform', 'args': {'operation': 'state.read'}, 'fields': {'world.ready': 'world.ready'}}}}
            compiled = prepare.compile_scenario(order, mapping)
            for path, value in ((order_path, order), (mapping_path, mapping), (compiled_path, compiled)): path.write_text(json.dumps(value), encoding='utf-8')
            before = order_path.read_bytes()
            receipt = prepare.prepare(order_path, mapping_path, compiled_path, root / 'generated', 20, 32)
            self.assertEqual(order_path.read_bytes(), before)
            self.assertFalse(receipt['admitted']); self.assertEqual(receipt['nativeStarts'], 0)
            execution = json.loads((root / 'generated/execution-plan.json').read_text())
            self.assertEqual(execution['semantic']['originalTesting'], order['testing'])
            self.assertEqual(execution['semantic']['scenario'], compiled)
            with self.assertRaisesRegex(ValueError, 'never overwrite'): prepare.prepare(order_path, mapping_path, compiled_path, root / 'generated', 20)
            compiled['steps'][1]['assert'][0]['equals'] = False; compiled_path.write_text(json.dumps(compiled))
            with self.assertRaisesRegex(ValueError, 'differs'): prepare.prepare(order_path, mapping_path, compiled_path, root / 'rejected', 20)


if __name__ == '__main__': unittest.main()
