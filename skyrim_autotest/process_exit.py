"""Read-only exit telemetry for one identity-verified retained Windows handle.

capture(identity).snapshot() observes running/exited/unavailable. The observation
is not an exit cause or crash classification. Call close() in the owner's finally
block, or use the returned object as a context manager. No process is terminated.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from datetime import datetime, timezone
import ntpath
import os
from pathlib import Path, PureWindowsPath
import threading

SYNCHRONIZE = 0x00100000
QUERY_LIMITED_INFORMATION = 0x1000
ACCESS = SYNCHRONIZE | QUERY_LIMITED_INFORMATION
WAIT_OBJECT_0, WAIT_TIMEOUT, WAIT_FAILED = 0, 258, 0xFFFFFFFF


class _APIError(OSError):
    def __init__(self, operation, code):
        super().__init__(operation + ' unavailable')
        self.operation, self.winerror = operation, code


class _Win32:
    """Every identity component and observation uses the supplied process handle."""
    def __init__(self, kernel=None, last_error=None):
        if kernel is None:
            if os.name != 'nt': raise OSError('Windows process telemetry is unavailable')
            kernel = C.WinDLL('kernel32', use_last_error=True)
        self.k = kernel
        self.last_error = last_error or C.get_last_error
        signatures = {
            'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            'GetProcessId': ([W.HANDLE], W.DWORD),
            'GetProcessTimes': ([W.HANDLE] + [C.POINTER(W.FILETIME)] * 4, W.BOOL),
            'QueryFullProcessImageNameW': ([W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)], W.BOOL),
            'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
            'GetExitCodeProcess': ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
            'CloseHandle': ([W.HANDLE], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(kernel, name)
            function.argtypes, function.restype = args, result

    def _require(self, result, operation):
        if not result: raise _APIError(operation, self.last_error())
        return result

    def open(self, pid):
        return self._require(self.k.OpenProcess(ACCESS, False, pid), 'OpenProcess')

    def identity(self, handle):
        pid = int(self._require(self.k.GetProcessId(handle), 'GetProcessId'))
        times = [W.FILETIME() for _ in range(4)]
        self._require(self.k.GetProcessTimes(handle, *(C.byref(value) for value in times)), 'GetProcessTimes')
        path = C.create_unicode_buffer(32768)
        size = W.DWORD(len(path))
        self._require(self.k.QueryFullProcessImageNameW(handle, 0, path, C.byref(size)), 'QueryFullProcessImageNameW')
        return {'pid': pid, 'birth': (int(times[0].dwHighDateTime) << 32) | int(times[0].dwLowDateTime), 'path': path.value}

    def wait(self, handle):
        value = int(self.k.WaitForSingleObject(handle, 0))
        if value == WAIT_FAILED: raise _APIError('WaitForSingleObject', self.last_error())
        return value

    def exit_code(self, handle):
        code = W.DWORD()
        self._require(self.k.GetExitCodeProcess(handle, C.byref(code)), 'GetExitCodeProcess')
        return int(code.value) & 0xFFFFFFFF

    def close(self, handle):
        self._require(self.k.CloseHandle(handle), 'CloseHandle')


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'birth', 'path'} or
            type(value['pid']) is not int or not 0 < value['pid'] < 2**32 or
            type(value['birth']) is not int or not 0 < value['birth'] < 2**64 or
            not isinstance(value['path'], str) or not value['path'] or '\0' in value['path'] or
            not (PureWindowsPath(value['path']).is_absolute() or Path(value['path']).is_absolute())):
        raise ValueError('Exact PID/birth/absolute-path identity required')
    return dict(value)


def _diagnostic(operation, error):
    code = getattr(error, 'winerror', None)
    if type(code) is not int: code = getattr(error, 'errno', None)
    return {'operation': getattr(error, 'operation', operation), 'errorType': type(error).__name__,
            'winerror': code if type(code) is int else None}


class ProcessExitTelemetry:
    def __init__(self, identity, *, api=None, clock=None):
        self._lock, self._clock = threading.RLock(), clock or _utc
        self._api, self._handle, self._closed = api, None, False
        self.expected, self.verified, self.observed_identity = None, None, None
        self._failure, self._first_exit = None, None
        self._close_record = {'closed': False, 'closeAttempted': False, 'closeConfirmed': None, 'diagnostic': None}
        operation = 'validate-identity'
        try:
            self.expected = _identity(identity)
            operation = 'initialize-api'
            if self._api is None: self._api = _Win32()
            operation = 'OpenProcess'
            self._handle = self._api.open(self.expected['pid'])
            if not self._handle: raise _APIError('OpenProcess', 0)
            operation = 'same-handle-identity'
            actual = _identity(self._api.identity(self._handle))
            self.observed_identity = actual
            changed = [key for key in ('pid', 'birth') if actual[key] != self.expected[key]]
            if ntpath.normcase(ntpath.normpath(actual['path'])) != ntpath.normcase(ntpath.normpath(self.expected['path'])):
                changed.append('path')
            if changed:
                self._failure = {'operation': 'same-handle-identity', 'reason': 'identity-mismatch', 'fields': changed}
                self._release()
            else: self.verified = actual
        except Exception as error:
            self._failure = _diagnostic(operation, error)
            self._release()
        self.captured_at = self._clock()

    def _release(self):
        if not self._handle:
            self._handle = None
            return
        handle, self._handle = self._handle, None
        self._close_record.update(closeAttempted=True, closeConfirmed=False)
        try:
            self._api.close(handle)
            self._close_record.update(closeConfirmed=True)
        except Exception as error:
            self._close_record['diagnostic'] = _diagnostic('CloseHandle', error)

    def snapshot(self):
        with self._lock:
            result = {'schemaVersion': 1, 'status': 'unavailable', 'identityVerified': self.verified is not None,
                'identity': dict(self.verified) if self.verified else None,
                'expectedIdentity': dict(self.expected) if self.expected else None,
                'capturedAtUtc': self.captured_at, 'observedAtUtc': None,
                'firstExitObservedAtUtc': self._first_exit, 'exitCode': None, 'exitCodeHex': None,
                'exitCodeAvailable': False, 'handleRetained': self._handle is not None, 'diagnostic': None}
            if self._failure:
                result.update(diagnostic=dict(self._failure), observedIdentity=self.observed_identity)
                result['observedAtUtc'] = self._clock()
                return result
            if self._closed or self._handle is None:
                result['diagnostic'] = {'operation': 'snapshot', 'reason': 'handle-closed'}
                result['observedAtUtc'] = self._clock()
                return result
            try:
                state = self._api.wait(self._handle)
            except Exception as error:
                result['diagnostic'] = _diagnostic('WaitForSingleObject', error)
                result['observedAtUtc'] = self._clock()
                return result
            result['observedAtUtc'] = self._clock()
            if state == WAIT_TIMEOUT:
                result['status'] = 'running'
            elif state == WAIT_OBJECT_0:
                if self._first_exit is None: self._first_exit = result['observedAtUtc']
                result.update(status='exited', firstExitObservedAtUtc=self._first_exit)
                try:
                    code = int(self._api.exit_code(self._handle)) & 0xFFFFFFFF
                    result.update(exitCode=code, exitCodeHex=f'0x{code:08X}', exitCodeAvailable=True)
                except Exception as error:
                    result['diagnostic'] = _diagnostic('GetExitCodeProcess', error)
            else:
                result['diagnostic'] = {'operation': 'WaitForSingleObject', 'reason': 'unexpected-wait-result', 'waitResult': state}
            return result

    def close(self):
        """Retire the object and attempt CloseHandle once; failures are diagnostic."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._release()
                self._close_record['closed'] = True
            return {**self._close_record, 'diagnostic': dict(self._close_record['diagnostic']) if self._close_record['diagnostic'] else None}

    def __enter__(self): return self
    def __exit__(self, *_): self.close()


def capture(identity, *, api=None, clock=None):
    """Retain only a read/synchronize handle that matches this expected owner."""
    return ProcessExitTelemetry(identity, api=api, clock=clock)
