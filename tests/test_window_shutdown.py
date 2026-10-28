"""Posted WM_CLOSE, one original grace and actual owned exit proof."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from skyrim_autotest import config, game_shutdown as shutdown
from tests.test_game_shutdown import Clock, GAME, Session


def receipt(**fields):
    return {'requested': True, 'windows': [{'hwnd': 888, 'message': 16, 'accepted': True, 'error': 0}],
            'systemCommand': False, 'shutdownObserved': False, **fields}


class WindowExitTests(unittest.TestCase):
    def setUp(self):
        self.stack, self.clock, self.s = ExitStack(), Clock(), Session()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(shutdown.time, 'monotonic', self.clock.monotonic))
        self.stack.enter_context(patch.object(shutdown.time, 'sleep', self.clock.sleep))
        self.alive = self.stack.enter_context(patch.object(shutdown.native, 'alive', side_effect=lambda g: self.clock.now < .6))
        self.stack.enter_context(patch.object(shutdown.native, 'identity', side_effect=lambda pid: GAME if self.clock.now < .6 else None))
        self.close = self.stack.enter_context(patch.object(shutdown.native, 'close', side_effect=self.post))
        self.kill = self.stack.enter_context(patch.object(shutdown.native, 'terminate'))
        self.addCleanup(self.check_no_force_or_console)
    def check_no_force_or_console(self):
        self.kill.assert_not_called(); self.s.tool.assert_not_called()
    def post(self, game):
        self.assertEqual(game, GAME)
        r = self.s.saved[-1]['gracefulGameExit']
        self.assertEqual(r['command'], 'window-close'); self.assertTrue(r['requestAttempted'])
        return receipt()
    def test_post_is_intent_not_exit_then_actual_zero_qualifies(self):
        self.assertTrue(shutdown.request_and_wait(self.s, seconds=30, route='window-close'))
        self.close.assert_called_once_with(GAME)
        self.assertGreaterEqual(self.clock.now, .6)
        r = self.s.state['gracefulGameExit']
        self.assertEqual(r['deadlineMonotonic'], 30.)
        self.assertFalse(r['windowClose']['shutdownObserved'])
        self.assertEqual(shutdown.classify_exit(self.s)['kind'], 'normal_close')
    def test_uncertain_post_is_not_replayed_or_given_another_grace(self):
        self.alive.side_effect = None; self.alive.return_value = True
        self.close.side_effect = OSError('request outcome unavailable')
        self.assertFalse(shutdown.request_and_wait(self.s, seconds=1, route='window-close'))
        self.assertEqual(self.clock.now, 1.)
        self.assertFalse(shutdown.request_and_wait(self.s, seconds=1, route='window-close'))
        self.close.assert_called_once()
    def test_recovery_does_not_repeat_acknowledged_close(self):
        self.assertTrue(shutdown.request_and_wait(self.s, route='window-close'))
        self.assertTrue(shutdown.request_and_wait(self.s, route='window-close'))
        self.close.assert_called_once()
    def test_empty_declined_malformed_or_wrong_message_never_proves_owned_request(self):
        for value in (None, receipt(requested=False), receipt(systemCommand=True), receipt(windows=[]),
                      receipt(windows=[{'hwnd': 888, 'message': 16, 'accepted': False, 'error': 5}]),
                      receipt(windows=[{'hwnd': 888, 'message': 0x112, 'accepted': True, 'error': 0}]),
                      receipt(windows=[{'hwnd': True, 'message': 16, 'accepted': True, 'error': 0}])):
            with self.subTest(value=value): self.assertFalse(shutdown.window_close_receipt(value))
    def test_accepted_owned_post_can_coexist_with_other_failed_owned_window_posts(self):
        value = receipt(); value['windows'].append({'hwnd': 889, 'message': 16, 'accepted': False, 'error': 5})
        self.assertTrue(shutdown.window_close_receipt(value))
    def test_exit_without_accepted_receipt_remains_unknown(self):
        self.close.side_effect = lambda game: receipt(windows=[])
        self.assertTrue(shutdown.request_and_wait(self.s, route='window-close'))
        self.assertEqual(shutdown.classify_exit(self.s)['kind'], 'unknown')
    def test_nonzero_or_forced_exit_still_fails_despite_successful_post(self):
        self.assertTrue(shutdown.request_and_wait(self.s, route='window-close'))
        self.s.state['gameProcessObservations'][-1]['exitCode'] = 0xC0000005
        self.assertEqual(shutdown.classify_exit(self.s)['kind'], 'abnormal_exit')
        self.s.state['forcedGameStop'] = True
        self.assertEqual(shutdown.classify_exit(self.s)['kind'], 'forced_stop')
    def test_other_route_or_process_is_never_adopted(self):
        self.s.state['gracefulGameExit'] = {'game': copy.deepcopy(GAME), 'command': 'qqq'}
        with self.assertRaises(RuntimeError): shutdown.request_and_wait(self.s, route='window-close')
        self.close.assert_not_called()
    def test_new_se_templates_select_owned_window_route_and_vr_is_unchanged(self):
        self.assertEqual(config.template('se')['se_shutdown'], 'window-close-v1')
        self.assertNotIn('se_shutdown', config.template('vr'))


if __name__ == '__main__': unittest.main()
