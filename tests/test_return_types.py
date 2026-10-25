import math
import unittest
from skyrim_autotest.scenarios import check, result_type, validate


class ReturnedTypesTests(unittest.TestCase):
    def test_bool_never_coerces_strings_numbers_or_null(self):
        for value in (True, False):
            self.assertTrue(check({'returned': value}, {'path': 'returned', 'type': 'boolean'}))
        for value in ('true', 'false', 0, 1, None, [], {}):
            self.assertFalse(result_type(value, 'boolean'))

    def test_string_array_keeps_every_element_and_never_accepts_scalar_or_null(self):
        for value in ([], ['Amber', 'Bridge'], ['мост', '']):
            self.assertTrue(result_type(value, 'string[]'))
        for value in ('Amber', None, [None], ['Amber', 1], [True], [['Amber']]):
            self.assertFalse(result_type(value, 'string[]'))

    def test_finite_number_is_a_json_numeric_value_not_boolean_or_nonfinite(self):
        for value in (0, 1, -1.25, 0.0):
            self.assertTrue(result_type(value, 'number'))
        for value in (True, '0.0', None, math.nan, math.inf, -math.inf, 10**500):
            self.assertFalse(result_type(value, 'number'))
        self.assertFalse(result_type(True, 'integer'))
        self.assertFalse(result_type(1.0, 'integer'))
        self.assertTrue(result_type(1, 'integer'))

    def test_array_elements_remain_independently_typed(self):
        self.assertTrue(result_type([False, True], 'boolean[]'))
        self.assertFalse(result_type([False, 0], 'boolean[]'))
        self.assertTrue(result_type([1, 2], 'integer[]'))
        self.assertFalse(result_type([1, 2.0], 'integer[]'))
        self.assertTrue(result_type([1, 2.0], 'number[]'))
        self.assertFalse(result_type([1, math.nan], 'number[]'))

    def test_type_assertion_is_validated_before_launch(self):
        scenario = {'schemaVersion': 1, 'steps': [{'name': 'Typed return', 'tool': 'papyrus',
            'args': {'action': 'call', 'script': 'Fixture', 'function': 'KnownGetter'},
            'assert': [{'path': 'returned', 'type': 'string[]'}]}]}
        validate(scenario)
        for unsupported in ('guessed-native-layout', None, [], {}, True):
            scenario['steps'][0]['assert'][0]['type'] = unsupported
            with self.assertRaises(ValueError):
                validate(scenario)
            with self.assertRaises(ValueError):
                result_type([], unsupported)

    def test_type_and_value_checks_are_separate_assertions(self):
        observed = {'returned': ['Amber', 'Bridge']}
        self.assertTrue(check(observed, {'path': 'returned', 'type': 'string[]'}))
        self.assertTrue(check(observed, {'path': 'returned', 'equals': ['Amber', 'Bridge']}))
        self.assertFalse(check({'returned': {'raw': 'broken'}}, {'path': 'returned', 'type': 'string[]'}))
