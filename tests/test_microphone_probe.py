from array import array
import ctypes as C
import io
import contextlib
import unittest
from unittest.mock import patch

from skyrim_autotest import microphone_probe as mic


class MicrophoneProbeTests(unittest.TestCase):
    def test_silence_is_audio_data_not_human_speech(self):
        result = mic.levels(array('h', [0] * 16000).tobytes())
        self.assertEqual(result['seconds'], 1)
        self.assertEqual(result['peak'], 0)
        self.assertIsNone(result['rmsDbFS'])
        self.assertFalse(result['recognizedHumanSpeech'])

    def test_nonzero_levels_and_second_buckets_are_measured(self):
        pcm = array('h', [1000, -1000] * 16000).tobytes()
        result = mic.levels(pcm)
        self.assertEqual(result['rms'], 1000)
        self.assertEqual(result['peak'], 1000)
        self.assertEqual(len(result['perSecond']), 2)
        self.assertEqual(result['perSecond'][1]['second'], 1)
        self.assertFalse(result['recognizedHumanSpeech'])

    def test_partial_samples_and_unbounded_capture_rejected(self):
        with self.assertRaises(ValueError):
            mic.levels(b'x')
        for duration in (0, 31, float('nan'), float('inf')):
            with self.subTest(duration=duration), self.assertRaises(ValueError):
                mic.probe(0, duration)

    def test_device_absent_or_ambiguous_never_falls_back(self):
        for found in ([], [dict(name='Steam Streaming a'), dict(name='Steam Streaming b')]):
            with patch.object(mic, 'devices', return_value=found), patch.object(mic, 'probe') as probe:
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(mic.main(['--device', 'Steam Streaming']), 2)
                probe.assert_not_called()

    def test_resource_cleanup_after_input_failure(self):
        class Fake:
            def __init__(self):
                self.calls = []
            def waveInOpen(self, handle, *args):
                handle._obj.value = 1
                return 0
            def waveInPrepareHeader(self, *args):
                self.calls.append('prepare')
                return 0
            def waveInAddBuffer(self, *args):
                return 3
            def waveInStop(self, *args):
                self.calls.append('stop')
                return 0
            def waveInReset(self, *args):
                self.calls.append('reset')
                return 0
            def waveInUnprepareHeader(self, *args):
                self.calls.append('unprepare')
                return 0
            def waveInClose(self, *args):
                self.calls.append('close')
                return 0
        api = Fake()
        with patch.object(mic, 'api', return_value=api), self.assertRaises(OSError):
            mic.probe(0, 1)
        self.assertEqual(api.calls, ['prepare', 'stop', 'reset', 'unprepare', 'close'])


if __name__ == '__main__':
    unittest.main()
