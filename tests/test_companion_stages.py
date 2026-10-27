"""Two real interpreter stages over the frozen companion and a temporary bus.

Only the game backend is fake: actual requests, events, child interpreter,
durable delivery/completion and owner finish use the existing transport.
"""
import copy
import json
from pathlib import Path
import runpy
import tempfile
import time
import unittest

from skyrim_autotest import morph_qualification as qualification, semantic_companion as semantic
from tests import test_subject_companion as transport
from tools import prepare_morph_qualification as prepare


BRIDGE_CASE = prepare.HELD_BRIDGE_CASE


def qualification_spec():
    actors = [{'tag': 'Fixture' + str(index), 'sex': 'female' if index % 2 else 'male',
        'displayName': 'Owned fixture ' + str(index), 'base': {'formId': '0x00000' + str(100 + index)},
        'humanRace': '0x00013746', 'humanPreset': 'Preset' + str(index),
        'placement': {'forwardGameUnits': 150, 'rightGameUnits': index * 30}} for index in range(6)]
    return {'actors': actors, 'catalogRequest': {'domain': 'human-preset-catalog'},
        'configurationRequest': {'domain': 'human-provider-config'},
        'presetsBySex': {sex: [a['humanPreset'] for a in actors if a['sex'] == sex] for sex in ('male', 'female')},
        'profiles': {sex: {'familyId': sex + '-family', 'rows': [], 'publicTargets': ['GenericTarget']} for sex in ('male', 'female')},
        'ownKey': 'Owned', 'beastRace': '0x000CDD84', 'testValues': [
            {'morph': 'HumanMorph', 'key': 'Fixture.Test.Foreign', 'value': -.35},
            {'morph': 'HumanMorph', 'key': 'Fixture.Test.Zero', 'value': 0},
            {'morph': 'BeastMorph', 'key': 'Fixture.Test.Beast', 'value': .2}]}


def semantic_spec():
    return {'schemaVersion': 1, 'interface': semantic.INTERFACE, 'subjectOrderSha256': 'a' * 64,
        'originalTesting': {'start': {'kind': 'check', 'name': BRIDGE_CASE},
            'checks': [{'name': BRIDGE_CASE, 'role': 'subject'}]},
        'scenario': {'schemaVersion': 1, 'cell': 'QASmoke', 'steps': [
            {'name': BRIDGE_CASE, 'tool': 'platform', 'args': {'operation': 'state.read'},
             'timeout': 3, 'assert': [{'path': 'world.ready', 'equals': True}]}]},
        'bounds': {'maximumSeconds': 20, 'maximumCommands': 4}, 'provenance': {}}


