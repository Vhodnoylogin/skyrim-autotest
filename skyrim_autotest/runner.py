"""Skyrim VR session runner: preflight, reversible setup, launch, proof and recovery.

Tags: РёРЅСЃС‚СЂСѓРјРµРЅС‚С‹, mo2, devbench

python runner.py preflight --profile SkyrimVR-Core
python runner.py run --profile SkyrimVR-Core --scenario scenarios/startup.json
python runner.py recover
python runner.py status

Dependencies, backups, tokens and evidence stay in the configured external runtime directory, outside Git.
The guardian is an independent process; recover handles abandoned sessions after reboot.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import urllib.error
import uuid
import zipfile

from .config import P, configure as configure_paths
from . import native

DRIVER_URL = 'https://raw.githubusercontent.com/DubiousDuo/VR-Emulator-Driver---SkyrimVR-Devkit/dedb8ab33fc46b25ecee191f882951c064422505/null%20driver.zip'
DRIVER_ZIP_HASH = '4a4015b710e0b764f4d61ad642e3e3dbba59e5100749e43e7853e1f4e6fe41bd'
DRIVER_DLL_HASH = '798a148e3579bb790070d1800b0c753d814acdf46c010984f6c81969fd71b939'
VR_NAMES = {'vrserver.exe', 'vrmonitor.exe', 'vrcompositor.exe', 'vrstartup.exe',
            'vrdashboard.exe', 'vrwebhelper.exe', 'vrprismhost.exe'}
GAME_NAMES = {'skyrimvr.exe', 'sksevr_loader.exe'}
OCU = {'OpenComposite Unleashed for Skyrim VR', 'OpenComposite Unleashed for Skyrim VR - No Grip Ready Weapon'}
ROOT = P.runtime
RUNS = ROOT / 'runs'

def configure(value):
    global ROOT, RUNS
    configure_paths(value)
    ROOT = P.runtime
    RUNS = ROOT / 'runs'


class Blocked(RuntimeError):
    pass


class HTTPResponseError(RuntimeError):
    """Retain status/route/body without inferring the server's failure cause."""
    def __init__(self, status, route, body):
        self.status, self.route, self.body = status, route, body
        super().__init__(f'HTTP {status} {route}: {body}')


