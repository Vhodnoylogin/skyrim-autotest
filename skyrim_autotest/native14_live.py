"""Opt-in native14 copied reads inside the current executor-owned VR session.

Inventory paths plus stable disk-file hashes do not attest loaded memory bytes.
No controller commands, launches, retries or subject verdicts are implemented.
"""
import copy
import hashlib
import math
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import time

from . import native14


class Native14LiveError(ValueError):
    """Owned identity, policy, freshness or observation coverage is unavailable."""


class Native14DurabilityError(Native14LiveError):
    """A failed native14 state commit could not be durably rolled back."""


_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,127}')
_PATH = re.compile(r'[A-Za-z_][A-Za-z_0-9]*(?:\.(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*')
_DLL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_. -]{0,250}\.dll', re.I)
_BASIS = 'loaded_module_path_inventory_and_stable_disk_image_sha256; not_in_memory_byte_attestation'


def _error(message):
    raise Native14LiveError(message)


def _basename(path):
    return ntpath.basename(path).lower()


def _path(path):
    if (type(path) is not str or not 1 <= len(path) <= 32767 or '\0' in path or
            not (Path(path).is_absolute() or PureWindowsPath(path).is_absolute())):
        _error('An explicit absolute module/process path is required')
    if PureWindowsPath(path).is_absolute():
        return ntpath.normcase(ntpath.normpath(path))
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def configuration(value):
    """Normalize an explicit DLL target policy without opening any target files."""
    if (type(value) is not dict or not {'maxAgeMicros', 'modules', 'absentModules'} <= set(value) or
            set(value) - {'maxAgeMicros', 'modules', 'absentModules', 'pollIntervalMs'}):
        _error('native14_live requires maxAgeMicros, modules and absentModules')
    age = value['maxAgeMicros']
    if type(age) is not int or not 0 < age <= native14.UINT64_MAX:
        _error('maxAgeMicros must be a positive uint64 integer')
    interval = value.get('pollIntervalMs', 50)
    if type(interval) is not int or not 5 <= interval <= 1000:
        _error('pollIntervalMs must be an integer within [5, 1000]')
    modules, absent = value['modules'], value['absentModules']
    if type(modules) is not list or not 2 <= len(modules) <= 19:
        _error('Two required DLLs and at most sixteen additional pinned DLLs are supported')
    if type(absent) is not list or len(absent) > 17:
        _error('Bounded explicit absent DLL basenames required')
    normalized, names, paths = [], set(), set()
    for item in modules:
        if type(item) is not dict or set(item) != {'path', 'sha256'}:
            _error('Each native14 module pin needs only path and sha256')
        path = _path(item['path'])
        name = _basename(path)
        if _DLL.fullmatch(name) is None or name in names or path in paths:
            _error('Duplicate or invalid pinned DLL basename/path')
        digest = item['sha256']
        if type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None:
            _error('A lowercase SHA256 is required for every pinned DLL')
        names.add(name)
        paths.add(path)
        normalized.append({'path': path, 'sha256': digest})
    absence = []
    for name in absent:
        if type(name) is not str or _DLL.fullmatch(name) is None or ntpath.basename(name) != name:
            _error('Absent modules must be DLL basenames, never paths')
        name = name.lower()
        if name in absence or name in names or name in ('devbench.dll', 'vrik.dll'):
            _error('Duplicate or conflicting required/absent DLL')
        absence.append(name)
    if not {'devbench.dll', 'vrik.dll'} <= names:
        _error('devbench.dll and VRIK.dll must both be pinned')
    if ('bodyslots.dll' in names) == ('bodyslots.dll' in absence):
        _error('BodySlots.dll must be pinned or explicitly absent')
    required_count = 3 if 'bodyslots.dll' in names else 2
    if len(names) - required_count > 16:
        _error('At most sixteen extra pinned modules are supported')
    return {'maxAgeMicros': age, 'pollIntervalMs': interval,
            'modules': sorted(normalized, key=lambda item: _basename(item['path'])),
            'absentModules': sorted(absence)}


