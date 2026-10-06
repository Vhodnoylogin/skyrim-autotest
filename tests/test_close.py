"""Graceful close delivery observes owned identity and never implies exit."""
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


if __name__ == '__main__': unittest.main()
