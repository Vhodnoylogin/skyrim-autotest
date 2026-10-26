"""Protocol-only final-ASR JSONL forwarding. Never captures or interprets audio."""
import argparse
from contextlib import contextmanager
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import time
import uuid

from .command_bus import BusError, binding_value, external_path, load_config, strict_json
from .command_bus_http import CommandHTTPClient

LIMIT = 32 * 1024 * 1024
FIELDS = set('seq event revision text accepted executable utteranceId audioSha256 final audioComplete endpointReason startSample speechStartSample sampleRate wav captureStartedAt endSample speechEndSample captureEndedAt segments asrStartedAt asrEndedAt note at receivedAt'.split())


class BridgeError(ValueError): pass
class ReceiverUnavailable(BridgeError): pass
class SourcePending(BridgeError): pass


def _sha(data): return hashlib.sha256(data).hexdigest()
def _json(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
def _pin(raw): return {'bytes': len(raw), 'sha256': _sha(raw)}


@contextmanager
def locked(path):
    path = external_path(path, 'forwarder lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0: stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise BridgeError('Another forwarder owns this cursor lock') from error
        try: yield
        finally:
            stream.seek(0)
            if os.name == 'nt': msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream, fcntl.LOCK_UN)


def _row(value, sequence):
    if (type(value) is not dict or set(value) - FIELDS or type(value.get('seq')) is not int or value['seq'] != sequence or
            value.get('event') != 'speech.final' or type(value.get('revision')) is not int or value['revision'] != 2 or
            any(value.get(key) is not True for key in ('accepted', 'executable', 'final', 'audioComplete')) or
            value.get('endpointReason') != 'pause' or not isinstance(value.get('text'), str) or not value['text'].strip() or
            len(value['text'].encode('utf-8')) > 32768 or any(ord(c) < 32 and c not in '\n\r\t' for c in value['text']) or
            not isinstance(value.get('utteranceId'), str) or not re.fullmatch('[0-9a-f]{32}', value['utteranceId']) or
            not isinstance(value.get('audioSha256'), str) or not re.fullmatch('[0-9a-f]{64}', value['audioSha256'])):
        raise BridgeError('Source has a gap, duplicate, unknown or non-final/accepted complete record; nothing skipped')
    return value


class ASRBridge:
    def __init__(self, channel_config, source, state, session, source_id, after=None, client=None):
        self.channel, self.source, self.path = [external_path(value, name) for value, name in
            ((channel_config, 'channel configuration'), (source, 'ASR source'), (state, 'own cursor'))]
        self.lock = external_path(str(self.path) + '.lock', 'own cursor lock')
        cfg = load_config(self.channel)
        protected = {self.channel, self.source, Path(cfg['database']), Path(cfg['tokenFile'])}
        protected.update(Path(cfg['database'] + suffix) for suffix in ('-wal', '-shm', '-journal'))
        if self.path in protected or self.lock in protected or self.path == self.lock:
            raise BridgeError('Own cursor/lock must be separate from source and receiver files')
        for value in (session, source_id):
            if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 33 or ord(c) == 127 for c in value):
                raise BridgeError('Exact session and source IDs are required')
        self.session, self.source_id, self.after = session, source_id, after
        self.client = client or CommandHTTPClient(self.channel, timeout=3)
        self.state, self.state_sha = None, None

    def _snapshot(self):
        external_path(self.source, 'ASR source')
        if not self.source.exists() and self.state is None and not self.path.exists() and self.after == 0:
            raise SourcePending('Waiting for external source creation; producer file is untouched')
        with self.source.open('rb') as stream:
            info = os.fstat(stream.fileno())
            raw = stream.read(LIMIT + 1)
            current = self.source.stat()
        if max(len(raw), info.st_size, current.st_size) > LIMIT: raise BridgeError('ASR source exceeds the 32MiB byte bound')
        if (info.st_dev, info.st_ino) != (current.st_dev, current.st_ino) or current.st_size < len(raw):
            raise BridgeError('ASR source identity changed or truncated while reading')
        identity = {'source': str(self.source), 'device': info.st_dev, 'inode': info.st_ino,
            'channelConfig': str(self.channel), 'channelSha256': _sha(self.channel.read_bytes()),
            'sessionId': self.session, 'sourceId': self.source_id}
        complete = raw[:raw.rfind(b'\n') + 1]
        rows, offsets, seen, offset = [], [0], set(), 0
        for line in complete.splitlines(keepends=True):
            row = _row(strict_json(line.decode('utf-8')), len(rows) + 1)
            if row['utteranceId'] in seen: raise BridgeError('Duplicate utterance identity in ASR source')
            seen.add(row['utteranceId']); rows.append(row); offset += len(line); offsets.append(offset)
        return identity, raw, rows, offsets, len(raw) != len(complete)

    def _save(self, initial=False):
        external_path(self.path, 'own cursor')
        if not initial and _sha(self.path.read_bytes()) != self.state_sha:
            raise BridgeError('Own cursor changed externally; refusing overwrite/reset')
        data = _json(self.state)
        temporary = self.path.with_name(self.path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            if initial: os.link(temporary, self.path)
            else: os.replace(temporary, self.path)
        finally: temporary.unlink(missing_ok=True)
        self.state_sha = _sha(data)

    def _load(self):
        identity, raw, rows, offsets, partial = self._snapshot()
        if self.state is None:
            if self.path.exists():
                if self.after is not None: raise BridgeError('--after is only for a new reviewed baseline; existing state is never reset')
                data = self.path.read_bytes(); self.state_sha = _sha(data); self.state = strict_json(data)
            else:
                if type(self.after) is not int or not 0 <= self.after <= len(rows):
                    raise BridgeError('A new cursor requires explicit reviewed --after within the complete source sequence')
                self.path.parent.mkdir(parents=True, exist_ok=True)
                namespace = _sha(_json({key: identity[key] for key in ('source', 'device', 'inode')}))
                self.state = {'schemaVersion': 1, 'identity': identity, 'namespace': namespace, 'cursor': self.after,
                    'anchor': _pin(raw[:offsets[self.after]]), 'observed': _pin(raw), 'binding': None}
                self._save(initial=True)
        state = self.state
        namespace = _sha(_json({key: identity[key] for key in ('source', 'device', 'inode')}))
        if (type(state) is not dict or set(state) != {'schemaVersion', 'identity', 'namespace', 'cursor', 'anchor', 'observed', 'binding'} or
                type(state['schemaVersion']) is not int or state['schemaVersion'] != 1 or state['identity'] != identity or state['namespace'] != namespace or
                type(state['cursor']) is not int or not 0 <= state['cursor'] <= len(rows) or
                state['anchor'] != _pin(raw[:offsets[state['cursor']]]) or
                type(state['observed']) is not dict or type(state['observed'].get('bytes')) is not int or
                not 0 <= state['observed']['bytes'] <= len(raw) or state['observed'] != _pin(raw[:state['observed']['bytes']])):
            raise BridgeError('Source/session identity, cursor anchor or observed prefix changed/truncated; refusing reset/skip')
        if _sha(self.path.read_bytes()) != self.state_sha: raise BridgeError('Own cursor changed externally')
        if state['observed'] != _pin(raw): state['observed'] = _pin(raw); self._save()
        return raw, rows, offsets, partial

    def _receive(self, action, value):
        try:
            return self.client.submit(value) if action == 'submit' else self.client.call(action, value)
        except BusError as error:
            if error.status == 503: raise ReceiverUnavailable('Receiver unavailable; durable cursor retained') from error
            raise BridgeError('Receiver refused the fixed source/session request; cursor retained') from error
        except (OSError, HTTPException) as error:
            raise ReceiverUnavailable('Receiver unavailable or ACK lost; durable cursor retained') from error

    def once(self):
        raw, rows, offsets, partial = self._load()
        forwarded = 0
        if len(rows) > self.state['cursor']:
            status = self._receive('status', {'sessionId': self.session})
            if not isinstance(status, dict) or status.get('sessionId') != self.session or 'binding' not in status:
                raise BridgeError('Receiver status does not identify the exact operator session')
            if status['binding'] is None:
                if self.state['binding'] is None:
                    raise ReceiverUnavailable('Operator session is not bound yet; durable cursor retained')
                raise BridgeError('Pinned operator binding disappeared; forwarding stopped')
            binding = binding_value(status['binding'])
            if self.state['binding'] is not None and self.state['binding'] != binding:
                raise BridgeError('Operator session binding changed; source forwarding stopped')
            if self.state['binding'] is None: self.state['binding'] = binding; self._save()
        for row in rows[self.state['cursor']:]:
            # Revalidate the pinned source before each immutable ingress attempt.
            self._load()
            event = self.state['namespace'] + ':' + row['utteranceId']
            request = {'sessionId': self.session, 'sourceId': self.source_id, 'sourceEventId': event,
                'kind': 'asr.final', 'text': row['text'], 'metadata': {'queueNamespace': self.state['namespace'],
                    'seq': row['seq'], 'utteranceId': row['utteranceId'], 'audioSha256': row['audioSha256'], 'revision': 2}}
            ack = self._receive('submit', request)
            command = ack.get('command', {}) if isinstance(ack, dict) else None
            if (not isinstance(command, dict) or ack.get('acknowledged') is not True or any(command.get(key) != request[key] for key in request) or
                    command.get('binding') != self.state['binding']):
                raise BridgeError('Receiver ACK does not match this immutable final utterance/session; cursor retained')
            self.state.update(cursor=row['seq'], anchor=_pin(raw[:offsets[row['seq']]]))
            self._save(); forwarded += 1
        return {'forwarded': forwarded, 'cursor': self.state['cursor'], 'partialTail': partial}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('channel-config', 'source', 'state', 'session', 'source-id'): parser.add_argument('--' + field, required=True)
    parser.add_argument('--after', type=int)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument('--once', action='store_true'); mode.add_argument('--serve', action='store_true')
    args = parser.parse_args(argv)
    try:
        bridge = ASRBridge(args.channel_config, args.source, args.state, args.session, args.source_id, args.after)
        with locked(bridge.lock):
            unavailable = False
            while True:
                try:
                    result = bridge.once()
                    if args.once or result['forwarded'] or unavailable: print(json.dumps(result), flush=True)
                    unavailable = False
                    if args.once: return 0
                except (ReceiverUnavailable, SourcePending) as waiting:
                    if args.once: raise
                    if not unavailable: print(json.dumps({'status': 'source-pending' if isinstance(waiting, SourcePending) else 'receiver-unavailable', 'cursorRetained': True}), flush=True)
                    unavailable = True
                time.sleep(.5)
    except KeyboardInterrupt:
        print(json.dumps({'status': 'stopped'})); return 0
    except (BridgeError, BusError, OSError, UnicodeError, ValueError) as error:
        reason = str(error) if isinstance(error, (BridgeError, BusError)) else 'Forwarder file/encoding failure; no source record skipped'
        print(json.dumps({'status': 'blocked', 'error': reason})); return 2


if __name__ == '__main__': raise SystemExit(main())
