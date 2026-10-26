import copy
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import interactive_bindings as bindings


ACTOR = {"reference": "0xFF000123", "base": "0x01000801"}
RACE = "0x00013746"


def declaration(binding_id="assign-preset", **overrides):
    value = {"id": binding_id, "script": "GenericPresetNative", "function": "AssignPresetToActor", "scope": "global",
             "params": ["Actor", "String", "Bool", "Bool"], "returnType": "Bool", "effect": "mutate",
             "actorSelf": False, "actorArgs": [0], "raceArgs": [], "completion": "native-return"}
    value.update(overrides)
    return value


def policy(*entries):
    return {"schemaVersion": 1, "fixtureActorBases": [ACTOR["base"]], "allowedRaceForms": [RACE],
            "bindings": list(entries) or [declaration()]}


def race_declaration():
    return declaration("set-race", script="Actor", function="SetRace", scope="member", params=["Race"],
                       returnType="None", actorSelf=True, actorArgs=[], raceArgs=[0], completion="actor-race")


class Session:
    def __init__(self, configured):
        self.state = {"game": {"pid": 123, "path": "owned-game.exe", "birth": 456}, "testProfile": "Owned Disposable Profile",
                      "id": "binding-run", "ownedWorldGeneration": 1,
                      "gameplayBootstrap": {"completed": True},
                      "configuration": {"interactive_session": {"nativeBindings": copy.deepcopy(configured)}}}
        self.calls, self.logs, self.mutations = [], [], []
        self.base, self.race, self.handle, self.generation = ACTOR["base"], "0x00013740", 12, 1
        self.loaded, self.disabled, self.deleted = True, False, False
        self.return_value, self.return_type = True, "Bool"
        self.metadata_change = lambda value: value
        self.on_declared_call = lambda: None
        self.apply_race = True
        self.fail_after_mutation = False
        self.state["interactiveActorFixtures"] = {"npc": {"status": "created", "runId": "binding-run", "base": ACTOR["base"],
            "reference": ACTOR["reference"], "game": copy.deepcopy(self.state["game"]), "worldGeneration": 1, "creationId": "a" * 32,
            "incarnation": {"sessionId": "observer-session", "loadGeneration": 1, "runtimeHandle": 12}, "actor": {"sex": "female"},
            "creationWitness": {"method": "ObjectReference.PlaceAtMe", "runId": "binding-run", "creationId": "a" * 32,
                "reference": ACTOR["reference"], "base": ACTOR["base"], "anchor": "0x00000014", "count": 1,
                "nativeReturned": True, "priorActorCount": 0, "priorActorsSha256": "b" * 64}}}

    def log(self, kind, **data):
        self.logs.append((kind, data))

    def save(self):
        pass

    def tool(self, tool, args, timeout, deadline):
        self.calls.append((tool, copy.deepcopy(args), timeout, deadline))
        if tool == "inspect":
            ref = args["refs"][0]
            return {"ok": True, "sessionId": "observer-session", "loadGeneration": self.generation,
                    "refs": [{"status": "available", "deleted": self.deleted, "disabled": self.disabled, "loaded3D": self.loaded,
                              "identity": {"form": ref, "runtimeHandle": self.handle, "loadGeneration": self.generation}}]}
        if tool != "papyrus":
            raise AssertionError("Unexpected tool")
        if args["action"] == "describe":
            configured = self.state["configuration"]["interactive_session"]["nativeBindings"]
            result = {"name": args["script"], "globalFunctions": [], "memberFunctions": []}
            for entry in configured["bindings"]:
                if entry["script"] == args["script"]:
                    scope = "memberFunctions" if entry["scope"] == "member" else "globalFunctions"
                    result[scope].append({"name": entry["function"], "params": [{"name": f"arg{i}", "type": kind}
                                          for i, kind in enumerate(entry["params"])], "returnType": entry["returnType"], "native": True})
            return self.metadata_change(result)
        script, function = args["script"], args["function"]
        if function == "GetActorBase":
            return {"returned": {"formId": self.base}}
        if function == "GetSex":
            return {"returned": 1}
        if function == "GetWeight":
            return {"returned": 50.0}
        if function == "GetRace":
            return {"returned": {"formId": self.race}}
        if function in ("AssignPresetToActor", "SetRace"):
            self.mutations.append(copy.deepcopy(args))
            if function == "SetRace" and self.apply_race:
                self.race = args["args"][0]["form"]
            self.on_declared_call()
            if self.fail_after_mutation:
                raise TimeoutError("native action may have applied; callback was lost")
            return {"called": True, "returned": None if function == "SetRace" else self.return_value,
                    "returnedType": "None" if function == "SetRace" else self.return_type}
        self.on_declared_call()
        return {"called": True, "returned": self.return_value, "returnedType": self.return_type}


