"""Handle-based exit observations: fake Win32 boundaries and benign owned children."""
import ctypes as C
from datetime import datetime, timezone
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock

from skyrim_autotest import process_exit

EXPECTED = {'pid': 771, 'birth': 0x01D9000012345678, 'path': 'C:/Owned/SkyrimSE.exe'}


class Kernel:
    def __init__(self):
        self.identity = dict(EXPECTED)
        self.handle, self.wait_value, self.code = 991, process_exit.WAIT_TIMEOUT, 259
        self.fail = set()
        self.OpenProcess = Mock(side_effect=self.open)
        self.GetProcessId = Mock(side_effect=lambda handle: 0 if 'pid' in self.fail else self.identity['pid'])
        self.GetProcessTimes = Mock(side_effect=self.times)
        self.QueryFullProcessImageNameW = Mock(side_effect=self.image)
        self.WaitForSingleObject = Mock(side_effect=lambda handle, timeout: self.wait_value)
        self.GetExitCodeProcess = Mock(side_effect=self.exit)
        self.CloseHandle = Mock(side_effect=lambda handle: 'close' not in self.fail)
    def open(self, access, inherit, pid):
        return 0 if 'open' in self.fail else self.handle
    def times(self, handle, birth, exit_time, kernel_time, user_time):
        if 'times' in self.fail: return False
        birth._obj.dwLowDateTime = self.identity['birth'] & 0xFFFFFFFF
        birth._obj.dwHighDateTime = self.identity['birth'] >> 32
        return True
    def image(self, handle, flags, buffer, size):
        if 'image' in self.fail: return False
        buffer.value = self.identity['path']
        size._obj.value = len(buffer.value)
        return True
    def exit(self, handle, out):
        if 'exit' in self.fail: return False
        out._obj.value = self.code
        return True
    def api(self):
        return process_exit._Win32(kernel=self, last_error=lambda: 777)


