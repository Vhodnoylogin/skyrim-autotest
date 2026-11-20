import ctypes
import os
import unittest

from skyrim_autotest import native


@unittest.skipUnless(os.name == 'nt', 'Windows QPC required')
class NativeClockTests(unittest.TestCase):
    def test_samples_share_integer_units_and_origin_with_win32_qpc(self):
        kernel = ctypes.windll.kernel32
        before, after, frequency = (ctypes.c_longlong() for _ in range(3))
        self.assertTrue(kernel.QueryPerformanceFrequency(ctypes.byref(frequency)))
        self.assertGreater(frequency.value, 0)
        self.assertTrue(kernel.QueryPerformanceCounter(ctypes.byref(before)))
        sampled = native.qpc_ticks()
        self.assertTrue(kernel.QueryPerformanceCounter(ctypes.byref(after)))
        self.assertEqual(native.qpc_frequency(), frequency.value)
        self.assertIs(type(sampled), int)
        self.assertLessEqual(before.value, sampled)
        self.assertLessEqual(sampled, after.value)
