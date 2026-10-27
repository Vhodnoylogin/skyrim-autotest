"""Save lifecycle cannot authorize an overlapping or redundant cell transition."""
import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap, fixture_anchor as anchor, runner


class FixtureTransitionTests(unittest.TestCase):
    def test_loaded_fixture_stabilizes_before_optional_single_cell_transition(self):
        for loaded_cell in ('QASmoke', 'OtherCell'):
            with self.subTest(loaded_cell=loaded_cell):
                timeline = []
                class Session:
                    state = {'port': 1}
                    def phase(self, *args): pass
                    def log(self, *args, **kwargs): pass
                    def save(self): pass
                    def tool(self, name, args, **kwargs):
                        timeline.append((name, args))
                        return {'cell': {'editorId': 'VRPlayroom01'}, 'frame': 100}
                ready_scene = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}
                def ready(session, cell, new_game, **kwargs):
                    timeline.append(('stable', cell))
                    return ({'playerLoaded': True, 'cell': {'editorId': loaded_cell}}
                            if cell is None else ready_scene), {'openMenus': ['HUD Menu']}
                with patch('skyrim_autotest.initial_world.InitialWorld'), patch.object(bootstrap, 'advance_calibration', return_value=True), \
                     patch.object(bootstrap, 'wait_gameplay_ready', side_effect=ready), \
                     patch.object(bootstrap.vr_probe, 'guard_fixture_modal', return_value=False), \
                     patch.object(bootstrap.vr_probe, 'wait_test_cell', return_value=ready_scene), \
                     patch.object(runner, 'request', return_value={'events': [
                         {'topic': 'lifecycle', 'event': 'postLoadGame', 'frame': 101}]}):
                    session = Session()
                    session.state = {'port': 1}
                    bootstrap.prepare_gameplay(session, {'cell': 'QASmoke', 'fixture': {'saveStem': 'pinned'}})
                transitions = [row for row in timeline if row[0] == 'console']
                self.assertEqual(len(transitions), 0 if loaded_cell == 'QASmoke' else 1)
                self.assertEqual(len([row for row in timeline if row[0] == 'game']), 1)
                if transitions:
                    self.assertLess(timeline.index(('stable', None)), timeline.index(transitions[0]))
                self.assertTrue(session.state['gameplayBootstrap']['completed'])


