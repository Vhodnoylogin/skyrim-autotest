"""Graceful close delivery observes owned identity and never implies exit."""
from contextlib import ExitStack
import unittest
from unittest.mock import MagicMock, patch
from skyrim_autotest import native


class CloseTests(unittest.TestCase):
    def test_system_close_uses_only_visible_owned_window_and_records_delivery(self):
        ui = MagicMock()
        ident = {'pid': 42, 'birth': 1, 'path': 'owned.exe'}
        def owner(hwnd, out): out._obj.value = 99 if hwnd == 300 else 42
        ui.GetWindowThreadProcessId.side_effect = owner
        ui.IsWindowVisible.side_effect = lambda hwnd: hwnd != 200
        ui.EnumWindows.side_effect = lambda callback, _: [callback(h,0) for h in (100,200,300)]
        ui.PostMessageW.return_value = False
        with patch.object(native, 'U', ui), patch.object(native, 'alive', return_value=True), \
             patch.object(native.C, 'get_last_error', return_value=5):
            result = native.close(ident, system_command=True)
        ui.PostMessageW.assert_called_once_with(100,0x112,0xF060,0)
        self.assertFalse(result['windows'][0]['accepted'])
        self.assertEqual(result['windows'][0]['error'],5)
        self.assertFalse(result['shutdownObserved'])

    def test_identity_loss_prevents_any_close_request(self):
        with patch.object(native,'alive',return_value=False), patch.object(native,'U') as ui:
            result = native.close({'pid':42},system_command=True)
        ui.PostMessageW.assert_not_called()
        self.assertFalse(result['requested'])


