"""Read-only identity of a record in one active, full ESP or ESM."""

import re


def _typed_game_return(call, function, arguments, expected):
    reply = call(function, arguments)
    kind = reply.get('returnedType') if isinstance(reply, dict) else None
    if (type(kind) is not str or kind.casefold() != expected or reply.get('called') is not True
            or 'returned' not in reply or reply.get('error') or reply.get('isError')):
        raise ValueError(f'Typed Game.{function} completion unavailable')
    return reply['returned']


def full_form_local_id(plugin, local_id):
    if (type(plugin) is not str or not 5 <= len(plugin) <= 255 or not plugin.isascii() or plugin != plugin.strip()
            or not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f\x7f]+\.(esp|esm)', plugin, re.I)
            or type(local_id) is not str or not re.fullmatch(r'[0-9A-Fa-f]{1,6}', local_id)):
        raise ValueError('Full form identity requires an ASCII ESP/ESM filename and a 24-bit local hex ID')
    return int(local_id, 16)


def resolve_full_plugin_form(call, plugin, local_id):
    """Read three typed Game replies via call(function, args), in one caller deadline."""
    local = full_form_local_id(plugin, local_id)
    index = _typed_game_return(call, 'GetModByName', [plugin], 'int')
    if type(index) is not int or not 0 <= index <= 0xFD:
        raise ValueError('Active full plugin load index unavailable')
    indexed_name = _typed_game_return(call, 'GetModName', [index], 'string')
    if (type(indexed_name) is not str or not indexed_name.isascii()
            or indexed_name.casefold() != plugin.casefold()):
        raise ValueError('Indexed plugin filename differs from the requested full plugin')
    record = _typed_game_return(call, 'GetFormFromFile', [local, plugin], 'form')
    runtime_id = record.get('formId') if isinstance(record, dict) else None
    if not isinstance(runtime_id, str) or not re.fullmatch(r'0[xX][0-9A-Fa-f]{8}', runtime_id):
        raise ValueError('Native full record FormID unavailable')
    runtime = int(runtime_id, 16)
    if runtime == 0 or runtime != ((index << 24) | local):
        raise ValueError('Native FormID differs from the indexed plugin or requested local record')
    return {'plugin': indexed_name, 'loadIndex': index, 'localId': f'{runtime & 0xFFFFFF:06X}',
            'runtimeId': f'0x{runtime:08X}'}
