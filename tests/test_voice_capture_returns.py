"""Synthetic WinMM returned-buffer shapes; no microphone/device access."""
import threading
import unittest
from unittest.mock import patch

from skyrim_autotest import voice_audio as audio
from tests import test_voice_audio as fixtures


class ReturnedBuffersTests(unittest.TestCase):
    def capture_fault(self, fake):
        with patch.object(audio, 'api', return_value=fake):
            source = audio._capture_blocks(0, threading.Event())
            with self.assertRaises(audio.CaptureGap) as caught:
                next(source)
        self.assertTrue(fake.closed)
        self.assertEqual(fake.unprepared, audio.NATIVE_BUFFER_COUNT)
        self.assertEqual(fake.queues, audio.NATIVE_BUFFER_COUNT)
        self.assertFalse(caught.exception.diagnostics['coverageEstablished'])
        self.assertIsNone(caught.exception.diagnostics['missingSamples'])
        return caught.exception.diagnostics

    def test_actual_empty_and_partial_return_is_interruption_not_full_reserve(self):
        class Returned(fixtures.NativeRing):
            def waveInStart(self, *args):
                for header in self.headers:
                    header.flags = 2 | audio.WHDR_DONE
                    header.recorded = 0
                self.headers[72].recorded = 2178
                return 0
        result = self.capture_fault(Returned())
        self.assertEqual(result['reason'], 'interrupted-buffer-return')
        self.assertEqual(result['completedFullHeaders'], 0)
        self.assertEqual(result['completedEmptyHeaders'], 127)
        self.assertEqual(result['completedPartialHeaders'], 1)
        self.assertEqual(result['completedInvalidHeaders'], 0)

    def test_all_full_return_keeps_reserve_exhaustion_and_never_yields_fragments(self):
        result = self.capture_fault(fixtures.NativeRing(complete=audio.NATIVE_BUFFER_COUNT))
        self.assertEqual(result['reason'], 'native-reserve-exhausted')
        self.assertEqual(result['completedFullHeaders'], audio.NATIVE_BUFFER_COUNT)
        self.assertEqual(result['completedEmptyHeaders'], 0)
        self.assertEqual(result['completedPartialHeaders'], 0)

    def test_all_empty_return_does_not_invent_missing_sample_count(self):
        class Empty(fixtures.NativeRing):
            def waveInStart(self, *args):
                for header in self.headers:
                    header.flags = 2 | audio.WHDR_DONE
                return 0
        result = self.capture_fault(Empty())
        self.assertEqual(result['reason'], 'interrupted-buffer-return')
        self.assertEqual(result['completedEmptyHeaders'], audio.NATIVE_BUFFER_COUNT)
        self.assertEqual(result['drainedSamples'], 0)


if __name__ == '__main__': unittest.main()
