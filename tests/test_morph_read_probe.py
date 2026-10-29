import copy
import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).resolve().parents[1] / "tools/prepare_morph_read_probe.py"
spec = importlib.util.spec_from_file_location("prepare_morph_read_probe", MODULE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def source():
    presets = [{"name": f"{sex}{n}", "sex": sex, "set": "ExampleSet"} for sex in ("male", "female") for n in range(3)]
    steps = [{"name": "ready", "operation": "state.read", "assert": [{"field": "world.ready", "equals": True}]}]
    def add(name, req, rules=None, operation="world.read"):
        step = {"name": name, "operation": operation, "parameters": {"request": copy.deepcopy(req)}, "timeout": 6}
        step.update({"assert": rules} if rules else {"observe": True})
        steps.append(step)
    add("catalog", {"domain": "human-preset-catalog", "presets": presets, "wolfPresetRequirement": "none"},
        [{"field": "catalog.missingRequestedPresetCount", "equals": 0}])
    add("config", {"domain": "human-provider-config", "presetPoolPolicy": "exact-six-existing-human-preset-elements",
        "requiredDisablePresetDistribution": "none", "otherActorsPolicy": "Exact test fixture",
        "baseSelectionPolicy": [{"plugin": "Example.esm", "baseFormId": f"0x{i+1:08X}", "allowedHumanPresets": [p["name"]]}
                                for i, p in enumerate(presets)]}, [{"field": "human.officialApiReady", "equals": True}])
    for i, preset in enumerate(presets):
        tag, sex = "Fixture" + str(i), preset["sex"]
        actor = {"fixtureTag": tag}
        add(tag + "-create", {"domain": "actor-fixture", "action": "create", "actor": actor,
            "base": {"plugin": "Example.esm", "formId": f"0x{i+1:08X}"}, "maximumCreations": 6,
            "persistence": "save-load-witness-required", "placement": {"forwardGameUnits": 200, "rightGameUnits": 0}}, operation="object.perform")
        add(tag + "-identity", {"domain": "actor-fixture-identity", "actor": actor},
            [{"field": "actor.sex", "equals": sex}, {"field": "actor.race", "equals": "0x00013746"}])
        for action in ("set-reference-display-name", "unequip-all-reference-gear", "hold-position-keep-collision", None):
            req = {"domain": "actor-fixture-inspection", "actor": actor, "displayName": tag, "nameScope": "reference-only",
                "phase": "initial", "requireActualOwnedReferenceWitness": True}
            if action:
                req.update(action=action, preserveInventory=True, editBaseNPC=False, editBaseOutfit=False,
                           collisionPolicy="retain-enabled", noRetryOnUnknownOutcome=True)
            else:
                req.update(wornArmorSlots=[30, 61], minimumPositionSamples=2, minimumObservationSpanMs=200, positionToleranceGameUnits=1.0)
            add(tag + "-inspection-" + str(action), req, operation="object.perform" if action else "world.read")
        add(tag + "-origin", {"domain": "human-preset-state", "actor": actor, "requireStockGenerationWitness": True,
            "requireAutomaticOrigin": True, "allowedHumanPresets": [preset["name"]], "manualGenerationOrAssignmentCallsBeforeThisObservation": 0},
            [{"field": "human.automaticGenerationWitnessCount", "min": 1}])
        source_count, target_count, row_count = (61, 24, 95) if sex == "male" else (52, 25, 70)
        rows = [{"sourceMorph": "Source" + str(n % source_count), "targetMorph": "Target" + str(n % target_count), "gain": -.5, "cap": 1.}
                for n in range(row_count)]
        vector = {"domain": "actor-morph-link-evaluation", "actor": actor, "familyId": "Example.Geometry",
                  "rows": rows, "publicTargets": ["Target" + str(n) for n in range(target_count)], "ownKey": "Example.Distribution",
                  "sourceValueMeaning": "actual-SKEE-aggregate", "stage": "human-own-clear", "captureSnapshot": tag + "-base"}
        coverage = [{"field": "sources.aggregateReadCount", "equals": source_count},
                    {"field": "own.targetReadCount", "equals": target_count}]
        add(tag + "-human", vector, [{"field": "claw.status", "equals": 5}, *coverage])
        for phase, race in (("beast", "0x000CDD84"), ("return", "0x00013746")):
            add(tag + "-race-" + phase, {"domain": "actor-race", "actor": actor, "action": "change-current-race", "race": race,
                "preserveBaseRecord": True}, operation="object.perform")
            req = {**copy.deepcopy(vector), "stage": "linked-beast" if phase == "beast" else "human-own-clear",
                   "captureSnapshot": tag + "-" + phase, "compareSnapshot": tag + "-base"}
            add(tag + "-vector-" + phase, req, [{"field": "mapping.maxAbsoluteError", "max": .0001}, *copy.deepcopy(coverage)])
    return {"schemaVersion": 2, "id": "subject", "profile": "Test", "inputs": [{"path": "example.dll", "sha256": "a" * 64, "role": "subject"}],
            "subjectPlan": {"interface": "polygon-actions/1", "fixture": {"cell": "QASmoke", "startMode": "new-game"}, "steps": steps}}


class ProbeTests(unittest.TestCase):
    def build(self, original):
        return probe.build_probe(original, "component-test", source_chat="tool", source_thread_id="actual-tool-thread")

    def test_six_refs_two_inspections_full_signed_templates_no_subject_output_verdict(self):
        original = source()
        before = copy.deepcopy(original)
        result, coverage = self.build(original)
        self.assertEqual(original, before)
        self.assertEqual(len(result["subjectPlan"]["steps"]), 59)
        self.assertEqual(result["sourceThreadId"], "actual-tool-thread")
        self.assertEqual(len(coverage["inspectionRepresentatives"]), 2)
        self.assertEqual(len(coverage["vectorCoverage"]), 18)
        self.assertEqual({(r["sourceCount"], r["targetCount"], r["rowCount"]) for r in coverage["vectorCoverage"]}, {(61, 24, 95), (52, 25, 70)})
        vectors = [s for s in result["subjectPlan"]["steps"] if probe.request(s).get("domain") == "actor-morph-link-evaluation"]
        self.assertTrue(all(r["gain"] < 0 for s in vectors for r in probe.request(s)["rows"]))
        self.assertFalse(any(r["field"] in ("claw.status", "mapping.maxAbsoluteError") for s in vectors for r in s["assert"]))
        self.assertFalse(coverage["qualified"])
        self.assertFalse(coverage["subjectModAccepted"])

    def test_unknown_or_provider_writing_action_refuses_instead_of_silent_omission(self):
        for domain in ("human-preset", "morph-link", "actor-morph-fixture", "unknown"):
            value = source()
            value["subjectPlan"]["steps"].append({"name": "unexpected", "operation": "object.perform", "parameters": {"request": {"domain": domain}}})
            with self.subTest(domain=domain), self.assertRaisesRegex(ValueError, "refuses"):
                self.build(value)

    def test_missing_origin_race_or_vector_coverage_refuses(self):
        for domain in ("human-preset-catalog", "human-provider-config", "human-preset-state", "actor-race", "actor-morph-link-evaluation"):
            value = source()
            steps = value["subjectPlan"]["steps"]
            index = next(i for i, s in enumerate(steps) if probe.request(s).get("domain") == domain)
            steps.pop(index)
            with self.subTest(domain=domain), self.assertRaises(ValueError): self.build(value)

    def test_filtered_inspection_still_requires_valid_reference_only_action(self):
        value = source()
        for step in value["subjectPlan"]["steps"]:
            req = probe.request(step)
            if req.get("actor", {}).get("fixtureTag") == "Fixture1" and req.get("domain") == "actor-fixture-inspection" and "action" in req:
                req["editBaseNPC"] = True
                break
        with self.assertRaisesRegex(ValueError, "invalid or unsupported"): self.build(value)

    def test_duplicate_actor_selector_cannot_hide_another_fixture(self):
        for domain in ("human-preset-state", "actor-race", "actor-morph-link-evaluation"):
            value = source()
            for step in value["subjectPlan"]["steps"]:
                req = probe.request(step)
                if req.get("domain") == domain and req.get("actor", {}).get("fixtureTag") == "Fixture1":
                    req["actor"]["fixtureTag"] = "Fixture0"
            with self.subTest(domain=domain), self.assertRaisesRegex(ValueError, "per-fixture"):
                self.build(value)

    def test_truncated_vector_and_wrong_snapshot_or_return_race_refuse(self):
        for defect in ("vector", "snapshot", "race"):
            value = source()
            for step in value["subjectPlan"]["steps"]:
                req = probe.request(step)
                if req.get("actor", {}).get("fixtureTag") != "Fixture0": continue
                if defect == "vector" and req.get("domain") == "actor-morph-link-evaluation":
                    req["rows"] = req["rows"][:1]
                    break
                if defect == "snapshot" and "compareSnapshot" in req:
                    req["compareSnapshot"] = "Fixture1-base"
                    break
                if defect == "race" and req.get("domain") == "actor-race" and req["race"] == "0x00013746":
                    req["race"] = "0x000CDD84"
                    break
            with self.subTest(defect=defect), self.assertRaises(ValueError): self.build(value)


if __name__ == "__main__": unittest.main()