def validate_request(args):
    """Return a normalized, bounded read request; names never select executable code."""
    if type(args) is not dict or not {'select'} <= set(args) or set(args) - {
            'select', 'tag', 'baseline', 'transition', 'haptics'}:
        _error('native14 read requires select and only optional tag/baseline/transition/haptics')
    selected = args['select']
    if type(selected) is not dict or not 1 <= len(selected) <= 64:
        _error('Between one and sixty-four measurement aliases are required')
    for alias, path in selected.items():
        if type(alias) is not str or len(alias) > 64 or _NAME.fullmatch(alias) is None:
            _error('Measurement alias must be a bounded safe name')
        if type(path) is not str or len(path) > 256 or _PATH.fullmatch(path) is None:
            _error('Measurement path must be a bounded dotted field selector')
    for key in ('tag', 'baseline'):
        if key in args and (type(args[key]) is not str or _NAME.fullmatch(args[key]) is None):
            _error('Snapshot tags/baselines must be bounded safe names')
    transition = args.get('transition', 'same-context')
    if transition not in ('same-context', 'new-load', 'new-body'):
        _error('Unsupported native14 context transition')
    haptics = args.get('haptics', False)
    if type(haptics) is not bool:
        _error('haptics must be boolean')
    if (transition != 'same-context' or haptics) and 'baseline' not in args:
        _error('Context changes and haptic intervals require a prior named baseline')
    return {**copy.deepcopy(args), 'transition': transition, 'haptics': haptics}


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('native14 owned-read deadline exhausted')
    return remaining


def _identity(value):
    if (type(value) is not dict or set(value) != {'pid', 'birth', 'path'} or
            type(value['pid']) is not int or not 0 < value['pid'] <= 0xffffffff or
            type(value['birth']) is not int or value['birth'] <= 0):
        _error('Exact PID, creation time and executable path are required')
    _path(value['path'])
    return value


def _owner(session, native, expected_game=None, expected_port=None):
    state = session.state
    if state.get('native14LiveCommitUncertain'):
        _error('Native14 durable commit uncertainty requires recovery/review; further reads refused')
    owner, game = _identity(state.get('runner')), _identity(state.get('game'))
    if native.identity(os.getpid()) != owner:
        _error('Current runner does not own this native14 session')
    if (state.get('done') is True or state.get('gameplayBootstrap', {}).get('completed') is not True or
            state.get('configuration', {}).get('game_edition') != 'vr'):
        _error('An unfinished bootstrapped owned VR session is required')
    if (_basename(game['path']) != 'skyrimvr.exe' or
            not any(type(item) is dict and item.get('identity') == game for item in state.get('owned', [])) or
            native.identity(game['pid']) != game):
        _error('Game identity is dead, changed or absent from owned processes')
    port = state.get('port')
    if type(port) is not int or not 1 <= port <= 65535:
        _error('Owned endpoint port is unavailable')
    if expected_game is not None and (game != expected_game or port != expected_port):
        _error('Owned game or endpoint changed during native14 read')
    return copy.deepcopy(game), port


def _health(session, runner, native, game, port, deadline):
    _remaining(deadline)
    _owner(session, native, game, port)
    health = runner.request(port, 'api/health', timeout=min(3, _remaining(deadline)))
    _remaining(deadline)
    if (type(health) is not dict or type(health.get('pid')) is not int or health['pid'] != game['pid'] or
            type(health.get('port')) is not int or health['port'] != port or health.get('vr') is not True or
            type(health.get('exe')) is not str or not 1 <= len(health['exe']) <= 32767 or
            _basename(health['exe']) != _basename(game['path'])):
        _error('DevBench health PID/port/executable/VR identity disagrees with the owned game')
    _owner(session, native, game, port)
    return copy.deepcopy(health)


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _hash_image(path, deadline):
    """Hash the enumerated file itself; never substitute a configured source path."""
    _remaining(deadline)
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > 512 * 1024 * 1024:
            _error('Enumerated module image is not a bounded regular disk file')
        while True:
            _remaining(deadline)
            block = stream.read(1024 * 1024)
            _remaining(deadline)
            if not block:
                break
            digest.update(block)
        after = os.fstat(stream.fileno())
        current = os.stat(path)
    _remaining(deadline)
    if _stamp(before) != _stamp(after) or _stamp(before) != _stamp(current):
        _error('Enumerated module disk image changed while hashing')
    return {'sha256': digest.hexdigest(), 'fileIdentity': {
        key: str(value) for key, value in zip(('device', 'inode', 'size', 'mtimeNs'), _stamp(before))}}


