import copy
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import fixture_actors, interactive, matrix_lifecycle as subject
from skyrim_autotest import matrix_evaluator, morph_session, native_session, platform_mapping, visual_freeze, actor_inspection
from tests.test_morph_session import Session, FakeBackend, policy, declaration, BASE, HUMAN, BEAST


def configuration(selected=True):
    signatures = subject.SIGNATURES | ({"selectedFamily": ([], "string", "read")} if selected else {})
    entries = policy()["bindings"]
    roles = {entry["id"]: entry["id"] for entry in entries if entry["id"] in signatures}
    for role, (params, returned, effect) in signatures.items():
        if role not in roles:
            entries.append(declaration(role, returned, effect, params))
            roles[role] = role
    frozen = policy()
    frozen["bindings"] = entries
    root = Path.cwd().resolve()
    config = {"maximumFixtures": 2, "bindings": roles, "sourceMorphs": [], "beastRace": BEAST,
              "traitSources": ["$human.height"], "publicTargets": ["TargetA", "Unmapped"],
              "ownKey": "Example.Distribution", "evaluator": {
                  "executable": str(root / "external.exe"), "executableSha256": "a" * 64,
                  "matrix": str(root / "external.xml"), "matrixSha256": "b" * 64}}
    return config, frozen


class MatrixLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.session = Session()
        self.config, self.policy = configuration()
        self.settings = {"npcPersistence": True, "matrixLifecycle": self.config, "nativeBindings": self.policy}
        self.session.state["configuration"] = {"game_edition": "se", "native_session": self.settings}
        self.session.state["matrixLifecycle"] = {"fixtures": {"Fixture": {"status": "created", "creationId": "c" * 32, "humanRace": HUMAN}},
                                                 "snapshots": {}, "mutations": []}
        self.family, self.trait_available, self.predicted = "Example.UNP", True, .2
        self.mock_prediction = patch.object(matrix_evaluator, "evaluate", side_effect=self.evaluate).start()
        self.addCleanup(patch.stopall)
        patch("skyrim_autotest.native.alive", return_value=True).start()
        patch.object(morph_session, "Backend", FakeBackend).start()
        patch.object(subject, "Backend", FakeBackend).start()
        patch.object(fixture_actors, "Backend", FakeBackend).start()
        patch.object(subject, "_value", side_effect=self.value).start()

    def value(self, session, config, policy, role, spec, deadline, extras=()):
        return {"status": 5, "error": "", "humanWeight": .5, "beastWeight": .5,
                "hasHumanTrait": self.trait_available, "getHumanTrait": 1.1,
                "selectedFamily": self.family}[role]

    def evaluate(self, config, family, values, weight, timeout):
        return {"available": True, "graph": {"profile": family, "sources": [
                {"name": "$human.height", "kind": "human-height"}], "targets": ["TargetA"]},
                "outputs": {"TargetA": self.predicted, "Unmapped": 0.0},
                "inputs": {"sources": copy.deepcopy(values), "weightRaw": weight}}

    def observe(self, label="HumanBaseline", **extra):
        request = {"domain": "actor-matrix-state", "actor": {"fixtureTag": "Fixture"}, "stage": "human",
                   "captureSnapshot": label, "familyId": "Example.UNP", **extra}
        return morph_session.execute(self.session, {"operation": "world.read", "request": request}, time.monotonic() + 25, self.policy)

    def test_empty_available_sources_no_obody_and_complete_absent_zero_targets(self):
        result = self.observe()
        matrix = result["matrix"]
        self.assertTrue(matrix["ordinarySourceMapAvailable"])
        self.assertTrue(matrix["ordinarySourceMapEmpty"])
        self.assertEqual(matrix["publicTargetCount"], 2)
        self.assertEqual(matrix["mismatchCount"], 0)
        self.assertFalse(matrix["targets"]["Unmapped"]["namePresent"])
        self.assertFalse(matrix["targets"]["Unmapped"]["ownKeyPresent"])
        self.assertFalse(any("obody" in args or tool == "morph_provider" for tool, args in self.session.calls))

    def test_unavailable_trait_is_not_zero_or_observed(self):
        self.trait_available = False
        result = self.observe()
        trait = result["matrix"]["traits"]["$human.height"]
        self.assertFalse(trait["available"])
        self.assertIsNone(trait["value"])
        self.assertNotIn("$human.height", self.mock_prediction.call_args.args[2])
        self.assertEqual(result["matrix"]["availability"], "partial")

    def test_selected_family_is_observed_and_can_mismatch(self):
        self.family = "Different.Actual.Family"
        result = self.observe()
        self.assertEqual(result["matrix"]["selectedFamily"]["value"], self.family)
        self.assertNotEqual(result["matrix"]["selectedFamily"]["value"], result["matrix"]["requestedFamily"])
        self.assertFalse(result['matrix']['nativeParityAvailable'])

    def test_missing_selected_family_binding_stays_unavailable(self):
        del self.config["bindings"]["selectedFamily"]
        result = self.observe()
        self.assertFalse(result["matrix"]["selectedFamily"]["available"])
        self.assertIsNone(result["matrix"]["selectedFamily"]["value"])

    def test_beast_uses_same_actor_human_baseline_and_native_outputs(self):
        self.observe()
        self.session.own_value = .2
        self.session.race = BEAST
        result = self.observe("Wolf", stage="beast", baselineSnapshot="HumanBaseline")
        self.assertEqual(result["matrix"]["mismatchCount"], 0)
        self.assertTrue(result["matrix"]["sourcePreserved"])
        self.assertTrue(result["matrix"]["weightPreserved"])
        self.assertEqual(self.mock_prediction.call_args.args[3], 50)

    def test_missing_or_foreign_baseline_never_becomes_current_source(self):
        self.session.race = BEAST
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.observe("Wolf", stage="beast", baselineSnapshot="Missing")
        self.session.race = HUMAN
        self.observe()
        self.session.race = BEAST
        self.session.state["matrixLifecycle"]["snapshots"]["HumanBaseline"]["creationId"] = "foreign"
        with self.assertRaisesRegex(ValueError, "baseline"):
            self.observe("Wolf", stage="beast", baselineSnapshot="HumanBaseline")

    def test_failed_skee_read_is_not_available_empty_and_retains_no_snapshot(self):
        original = self.session.observer
        def unavailable(request):
            result = original(request)
            if 'skee' in result:
                result['skee'][0]['status'] = 'unavailable'
            return result
        with patch.object(self.session, 'observer', side_effect=unavailable):
            with self.assertRaisesRegex(ValueError, "changed.*batches"):
                self.observe()
        self.assertFalse(self.session.state["matrixLifecycle"]["snapshots"])

    def test_native_partial_target_vector_and_missing_trait_catalog_refused(self):
        with patch.object(matrix_evaluator, "evaluate", return_value={"outputs": {"TargetA": .2}, "graph": {"sources": []}}):
            with self.assertRaisesRegex(ValueError, "complete.*target"):
                self.observe()
        self.config["traitSources"] = []
        with self.assertRaisesRegex(ValueError, "undeclared human"):
            self.observe()

    def test_snapshot_labels_are_immutable_and_read_has_no_game_mutation(self):
        self.observe()
        count = len(self.session.calls)
        with self.assertRaisesRegex(ValueError, "already retained"):
            self.observe()
        self.assertEqual(len(self.session.calls), count)

    def test_configuration_scopes_and_exact_signature(self):
        self.assertEqual(subject.validate_config(self.config, self.policy)["sourceMorphs"], [])
        broken = copy.deepcopy(self.config)
        broken["maximumFixtures"] = True
        with self.assertRaises(ValueError): subject.validate_config(broken, self.policy)
        broken = copy.deepcopy(self.config)
        broken["sourceMorphs"] = ["Same", "same"]
        with self.assertRaises(ValueError): subject.validate_config(broken, self.policy)
        broken = copy.deepcopy(self.policy)
        next(row for row in broken["bindings"] if row["id"] == "getHumanTrait")["effect"] = "mutate"
        with self.assertRaises(ValueError): subject.validate_config(self.config, broken)
        self.assertEqual(native_session.validate(self.settings)["matrixLifecycle"]["maximumFixtures"], 2)
        with self.assertRaises(ValueError): native_session.validate(dict(self.settings, morphSession={}))

    def test_two_actor_request_admission_and_no_opt_in_refusal(self):
        request = {"domain": "actor-fixture", "action": "create", "actor": {"fixtureTag": "Second"},
                   "base": {"plugin": "Example.esm", "formId": "0x0013475"},
                   "placement": {"forwardGameUnits": 100, "rightGameUnits": 0},
                   "maximumCreations": 2, "persistence": "save-load-witness-required"}
        self.assertTrue(morph_session.validate("object.perform", request))
        self.session.state["configuration"] = Session().state["configuration"]
        with self.assertRaisesRegex(ValueError, "Two-actor creation"):
            morph_session.execute(self.session, {"operation": "object.perform", "request": request}, time.monotonic() + 25, policy())

    def test_vr_matrix_execution_refused_and_mapping_explicit(self):
        self.session.state["configuration"]["game_edition"] = "vr"
        with self.assertRaisesRegex(ValueError, "SE opt-in"):
            self.observe()
        self.assertNotIn("matrix.sources", platform_mapping.operations()["world.read"]["fields"])
        self.assertIn("matrix.sources", platform_mapping.matrix_operations()["world.read"]["fields"])

    def test_counterfactual_remains_separate_and_cannot_override_trait(self):
        result = self.observe(counterfactual={"weightRaw": 100})
        self.assertEqual(result["matrix"]["nativePrediction"]["inputs"]["weightRaw"], 50)
        self.assertEqual(result["matrix"]["counterfactual"]["inputs"]["weightRaw"], 100)
        with self.assertRaisesRegex(ValueError, "Counterfactual"):
            self.observe("Other", counterfactual={"sources": {"$human.height": 8}})

    def test_declared_stage_cannot_turn_a_wolf_into_a_human_baseline(self):
        self.session.race = BEAST
        with self.assertRaisesRegex(ValueError, 'stage differs'):
            self.observe()
        self.assertFalse(self.session.state['matrixLifecycle']['snapshots'])

    def test_foreign_or_partial_roster_is_not_adopted(self):
        self.session.state['interactiveActorFixtures']['Foreign'] = copy.deepcopy(self.session.state['interactiveActorFixtures']['Fixture'])
        with self.assertRaisesRegex(ValueError, 'all and only'):
            self.observe()

    def test_empty_observed_map_can_have_explicit_hypothetical_ordinary_controls(self):
        self.config['counterfactualSourceMorphs'] = ['KnownControl']
        result = self.observe(counterfactual={'sources': {'KnownControl': .75}})
        self.assertEqual(result['matrix']['sources'], {})
        self.assertNotIn('KnownControl', result['matrix']['nativePrediction']['inputs']['sources'])
        cf = result['matrix']['counterfactual']
        self.assertEqual(cf['inputs']['sources']['KnownControl'], .75)
        self.assertIn('hypothetical', cf['basis'])

    def test_later_available_trait_cannot_upgrade_unavailable_baseline_inputs(self):
        self.trait_available = False
        self.observe()
        self.trait_available = True
        self.session.race = BEAST
        result = self.observe('Wolf', stage='beast', baselineSnapshot='HumanBaseline')
        self.assertEqual(result['matrix']['availability'], 'partial')
        self.assertFalse(result['matrix']['nativeParityAvailable'])
        self.assertFalse(result['matrix']['inputTraits']['$human.height']['available'])

    def test_interactive_admission_uses_new_mode_without_legacy_morph_session(self):
        settings = dict(self.settings, channelConfig=str(Path.cwd()/'channel.json'), maximumSeconds=60,
                        allowedTools=['platform','papyrus'], sourceId='operator.actions')
        checked = interactive.validate(settings)
        self.assertNotIn('morphSession', checked)
        request = {'schemaVersion':1,'operation':'tool','tool':'platform','timeoutSeconds':25,
            'args':{'operation':'world.read','request':{'domain':'actor-matrix-state',
                'actor':{'fixtureTag':'Fixture'},'stage':'human','captureSnapshot':'Fresh','familyId':'Example.UNP'}}}
        import json
        self.assertEqual(interactive._request(json.dumps(request), checked, self.session), request)

    def enable_freeze(self):
        self.config['freezeActors'] = True
        self.policy['bindings'].append({'id': 'hold', 'script': 'Actor', 'function': 'SetDontMove',
            'scope': 'member', 'params': ['bool'], 'returnType': 'none', 'effect': 'mutate',
            'actorSelf': True, 'actorArgs': [], 'raceArgs': [], 'completion': 'native-return'})

    def frozen(self, session, tag, deadline, policy):
        return {'fixture': {'tag': tag, 'visualFrozen': True, 'dontMove': True},
                'actor': {'aiEnabled': False, 'collisionsEnabled': False},
                'native': dict.fromkeys(visual_freeze.GUARDS, 1) | {'referenceCollisionsEnabled': False}}

    def test_frozen_policy_requires_bool_and_exact_hold_binding(self):
        self.config['freezeActors'] = 1
        with self.assertRaisesRegex(ValueError, 'Bool'):
            subject.validate_config(self.config, self.policy)
        self.config['freezeActors'] = True
        with self.assertRaisesRegex(ValueError, 'SetDontMove'):
            subject.validate_config(self.config, self.policy)
        del self.config['freezeActors']
        self.enable_freeze()
        self.assertTrue(subject.validate_config(self.config, self.policy)['freezeActors'])

    def test_unfrozen_fixture_stops_before_measurement_without_mutation_or_snapshot(self):
        self.enable_freeze()
        with patch.object(visual_freeze, 'require_frozen', side_effect=ValueError('controller still enabled')), \
                patch.object(visual_freeze, 'execute') as mutations:
            with self.assertRaisesRegex(ValueError, 'controller still enabled'): self.observe()
        mutations.assert_not_called()
        self.mock_prediction.assert_not_called()
        self.assertEqual(self.session.state['matrixLifecycle']['snapshots'], {})

    def test_snapshot_brackets_all_owned_actors_and_preserves_actual_flags(self):
        self.enable_freeze()
        with patch.object(visual_freeze, 'require_frozen', side_effect=self.frozen) as reads, \
                patch.object(visual_freeze, 'execute') as mutations:
            result = self.observe()
        mutations.assert_not_called()
        self.assertGreaterEqual(reads.call_count, 2)
        self.assertFalse(result['actor']['referenceCollisionsEnabled'])
        self.assertTrue(result['fixture']['dontMove'])
        self.assertIn('Fixture', result['inspectionFreeze']['before'])

    def test_model_change_across_matrix_measurement_cannot_retain_baseline(self):
        self.enable_freeze()
        values = [self.frozen(None, 'Fixture', None, None), self.frozen(None, 'Fixture', None, None)]
        values[1]['native']['sampledRootToken'] = 2
        with patch.object(visual_freeze, 'require_frozen', side_effect=values):
            with self.assertRaisesRegex(ValueError, 'Race/model/world changed'): self.observe()
        self.assertFalse(self.session.state['matrixLifecycle']['snapshots'])

    def test_creation_freezes_new_actor_before_success_and_failed_freeze_prevents_new_write(self):
        self.enable_freeze()
        template = copy.deepcopy(self.session.state['interactiveActorFixtures']['Fixture'])
        self.session.state['interactiveActorFixtures'] = {}
        self.session.state['matrixLifecycle']['fixtures'] = {}
        request = {'domain': 'actor-fixture', 'action': 'create', 'actor': {'fixtureTag': 'New'},
            'base': {'plugin': 'Example.esm', 'formId': '0x0013475'}, 'maximumCreations': 2,
            'placement': {'forwardGameUnits': 100, 'rightGameUnits': 0}, 'persistence': 'save-load-witness-required'}
        def create(session, req, deadline, policy):
            entry = copy.deepcopy(template); entry['tag'] = req['tag']; entry['actor']['race'] = HUMAN
            session.state['interactiveActorFixtures'][req['tag']] = entry
            return {'created': True}
        with patch.object(fixture_actors, 'create', side_effect=create), \
                patch.object(subject, '_freeze_actor', side_effect=TimeoutError('filter did not turn off')) as freeze:
            with self.assertRaisesRegex(TimeoutError, 'filter did not'):
                subject.execute(self.session, {'operation': 'object.perform', 'request': request}, time.monotonic()+25, self.policy)
        self.assertEqual(freeze.call_args.args[2], 'New')
        self.assertEqual(self.session.state['matrixLifecycle']['mutations'][0]['status'], 'intent')
        self.session.state['activeSemanticCommandId'] = 'new-write'
        with self.assertRaisesRegex(ValueError, 'Unsettled matrix'):
            subject._begin(self.session, {})
        self.assertFalse(self.session.state['matrixLifecycle']['snapshots'])

    def test_load_reprepares_both_owned_actors_and_race_reprepares_target(self):
        self.enable_freeze()
        other = copy.deepcopy(self.session.state['interactiveActorFixtures']['Fixture'])
        other.update(tag='Other', creationId='d'*32, reference='0xFF000456', createdReference='0xFF000456')
        other['creationWitness'].update(creationId='d'*32, reference='0xFF000456')
        self.session.state['interactiveActorFixtures']['Other'] = other
        self.session.state['matrixLifecycle']['fixtures']['Other'] = dict(status='created', creationId='d'*32, humanRace=HUMAN)
        with patch.object(subject.npc_persistence, 'perform', return_value={'load': {'completed': True}}), \
                patch.object(subject, '_freeze_actor', return_value={'verified': True}) as freeze:
            result = subject.execute(self.session, {'operation': 'object.perform', 'request': {
                'domain': 'save-state', 'action': 'load-owned-disposable-once', 'saveLabel': 'save-one',
                'maximumLoads': 1, 'processRestart': False}}, time.monotonic()+25, self.policy)
        self.assertEqual({call.args[2] for call in freeze.call_args_list}, {'Fixture', 'Other'})
        self.assertEqual(set(result['inspectionFreeze']), {'Fixture', 'Other'})
        self.session.state['activeSemanticCommandId'] = 'race-next'
        with patch.object(subject, '_binding', return_value={'domainCompletion': 'observed-race-readback'}) as mutation, \
                patch.object(subject, '_freeze_actor', return_value={'verified': True}) as freeze:
            result = subject.execute(self.session, {'operation': 'object.perform', 'request': {
                'domain': 'actor-race', 'action': 'change-current-race', 'actor': {'fixtureTag': 'Fixture'},
                'race': BEAST, 'preserveBaseRecord': True}}, time.monotonic()+25, self.policy)
        self.assertEqual(mutation.call_args.args[3], 'race')
        self.assertEqual(freeze.call_args.args[2], 'Fixture')
        self.assertTrue(result['inspectionFreeze']['verified'])

    def test_inspection_write_uses_same_uncertainty_barrier_and_preserves_collision_off(self):
        from tests.test_actor_inspection import request as inspection_request
        self.enable_freeze()
        req = inspection_request('set-reference-display-name')
        req['actor']['fixtureTag'] = 'Fixture'; req['collisionPolicy'] = 'preserve-current'
        self.assertEqual(actor_inspection.validate('object.perform', req)['collisionPolicy'], 'preserve-current')
        self.session.state['matrixLifecycle']['mutations'].append({'commandId': 'earlier', 'status': 'intent'})
        with patch.object(visual_freeze, 'require_frozen', side_effect=self.frozen), \
                patch.object(actor_inspection, 'execute') as mutate:
            with self.assertRaisesRegex(ValueError, 'Unsettled matrix'):
                subject.execute(self.session, {'operation': 'object.perform', 'request': req}, time.monotonic()+25, self.policy)
        mutate.assert_not_called()

    def test_transition_reapplies_explicit_locomotion_hold_before_freeze(self):
        self.enable_freeze()
        before = self.frozen(None, 'Fixture', None, None)
        before['fixture']['dontMove'] = False
        prepared = {'preparation': {'completed': True}}
        with patch.object(visual_freeze, 'execute', side_effect=[before, prepared]), \
                patch.object(visual_freeze, 'require_frozen', side_effect=self.frozen), \
                patch.object(subject.bindings, 'guarded_call', return_value={'returned': None}) as hold:
            result = subject._freeze_actor(FakeBackend(self.session, time.monotonic()+25), self.policy, 'Fixture')
        self.assertEqual(hold.call_args.args[1]['args'], [True])
        self.assertEqual(hold.call_args.args[1]['self']['reference'], self.session.state['interactiveActorFixtures']['Fixture']['reference'])
        self.assertTrue(result['after']['fixture']['dontMove'])

    def test_uncertain_freeze_blocks_even_the_hold_setter_under_a_new_command(self):
        self.enable_freeze()
        self.session.state['visualFreeze'] = {'commands': {'earlier': {'creationId': 'c'*32, 'status': 'uncertain'}}}
        with patch.object(visual_freeze, 'execute') as prepare, patch.object(subject.bindings, 'guarded_call') as hold:
            with self.assertRaisesRegex(ValueError, 'Uncertain visual-freeze'):
                subject._freeze_actor(FakeBackend(self.session, time.monotonic()+25), self.policy, 'Fixture')
        prepare.assert_not_called(); hold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
