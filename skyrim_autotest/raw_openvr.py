"""Read application-specific SteamVR state in a background client.

ABI checked against Valve openvr v1.26.7 headers/openvr_capi.h, IVRSystem_022.
No copied SDK is stored in Git. This never injects input or takes scene focus.
Background legacy bindings differ from the game's; this is not raw scene input.
"""
import ctypes as C
from pathlib import Path
from . import native


class Axis(C.Structure):
    _fields_ = [('x', C.c_float), ('y', C.c_float)]


class Controller(C.Structure):
    _fields_ = [('packet', C.c_uint32), ('pressed', C.c_uint64),
                ('touched', C.c_uint64), ('axes', Axis * 5)]


def observe(session):
    if not native.alive(session.state.get('game')):
        raise RuntimeError('Raw observation requires our live game session')
    dll = C.CDLL(str(Path(session.state['preflight']['runtime']) / 'bin/win64/openvr_api.dll'))
    dll.VR_InitInternal.argtypes = [C.POINTER(C.c_int), C.c_int]
    dll.VR_InitInternal.restype = C.c_size_t
    dll.VR_GetGenericInterface.argtypes = [C.c_char_p, C.POINTER(C.c_int)]
    dll.VR_GetGenericInterface.restype = C.c_void_p
    error = C.c_int()
    dll.VR_InitInternal(C.byref(error), 3)  # Background, not a scene application.
    if error.value:
        raise RuntimeError(f'OpenVR background init: {error.value}')
    try:
        address = dll.VR_GetGenericInterface(b'FnTable:IVRSystem_022', C.byref(error))
        if error.value or not address:
            raise RuntimeError(f'OpenVR IVRSystem_022: {error.value}')
        table = C.cast(address, C.POINTER(C.c_void_p))
        role_index = C.WINFUNCTYPE(C.c_uint32, C.c_int)(table[17])
        state = C.WINFUNCTYPE(C.c_bool, C.c_uint32, C.POINTER(Controller), C.c_uint32)(table[33])
        result = {}
        for role, code in [('left', 1), ('right', 2)]:
            index, controller = role_index(code), Controller()
            ok = state(index, C.byref(controller), C.sizeof(controller))
            result[role] = {'index': index, 'ok': ok, 'packet': controller.packet,
                            'pressed': controller.pressed, 'touched': controller.touched,
                            'axes': [[a.x, a.y] for a in controller.axes]}
        return result
    finally:
        dll.VR_ShutdownInternal()
