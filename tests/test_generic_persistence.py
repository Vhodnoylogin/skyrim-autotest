"""Generic pair admission and real adapters over synthetic native boundaries."""
import copy
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import config, fixture_actors, interactive, native_session, npc_persistence, platform
from tests import test_npc_persistence as base
from tests import test_fixture_actors as creation
from tests import test_native_session as finite

BORN, BEAST = '0xFE006805', '0x000CDD84'


class GenericPersistenceTests(unittest.TestCase):
    def setUp(self):
        base.PersistenceTests.setUp(self)
        self.tags = ['Born', 'Human']
        self.policy = copy.deepcopy(base.POLICY)
        self.policy['fixtureActorBases'].append(BORN)
        entries = list(self.s.state['interactiveActorFixtures'].values())[:2]
        self.s.state['interactiveActorFixtures'] = dict(zip(self.tags, entries))
        for tag, entry in self.s.state['interactiveActorFixtures'].items(): entry['tag'] = tag
        born = entries[0]
        born['base'] = born['creationWitness']['base'] = born['nativePersistentIdentity']['base'] = BORN
        born['actor'].update(base=BORN, race=BEAST, sex='female')
        self.s.state['configuration']['game_edition'] = 'se'
        self.settings = self.s.state['configuration']['interactive_session']
        self.settings.update(nativeBindings=copy.deepcopy(self.policy), npcPersistenceRoster={
            'mode': 'generic-two-actor-v1', 'fixtures': {'Born': BORN, 'Human': base.BASE}},
            channelConfig=str(Path(self.tmp.name)/'channel.json'), maximumSeconds=120,
            sourceId='operator.actions', allowedTools=['papyrus', 'platform'])

    def args(self, action=None):
        request = {'domain': 'save-state', 'saveLabel': 'unit-save'}
        if action == 'save': request.update(action='save-disposable-once', actors=list(self.tags),
            scope='current-temporary-profile', maximumSaves=1)
        if action == 'load': request.update(action='load-owned-disposable-once', maximumLoads=1, processRestart=False)
        return {'operation': 'world.read' if action is None else 'object.perform', 'request': request}

    def execute(self, action=None):
        return platform.execute(self.s, self.args(action), time.monotonic()+10)

    def envelope(self, action=None):
        return {'schemaVersion': 1, 'operation': 'tool', 'tool': 'platform', 'args': self.args(action),
                'timeoutSeconds': 90 if action == 'load' else 30}

    def no_mutation(self):
        self.assertFalse(any(tool in ('game', 'npc_persistence') for tool, _ in self.s.calls))

    def test_public_finite_and_held_policy_and_bus_admission_need_no_morphs(self):
        accepted = interactive.validate(self.settings)
        finite = native_session.validate({key: accepted[key] for key in ('nativeBindings', 'npcPersistence', 'npcPersistenceRoster')})
        self.assertEqual(finite['npcPersistenceRoster'], accepted['npcPersistenceRoster'])
        for action in ('save', 'load', None):
            envelope = self.envelope(action)
            self.assertEqual(interactive._request(json.dumps(envelope), accepted, self.s), envelope)
        for tag, actor_base in (('Born', BORN), ('Human', base.BASE)):
            envelope = {'schemaVersion': 1, 'operation': 'fixture-create', 'timeoutSeconds': 30,
                'request': {'tag': tag, 'base': actor_base, 'forwardGameUnits': 120, 'rightGameUnits': 60,
                            'persistentForOwnedSave': True}}
            self.assertEqual(interactive._request(json.dumps(envelope), accepted, self.s), envelope)

    def test_full_semantic_pair_save_read_load_remap_and_read_without_morph_ledger(self):
        saved = self.execute('save')
        self.assertEqual(saved['save']['actorWitnessCount'], 2)
        self.assertEqual(self.execute()['save']['actorWitnessCount'], 2)
        loaded = self.execute('load')
        self.assertEqual(loaded['save']['actorRemapWitnessCount'], 2)
        self.assertEqual(self.execute()['load']['actorWitnessCount'], 2)
        self.assertEqual(self.s.state['interactiveActorFixtures']['Born']['actor']['race'], BEAST)
        self.assertNotIn('morphSession', self.s.state)
        self.assertNotIn('matrixLifecycle', self.s.state)
        for tag, entry in self.s.state['interactiveActorFixtures'].items():
            fixture_actors.require_fixture(self.s, {'reference': entry['reference'], 'base': entry['base']})
        self.assertEqual([args['action'] for tool, args in self.s.calls if tool == 'game'], ['save', 'load'])
        self.assertTrue(all(args.get('script') != 'OBody' for _, args in self.s.calls))
        with self.assertRaises(ValueError): self.execute('load')
        with self.assertRaises(ValueError): self.execute('save')

    def test_same_capability_runs_through_finite_native_session(self):
        config = self.s.state['configuration']
        config['native_session'] = {key: copy.deepcopy(self.settings[key]) for key in ('nativeBindings', 'npcPersistence', 'npcPersistenceRoster')}
        del config['interactive_session']
        self.execute('save')
        self.assertEqual(self.execute('load')['load']['actorWitnessCount'], 2)

    def test_complete_configuration_accepts_se_but_refuses_vr(self):
        value = finite.finite_configuration(Path(self.tmp.name))
        value['native_session'] = {key: copy.deepcopy(self.settings[key]) for key in ('nativeBindings', 'npcPersistence', 'npcPersistenceRoster')}
        self.assertEqual(config.configure(value)['native_session']['npcPersistenceRoster'], self.settings['npcPersistenceRoster'])
        with self.assertRaisesRegex(ValueError, 'Generic NPC persistence requires the explicit SE target'):
            config.configure(dict(value, game_edition='vr', openvr_paths=str(Path(self.tmp.name)/'openvr.json')))

    def test_malformed_or_conflicting_rosters_are_rejected(self):
        original = copy.deepcopy(self.settings)
        changes = [lambda s: s.update(npcPersistence=False), lambda s: s.pop('nativeBindings'),
            lambda s: s.update(npcPersistenceRoster=None), lambda s: s['npcPersistenceRoster'].update(mode='other'),
            lambda s: s['npcPersistenceRoster'].update(maximumFixtures=2),
            lambda s: s['npcPersistenceRoster'].update(fixtures=['Born', 'Human']),
            lambda s: s['npcPersistenceRoster'].update(fixtures={'Born': BORN}),
            lambda s: s['npcPersistenceRoster']['fixtures'].update(Third=BORN),
            lambda s: s['npcPersistenceRoster']['fixtures'].update(Human='0x00000007'),
            lambda s: s['npcPersistenceRoster']['fixtures'].update(Human=None),
            lambda s: s.update(morphSession=None), lambda s: s.update(matrixLifecycle=None)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                value = copy.deepcopy(original); change(value)
                with self.assertRaises(ValueError): interactive.validate(value)
                finite = {key: value[key] for key in ('nativeBindings', 'npcPersistence', 'npcPersistenceRoster', 'morphSession', 'matrixLifecycle') if key in value}
                with self.assertRaises(ValueError): native_session.validate(finite)

    def test_absent_optin_and_vr_never_relax_default_roster(self):
        original = copy.deepcopy(self.s.state['configuration'])
        for change in (lambda: self.settings.pop('npcPersistenceRoster'),
                       lambda: self.s.state['configuration'].update(game_edition='vr')):
            with self.subTest(change=change):
                change()
                with self.assertRaises(ValueError): self.execute('save')
                self.no_mutation()
                self.s.state['configuration'] = copy.deepcopy(original)
                self.settings = self.s.state['configuration']['interactive_session']

    def test_unrelated_morph_domain_and_raw_save_are_not_newly_admitted(self):
        envelope = self.envelope()
        envelope['args'] = {'operation': 'world.read', 'request': {
            'domain': 'actor-fixture-identity', 'actor': {'fixtureTag': 'Born'}, 'requireActualOwnedReferenceWitness': True}}
        with self.assertRaises(ValueError): interactive._request(json.dumps(envelope), self.settings, self.s)
        envelope = self.envelope('save')
        envelope.update(tool='game', args={'action': 'save', 'name': 'raw'})
        with self.assertRaises(ValueError): interactive._request(json.dumps(envelope), self.settings, self.s)

    def test_generic_creation_refuses_undeclared_tag_base_or_nonpersistent_before_provider(self):
        original = {'tag': 'Born', 'base': BORN, 'forwardGameUnits': 120, 'rightGameUnits': 60, 'persistentForOwnedSave': True}
        for change in ({'tag': 'Foreign'}, {'base': base.BASE}, {'persistentForOwnedSave': False}):
            with self.subTest(change=change):
                request = {**original, **change}
                envelope = {'schemaVersion': 1, 'operation': 'fixture-create', 'request': request, 'timeoutSeconds': 30}
                with self.assertRaises(ValueError): interactive._request(json.dumps(envelope), self.settings, self.s)
                with self.assertRaises(ValueError): fixture_actors.create(self.s, request, time.monotonic()+10, self.policy)
                self.no_mutation()

    def test_partial_foreign_or_wrong_requested_roster_fails_before_native(self):
        for tags in (['Born'], ['Born', 'Foreign'], ['Born', 'Born'], ['Human', 'Born', 'Foreign']):
            with self.subTest(tags=tags):
                args = self.args('save'); args['request']['actors'] = tags
                with self.assertRaises(ValueError): platform.execute(self.s, args, time.monotonic()+10)
                self.no_mutation()

    def test_invalid_registry_and_creation_context_fail_before_native_mutation(self):
        baseline = copy.deepcopy(self.s.state)
        changes = [lambda f: f.pop('Human'), lambda f: f.update(Foreign={}),
            lambda f: f['Born'].update(tag='Human'), lambda f: f['Born'].update(base=base.BASE),
            lambda f: f['Born'].update(status='intent'), lambda f: f['Born'].update(runId='foreign'),
            lambda f: f['Born'].update(worldGeneration=2), lambda f: f['Born']['game'].update(pid=99),
            lambda f: f['Born']['creationWitness'].update(forcePersist=False),
            lambda f: f['Born'].pop('nativePersistentIdentity'),
            lambda f: f['Born'].update(reference='0x00000014'),
            lambda f: f['Born'].update(reference=f['Human']['reference'])]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state = copy.deepcopy(baseline); self.s.calls.clear()
                change(self.s.state['interactiveActorFixtures'])
                with self.assertRaises(ValueError): self.execute('save')
                self.no_mutation()

    def test_saved_policy_and_creation_identity_cannot_be_replaced(self):
        self.execute('save')
        baseline = copy.deepcopy(self.s.state)
        changes = [lambda s: s['configuration']['interactive_session'].pop('npcPersistenceRoster'),
            lambda s: s['configuration']['interactive_session']['npcPersistenceRoster']['fixtures'].update(Born=base.BASE),
            lambda s: s['npcPersistence']['unit-save'].pop('rosterPolicy'),
            lambda s: s['interactiveActorFixtures']['Born']['creationWitness'].update(priorActorCount=700)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state = copy.deepcopy(baseline); self.s.calls.clear(); change(self.s.state)
                with self.assertRaises(ValueError): self.execute()
                with self.assertRaises(ValueError): self.execute('load')
                self.assertFalse(any(tool == 'game' for tool, _ in self.s.calls))

    def test_partial_or_stale_native_remap_never_publishes_replacement_roster(self):
        self.execute('save')
        baseline, receipt = copy.deepcopy(self.s.state), copy.deepcopy(self.s.receipt)
        changes = [lambda r: r['actors'].pop(), lambda r: r['actors'][0].update(handleResolved=False),
            lambda r: r['actors'][0].update(base=base.BASE),
            lambda r: r['actors'][0].update(currentVmHandle=r['actors'][1]['currentVmHandle']),
            lambda r: r['actors'][0].update(currentReference=r['actors'][1]['currentReference'])]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state, self.s.receipt = copy.deepcopy(baseline), copy.deepcopy(receipt)
                self.s.bad_receipt = lambda r: change(r) if r.get('phase') == 'loaded' else None
                with self.assertRaises(ValueError): self.execute('load')
                self.assertTrue(all(e['status'] == 'load-uncertain' for e in self.s.state['interactiveActorFixtures'].values()))

    def test_postload_partial_registry_or_rebindings_cannot_pass_read_or_actor_guard(self):
        self.execute('save'); self.execute('load')
        baseline = copy.deepcopy(self.s.state)
        changes = [lambda s: s['interactiveActorFixtures'].pop('Human'),
            lambda s: s['npcPersistence']['unit-save']['rebindings'].pop('Human'),
            lambda s: s['npcPersistence']['unit-save']['loadedReceipt']['actors'][0].update(handleResolved=False)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state = copy.deepcopy(baseline); change(self.s.state)
                with self.assertRaises(ValueError): self.execute()
                entry = self.s.state['interactiveActorFixtures']['Born']
                with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {'reference': entry['reference'], 'base': BORN})

    def test_policy_loss_after_load_also_refuses_ordinary_restored_actor_guard(self):
        self.execute('save'); self.execute('load')
        baseline = copy.deepcopy(self.s.state)
        for matrix in (False, True):
            with self.subTest(matrix=matrix):
                self.s.state = copy.deepcopy(baseline)
                settings = self.s.state['configuration']['interactive_session']
                settings.pop('npcPersistenceRoster')
                if matrix: settings['matrixLifecycle'] = {'maximumFixtures': 2}
                entry = self.s.state['interactiveActorFixtures']['Born']
                with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {'reference': entry['reference'], 'base': BORN})

    def test_stale_or_foreign_peer_cannot_pass_another_members_restored_guard(self):
        self.execute('save'); self.execute('load')
        baseline = copy.deepcopy(self.s.state)
        saved = baseline['npcPersistence']['unit-save']['fixtures']['Human']
        changes = [lambda e: e.update(runId='foreign'), lambda e: e.update(reference=saved['reference']),
            lambda e: e.update(worldGeneration=1), lambda e: e.update(creationId='a'*32),
            lambda e: e['creationWitness'].update(forcePersist=False),
            lambda e: e['nativePersistentIdentity'].update(providerSession='other'),
            lambda e: e['incarnation'].update(loadGeneration=1)]
        for index, change in enumerate(changes):
            with self.subTest(index=index):
                self.s.state = copy.deepcopy(baseline)
                change(self.s.state['interactiveActorFixtures']['Human'])
                entry = self.s.state['interactiveActorFixtures']['Born']
                with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {'reference': entry['reference'], 'base': BORN})

    def test_generic_adapter_allocates_primitive_budgets_without_refreshing_parent(self):
        parent = time.monotonic()+120
        for action, maximum in (('save', 30), ('load', 90)):
            with self.subTest(action=action), patch.object(npc_persistence, 'perform', return_value={'synthetic': True}) as perform:
                platform.execute(self.s, self.args(action), parent)
                child = perform.call_args.args[2]
                self.assertGreater(child, time.monotonic())
                self.assertLessEqual(child, parent)
                self.assertLessEqual(child-time.monotonic(), maximum)

    def test_lost_save_ack_remains_terminal_and_never_replayed(self):
        self.s.fail = 'save'
        with self.assertRaises(TimeoutError): self.execute('save')
        self.s.fail = None
        with self.assertRaises(ValueError): self.execute('save')
        self.assertEqual(sum(tool == 'game' and args['action'] == 'save' for tool, args in self.s.calls), 1)


