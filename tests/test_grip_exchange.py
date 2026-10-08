import copy
import unittest
from unittest.mock import patch

from skyrim_autotest import grip_exchange, platform
from skyrim_autotest.hardware import neutral


REQUEST = {'action': 'exchange_grip', 'fromHand': 'right', 'toHand': 'left',
           'referenceTag': 'bottle-a', 'settleSeconds': .2}


class Fake:
    end = 100

    def __init__(self):
        self.s = self
        self.state = {'inputBackend': 'driver', 'driverBackend': 'file'}
        self.logs, self.calls, self.publications = [], [], []
        self.input = neutral()
        self.input['right']['controller']['pressed'] = 4
        self.identities = [{'sessionId': 'game1', 'loadGeneration': 1, 'runtimeHandle': 9}] * 2
        self.held_values = [{'formId': '0xff001234'}, None]
        self.can_grab = True
        self.time_left = 10
        self.world_checks = 0
        self.fail_publication = False
        self.fail_world_at = None

    def log(self, *a, **kw): self.logs.append((a, kw))
    def remaining(self):
        if self.time_left <= 0: raise TimeoutError('deadline')
        return self.time_left
    def recover_input_gate(self, menus): pass
    def call(self, tool, args):
        self.calls.append((tool, args))
        return {'messageBoxOpen': False, 'openMenus': [], 'menuStates': []}
    def tagged(self, req): return '0xFF001234'
    def reference_incarnation(self, ref): return self.identities.pop(0)
    def pap(self, script, function, args):
        self.calls.append((script, function, args))
        if function == 'CanGrabObject': return self.can_grab
        return self.held_values.pop(0)
    def frame(self): return copy.deepcopy(self.input)
    def publish(self, frame, duration):
        self.publications.append((copy.deepcopy(frame), duration))
        if self.fail_publication: raise OSError('unknown publication outcome')
        return {'published': True}
    def pause(self, seconds): self.remaining()
    def guard_world(self):
        self.world_checks += 1
        if self.world_checks == self.fail_world_at: raise ValueError('world changed')


