"""Synthetic public-contract fixtures; no game, mod DLL or external trace inputs."""
import copy
import math
import struct
import unittest

from skyrim_autotest.native14 import (
    KIND, UINT64_MAX, Native14Error, Native14GapError,
    measurement, new_haptic_requests, validate,
)


def ieee(value=0.0, width=32, *, bits=None):
    code = '>f' if width == 32 else '>d'
    if bits is None:
        bits = '0x' + struct.pack(code, value).hex()
    decoded = struct.unpack(code, bytes.fromhex(bits[2:]))[0]
    return {'value': decoded if math.isfinite(decoded) else None, 'bits': bits}


def pose():
    return {'position': [ieee() for _ in range(3)],
            'rotation': [ieee(1.0 if index in (0, 4, 8) else 0.0) for index in range(9)]}


def snapshot():
    """A shape-only PID77 v1 frame with deliberately independent decision facts."""
    token = {'loadGeneration': '1', 'frameSerial': '2', 'bodyGeneration': '3'}
    hands = []
    for hand in ('left', 'right'):
        hands.append({'physicalHand': hand, 'availableMask': 5,
                      'probe': [ieee(7.0), ieee(), ieee()], 'weaponType': 0,
                      'weaponClass': 0, 'isPrimary': False, 'hoverSlot': 0,
                      'hoverDistance': ieee(7.0), 'gripHeld': False,
                      'gripInputUsed': False, 'handPulsed': False, 'gripLock': 0,
                      'inputBlockRequested': False})
    slots = []
    for number in range(1, 15):
        gate = {'evaluated': True, 'handAllowed': False, 'normalCompatible': False,
                'suspended': False, 'debugDisplayBypass': False, 'passed': True,
                'distanceEvaluated': True, 'weightedDistance': ieee(7.0),
                'withinFar': False, 'selectedHover': False}
        scene = {'availableMask': 7, 'nodePresent': True, 'nodeIsNiNode': True,
                 'nodeFlags': 0, 'parentFlags': 0, 'configuredVisible': False,
                 'displayVisible': False, 'visibilityDecision': False,
                 'childrenVisited': 0, 'namedChildren': 0, 'skippedChildren': 0,
                 'zeroScaleChildren': 0, 'nonzeroScaleChildren': 0,
                 'nonfiniteScaleChildren': 0, 'childCullBitChildren': 0,
                 'hiddenByVrikScaleWrites': 0}
        slots.append({'slotNumber': number, 'availableMask': 31, 'local': pose(),
                      'world': pose(), 'policyValueMask': 259,
                      'policyValues': [ieee(1.0, 64) for _ in range(9)],
                      'weaponType': 0, 'equippedState': 0, 'suspended': False,
                      'legacyNodePresentFlag': False, 'gates': [copy.deepcopy(gate), copy.deepcopy(gate)],
                      'scene': scene})
    frame = {'token': token, 'producerTimeMicros': '95', 'ageMicros': '5',
             'contextFlags': 0, 'leftHanded': False, 'useTriggersInstead': False,
             'holstersEnabled': True, 'activationDisabled': False,
             'displayHolsters': False, 'hapticsEnabled': False,
             'maxCloseDistance': ieee(10.0), 'maxFarDistance': ieee(20.0),
             'placementRead': {'source': 'shared', 'status': 0, 'revision': str(UINT64_MAX)},
             'policyRead': {'source': 'legacy', 'status': 8, 'revision': '0'},
             'hands': hands, 'slots': slots}
    events = []
    for sequence in range(1, 3):
        events.append({'sequence': str(sequence), 'token': copy.deepcopy(token),
                       'producerTimeMicros': '98', 'ageMicros': '2',
                       'physicalHand': 'left' if sequence == 1 else 'right',
                       'slotNumber': sequence, 'reason': 'hover', 'frames': sequence,
                       'duration': 750})
    return {'schemaVersion': 1, 'kind': KIND, 'processId': 77,
            'availability': 'available', 'sourcePhase': 'complete', 'reason': 'none',
            'frame': frame, 'haptics': {'claim': 'native_request_only', 'totalRequests': '2',
                                     'overwrittenRequests': '0', 'count': 2, 'requests': events},
            'publications': '1', 'copiedAtMicros': '100',
            'observations': {'scene': 'scene_graph_state', 'haptics': 'native_requests', 'actions': 'unobserved'}}


