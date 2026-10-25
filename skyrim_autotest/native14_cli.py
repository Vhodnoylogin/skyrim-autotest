"""Read-only validation of an already collected native14 JSON file.

This command never contacts a process or promotes file contents to live evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _constant(value):
    raise ValueError('Non-JSON numeric constant: ' + value)


def _parse(data):
    try:
        return json.loads(data, object_pairs_hook=_unique, parse_constant=_constant)
    except RecursionError:
        raise ValueError('JSON nesting exceeds the snapshot parser limit') from None


def _read(path):
    with path.open('rb') as stream:
        contents = stream.read(MAX_BYTES + 1)
    if len(contents) > MAX_BYTES:
        raise ValueError('Native14 snapshot exceeds the 2 MiB file-validation limit')
    return contents, _parse(contents.decode('utf-8-sig'))


def main(argv=None):
    parser = argparse.ArgumentParser(prog='skyrim-autotest validate-native14')
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--expected-pid', type=int, required=True)
    parser.add_argument('--max-age-micros', type=int, required=True)
    parser.add_argument('--measure', action='append', default=[])
    parser.add_argument('--haptics-baseline', type=Path, help='Actual pre-action snapshot for an event interval')
    args = parser.parse_args(argv)
    if len(args.measure) > 256 or len(set(args.measure)) != len(args.measure):
        raise ValueError('Choose at most 256 distinct measurement paths')
    contents, raw = _read(args.snapshot)
    from .native14 import validate, measurement, new_haptic_requests
    checked = validate(raw, expected_pid=args.expected_pid,
                       max_age_micros=args.max_age_micros)
    result = {
        'schemaVersion': 1,
        'mode': 'offline-native14-validation',
        'observationValidation': 'valid',
        'inputSha256': hashlib.sha256(contents).hexdigest(),
        'processId': checked['processId'],
        'token': checked['frame']['token'],
        'publications': checked['publications'],
        'measurements': {path: measurement(checked, path) for path in args.measure},
        'gameTestingPerformed': False,
        'claims': {'scene': 'scene_graph_state', 'haptics': 'native_requests',
                   'renderedPixels': 'unobserved', 'hardwareDelivery': 'unobserved',
                   'equipmentActions': 'unobserved'},
    }
    if args.haptics_baseline is not None:
        baseline_contents, baseline_raw = _read(args.haptics_baseline)
        baseline = validate(baseline_raw, expected_pid=args.expected_pid,
                            max_age_micros=args.max_age_micros)
        result['baselineSha256'] = hashlib.sha256(baseline_contents).hexdigest()
        result['newHapticRequests'] = new_haptic_requests(
            checked, baseline=baseline)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0
