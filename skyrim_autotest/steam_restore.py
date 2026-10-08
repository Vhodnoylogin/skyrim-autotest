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


class ClientInventoryUnavailable(RuntimeError):
    """Unknown identity, never evidence that the client is absent."""


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
    # Toolhelp rows can outlive their process during graceful exit. An unknown
    # row is never treated as absence: obtain a fresh complete inventory first.
    for attempt in range(3):
        out, unavailable = [], False
        for row in native.processes():
            if row['name'].lower() != 'steam.exe':
                continue
            ident = native.identity(row['pid'])
            if ident is None:
                unavailable = True
                break
            if Path(ident['path']).resolve() != Path(exe).resolve():
                raise RuntimeError('Different Steam client executable identity')
            out.append(ident)
        if not unavailable:
            if len(out) > 1:
                raise RuntimeError('Multiple Steam clients prevent graceful restoration')
            return out
        if attempt < 2:
            time.sleep(.05)
    raise ClientInventoryUnavailable('Unavailable Steam client identity persisted after bounded resampling')


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


def observe_module(ident, target):
    """Allow Steam's delayed watchdog transition before deciding no lock exists."""
    started = time.monotonic()
    wanted = Path(target).resolve()
    observed = wanted in {Path(p).resolve() for p in native.modules(ident)}
    while not observed and time.monotonic() - started < 8:
        time.sleep(.25)
        observed = wanted in {Path(p).resolve() for p in native.modules(ident)}
    return {'identity': ident, 'modulePath': str(wanted), 'observed': observed,
            'elapsedSeconds': time.monotonic()-started, 'maximumWaitSeconds': 8,
            'basis': 'Identity-bracketed module snapshots during delayed Steam watchdog startup; later loads remain possible'}


def staged_digest(session, target):
    actual = digest(target)
    if session.state.get('driverBackend') != 'file':
        raise RuntimeError('Staged driver identity unavailable for graceful Steam restoration')
    if actual == session.state.get('driverManifest', {}).get('dllSha256'):
        return actual
    # Setup first unpacks the hash-pinned upstream archive, then replaces its
    # DLL with our adapter. An interrupted pre-launch setup can leave this
    # intermediate, equally identified payload. Do not invent an adapter
    # manifest or accept arbitrary bytes to recover that state.
    from . import runner
    archive = runner.ROOT / 'dependencies/driver-dedb8ab.zip'
    if (session.state.get('owned') or session.state.get('launchIntents') or
            session.state.get('game') or session.state.get('hardwareFrame') or
            actual != runner.DRIVER_DLL_HASH or not archive.is_file() or
            digest(archive) != runner.DRIVER_ZIP_HASH):
        raise RuntimeError('Staged driver identity unavailable for graceful Steam restoration')
    import zipfile
    member = 'null/bin/win64/driver_null.dll'
    with zipfile.ZipFile(archive) as z:
        if z.namelist().count(member) != 1 or hashlib.sha256(z.read(member)).hexdigest() != actual:
            raise RuntimeError('Pinned intermediate driver payload mismatch')
    session.log('steam-driver-intermediate-identity', driverSha256=actual,
                archiveSha256=runner.DRIVER_ZIP_HASH, noLaunchIntent=True,
                basis='Exact pinned upstream archive/DLL during interrupted pre-launch staging')
    return actual


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
    staged = staged_digest(session, target)
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
    module = observe_module(ident, target)
    session.log('steam-driver-module-observation', **module)
    if not module['observed']:
        return # No observed owned-driver module: do not gratuitously restart Steam.
    inventory = idle_inventory(ident)
    if clients(ident['path']) != [ident] or not native.alive(ident) or digest(target) != staged:
        raise RuntimeError('Steam identity changed before graceful shutdown')
    lifecycle = {'before': ident, 'target': str(target), 'driverSha256': digest(target),
                 'inventory': inventory, 'moduleObservation': module, 'shutdownRequested': True, 'shutdownObserved': False,
                 'shutdownCommand': [ident['path'], '-shutdown'], 'forced': False}
    session.state['steamClientRestore'] = lifecycle
    session.save() # Record intent before mutation; interruption cannot replay it.
    session.log('steam-driver-graceful-shutdown-requested', **lifecycle)
    launch(lifecycle['shutdownCommand'])
    end = time.monotonic() + 45
    observed = False
    while time.monotonic() < end:
        if not native.alive(ident):
            try:
                found = clients(ident['path'])
            except ClientInventoryUnavailable as error:
                session.log('steam-client-inventory-unavailable', phase='shutdown-observation', error=str(error), absenceObserved=False)
            else:
                if found:
                    raise RuntimeError('Foreign Steam client appeared during shutdown; no force or replay')
                observed = True
                break
        time.sleep(.25)
    if not observed:
        raise RuntimeError('Graceful Steam shutdown not observed; no force or replay')
    lifecycle['shutdownObserved'] = True
    session.save()
    session.log('steam-driver-graceful-shutdown-observed', identity=ident, forced=False)


def retry_locked_driver(session, path, error):
    """One guarded restoration retry for a driver loaded after initial inspection."""
    if getattr(error, 'winerror', None) != 32 or not session.state.get('preflight', {}).get('steamClientRestart'):
        return False
    target = Path(session.state['preflight']['runtime'])/'drivers/null/bin/win64/driver_null.dll'
    if Path(path).resolve() != target.resolve() or session.state.get('steamDriverCopyRetryIssued'):
        return False
    session.log('steam-driver-restore-sharing-violation', path=str(target), error=str(error), winerror=32)
    prepare(session)
    if not session.state.get('steamClientRestore', {}).get('shutdownObserved'):
        return False
    session.state['steamDriverCopyRetryIssued'] = True
    session.save()
    session.log('steam-driver-restore-retry-issued', path=str(target), originalError=str(error), maximumRetries=1)
    return True


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
        try:
            found = clients(before['path'])
        except ClientInventoryUnavailable as error:
            session.log('steam-client-inventory-unavailable', phase='reopen-observation', error=str(error), absenceObserved=False)
    if len(found) != 1 or found[0] == before:
        raise RuntimeError('New matching Steam client not observed; no launch replay')
    lifecycle.update(reopened=True, after=found[0],
                     reopenBasis='Exact matching client presence after durable reopen intent; no ownership or readiness claim')
    session.save()
    session.log('steam-driver-client-reopened', identity=found[0], ownershipClaimed=False)
