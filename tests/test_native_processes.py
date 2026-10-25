"""Toolhelp enumeration failure boundaries with a fake Win32 API only."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import native


class ProcessEnumerationTests(unittest.TestCase):
    def setUp(self):
        self.error = 777
        self.index = 0
        self.first_error = None
        self.next_error = None
        self.invalid_snapshot = False
        self.errors_at_call = []
        self.rows = [{'pid': 4, 'parent': 0, 'name': 'System'},
                     {'pid': 77, 'parent': 4, 'name': 'python.exe'}]
        self.api = SimpleNamespace(CreateToolhelp32Snapshot=Mock(side_effect=self.snapshot),
                Process32FirstW=Mock(side_effect=self.first), Process32NextW=Mock(side_effect=self.next),
                CloseHandle=Mock())
        for item in (patch.object(native, 'K', self.api, create=True),
                     patch.object(native.C, 'get_last_error', side_effect=lambda: self.error, create=True),
                     patch.object(native.C, 'set_last_error', side_effect=lambda value: setattr(self, 'error', value), create=True),
                     patch.object(native.C, 'WinError', side_effect=lambda code: OSError(code, 'synthetic Win32 failure'), create=True)):
            item.start()
            self.addCleanup(item.stop)

    def snapshot(self, flags, pid):
        self.assertEqual((flags, pid), (2, 0))
        if self.invalid_snapshot:
            self.error = 5
            return native.C.c_void_p(-1).value
        return 123

    def fill(self, pointer):
        row = self.rows[self.index]
        entry = pointer._obj
        entry.th32ProcessID = row['pid']
        entry.th32ParentProcessID = row['parent']
        entry.szExeFile = row['name']

    def first(self, snapshot, pointer):
        self.errors_at_call.append(self.error)
        self.index = 0
        if self.first_error is not None:
            self.error = self.first_error
            return False
        self.fill(pointer)
        return True

    def next(self, snapshot, pointer):
        self.errors_at_call.append(self.error)
        if self.next_error is not None:
            self.error = self.next_error
            return False
        self.index += 1
        if self.index == len(self.rows):
            self.error = 18  # ERROR_NO_MORE_FILES: successful complete end.
            return False
        self.fill(pointer)
        return True

    def test_complete_inventory_requires_normal_end_and_closes_snapshot(self):
        self.assertEqual(native.processes(), self.rows)
        self.assertEqual(self.errors_at_call, [0, 0, 0])
        self.api.CloseHandle.assert_called_once_with(123)

    def test_first_failure_never_returns_empty_success_and_closes_snapshot(self):
        for error in (0, 5, 18):
            with self.subTest(error=error):
                self.first_error = error
                self.api.CloseHandle.reset_mock()
                with self.assertRaises(OSError):
                    native.processes()
                self.api.Process32NextW.assert_not_called()
                self.api.CloseHandle.assert_called_once_with(123)

    def test_unexpected_next_error_never_returns_partial_inventory(self):
        for error in (0, 5, 24):
            with self.subTest(error=error):
                self.next_error = error
                self.api.CloseHandle.reset_mock()
                with self.assertRaises(OSError):
                    native.processes()
                self.api.CloseHandle.assert_called_once_with(123)

    def test_invalid_snapshot_is_not_enumerated_or_closed_as_owned_handle(self):
        self.invalid_snapshot = True
        with self.assertRaises(OSError):
            native.processes()
        self.api.Process32FirstW.assert_not_called()
        self.api.CloseHandle.assert_not_called()

    def test_exception_mid_enumeration_still_closes_snapshot(self):
        self.api.Process32NextW.side_effect = RuntimeError('enumeration interrupted')
        with self.assertRaisesRegex(RuntimeError, 'enumeration interrupted'):
            native.processes()
        self.api.CloseHandle.assert_called_once_with(123)


if __name__ == '__main__':
    unittest.main()
