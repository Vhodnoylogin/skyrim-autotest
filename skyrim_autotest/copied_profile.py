"""Explicit composition reduction of a fresh owned disposable SE profile only."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import tempfile

from .profile_cache import regular_tree

FILES = ('modlist.txt', 'plugins.txt', 'loadorder.txt')


def _name(value, *, plugin=False):
    if (not isinstance(value, str) or not 1 <= len(value) <= 256 or value != value.strip()
            or value in ('.', '..') or value[0] in '+-*#;'
            or any(ord(c) < 32 or c in '<>:"/\\|?*' for c in value)
            or value.casefold().endswith('_separator')
            or plugin and re.search(r'\.(esm|esp|esl)$', value, re.I) is None):
        raise ValueError('Copied-profile policy requires exact names without paths, separators or control characters')
    return value


def validate(value):
    """Return the explicit policy; absent/null preserves the ordinary copied profile."""
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'enabledMods', 'enabledPlugins', 'reason'}:
        raise ValueError('Copied-profile policy requires enabledMods, enabledPlugins and reason')
    if (not isinstance(value['reason'], str) or not value['reason'].strip()
            or len(value['reason']) > 4096 or '\x00' in value['reason']):
        raise ValueError('Copied-profile policy requires a nonempty bounded reason')
    for field, plugin in (('enabledMods', False), ('enabledPlugins', True)):
        names = value[field]
        if not isinstance(names, list) or not 1 <= len(names) <= 256:
            raise ValueError('Copied-profile policy requires between1 and256 exact names per list')
        for name in names:
            _name(name, plugin=plugin)
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError('Copied-profile policy names must be unique ignoring case')
    return copy.deepcopy(value)


def _plain(path, *, directory=False):
    """Inspect lexical ancestors before resolve, so a junction cannot hide itself."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('Copied-profile paths must be absolute')
    for current in (path, *path.parents):
        if current.is_symlink() or (current.exists() and getattr(current.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('Copied-profile path contains a symlink or reparse point')
    if not (path.is_dir() if directory else path.is_file()):
        raise ValueError('Copied-profile path is missing or not a regular file/directory')
    return path.resolve()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _rows(data, *, mods):
    text = data.decode('utf-8-sig')
    rows = []
    seen = set()
    for line in text.splitlines(keepends=True):
        body = line.rstrip('\r\n')
        if not body.strip() or body.lstrip().startswith(('#', ';')):
            rows.append((line, None, None))
            continue
        if mods:
            if body[:1] not in ('+', '-', '*'):
                raise ValueError('Malformed copied/source modlist row')
            marker, name = body[0], body[1:]
            if marker == '*':
                # MO2's unmanaged game content is informational and cannot be
                # disabled through managed +/- mod rows. Keep it explicit.
                prefixes = ('DLC: ', 'Creation Club: ', 'Unmanaged: ')
                prefix = next((p for p in prefixes if name.startswith(p)), None)
                if prefix is None:
                    raise ValueError('Unknown unmanaged MO2 modlist row')
                _name(name[len(prefix):])
            elif name.casefold().endswith('_separator'):
                if not name or name != name.strip() or any(ord(c) < 32 or c in '/\\:' for c in name):
                    raise ValueError('Malformed mod separator')
            else:
                _name(name)
        else:
            marker, name = ('*', body[1:]) if body.startswith('*') else ('', body)
            _name(name, plugin=True)
        if name.casefold() in seen:
            raise ValueError('Duplicate copied/source profile row ignoring case')
        seen.add(name.casefold())
        rows.append((line, marker, name))
    return rows


def _encode(rows, original, desired, *, mods):
    lines = []
    for line, marker, name in rows:
        if name is None or mods and (marker == '*' or name.casefold().endswith('_separator')):
            lines.append(line)
        elif mods:
            lines.append(('+' if name in desired else '-') + line[1:])
        elif name in desired:
            lines.append(line)
    prefix = b'\xef\xbb\xbf' if original.startswith(b'\xef\xbb\xbf') else b''
    return prefix + ''.join(lines).encode('utf-8')


def _atomic(path, data):
    # Replace the directory entry: even a hard-linked copy cannot alter its source.
    descriptor, temporary = tempfile.mkstemp(prefix='.autotest-composition-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply(session, configuration):
    policy = validate(configuration.get('copied_profile_mods'))
    if policy is None:
        return None
    state = session.state
    if (configuration.get('game_edition') != 'se' or configuration.get('reuse_test_profile')
            or state.get('borrowedMO2') or state.get('reusableProfile')
            or state.get('game') or 'game' in state.get('launchIntents', {})
            or any(row.get('role') == 'game' for row in state.get('owned', []))
            or state.get('done') or state.get('restored') or state.get('copiedProfileMods')):
        raise ValueError('Copied-profile policy requires fresh owned SE preparation before game launch')
    profiles = _plain(configuration['profiles'], directory=True)
    target = _plain(state['testProfile'], directory=True)
    source_name = _name(state.get('preflight', {}).get('profile'))
    source = _plain(profiles / source_name, directory=True)
    expected = 'Autotest-' + str(state.get('id', ''))
    if (not state.get('id') or target.parent != profiles or source.parent != profiles
            or target == source or target.name != expected or state.get('testProfileName') != expected
            or target.name.startswith('Autotest-Reuse-')):
        raise ValueError('Copied-profile target must be this attempt\'s fresh Autotest profile, distinct from source')
    regular_tree(source)
    regular_tree(target)
    originals, source_bytes, outputs = {}, {}, {}
    for filename in FILES:
        original_path = _plain(source / filename)
        target_path = _plain(target / filename)
        source_bytes[filename] = original_path.read_bytes()
        originals[filename] = target_path.read_bytes()
        source_rows = _rows(source_bytes[filename], mods=filename == 'modlist.txt')
        copied_rows = _rows(originals[filename], mods=filename == 'modlist.txt')
        if filename == 'modlist.txt':
            enabled_source = {name for _, marker, name in source_rows
                              if marker == '+' and not name.casefold().endswith('_separator')}
            enabled_copy = {name for _, marker, name in copied_rows
                            if marker == '+' and not name.casefold().endswith('_separator')}
            desired = set(policy['enabledMods'])
            if not desired <= enabled_source or not desired <= enabled_copy:
                raise ValueError('Every chosen mod must already be enabled by its exact name in source and copy')
            if [name for _, _, name in copied_rows if name] != [name for _, _, name in source_rows if name]:
                raise ValueError('Copied modlist names/order differ from the actual source profile')
        else:
            desired = set(policy['enabledPlugins'])
            if [(marker, name) for _, marker, name in copied_rows if name] != [(marker, name) for _, marker, name in source_rows if name]:
                raise ValueError('Copied plugin names/order/markers differ from the actual source profile')
        outputs[filename] = _encode(copied_rows, originals[filename], desired, mods=filename == 'modlist.txt')
    record = {'status': 'preparing', 'policy': policy, 'profile': str(target), 'sourceProfile': str(source),
              'unmanagedEntries': [name for _, marker, name in _rows(outputs['modlist.txt'], mods=True) if marker == '*'],
              'scope': 'owned temporary copy only; original source profile and lifecycle inventory unchanged',
              'files': [{'path': str(target / name), 'beforeSha256': _hash(originals[name]),
                         'afterSha256': _hash(outputs[name]), 'sourcePath': str(source / name),
                         'sourceBeforeSha256': _hash(source_bytes[name])} for name in FILES]}
    state['copiedProfileMods'] = record
    session.save()
    session.log('copied-profile-mods-intent', **copy.deepcopy(record))
    for filename in FILES:
        _plain(target / filename)
        if (target / filename).read_bytes() != originals[filename]:
            raise ValueError('Copied profile changed during composition preparation')
        _atomic(target / filename, outputs[filename])
    for entry, filename in zip(record['files'], FILES):
        if _plain(source / filename).read_bytes() != source_bytes[filename]:
            raise ValueError('Original source profile changed during copied-profile preparation')
        if _plain(target / filename).read_bytes() != outputs[filename]:
            raise ValueError('Copied-profile composition readback differs')
        entry['sourceAfterSha256'] = _hash(source_bytes[filename])
    enabled = {name for _, marker, name in _rows(outputs['modlist.txt'], mods=True)
               if marker == '+' and not name.casefold().endswith('_separator')}
    if enabled != set(policy['enabledMods']):
        raise ValueError('Copied profile enabled-mod set does not equal the explicit policy')
    record['status'] = 'completed'
    record['sourceProfileUnchanged'] = True
    record['enabledMods'] = sorted(enabled)
    record['retainedPluginRows'] = {name: [plugin for _, _, plugin in _rows(outputs[name], mods=False) if plugin]
                                    for name in ('plugins.txt', 'loadorder.txt')}
    session.save()
    session.log('copied-profile-mods-prepared', **copy.deepcopy(record))
    return copy.deepcopy(record)
