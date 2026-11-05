"""Owned visual-freeze protocol/identity tests; not engine qualification."""
import copy
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import actor_inspection, fixture_actors, visual_freeze as domain
from tests.test_actor_inspection import Clock, POLICY, REF, BASE, Session as InspectionSession


def request(mutate=False):
    return {"domain": domain.DOMAIN, "actor": {"fixtureTag": "MThin"},
            **({"action": domain.ACTION} if mutate else {})}


class Session(InspectionSession):
    def __init__(self):
        super().__init__()
        self.state["configuration"]["interactive_session"].update(npcPersistence=True, morphSession={"candidate": True})
        self.raw.update(parentCell="0x00032AE7", worldGeneration=1)
        self.flags = dict(aiEnabled=True, collisionsEnabled=True, referenceCollisionsEnabled=True)
        self.root, self.native_generation = 1, 1
        self.mutations, self.visual_reads = [], 0
        self.fail_ack, self.stuck_filter, self.unavailable = False, False, False
        self.change_visual = lambda value: None
        self.change_after_call = lambda: None

    def visual(self):
        entry = self.state["interactiveActorFixtures"]["MThin"]
        return {key: copy.deepcopy(self.raw[key]) for key in ("pid", "providerSession", "currentReference", "base",
            "currentVmHandle", "runtimeHandle", "persistent", "parentCell")} | {
            "protocol": domain.PROTOCOL, "worldGeneration": self.native_generation, "sampledRootToken": self.root,
            "raceForm": entry["actor"]["race"], "disabled": False, "loaded3D": True,
            "collisionStateObserved": not self.unavailable, "collisionStatus": "unavailable" if self.unavailable else "available",
            "collisionFilter": 0 if self.flags["collisionsEnabled"] else 16384,
            "visualFrozen": not any(self.flags.values()), **self.flags}

    def tool(self, tool, args, **kwargs):
        if tool != "npc_persistence" or args["action"] not in ("visual_state", "freeze_visual"):
            return super().tool(tool, args, **kwargs)
        self.calls.append((tool, copy.deepcopy(args)))
        if args["action"] == "visual_state":
            self.visual_reads += 1
            value = self.visual(); self.change_visual(value)
            return value
        command = list(self.durable[-1]["visualFreeze"]["commands"].values())[-1]
        if command["status"] != "intent" or command["requestId"] != args["requestId"]:
            raise AssertionError("Freeze call requires persisted unique intent")
        before = self.visual()
        if any(args[key] != before[key] for key in domain.GUARDS):
            raise ValueError("native identity guard refused")
        self.mutations.append(copy.deepcopy(args))
        self.flags.update(aiEnabled=False, referenceCollisionsEnabled=False)
        if not self.stuck_filter:
            self.flags["collisionsEnabled"] = False
        self.change_after_call()
        if self.fail_ack:
            raise TimeoutError("lost native ACK")
        return self.visual() | {"requestId": args["requestId"], "mutationIssued": True, "toggleUsed": False}


