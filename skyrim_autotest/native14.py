"""Strict, passive consumer of the public ``vrik_native14_v1`` copied trace.

No transport, game operations or subject verdicts live here. Call ``validate``
with an independently owned PID and an explicit age limit before selecting data.
Decimal uint64 strings and IEEE bits remain unchanged in the copied evidence.
"""
import copy
import math
import re
import struct


UINT64_MAX = (1 << 64) - 1
KIND = 'vrik_native14_v1'


class Native14Error(ValueError):
    """The public trace is invalid, unavailable, or cannot support a measurement."""


class Native14GapError(Native14Error):
    """A haptic cursor is outside the completely retained request interval."""


def _fail(path, message):
    raise Native14Error(f'{path}: {message}')


def _object(value, keys, path):
    if type(value) is not dict or set(value) != set(keys.split()):
        _fail(path, 'missing or unknown v1 fields')
    return value


def _integer(value, low, high, path):
    if type(value) is not int or not low <= value <= high:
        _fail(path, f'integer outside [{low}, {high}]')
    return value


def _uint64(value, path):
    if (type(value) is not str or len(value) > 20 or
            re.fullmatch(r'0|[1-9][0-9]*', value) is None):
        _fail(path, 'canonical decimal uint64 string required')
    if int(value) > UINT64_MAX:
        _fail(path, 'uint64 overflow')
    return int(value)


def _boolean(value, path):
    if type(value) is not bool:
        _fail(path, 'boolean required')


def _choice(value, choices, path):
    if type(value) is not str or value not in choices:
        _fail(path, 'unsupported v1 value')


def _array(value, length, path):
    if type(value) is not list or len(value) != length:
        _fail(path, f'exactly {length} ordered records required')