def _modules(native, game, policy, deadline):
    _remaining(deadline)
    inventory = native.modules(game)
    _remaining(deadline)
    if (type(inventory) is not list or not 1 <= len(inventory) <= 4096 or
            any(type(path) is not str for path in inventory) or sum(map(len, inventory)) > 1024 * 1024):
        _error('Loaded module inventory is unavailable or unbounded')
    actual, normalized, names = {}, [], set()
    for path in inventory:
        canonical = _path(path)
        name = _basename(path)
        names.add(name)
        normalized.append(canonical)
        actual.setdefault(name, []).append(path)
    if names.intersection(policy['absentModules']):
        _error('An explicitly absent module is loaded')
    images = []
    for pin in policy['modules']:
        name = _basename(pin['path'])
        if name in actual and len(actual[name]) != 1:
            _error('Pinned module inventory has ambiguous duplicate basenames or paths: ' + name)
        if name not in actual or _path(actual[name][0]) != pin['path']:
            _error('Pinned module is missing or its actual loaded path differs: ' + name)
        observed = _hash_image(actual[name][0], deadline)
        if observed['sha256'] != pin['sha256']:
            _error('Actual enumerated module disk-image SHA256 mismatch: ' + name)
        images.append({'basename': name, 'path': _path(actual[name][0]), **observed})
    return {'inventory': sorted(normalized), 'images': images}


def _ordering(current, previous):
    if (int(current['publications']) < int(previous['publications']) or
            int(current['copiedAtMicros']) < int(previous['copiedAtMicros'])):
        _error('Native14 publication/copy cursor regressed')


def _duplicate(current, previous):
    _ordering(current, previous)
    return current['frame']['token'] == previous['frame']['token']


def _pending(raw, pid):
    # This is a narrowly identified diagnostic outcome, not a partial gameplay
    # validation. Unknown schemas, foreign producers and host fallbacks never poll.
    recognized = (type(raw) is dict and set(raw) == {
        'schemaVersion', 'kind', 'processId', 'availability', 'sourcePhase', 'reason',
        'frame', 'haptics', 'publications', 'copiedAtMicros', 'observations'} and
        type(raw['schemaVersion']) is int and raw['schemaVersion'] == 1 and
        raw['kind'] == native14.KIND and type(raw['processId']) is int and raw['processId'] == pid and
        raw['availability'] == 'pending' and type(raw['sourcePhase']) is str and
        1 <= len(raw['sourcePhase']) <= 64 and type(raw['reason']) is str and 1 <= len(raw['reason']) <= 1024 and
        all(type(raw[key]) is dict for key in ('frame', 'haptics', 'observations')))
    if not recognized:
        return False
    # These shared validators check diagnostic metadata and independent recorded
    # history only. They do not make the pending frame's pose/policy fields valid.
    _metadata(raw)
    native14._token(raw['frame'].get('token'), 'pending.frame.token')
    for key in ('producerTimeMicros', 'ageMicros'):
        native14._uint64(raw['frame'].get(key), 'pending.frame.' + key)
    native14._history(raw['haptics'], int(raw['copiedAtMicros']))
    if raw['observations'] != {'scene': 'scene_graph_state', 'haptics': 'native_requests', 'actions': 'unobserved'}:
        _error('Pending native14 diagnostic claims are malformed or unsupported')
    return True


