"""Corroborate only VRIK numeric slot-pose output; never adopt arbitrary INI edits."""
import copy
import hashlib
import math
from pathlib import Path
import re

NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
LINE = re.compile(r'^([ \t]*(?P<key>(?:pos[XYZ]|rot[A-I])(?:[1-9]|1[0-4]))[ \t]*=[ \t]*)(?P<value>' + NUMBER + r')(?=[ \t]*\r?$)', re.M)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parsed(data):
    text = data.decode('utf-8-sig')
    values = {}
    def mask(match):
        key, value = match['key'], float(match['value'])
        if key in values or not math.isfinite(value) or abs(value) > (100000 if key.startswith('pos') else 1.001):
            raise ValueError('Duplicate or extreme VRIK slot pose output')
        values[key] = value
        return match[1] + '<verified-numeric-pose>'
    shape = LINE.sub(mask, text)
    return (data.startswith(b'\xef\xbb\xbf'), shape), values


def record_for(b, target, subject):
    from .subject_state import snapshot
    snapshot(b, target)
    record = b.s.state.get('fixtureSettingsWrites', {}).get(str(target))
    if not record or record.get('slotSubject') != subject:
        return None
    written = bytes.fromhex(record['writtenBytesHex'])
    if digest(written) != record['writtenSha256'] or type(record.get('writeOrdinal')) is not int:
        raise ValueError('Original VRIK slot fixture write identity changed')
    return record


def capture(b, target, subject):
    record = record_for(b, target, subject)
    if record is None:
        return None  # Legacy/unowned writes retain the strict byte guard.
    _, keys = parsed(bytes.fromhex(record['writtenBytesHex']))
    if not keys:
        return None
    b.guard_world()
    game = copy.deepcopy(b.s.state['game'])
    transition = copy.deepcopy(b.s.state.get('ownedLoadTransition', {}))
    if transition.get('completed') is not True or transition.get('afterGame') != game:
        raise ValueError('VRIK slot output requires the exact completed owned load')
    samples = []
    for _ in range(2):
        calls = [{'script': 'VRIK', 'function': 'VrikGetSlot', 'args': [key]} for key in keys]
        values = []
        for i in range(0, len(calls), 16):
            b.remaining()
            values.extend(b.pap_read_batch(calls[i:i+16]))
        if len(values) != len(keys) or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
            raise ValueError('Actual loaded VRIK pose values unavailable')
        samples.append(dict(zip(keys, values)))
    b.guard_world()
    if b.s.state['game'] != game or samples[0] != samples[1]:
        raise ValueError('VRIK native pose changed during output observation')
    sample = {'path': str(target), 'subject': subject, 'game': game,
              'writtenSha256': record['writtenSha256'], 'writeOrdinal': record['writeOrdinal'],
              'ownedLoadTransition': transition, 'values': samples[1],
              'basis': 'Two matching loaded VRIK getter batches bracketed by current-world guards; sampled, not atomic; writer identity unknown'}
    b.s.state.setdefault('fixtureSlotNativeSamples', []).append(copy.deepcopy(sample))
    b.s.save()
    b.s.log('platform-fixture-slot-native-sample', sample=sample)
    return sample


def reconcile(b, target, subject, sample):
    if sample is None:
        return
    record = record_for(b, target, subject)
    if (record is None or sample['path'] != str(target) or sample['subject'] != subject or
            sample['game'] != b.s.state['game'] or sample['writtenSha256'] != record['writtenSha256'] or
            sample['writeOrdinal'] != record['writeOrdinal']):
        raise ValueError('VRIK output sample/write/process identity changed')
    stat = target.lstat()
    if (not target.is_file() or target.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400 or stat.st_size > 4*1024*1024):
        raise ValueError('VRIK output is not a bounded regular file')
    data = target.read_bytes()
    if digest(data) == record['sha256']:
        return
    original = bytes.fromhex(record['writtenBytesHex'])
    shape, values = parsed(data)
    old_shape, old_values = parsed(original)
    if shape != old_shape or values.keys() != old_values.keys():
        raise ValueError('VRIK output changed fields outside numeric slot pose')
    if values.keys() != sample['values'].keys() or any(
            not math.isclose(value, sample['values'][key], rel_tol=1e-7, abs_tol=5e-6)
            for key, value in values.items()):
        raise ValueError('VRIK output does not match actual loaded pose')
    if target.read_bytes() != data:
        raise ValueError('VRIK output changed during reconciliation')
    evidence = {'path': str(target), 'sha256': digest(data), 'bytes': len(data),
                'previousVerifiedSha256': record['sha256'], 'writtenSha256': record['writtenSha256'],
                'actualBytesHex': data.hex(), 'changedKeys': [key for key in values if values[key] != old_values[key]],
                'nativeSample': copy.deepcopy(sample), 'writerIdentity': 'unknown',
                'basis': 'Only numeric VRIK pose values changed; all other bytes and flags preserved; actual loaded native values corroborate output within float serialization tolerance'}
    record.update(sha256=evidence['sha256'], bytes=len(data), nativeOutput=evidence)
    b.s.state.setdefault('fixtureSettingsOutputHistory', []).append(copy.deepcopy(evidence))
    b.s.save()
    b.s.log('platform-fixture-slot-output-reconciled', evidence=evidence)
