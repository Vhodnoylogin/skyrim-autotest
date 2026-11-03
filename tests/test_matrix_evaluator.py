import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import matrix_evaluator as subject
from skyrim_autotest.interactive_bindings import BindingError


def graph(**changes):
    return {"schema": "claw-matrix-input-graph/1", "profile": "Example.Weight", "sex": "female",
            "activeRules": 1, "sources": [{"name": "$actor.weight", "kind": "actor-weight"}],
            "targets": ["WolfA"], **changes}


class MatrixEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.exe, self.xml, self.source = [self.root / name for name in ("native.exe", "matrix.xml", "Kernel.cpp")]
        for path in (self.exe, self.xml, self.source):
            path.write_bytes(path.name.encode())
        sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.config = {"executable": str(self.exe), "executableSha256": sha(self.exe),
                       "matrix": str(self.xml), "matrixSha256": sha(self.xml),
                       "sourcePins": [{"path": str(self.source), "sha256": sha(self.source)}]}

    def run_native(self, config=None, family="Example.Weight", sources=None, weight=40, timeout=3, responses=None):
        if responses is None:
            responses = [(graph(), ""), ({"WolfA": 0.0, "WolfUnused": 0.0}, "native unavailable human diagnostic")]
        with patch.object(subject, "_run", side_effect=responses) as run:
            result = subject.evaluate(config or self.config, family, {} if sources is None else sources, weight, timeout)
        return result, run

    def test_available_empty_sources_preserve_all_native_zero_outputs_and_diagnostics(self):
        result, run = self.run_native()
        self.assertEqual(result["outputs"], {"WolfA": 0.0, "WolfUnused": 0.0})
        self.assertEqual(result["inputs"], {"sources": {}, "weightRaw": 40.0})
        self.assertIn("unavailable", result["diagnostics"]["matrix"])
        self.assertFalse(result["provenance"]["publicTargetCatalogVerified"])
        self.assertFalse(result["provenance"]["gameContacted"])
        self.assertEqual(run.call_args_list[0].args[2], run.call_args_list[1].args[2])
        self.assertEqual(run.call_args_list[1].args[0][-2:], ["--actor-weight-raw", "40.0"])

    def test_failed_pin_never_invokes_executable(self):
        for field in ("executableSha256", "matrixSha256"):
            with self.subTest(field=field):
                config = {**self.config, field: "0" * 64}
                with patch.object(subject, "_run") as run, self.assertRaises(BindingError):
                    subject.evaluate(config, "Example.Weight", {}, 40, 3)
                run.assert_not_called()
        self.source.write_bytes(b"changed closure")
        with patch.object(subject, "_run") as run, self.assertRaises(BindingError):
            subject.evaluate(self.config, "Example.Weight", {}, 40, 3)
        run.assert_not_called()

    def test_changed_input_between_commands_blocks_second_call(self):
        def changed(*unused):
            self.xml.write_bytes(b"changed")
            return graph(), ""
        with patch.object(subject, "_run", side_effect=changed) as run, self.assertRaises(BindingError):
            subject.evaluate(self.config, "Example.Weight", {}, 40, 3)
        self.assertEqual(run.call_count, 1)

    def test_foreign_family_and_missing_targets_refused(self):
        for responses in ([(graph(profile="Foreign"), "")], [(graph(), ""), ({"Other": 0.0}, "")]):
            with self.subTest(responses=responses), self.assertRaises(BindingError):
                self.run_native(responses=responses)

    def test_malformed_graph_source_and_late_native_result_refused(self):
        for sources in ([{"name": "Belly", "kind": []}], [{"name": "Belly", "kind": "skee-morph"}] * 2):
            with self.subTest(sources=sources), self.assertRaises(BindingError):
                self.run_native(responses=[(graph(sources=sources), "")])
        result = subprocess.CompletedProcess([], 0, b"{}", b"")
        with patch.object(subject.subprocess, "run", return_value=result), \
                patch.object(subject.time, "monotonic", side_effect=[0, 2]), self.assertRaisesRegex(BindingError, "after its original deadline"):
            subject._run(["native"], "", 1)

    def test_missing_ordinary_observation_never_becomes_zero(self):
        response = graph(sources=[{"name": "Belly", "kind": "skee-morph"}])
        with self.assertRaisesRegex(BindingError, "lacks observed ordinary"):
            self.run_native(responses=[(response, "")])
        result, run = self.run_native(sources={"Belly": 0}, responses=[(response, ""), ({"WolfA": 0.0}, "")])
        self.assertEqual(run.call_args_list[1].args[1], "Belly\t0.0\n")
        self.assertEqual(result["inputs"]["sources"], {"Belly": 0.0})

    def test_invalid_inputs_are_not_native_calls(self):
        for kwargs in ({"sources": {"A": float("nan")}}, {"sources": {"A": True}},
                       {"sources": {"$actor.weight": .5}}, {"sources": {"Name": 0, "name": 1}},
                       {"sources": {"Bad\nname": 0}}, {"weight": None}, {"weight": True},
                       {"weight": 101}, {"weight": float("inf")}, {"timeout": 0}, {"timeout": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(BindingError):
                self.run_native(**kwargs)

    def test_nonfinite_bool_and_duplicate_output_identities_refused(self):
        for outputs in ({"WolfA": float("inf")}, {"WolfA": True}, {"WolfA": 0, "wolfa": 0}):
            with self.subTest(outputs=outputs), self.assertRaises(BindingError):
                self.run_native(responses=[(graph(), ""), (outputs, "")])

    def test_strict_json_duplicate_nonfinite_and_invalid_encoding_refused(self):
        for data in (b'{"A":0,"A":1}', b'{"A":NaN}', b'{"A":Infinity}', b'\xff', b'{"A":'):
            with self.subTest(data=data), self.assertRaises(BindingError):
                subject._json(data)

    def test_timeout_exit_and_size_are_visible_errors(self):
        with patch.object(subject.subprocess, "run", side_effect=subprocess.TimeoutExpired(["native"], 1)), self.assertRaises(BindingError):
            subject._run(["native"], "", subject.time.monotonic() + 1)
        for result in (subprocess.CompletedProcess([], 2, b"{}", b"unknown family"),
                       subprocess.CompletedProcess([], 0, b"x" * (subject._MAX_RESPONSE + 1), b"")):
            with self.subTest(result=result.returncode), patch.object(subject.subprocess, "run", return_value=result), self.assertRaises(BindingError):
                subject._run(["native"], "", subject.time.monotonic() + 1)
        with patch.object(subject.subprocess, "run") as run, self.assertRaises(BindingError):
            subject._run(["native"], "", subject.time.monotonic() - 1)
        run.assert_not_called()

    def test_duplicate_alias_source_pin_and_nonabsolute_paths_refused(self):
        configs = [{**self.config, "matrix": "relative.xml"},
                   {**self.config, "sourcePins": [self.config["sourcePins"][0]] * 2},
                   {**self.config, "executableSha256": "F" * 64}]
        for config in configs:
            with self.subTest(config=config), self.assertRaises(BindingError):
                subject.validate_config(config)


if __name__ == "__main__":
    unittest.main()