@patch('skyrim_autotest.vr_probe.ensure_owned_focus')
class ExchangeTests(unittest.TestCase):
    def test_one_command_changes_only_two_grip_masks_and_never_claims_race(self, focus):
        b = Fake()
        before = copy.deepcopy(b.input)
        result = grip_exchange.perform(b, REQUEST)
        self.assertEqual(len(b.publications), 1)
        frame, duration = b.publications[0]
        expected = copy.deepcopy(before)
        expected['right']['controller']['pressed'] = 0
        expected['left']['controller']['pressed'] = 4
        self.assertEqual(frame, expected)
        self.assertEqual(b.input, before)
        self.assertEqual(duration, .2)
        self.assertTrue(result['inputIssued'])
        self.assertFalse(result['gripExchange']['nativeRaceProven'])
        self.assertFalse(result['gripExchange']['consumerAtomicityProven'])
        self.assertIsNone(result['observedGameplaySuccess'])
        self.assertEqual([c[1] for c in b.calls if c[0] == 'HiggsVR'], ['GetGrabbedObject'] * 2 + ['CanGrabObject'])
        focus.assert_called_once()

    def test_wrong_source_occupied_or_unknown_receiver_never_publishes(self, focus):
        for values in ([{'formId': '0xFF009999'}, None],
                       [{'formId': '0xFF001234'}, {'formId': '0xFF008888'}],
                       [{'formId': '0xFF001234'}, {}],
                       [None, None]):
            with self.subTest(values=values):
                b = Fake(); b.held_values = copy.deepcopy(values)
                with self.assertRaises(ValueError): grip_exchange.perform(b, REQUEST)
                self.assertEqual(b.publications, [])

    def test_changed_incarnation_cannot_reuse_reference_number(self, focus):
        b = Fake(); b.identities[1] = dict(b.identities[1], runtimeHandle=10)
        with self.assertRaisesRegex(ValueError, 'incarnation'): grip_exchange.perform(b, REQUEST)
        self.assertEqual(b.publications, [])

    def test_non_neutral_buttons_or_axes_are_not_silently_released(self, focus):
        for hand, key, value in [('right', 'pressed', 0), ('right', 'pressed', 5),
                                 ('left', 'pressed', 4), ('left', 'touched', 2),
                                 ('right', 'axes', [[1, 0]] * 5), ('right', 'pressed', True)]:
            with self.subTest(hand=hand, key=key, value=value):
                b = Fake(); b.input[hand]['controller'][key] = value
                with self.assertRaisesRegex(ValueError, 'neutral'): grip_exchange.perform(b, REQUEST)
                self.assertEqual(b.publications, [])

    def test_unknown_publication_outcome_is_not_replayed(self, focus):
        b = Fake(); b.fail_publication = True
        with self.assertRaises(OSError): grip_exchange.perform(b, REQUEST)
        self.assertEqual(len(b.publications), 1)
        self.assertEqual(b.world_checks, 1)

    def test_original_deadline_is_checked_before_edge(self, focus):
        b = Fake(); b.time_left = .1
        with self.assertRaises(TimeoutError): grip_exchange.perform(b, REQUEST)
        self.assertEqual(b.publications, [])

    def test_unready_receiver_and_nonphysical_backend_refuse_before_edge(self, focus):
        b = Fake(); b.can_grab = False
        with self.assertRaisesRegex(ValueError, 'ready'): grip_exchange.perform(b, REQUEST)
        self.assertEqual(b.publications, [])
        for key, value in [('inputBackend', 'devbench'), ('driverBackend', 'other')]:
            b = Fake(); b.state[key] = value
            with self.assertRaisesRegex(ValueError, 'physical file'): grip_exchange.perform(b, REQUEST)
            self.assertEqual(b.calls, [])
            self.assertEqual(b.publications, [])

    def test_world_failure_before_or_after_edge_never_replays(self, focus):
        for fail_at, count in [(1, 0), (2, 1)]:
            with self.subTest(fail_at=fail_at):
                b = Fake(); b.fail_world_at = fail_at
                with self.assertRaisesRegex(ValueError, 'world changed'): grip_exchange.perform(b, REQUEST)
                self.assertEqual(len(b.publications), count)

    def test_closed_menu_and_focus_required_before_edge(self, focus):
        b = Fake()
        b.call = lambda *a: {'messageBoxOpen': True, 'openMenus': [], 'menuStates': []}
        with self.assertRaisesRegex(ValueError, 'blocked'): grip_exchange.perform(b, REQUEST)
        self.assertEqual(b.publications, [])
        b = Fake(); focus.side_effect = ValueError('foreign game')
        with self.assertRaisesRegex(ValueError, 'foreign'): grip_exchange.perform(b, REQUEST)
        self.assertEqual(b.calls, [])
        self.assertEqual(b.publications, [])


class ContractTests(unittest.TestCase):
    def test_explicit_semantic_request_and_controller_only(self):
        platform.validate({'operation': 'controller.perform', 'request': REQUEST})
        for op, req in [('object.perform', REQUEST),
                        ('controller.perform', dict(REQUEST, toHand='right')),
                        ('controller.perform', dict(REQUEST, toHand=[])),
                        ('controller.perform', dict(REQUEST, settleSeconds=0)),
                        ('controller.perform', dict(REQUEST, settleSeconds=True)),
                        ('controller.perform', dict(REQUEST, referenceTag='../file')),
                        ('controller.perform', dict(REQUEST, callback='inject'))]:
            with self.subTest(op=op, req=req):
                with self.assertRaises(ValueError): platform.validate({'operation': op, 'request': req})

    def test_backend_dispatch_has_no_extra_publication_or_read_in_edge(self):
        b = platform.Backend(None, 100)
        with patch.object(grip_exchange, 'perform', return_value={'inputIssued': True}) as perform:
            self.assertTrue(b.controller(REQUEST)['inputIssued'])
            perform.assert_called_once_with(b, REQUEST)


if __name__ == '__main__': unittest.main()