class ProcessExitTests(unittest.TestCase):
    def setUp(self):
        self.kernel = Kernel()
        self.api = self.kernel.api()
        self.tick = 0
    def clock(self):
        self.tick += 1
        return f'2026-10-26T12:00:00.{self.tick:03d}Z'
    def capture(self, identity=None):
        result = process_exit.capture(identity or dict(EXPECTED), api=self.api, clock=self.clock)
        self.addCleanup(result.close)
        return result

    def test_same_handle_proves_pid_birth_path_with_query_synchronize_rights_only(self):
        tracker = self.capture()
        snapshot = tracker.snapshot()
        self.assertEqual(snapshot['status'], 'running')
        self.assertTrue(snapshot['identityVerified'])
        self.kernel.OpenProcess.assert_called_once_with(process_exit.ACCESS, False, EXPECTED['pid'])
        self.assertEqual(process_exit.ACCESS, 0x101000)
        self.assertEqual(process_exit.ACCESS & 1, 0)  # No PROCESS_TERMINATE.
        self.kernel.GetProcessId.assert_called_once_with(991)
        self.assertEqual(self.kernel.GetProcessTimes.call_args.args[0], 991)
        self.assertEqual(self.kernel.QueryFullProcessImageNameW.call_args.args[0], 991)
        self.kernel.WaitForSingleObject.assert_called_once_with(991, 0)
        self.kernel.GetExitCodeProcess.assert_not_called()
        self.assertEqual(snapshot['observedAtUtc'], '2026-10-26T12:00:00.002Z')
        self.assertIsNone(snapshot['exitCode'])

    def test_pid_birth_or_path_mismatch_closes_without_observing_foreign_process(self):
        for field, changed in (('pid', 772), ('birth', EXPECTED['birth'] + 1), ('path', 'C:/Foreign/Other.exe')):
            kernel = Kernel(); kernel.identity[field] = changed
            tracker = process_exit.capture(dict(EXPECTED), api=kernel.api(), clock=self.clock)
            self.assertEqual(tracker.snapshot()['diagnostic']['reason'], 'identity-mismatch')
            self.assertFalse(tracker.snapshot()['identityVerified'])
            self.assertEqual(tracker.snapshot()['diagnostic']['fields'], [field])
            kernel.WaitForSingleObject.assert_not_called()
            kernel.GetExitCodeProcess.assert_not_called()
            tracker.close(); tracker.close()
            kernel.CloseHandle.assert_called_once_with(991)

    def test_zero_handle_is_unavailable_and_is_not_closed(self):
        self.kernel.fail.add('open')
        tracker = self.capture()
        self.assertEqual(tracker.snapshot()['diagnostic']['operation'], 'OpenProcess')
        self.assertFalse(tracker.snapshot()['handleRetained'])
        tracker.close(); tracker.close()
        self.kernel.GetProcessId.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()
        fake = Mock(open=Mock(return_value=0))
        empty = process_exit.capture(dict(EXPECTED), api=fake)
        self.assertEqual(empty.snapshot()['status'], 'unavailable')
        empty.close(); fake.close.assert_not_called()

    def test_lost_identity_queries_close_once_and_remain_diagnostic(self):
        for failure, operation in (('pid', 'GetProcessId'), ('times', 'GetProcessTimes'), ('image', 'QueryFullProcessImageNameW')):
            kernel = Kernel(); kernel.fail.add(failure)
            tracker = process_exit.capture(dict(EXPECTED), api=kernel.api())
            result = tracker.snapshot()
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['diagnostic']['operation'], operation)
            self.assertEqual(result['diagnostic']['winerror'], 777)
            tracker.close(); tracker.close()
            kernel.CloseHandle.assert_called_once_with(991)
            kernel.WaitForSingleObject.assert_not_called()

    def test_zero_seven_and_unsigned_nonzero_codes_do_not_classify_cause(self):
        tracker = self.capture()
        self.kernel.wait_value = process_exit.WAIT_OBJECT_0
        first = None
        for code in (0, 7, 0xC0000005, 0xFFFFFFFF):
            self.kernel.code = code
            result = tracker.snapshot()
            self.assertEqual(result['status'], 'exited')
            self.assertEqual(result['exitCode'], code)
            self.assertEqual(result['exitCodeHex'], f'0x{code:08X}')
            self.assertTrue(result['exitCodeAvailable'])
            self.assertNotIn('crash', json.dumps(result).lower())
            first = first or result['firstExitObservedAtUtc']
            self.assertEqual(result['firstExitObservedAtUtc'], first)
            self.assertTrue(result['handleRetained'])
        self.assertEqual(self.kernel.GetExitCodeProcess.call_count, 4)
        tracker.close()
        self.kernel.CloseHandle.assert_called_once_with(991)

    def test_exit_code_259_is_an_exit_only_when_wait_is_signaled(self):
        tracker = self.capture()
        self.kernel.code = 259
        running = tracker.snapshot()
        self.assertEqual(running['status'], 'running')
        self.assertIsNone(running['exitCode'])
        self.kernel.GetExitCodeProcess.assert_not_called()
        self.kernel.wait_value = process_exit.WAIT_OBJECT_0
        exited = tracker.snapshot()
        self.assertEqual((exited['status'], exited['exitCode'], exited['exitCodeHex']), ('exited', 259, '0x00000103'))

    def test_exit_observation_timestamp_follows_the_state_check(self):
        tracker = self.capture()
        def signaled(handle, timeout):
            self.tick = 500
            return process_exit.WAIT_OBJECT_0
        self.kernel.WaitForSingleObject.side_effect = signaled
        result = tracker.snapshot()
        self.assertEqual(result['status'], 'exited')
        self.assertEqual(result['observedAtUtc'], '2026-10-26T12:00:00.501Z')
        self.assertEqual(result['firstExitObservedAtUtc'], result['observedAtUtc'])

    def test_lost_exit_query_still_preserves_observed_termination(self):
        tracker = self.capture()
        self.kernel.wait_value = process_exit.WAIT_OBJECT_0
        self.kernel.fail.add('exit')
        result = tracker.snapshot()
        self.assertEqual(result['status'], 'exited')
        self.assertFalse(result['exitCodeAvailable'])
        self.assertIsNone(result['exitCode'])
        self.assertEqual(result['diagnostic']['operation'], 'GetExitCodeProcess')
        self.assertIsNotNone(result['firstExitObservedAtUtc'])
        self.assertTrue(result['handleRetained'])
        self.kernel.fail.remove('exit'); self.kernel.code = 7
        self.assertEqual(tracker.snapshot()['exitCode'], 7)
        self.kernel.OpenProcess.assert_called_once()

    def test_wait_failed_and_unexpected_wait_result_do_not_claim_exit(self):
        tracker = self.capture()
        self.kernel.wait_value = process_exit.WAIT_FAILED
        result = tracker.snapshot()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['diagnostic']['winerror'], 777)
        self.assertEqual(result['diagnostic']['operation'], 'WaitForSingleObject')
        self.kernel.GetExitCodeProcess.assert_not_called()
        self.kernel.wait_value = 0x80
        result = tracker.snapshot()
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['diagnostic']['reason'], 'unexpected-wait-result')

    def test_close_is_once_on_success_and_failure_and_snapshot_cannot_reopen(self):
        tracker = self.capture()
        self.kernel.fail.add('close')
        result = tracker.close()
        self.assertTrue(result['closed'])
        self.assertFalse(result['closeConfirmed'])
        self.assertEqual(result['diagnostic']['operation'], 'CloseHandle')
        self.assertEqual(tracker.close(), result)
        self.assertEqual(tracker.snapshot()['diagnostic']['reason'], 'handle-closed')
        self.kernel.CloseHandle.assert_called_once_with(991)
        self.kernel.WaitForSingleObject.assert_not_called()
        self.kernel.OpenProcess.assert_called_once()

    def test_context_manager_finally_preserves_owner_exception_and_closes(self):
        tracker = self.capture()
        with self.assertRaisesRegex(RuntimeError, 'owner failure'):
            with tracker:
                raise RuntimeError('owner failure')
        self.kernel.CloseHandle.assert_called_once_with(991)
        self.assertTrue(tracker.close()['closeConfirmed'])

    def test_invalid_identity_and_caller_mutation_cannot_retarget(self):
        for identity in ({}, dict(EXPECTED, pid=True), dict(EXPECTED, birth=0), dict(EXPECTED, path='relative.exe')):
            tracker = process_exit.capture(identity, api=self.api)
            self.assertEqual(tracker.snapshot()['status'], 'unavailable')
            tracker.close()
        self.kernel.OpenProcess.assert_not_called()
        expected = dict(EXPECTED)
        tracker = process_exit.capture(expected, api=self.api)
        expected['pid'] = 88
        self.assertEqual(tracker.snapshot()['expectedIdentity']['pid'], 771)
        tracker.close()


