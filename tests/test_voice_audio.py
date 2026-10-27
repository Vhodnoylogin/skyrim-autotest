from array import array
import json
import ctypes
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import wave

from skyrim_autotest.voice_audio import CapturedPCM, CaptureGap, Utterances, BLOCK_SAMPLES, RATE, wav_blocks
from skyrim_autotest import voice_audio
from skyrim_autotest.voice_listener import Session, main


def pcm(value=0):
    return array('h', [value] * BLOCK_SAMPLES).tobytes()


class NativeRing:
    def __init__(self, complete=1, partial=False):
        self.headers, self.queues, self.unprepared = [], 0, 0
        self.initial_complete, self.partial, self.closed = complete, partial, False

    def waveInOpen(self, handle, *args):
        handle._obj.value = 1
        return 0

    def waveInPrepareHeader(self, handle, header, *args):
        self.headers.append(header._obj)
        return 0

    def waveInAddBuffer(self, handle, header, *args):
        header._obj.flags = 2 | 16
        header._obj.recorded = 0
        self.queues += 1
        return 0

    def complete(self, count):
        for index, header in enumerate(self.headers[:count]):
            ctypes.memmove(header.data, pcm(index + 1), BLOCK_SAMPLES * 2)
            header.recorded = BLOCK_SAMPLES * 2 - (2 if self.partial else 0)
            header.flags = 2 | voice_audio.WHDR_DONE

    def waveInStart(self, *args):
        self.complete(self.initial_complete)
        return 0

    def waveInStop(self, *args): return 0
    def waveInReset(self, *args): return 0
    def waveInUnprepareHeader(self, *args):
        self.unprepared += 1
        return 0
    def waveInClose(self, *args):
        self.closed = True
        return 0


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
            self.assertEqual(fake.calls.count('queue'), voice_audio.NATIVE_BUFFER_COUNT + 1)
            stream.close()
        self.assertEqual(fake.calls.count('unprepare'), voice_audio.NATIVE_BUFFER_COUNT)
        self.assertEqual(fake.calls[-1], 'close')

    def test_native_ring_returns_entire_ready_burst_before_yielding_to_consumer(self):
        fake = NativeRing(complete=16)
        with patch.object(voice_audio, 'api', return_value=fake), \
             patch.object(voice_audio.time, 'time', return_value=1000.):
            stream = voice_audio._capture_blocks(0, threading.Event())
            try:
                first = next(stream)
                self.assertEqual(first, pcm(1))
                self.assertEqual(fake.queues, voice_audio.NATIVE_BUFFER_COUNT + 16)
                self.assertFalse(any(header.flags & voice_audio.WHDR_DONE for header in fake.headers))
                blocks = [first] + [next(stream) for _ in range(15)]
                self.assertEqual(blocks, [pcm(index + 1) for index in range(16)])
                self.assertAlmostEqual(blocks[-1].captured_at - blocks[0].captured_at, 3.)
            finally:
                stream.close()
        self.assertTrue(fake.closed)
        self.assertEqual(fake.unprepared, voice_audio.NATIVE_BUFFER_COUNT)

    def test_native_reserve_exhaustion_retains_header_and_drain_timing_without_replay(self):
        fake = NativeRing()
        now = [100.]
        with patch.object(voice_audio, 'api', return_value=fake), \
             patch.object(voice_audio.time, 'monotonic', side_effect=lambda: now[0]):
            stream = voice_audio._capture_blocks(0, threading.Event())
            self.assertEqual(next(stream), pcm(1))
            fake.complete(voice_audio.NATIVE_BUFFER_COUNT)
            now[0] += 26.
            with self.assertRaisesRegex(CaptureGap, 'possible audio gap') as caught:
                next(stream)
        diagnostic = caught.exception.diagnostics
        self.assertEqual(diagnostic['reason'], 'native-reserve-exhausted')
        self.assertEqual(diagnostic['nativeBufferCount'], 128)
        self.assertEqual(diagnostic['nativeReserveSeconds'], 25.6)
        self.assertEqual(diagnostic['completedHeaders'], 128)
        self.assertEqual(diagnostic['drainedBlocks'], 1)
        self.assertEqual(diagnostic['sinceLastDrainSeconds'], 26)
        self.assertEqual(len(diagnostic['headerFlags']), 128)
        self.assertEqual(diagnostic['recordedBytes'], [BLOCK_SAMPLES * 2] * 128)
        self.assertFalse(diagnostic['coverageEstablished'])
        self.assertIsNone(diagnostic['missingSamples'])
        self.assertIn('"reason": "native-reserve-exhausted"', str(caught.exception))
        self.assertTrue(fake.closed)

    def test_partial_native_block_records_actual_bytes_and_never_yields_audio(self):
        fake = NativeRing(partial=True)
        with patch.object(voice_audio, 'api', return_value=fake):
            with self.assertRaises(CaptureGap) as caught:
                next(voice_audio._capture_blocks(0, threading.Event()))
        self.assertEqual(caught.exception.diagnostics['reason'], 'partial-input-block')
        self.assertEqual(caught.exception.diagnostics['recordedBytes'][0], BLOCK_SAMPLES * 2 - 2)
        self.assertEqual(caught.exception.diagnostics['drainedBlocks'], 0)
        self.assertTrue(fake.closed)

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

    def test_winmm_drainer_continues_while_disk_consumer_is_paused(self):
        release, drained, closed = threading.Event(), threading.Event(), threading.Event()
        def source(device, stop):
            try:
                yield CapturedPCM(pcm(1), 100.)
                if not release.wait(1): raise TimeoutError('test producer barrier')
                for index in range(24):
                    yield CapturedPCM(pcm(index + 2), 100.2 + index * .2)
                drained.set()
                stop.wait(1)
            finally:
                closed.set()
        with patch.object(voice_audio, '_capture_blocks', side_effect=source):
            stream = voice_audio.capture(0, maximum_pending=32)
            try:
                self.assertEqual(next(stream), pcm(1))
                release.set()
                self.assertTrue(drained.wait(1))  #4.8seconds of PCM drained without another consumer call.
                block = next(stream)
                self.assertEqual(block, pcm(2))
                self.assertEqual(block.captured_at, 100.2)
            finally:
                stream.close()
        self.assertTrue(closed.is_set())

    def test_bounded_capture_overflow_discards_buffered_fragments_instead_of_replaying_them(self):
        release, closed = threading.Event(), threading.Event()
        def source(device, stop):
            try:
                yield CapturedPCM(pcm(1), 100.)
                if not release.wait(1): raise TimeoutError('test producer barrier')
                for index in range(4): yield CapturedPCM(pcm(index + 2), 100.2 + index * .2)
            finally:
                closed.set()
        with patch.object(voice_audio, '_capture_blocks', side_effect=source):
            stream = voice_audio.capture(0, maximum_pending=2)
            self.assertEqual(next(stream), pcm(1))
            release.set()
            self.assertTrue(closed.wait(1))
            with self.assertRaisesRegex(CaptureGap, 'consumer backlog exhausted'):
                next(stream)
        for bound in (0, 151, True):
            with self.subTest(bound=bound), self.assertRaises(ValueError): next(voice_audio.capture(0, bound))

    def test_buffered_old_audio_keeps_capture_time_and_cannot_enter_new_owner_dialog(self):
        session = Session(self.root / 'old-buffer', {'cli': 'cli', 'model': 'model'}, operator_thread=str(uuid.uuid4()))
        from skyrim_autotest.voice_inbox import atomic
        atomic(session.folder / 'conversation-request.json', {'id': uuid.uuid4().hex, 'threadId': session.operator_thread,
            'ownerRef': 'owner-start', 'at': time.time(), 'seconds': 1800})
        session.apply_control()
        def asr(command, **kwargs):
            Path(command[command.index('-of') + 1] + '.json').write_text(
                json.dumps({'transcription': [{'text': 'обычная новая команда'}]}))
            return subprocess.CompletedProcess(command, 0)
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=asr):
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            for index, block in enumerate([pcm(500)] * 2 + [pcm()] * 5):
                collector.feed(CapturedPCM(block, session.control_started_at - 5 + index * .2))
            session.close()
        self.assertEqual(session.heard.read_text(), '')
        final = json.loads(next(session.folder.glob('*.final.json')).read_text(encoding='utf-8'))
        self.assertLess(final['captureStartedAt'], session.control_started_at)
        self.assertLess(final['captureEndedAt'], session.control_started_at)
        self.assertFalse(final['accepted'])

    def test_capture_gap_keeps_incomplete_audio_and_suppresses_pending_asr_commands(self):
        entered, release = threading.Event(), threading.Event()
        def asr(command, **kwargs):
            entered.set()
            if not release.wait(2): raise TimeoutError('test ASR barrier')
            Path(command[command.index('-of') + 1] + '.json').write_text(
                json.dumps({'transcription': [{'text': 'Полигон, команда'}]}))
            return subprocess.CompletedProcess(command, 0)
        with patch('skyrim_autotest.voice_listener.subprocess.run', side_effect=asr) as backend:
            session = Session(self.root / 'gap', {'cli': 'cli', 'model': 'model'})
            collector = Utterances(session.folder / 'audio', session.event, pause=.9)
            try:
                for block in [pcm(500)] * 2 + [pcm()] * 5: collector.feed(block)
                self.assertTrue(entered.wait(1))
                collector.feed(pcm(500))
                session.fail_capture(CaptureGap('explicit capture gap'))
                collector.finish('capture_gap', False)
            finally:
                release.set()
                session.close()
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(session.heard.read_text(), '')
        finals = [json.loads(path.read_text(encoding='utf-8')) for path in session.folder.glob('*.audio.json')]
        self.assertEqual(sum(row['audioComplete'] is False and row['endpointReason'] == 'capture_gap' for row in finals), 1)
        final = json.loads(next(session.folder.glob('*.final.json')).read_text(encoding='utf-8'))
        self.assertFalse(final['accepted'])
        self.assertIn('capture gap', final['admissionError'])
        health = json.loads((session.folder / 'health.json').read_text(encoding='utf-8'))
        self.assertFalse(health['ok'])
        self.assertFalse(health['audioCoverageComplete'])
        self.assertIn('"event": "capture.gap"', session.events.read_text(encoding='utf-8'))

    def test_listener_gap_exit_records_fault_before_finishing_partial_utterance(self):
        config = self.root / 'asr.json'
        model, cli = self.root / 'model', self.root / 'cli'
        model.touch(); cli.touch()
        config.write_text(json.dumps({'cli': str(cli), 'model': str(model)}))
        def broken_capture(path):
            yield CapturedPCM(pcm(500), time.time() - .2)
            raise CaptureGap('simulated ring gap')
        with patch('skyrim_autotest.voice_listener.wav_blocks', side_effect=broken_capture), \
             patch('skyrim_autotest.voice_listener.subprocess.run') as asr:
            result = main(['--asr-config', str(config), '--session', str(self.root / 'gap-main'),
                           '--replay-wav', str(self.root / 'unused.wav')])
        self.assertEqual(result, 2)
        asr.assert_not_called()
        session = self.root / 'gap-main'
        final = json.loads(next(session.glob('*.audio.json')).read_text(encoding='utf-8'))
        self.assertFalse(final['audioComplete'])
        self.assertEqual(final['endpointReason'], 'capture_gap')
        health = json.loads((session / 'health.json').read_text(encoding='utf-8'))
        self.assertFalse(health['ok'])
        self.assertFalse(health['captureActive'])
        self.assertEqual((session / 'heard.jsonl').read_text(), '')

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