def _metadata(raw):
    values = []
    for key in ('publications', 'copiedAtMicros'):
        value = raw[key]
        if (type(value) is not str or len(value) > 20 or re.fullmatch(r'0|[1-9][0-9]*', value) is None or
                int(value) > native14.UINT64_MAX):
            _error('Pending/available publication metadata must be canonical uint64 strings')
        values.append(int(value))
    return tuple(values)


def _transition(current, previous, transition):
    _ordering(current, previous)
    now, old = current['frame']['token'], previous['frame']['token']
    load, body, frame = (int(now[key]) for key in ('loadGeneration', 'bodyGeneration', 'frameSerial'))
    old_load, old_body, old_frame = (int(old[key]) for key in ('loadGeneration', 'bodyGeneration', 'frameSerial'))
    if transition == 'same-context' and not (load == old_load and body == old_body and frame > old_frame):
        _error('Native14 frame did not advance in the same load/body context')
    if transition == 'new-load' and not (load > old_load and frame > old_frame):
        _error('Expected a newer native14 load and frame generation')
    if transition == 'new-body' and not (load == old_load and body > old_body and frame >= old_frame):
        _error('Expected a newer native14 body in the same load with nonbackward frame')


def execute(session, args, deadline):
    """Sample only copied reads within one deadline; commit only checked evidence."""
    from . import runner, native, platform
    raw = None
    try:
        if type(deadline) not in (int, float) or not math.isfinite(deadline):
            _error('One finite absolute monotonic deadline is required')
        _remaining(deadline)
        request = validate_request(args)
        policy = configuration(session.state.get('configuration', {}).get('native14_live'))
        game, port = _owner(session, native)
        original_live = copy.deepcopy(session.state.get('native14Live'))
        if original_live is not None and (type(original_live) is not dict or
                set(original_live) != {'game', 'cursor', 'tags'} or original_live['game'] != game or
                type(original_live['tags']) is not dict or len(original_live['tags']) > 128):
            _error('Native14 stream belongs to another game or is malformed; start a new owned session')
        tags = copy.deepcopy(original_live['tags']) if original_live else {}
        if 'tag' in request and (request['tag'] in tags or len(tags) >= 128):
            _error('Snapshot tag already exists or the 128-tag limit is reached')
        if 'baseline' in request and request['baseline'] not in tags:
            _error('Named native14 baseline is unavailable in this owned game')
        previous = (native14.validate(original_live['cursor'], expected_pid=game['pid'],
                                     max_age_micros=policy['maxAgeMicros']) if original_live else None)
        baseline = (native14.validate(tags[request['baseline']], expected_pid=game['pid'],
                                     max_age_micros=policy['maxAgeMicros']) if 'baseline' in request else None)
        backend = platform.Backend(session, deadline)
        backend.guard_world()
        _remaining(deadline)
        generation = session.state.get('ownedWorldGeneration')
        if type(generation) is not int or generation <= 0:
            _error('Owned world generation is unavailable')
        health_before = _health(session, runner, native, game, port, deadline)
        modules_before = _modules(native, game, policy, deadline)
        last_metadata = _metadata(previous) if previous is not None else None
        while True:
            _remaining(deadline)
            _owner(session, native, game, port)
            dispatch_time = time.monotonic()
            raw = session.tool('inspect', {'kind': native14.KIND},
                               timeout=min(12, _remaining(deadline)), deadline=deadline)
            session.log('native14-live-raw', raw=raw, game=game)
            _remaining(deadline)
            waiting = 'pending' if _pending(raw, game['pid']) else None
            if waiting is None:
                checked = native14.validate(raw, expected_pid=game['pid'], max_age_micros=policy['maxAgeMicros'])
                if previous is not None and _duplicate(checked, previous):
                    waiting = 'same-frame'
            metadata = _metadata(raw)
            if last_metadata is not None and any(now < old for now, old in zip(metadata, last_metadata)):
                _error('Native14 publication/copy metadata regressed during serial sampling')
            last_metadata = metadata
            if waiting is None:
                break
            session.log('native14-live-sampling', outcome=waiting, game=game)
            _owner(session, native, game, port)
            backend.guard_world()
            _remaining(deadline)
            if session.state.get('ownedWorldGeneration') != generation:
                _error('Owned world generation drifted during native14 sampling')
            time.sleep(min(policy['pollIntervalMs'] / 1000, _remaining(deadline)))
            _remaining(deadline)
        health_after = _health(session, runner, native, game, port, deadline)
        modules_after = _modules(native, game, policy, deadline)
        if modules_before['images'] != modules_after['images']:
            _error('Declared module inventory or disk-image identity changed during the read')
        backend.guard_world()
        _remaining(deadline)
        _owner(session, native, game, port)
        if session.state.get('ownedWorldGeneration') != generation:
            _error('Owned world generation drifted during native14 observation')
        if configuration(session.state['configuration']['native14_live']) != policy:
            _error('Native14 policy changed during observation')
        if previous is not None:
            _transition(checked, previous, request['transition'])
        if baseline is not None:
            _transition(checked, baseline, request['transition'])
        observations = {alias: native14.measurement(checked, path) for alias, path in request['select'].items()}
        haptics = native14.new_haptic_requests(checked, baseline=baseline) if request['haptics'] else None
        _remaining(deadline)
        elapsed = math.ceil(max(0, time.monotonic() - dispatch_time) * 1000000)
        age = int(checked['frame']['ageMicros']) + elapsed
        if age > policy['maxAgeMicros']:
            _error('Native14 conservative age including host read/postchecks exceeds policy')
        result = {'available': True, 'observations': observations,
                  'token': copy.deepcopy(checked['frame']['token']), 'publications': checked['publications'],
                  'game': game, 'worldGeneration': generation,
                  'moduleEvidence': {'basis': _BASIS, 'before': modules_before, 'after': modules_after,
                                     'absentModules': policy['absentModules']},
                  'healthEvidence': {'before': health_before, 'after': health_after},
                  'ageEvidence': {'producerAgeMicros': checked['frame']['ageMicros'],
                                  'hostElapsedMicros': elapsed, 'conservativeAgeMicros': age,
                                  'maximumAgeMicros': policy['maxAgeMicros']}}
        if haptics is not None:
            result['hapticRequests'] = haptics
        if 'tag' in request:
            tags[request['tag']] = copy.deepcopy(checked)
        _remaining(deadline)
        with session.lock:
            if session.state.get('native14Live') != original_live:
                _error('Native14 cursor changed concurrently')
            session.state['native14Live'] = {'game': game, 'cursor': checked, 'tags': tags}
            try:
                session.save()
                _remaining(deadline)
            except Exception as commit_error:
                if original_live is None:
                    session.state.pop('native14Live', None)
                else:
                    session.state['native14Live'] = original_live
                try:
                    # Rollback is restoration, permitted to finish after the read
                    # deadline. Preserve lifecycle invalidations/cursors and every
                    # other current safety field rather than restoring old state.
                    session.save()
                except Exception as rollback_error:
                    session.state['native14LiveCommitUncertain'] = {
                        'reason': 'Native14 cursor/tag rollback persistence failed',
                        'commitError': str(commit_error), 'rollbackError': str(rollback_error), 'game': game}
                    try:
                        session.save()
                    except Exception as marker_error:
                        session.state['native14LiveCommitUncertain']['markerPersistenceError'] = str(marker_error)
                    raise Native14DurabilityError(
                        'Native14 durable commit uncertainty: cursor/tag rollback could not be persisted; '
                        'further reads require recovery/review') from rollback_error
                raise
        return result
    except Exception as error:
        try:
            session.log('native14-live-error', error=str(error), request=args,
                        raw=raw if raw is not None else getattr(error, 'result', None))
        except Exception as log_error:
            error.add_note('Native14 error log could not be persisted: ' + str(log_error))
        raise
