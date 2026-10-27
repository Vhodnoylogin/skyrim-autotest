import copy
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from skyrim_autotest import actor_domain, fixture_actors, npc_persistence, owned_saves


BASE, RACE = "0x00013475", "0x00013746"
TAGS = ["MThin", "MMuscular", "MHeavy", "FThin", "FMuscular", "FHeavy"]
POLICY = {"schemaVersion": 1, "fixtureActorBases": [BASE], "allowedRaceForms": [RACE], "bindings": [{
    "id": "race", "script": "Actor", "function": "SetRace", "scope": "member", "params": ["race"],
    "returnType": "none", "effect": "mutate", "actorSelf": True, "actorArgs": [], "raceArgs": [0], "completion": "actor-race"}]}


class Session:
    def __init__(self, root):
        profile = root / "Autotest-npc"
        saves = profile / "saves"
        saves.mkdir(parents=True)
        self.state = {"id": "npc-unit", "game": {"pid": 17, "birth": 123, "path": "owned.exe"},
            "testProfile": str(profile), "testProfileName": profile.name, "ownedSaveDirectory": str(saves),
            "configuration": {"allow_owned_save_load": True, "profiles": str(root),
                              "interactive_session": {"nativeBindings": copy.deepcopy(POLICY), "npcPersistence": True}},
            "preflight": {"profile": "Original"}, "ownedWorldGeneration": 1,
            "gameplayBootstrap": {"completed": True}, "scenario": {"cell": "QASmoke"}, "port": 99,
            "platformReferences": {"old": {"id": "0xFF000100"}}, "interactiveActorFixtures": {}, "probeObjectLive": True}
        self.calls, self.durable, self.events, self.logs = [], [], [], []
        self.receipt = None
        self.fail, self.bad_receipt, self.bad_observation = None, None, None
        self.skip_save_callback, self.skip_load_callback = False, False
        self.limit_wait = False
        for index, tag in enumerate(TAGS):
            ref, creation_id = f"0xFF000{index+1:03X}", f"{index+1:032x}"
            actor = {"reference": ref, "base": BASE, "race": RACE, "sex": "male" if index < 3 else "female",
                     "weight": 50, "loaded3D": True}
            witness = {"method": "ObjectReference.PlaceAtMe", "runId": "npc-unit", "creationId": creation_id,
                "reference": ref, "base": BASE, "anchor": "0x00000014", "count": 1, "nativeReturned": True,
                "priorActorCount": index+1, "priorActorsSha256": "1"*64, "forcePersist": True}
            self.state["interactiveActorFixtures"][tag] = {"tag": tag, "status": "created", "runId": "npc-unit",
                "game": copy.deepcopy(self.state["game"]), "worldGeneration": 1, "creationId": creation_id,
                "reference": ref, "createdReference": ref, "base": BASE, "actor": actor,
                "nativePersistentIdentity": {"persistent": True, "currentReference": ref, "base": BASE,
                                             "currentVmHandle": str(9000+index), "protocol": "npc-persistence/1",
                                             "pid": 17, "providerSession": "native-session"},
                "creationWitness": witness, "incarnation": {"sessionId": "observer", "loadGeneration": 1, "runtimeHandle": 700+index}}

    def save(self): self.durable.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): self.logs.append((args, kwargs))
    def phase(self, *args): pass
    def capture_probe_cursor(self): return len(self.events)
    def invalidate_probe_reference(self, reason): self.state["probeObjectLive"] = False

    def add_event(self, name):
        self.events.append({"seq": len(self.events)+1, "topic": "lifecycle", "data": {"event": name}})

    def stream(self, port, path, **kwargs):
        cursor = int(parse_qs(urlparse(path).query).get("since", [0])[0])
        return {"headSeq": len(self.events), "events": copy.deepcopy(self.events[cursor:])}

    def tool(self, tool, args, **kwargs):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "npc_persistence":
            if args["action"] == "bind":
                intent = self.durable[-1]["npcPersistence"]["unit-save"]
                if intent["status"] != "save-intent": raise AssertionError("Bind lacks durable intent")
                actors = []
                for index, entry in enumerate(args["actors"]):
                    actors.append({"tag": entry["tag"], "creationId": entry["creationId"], "base": entry["base"],
                        "savedReference": entry["reference"], "savedVmHandle": str(9000+index),
                        "currentReference": entry["reference"], "currentVmHandle": str(9000+index),
                        "runtimeHandle": 700+index, "persistent": True})
                self.receipt = {"schemaVersion": 1, "protocol": npc_persistence.PROTOCOL, "providerSession": "native-session",
                    "pid": 17, "bindingId": args["bindingId"], "runId": args["runId"], "saveTag": args["saveTag"],
                    "phase": "bound", "saveOrdinal": 0, "loadOrdinal": 0, "actors": actors}
            if self.fail == args["action"]: raise TimeoutError("lost native " + args["action"] + " ACK")
            receipt = copy.deepcopy(self.receipt)
            if self.bad_receipt: self.bad_receipt(receipt)
            return receipt
        if tool == "game":
            if args["action"] == "save":
                target = Path(self.state["ownedSaveDirectory"])
                (target / (args["name"] + ".ess")).write_bytes(b"TESV_SAVEGAMEtest")
                (target / (args["name"] + ".skse")).write_bytes(b"SKSEnative-bundle")
                self.add_event("saveGame")
                if not self.skip_save_callback:
                    self.receipt.update(phase="saved", saveOrdinal=1)
            else:
                intent = self.durable[-1]["npcPersistence"]["unit-save"]
                if intent["status"] != "load-intent" or any(entry["status"] != "load-pending"
                        for entry in self.durable[-1]["interactiveActorFixtures"].values()):
                    raise AssertionError("Load lacks durable invalidation of every old fixture")
                self.add_event("preLoadGame"); self.add_event("postLoadGame")
                if not self.skip_load_callback:
                    self.receipt.update(phase="loaded", loadOrdinal=1)
                    for index, row in enumerate(self.receipt["actors"]):
                        ref, vm = f"0xFF100{index+1:03X}", str(19000+index)
                        row.update(currentReference=ref, resolvedReference=ref, currentVmHandle=vm,
                                   resolvedVmHandle=vm, formResolved=True, handleResolved=True)
            if self.fail == args["action"]: raise TimeoutError("lost native " + args["action"] + " ACK")
            return {"queued": True}
        if tool == "papyrus": return {"returned": self.state["ownedSaveDirectory"]}
        if tool == "inspect": return {"playerLoaded": True, "cell": {"editorId": "QASmoke"}}
        if tool == "menu": return {"messageBoxOpen": False, "openMenus": [], "menuStates": []}
        raise AssertionError("Unexpected tool " + tool)

    def observe_actor(self, backend, spec):
        if self.receipt and self.receipt["phase"] == "loaded":
            row = next(row for row in self.receipt["actors"] if row["currentReference"] == spec["reference"])
            original = self.state["npcPersistence"]["unit-save"]["fixtures"][row["tag"]]
            actor = dict(original["actor"], reference=spec["reference"])
            observation = {"actor": actor, "incarnation": {"sessionId": "observer", "loadGeneration": 2,
                                                          "runtimeHandle": row["runtimeHandle"]}}
        else:
            entry = next(entry for entry in self.state["interactiveActorFixtures"].values() if entry["reference"] == spec["reference"])
            observation = {"actor": copy.deepcopy(entry["actor"]), "incarnation": copy.deepcopy(entry["incarnation"])}
        if self.bad_observation: self.bad_observation(observation)
        return observation


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = Session(Path(self.tmp.name))
        patches = [patch.object(fixture_actors.native, "alive", return_value=True),
            patch.object(npc_persistence.Backend, "guard_world", return_value=None),
            patch.object(actor_domain, "observe_actor", side_effect=self.s.observe_actor),
            patch("skyrim_autotest.runner.request", side_effect=self.s.stream),
            patch("skyrim_autotest.bootstrap.wait_gameplay_ready", return_value=({"playerLoaded": True, "cell": {"editorId": "QASmoke"}}, {})),
            patch("skyrim_autotest.platform.initialize_controllers")]
        for item in patches: item.start(); self.addCleanup(item.stop)

    def save_npcs(self, seconds=10):
        return npc_persistence.perform(self.s, {"action": "save", "saveTag": "unit-save", "fixtureTags": TAGS},
                                       time.monotonic()+seconds, POLICY)

    def load_npcs(self):
        return npc_persistence.perform(self.s, {"action": "load", "saveTag": "unit-save"}, time.monotonic()+10, POLICY)

    def test_full_real_owned_save_load_requires_pair_events_native_remap_and_atomic_six_rebind(self):
        saved = self.save_npcs()
        self.assertTrue(saved["save"]["completed"])
        self.assertEqual(saved["save"]["actorWitnessCount"], 6)
        self.assertEqual(saved["save"]["essSha256"], hashlib.sha256(b"TESV_SAVEGAMEtest").hexdigest())
        loaded = self.load_npcs()
        self.assertTrue(loaded["load"]["sameProcess"])
        self.assertEqual(len(loaded["actors"]), 6)
        self.assertEqual(self.s.state["ownedWorldGeneration"], 2)
        self.assertEqual([args["action"] for tool, args in self.s.calls if tool == "game"], ["save", "load"])
        self.assertEqual(self.s.state["platformReferences"], {})
        for index, tag in enumerate(TAGS):
            entry = self.s.state["interactiveActorFixtures"][tag]
            self.assertEqual(entry["reference"], f"0xFF100{index+1:03X}")
            fixture_actors.require_fixture(self.s, {"reference": entry["reference"], "base": BASE})
        statuses = [{entry["status"] for entry in state["interactiveActorFixtures"].values()}
                    for state in self.s.durable if state.get("npcPersistence", {}).get("unit-save", {}).get("loadAttempted")]
        self.assertTrue(all(value in ({"load-pending"}, {"created"}) for value in statuses))
        observed = npc_persistence.observe(self.s, {"saveTag": "unit-save"}, time.monotonic()+10, POLICY)
        self.assertTrue(observed["load"]["completed"])

    def test_save_requires_actual_persistent_creation_and_exact_complete_six_set(self):
        for change in (lambda: self.s.state["interactiveActorFixtures"][TAGS[0]]["creationWitness"].update(forcePersist=False),
                       lambda: self.s.state["interactiveActorFixtures"].update(extra={})):
            with self.subTest(change=change):
                previous = copy.deepcopy(self.s.state)
                change()
                with self.assertRaises(ValueError): self.save_npcs()
                self.assertFalse(any(tool in ("game", "npc_persistence") for tool, args in self.s.calls))
                self.s.state = previous

    def _lost_save_path(self, fault):
        self.s.fail = fault
        with self.assertRaises(TimeoutError): self.save_npcs()
        before = len(self.s.calls)
        self.assertEqual(self.s.state["npcPersistence"]["unit-save"]["status"], "save-uncertain")
        with self.assertRaises(ValueError): self.save_npcs()
        self.assertFalse(any(tool == "game" for tool, args in self.s.calls[before:]))

    def test_lost_bind_ack_is_durable_terminal_and_never_replayed(self):
        self._lost_save_path("bind")

    def test_lost_save_ack_is_durable_terminal_and_never_replayed(self):
        self._lost_save_path("save")

    def test_lost_load_ack_invalidates_every_old_actor_and_blocks_replay(self):
        self.save_npcs(); self.s.fail = "load"
        with self.assertRaises(TimeoutError): self.load_npcs()
        self.assertTrue(all(entry["status"] == "load-uncertain" for entry in self.s.state["interactiveActorFixtures"].values()))
        with self.assertRaises(ValueError): self.load_npcs()
        self.assertEqual(sum(tool == "game" and args["action"] == "load" for tool, args in self.s.calls), 1)
        with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {"reference": "0xFF000001", "base": BASE})

    def test_changed_pair_stops_before_load_and_saved_bundle_is_not_completed_twice(self):
        self.save_npcs()
        record = self.s.state["ownedSaves"]["unit-save"]
        (Path(self.s.state["ownedSaveDirectory"]) / (record["stem"] + ".skse")).write_bytes(b"SKSEchanged")
        with self.assertRaisesRegex(ValueError, "changed"): self.load_npcs()
        self.assertFalse(any(tool == "game" and args["action"] == "load" for tool, args in self.s.calls))

    def test_native_remap_missing_or_wrong_vm_never_rebinds_even_matching_base_and_form(self):
        self.save_npcs()
        def corrupt(receipt):
            if receipt["phase"] == "loaded": receipt["actors"][-1]["resolvedVmHandle"] = "42"
        self.s.bad_receipt = corrupt
        with self.assertRaisesRegex(ValueError, "remap"): self.load_npcs()
        self.assertTrue(all(entry["status"] == "load-uncertain" and entry["reference"].startswith("0xFF000")
                            for entry in self.s.state["interactiveActorFixtures"].values()))

    def test_stale_observer_load_generation_cannot_rebind_correct_native_remap(self):
        self.save_npcs()
        self.s.bad_observation = lambda observation: observation["incarnation"].update(loadGeneration=1)
        with self.assertRaisesRegex(ValueError, "fresh matching"): self.load_npcs()
        self.assertTrue(all(entry["status"] == "load-uncertain" for entry in self.s.state["interactiveActorFixtures"].values()))

    def test_duplicate_or_foreign_native_identity_is_refused_before_game_save(self):
        self.s.bad_receipt = lambda receipt: receipt["actors"][-1].update(currentVmHandle=receipt["actors"][0]["currentVmHandle"])
        with self.assertRaises(ValueError): self.save_npcs()
        self.assertFalse(any(tool == "game" for tool, args in self.s.calls))

    def test_file_pair_and_native_save_event_without_serialized_bundle_do_not_complete(self):
        self.s.skip_save_callback = True
        with self.assertRaises(TimeoutError): self.save_npcs(seconds=1.5)
        record = self.s.state["npcPersistence"]["unit-save"]
        self.assertEqual(record["status"], "save-uncertain")
        self.assertTrue(self.s.state["ownedSaves"]["unit-save"]["completed"])
        self.assertEqual(sum(tool == "game" and args["action"] == "save" for tool, args in self.s.calls), 1)
        with self.assertRaises(ValueError): self.save_npcs()

    def test_native_receipt_ordinals_provider_and_vm_are_exact(self):
        self.save_npcs()
        record = self.s.state["npcPersistence"]["unit-save"]
        for change in (lambda raw: raw.update(saveOrdinal=2), lambda raw: raw.update(providerSession="foreign"),
                       lambda raw: raw["actors"][0].update(savedVmHandle="9007199254740993", currentVmHandle="9007199254740993")):
            raw = copy.deepcopy(record["savedReceipt"]); change(raw)
            with self.assertRaises(ValueError): npc_persistence._receipt(raw, record, "saved", baseline=record["boundReceipt"])

    def test_completed_load_cannot_be_replayed_and_old_reference_is_not_adopted(self):
        self.save_npcs(); self.load_npcs()
        with self.assertRaises(ValueError): self.load_npcs()
        with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {"reference": "0xFF000001", "base": BASE})
        entry = self.s.state["interactiveActorFixtures"][TAGS[0]]
        entry["restorationWitness"]["native"]["resolvedVmHandle"] = "42"
        with self.assertRaises(ValueError): fixture_actors.require_fixture(self.s, {"reference": entry["reference"], "base": BASE})

    def test_new_process_during_load_is_rejected_without_rebinding(self):
        self.save_npcs()
        original = self.s.tool
        def changed(tool, args, **kwargs):
            result = original(tool, args, **kwargs)
            if tool == "game" and args["action"] == "load": self.s.state["game"]["birth"] = 999
            return result
        self.s.tool = changed
        with self.assertRaisesRegex(ValueError, "process identity"): self.load_npcs()

    def test_exact_request_contract_rejects_arbitrary_save_load_and_partial_bundles(self):
        for request in ({"action": "restart", "saveTag": "unit-save"},
                        {"action": "load", "saveTag": "../outside"},
                        {"action": "load", "saveTag": "unit-save", "dir": "foreign"},
                        {"action": "save", "saveTag": "unit-save", "fixtureTags": TAGS[:5]},
                        {"action": "save", "saveTag": "unit-save", "fixtureTags": [TAGS[0]]*6}):
            with self.subTest(request=request), self.assertRaises(ValueError): npc_persistence.validate_request(request)

    def test_missing_frozen_optin_refuses_before_provider_access(self):
        self.s.state["configuration"]["interactive_session"].pop("npcPersistence")
        with self.assertRaisesRegex(ValueError, "opt-in"): self.save_npcs()
        self.assertEqual(self.s.calls, [])


if __name__ == "__main__": unittest.main()
