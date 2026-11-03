import copy
from pathlib import Path
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import fixture_actors, interactive, matrix_lifecycle as subject
from skyrim_autotest import matrix_evaluator, morph_session, native_session, platform_mapping
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


if __name__ == "__main__":
    unittest.main()
