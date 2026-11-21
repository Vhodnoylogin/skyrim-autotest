import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skyrim_autotest import runner


class CaptureOperationTimingTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.ledger = Path(directory) / 'steps.jsonl'
        self.enterContext(patch.object(runner.native, 'alive', return_value=True))
        self.request = self.enterContext(patch.object(runner, 'request'))
        self.session = runner.Session(directory, {'port': 1, 'game': {'pid': 42}})

    def rows(self):
        return [json.loads(line) for line in self.ledger.read_text(encoding='utf-8').splitlines()]

    @unittest.skipUnless(os.name == 'nt', 'Windows QPC required')
    def test_outer_interval_encloses_transport_and_preserves_reply(self):
        reply = {'kind': 'screenshot', 'frame': 81}
        internal = []

        def fake_request(port, route, *args, **kwargs):
            internal.append(runner.native.qpc_ticks())
            return {'pid': 42} if route == 'api/health' else reply

        self.request.side_effect = fake_request
        self.assertIs(self.session.tool('capture', {'kind': 'native'}), reply)
        row, = self.rows()
        timing = row['captureOperationInterval']
        self.assertEqual(timing['clock'], 'windows-qpc')
        self.assertEqual(timing['qpcFrequency'], runner.native.qpc_frequency())
        self.assertLessEqual(internal[0], timing['requestQpc'])
        self.assertLessEqual(timing['requestQpc'], internal[1])
        self.assertLessEqual(internal[1], timing['responseQpc'])
        self.assertEqual(row['result'], reply)

    def test_rejected_and_failed_capture_dispatch_keep_the_interval(self):
        server_error = runner.HTTPResponseError(404, 'api/tool/capture', 'provider unavailable')
        rejection = {'ok': False, 'isError': True, 'error': 'capture unavailable'}
        args = {'kind': 'native'}
        self.request.side_effect = [{'pid': 42}, server_error, {'pid': 42}, rejection]
        with patch.object(runner.native, 'qpc_frequency', return_value=100), \
                patch.object(runner.native, 'qpc_ticks', side_effect=[10, 30, 31, 40]):
            with self.assertRaises(runner.HTTPResponseError) as raised:
                self.session.tool('capture', args)
            self.assertIs(raised.exception, server_error)
            with self.assertRaises(runner.ToolError) as raised:
                self.session.tool('capture', args)
            self.assertEqual(raised.exception.result, rejection)
        failure, rejected = self.rows()
        self.assertEqual((failure['kind'], rejected['kind']), ('tool-error', 'tool'))
        self.assertEqual(failure['clientRequestId'], server_error.client_request_id)
        timings = [row['captureOperationInterval'] for row in (failure, rejected)]
        self.assertEqual(timings, [
            {'schemaVersion': 1, 'status': 'measured', 'clock': 'windows-qpc',
             'qpcFrequency': 100, 'requestQpc': start, 'responseQpc': end}
            for start, end in ((10, 30), (31, 40))
        ])
        self.assertEqual(self.request.call_count, 4)

    def test_unavailable_clock_preserves_single_dispatch_and_original_failure(self):
        missing = OSError('clock unavailable')
        request_error = TimeoutError('capture did not return')
        self.request.side_effect = [{'pid': 42}, {'ok': True}, {'pid': 42}, request_error]
        with patch.object(runner.native, 'qpc_frequency', side_effect=[missing, 100]), \
                patch.object(runner.native, 'qpc_ticks', side_effect=[10, missing]):
            self.assertEqual(self.session.tool('capture', {}), {'ok': True})
            with self.assertRaises(TimeoutError) as raised:
                self.session.tool('capture', {})
            self.assertIs(raised.exception, request_error)
        self.assertEqual([row['captureOperationInterval'] for row in self.rows()],
                         [{'schemaVersion': 1, 'status': 'unavailable'}] * 2)
        self.assertEqual(self.request.call_count, 4)

    def test_neither_discovery_nor_expired_capture_before_dispatch_has_an_interval(self):
        self.request.side_effect = [{'pid': 42}, {}] * 3 + [{'pid': 42}]
        with patch.object(runner.native, 'qpc_frequency') as frequency:
            for args in ({'kind': 'providers'}, {'kind': 'extensions'}, {'action': 'status'}):
                self.session.tool('capture', args)
            with patch.object(runner.time, 'monotonic', side_effect=[0, 0, 2, 2]):
                with self.assertRaisesRegex(TimeoutError, 'readiness deadline'):
                    self.session.tool('capture', {}, deadline=1)
        frequency.assert_not_called()
        self.assertEqual(self.request.call_count, 7)
        self.assertEqual(len(self.rows()), 4)
        self.assertTrue(all('captureOperationInterval' not in row for row in self.rows()))
