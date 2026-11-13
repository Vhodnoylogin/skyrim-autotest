"""Opt-in CDB second-chance evidence for one already owned SE process.

This module neither launches a game nor changes its exception handling. The
runner calls start after launch, before NEW, and stop after the game has ended.
"""
import copy
import hashlib
import math
import os
from pathlib import Path
import re
import subprocess
import time

from . import native


READY = b'AUTOTEST_CRASH_CAPTURE_READY'
SUPPORT = {'dbgeng.dll', 'dbghelp.dll', 'dbgcore.dll', 'symsrv.dll'}


def _path(value):
    if (not isinstance(value, str) or not value or any(ord(c) < 32 for c in value)
            or not Path(value).is_absolute() or value.startswith(('\\\\', '//'))):
        raise ValueError('Crash capture requires an absolute local file path')
    return Path(value)


def _sha(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-fA-F]{64}', value):
        raise ValueError('Crash capture requires exact SHA-256 pins')


def validate_config(value):
    """Validate the optional object, without acquiring tools or starting anything."""
    if value is None:
        return None
    fields = {'provider', 'executable', 'sha256', 'supportFiles', 'maximumAttachSeconds'}
    if not isinstance(value, dict) or set(value) != fields or value['provider'] != 'cdb':
        raise ValueError('Unsupported crash_capture configuration')
    executable = _path(value['executable'])
    if executable.name.lower() != 'cdb.exe':
        raise ValueError('Crash capture requires the explicitly pinned cdb.exe')
    _sha(value['sha256'])
    seconds = value['maximumAttachSeconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 15:
        raise ValueError('Crash capture attach bound must be within (0, 15] seconds')
    rows = value['supportFiles']
    if not isinstance(rows, list) or not 2 <= len(rows) <= len(SUPPORT):
        raise ValueError('Pin the CDB support DLLs beside the executable')
    names = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'sha256'}:
            raise ValueError('Invalid crash capture support pin')
        path = _path(row['path'])
        name = path.name.lower()
        if name not in SUPPORT or name in names or path.parent.resolve() != executable.parent.resolve():
            raise ValueError('CDB support files must be unique known DLLs beside cdb.exe')
        _sha(row['sha256'])
        names.add(name)
    if not {'dbgeng.dll', 'dbghelp.dll'} <= names:
        raise ValueError('Both dbgeng.dll and dbghelp.dll must be pinned')
    return copy.deepcopy(value)


def _pin(path):
    path = Path(path)
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': size}


def _verify_tools(config):
    rows = [{'path': config['executable'], 'sha256': config['sha256']}, *config['supportFiles']]
    pins = []
    for row in rows:
        path = Path(row['path'])
        if not path.is_file() or path.is_symlink():
            raise RuntimeError('Crash capture tool is unavailable or is a symbolic link')
        actual = _pin(path)
        if actual['sha256'] != row['sha256'].lower():
            raise RuntimeError('Crash capture tool pin changed')
        pins.append(actual)
    return pins


def _script():
    # No caller text enters this program. Relative output stays in the fresh cwd.
    fatal = ('.echo AUTOTEST_SECOND_CHANCE; .exr -1; .ecxr; r; kv 40; '
             '.dump /mA second-chance.dmp; .echo AUTOTEST_CAPTURE_COMMANDS_FINISHED; gn')
    return ('sxd -c "" -c2 "' + fatal + '" av\n'
            'sxd -c "" -c2 "' + fatal + '" 0xe06d7363\n'
            'sxd -c "" -c2 "' + fatal + '" *\n'
            # The built-in stack-buffer-overrun filter takes precedence over
            # wildcard commands. __fastfail reports C0000409 on second chance.
            'sxd -c "" -c2 "' + fatal + '" sbo\n'
            'sx\n.echo AUTOTEST_CRASH_CAPTURE_READY\ng\n')


def _save(session, **values):
    session.state['crashCapture'].update(values)
    session.save()


