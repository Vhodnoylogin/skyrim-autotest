import copy
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import fixture_actors, interactive_bindings


BASE, REF, RACE = "0x00013475", "0xFF000123", "0x00013746"
POLICY = {"schemaVersion": 1, "fixtureActorBases": [BASE], "allowedRaceForms": [RACE, "0x000CDD84"], "bindings": [{
    "id": "npc_race", "script": "Actor", "function": "SetRace", "scope": "member", "params": ["Race"],
    "returnType": "None", "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [0], "completion": "actor-race"}]}
REQUEST = {"tag": "M1", "base": BASE, "forwardGameUnits": 200, "rightGameUnits": 50}
CONTRACT = {
    "ObjectReference": {"PlaceAtMe": (["Form", "Int", "Bool", "Bool"], "ObjectReference"),
        "MoveTo": (["ObjectReference", "Float", "Float", "Float", "Bool"], "None"),
        "SetAngle": (["Float"] * 3, "None"), "GetPositionX": ([], "Float"), "GetPositionY": ([], "Float"),
        "GetPositionZ": ([], "Float"), "GetAngleZ": ([], "Float")},
    "Actor": {"GetActorBase": ([], "ActorBase"), "GetRace": ([], "Race"), "SetRace": (["Race"], "None"),
              "SetDontMove": (["Bool"], "None")},
    "ActorBase": {"GetSex": ([], "Int"), "GetRace": ([], "Race"), "GetWeight": ([], "Float")}}


class FixtureSession:
    def __init__(self):
        self.state = {"id": "fixture-run", "game": {"pid": 123, "birth": 456, "path": "owned.exe"}, "ownedWorldGeneration": 1,
                      "testProfile": "Owned Copy", "gameplayBootstrap": {"completed": True},
                      "configuration": {"interactive_session": {"nativeBindings": copy.deepcopy(POLICY)}}}
        self.calls, self.mutations, self.saved, self.logs = [], [], [], []
        self.new_ref, self.actual_base, self.race = REF, BASE, RACE
        self.generation, self.handle = 1, 777
        self.loaded, self.foreign_actor_world = True, False
        self.prior, self.truncated = ["0x00000014"], False
        self.position = {"0x00000014": [100.0, 200.0, 5.0], REF: [100.0, 200.0, 5.0]}
        self.angles = {"0x00000014": 90.0, REF: 0.0}
        self.fail_after, self.world_invalid, self.metadata_invalid = None, False, False
        self.dont_move_metadata_invalid = False
        self.metadata_overrides = {}
        self.on_mutation = lambda function: None
        self.bad_position, self.actor_sex = False, 1
        self.native_identity_hook = lambda raw: None
        self.identity_reads = 0

    def log(self, *args, **kwargs): self.logs.append((args, kwargs))
    def save(self): self.saved.append(copy.deepcopy(self.state))

    def tool(self, tool, args, timeout, deadline):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "menu":
            return {"messageBoxOpen": False, "openMenus": [], "menuStates": []}
        if tool == "npc_persistence":
            if args["action"] != "identity": raise AssertionError("Unexpected native persistence action")
            self.identity_reads += 1
            raw = {"protocol": "npc-persistence/1", "pid": self.state["game"]["pid"], "providerSession": "native-session",
                   "persistent": True, "currentReference": args["reference"], "base": args["base"],
                   "currentVmHandle": "9001", "runtimeHandle": self.handle}
            self.native_identity_hook(raw)
            return raw
        if tool == "inspect":
            if args["kind"] == "scene":
                return {"playerLoaded": True, "cell": {"editorId": "QASmoke"}}
            if args["kind"] == "refs":
                if "formId" in args:
                    return {"refs": [{"formId": args["formId"], "formType": "NPC_"}]}
                return {"count": len(self.prior), "returned": len(self.prior), "truncated": self.truncated,
                        "refs": [{"formId": ref} for ref in self.prior]}
            ref = args["refs"][0]
            player = ref == "0x00000014"
            return {"ok": True, "sessionId": "foreign" if self.foreign_actor_world and not player else "observer-session",
                    "loadGeneration": self.generation, "refs": [{"status": "available", "deleted": False, "disabled": False,
                    "loaded3D": self.loaded if not player else True, "baseForm": "0x00000007" if player else self.actual_base,
                    "identity": {"form": ref, "runtimeHandle": 111 if player else self.handle, "loadGeneration": self.generation}}]}
        if args["action"] == "describe":
            methods = CONTRACT[args["script"]]
            rows = [{"name": name, "params": [{"type": kind} for kind in signature[0]], "returnType": signature[1], "native": True}
                    for name, signature in methods.items()]
            if self.metadata_invalid:
                rows[0]["native"] = False
            if self.dont_move_metadata_invalid and args["script"] == "Actor":
                next(row for row in rows if row["name"] == "SetDontMove")["params"] = [{"type": "Float"}]
            for row in rows:
                row.update(self.metadata_overrides.get((args["script"], row["name"]), {}))
            return {"name": args["script"], "memberFunctions": rows, "globalFunctions": []}
        function, target = args["function"], args.get("self", {}).get("form")
        if function == "GetActorBase":
            return {"returned": {"formId": "0x00000007" if target == "0x00000014" else self.actual_base}}
        if function == "GetSex": return {"returned": self.actor_sex}
        if function == "GetWeight": return {"returned": 50.0}
        if function == "GetRace": return {"returned": {"formId": RACE if args["script"] == "ActorBase" else self.race}}
        if function.startswith("GetPosition"):
            return {"returned": self.position[target]["XYZ".index(function[-1])]}
        if function == "GetAngleZ": return {"returned": self.angles[target]}
        self.mutations.append(copy.deepcopy(args))
        if function == "PlaceAtMe":
            intent = self.saved[-1]["interactiveActorFixtures"][REQUEST["tag"]]
            if intent["status"] != "intent" or intent["steps"].get("PlaceAtMe") != "intent":
                raise AssertionError("Spawn happened without durable intent")
            self.position.setdefault(self.new_ref, [100.0, 200.0, 5.0]); self.angles.setdefault(self.new_ref, 0.0)
            returned, returned_type = {"formId": self.new_ref}, "ObjectReference"
        elif function == "MoveTo":
            player = self.position["0x00000014"]
            self.position[target] = [player[i] + args["args"][i + 1] for i in range(3)]
            if self.bad_position: self.position[target][0] += 100
            returned, returned_type = None, "None"
        elif function == "SetAngle":
            self.angles[target] = args["args"][2]
            returned, returned_type = None, "None"
        elif function == "SetRace":
            self.race = args["args"][0]["form"]
            returned, returned_type = None, "None"
        elif function == "SetDontMove":
            if args["args"] != [True] or args["script"] != "Actor":
                raise AssertionError("Only the exact owned locomotion blocker is permitted")
            intent = self.saved[-1]["interactiveActorFixtures"][REQUEST["tag"]]
            if intent["steps"].get("SetDontMove") != "intent" or intent.get("reference") != target or "incarnation" not in intent:
                raise AssertionError("Locomotion setter happened without a durable witnessed intent")
            returned, returned_type = None, "None"
        else:
            raise AssertionError("Unexpected mutation " + function)
        self.on_mutation(function)
        if self.fail_after == function:
            raise TimeoutError("lost native callback after " + function)
        return {"called": True, "returned": returned, "returnedType": returned_type}


class FixtureActorTests(unittest.TestCase):
    def setUp(self):
        self.session = FixtureSession()
        def world(backend):
            if backend.s.world_invalid: raise ValueError("world generation changed")
        self.world_patch = patch.object(fixture_actors.Backend, "guard_world", world)
        self.native_patch = patch.object(fixture_actors.native, "alive", return_value=True)
        self.world_patch.start(); self.native_patch.start()
        self.addCleanup(self.world_patch.stop); self.addCleanup(self.native_patch.stop)

    def create(self, request=None, seconds=10):
        return fixture_actors.create(self.session, REQUEST if request is None else request, time.monotonic() + seconds, POLICY)

    def test_creation_has_durable_intent_exact_once_placement_and_registry_witness(self):
        result = self.create()
        self.assertEqual([call["function"] for call in self.session.mutations], ["PlaceAtMe", "SetDontMove", "MoveTo", "SetAngle"])
        self.assertEqual(self.session.mutations[0]["args"], [{"form": BASE}, 1, False, False])
        self.assertEqual(result["placement"]["position"], [300.0, 150.0, 5.0])
        self.assertEqual(result["actor"]["reference"], REF)
        entry = fixture_actors.require_fixture(self.session, {"reference": REF, "base": BASE})
        self.assertEqual(entry["status"], "created")
        self.assertTrue(entry["creationWitness"]["nativeReturned"])
        self.assertEqual(entry["steps"]["SetDontMove"], "returned")
        self.assertFalse(any(call["function"] in ("EnableAI", "SetCollision", "RemoveAllItems", "UnequipAll") for call in self.session.mutations))
        self.assertNotIn("photography", self.session.state)

    def test_actual_creation_then_guarded_race_uses_same_witness(self):
        self.create()
        result = interactive_bindings.guarded_call(self.session, {"bindingId": "npc_race", "self": {"reference": REF, "base": BASE},
                                                   "args": ["0x000CDD84"]}, time.monotonic() + 10, POLICY)
        self.assertEqual(result["result"]["actor"]["race"], "0x000CDD84")
        self.assertEqual([call["function"] for call in self.session.mutations].count("SetRace"), 1)

    def test_explicit_persistent_creation_requires_frozen_optin_and_records_exact_native_argument(self):
        request = dict(REQUEST, persistentForOwnedSave=True)
        with self.assertRaisesRegex(ValueError, "opt-in"):
            self.create(request)
        self.assertEqual(self.session.mutations, [])
        self.session.state["configuration"]["interactive_session"]["npcPersistence"] = True
        result = self.create(request)
        self.assertEqual(self.session.mutations[0]["args"], [{"form": BASE}, 1, True, False])
        entry = fixture_actors.require_fixture(self.session, {"reference": REF, "base": BASE})
        self.assertTrue(entry["creationWitness"]["forcePersist"])
        self.assertEqual(entry["createdReference"], result["actor"]["reference"])
        self.assertTrue(result["actor"]["persistentSaveWitnessAvailable"])
        self.assertEqual(entry["nativePersistentIdentity"]["currentVmHandle"], "9001")
        self.assertEqual(self.session.identity_reads, 2)

    def test_persistent_flag_rejects_coerced_boolean_before_creation(self):
        for value in (1, "true", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.create(dict(REQUEST, persistentForOwnedSave=value))
        self.assertEqual(self.session.mutations, [])

    def test_requested_force_persist_with_false_actual_native_flag_never_becomes_created(self):
        self.session.state["configuration"]["interactive_session"]["npcPersistence"] = True
        self.session.native_identity_hook = lambda raw: raw.update(persistent=False)
        with self.assertRaisesRegex(ValueError, "persistent native"):
            self.create(dict(REQUEST, persistentForOwnedSave=True))
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")
        self.assertEqual([entry["function"] for entry in self.session.mutations], ["PlaceAtMe"])
        with self.assertRaises(ValueError): self.create(dict(REQUEST, persistentForOwnedSave=True))

    def test_changed_native_vm_across_creation_placement_is_uncertain_and_not_replayed(self):
        self.session.state["configuration"]["interactive_session"]["npcPersistence"] = True
        def changed(raw):
            if self.session.identity_reads > 1: raw["currentVmHandle"] = "9002"
        self.session.native_identity_hook = changed
        with self.assertRaisesRegex(ValueError, "identity changed"):
            self.create(dict(REQUEST, persistentForOwnedSave=True))
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_old_completed_or_uncertain_tag_is_never_replayed(self):
        self.create()
        for status in ("created", "uncertain", "intent"):
            self.session.state["interactiveActorFixtures"]["M1"]["status"] = status
            with self.assertRaisesRegex(ValueError, "already attempted"):
                self.create()
        self.assertEqual(len(self.session.mutations), 4)

    def test_lost_spawn_callback_leaves_uncertainty_without_search_adoption_or_replay(self):
        self.session.fail_after = "PlaceAtMe"
        with self.assertRaises(TimeoutError): self.create()
        self.assertEqual(len(self.session.mutations), 1)
        entry = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(entry["status"], "uncertain")
        self.assertNotIn("reference", entry)
        with self.assertRaises(ValueError): self.create()
        self.assertEqual(len(self.session.mutations), 1)

    def test_lost_placement_callback_does_not_repeat_creation_move_or_set_angle(self):
        self.session.fail_after = "MoveTo"
        with self.assertRaises(TimeoutError): self.create()
        self.assertEqual([call["function"] for call in self.session.mutations], ["PlaceAtMe", "SetDontMove", "MoveTo"])
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_lost_locomotion_setter_callback_stops_before_placement_without_replay(self):
        self.session.fail_after = "SetDontMove"
        with self.assertRaises(TimeoutError): self.create()
        self.assertEqual([call["function"] for call in self.session.mutations], ["PlaceAtMe", "SetDontMove"])
        entry = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(entry["status"], "uncertain")
        self.assertEqual(entry["steps"]["SetDontMove"], "intent")
        with self.assertRaises(ValueError): self.create()
        self.assertEqual(len(self.session.mutations), 2)
        self.assertFalse(any(call["function"] in ("EnableAI", "SetCollision") for call in self.session.mutations))

    def test_locomotion_setter_requires_actual_bool_metadata_before_creation(self):
        self.session.dont_move_metadata_invalid = True
        with self.assertRaises((ValueError, AssertionError)):
            self.create()
        self.assertEqual(self.session.mutations, [])

    def test_actual_stock_actor_base_read_wrapper_is_qualified_without_relaxing_mutators(self):
        # Retained RC4 SE metadata: native:false, no parameters, ActorBase return.
        self.session.metadata_overrides[("Actor", "GetActorBase")] = {
            "native": False, "params": [], "returnType": "ActorBase"}
        result = self.create()
        self.assertEqual(result["fixture"]["status"], "created")
        self.assertEqual(result["actor"]["base"], BASE)
        self.assertEqual([call["function"] for call in self.session.mutations], ["PlaceAtMe", "SetDontMove", "MoveTo", "SetAngle"])

    def test_non_native_spawn_and_locomotion_setters_remain_rejected_with_exact_error(self):
        for script, function in (("ObjectReference", "PlaceAtMe"), ("Actor", "SetDontMove")):
            self.session = FixtureSession()
            self.session.metadata_overrides[("Actor", "GetActorBase")] = {"native": False}
            self.session.metadata_overrides[(script, function)] = {"native": False}
            with self.subTest(function=function), self.assertRaises(ValueError) as caught:
                self.create()
            self.assertIn(script + "." + function, str(caught.exception))
            self.assertIn("'native': False", str(caught.exception))
            self.assertIn("expected=", str(caught.exception))
            self.assertIn("'native': True", str(caught.exception))
            self.assertEqual(self.session.mutations, [])

    def test_actor_base_wrapper_exception_requires_exact_signature_and_boolean_flag(self):
        for invalid in ({"params": [{"type": "Form"}]}, {"returnType": "Form"}, {"native": None}):
            self.session = FixtureSession()
            self.session.metadata_overrides[("Actor", "GetActorBase")] = {"native": False, **invalid}
            with self.subTest(invalid=invalid), self.assertRaises(ValueError) as caught:
                self.create()
            self.assertIn("Actor.GetActorBase", str(caught.exception))
            self.assertIn("actual=", str(caught.exception))
            self.assertIn("expected=", str(caught.exception))
            self.assertEqual(self.session.mutations, [])

    def test_player_static_prior_foreign_and_duplicate_references_are_refused(self):
        for ref, prior in (("0x00000014", []), ("0x00012345", []), (REF, [REF])):
            self.session = FixtureSession(); self.session.new_ref = ref; self.session.prior += prior
            with self.subTest(ref=ref), self.assertRaises(ValueError): self.create()
            self.assertEqual(len(self.session.mutations), 1)
            self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_wrong_actual_base_or_foreign_observer_world_is_not_a_fixture(self):
        for field, value in (("actual_base", "0x0001347D"), ("foreign_actor_world", True)):
            self.session = FixtureSession(); setattr(self.session, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError): self.create()
            self.assertEqual(len(self.session.mutations), 1)
            self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_world_change_after_spawn_stops_before_placement(self):
        self.session.on_mutation = lambda function: setattr(self.session, "world_invalid", function == "PlaceAtMe")
        with self.assertRaisesRegex(ValueError, "world generation"):
            self.create()
        self.assertEqual(len(self.session.mutations), 1)
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_unloaded_actor_deadline_stops_without_repeating_spawn(self):
        self.session.loaded = False
        with self.assertRaises(TimeoutError): self.create(seconds=.05)
        self.assertEqual(len(self.session.mutations), 1)
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

    def test_wrong_actual_placement_never_becomes_created(self):
        self.session.bad_position = True
        with self.assertRaisesRegex(ValueError, "placement") as caught:
            self.create()
        self.assertEqual(len(self.session.mutations), 4)
        record = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(record["status"], "uncertain")
        self.assertEqual(record["placementReadback"]["samples"][0]["positionErrorGameUnits"], 100)
        self.assertIn("requestedPosition", str(caught.exception))
        self.assertIn("positionErrorGameUnits", str(caught.exception))

    def test_ongoing_xy_drift_is_not_accepted_by_a_single_in_tolerance_sample(self):
        original = self.session.tool
        def tool(name, args, timeout, deadline):
            entry = self.session.state.get("interactiveActorFixtures", {}).get("M1", {})
            if (name == "papyrus" and args.get("function") == "GetPositionX"
                    and args.get("self") == {"form": REF} and entry.get("steps", {}).get("SetAngle") == "returned"):
                self.session.position[REF][0] += 1.5
            return original(name, args, timeout, deadline)
        self.session.tool = tool
        with self.assertRaisesRegex(ValueError, "placement"): self.create()
        record = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(record["status"], "uncertain")
        self.assertEqual([x["positionErrorGameUnits"] for x in record["placementReadback"]["samples"]], [1.5, 3, 4.5])
        self.assertEqual(len(self.session.mutations), 4)
        with self.assertRaisesRegex(ValueError, "already attempted"): self.create()
        self.assertEqual(len(self.session.mutations), 4)

    def test_small_floor_settle_requires_two_stable_reads_with_original_tolerance(self):
        def settle(function):
            if function == "SetAngle": self.session.position[REF][2] -= .35
        self.session.on_mutation = settle
        result = self.create()
        record = self.session.state["interactiveActorFixtures"]["M1"]
        readback = record["placementReadback"]
        self.assertGreaterEqual(len(readback["samples"]), 2)
        self.assertGreaterEqual(readback["stableSampleSpanSeconds"], .2)
        self.assertEqual(readback["positionToleranceGameUnits"], 4)
        self.assertEqual(readback["headingToleranceDegrees"], 1)
        self.assertAlmostEqual(result["placement"]["position"][2], 4.65)
        self.assertEqual(readback["requestedPosition"][2], 5)
        self.assertEqual(len(self.session.mutations), 4)

    def test_retained_mheavy_33_unit_xy_displacement_is_not_floor_settling(self):
        # q04:20261027-124523-b1e00f, completed MoveTo and SetAngle callbacks.
        self.session.position["0x00000014"] = [-363.2663879394531, 2035.23779296875, 6976.35009765625]
        self.session.angles["0x00000014"] = 260.2141418457031
        actual = [-568.7416381835938, 2244.05224609375, 6976.0009765625]
        def displaced(function):
            if function == "SetAngle": self.session.position[REF] = list(actual)
        self.session.on_mutation = displaced
        with self.assertRaisesRegex(ValueError, "placement"):
            self.create(dict(REQUEST, forwardGameUnits=200, rightGameUnits=240))
        record = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(record["status"], "uncertain")
        self.assertEqual(record["steps"]["MoveTo"], "returned")
        self.assertEqual(record["steps"]["SetAngle"], "returned")
        sample = record["placementReadback"]["samples"][0]
        self.assertEqual(sample["position"], actual)
        self.assertGreater(sample["positionErrorGameUnits"], 33)
        self.assertLess(sample["positionErrorGameUnits"], 34)
        self.assertEqual(sample["headingErrorDegrees"], 0)
        self.assertEqual(len(self.session.mutations), 4)
        with self.assertRaisesRegex(ValueError, "already attempted"): self.create()
        self.assertEqual(len(self.session.mutations), 4)

    def test_lost_orientation_ack_never_retries_or_starts_stability_reads(self):
        self.session.fail_after = "SetAngle"
        with self.assertRaises(TimeoutError): self.create()
        record = self.session.state["interactiveActorFixtures"]["M1"]
        self.assertEqual(record["status"], "uncertain")
        self.assertEqual(record["steps"]["SetAngle"], "intent")
        self.assertNotIn("placementReadback", record)
        self.assertEqual(len(self.session.mutations), 4)
        with self.assertRaisesRegex(ValueError, "already attempted"): self.create()
        self.assertEqual(len(self.session.mutations), 4)

    def test_metadata_and_truncated_census_fail_before_any_mutation(self):
        for field in ("metadata_invalid", "truncated"):
            self.session = FixtureSession(); setattr(self.session, field, True)
            with self.subTest(field=field), self.assertRaises(ValueError): self.create()
            self.assertEqual(self.session.mutations, [])

    def test_strict_request_default_scope_and_sixteen_limit(self):
        invalid = [dict(REQUEST, base="0x00000007"), dict(REQUEST, base="0x0001347D"), dict(REQUEST, rightGameUnits=True),
                   dict(REQUEST, forwardGameUnits=1001), dict(REQUEST, tag="../unsafe"), dict(REQUEST, forwardGameUnits=0, rightGameUnits=0),
                   dict(REQUEST, count=2)]
        for request in invalid:
            with self.subTest(request=request), self.assertRaises(ValueError):
                fixture_actors.validate_request(request, POLICY)
        with self.assertRaises(ValueError): fixture_actors.validate_request(REQUEST, None)
        self.session.state["interactiveActorFixtures"] = {f"old-{i}": {"status": "uncertain"} for i in range(16)}
        with self.assertRaisesRegex(ValueError, "sixteen"):
            self.create()
        self.assertEqual(self.session.mutations, [])

    def test_witness_guard_rejects_existing_same_base_old_run_and_changed_incarnation(self):
        with self.assertRaisesRegex(ValueError, "witness"):
            fixture_actors.guard(self.session, {"reference": REF, "base": BASE}, time.monotonic() + 5, POLICY)
        self.create()
        entry = self.session.state["interactiveActorFixtures"]["M1"]
        entry["runId"] = "old"
        with self.assertRaises(ValueError): fixture_actors.require_fixture(self.session, {"reference": REF, "base": BASE})
        entry["runId"] = "fixture-run"
        self.session.handle += 1
        with self.assertRaisesRegex(ValueError, "incarnation"):
            fixture_actors.guard(self.session, {"reference": REF, "base": BASE}, time.monotonic() + 5, POLICY)


if __name__ == "__main__":
    unittest.main()
