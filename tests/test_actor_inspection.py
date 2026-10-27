import copy
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import actor_domain, actor_inspection, fixture_actors, interactive_bindings


REF, BASE, RACE = "0xFF000001", "0x00013475", "0x00013746"
POLICY = {"schemaVersion": 1, "fixtureActorBases": [BASE], "allowedRaceForms": [RACE], "bindings": [
    {"id": "inspect_unequip", "script": "Actor", "function": "UnequipAll", "scope": "member", "params": [],
     "returnType": "None", "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [], "completion": "native-return"},
    {"id": "inspect_hold", "script": "Actor", "function": "SetDontMove", "scope": "member", "params": ["Bool"],
     "returnType": "None", "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [], "completion": "native-return"}]}


def request(action=None, phase="initial", name="Anton"):
    value = {"domain": "actor-fixture-inspection", "actor": {"fixtureTag": "MThin"}, "displayName": name,
             "nameScope": "reference-only", "phase": phase, "requireActualOwnedReferenceWitness": True}
    if action is None:
        value.update(wornArmorSlots=[30, 61], minimumPositionSamples=2, minimumObservationSpanMs=200,
                     positionToleranceGameUnits=1.0)
    else:
        value.update(action=action, preserveInventory=True, editBaseNPC=False, editBaseOutfit=False,
                     collisionPolicy="retain-enabled", noRetryOnUnknownOutcome=True)
    return value


class Clock:
    now = 100.0
    def __call__(self): return self.now


class Session:
    def __init__(self):
        game = {"pid": 17, "birth": 123, "path": "owned.exe"}
        actor = {"reference": REF, "base": BASE, "race": RACE, "sex": "male", "weight": 50, "loaded3D": True}
        incarnation = {"sessionId": "observer", "loadGeneration": 1, "runtimeHandle": 777}
        self.state = {"id": "inspection-run", "game": game, "testProfile": "owned", "ownedWorldGeneration": 1,
            "gameplayBootstrap": {"completed": True}, "configuration": {"interactive_session": {"nativeBindings": copy.deepcopy(POLICY)}},
            "activeSemanticCommandId": "command-1", "interactiveActorFixtures": {"MThin": {
                "tag": "MThin", "status": "created", "runId": "inspection-run", "game": copy.deepcopy(game), "worldGeneration": 1,
                "creationId": "1"*32, "createdReference": REF, "reference": REF, "base": BASE, "actor": actor,
                "incarnation": incarnation, "nativePersistentIdentity": {"currentVmHandle": "9001", "providerSession": "native"},
                "creationWitness": {"method": "ObjectReference.PlaceAtMe", "runId": "inspection-run", "creationId": "1"*32,
                    "reference": REF, "base": BASE, "anchor": "0x00000014", "count": 1, "nativeReturned": True,
                    "priorActorCount": 1, "priorActorsSha256": "a"*64, "forcePersist": True}}}}
        self.raw = {"protocol": "npc-persistence/1", "pid": 17, "providerSession": "native", "persistent": True,
            "currentReference": REF, "base": BASE, "currentVmHandle": "9001", "runtimeHandle": 777,
            "displayName": "Alvor", "position": [10., 20., 30.], "dontMove": False,
            "wornArmorSlots": [{"slot": slot, "form": None if slot != 32 else "0x00000012"} for slot in range(30, 62)],
            "equippedLeft": None, "equippedRight": "0x00000013", "equippedLeftIsWeapon": False,
            "equippedRightIsWeapon": True, "collision": {"available": False}}
        self.calls, self.binding_calls, self.durable, self.logs = [], [], [], []
        self.fail_name, self.fail_binding = False, False
        self.inspection_change = lambda raw: None
        self.positions = []

    def save(self): self.durable.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): self.logs.append((args, kwargs))
    def observe(self, backend, spec):
        entry = self.state["interactiveActorFixtures"]["MThin"]
        return {"actor": copy.deepcopy(entry["actor"]), "incarnation": copy.deepcopy(entry["incarnation"])}

    def _intent(self):
        command = list(self.durable[-1]["actorInspection"]["commands"].values())[-1]
        if command["status"] != "intent": raise AssertionError("Preparation lacks durable intent")
        return command

    def tool(self, tool, args, **kwargs):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool != "npc_persistence": raise AssertionError("Unexpected direct tool " + tool)
        if args["action"] == "prepare":
            command = self._intent()
            if args["kind"] != "name" or args["requestId"] != command["requestId"]:
                raise AssertionError("Preparation is not the exact unique name request")
            self.raw["displayName"] = args["displayName"]
            if self.fail_name: raise TimeoutError("lost name mutation ACK")
            return {"prepared": True, "requestId": args["requestId"], **copy.deepcopy(self.raw)}
        if args["action"] != "inspection": raise AssertionError("Unexpected native operation")
        raw = copy.deepcopy(self.raw)
        if self.positions: raw["position"] = self.positions.pop(0)
        self.inspection_change(raw)
        return raw

    def binding(self, session, args, deadline, policy):
        self._intent()
        self.binding_calls.append(copy.deepcopy(args))
        if args["bindingId"] == "inspect_unequip":
            for row in self.raw["wornArmorSlots"]: row["form"] = None
            self.raw["equippedLeft"] = self.raw["equippedRight"] = None
            self.raw["equippedLeftIsWeapon"] = self.raw["equippedRightIsWeapon"] = False
        elif args["bindingId"] == "inspect_hold":
            if args["args"] != [True]: raise AssertionError("Hold requires the explicit true flag")
            self.raw["dontMove"] = True
        else: raise AssertionError("Unexpected binding")
        if self.fail_binding: raise TimeoutError("lost Papyrus mutation ACK")
        return {"returned": None, "domainCompletion": "unverified"}


class ActorInspectionTests(unittest.TestCase):
    def setUp(self):
        self.s, self.clock = Session(), Clock()
        self.clock.now = 100.0
        def pause(backend, seconds):
            if seconds >= backend.remaining(): raise TimeoutError("deadline exhausted")
            self.clock.now += seconds
        patches = [patch.object(actor_inspection.time, "monotonic", side_effect=self.clock),
            patch.object(fixture_actors.native, "alive", return_value=True),
            patch.object(actor_inspection.Backend, "guard_world", return_value=None),
            patch.object(actor_inspection.Backend, "pause", pause),
            patch.object(actor_domain, "observe_actor", side_effect=self.s.observe),
            patch.object(interactive_bindings, "guarded_call", side_effect=self.s.binding)]
        for item in patches: item.start(); self.addCleanup(item.stop)

    def execute(self, req, command=None):
        if command is not None: self.s.state["activeSemanticCommandId"] = command
        return actor_inspection.execute(self.s, {"operation": "object.perform" if "action" in req else "world.read", "request": req},
                                        time.monotonic()+10, POLICY)

    def named(self): return self.execute(request("set-reference-display-name"), "name-command")

    def test_name_is_reference_only_once_and_raw_actual_name_binds_spoken_registry(self):
        result = self.named()
        self.assertEqual(result["actor"]["displayName"], "Anton")
        self.assertTrue(result["fixture"]["registryIdentityMatch"])
        self.assertEqual(result["fixture"]["spokenAliases"], ["Anton"])
        setters = [args for tool, args in self.s.calls if args["action"] == "prepare"]
        self.assertEqual(len(setters), 1)
        self.assertEqual(setters[0]["kind"], "name")
        self.assertEqual(setters[0]["reference"], REF)
        self.assertNotIn("baseOutfit", setters[0])
        with self.assertRaisesRegex(ValueError, "already attempted"): self.named()
        self.assertEqual(len([args for tool, args in self.s.calls if args["action"] == "prepare"]), 1)

    def test_unequip_and_hold_require_exact_typed_bindings_then_observe_actual_state(self):
        self.named()
        unequipped = self.execute(request("unequip-all-reference-gear"), "unequip-1")
        held = self.execute(request("hold-position-keep-collision"), "hold-1")
        self.assertEqual(unequipped["fixture"]["wornArmorItemCount"], 0)
        self.assertEqual(unequipped["fixture"]["equippedWeaponCount"], 0)
        self.assertTrue(held["fixture"]["dontMove"])
        self.assertEqual(self.s.binding_calls, [
            {"bindingId": "inspect_unequip", "self": {"reference": REF, "base": BASE}, "args": []},
            {"bindingId": "inspect_hold", "self": {"reference": REF, "base": BASE}, "args": [True]}])
        self.assertEqual(held["fixture"]["collisionDisableCommandCount"], 0)

    def test_two_actual_position_samples_cover_declared_interval_and_report_drift_without_assuming_stillness(self):
        self.named()
        self.s.positions = [[10., 20., 30.], [12., 20., 30.], [12., 20., 30.]]
        result = self.execute(request())
        self.assertGreaterEqual(result["fixture"]["positionSampleCount"], 2)
        self.assertGreaterEqual(result["fixture"]["positionObservationSpanMs"], 200)
        self.assertEqual(result["fixture"]["positionDriftGameUnits"], 2)
        self.assertEqual(result["samples"][0]["native"]["position"], [10., 20., 30.])
        self.assertFalse(result["samples"][0]["native"]["collision"]["available"])
        self.assertEqual(result["fixture"]["collisionDisableCommandCount"], 0)

    def test_missing_native_armor_or_weapon_fields_are_unavailable_never_zero(self):
        for change in (lambda raw: raw.update(wornArmorSlots=raw["wornArmorSlots"][:-1]),
                       lambda raw: raw.pop("equippedRight"), lambda raw: raw.update(position=[float("nan"), 0, 0]),
                       lambda raw: raw.update(dontMove=None)):
            self.s.inspection_change = change
            with self.subTest(change=change), self.assertRaises(ValueError): self.execute(request())

    def test_same_base_wrong_vm_or_runtime_or_reference_cannot_become_an_inspection(self):
        for change in (lambda raw: raw.update(currentVmHandle="9002"), lambda raw: raw.update(runtimeHandle=778),
                       lambda raw: raw.update(currentReference="0xFF000002"), lambda raw: raw.update(pid=18),
                       lambda raw: raw.update(persistent=False), lambda raw: raw.update(providerSession="foreign")):
            self.s.inspection_change = change
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, "reference/VM identity"):
                self.execute(request())

    def test_no_creation_witness_or_stale_owned_world_blocks_before_native_call(self):
        entry = self.s.state["interactiveActorFixtures"]["MThin"]
        entry["worldGeneration"] = 2
        with self.assertRaises(ValueError): self.named()
        self.assertEqual(self.s.calls, [])
        self.s.state["interactiveActorFixtures"] = {}
        with self.assertRaises(ValueError): self.named()
        self.assertEqual(self.s.calls, [])

    def test_lost_name_ack_preserves_intent_and_blocks_replay_or_further_mutation(self):
        self.s.fail_name = True
        with self.assertRaises(TimeoutError): self.named()
        ledger = self.s.state["actorInspection"]["commands"]
        self.assertEqual(next(iter(ledger.values()))["status"], "uncertain")
        self.assertNotIn("MThin", self.s.state["actorInspection"]["registry"])
        with self.assertRaises(ValueError): self.named()
        with self.assertRaisesRegex(ValueError, "uncertain"): self.execute(request("unequip-all-reference-gear"), "different-command")
        self.assertEqual(len([args for tool, args in self.s.calls if args["action"] == "prepare"]), 1)

    def test_lost_unequip_ack_is_not_replayed_and_actual_empty_state_is_not_repair_authority(self):
        self.named(); self.s.fail_binding = True
        with self.assertRaises(TimeoutError): self.execute(request("unequip-all-reference-gear"), "unequip-1")
        with self.assertRaises(ValueError): self.execute(request("unequip-all-reference-gear"), "unequip-1")
        with self.assertRaises(ValueError): self.execute(request("unequip-all-reference-gear"), "unequip-2")
        self.assertEqual(len(self.s.binding_calls), 1)

    def test_deliberate_later_returned_human_unequip_accepts_new_command_identity(self):
        self.named()
        self.execute(request("unequip-all-reference-gear", "returned-human"), "return-1")
        self.s.raw["wornArmorSlots"][2]["form"] = "0x00000012"
        self.execute(request("unequip-all-reference-gear", "returned-human"), "final-return-1")
        self.assertEqual(len(self.s.binding_calls), 2)
        ids = [value["requestId"] for value in self.s.state["actorInspection"]["commands"].values()]
        self.assertEqual(len(set(ids)), 3)

    def test_changed_actual_name_is_reported_as_registry_mismatch_without_silent_repair(self):
        self.named(); self.s.raw["displayName"] = "Other"
        result = self.execute(request(phase="returned-human"))
        self.assertEqual(result["actor"]["displayName"], "Other")
        self.assertFalse(result["fixture"]["registryIdentityMatch"])
        self.assertEqual(result["fixture"]["spokenAliases"], [])
        self.assertEqual(len([args for tool, args in self.s.calls if args["action"] == "prepare"]), 1)

    def test_equipped_non_weapon_form_is_retained_raw_and_not_counted_as_a_weapon(self):
        self.named()
        self.s.raw.update(equippedRight="0x00000013",equippedRightIsWeapon=False)
        result=self.execute(request())
        self.assertEqual(result["fixture"]["equippedWeaponCount"],0)
        self.assertEqual(result["samples"][0]["native"]["equippedRight"],"0x00000013")

    def test_postload_uses_real_remapped_vm_reference_and_preserves_original_name_registry_identity(self):
        self.named()
        entry = self.s.state["interactiveActorFixtures"]["MThin"]
        ref = "0xFF100001"
        entry["reference"] = entry["actor"]["reference"] = ref
        entry["worldGeneration"] = self.s.state["ownedWorldGeneration"] = 2
        entry["incarnation"].update(loadGeneration=2, runtimeHandle=888)
        native = {"currentReference": ref, "savedReference": REF, "currentVmHandle": "19001", "resolvedVmHandle": "19001",
                  "creationId": entry["creationId"], "formResolved": True, "handleResolved": True}
        witness = {"saveTag": "saved", "bindingId": "b"*32, "native": native, "worldGeneration": 2}
        entry["restorationWitness"] = copy.deepcopy(witness)
        self.s.state["npcPersistence"] = {"saved": {"status": "loaded", "bindingId": "b"*32,
            "runId": self.s.state["id"], "game": copy.deepcopy(self.s.state["game"]), "afterWorldGeneration": 2,
            "rebindings": {"MThin": {"actor": copy.deepcopy(entry["actor"]), "incarnation": copy.deepcopy(entry["incarnation"]),
                                      "restorationWitness": copy.deepcopy(witness)}}}}
        self.s.raw.update(currentReference=ref, currentVmHandle="19001", runtimeHandle=888)
        result = self.execute(request(phase="returned-human"))
        self.assertTrue(result["fixture"]["registryIdentityMatch"])
        self.assertEqual(result["actor"]["reference"], ref)
        self.s.raw["currentVmHandle"] = "9001"
        with self.assertRaises(ValueError): self.execute(request(phase="returned-human"))

    def test_mutation_requires_real_dispatch_identity_and_refuses_wrong_frozen_role_signature(self):
        self.s.state.pop("activeSemanticCommandId")
        with self.assertRaisesRegex(ValueError, "command identity"): self.execute(request("set-reference-display-name"))
        self.assertFalse(any(args["action"] == "prepare" for tool, args in self.s.calls))
        invalid = interactive_bindings.validate(POLICY)
        invalid["bindings"][0]["params"] = ["bool"]
        with self.assertRaisesRegex(ValueError, "exact native"):
            actor_inspection._role(invalid, "unequip")

    def test_exact_contract_rejects_collision_base_outfit_raw_actor_and_loose_measurements(self):
        variants = []
        for field, value in (("collisionPolicy", "disable"), ("editBaseNPC", True), ("editBaseOutfit", True),
                             ("preserveInventory", False), ("noRetryOnUnknownOutcome", False), ("nameScope", "base")):
            req = request("unequip-all-reference-gear"); req[field] = value; variants.append(("object.perform", req))
        for field, value in (("wornArmorSlots", [30]), ("minimumPositionSamples", 1), ("minimumObservationSpanMs", 0),
                             ("positionToleranceGameUnits", float("nan")), ("actor", {"reference": REF, "base": BASE})):
            req = request(); req[field] = value; variants.append(("world.read", req))
        for operation, req in variants:
            with self.subTest(req=req), self.assertRaises(ValueError): actor_inspection.validate(operation, req)


if __name__ == "__main__": unittest.main()