class ToolError(RuntimeError):
    """A structured error returned by an identity-checked owned tool endpoint."""
    def __init__(self, tool, args, result):
        self.tool = tool
        self.args_value = copy.deepcopy(args)
        self.result = copy.deepcopy(result)
        super().__init__(f'{tool}: {result}')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(value, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    for attempt in range(20):
        try:
            os.replace(temp, path)
            break
        except PermissionError:
            # Windows can briefly deny replacement while the guardian reads it.
            if attempt == 19:
                raise
            time.sleep(.05)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def request(port, route, body=None, token=None, timeout=12):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-Token'] = token
    req = urllib.request.Request(f'http://127.0.0.1:{int(port)}/{route.lstrip("/")}',
        data=None if body is None else json.dumps(body).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', errors='replace')
        raise HTTPResponseError(e.code, route, detail) from None


def set_ini(text, section, key, value):
    pattern = re.compile(r'(?ms)^\[' + re.escape(section) + r'\]\r?\n(.*?)(?=^\[|\Z)')
    match = pattern.search(text)
    newline = '\r\n' if '\r\n' in text else '\n'
    if not match:
        return text.rstrip() + newline + f'[{section}]' + newline + f'{key}={value}' + newline
    contents = match[1]
    keypattern = re.compile(r'(?m)^' + re.escape(key) + r'=.*$')
    if keypattern.search(contents):
        contents = keypattern.sub(lambda _: f'{key}={value}', contents)
    else:
        contents += f'{key}={value}{newline}'
    return text[:match.start(1)] + contents + text[match.end(1):]


def preflight(profile, restart_idle_mo2=False):
    if Path(profile).name != profile or profile in ('.', '..'):
        raise Blocked('Invalid profile name')
    source = P.profiles / profile
    for plugin in P.staged_plugins:
        if not Path(plugin['source']).is_file() or sha(plugin['source']) != plugin['sha256']:
            raise Blocked('Missing or changed staged plugin: ' + plugin['source'])
    for path in (P.mo2_exe, P.mo2_ini, P.game / 'SkyrimVR.exe', source / 'modlist.txt'):
        if not path.is_file():
            raise Blocked(f'Missing required file: {path}')
    busy = [p for p in native.processes() if p['name'].lower() in VR_NAMES | GAME_NAMES | {'modorganizer.exe'}]
    idle_mo2 = [p for p in busy if p['name'].lower() == 'modorganizer.exe']
    if busy and not (restart_idle_mo2 and len(busy) == len(idle_mo2) == 1):
        raise Blocked('Existing MO2/game/VR session; refusing to take it over: ' + str(busy))
    if idle_mo2:
        ident = native.identity(idle_mo2[0]['pid'])
        if not ident or Path(ident['path']).resolve() != P.mo2_exe.resolve():
            raise Blocked('Idle MO2 belongs to a different installation')
        token = (P.bridge_token).read_text().strip()
        procs = request(P.bridge_port, 'procs', token=token)
        if procs.get('busy') or procs.get('running') or procs.get('launchedByMO2'):
            raise Blocked('MO2 is busy; an idle restart is not allowed')
    vrpaths = P.openvr_paths
    paths = read_json(vrpaths)
    runtime = Path(paths['runtime'][0])
    config = Path(paths['config'][0]) / 'steamvr.vrsettings'
    if paths.get('external_drivers'):
        raise Blocked('External SteamVR drivers require an explicit isolated test configuration')
    vive_profile = runtime / 'drivers/htc/resources/input/vive_controller_profile.json'
    if not vive_profile.is_file():
        raise Blocked('The adapter requires the installed SteamVR Vive input profile')
    enabled = {line[1:] for line in (source / 'modlist.txt').read_text(encoding='utf-8-sig').splitlines() if line.startswith('+')}
    required = set(P.required_mods)
    if not required <= enabled:
        raise Blocked('Required disabled mods: ' + str(sorted(required - enabled)))
    rb = P.mo2 / 'plugins/data/RootBuilder'
    originals = [p for p in rb.rglob('openvr_api.dll') if p.parent.name == 'Backup' and p.stat().st_size < 2000000]
    if len(originals) != 1:
        raise Blocked('Need exactly one verified stock openvr_api.dll in Root Builder backup')
    original = originals[0]
    rbdata = original.parent.parent
    # Fingerprint installed binaries, rather than the stale business index.
    dlls = {}
    for mod in sorted(required):
        for file in (P.mods / mod / 'SKSE/Plugins').glob('*.dll'):
            dlls[str(file.relative_to(P.mods))] = sha(file)
    configs = {}
    for mod in sorted(enabled):
        root = (P.mods / mod).resolve()
        if not root.is_relative_to(P.mods.resolve()):
            raise Blocked('Enabled mod path escapes the configured mods directory')
        for file in root.rglob('*'):
            if file.is_file() and file.suffix.lower() in ('.ini', '.toml', '.json') and file.name.lower() != 'meta.ini':
                if not file.resolve().is_relative_to(root):
                    raise Blocked('Configuration symlink escapes its mod directory')
                configs[str(file)] = sha(file)
    return {'profile': profile, 'runtime': str(runtime), 'settings': str(config),
            'viveInputProfile': str(vive_profile), 'viveInputProfileHash': sha(vive_profile),
            'idleMO2': native.identity(idle_mo2[0]['pid']) if idle_mo2 else None,
            'vrpaths': str(vrpaths), 'stockOpenVR': str(original), 'stockOpenVRHash': sha(original),
            'rootBuilderData': str(rbdata), 'dlls': dlls,
            'configHashes': configs,
            'profileHashes': {name: sha(source / name) for name in ('modlist.txt', 'plugins.txt', 'loadorder.txt') if (source / name).exists()}}


class Session:
    def __init__(self, directory, state=None):
        self.dir = Path(directory)
        self.state = state if state is not None else read_json(self.dir / 'state.json')
        if self.state.get('configuration'):
            configure(self.state['configuration'])
        self.lock = threading.RLock()
        self.finished = threading.Event()

    def save(self):
        with self.lock:
            atomic_json(self.dir / 'state.json', self.state)

    def log(self, kind, **details):
        with self.lock:
            with (self.dir / 'steps.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps({'at': time.time(), 'kind': kind, **details}, ensure_ascii=False) + '\n')
                f.flush()
                os.fsync(f.fileno())

    def phase(self, name, seconds=120):
        with self.lock:
            self.state.update(phase=name, deadline=time.time() + seconds)
            self.save()
        self.log('phase', name=name, deadline=self.state['deadline'])
        print(name, flush=True)

    def snapshot(self, path):
        path = Path(path).resolve()
        if any(s['path'].casefold() == str(path).casefold() for s in self.state['snapshots']):
            return
        entry = {'path': str(path), 'exists': path.is_file()}
        if path.exists() and not path.is_file():
            raise Blocked(f'Snapshot target is not a regular file: {path}')
        if path.is_file():
            backup = self.dir / 'backups' / str(len(self.state['snapshots']))
            backup.parent.mkdir(exist_ok=True)
            shutil.copy2(path, backup)
            entry.update(backup=str(backup), sha256=sha(backup))
        self.state['snapshots'].append(entry)
        self.save()  # Write-ahead: no mutation until the durable backup is registered.

    def write(self, path, contents):
        self.snapshot(path)
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(contents, dict):
            atomic_json(path, contents)
        else:
            path.write_bytes(contents if isinstance(contents, bytes) else contents.encode('utf-8'))

    def own(self, pid, role):
        ident = native.identity(pid)
        if not ident:
            return
        with self.lock:
            if ident not in [p['identity'] for p in self.state['owned']]:
                self.state['owned'].append({'role': role, 'identity': ident})
                self.save()

    def discover(self):
        # Launch intents are durable before spawning. Discover children even if the
        # runner dies in the small interval before recording the returned PID.
        items = native.processes()
        by_pid = {p['pid']: p for p in items}
        for item in items:
            name = item['name'].lower()
            intent = self.state.get('launchIntents', {}).get('game' if name in GAME_NAMES else 'vr' if name in VR_NAMES else 'mo2' if name == 'modorganizer.exe' else '')
            if not intent:
                continue
            ident = native.identity(item['pid'])
            if not ident:
                continue
            birth_unix = ident['birth'] / 10000000 - 11644473600
            if birth_unix < intent['at'] - 1:
                continue
            expected = Path(intent['directory']).resolve()
            if not Path(ident['path']).resolve().is_relative_to(expected):
                continue
            # Matching name/path/time is insufficient: a later manual launch is
            # foreign. Require ancestry through a recorded launch identity. A
            # dead launcher's PID is allowed only when no reused PID conflicts.
            ancestors = {p['identity']['pid']: p['identity'] for p in self.state['owned']}
            if self.state.get('runner'):
                ancestors[self.state['runner']['pid']] = self.state['runner']
            parent = item['parent']
            seen = {item['pid']}
            related = False
            while parent and parent not in seen:
                seen.add(parent)
                ancestor = ancestors.get(parent)
                if ancestor:
                    current = native.identity(parent)
                    related = ancestor['birth'] <= ident['birth'] and (current is None or current == ancestor)
                    break
                entry = by_pid.get(parent)
                parent_ident = native.identity(parent) if entry else None
                if not parent_ident or parent_ident['birth'] > ident['birth']:
                    break
                parent = entry['parent']
            if not related:
                continue
            self.own(item['pid'], 'game' if name in GAME_NAMES else 'vr' if name in VR_NAMES else 'mo2')

    def spawn(self, command, role, cwd=None):
        self.state['launchIntents'][role] = {'at': time.time(), 'directory': str(Path(command[0]).parent)}
        self.save()
        flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        process = subprocess.Popen(command, cwd=cwd, creationflags=flags,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.own(process.pid, role)
        return process

    def heartbeat(self):
        while not self.finished.wait(1):
            with self.lock:
                self.state['heartbeat'] = time.time()
                if self.state.get('hardwareFrame') and not self.state.get('restoringFiles'):
                    from . import hardware
                    if time.time() > self.state.get('hardwareHoldUntil', float('inf')):
                        hardware.release(self.state['hardwareFrame'])
                    hardware.publish(self.state['hardwareFrame'])
                self.discover()
                self.save()

    def driver_tool(self, args):
        if self.state.get('inputBackend') != 'driver' or self.state.get('driverBackend') != 'file':
            raise Blocked('Local driver tools require the qualified file-adapter backend')
        from . import hardware
        from .scenarios import validate_driver
        validate_driver(args)
        action = args.get('action')
        with self.lock:
            if action == 'status':
                result = {'backend': 'physical-driver', 'published': bool(self.state.get('hardwareFrame')), 'holdUntil': self.state.get('hardwareHoldUntil'), 'acknowledgedByDriver': False}
            elif action == 'release':
                hardware.release(self.state['hardwareFrame'])
                self.state['hardwareHoldUntil'] = time.time()
                hardware.publish(self.state['hardwareFrame'])
                result = {'published': True, 'released': True, 'acknowledgedByDriver': False}
            elif action == 'publish':
                frame = copy.deepcopy(args['frame'])
                duration = args['holdSeconds']
                hardware.publish(frame)
                self.state['hardwareFrame'] = frame
                self.state['hardwareHoldUntil'] = time.time() + duration
                result = {'published': True, 'holdSeconds': duration, 'acknowledgedByDriver': False}
            else:
                raise ValueError('Unknown driver action')
            self.save()
            self.log('driver', action=action, result=result)
            return result

    def invalidate_probe_reference(self, reason):
        self.state['probeObjectLive'] = False
        self.save()
        self.log('probe-reference-invalidated', reason=reason)

    def capture_probe_cursor(self):
        envelope = request(self.state['port'], 'api/events', timeout=3)
        events = envelope.get('events')
        if not isinstance(events, list) or any(not isinstance(event, dict) or type(event.get('seq')) is not int for event in events):
            raise Blocked('Cannot establish probe reference lifecycle cursor')
        return max((event['seq'] for event in events), default=0)

    def bind_probe_reference(self, ref, cursor):
        # Cursor was observed before creation, so a load while PlaceAtMe returns
        # cannot be silently adopted as the new reference's generation.
        self.state.update(probeObject=ref, probeObjectLive=True, probeEventCursor=cursor)
        self.save()
        self.validate_probe_reference()

    def validate_probe_reference(self, timeout=3):
        if not self.state.get('probeObjectLive') or 'probeEventCursor' not in self.state:
            raise Blocked('Probe reference is unavailable or invalidated')
        cursor = self.state['probeEventCursor']
        deadline = time.monotonic() + timeout
        try:
            # Since() and HeadSeq() are fetched separately by the producer.
            # A leading head is not evidence that its events were observed.
            for attempt in range(3):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Blocked('Probe lifecycle check exceeded its deadline')
                envelope = request(self.state['port'], 'api/events?since=' + str(cursor), timeout=min(remaining, 3))
                events, head = envelope.get('events'), envelope.get('headSeq')
                if not isinstance(events, list) or type(head) is not int or head < cursor:
                    raise Blocked('Probe lifecycle stream reset or is malformed')
                for event in events:
                    if not isinstance(event, dict) or type(event.get('seq')) is not int or event['seq'] != cursor + 1:
                        raise Blocked('Probe lifecycle event gap; reference generation is unknown')
                    cursor = event['seq']
                    payload = event.get('data', {})
                    lifecycle = payload.get('event', payload.get('type')) if isinstance(payload, dict) else None
                    if event.get('topic') == 'lifecycle' and lifecycle in ('preLoadGame', 'postLoadGame', 'newGame'):
                        raise Blocked('Probe reference invalidated by a world lifecycle transition')
                self.state['probeEventCursor'] = cursor
                self.save()
                if head <= cursor:
                    return
            raise Blocked('Unseen lifecycle head could not be reconciled within the bound')
        except Exception as error:
            self.invalidate_probe_reference(str(error))
            raise

    def tool(self, name, args, timeout=12, deadline=None):
        if self.state.get('postStepsActive') and changes_reference_world(name, args):
            self.invalidate_probe_reference('potential world-changing request: ' + name)
        if name == 'driver':
            return self.driver_tool(args)
        def bounded_timeout(limit):
            if deadline is None:
                return limit
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Tool readiness deadline exceeded: ' + name)
            return min(limit, remaining)
        health = request(self.state['port'], 'api/health', timeout=bounded_timeout(3))
        if health.get('pid') != self.state['game']['pid'] or not native.alive(self.state['game']):
            raise Blocked('DevBench identity no longer matches the owned game')
        started = time.monotonic()
        try:
            result = request(self.state['port'], f'api/tool/{name}', args, timeout=bounded_timeout(timeout))
        except Exception as e:
            self.log('tool-error', tool=name, args=args, error=str(e), elapsedMs=int((time.monotonic() - started) * 1000))
            raise
        self.log('tool', tool=name, args=args, result=result)
        if isinstance(result, dict) and (result.get('isError') or result.get('error')):
            raise ToolError(name, args, result)
        return result

    def setup(self):
        self.phase('snapshot', 180)
        info = self.state['preflight']
        if info.get('idleMO2'):
            self.state['reopenMO2'] = True
            self.save()
            native.close(info['idleMO2'])
            end = time.monotonic() + 30
            while native.alive(info['idleMO2']) and time.monotonic() < end:
                time.sleep(.5)
            if native.alive(info['idleMO2']):
                self.state['reopenMO2'] = False
                self.save()
                raise Blocked('Idle MO2 did not close gracefully; refusing to force it')
        runtime = Path(info['runtime'])
        driver = runtime / 'drivers/null'
        dep = ROOT / 'dependencies/driver-dedb8ab.zip'
        if not dep.exists():
            dep.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(DRIVER_URL, timeout=30) as response:
                data = response.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise Blocked('Driver archive exceeds the bounded download size')
            dep.write_bytes(data)
        if sha(dep) != DRIVER_ZIP_HASH:
            raise Blocked('Pinned driver archive hash mismatch')
        # Snapshot any Root Builder target including targets from disabled OCU.
        targets = {P.game / 'openvr_api.dll'}
        for mod in P.mods.iterdir():
            root = mod / 'Root'
            if root.is_dir():
                for file in root.rglob('*'):
                    if file.is_file():
                        targets.add(P.game / file.relative_to(root))
        for path in sorted(targets):
            self.snapshot(path)
            self.snapshot(Path(info['rootBuilderData']) / 'Backup' / path.relative_to(P.game))
        for file in (Path(info['rootBuilderData']) / 'Backup').rglob('*'):
            if file.is_file():
                self.snapshot(file)
        for file in Path(info['rootBuilderData']).glob('*.json'):
            self.snapshot(file)
        for name in ('GameData.json', 'BuildData.json'):
            self.snapshot(Path(info['rootBuilderData']) / name)
        self.snapshot(P.mo2_ini)
        self.snapshot(info['settings'])
        # Existing mod configuration may be rewritten by the game, even when
        # our APIs change settings only in memory. Preserve those inputs too.
        for path in P.extra_files:
            self.snapshot(path)
        for plugin in P.staged_plugins:
            source = Path(plugin['source'])
            target = (P.overwrite / plugin['destination']).resolve()
            if not target.is_relative_to(P.overwrite.resolve()):
                raise Blocked('Staged plugin destination escapes overwrite')
            if sha(source) != plugin['sha256']:
                raise Blocked('Staged plugin hash mismatch: ' + str(source))
            self.write(target, source.read_bytes())
            self.state.setdefault('stagedPlugins', []).append({'destination': str(target), 'sha256': plugin['sha256']})
            self.save()
        for path, digest in info.get('configHashes', {}).items():
            if sha(path) != digest:
                raise Blocked('Mod configuration changed after preflight: ' + path)
            self.snapshot(path)
        # Existing deployed OCU entries must not be merged into the test build and
        # harvested back into third-party mods when Root Builder clears it.
        old_build = Path(info['rootBuilderData']) / 'BuildData.json'
        if old_build.exists():
            old_build.unlink()
        # Isolated profile: never load or autosave over the owner's original saves.
        profile_name = 'Autotest-' + self.state['id']
        test_profile = P.profiles / profile_name
        if test_profile.exists():
            raise Blocked('Generated test profile already exists')
        self.state['testProfile'] = str(test_profile)
        self.state['testProfileName'] = profile_name
        self.save()
        test_profile.mkdir()
        (test_profile / 'saves').mkdir()
        for file in (P.profiles / info['profile']).iterdir():
            if file.is_file():
                shutil.copy2(file, test_profile / file.name)
        settings_file = test_profile / 'settings.ini'
        settings_text = settings_file.read_text(encoding='utf-8-sig') if settings_file.exists() else '[General]\n'
        for key in ('LocalSaves', 'LocalSettings'):
            settings_text = set_ini(settings_text, 'General', key, 'true')
        settings_file.write_text(settings_text, encoding='utf-8')
        fixture = self.state['scenario'].get('fixture')
        if fixture:
            stem = fixture['saveStem']
            if Path(stem).name != stem or '/' in stem or '\\' in stem:
                raise Blocked('Invalid fixture save name')
            for ext in ('ess', 'skse'):
                source = (P.fixture_dir or P.profiles / info['profile'] / 'saves') / f'{stem}.{ext}'
                if sha(source) != fixture[ext + 'Sha256']:
                    raise Blocked('Save fixture hash mismatch: ' + ext)
                shutil.copy2(source, test_profile / 'saves' / source.name)
            self.state['fixture'] = fixture
            self.save()
        modlist = test_profile / 'modlist.txt'
        text = modlist.read_text(encoding='utf-8-sig')
        text = '\n'.join('-' + line[1:] if line.startswith('+') and line[1:] in OCU else line for line in text.splitlines()) + '\n'
        modlist.write_text(text, encoding='utf-8')
        prefs = test_profile / 'SkyrimPrefs.ini'
        if prefs.exists():
            text = prefs.read_text(encoding='utf-8-sig')
            for key in ('bSaveOnPause', 'bSaveOnTravel', 'bSaveOnWait', 'bSaveOnRest'):
                text = re.sub(r'(?im)^(\s*' + key + r'\s*=).*$', r'\g<1>0', text)
                text = set_ini(text, 'Main', key, '0')
            prefs.write_text(text, encoding='utf-8')
        # MO2 stores its selected profile in memory, so only write while it is closed.
        text = P.mo2_ini.read_bytes().decode('utf-8-sig')
        text = re.sub(r'(?m)^selected_profile=.*$', lambda _: 'selected_profile=@ByteArray(' + profile_name + ')', text)
        self.write(P.mo2_ini, text)
        # Disable autobuild's redirect case: registered SKSE is already game-root based.
        self.write(P.game / 'openvr_api.dll', Path(info['stockOpenVR']).read_bytes())
        with zipfile.ZipFile(dep) as archive:
            binary = archive.read('null/bin/win64/driver_null.dll')
            if hashlib.sha256(binary).hexdigest() != DRIVER_DLL_HASH:
                raise Blocked('Pinned driver DLL hash mismatch')
            for name in archive.namelist():
                relative = Path(name)
                if name.endswith('/'):
                    continue
                if relative.parts[0] != 'null' or '..' in relative.parts:
                    raise Blocked('Unsafe pinned driver archive member')
                self.write(driver / Path(*relative.parts[1:]), archive.read(name))
        if self.state['driverBackend'] == 'file':
            build = ROOT / 'dependencies/driver-build'
            manifest = read_json(build / 'manifest.json')
            here = Path(__file__).resolve().parent
            if sha(build / 'driver_null.dll') != manifest['dllSha256'] or sha(here / 'autotest_protocol.h') != manifest['ownProtocolSha256'] or sha(here / 'build_driver.py') != manifest['buildScriptSha256'] or sha(here / 'driver_sources.json') != manifest.get('sourceCatalogueSha256'):
                raise Blocked('External driver adapter is stale; run build_driver.py')
            self.write(driver / 'bin/win64/driver_null.dll', (build / 'driver_null.dll').read_bytes())
            signature = driver / 'bin/win64/driver_null.dll.sig'
            if signature.exists():
                signature.unlink()
            self.state['driverManifest'] = manifest
            from . import hardware
            with self.lock:
                self.snapshot(hardware.PATH)
                self.state['hardwareFrame'] = hardware.neutral()
                self.save()
                hardware.publish(self.state['hardwareFrame'])
        settings = read_json(info['settings']) if Path(info['settings']).exists() else {}
        settings.setdefault('driver_null', {}).update(enable=True)
        settings.setdefault('steamvr', {}).update(forcedDriver='null', requireHmd=True,
            activateMultipleDrivers=False, enableHomeApp=False, startDashboardFromAppLaunch=False)
        self.write(info['settings'], settings)
        # The driver starts every device at the floor. Seed a standing HMD and
        # separated hands before Skyrim initializes height/calibration or its VR room.
        actions = Path(os.environ['PROGRAMDATA']) / 'SkyrimVR Devkit/Actions'
        for name, xyz in [('headset', '0 1.65 0'), ('controller1', '-0.3 1.2 -0.35'), ('controller2', '0.3 1.2 -0.35')]:
            self.write(actions / f'{name}_position_changes.txt', xyz)
            self.write(actions / f'{name}_rotation_changes.txt', '0 0 0')
        self.log('configured', driverHash=DRIVER_DLL_HASH, stockOpenVRHash=info['stockOpenVRHash'], profile=profile_name)

    def launch(self):
        self.phase('start-mo2', 90)
        self.spawn([str(P.mo2_exe)], 'mo2', str(P.mo2))
        token_file = P.bridge_token
        end = time.monotonic() + 75
        ping = None
        while time.monotonic() < end:
            try:
                token = token_file.read_text().strip()
                ping = request(P.bridge_port, 'ping', token=token, timeout=3)
                if ping:
                    break
            except (OSError, ValueError, RuntimeError):
                pass
            time.sleep(1)
        if not ping:
            raise Blocked('MO2 bridge readiness timeout; inspect MO2 log/windows')
        self.log('mo2-ping', result=ping)
        if ping.get('profile') != self.state['testProfileName']:
            raise Blocked('MO2 selected profile does not match the isolated profile')
        if ping.get('game') != 'SkyrimVR' or Path(ping.get('modsPath', '')).resolve() != P.mods.resolve():
            raise Blocked('MO2 bridge belongs to a different game/instance')
        self.phase('start-steamvr', 90)
        self.spawn([str(Path(self.state['preflight']['runtime']) / 'bin/win64/vrstartup.exe')], 'vr')
        end = time.monotonic() + 45
        while time.monotonic() < end:
            self.discover()
            if any(p['name'].lower() == 'vrcompositor.exe' for p in native.processes()):
                break
            time.sleep(1)
        else:
            raise Blocked('SteamVR compositor readiness timeout')
        self.phase('start-skse', 180)
        self.state['launchIntents']['game'] = {'at': time.time(), 'directory': str(P.game)}
        self.save()
        launch = request(P.bridge_port, 'run', {'binary': 'SKSE', 'wait': False,
            'iUnderstandTheRisk': 'yes-I-read-the-docs-and-accept-irreversible-changes'}, token=token, timeout=30)
        self.log('mo2-launch', result=launch)
        if not launch.get('started') or launch.get('applied') is False:
            raise Blocked('MO2 did not start registered SKSE')
        if launch.get('pid'):
            self.own(launch['pid'], 'loader')
        self.phase('wait-devbench', 180)
        candidates = [Path(p) for p in P.devbench_runtime_files] or [Path(os.environ['LOCALAPPDATA']) / 'devbench/vr/runtime.json', P.overwrite / 'SKSE/Plugins/devbench/runtime.json']
        end = time.monotonic() + 150
        first_frame = None
        while time.monotonic() < end:
            self.discover()
            games = [x['identity'] for x in self.state['owned'] if Path(x['identity']['path']).name.lower() == 'skyrimvr.exe' and native.alive(x['identity'])]
            for file in candidates:
                try:
                    if file.stat().st_mtime < self.state['launchIntents']['game']['at'] - 1:
                        continue
                    port = int(read_json(file)['port'])
                    health = request(port, 'api/health', timeout=3)
                    matching = next((g for g in games if g['pid'] == health.get('pid')), None)
                    if not matching:
                        continue
                    self.state.update(port=port, game=matching)
                    self.save()
                    self.log('health', result=health)
                    frame = health.get('frame')
                    if first_frame is not None and frame != first_frame:
                        self.phase('wait-task-queue', 90)
                        ready_end = time.monotonic() + 75
                        while time.monotonic() < ready_end:
                            try:
                                state = self.tool('inspect', {'kind': 'state'}, timeout=8)
                                self.log('task-queue-ready', state=state)
                                return
                            except RuntimeError as e:
                                if not str(e).startswith('HTTP 504'):
                                    raise
                                # Safe read only: the server abandons a task that did
                                # not start. No mutation or whole-game retry occurs.
                                self.log('task-queue-not-ready', error=str(e))
                                time.sleep(1)
                        raise Blocked('Game renders but SKSE task queue did not become ready')
                    first_frame = frame
                except (OSError, ValueError, KeyError, RuntimeError):
                    continue
            time.sleep(1)
        raise Blocked('Fresh matching DevBench with advancing game frames not found')

    def collect(self):
        dest = self.dir / 'evidence'
        dest.mkdir(exist_ok=True)
        log_dir = P.skse_logs
        manifest = []
        launched_at = self.state.get('launchIntents', {}).get('game', {}).get('at')
        for path in log_dir.glob('*.log'):
            fresh = bool(launched_at and path.stat().st_mtime >= launched_at - 1)
            if not fresh:
                continue
            try:
                shutil.copy2(path, dest / path.name)
                manifest.append({'name': path.name, 'sha256': sha(dest / path.name), 'mtime': path.stat().st_mtime, 'fresh': True})
            except OSError as e:
                self.log('collect-error', path=str(path), error=str(e))
        steamlog = Path(read_json(self.state['preflight']['vrpaths'])['log'][0])
        for name in ('vrserver.txt', 'vrcompositor.txt', 'vrmonitor.txt'):
            file = steamlog / name
            if file.exists():
                shutil.copy2(file, dest / name)
        bridge_log = P.mo2 / 'plugins/mo2aibridge/mo2aibridge.log'
        if bridge_log.exists():
            shutil.copy2(bridge_log, dest / 'mo2aibridge.log')
        # Captures written through MO2's virtual Data directory end up in overwrite.
        # Copy only artifacts named for this run and constrained to our capture tree.
        capture_root = P.overwrite / 'SKSE/Plugins/devbench/captures'
        if capture_root.exists():
            for path in capture_root.rglob(self.state['id'] + '-*.png'):
                if path.is_file() and path.resolve().is_relative_to(capture_root.resolve()):
                    shutil.copy2(path, dest / path.name)
                    manifest.append({'name': path.name, 'sha256': sha(dest / path.name), 'source': str(path), 'kind': 'capture'})
        atomic_json(dest / 'manifest.json', manifest)
        self.log('evidence-collected', files=[p.name for p in dest.iterdir()])

    def cleanup(self):
        self.phase('stop-and-restore', 150)
        if self.state.get('hardwareFrame'):
            from . import hardware
            with self.lock:
                hardware.release(self.state['hardwareFrame'])
                hardware.publish(self.state['hardwareFrame'])
                self.save()
        self.discover()
        if self.state.get('game') and native.alive(self.state['game']):
            try:
                self.tool('console', {'action': 'exec', 'command': 'qqq'}, timeout=4)
            except Exception as e:
                self.log('exit-request', error=str(e))
        roles = ('game', 'loader', 'mo2', 'vr')
        for role in roles:
            self.discover()
            owned = [p['identity'] for p in self.state['owned'] if p['role'] == role and native.alive(p['identity'])]
            for ident in owned:
                native.close(ident)
            end = time.monotonic() + (12 if owned else 0)
            while time.monotonic() < end and any(native.alive(i) for i in owned):
                time.sleep(.5)
            for ident in owned:
                if native.alive(ident):
                    self.log('forced-stop', role=role, pid=ident['pid'])
                    native.terminate(ident)
            end = time.monotonic() + 4
            while time.monotonic() < end and any(native.alive(i) for i in owned):
                time.sleep(.2)
            if any(native.alive(i) for i in owned):
                raise RuntimeError(f'Owned {role} process did not exit; refusing file restoration')
        self.collect()
        # New unrelated sessions block restore: never change settings under another game.
        busy = [p for p in native.processes() if p['name'].lower() in VR_NAMES | GAME_NAMES | {'modorganizer.exe'}]
        if busy:
            raise RuntimeError(f'Unexpected session after owned process shutdown: {busy}')
        with self.lock:
            self.state['restoringFiles'] = True
            self.save()
        errors = []
        for snapshot in reversed(self.state['snapshots']):
            path = Path(snapshot['path'])
            try:
                if snapshot['exists']:
                    backup = Path(snapshot['backup'])
                    if sha(backup) != snapshot['sha256']:
                        raise RuntimeError('Backup hash mismatch')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, path)
                    if sha(path) != snapshot['sha256']:
                        raise RuntimeError('Restored file hash mismatch')
                elif path.exists():
                    path.unlink()  # Only an individually registered file, never recursive deletion.
            except Exception as e:
                errors.append({'path': str(path), 'error': str(e)})
        self.state['restoreErrors'] = errors
        self.state['restored'] = False
        self.save()
        if errors:
            raise RuntimeError(f'Restoration incomplete: {errors}')
        profile = self.state.get('testProfile')
        if profile and Path(profile).exists():
            source = Path(profile).resolve()
            destination = (self.dir / 'test-profile').resolve()
            if source.parent != P.profiles.resolve() or source.name != 'Autotest-' + self.state['id'] or not destination.is_relative_to(RUNS.resolve()):
                raise RuntimeError('Refusing to archive a profile outside this run')
            if destination.exists():
                raise RuntimeError('Profile evidence archive already exists')
            shutil.move(str(source), str(destination))
            self.state['profileArchive'] = str(destination)
            self.save()
        self.state['restored'] = True
        self.save()
        self.log('restored', files=len(self.state['snapshots']))

    def report(self):
        status = self.state.get('result', 'blocked')
        lines = [f'# Skyrim VR run {self.state["id"]}', '', f'Result: **{status}**', '',
                 f'Profile: {self.state["preflight"]["profile"]}',
                 f'Restored: {self.state.get("restored", False)}',
                 f'Reason: {self.state.get("reason", "")}', '', '## Steps', '']
        for item in self.state.get('checks', []):
            lines.append(f'- {item["name"]}: {item["result"]}')
        (self.dir / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        atomic_json(self.dir / 'result.json', {k: self.state.get(k) for k in ('id', 'result', 'reason', 'restored', 'checks', 'restoreErrors', 'preflight')})

    def reopen_mo2(self):
        if self.state.get('reopenMO2') and self.state.get('restored'):
            self.state['launchIntents'] = {}
            self.state['reopenMO2'] = False
            self.save()
            subprocess.Popen([str(P.mo2_exe)], cwd=str(P.mo2),
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.log('original-mo2-reopened')


def guardian(directory):
    # Observe only; claim the same OS mutex after the owner dies or exits its scope.
    log = Path(directory) / 'guardian.log'
    last_health = None
    health_changed = time.monotonic()
    connection_failed = None
    since = 0
    while True:
        state = read_json(Path(directory) / 'state.json')
        if state.get('done'):
            return
        owner = state.get('runner')
        reason = 'Runner died or exceeded its deadline; independent guardian recovered the session'
        expired = time.time() > state.get('deadline', time.time() + 1) + 15 or time.time() - state.get('heartbeat', time.time()) > 35
        if state.get('game') and not state.get('phase', '').startswith('stop-and-restore'):
            if not native.alive(state['game']):
                reason, expired = 'Owned SkyrimVR process exited unexpectedly (CTD or external termination)', True
            else:
                try:
                    health = request(state['port'], 'api/health', timeout=2)
                    if health.get('pid') != state['game']['pid']:
                        reason, expired = 'DevBench process identity changed', True
                    connection_failed = None
                    marker = (health.get('frame'), health.get('lastTaskFrame'))
                    if marker != last_health:
                        last_health, health_changed = marker, time.monotonic()
                    elif health.get('pendingTasks', 0) > 0 and time.monotonic() - health_changed > 20:
                        reason, expired = 'Game frames and SKSE task completion stalled with pending work', True
                    with (Path(directory) / 'health.jsonl').open('a', encoding='utf-8') as f:
                        f.write(json.dumps({'at': time.time(), 'health': health}) + '\n')
                    events = request(state['port'], f'api/events?since={since}', timeout=2)
                    if events.get('events'):
                        with (Path(directory) / 'events.jsonl').open('a', encoding='utf-8') as f:
                            for event in events['events']:
                                f.write(json.dumps(event) + '\n')
                        since = max(e['seq'] for e in events['events'])
                except (OSError, ValueError, RuntimeError):
                    connection_failed = connection_failed or time.monotonic()
                    if time.monotonic() - connection_failed > 20:
                        reason, expired = 'DevBench connection lost while the owned game remains alive', True
        if native.alive(owner) and not expired:
            time.sleep(2)
            continue
        if native.alive(owner):
            native.terminate(owner)
        try:
            with native.SessionMutex():
                session = Session(directory)
                session.state.update(result='failed', reason=reason)
                session.save()
                try:
                    session.cleanup()
                except Exception:
                    log.write_text(traceback.format_exc(), encoding='utf-8')
                    session.state['reason'] += '; recovery incomplete, run recover before retrying'
                session.state['done'] = session.state.get('restored', False)
                session.save()
                session.report()
                session.reopen_mo2()
                return
        except RuntimeError:
            time.sleep(2)


def recover():
    # Recovery activates each abandoned session's durable environment only while
    # restoring that session. Historical runs must not overwrite the next run's
    # caller-selected configuration, staging list, tokens or runtime root.
    caller = copy.deepcopy(P.snapshot())
    scan_root = RUNS.resolve()
    try:
        with native.SessionMutex():
            directories = sorted(scan_root.glob('*'))
            for directory in directories:
                file = directory / 'state.json'
                if not file.exists():
                    continue
                state = read_json(file)
                if state.get('done'):
                    continue
                if native.alive(state.get('runner')):
                    raise Blocked('Runner is still alive; refusing recovery takeover')
                session = Session(directory, state)
                session.state.update(result='failed', reason='Recovered an abandoned session')
                session.cleanup()
                session.state['done'] = True
                session.save()
                session.report()
                session.reopen_mo2()
                configure(caller)
    finally:
        configure(caller)


def changes_reference_world(name, args):
    if name == 'game':
        return args.get('action') not in ('status', 'capabilities', 'save')
    if name == 'console':
        # Arbitrary console commands/batch files may perform a load. Invalidate
        # conservatively rather than attempting to parse an unsafe command text.
        return args.get('action') == 'exec'
    if name == 'papyrus' and args.get('action') == 'call':
        script, function = args.get('script'), args.get('function')
        return (script == 'Game' and function in ('LoadGame', 'StartNewGame', 'QuitToMainMenu')) or (script == 'ObjectReference' and function in ('MoveTo', 'MoveToNode', 'Delete', 'DeleteWhenAble'))
    return False


def guardian_command(directory):
    # A portable distribution started through absolute run.py need not be on the
    # child's default sys.path. Pass its verified package root as a plain argv.
    bootstrap = 'import sys; sys.path.insert(0, sys.argv[1]); from skyrim_autotest.cli import main; raise SystemExit(main(["guardian", sys.argv[2]]))'
    return [sys.executable, '-c', bootstrap, str(Path(__file__).resolve().parent.parent), str(Path(directory).resolve())]


def run(profile, scenario_file, fault=None, restart_idle_mo2=False, order=None, driver_backend='file', input_backend=None):
    scenario = read_json(scenario_file)
    from .scenarios import validate
    validate(scenario)
    fixture = scenario.get('fixture')
    if fixture:
        folder = P.fixture_dir or P.profiles / profile / 'saves'
        for ext in ('ess', 'skse'):
            file = folder / (fixture['saveStem'] + '.' + ext)
            if not file.is_file() or sha(file) != fixture[ext + 'Sha256']:
                raise Blocked('Missing or changed authorized fixture: ' + str(file))
    input_backend = input_backend or ('driver' if driver_backend == 'file' else 'devbench')
    if scenario.get('allowBackgroundVR') and (input_backend != 'driver' or driver_backend != 'file'):
        raise Blocked('allowBackgroundVR requires the physical file-adapter backend')
    if input_backend == 'driver' and driver_backend != 'file':
        raise Blocked('Physical frame control requires the file adapter driver')
    recover()
    with native.SessionMutex():
        info = preflight(profile, restart_idle_mo2)
        run_id = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6]
        directory = RUNS / run_id
        directory.mkdir(parents=True)
        state = {'id': run_id, 'runner': native.identity(os.getpid()), 'heartbeat': time.time(),
                 'deadline': time.time() + 180, 'snapshots': [], 'owned': [], 'launchIntents': {},
                 'preflight': info, 'checks': [], 'done': False, 'restored': False,
                 'configuration': P.snapshot(), 'scenario': scenario, 'scenarioHash': sha(scenario_file)}
        state['fault'] = fault
        source = directory / 'executor-source'
        source.mkdir()
        state['executorHashes'] = {}
        for file in [*Path(__file__).parent.glob('*.py'), *Path(__file__).parent.glob('*.h'), *Path(__file__).parent.glob('*.json')]:
            shutil.copy2(file, source / file.name)
            state['executorHashes'][file.name] = sha(file)
        state['driverBackend'] = driver_backend
        state['inputBackend'] = input_backend
        if order:
            state['order'] = order
        session = Session(directory, state)
        session.save()
        shutil.copy2(scenario_file, directory / 'scenario.json')
        subprocess.Popen(guardian_command(directory),
                         creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        heartbeat = threading.Thread(target=session.heartbeat, daemon=True)
        heartbeat.start()
        try:
            session.setup()
            if fault == 'after-setup':
                os._exit(99)  # Acceptance test: guardian must restore without finally.
            session.launch()
            if any(sha(Path(__file__).parent / name) != digest for name, digest in state['executorHashes'].items()):
                raise Blocked('Executor source changed during startup; rerun with stable sources')
            if fault == 'after-ready':
                os._exit(99)  # Recovery acceptance with the actual game and compositor alive.
            from .scenarios import execute
            # Common launch/loading is platform work, before subject actions.
            from .bootstrap import prepare_gameplay
            prepare_gameplay(session, scenario)
            execute(session, scenario)
            if any(sha(Path(__file__).parent / name) != digest for name, digest in state['executorHashes'].items()):
                raise Blocked('Executor source changed during the scenario; evidence needs a stable rerun')
            session.state['result'] = 'passed'
        except Blocked as e:
            session.state.update(result='blocked', reason=str(e))
        except Exception as e:
            session.state.update(result='failed', reason=str(e))
            session.log('exception', trace=traceback.format_exc())
        finally:
            try:
                session.cleanup()
            except Exception as e:
                session.state.update(result='failed', reason=session.state.get('reason', '') + '; cleanup: ' + str(e))
                session.log('cleanup-error', trace=traceback.format_exc())
            session.state['done'] = session.state.get('restored', False)
            session.save()
            session.report()
            session.finished.set()
            heartbeat.join(timeout=3)
            session.reopen_mo2()
        print(json.dumps({'run': str(directory), 'result': session.state['result'], 'restored': session.state['restored'], 'reason': session.state.get('reason', '')}), flush=True)
        return 0 if session.state['result'] == 'passed' and session.state['restored'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    for name in ('preflight', 'run'):
        item = subs.add_parser(name)
        item.add_argument('--profile', required=True)
        if name == 'run':
            item.add_argument('--scenario', type=Path, required=True)
            item.add_argument('--fault', choices=['after-setup', 'after-ready', 'while-held'])
            item.add_argument('--driver-backend', choices=['file', 'devkit'], default='file')
            item.add_argument('--input-backend', choices=['driver', 'devbench'], help='Compare injection with the same staged driver; default is physical driver control')
        item.add_argument('--restart-idle-mo2', action='store_true', help='Gracefully restart an idle MO2 and reopen it with its original settings after the test')
    subs.add_parser('recover')
    subs.add_parser('status')
    item = subs.add_parser('guardian')
    item.add_argument('directory', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'preflight':
        with native.SessionMutex():
            print(json.dumps(preflight(args.profile, args.restart_idle_mo2), indent=2))
    elif args.command == 'run':
        return run(args.profile, args.scenario, args.fault, args.restart_idle_mo2, driver_backend=args.driver_backend, input_backend=args.input_backend)
    elif args.command == 'guardian':
        guardian(args.directory)
    elif args.command == 'recover':
        recover()
    else:
        for file in sorted(RUNS.glob('*/result.json')):
            result = read_json(file)
            print(json.dumps({k: result.get(k) for k in ('id', 'result', 'reason', 'restored')}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Blocked, native.Busy) as e:
        print(json.dumps({'result': 'blocked', 'reason': str(e)}))
        sys.exit(2)