class FakeGame:
    def __init__(self):
        self.spec = qualification_spec()
        self.actors = {a['tag']: a for a in self.spec['actors']}
        self.calls, self.assigned, self.test_values = [], {}, []
        self.subject_status = 5

    def __call__(self, envelope):
        self.calls.append(copy.deepcopy(envelope))
        if envelope['operation'] == 'finish': return {'outcome': 'owner-finished'}
        if envelope['operation'] == 'binding':
            return {'returned': self.subject_status if envelope['bindingId'] == 'morph_status' else .5}
        if envelope['tool'] == 'inspect': return {'readOnly': True}
        args = envelope['args']
        if args['operation'] == 'state.read': return {'world': {'ready': True}}
        req = args['request']; domain = req['domain']; action = req.get('action')
        tag = req.get('actor', {}).get('fixtureTag'); actor = self.actors.get(tag)
        if domain == 'human-preset-catalog': return {'catalog': {'missingRequestedPresetCount': 0}}
        if domain == 'human-provider-config':
            return {'human': {'config': {'disablePresetDistribution': 'none'}, 'officialApiReady': True}}
        if domain == 'actor-fixture': return {'request': {'admitted': True}}
        if domain == 'actor-fixture-identity':
            return {'actor': {'reference': '0xFF00010' + tag[-1], 'baseFormId': actor['base']['formId'], 'persistentSaveWitnessAvailable': True}}
        if domain == 'human-preset-state':
            return {'human': {'assignedPreset': self.assigned.get(tag, actor['humanPreset']),
                'appliedSourceReadUnavailableCount': 0, 'automaticGenerationWitnessCount': 1}}
        if domain == 'actor-fixture-inspection':
            return {'actor': {'displayName': actor['displayName']}, 'fixture': {'registryIdentityMatch': True,
                'wornArmorItemCount': 0, 'equippedWeaponCount': 0, 'positionDriftGameUnits': 0, 'collisionDisableCommandCount': 0}}
        if domain == 'human-preset':
            if action == 'assign': self.assigned[tag] = req['presetName']
            if action == 'unassign': self.assigned[tag] = ''
            return {'request': {'assignmentAccepted': True}}
        if domain == 'actor-morph-fixture':
            self.test_values = req['values'] if action == 'set-keyed-coefficients-once' else []
            return {'request': {'admitted': True}}
        if domain == 'actor-race':
            self.subject_status = 2 if req['race'] == self.spec['beastRace'] else 5
            return {'request': {'admitted': True}}
        if domain == 'morph-link':
            self.subject_status = 2 if action == 'bind-resource-family' else 6
            return {'request': {'admitted': True}}
        if domain == 'save-state':
            return {'save': {'ownedPairCount': 1, 'loadedOwnedPairCount': 1, 'actorWitnessCount': 6, 'actorRemapWitnessCount': 6, 'worldReady': True}}
        if domain == 'actor-morph-link-evaluation':
            values = self.spec['testValues']
            return {'sources': {'unavailableReadCount': 0}, 'own': {'targetReadCount': 1},
                # A nonzero subject mismatch is deliberately retained: this stage
                # qualifies data routes, never the subject's numerical behavior.
                'mapping': {'maxAbsoluteError': .37}, 'sourceAggregationWasReconstructedFromKeys': False,
                'human': {'providerOwnMaxAbsoluteCoefficient': 0}, 'fixture': {
                    'foreignHumanValue': values[0]['value'], 'zeroHumanKeyValue': 0,
                    'foreignWolfValue': values[2]['value'], 'zeroHumanKeyPresenceRecorded': True,
                    'remainingOwnedTestKeyCount': len(self.test_values)}}
        raise AssertionError('Unknown fake backend request: ' + repr(req))


def program_source():
    """Use the production preparer's exact reusable composition renderer."""
    return prepare.staged_source(qualification_spec(), semantic_spec(),
        Path(qualification.__file__).read_text(encoding='utf-8'),
        Path(semantic.__file__).read_text(encoding='utf-8'))


def saved_state(fixture, label):
    """Synthetic native six-actor receipt, kept behind the actual save callback."""
    state = fixture.state
    fixtures, rows = {}, []
    for index, definition in enumerate(qualification_spec()['actors']):
        tag, reference, creation = definition['tag'], '0xFF00010' + str(index), f'{index + 1:032x}'
        actor = {'reference': reference, 'base': definition['base']['formId'], 'sex': definition['sex'],
                 'race': definition['humanRace'], 'weight': 50, 'loaded3D': True}
        incarnation = {'sessionId': 'observer', 'loadGeneration': 1, 'runtimeHandle': 700 + index}
        fixtures[tag] = {'tag': tag, 'status': 'created', 'runId': fixture.run_id, 'creationId': creation,
            'reference': reference, 'createdReference': reference, 'base': actor['base'], 'game': copy.deepcopy(fixture.game),
            'worldGeneration': 1, 'actor': actor, 'incarnation': incarnation,
            'creationWitness': {'reference': reference, 'creationId': creation, 'forcePersist': True},
            'savedObservation': {'actor': copy.deepcopy(actor), 'incarnation': copy.deepcopy(incarnation)}}
        rows.append({'tag': tag, 'creationId': creation, 'base': actor['base'], 'savedReference': reference,
            'currentReference': reference, 'savedVmHandle': str(9000 + index), 'currentVmHandle': str(9000 + index),
            'runtimeHandle': 700 + index, 'persistent': True})
    state['interactiveActorFixtures'] = copy.deepcopy(fixtures)
    receipt = {'schemaVersion': 1, 'protocol': 'npc-persistence/1', 'pid': fixture.game['pid'], 'providerSession': 'native',
        'bindingId': 'b' * 32, 'runId': fixture.run_id, 'saveTag': label, 'phase': 'saved', 'saveOrdinal': 1,
        'loadOrdinal': 0, 'actors': rows}
    state['npcPersistence'] = {label: {'status': 'saved', 'saveTag': label, 'bindingId': 'b' * 32,
        'runId': fixture.run_id, 'game': copy.deepcopy(fixture.game), 'worldGeneration': 1, 'loadAttempted': False,
        'fixtures': fixtures, 'savedReceipt': receipt}}
    state['ownedSaves'] = {label: {'completed': True, 'ownedByAttempt': True, 'stem': 'OwnedStageSave',
        'files': {'ess': {'sha256': '1' * 64, 'bytes': 100}, 'skse': {'sha256': '2' * 64, 'bytes': 100}}}}
    fixture.write_state()


