"""Offline regressions for compound SE steps and their strict primitive budgets.

The request shapes/timeouts mirror the retained 38-step passive matrix scenario.
Creation uses the existing fake engine and the real creation/witness code. Other
primitive boundaries are captured so this file needs no game, runtime or CLI.
"""
import copy
import math
import unittest
from unittest.mock import patch

from skyrim_autotest import actor_inspection, fixture_actors, fixture_anchor
from skyrim_autotest import interactive_bindings as bindings
from skyrim_autotest import matrix_evaluator, matrix_lifecycle, morph_session
from skyrim_autotest import npc_persistence, platform, visual_freeze
from tests.test_actor_inspection import request as inspection_request
from tests.test_fixture_actors import FixtureSession, REQUEST
from tests.test_matrix_lifecycle import configuration
from tests.test_morph_session import Session, BASE, REF, HUMAN, BEAST, policy


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class OfflineBackend(platform.Backend):
    """Keep real semantic/deadline behavior, replacing only live world ownership."""
    def __init__(self, session, deadline):
        super().__init__(session, deadline)
        self.initial_end = deadline
        session.backends.append(self)

    def guard_world(self): self.s.guards += 1

    def pause(self, seconds):
        if seconds >= self.remaining():
            raise TimeoutError('Insufficient operation time for settling')
        self.s.clock.advance(seconds)


def matrix_settings(session, *, freeze=True, empty=False):
    config, frozen = configuration()
    if freeze:
        config['freezeActors'] = True
        frozen['bindings'].append({'id': 'hold', 'script': 'Actor', 'function': 'SetDontMove',
            'scope': 'member', 'params': ['bool'], 'returnType': 'none', 'effect': 'mutate',
            'actorSelf': True, 'actorArgs': [], 'raceArgs': [], 'completion': 'native-return'})
    session.state['configuration'] = {'game_edition': 'se', 'native_session': {
        'npcPersistence': True, 'matrixLifecycle': config, 'nativeBindings': frozen}}
    fixtures = {} if empty else {'Fixture': {'status': 'created', 'creationId': 'c' * 32, 'humanRace': HUMAN}}
    session.state['matrixLifecycle'] = {'fixtures': fixtures, 'snapshots': {}, 'mutations': []}
    session.state['activeSemanticCommandId'] = 'semantic-command'
    session.backends = []
    return config, frozen


def frozen_result(session, tag):
    entry = session.state['interactiveActorFixtures'][tag]
    return {'fixture': {'tag': tag, 'creationId': entry['creationId'], 'visualFrozen': True, 'dontMove': True},
            'actor': {'aiEnabled': False, 'collisionsEnabled': False},
            'incarnation': copy.deepcopy(entry['incarnation']),
            'native': dict.fromkeys(visual_freeze.GUARDS, 1) | {
                'pid': session.state['game']['pid'], 'currentReference': entry['reference'], 'base': entry['base'],
                'referenceCollisionsEnabled': False}}


class SemanticFixtureSession(FixtureSession):
    """Reuse the real-create fake engine, adding only semantic base resolution."""
    def __init__(self, clock):
        super().__init__()
        self.clock, self.guards, self.backends = clock, 0, []
        self.native_deadlines = []

    def tool(self, tool, args, timeout, deadline):
        self.native_deadlines.append((tool, args.get('function'), deadline, self.clock.now))
        if tool == 'papyrus' and args.get('function') == 'GetFormFromFile':
            self.calls.append((tool, copy.deepcopy(args)))
            return {'returned': {'formId': BASE}}
        # The creation fake enforces creation's own durable SetDontMove intent.
        # A later declared hold uses the real guarded binding instead.
        entry = self.state.get('interactiveActorFixtures', {}).get(REQUEST['tag'], {})
        if tool == 'papyrus' and args.get('function') == 'SetDontMove' and entry.get('status') == 'created':
            if args.get('self') != {'form': REF} or args.get('args') != [True]:
                raise AssertionError('Unexpected postcreation hold target/arguments')
            self.calls.append((tool, copy.deepcopy(args)))
            self.mutations.append(copy.deepcopy(args))
            self.on_mutation('SetDontMove')
            return {'called': True, 'returned': None, 'returnedType': 'None'}
        return super().tool(tool, args, timeout, deadline)


