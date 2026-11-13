"""Continuous shared input and pause-delimited audio, independent of inference."""
from array import array
from collections import deque
import ctypes as C
import json
import math
from pathlib import Path
import queue
import threading
import time
import uuid
import wave

from .microphone_probe import api, check, Format, Header

RATE = 16000
BLOCK_SAMPLES = 3200  # 200ms; contiguous PCM16 mono
CAPTURE_PENDING_BLOCKS = 150  # At most30seconds /960000bytes outside WinMM.
NATIVE_BUFFER_COUNT = 128  #25.6seconds /819200bytes; capacity, not batching latency.
WHDR_DONE = 1


class CaptureGap(OSError):
    """Capture coverage was lost; buffered fragments must not become commands."""

    def __init__(self, message, diagnostics=None):
        self.diagnostics = diagnostics or {}
        detail = '; capture=' + json.dumps(self.diagnostics, sort_keys=True, allow_nan=False) if self.diagnostics else ''
        super().__init__(message + detail)


class CapturedPCM(bytes):
    def __new__(cls, pcm, captured_at):
        value = super().__new__(cls, pcm)
        value.captured_at = captured_at
        return value


def _capture_blocks(device, stop):
    """Keep a bounded native reserve; requeue every ready header before yielding."""
    mm = api()
    handle = C.c_void_p()
    fmt = Format(1, 1, RATE, RATE * 2, 2, 16, 0)
    check(mm.waveInOpen(C.byref(handle), device, C.byref(fmt), 0, 0, 0), 'shared input open')
    buffers = [C.create_string_buffer(BLOCK_SAMPLES * 2) for _ in range(NATIVE_BUFFER_COUNT)]
    headers = [Header(C.addressof(b), len(b), 0, 0, 0, 0, None, 0) for b in buffers]
    prepared = []
    try:
        for header in headers:
            check(mm.waveInPrepareHeader(handle, C.byref(header), C.sizeof(header)), 'prepare')
            prepared.append(header)
            check(mm.waveInAddBuffer(handle, C.byref(header), C.sizeof(header)), 'queue')
        check(mm.waveInStart(handle), 'capture start')
        index = 0
        started = last_drained = time.monotonic()
        drained = 0
        deadline = started + 5

        def fault(reason, message, flags=None):
            now = time.monotonic()
            flags = [int(h.flags) for h in headers] if flags is None else flags
            recorded = [int(h.recorded) for h in headers]
            completed_sizes = [size for flag, size in zip(flags, recorded) if flag & WHDR_DONE]
            return CaptureGap(message, {'reason': reason, 'nativeBufferCount': len(headers),
                'blockSamples': BLOCK_SAMPLES, 'nativeReserveSeconds': len(headers) * BLOCK_SAMPLES / RATE,
                'nextHeader': index, 'completedHeaders': sum(bool(value & WHDR_DONE) for value in flags),
                'drainedBlocks': drained, 'drainedSamples': drained * BLOCK_SAMPLES,
                'captureElapsedSeconds': now - started, 'sinceLastDrainSeconds': now - last_drained,
                'headerFlags': flags, 'recordedBytes': recorded,
                'completedFullHeaders': sum(size == BLOCK_SAMPLES * 2 for size in completed_sizes),
                'completedEmptyHeaders': completed_sizes.count(0),
                'completedPartialHeaders': sum(0 < size < BLOCK_SAMPLES * 2 for size in completed_sizes),
                'completedInvalidHeaders': sum(size > BLOCK_SAMPLES * 2 or size % 2 for size in completed_sizes),
                'missingSamples': None, 'coverageEstablished': False})

        while not stop.is_set():
            header = headers[index]
            if not header.flags & WHDR_DONE:
                if time.monotonic() > deadline:
                    raise fault('input-timeout', 'Input stopped; audio coverage unavailable')
                time.sleep(.005)
                continue
            batch = []
            while headers[index].flags & WHDR_DONE and len(batch) < len(headers) and not stop.is_set():
                flags = [int(h.flags) for h in headers]
                completed = sum(bool(value & WHDR_DONE) for value in flags)
                if completed == len(headers):
                    if any(h.recorded != BLOCK_SAMPLES * 2 for h in headers):
                        # An input reset/interruption may return every queued
                        # header empty except the partially recorded current one.
                        # That shape is not a reserve filled with captured PCM.
                        # Neither the initiating cause nor lost duration is known.
                        raise fault('interrupted-buffer-return',
                            'Input buffers returned empty or incomplete; audio continuity unavailable', flags)
                    # DONE proves return of a buffer, not a measured loss count.
                    # With no native reserve left, continuity is unproven; fail
                    # closed and retain timing/flags instead of guessing a cause.
                    raise fault('native-reserve-exhausted', 'Capture ring exhausted: possible audio gap, no complete command', flags)
                header = headers[index]
                if header.recorded != BLOCK_SAMPLES * 2:
                    raise fault('partial-input-block', 'Partial input block: audio coverage unavailable', flags)
                # Host estimate only: WinMM supplies no hardware timestamp here.
                captured_at = time.time() - completed * BLOCK_SAMPLES / RATE
                pcm = buffers[index].raw[:header.recorded]
                check(mm.waveInAddBuffer(handle, C.byref(header), C.sizeof(header)), 'requeue')
                last_drained = time.monotonic()
                drained += 1
                index = (index + 1) % len(headers)
                deadline = last_drained + 5
                batch.append(CapturedPCM(pcm, captured_at))
            for pcm in batch:
                if stop.is_set(): break
                yield pcm
    finally:
        mm.waveInStop(handle)
        mm.waveInReset(handle)
        for header in prepared:
            mm.waveInUnprepareHeader(handle, C.byref(header), C.sizeof(header))
        mm.waveInClose(handle)