def _remaining(end):
    remaining = end - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Crash capture attach/readiness bound expired; no reattach')
    return remaining


def _same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def _game(session, expected):
    if (session.state.get('game') != expected or native.identity(expected['pid']) != expected
            or not any(row.get('role') == 'game' and row.get('identity') == expected
                       for row in session.state.get('owned', []))):
        raise RuntimeError('Crash capture requires the exact already owned game identity')


def _debugger(expected, process):
    if process.poll() is not None or native.identity(expected['pid']) != expected:
        raise RuntimeError('Owned crash capture debugger stopped or changed identity')


def _health(session, game, end):
    from .runner import request
    value = request(session.state['port'], 'api/health', timeout=min(3, _remaining(end)))
    if (not isinstance(value, dict) or value.get('ok') is not True or value.get('pid') != game['pid']
            or value.get('exe') != Path(game['path']).name or value.get('vr') is not False
            or type(value.get('frame')) is not int or value['frame'] < 0):
        raise RuntimeError('Fresh DevBench health does not identify the owned SE game')
    return value


def start(session):
    """Attach once to an owned SE game. Any unknown result is terminal for start."""
    config = validate_config(session.state.get('configuration', {}).get('crash_capture'))
    if config is None:
        return None
    if session.state.get('configuration', {}).get('game_edition') != 'se':
        raise ValueError('Crash capture is supported only for explicit SE configuration')
    if 'crashCapture' in session.state:
        raise RuntimeError('Crash capture intent already exists; no reattach or replay')
    pins = _verify_tools(config)
    game = copy.deepcopy(session.state.get('game'))
    if not isinstance(game, dict) or set(game) != {'pid', 'birth', 'path'}:
        raise RuntimeError('Crash capture has no exact owned game identity')
    _game(session, game)
    seconds = config['maximumAttachSeconds']
    if 'deadline' in session.state:
        seconds = min(seconds, session.state['deadline'] - time.time())
    if seconds <= 0:
        raise TimeoutError('No remaining native deadline for crash capture')
    end = time.monotonic() + seconds
    directory = Path(session.dir).resolve() / 'crash-capture'
    directory.mkdir(exist_ok=False)
    command = directory / 'capture.cdb'
    command.write_text(_script(), encoding='ascii', newline='\n')
    argv = [config['executable'], '-pd', '-G', '-sins', '-netsyms:no', '-noshell', '-nosqm',
            '-y', str(directory), '-logo', 'debugger.log', '-cf', 'capture.cdb', '-p', str(game['pid'])]
    session.state['crashCapture'] = {'schemaVersion': 1, 'provider': 'cdb', 'status': 'attach-intent',
        'target': game, 'directory': str(directory), 'toolPins': pins, 'script': _pin(command),
        'argv': argv, 'attachRequests': 1, 'startedAt': time.time(), 'ready': False,
        'exceptionPolicy': 'second-chance capture then gn; first-chance AV is not handled',
        'artifacts': []}
    session.save()  # Durable intent precedes the only spawn/attach.
    session.log('crash-capture-intent', capture=copy.deepcopy(session.state['crashCapture']))
    process = None
    try:
        _game(session, game)
        _verify_tools(config)
        env = {k: v for k, v in os.environ.items() if k.upper() not in
               {'_NT_SYMBOL_PATH', '_NT_ALT_SYMBOL_PATH', '_NT_SOURCE_PATH', '_NT_EXECUTABLE_IMAGE_PATH'}}
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        with (directory / 'debugger-output.log').open('xb') as output:
            process = subprocess.Popen(argv, cwd=directory, env=env, stdin=subprocess.DEVNULL,
                stdout=output, stderr=subprocess.STDOUT, creationflags=flags, shell=False)
        session._crash_capture_process = process
        _save(session, status='attaching', debuggerPid=process.pid)
        while True:
            _remaining(end)
            if process.poll() is not None:
                raise RuntimeError('Crash capture debugger exited before owned identity/readiness')
            actual = native.identity(process.pid)
            if actual is not None:
                if not _same_path(actual['path'], config['executable']):
                    raise RuntimeError('Crash capture debugger executable identity mismatch')
                break
            time.sleep(min(.05, _remaining(end)))
        debugger = copy.deepcopy(actual)
        _debugger(debugger, process)
        if any(row.get('role') == 'crash-capture' or row.get('identity', {}).get('pid') == debugger['pid']
               for row in session.state.get('owned', [])):
            raise RuntimeError('Crash capture debugger has duplicate process ownership')
        session.state['owned'].append({'role': 'crash-capture', 'identity': debugger})
        _save(session, debugger=debugger)
        while True:
            _remaining(end)
            _game(session, game)
            _debugger(debugger, process)
            log = directory / 'debugger.log'
            if log.exists() and READY in log.read_bytes():
                break
            time.sleep(min(.05, _remaining(end)))
        health = _health(session, game, end)
        _game(session, game)
        _debugger(debugger, process)
        _remaining(end)
        _save(session, status='ready', ready=True, readyAt=time.time(), health=health,
              readinessBasis='fixed script marker, exact debugger/game identities and fresh DevBench health')
        session.log('crash-capture-ready', debugger=debugger, target=game, health=health)
        return copy.deepcopy(session.state['crashCapture'])
    except BaseException as error:
        _save(session, status='attach-failed', ready=False, errorType=type(error).__name__)
        session.log('crash-capture-unavailable', errorType=type(error).__name__, noReattach=True)
        raise


