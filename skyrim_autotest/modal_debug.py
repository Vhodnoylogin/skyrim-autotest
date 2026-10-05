"""Read-only diagnostic for the pinned Skyrim VR 1.4.15 message queue.

No memory writes, injection, callback invocation or arbitrary address interface.
Layout: CommonLibVR abe9ca7 / MessageBoxData and BSTArray; queue id519819 is
RVA3013ac8 in the installed VR Address Library. Never qualify another executable
by its filename alone. Pointer ids describe only the current process lifetime.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
import struct

ENGINE_SHA = '6961efb4f4775a307b0fc9a3d637542c1e090be207d3b09467eab216b7f87971'
QUEUE_RVA = 0x3013AC8


def decode_queue(read, address):
    def array(raw, maximum):
        pointer, capacity, _, count, _ = struct.unpack('<QIIII', raw)
        if count > capacity or capacity > 4096 or count > maximum or (count and pointer < 65536):
            raise ValueError('Unqualified message array layout')
        return pointer, count

    def string(raw):
        pointer, size, capacity, _ = struct.unpack('<QHHI', raw)
        if size > capacity or size > 8192 or (size and pointer < 65536):
            raise ValueError('Unqualified message string layout')
        if not size:
            return ''
        value = read(pointer, size + 1)
        if value[-1] != 0:
            raise ValueError('Message string is not terminated')
        return value[:-1].decode('utf-8')

    header = read(address, 24)
    pointer, count = array(header, 32)
    ids = read(pointer, count * 8) if count else b''
    queued = []
    for identity in struct.unpack('<' + 'Q' * count, ids):
        if identity < 65536:
            raise ValueError('Invalid message identity')
        data = read(identity, 80)
        buttons_pointer, buttons_count = array(data[32:56], 8)
        buttons = read(buttons_pointer, buttons_count * 16) if buttons_count else b''
        queued.append({'id': hex(identity), 'bodyText': string(data[16:32]),
                       'buttons': [string(buttons[i:i+16]) for i in range(0, len(buttons), 16)],
                       'cancelIndex': struct.unpack_from('<i', data, 60)[0],
                       'buttonPressOffset': data[76]})
    if read(address, 24) != header or (count and read(pointer, count * 8) != ids):
        raise ValueError('Message queue changed during diagnostic read')
    return {'available': True, 'depth': count, 'queued': queued, 'coherence': 'stable header and ids'}


def snapshot(ident):
    from . import native
    if not native.alive(ident) or os.path.basename(ident['path']).casefold() != 'skyrimvr.exe':
        raise ValueError('Message diagnostic requires the unchanged owned game')
    with open(ident['path'], 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != ENGINE_SHA:
            raise ValueError('Message queue diagnostic unavailable for this engine build')
    kernel = native.K
    kernel.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(native.MODULEENTRY32W)]
    kernel.Module32NextW.argtypes = [W.HANDLE, C.POINTER(native.MODULEENTRY32W)]
    kernel.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    modules = kernel.CreateToolhelp32Snapshot(0x18, ident['pid'])
    if modules == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    base = None
    try:
        entry = native.MODULEENTRY32W(); entry.dwSize = C.sizeof(entry)
        valid = kernel.Module32FirstW(modules, C.byref(entry))
        while valid:
            if os.path.normcase(entry.szExePath) == os.path.normcase(ident['path']):
                base = entry.modBaseAddr
                break
            valid = kernel.Module32NextW(modules, C.byref(entry))
    finally:
        kernel.CloseHandle(modules)
    if not base or not native.alive(ident):
        raise ValueError('Owned engine module unavailable')
    process = kernel.OpenProcess(0x10, False, ident['pid'])  # PROCESS_VM_READ only
    if not process:
        raise C.WinError(C.get_last_error())
    try:
        def read(address, size):
            if not 0 <= size <= 8193:
                raise ValueError('Diagnostic read exceeds bounds')
            buffer = C.create_string_buffer(size); count = C.c_size_t()
            if not kernel.ReadProcessMemory(process, address, buffer, size, C.byref(count)) or count.value != size:
                raise C.WinError(C.get_last_error())
            return buffer.raw
        value = decode_queue(read, base + QUEUE_RVA)
        if not native.alive(ident):
            raise ValueError('Owned engine identity changed during read')
        return {**value, 'engineSha256': ENGINE_SHA, 'queueRva': hex(QUEUE_RVA), 'diagnosticOnly': True}
    finally:
        kernel.CloseHandle(process)
