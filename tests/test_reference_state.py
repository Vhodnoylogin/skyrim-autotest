import copy
import time
import unittest

from skyrim_autotest.platform import Backend


REF = '0xFF001234'
REQ = {'observation': 'reference.state', 'referenceTag': 'fixture'}


class Session:
    def __init__(self):
        self.state = {'platformReferences': {'fixture': {'id': REF}}}


class ReferenceStateTests(unittest.TestCase):
    def setUp(self):
        self.b = Backend(Session(), time.monotonic()+20)
        self.raw = {'count': 1, 'refs': [{'formId': REF, 'quantityItems': 5}]}
        self.row = {'status': 'available', 'identity': {'form': REF, 'runtimeHandle': 7, 'loadGeneration': 1},
                    'loaded3D': True, 'deleted': False, 'disabled': False}
        self.snapshot = {'ok': True, 'phase': 'skse_main_thread_task', 'sessionId': 'same-session',
                         'loadGeneration': 1, 'refs': [self.row]}
        self.calls = []
        self.guards = []
        self.b.guard_world = lambda: self.guards.append(True)
        self.b.call = self.call
        self.b.pap = lambda *a, **kw: True
        self.b.item = lambda *a: {'runtimeId': '0x0003EADD'}

    def call(self, tool, args):
        self.calls.append((tool, copy.deepcopy(args)))
        return self.raw if args['kind'] == 'refs' else self.snapshot

    def read(self):
        return self.b.observe(REQ)

    def missing(self):
        self.raw = {'count': 0, 'refs': []}
        self.snapshot['refs'] = [{'form': REF, 'status': 'unavailable', 'reason': 'Reference not resolved'}]

    def assert_absent(self, status):
        self.b.pap = lambda *a, **kw: self.fail('Do not call Papyrus on an absent reference')
        self.b.item = lambda *a: self.fail('Do not resolve base of an absent reference')
        result = self.read()
        ref = result['reference']
        self.assertIs(ref['existsInLoadedWorld'], False)
        self.assertEqual(ref['presence'], status)
        self.assertEqual(ref['id'], REF)
        self.assertNotIn('items', ref['quantity'])
        self.assertIs(ref['quantity']['available'], False)
        self.assertNotIn('runtimeId', ref['item'])
        self.assertEqual(result['presenceObservation'], self.snapshot)
        self.assertEqual(len(self.guards), 2)

    def test_exact_unresolved_lookup_is_not_loaded_and_has_no_quantity(self):
        self.missing()
        self.assert_absent('not_resolved')

    def test_deleted_tombstone_count_is_raw_only_even_with_loaded_tree(self):
        self.row['deleted'] = True
        self.assert_absent('deleted')

    def test_unloaded_resolved_reference_has_no_live_world_quantity(self):
        self.row['loaded3D'] = False
        self.assert_absent('unloaded')

    def test_loaded_quantity_and_identity_remain_actual(self):
        result = self.read()['reference']
        self.assertTrue(result['existsInLoadedWorld'])
        self.assertEqual(result['quantity']['items'], 5)
        self.assertEqual(result['item']['runtimeId'], '0x0003EADD')

    def test_loaded_missing_count_cannot_be_synthesized(self):
        del self.raw['refs'][0]['quantityItems']
        with self.assertRaisesRegex(ValueError, 'stack-count'):
            self.read()

    def test_non_boolean_papyrus_result_is_not_absence(self):
        for value in (None, {}, 0, 1, 'false'):
            self.b.pap = lambda *a, **kw: value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'boolean'):
                self.read()

    def test_changed_loaded_state_stops_without_polling(self):
        self.b.pap = lambda *a, **kw: False
        with self.assertRaisesRegex(ValueError, 'changed between samples'):
            self.read()
        self.assertEqual(len(self.calls), 2)

    def test_unknown_unavailable_reason_never_proves_absence(self):
        self.missing()
        for reason in ('Non-finite reference transform', 'deadline', '', None):
            self.snapshot['refs'][0]['reason'] = reason
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                self.read()

    def test_empty_malformed_or_wrong_native_response_is_not_absence(self):
        for response in ({}, {'refs': []}, {'count': True, 'refs': []}, {'count': 1, 'refs': []},
                         {'count': 0, 'refs': None}, {'count': 1, 'refs': [{'formId': '0xFF009999'}]},
                         {'count': 2, 'refs': [self.raw['refs'][0], self.raw['refs'][0]]}):
            self.raw = response
            with self.subTest(response=response), self.assertRaises(ValueError):
                self.read()

    def test_wrong_or_incomplete_presence_never_proves_absence(self):
        self.missing()
        valid = copy.deepcopy(self.snapshot)
        for key, value in (('ok', False), ('loadGeneration', True), ('phase', 'unknown'),
                           ('sessionId', ''), ('refs', []), ('refs', [{'status': 'unavailable',
                           'reason': 'Reference not resolved', 'form': '0xFF009999'}])):
            self.snapshot = dict(valid, **{key: value})
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.read()

    def test_reused_handle_or_changed_observer_epoch_rejected(self):
        self.b.s.state['platformReferences']['fixture']['incarnation'] = {
            'sessionId': 'same-session', 'loadGeneration': 1, 'runtimeHandle': 7}
        for change in ('handle', 'generation', 'session'):
            old = copy.deepcopy(self.snapshot)
            if change == 'handle': self.row['identity']['runtimeHandle'] = 8
            if change == 'generation': self.snapshot['loadGeneration'] = 2
            if change == 'session': self.snapshot['sessionId'] = 'other'
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.read()
            self.snapshot = old
            self.row = self.snapshot['refs'][0]

    def test_known_incarnation_can_be_absent_only_in_same_epoch(self):
        self.b.s.state['platformReferences']['fixture']['incarnation'] = {
            'sessionId': 'same-session', 'loadGeneration': 1, 'runtimeHandle': 7}
        self.missing()
        self.assert_absent('not_resolved')
        self.snapshot['loadGeneration'] = 2
        with self.assertRaisesRegex(ValueError, 'session/generation'):
            self.read()

    def test_world_changed_after_read_remains_terminal(self):
        self.missing()
        def guard():
            self.guards.append(True)
            if len(self.guards) == 2: raise ValueError('generation changed')
        self.b.guard_world = guard
        with self.assertRaisesRegex(ValueError, 'generation changed'):
            self.read()


if __name__ == '__main__':
    unittest.main()