@unittest.skipUnless(os.name == 'nt', 'Benign retained-handle integration requires Windows')
class RealOwnedChildExitTests(unittest.TestCase):
    def observe_child(self, code):
        child = subprocess.Popen([sys.executable, '-B', '-c',
            'import sys; sys.stdin.buffer.read(1); sys.exit(int(sys.argv[1]))', str(code)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW)
        tracker = None
        try:
            # This handle belongs to the benign child just launched by this test.
            expected = process_exit._Win32().identity(child._handle)
            tracker = process_exit.capture(expected)
            self.assertEqual(tracker.snapshot()['status'], 'running')
            child.stdin.write(b'x'); child.stdin.flush(); child.stdin.close()
            self.assertEqual(child.wait(timeout=10), code)
            before = datetime.now(timezone.utc)
            result = tracker.snapshot()
            after = datetime.now(timezone.utc)
            self.assertEqual(result['status'], 'exited')
            self.assertEqual(result['exitCode'], code)
            self.assertEqual(result['exitCodeHex'], f'0x{code:08X}')
            self.assertEqual(result['identity'], expected)
            self.assertTrue(result['identityVerified'])
            observed = datetime.fromisoformat(result['observedAtUtc'].replace('Z', '+00:00'))
            # UTC observation is millisecond-rounded; permit one rounding millisecond.
            self.assertLessEqual(observed.timestamp(), after.timestamp())
            self.assertGreaterEqual(observed.timestamp() + .001, before.timestamp())
        finally:
            if tracker is not None: tracker.close()
            if child.stdin and not child.stdin.closed: child.stdin.close()  # EOF, never force-kill.
            child.wait(timeout=10)
    def test_real_owned_child_exit_zero(self): self.observe_child(0)
    def test_real_owned_child_exit_seven(self): self.observe_child(7)


if __name__ == '__main__': unittest.main()