class GenericCreationTests(unittest.TestCase):
    def test_actual_creation_adapter_accepts_a_declared_born_beast_without_any_morph_policy(self):
        creation.FixtureActorTests.setUp(self)
        settings = self.session.state['configuration']['interactive_session']
        self.session.state['configuration']['game_edition'] = 'se'
        settings.update(npcPersistence=True, npcPersistenceRoster={'mode': 'generic-two-actor-v1',
            'fixtures': {'M1': creation.BASE, 'Second': creation.BASE}})
        self.session.race = BEAST
        original = self.session.tool
        def native(tool, args, **kwargs):
            if tool == 'papyrus' and args.get('script') == 'ActorBase' and args.get('function') == 'GetRace':
                return {'returned': {'formId': BEAST}}
            return original(tool, args, **kwargs)
        self.session.tool = native
        result = fixture_actors.create(self.session, dict(creation.REQUEST, persistentForOwnedSave=True),
                                      time.monotonic()+10, creation.POLICY)
        self.assertEqual(result['actor']['race'], BEAST)
        self.assertTrue(result['actor']['persistentSaveWitnessAvailable'])
        self.assertEqual(len(self.session.state['interactiveActorFixtures']), 1)
        self.assertEqual(self.session.mutations[0]['args'], [{'form': creation.BASE}, 1, True, False])
        self.assertFalse(any(call['function'] == 'SetRace' for call in self.session.mutations))