def _ended(identity):
    observed = native.identity(identity['pid'])
    if observed == identity:
        return False
    if observed is not None:
        return True  # A reused PID belongs to a different process; never touch it.
    rows = native.processes()
    if (not isinstance(rows, list) or not rows or any(not isinstance(row, dict)
            or type(row.get('pid')) is not int or row['pid'] < 0
            or not isinstance(row.get('name'), str) or not row['name']
            or type(row.get('parent')) is not int or row['parent'] < 0 for row in rows)):
        raise RuntimeError('Complete process inventory unavailable; death is unproven')
    return not any(row['pid'] == identity['pid'] for row in rows)


def stop(session):
    """After game death, collect logs/dump and close only this exact debugger."""
    capture = session.state.get('crashCapture')
    if capture is None:
        return None
    if capture.get('status') == 'stopped':
        return copy.deepcopy(capture)
    if not _ended(capture['target']):
        raise RuntimeError('Crash capture stop requires confirmed owned game end')
    debugger = capture.get('debugger')
    process = getattr(session, '_crash_capture_process', None)
    end = time.monotonic() + 2
    forced = False
    if debugger is None and capture.get('debuggerPid'):
        raise RuntimeError('Crash capture debugger ownership unavailable; no process action')
    if debugger is not None:
        while time.monotonic() < end and not _ended(debugger):
            time.sleep(.05)
        if not _ended(debugger):
            if native.identity(debugger['pid']) != debugger:
                raise RuntimeError('Crash capture debugger ownership changed; no process action')
            native.terminate(debugger)  # -pd: debugger exit must never terminate its target.
            forced = True
            end = time.monotonic() + 2
            while time.monotonic() < end and not _ended(debugger):
                time.sleep(.05)
        if not _ended(debugger):
            raise RuntimeError('Exact owned crash capture debugger did not stop')
    exit_code = process.poll() if process is not None else None
    artifacts = [_pin(path) for path in sorted(Path(capture['directory']).iterdir())
                 if path.is_file() and not path.is_symlink()]
    _save(session, status='stopped', ready=False, stoppedAt=time.time(), debuggerExitCode=exit_code,
          debuggerForcedStop=forced, artifacts=artifacts,
          dumpObserved=any(Path(row['path']).suffix.lower() == '.dmp' for row in artifacts))
    session._crash_capture_process = None
    session.log('crash-capture-stopped', capture=copy.deepcopy(session.state['crashCapture']))
    return copy.deepcopy(session.state['crashCapture'])
