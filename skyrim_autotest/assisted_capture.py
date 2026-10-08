"""One explicit assisted screenshot: spoken countdown, capture, verified file.

No keyboard/focus operations, game launch, restart or automatic retry. PNG/BMP
file integrity does not prove visual content; the operator must view the image.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
from urllib.request import Request, urlopen
import zlib

from .voice_inbox import atomic, locked


def image_info(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        offset, compressed, dimensions = 8, bytearray(), None
        ended = False
        while offset + 12 <= len(data):
            size = struct.unpack_from('>I', data, offset)[0]
            kind = data[offset + 4:offset + 8]
            end = offset + 12 + size
            if end > len(data):
                raise ValueError('Truncated PNG chunk')
            payload = data[offset + 8:offset + 8 + size]
            if zlib.crc32(kind + payload) & 0xffffffff != struct.unpack_from('>I', data, end - 4)[0]:
                raise ValueError('PNG CRC mismatch')
            if dimensions is None:
                if kind != b'IHDR' or size != 13:
                    raise ValueError('PNG header missing')
                width, height, depth, colour, compression, filtering, interlace = struct.unpack('>IIBBBBB', payload)
                if depth != 8 or colour not in (0, 2, 4, 6) or compression or filtering or interlace:
                    raise ValueError('Unsupported PNG encoding; do not claim verified image')
                dimensions = width, height
                channels = {0: 1, 2: 3, 4: 2, 6: 4}[colour]
            elif kind == b'IDAT':
                compressed.extend(payload)
            elif kind == b'IEND':
                if size or end != len(data):
                    raise ValueError('Invalid PNG end')
                ended = True
                break
            offset = end
        if not ended or not dimensions or not compressed:
            raise ValueError('Incomplete PNG')
        width, height = dimensions
        expected = height * (1 + width * channels)
        if not width or not height or expected > 128 * 1024 * 1024:
            raise ValueError('Image dimensions exceed bounded decoder')
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, expected + 1)
        if len(raw) != expected or not decoder.eof or decoder.unused_data:
            raise ValueError('Incomplete/excess PNG pixels')
        stride = 1 + width * channels
        if any(raw[i] > 4 for i in range(0, len(raw), stride)):
            raise ValueError('Invalid PNG row filter')
        return dict(format='png', width=width, height=height)
    if data.startswith(b'BM') and len(data) >= 54:
        declared, offset = struct.unpack_from('<I', data, 2)[0], struct.unpack_from('<I', data, 10)[0]
        header, width, height, planes, bits, compression = struct.unpack_from('<IiiHHI', data, 14)
        if header < 40 or width <= 0 or not height or planes != 1 or bits not in (24, 32) or compression != 0:
            raise ValueError('Unsupported BMP encoding')
        expected = abs(height) * (((width * bits + 31) // 32) * 4)
        if declared != len(data) or offset < 14 + header or offset + expected > len(data):
            raise ValueError('Incomplete BMP pixels')
        return dict(format='bmp', width=width, height=abs(height))
    raise ValueError('Unsupported/invalid image; expected PNG or uncompressed BMP')


def speak(text, output):
    env = dict(os.environ, SKYRIM_ASSISTED_TEXT=text, SKYRIM_ASSISTED_OUTPUT=output)
    script = """$ErrorActionPreference='Stop'; $s=New-Object -ComObject SAPI.SpVoice;
$o=@($s.GetAudioOutputs() | Where-Object {$_.GetDescription() -eq $env:SKYRIM_ASSISTED_OUTPUT});
if($o.Count -ne 1){throw 'Exact headset output unavailable or ambiguous'};
$v=@($s.GetVoices() | Where-Object {$_.GetDescription() -match 'Irina'});
if($v.Count -ne 1){throw 'Russian voice unavailable or ambiguous'};
$s.AudioOutput=$o[0]; $s.Voice=$v[0]; $s.Rate=1; [void]$s.Speak($env:SKYRIM_ASSISTED_TEXT,0)"""
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                   env=env, check=True, timeout=20, capture_output=True)


def request(port, endpoint, body=None):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = Request(f'http://127.0.0.1:{port}/api/{endpoint}', data=data,
                  headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def capture(folder, identifier, guard, call, say):
    folder = Path(folder).resolve()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identifier):
        raise ValueError('Invalid unique screenshot request ID')
    with locked(folder):
        bundle = folder / identifier
        bundle.mkdir()  # Existing/uncertain request never replays a screenshot.
        report = dict(id=identifier, startedAt=time.time(), status='preparing',
                      foregroundChanged=False, visualContentVerified=False)
        report_file = bundle / 'capture-receipt.json'
        atomic(report_file, report)
        try:
            guard()
            say('Сейчас будет скриншот. Три, два, один. Снимаю.')
            report['countdownCompletedAt'] = time.time()
            guard()
            report['status'] = 'capture_requested'
            atomic(report_file, report)
            receipt = call(dict(kind='auto', allowNative=True, excludeUi=False,
                                allowTimeScale=True, checkpointId=identifier,
                                recording='assisted', variant='manual',
                                outDir=str(bundle), resolveRealPath=True, timeoutMs=8000))
            report['providerReceipt'] = receipt
            if receipt.get('ok') is False or not receipt.get('file'):
                raise ValueError('Capture provider did not return an image file')
            name = receipt['file']
            if Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('Capture filename is not a single segment')
            # An explicit external outDir avoids MO2 virtual-path guessing.
            image = bundle / 'assisted' / 'manual' / name
            if image.is_symlink() or not image.resolve().is_relative_to(bundle) or not image.is_file():
                raise ValueError('Provider image missing from external output directory')
            size = image.stat().st_size
            if not 0 < size <= 32 * 1024 * 1024:
                raise ValueError('Image file empty or exceeds 32 MiB bound')
            data = image.read_bytes()
            info = image_info(data)
            guard()
            report.update(status='file_verified', image=str(image), bytes=len(data),
                          sha256=hashlib.sha256(data).hexdigest(), imageInfo=info,
                          captureFileVerified=True, finishedAt=time.time())
        except Exception as error:
            report.update(status='unavailable_or_uncertain', reason=str(error),
                          captureFileVerified=False, finishedAt=time.time())
            atomic(report_file, report)
            raise
        atomic(report_file, report)
        return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--identity', type=Path, required=True, help='External exact game {pid,birth,path}')
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--voice-output', required=True, help='Exact headset SAPI device description')
    args = parser.parse_args(argv)
    try:
        if os.name != 'nt' or not 1 <= args.port <= 65535:
            raise ValueError('Requires Windows and a verified local DevBench port')
        from . import native
        identity = json.loads(args.identity.read_text(encoding='utf-8-sig'))
        def guard():
            if not native.alive(identity) or request(args.port, 'health').get('pid') != identity['pid']:
                raise ValueError('Original manual game identity unavailable/changed')
        result = capture(args.out, args.id, guard,
                         lambda body: request(args.port, 'tool/capture', body),
                         lambda text: speak(text, args.voice_output))
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, zlib.error, subprocess.SubprocessError) as error:
        print(json.dumps(dict(status='unavailable_or_uncertain', reason=str(error)), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
