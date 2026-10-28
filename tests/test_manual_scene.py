import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import manual_scene, morph_session


class SceneBackend:
    def __init__(self, spec):
        self.spec, self.calls, self.states = spec, [], {}
        self.fail_action = None
        self.distribution = 'none'
        self.drift_after_six = False
        self.missing_automatic = False
        self.bad_visibility = False
        self.missing_additional_presets = 0

    def exchange(self, envelope):
        self.calls.append(copy.deepcopy(envelope))
        if envelope['operation'] == 'finish':
            return {'outcome': 'owner-finished'}
        args = envelope['args']; r = args['request']
        morph_session.validate(args['operation'], r)
        if r.get('action') == self.fail_action and self.fail_action:
            raise TimeoutError('Unknown native outcome')
        domain = r['domain']
        if domain == 'human-preset-catalog':
            return {'catalog': {'missingRequestedPresetCount': 0}}
        if domain == 'human-provider-config':
            return {'human': {'officialApiReady': True, 'config': {'disablePresetDistribution': self.distribution,
                    'unexpectedLoadedPresetCount': 0, 'missingExpectedPresetCount': 0,
                    'missingAllowedAdditionalPresetCount': self.missing_additional_presets}}}
        tag = r['actor']['fixtureTag']
        if domain == 'actor-fixture':
            a = next(a for a in self.spec['actors'] + self.spec.get('wildActors', []) if a['tag'] == tag)
            if tag in self.states: raise AssertionError('Duplicate creation')
            self.states[tag] = {'reference': '0xFF%06X' % (len(self.states) + 1),
                                'baseFormId': a['base']['formId'], 'race': a.get('initialRace', a.get('humanRace')),
                                'displayName': '', 'preset': '', 'dontMove': True, 'sex': a['sex']}
            if self.spec.get('presetMode') == 'automatic-stock' and not self.missing_automatic:
                self.states[tag]['preset'] = a['allowedHumanPresets'][0]
            return {'created': True, 'actor': {'base': a['base']['formId']}}
        state = self.states[tag]
        if domain == 'actor-fixture-identity': return {'actor': dict(state)}
        if domain == 'actor-fixture-inspection':
            if r.get('action') == 'set-reference-display-name': state['displayName'] = r['displayName']
            if self.drift_after_six and len(self.states) == 6 and tag == 'Actor0': state['displayName'] = 'Changed'
            return {'actor': dict(state), 'fixture': {'registryIdentityMatch': True,
                    'wornArmorItemCount': 0, 'equippedWeaponCount': 0, 'dontMove': state['dontMove'],
                    'positionDriftGameUnits': 0, 'collisionDisableCommandCount': 0}}
        if domain == 'human-preset':
            state['preset'] = r['presetName']
            return {'request': {'assignmentAccepted': True}}
        if domain == 'human-preset-state':
            return {'human': {'assignedPreset': state['preset'], 'appliedSourceReadUnavailableCount': 0,
                    'automaticGenerationWitnessCount': int(bool(state['preset']))},
                    'providerObservation': {'events': ['actual mocked raw assignment witness']}}
        if domain == 'actor-morph-link-evaluation':
            return {'raw': {'sources': {'SignedSource': -0.4, 'ZeroSource': 0}, 'targetKeys': {'Target': [{'key': 'Own', 'value': .2}]}},
                    'captureSnapshot': r['captureSnapshot'], 'stage': r['stage'], 'renderedMorphsVerified': False}
        if domain == 'actor-fixture-visibility':
            if r['action'] != 'read': state['disabled'] = r['action'] == 'hide'
            disabled = state.get('disabled', False)
            return {'actor': {'reference': '0xFF000BAD' if self.bad_visibility else state['reference'], 'base': state['baseFormId']},
                    'disabled': disabled, 'loaded3D': not disabled, 'unchangedIdentity': True}
        if domain == 'actor-race':
            state['race'] = r['race']; return {'request': {'admitted': True}}
        raise AssertionError(domain)


