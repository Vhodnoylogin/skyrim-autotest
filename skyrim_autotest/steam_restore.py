"""Opt-in graceful client restart for our staged driver, never process ownership.

Steam can retain a loaded driver after the owned VR processes have stopped.
Only its exact preflight client may receive one ordinary shutdown request.
"""
import hashlib
from pathlib import Path
import subprocess
import time
from . import native

HELPERS = {'steamwebhelper.exe', 'steamerrorreporter.exe', 'steamerrorreporter64.exe'}
VR_GAME_NAMES = {'skyrimvr.exe', 'sksevr_loader.exe', 'vrserver.exe', 'vrmonitor.exe',
                 'vrcompositor.exe', 'vrstartup.exe', 'vrdashboard.exe', 'vrwebhelper.exe', 'vrprismhost.exe'}


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def running_apps():
    """Steam's current-user running-app hints supplement process ancestry."""
    import winreg
    out = []
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam\Apps') as key:
        for i in range(winreg.QueryInfoKey(key)[0]):
            app = winreg.EnumKey(key, i)
            with winreg.OpenKey(key, app) as sub:
                try:
                    value, kind = winreg.QueryValueEx(sub, 'Running')
                except FileNotFoundError:
                    continue
                if kind != winreg.REG_DWORD or type(value) is not int or value not in (0, 1):
                    raise RuntimeError('Steam running-app state is unavailable')
                if value:
                    out.append(app)
    return out


def clients(exe):
    out = []
    for row in native.processes():
        if row['name'].lower() == 'steam.exe':
            ident = native.identity(row['pid'])
            if not ident or Path(ident['path']).resolve() != Path(exe).resolve():
                raise RuntimeError('Different or unavailable Steam client identity')
            out.append(ident)
    if len(out) > 1:
        raise RuntimeError('Multiple Steam clients prevent graceful restoration')
    return out


def preflight(configuration):
    if not configuration.get('allow_steam_client_restart', False):
        return None
    exe = Path(configuration['steam_exe']).resolve()
    if exe.name.lower() != 'steam.exe' or not exe.is_file():
        raise RuntimeError('Configured Steam client executable unavailable')
    found = clients(exe)
    if len(found) != 1:
        raise RuntimeError('Opt-in Steam restoration requires one existing exact client')
    return {'identity': found[0], 'executableSha256': digest(exe), 'idleInventory': idle_inventory(found[0]),
            'authority': 'Explicit allow_steam_client_restart configuration; graceful driver restoration only'}


def idle_inventory(ident):
    """Reject any current game/VR or non-helper descendant; no name-only takeover."""
    items = native.processes()
    if any(row['name'].lower() in VR_GAME_NAMES for row in items):
        raise RuntimeError('Game/VR still running before graceful Steam shutdown')
    if running_apps():
        raise RuntimeError('Steam reports running applications; shutdown refused')
    descendants = {ident['pid']: ident}
    remaining = list(items)
    evidence = []
    while True:
        changed = False
        for row in remaining[:]:
            if row['pid'] == ident['pid'] or row['parent'] not in descendants:
                continue
            child = native.identity(row['pid'])
            parent = descendants[row['parent']]
            if not child or not native.alive(parent) or child['birth'] < parent['birth']:
                raise RuntimeError('Steam descendant ancestry unavailable or reused')
            path = Path(child['path']).resolve()
            if path.name.lower() not in HELPERS or not path.is_relative_to(Path(ident['path']).resolve().parent):
                raise RuntimeError('Non-helper Steam descendant; graceful shutdown refused')
            descendants[row['pid']] = child
            evidence.append({'identity': child, 'parent': parent})
            remaining.remove(row)
            changed = True
        if not changed:
            break
    if not native.alive(ident):
        raise RuntimeError('Steam identity changed during idle inventory')
    return {'helpers': evidence, 'runningAppHints': [], 'processCount': len(items),
            'basis': 'Current process/ancestry and registry snapshots; later external launches remain unobserved; shutdown is graceful only'}


