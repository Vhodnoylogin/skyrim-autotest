"""Explicit bounded artifact collection, independent from file restoration."""
from pathlib import Path
import shutil


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
            before = sha(path)
            target = dest / name
            shutil.copy2(path, target)
            digest = sha(target)
            if digest != before or sha(path) != before:
                raise ValueError('Collection source changed during copy')
            manifest.append({'name': name, 'source': str(path), 'kind': kind,
                             'sha256': digest, 'bytes': target.stat().st_size,
                             'mtime': stat.st_mtime})
            if kind == 'skse-log': manifest[-1]['fresh'] = True
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
    capture = P.overwrite/'SKSE/Plugins/devbench/captures'
    if capture.exists():
        for path in capture.rglob(session.state['id']+'-*.png'):
            if path.resolve().is_relative_to(capture.resolve()): copy(path, path.name, 'capture')
    # Only explicitly selected restore targets may be exposed as output evidence.
    # Backup files/settings are never published by enumerating all snapshots.
    for index, path in enumerate(P.value.get('collected_files', [])):
        copy(path, f'output-{index:03d}-{Path(path).name}', 'declared-output', required=True)
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
            unexpected = set(dest.glob('before-restart-*')) - set(folders)
            for folder in unexpected: error(folder, 'Unreserved restart evidence segment')
        else:
            folders = sorted(dest.glob('before-restart-*'))
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
                    copy(source, folder.name+'--'+name, 'restart-artifact', required=True)
            except (OSError, ValueError, KeyError, TypeError) as exception: error(folder, exception)
    atomic_json(dest/'manifest.json', manifest)
    session.state.setdefault('collectionErrors', []).extend(errors)
    session.state['collectionComplete'] = not session.state['collectionErrors']
    session.save()
    session.log('evidence-collected', segment=segment, artifacts=manifest,
                complete=session.state['collectionComplete'], errors=errors)
    return not errors