def scope_history(row, total, *, last_sequence=None):
    """Set a synthetic load-scope ring with an independent process sequence offset."""
    count = min(total, 16)
    events = []
    if count:
        last_sequence = total if last_sequence is None else last_sequence
        prototype = snapshot()['haptics']['requests'][0]
        for sequence in range(last_sequence - count + 1, last_sequence + 1):
            event = copy.deepcopy(prototype)
            event['sequence'] = str(sequence)
            event['token'] = copy.deepcopy(row['frame']['token'])
            events.append(event)
    row['haptics'].update(totalRequests=str(total), overwrittenRequests=str(total - count),
                         count=count, requests=events)
    return row


class Native14Tests(unittest.TestCase):
    def checked(self, value=None, **kwargs):
        return validate(snapshot() if value is None else value,
                        expected_pid=kwargs.get('expected_pid', 77),
                        max_age_micros=kwargs.get('max_age_micros', 5))

    def test_raw_evidence_is_an_independent_copy_without_semantic_inference(self):
        original = snapshot()
        checked = self.checked(original)
        self.assertEqual(checked, original)
        self.assertEqual(checked['frame']['placementRead']['revision'], str(UINT64_MAX))
        self.assertEqual(measurement(checked, 'frame.slots.0.gates.0.passed'), True)
        self.assertEqual(measurement(checked, 'frame.slots.0.gates.0.handAllowed'), False)
        checked['frame']['slots'][0]['local']['position'][0]['value'] = 99
        self.assertEqual(original['frame']['slots'][0]['local']['position'][0]['value'], 0)

    def test_refuses_missing_error_fallback_unknown_and_pending(self):
        bad = [{}, {'raw': '{}'}, {'error': 'failed'}, {'isError': True}]
        for key, value in (('schemaVersion', 2), ('schemaVersion', True), ('kind', 'other'),
                           ('availability', 'unavailable'), ('sourcePhase', 'pending')):
            row = snapshot()
            row[key] = value
            bad.append(row)
        row = snapshot()
        del row['frame']['ageMicros']
        bad.append(row)
        for row in bad:
            with self.subTest(row=list(row)):
                with self.assertRaises(Native14Error):
                    self.checked(row)

    def test_pid_and_copy_age_gate(self):
        for expected in (76, True, 0):
            with self.assertRaises(Native14Error):
                self.checked(expected_pid=expected)
        with self.assertRaisesRegex(Native14Error, 'stale'):
            self.checked(max_age_micros=4)
        self.checked(max_age_micros=5)
        row = snapshot()
        row['frame']['ageMicros'] = '0'
        with self.assertRaisesRegex(Native14Error, 'age must match'):
            self.checked(row)

    def test_uint64_strings_remain_exact_and_canonical(self):
        row = snapshot()
        row['frame']['token']['loadGeneration'] = str(UINT64_MAX)
        row['publications'] = str(UINT64_MAX)
        self.assertEqual(self.checked(row)['publications'], str(UINT64_MAX))
        for bad in (UINT64_MAX, True, '-1', '01', '+1', ' 1', '1.0', '1e0', str(UINT64_MAX + 1), '١'):
            row = snapshot()
            row['frame']['placementRead']['revision'] = bad
            with self.subTest(value=bad):
                with self.assertRaises(Native14Error):
                    self.checked(row)

    def test_ieee32_and_ieee64_nan_infinity_signed_zero_and_roundtrip(self):
        for width, path, values in (
                (32, ('local', 'position'), ('0x7fc00123', '0x7f800000', '0xff800000', '0x80000000', '0x00000000')),
                (64, ('policyValues',), ('0x7ff8000000000123', '0x7ff0000000000000',
                                       '0xfff0000000000000', '0x8000000000000000', '0x0000000000000000'))):
            for bits in values:
                row = snapshot()
                values_at = row['frame']['slots'][0]
                for key in path:
                    values_at = values_at[key]
                record = ieee(width=width, bits=bits)
                if record['value'] == 0:
                    record['value'] = 0  # JSON can lose the lexical sign of -0.
                values_at[0] = record
                checked = self.checked(row)
                selected = 'frame.slots.0.' + '.'.join(path) + '.0'
                self.assertEqual(measurement(checked, selected + '.bits'), bits)
                if record['value'] is None:
                    with self.assertRaisesRegex(Native14Error, 'observed nonfinite'):
                        measurement(checked, selected + '.value')
                else:
                    self.assertEqual(measurement(checked, selected), 0)
        row = snapshot()
        row['frame']['slots'][0]['local']['position'][0] = {'value': 0.100000001, 'bits': '0x3dcccccd'}
        self.checked(row)  # Float32's nine significant digits round back to its bits.

    def test_ieee_mismatches_are_rejected_even_in_unobserved_storage(self):
        for record in ({'value': 1, 'bits': '0x00000000'}, {'value': None, 'bits': '0x00000000'},
                       {'value': float('nan'), 'bits': '0x7fc00123'}, {'value': 1, 'bits': '0x7f800000'},
                       {'value': 1, 'bits': '0x3F800000'}, {'value': True, 'bits': '0x3f800000'}):
            row = snapshot()
            row['frame']['hands'][0]['availableMask'] = 0
            row['frame']['hands'][0]['probe'][0] = record
            with self.assertRaises(Native14Error):
                self.checked(row)

    def test_exact_slot_count_numbering_and_physical_hands(self):
        for change in ('count', 'duplicate', 'reorder', 'hand', 'duplicate_hand', 'reorder_hands'):
            row = snapshot()
            if change == 'count':
                row['frame']['slots'].pop()
            elif change == 'duplicate':
                row['frame']['slots'][1]['slotNumber'] = 1
            elif change == 'reorder':
                row['frame']['slots'].reverse()
            elif change == 'hand':
                row['frame']['hands'][0]['physicalHand'] = 'primary'
            elif change == 'duplicate_hand':
                row['frame']['hands'][1]['physicalHand'] = 'left'
            else:
                row['frame']['hands'].reverse()
            with self.subTest(change=change):
                with self.assertRaises(Native14Error):
                    self.checked(row)

    def test_all_known_masks_and_unknown_bits(self):
        for owner, field, invalid in (('hand', 'availableMask', 32), ('slot', 'availableMask', 32),
                                       ('slot', 'policyValueMask', 512), ('scene', 'availableMask', 64),
                                       ('frame', 'contextFlags', 256)):
            row = snapshot()
            target = {'hand': row['frame']['hands'][0], 'slot': row['frame']['slots'][0],
                      'scene': row['frame']['slots'][0]['scene'], 'frame': row['frame']}[owner]
            target[field] = invalid
            with self.assertRaises(Native14Error):
                self.checked(row)

    def test_context_flags_are_observed_values_not_availability(self):
        row = self.checked()
        self.assertIs(measurement(row, 'frame.leftHanded'), False)
        self.assertIs(measurement(row, 'frame.displayHolsters'), False)
        self.assertEqual(measurement(row, 'frame.maxCloseDistance.value'), 10)
        self.assertEqual(measurement(row, 'frame.contextFlags'), 0)

    def test_read_status_and_revision_do_not_promote_default_sentinels(self):
        for field in ('placementRead', 'policyRead'):
            row = snapshot()
            read = row['frame'][field]
            read.update(source='not_sampled', status=0, revision='0')
            self.assertEqual(measurement(row, f'frame.{field}.source'), 'not_sampled')
            for leaf in ('status', 'revision'):
                with self.assertRaises(Native14Error):
                    measurement(row, f'frame.{field}.{leaf}')
            for source in ('legacy', 'unavailable'):
                read.update(source=source, status=8, revision='0')
                self.assertEqual(measurement(row, f'frame.{field}.status'), 8)
                with self.assertRaisesRegex(Native14Error, 'shared-bank revision'):
                    measurement(row, f'frame.{field}.revision')
            read.update(source='shared', status=0, revision=str(UINT64_MAX))
            self.assertEqual(measurement(row, f'frame.{field}.revision'), str(UINT64_MAX))

    def test_hand_observedness_is_independent_per_field_group(self):
        fields = {1: 'probe.0.value', 2: 'weaponType', 4: 'hoverSlot',
                  8: 'gripHeld', 16: 'inputBlockRequested'}
        for bit, field in fields.items():
            row = snapshot()
            row['frame']['hands'][0]['availableMask'] = bit
            self.checked(row)
            measurement(row, 'frame.hands.0.' + field)
            row['frame']['hands'][0]['availableMask'] = 0
            with self.assertRaisesRegex(Native14Error, 'not observed'):
                measurement(row, 'frame.hands.0.' + field)

    def test_slot_policy_pose_and_cached_state_masks(self):
        paths = {1: 'local.position.0.value', 2: 'policyValues.0.value',
                 4: 'world.rotation.0.bits', 8: 'suspended'}
        for bit, field in paths.items():
            row = snapshot()
            row['frame']['slots'][0]['availableMask'] = bit
            measurement(row, 'frame.slots.0.' + field)
            row['frame']['slots'][0]['availableMask'] = 0
            with self.assertRaises(Native14Error):
                measurement(row, 'frame.slots.0.' + field)
        row = self.checked()
        self.assertEqual(measurement(row, 'frame.slots.0.policyValues.8.value'), 1)
        with self.assertRaises(Native14Error):
            measurement(row, 'frame.slots.0.policyValues.2.value')

    def test_scene_masks_distinguish_unknown_from_observed_zero(self):
        row = self.checked()
        self.assertEqual(measurement(row, 'frame.slots.0.scene.nodeFlags'), 0)
        self.assertFalse(measurement(row, 'frame.slots.0.legacyNodePresentFlag'))
        for field in ('parentFlags', 'configuredVisible', 'childrenVisited'):
            with self.assertRaisesRegex(Native14Error, 'not observed'):
                measurement(row, 'frame.slots.0.scene.' + field)
        row['frame']['slots'][0]['scene']['availableMask'] = 63
        self.assertEqual(measurement(row, 'frame.slots.0.scene.childrenVisited'), 0)
        self.assertFalse(measurement(row, 'frame.slots.0.scene.configuredVisible'))
        row['frame']['slots'][0]['availableMask'] &= ~16
        with self.assertRaises(Native14Error):
            measurement(row, 'frame.slots.0.scene.nodeFlags')

    def test_gate_and_distance_evaluation_are_separate(self):
        row = snapshot()
        gate = row['frame']['slots'][0]['gates'][0]
        gate['evaluated'] = False
        self.assertFalse(measurement(row, 'frame.slots.0.gates.0.evaluated'))
        for field in ('passed', 'distanceEvaluated', 'weightedDistance.value'):
            with self.assertRaisesRegex(Native14Error, 'not evaluated'):
                measurement(row, 'frame.slots.0.gates.0.' + field)
        gate['evaluated'] = True
        gate['distanceEvaluated'] = False
        self.assertFalse(measurement(row, 'frame.slots.0.gates.0.distanceEvaluated'))
        with self.assertRaisesRegex(Native14Error, 'distance was not evaluated'):
            measurement(row, 'frame.slots.0.gates.0.weightedDistance.value')

    def test_selected_hover_uses_physical_hand_mask_independent_of_gate_and_dominance(self):
        for left_handed in (False, True):
            row = snapshot()
            row['frame']['leftHanded'] = left_handed
            for gate in row['frame']['slots'][0]['gates']:
                gate.update(evaluated=False, distanceEvaluated=False)
            for observed_index in (0, 1):
                row['frame']['hands'][observed_index]['availableMask'] = 4
                row['frame']['hands'][1 - observed_index]['availableMask'] = 1
                self.assertIs(measurement(row, f'frame.slots.0.gates.{observed_index}.selectedHover'), False)
                with self.assertRaisesRegex(Native14Error, 'not observed'):
                    measurement(row, f'frame.slots.0.gates.{1 - observed_index}.selectedHover')

    def test_unsupported_selectors_are_explicit(self):
        for path in ('frame.slots.14.slotNumber', 'frame.slots.00.slotNumber',
                     'frame.slots.0.scene.invented', 'frame.slots.0.local',
                     'haptics.requests.0.sequence', 'frame.unknown', 'frame.slots.-1'):
            with self.subTest(path=path):
                with self.assertRaises(Native14Error):
                    measurement(snapshot(), path)

    def test_exact_current_token_haptic_requests_and_copy(self):
        row = self.checked()
        baseline = scope_history(copy.deepcopy(row), 1)
        result = new_haptic_requests(row, baseline=baseline)
        self.assertEqual([item['sequence'] for item in result], ['2'])
        result[0]['duration'] = 0
        self.assertEqual(row['haptics']['requests'][1]['duration'], 750)
        self.assertEqual(new_haptic_requests(row, baseline=row), [])
        baseline = scope_history(copy.deepcopy(row), 3)
        with self.assertRaises(Native14GapError):
            new_haptic_requests(row, baseline=baseline)

    def test_history_gaps_and_uint64_sequence_limit(self):
        row = scope_history(snapshot(), UINT64_MAX)
        self.checked(row)
        baseline = scope_history(copy.deepcopy(row), UINT64_MAX - 17)
        with self.assertRaisesRegex(Native14GapError, 'coverage gap'):
            new_haptic_requests(row, baseline=baseline)
        baseline = scope_history(copy.deepcopy(row), UINT64_MAX - 16)
        self.assertEqual(len(new_haptic_requests(row, baseline=baseline)), 16)
        self.assertEqual(new_haptic_requests(row, baseline=row), [])

    def test_haptic_token_crossing_is_not_silently_filtered(self):
        row = snapshot()
        baseline = scope_history(copy.deepcopy(row), 0)
        baseline['frame']['token']['bodyGeneration'] = '4'
        with self.assertRaisesRegex(Native14Error, 'load or body generation changed'):
            new_haptic_requests(row, baseline=baseline)
        baseline['frame']['token']['bodyGeneration'] = row['frame']['token']['bodyGeneration']
        row['haptics']['requests'][0]['token']['bodyGeneration'] = '4'
        self.checked(row)  # Prior-token history can validly be retained.
        with self.assertRaisesRegex(Native14Error, 'load or body generation changed'):
            new_haptic_requests(row, baseline=baseline)
        baseline = copy.deepcopy(row)
        baseline['haptics'].update(totalRequests='1', overwrittenRequests='0', count=1,
                                  requests=[copy.deepcopy(row['haptics']['requests'][0])])
        self.assertEqual(len(new_haptic_requests(row, baseline=baseline)), 1)

    def test_haptic_interval_spans_normal_frames_within_one_load_and_body(self):
        row = snapshot()
        baseline = scope_history(copy.deepcopy(row), 0)
        row['frame']['token']['frameSerial'] = '8'
        row['haptics']['requests'][0]['token']['frameSerial'] = '3'
        row['haptics']['requests'][1]['token']['frameSerial'] = '8'
        events = new_haptic_requests(row, baseline=baseline)
        self.assertEqual([event['token']['frameSerial'] for event in events], ['3', '8'])
        self.assertEqual([event['sequence'] for event in events], ['1', '2'])
        self.assertEqual(new_haptic_requests(row, baseline=row), [])

    def test_haptic_interval_rejects_changed_context_and_backward_or_future_frames(self):
        for field in ('loadGeneration', 'bodyGeneration'):
            row = snapshot()
            baseline = scope_history(copy.deepcopy(row), 0)
            baseline['frame']['token'][field] = '9'
            with self.assertRaisesRegex(Native14Error, 'generation changed'):
                new_haptic_requests(row, baseline=baseline)
            baseline = scope_history(copy.deepcopy(row), 0)
            row['haptics']['requests'][0]['token'][field] = '9'
            with self.assertRaisesRegex(Native14Error, 'generation changed'):
                new_haptic_requests(row, baseline=baseline)
        for serial in ('1', '4'):
            row = snapshot()
            baseline = scope_history(copy.deepcopy(row), 0)
            row['frame']['token']['frameSerial'] = '3'
            row['haptics']['requests'][0]['token']['frameSerial'] = serial
            with self.assertRaisesRegex(Native14Error, 'before baseline or after current'):
                new_haptic_requests(row, baseline=baseline)
        row = snapshot()
        baseline = scope_history(copy.deepcopy(row), 0)
        baseline['frame']['token']['frameSerial'] = '3'
        with self.assertRaisesRegex(Native14Error, 'precedes'):
            new_haptic_requests(row, baseline=baseline)
        baseline['frame']['token']['frameSerial'] = '2'
        row['frame']['token']['frameSerial'] = '8'
        row['haptics']['requests'][0]['token']['frameSerial'] = '8'
        row['haptics']['requests'][1]['token']['frameSerial'] = '3'
        with self.assertRaisesRegex(Native14Error, 'move backwards'):
            new_haptic_requests(row, baseline=baseline)

    def test_load_scope_counts_do_not_reset_the_process_sequence(self):
        row = scope_history(snapshot(), 2, last_sequence=102)
        self.checked(row)
        baseline = scope_history(copy.deepcopy(row), 0)
        self.assertEqual([event['sequence'] for event in new_haptic_requests(row, baseline=baseline)],
                         ['101', '102'])
        empty = scope_history(snapshot(), 0)
        self.assertEqual(new_haptic_requests(empty, baseline=empty), [])
        # A nonempty baseline proves the exact process sequence as well as scope count.
        baseline = scope_history(copy.deepcopy(row), 1, last_sequence=101)
        self.assertEqual([event['sequence'] for event in new_haptic_requests(row, baseline=baseline)], ['102'])

    def test_interval_rejects_sequence_offsets_changing_missing_records_and_exhaustion(self):
        baseline = scope_history(snapshot(), 2, last_sequence=102)
        for total, last_sequence in ((2, 101), (2, 103), (3, 102), (3, 104)):
            row = scope_history(snapshot(), total, last_sequence=last_sequence)
            self.checked(row)
            with self.assertRaisesRegex(Native14GapError, 'sequence regression or missing/future'):
                new_haptic_requests(row, baseline=baseline)
        baseline = scope_history(snapshot(), 1, last_sequence=UINT64_MAX)
        row = scope_history(snapshot(), 2, last_sequence=UINT64_MAX)
        with self.assertRaisesRegex(Native14GapError, 'exhausted'):
            new_haptic_requests(row, baseline=baseline)

    def test_interval_validates_baseline_pid_copy_time_and_history(self):
        row = snapshot()
        baseline = copy.deepcopy(row)
        baseline['processId'] = 78
        with self.assertRaisesRegex(Native14Error, 'different processes'):
            new_haptic_requests(row, baseline=baseline)
        baseline = copy.deepcopy(row)
        baseline['copiedAtMicros'] = '101'
        baseline['frame']['ageMicros'] = '6'
        for event in baseline['haptics']['requests']:
            event['ageMicros'] = '3'
        with self.assertRaisesRegex(Native14Error, 'copy time precedes'):
            new_haptic_requests(row, baseline=baseline)
        baseline = snapshot()
        baseline['haptics']['count'] = 1
        with self.assertRaises(Native14Error):
            new_haptic_requests(row, baseline=baseline)

    def test_overlapping_request_facts_are_fixed_but_computed_ages_can_change(self):
        baseline = scope_history(snapshot(), 1, last_sequence=101)
        row = scope_history(snapshot(), 2, last_sequence=102)
        row['copiedAtMicros'] = '101'
        row['frame']['ageMicros'] = '6'
        for event in row['haptics']['requests']:
            event['ageMicros'] = '3'
        self.assertEqual([event['sequence'] for event in new_haptic_requests(row, baseline=baseline)], ['102'])
        changes = {'physicalHand': 'right', 'slotNumber': 2, 'reason': 'slot_remove',
                   'frames': 9, 'duration': -10, 'producerTimeMicros': '97',
                   'token': {'loadGeneration': '1', 'frameSerial': '2', 'bodyGeneration': '4'}}
        for field, value in changes.items():
            changed = copy.deepcopy(row)
            changed['haptics']['requests'][0][field] = value
            if field == 'producerTimeMicros':
                changed['haptics']['requests'][0]['ageMicros'] = '4'
            with self.subTest(field=field):
                with self.assertRaisesRegex(Native14GapError, 'changed its recorded facts'):
                    new_haptic_requests(changed, baseline=baseline)

    def test_malformed_or_oversize_history_and_raw_signed_arguments(self):
        for field, value in (('count', 17), ('totalRequests', '3'), ('overwrittenRequests', '1')):
            row = snapshot()
            row['haptics'][field] = value
            with self.assertRaises(Native14Error):
                self.checked(row)
        row = snapshot()
        row['haptics']['requests'][1]['sequence'] = '1'
        with self.assertRaises(Native14Error):
            self.checked(row)
        row = snapshot()
        row['haptics']['requests'][1].update(frames=-(1 << 31), duration=-32768)
        self.checked(row)  # These are raw request arguments, not successful pulse values.


if __name__ == '__main__':
    unittest.main()
