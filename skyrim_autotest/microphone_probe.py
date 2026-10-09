"""Bounded shared WinMM input probe; level evidence is not speech qualification.

Does not change device defaults/mute/gain or start/stop the ASR singleton.
PCM stays in memory unless an explicit external --wav path is supplied.
"""
import argparse
from array import array
import ctypes as C
from ctypes import wintypes as W
import datetime
import json
import math
import os
from pathlib import Path
import time
import wave


class Format(C.Structure):
    _pack_ = 2
    _fields_ = [('tag', W.WORD), ('channels', W.WORD), ('rate', W.DWORD),
                ('bytesPerSecond', W.DWORD), ('align', W.WORD),
                ('bits', W.WORD), ('extra', W.WORD)]


class Caps(C.Structure):
    _fields_ = [('manufacturer', W.WORD), ('product', W.WORD), ('version', W.DWORD),
                ('name', W.WCHAR * 32), ('formats', W.DWORD),
                ('channels', W.WORD), ('reserved', W.WORD)]


class Header(C.Structure):
    _fields_ = [('data', C.c_void_p), ('length', W.DWORD), ('recorded', W.DWORD),
                ('user', C.c_size_t), ('flags', W.DWORD), ('loops', W.DWORD),
                ('next', C.c_void_p), ('reserved', C.c_size_t)]


def api():
    if os.name != 'nt':
        raise OSError('Windows shared audio capture required')
    mm = C.WinDLL('winmm')
    mm.waveInGetNumDevs.restype = W.UINT
    mm.waveInGetDevCapsW.argtypes = [C.c_size_t, C.POINTER(Caps), W.UINT]
    mm.waveInOpen.argtypes = [C.POINTER(C.c_void_p), W.UINT, C.POINTER(Format), C.c_size_t, C.c_size_t, W.DWORD]
    for name in ['waveInPrepareHeader', 'waveInAddBuffer', 'waveInUnprepareHeader']:
        getattr(mm, name).argtypes = [C.c_void_p, C.POINTER(Header), W.UINT]
    for name in ['waveInStart', 'waveInStop', 'waveInReset', 'waveInClose']:
        getattr(mm, name).argtypes = [C.c_void_p]
    return mm


def check(code, operation):
    if code:
        raise OSError(f'{operation} failed with WinMM code {code}')


def devices():
    mm = api()
    result = []
    for index in range(mm.waveInGetNumDevs()):
        caps = Caps()
        check(mm.waveInGetDevCapsW(index, C.byref(caps), C.sizeof(caps)), 'device enumeration')
        result.append(dict(index=index, name=caps.name, maximumChannels=caps.channels,
                           note='WinMM name truncated to 31 UTF-16 characters; match uniquely'))
    return result


def levels(pcm, rate=16000):
    if len(pcm) % 2:
        raise ValueError('Partial PCM sample')
    samples = array('h', pcm)
    def stats(values):
        peak = max((abs(v) for v in values), default=0)
        rms = math.sqrt(sum(v * v for v in values) / len(values)) if values else 0
        return dict(peak=peak, rms=rms,
                    peakDbFS=20 * math.log10(peak / 32768) if peak else None,
                    rmsDbFS=20 * math.log10(rms / 32768) if rms else None,
                    nonzeroSamples=sum(v != 0 for v in values))
    return {**stats(samples), 'seconds': len(samples) / rate,
            'perSecond': [dict(second=i // rate, **stats(samples[i:i + rate]))
                          for i in range(0, len(samples), rate)],
            'recognizedHumanSpeech': False,
            'note': 'Audio level alone cannot distinguish speech, game sound or room noise'}


def probe(device, seconds=6):
    if not math.isfinite(seconds) or not 1 <= seconds <= 30:
        raise ValueError('Probe duration must be between 1 and 30 seconds')
    if type(device) is not int or device < 0:
        raise ValueError('Explicit enumerated device index required')
    mm = api()
    rate = 16000
    fmt = Format(1, 1, rate, rate * 2, 2, 16, 0)
    handle = C.c_void_p()
    buffer = C.create_string_buffer(round(rate * seconds) * 2)
    header = Header(C.addressof(buffer), len(buffer), 0, 0, 0, 0, None, 0)
    check(mm.waveInOpen(C.byref(handle), device, C.byref(fmt), 0, 0, 0), 'shared input open')
    prepared = False
    try:
        check(mm.waveInPrepareHeader(handle, C.byref(header), C.sizeof(header)), 'prepare audio buffer')
        prepared = True
        check(mm.waveInAddBuffer(handle, C.byref(header), C.sizeof(header)), 'queue audio buffer')
        check(mm.waveInStart(handle), 'start audio capture')
        deadline = time.monotonic() + seconds + 3
        while not header.flags & 1:
            if time.monotonic() >= deadline:
                raise TimeoutError('Input did not complete audio buffer in original deadline')
            time.sleep(.02)
        mm.waveInStop(handle)
        mm.waveInReset(handle)
        if header.recorded != len(buffer):
            raise ValueError('Incomplete input buffer')
        pcm = buffer.raw[:header.recorded]
        return dict(sampleRate=rate, recordedBytes=len(pcm), **levels(pcm, rate)), pcm
    finally:
        mm.waveInStop(handle)
        mm.waveInReset(handle)
        if prepared:
            mm.waveInUnprepareHeader(handle, C.byref(header), C.sizeof(header))
        mm.waveInClose(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', help='Unique name fragment; never falls back to default')
    parser.add_argument('--seconds', type=float, default=6)
    parser.add_argument('--output', type=Path, help='External level JSON')
    parser.add_argument('--wav', type=Path, help='Explicit external PCM recording for offline ASR diagnosis')
    args = parser.parse_args(argv)
    try:
        found = devices()
        if not args.device:
            result = dict(devices=found)
        else:
            matches = [d for d in found if args.device.casefold() in d['name'].casefold()]
            if len(matches) != 1:
                raise ValueError('Selected input absent/ambiguous; enumerate first')
            result, pcm = probe(matches[0]['index'], args.seconds)
            result.update(device=matches[0], atUtc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          rawAudioSaved=False)
            if args.wav:
                args.wav.parent.mkdir(parents=True, exist_ok=True)
                with args.wav.open('xb') as stream:
                    with wave.open(stream, 'wb') as wav:
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(result['sampleRate'])
                        wav.writeframes(pcm)
                result.update(rawAudioSaved=True, wav=str(args.wav.resolve()))
        if args.output:
            from .voice_inbox import atomic
            args.output.parent.mkdir(parents=True, exist_ok=True)
            atomic(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps(dict(status='unavailable', reason=str(error)), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
