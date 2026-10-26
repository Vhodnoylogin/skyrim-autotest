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
        self.on_mutation = lambda function: None
        self.bad_position, self.actor_sex = False, 1

    def log(self, *args, **kwargs): self.logs.append((args, kwargs))
    def save(self): self.saved.append(copy.deepcopy(self.state))

    def tool(self, tool, args, timeout, deadline):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "menu":
            return {"messageBoxOpen": False, "openMenus": [], "menuStates": []}
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
        with self.assertRaisesRegex(ValueError, "placement"):
            self.create()
        self.assertEqual(len(self.session.mutations), 4)
        self.assertEqual(self.session.state["interactiveActorFixtures"]["M1"]["status"], "uncertain")

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
