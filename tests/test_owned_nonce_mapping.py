"""Fresh-New-Game owned save mapping; native receipts are simulated evidence."""
import copy
import hashlib
from pathlib import Path
import re
import tempfile
import unittest

from skyrim_autotest import owned_saves


class Session:
    def __init__(self, root):
        profile = root / "Autotest-nonce"
        self.target = profile / "saves"
        self.target.mkdir(parents=True)
        (profile / "settings.ini").write_text("[General]\nLocalSaves=true\nLocalSettings=true\n", encoding="utf-8")
        self.state = {"id": "nonce-unit", "scenario": {"startMode": "new-game", "steps": []},
            "testProfile": str(profile), "testProfileName": profile.name, "ownedSaveDirectory": str(self.target),
            "preflight": {"profile": "Original"},
            "configuration": {"allow_owned_save_load": True, "profiles": str(root),
                "skse_logs": str(root / "Game user" / "SKSE"), "interactive_session": {"npcPersistence": True}}}
        self.durable, self.logs = [], []

    def save(self): self.durable.append(copy.deepcopy(self.state))
    def log(self, *args, **kwargs): self.logs.append((args, kwargs))


class Backend:
    def __init__(self, session):
        self.s, self.calls, self.mutations = session, [], []
        self.observed, self.receipt_change = "__MO_Saves\\", lambda receipt: None

    def remaining(self): return 15
    def pap(self, script, function, arguments):
        if (script, function, arguments) != ("Utility", "GetINIString", ["sLocalSavePath:General"]):
            raise AssertionError("Unexpected Papyrus operation")
        return self.observed

    def call(self, tool, args):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "game":
            self.mutations.append(args)
            raise AssertionError("A save/load mutation escaped an invalid mapping proof")
        if tool != "npc_persistence" or args.get("action") != "mapping_probe":
            raise AssertionError("Only native mapping read is permitted")
        receipt = {"protocol": "npc-save-mapping/1", "pid": self.s.state["game"]["pid"],
            "marker": args["marker"], "nonce": args["nonce"], "exactBytes": 32, "readOnly": True,
            "nativeDirectory": str(Path(self.s.state["configuration"]["skse_logs"]).parent / self.observed)}
        self.receipt_change(receipt)
        return receipt


class OwnedNonceMappingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.s = Session(Path(self.tmp.name))
        self.b = Backend(self.s)

    def prepare(self):
        owned_saves.prepare_required_mapping_probe(self.s, self.s.target)
        return self.s.state["ownedSaveMappingProbe"]

    def launched(self):
        probe = self.prepare()
        self.s.state["game"] = {"pid": 17, "birth": 123, "path": "owned.exe"}
        return probe

    def save(self):
        return owned_saves.perform(self.b, {"action": "save_game", "saveTag": "owned",
                                            "scope": "owned-disposable-profile"})

    def test_explicit_npc_optin_prepares_random_physical_nonce_before_new_game_without_ess_seed(self):
        probe = self.prepare()
        self.assertTrue(self.s.state["ownedSaveMappingRequired"])
        self.assertEqual(probe["kind"], "native-nonce/1")
        self.assertTrue(probe["preparedBeforeLaunch"])
        self.assertRegex(probe["marker"], re.compile(r"^[0-9a-f]{32}$"))
        self.assertRegex(probe["nonce"], re.compile(r"^[0-9a-f]{32}$"))
        self.assertNotEqual(probe["marker"], probe["nonce"])
        challenge = self.s.target / ("Autotest_Map_" + probe["marker"] + ".probe")
        self.assertEqual(Path(probe["path"]), challenge.resolve())
        self.assertEqual(challenge.read_bytes(), probe["nonce"].encode("ascii"))
        self.assertEqual(probe["sha256"], hashlib.sha256(challenge.read_bytes()).hexdigest())
        self.assertEqual(list(self.s.target.glob("*.ess")), [])
        self.assertEqual(list(self.s.target.glob("*.skse")), [])
        self.assertEqual(self.s.durable[-1]["ownedSaveMappingProbe"], probe)
        self.assertEqual(self.b.calls, [])

    def test_native_exact_nonce_default_virtual_path_and_pid_prove_physical_owned_save_scope(self):
        probe = self.launched()
        self.assertEqual(owned_saves.directory(self.b), self.s.target)
        self.assertEqual(len(self.b.calls), 1)
        tool, args = self.b.calls[0]
        self.assertEqual(tool, "npc_persistence")
        self.assertEqual(args, {"action": "mapping_probe", "marker": probe["marker"], "nonce": probe["nonce"], "timeoutMs": 3000})
        self.assertFalse(self.b.mutations)
        self.assertEqual(self.s.logs[-1][0], ("owned-save-virtual-mapping-verified",))

    def test_wrong_native_mapping_tokens_pid_protocol_length_or_mutability_refuse_before_game_save(self):
        self.launched()
        changes = {
            "foreign PID": lambda receipt: receipt.update(pid=18),
            "wrong marker": lambda receipt: receipt.update(marker="0"*32),
            "wrong nonce": lambda receipt: receipt.update(nonce="0"*32),
            "wrong protocol": lambda receipt: receipt.update(protocol="other/1"),
            "short native bytes": lambda receipt: receipt.update(exactBytes=31),
            "not read-only": lambda receipt: receipt.update(readOnly=False),
            "foreign directory": lambda receipt: receipt.update(nativeDirectory=str(self.s.target.parent / "other")),
            "physical directory echo": lambda receipt: receipt.update(nativeDirectory=str(self.s.target)),
        }
        for label, change in changes.items():
            self.b.receipt_change = change
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, "did not prove"):
                self.save()
        self.assertFalse(self.b.mutations)
        self.assertNotIn("ownedSaves", self.s.state)

    def test_native_pid_and_byte_count_require_real_integer_fields(self):
        self.launched()
        for change in (lambda receipt: receipt.update(pid=17.0), lambda receipt: receipt.update(exactBytes=32.0)):
            self.b.receipt_change = change
            with self.subTest(change=change), self.assertRaises(ValueError):
                owned_saves.directory(self.b)
        self.assertFalse(self.b.mutations)

    def test_changed_physical_nonce_or_saved_hash_refuses_before_native_read_or_game_save(self):
        probe = self.launched()
        challenge = Path(probe["path"])
        original = challenge.read_bytes()
        challenge.write_bytes(b"x"*32)
        with self.assertRaisesRegex(ValueError, "nonce changed"): self.save()
        self.assertEqual(self.b.calls, [])
        challenge.write_bytes(original)
        probe["sha256"] = "0"*64
        with self.assertRaisesRegex(ValueError, "nonce changed"): self.save()
        self.assertEqual(self.b.calls, [])

    def test_wrong_prelaunch_nonce_record_path_and_flags_refuse_before_native_read(self):
        probe = self.launched()
        changes = {
            "not prelaunch": lambda value: value.update(preparedBeforeLaunch=False),
            "coerced prelaunch": lambda value: value.update(preparedBeforeLaunch=1),
            "invalid marker": lambda value: value.update(marker="../outside"),
            "invalid nonce": lambda value: value.update(nonce="not-the-nonce"),
            "foreign recorded path": lambda value: value.update(path=str(self.s.target.parent / "foreign.probe")),
        }
        for label, change in changes.items():
            altered = copy.deepcopy(probe); change(altered)
            self.s.state["ownedSaveMappingProbe"] = altered
            with self.subTest(label=label), self.assertRaises(ValueError): self.save()
        self.assertEqual(self.b.calls, [])
        self.assertFalse(self.b.mutations)

    def test_local_save_and_settings_flags_remain_required_before_native_mapping_read(self):
        self.launched()
        for local_saves, local_settings in ((False, True), (True, False)):
            (self.s.target.parent / "settings.ini").write_text(
                f"[General]\nLocalSaves={str(local_saves).lower()}\nLocalSettings={str(local_settings).lower()}\n", encoding="utf-8")
            with self.subTest(flags=(local_saves, local_settings)), self.assertRaisesRegex(ValueError, "local saves/settings"):
                self.save()
        self.assertEqual(self.b.calls, [])

    def test_late_probe_preparation_and_outside_owned_directory_are_refused_without_writes(self):
        for key in ("game", "launchIntents"):
            self.s.state[key] = {"game": {"pid": 17}} if key == "launchIntents" else {"pid": 17}
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "precede game launch"):
                self.prepare()
            self.s.state.pop(key)
        foreign = self.s.target.parent / "foreign"
        foreign.mkdir()
        with self.assertRaisesRegex(ValueError, "outside owned"):
            owned_saves.prepare_mapping_probe(self.s, foreign)
        self.assertEqual(list(self.s.target.iterdir()), [])
        self.assertEqual(list(foreign.iterdir()), [])

    def test_absent_explicit_npc_optin_preserves_legacy_no_fixture_behavior(self):
        self.s.state["configuration"]["interactive_session"].pop("npcPersistence")
        owned_saves.prepare_required_mapping_probe(self.s, self.s.target)
        self.assertFalse(self.s.state["ownedSaveMappingRequired"])
        self.assertNotIn("ownedSaveMappingProbe", self.s.state)
        self.assertEqual(list(self.s.target.iterdir()), [])


if __name__ == "__main__": unittest.main()