class MarkerSession:
    def __init__(self, clock):
        self.clock = clock
        game = {"pid": 123, "birth": 456, "path": "C:/Game/SkyrimSE.exe"}
        self.state = {"id": "marker-run", "game": game, "testProfile": "Owned Copy",
            "configuration": {"game_edition": "se", "se_new_game_ui": True,
                "se_fixture_anchor": anchor.RECIPE, "se_fixture_transition": anchor.TRANSITION_RECIPE},
            "initialWorldTransition": {"mode": "new-game", "completed": False, "beforeGame": copy.deepcopy(game)}}
        self.source = {"editorId": "RealmLorkhan", "formId": "0x06000D62"}
        self.marker = {"baseForm": "0x0000003B", "cellForm": anchor.CELL,
                       "position": list(anchor.TARGET_POSITION)}
        self.target, self.calls, self.saved, self.mutations = "0x0702A1B9", [], [], []
        self.player_loaded, self.blocked, self.native_metadata = True, False, True
        self.lifecycle, self.fail_after, self.bad_return = ["newGame"], False, False
        self.on_mutation = lambda: None
        self.on_read = lambda name, args: None

    def save(self): self.saved.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): pass
    def initial_read(self): return list(self.lifecycle)

    def tool(self, name, args, timeout, deadline):
        self.clock[0] += .001
        self.calls.append((name, copy.deepcopy(args)))
        self.on_read(name, args)
        if name == "menu":
            return {"messageBoxOpen": self.blocked, "openMenus": [], "menuStates": []}
        if name == "inspect":
            if args["kind"] == "scene":
                return {"playerLoaded": self.player_loaded, "cell": copy.deepcopy(self.source)}
            ref = args["refs"][0]
            player = ref == "0x00000014"
            row = {"status": "available", "deleted": False, "disabled": False,
                "loaded3D": self.player_loaded if player else False,
                "baseForm": "0x00000007" if player else self.marker["baseForm"],
                "cellForm": self.source["formId"] if player else self.marker["cellForm"],
                "position": [0.0, 0.0, 0.0] if player else list(self.marker["position"]),
                "identity": {"form": ref, "runtimeHandle": 100 if player else 200, "loadGeneration": 1}}
            return {"ok": True, "sessionId": "observer", "loadGeneration": 1, "refs": [row]}
        if name != "papyrus": raise AssertionError("Unexpected tool")
        if args["action"] == "describe":
            script = args["script"]
            methods = {"GetFormFromFile": (["Int", "String"], "Form")} if script == "Game" else {
                "MoveTo": (["ObjectReference", "Float", "Float", "Float", "Bool"], "None"),
                "SetAngle": (["Float"]*3, "None"),
                **{fn: ([], "Float") for fn in ("GetPositionX", "GetPositionY", "GetPositionZ", "GetAngleZ")}}
            rows = [{"name": fn, "params": [{"type": p} for p in params], "returnType": returns,
                     "native": self.native_metadata} for fn, (params, returns) in methods.items()]
            return {"name": script, "globalFunctions": rows if script == "Game" else [],
                    "memberFunctions": rows if script != "Game" else []}
        if args["function"] == "GetFormFromFile":
            assert args["args"] == [0x02A1B9, "Dragonborn.esm"]
            return {"returned": {"formId": self.target}}
        assert args["function"] == "MoveTo"
        assert args["self"] == {"form": "0x00000014"}
        assert args["args"] == [{"form": self.target}, 0.0, 0.0, 0.0, False]
        intent = self.saved[-1]["fixtureTransition"]
        assert intent["status"] == "intent" and intent["nativeCallAttempted"] is True
        assert intent["steps"] == {"MoveTo": "intent"}
        self.mutations.append(copy.deepcopy(args))
        self.source = {"editorId": "QASmoke", "formId": anchor.CELL}
        self.on_mutation()
        if self.fail_after: raise TimeoutError("lost MoveTo ACK")
        return {"called": not self.bad_return, "returned": None, "returnedType": "None"}


