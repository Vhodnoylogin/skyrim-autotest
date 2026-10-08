"""Explicit bounded artifact collection, independent from file restoration."""
from pathlib import Path
import shutil


def snapshot_log(path, target):
    """Pin a bounded twice-read prefix of one open live log, allowing append.

    No atomic snapshot/history claim: subsequent bytes and intervening writes
    are unobserved. Rewrite, truncation or path replacement still fail.
    """
    import os,hashlib
    selected=path.lstat()
    with path.open('rb',buffering=0) as source:
        before=os.fstat(source.fileno())
        if (selected.st_dev,selected.st_ino)!=(before.st_dev,before.st_ino):
            raise ValueError('Live log path replaced before open')
        if before.st_size>64*1024*1024:raise ValueError('Collection artifact exceeds64MiB bound')
        length=before.st_size
        def transfer(destination=None):
            remaining=length;digest=hashlib.sha256()
            while remaining:
                data=source.read(min(1024*1024,remaining))
                if not data:raise ValueError('Live log truncated during prefix collection')
                remaining-=len(data);digest.update(data)
                if destination is not None:destination.write(data)
            return digest.hexdigest()
        with target.open('wb') as destination:copied=transfer(destination)
        source.seek(0);verified=transfer()
        after=os.fstat(source.fileno());current=path.lstat()
        if path.is_symlink() or getattr(current,'st_file_attributes',0)&0x400:
            raise ValueError('Live log path became a link during collection')
        if (current.st_dev,current.st_ino)!=(before.st_dev,before.st_ino):
            raise ValueError('Live log path replaced during collection')
        if after.st_size<length or current.st_size<length or copied!=verified:
            raise ValueError('Live log prefix changed during collection')
        return {'mode':'two-pass-verified-prefix','byteStart':0,'byteEndExclusive':length,
                'sourceSizeAtOpen':length,'sourceSizeAfterVerification':after.st_size,
                'sourceSizeAtPathRecheck':current.st_size,'prefixSha256':copied,
                'tailOutsideSnapshot':max(after.st_size,current.st_size)>length,
                'fileIdentity':{'device':before.st_dev,'inode':before.st_ino},
                'atomicSnapshot':False,'completeRecordBoundaryProven':False,
                'basis':'same open file prefix read twice identically; later tail and intervening writes unobserved'}