class PrimaryGameCloseTests(unittest.TestCase):
    """No real window query or message: all Win32 calls use this fake API."""
    def setUp(self):
        self.ident = {'pid': 42, 'birth': 1234, 'path': 'D:/Game/SkyrimSE.exe'}
        self.rows = {
            100: {'pid': 42, 'thread': 123, 'class': 'Skyrim Special Edition', 'visible': True, 'owner': 0, 'style': 0},
            200: {'pid': 42, 'thread': 456, 'class': 'HiddenHelper', 'visible': False, 'owner': 0, 'style': 0},
            300: {'pid': 42, 'thread': 789, 'class': 'PopupHelper', 'visible': True, 'owner': 100, 'style': 0},
            400: {'pid': 99, 'thread': 987, 'class': 'Skyrim Special Edition', 'visible': True, 'owner': 0, 'style': 0},
        }
        self.error = 0
        self.ui = MagicMock()
        self.ui.GetWindowThreadProcessId.side_effect = self.owner
        self.ui.GetClassNameW.side_effect = self.window_class
        self.ui.GetWindow.side_effect = lambda hwnd, _: self.rows[hwnd]['owner']
        self.ui.GetWindowLongPtrW.side_effect = lambda hwnd, _: self.rows[hwnd]['style']
        self.ui.IsWindowVisible.side_effect = lambda hwnd: self.rows[hwnd]['visible']
        self.ui.EnumWindows.side_effect = self.enumerate
        self.ui.PostMessageW.return_value = True
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(native, 'U', self.ui))
        self.alive = self.stack.enter_context(patch.object(native, 'alive', return_value=True))
        self.stack.enter_context(patch.object(native.C, 'get_last_error', side_effect=lambda: self.error))
        self.stack.enter_context(patch.object(native.C, 'set_last_error', side_effect=lambda value: setattr(self, 'error', value)))
    def owner(self, hwnd, out):
        row = self.rows[hwnd]
        out._obj.value = row['pid']
        return row['thread']
    def window_class(self, hwnd, out, maximum):
        value = self.rows[hwnd]['class']
        out.value = value
        return len(value)
    def enumerate(self, callback, _):
        for hwnd in list(self.rows):
            if not callback(hwnd, 0):
                return False
        return True
    def close(self):
        return native.close_game_window(self.ident, expected_class='Skyrim Special Edition')
    def test_one_primary_post_excludes_hidden_owned_popup_and_foreign_windows(self):
        result = self.close()
        self.ui.PostMessageW.assert_called_once_with(100, 0x10, 0, 0)
        self.assertTrue(result['requested'])
        self.assertFalse(result['shutdownObserved'])
        self.assertEqual(result['selection']['candidateCount'], 1)
        self.assertEqual(len(result['windows']), 1)
        self.assertEqual(result['windows'][0]['class'], 'Skyrim Special Edition')
        self.assertEqual(len(result['selection']['observedOwnedWindows']), 3)
    def test_hidden_primary_wrong_class_or_owned_primary_is_not_guessed(self):
        for changes in ({'visible': False}, {'class': 'OtherGame'}, {'owner': 200}, {'style': 0x80}):
            with self.subTest(changes=changes):
                original = dict(self.rows[100]); self.rows[100].update(changes)
                result = self.close()
                self.assertEqual(result['reason'], 'primary-window-unavailable')
                self.assertFalse(result['requested'])
                self.rows[100] = original
        self.ui.PostMessageW.assert_not_called()
    def test_two_primary_matches_refuse_without_posting_to_either(self):
        self.rows[500] = dict(self.rows[100])
        result = self.close()
        self.assertEqual(result['reason'], 'primary-window-ambiguous')
        self.assertEqual(result['selection']['candidateCount'], 2)
        self.ui.PostMessageW.assert_not_called()
    def test_process_identity_loss_before_inventory_or_before_post_refuses(self):
        for side_effect in ([False], [True, False], [True, True, False]):
            with self.subTest(sequence=side_effect):
                self.alive.side_effect = side_effect
                result = self.close()
                self.assertFalse(result['requested'])
        self.ui.PostMessageW.assert_not_called()
    def test_window_pid_or_thread_change_during_final_recheck_refuses(self):
        for changes in ({'pid': 99}, {'thread': 999}, {'class': 'ChangedClass'}, {'visible': False}):
            with self.subTest(changes=changes):
                def enumerate_then_change(callback, param):
                    result = self.enumerate(callback, param)
                    self.rows[100].update(changes)
                    return result
                original = dict(self.rows[100])
                self.ui.EnumWindows.side_effect = enumerate_then_change
                self.assertFalse(self.close()['requested'])
                self.rows[100] = original
        self.ui.PostMessageW.assert_not_called()
    def test_empty_or_failed_enumeration_never_posts(self):
        self.ui.EnumWindows.return_value = False
        self.ui.EnumWindows.side_effect = None
        result = self.close()
        self.assertEqual(result['reason'], 'window-inventory-unavailable')
        self.ui.EnumWindows.return_value = True
        result = self.close()
        self.assertEqual(result['reason'], 'primary-window-unavailable')
        self.ui.PostMessageW.assert_not_called()
    def test_class_or_style_query_failure_refuses_without_broad_fallback(self):
        self.ui.GetClassNameW.side_effect = lambda *args: 0
        self.assertEqual(self.close()['reason'], 'window-inventory-unavailable')
        self.ui.GetClassNameW.side_effect = self.window_class
        def failed_style(hwnd, index):
            self.error = 5
            return 0
        self.ui.GetWindowLongPtrW.side_effect = failed_style
        self.assertEqual(self.close()['reason'], 'window-inventory-unavailable')
        self.ui.PostMessageW.assert_not_called()
    def test_post_failure_is_one_uncertain_request_not_another_window_attempt(self):
        def decline(*args):
            self.error = 5
            return False
        self.ui.PostMessageW.side_effect = decline
        result = self.close()
        self.ui.PostMessageW.assert_called_once_with(100, 0x10, 0, 0)
        self.assertTrue(result['requested'])
        self.assertFalse(result['windows'][0]['accepted'])
        self.assertEqual(result['windows'][0]['error'], 5)
    def test_class_must_be_explicit_nonempty_and_finite_length(self):
        for value in ('', None, 'x' * 129, 'bad\0class'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.close_game_window(self.ident, expected_class=value)
        self.ui.EnumWindows.assert_not_called()
        self.ui.PostMessageW.assert_not_called()


if __name__ == '__main__': unittest.main()
