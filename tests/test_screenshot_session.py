import hashlib
import json
from pathlib import Path
import struct
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from skyrim_autotest import cli, runner, screenshots


def bmp():
    return (b'BM' + struct.pack('<IHHI', 58, 0, 0, 54) +
            struct.pack('<IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0) + b'\x12\x34\x56\x00')


class ScreenshotSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = []
        self.rows = []
        self.session = SimpleNamespace(dir=self.root, heartbeat_failed=threading.Event(),
            state={'id': 'owned-test', 'game': {'pid': 123}, 'port': 9999},
            save=lambda: None, log=lambda *a, **kw: self.rows.append((a, kw)))
        self.write_image = True
        self.healths = []
        self.addCleanup(patch.stopall)
        patch('skyrim_autotest.runner.native.alive', return_value=True).start()
        patch('skyrim_autotest.runner.request', side_effect=self.request).start()

    def request(self, port, route, body=None, **kw):
        self.calls.append((route, body))
        if route == 'api/health':
            return {'pid': self.healths.pop(0) if self.healths else 123}
        if body.get('kind') == 'providers':
            return {'providers': ['native']}
        if body.get('action') == 'status':
            return {'state': 'done'}
        target = Path(body['outDir']) / body['recording'] / body['variant'] / (body['checkpointId'] + '.bmp')
        if self.write_image:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bmp())
        return {'ok': True, 'file': target.name, 'path': str(target), 'bytes': len(bmp()),
                'provider': 'native', 'degraded': ['nativeFallback']}

    def run_capture(self, **options):
        return runner.Session.tool(self.session, 'capture', {'checkpointId': 'shot-1', **options})

    def test_generic_step_returns_only_actual_verified_bytes(self):
        result = self.run_capture()
        self.assertTrue(result['captureFileVerified'])
        self.assertEqual(result['sha256'], hashlib.sha256(Path(result['image']).read_bytes()).hexdigest())
        self.assertEqual(result['degraded'], ['nativeFallback'])
        posts = [body for route, body in self.calls if route == 'api/tool/capture']
        self.assertEqual(len(posts), 1)
        self.assertTrue(Path(posts[0]['outDir']).is_relative_to(self.root))
        self.assertEqual(self.session.state['screenshots']['shot-1']['status'], 'file_verified')

    def test_scenario_keeps_original_devbench_scale_gate(self):
        self.run_capture(kind='strict-photo', allowNative=False, excludeUi=True)
        body = next(body for route, body in self.calls if route == 'api/tool/capture')
        self.assertIs(body['allowTimeScale'], False)
        self.assertIs(body['allowNative'], False)
        self.assertIs(body['excludeUi'], True)
        self.assertEqual(body['kind'], 'strict-photo')

    def test_path_only_success_is_failure_with_retained_provider_receipt(self):
        self.write_image = False
        with self.assertRaises((ValueError, OSError)):
            self.run_capture()
        record = self.session.state['screenshots']['shot-1']
        self.assertFalse(record['captureFileVerified'])
        self.assertTrue(record['providerReceipt']['ok'])
        self.assertEqual(record['status'], 'unavailable_or_uncertain')
        receipt = json.loads(Path(record['receipt']).read_text())
        self.assertFalse(receipt['captureFileVerified'])

    def test_failed_or_successful_request_id_is_never_replayed(self):
        self.run_capture()
        with self.assertRaisesRegex(ValueError, 'never replay'):
            self.run_capture()
        self.assertEqual(sum(route == 'api/tool/capture' for route, body in self.calls), 1)

    def test_game_identity_change_after_capture_does_not_pass(self):
        self.healths = [123, 123, 999]
        with self.assertRaises(runner.Blocked):
            self.run_capture()
        self.assertFalse(self.session.state['screenshots']['shot-1']['captureFileVerified'])

    def test_provider_discovery_and_burst_status_remain_reads(self):
        self.assertEqual(runner.Session.tool(self.session, 'capture', {'kind': 'providers'}),
                         {'providers': ['native']})
        self.assertEqual(runner.Session.tool(self.session, 'capture', {'action': 'status', 'runId': 'burst-1'}),
                         {'state': 'done'})
        self.assertNotIn('screenshots', self.session.state)

    def test_scenario_cannot_write_outside_run(self):
        with self.assertRaisesRegex(ValueError, 'within its run'):
            self.run_capture(outDir=str(self.root.parent))
        self.assertFalse(any(route == 'api/tool/capture' for route, body in self.calls))

    def test_verified_bmp_and_receipt_collected_and_later_tamper_rejected(self):
        result = self.run_capture()
        artifacts = []
        def copy(path, name, kind, required=False):
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            artifacts.append((name, kind))
            return {'sha256': digest}
        screenshots.collect(self.session, copy)
        self.assertEqual(artifacts, [('screenshot-shot-1.json', 'capture-receipt'),
                                     ('screenshot-shot-1.bmp', 'capture')])
        path = Path(result['image'])
        path.write_bytes(bmp()[:-4] + b'\x99\x88\x77\x00')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            screenshots.collect(self.session, copy)

    def test_existing_pixels_are_not_overwritten_or_adopted(self):
        output = self.root / 'explicit'
        image = output / 'autotest' / 'diagnostic' / 'shot-1.bmp'
        image.parent.mkdir(parents=True)
        image.write_bytes(bmp())
        with self.assertRaisesRegex(ValueError, 'already exist'):
            self.run_capture(outDir=str(output))
        self.assertFalse(any(route == 'api/tool/capture' for route, body in self.calls))

    def test_public_cli_routes_screenshot_to_devbench_module(self):
        with patch('skyrim_autotest.screenshots.main', return_value=0) as command:
            self.assertEqual(cli.main(['screenshot', '--port', '9999', '--id', 'shot-1']), 0)
        command.assert_called_once_with(['--port', '9999', '--id', 'shot-1'])


if __name__ == '__main__':
    unittest.main()
