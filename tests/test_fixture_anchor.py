"""One-shot common arena preparation with actual identity and stable readback."""
import copy
import math
import unittest
from unittest.mock import patch

from skyrim_autotest import fixture_anchor as anchor, runner


class Session:
    def __init__(self, clock):
        self.clock = clock
        game = {"pid": 123, "birth": 456, "path": "C:/Game/SkyrimSE.exe"}
        self.state = {"id": "anchor-run", "game": game, "testProfile": "Owned Copy", "port": 8920,
            "ownedWorldGeneration": 1, "configuration": {"game_edition": "se", "se_fixture_anchor": anchor.RECIPE},
            "initialWorldTransition": {"completed": True, "beforeGame": copy.deepcopy(game),
                "afterGame": copy.deepcopy(game), "worldGeneration": 1, "cursor": 10}}
        self.ref = "0x0702A1B9"  # Installed load order, not the file's raw0202A1B9.
        self.position, self.heading = [-363.0, 2035.0, 6976.35], 260.0
        self.marker_position, self.marker_base = list(anchor.TARGET_POSITION), "0x0000003B"
        self.player_handle, self.marker_handle = 100, 200
        self.calls, self.mutations, self.saved, self.logs = [], [], [], []
        self.fail_after, self.drift, self.bad_heading = None, 0, False
        self.on_mutation = lambda function: None
        self.blocked, self.metadata_bad = False, False

    def save(self): self.saved.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): self.logs.append((args, kwargs))

    def tool(self, tool, args, timeout, deadline):
        self.clock[0] += .001
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "menu":
            return {"messageBoxOpen": self.blocked, "openMenus": [], "menuStates": []}
        if tool == "inspect":
            if args["kind"] == "scene":
                return {"playerLoaded": True, "cell": {"editorId": "QASmoke", "formId": anchor.CELL}}
            ref = args["refs"][0]
            player = ref == "0x00000014"
            return {"ok": True, "sessionId": "observer", "loadGeneration": 1, "refs": [{
                "status": "available", "deleted": False, "disabled": False, "loaded3D": player,
                "baseForm": "0x00000007" if player else self.marker_base, "cellForm": anchor.CELL,
                "position": list(self.position if player else self.marker_position),
                "identity": {"form": ref, "runtimeHandle": self.player_handle if player else self.marker_handle,
                             "loadGeneration": 1}}]}
        if tool != "papyrus": raise AssertionError("Unexpected tool")
        if args["action"] == "describe":
            script = args["script"]
            methods = {"GetFormFromFile": (["Int", "String"], "Form")} if script == "Game" else {
                "MoveTo": (["ObjectReference", "Float", "Float", "Float", "Bool"], "None"),
                "SetAngle": (["Float"]*3, "None"),
                **{name: ([], "Float") for name in ("GetPositionX", "GetPositionY", "GetPositionZ", "GetAngleZ")}}
            rows = [{"name": n, "params": [{"type": p} for p in params], "returnType": returns,
                     "native": not self.metadata_bad} for n, (params, returns) in methods.items()]
            return {"name": script, "globalFunctions": rows if script == "Game" else [],
                    "memberFunctions": rows if script != "Game" else []}
        function = args["function"]
        if function == "GetFormFromFile":
            assert args["args"] == [0x02A1B9, "Dragonborn.esm"]
            return {"returned": {"formId": self.ref}}
        if function.startswith("GetPosition"):
            if function.endswith("X") and self.state.get("fixtureAnchor", {}).get("steps", {}).get("SetAngle") == "returned":
                self.position[0] += self.drift
            return {"returned": self.position["XYZ".index(function[-1])]}
        if function == "GetAngleZ": return {"returned": self.heading}
        self.mutations.append(copy.deepcopy(args))
        intent = self.saved[-1]["fixtureAnchor"]
        assert intent["status"] == "intent" and intent["steps"][function] == "intent"
        assert args["self"] == {"form": "0x00000014"}
        if function == "MoveTo":
            assert args["args"] == [{"form": self.ref}, *anchor.OFFSET, False]
            self.position = [self.marker_position[i]+anchor.OFFSET[i] for i in range(3)]
        elif function == "SetAngle": self.heading = 100 if self.bad_heading else args["args"][2]
        else: raise AssertionError("Unexpected mutation")
        self.on_mutation(function)
        if function == self.fail_after: raise TimeoutError("lost mutation ACK")
        return {"called": True, "returned": None, "returnedType": "None"}


class FixtureAnchorTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.s = Session(self.clock)
        self.events = []
        for patcher in (patch.object(anchor.time, "monotonic", side_effect=lambda: self.clock[0]),
                        patch.object(anchor.time, "sleep", side_effect=lambda n: self.clock.__setitem__(0, self.clock[0]+n)),
                        patch.object(anchor.native, "alive", return_value=True),
                        patch.object(runner, "request", side_effect=self.event_read)):
            patcher.start(); self.addCleanup(patcher.stop)

    def event_read(self, port, route, **kwargs):
        self.assertEqual(port, 8920)
        return {"events": list(self.events), "headSeq": 10+len(self.events)}

    def prepare(self): return anchor.prepare_anchor(self.s, self.clock[0]+20)

    def test_exact_installed_marker_two_one_shot_mutations_and_stable_readback(self):
        result = self.prepare()
        self.assertEqual([x["function"] for x in self.s.mutations], ["MoveTo", "SetAngle"])
        self.assertEqual(result["target"]["reference"], "0x0702A1B9")
        self.assertEqual(result["status"], "prepared")
        self.assertLess(math.dist(result["position"], anchor.POSITION), .001)
        self.assertGreaterEqual(result["stableSampleSpanSeconds"], .2)
        self.assertEqual(len(result["samples"]), 2)
        self.assertFalse(result["provenance"]["physicsClearanceVerified"])
        self.assertFalse(result["provenance"]["subjectStarted"])
        self.assertNotIn("gameplayBootstrap", self.s.state)
        self.assertEqual(self.s.state["initialWorldTransition"]["worldGeneration"], 1)

    def test_absent_wrong_recipe_vr_and_incomplete_world_fail_before_mutation(self):
        for change in (None, "unknown", True):
            self.s.state["configuration"]["se_fixture_anchor"] = change
            with self.subTest(change=change), self.assertRaises(ValueError): self.prepare()
        self.s.state["configuration"]["se_fixture_anchor"] = anchor.RECIPE
        self.s.state["configuration"]["game_edition"] = "vr"
        with self.assertRaises(ValueError): self.prepare()
        self.s.state["configuration"]["game_edition"] = "se"
        self.s.state["initialWorldTransition"]["completed"] = False
        with self.assertRaises(ValueError): self.prepare()
        self.assertFalse(self.s.mutations)

    def test_actual_marker_position_or_base_must_match_before_player_move(self):
        for kind in ("position", "base"):
            self.s = Session(self.clock)
            if kind == "position": self.s.marker_position[0] += 20
            else: self.s.marker_base = "0x00000034"
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "marker"):
                self.prepare()
            self.assertFalse(self.s.mutations)

    def test_existing_actor_attempt_or_anchor_attempt_never_replays(self):
        self.s.state["interactiveActorFixtures"] = {"M1": {"status": "uncertain"}}
        with self.assertRaisesRegex(ValueError, "never replay"): self.prepare()
        self.s.state.pop("interactiveActorFixtures")
        self.prepare()
        with self.assertRaisesRegex(ValueError, "never replay"): self.prepare()
        self.assertEqual(len(self.s.mutations), 2)

    def test_lost_move_or_angle_ack_is_terminal_without_replay(self):
        for function, count in (("MoveTo", 1), ("SetAngle", 2)):
            self.s = Session(self.clock); self.s.fail_after = function
            with self.subTest(function=function), self.assertRaises(TimeoutError): self.prepare()
            self.assertEqual(len(self.s.mutations), count)
            self.assertEqual(self.s.state["fixtureAnchor"]["status"], "uncertain")
            self.assertEqual(self.s.state["fixtureAnchor"]["steps"][function], "intent")
            with self.assertRaisesRegex(ValueError, "never replay"): self.prepare()
            self.assertEqual(len(self.s.mutations), count)

    def test_marker_or_player_identity_change_after_move_stops_before_angle(self):
        for field in ("marker_handle", "player_handle"):
            self.s = Session(self.clock)
            self.s.on_mutation = lambda fn: setattr(self.s, field, 999)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "changed|differs"):
                self.prepare()
            self.assertEqual(len(self.s.mutations), 1)
            self.assertEqual(self.s.state["fixtureAnchor"]["status"], "uncertain")

    def test_blocked_menu_or_non_native_metadata_cannot_prepare_arena(self):
        for field in ("blocked", "metadata_bad"):
            self.s = Session(self.clock); setattr(self.s, field, True)
            with self.subTest(field=field), self.assertRaises(ValueError): self.prepare()
            self.assertFalse(self.s.mutations)

    def test_current_lifecycle_change_refuses_before_any_mutation(self):
        self.events = [{"seq": 11, "topic": "lifecycle", "data": {"event": "preLoadGame"}}]
        with self.assertRaisesRegex(ValueError, "World transition"): self.prepare()
        self.assertTrue(self.s.state["initialWorldTransition"]["worldInvalidated"])
        self.assertFalse(self.s.mutations)

    def test_drift_and_wrong_heading_keep_raw_samples_and_never_repeat_mutations(self):
        for field, value in (("drift", 2), ("bad_heading", True)):
            self.s = Session(self.clock); setattr(self.s, field, value)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "did not settle|settling deadline"):
                self.prepare()
            record = self.s.state["fixtureAnchor"]
            self.assertEqual(record["status"], "uncertain")
            self.assertGreater(len(record["samples"]), 2)
            self.assertEqual(len(self.s.mutations), 2)
            self.assertIn("positionErrorGameUnits", record["samples"][-1])

    def test_late_mutation_ack_stops_at_original_deadline(self):
        self.s.on_mutation = lambda function: self.clock.__setitem__(0, self.clock[0]+21)
        with self.assertRaises(TimeoutError): self.prepare()
        self.assertEqual(len(self.s.mutations), 1)
        self.assertEqual(self.s.state["fixtureAnchor"]["steps"]["MoveTo"], "intent")

    def test_late_affirmative_stable_sample_cannot_bypass_settling_deadline(self):
        original = self.s.tool
        reads = []
        def tool(name, args, timeout, deadline):
            result = original(name, args, timeout, deadline)
            if name == "papyrus" and args.get("function") == "GetAngleZ":
                reads.append(True)
                if len(reads) == 2: self.clock[0] += 6
            return result
        self.s.tool = tool
        with self.assertRaisesRegex(ValueError, "settling deadline"): self.prepare()
        self.assertEqual(len(self.s.state["fixtureAnchor"]["samples"]), 2)
        self.assertEqual(len(self.s.mutations), 2)
        self.assertEqual(self.s.state["fixtureAnchor"]["status"], "uncertain")


if __name__ == "__main__": unittest.main()