class ManualSceneTests(unittest.TestCase):
    def setUp(self):
        self.spec = {'actors': [{'tag': 'Actor' + str(i), 'displayName': 'Actor' + str(i), 'sex': 'male',
                      'base': {'plugin': 'Skyrim.esm', 'formId': '0x%08X' % (100 + i)},
                      'humanRace': '0x00013746', 'humanPreset': 'Preset' + str(i),
                      'placement': {'forwardGameUnits': 200, 'rightGameUnits': i * 50}}
                     for i in range(6)], 'beastRace': '0x000CDD84',
            'catalogRequest': {'domain': 'human-preset-catalog', 'presets': [
                {'name': 'Preset0', 'sex': 'male', 'set': 'Example'}], 'wolfPresetRequirement': 'none'},
            'configurationRequest': {'domain': 'human-provider-config', 'presetPoolPolicy': 'exact-six-existing-human-preset-elements',
                'otherActorsPolicy': 'unchanged', 'requiredDisablePresetDistribution': 'none',
                'baseSelectionPolicy': [{'plugin': 'Skyrim.esm', 'baseFormId': '0x%08X' % (100 + i),
                    'allowedHumanPresets': ['a', 'b', 'c']} for i in range(6)]}}

    def run_scene(self, commands, backend=None):
        backend = backend or SceneBackend(self.spec)
        records, notices = [], []
        commands = iter(commands)
        result = manual_scene.run_plan(self.spec, backend.exchange, records.append,
                                       lambda: next(commands), lambda k, v: notices.append((k, v)))
        return result, backend, records, notices

    def test_ready_precedes_commands_and_no_automatic_transform(self):
        result, backend, records, notices = self.run_scene([{'sequence': 1, 'sourceRef': 'owner-stop', 'action': 'finish'}])
        self.assertEqual(len(backend.states), 6)
        creates = [c['args']['request'] for c in backend.calls if c.get('args', {}).get('request', {}).get('domain') == 'actor-fixture']
        self.assertEqual(len(creates), 6)
        self.assertTrue(all(c['placement']['basis'] == 'prepared-qasmoke-anchor-v1' for c in creates))
        self.assertTrue(all(s['race'] == '0x00013746' for s in backend.states.values()))
        self.assertEqual(notices[0][0], 'scene-ready')
        self.assertFalse(result['wholeModAccepted'])
        self.assertIsNone([r for r in records if r.get('request', {}).get('operation') == 'finish'][0]['caseId'])
        self.assertEqual(sum(c.get('operation') == 'finish' for c in backend.calls), 1)

    def test_only_named_actor_changes_and_human_return_is_valid(self):
        commands = [{'sequence': 1, 'sourceRef': 'speech-1', 'action': 'to-beast', 'actor': 'Actor2'},
                    {'sequence': 2, 'sourceRef': 'speech-2', 'action': 'to-human', 'actor': 'Actor2'},
                    {'sequence': 3, 'sourceRef': 'stop', 'action': 'finish'}]
        _, backend, _, notices = self.run_scene(commands)
        races = [c['args']['request'] for c in backend.calls if c.get('args', {}).get('request', {}).get('domain') == 'actor-race']
        self.assertEqual([r['actor']['fixtureTag'] for r in races], ['Actor2', 'Actor2'])
        self.assertEqual(len([n for n in notices if n[0] == 'command-result']), 2)

    def test_unknown_mutation_stops_without_retry_finish_or_ready(self):
        backend = SceneBackend(self.spec); backend.fail_action = 'assign'
        records, notices = [], []
        with self.assertRaises(TimeoutError):
            manual_scene.run_plan(self.spec, backend.exchange, records.append, lambda: None,
                                  lambda k, v: notices.append((k, v)))
        self.assertEqual(sum(c.get('args', {}).get('request', {}).get('action') == 'assign' for c in backend.calls), 1)
        self.assertFalse(any(c['operation'] == 'finish' for c in backend.calls))
        self.assertNotIn('scene-ready', [k for k, _ in notices])

    def test_ambiguous_target_never_transforms(self):
        backend = SceneBackend(self.spec)
        with self.assertRaises(ValueError):
            self.run_scene([{'sequence': 1, 'sourceRef': 'speech', 'action': 'to-beast', 'actor': 'unknown'}], backend)
        self.assertFalse(any(c.get('args', {}).get('request', {}).get('domain') == 'actor-race' for c in backend.calls))

    def test_repeated_requested_race_is_observed_without_second_setter(self):
        commands = [{'sequence': i, 'sourceRef': 'speech-' + str(i), 'action': 'to-beast', 'actor': 'Actor2'} for i in (1, 2)]
        commands.append({'sequence': 3, 'sourceRef': 'stop', 'action': 'finish'})
        _, backend, _, _ = self.run_scene(commands)
        self.assertEqual(sum(c.get('args', {}).get('request', {}).get('domain') == 'actor-race' for c in backend.calls), 1)

    def test_directory_reads_only_next_sequence(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / '000002.json').write_text('{"sequence":2}', encoding='utf-8')
            (folder / '000001.json').write_text('{"sequence":1}', encoding='utf-8')
            source = manual_scene.directory_commands(folder, 2)
            self.assertEqual(next(source)['sequence'], 1)
            self.assertEqual(next(source)['sequence'], 2)

    def test_disabled_provider_refuses_before_creation(self):
        backend = SceneBackend(self.spec); backend.distribution = 'all'
        with self.assertRaises(AssertionError): self.run_scene([], backend)
        self.assertEqual(backend.states, {})

    def test_late_name_drift_refuses_ready(self):
        backend = SceneBackend(self.spec); backend.drift_after_six = True
        notices = []
        with self.assertRaises(AssertionError):
            manual_scene.run_plan(self.spec, backend.exchange, lambda r: None, lambda: None,
                                  lambda k, v: notices.append(k))
        self.assertNotIn('scene-ready', notices)

    def automatic(self, wild=False):
        self.spec.update(presetMode='automatic-stock', automaticObservationSeconds=1)
        for actor in self.spec['actors']:
            actor['allowedHumanPresets'] = [actor['humanPreset'], actor['humanPreset'] + '-B']
        if wild:
            self.spec['wildOriginPolicy'] = 'observe-natural-host'
            self.spec['wildActors'] = []
            for i, human in enumerate(self.spec['actors']):
                actor = copy.deepcopy(human)
                actor.update(tag='Wild' + str(i), displayName='Wild ' + str(i), initialRace=self.spec['beastRace'])
                actor.pop('humanRace')
                actor['base']['formId'] = '0x%08X' % (300 + i)
                self.spec['wildActors'].append(actor)

    def test_automatic_origin_precedes_inspection_without_manual_assignment(self):
        self.automatic()
        _, backend, _, notices = self.run_scene([{'sequence': 1, 'sourceRef': 'stop', 'action': 'finish'}])
        requests = [c['args']['request'] for c in backend.calls if 'args' in c]
        self.assertFalse(any(r['domain'] == 'human-preset' for r in requests))
        for actor in self.spec['actors']:
            own = [r for r in requests if r.get('actor', {}).get('fixtureTag') == actor['tag']]
            read = next(i for i, r in enumerate(own) if r['domain'] == 'human-preset-state')
            inspect = next(i for i, r in enumerate(own) if r['domain'] == 'actor-fixture-inspection')
            self.assertLess(read, inspect)
            self.assertTrue(own[read]['requireAutomaticOrigin'])
        ready = next(v for k, v in notices if k == 'scene-ready')
        self.assertTrue(all(v['automaticOriginVerified'] for v in ready['automaticOrigins'].values()))

    def test_missing_automatic_result_stays_unavailable_without_forced_generation(self):
        self.automatic()
        backend = SceneBackend(self.spec); backend.missing_automatic = True
        clock = iter(range(1000))
        with patch.object(manual_scene.time, 'monotonic', side_effect=lambda: next(clock)), patch.object(manual_scene.time, 'sleep'):
            _, backend, _, notices = self.run_scene([{'sequence': 1, 'sourceRef': 'stop', 'action': 'finish'}], backend)
        origins = [v for k, v in notices if k == 'automatic-origin']
        self.assertEqual(len(origins), 6)
        self.assertTrue(all(v['status'] == 'unavailable' and not v['automaticOriginVerified'] for v in origins))
        self.assertFalse(any(c.get('args', {}).get('request', {}).get('domain') in ('human-preset', 'morph-link') for c in backend.calls))

    def test_groups_create_wild_only_on_first_add_and_preserve_refs(self):
        self.automatic(wild=True)
        commands = [{'sequence': i + 1, 'sourceRef': 'owner-' + str(i), 'action': action, 'group': group}
                    for i, (action, group) in enumerate([
                        ('remove-group', 'wild'), ('remove-group', 'humans'), ('add-group', 'wild'),
                        ('remove-group', 'wild'), ('add-group', 'wild'), ('add-group', 'humans')])]
        commands.append({'sequence': 7, 'sourceRef': 'stop', 'action': 'finish'})
        _, backend, _, notices = self.run_scene(commands)
        ready = next(v for k, v in notices if k == 'scene-ready')
        self.assertEqual(ready['wildCreatedCount'], 0)
        requests = [c['args']['request'] for c in backend.calls if 'args' in c]
        self.assertEqual(sum(r['domain'] == 'actor-fixture' for r in requests), 12)
        self.assertFalse(any(r['domain'] in ('actor-race', 'human-preset', 'morph-link') for r in requests))
        self.assertTrue(all(s['race'] == self.spec['beastRace'] for tag, s in backend.states.items() if tag.startswith('Wild')))
        self.assertEqual(len({s['reference'] for s in backend.states.values()}), 12)
        origins = [v for k, v in notices if k == 'automatic-origin' and v['actor'].startswith('Wild')]
        self.assertEqual(len(origins), 6)
        self.assertTrue(all(v['naturalHostOrigin'] == 'unverified-raw-evidence' and not v['automaticOriginVerified'] for v in origins))
        human_mutations = [r for r in requests if r['domain'] == 'actor-fixture-visibility' and r['actor']['fixtureTag'].startswith('Actor')]
        self.assertEqual([r['action'] for r in human_mutations], ['hide'] * 6 + ['show'] * 6)

    def test_preset_diagnostic_is_only_owner_requested_and_keeps_origin_evidence(self):
        self.automatic()
        commands = [{'sequence': 1, 'sourceRef': 'owner-preset-B', 'action': 'assign-preset', 'actor': 'Actor1', 'presetName': 'Preset1-B'},
                    {'sequence': 2, 'sourceRef': 'owner-preset-A', 'action': 'assign-preset', 'actor': 'Actor1', 'presetName': 'Preset1'},
                    {'sequence': 3, 'sourceRef': 'stop', 'action': 'finish'}]
        _, backend, _, notices = self.run_scene(commands)
        assignments = [c['args']['request'] for c in backend.calls if c.get('args', {}).get('request', {}).get('domain') == 'human-preset']
        self.assertEqual([r['presetName'] for r in assignments], ['Preset1-B', 'Preset1'])
        self.assertTrue(all(v['separateOwnerPresetDiagnostic'] for k, v in notices if k == 'command-result'))
        with self.assertRaisesRegex(ValueError, 'outside the declared'):
            self.run_scene([{'sequence': 1, 'sourceRef': 'owner', 'action': 'assign-preset', 'actor': 'Actor1', 'presetName': 'Foreign'}])

    def test_full_morph_template_preserves_raw_signed_zero_and_target_evidence(self):
        from test_morph_session import evaluation
        self.automatic()
        template = evaluation()
        for key in ('actor', 'captureSnapshot', 'stage'): template.pop(key)
        self.spec['morphObservationRequest'] = template
        commands = [{'sequence': 1, 'sourceRef': 'owner-transform', 'action': 'to-beast', 'actor': 'Actor1'},
                    {'sequence': 2, 'sourceRef': 'stop', 'action': 'finish'}]
        _, backend, records, notices = self.run_scene(commands)
        requests = [c['args']['request'] for c in backend.calls if c.get('args', {}).get('request', {}).get('domain') == 'actor-morph-link-evaluation']
        self.assertEqual(len(requests), 7)
        self.assertTrue(all(r['manualTesterMutationsBeforeThisObservation'] == 0 for r in requests[:6]))
        self.assertNotIn('manualTesterMutationsBeforeThisObservation', requests[-1])
        self.assertEqual(requests[-1]['stage'], 'linked-beast')
        evidence = next(v['morphObservation'] for k, v in notices if k == 'command-result')
        self.assertEqual(evidence['raw']['sources'], {'SignedSource': -.4, 'ZeroSource': 0})
        self.assertEqual(len({r['captureSnapshot'] for r in requests}), 7)

    def test_invalid_complete_spec_refuses_before_first_exchange(self):
        self.automatic(wild=True)
        for mutate in (lambda s: s.update(presetMod='automatic-stock'),
                       lambda s: s['wildActors'][-1].update(initialRace=s['actors'][0]['humanRace']),
                       lambda s: s['wildActors'][-1].update(tag=s['actors'][0]['tag'])):
            original = copy.deepcopy(self.spec); mutate(self.spec)
            backend = SceneBackend(self.spec)
            with self.assertRaises(ValueError): self.run_scene([], backend)
            self.assertEqual(backend.calls, [])
            self.spec = original

    def pinned_additional_catalog(self, wild=False):
        self.automatic(wild=wild)
        self.spec['catalogRequest']['presets'] = [
            {'name': a['humanPreset'], 'sex': a['sex'], 'set': 'Diagnostic'} for a in self.spec['actors']]
        mappings = []
        for actor in self.spec['actors'] + self.spec.get('wildActors', []):
            index = int(actor['tag'].removeprefix('Actor').removeprefix('Wild'))
            mappings.append({'plugin': actor['base']['plugin'], 'baseFormId': actor['base']['formId'],
                             'allowedHumanPresets': ['Preset' + str(index)]})
        self.spec['configurationRequest'].update(baseSelectionPolicy=mappings,
            allowedAdditionalLoadedPresets=[{'category': 'female', 'name': 'Declared official stock'}])
        if wild:
            self.spec['wildConfigurationRequest'] = copy.deepcopy(self.spec['configurationRequest'])

    def test_pinned_additional_catalog_preserves_untouched_origins_and_lazy_wild(self):
        self.pinned_additional_catalog(wild=True)
        _, backend, _, notices = self.run_scene([{'sequence': 1, 'sourceRef': 'stop', 'action': 'finish'}])
        self.assertEqual(len(backend.states), 6)
        self.assertTrue(any(k == 'scene-ready' for k, _ in notices))
        self.assertFalse(any(c.get('args', {}).get('request', {}).get('domain') in ('human-preset', 'morph-link', 'actor-race')
                             for c in backend.calls))

    def test_missing_pinned_additional_preset_stops_before_creation(self):
        self.pinned_additional_catalog()
        backend = SceneBackend(self.spec); backend.missing_additional_presets = 1
        with self.assertRaises(AssertionError): self.run_scene([], backend)
        self.assertFalse(backend.states)

    def test_pinned_catalog_declaration_errors_refuse_before_exchange(self):
        self.pinned_additional_catalog(wild=True)
        for mutate in (
                lambda s: s.pop('catalogRequest'),
                lambda s: s['catalogRequest']['presets'].pop(),
                lambda s: s['catalogRequest']['presets'][0].update(name='Different target'),
                lambda s: s['wildConfigurationRequest'].pop('allowedAdditionalLoadedPresets'),
                lambda s: s['wildConfigurationRequest']['allowedAdditionalLoadedPresets'][0].update(category='male')):
            original = copy.deepcopy(self.spec); mutate(self.spec)
            backend = SceneBackend(self.spec)
            with self.assertRaises(ValueError): self.run_scene([], backend)
            self.assertEqual(backend.calls, [])
            self.spec = original

    def test_mixed_sex_templates_select_actual_actor_sex_and_single_template_refuses(self):
        from test_morph_session import evaluation
        self.automatic()
        for actor in self.spec['actors'][3:]: actor['sex'] = 'female'
        template = evaluation()
        for key in ('actor', 'captureSnapshot', 'stage'): template.pop(key)
        self.spec['morphObservationRequest'] = template
        backend = SceneBackend(self.spec)
        with self.assertRaisesRegex(ValueError, 'Mixed-sex'):
            self.run_scene([], backend)
        self.assertEqual(backend.calls, [])
        self.spec.pop('morphObservationRequest')
        self.spec['morphObservationRequestsBySex'] = {
            sex: dict(copy.deepcopy(template), familyId='Example.' + sex) for sex in ('male', 'female')}
        _, backend, _, _ = self.run_scene([{'sequence': 1, 'sourceRef': 'stop', 'action': 'finish'}])
        reads = [c['args']['request'] for c in backend.calls if c.get('args', {}).get('request', {}).get('domain') == 'actor-morph-link-evaluation']
        self.assertEqual([r['familyId'] for r in reads], ['Example.male'] * 3 + ['Example.female'] * 3)

    def test_native_name_bound_and_zero_race_refuse_before_creation(self):
        for mutate in (lambda s: s['actors'][-1].update(displayName='я' * 65),
                       lambda s: s.update(beastRace='0x00000000')):
            original = copy.deepcopy(self.spec); mutate(self.spec)
            backend = SceneBackend(self.spec)
            with self.assertRaises(ValueError): self.run_scene([], backend)
            self.assertEqual(backend.calls, [])
            self.spec = original

    def test_bad_visibility_readback_stops_without_recreation_or_finish(self):
        self.automatic(wild=True)
        backend = SceneBackend(self.spec); backend.bad_visibility = True
        with self.assertRaisesRegex(ValueError, 'visibility readback'):
            self.run_scene([{'sequence': 1, 'sourceRef': 'owner-hide', 'action': 'remove-group', 'group': 'humans'}], backend)
        self.assertEqual(len(backend.states), 6)
        self.assertFalse(any(c['operation'] == 'finish' for c in backend.calls))

    def test_born_beast_never_gets_human_transition(self):
        self.automatic(wild=True)
        backend = SceneBackend(self.spec)
        commands = [{'sequence': 1, 'sourceRef': 'owner-add', 'action': 'add-group', 'group': 'wild'},
                    {'sequence': 2, 'sourceRef': 'owner-human', 'action': 'to-human', 'actor': 'Wild1'}]
        with self.assertRaisesRegex(ValueError, 'never create a human history'):
            self.run_scene(commands, backend)
        self.assertFalse(any(c.get('args', {}).get('request', {}).get('domain') == 'actor-race' for c in backend.calls))

    def test_world_control_keeps_owner_open_and_measures_actual_position(self):
        calls, notices, records = [], [], []
        positions = iter([[0, 0, 0], [0, 0, 0], [0, 2, 0]])
        def exchange(e):
            calls.append(e)
            if e.get('tool') == 'inspect': return {'playerLoaded': True, 'position': next(positions)}
            return {'outcome': 'owner-finished'} if e['operation'] == 'finish' else {}
        commands = iter([{'sequence': 1, 'sourceRef': 'owner-walk', 'action': 'move', 'key': 'W', 'milliseconds': 100},
                         {'sequence': 2, 'sourceRef': 'owner-stop', 'action': 'finish'}])
        manual_scene.run_world_plan(exchange, records.append, lambda: next(commands),
                                    lambda k, v: notices.append((k, v)), 'autotest-exact-owned-run')
        self.assertEqual(notices[1][1]['positionDeltaGameUnits'], 2)
        self.assertEqual([e['args']['action'] for e in calls if e.get('tool') == 'input'], ['capabilities', 'down', 'up'])
        self.assertFalse(notices[0][1]['sixActorSceneReady'])

    def test_world_finish_passes_actual_companion_assertion_and_finish_contract(self):
        from test_subject_companion import Fixture
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Fixture(Path(temporary))
            plan = json.loads(fixture.plan.read_text(encoding='utf-8'))
            plan['checks'] = [{'name': manual_scene.CASE, 'role': 'subject'}]
            plan.pop('cases', None)
            fixture.plan.write_text(json.dumps(plan), encoding='utf-8')
            fixture.client.result = {'playerLoaded': True, 'position': [1.0, 2.0, 3.0]}
            companion = fixture.companion()
            manual_scene.run_world_plan(companion.exchange, companion.emit,
                lambda: {'sequence': 1, 'sourceRef': 'owner-stop', 'action': 'finish'},
                lambda kind, value: None, 'autotest-exact-owned-run')
            self.assertTrue(companion.finish_completed)
            self.assertEqual(companion.assertions[manual_scene.CASE], ['passed'])