def capture(device, maximum_pending=CAPTURE_PENDING_BLOCKS):
    """Drain WinMM independently of WAV/event/control/health disk operations.

    The bounded queue absorbs short consumer stalls. Either exhausted buffer
    stops this capture explicitly; queued audio is never drained after a gap.
    """
    if type(maximum_pending) is not int or not 1 <= maximum_pending <= CAPTURE_PENDING_BLOCKS:
        raise ValueError('Capture queue requires1..150blocks')
    pending = queue.Queue(maximum_pending)
    stop, done = threading.Event(), threading.Event()
    failures = []

    def drain():
        source = None
        try:
            source = _capture_blocks(device, stop)
            for pcm in source:
                if stop.is_set(): break
                try:
                    pending.put_nowait(pcm)
                except queue.Full as error:
                    raise CaptureGap('Capture consumer backlog exhausted; audio gap, no complete command') from error
        except BaseException as error:
            failures.append(error)
        finally:
            try:
                if source is not None: source.close()
            except BaseException as error:
                failures.append(error)
            done.set()

    worker = threading.Thread(target=drain, name='voice-winmm-capture', daemon=True)
    worker.start()
    try:
        while True:
            if failures: raise failures[0]
            try:
                pcm = pending.get(timeout=.1)
            except queue.Empty:
                if done.is_set():
                    if failures: raise failures[0]
                    return
                continue
            if failures: raise failures[0]
            yield pcm
    finally:
        stop.set()
        worker.join(2)
        if worker.is_alive():
            raise CaptureGap('Capture worker did not stop; microphone cleanup unconfirmed')


class Utterances:
    """Preserve whole audio intervals; never deduplicate by recognized text.

    The energy gate is an endpoint heuristic, not proof of human speech. Noise
    and quiet speech need explicit qualification. Limits fail visibly, not split
    a long unfinished instruction into executable fragments.
    """
    def __init__(self, folder, emit, threshold=100, pause=1.6, maximum=120):
        self.validate(threshold, pause, maximum)
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.emit = emit
        self.threshold, self.pause, self.maximum = threshold, pause, maximum
        self.sample = 0
        self.pre = deque(maxlen=2)
        self.active = None
        self.stream = None
        self.wav = None
        self.last_voice = 0
        self.capture_ended_at = None

    @staticmethod
    def validate(threshold, pause, maximum):
        if (not all(math.isfinite(v) for v in (threshold, pause, maximum))
                or not 1 <= threshold <= 32768 or not .4 <= pause <= 5
                or not 5 <= maximum <= 300):
            raise ValueError('Invalid energy gate, pause or utterance maximum')

    def feed(self, pcm):
        if not pcm or len(pcm) % 2:
            raise ValueError('Invalid PCM block')
        values = array('h', pcm)
        captured_at = getattr(pcm, 'captured_at', None)
        if captured_at is not None and (type(captured_at) not in (int, float) or not math.isfinite(captured_at)):
            raise ValueError('Invalid captured audio timestamp')
        self.capture_ended_at = time.time() if captured_at is None else captured_at + len(values) / RATE
        rms = math.sqrt(sum(v * v for v in values) / len(values))
        begin = self.sample
        self.sample += len(values)
        voiced = rms >= self.threshold
        if self.active is None:
            if not voiced:
                self.pre.append((begin, pcm))
                return
            identity = uuid.uuid4().hex
            start = self.pre[0][0] if self.pre else begin
            self.active = {'utteranceId': identity, 'startSample': start,
                           'speechStartSample': begin, 'sampleRate': RATE,
                           'wav': str((self.folder / (identity + '.wav')).resolve()),
                           'captureStartedAt': time.time() if captured_at is None else captured_at, 'revision': 0}
            self.stream = Path(self.active['wav']).open('xb')
            self.wav = wave.open(self.stream, 'wb')
            self.wav.setparams((1, 2, RATE, 0, 'NONE', 'not compressed'))
            for _, raw in self.pre:
                self.wav.writeframesraw(raw)
            self.pre.clear()
            self.emit({**self.active, 'event': 'speech.started', 'final': False,
                       'executable': False})
        self.wav.writeframesraw(pcm)
        if voiced:
            self.last_voice = self.sample
        if (self.sample - self.active['startSample']) / RATE >= self.maximum:
            self.finish('utterance_limit', False)
            raise OverflowError('Utterance exceeded explicit maximum; incomplete audio retained')
        if (self.sample - self.last_voice) / RATE >= self.pause:
            self.finish('pause', True)

    def finish(self, reason='capture_interrupted', complete=False):
        if self.active is None:
            return
        try:
            self.wav.close()
            self.stream.flush()
            import os
            os.fsync(self.stream.fileno())
        finally:
            self.stream.close()
        event = {**self.active, 'event': 'audio.final', 'revision': 1,
                 'endSample': self.sample, 'speechEndSample': self.last_voice,
                 'captureEndedAt': self.capture_ended_at, 'endpointReason': reason,
                 'audioComplete': complete, 'final': True, 'executable': False}
        self.active = self.wav = self.stream = None
        self.emit(event)


def wav_blocks(path):
    with wave.open(str(path), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, RATE):
            raise ValueError('Replay requires PCM16 mono 16000Hz; never silently resample')
        while pcm := wav.readframes(BLOCK_SAMPLES):
            yield pcm
