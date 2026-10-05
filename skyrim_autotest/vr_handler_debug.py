"""Bounded read-only diagnostics of this exact owned VR engine's input handlers.

No arbitrary address interface, memory writes, hooks or callback invocation.
The raw snapshot is for offline source analysis, never input-consumption proof.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import os
import struct

from .modal_debug import ENGINE_SHA

TABLES = {'TeleportHandler': 0x16F20B0, 'ActivateHandler': 0x16F22E8}
# Fixed callees observed in the exact engine's captured ActivateHandler. These
# bounded reads explain routing/zones; they never call or modify engine code.
HELPERS = (0xC4C340, 0xC5A380, 0xC5A650, 0x6CBCE0)


def collect(session):
    from .runner import atomic_json
    value = snapshot(session.state['game'])
    evidence = session.dir / 'evidence' / 'pickup-engine-handlers.json'
    evidence.parent.mkdir(exist_ok=True)
    atomic_json(evidence, value)
    session.log('vanilla-pickup-handler-diagnostic', path=str(evidence),
                diagnosticOnly=True, acceptedAsInputProof=False)


def decode_handlers(read, base):
    handlers = {}
    code = {}
    for name, rva in TABLES.items():
        table = read(base+rva, 56)
        addresses = struct.unpack('<7Q', table)
        for address in addresses:
            relative = address-base
            if not 0x1000 <= relative <= 0x1600000-4096:
                raise ValueError('Handler pointer outside qualified engine code range')
            if relative not in code:
                data = read(address, 4096)
                code[relative] = {'rva': hex(relative), 'bytesHex': data.hex(),
                                  'sha256': hashlib.sha256(data).hexdigest()}
        if read(base+rva, 56) != table:
            raise ValueError('Handler table changed during diagnostic read')
        handlers[name] = {'tableRva': hex(rva), 'slots': [hex(a-base) for a in addresses]}
    for relative in HELPERS:
        data = read(base+relative, 4096)
        code[relative] = {'rva': hex(relative), 'bytesHex': data.hex(),
                          'sha256': hashlib.sha256(data).hexdigest()}
    return {'handlers': handlers, 'code': list(code.values()),
            'available': True, 'diagnosticOnly': True,
            'domain': 'owned engine code snapshot; no handler invocation or consumption proof'}


def snapshot(ident):
    from . import native
    if not native.alive(ident) or os.path.basename(ident['path']).casefold() != 'skyrimvr.exe':
        raise ValueError('Handler diagnostic requires unchanged owned game')
    with open(ident['path'], 'rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != ENGINE_SHA:
            raise ValueError('Handler diagnostic unavailable for this engine build')
    kernel = native.K
    kernel.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(native.MODULEENTRY32W)]
    kernel.Module32NextW.argtypes = [W.HANDLE, C.POINTER(native.MODULEENTRY32W)]
    kernel.ReadProcessMemory.argtypes = [W.HANDLE,C.c_void_p,C.c_void_p,C.c_size_t,C.POINTER(C.c_size_t)]
    modules = kernel.CreateToolhelp32Snapshot(0x18, ident['pid'])
    if modules == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    base = None
    try:
        entry=native.MODULEENTRY32W(); entry.dwSize=C.sizeof(entry)
        valid=kernel.Module32FirstW(modules,C.byref(entry))
        while valid:
            if os.path.normcase(entry.szExePath)==os.path.normcase(ident['path']):
                base=entry.modBaseAddr
                break
            valid=kernel.Module32NextW(modules,C.byref(entry))
    finally:
        kernel.CloseHandle(modules)
    if not base or not native.alive(ident):
        raise ValueError('Owned engine module unavailable')
    process=kernel.OpenProcess(0x10,False,ident['pid'])
    if not process:
        raise C.WinError(C.get_last_error())
    try:
        def read(address,size):
            if not base <= address or address+size > base+0x2200000 or not 0 < size <= 4096:
                raise ValueError('Handler diagnostic read exceeds engine bounds')
            buffer=C.create_string_buffer(size); count=C.c_size_t()
            if not kernel.ReadProcessMemory(process,address,buffer,size,C.byref(count)) or count.value!=size:
                raise C.WinError(C.get_last_error())
            return buffer.raw
        value=decode_handlers(read,base)
        if not native.alive(ident):
            raise ValueError('Owned engine identity changed during read')
        return {**value,'engineSha256':ENGINE_SHA}
    finally:
        kernel.CloseHandle(process)