def loaded_state(fixture, label, command_id):
    """Publish actual fake-producer state only after its durable load delivery."""
    state, game = fixture.state, copy.deepcopy(fixture.game)
    record = state['npcPersistence'][label]
    record.update(status='loaded', loadAttempted=True, loadCommandId=command_id, ownedLoadOrdinal=1,
        interactiveWindow={'phase': 'interactive-session', 'deadline': state['deadline']}, afterWorldGeneration=2)
    scene = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}
    state['ownedWorldGeneration'] = 2
    state['gameplayBootstrap'].update(completed=True, loadedOwnedSave=label, scene=scene,
        menus={'messageBoxOpen': False, 'openMenus': [], 'menuStates': []})
    state['ownedLoadTransition'] = {'saveTag': label, 'completed': True, 'beforeGame': game, 'afterGame': game,
        'ordinal': 1, 'worldGeneration': 2, 'scene': scene, 'events': [
            {'seq': 1, 'topic': 'lifecycle', 'data': {'event': 'preLoadGame'}},
            {'seq': 2, 'topic': 'lifecycle', 'data': {'event': 'postLoadGame'}}], 'cursor': 2}
    state['ownedLoadHistory'] = [copy.deepcopy(state['ownedLoadTransition'])]
    receipt = copy.deepcopy(record['savedReceipt']); receipt.update(phase='loaded', loadOrdinal=1)
    rebindings, replacements = {}, {}
    for index, row in enumerate(receipt['actors']):
        old = record['fixtures'][row['tag']]
        reference, vm = f'0xFF100{index:03X}', str(19000 + index)
        row.update(currentReference=reference, resolvedReference=reference, currentVmHandle=vm, resolvedVmHandle=vm,
            formResolved=True, handleResolved=True, runtimeHandle=1700 + index)
        actor = dict(old['actor'], reference=reference)
        incarnation = {'sessionId': 'observer', 'loadGeneration': 2, 'runtimeHandle': 1700 + index}
        witness = {'saveTag': label, 'bindingId': record['bindingId'], 'native': copy.deepcopy(row), 'worldGeneration': 2}
        rebindings[row['tag']] = {'actor': actor, 'incarnation': incarnation, 'restorationWitness': copy.deepcopy(witness)}
        replacement = copy.deepcopy(old)
        replacement.update(status='created', reference=reference, actor=copy.deepcopy(actor), incarnation=copy.deepcopy(incarnation),
            restorationWitness=copy.deepcopy(witness), worldGeneration=2)
        replacements[row['tag']] = replacement
    record.update(loadedReceipt=receipt, rebindings=rebindings)
    state['interactiveActorFixtures'] = replacements
    fixture.write_state()


