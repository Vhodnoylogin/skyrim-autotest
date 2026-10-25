import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from skyrim_autotest.cli import main
from test_native14 import snapshot


class Native14CliTests(unittest.TestCase):
    def invoke(self, path, *extra):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(['validate-native14', '--snapshot', str(path),
                         '--expected-pid', '77', '--max-age-micros', '500000', *extra])
        return code, json.loads(output.getvalue())

    def test_file_check_needs_no_configuration_and_is_not_a_game_test(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native14.json'
            contents = json.dumps(snapshot()).encode()
            path.write_bytes(contents)
            code, result = self.invoke(path)
            self.assertEqual(code, 0)
            self.assertEqual(result['observationValidation'], 'valid')
            self.assertFalse(result['gameTestingPerformed'])
            self.assertEqual(result['inputSha256'], hashlib.sha256(contents).hexdigest())
            self.assertEqual(result['measurements'], {})
            self.assertEqual(path.read_bytes(), contents)

    def test_duplicate_keys_and_non_json_constants_are_refused_before_validation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            for data in (b'{"schemaVersion":1,"schemaVersion":2}', b'{"value":NaN}', b'{"value":Infinity}'):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    code, result = self.invoke(path)
                    self.assertEqual(code, 2)
                    self.assertEqual(result['result'], 'blocked')
                    self.assertEqual(path.read_bytes(), data)

    def test_finite_measurement_selection_preserves_an_observed_false(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native14.json'
            raw = snapshot()
            raw['frame']['contextFlags'] = 0
            raw['frame']['holstersEnabled'] = False
            raw['frame']['maxCloseDistance'] = {'value': 3.5, 'bits': '0x40600000'}
            path.write_text(json.dumps(raw), encoding='utf-8')
            code, result = self.invoke(path, '--measure', 'frame.maxCloseDistance.value',
                                       '--measure', 'frame.holstersEnabled')
            self.assertEqual(code, 0)
            self.assertEqual(result['measurements']['frame.maxCloseDistance.value'], 3.5)
            self.assertIs(result['measurements']['frame.holstersEnabled'], False)

    def test_oversize_file_is_refused(self):
        from skyrim_autotest.native14_cli import MAX_BYTES
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'large.json'
            path.write_bytes(b' ' * (MAX_BYTES + 1))
            code, result = self.invoke(path)
            self.assertEqual(code, 2)
            self.assertIn('2 MiB', result['reason'])

    def test_duplicate_selection_and_unavailable_observation_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native14.json'
            path.write_text(json.dumps(snapshot()), encoding='utf-8')
            code, result = self.invoke(path, '--measure', 'frame.token', '--measure', 'frame.token')
            self.assertEqual(code, 2)
            self.assertIn('distinct', result['reason'])
            raw = snapshot()
            raw['availability'] = 'pending'
            path.write_text(json.dumps(raw), encoding='utf-8')
            code, result = self.invoke(path)
            self.assertEqual(code, 2)

    def test_excessive_json_nesting_is_a_refusal_without_traceback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'nested.json'
            path.write_bytes(b'[' * 1500 + b'0' + b']' * 1500)
            code, result = self.invoke(path)
            self.assertEqual(code, 2)
            # Parser recursion limits differ across Python builds; an early
            # structural refusal is equally valid and must remain concise JSON.
            self.assertTrue(result['reason'])
            self.assertNotIn('Traceback', result['reason'])

    def test_multiframe_haptic_interval_uses_the_real_baseline_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native14.json'
            baseline_path = Path(folder) / 'baseline.json'
            raw = snapshot()
            baseline = snapshot()
            baseline['haptics'] = {'claim': 'native_request_only', 'totalRequests': '0',
                                   'overwrittenRequests': '0', 'count': 0, 'requests': []}
            baseline_path.write_text(json.dumps(baseline), encoding='utf-8')
            raw['frame']['token']['frameSerial'] = str(int(baseline['frame']['token']['frameSerial']) + 1)
            raw['publications'] = str(int(baseline['publications']) + 1)
            path.write_text(json.dumps(raw), encoding='utf-8')
            code, result = self.invoke(path, '--haptics-baseline', str(baseline_path))
            self.assertEqual(code, 0)
            self.assertEqual(len(result['newHapticRequests']), len(raw['haptics']['requests']))
            self.assertIn('baselineSha256', result)

    def test_a_baseline_with_unknown_frame_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'native14.json'
            path.write_text(json.dumps(snapshot()), encoding='utf-8')
            baseline_path = Path(folder) / 'baseline.json'
            baseline = snapshot()
            baseline['availability'] = 'pending'
            baseline_path.write_text(json.dumps(baseline), encoding='utf-8')
            code, result = self.invoke(path, '--haptics-baseline', str(baseline_path))
            self.assertEqual(code, 2)


if __name__ == '__main__':
    unittest.main()
