"""Opt-in owned-profile save/load. Mutations once; actual completion evidence."""
import copy
import hashlib
import os
from pathlib import Path
import time


def prepare_required_mapping_probe(session, target):
    """Capability opt-in alone must not require a save in a no-save new game."""
    scenario = session.state['scenario']
    save_actions = {'save_game', 'load_game', 'restart_game'}
    steps = [*scenario.get('steps', []), *scenario.get('postSteps', [])]
    required = bool(scenario.get('fixture')) or any(
        step.get('tool') == 'platform' and step.get('args', {}).get('operation') == 'input.perform'
        and step['args'].get('request', {}).get('action') in save_actions for step in steps)
    session.state['ownedSaveMappingRequired'] = required
    session.save()
    if required:
        prepare_mapping_probe(session, target)
    else:
        session.log('owned-save-mapping-probe-not-needed',
                    reason='No pinned fixture or declared owned save/load/restart operations; opt-in capability alone is not a fixture requirement',
                    runtimeSaveProtectionUnchanged=True)


def prepare_mapping_probe(session, target):
    """Stage a unique valid ESS before MO2 constructs the process's USVFS map."""
    import uuid
    state=session.state
    if state.get('game') or state.get('launchIntents',{}).get('game'):
        raise ValueError('Save mapping probe must precede game launch')
    if target.resolve()!=Path(state['ownedSaveDirectory']).resolve():
        raise ValueError('Mapping probe outside owned save directory')
    fixture=state.get('fixture',{})
    stem=fixture.get('saveStem','')
    if not stem or Path(stem).name!=stem or '/' in stem or '\\' in stem:
        raise ValueError('Pinned owned fixture needed for save mapping challenge')
    source=target/(stem+'.ess')
    if (not source.is_file() or source.is_symlink() or getattr(source.lstat(),'st_file_attributes',0)&0x400 or
            source.stat().st_size>256*1024*1024):
        raise ValueError('Owned mapping fixture unavailable')
    contents=source.read_bytes()
    digest=hashlib.sha256(contents).hexdigest()
    if digest!=fixture.get('essSha256') or not contents.startswith(b'TESV_SAVEGAME'):
        raise ValueError('Owned mapping fixture hash/header mismatch')
    marker='Autotest_Map_'+uuid.uuid4().hex
    challenge=target/(marker+'.ess')
    with challenge.open('xb') as stream:stream.write(contents)
    state['ownedSaveMappingProbe']={'stem':marker,'path':str(challenge.resolve()),'sha256':digest,
                                   'preparedAt':time.time(),'preparedBeforeLaunch':True}
    session.save()
    session.log('owned-save-mapping-probe-prepared',probe=state['ownedSaveMappingProbe'])


def verify_mo2_save_mapping(backend, target, observed):
    """Read the prelaunch nonce through the game's default virtual directory."""
    import configparser
    import re
    state=backend.s.state
    settings=configparser.ConfigParser(interpolation=None)
    settings.read(target.parent/'settings.ini',encoding='utf-8-sig')
    if not all(settings.getboolean('General',key,fallback=False) for key in ('LocalSaves','LocalSettings')):
        raise ValueError('MO2 save mapping requires owned local saves/settings')
    probe=state.get('ownedSaveMappingProbe',{})
    marker=probe.get('stem','')
    if (not re.fullmatch(r'Autotest_Map_[0-9a-f]{32}',marker) or probe.get('preparedBeforeLaunch') is not True or
            Path(probe.get('path','')).resolve()!=(target/(marker+'.ess')).resolve()):
        raise ValueError('Owned prelaunch save mapping probe unavailable')
    challenge=target/(marker+'.ess')
    if challenge.is_symlink() or hashlib.sha256(challenge.read_bytes()).hexdigest()!=probe['sha256']:
        raise ValueError('Owned mapping probe changed')
    expected=Path(state['configuration']['skse_logs']).parent / observed
    during=backend.call('game',{'action':'list','filter':marker,'limit':2,'detail':True})
    if (Path(during.get('dir','')).resolve()!=expected.resolve() or during.get('truncated') is not False or
            during.get('count')!=1 or during.get('returned')!=1 or during.get('metaAvailable') is not True or
            not isinstance(during.get('saves'),list) or [p.get('name') for p in during['saves']]!=[marker] or
            not isinstance(during['saves'][0].get('meta'),dict)):
        raise ValueError('Native MO2 save alias cannot read exact prelaunch owned probe')
    backend.s.log('owned-save-virtual-mapping-verified',ownedDirectory=str(target),nativeSetting=observed,
                  logicalDirectory=str(expected),probe=probe,nativeEnumeration=during,
                  basis='prelaunch unique owned pinned ESS enumerated/header-read through default game directory; observed USVFS mapping, not atomic filesystem contract')