def collect(session, segment=None):
    from .runner import P, atomic_json, read_json, sha
    import re
    from .restart_budget import segment_number
    if segment is not None:
        segment_number(session.state, segment)
    dest = session.dir / 'evidence'
    if segment is not None: dest /= segment
    if segment is not None and dest.exists():
        raise ValueError('Restart evidence segment already exists; no overwrite')
    dest.mkdir(parents=True, exist_ok=True)
    manifest, errors, names = [], [], set()

    def error(path, exception):
        value = {'path': str(path), 'error': str(exception), 'segment': segment}
        errors.append(value)
        session.log('collect-error', **value)

    def copy(path, name, kind, required=False):
        path = Path(path)
        try:
            if not path.exists() and not required: return
            stat = path.lstat()
            if (not path.is_file() or path.is_symlink()
                    or getattr(stat, 'st_file_attributes', 0) & 0x400):
                raise ValueError('Collection source is not a regular unlinked file')
            if stat.st_size > 64*1024*1024:
                raise ValueError('Collection artifact exceeds64MiB bound')
            if name.casefold() in names:
                raise ValueError('Duplicate collection artifact name')
            names.add(name.casefold())
            target = dest / name
            snapshot=None
            if kind in ('skse-log','steamvr-log','bridge-log'):
                snapshot=snapshot_log(path,target)
                digest=sha(target)
                if digest!=snapshot['prefixSha256']:raise ValueError('Collected log target changed after verification')
            else:
                before = sha(path)
                shutil.copy2(path, target)
                digest = sha(target)
                if digest != before or sha(path) != before:
                    raise ValueError('Collection source changed during copy')
            manifest.append({'name': name, 'source': str(path), 'kind': kind,
                             'sha256': digest, 'bytes': target.stat().st_size,
                             'mtime': stat.st_mtime})
            if kind == 'skse-log': manifest[-1]['fresh'] = True
            if snapshot is not None:manifest[-1]['snapshot']=snapshot
            return manifest[-1]
        except (OSError, ValueError) as exception:
            error(path, exception)

    launched = session.state.get('launchIntents', {}).get('game', {}).get('at')
    for path in P.skse_logs.glob('*.log'):
        try:
            if launched and path.stat().st_mtime >= launched-1:
                copy(path, path.name, 'skse-log')
        except OSError as exception: error(path, exception)
    try:
        steam = Path(read_json(session.state['preflight']['vrpaths'])['log'][0])
        for name in ('vrserver.txt', 'vrcompositor.txt', 'vrmonitor.txt'):
            copy(steam/name, name, 'steamvr-log')
    except (OSError, ValueError, KeyError, IndexError) as exception:
        error('SteamVR log metadata', exception)
    copy(P.mo2/'plugins/mo2aibridge/mo2aibridge.log', 'mo2aibridge.log', 'bridge-log')
    if segment is None and 'boundaryCollection' in session.state:
        from .boundary_collection import finalize
        finalize(session)
        copy(session.dir/'boundary-collection-plan.json', 'boundary-collection-plan.json', 'boundary-plan', required=True)
        copy(session.dir/'boundary-collection.json', 'boundary-collection.json', 'boundary-accounting', required=True)
        for record in session.state['boundaryCollection']['requests']:
            entry = record.get('evidence')
            if entry:
                name = entry.get('name', '')
                if name != 'boundary-' + record['id'] + '.json':
                    error(name, 'Boundary evidence name mismatch')
                    continue
                artifact = copy(session.dir/name, name, 'boundary-response', required=True)
                if artifact is not None and artifact['sha256'] != entry.get('sha256'):
                    error(name, 'Boundary evidence digest mismatch')
    if segment is None:
        from .actor_scene import collect as collect_actor_captures
        try:collect_actor_captures(session,copy)
        except (OSError,ValueError,KeyError,TypeError) as exception:error('actor contact captures',exception)
    capture = P.overwrite/'SKSE/Plugins/devbench/captures'
    if capture.exists():
        for path in capture.rglob(session.state['id']+'-*.png'):
            if path.resolve().is_relative_to(capture.resolve()): copy(path, path.name, 'capture')
    # Only explicitly selected restore targets may be exposed as output evidence.
    # Backup files/settings are never published by enumerating all snapshots.
    for index, path in enumerate(P.value.get('collected_files', [])):
        copy(path, f'output-{index:03d}-{Path(path).name}', 'declared-output', required=True)
    for index, record in enumerate(session.state.get('fixtureSettingsWrites',{}).values()):
        path=Path(record['path'])
        allowed=({str(Path(p).resolve()).casefold() for p in P.value.get('extra_files',[])} if not record.get('profileLocal')
                 else {str((Path(session.state['testProfile'])/binding['handednessProfileIni']).resolve()).casefold()
                       for binding in P.value.get('subject_state_bindings',{}).values() if 'handednessProfileIni' in binding})
        if str(path.resolve()).casefold() not in allowed:error(path,'Fixture setting output not explicitly configured')
        else:
            entry=copy(path,f'fixture-settings-{index:03d}-{path.name}','fixture-settings',required=True)
            if entry is not None:
                entry.update(writtenSha256=record.get('writtenSha256',record['sha256']),
                             expectedCurrentSha256=record['sha256'],
                             matchesLastVerifiedBytes=entry['sha256']==record['sha256'],
                             nativeOutputCorroborated=entry['sha256']==record.get('nativeOutput',{}).get('sha256'))
                if not entry['matchesLastVerifiedBytes']:
                    session.log('fixture-setting-output-mismatch',path=str(path),
                                expected=record['sha256'],actual=entry['sha256'],
                                collected=True,writerIdentity='unknown')
    if segment is None:
        # The old consumer deliberately accepts only flat, safe artifact names.
        # Project declared restart artifacts into this manifest without weakening it.
        if 'ownedGameRestartBudget' in session.state:
            from .restart_budget import verify
            maximum = verify(session.state)['maximum']
            used = session.state.get('ownedGameRestartCount', 0)
            if type(used) is not int or not 0 <= used <= maximum:
                raise ValueError('Invalid reserved restart count during collection')
            folders = [dest/f'before-restart-{i}' for i in range(1, used+1)]
            unexpected = {p for p in dest.glob('before-restart-*') if p.is_dir() or p.is_symlink()} - set(folders)
            for folder in unexpected: error(folder, 'Unreserved restart evidence segment')
        else:
            folders = sorted(p for p in dest.glob('before-restart-*') if p.is_dir() or p.is_symlink())
        for folder in folders:
            try:
                segment_number(session.state, folder.name)
                if folder.is_symlink() or getattr(folder.lstat(), 'st_file_attributes', 0) & 0x400:
                    raise ValueError('Restart evidence directory is a link')
                entries = read_json(folder/'manifest.json')
                if not isinstance(entries, list): raise ValueError('Invalid restart collection manifest')
                for entry in entries:
                    name = entry.get('name')
                    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_. -]+', name) or name in ('.', '..'):
                        raise ValueError('Invalid restart collection artifact name')
                    source = folder/name
                    if sha(source) != entry.get('sha256'):
                        raise ValueError('Restart artifact hash mismatch')
                    projected=copy(source, folder.name+'--'+name, 'restart-artifact', required=True)
                    if projected is not None and 'snapshot' in entry:
                        projected['sourceSnapshot']=entry['snapshot']
            except (OSError, ValueError, KeyError, TypeError) as exception: error(folder, exception)
    atomic_json(dest/'manifest.json', manifest)
    session.state.setdefault('collectionErrors', []).extend(errors)
    session.state['collectionComplete'] = not session.state['collectionErrors']
    session.save()
    session.log('evidence-collected', segment=segment, artifacts=manifest,
                complete=session.state['collectionComplete'], errors=errors)
    return not errors
