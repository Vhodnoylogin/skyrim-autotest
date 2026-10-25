"""Owned-read fixtures: mock processes/transport, and hash temporary plain files only."""
import builtins
import copy
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from skyrim_autotest import native14_live as live
from skyrim_autotest import native, platform, runner
from test_native14 import snapshot


def later(raw, *, frame=None, load=None, body=None):
    row = copy.deepcopy(raw)
    row['publications'] = str(int(row['publications']) + 1)
    row['copiedAtMicros'] = str(int(row['copiedAtMicros']) + 1)
    row['frame']['producerTimeMicros'] = str(int(row['frame']['producerTimeMicros']) + 1)
    row['frame']['token']['frameSerial'] = str(frame if frame is not None else int(row['frame']['token']['frameSerial']) + 1)
    if load is not None:
        row['frame']['token']['loadGeneration'] = str(load)
    if body is not None:
        row['frame']['token']['bodyGeneration'] = str(body)
    for event in row['haptics']['requests']:
        event['ageMicros'] = str(int(row['copiedAtMicros']) - int(event['producerTimeMicros']))
    return row


class Native14LiveTests(unittest.TestCase):
    def setUp(self):
        self.box = tempfile.TemporaryDirectory()
        self.addCleanup(self.box.cleanup)
        self.root = Path(self.box.name)
        self.now = 10.0
        self.owner = {'pid': os.getpid(), 'birth': 123, 'path': str(self.root / 'python.exe')}
        self.game = {'pid': 77 if os.getpid() != 77 else 78, 'birth': 456,
                     'path': str(self.root / 'SkyrimVR.exe')}
        self.images = []
        pins = []
        for name in ('devbench.dll', 'VRIK.dll', 'BodySlots.dll'):
            path = self.root / name
            path.write_bytes(('plain fixture bytes ' + name).encode())
            self.images.append(str(path))
            pins.append({'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        self.policy = {'maxAgeMicros': 1000000, 'modules': pins, 'absentModules': []}
        self.raw = snapshot()
        self.raw['processId'] = self.game['pid']
        self.responses = [self.raw]
        self.last_response = self.raw
        self.logs, self.tool_calls, self.health_calls = [], [], []
        self.saves = 0
        self.guard_calls = 0
        self.guard_hook = None
        self.tool_hook = None
        self.identities = {self.owner['pid']: self.owner, self.game['pid']: self.game}
        self.health = {'pid': self.game['pid'], 'port': 12345, 'exe': 'SkyrimVR.exe', 'vr': True}
        self.session = SimpleNamespace(state={
            'runner': copy.deepcopy(self.owner), 'game': copy.deepcopy(self.game), 'done': False,
            'owned': [{'role': 'game', 'identity': copy.deepcopy(self.game)}], 'port': 12345,
            'configuration': {'game_edition': 'vr', 'native14_live': copy.deepcopy(self.policy)},
            'gameplayBootstrap': {'completed': True}, 'ownedWorldGeneration': 1}, lock=threading.RLock())
        self.session.log = lambda kind, **value: self.logs.append((kind, copy.deepcopy(value)))
        self.session.save = self.save
        self.session.tool = self.tool
        test = self
        class Backend:
            def __init__(self, session, deadline):
                self.session, self.deadline = session, deadline
            def guard_world(self):
                test.guard_calls += 1
                if test.guard_hook:
                    test.guard_hook(test.guard_calls)
        for patch in (mock.patch.object(live.time, 'monotonic', lambda: self.now),
                      mock.patch.object(live.time, 'sleep', lambda seconds: setattr(self, 'now', self.now + seconds)),
                      mock.patch.object(native, 'identity', lambda pid: copy.deepcopy(self.identities.get(pid))),
                      mock.patch.object(native, 'modules', lambda game: list(self.images)),
                      mock.patch.object(runner, 'request', self.request),
                      mock.patch.object(platform, 'Backend', Backend)):
            patch.start()
            self.addCleanup(patch.stop)

    def save(self):
        self.saves += 1

    def tool(self, name, args, timeout, deadline):
        self.tool_calls.append((name, copy.deepcopy(args), timeout, deadline))
        if self.tool_hook:
            self.tool_hook()
        if self.responses:
            self.last_response = self.responses.pop(0)
        return copy.deepcopy(self.last_response)

    def request(self, port, route, *, timeout):
        self.health_calls.append((port, route, timeout))
        return copy.deepcopy(self.health)

    def execute(self, args=None, deadline=20):
        return live.execute(self.session, args or {'select': {'visible': 'frame.displayHolsters'}}, deadline)

    def fails_unchanged(self, args=None, message=None, error=Exception, deadline=20):
        before = copy.deepcopy(self.session.state)
        with self.assertRaisesRegex(error, message) if message else self.assertRaises(error):
            self.execute(args, deadline=deadline)
        self.assertEqual(self.session.state, before)
        self.assertTrue(any(kind == 'native14-live-error' for kind, _ in self.logs))

    def test_configuration_is_normalized_without_requiring_source_files(self):
        value = copy.deepcopy(self.policy)
        value['modules'][0]['path'] = str(self.root / 'future' / 'devbench.dll')
        result = live.configuration(value)
        self.assertEqual(len(result['modules']), 3)
        self.assertEqual(result['maxAgeMicros'], 1000000)
        result['modules'][0]['path'] = 'changed'
        self.assertNotEqual(result, value)

    def test_policy_requires_known_modules_and_explicit_bodyslots_mode(self):
        modifications = [lambda row: row['modules'].pop(0),
                         lambda row: row['modules'].append(copy.deepcopy(row['modules'][0])),
                         lambda row: row.update(absentModules=['BodySlots.dll']),
                         lambda row: row.update(absentModules=['VRIK.dll']),
                         lambda row: row.update(maxAgeMicros=True),
                         lambda row: row.update(maxAgeMicros=0),
                         lambda row: row['modules'][0].update(path='devbench.dll'),
                         lambda row: row['modules'][0].update(sha256='A' * 64)]
        for change in modifications:
            row = copy.deepcopy(self.policy)
            change(row)
            with self.subTest(policy=row):
                with self.assertRaises(ValueError):
                    live.configuration(row)
        row = copy.deepcopy(self.policy)
        row['modules'].pop()
        with self.assertRaisesRegex(ValueError, 'BodySlots'):
            live.configuration(row)
        row['absentModules'] = ['BodySlots.dll']
        self.assertEqual(live.configuration(row)['absentModules'], ['bodyslots.dll'])

    def test_request_shape_names_and_bounded_selectors(self):
        self.assertEqual(live.validate_request({'select': {'x': 'frame.hands.0.probe.0.value'}})['transition'], 'same-context')
        for value in ({'select': {}}, {'select': {'../x': 'frame.contextFlags'}},
                      {'select': {'x': 'frame.slots.-1'}}, {'select': {'x': 'frame.contextFlags'}, 'action': 'read'},
                      {'select': {'x': 'frame.contextFlags'}, 'haptics': True},
                      {'select': {'x': 'frame.contextFlags'}, 'transition': 'new-load'},
                      {'select': {'x': 'frame.contextFlags'}, 'haptics': 1},
                      {'select': {str(i): 'frame.contextFlags' for i in range(65)}}):
            with self.assertRaises(ValueError):
                live.validate_request(value)

    def test_success_is_owned_kind_only_read_with_disk_evidence_and_observed_false(self):
        result = self.execute({'select': {'visible': 'frame.displayHolsters'}, 'tag': 'before'})
        self.assertTrue(result['available'])
        self.assertIs(result['observations']['visible'], False)
        self.assertIn('not_in_memory_byte_attestation', result['moduleEvidence']['basis'])
        self.assertEqual(len(result['moduleEvidence']['before']['images']), 3)
        self.assertEqual(len(self.health_calls), 2)
        self.assertEqual(self.guard_calls, 2)
        self.assertEqual(self.tool_calls[0][:2], ('inspect', {'kind': 'vrik_native14_v1'}))
        self.assertEqual(self.tool_calls[0][3], 20)
        self.assertEqual(self.saves, 1)
        self.assertEqual(self.session.state['native14Live']['tags']['before'], self.raw)

    def test_stable_absent_bodyslots_is_supported_but_loaded_absence_is_refused(self):
        self.session.state['configuration']['native14_live']['modules'].pop()
        self.session.state['configuration']['native14_live']['absentModules'] = ['BodySlots.dll']
        self.fails_unchanged(message='explicitly absent')
        self.images.pop()
        self.execute()

    def test_wrong_dead_foreign_or_finished_owner_is_refused_without_state_change(self):
        changes = [lambda: self.identities.pop(self.owner['pid']),
                   lambda: self.identities.pop(self.game['pid']),
                   lambda: self.identities[self.game['pid']].update(birth=999),
                   lambda: self.identities[self.game['pid']].update(path=str(self.root / 'foreign' / 'SkyrimVR.exe')),
                   lambda: self.session.state.update(owned=[]),
                   lambda: self.session.state.update(done=True),
                   lambda: self.session.state['gameplayBootstrap'].update(completed=False),
                   lambda: self.session.state['configuration'].update(game_edition='se')]
        for change in changes:
            old_state = copy.deepcopy(self.session.state)
            old_identities = copy.deepcopy(self.identities)
            change()
            self.fails_unchanged()
            self.session.state = old_state
            self.identities = old_identities
        self.assertEqual(self.tool_calls, [])

    def test_wrong_health_pid_port_executable_or_vr_is_refused(self):
        for field, value in (('pid', 999), ('port', 12346), ('exe', 'SkyrimSE.exe'), ('vr', False)):
            old = self.health[field]
            self.health[field] = value
            self.fails_unchanged(message='health PID/port/executable/VR')
            self.health[field] = old
        self.assertEqual(self.tool_calls, [])

    def test_missing_duplicate_path_and_unreadable_actual_modules_are_refused(self):
        original = list(self.images)
        self.images.pop(1)
        self.fails_unchanged(message='missing or its actual loaded path')
        self.images = original + original[:1]
        self.fails_unchanged(message='duplicate')
        other = self.root / 'other' / 'VRIK.dll'
        other.parent.mkdir()
        other.write_bytes(Path(original[1]).read_bytes())
        self.images = [original[0], str(other), original[2]]
        self.fails_unchanged(message='actual loaded path differs')
        self.images = original
        real_open = builtins.open
        def unreadable(path, *args, **kwargs):
            if Path(path).name.lower() == 'vrik.dll':
                raise PermissionError('actual enumerated path is unreadable')
            return real_open(path, *args, **kwargs)
        with mock.patch.object(live, 'open', unreadable, create=True):
            self.fails_unchanged(message='unreadable', error=PermissionError)
        self.assertEqual(self.tool_calls, [])

    def test_wrong_hash_never_uses_a_configured_alternative(self):
        self.session.state['configuration']['native14_live']['modules'][1]['sha256'] = '0' * 64
        self.fails_unchanged(message='disk-image SHA256 mismatch')
        self.assertEqual(self.tool_calls, [])

    def test_unrelated_module_addition_is_evidence_without_invalidating_declared_images(self):
        extra = self.root / 'unexpected.dll'
        extra.write_bytes(b'unloaded fixture')
        self.tool_hook = lambda: self.images.append(str(extra))
        result = self.execute()
        self.assertNotEqual(result['moduleEvidence']['before']['inventory'], result['moduleEvidence']['after']['inventory'])
        self.assertEqual(result['moduleEvidence']['before']['images'], result['moduleEvidence']['after']['images'])

    def test_same_byte_disk_identity_change_after_read_is_refused(self):
        image = Path(self.images[0])
        def change_stamp():
            st = image.stat()
            os.utime(image, ns=(st.st_atime_ns, st.st_mtime_ns + 1000000000))
        self.tool_hook = change_stamp
        self.fails_unchanged(message='inventory or disk-image identity changed')

    def test_hash_checks_stable_fstat_before_after(self):
        original = live.os.fstat
        count = 0
        def changed(descriptor):
            nonlocal count
            count += 1
            row = original(descriptor)
            return SimpleNamespace(st_dev=row.st_dev, st_ino=row.st_ino, st_size=row.st_size,
                                   st_mtime_ns=row.st_mtime_ns + (1 if count == 2 else 0), st_mode=row.st_mode)
        with mock.patch.object(live.os, 'fstat', changed):
            self.fails_unchanged(message='changed while hashing')

    def test_unavailable_error_wrong_pid_and_unobserved_selector_do_not_commit(self):
        bad = [dict(self.raw, availability='unavailable'), {'error': 'native unavailable'},
               dict(self.raw, processId=999)]
        for raw in bad:
            self.responses = [raw]
            self.fails_unchanged()
        self.responses = [self.raw]
        self.fails_unchanged({'select': {'unknown': 'frame.slots.0.scene.parentFlags'}}, message='not observed')
        self.assertEqual(self.saves, 0)

    def test_deadline_expiry_and_host_age_include_the_whole_postcheck_window(self):
        before = copy.deepcopy(self.session.state)
        with self.assertRaises(TimeoutError):
            self.execute(deadline=self.now)
        self.assertEqual(self.session.state, before)
        self.tool_hook = lambda: setattr(self, 'now', 21)
        self.fails_unchanged(error=TimeoutError)
        self.now, self.responses = 10.0, [self.raw]
        self.tool_hook = None
        self.session.state['configuration']['native14_live']['maxAgeMicros'] = 100
        after_sample_guard = self.guard_calls + 2
        def after_guard(number):
            if number == after_sample_guard:
                self.now += .001
        self.guard_hook = after_guard
        self.fails_unchanged(message='conservative age')

    def test_world_generation_drift_preserves_safety_state_but_not_a_native14_cursor(self):
        def drift(number):
            if number == 2:
                self.session.state['ownedWorldGeneration'] = 2
        self.guard_hook = drift
        with self.assertRaisesRegex(ValueError, 'world generation drifted'):
            self.execute()
        self.assertNotIn('native14Live', self.session.state)
        self.assertEqual(self.session.state['ownedWorldGeneration'], 2)

    def test_same_frame_is_sampled_until_fresh_and_deadline_keeps_the_old_stream(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        self.responses = [later(self.raw, frame=2), later(self.raw)]
        self.execute()
        self.assertEqual(self.session.state['native14Live']['cursor']['frame']['token']['frameSerial'], '3')
        self.assertEqual(len(self.tool_calls), 3)
        self.assertTrue(any(kind == 'native14-live-sampling' and row['outcome'] == 'same-frame'
                            for kind, row in self.logs))
        self.responses = [later(self.raw)]
        self.fails_unchanged(error=TimeoutError, deadline=self.now + .06)

    def test_pending_then_available_samples_only_within_the_original_deadline(self):
        pending = dict(self.raw, availability='pending', sourcePhase='pending')
        self.responses = [pending, self.raw]
        result = self.execute()
        self.assertTrue(result['available'])
        self.assertEqual(len(self.tool_calls), 2)
        self.assertEqual({call[3] for call in self.tool_calls}, {20})
        self.assertTrue(any(kind == 'native14-live-sampling' and row['outcome'] == 'pending'
                            for kind, row in self.logs))

    def test_pending_deadline_and_errors_never_commit_or_replay_failed_transport(self):
        pending = dict(self.raw, availability='pending', sourcePhase='pending')
        self.responses = [pending]
        self.fails_unchanged(error=TimeoutError, deadline=self.now + .06)
        calls = len(self.tool_calls)
        def failed_request():
            raise RuntimeError('transport refused')
        self.tool_hook = failed_request
        self.fails_unchanged(message='transport refused')
        self.assertEqual(len(self.tool_calls), calls + 1)

    def test_pending_header_errors_and_regressed_serial_metadata_are_not_sampled_again(self):
        pending = dict(self.raw, availability='pending', sourcePhase='pending')
        for field, value in (('processId', 999), ('schemaVersion', 2), ('copiedAtMicros', '00100'),
                             ('frame', None)):
            self.responses = [dict(pending, **{field: value}), self.raw]
            before = len(self.tool_calls)
            self.fails_unchanged()
            self.assertEqual(len(self.tool_calls), before + 1)
        malformed = []
        row = copy.deepcopy(pending)
        row['frame']['token']['frameSerial'] = '02'
        malformed.append(row)
        row = copy.deepcopy(pending)
        row['publications'] = '01'
        malformed.append(row)
        row = copy.deepcopy(pending)
        row['observations']['actions'] = 'observed'
        malformed.append(row)
        row = copy.deepcopy(pending)
        row['haptics']['claim'] = 'hardware_delivery'
        malformed.append(row)
        for row in malformed:
            self.responses = [row, self.raw]
            before = len(self.tool_calls)
            self.fails_unchanged()
            self.assertEqual(len(self.tool_calls), before + 1)
        self.responses = [dict(pending, publications='2'), self.raw]
        self.fails_unchanged(message='metadata regressed')

    def test_post_read_endpoint_drift_and_failed_save_never_commit_native14_state(self):
        self.tool_hook = lambda: self.health.update(port=12346)
        self.fails_unchanged(message='health PID/port/executable/VR')
        self.health['port'] = 12345
        self.tool_hook = None
        self.responses = [self.raw]
        attempts = 0
        def failed_save():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError('durable state write refused')
        self.session.save = failed_save
        self.fails_unchanged(message='durable state write refused', error=OSError)
        self.assertEqual(attempts, 2)

    def test_late_durable_save_persists_the_old_cursor_and_tags_with_current_safety_state(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        previous = copy.deepcopy(self.session.state['native14Live'])
        self.responses = [later(self.raw)]
        durable = {}
        saves = 0
        safety_guard = self.guard_calls + 2
        def safety(number):
            if number == safety_guard:
                self.session.state['lifecycleSafety'] = 'advanced-owned-cursor'
        self.guard_hook = safety
        def durable_save():
            nonlocal saves
            saves += 1
            durable.clear()
            durable.update(copy.deepcopy(self.session.state))
            if saves == 1:
                self.now = 21
        self.session.save = durable_save
        with self.assertRaises(TimeoutError):
            self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'failedTag'})
        self.assertEqual(saves, 2)
        self.assertEqual(self.session.state['native14Live'], previous)
        self.assertEqual(durable['native14Live'], previous)
        self.assertEqual(durable['lifecycleSafety'], 'advanced-owned-cursor')
        self.assertNotIn('failedTag', durable['native14Live']['tags'])

    def test_partial_durable_write_failure_also_persists_rollback(self):
        durable = {}
        attempts = 0
        def partial_write():
            nonlocal attempts
            attempts += 1
            durable.clear()
            durable.update(copy.deepcopy(self.session.state))
            if attempts == 1:
                raise OSError('failure after durable cursor replacement')
        self.session.save = partial_write
        self.fails_unchanged(message='failure after durable cursor replacement', error=OSError)
        self.assertEqual(attempts, 2)
        self.assertNotIn('native14Live', durable)

    def test_failed_rollback_is_explicit_durable_uncertainty_and_blocks_further_reads(self):
        durable = {}
        attempts = 0
        def uncertain_write():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                durable.update(copy.deepcopy(self.session.state))
            raise OSError('disk commit/rollback unavailable')
        self.session.save = uncertain_write
        with self.assertRaisesRegex(live.Native14DurabilityError, 'durable commit uncertainty'):
            self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'uncertainTag'})
        self.assertEqual(attempts, 3)
        self.assertIn('native14Live', durable)  # Never claim this on-disk commit was undone.
        self.assertNotIn('native14Live', self.session.state)
        self.assertTrue(self.session.state['native14LiveCommitUncertain'])
        calls = len(self.tool_calls)
        with self.assertRaisesRegex(live.Native14LiveError, 'further reads refused'):
            self.execute()
        self.assertEqual(len(self.tool_calls), calls)

    def test_equal_copy_ticks_and_nonregressing_phase_counters_are_supported(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        same_tick = copy.deepcopy(self.raw)
        same_tick['frame']['token']['frameSerial'] = '3'
        same_tick['publications'] = '2'
        self.responses = [same_tick]
        self.execute()
        body = copy.deepcopy(same_tick)
        body['frame']['token']['bodyGeneration'] = '4'
        self.responses = [body]
        self.execute({'select': {'x': 'frame.contextFlags'}, 'baseline': 'start', 'transition': 'new-body'})

    def test_duplicate_unknown_tags_and_other_game_stream_are_refused(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        for args in ({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'},
                     {'select': {'x': 'frame.contextFlags'}, 'baseline': 'missing'}):
            self.fails_unchanged(args)
        self.session.state['native14Live']['game']['birth'] = 1000
        self.fails_unchanged(message='another game')

    def test_new_body_and_load_require_declared_transition_and_named_baseline(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        self.responses = [later(self.raw, frame=2, body=4)]
        self.fails_unchanged(message='same load/body context')
        self.responses = [later(self.raw, frame=2, body=4)]
        self.execute({'select': {'x': 'frame.contextFlags'}, 'baseline': 'start', 'transition': 'new-body', 'tag': 'body'})
        previous = self.session.state['native14Live']['cursor']
        self.responses = [later(previous, frame=3, load=2, body=5)]
        self.execute({'select': {'x': 'frame.contextFlags'}, 'baseline': 'body', 'transition': 'new-load'})

    def test_tagged_multiframe_haptic_interval_uses_only_observed_new_requests(self):
        self.execute({'select': {'x': 'frame.contextFlags'}, 'tag': 'start'})
        current = later(self.raw)
        event = copy.deepcopy(current['haptics']['requests'][-1])
        event.update(sequence='3', token=copy.deepcopy(current['frame']['token']))
        current['haptics']['requests'].append(event)
        current['haptics'].update(totalRequests='3', count=3)
        self.responses = [current]
        result = self.execute({'select': {'x': 'frame.contextFlags'}, 'baseline': 'start', 'haptics': True})
        self.assertEqual([row['sequence'] for row in result['hapticRequests']], ['3'])
        self.assertEqual(result['observations']['x'], 0)

    def test_game_identity_changes_during_raw_read_are_refused(self):
        self.tool_hook = lambda: self.identities[self.game['pid']].update(birth=999)
        self.fails_unchanged(message='identity is dead, changed')


if __name__ == '__main__':
    unittest.main()
