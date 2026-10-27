"""Pure schema checks; no runtime, game or provider is contacted."""
from copy import deepcopy
import json
import unittest

from skyrim_autotest.observer_query import validate


class ObserverQueryTests(unittest.TestCase):
    def query(self, **fields):
        return {'kind': 'world_observer', **fields}

    def check(self, args, timeout=3, edition='se'):
        before = deepcopy(args)
        self.assertIs(validate(args, timeout, edition), args)
        self.assertEqual(args, before)

    def reject(self, args, timeout=3, edition='se'):
        with self.assertRaises(ValueError):
            validate(args, timeout, edition)

    def test_allowed_read_only_shape_is_unchanged(self):
        self.check(self.query())
        self.check(self.query(action='snapshot', refs=[20, '0xFFFFFFFF'], nodes=[
            {'ref': '0x14', 'name': 'NPC Pelvis [Pelv]', 'firstPerson': False}],
            actors=True, cbpc=True, skee={'refs': [20], 'morphs': ['Human', 'Wolf']},
            obody={'refs': [20], 'afterSequence': 0, 'maximumEvents': 256}, timeoutMs=3000))
        self.check(self.query(refs=[], nodes=[], actors=False, cbpc=False, obody={}))
        self.check(self.query(action='capabilities'), timeout=.01)

    def test_se_only_and_explicit_kind_action(self):
        for edition in ('vr', 'SE', '', None, True):
            self.reject(self.query(), edition=edition)
        for args in ({}, [], None, {'kind': 'scene'}, {'kind': True}, {'kind': 'world_observer', 'action': True}):
            self.reject(args)
        for action in ('capture', 'start', 'evaluate', 'set', '', None, 1):
            self.reject(self.query(action=action))
        for field, value in (('refs', []), ('timeoutMs', 100), ('actors', False), ('skee', {}), ('nodes', [])):
            self.reject(self.query(action='capabilities', **{field: value}))

    def test_forms_match_native_nonzero_uint32_and_exact_hex(self):
        self.check(self.query(refs=[1, 0xffffffff, '0x1', '0x00000001', '0xAbCdEF12']))
        invalid = (True, False, 0, -1, 1 << 32, 20.0, float('nan'), float('inf'),
                   '20', '0x0', '0x00000000', '0X14', '0x100000000', '0x000000001',
                   '0x+14', '0x-1', '0x 14', ' 0x14', '0x14\n', 'player', None, {})
        for form in invalid:
            with self.subTest(form=repr(form)):
                self.reject(self.query(refs=[form]))
                self.reject(self.query(nodes=[{'ref': form, 'name': 'Hand'}]))
                self.reject(self.query(skee={'refs': [form], 'morphs': ['Human']}))
                self.reject(self.query(obody={'refs': [form]}))

    def test_reference_and_node_cardinality_boundaries(self):
        self.check(self.query(refs=[20] * 16, nodes=[{'ref': 20, 'name': 'Hand'}] * 64))
        self.reject(self.query(refs=[20] * 17))
        self.reject(self.query(nodes=[{'ref': 20, 'name': 'Hand'}] * 65))
        for value in (None, '0x14', {}, (20,), True):
            self.reject(self.query(refs=value))
            self.reject(self.query(nodes=value))
        for node in ({'ref': 20}, {'name': 'Hand'}, [], True,
                     {'ref': 20, 'name': 'Hand', 'firstPerson': 0},
                     {'ref': 20, 'name': 'Hand', 'firstPerson': 'false'}):
            self.reject(self.query(nodes=[node]))

    def test_names_count_utf8_bytes_reject_nul_and_surrogates(self):
        for name in ('x' * 128, 'я' * 64, '🐺' * 32):
            self.check(self.query(nodes=[{'ref': 20, 'name': name, 'firstPerson': True}],
                                  skee={'refs': [20], 'morphs': [name]}))
        for name in ('', 'x' * 129, 'я' * 65, '🐺' * 33, 'A\0B', '\ud800', 14, None):
            self.reject(self.query(nodes=[{'ref': 20, 'name': name}]))
            self.reject(self.query(skee={'refs': [20], 'morphs': [name]}))

    def test_skee_explicit_bounds_and_pair_limit(self):
        self.check(self.query(skee={'refs': [20] * 2, 'morphs': ['Human'] * 32}))
        self.check(self.query(skee={'refs': [20] * 16, 'morphs': ['Human'] * 4}))
        bad = ({}, {'refs': [20]}, {'morphs': ['Human']}, {'refs': [], 'morphs': ['Human']},
               {'refs': [20] * 17, 'morphs': ['Human']}, {'refs': [20], 'morphs': []},
               {'refs': [20], 'morphs': ['Human'] * 33}, {'refs': [20] * 3, 'morphs': ['Human'] * 22},
               {'refs': [20], 'morphs': 'Human'}, None, [])
        for skee in bad:
            self.reject(self.query(skee=skee))

    def test_obody_cursors_and_event_bounds_reject_numeric_coercion(self):
        self.check(self.query(obody={'refs': [20] * 16, 'afterSequence': (1 << 64) - 1, 'maximumEvents': 1}))
        self.check(self.query(obody={'afterSequence': 0, 'maximumEvents': 256}))
        for refs in ([], [20] * 17, '0x14'):
            self.reject(self.query(obody={'refs': refs}))
        for cursor in (-1, 1 << 64, True, False, 0.0, '0', float('nan'), float('inf')):
            self.reject(self.query(obody={'afterSequence': cursor}))
        for count in (0, 257, True, False, 1.0, '1', float('nan')):
            self.reject(self.query(obody={'maximumEvents': count}))

    def test_timeout_default_and_exact_enclosing_deadline(self):
        self.check(self.query(), timeout=1.5)
        self.reject(self.query(), timeout=1.4999999)
        self.check(self.query(timeoutMs=100), timeout=.1)
        self.reject(self.query(timeoutMs=100), timeout=.0999999)
        self.check(self.query(timeoutMs=3000), timeout=3)
        for timeout in (99, 3001, True, False, 1500.0, '1500', None, float('nan'), float('inf')):
            self.reject(self.query(timeoutMs=timeout))
        for enclosing in (0, -1, True, False, None, '3', float('nan'), float('inf'), -float('inf'), 1 << 10000):
            self.reject(self.query(), timeout=enclosing)
            self.reject(self.query(action='capabilities'), timeout=enclosing)

    def test_unknown_fields_at_every_level_and_boolean_fields(self):
        for field in ('physics', 'render', 'vrPicking', 'actorState', 'command', 'captureAction',
                      'setMorph', 'provider', 'path', 'url', 'script'):
            self.reject(self.query(**{field: False}))
        for field in ('actors', 'cbpc'):
            for value in (0, 1, None, 'true', {}, float('nan')):
                self.reject(self.query(**{field: value}))
        self.reject(self.query(nodes=[{'ref': 20, 'name': 'Hand', 'offset': 0}]))
        self.reject(self.query(skee={'refs': [20], 'morphs': ['Human'], 'keys': ['CLAW']}))
        self.reject(self.query(obody={'refs': [20], 'ready': True}))
        self.reject(self.query(obody={'maxEvents': 1}))

    def test_ascii_escaped_wire_limit_is_conservative(self):
        # UTF-8 is under 16KiB; the default transport expands each wolf to a
        # surrogate pair, so counting only UTF-8 would admit an oversized query.
        args = self.query(nodes=[{'ref': 20, 'name': '🐺' * 32}] * 64)
        self.assertLess(len(json.dumps(args, ensure_ascii=False).encode('utf-8')), 16384)
        self.assertGreater(len(json.dumps(args, ensure_ascii=True).encode('utf-8')), 16384)
        self.reject(args)
        below = self.query(nodes=[{'ref': 20, 'name': '🐺' * 32}] * 38)
        self.assertLessEqual(len(json.dumps(below, ensure_ascii=True).encode('utf-8')), 16384)
        self.check(below)


if __name__ == '__main__':
    unittest.main()