class InteractiveBindingTests(unittest.TestCase):
    def setUp(self):
        self.policy = policy()
        self.session = Session(self.policy)
        self.world_calls = []
        def guard(backend):
            self.world_calls.append(backend.end)
        self.guard_patch = patch.object(bindings.Backend, "guard_world", guard)
        self.native_patch = patch.object(bindings.native, "alive", return_value=True)
        self.guard_patch.start(); self.native_patch.start()
        self.addCleanup(self.guard_patch.stop); self.addCleanup(self.native_patch.stop)

    def invoke(self, request=None, selected=None, seconds=10):
        return bindings.guarded_call(self.session, request or {"bindingId": "assign-preset", "args": [ACTOR, "Human preset", True, False]},
                                     time.monotonic() + seconds, self.policy if selected is None else selected)

    def configure(self, new_policy):
        self.policy = new_policy
        self.session.state["configuration"]["interactive_session"]["nativeBindings"] = copy.deepcopy(new_policy)

    def test_default_is_disabled_and_policy_validation_does_no_io(self):
        self.assertIsNone(bindings.validate(None))
        self.session.state["configuration"]["interactive_session"].pop("nativeBindings")
        with self.assertRaisesRegex(bindings.BindingError, "disabled"):
            bindings.guarded_call(self.session, {"bindingId": "anything", "args": []}, time.monotonic() + 2, None)
        self.assertEqual(self.session.calls, [])
        normalized = bindings.validate(policy(race_declaration()))
        self.assertEqual(normalized["bindings"][0]["params"], ["race"])
        self.assertEqual(normalized["bindings"][0]["returnType"], "none")

    def test_declared_global_call_has_typed_args_one_invocation_and_no_completion_claim(self):
        result = self.invoke()
        self.assertIs(result["returned"], True)
        self.assertEqual(result["domainCompletion"], "unverified")
        self.assertEqual(len(self.session.mutations), 1)
        call = self.session.mutations[0]
        self.assertNotIn("self", call)
        self.assertEqual(call["args"], [{"form": ACTOR["reference"]}, "Human preset", True, False])
        self.assertNotIn("fillNeutral", call)
        self.assertTrue(self.world_calls)

    def test_actual_race_readback_uses_existing_domain_once(self):
        self.configure(policy(race_declaration()))
        result = self.invoke({"bindingId": "set-race", "args": [RACE], "self": ACTOR})
        self.assertEqual(result["domainCompletion"], "observed-race-readback")
        self.assertEqual(result["result"]["actor"]["race"], RACE)
        self.assertTrue(result["result"]["action"]["completed"])
        self.assertEqual(len(self.session.mutations), 1)
        self.assertEqual(self.session.mutations[0]["self"], {"form": ACTOR["reference"]})

    def test_existing_same_base_or_incomplete_foreign_witness_is_never_adopted(self):
        original = copy.deepcopy(self.session.state["interactiveActorFixtures"])
        changes = [lambda entry: entry.update(status="uncertain"), lambda entry: entry.update(runId="old-run"),
                   lambda entry: entry.pop("creationWitness"), lambda entry: entry["creationWitness"].update(reference="0xFF000999"),
                   lambda entry: entry.update(worldGeneration=2)]
        self.session.state["interactiveActorFixtures"] = {}
        with self.assertRaisesRegex(ValueError, "creation witness"):
            self.invoke()
        for change in changes:
            self.session.state["interactiveActorFixtures"] = copy.deepcopy(original)
            change(self.session.state["interactiveActorFixtures"]["npc"])
            with self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(self.session.mutations, [])

    def test_wrong_actor_base_player_race_and_extra_raw_selection_fail_before_mutation(self):
        bad = [dict(ACTOR, reference="0x00000014"), dict(ACTOR, base="0x02000801"), {"reference": ACTOR["reference"]},
               {"form": ACTOR["reference"]}]
        for actor in bad:
            with self.subTest(actor=actor), self.assertRaises(ValueError):
                self.invoke({"bindingId": "assign-preset", "args": [actor, "Preset", True, False]})
        for extra in ({"script": "Actor"}, {"function": "SetRace"}, {"policy": self.policy}):
            with self.assertRaises(ValueError):
                self.invoke(dict({"bindingId": "assign-preset", "args": [ACTOR, "Preset", True, False]}, **extra))
        self.configure(policy(race_declaration()))
        with self.assertRaisesRegex(ValueError, "Race is outside"):
            self.invoke({"bindingId": "set-race", "args": ["0x00013741"], "self": ACTOR})
        self.assertEqual(self.session.mutations, [])

    def test_observed_base_loaded_state_and_incarnation_guard_before_call(self):
        self.session.base = "0x01000802"
        with self.assertRaisesRegex(ValueError, "base differs"):
            self.invoke()
        self.session.base = ACTOR["base"]
        self.session.loaded = False
        with self.assertRaisesRegex(ValueError, "loaded 3D"):
            self.invoke()
        self.session.loaded = True
        actual = bindings.actor_domain.observe_actor
        count = [0]
        def change_actor(backend, spec):
            count[0] += 1
            if count[0] == 2:
                self.session.handle += 1
            return actual(backend, spec)
        with patch.object(bindings.actor_domain, "observe_actor", change_actor), self.assertRaisesRegex(ValueError, "incarnation"):
            self.invoke()
        self.assertEqual(self.session.mutations, [])

    def test_metadata_wrong_native_scope_script_return_or_param_refuses_before_mutation(self):
        def alter(field, value):
            def edit(description):
                description["globalFunctions"][0][field] = value
                return description
            return edit
        changes = [alter("native", False), alter("returnType", "Int"), alter("params", [{"type": "Actor"}]),
                   lambda d: dict(d, name="WrongScript"), lambda d: dict(d, globalFunctions=[], memberFunctions=d["globalFunctions"]),
                   lambda d: dict(d, globalFunctions=d["globalFunctions"] * 2)]
        for change in changes:
            self.session.metadata_change = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.invoke()
        self.assertEqual(self.session.mutations, [])

    def test_member_metadata_must_match_member_scope_before_race(self):
        self.configure(policy(race_declaration()))
        self.session.metadata_change = lambda d: dict(d, memberFunctions=[], globalFunctions=d["memberFunctions"])
        with self.assertRaises(ValueError):
            self.invoke({"bindingId": "set-race", "args": [RACE], "self": ACTOR})
        self.assertEqual(self.session.mutations, [])

    def test_explicit_bool_types_complete_args_and_target_scope(self):
        for args in ([ACTOR, "Preset", 1, False], [ACTOR, "Preset", True], [ACTOR, "Preset", True, False, False]):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.invoke({"bindingId": "assign-preset", "args": args})
        with self.assertRaises(ValueError):
            self.invoke({"bindingId": "assign-preset", "args": [ACTOR, "Preset", True, False], "self": ACTOR})
        self.assertEqual(self.session.mutations, [])

    def test_callback_loss_never_retries_or_claims_completed_mutation(self):
        self.session.fail_after_mutation = True
        with self.assertRaisesRegex(TimeoutError, "may have applied"):
            self.invoke()
        self.assertEqual(len(self.session.mutations), 1)
        self.assertFalse(any(kind.endswith("completed") for kind, _ in self.session.logs))

    def test_false_return_also_does_not_invent_domain_completion(self):
        self.session.return_value = False
        result = self.invoke()
        self.assertIs(result["returned"], False)
        self.assertEqual(result["domainCompletion"], "unverified")
        self.assertEqual(len(self.session.mutations), 1)

    def test_identity_and_world_failures_prevent_any_native_call(self):
        with patch.object(bindings.native, "alive", return_value=False), self.assertRaises(ValueError):
            self.invoke()
        with patch.object(bindings.Backend, "guard_world", side_effect=ValueError("world generation invalid")), self.assertRaisesRegex(ValueError, "generation"):
            self.invoke()
        self.assertEqual(self.session.calls, [])

    def test_result_after_absolute_deadline_is_not_a_completed_action(self):
        now = [10.0]
        self.session.on_declared_call = lambda: now.__setitem__(0, 20.0)
        with patch.object(bindings.time, "monotonic", side_effect=lambda: now[0]), self.assertRaises(TimeoutError):
            bindings.guarded_call(self.session, {"bindingId": "assign-preset", "args": [ACTOR, "Human", True, False]}, 11.0, self.policy)
        self.assertEqual(len(self.session.mutations), 1)

    def test_race_timeout_does_not_repeat_setter_or_use_ack_as_readback(self):
        self.configure(policy(race_declaration()))
        self.session.apply_race = False
        with self.assertRaises(TimeoutError):
            self.invoke({"bindingId": "set-race", "args": [RACE], "self": ACTOR}, seconds=.05)
        self.assertEqual(len(self.session.mutations), 1)
        self.assertNotEqual(self.session.race, RACE)

    def test_post_mutation_incarnation_change_preserves_unknown_outcome(self):
        self.session.on_declared_call = lambda: setattr(self.session, "generation", self.session.generation + 1)
        with self.assertRaisesRegex(ValueError, "incarnation"):
            self.invoke()
        self.assertEqual(len(self.session.mutations), 1)

    def test_typed_getters_catalog_and_skee_read_use_declared_native_signature(self):
        cases = [(declaration("catalog", function="GetAllPossiblePresets", params=["Actor"], returnType="String[]", effect="read"),
                  [ACTOR], ["A", "B"], "String[]"),
                 (declaration("assigned", function="GetPresetAssignedToActor", params=["Actor"], returnType="String", effect="read"),
                  [ACTOR], "Human preset", "String"),
                 (declaration("skee", script="NiOverride", function="GetBodyMorph", params=["ObjectReference", "String", "String"], returnType="Float", effect="read"),
                  [ACTOR, "Morph", "Key"], .25, "Float")]
        for entry, arguments, returned, returned_type in cases:
            self.configure(policy(entry))
            self.session.return_value, self.session.return_type = returned, returned_type
            result = self.invoke({"bindingId": entry["id"], "args": arguments})
            self.assertEqual(result["returned"], returned)
            self.assertEqual(result["domainCompletion"], "not-applicable")
        self.assertEqual(self.session.mutations, [])

    def test_actual_return_types_and_finite_values_are_checked(self):
        self.session.return_value = 1
        with self.assertRaisesRegex(ValueError, "real Bool"):
            self.invoke()
        self.assertEqual(len(self.session.mutations), 1)
        self.session.return_value, self.session.return_type = True, "Int"
        with self.assertRaisesRegex(ValueError, "typed return"):
            self.invoke()
        self.assertEqual(len(self.session.mutations), 2)

    def test_frozen_policy_mismatch_expired_deadline_and_owned_game_gate(self):
        changed = copy.deepcopy(self.policy)
        changed["fixtureActorBases"].append("0x02000801")
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.invoke(selected=changed)
        with self.assertRaises(ValueError):
            self.invoke(seconds=-1)
        self.session.state["testProfile"] = None
        with self.assertRaisesRegex(ValueError, "owned game"):
            self.invoke()
        self.assertEqual(self.session.calls, [])

    def test_policy_rejects_unanchored_mutator_untyped_actor_world_calls_and_race_ack_only(self):
        wrong = [declaration(actorArgs=[]), declaration(scope="member"), declaration(params=["Actor[]"]),
                 declaration(function="Delete", scope="member", actorSelf=True, params=[], actorArgs=[], returnType="None"),
                 dict(race_declaration(), completion="native-return"), declaration(effect="guess")]
        for entry in wrong:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                bindings.validate(policy(entry))
        for bases in (["0x00000007"], [ACTOR["base"], ACTOR["base"]]):
            selected = policy()
            selected["fixtureActorBases"] = bases
            with self.assertRaises(ValueError):
                bindings.validate(selected)


if __name__ == "__main__":
    unittest.main()