def create_request(session):
    """Use the reviewed fixed-anchor route with the existing engine's M1/base."""
    session.state['configuration']['se_fixture_anchor'] = fixture_anchor.RECIPE
    session.state['fixtureAnchor'] = {'recipe': fixture_anchor.RECIPE, 'status': 'prepared',
        'preparationId': 'a' * 32, 'runId': session.state['id'], 'game': copy.deepcopy(session.state['game']),
        'worldGeneration': 1, 'steps': {'MoveTo': 'returned', 'SetAngle': 'returned'},
        'target': {**fixture_anchor.TARGET, 'reference': session.marker,
            'incarnation': {'sessionId': 'observer-session', 'loadGeneration': 1, 'runtimeHandle': session.marker_handle},
            'position': list(fixture_anchor.TARGET_POSITION)},
        'playerIncarnation': {'sessionId': 'observer-session', 'loadGeneration': 1, 'runtimeHandle': 111},
        'expectedPosition': list(fixture_anchor.POSITION), 'position': list(fixture_anchor.POSITION),
        'headingDegrees': fixture_anchor.HEADING}
    return {'operation': 'object.perform', 'request': {'domain': 'actor-fixture', 'action': 'create',
        'actor': {'fixtureTag': REQUEST['tag']}, 'base': {'plugin': 'Skyrim.esm', 'formId': BASE},
        'placement': {'basis': fixture_actors.FIXED_BASIS, 'forwardGameUnits': 372.05517578125, 'rightGameUnits': -300.0},
        'persistence': 'save-load-witness-required', 'maximumCreations': 2}}


class DeadlineTestCase(unittest.TestCase):
    def setUp(self):
        self.clock, self.captured = Clock(), []
        self.parent = None
        patches = [patch.object(bindings.time, 'monotonic', self.clock),
                   patch('skyrim_autotest.native.alive', return_value=True)]
        patches += [patch.object(module, 'Backend', OfflineBackend)
                    for module in (platform, morph_session, matrix_lifecycle, fixture_actors, bindings)]
        for value in patches:
            value.start()
            self.addCleanup(value.stop)

    def capture(self, name, deadline, maximum=30):
        self.assertEqual(deadline, min(self.parent, self.clock.now + maximum), name)
        self.assertGreater(deadline, self.clock.now, name)
        self.assertLessEqual(deadline - self.clock.now, maximum, name)
        if maximum == 30:
            bindings.bounded_deadline(deadline)
        self.captured.append((name, deadline, self.clock.now, maximum))

    def run_step(self, session, args, seconds):
        session.clock = self.clock
        self.parent = self.clock.now + seconds
        result = platform.execute(session, args, self.parent)
        # The compound backend retains the caller's complete budget throughout.
        parents = [backend for backend in session.backends if backend.initial_end == self.parent]
        self.assertTrue(parents)
        self.assertTrue(all(backend.end == self.parent for backend in parents))
        return result


