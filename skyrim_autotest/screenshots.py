"""DevBench-only diagnostic screenshots with fresh, independently checked files.

No desktop capture, focus changes, game starts or retries. Assisted capture keeps
its separate mandatory spoken countdown. Verified pixels are not a visual verdict.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import zlib

from .assisted_capture import image_info, request
from .voice_inbox import atomic, locked


def segment(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', value):
        raise ValueError('Screenshot needs a unique single-segment identifier')
    return value


def unlinked(path):
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Screenshot path contains a link or reparse point')


def verify_file(output, body, receipt):
    if not isinstance(receipt, dict) or receipt.get('ok') is not True:
        raise ValueError('DevBench did not confirm a completed screenshot')
    filename = receipt.get('file')
    if (not isinstance(filename, str) or Path(filename).name != filename or
            '/' in filename or '\\' in filename or ':' in filename or
            Path(filename).stem != body['checkpointId'] or
            Path(filename).suffix.lower() not in ('.png', '.bmp')):
        raise ValueError('DevBench returned an invalid screenshot filename')
    image = output / body['recording'] / body['variant'] / filename
    unlinked(image)
    if not image.is_file() or not image.resolve().is_relative_to(output.resolve()):
        raise ValueError('DevBench image missing from the requested external directory')
    for key in ('path', 'realPath'):
        returned = receipt.get(key)
        if returned is not None and (not isinstance(returned, str) or
                Path(returned).resolve() != image.resolve()):
            raise ValueError('DevBench returned a different screenshot path')
    before = image.stat()
    if not 0 < before.st_size <= 32 * 1024 * 1024:
        raise ValueError('Screenshot empty or exceeds 32 MiB bound')
    with image.open('rb') as stream:
        opened = os.fstat(stream.fileno())
        data = stream.read(32 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    current = image.stat()
    signature = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)
    if (signature(before) != signature(opened) or signature(opened) != signature(after) or
            signature(after) != signature(current) or len(data) != opened.st_size):
        raise ValueError('Screenshot file changed during verification')
    unlinked(image)
    try:
        info = image_info(data)
    except zlib.error as error:
        raise ValueError('Invalid screenshot compressed pixels: ' + str(error)) from None
    if image.suffix.lower() != '.' + info['format']:
        raise ValueError('Screenshot filename does not match the actual image format')
    if 'bytes' in receipt and (type(receipt['bytes']) is not int or receipt['bytes'] != len(data)):
        raise ValueError('DevBench screenshot byte count differs from the actual file')
    return dict(image=str(image.resolve()), bytes=len(data), imageInfo=info,
                sha256=hashlib.sha256(data).hexdigest(), captureFileVerified=True)


def capture(folder, identifier, guard, call, *, options=None, announce=None):
    segment(identifier)
    folder = Path(folder).absolute()
    unlinked(folder)
    folder.mkdir(parents=True, exist_ok=True)
    unlinked(folder)
    with locked(folder):
        bundle = folder / identifier
        bundle.mkdir()  # Uncertain/existing requests never replay.
        report_file = bundle / 'screenshot-receipt.json'
        report = dict(id=identifier, startedAt=time.time(), status='preparing',
                      api='/api/tool/capture', foregroundChanged=False,
                      visualContentVerified=False, captureFileVerified=False)
        atomic(report_file, report)
        try:
            body = dict(kind='auto', allowNative=True, excludeUi=False,
                        allowTimeScale=True, checkpointId=identifier,
                        recording='autotest', variant='diagnostic', outDir=str(bundle),
                        resolveRealPath=True, timeoutMs=8000)
            body.update(options or {})
            if body.get('checkpointId') != identifier or body.get('action', 'capture') != 'capture':
                raise ValueError('Only one matching screenshot capture is supported')
            for key in ('recording', 'variant'):
                segment(body[key])
            if any(key in body for key in ('repeat', 'count', 'everyNFrames')):
                raise ValueError('Screenshot capture cannot alias repeated or burst requests')
            output = Path(body['outDir'])
            if not output.is_absolute():
                raise ValueError('Screenshot output must be an absolute external directory')
            unlinked(output)
            output.mkdir(parents=True, exist_ok=True)
            unlinked(output)
            body['outDir'] = str(output.resolve())
            target = output / body['recording'] / body['variant']
            unlinked(target)
            if target.exists():
                unlinked(target)
                if any(path.stem == identifier for path in target.iterdir()):
                    raise ValueError('Screenshot pixels already exist; never adopt or overwrite')
            report['request'] = body
            guard()
            if announce is not None:
                announce('Сейчас будет скриншот. Три, два, один. Снимаю.')
                report['countdownCompletedAt'] = time.time()
                guard()
            report['status'] = 'capture_requested'
            atomic(report_file, report)
            receipt = call(body)
            report['providerReceipt'] = receipt
            atomic(report_file, report)
            verified = verify_file(output, body, receipt)
            guard()
            report.update(verified, status='file_verified', finishedAt=time.time())
        except Exception as error:
            report.update(status='unavailable_or_uncertain', reason=str(error),
                          captureFileVerified=False, finishedAt=time.time())
            atomic(report_file, report)
            raise
        atomic(report_file, report)
        return report


def session_capture(session, args, call, guard):
    identifier = segment(args.get('checkpointId'))
    records = session.state.setdefault('screenshots', {})
    if identifier in records:
        raise ValueError('Screenshot already attempted; never replay')
    options = dict(args)
    # Preserve DevBench's ordinary scale admission (strict photography relies
    # on it). Only standalone diagnostic capture explicitly permits any scale.
    options.setdefault('allowTimeScale', False)
    if 'outDir' in options:
        selected = Path(options['outDir'])
        if not selected.is_absolute() or not selected.resolve().is_relative_to(session.dir.resolve()):
            raise ValueError('Scenario screenshot output must stay within its run directory')
    folder = session.dir / 'screenshots'
    receipt_file = folder / identifier / 'screenshot-receipt.json'
    record = dict(id=identifier, receipt=str(receipt_file), status='preparing')
    records[identifier] = record
    session.save()
    try:
        report = capture(folder, identifier, guard, call, options=options)
        record.update(report)
        # Preserve the provider contract and its native/degraded metadata.
        return dict(report['providerReceipt'], captureFileVerified=True,
                    image=report['image'], imageInfo=report['imageInfo'], sha256=report['sha256'])
    except Exception:
        if receipt_file.is_file():
            record.update(json.loads(receipt_file.read_text(encoding='utf-8')))
        else:
            record['status'] = 'unavailable_or_uncertain'
        raise
    finally:
        session.save()


def collect(session, copy):
    for identifier, record in session.state.get('screenshots', {}).items():
        segment(identifier)
        receipt_file = session.dir / 'screenshots' / identifier / 'screenshot-receipt.json'
        if Path(record['receipt']).resolve() != receipt_file.resolve():
            raise ValueError('Screenshot receipt escaped its owned run')
        unlinked(receipt_file)
        copy(receipt_file, 'screenshot-' + identifier + '.json', 'capture-receipt', required=True)
        if record.get('captureFileVerified') is not True:
            continue
        actual = verify_file(Path(record['request']['outDir']), record['request'], record['providerReceipt'])
        if actual['sha256'] != record.get('sha256') or actual['image'] != record.get('image'):
            raise ValueError('Verified screenshot evidence changed before collection')
        copied = copy(Path(actual['image']), 'screenshot-' + identifier + Path(actual['image']).suffix,
                      'capture', required=True)
        if copied is None or copied['sha256'] != actual['sha256']:
            raise ValueError('Screenshot evidence changed during collection')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--id', required=True)
    parser.add_argument('--identity', type=Path, required=True, help='Exact already-owned game {pid,birth,path}')
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if os.name != 'nt' or not 1 <= args.port <= 65535:
            raise ValueError('Requires Windows and a verified local DevBench port')
        from . import native
        identity = json.loads(args.identity.read_text(encoding='utf-8-sig'))
        def guard():
            if not native.alive(identity) or request(args.port, 'health').get('pid') != identity['pid']:
                raise ValueError('Original game identity unavailable/changed')
        report = capture(args.out, args.id, guard,
                         lambda body: request(args.port, 'tool/capture', body))
        print(json.dumps(report, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, zlib.error) as error:
        print(json.dumps(dict(status='unavailable_or_uncertain', captureFileVerified=False,
                              reason=str(error)), ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
