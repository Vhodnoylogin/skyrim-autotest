import copy
import hashlib
import json
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import morph_session as subject, fixture_actors, interactive_bindings, morph_analysis
from skyrim_autotest.scenarios import check as assertion_check


REF, BASE, HUMAN, BEAST = "0xFF000123", "0x00013475", "0x00013746", "0x000CDD84"
TEST_KEYS = ["Example.Test.ForeignHuman", "Example.Test.ZeroHuman", "Example.Test.ForeignBeast"]
SOURCES = [f"Source{index}" for index in range(33)]
ROWS = [{"sourceMorph": name, "targetMorph": "TargetA", "gain": 1 / 33, "cap": 1} for name in SOURCES]


def declaration(role, return_type, effect="read", extra=None):
    return {"id": role, "script": "ExampleNative", "function": role, "scope": "global", "params": ["actor"] + (extra or []),
            "returnType": return_type, "effect": effect, "actorSelf": False, "actorArgs": [0], "raceArgs": [], "completion": "native-return"}


def policy():
    entries = [declaration("status", "int"), declaration("error", "string"), declaration("assigned", "string"),
               declaration("humanWeight", "float"), declaration("beastWeight", "float"),
               declaration("clear", "bool", "mutate"), declaration("refresh", "bool", "mutate"), declaration("configure", "bool", "mutate", ["string"])]
    entries.append({"id": "race", "script": "Actor", "function": "SetRace", "scope": "member", "params": ["race"], "returnType": "none",
                    "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [0], "completion": "actor-race"})
    return {"schemaVersion": 1, "fixtureActorBases": [BASE], "allowedRaceForms": [HUMAN, BEAST], "bindings": entries}


def evaluation(label="baseline", **changes):
    return {"domain": "actor-morph-link-evaluation", "actor": {"fixtureTag": "Fixture"}, "stage": "human-own-clear",
            "captureSnapshot": label, "familyId": "Example.Geometry", "rows": copy.deepcopy(ROWS), "publicTargets": ["TargetA", "Unmapped"],
            "ownKey": "Example.Distribution", "sourceValueMeaning": "actual-SKEE-aggregate", **changes}


class FakeBackend(subject.Backend):
    def guard_world(self):
        self.s.guards += 1


class Session:
    def __init__(self):
        self.calls, self.logs, self.guards, self.saves = [], [], 0, 0
        self.race, self.handle, self.epoch, self.generation, self.root = HUMAN, 12, 3, 1, 23
        self.status, self.assigned, self.own_value = 5, "F1", 0.0
        self.fail_mutation, self.unsafe_guard, self.unavailable, self.event_gap = False, False, False, False
        self.events, self.next_sequence = [], 10
        self.fixture_values = {}
        self.weights = {"humanWeight": .5, "beastWeight": .5}
        settings = {"bindings": {role: role for role in subject.ROLES}, "testKeys": TEST_KEYS,
                    "providerOwnKeys": ["Provider"], "providerKeyEvidence": {"sourceCommit": "a" * 40, "providerSha256": "b" * 64},
                    "sourceMorphsBySex": {"female": SOURCES, "male": SOURCES}}
        self.state = {"id": "test-run", "game": {"pid": 123, "path": "owned.exe", "birth": 456}, "testProfile": "Disposable",
            "ownedWorldGeneration": 1, "gameplayBootstrap": {"completed": True}, "activeSemanticCommandId": "command-1",
            "configuration": {"game_edition": "se", "interactive_session": {"morphSession": settings, "nativeBindings": policy(), "npcPersistence": True}}}
        entry = {"tag": "Fixture", "status": "created", "runId": "test-run", "game": copy.deepcopy(self.state["game"]), "base": BASE,
            "reference": REF, "createdReference": REF, "worldGeneration": 1, "creationId": "c" * 32,
            "actor": {"sex": "female"}, "incarnation": {"sessionId": "observer", "loadGeneration": 1, "runtimeHandle": 12},
            "creationWitness": {"method": "ObjectReference.PlaceAtMe", "runId": "test-run", "creationId": "c" * 32, "reference": REF,
                "base": BASE, "anchor": "0x00000014", "count": 1, "nativeReturned": True, "forcePersist": True,
                "priorActorCount": 0, "priorActorsSha256": "d" * 64},
            "nativePersistentIdentity": {"protocol": "npc-persistence/1", "pid": 123, "providerSession": "persistent-provider", "persistent": True,
                "currentReference": REF, "base": BASE, "currentVmHandle": "5678", "runtimeHandle": 12}}
        self.state["interactiveActorFixtures"] = {"Fixture": entry}
        self.state["morphSession"] = {"owner": "e" * 32, "fixtures": {"Fixture": {"creationId": "c" * 32, "manualHumanCalls": 0, "manualFamilyCalls": 0,
            "worldGeneration": 1, "eventIntent": {"observerSession": "observer", "observerGeneration": 1, "providerEpoch": 3,
                "afterSequence": 1, "producerMonotonicNs": 1000}}}, "snapshots": {}, "mutations": [], "metadata": {}}

    def log(self, kind, **data): self.logs.append((kind, copy.deepcopy(data)))
    def save(self): self.saves += 1
    def identity(self, ref=REF): return {"form": ref, "loadGeneration": self.generation, "runtimeHandle": self.handle if ref == REF else self.handle + 1}
    def actor(self):
        return {"status": "available", "baseForm": BASE, "race": self.race, "baseRace": HUMAN, "sex": 1,
                "weight": {"status": "available", "rawNPCWeight": 50, "normalizedNPCWeight": .5}}
    def control(self):
        return {"actorFormId": REF, "baseFormId": BASE, "raceFormId": self.race, "runtimeHandle": 99 if self.unsafe_guard else self.handle,
                "modelIdentity": "model", "worldGeneration": 2, "pid": 123}
    def observer(self, request):
        reference = (request.get("refs") or request.get("skee", {}).get("refs") or request.get("obody", {}).get("refs") or [REF])[0]
        root = {"sampledRootToken": self.root, "firstPerson": False}
        out = {"ok": True, "sessionId": "observer", "loadGeneration": self.generation, "producerMonotonicNs": 5000,
               "refs": [], "quality": "complete"}
        if request.get("refs"):
            out["refs"] = [{"status": "available", "deleted": False, "disabled": False, "loaded3D": True, "identity": self.identity(reference),
                            "baseForm": BASE, "rootIdentity": root, "actor": self.actor()}]
        if "skee" in request:
            rows = []
            for name in request["skee"]["morphs"]:
                if name in SOURCES:
                    present, value, keys = True, .2, [{"key": "Provider", "status": "available", "value": 9.0}, {"key": "Unrelated", "status": "available", "value": -4.0}]
                elif name == "TargetA":
                    present, value, keys = True, self.own_value, ([{"key": "Example.Distribution", "status": "available", "value": self.own_value}] if self.own_value else []) + [{"key": "Foreign.Target", "status": "available", "value": .7}]
                else: present, value, keys = False, 0, []
                keys.extend({"key": key, "status": "available", "value": item["value"]} for key, item in self.fixture_values.items() if item["morph"] == name)
                rows.append({"name": name, "status": "unavailable" if self.unavailable and name == SOURCES[-1] else "available",
                    "namePresence": {"status": "available", "present": present or bool(keys)}, "aggregate": {"status": "available", "value": value},
                    "keys": {"status": "available", "entries": keys, "retainedCount": len(keys), "callbackCount": len(keys), "truncated": False,
                             "invalidKey": False, "nonFinite": False, "captureFailure": False, "providerTraversalCompleted": True}})
            out["skee"] = [{"status": "available", "provider": {"status": "available", "interfaceVersion": 5, "interfaceEpoch": 1},
                            "identity": self.identity(reference), "rootIdentity": root, "morphs": rows}]
        if "obody" in request:
            out["obody"] = {"status": "available", "quality": "partial" if self.event_gap else "complete",
                "provider": {"interfaceAvailable": True, "ready": True, "actorListenerRegistered": True, "epoch": self.epoch},
                "retention": {"droppedTotal": int(self.event_gap), "callbackFailuresTotal": 0, "missingBeforeRetained": 0,
                    "truncatedTextFieldsTotal": 0, "cursorAhead": False, "moreAvailable": False, "latestSequence": self.next_sequence},
                "events": copy.deepcopy(self.events), "assignments": []}
            if request["obody"].get("refs"):
                out["obody"]["assignments"] = [{"status": "available", "actorForm": reference, "providerEpoch": self.epoch, "assigned": bool(self.assigned),
                    "presetName": {"value": self.assigned, "truncated": False}}]
        return out

    def tool(self, tool, args, timeout, deadline):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "inspect": return self.observer(args)
        if tool == "fixture_config": return copy.deepcopy(self.config_read)
        if tool == "npc_persistence": return copy.deepcopy(self.state["interactiveActorFixtures"]["Fixture"]["nativePersistentIdentity"])
        if tool == "morph_provider":
            action = args["action"]
            if action == "actor_status": return {"pid": 123, "identity": self.control(), "identityCurrentAfterRead": True}
            if action == "catalog":
                names = {"female": ["F1", "F2", "F3"], "male": ["M1", "M2", "M3"], "female_blacklisted": [], "male_blacklisted": []}[args["category"]]
                values = names[args["offset"]:args["offset"] + args["limit"]]
                return {"pid": 123, "providerEpoch": self.epoch, "counts": {"female": 3, "femaleBlacklisted": 0, "male": 3, "maleBlacklisted": 0}, "names": values, "returnedCount": len(values)}
            if args["guard"] != self.control(): raise AssertionError("provider received a different guarded actor")
            if action == "assign_preset": self.assigned = args["presetName"]
            elif action == "unassign_preset": self.assigned = ""
            elif action == "set_test_morphs": self.fixture_values.update({item["key"]: item for item in args["values"]})
            elif action == "remove_test_keys":
                for key in args["keys"]: self.fixture_values.pop(key, None)
            if self.fail_mutation: raise TimeoutError("actual call may have applied; response lost")
            return {"status": "call_returned", "providerAccepted": True, "identityCurrentAfterCall": True, "identity": args["guard"], "completion": "unobserved"}
        if tool == "papyrus":
            if args["action"] == "describe":
                result = {"name": args["script"], "memberFunctions": [], "globalFunctions": []}
                for entry in policy()["bindings"]:
                    if entry["script"] == args["script"]:
                        result["memberFunctions" if entry["scope"] == "member" else "globalFunctions"].append({"name": entry["function"], "native": True,
                            "params": [{"type": kind} for kind in entry["params"]], "returnType": entry["returnType"]})
                return result
            function = args["function"]
            if function == "GetFormFromFile": return {"returned": {"formId": BASE}}
            if function == "GetActorBase": return {"returned": {"formId": BASE}}
            if function == "GetRace": return {"returned": {"formId": self.race}}
            if function == "GetSex": return {"returned": 1}
            if function == "GetWeight": return {"returned": 50}
            entry = next(item for item in policy()["bindings"] if item["function"] == function)
            returned = {"status": self.status, "error": "", "assigned": "", **self.weights}.get(function, True)
            if function == "clear": self.status, self.own_value = 6, 0
            if function == "configure": self.status, self.own_value = 2, .2
            if function == "SetRace": self.race = args["args"][0]["form"]; self.status = 2 if self.race == BEAST else 5; self.own_value = .2 if self.race == BEAST else 0; returned = None
            return {"called": True, "returned": returned, "returnedType": entry["returnType"]}
        raise AssertionError((tool, args))


class MorphSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = Session(); self.policy = policy()
        self.patches = [patch.object(subject, "Backend", FakeBackend), patch.object(fixture_actors, "Backend", FakeBackend),
                        patch.object(interactive_bindings, "Backend", FakeBackend), patch("skyrim_autotest.native.alive", return_value=True)]
        for value in self.patches: value.start()
        self.addCleanup(lambda: [value.stop() for value in reversed(self.patches)])

    def execute(self, request, *, command="command-1", seconds=10):
        self.session.state["activeSemanticCommandId"] = command
        read = request["domain"] in ("human-preset-state", "actor-morph-link-evaluation", "human-preset-catalog", "human-provider-config", "actor-fixture-identity") or (request["domain"] == "save-state" and "action" not in request)
        return subject.execute(self.session, {"operation": "world.read" if read else "object.perform", "request": request}, time.monotonic() + seconds, self.policy)

    def test_full_observed_vectors_use_aggregate_not_keys_and_batch32(self):
        self.session.race, self.session.status, self.session.own_value = BEAST, 2, .2
        result = self.execute(evaluation(stage="linked-beast"))
        self.assertAlmostEqual(result["mapping"]["maxAbsoluteError"], 0)
        self.assertEqual(result["sources"]["aggregateReadCount"], 33)
        self.assertEqual(result["raw"]["sources"][SOURCES[0]]["keys"][0]["value"], 9)
        self.assertEqual(result["raw"]["sources"][SOURCES[0]]["value"], .2)
        reads = [args["skee"]["morphs"] for tool, args in self.session.calls if tool == "inspect" and "skee" in args]
        self.assertEqual([len(names) for names in reads], [32, 3, 1])
        self.assertFalse(any(tool == "morph_provider" and args["action"] not in ("catalog", "actor_status") for tool, args in self.session.calls))
        self.assertTrue(self.session.guards > 0)

    def test_unavailable_one_source_does_not_become_zero_or_pass(self):
        self.session.unavailable = True
        with self.assertRaisesRegex(ValueError, "incomplete"): self.execute(evaluation())
        self.assertFalse(self.session.state["morphSession"]["snapshots"])

    def test_unknown_visited_form_weight_is_unavailable(self):
        self.session.weights["humanWeight"] = -1
        self.session.status = 1
        result = self.execute(evaluation())
        self.assertEqual(result["quality"], "partial")
        self.assertEqual(result["weight"]["observationStatus"], "unavailable")
        self.assertIsNone(result["weight"]["humanObservationAbsoluteError"])
        self.assertEqual(result["claw"]["humanWeight"], -1)
        self.assertEqual(result["raw"]["subjectDiagnostics"]["humanWeight"], -1)
        self.assertEqual(result["actor"]["weightRaw"], 50)
        self.assertEqual(result["actor"]["weightNormalized"], .5)
        self.assertFalse(assertion_check(result, {"path": "weight.humanObservationAbsoluteError", "max": .0001}))
        self.assertEqual(result["sources"]["unavailableReadCount"], 0)
        self.session.weights["humanWeight"], self.session.status = .5, 5
        settled = self.execute(evaluation(), command="later-read")
        self.assertEqual(settled["quality"], "complete")
        self.assertEqual(settled["weight"]["observationStatus"], "available")
        self.assertTrue(assertion_check(settled, {"path": "weight.humanObservationAbsoluteError", "max": .0001}))
        self.assertEqual(self.session.state["morphSession"]["mutations"], [])

    def test_unknown_beast_diagnostic_is_partial_but_unvisited_unknown_is_preserved(self):
        self.session.weights["beastWeight"] = -1
        human = self.execute(evaluation("human"))
        self.assertEqual(human["quality"], "complete")
        self.assertEqual(human["claw"]["beastWeight"], -1)
        self.session.race, self.session.status, self.session.own_value = BEAST, 2, .2
        beast = self.execute(evaluation("beast", stage="linked-beast"))
        self.assertEqual(beast["quality"], "partial")
        self.assertIsNone(beast["weight"]["beastObservationAbsoluteError"])
        self.assertFalse(assertion_check(beast, {"path": "weight.beastObservationAbsoluteError", "max": .0001}))

    def test_span_preserves_unknown_subject_quantity_instead_of_hiding_first_sample(self):
        original = subject._capture_once
        count = 0
        def capture(*args):
            nonlocal count
            self.session.weights["humanWeight"] = -1 if count == 0 else .5
            count += 1
            return original(*args)
        with patch.object(subject, "_capture_once", side_effect=capture):
            result = self.execute(evaluation("unknown-span", minimumObservationSpanSeconds=.01))
        self.assertGreaterEqual(count, 2)
        self.assertEqual(result["quality"], "partial")
        self.assertEqual(result["weight"]["observationStatus"], "unavailable")
        self.assertIsNone(result["weight"]["humanObservationAbsoluteError"])
        self.assertEqual(result["interval"]["samples"][0]["claw"]["humanWeight"], -1)
        self.assertEqual(result["interval"]["samples"][-1]["claw"]["humanWeight"], .5)

    def test_pending_to_settled_span_preserves_transition_without_channel_exception(self):
        original = subject._capture_once
        count = 0
        self.session.race = BEAST
        def capture(*args):
            nonlocal count
            self.session.status = 1 if count == 0 else 2
            self.session.own_value = .35 if count == 0 else .2
            count += 1
            return original(*args)
        with patch.object(subject, "_capture_once", side_effect=capture):
            result = self.execute(evaluation("pending-span", stage="linked-beast", minimumObservationSpanSeconds=.01))
        self.assertEqual(result["quality"], "partial")
        self.assertIsNone(result["claw"]["status"])
        self.assertEqual(result["claw"]["statusObservationStatus"], "unavailable")
        self.assertEqual(result["interval"]["statusTransitionCount"], 1)
        self.assertEqual(result["interval"]["lastObservedStatus"], 2)
        self.assertEqual(result["claw"]["lastObservedStatus"], 2)
        self.assertEqual(result["interval"]["samples"][0]["claw"]["status"], 1)
        self.assertEqual(result["interval"]["samples"][-1]["claw"]["status"], 2)
        self.assertEqual(result["raw"]["subjectDiagnostics"]["status"], 2)
        self.assertEqual(result["own"]["maxAbsoluteCoefficient"], .35)
        self.assertFalse(assertion_check(result, {"path": "claw.status", "equals": 2}))
        self.assertEqual(self.session.state["morphSession"]["mutations"], [])

    def test_stable_suppressed_span_keeps_numeric_subject_status(self):
        self.session.race, self.session.status, self.session.own_value = BEAST, 6, 0
        result = self.execute(evaluation("stable-six", stage="suppressed-own-clear", minimumObservationSpanSeconds=.01))
        self.assertEqual(result["quality"], "complete")
        self.assertEqual(result["claw"]["status"], 6)
        self.assertEqual(result["claw"]["statusObservationStatus"], "available")
        self.assertEqual(result["interval"]["statusTransitionCount"], 0)
        self.assertEqual(result["interval"]["lastObservedStatus"], 6)
        self.assertTrue(all(value == 6 for value in result["interval"]["observedStatuses"]))
        self.assertTrue(assertion_check(result, {"path": "claw.status", "equals": 6}))

    def test_exact_native_assignment_is_once_and_does_not_claim_completion(self):
        request = {"domain": "human-preset", "action": "assign", "actor": {"fixtureTag": "Fixture"}, "presetName": "F2", "applyImmediately": True, "assignmentOnly": False}
        result = self.execute(request)
        self.assertFalse(result["request"]["completed"])
        self.assertTrue(result["request"]["assignmentAccepted"])
        self.assertEqual(self.session.assigned, "F2")
        with self.assertRaisesRegex(ValueError, "already attempted"): self.execute(request)
        mutations = [args for tool, args in self.session.calls if tool == "morph_provider" and args["action"] == "assign_preset"]
        self.assertEqual(len(mutations), 1)
        self.assertEqual(self.session.state["morphSession"]["fixtures"]["Fixture"]["manualHumanCalls"], 1)

    def test_lost_provider_response_retains_intent_and_forbids_reentry(self):
        self.session.fail_mutation = True
        request = {"domain": "human-preset", "action": "unassign", "actor": {"fixtureTag": "Fixture"}}
        with self.assertRaises(TimeoutError): self.execute(request)
        with self.assertRaisesRegex(ValueError, "already attempted"): self.execute(request)
        self.assertEqual(sum(tool == "morph_provider" and args["action"] == "unassign_preset" for tool, args in self.session.calls), 1)

    def test_native_handle_mismatch_stops_before_mutation(self):
        self.session.unsafe_guard = True
        request = {"domain": "human-preset", "action": "unassign", "actor": {"fixtureTag": "Fixture"}}
        with self.assertRaisesRegex(ValueError, "guard differs"): self.execute(request)
        self.assertFalse(self.session.state["morphSession"]["mutations"])

    def test_stock_event_uses_birth_cursor_time_and_epoch_without_guessing_event_world(self):
        self.session.events = [{"sequence": 2, "event": "OnActorGenerated", "channel": "obody_native_actor_change", "actorForm": REF,
            "stockInternalGeneration": True, "responsibility": "obody_internal_stock", "providerReadyAtReceipt": True, "providerEpoch": 3,
            "producerMonotonicNs": 2000, "loadGeneration": 0, "responsibleOwner": {"value": None},
            "presetName": {"value": "F1", "truncated": False}}]
        request = {"domain": "human-preset-state", "actor": {"fixtureTag": "Fixture"}, "requireStockGenerationWitness": True,
            "requireAutomaticOrigin": True, "expectedStockEventResponsibleInterface": None, "allowedHumanPresets": ["F1", "F2", "F3"],
            "manualGenerationOrAssignmentCallsBeforeThisObservation": 0}
        result = self.execute(request)
        self.assertEqual(result["human"]["automaticGenerationWitnessCount"], 1)
        self.assertEqual(result["human"]["appliedSourceReadCount"], 33)
        self.session.state["morphSession"]["fixtures"]["Fixture"]["manualHumanCalls"] = 1
        with self.assertRaisesRegex(ValueError, "Manual provider action"): self.execute(request)

    def test_event_gap_or_foreign_responsibility_never_proves_stock_generation(self):
        self.session.event_gap = True
        with self.assertRaisesRegex(ValueError, "Complete current-epoch"): self.execute({"domain": "human-preset-state", "actor": {"fixtureTag": "Fixture"}})

    def test_exact_fixture_allowlist_signed_zero_and_observed_cleanup(self):
        values = [{"morph": SOURCES[0], "key": TEST_KEYS[0], "value": -.875}, {"morph": SOURCES[1], "key": TEST_KEYS[1], "value": 0}, {"morph": "TargetA", "key": TEST_KEYS[2], "value": .125}]
        request = {"domain": "actor-morph-fixture", "action": "set-keyed-coefficients-once", "values": values,
                   "sourceOfValues": "explicit independent contributions", "actor": {"fixtureTag": "Fixture"}}
        self.execute(request)
        observed = self.execute(evaluation("foreign"), command="read-1")
        self.assertEqual(observed["fixture"]["foreignHumanValue"], -.875)
        self.assertEqual(observed["fixture"]["zeroHumanKeyValue"], 0)
        self.assertTrue(observed["fixture"]["zeroHumanKeyPresenceRecorded"])
        invalid = copy.deepcopy(request); invalid["values"][0]["key"] = "Foreign.Test.Unowned"
        with self.assertRaisesRegex(ValueError, "outside the frozen"): self.execute(invalid, command="command-2")
        self.execute({"domain": "actor-morph-fixture", "action": "remove-exact-keys-once", "keys": TEST_KEYS, "actor": {"fixtureTag": "Fixture"}}, command="command-3")
        clean = self.execute(evaluation("clean"), command="read-2")
        self.assertEqual(clean["fixture"]["remainingOwnedTestKeyCount"], 0)
        self.assertEqual(clean["raw"]["targetKeys"]["TargetA"][0]["key"], "Foreign.Target")

    def test_full_named_snapshot_diffs_and_foreign_preservation(self):
        self.execute(evaluation())
        self.session.race, self.session.status, self.session.own_value = BEAST, 2, .2
        result = self.execute(evaluation("beast", stage="linked-beast", compareSnapshot="baseline"))
        self.assertEqual(result["preservation"]["changedHumanKeyEntryCount"], 0)
        self.assertEqual(result["preservation"]["changedForeignTargetEntryCount"], 0)
        self.assertEqual(result["comparison"]["changedExpectedTargetCount"], 1)
        self.assertEqual(result["comparison"]["changedOwnTargetEntryCount"], 1)

    def test_catalog_reads_each_sex_and_actual_fixed_vfs_config_pin(self):
        presets = [{"name": f"{prefix}{i}", "sex": sex, "set": "DeclaredSet"} for sex, prefix in (("female", "F"), ("male", "M")) for i in (1, 2, 3)]
        result = self.execute({"domain": "human-preset-catalog", "presets": presets, "wolfPresetRequirement": "none"})
        self.assertEqual(result["catalog"]["missingRequestedPresetCount"], 0)
        policies = [{"plugin": "Example.esm", "baseFormId": f"0x{i:08X}", "allowedHumanPresets": [f"{prefix}{n}" for n in (1, 2, 3)]} for i, prefix in enumerate(("M", "M", "M", "F", "F", "F"), 1)]
        parsed = {"disablePresetDistribution": "none", "npcFormID": {"Example.esm": {p["baseFormId"][2:]: p["allowedHumanPresets"] for p in policies}}}
        text = json.dumps(parsed); digest = hashlib.sha256(text.encode()).hexdigest()
        self.session.config_read = {"pid": 123, "path": "SKSE/Plugins/OBody_presetDistributionConfig.json", "rawText": text, "bytes": len(text), "inMemoryConfigObserved": False}
        self.session.state["configuration"]["interactive_session"]["morphSession"]["providerConfigSha256"] = digest
        request = {"domain": "human-provider-config", "presetPoolPolicy": "exact-six-existing-human-preset-elements", "baseSelectionPolicy": policies,
                   "otherActorsPolicy": "Reviewed bounded base policy", "requiredDisablePresetDistribution": "none"}
        self.assertEqual(self.execute(request)["human"]["config"]["disablePresetDistribution"], "none")
        self.session.config_read["rawText"] += " "
        with self.assertRaisesRegex(ValueError, "frozen staged pin"): self.execute(request)

    def test_typed_subject_queue_admission_and_same_reference_race(self):
        result = self.execute({"domain": "morph-link", "action": "clear-own", "actor": {"fixtureTag": "Fixture"}})
        self.assertTrue(result["request"]["admitted"]); self.assertFalse(result["request"]["completed"])
        result = self.execute({"domain": "actor-race", "action": "change-current-race", "race": BEAST, "preserveBaseRecord": True, "actor": {"fixtureTag": "Fixture"}}, command="race-1")
        self.assertEqual(result["actor"]["race"], BEAST)
        calls = [args for tool, args in self.session.calls if tool == "papyrus" and args.get("function") == "SetRace"]
        self.assertEqual(len(calls), 1)

    def test_frozen_config_is_required_and_read_role_cannot_mutate(self):
        self.session.state["configuration"]["game_edition"] = "vr"
        with self.assertRaisesRegex(ValueError, "frozen SE"): self.execute(evaluation())
        self.session.state["configuration"]["game_edition"] = "se"
        self.session.state["configuration"]["interactive_session"]["morphSession"]["bindings"]["status"] = "clear"
        with self.assertRaisesRegex(ValueError, "wrong frozen read/mutate"): self.execute(evaluation())

    def test_ordinary_unrelated_requests_are_not_claimed(self):
        self.assertFalse(subject.validate("world.read", {"quantity": "actor-base-weight"}))
        with self.assertRaises(ValueError): subject.validate("object.perform", evaluation())

    def test_native_request_deadline_never_starts_after_remaining_budget(self):
        backend = FakeBackend(self.session, time.monotonic() + .04)
        with self.assertRaisesRegex(TimeoutError, "Insufficient remaining time"):
            subject._call(backend, "morph_provider", {"action": "capabilities"})
        self.assertEqual(self.session.calls, [])
        self.session.config_read = {"rawText": "{}"}
        subject._call(FakeBackend(self.session, time.monotonic() + 10), "fixture_config", {"action": "obody"})
        self.assertEqual(self.session.calls[-1][1]["timeoutMs"], 3000)

    def test_persistent_creation_has_event_intent_before_one_actual_create(self):
        template = copy.deepcopy(self.session.state["interactiveActorFixtures"]["Fixture"])
        self.session.state["interactiveActorFixtures"] = {}; self.session.state["morphSession"]["fixtures"] = {}
        def create(session, request, deadline, configured):
            self.assertTrue(request["persistentForOwnedSave"])
            intent = session.state["morphSession"]["fixtures"]["Fresh"]
            self.assertEqual(intent["eventIntent"]["afterSequence"], 10)
            self.assertGreater(intent["createdMonotonicNs"], 0)
            value = copy.deepcopy(template); value["tag"] = "Fresh"
            session.state["interactiveActorFixtures"]["Fresh"] = value
            return {"fixture": {"tag": "Fresh", "status": "created"}}
        request = {"domain": "actor-fixture", "action": "create", "actor": {"fixtureTag": "Fresh"}, "base": {"plugin": "Skyrim.esm", "formId": BASE},
            "placement": {"forwardGameUnits": 200, "rightGameUnits": 0}, "persistence": "save-load-witness-required", "maximumCreations": 6}
        with patch.object(fixture_actors, "create", side_effect=create) as actual:
            self.execute(request)
            with self.assertRaisesRegex(ValueError, "never replay"): self.execute(request)
            self.assertEqual(actual.call_count, 1)

    def test_owned_save_load_routes_exact_six_tag_bundle_once(self):
        request = {"domain": "save-state", "action": "save-disposable-once", "saveLabel": "OwnedSave", "actors": [f"Fixture{i}" for i in range(6)],
            "scope": "current-temporary-profile", "maximumSaves": 1}
        with patch.object(subject.npc_persistence, "perform", return_value={"save": {"completed": True}}) as perform:
            self.execute(request)
            self.assertEqual(perform.call_args.args[1], {"action": "save", "saveTag": "OwnedSave", "fixtureTags": request["actors"]})
            with self.assertRaisesRegex(ValueError, "already attempted"): self.execute(request)
            self.execute({"domain": "save-state", "action": "load-owned-disposable-once", "saveLabel": "OwnedSave", "maximumLoads": 1, "processRestart": False}, command="load-1")
            self.assertEqual(perform.call_args.args[1], {"action": "load", "saveTag": "OwnedSave"})
            self.assertEqual(perform.call_count, 2)
        with patch.object(subject.npc_persistence, "observe", return_value={"save": {"completed": True}}) as read:
            self.execute({"domain": "save-state", "saveLabel": "OwnedSave"}, command="read-save")
            self.assertEqual(read.call_args.args[1], {"saveTag": "OwnedSave"})

    def test_peer_preservation_uses_actual_independent_peer_reads(self):
        self.execute(evaluation())
        peer_ref = "0xFF000124"
        peer = copy.deepcopy(self.session.state["interactiveActorFixtures"]["Fixture"])
        peer.update(tag="Peer", reference=peer_ref, createdReference=peer_ref, creationId="9" * 32)
        peer["incarnation"]["runtimeHandle"] += 1
        peer["creationWitness"].update(reference=peer_ref, creationId="9" * 32)
        self.session.state["interactiveActorFixtures"]["Peer"] = peer
        semantic = copy.deepcopy(self.session.state["morphSession"]["fixtures"]["Fixture"]); semantic["creationId"] = "9" * 32
        self.session.state["morphSession"]["fixtures"]["Peer"] = semantic
        self.execute(evaluation("peer", actor={"fixtureTag": "Peer"}))
        result = self.execute(evaluation("main", preserveOtherActors=[{"fixtureTag": "Peer", "snapshot": "peer"}]))
        self.assertEqual(result["preservation"]["changedOtherActorEntryCount"], 0)
        self.assertEqual(result["peerComparisons"][0]["actual"]["raw"]["reference"], peer_ref)
        self.assertIn("providerObservations", result["peerComparisons"][0]["actual"]["raw"])
        retained = self.session.state["morphSession"]["snapshots"]["main"]["result"]
        self.assertNotIn("peerComparisons", retained)
        self.assertNotIn("providerObservations", retained["raw"])
        self.assertEqual(retained["raw"]["sources"], result["raw"]["sources"])
        self.assertEqual(result["peerComparisons"][0]["baselineEvidence"]["basis"], "retained_prior_observation_not_a_fresh_read")
        logged = [entry[1]["rawResult"] for entry in self.session.logs if entry[0] == "morph-session-snapshot" and entry[1]["label"] == "main"][-1]
        self.assertIn("providerObservations", logged["peerComparisons"][0]["actual"]["raw"])
        result["peerComparisons"][0]["actual"]["raw"]["sources"][SOURCES[0]]["value"] = 999
        self.assertEqual(self.session.state["morphSession"]["snapshots"]["peer"]["result"]["raw"]["sources"][SOURCES[0]]["value"], .2)
        self.assertTrue(any(tool == "inspect" and args.get("refs") == [peer_ref] for tool, args in self.session.calls))

    def test_required_observation_span_polls_only_reads(self):
        result = self.execute(evaluation("spanned", minimumObservationSpanSeconds=.01))
        self.assertGreaterEqual(result["interval"]["observedSpanSeconds"], .01)
        self.assertGreaterEqual(len(result["interval"]["samples"]), 2)
        self.assertEqual(self.session.state["morphSession"]["mutations"], [])

    def test_retained_baseline_is_compact_without_losing_full_return_or_logged_proof(self):
        result = self.execute(evaluation("compact", minimumObservationSpanSeconds=.01), command="observed-command")
        cache = self.session.state["morphSession"]["snapshots"]["compact"]
        retained = cache["result"]
        logged = [entry[1] for entry in self.session.logs if entry[0] == "morph-session-snapshot"][-1]
        self.assertEqual(cache["commandId"], "observed-command")
        self.assertEqual(cache["snapshotLabel"], "compact")
        self.assertEqual(cache["basis"], "retained_prior_observation_not_a_fresh_read")
        digest = hashlib.sha256(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        self.assertEqual(cache["fullResultSha256"], digest)
        for proof in (result, logged["rawResult"]):
            self.assertIn("providerObservations", proof["raw"])
            self.assertIn("obodyObservation", proof["raw"])
            self.assertIn("interval", proof)
            self.assertGreaterEqual(len(proof["interval"]["samples"]), 2)
        self.assertNotIn("providerObservations", retained["raw"])
        self.assertNotIn("obodyObservation", retained["raw"])
        self.assertNotIn("interval", retained)
        self.assertNotIn("peerComparisons", retained)
        for field in ("sources", "own", "targetKeys", "identity", "weightRaw", "weightNormalized", "timestamp"):
            self.assertEqual(retained["raw"][field], result["raw"][field])
        self.assertEqual(retained["expected"], result["expected"])
        comparison = morph_analysis.compare(retained, result)
        self.assertEqual(comparison["comparison"]["changedSourceKeyEntryCount"], 0)
        self.assertEqual(comparison["comparison"]["changedOwnTargetEntryCount"], 0)
        self.assertLess(len(json.dumps(cache)), len(json.dumps(result)) / 2)
        result["raw"]["sources"][SOURCES[0]]["keys"][0]["value"] = 88
        self.assertEqual(retained["raw"]["sources"][SOURCES[0]]["keys"][0]["value"], 9)
        self.assertEqual(logged["rawResult"]["raw"]["sources"][SOURCES[0]]["keys"][0]["value"], 9)


if __name__ == "__main__": unittest.main()