class VisualFreezeTests(unittest.TestCase):
    def setUp(self):
        self.s, self.clock = Session(), Clock()
        self.clock.now = 100
        def pause(backend, seconds):
            if seconds >= backend.remaining(): raise TimeoutError("deadline exhausted")
            self.clock.now += max(seconds, .5)
        for item in (patch.object(domain.time, "monotonic", side_effect=self.clock),
                     patch.object(fixture_actors.native, "alive", return_value=True),
                     patch.object(domain.Backend, "guard_world", return_value=None),
                     patch.object(domain.Backend, "pause", pause)):
            item.start(); self.addCleanup(item.stop)

    def execute(self, mutate=False, command=None, seconds=3):
        if command is not None: self.s.state["activeSemanticCommandId"] = command
        return domain.execute(self.s, {"operation": "object.perform" if mutate else "world.read", "request": request(mutate)},
                              time.monotonic()+seconds, POLICY)

    def test_read_reports_actual_flags_without_preparing_or_claiming_contact(self):
        result = self.execute()
        self.assertTrue(result["actor"]["aiEnabled"])
        self.assertFalse(result["fixture"]["visualFrozen"])
        self.assertFalse(result["physicalContactAbsenceAccepted"])
        self.assertFalse(result["fixture"]["dontMove"])
        self.assertEqual(result["inspection"]["native"]["currentVmHandle"], self.s.raw["currentVmHandle"])
        self.assertEqual(self.s.mutations, [])

    def test_matrix_freeze_requires_explicit_se_opt_in_and_keeps_legacy_morph_route(self):
        settings = self.s.state["configuration"]["interactive_session"]
        settings.pop("morphSession")
        settings["matrixLifecycle"] = {"freezeActors": True}
        with self.assertRaisesRegex(ValueError, "opt-ins"): self.execute(True)
        self.s.state["configuration"]["game_edition"] = "vr"
        with self.assertRaisesRegex(ValueError, "opt-ins"): self.execute(True)
        self.s.state["configuration"]["game_edition"] = "se"
        settings["matrixLifecycle"].pop("freezeActors")
        with self.assertRaisesRegex(ValueError, "opt-ins"): self.execute(True)
        settings["matrixLifecycle"]["freezeActors"] = True
        self.assertTrue(self.execute(True)["fixture"]["visualFrozen"])

    def test_require_frozen_reads_actual_hold_without_issuing_any_mutation(self):
        self.s.flags = dict.fromkeys(self.s.flags, False)
        with self.assertRaisesRegex(ValueError, "locomotion hold"):
            domain.require_frozen(self.s, "MThin", time.monotonic()+3, POLICY)
        self.assertEqual(self.s.mutations, [])
        self.assertNotIn("visualFreeze", self.s.state)
        self.s.raw["dontMove"] = True
        result = domain.require_frozen(self.s, "MThin", time.monotonic()+3, POLICY)
        self.assertTrue(result["fixture"]["visualFrozen"])
        self.assertTrue(result["fixture"]["dontMove"])
        self.assertTrue(result["inspection"]["native"]["dontMove"])
        self.assertEqual(self.s.mutations, [])
        self.assertNotIn("visualFreeze", self.s.state)

    def test_require_frozen_rejects_each_independently_enabled_flag_without_mutating(self):
        self.s.raw["dontMove"] = True
        for field in self.s.flags:
            with self.subTest(field=field):
                self.s.flags = dict.fromkeys(self.s.flags, False)
                self.s.flags[field] = True
                with self.assertRaisesRegex(ValueError, "AI/collision off"):
                    domain.require_frozen(self.s, "MThin", time.monotonic()+3, POLICY)
                self.assertEqual(self.s.mutations, [])

    def test_freeze_is_one_explicit_set_with_fresh_readback_and_durable_intent(self):
        result = self.execute(True)
        self.assertTrue(result["fixture"]["visualFrozen"])
        self.assertEqual(len(self.s.mutations), 1)
        self.assertGreaterEqual(self.s.visual_reads, 2)
        self.assertFalse(result["preparation"]["toggleUsed"])
        self.assertEqual(list(self.s.state["visualFreeze"]["commands"].values())[0]["status"], "completed")
        with self.assertRaisesRegex(ValueError, "never replay"): self.execute(True)
        self.assertEqual(len(self.s.mutations), 1)

    def test_new_command_is_idempotent_and_does_not_toggle_already_off_states(self):
        self.execute(True)
        result = self.execute(True, "new-command")
        self.assertTrue(result["preparation"]["freezeWasAlreadyObservedBeforeCall"])
        self.assertFalse(result["actor"]["aiEnabled"])
        self.assertFalse(result["actor"]["collisionsEnabled"])

    def test_one_held_command_can_freeze_distinct_creations_but_never_replay_either(self):
        first = self.execute(True)
        commands = self.s.state["visualFreeze"]
        self.s = Session()
        entry = self.s.state["interactiveActorFixtures"]["MThin"]
        entry["creationId"] = entry["creationWitness"]["creationId"] = "2"*32
        entry["reference"] = entry["createdReference"] = entry["actor"]["reference"] = "0xFF000002"
        entry["creationWitness"]["reference"] = "0xFF000002"
        entry["incarnation"]["runtimeHandle"] = 778
        entry["nativePersistentIdentity"]["currentVmHandle"] = "9002"
        self.s.raw.update(currentReference="0xFF000002", runtimeHandle=778, currentVmHandle="9002")
        self.s.state["visualFreeze"] = commands
        second = self.execute(True)
        rows = list(commands["commands"].values())
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["creationId"] for row in rows}, {"1"*32, "2"*32})
        self.assertEqual({row["reference"] for row in rows}, {REF, "0xFF000002"})
        self.assertEqual({row["commandId"] for row in rows}, {"command-1"})
        self.assertNotEqual(first["preparation"]["requestId"], second["preparation"]["requestId"])
        with self.assertRaisesRegex(ValueError, "never replay"): self.execute(True)
        self.assertEqual(len(self.s.mutations), 1)

    def test_ack_loss_blocks_new_commands_but_allows_independent_read(self):
        self.s.fail_ack = True
        with self.assertRaises(TimeoutError): self.execute(True)
        with self.assertRaisesRegex(ValueError, "uncertain"): self.execute(True, "new-command")
        self.assertTrue(self.execute()["fixture"]["visualFrozen"])
        self.assertEqual(len(self.s.mutations), 1)

    def test_reference_collision_flag_alone_is_not_controller_disable_acceptance(self):
        self.s.stuck_filter = True
        with self.assertRaises(TimeoutError): self.execute(True)
        self.assertFalse(self.s.flags["referenceCollisionsEnabled"])
        self.assertTrue(self.s.flags["collisionsEnabled"])
        self.assertFalse(self.execute()["fixture"]["visualFrozen"])
        with self.assertRaisesRegex(ValueError, "uncertain"): self.execute(True, "another-command")
        self.assertEqual(len(self.s.mutations), 1)

    def test_missing_controller_or_incoherent_flags_refuse_before_mutation(self):
        for change in (lambda v: v.update(collisionStateObserved=False), lambda v: v.update(collisionStatus="unavailable"),
                       lambda v: v.update(collisionFilter=None), lambda v: v.update(visualFrozen=True),
                       lambda v: v.update(aiEnabled=0), lambda v: v.update(collisionsEnabled=0),
                       lambda v: v.update(referenceCollisionsEnabled=0)):
            with self.subTest(change=change):
                self.s.change_visual = change
                with self.assertRaises(ValueError): self.execute(True)
                self.assertEqual(self.s.mutations, [])

    def test_wrong_native_identity_and_provider_world_refuse_before_mutation(self):
        for field, value in (("pid", 99), ("providerSession", "foreign"), ("currentReference", "0xFF000002"),
            ("base", "0x00000001"), ("currentVmHandle", "9002"), ("runtimeHandle", 778),
            ("parentCell", "0x00000001"), ("raceForm", "0x00000001"), ("sampledRootToken", 0),
            ("worldGeneration", 0), ("worldGeneration", 2), ("disabled", True), ("loaded3D", False)):
            with self.subTest(field=field):
                self.s.change_visual = lambda v, field=field, value=value: v.update({field:value})
                with self.assertRaises(ValueError): self.execute(True)
                self.assertEqual(self.s.mutations, [])

    def test_missing_native_inspection_generation_refuses_before_visual_call(self):
        self.s.raw.pop("worldGeneration")
        with self.assertRaisesRegex(ValueError, "world generation is unavailable"): self.execute(True)
        self.assertEqual(self.s.visual_reads, 0)
        self.assertEqual(self.s.mutations, [])

    def test_valid_replacement_creation_during_visual_read_cannot_pass_old_sample(self):
        def replace_creation(raw):
            entry = copy.deepcopy(self.s.state["interactiveActorFixtures"]["MThin"])
            entry["creationId"] = entry["creationWitness"]["creationId"] = "2"*32
            self.s.state["interactiveActorFixtures"]["MThin"] = entry
        self.s.change_visual = replace_creation
        with self.assertRaisesRegex(ValueError, "complete creation identity changed"): self.execute()
        self.assertEqual(self.s.mutations, [])

    def test_in_place_vm_identity_change_during_visual_read_cannot_pass_old_sample(self):
        def replace_vm(raw):
            self.s.state["interactiveActorFixtures"]["MThin"]["nativePersistentIdentity"]["currentVmHandle"] = "9002"
            self.s.raw["currentVmHandle"] = "9002"
        self.s.change_visual = replace_vm
        with self.assertRaisesRegex(ValueError, "complete creation identity changed"): self.execute()
        self.assertEqual(self.s.mutations, [])

    def test_game_or_owned_generation_change_after_visual_read_refuses(self):
        for field in ("game", "ownedWorldGeneration"):
            with self.subTest(field=field):
                self.s = Session()
                def change(raw):
                    entry = self.s.state["interactiveActorFixtures"]["MThin"]
                    if field == "game":
                        self.s.state["game"]["birth"] += 1
                        entry["game"] = copy.deepcopy(self.s.state["game"])
                    else:
                        self.s.state[field] += 1
                        entry["worldGeneration"] = self.s.state[field]
                self.s.change_visual = change
                with self.assertRaises(ValueError): self.execute()
                self.assertEqual(self.s.mutations, [])

    def test_race_or_root_change_during_call_is_uncertain_without_replay(self):
        self.s.change_after_call = lambda: setattr(self.s, "root", 2)
        with self.assertRaisesRegex(ValueError, "completion witness"): self.execute(True)
        with self.assertRaisesRegex(ValueError, "uncertain"): self.execute(True, "later")

    def test_new_race_requires_new_observation_and_explicit_command(self):
        self.execute(True)
        entry = self.s.state["interactiveActorFixtures"]["MThin"]
        entry["actor"]["race"] = "0x000CDD84"; self.root_changed()
        self.s.flags.update(aiEnabled=True, collisionsEnabled=True, referenceCollisionsEnabled=True)
        observed = self.execute()
        self.assertFalse(observed["fixture"]["visualFrozen"])
        result = self.execute(True, "after-race")
        self.assertTrue(result["fixture"]["visualFrozen"])
        self.assertEqual(self.s.mutations[-1]["raceForm"], entry["actor"]["race"])

    def root_changed(self): self.s.root += 1

    def test_postload_uses_actual_remapped_vm_reference_and_rejects_old_ff_handle(self):
        self.execute(True)
        entry = self.s.state["interactiveActorFixtures"]["MThin"]; ref = "0xFF100001"
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
        self.s.raw.update(currentReference=ref, currentVmHandle="19001", runtimeHandle=888, worldGeneration=2)
        self.s.native_generation = 2; self.root_changed()
        self.assertTrue(self.execute()["fixture"]["visualFrozen"])
        self.execute(True, "after-load")
        self.assertEqual(self.s.mutations[-1]["currentVmHandle"], "19001")
        self.s.raw["currentVmHandle"] = "9001"
        with self.assertRaises(ValueError): self.execute(True, "old-vm")

    def test_no_owned_witness_foreign_process_and_missing_opt_in_cannot_mutate(self):
        for change in (lambda: self.s.state["interactiveActorFixtures"]["MThin"].pop("creationWitness"),
                       lambda: self.s.state["game"].update(pid=99),
                       lambda: self.s.state["configuration"]["interactive_session"].update(npcPersistence=False)):
            self.s = Session(); change()
            with self.assertRaises(ValueError): self.execute(True)
            self.assertEqual(self.s.mutations, [])

    def test_exact_schema_rejects_player_global_console_true_and_raw_selectors(self):
        for extra in ({"reference":"0x00000014"}, {"script":"Actor"}, {"collisionsEnabled":True}, {"command":"tcl"}):
            with self.assertRaises(ValueError): domain.validate("object.perform", request(True) | extra)
        with self.assertRaises(ValueError): domain.validate("object.perform", request(True) | {"action":"toggle"})


if __name__ == "__main__": unittest.main()
