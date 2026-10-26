"""Collect exact owned large interactive results without truncating their data."""
from pathlib import Path
import re


def collect(session, copy_file):
    from .runner import sha
    rows = session.state.get('interactiveArtifacts', [])
    if not isinstance(rows, list) or len(rows) > 512:
        raise ValueError('Invalid interactive artifact registry')
    root = session.dir.resolve()
    folder = session.dir / 'interactive-results'
    if rows and (folder.is_symlink() or getattr(folder.lstat(), 'st_file_attributes', 0) & 0x400):
        raise ValueError('Interactive results directory is a link')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'commandId', 'path', 'sha256', 'bytes', 'format'}
                or not isinstance(row['commandId'], str) or not re.fullmatch('[0-9a-f]{32}', row['commandId'])
                or row['commandId'] in seen or row['format'] != 'json'
                or type(row['bytes']) is not int or not 0 < row['bytes'] <= 16 * 1024 * 1024
                or not isinstance(row['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Invalid or duplicate interactive artifact identity')
        seen.add(row['commandId'])
        path = Path(row['path'])
        expected = root / 'interactive-results' / (row['commandId'] + '.json')
        if not path.is_absolute() or path != expected or path.resolve() != expected:
            raise ValueError('Interactive artifact escapes the exact owned run path')
        stat = path.lstat()
        if (path.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400
                or not path.is_file() or stat.st_size != row['bytes'] or sha(path) != row['sha256']):
            raise ValueError('Interactive artifact bytes or identity changed')
        result = copy_file(path, 'interactive-' + row['commandId'] + '.json', 'interactive-result', True)
        if result is not None and (result['sha256'] != row['sha256'] or result['bytes'] != row['bytes']):
            raise ValueError('Collected interactive artifact differs from its durable receipt')
