"""Windows process identities and the machine-wide Skyrim VR session mutex.

Uses only the Python standard library. A PID alone is never an ownership proof.
"""
import ctypes as C
from ctypes import wintypes as W
import os
import time


class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                ('th32DefaultHeapID', C.c_size_t), ('th32ModuleID', W.DWORD),
                ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD),
                ('pcPriClassBase', W.LONG), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]


class MODULEENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('th32ModuleID', W.DWORD), ('th32ProcessID', W.DWORD),
                ('GlblcntUsage', W.DWORD), ('ProccntUsage', W.DWORD), ('modBaseAddr', C.c_void_p),
                ('modBaseSize', W.DWORD), ('hModule', W.HMODULE), ('szModule', W.WCHAR * 256),
                ('szExePath', W.WCHAR * 260)]


if os.name == 'nt':
    K = C.WinDLL('kernel32', use_last_error=True)
    U = C.WinDLL('user32', use_last_error=True)
    K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
    K.OpenProcess.restype = W.HANDLE
    K.CloseHandle.argtypes = [W.HANDLE]
    K.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
    K.CreateToolhelp32Snapshot.restype = W.HANDLE
    K.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
    K.Process32NextW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
    K.GetProcessTimes.argtypes = [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4
    K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
    K.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
    K.CreateMutexW.argtypes = [C.c_void_p, W.BOOL, W.LPCWSTR]
    K.CreateMutexW.restype = W.HANDLE
    K.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    K.ReleaseMutex.argtypes = [W.HANDLE]
    U.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]


def identity(pid):
    h = K.OpenProcess(0x1000, False, int(pid))
    if not h:
        return None
    try:
        values = [W.FILETIME() for _ in range(4)]
        if not K.GetProcessTimes(h, *(C.byref(v) for v in values)):
            return None
        birth = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        path = C.create_unicode_buffer(32768)
        n = W.DWORD(len(path))
        if not K.QueryFullProcessImageNameW(h, 0, path, C.byref(n)):
            return None
        return {'pid': int(pid), 'birth': birth, 'path': path.value}
    finally:
        K.CloseHandle(h)


def alive(ident):
    return bool(ident and identity(ident['pid']) == {k: ident[k] for k in ('pid', 'birth', 'path')})


