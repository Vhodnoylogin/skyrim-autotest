"""Whole-utterance external Whisper CLI listener/replay. No game or AI actions."""
import argparse
import datetime
import hashlib
import http.server
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time
import urllib.parse

from .voice_audio import Utterances, capture, wav_blocks
from .voice_inbox import atomic, locked, records
from .microphone_probe import devices


def external(path):
    path = Path(path).resolve()
    if any((p / '.git').exists() for p in [path, *path.parents]):
        raise ValueError('Audio, transcripts and runtime state must remain outside Git')
    return path


class Session:
    def __init__(self, folder, config, wake='полигон', window=1800, conversation=14400,
                 timeout=180, threads=4, maximum_pending=32):
        if not 1 <= timeout <= 600 or not 1 <= threads <= 32 or not 1 <= maximum_pending <= 256:
            raise ValueError('Invalid ASR timeout, threads or pending limit')
        if not 1 <= window <= conversation <= 86400:
            raise ValueError('Invalid conversation window')
        self.folder = external(folder)
        self.folder.mkdir(parents=True, exist_ok=False)
        self.config, self.wake = config, wake.casefold()
        self.window, self.conversation = window, conversation
        self.timeout, self.threads = timeout, threads
        self.heard = self.folder / 'heard.jsonl'
        self.heard.touch()
        self.events = self.folder / 'events.jsonl'
        self.mutex = threading.Lock()
        self.pending = queue.Queue(maximum_pending)
        self.seq = 0
        self.until = self.woke = 0
        self.error = None
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker.start()
        self.health = {'ok': True, 'pid': os.getpid(), 'protocol': 'whole-utterance-v2',
                       'liveQualified': False, 'heard': str(self.heard)}
        self.update_health()

    def update_health(self, **fields):
        self.health.update(fields, error=self.error, pending=self.pending.qsize(),
                           lastSeq=self.seq, checkedAt=time.time())
        self.health['ok'] = self.error is None
        atomic(self.folder / 'health.json', self.health)

    def event(self, event):
        with self.mutex:
            with self.events.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({**event, 'atUtc': datetime.datetime.now(
                    datetime.timezone.utc).isoformat()}, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        if event['event'] == 'audio.final':
            # Metadata is durable before admission; full spool never silently drops.
            atomic(self.folder / (event['utteranceId'] + '.audio.json'), event)
            if event['audioComplete']:
                try:
                    self.pending.put_nowait(event)
                except queue.Full as error:
                    self.error = 'ASR backlog full; retained unprocessed audio, capture must stop'
                    raise OverflowError(self.error) from error

    def _worker(self):
        while True:
            event = self.pending.get()
            try:
                if event is None:
                    return
                self.transcribe(event)
            except Exception as error:
                self.error = str(error)
                try:
                    self.event({'event': 'asr.failed', 'utteranceId': event['utteranceId'],
                                'reason': self.error, 'executable': False})
                except Exception as report_error:
                    # A failed diagnostic disk write must not kill the worker
                    # leaving unfinished queue tasks and an infinite shutdown.
                    self.error += '; failed to retain diagnostic: ' + str(report_error)
            finally:
                self.pending.task_done()

    def transcribe(self, audio):
        identity = audio['utteranceId']
        output = self.folder / (identity + '.asr')
        started = time.time()
        self.event({'event': 'asr.started', 'utteranceId': identity, 'asrStartedAt': started})
        command = [self.config['cli'], '-m', self.config['model'], '-l',
                   self.config.get('language', 'ru'), '-f', audio['wav'],
                   '-oj', '-of', str(output), '-t', str(self.threads)]
        with (self.folder / (identity + '.asr.log')).open('xb') as diagnostic:
            result = subprocess.run(command, stdout=diagnostic, stderr=subprocess.STDOUT,
                                    timeout=self.timeout, check=False)
        if result.returncode:
            raise ValueError('Whisper CLI failed; inspect retained ASR log')
        raw = json.loads(output.with_suffix('.asr.json').read_text(encoding='utf-8'))
        segments = raw.get('transcription')
        if not isinstance(segments, list) or not all(isinstance(s.get('text'), str) for s in segments):
            raise ValueError('Whisper JSON lacks transcription segments')
        text = ' '.join(s['text'].strip() for s in segments).strip()
        now = time.monotonic()
        if self.wake and self.wake in text.casefold():
            self.woke, self.until = now, now + self.window
        accepted = (bool(text) and not re.fullmatch(r'[\s\[(].*[\])\s]', text)
                    and (not self.wake or now < self.until and now - self.woke < self.conversation))
        ended = time.time()
        final = {**audio, 'event': 'speech.final', 'revision': 2, 'text': text,
                 'segments': segments, 'asrStartedAt': started, 'asrEndedAt': ended,
                 'audioSha256': hashlib.sha256(Path(audio['wav']).read_bytes()).hexdigest(),
                 'accepted': accepted, 'executable': accepted,
                 'note': 'Final ASR is fallible; human intent still requires operator review'}
        atomic(self.folder / (identity + '.final.json'), final)
        self.event(final)
        if accepted:
            self.seq += 1
            row = {**final, 'seq': self.seq, 'at': datetime.datetime.now(
                datetime.timezone.utc).isoformat(), 'receivedAt': time.time()}
            with self.heard.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            self.until = now + self.window

    def close(self):
        self.pending.join()
        self.pending.put(None)
        self.worker.join(self.timeout + 5)
        if self.worker.is_alive():
            raise TimeoutError('ASR worker did not settle; retain session for reconciliation')
        self.update_health(captureActive=False)


def serve(session, port):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            if url.path == '/api/health':
                result, code = dict(session.health), 200
            elif url.path == '/api/events':
                try:
                    since = int(urllib.parse.parse_qs(url.query).get('since', ['0'])[0])
                    result = {'events': [{'seq': r['seq'], 'at': r['at'],
                              'topic': 'voice.heard', 'payload': r}
                              for r in records(session.heard) if r['seq'] > since],
                              'last': session.seq}
                    code = 200
                except (OSError, ValueError):
                    result, code = {'error': 'Invalid cursor/queue'}, 400
            else:
                result, code = {'error': 'Unavailable endpoint'}, 404
            body = json.dumps(result, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asr-config', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True, help='NEW external audio/transcript folder')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--replay-wav', type=Path)
    source.add_argument('--device', help='Explicit unique WinMM input name fragment')
    parser.add_argument('--listen-lock', type=Path, help='REQUIRED live: existing shared singleton lock path')
    parser.add_argument('--wake', default='полигон')
    parser.add_argument('--pause', type=float, default=1.6,
                        help='Endpoint silence seconds; allow slow speech, tune with retained audio')
    parser.add_argument('--threshold', type=float, default=100)
    parser.add_argument('--maximum', type=float, default=120)
    parser.add_argument('--timeout', type=float, default=180)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--maximum-pending', type=int, default=32)
    parser.add_argument('--serve', type=int, default=0, help='Optional localhost GET health/events port')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.asr_config.read_text(encoding='utf-8'))
        for field in ('cli', 'model'):
            if not Path(config[field]).is_file():
                raise ValueError('Explicit external Whisper CLI/model unavailable')
        if args.device and not args.listen_lock:
            raise ValueError('Live input requires exact existing singleton lock path')
        if not 0 <= args.serve <= 65535:
            raise ValueError('Invalid localhost port')
        Utterances.validate(args.threshold, args.pause, args.maximum)
        def run():
            session = Session(args.session, config, args.wake, timeout=args.timeout,
                              threads=args.threads, maximum_pending=args.maximum_pending)
            collector = Utterances(session.folder / 'audio', session.event,
                                   args.threshold, args.pause, args.maximum)
            audio = None
            server = None
            try:
                if args.serve:
                    server = serve(session, args.serve)
                if args.replay_wav:
                    audio = wav_blocks(args.replay_wav)
                else:
                    matches = [d for d in devices() if args.device.casefold() in d['name'].casefold()]
                    if len(matches) != 1:
                        raise ValueError('Explicit input absent/ambiguous; no default fallback')
                    audio = capture(matches[0]['index'])
                session.update_health(captureActive=True, replay=bool(args.replay_wav))
                updated = time.monotonic()
                for pcm in audio:
                    if session.error:
                        raise ValueError(session.error)
                    collector.feed(pcm)
                    if time.monotonic() - updated >= 1:
                        session.update_health(captureActive=True, capturedSamples=collector.sample)
                        updated = time.monotonic()
            except BaseException as error:
                session.error = str(error) or type(error).__name__
                raise
            finally:
                try:
                    if audio is not None:
                        audio.close()
                    collector.finish()
                finally:
                    try:
                        session.close()
                    finally:
                        if server:
                            server.shutdown()
                            server.server_close()
            if session.error:
                raise ValueError(session.error)
            print(json.dumps({'status': 'replayed', 'heard': str(session.heard),
                              'records': len(records(session.heard)), 'liveQualified': False}))
        if args.replay_wav:
            run()
        else:
            lock = external(args.listen_lock)
            # Never take over or kill the previous listener, even with a stale PID.
            with locked(lock.parent / 'whole-utterance-listener'):
                with lock.open('x', encoding='utf-8') as stream:
                    owned = {'pid': os.getpid(), 'protocol': 'whole-utterance-v2', 'at': time.time()}
                    json.dump(owned, stream)
                try:
                    run()
                finally:
                    if json.loads(lock.read_text(encoding='utf-8')) == owned:
                        lock.unlink()
    except (OSError, ValueError, KeyError, OverflowError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}, ensure_ascii=False))
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
