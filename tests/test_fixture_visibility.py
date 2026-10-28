import copy
import time
import unittest
from unittest.mock import patch

from skyrim_autotest import fixture_visibility as visibility


REF, BASE, CELL = "0xFF000001", "0x00013475", "0x00032AE7"
POLICY = {"schemaVersion": 1, "fixtureActorBases": [BASE], "allowedRaceForms": [], "bindings": [
    {"id": "hold", "script": "Actor", "function": "SetDontMove", "scope": "member", "params": ["Bool"],
     "returnType": "None", "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [], "completion": "native-return"}]}


def request(action="read"):
    return {"domain": visibility.DOMAIN, "action": action, "actor": {"fixtureTag": "Anton"}}


class Session:
    def __init__(self):
        game = {"pid": 17, "birth": 123, "path": "owned.exe"}
        identity = {"protocol": "npc-persistence/1", "pid": 17, "providerSession": "native", "persistent": True,
                    "currentReference": REF, "base": BASE, "currentVmHandle": "9001", "runtimeHandle": 777}
        self.incarnation = {"sessionId": "observer", "loadGeneration": 1, "runtimeHandle": 777}
        self.state = {"id": "visibility-run", "game": game, "testProfile": "owned", "ownedWorldGeneration": 1,
            "gameplayBootstrap": {"completed": True}, "configuration": {"interactive_session": {
                "nativeBindings": copy.deepcopy(POLICY), "npcPersistence": True}},
            "activeSemanticCommandId": "command-1", "interactiveActorFixtures": {"Anton": {
                "tag": "Anton", "status": "created", "runId": "visibility-run", "game": copy.deepcopy(game),
                "worldGeneration": 1, "creationId": "1"*32, "createdReference": REF, "reference": REF,
                "base": BASE, "incarnation": copy.deepcopy(self.incarnation), "actor": {"sex": "male"},
                "nativePersistentIdentity": identity, "creationWitness": {
                    "method": "ObjectReference.PlaceAtMe", "runId": "visibility-run", "creationId": "1"*32,
                    "reference": REF, "base": BASE, "anchor": "0x00000014", "count": 1, "nativeReturned": True,
                    "priorActorCount": 1, "priorActorsSha256": "a"*64, "forcePersist": True}}}}
        self.raw = dict(identity, protocol=visibility.PROTOCOL, parentCell=CELL, worldGeneration=2, disabled=False, loaded3D=True)
        self.calls, self.saved = [], []
        self.fail_mutation = False
        self.hook = lambda action, raw: None
        self.load_on_pause = False
        self.pauses = 0
        self.player_cell = CELL
        self.player_inc = {"sessionId": "observer", "loadGeneration": 1, "runtimeHandle": 111}

    def save(self): self.saved.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): pass
    def player(self, backend, ref):
        if ref != "0x00000014": raise AssertionError("Disabled fixture must not use loaded actor anchor")
        return copy.deepcopy(self.player_inc), {"baseForm": "0x00000007", "loaded3D": True, "cellForm": self.player_cell}, {}
    def pause(self, backend, seconds):
        self.pauses += 1
        if not self.load_on_pause: raise TimeoutError("original bounded deadline exhausted")
        self.raw["loaded3D"] = True
    def tool(self, tool, args, **kwargs):
        if tool != "npc_persistence": raise AssertionError("Unexpected tool")
        self.calls.append(copy.deepcopy(args))
        action = args["action"]
        if action == "set_visibility":
            records = list(self.saved[-1]["fixtureVisibility"]["commands"].values())
            if not records or records[-1]["status"] != "intent": raise AssertionError("Durable mutation intent missing")
            for key in ("providerSession", "worldGeneration", "currentVmHandle", "runtimeHandle", "parentCell"):
                if args[key] != self.raw[key]: raise AssertionError("Native exact guard mismatch")
            if args["expectedDisabled"] != self.raw["disabled"]: raise AssertionError("Expected state mismatch")
            self.raw["disabled"] = not args["visible"]
            self.raw["loaded3D"] = False
            if self.fail_mutation: raise TimeoutError("engine action completed but native ACK lost")
            raw = dict(self.raw, requestId=args["requestId"], mutationIssued=True, resetInventory=False)
        elif action == "visibility_state":
            raw = copy.deepcopy(self.raw)
        else: raise AssertionError("No generic Enable/Disable or Papyrus permitted")
        self.hook(action, raw)
        return raw


class FixtureVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.s = Session()
        self.guard = patch.object(visibility.fixture_actors, "guard", return_value={"incarnation": self.s.incarnation})
        self.guarded = self.guard.start(); self.addCleanup(self.guard.stop)
        patches = [patch.object(visibility.fixture_actors.native, "alive", return_value=True),
                   patch.object(visibility.Backend, "guard_world", return_value=None),
                   patch.object(visibility.actor_domain, "anchor", side_effect=self.s.player),
                   patch.object(visibility.Backend, "pause", lambda backend, seconds: self.s.pause(backend, seconds))]
        for item in patches: item.start(); self.addCleanup(item.stop)

    def run_action(self, action="read", command=None):
        if command is not None: self.s.state["activeSemanticCommandId"] = command
        return visibility.perform(self.s, request(action), time.monotonic()+10, POLICY)

    def setters(self): return [r for r in self.s.calls if r["action"] == "set_visibility"]

    def test_read_disabled_reference_needs_no_loaded3d_and_never_mutates(self):
        self.s.raw.update(disabled=True, loaded3D=False)
        out = self.run_action()
        self.assertTrue(out["disabled"])
        self.assertFalse(out["loaded3D"])
        self.assertTrue(out["unchangedIdentity"])
        self.assertFalse(self.setters())
        self.guarded.assert_not_called()

    def test_hide_once_confirms_disabled_and_preserves_reference(self):
        out = self.run_action("hide")
        self.assertTrue(out["disabled"])
        self.assertFalse(out["loaded3D"])
        self.assertEqual(out["actor"]["reference"], REF)
        self.assertEqual(len(self.setters()), 1)
        self.assertEqual(self.setters()[0]["worldGeneration"], 2)
        self.guarded.assert_not_called()

    def test_show_waits_for_loaded3d_then_checks_ordinary_guard(self):
        self.s.raw.update(disabled=True, loaded3D=False)
        self.s.load_on_pause = True
        out = self.run_action("show")
        self.assertFalse(out["disabled"])
        self.assertTrue(out["loaded3D"])
        self.assertEqual(self.s.pauses, 1)
        self.assertEqual(len(self.setters()), 1)
        self.guarded.assert_called_once()

    def test_already_hidden_is_observed_without_engine_call(self):
        self.s.raw.update(disabled=True, loaded3D=False)
        out = self.run_action("hide")
        self.assertFalse(out["mutationIssued"])
        self.assertFalse(self.setters())

    def test_lost_ack_blocks_new_command_and_does_not_repeat_mutation(self):
        self.s.fail_mutation = True
        with self.assertRaisesRegex(TimeoutError, "ACK lost"): self.run_action("hide")
        self.s.fail_mutation = False
        with self.assertRaisesRegex(ValueError, "Uncertain"): self.run_action("show", "new-command")
        self.assertEqual(len(self.setters()), 1)
        self.assertTrue(self.run_action()["disabled"])

    def test_same_completed_command_cannot_be_replayed(self):
        self.run_action("hide")
        with self.assertRaisesRegex(ValueError, "already attempted"): self.run_action("show")
        self.assertEqual(len(self.setters()), 1)

    def test_foreign_vm_reference_runtime_provider_or_cell_rejected(self):
        for key, value in (("currentVmHandle", "9002"), ("currentReference", "0xFF000002"),
                           ("runtimeHandle", 888), ("providerSession", "foreign"), ("parentCell", "0x00000001")):
            with self.subTest(key=key):
                original = self.s.raw[key]; self.s.raw[key] = value
                with self.assertRaisesRegex(ValueError, "identity changed"): self.run_action("hide")
                self.s.raw[key] = original
        self.assertFalse(self.setters())

    def test_actor_without_creation_witness_or_persistence_rejected(self):
        entry = self.s.state["interactiveActorFixtures"]["Anton"]
        entry["creationWitness"]["nativeReturned"] = False
        with self.assertRaisesRegex(ValueError, "creation witness"): self.run_action("hide")
        self.assertFalse(self.s.calls)

    def test_observer_world_change_before_native_read_rejected(self):
        self.s.player_inc["loadGeneration"] = 2
        with self.assertRaisesRegex(ValueError, "another world"): self.run_action("hide")
        self.assertFalse(self.setters())

    def test_native_world_change_after_mutation_is_uncertain_without_replay(self):
        def change(action, raw):
            if action == "set_visibility": raw["worldGeneration"] += 1
        self.s.hook = change
        with self.assertRaisesRegex(ValueError, "identity changed"): self.run_action("hide")
        self.assertEqual(len(self.setters()), 1)
        self.assertEqual(next(iter(self.s.state["fixtureVisibility"]["commands"].values()))["status"], "uncertain")

    def test_native_world_change_between_separate_calls_rejected(self):
        self.run_action()
        self.s.raw["worldGeneration"] += 1
        with self.assertRaisesRegex(ValueError, "identity changed"): self.run_action("hide")
        self.assertFalse(self.setters())

    def test_enable_timeout_does_not_retry_engine_call(self):
        self.s.raw.update(disabled=True, loaded3D=False)
        with self.assertRaises(TimeoutError): self.run_action("show")
        self.assertEqual(len(self.setters()), 1)
        self.assertEqual(next(iter(self.s.state["fixtureVisibility"]["commands"].values()))["status"], "uncertain")

    def test_creation_native_identity_modified_during_read_rejected(self):
        def change(action, raw):
            self.s.state["interactiveActorFixtures"]["Anton"]["nativePersistentIdentity"]["currentVmHandle"] = "9002"
        self.s.hook = change
        with self.assertRaisesRegex(ValueError, "creation identity changed"): self.run_action("hide")
        self.assertFalse(self.setters())

    def test_player_cell_changed_during_read_rejected(self):
        self.s.hook = lambda action, raw: setattr(self.s, "player_cell", "0x00000001")
        with self.assertRaisesRegex(ValueError, "cell changed"): self.run_action("hide")
        self.assertFalse(self.setters())

    def test_hide_can_complete_before_model_unloads(self):
        def change(action, raw):
            if action == "set_visibility": self.s.raw["loaded3D"] = raw["loaded3D"] = True
        self.s.hook = change
        result = self.run_action("hide")
        self.assertTrue(result["disabled"])
        self.assertTrue(result["loaded3D"])
        self.assertEqual(len(self.setters()), 1)

    def test_other_group_fixture_is_unchanged(self):
        other = copy.deepcopy(self.s.state["interactiveActorFixtures"]["Anton"])
        other.update(tag="Wild", reference="0xFF000002", createdReference="0xFF000002", creationId="2"*32)
        other["creationWitness"].update(reference="0xFF000002", creationId="2"*32)
        self.s.state["interactiveActorFixtures"]["Wild"] = other
        before = copy.deepcopy(other)
        self.run_action("hide")
        self.assertEqual(self.s.state["interactiveActorFixtures"]["Wild"], before)

    def test_exact_request_does_not_accept_raw_selectors_or_reference(self):
        for extra in ("reference", "script", "resetInventory"):
            value = request("hide"); value[extra] = True
            with self.assertRaises(ValueError): visibility.validate("object.perform", value)

    def test_read_and_mutation_operation_separation(self):
        with self.assertRaisesRegex(ValueError, "requires world.read"): visibility.validate("object.perform", request())
        with self.assertRaisesRegex(ValueError, "require object.perform"): visibility.validate("world.read", request("hide"))


if __name__ == "__main__": unittest.main()