def focus_owned(ident, timeout=3):
    """Bounded foreground requests; observe success and never touch foreign queues."""
    import math
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError('Owned focus timeout must be finite within (0, 5]')
    if not alive(ident):
        raise RuntimeError('Cannot focus a process whose identity changed')
    U.GetForegroundWindow.restype = W.HWND
    U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    U.GetWindowThreadProcessId.restype = W.DWORD
    U.IsWindowVisible.argtypes = [W.HWND]
    U.ShowWindowAsync.argtypes = [W.HWND, C.c_int]
    U.SetForegroundWindow.argtypes = [W.HWND]
    U.AttachThreadInput.argtypes = [W.DWORD, W.DWORD, W.BOOL]
    U.PeekMessageW.argtypes = [C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT, W.UINT]
    U.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    U.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
    K.GetCurrentThreadId.restype = W.DWORD
    found = []
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def visit(hwnd, _):
        pid = W.DWORD()
        U.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value == ident['pid'] and U.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    callback = callback_type(visit)
    U.EnumWindows(callback, 0)
    if not found:
        return {'requested': False, 'focused': False, 'reason': 'no-owned-visible-window', 'attempts': 0}
    window = found[0]
    attachment = {'attempted': False, 'attached': False}
    windows = []
    for hwnd in found:
        title, classname = C.create_unicode_buffer(512), C.create_unicode_buffer(256)
        U.GetWindowTextW(hwnd, title, len(title))
        U.GetClassNameW(hwnd, classname, len(classname))
        windows.append({'hwnd': int(hwnd), 'title': title.value, 'class': classname.value})
    def result(**values):
        foreground = U.GetForegroundWindow()
        pid = W.DWORD()
        foreground_thread = U.GetWindowThreadProcessId(foreground, C.byref(pid)) if foreground else 0
        return {**values, 'ownedWindows': windows, 'targetWindow': int(window), 'foreground': {'hwnd': int(foreground or 0), 'pid': int(pid.value), 'thread': int(foreground_thread)}, 'attachment': dict(attachment)}
    started = time.monotonic()
    deadline = started + timeout
    requested, attempts, attached_attempted = False, 0, False
    def target_thread():
        if not alive(ident):
            return 0
        pid = W.DWORD()
        thread = U.GetWindowThreadProcessId(window, C.byref(pid))
        return thread if pid.value == ident['pid'] and U.IsWindowVisible(window) else 0
    def focused():
        pid = W.DWORD()
        U.GetWindowThreadProcessId(U.GetForegroundWindow(), C.byref(pid))
        return pid.value == ident['pid'] and alive(ident)
    while time.monotonic() < deadline:
        thread = target_thread()
        if not thread:
            return result(requested=requested, focused=False, reason='owned-window-identity-changed', attempts=attempts)
        if focused():
            return result(requested=requested, focused=True, attempts=attempts)
        # This API posts the restore request instead of waiting for a possibly
        # still-loading window. Foreground activation may also settle later.
        U.ShowWindowAsync(window, 9)
        requested = bool(U.SetForegroundWindow(window)) or requested
        attempts += 1
        if not attached_attempted and time.monotonic() - started >= .5:
            attached_attempted = True
            current = K.GetCurrentThreadId()
            # Only our own live game's input thread may be joined. Never attach
            # to the unrelated foreground application or inject keyboard events.
            if current != thread and target_thread() == thread:
                # Ensure the executor has its own message queue before attaching.
                message = W.MSG()
                U.PeekMessageW(C.byref(message), None, 0, 0, 0)
                attachment.update(attempted=True, executorThread=int(current), gameThread=int(thread))
                C.set_last_error(0)
                attached = bool(U.AttachThreadInput(current, thread, True))
                attachment.update(attached=attached, error=0 if attached else C.get_last_error())
                if attached:
                    try:
                        if target_thread() == thread:
                            requested = bool(U.SetForegroundWindow(window)) or requested
                            attempts += 1
                    finally:
                        C.set_last_error(0)
                        detached = bool(U.AttachThreadInput(current, thread, False))
                        attachment.update(detached=detached, detachError=0 if detached else C.get_last_error())
        if focused():
            return result(requested=requested, focused=True, attempts=attempts)
        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(.1, remaining))
    return result(requested=requested, focused=False, reason='foreground-request-deadline', attempts=attempts)


def processes():
    snap = K.CreateToolhelp32Snapshot(2, 0)
    if snap == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = C.sizeof(entry)
        ok = K.Process32FirstW(snap, C.byref(entry))
        while ok:
            out.append({'pid': entry.th32ProcessID, 'parent': entry.th32ParentProcessID,
                        'name': entry.szExeFile})
            ok = K.Process32NextW(snap, C.byref(entry))
    finally:
        K.CloseHandle(snap)
    return out


def close(ident):
    if not alive(ident):
        return
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    def callback(hwnd, _):
        pid = W.DWORD()
        U.GetWindowThreadProcessId(hwnd, C.byref(pid))
        if pid.value == ident['pid']:
            U.PostMessageW(hwnd, 0x10, 0, 0)
        return True
    U.EnumWindows.argtypes = [callback_type, W.LPARAM]
    U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    U.EnumWindows(callback_type(callback), 0)


def terminate(ident):
    if not alive(ident):
        return
    h = K.OpenProcess(0x1001, False, ident['pid'])
    if not h:
        raise C.WinError(C.get_last_error())
    try:
        # Recheck after acquiring the process handle; a reused PID cannot be killed.
        values = [W.FILETIME() for _ in range(4)]
        if not K.GetProcessTimes(h, *(C.byref(v) for v in values)):
            raise C.WinError(C.get_last_error())
        birth = (values[0].dwHighDateTime << 32) | values[0].dwLowDateTime
        if birth != ident['birth']:
            return
        if not K.TerminateProcess(h, 125):
            raise C.WinError(C.get_last_error())
    finally:
        K.CloseHandle(h)


class Busy(RuntimeError):
    pass


class SessionMutex:
    def __enter__(self):
        self.handle = K.CreateMutexW(None, False, 'Local\\SkyrimVRAutotestSession-v1')
        if not self.handle:
            raise C.WinError(C.get_last_error())
        result = K.WaitForSingleObject(self.handle, 0)
        if result not in (0, 0x80):
            K.CloseHandle(self.handle)
            raise Busy('Another test runner or recovery owns the Skyrim VR session')
        return self

    def __exit__(self, *args):
        K.ReleaseMutex(self.handle)
        K.CloseHandle(self.handle)