class ChildDeadlineTests(DeadlineTestCase):
    def test_children_cap_only_primitives_and_preserve_shorter_parent(self):
        for seconds, maximum, expected in ((60, 30, 30), (120, 30, 30), (180, 90, 90),
                                            (12, 30, 12), (12, 90, 12)):
            with self.subTest(seconds=seconds, maximum=maximum):
                parent = self.clock.now + seconds
                self.assertEqual(bindings.child_deadline(parent, maximum), self.clock.now + expected)
                self.assertEqual(parent, 1000 + seconds)

    def test_elapsed_time_uses_original_absolute_parent_and_cannot_refresh_budget(self):
        parent = self.clock.now + 60
        self.assertEqual(bindings.child_deadline(parent), 1030)
        self.clock.advance(45)
        self.assertEqual(bindings.child_deadline(parent), 1060)
        self.clock.advance(14)
        self.assertEqual(bindings.child_deadline(parent, 90), 1060)
        self.clock.advance(1)
        with self.assertRaises(ValueError): bindings.child_deadline(parent)
        self.assertEqual(parent, 1060)

    def test_invalid_parent_or_noncontractual_maximum_is_rejected(self):
        invalid = (None, True, False, '1060', math.nan, math.inf, -math.inf, 0, -1,
                   self.clock.now, self.clock.now - 1, 10 ** 1000)
        for value in invalid:
            with self.subTest(parent=str(value)[:40]), self.assertRaises(ValueError):
                bindings.child_deadline(value)
        for value in (None, True, False, 30.0, 90.0, '30', 0, 29, 31, 60, 120):
            with self.subTest(maximum=value), self.assertRaises(ValueError):
                bindings.child_deadline(1060, value)

    def test_public_binding_and_bounded_deadline_still_reject_long_direct_call(self):
        session = Session()
        request = {'bindingId': 'refresh', 'args': [{'reference': REF, 'base': BASE}]}
        for deadline in (1030.001, 1060, 1090):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError): bindings.bounded_deadline(deadline)
                with self.assertRaises(ValueError): bindings.guarded_call(session, request, deadline, policy())
        self.assertEqual(session.calls, [])
        self.assertEqual(session.state['morphSession']['mutations'], [])
        bindings.bounded_deadline(1030)


class SemanticCreationDeadlineTests(DeadlineTestCase):
    def new_session(self):
        session = SemanticFixtureSession(self.clock)
        matrix_settings(session, empty=True)
        return session

    def create_with_strict_boundaries(self, session, seconds, *, spend=False):
        actual_create, actual_binding = fixture_actors.create, bindings.guarded_call

        def create(s, request, deadline, frozen):
            self.capture('real fixture create', deadline)
            return actual_create(s, request, deadline, frozen)

        def bound(s, request, deadline, frozen):
            self.capture('real guarded SetDontMove', deadline)
            return actual_binding(s, request, deadline, frozen)

        def freeze(s, args, deadline, frozen):
            self.capture('freeze ' + args['operation'], deadline)
            if args['operation'] == 'world.read':
                result = frozen_result(s, REQUEST['tag'])
                result['fixture']['dontMove'] = False
                if spend: self.clock.advance(4)
                return result
            if spend: self.clock.advance(20)
            return {'preparation': {'completed': True}}

        def require(s, tag, deadline, frozen):
            self.capture('require frozen', deadline)
            return frozen_result(s, tag)

        if spend: session.on_mutation = lambda function: self.clock.advance(4)
        with patch.object(fixture_actors, 'create', side_effect=create) as creation, \
                patch.object(bindings, 'guarded_call', side_effect=bound) as hold, \
                patch.object(visual_freeze, 'execute', side_effect=freeze), \
                patch.object(visual_freeze, 'require_frozen', side_effect=require):
            result = self.run_step(session, create_request(session), seconds)
        self.assertEqual(creation.call_count, 1)
        self.assertEqual(hold.call_count, 1)
        return result

    def test_sixty_second_platform_create_reaches_real_witness_then_bounded_freeze_and_hold(self):
        session = self.new_session()
        result = self.create_with_strict_boundaries(session, 60, spend=True)
        self.assertEqual(result['fixture']['status'], 'created')
        entry = fixture_actors.require_fixture(session, {'reference': REF, 'base': BASE})
        self.assertTrue(entry['creationWitness']['nativeReturned'])
        self.assertTrue(entry['creationWitness']['forcePersist'])
        self.assertEqual(entry['nativePersistentIdentity']['currentVmHandle'], '9001')
        self.assertEqual(entry['steps'], dict.fromkeys(('PlaceAtMe', 'SetDontMove', 'MoveTo', 'SetAngle'), 'returned'))
        self.assertEqual([call['function'] for call in session.mutations],
                         ['PlaceAtMe', 'SetDontMove', 'MoveTo', 'SetAngle', 'SetDontMove'])
        self.assertEqual(session.mutations[0]['args'], [{'form': BASE}, 1, True, False])
        self.assertEqual(session.mutations[2]['args'][0], {'form': session.marker})
        self.assertEqual(session.state['matrixLifecycle']['fixtures'][REQUEST['tag']]['creationId'], entry['creationId'])
        self.assertEqual(session.state['matrixLifecycle']['mutations'][0]['status'], 'returned')
        self.assertTrue(result['inspectionFreeze']['after']['fixture']['visualFrozen'])
        self.assertEqual(self.parent, 1060)
        self.assertEqual(self.captured[0][1], 1030)
        self.assertEqual(self.captured[-1][1], self.parent)
        self.assertLess(self.captured[-1][1] - self.captured[-1][2], 30)
        for tool, function, deadline, started in session.native_deadlines:
            if function == 'GetFormFromFile':
                self.assertEqual(deadline, self.parent)  # Ordinary semantic resolution retains its parent.
                continue
            self.assertGreater(deadline - started, 0, (tool, function))
            self.assertLessEqual(deadline - started, 30, (tool, function))

    def test_short_parent_is_preserved_across_real_creation_and_postcreation_calls(self):
        session = self.new_session()
        self.create_with_strict_boundaries(session, 12)
        self.assertTrue(self.captured)
        self.assertTrue(all(deadline == 1012 for _, deadline, _, _ in self.captured))
        self.assertTrue(all(backend.end == 1012 for backend in session.backends))

    def test_invalid_parent_stops_before_creation_or_semantic_mutation_intent(self):
        for deadline in (None, True, False, '1060', math.nan, math.inf, -math.inf, 0, 999, 1000):
            session = self.new_session()
            args = create_request(session)
            before = copy.deepcopy(session.state)
            with self.subTest(deadline=deadline), self.assertRaises((ValueError, TimeoutError)):
                platform.execute(session, args, deadline)
            self.assertEqual(session.state, before)
            self.assertEqual(session.mutations, [])
            self.assertEqual(session.calls, [])
            self.assertEqual(session.saved, [])

    def test_lost_creation_callback_stays_uncertain_and_is_never_replayed(self):
        session = self.new_session()
        session.fail_after = 'PlaceAtMe'
        self.parent = self.clock.now + 60
        args = create_request(session)
        with patch.object(visual_freeze, 'execute') as freeze:
            with self.assertRaisesRegex(TimeoutError, 'lost native callback'):
                platform.execute(session, args, self.parent)
            self.assertEqual(session.state['interactiveActorFixtures'][REQUEST['tag']]['status'], 'uncertain')
            retained = copy.deepcopy(session.state)
            with self.assertRaises(ValueError): platform.execute(session, args, self.parent)
            self.assertEqual(session.state, retained)
            session.state['activeSemanticCommandId'] = 'different-command'
            with self.assertRaises(ValueError): platform.execute(session, args, self.parent)
            freeze.assert_not_called()
        self.assertEqual([call['function'] for call in session.mutations], ['PlaceAtMe'])
        self.assertEqual(session.state['matrixLifecycle']['mutations'][0]['status'], 'intent')


