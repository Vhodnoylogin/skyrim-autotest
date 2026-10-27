import copy
from pathlib import Path
import tempfile
import unittest

from skyrim_autotest import manual_scene, morph_session


class SceneBackend:
    def __init__(self, spec):
        self.spec, self.calls, self.states = spec, [], {}
        self.fail_action = None
        self.distribution = 'none'
        self.drift_after_six = False

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
                    'unexpectedLoadedPresetCount': 0, 'missingExpectedPresetCount': 0}}}
        tag = r['actor']['fixtureTag']
        if domain == 'actor-fixture':
            a = next(a for a in self.spec['actors'] if a['tag'] == tag)
            if tag in self.states: raise AssertionError('Duplicate creation')
            self.states[tag] = {'reference': '0xFF%06X' % (len(self.states) + 1),
                                'baseFormId': a['base']['formId'], 'race': a['humanRace'],
                                'displayName': '', 'preset': '', 'dontMove': True}
            return {'created': True}
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
            return {'human': {'assignedPreset': state['preset'], 'appliedSourceReadUnavailableCount': 0}}
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