def _ieee(value, width, path):
    _object(value, 'value bits', path)
    bits = value['bits']
    if type(bits) is not str or re.fullmatch(r'0x[0-9a-f]{' + str(width // 4) + '}', bits) is None:
        _fail(path, f'exact lowercase IEEE{width} bits required')
    raw = bytes.fromhex(bits[2:])
    code = '>f' if width == 32 else '>d'
    decoded = struct.unpack(code, raw)[0]
    number = value['value']
    if not math.isfinite(decoded):
        if number is not None:
            _fail(path, 'observed NaN/infinity must use value:null')
        return
    if type(number) not in (int, float):
        _fail(path, 'finite bits require a finite numeric value')
    try:
        numeric = float(number)
        encoded = struct.pack(code, numeric)
    except (OverflowError, ValueError, struct.error):
        _fail(path, 'numeric value cannot represent the supplied bits')
    if not math.isfinite(numeric) or (encoded != raw and not (numeric == decoded == 0.0)):
        _fail(path, 'numeric value disagrees with IEEE bits')


def _token(value, path):
    _object(value, 'loadGeneration frameSerial bodyGeneration', path)
    for key, item in value.items():
        _uint64(item, f'{path}.{key}')


def _pose(value, path):
    _object(value, 'position rotation', path)
    for key, size in (('position', 3), ('rotation', 9)):
        _array(value[key], size, f'{path}.{key}')
        for index, item in enumerate(value[key]):
            _ieee(item, 32, f'{path}.{key}.{index}')


def _read(value, path):
    _object(value, 'source status revision', path)
    _choice(value['source'], ('not_sampled', 'legacy', 'shared', 'unavailable'), f'{path}.source')
    _integer(value['status'], -(1 << 31), (1 << 32) - 1, f'{path}.status')
    revision = _uint64(value['revision'], f'{path}.revision')
    if value['source'] == 'shared' and revision == 0:
        _fail(path, 'shared consumption requires a nonzero revision')
    if value['source'] != 'shared' and revision != 0:
        _fail(path, 'legacy or unread consumption requires revision zero')


def _timing(value, copied_at, path):
    produced = _uint64(value['producerTimeMicros'], f'{path}.producerTimeMicros')
    age = _uint64(value['ageMicros'], f'{path}.ageMicros')
    if produced > copied_at or copied_at - produced != age:
        _fail(path, 'age must match producer/copy times in the same steady-clock epoch')
    return age


def _hand(value, path):
    _object(value, 'physicalHand availableMask probe weaponType weaponClass isPrimary hoverSlot '
            'hoverDistance gripHeld gripInputUsed handPulsed gripLock inputBlockRequested', path)
    _choice(value['physicalHand'], ('left', 'right'), f'{path}.physicalHand')
    _integer(value['availableMask'], 0, 31, f'{path}.availableMask')
    _array(value['probe'], 3, f'{path}.probe')
    for index, item in enumerate(value['probe']):
        _ieee(item, 32, f'{path}.probe.{index}')
    for key in ('weaponType', 'weaponClass', 'gripLock'):
        _integer(value[key], -(1 << 31), (1 << 32) - 1, f'{path}.{key}')
    _integer(value['hoverSlot'], 0, 14, f'{path}.hoverSlot')
    _ieee(value['hoverDistance'], 32, f'{path}.hoverDistance')
    for key in ('isPrimary', 'gripHeld', 'gripInputUsed', 'handPulsed', 'inputBlockRequested'):
        _boolean(value[key], f'{path}.{key}')


def _gate(value, path):
    keys = ('evaluated handAllowed normalCompatible suspended debugDisplayBypass passed '
            'distanceEvaluated weightedDistance withinFar selectedHover')
    _object(value, keys, path)
    for key in keys.split():
        if key == 'weightedDistance':
            _ieee(value[key], 32, f'{path}.{key}')
        else:
            _boolean(value[key], f'{path}.{key}')


def _scene(value, path):
    _object(value, 'availableMask nodePresent nodeIsNiNode nodeFlags parentFlags configuredVisible '
            'displayVisible visibilityDecision childrenVisited namedChildren skippedChildren '
            'zeroScaleChildren nonzeroScaleChildren nonfiniteScaleChildren childCullBitChildren '
            'hiddenByVrikScaleWrites', path)
    for key, item in value.items():
        if key in ('nodePresent', 'nodeIsNiNode', 'configuredVisible', 'displayVisible', 'visibilityDecision'):
            _boolean(item, f'{path}.{key}')
        else:
            _integer(item, 0, (1 << 32) - 1, f'{path}.{key}')
    _integer(value['availableMask'], 0, 63, f'{path}.availableMask')


def _slot(value, number, path):
    _object(value, 'slotNumber availableMask local world policyValueMask policyValues weaponType '
            'equippedState suspended legacyNodePresentFlag gates scene', path)
    if type(value['slotNumber']) is not int or value['slotNumber'] != number:
        _fail(path, 'slots must be ordered and numbered 1 through 14')
    _integer(value['availableMask'], 0, 31, f'{path}.availableMask')
    _integer(value['policyValueMask'], 0, 511, f'{path}.policyValueMask')
    _pose(value['local'], f'{path}.local')
    _pose(value['world'], f'{path}.world')
    _array(value['policyValues'], 9, f'{path}.policyValues')
    for index, item in enumerate(value['policyValues']):
        _ieee(item, 64, f'{path}.policyValues.{index}')
    for key in ('weaponType', 'equippedState'):
        _integer(value[key], -(1 << 31), (1 << 32) - 1, f'{path}.{key}')
    for key in ('suspended', 'legacyNodePresentFlag'):
        _boolean(value[key], f'{path}.{key}')
    _array(value['gates'], 2, f'{path}.gates')
    for index, item in enumerate(value['gates']):
        _gate(item, f'{path}.gates.{index}')
    _scene(value['scene'], f'{path}.scene')


def _history(value, copied_at):
    path = 'haptics'
    _object(value, 'claim totalRequests overwrittenRequests count requests', path)
    if value['claim'] != 'native_request_only':
        _fail(path, 'only native request-site evidence is supported')
    total = _uint64(value['totalRequests'], f'{path}.totalRequests')
    overwritten = _uint64(value['overwrittenRequests'], f'{path}.overwrittenRequests')
    count = _integer(value['count'], 0, 16, f'{path}.count')
    _array(value['requests'], count, f'{path}.requests')
    if count != min(total, 16) or overwritten != total - count:
        _fail(path, 'latest-sixteen ring counters are inconsistent')
    previous_sequence = None
    for index, event in enumerate(value['requests']):
        here = f'{path}.requests.{index}'
        _object(event, 'sequence token producerTimeMicros ageMicros physicalHand slotNumber reason frames duration', here)
        sequence = _uint64(event['sequence'], f'{here}.sequence')
        if sequence == 0 or (previous_sequence is not None and sequence != previous_sequence + 1):
            _fail(here, 'retained request sequence is not contiguous')
        previous_sequence = sequence
        _token(event['token'], f'{here}.token')
        _timing(event, copied_at, here)
        _choice(event['physicalHand'], ('left', 'right'), f'{here}.physicalHand')
        _integer(event['slotNumber'], 1, 14, f'{here}.slotNumber')
        _choice(event['reason'], ('hover', 'reposition_start', 'slot_remove'), f'{here}.reason')
        for key in ('frames', 'duration'):
            _integer(event[key], -(1 << 31), (1 << 31) - 1, f'{here}.{key}')
    if previous_sequence is not None and previous_sequence < total:
        _fail(path, 'process request sequence cannot precede its load-scope count')


def _checked(snapshot):
    if type(snapshot) is dict and ('raw' in snapshot or 'error' in snapshot or snapshot.get('isError') is True):
        _fail('snapshot', 'host fallback or explicit error is not an observation')
    _object(snapshot, 'schemaVersion kind processId availability sourcePhase reason frame haptics '
            'publications copiedAtMicros observations', 'snapshot')
    if type(snapshot['schemaVersion']) is not int or snapshot['schemaVersion'] != 1 or snapshot['kind'] != KIND:
        _fail('snapshot', 'unsupported native14 schema/kind')
    _integer(snapshot['processId'], 1, (1 << 32) - 1, 'processId')
    if snapshot['availability'] != 'available' or snapshot['sourcePhase'] != 'complete':
        _fail('snapshot', 'native14 frame is unavailable or pending')
    if type(snapshot['reason']) is not str or not 1 <= len(snapshot['reason']) <= 1024:
        _fail('reason', 'bounded reason string required')
    _uint64(snapshot['publications'], 'publications')
    copied = _uint64(snapshot['copiedAtMicros'], 'copiedAtMicros')
    frame = snapshot['frame']
    _object(frame, 'token producerTimeMicros ageMicros contextFlags leftHanded useTriggersInstead '
            'holstersEnabled activationDisabled displayHolsters hapticsEnabled maxCloseDistance '
            'maxFarDistance placementRead policyRead hands slots', 'frame')
    _token(frame['token'], 'frame.token')
    _timing(frame, copied, 'frame')
    _integer(frame['contextFlags'], 0, 255, 'frame.contextFlags')
    for key in ('leftHanded', 'useTriggersInstead', 'holstersEnabled', 'activationDisabled', 'displayHolsters', 'hapticsEnabled'):
        _boolean(frame[key], f'frame.{key}')
    for key in ('maxCloseDistance', 'maxFarDistance'):
        _ieee(frame[key], 32, f'frame.{key}')
    for key in ('placementRead', 'policyRead'):
        _read(frame[key], f'frame.{key}')
    _array(frame['hands'], 2, 'frame.hands')
    for index, item in enumerate(frame['hands']):
        _hand(item, f'frame.hands.{index}')
    if [hand['physicalHand'] for hand in frame['hands']] != ['left', 'right']:
        _fail('frame.hands', 'physical-hand records must be ordered left, right')
    _array(frame['slots'], 14, 'frame.slots')
    for index, item in enumerate(frame['slots']):
        _slot(item, index + 1, f'frame.slots.{index}')
    _history(snapshot['haptics'], copied)
    observed = _object(snapshot['observations'], 'scene haptics actions', 'observations')
    if observed != {'scene': 'scene_graph_state', 'haptics': 'native_requests', 'actions': 'unobserved'}:
        _fail('observations', 'unknown observation claims')
    return snapshot


def validate(snapshot, *, expected_pid: int, max_age_micros: int) -> dict:
    """Validate an available v1 frame and return independent, unchanged copied data.

    Age is the producer's age *at copy time*, not elapsed network/offline time.
    A matching PID is an identity check, not process creation-time ownership proof.
    Nonfinite observations remain ``value: None`` with their exact IEEE bits.
    """
    _integer(expected_pid, 1, (1 << 32) - 1, 'expected_pid')
    _integer(max_age_micros, 0, UINT64_MAX, 'max_age_micros')
    _checked(snapshot)
    if snapshot['processId'] != expected_pid:
        _fail('processId', 'snapshot belongs to another process')
    if int(snapshot['frame']['ageMicros']) > max_age_micros:
        _fail('frame.ageMicros', 'stale native14 publication')
    return copy.deepcopy(snapshot)


def _require_mask(mask, bit, path):
    if not mask & bit:
        _fail(path, 'requested field was not observed (availability mask)')


def _observable(snapshot, parts, path):
    if parts[:2] == ['haptics', 'requests']:
        _fail(path, 'use new_haptic_requests with an explicit baseline snapshot')
    if parts[:1] == ['frame'] and len(parts) >= 3 and parts[1] in ('placementRead', 'policyRead'):
        source = snapshot['frame'][parts[1]]['source']
        if parts[2] == 'status' and source == 'not_sampled':
            _fail(path, 'compatibility consumption was not sampled; status is unobserved')
        if parts[2] == 'revision' and source != 'shared':
            _fail(path, 'only a consumed shared-bank revision is an observed revision')
    if parts[:2] == ['frame', 'hands'] and len(parts) >= 4:
        hand, field = snapshot['frame']['hands'][int(parts[2])], parts[3]
        bits = {'probe': 1, 'weaponType': 2, 'weaponClass': 2, 'isPrimary': 2,
                'hoverSlot': 4, 'hoverDistance': 4, 'gripHeld': 8, 'gripInputUsed': 8,
                'handPulsed': 8, 'gripLock': 8, 'inputBlockRequested': 16}
        if field in ('physicalHand', 'availableMask'):
            return
        if field not in bits:
            _fail(path, 'public contract does not yet map this hand field to a mask bit')
        _require_mask(hand['availableMask'], bits[field], path)
    if parts[:2] == ['frame', 'slots'] and len(parts) >= 4:
        slot, field = snapshot['frame']['slots'][int(parts[2])], parts[3]
        if field in ('slotNumber', 'availableMask', 'policyValueMask'):
            return
        if field == 'gates':
            if len(parts) < 6:
                return
            gate = slot['gates'][int(parts[4])]
            leaf = parts[5]
            if leaf == 'evaluated':
                return
            if leaf == 'selectedHover':
                hand = snapshot['frame']['hands'][int(parts[4])]
                _require_mask(hand['availableMask'], 4, path)
                return
            if not gate['evaluated']:
                _fail(path, 'native hand gate was not evaluated')
            if leaf in ('weightedDistance', 'withinFar') and not gate['distanceEvaluated']:
                _fail(path, 'native distance was not evaluated')
            return
        if field == 'legacyNodePresentFlag':
            _require_mask(slot['availableMask'], 16, path)
            _require_mask(slot['scene']['availableMask'], 1, path)
            return
        bits = {'local': 1, 'policyValues': 2, 'world': 4, 'weaponType': 8,
                'equippedState': 8, 'suspended': 8, 'scene': 16}
        if field not in bits:
            _fail(path, 'public contract does not map this slot field to a mask bit')
        _require_mask(slot['availableMask'], bits[field], path)
        if field == 'policyValues' and len(parts) >= 5:
            _require_mask(slot['policyValueMask'], 1 << int(parts[4]), path)
        if field == 'scene' and len(parts) >= 5:
            scene_bits = {'nodePresent': 1, 'nodeIsNiNode': 2, 'nodeFlags': 4,
                          'parentFlags': 8, 'configuredVisible': 16, 'displayVisible': 16,
                          'visibilityDecision': 16, 'childrenVisited': 32, 'namedChildren': 32,
                          'skippedChildren': 32, 'zeroScaleChildren': 32, 'nonzeroScaleChildren': 32,
                          'nonfiniteScaleChildren': 32, 'childCullBitChildren': 32,
                          'hiddenByVrikScaleWrites': 32}
            if parts[4] != 'availableMask':
                if parts[4] not in scene_bits:
                    _fail(path, 'scene sub-mask field is not specified by the public contract')
                _require_mask(slot['scene']['availableMask'], scene_bits[parts[4]], path)


def measurement(snapshot, path: str):
    """Select one observed primitive using dotted keys and zero-based array indices.

    This repeats schema checks, but callers must first validate owned PID and age.
    IEEE records unwrap to finite numeric values; select ``.bits`` for nonfinite
    raw evidence. Containers, unobserved fields and unspecified masks are refused.
    """
    _checked(snapshot)
    if (type(path) is not str or len(path) > 256 or
            re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(?:\.(?:[A-Za-z_][A-Za-z_0-9]*|0|[1-9][0-9]*))*', path) is None):
        _fail('path', 'bounded dotted field path with canonical zero-based indices required')
    parts = path.split('.')
    selected = snapshot
    try:
        for part in parts:
            if type(selected) is dict:
                selected = selected[part]
            elif type(selected) is list and part.isdecimal():
                selected = selected[int(part)]
            else:
                _fail(path, 'unsupported field selector')
        _observable(snapshot, parts, path)
    except (KeyError, IndexError, ValueError) as error:
        if isinstance(error, Native14Error):
            raise
        _fail(path, 'field is missing or selector is unsupported')
    if type(selected) is dict and set(selected) == {'value', 'bits'}:
        selected = selected['value']
    if selected is None:
        _fail(path, 'observed nonfinite IEEE value; select .bits for raw evidence')
    if type(selected) not in (bool, int, float, str):
        _fail(path, 'one observed primitive required, not a container')
    return selected


def new_haptic_requests(snapshot, *, baseline: dict) -> list:
    """Return copied request-site events in a covered baseline/current interval.

    This supports complete available frames only, although the producer can retain
    history while a frame is pending. It does not establish driver submission,
    sensation, rendered state or equipment actions. Both snapshots must have been
    validated against the independently owned process and explicit freshness limits.
    Load/body must remain unchanged. Load-scope count deltas establish how many
    new events must be retained; process-wide sequences never restart at zero on
    load. New event frame serials lie inclusively between the two complete frames.
    Gaps and unattributable events are errors, never filtered into an empty result.
    """
    _checked(snapshot)
    _checked(baseline)
    if snapshot['processId'] != baseline['processId']:
        _fail('processId', 'baseline/current snapshots belong to different processes')
    token = baseline['frame']['token']
    current = snapshot['frame']['token']
    context_fields = ('loadGeneration', 'bodyGeneration')
    if any(token[key] != current[key] for key in context_fields):
        _fail('token', 'baseline/current load or body generation changed')
    first_frame, last_frame = int(token['frameSerial']), int(current['frameSerial'])
    if first_frame > last_frame:
        _fail('token', 'current frame precedes the action baseline frame')
    if int(snapshot['copiedAtMicros']) < int(baseline['copiedAtMicros']):
        _fail('copiedAtMicros', 'current copy time precedes the action baseline')
    history = snapshot['haptics']
    previous = baseline['haptics']
    total = int(history['totalRequests'])
    delta = total - int(previous['totalRequests'])
    if delta < 0:
        raise Native14GapError('haptics: load-scope request count regressed within the interval')
    if delta > history['count']:
        raise Native14GapError('haptics: retained-ring coverage gap after the baseline snapshot')
    if previous['requests']:
        expected_sequence = int(previous['requests'][-1]['sequence']) + delta
        if expected_sequence > UINT64_MAX:
            raise Native14GapError('haptics: request sequence exhausted; wrapping is unsupported')
        if not history['requests'] or int(history['requests'][-1]['sequence']) != expected_sequence:
            raise Native14GapError('haptics: process sequence regression or missing/future new records')
    previous_events = {event['sequence']: event for event in previous['requests']}
    for event in history['requests']:
        old = previous_events.get(event['sequence'])
        if old is not None and ({key: value for key, value in old.items() if key != 'ageMicros'} !=
                                {key: value for key, value in event.items() if key != 'ageMicros'}):
            raise Native14GapError('haptics: overlapping request sequence changed its recorded facts')
    # An empty baseline has no known process sequence. In particular it is not
    # sequence zero: a load clears scope history/counters without resetting it.
    events = history['requests'][-delta:] if delta else []
    previous_frame = first_frame
    for event in events:
        if any(event['token'][key] != current[key] for key in context_fields):
            _fail('haptics', 'new event load or body generation changed')
        event_frame = int(event['token']['frameSerial'])
        if not first_frame <= event_frame <= last_frame:
            _fail('haptics', 'new event frame lies before baseline or after current frame')
        if event_frame < previous_frame:
            _fail('haptics', 'new event frame serials move backwards across increasing sequences')
        previous_frame = event_frame
    return copy.deepcopy(events)