class SemanticPrimitiveDeadlineTests(DeadlineTestCase):
    def new_session(self):
        session = Session()
        matrix_settings(session)
        return session

    def freeze(self, session, args, deadline, frozen):
        self.capture('visual freeze', deadline)
        result = frozen_result(session, args['request']['actor']['fixtureTag'])
        if args['operation'] == 'object.perform': result['preparation'] = {'completed': True}
        self.clock.advance(1)
        return result

    def require(self, session, tag, deadline, frozen):
        self.capture('frozen roster read', deadline)
        self.clock.advance(1)
        return frozen_result(session, tag)

    def binding(self, session, request, deadline, frozen):
        self.capture('guarded ' + request['bindingId'], deadline)
        self.clock.advance(1)
        values = {'status': 5, 'error': '', 'humanWeight': .5, 'beastWeight': .5,
                  'hasHumanTrait': True, 'getHumanTrait': 1.1, 'selectedFamily': 'Example.UNP'}
        return {'returned': values.get(request['bindingId'], True), 'result': {'actor': {'race': BEAST}}}

    def test_sixty_second_freeze_identity_refresh_and_ninety_second_race_cap_primitives(self):
        requests = [
            (60, 'world.read', {'domain': 'actor-visual-freeze', 'actor': {'fixtureTag': 'Fixture'}}),
            (60, 'world.read', {'domain': 'actor-fixture-identity', 'actor': {'fixtureTag': 'Fixture'}}),
            (60, 'object.perform', {'domain': 'morph-link', 'action': 'refresh', 'actor': {'fixtureTag': 'Fixture'}}),
            (90, 'object.perform', {'domain': 'actor-race', 'action': 'change-current-race',
                'actor': {'fixtureTag': 'Fixture'}, 'race': BEAST, 'preserveBaseRecord': True}),
        ]
        for seconds, operation, request in requests:
            with self.subTest(domain=request['domain']):
                session = self.new_session()
                self.captured = []
                def guard(s, spec, deadline, frozen):
                    self.capture('fixture guard', deadline)
                    return {'actor': {'reference': REF, 'base': BASE, 'sex': 'female', 'race': HUMAN, 'loaded3D': True}}
                with patch.object(visual_freeze, 'execute', side_effect=self.freeze), \
                        patch.object(visual_freeze, 'require_frozen', side_effect=self.require), \
                        patch.object(bindings, 'guarded_call', side_effect=self.binding), \
                        patch.object(fixture_actors, 'guard', side_effect=guard):
                    self.run_step(session, {'operation': operation, 'request': request}, seconds)
                self.assertTrue(self.captured)
                self.assertTrue(all(maximum == 30 for _, _, _, maximum in self.captured))

    def test_120_second_matrix_read_keeps_parent_for_observation_and_caps_each_native_binding(self):
        session = self.new_session()
        request = {'domain': 'actor-matrix-state', 'actor': {'fixtureTag': 'Fixture'},
                   'stage': 'human', 'captureSnapshot': 'HumanBaseline', 'familyId': 'Example.UNP'}
        def evaluate(config, family, sources, weight, timeout):
            self.assertEqual(timeout, self.parent - self.clock.now)
            self.assertGreater(timeout, 30)
            self.clock.advance(3)
            return {'outputs': {'TargetA': .2, 'Unmapped': 0}, 'graph': {'sources': []}}
        with patch.object(visual_freeze, 'require_frozen', side_effect=self.require), \
                patch.object(bindings, 'guarded_call', side_effect=self.binding), \
                patch.object(matrix_evaluator, 'evaluate', side_effect=evaluate) as evaluator:
            result = self.run_step(session, {'operation': 'world.read', 'request': request}, 120)
        self.assertEqual(evaluator.call_count, 1)
        self.assertEqual(result['matrix']['mismatchCount'], 0)
        self.assertEqual(result['matrix']['selectedFamily']['value'], 'Example.UNP')
        self.assertEqual({name for name, _, _, _ in self.captured if name.startswith('guarded ')},
                         {'guarded ' + name for name in ('status', 'error', 'humanWeight', 'beastWeight',
                                                        'hasHumanTrait', 'getHumanTrait', 'selectedFamily')})
        self.assertEqual(session.state['matrixLifecycle']['mutations'], [])
        self.assertIn('HumanBaseline', session.state['matrixLifecycle']['snapshots'])

    def test_120_second_save_180_second_load_and_save_read_use_existing_primitive_caps(self):
        requests = [
            (120, 30, 'object.perform', {'domain': 'save-state', 'action': 'save-disposable-once',
                'saveLabel': 'OwnedSave', 'actors': ['Fixture', 'Peer'],
                'scope': 'current-temporary-profile', 'maximumSaves': 1}),
            (180, 90, 'object.perform', {'domain': 'save-state', 'action': 'load-owned-disposable-once',
                'saveLabel': 'OwnedSave', 'maximumLoads': 1, 'processRestart': False}),
            (60, 30, 'world.read', {'domain': 'save-state', 'saveLabel': 'OwnedSave'}),
        ]
        for seconds, maximum, operation, request in requests:
            with self.subTest(action=request.get('action')):
                session = self.new_session()
                self.captured = []
                def persistence(s, translated, deadline, frozen):
                    self.capture('persistence ' + translated.get('action', 'read'), deadline, maximum)
                    if maximum == 90: self.clock.advance(80)
                    return {'save': {'completed': True}}
                with patch.object(npc_persistence, 'perform', side_effect=persistence) as perform, \
                        patch.object(npc_persistence, 'observe', side_effect=persistence) as observe, \
                        patch.object(visual_freeze, 'execute', side_effect=self.freeze), \
                        patch.object(visual_freeze, 'require_frozen', side_effect=self.require):
                    self.run_step(session, {'operation': operation, 'request': request}, seconds)
                target = observe if operation == 'world.read' else perform
                self.assertEqual(target.call_count, 1)
                if maximum == 90:
                    self.assertEqual(perform.call_args.args[1], {'action': 'load', 'saveTag': 'OwnedSave'})
                    self.assertGreater(len(self.captured), 1)  # Postload preparation remains bounded by the same parent.
                    self.assertTrue(all(cap == 30 for _, _, _, cap in self.captured[1:]))

    def test_inspection_routes_cap_primitives_while_preserving_frozen_roster(self):
        session = self.new_session()
        request = inspection_request()
        request['actor']['fixtureTag'] = 'Fixture'
        def inspect(s, args, deadline, frozen):
            self.capture('inspection', deadline)
            return {'actual': True}
        with patch.object(actor_inspection, 'execute', side_effect=inspect), \
                patch.object(visual_freeze, 'require_frozen', side_effect=self.require):
            result = self.run_step(session, {'operation': 'world.read', 'request': request}, 60)
        self.assertTrue(result['actual'])
        self.assertIn('inspectionFreeze', result)

    def test_legacy_morph_dispatch_derives_children_for_real_guard_binding_and_persistence(self):
        requests = [
            (60, 'world.read', {'domain': 'actor-fixture-identity', 'actor': {'fixtureTag': 'Fixture'}}),
            (60, 'object.perform', {'domain': 'human-preset', 'action': 'unassign', 'actor': {'fixtureTag': 'Fixture'}}),
            (60, 'object.perform', {'domain': 'morph-link', 'action': 'refresh', 'actor': {'fixtureTag': 'Fixture'}}),
            (90, 'object.perform', {'domain': 'actor-race', 'action': 'change-current-race',
                'actor': {'fixtureTag': 'Fixture'}, 'race': BEAST, 'preserveBaseRecord': True}),
            (120, 'object.perform', {'domain': 'save-state', 'action': 'save-disposable-once',
                'saveLabel': 'OwnedSave', 'actors': ['Fixture' + str(i) for i in range(6)],
                'scope': 'current-temporary-profile', 'maximumSaves': 1}),
            (180, 'object.perform', {'domain': 'save-state', 'action': 'load-owned-disposable-once',
                'saveLabel': 'OwnedSave', 'maximumLoads': 1, 'processRestart': False}),
            (60, 'world.read', {'domain': 'save-state', 'saveLabel': 'OwnedSave'}),
        ]
        actual_guard, actual_binding = fixture_actors.guard, bindings.guarded_call
        for seconds, operation, request in requests:
            with self.subTest(domain=request['domain'], action=request.get('action')):
                session = Session()
                session.backends, self.captured = [], []
                def guard(s, spec, deadline, frozen):
                    self.capture('real legacy fixture guard', deadline)
                    return actual_guard(s, spec, deadline, frozen)
                def bound(s, req, deadline, frozen):
                    self.capture('real legacy binding', deadline)
                    return actual_binding(s, req, deadline, frozen)
                def persistence(s, translated, deadline, frozen):
                    maximum = 90 if translated.get('action') == 'load' else 30
                    self.capture('legacy persistence', deadline, maximum)
                    return {'save': {'completed': True}}
                with patch.object(fixture_actors, 'guard', side_effect=guard), \
                        patch.object(bindings, 'guarded_call', side_effect=bound), \
                        patch.object(npc_persistence, 'perform', side_effect=persistence), \
                        patch.object(npc_persistence, 'observe', side_effect=persistence):
                    self.run_step(session, {'operation': operation, 'request': request}, seconds)
                self.assertTrue(self.captured)
                if request['domain'] == 'actor-race':
                    self.assertEqual(session.race, BEAST)
                    calls = [args for tool, args in session.calls if tool == 'papyrus' and args.get('function') == 'SetRace']
                    self.assertEqual(len(calls), 1)


if __name__ == '__main__': unittest.main()
