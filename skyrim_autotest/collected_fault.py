"""Summarize a fresh, hash-verified CrashLogger record collected by this run."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re


_NAME = re.compile(r'crash-\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.log')
_LOGGER = re.compile(r'^CrashLogger(?:SSE)? v[^\r\n]+$', re.M)
_PID = re.compile(r'^\s*Process ID: ([0-9]+)\s*$', re.M)
_LOCATION = r'([a-zA-Z0-9_.-]+\.(?:dll|exe))\+([a-fA-F0-9]{1,16})'
_EXCEPTION = re.compile(r'^Unhandled exception "(EXCEPTION_[A-Z0-9_]+)" at 0x[a-fA-F0-9]+\s+' + _LOCATION,
                        re.M | re.I)
_PROBABLE = re.compile(r'^\s*\[\s*\d+\]\[P\]\s+0x[a-fA-F0-9]+\s+' + _LOCATION, re.M | re.I)
_ENTRY_LIMIT = 2 * 1024 * 1024
_FILETIME_UNIX_SECONDS = 11644473600


def _verified_bytes(path, size_max, expected):
    with path.open('rb') as stream:
        raw = stream.read(size_max + 1)
    if len(raw) <= size_max and hashlib.sha256(raw).hexdigest() == expected:
        return raw
    return b''


def _position(module, offset):
    return {'module': module, 'offsetHex': f'0x{int(offset, 16):X}'}


def _record(directory, entry, pid, start, end):
    if not isinstance(entry, dict) or not isinstance(name := entry.get('name'), str) or not _NAME.fullmatch(name):
        return None
    modified, size = entry.get('mtime'), entry.get('bytes')
    if (entry.get('kind') != 'skse-log' or entry.get('fresh') is not True
            or type(modified) not in (float, int) or not start <= modified <= end
            or type(size) is not int or not 0 < size <= _ENTRY_LIMIT):
        return None
    path = (directory / name).resolve(strict=True)
    if path.parent != directory:
        return None
    raw = _verified_bytes(path, size, entry.get('sha256'))
    if len(raw) != size:
        return None
    text = raw.decode('utf-8-sig', errors='replace').replace('\r\n', '\n')
    ids = _PID.findall(text)
    exception = _EXCEPTION.search(text)
    if ids != [str(pid)] or not _LOGGER.search(text[:1024]) or exception is None:
        return None
    kind, module, offset = exception.groups()
    frames = [_position(*row) for row in _PROBABLE.findall(text)[:8]]
    return {'artifact': name, 'exception': kind, **_position(module, offset), 'probableFrames': frames}


def collected_game_faults(state, directory, termination):
    if termination is None or termination['exitCode'] == 0 or state.get('collectionComplete') is not True:
        return []
    checkpoint = state.get('finalCollectionCheckpoint') or {}
    digest = checkpoint.get('manifestSha256')
    if not digest or not termination.get('firstExitObservedAtUtc'):
        return []
    try:
        exited = datetime.fromisoformat(termination['firstExitObservedAtUtc'])
        if exited.tzinfo is None:
            return []
        birth = termination['identity']['birth'] / 10_000_000 - _FILETIME_UNIX_SECONDS
        earliest = max(birth, exited.timestamp() - 90)
        latest = exited.timestamp() + 30
        evidence = (Path(directory) / 'evidence').resolve(strict=True)
        manifest = json.loads(_verified_bytes(evidence / 'manifest.json', _ENTRY_LIMIT, digest))
    except (OSError, UnicodeError, ValueError, OverflowError):
        return []
    faults = []
    for entry in manifest if isinstance(manifest, list) else ():
        try:
            record = _record(evidence, entry, termination['identity']['pid'], earliest, latest)
        except OSError:
            continue
        if record is not None:
            faults.append(record)
    return faults
