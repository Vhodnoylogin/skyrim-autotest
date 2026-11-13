"""Read-only exit evidence selection; an OS code never classifies the exit cause."""
from copy import deepcopy


def _identity(value):
    return (isinstance(value, dict) and set(value) == {'pid', 'birth', 'path'}
            and type(value['pid']) is int and 0 < value['pid'] <= 0xffffffff
            and type(value['birth']) is int and value['birth'] > 0
            and isinstance(value['path'], str) and bool(value['path']))


def terminal_exit_observation(observations, expected_identity):
    """Select a retained-handle exit for exactly one recorded process identity.

    Later unavailable recovery reads do not erase an earlier known exit. Different
    PID/birth/path records are never merged. Conflicting trusted codes refuse
    selection. The raw observations and all termination context stay unchanged.
    """
    expected = expected_identity
    if not isinstance(observations, list) or not _identity(expected):
        return None
    selected = None
    for row in reversed(observations):
        if (not isinstance(row, dict) or type(row.get('schemaVersion')) is not int or row['schemaVersion'] != 1
                or row.get('status') != 'exited' or row.get('identityVerified') is not True
                or row.get('handleRetained') is not True or row.get('exitCodeAvailable') is not True
                or not _identity(row.get('identity')) or not _identity(row.get('expectedIdentity'))
                or row.get('identity') != expected or row.get('expectedIdentity') != expected):
            continue
        code = row.get('exitCode')
        if (type(code) is not int or not 0 <= code <= 0xffffffff
                or row.get('exitCodeHex') != f'0x{code:08X}'):
            continue
        if selected is not None and selected['exitCode'] != code:
            return None
        if selected is None:
            selected = row
    return deepcopy(selected)