class StagesTests(unittest.TestCase):
    def test_qualification_default_finishes_and_stage_returns_without_fake_finish(self):
        for finish in (True, False):
            backend, events = FakeGame(), []
            result = qualification.run_plan(backend.spec, backend, events.append, finish_owner=finish)
            self.assertEqual(result['outcome'], 'passed')
            self.assertFalse(result['subjectModAccepted'])
            self.assertEqual(len(backend.calls), 101 if finish else 100)
            self.assertEqual(sum(call['operation'] == 'finish' for call in backend.calls), int(finish))
            self.assertEqual(sum(event['kind'] == 'check-result' and event['outcome'] == 'passed' for event in events), 9)
            if not finish: self.assertFalse(any(event.get('request', {}).get('operation') == 'finish' for event in events))

    def test_semantic_success_and_known_mismatch_are_returned_without_finish(self):
        for ready, outcome in ((True, 'passed'), (False, 'mismatch')):
            calls, events = [], []
            def exchange(envelope):
                calls.append(envelope)
                return {'world': {'ready': ready}}
            result = semantic.run_plan(semantic_spec(), exchange, events.append, finish_owner=False)
            self.assertEqual(result['outcome'], outcome)
            self.assertEqual(len(calls), 1)
            self.assertFalse(any(event.get('request', {}).get('operation') == 'finish' for event in events))

    def test_finish_flag_is_strict_and_invalid_never_exchanges(self):
        for module, spec in ((qualification, qualification_spec()), (semantic, semantic_spec())):
            for value in (None, 1, 'false'):
                with self.assertRaisesRegex(ValueError, 'explicit boolean'):
                    module.run_plan(spec, lambda envelope: self.fail('Invalid stage exchanged'), lambda event: None, finish_owner=value)

    def test_composer_failed_native_stage_declares_bridge_not_run_without_another_call(self):
        namespace = {'__name__': 'offline_stages', '__file__': __file__}
        exec(program_source(), namespace)
        calls, events = [], []
        def exchange(envelope):
            calls.append(envelope)
            return {'readOnly': False}
        with self.assertRaises(AssertionError): namespace['run'](exchange, events.append)
        self.assertEqual(len(calls), 1)
        self.assertEqual(events[-1]['caseId'], BRIDGE_CASE)
        self.assertEqual(events[-1]['outcome'], 'not_run')

    def test_preparer_keeps_default_nine_and_optionally_pins_actual_generic_stage_and_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); selected = qualification_spec()
            actors = [{'tag': a['tag'], 'sex': a['sex'], 'plugin': 'Skyrim.esm', 'baseFormId': a['base']['formId'],
                'placement': a['placement'], 'humanPreset': a['humanPreset'], 'raceFormId': a['humanRace']} for a in selected['actors']]
            requests = [selected['catalogRequest'], selected['configurationRequest'],
                {'domain': 'actor-morph-fixture', 'action': 'set-keyed-coefficients-once', 'values': selected['testValues']},
                {'domain': 'actor-race', 'race': selected['beastRace']}]
            for sex in ('male', 'female'):
                requests.append({'domain': 'actor-morph-link-evaluation', 'actor': {'fixtureTag': next(a['tag'] for a in actors if a['sex'] == sex)},
                    'rows': [{'sourceMorph': 'InputMorph'}], 'familyId': sex + '-family', 'publicTargets': ['GenericTarget'], 'ownKey': selected['ownKey']})
            inputs = [root / name for name in ('draft.json', 'fixture.json', 'registry.json', 'config.json', 'provider.bin')]
            for path, value in zip(inputs, ({'subjectPlan': {'steps': [{'parameters': {'request': req}} for req in requests]}},
                    {'actors': actors}, {'actors': [{'fixtureTag': a['tag'], 'displayName': a['displayName']} for a in selected['actors']]}, {}, {})):
                path.write_text(json.dumps(value), encoding='utf-8')
            for include in (False, True):
                output = root / ('ten' if include else 'nine')
                receipt = prepare.prepare(*inputs, output, include_held_bridge_check=include)
                plan = json.loads((output / 'execution-plan.json').read_text())
                self.assertEqual(len(plan['checks']), 10 if include else 9)
                self.assertEqual(plan['bounds'], {'maximumSeconds': 600, 'maximumCommands': 256})
                self.assertTrue(json.loads((output / 'interactive-policy.json').read_text())['manageCommandEndpoint'])
                self.assertEqual(len(receipt['sourceSnapshots']), 2)
                for source in receipt['sourceSnapshots']:
                    self.assertTrue(Path(source['path']).is_relative_to(output / 'source-snapshots'))
                    self.assertEqual(source, prepare.pin(source['path']))
                namespace = runpy.run_path(str(output / 'sequencer.py')); backend = FakeGame(); events = []
                result = namespace['run'](backend, events.append)
                self.assertEqual(result['outcome'], 'passed')
                self.assertEqual(len(backend.calls), 102 if include else 101)
                self.assertEqual(sum(call['operation'] == 'finish' for call in backend.calls), 1)
                if include:
                    bridge_spec = json.loads((output / 'held-bridge-spec.json').read_text())
                    for key in ('order', 'mappingManifest', 'compiledScenario'):
                        value = bridge_spec['provenance'][key]
                        self.assertEqual(value, prepare.pin(value['path']))
                    self.assertEqual(backend.calls[-2]['args'], {'operation': 'state.read'})

    def fixture(self, root, unknown=False):
        fixture = transport.Fixture(root, cases=qualification.CASES + (BRIDGE_CASE,))
        fixture.plan.write_bytes(transport.tool.encoded({'checks': [{'name': name, 'role': 'subject'} for name in qualification.CASES + (BRIDGE_CASE,)],
            'bounds': {'maximumSeconds': 600, 'maximumCommands': 110}, 'fixture': {'cell': 'QASmoke'}}))
        fixture.state['configuration']['interactive_session']['maximumSeconds'] = 600
        fixture.state['configuration']['interactive_session'].update(npcPersistence=True,
            morphSession={'bindings': {'reviewed': 'native-role'}, 'testKeys': ['Fixture.Test.One']})
        fixture.state['configuration']['allow_owned_save_load'] = True
        fixture.state['interactiveSession']['maximumSeconds'] = 600
        fixture.state['deadline'] = time.time() + 605
        fixture.state['ownedWorldGeneration'] = 1
        fixture.state['ownedLoadHistory'] = []
        fixture.write_state()
        fixture.sequencer.write_text(program_source(), encoding='utf-8', newline='\n')
        backend = FakeGame()
        class Client(transport.LocalClient):
            def call(self, operation, arguments):
                request = {}
                if operation == 'submit':
                    envelope = json.loads(arguments['text'])
                    args = envelope.get('args', {})
                    request = args.get('request', {}) if isinstance(args, dict) else {}
                    if unknown and request.get('domain') == 'actor-fixture':
                        self.mode = 'uncertain'
                    else:
                        self.result = backend(envelope)
                result = super().call(operation, arguments)
                if request.get('domain') == 'save-state':
                    if request.get('action') == 'save-disposable-once': saved_state(fixture, request['saveLabel'])
                    elif request.get('action') == 'load-owned-disposable-once':
                        loaded_state(fixture, request['saveLabel'], result['command']['id'])
                return result
        fixture.client = Client(fixture)
        return fixture

    def test_real_frozen_companion_runs_two_stages_with_102_actual_commands_and_one_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = self.fixture(Path(folder)); client = fixture.companion(ready=False)
            self.assertEqual(client.execute(), 0, client.report.get('reason'))
            self.assertTrue(client.report['completed']); self.assertFalse(client.report['uncertain'])
            self.assertEqual(len(client.report['cases']), 10)
            self.assertTrue(all(case['status'] == 'passed' for case in client.report['cases']))
            self.assertEqual(len(client.report['actions']), 102)
            self.assertEqual(sum(action['envelope']['operation'] == 'finish' for action in client.report['actions']), 1)
            self.assertEqual(client.report['actions'][-2]['caseId'], BRIDGE_CASE)
            actual = [json.loads(line) for line in (fixture.run_dir / 'steps.jsonl').read_text().splitlines()]
            self.assertEqual([row['commandId'] for row in actual], [action['commandId'] for action in client.report['actions']])
            self.assertEqual(fixture.bus.status(fixture.session_id)['commands'], {'completed': 102})
            self.assertEqual(client.report['ownedLoads'][0]['actorWitnessCount'], 6)

    def test_real_frozen_companion_unknown_first_stage_stops_before_next_stage_or_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = self.fixture(Path(folder), unknown=True); client = fixture.companion(ready=False)
            self.assertEqual(client.execute(), 2)
            self.assertFalse(client.report['completed']); self.assertTrue(client.report['uncertain'], client.report.get('reason'))
            self.assertEqual(client.report['cases'][-1]['status'], 'not_run')
            actions = client.report['actions']
            self.assertEqual(len(actions), 4)
            self.assertEqual(actions[-1]['status'], 'uncertain')
            self.assertEqual(sum(a['envelope'].get('args', {}).get('request', {}).get('domain') == 'actor-fixture' for a in actions), 1)
            self.assertFalse(any(a['caseId'] == BRIDGE_CASE or a['envelope']['operation'] == 'finish' for a in actions))
            self.assertEqual(fixture.bus.status(fixture.session_id)['commands'], {'completed': 3, 'uncertain': 1})


if __name__ == '__main__': unittest.main()
