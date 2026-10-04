"""Owned foreground activation observes Windows rather than assuming API success."""
import unittest
from unittest.mock import MagicMock, patch
from skyrim_autotest import native

class FocusTests(unittest.TestCase):
    def run_focus(self, focus_after=None, lose_after=None, exception_on_attached=False):
        clock = [0.]
        ident = {'pid':42,'birth':123,'path':'owned.exe'}
        ui = MagicMock()
        kernel = MagicMock()
        kernel.GetCurrentThreadId.return_value = 10
        def owner(hwnd, out):
            out._obj.value = 42 if hwnd == 100 else 99
            return 20 if hwnd == 100 else 900
        ui.GetWindowThreadProcessId.side_effect = owner
        ui.IsWindowVisible.return_value = True
        ui.GetForegroundWindow.side_effect = lambda: 100 if focus_after is not None and clock[0] >= focus_after else 200
        ui.SetForegroundWindow.return_value = True
        ui.AttachThreadInput.return_value = True
        ui.EnumWindows.side_effect = lambda callback, _: callback(100,0)
        if exception_on_attached:
            original_set = ui.SetForegroundWindow
            def activate(hwnd):
                if ui.AttachThreadInput.call_count and ui.AttachThreadInput.call_args.args[-1] is True:
                    raise RuntimeError('Owned activation failure')
                return True
            original_set.side_effect = activate
        with patch.object(native,'U',ui),patch.object(native,'K',kernel),patch.object(native,'alive',side_effect=lambda _: lose_after is None or clock[0] < lose_after),patch.object(native.time,'monotonic',side_effect=lambda:clock[0]),patch.object(native.time,'sleep',side_effect=lambda seconds:clock.__setitem__(0,clock[0]+seconds)):
            if exception_on_attached:
                with self.assertRaisesRegex(RuntimeError,'activation failure'):
                    native.focus_owned(ident,timeout=1)
                result=None
            else:
                result=native.focus_owned(ident,timeout=1)
        return result, ui, clock[0]
    def test_asynchronous_focus_settles_before_deadline(self):
        result,ui,elapsed=self.run_focus(focus_after=.2)
        self.assertTrue(result['focused'])
        self.assertGreaterEqual(elapsed,.2)
        self.assertEqual(ui.AttachThreadInput.call_count,0)
        ui.ShowWindowAsync.assert_called_with(100,9)
    def test_positive_api_response_cannot_mask_denied_foreground(self):
        result,ui,elapsed=self.run_focus()
        self.assertTrue(result['requested'])
        self.assertFalse(result['focused'])
        self.assertLessEqual(elapsed,1.000001)
        self.assertEqual([c.args for c in ui.AttachThreadInput.call_args_list],[(10,20,True),(10,20,False)])
        # Never joined the unrelated foreground window's thread900.
        self.assertTrue(all(c.args[1] == 20 for c in ui.AttachThreadInput.call_args_list))
    def test_identity_loss_stops_without_touching_reused_window(self):
        result,ui,elapsed=self.run_focus(lose_after=.2)
        self.assertFalse(result['focused'])
        self.assertEqual(result['reason'],'owned-window-identity-changed')
        self.assertEqual(ui.AttachThreadInput.call_count,0)
        self.assertLessEqual(elapsed,.2)
    def test_owned_thread_is_detached_even_if_activation_raises(self):
        result,ui,elapsed=self.run_focus(exception_on_attached=True)
        self.assertEqual([c.args for c in ui.AttachThreadInput.call_args_list],[(10,20,True),(10,20,False)])

if __name__=='__main__':
    unittest.main()
