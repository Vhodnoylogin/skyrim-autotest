from array import array
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import wave

from skyrim_autotest.voice_audio import Utterances, BLOCK_SAMPLES, RATE, wav_blocks
from skyrim_autotest import voice_audio
from skyrim_autotest.voice_listener import Session, main


def pcm(value=0):
    return array('h', [value] * BLOCK_SAMPLES).tobytes()


class VoiceAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.events = []
        self.collector = Utterances(self.root / 'audio', self.events.append, pause=.9)

    def test_long_phrase_is_one_complete_audio_without_overlap_text_cut(self):
        sequence = [pcm(), pcm()] + [pcm(1000 + i) for i in range(75)] + [pcm()] * 5
        for block in sequence:
            self.collector.feed(block)
        self.assertEqual([r['event'] for r in self.events], ['speech.started', 'audio.final'])
        final = self.events[-1]
        self.assertTrue(final['audioComplete'])
        self.assertEqual(final['startSample'], 0)
        self.assertEqual(final['endSample'], 82 * BLOCK_SAMPLES)
        self.assertFalse(final['executable'])
        with wave.open(final['wav']) as wav:
            self.assertEqual(wav.readframes(wav.getnframes()), b''.join(sequence))

    def test_short_pause_does_not_split_slow_command(self):
        for block in [pcm(500)] * 3 + [pcm()] * 3 + [pcm(500)] * 2 + [pcm()] * 5:
            self.collector.feed(block)
        self.assertEqual(len(self.events), 2)

    def test_default_pause_retains_slow_wake_and_following_instruction(self):
        collector = Utterances(self.root / 'slow', self.events.append)
        for block in [pcm(500)] * 2 + [pcm()] * 6 + [pcm(500)] * 2 + [pcm()] * 8:
            collector.feed(block)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(self.events[-1]['endSample'], 18 * BLOCK_SAMPLES)

    def test_distinct_repeated_words_keep_distinct_utterance_ids(self):
        for _ in range(2):
            for block in [pcm(500)] * 2 + [pcm()] * 5:
                self.collector.feed(block)
        finals = [r for r in self.events if r['event'] == 'audio.final']
        self.assertEqual(len(finals), 2)
        self.assertNotEqual(finals[0]['utteranceId'], finals[1]['utteranceId'])

    def test_interrupt_and_limit_never_finalize_executable_audio(self):
        self.collector.feed(pcm(500))
        self.collector.finish()
        self.assertFalse(self.events[-1]['audioComplete'])
        collector = Utterances(self.root / 'limit', self.events.append, maximum=5)
        with self.assertRaises(OverflowError):
            for _ in range(25):
                collector.feed(pcm(500))
        self.assertEqual(self.events[-1]['endpointReason'], 'utterance_limit')
        self.assertFalse(self.events[-1]['audioComplete'])

    def test_invalid_audio_and_endpoint_settings_rejected(self):
        with self.assertRaises(ValueError):
            self.collector.feed(b'x')
        for options in ({'pause': 0}, {'threshold': float('nan')}, {'maximum': 1}):
            with self.assertRaises(ValueError):
                Utterances(self.root, self.events.append, **options)

    def test_asr_runs_whole_wav_retains_segments_and_real_repetition(self):
        def fake_run(command, **kwargs):
            source = Path(command[command.index('-f') + 1])
            with wave.open(str(source)) as wav:
                self.assertGreater(wav.getnframes(), 8 * RATE)
            output = command[command.index('-of') + 1] + '.json'
            Path(output).write_text(json.dumps({'transcription': [
                {'text': 'Полигон, положи предмет.', 'offsets': {'from': 0, 'to': 7000}},
                {'text': 'Положи предмет.', 'offsets': {'from': 7000, 'to': 10000}}]}), encoding='utf-8')
            return subprocess.CompletedProcess(command, 0)
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=fake_run):
            session = Session(self.root / 'session', {'cli': 'external-cli', 'model': 'external-model'})
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            for block in [pcm(500)] * 50 + [pcm()] * 5:
                collector.feed(block)
            session.close()
        row = json.loads(session.heard.read_text(encoding='utf-8'))
        self.assertEqual(row['text'], 'Полигон, положи предмет. Положи предмет.')
        self.assertEqual(len(row['segments']), 2)
        self.assertTrue(row['final'])
        self.assertTrue(row['audioComplete'])
        self.assertGreaterEqual(row['asrEndedAt'], row['asrStartedAt'])
        self.assertEqual(row['revision'], 2)

    def test_capture_spools_while_asr_busy_then_completes_in_order(self):
        entered, release = threading.Event(), threading.Event()
        def slow_run(command, **kwargs):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('test barrier')
            Path(command[command.index('-of') + 1] + '.json').write_text(
                json.dumps({'transcription': [{'text': 'Полигон, проверка'}]}), encoding='utf-8')
            return subprocess.CompletedProcess(command, 0)
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=slow_run):
            session = Session(self.root / 'async', {'cli': 'external-cli', 'model': 'external-model'})
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            for block in [pcm(500)] * 2 + [pcm()] * 5:
                collector.feed(block)
            self.assertTrue(entered.wait(1))
            for block in [pcm(500)] * 2 + [pcm()] * 5:
                collector.feed(block)
            self.assertEqual(len(list(session.folder.glob('*.audio.json'))), 2)
            self.assertGreaterEqual(session.pending.qsize(), 1)
            release.set()
            session.close()
        rows = [json.loads(r) for r in session.heard.read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['seq'] for r in rows], [1, 2])
        self.assertNotEqual(rows[0]['utteranceId'], rows[1]['utteranceId'])

    def test_failed_asr_retains_audio_without_command(self):
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=subprocess.TimeoutExpired('cli', 1)):
            session = Session(self.root / 'failed', {'cli': 'external-cli', 'model': 'external-model'})
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            for block in [pcm(500)] * 2 + [pcm()] * 5:
                collector.feed(block)
            session.close()
        self.assertEqual(session.heard.read_text(), '')
        self.assertEqual(len(list((session.folder / 'audio').glob('*.wav'))), 1)
        self.assertFalse(json.loads((session.folder / 'health.json').read_text())['ok'])

    def test_backlog_limit_preserves_unqueued_audio_and_reports_failure(self):
        entered, release = threading.Event(), threading.Event()
        def slow_run(command, **kwargs):
            entered.set()
            release.wait(3)
            Path(command[command.index('-of') + 1] + '.json').write_text(
                json.dumps({'transcription': [{'text': 'Полигон, проверка'}]}), encoding='utf-8')
            return subprocess.CompletedProcess(command, 0)
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=slow_run):
            session = Session(self.root / 'full', {'cli': 'cli', 'model': 'model'}, maximum_pending=1)
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            try:
                for block in [pcm(500)] * 2 + [pcm()] * 5:
                    collector.feed(block)
                self.assertTrue(entered.wait(1))
                with self.assertRaises(OverflowError):
                    for block in ([pcm(500)] * 2 + [pcm()] * 5) * 2:
                        collector.feed(block)
                self.assertEqual(len(list(session.folder.glob('*.audio.json'))), 3)
                self.assertIn('backlog full', session.error)
            finally:
                release.set()
                session.close()

    def test_worker_diagnostic_write_failure_does_not_hang_shutdown(self):
        session = Session(self.root / 'diskfail', {'cli': 'cli', 'model': 'model'})
        with patch.object(session, 'transcribe', side_effect=OSError('disk full')):
            with patch.object(session, 'event', side_effect=OSError('diagnostic disk full')):
                session.pending.put({'utteranceId': 'test'})
                session.close()
        self.assertIn('failed to retain diagnostic', session.error)
        self.assertFalse(session.worker.is_alive())

    def test_continuous_capture_requeues_before_yield_and_cleans_all_headers(self):
        class Fake:
            def __init__(self):
                self.headers, self.calls = [], []
            def waveInOpen(self, handle, *args):
                handle._obj.value = 1
                return 0
            def waveInPrepareHeader(self, handle, header, *args):
                self.headers.append(header._obj)
                return 0
            def waveInAddBuffer(self, handle, header, *args):
                header._obj.flags = 0
                self.calls.append('queue')
                return 0
            def waveInStart(self, *args):
                self.headers[0].flags = 1
                self.headers[0].recorded = BLOCK_SAMPLES * 2
                return 0
            def waveInStop(self, *args):
                return 0
            def waveInReset(self, *args):
                return 0
            def waveInUnprepareHeader(self, *args):
                self.calls.append('unprepare')
                return 0
            def waveInClose(self, *args):
                self.calls.append('close')
                return 0
        fake = Fake()
        with patch.object(voice_audio, 'api', return_value=fake):
            stream = voice_audio.capture(0)
            self.assertEqual(len(next(stream)), BLOCK_SAMPLES * 2)
            self.assertEqual(fake.calls.count('queue'), 17)
            stream.close()
        self.assertEqual(fake.calls.count('unprepare'), 16)
        self.assertEqual(fake.calls[-1], 'close')

    def test_exhausted_capture_ring_never_claims_complete_audio(self):
        class Fake:
            def __init__(self):
                self.headers = []
                self.closed = False
            def waveInOpen(self, handle, *args):
                handle._obj.value = 1
                return 0
            def waveInPrepareHeader(self, handle, header, *args):
                self.headers.append(header._obj)
                return 0
            def waveInAddBuffer(self, *args):
                return 0
            def waveInStart(self, *args):
                for header in self.headers:
                    header.flags = 1
                    header.recorded = BLOCK_SAMPLES * 2
                return 0
            def waveInStop(self, *args):
                return 0
            def waveInReset(self, *args):
                return 0
            def waveInUnprepareHeader(self, *args):
                return 0
            def waveInClose(self, *args):
                self.closed = True
                return 0
        fake = Fake()
        with patch.object(voice_audio, 'api', return_value=fake):
            with self.assertRaisesRegex(OSError, 'possible audio gap'):
                next(voice_audio.capture(0))
        self.assertTrue(fake.closed)

    def test_existing_listener_lock_blocks_before_microphone(self):
        config = self.root / 'asr.json'
        model, cli = self.root / 'model', self.root / 'cli'
        model.touch()
        cli.touch()
        config.write_text(json.dumps({'cli': str(cli), 'model': str(model)}))
        lock = self.root / 'listen.lock'
        lock.write_text('{"pid":1234}')
        with patch('skyrim_autotest.voice_listener.capture') as capture_mock:
            result = main(['--asr-config', str(config), '--session', str(self.root / 'unused'),
                           '--device', 'headset', '--listen-lock', str(lock)])
        self.assertEqual(result, 2)
        capture_mock.assert_not_called()
        self.assertEqual(lock.read_text(), '{"pid":1234}')
        self.assertFalse((self.root / 'unused').exists())

    def test_no_resample_in_replay(self):
        file = self.root / 'wrong.wav'
        with wave.open(str(file), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm())
        with self.assertRaises(ValueError):
            list(wav_blocks(file))
