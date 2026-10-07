"""Owned reusable profiles. All calls require the executor mutex and idle MO2.

The caller switches away before resetting files. Archives retain the same working
directory between runs; evidence is a separate immutable copy in each run.
"""
import hashlib
import json
from pathlib import Path
import shutil


def regular_tree(root):
    root = Path(root)
    if root.is_symlink() or (root.exists() and getattr(root.lstat(), 'st_file_attributes', 0) & 0x400):
        raise RuntimeError('Profile root is a link')
    for path in root.rglob('*'):
        if (path.is_symlink() or getattr(path.lstat(), 'st_file_attributes', 0) & 0x400
                or not path.resolve().is_relative_to(root.resolve())):
            raise RuntimeError('Profile tree contains a link or escaping path')


def digest(root):
    regular_tree(root)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def identity(source, profiles):
    source, profiles = Path(source).resolve(), Path(profiles).resolve()
    if source.parent != profiles or not source.is_dir():
        raise RuntimeError('Reusable profile source escapes configured profiles')
    regular_tree(source)
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(source.iterdir()) if p.is_file()}
    key = hashlib.sha256(json.dumps([str(source), files], sort_keys=True).encode()).hexdigest()
    return key, 'Autotest-Reuse-' + key[:20]


def paths(runtime, profiles, key, name):
    if (len(key) != 64 or any(c not in '0123456789abcdef' for c in key)
            or name != 'Autotest-Reuse-' + key[:20]):
        raise RuntimeError('Invalid reusable profile identity')
    home = Path(runtime).resolve() / 'reusable-profiles' / key
    target = Path(profiles).resolve() / name
    for path in (home.parent, home, home / 'profile', target):
        if path.exists():
            regular_tree(path)
    return home, target


def acquire(runtime, profiles, key, name, owner, atomic_json):
    home, target = paths(runtime, profiles, key, name)
    record = home / 'record.json'
    cached = home / 'profile'
    if target.exists():
        raise RuntimeError('Reusable profile is still mounted; recover its owning run first')
    previous = json.loads(record.read_text(encoding='utf-8')) if record.exists() else None
    if previous and previous.get('state') != 'archived':
        raise RuntimeError('Reusable profile has an unresolved owner')
    if cached.exists() and (not previous or digest(cached) != previous.get('files')):
        raise RuntimeError('Reusable profile archive integrity mismatch')
    if previous and not cached.exists():
        raise RuntimeError('Reusable profile archive is missing')
    home.mkdir(parents=True, exist_ok=True)
    lease = {'schemaVersion': 2, 'state': 'preparing', 'run': owner, 'key': key,
             'name': name, 'archiveBefore': previous['files'] if cached.exists() else None}
    atomic_json(record, lease)
    if cached.exists():
        shutil.move(str(cached), str(target))
        reused = True
    else:
        target.mkdir()
        reused = False
    atomic_json(record, {**lease, 'state': 'leased'})
    return target, reused


def reset(target, source, prior_evidence):
    """Keep directory identity, preserve old contents, then reset inactive files."""
    regular_tree(target)
    if any(p.is_dir() and p.name != 'saves' for p in Path(target).iterdir()):
        raise RuntimeError('Unexpected directory in reusable profile')
    if any(Path(target).iterdir()):
        shutil.copytree(target, prior_evidence)
        if digest(target) != digest(prior_evidence):
            raise RuntimeError('Previous profile evidence verification failed before reset')
    for path in Path(target).iterdir():
        if path.is_file():
            path.unlink()
        elif path.name == 'saves':
            # Checked tree and exact owned directory; no cross-shell deletion.
            shutil.rmtree(path)
    (Path(target) / 'saves').mkdir()
    for path in Path(source).iterdir():
        if path.is_file():
            shutil.copy2(path, Path(target) / path.name)


def release(runtime, profiles, key, name, owner, evidence, atomic_json):
    home, target = paths(runtime, profiles, key, name)
    record = home / 'record.json'
    value = json.loads(record.read_text(encoding='utf-8'))
    cached = home / 'profile'
    if value.get('run') != owner:
        raise RuntimeError('Reusable profile lease belongs to another run')
    if value.get('state') == 'archived' and not target.exists():
        if not cached.is_dir() or digest(cached) != value.get('files'):
            raise RuntimeError('Reusable profile archive integrity mismatch')
        return
    if value.get('state') == 'preparing' and value.get('schemaVersion') == 2:
        before = value.get('archiveBefore')
        if cached.exists():
            if target.exists() or before is None or digest(cached) != before:
                raise RuntimeError('Interrupted profile acquisition archive identity mismatch')
            if not Path(evidence).exists():
                shutil.copytree(cached, evidence)
            if digest(evidence) != before:
                raise RuntimeError('Interrupted profile acquisition evidence mismatch')
            atomic_json(record, {**value, 'state': 'archived', 'files': before,
                                 'acquisitionNeverMounted': True})
            return
        if not target.exists():
            if before is not None:
                raise RuntimeError('Previous reusable profile archive is missing')
            # Durable v2 intent proves this first acquisition never mounted.
            # Create only its exact inactive directory, then archive it normally.
            target.mkdir()
        if digest(target) != (before if before is not None else {}):
            raise RuntimeError('Interrupted profile acquisition target identity mismatch')
        value = {**value, 'state': 'leased'}
        atomic_json(record, value)
    if value.get('state') != 'leased':
        raise RuntimeError('Invalid reusable profile lease state')
    if target.exists():
        files = digest(target)
        if not Path(evidence).exists():
            shutil.copytree(target, evidence)
        if digest(evidence) != files:
            raise RuntimeError('Reusable profile evidence differs from current profile')
        if cached.exists():
            raise RuntimeError('Reusable profile archive destination already exists')
        # Write hashes before move, permitting recovery after a process death.
        atomic_json(record, {**value, 'files': files})
        shutil.move(str(target), str(cached))
    elif cached.exists() and value.get('files') == digest(cached):
        files = value['files']
    else:
        raise RuntimeError('Reusable profile missing during recovery')
    atomic_json(record, {**value, 'state': 'archived', 'files': files})
