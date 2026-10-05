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
HELPERS = (0xC4C340, 0xC5A380, 0xC5A650, 0x6CBCE0, 0x6A8E40)


def collect(session):
    from .runner import atomic_json
    value = snapshot(session.state['game'])
    evidence = session.dir / 'evidence' / 'pickup-engine-handlers.json'
    evidence.parent.mkdir(exist_ok=True)
    atomic_json(evidence, value)
    session.log('vanilla-pickup-handler-diagnostic', path=str(evidence),
                diagnosticOnly=True, acceptedAsInputProof=False)


def collect_runtime(session, phase):
    from .runner import atomic_json
    if phase not in ('held', 'released'):
        raise ValueError('Unknown fixed handler sampling phase')
    value = snapshot(session.state['game'], include_code=False)
    evidence = session.dir / 'evidence' / ('pickup-handler-'+phase+'.json')
    atomic_json(evidence, value)
    session.log('vanilla-pickup-runtime-handler-diagnostic', phase=phase,
                path=str(evidence), diagnosticOnly=True, acceptedAsInputProof=False)


def decode_runtime(read, base):
    def pointer(address):
        value=struct.unpack('<Q',read(address,8))[0]
        if not 0x10000 <= value < 0x800000000000:
            raise ValueError('Invalid owned engine runtime pointer')
        return value
    # Actual SKSEVR2.0.12 GameInput.cpp and GameInput.h: PlayerControls singleton,
    # inputHandlers[kInputHandler_Activate] at0x1A0. Exact vtable is mandatory.
    controls=pointer(base+0x2F8AAA8)
    handler=pointer(controls+0x1A0)
    if pointer(handler) != base+TABLES['ActivateHandler']:
        raise ValueError('ActivateHandler runtime table is not the qualified engine table')
    state=read(handler,0x70)
    player=pointer(base+0x2FEB9F0)
    picker=pointer(base+0x2FC60C0)
    vr=pointer(base+0x2FEB9B0)
    table=pointer(vr)
    if not base+0x1600000 <= table < base+0x2000000:
        raise ValueError('VR routing table outside qualified engine')
    route=pointer(table+0x78)
    if not base+0x1000 <= route <= base+0x1600000-4096:
        raise ValueError('VR routing method outside qualified engine')
    code=read(route,4096)
    return {'handlerRawHex':state.hex(), 'handlerRawSha256':hashlib.sha256(state).hexdigest(),
            'handlerFlags':{hex(i):state[i] for i in (8,0x60,0x61,0x62,0x63)},
            'targetHandles':list(struct.unpack('<3I',read(picker+4,12))),
            'playerDominantControllerRaw':struct.unpack('<I',read(player+0x6D4,4))[0],
            'playerVRGrabStateRaw':[struct.unpack('<I',read(player+0xED0+i*0x68,4))[0] for i in (0,1)],
            'activationBothWandsRaw':read(base+0x1EC59C0,1)[0],
            'routingCode':{'rva':hex(route-base),'bytesHex':code.hex(),
                           'sha256':hashlib.sha256(code).hexdigest()},
            'atomicWorldSample':False,'domain':'bounded read-only raw runtime diagnostic, not gameplay proof'}


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


def snapshot(ident, include_code=True):
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
            if not 0x10000 <= address < address+size < 0x800000000000 or not 0 < size <= 4096:
                raise ValueError('Handler diagnostic read exceeds bounded user memory')
            buffer=C.create_string_buffer(size); count=C.c_size_t()
            if not kernel.ReadProcessMemory(process,address,buffer,size,C.byref(count)) or count.value!=size:
                raise C.WinError(C.get_last_error())
            return buffer.raw
        value=decode_handlers(read,base) if include_code else {'diagnosticOnly':True,'available':True}
        value['runtime']=decode_runtime(read,base)
        if not native.alive(ident):
            raise ValueError('Owned engine identity changed during read')
        return {**value,'engineSha256':ENGINE_SHA}
    finally:
        kernel.CloseHandle(process)