def launch(command):
    # A preexisting client never enters owned[] and is never force-terminated.
    return subprocess.Popen(command, cwd=str(Path(command[0]).parent),
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def prepare(session):
    grant = session.state.get('preflight', {}).get('steamClientRestart')
    if not grant:
        return
    target = Path(session.state['preflight']['runtime']) / 'drivers/null/bin/win64/driver_null.dll'
    snapshot = next((x for x in session.state['snapshots'] if Path(x['path']).resolve() == target.resolve()), None)
    if not snapshot or not target.is_file():
        return
    original = snapshot['sha256'] if snapshot['exists'] else None
    if digest(target) == original:
        return # Already restored, including after an interrupted client reopen.
    if snapshot['exists'] and digest(snapshot['backup']) != original:
        raise RuntimeError('Driver backup changed before graceful Steam restoration')
    if session.state.get('driverBackend') != 'file' or digest(target) != session.state.get('driverManifest', {}).get('dllSha256'):
        raise RuntimeError('Staged driver identity unavailable for graceful Steam restoration')
    ident = grant['identity']
    found = clients(ident['path'])
    lifecycle = session.state.get('steamClientRestore')
    if lifecycle:
        if found:
            raise RuntimeError('Steam shutdown intent already issued or foreign client appeared; never replay shutdown')
        lifecycle['shutdownObserved'] = True
        session.save()
        return
    if not found:
        return # Owner already closed it; no restart was requested by us.
    if found != [ident] or not native.alive(ident) or digest(ident['path']) != grant['executableSha256']:
        raise RuntimeError('Preflight Steam identity/executable changed; shutdown refused')
    if target.resolve() not in {Path(p).resolve() for p in native.modules(ident)}:
        return # No observed owned-driver module: do not gratuitously restart Steam.
    inventory = idle_inventory(ident)
    if clients(ident['path']) != [ident] or not native.alive(ident):
        raise RuntimeError('Steam identity changed before graceful shutdown')
    lifecycle = {'before': ident, 'target': str(target), 'driverSha256': digest(target),
                 'inventory': inventory, 'shutdownRequested': True, 'shutdownObserved': False,
                 'shutdownCommand': [ident['path'], '-shutdown'], 'forced': False}
    session.state['steamClientRestore'] = lifecycle
    session.save() # Record intent before mutation; interruption cannot replay it.
    session.log('steam-driver-graceful-shutdown-requested', **lifecycle)
    launch(lifecycle['shutdownCommand'])
    end = time.monotonic() + 45
    while time.monotonic() < end:
        if not native.alive(ident) and not clients(ident['path']):
            break
        time.sleep(.25)
    if native.alive(ident) or clients(ident['path']):
        raise RuntimeError('Graceful Steam shutdown not observed; no force or replay')
    lifecycle['shutdownObserved'] = True
    session.save()
    session.log('steam-driver-graceful-shutdown-observed', identity=ident, forced=False)


def reopen(session):
    lifecycle = session.state.get('steamClientRestore')
    if not lifecycle or not lifecycle.get('shutdownObserved'):
        return
    before = lifecycle['before']
    grant = session.state['preflight']['steamClientRestart']
    if digest(before['path']) != grant['executableSha256']:
        raise RuntimeError('Steam executable changed before reopening')
    found = clients(before['path'])
    if lifecycle.get('reopened'):
        if found != [lifecycle['after']]:
            raise RuntimeError('Restored Steam client identity changed')
        return
    if not lifecycle.get('reopenRequested'):
        if found:
            raise RuntimeError('Foreign Steam client appeared before reopening')
        lifecycle['reopenRequested'] = True
        session.save()
        session.log('steam-driver-client-reopen-requested', executable=before['path'])
        launch([before['path'], '-silent'])
    end = time.monotonic() + 25
    while not found and time.monotonic() < end:
        time.sleep(.25)
        found = clients(before['path'])
    if len(found) != 1 or found[0] == before:
        raise RuntimeError('New matching Steam client not observed; no launch replay')
    lifecycle.update(reopened=True, after=found[0],
                     reopenBasis='Exact matching client presence after durable reopen intent; no ownership or readiness claim')
    session.save()
    session.log('steam-driver-client-reopened', identity=found[0], ownershipClaimed=False)