def directory(backend):
    from .profile_cache import regular_tree
    state = backend.s.state
    if state.get('configuration', {}).get('allow_owned_save_load') is not True:
        raise ValueError('Owned save/load is not enabled for this executor')
    profile = Path(state['testProfile'])
    expected = Path(state['configuration']['profiles']).resolve() / state['testProfileName']
    if (not state['testProfileName'].startswith('Autotest-') or profile.resolve() != expected or
            profile.name == state['preflight']['profile']):
        raise ValueError('Save scope is not the owned disposable profile')
    regular_tree(profile)
    target = profile / 'saves'
    if Path(state['ownedSaveDirectory']).resolve() != target.resolve() or not target.is_dir():
        raise ValueError('Owned save directory mismatch')
    observed = backend.pap('Utility', 'GetINIString', ['sLocalSavePath:General'])
    if isinstance(observed,str) and observed.casefold().replace('/','\\')=='__mo_saves\\':
        verify_mo2_save_mapping(backend,target,observed)
    elif not isinstance(observed, str) or Path(observed).resolve() != target.resolve():
        raise ValueError('Native save path does not match owned disposable directory')
    return target


def pair(directory, stem):
    """Hash both quiescent files; Windows handles deny concurrent writers."""
    from contextlib import ExitStack
    import re
    if not isinstance(stem, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', stem):
        raise ValueError('Owned save stem is not a flat safe name')
    paths = [directory / (stem + '.' + ext) for ext in ('ess', 'skse')]
    if any(not p.is_file() for p in paths):
        return None
    result = {}
    try:
        with ExitStack() as stack:
            for p in paths:
                if p.is_symlink() or getattr(p.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Save file is a link')
                if os.name == 'nt':
                    import ctypes as c
                    import msvcrt
                    from ctypes import wintypes as w
                    kernel = c.WinDLL('kernel32', use_last_error=True)
                    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
                    kernel.CreateFileW.restype = w.HANDLE
                    kernel.CloseHandle.argtypes = [w.HANDLE]
                    handle = kernel.CreateFileW(str(p), 0x80000000, 0, None, 3, 0x80, None)
                    if handle == c.c_void_p(-1).value:
                        error = c.get_last_error()
                        if error in (32, 33): return None
                        raise c.WinError(error)
                    try:
                        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                    except Exception:
                        kernel.CloseHandle(handle)
                        raise
                    stream = stack.enter_context(os.fdopen(fd, 'rb'))
                else:
                    stream = stack.enter_context(p.open('rb'))
                # Keep the first file handle locked while hashing the second.
                digest = hashlib.sha256()
                header, size = b'', 0
                while chunk := stream.read(1024*1024):
                    if not size: header = chunk[:13]
                    size += len(chunk)
                    if size > 256*1024*1024: raise ValueError('Owned save exceeds bounded size')
                    digest.update(chunk)
                if not header.startswith(b'TESV_SAVEGAME' if p.suffix == '.ess' else b'SKSE'):
                    raise ValueError('Owned save/cosave header invalid')
                result[p.suffix[1:]] = {'sha256': digest.hexdigest(), 'bytes': size}
    except FileNotFoundError:
        return None
    return result


class Events:
    def __init__(self, backend, cursor):
        self.backend, self.cursor = backend, cursor
    def read(self):
        from .runner import request
        b, collected = self.backend, []
        for attempt in range(3):
            envelope = request(b.s.state['port'], 'api/events?since=' + str(self.cursor), timeout=min(3, b.remaining()))
            events, head = envelope.get('events'), envelope.get('headSeq')
            if not isinstance(events, list) or type(head) is not int or head < self.cursor:
                raise ValueError('Owned save/load lifecycle stream reset or malformed')
            for event in events:
                if not isinstance(event, dict) or type(event.get('seq')) is not int or event['seq'] != self.cursor+1:
                    raise ValueError('Owned save/load lifecycle event gap')
                self.cursor = event['seq']
                collected.append(event)
            if head < self.cursor: raise ValueError('Lifecycle event exceeds producer head')
            if head == self.cursor: return collected
        raise ValueError('Unseen owned lifecycle head could not be reconciled')


def lifecycle(event):
    data = event.get('data', {})
    return data.get('event', data.get('type')) if event.get('topic') == 'lifecycle' and isinstance(data, dict) else None


class BoundSession:
    def __init__(self, backend): self.backend = backend
    def __getattr__(self, name): return getattr(self.backend.s, name)
    def tool(self, name, args, timeout=12, deadline=None):
        return self.backend.s.tool(name, args, timeout=min(timeout, self.backend.remaining()), deadline=self.backend.end)
    def phase(self, name, seconds=120):
        return self.backend.s.phase(name,min(seconds,self.backend.remaining()))


def saved(backend, tag):
    target = directory(backend)
    record = backend.s.state.get('ownedSaves', {}).get(tag)
    if not record or record.get('completed') is not True:
        raise ValueError('No completed attempt-owned save for this tag')
    actual = pair(target, record['stem'])
    if actual is None or actual != record['files']:
        raise ValueError('Completed owned save changed or is still being written')
    return record


def perform(backend, req):
    b, state, tag = backend, backend.s.state, req['saveTag']
    target = directory(b)
    records = state.setdefault('ownedSaves', {})
    if req['action'] == 'save_game':
        if tag in records or len(records) >= 8:
            raise ValueError('Owned save tag already used or limit8 reached; no replay')
        marker = 'Autotest_' + state['id'].replace('-', '_') + '_' + tag.replace('-', '_')
        if any(target.glob(marker + '*')):
            raise ValueError('Attempt-owned save name already exists')
        record = {'requestedStem': marker, 'completed': False, 'ownedByAttempt': True}
        records[tag] = record
        events = Events(b, b.s.capture_probe_cursor())
        b.s.save()
        b.call('game', {'action': 'save', 'name': marker})
        saw_save, last, stable = False, None, None
        while True:
            for event in events.read():
                name = lifecycle(event)
                if name in ('preLoadGame', 'postLoadGame', 'newGame'):
                    raise ValueError('World changed while saving')
                if name == 'saveGame': saw_save = True
            matches = [p for p in target.glob(marker + '*.ess')
                       if p.stem == marker or p.stem.startswith(marker + '_')]
            if len(matches) > 1: raise ValueError('Ambiguous attempt-owned save stem')
            current = pair(target, matches[0].stem) if matches else None
            if saw_save and current is not None:
                stable = stable if current == last and stable is not None else time.monotonic()
                if time.monotonic() - stable >= 1:
                    record.update(stem=matches[0].stem, completed=True, files=current,
                                  eventCursor=events.cursor, completionBasis='SKSE save event + stable exclusive-readable owned ESS/SKSE pair')
                    b.s.save()
                    return observe(b, {'observation':'save.state', 'saveTag':tag})
            else: stable = None
            last = current
            b.pause(.2)
    record = saved(b, tag)
    cursor = b.s.capture_probe_cursor()
    previous_game = copy.deepcopy(state['game'])
    old_tags = sorted(state.get('platformReferences', {}))
    state.setdefault('invalidatedReferenceTags', []).extend(old_tags)
    state['platformReferences'] = {}
    b.s.invalidate_probe_reference('owned save load requested')
    state['gameplayBootstrap']['completed'] = False
    transition = {'saveTag':tag, 'completed':False, 'beforeGame':previous_game,
                  'oldReferenceTags':old_tags, 'cursorBefore':cursor, 'probeInvalidatedAtLoad':state.get('probeObjectLive') is False}
    state['ownedLoadTransition'] = transition
    b.s.save()
    if state.get('hardwareFrame'): b.call('driver', {'action':'release'})
    restarting=req['action']=='restart_game'
    if restarting:
        from .game_restart import start
        from .bootstrap import prepare_startup_screen
        start(b)
        prepare_startup_screen(BoundSession(b), deadline=b.end)
        saved(b,tag) # Reverify the exact owned pair and native mapping in the new process.
        cursor=b.s.capture_probe_cursor()
        transition['cursorBefore']=cursor
        transition['restartRequested']=True
        b.s.save()
        BoundSession(b).phase('gameplay-owned-restart-load',b.remaining())
    b.call('game', {'action':'load', 'name':record['stem'], 'dir':str(target)})
    events = Events(b, cursor)
    saw_pre, completed_events = False, []
    while True:
        for event in events.read():
            name = lifecycle(event)
            if name == 'newGame': raise ValueError('Unexpected New Game during owned load')
            if name == 'preLoadGame':
                if saw_pre: raise ValueError('Repeated load transition; provenance ambiguous')
                saw_pre = True
                completed_events.append(event)
            if name == 'postLoadGame':
                if not saw_pre or len(completed_events) != 1: raise ValueError('Owned load completion lacks unique ordered preLoadGame')
                completed_events.append(event)
        if len(completed_events) == 2: break
        b.pause(.2)
    from .bootstrap import wait_gameplay_ready
    proxy = BoundSession(b)
    cell = state.get('scenario', {}).get('cell')
    scene, menus = wait_gameplay_ready(proxy, cell, False, deadline=b.end)
    if (state['game'] != previous_game)!=restarting:
        raise ValueError('Owned load/restart process identity does not match requested transition')
    state['gameplayBootstrap'].update(completed=True, scene=scene, menus=menus, loadedOwnedSave=tag)
    from .platform import initialize_controllers
    initialize_controllers(proxy, state.get('configuration', {}))
    b.remaining()
    state['ownedWorldGeneration'] = state.get('ownedWorldGeneration', 0)+1
    transition.update(completed=True, afterGame=copy.deepcopy(state['game']), cursor=events.cursor,
                      events=completed_events, worldGeneration=state['ownedWorldGeneration'], scene=scene)
    if restarting:
        state['gameRestartTransition'].update(completed=True,stage='completed',afterGame=copy.deepcopy(state['game']))
    b.s.save()
    return observe(b, {'observation':'lifecycle.state','afterSaveTag':tag})


def observe(backend, req):
    b, state = backend, backend.s.state
    if req['observation'] == 'save.state':
        record = saved(b, req['saveTag'])
        return {'save':{'completed':True, 'ownedByAttempt':True,
                        'essSha256':record['files']['ess']['sha256'], 'skseSha256':record['files']['skse']['sha256'],
                        'stem':record['stem'], 'basis':record['completionBasis']}}
    directory(b)
    transition = state.get('ownedLoadTransition', {})
    if transition.get('completed') is not True or transition.get('saveTag') != req['afterSaveTag']:
        raise ValueError('No completed matching owned load transition')
    events = Events(b, transition['cursor'])
    if any(lifecycle(event) in ('preLoadGame','postLoadGame','newGame') for event in events.read()):
        raise ValueError('Later world transition invalidates owned load evidence')
    transition['cursor'] = events.cursor
    scene = b.call('inspect', {'kind':'scene'})
    menus = b.call('menu', {'action':'list','includeFlags':True})
    from .platform import menus_block_gameplay
    ready = (scene.get('playerLoaded') is True and scene.get('cell', {}).get('editorId') not in (None,'VRPlayroom01')
             and not menus_block_gameplay(menus) and state.get('gameplayBootstrap',{}).get('completed') is True)
    invalidated = (transition.get('probeInvalidatedAtLoad') is True and
                   all(tag not in state.get('platformReferences', {}) and
                       tag in state.get('invalidatedReferenceTags', []) for tag in transition['oldReferenceTags']))
    b.s.save()
    return {'lifecycle':{'worldReady':ready, 'pidChanged':state['game'] != transition['beforeGame'],
                         'generationChanged':len(transition['events']) == 2,
                         'oldReferenceTagsInvalidated':invalidated,
                         'worldGeneration':transition['worldGeneration'], 'invalidatedTags':transition['oldReferenceTags'],
                         'basis':'ordered native pre/postLoadGame and common gameplay readiness; executor epoch, not atomic engine generation'}}