class MarkerTransitionTests(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.s = MarkerSession(self.clock)
        for patcher in (patch.object(anchor.time, "monotonic", side_effect=lambda: self.clock[0]),
                        patch.object(anchor.native, "alive", return_value=True),
                        patch.object(anchor.time, "sleep", side_effect=AssertionError("No transition sleep"))):
            patcher.start(); self.addCleanup(patcher.stop)

    def move(self): return anchor.transition_to_anchor(self.s, self.clock[0]+20, self.s.initial_read)

    def test_unloaded_installed_marker_one_durable_native_call_without_cell_wait(self):
        result = self.move()
        self.assertEqual(len(self.s.mutations), 1)
        self.assertEqual(result["target"]["reference"], "0x0702A1B9")
        self.assertIs(result["target"]["loaded3D"], False)
        self.assertEqual(result["status"], "returned")
        self.assertIs(result["nativeCallbackReturned"], True)
        self.assertIs(result["cellReadinessVerified"], False)
        self.assertIs(self.s.state["initialWorldTransition"]["completed"], False)
        self.assertNotIn("ownedWorldGeneration", self.s.state)
        self.assertEqual(self.s.calls[-1][1]["function"], "MoveTo")

    def test_unknown_or_invalid_optin_cannot_move(self):
        for key, value in (("se_fixture_transition", None), ("se_fixture_transition", "unknown"),
                           ("se_fixture_anchor", None), ("game_edition", "vr"), ("se_new_game_ui", False)):
            self.s = MarkerSession(self.clock)
            self.s.state["configuration"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError): self.move()
            self.assertFalse(self.s.mutations)

    def test_completed_foreign_or_already_started_world_cannot_move(self):
        for field in ("completed", "beforeGame", "mode", "ownedLoadTransition", "interactiveSession",
                      "interactiveActorFixtures", "fixtureAnchor", "fixtureTransition"):
            self.s = MarkerSession(self.clock)
            if field == "completed": self.s.state["initialWorldTransition"][field] = True
            elif field == "beforeGame": self.s.state["initialWorldTransition"][field] = {"pid": 999}
            elif field == "mode": self.s.state["initialWorldTransition"][field] = "fixture"
            else: self.s.state[field] = {"status": "intent"}
            with self.subTest(field=field), self.assertRaises(ValueError): self.move()
            self.assertFalse(self.s.mutations)

    def test_lifecycle_blocked_or_unloaded_source_and_redundant_target_refuse(self):
        for field in ("lifecycle", "blocked", "player_loaded", "source"):
            self.s = MarkerSession(self.clock)
            setattr(self.s, field, {"lifecycle": ["newGame", "preLoadGame"], "blocked": True,
                "player_loaded": False, "source": {"editorId": "QASmoke", "formId": anchor.CELL}}[field])
            with self.subTest(field=field), self.assertRaises(ValueError): self.move()
            self.assertFalse(self.s.mutations)

    def test_marker_base_cell_position_or_installed_form_must_match_before_intent(self):
        for field in ("baseForm", "cellForm", "position", "target"):
            self.s = MarkerSession(self.clock)
            if field == "target": self.s.target = "0xFF02A1B9"
            else: self.s.marker[field] = {"baseForm": "0x00000034", "cellForm": "0x00000001",
                "position": [0.0, 0.0, 0.0]}[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "marker"): self.move()
            self.assertFalse(self.s.mutations)
            self.assertNotIn("fixtureTransition", self.s.state)

    def test_live_metadata_or_config_change_before_dispatch_stops(self):
        self.s.native_metadata = False
        with self.assertRaisesRegex(ValueError, "metadata"): self.move()
        self.assertFalse(self.s.mutations)
        self.s = MarkerSession(self.clock)
        def change(name, args):
            if name == "papyrus" and args.get("function") == "GetFormFromFile":
                self.s.state["configuration"]["foreign"] = True
        self.s.on_read = change
        with self.assertRaisesRegex(ValueError, "unchanged"): self.move()
        self.assertFalse(self.s.mutations)
        self.assertEqual(self.s.state["fixtureTransition"]["status"], "uncertain")

    def test_lost_or_invalid_ack_never_replays(self):
        for field in ("fail_after", "bad_return"):
            self.s = MarkerSession(self.clock); setattr(self.s, field, True)
            with self.subTest(field=field), self.assertRaises((TimeoutError, ValueError)): self.move()
            self.assertEqual(len(self.s.mutations), 1)
            self.assertEqual(self.s.state["fixtureTransition"]["status"], "uncertain")
            with self.assertRaisesRegex(ValueError, "never replay"): self.move()
            self.assertEqual(len(self.s.mutations), 1)

    def test_late_ack_or_changed_owner_stays_uncertain_without_readback(self):
        for field in ("deadline", "game"):
            self.s = MarkerSession(self.clock)
            self.s.on_mutation = (lambda: self.clock.__setitem__(0, self.clock[0]+21)) if field == "deadline" else (
                lambda: self.s.state["game"].update(pid=999))
            with self.subTest(field=field), self.assertRaises((TimeoutError, ValueError)): self.move()
            self.assertEqual(len(self.s.mutations), 1)
            self.assertEqual(self.s.state["fixtureTransition"]["status"], "uncertain")
            self.assertEqual(self.s.calls[-1][1]["function"], "MoveTo")


if __name__ == '__main__': unittest.main()
