"""Operator-owned listener preparation and direct polling. No AI host/game calls."""
import argparse
import ctypes
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .voice_inbox import Inbox, InboxBusy, atomic, locked
from .voice_listener import external


def process_identity(pid):
    """Distinguish a proven absent PID from access/inspection failure."""
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        raise ValueError('Invalid listener PID')
    if os.name != 'nt':
        raise OSError('Live listener management requires Windows')
    from .native import K, identity
    handle = K.OpenProcess(0x1000, False, int(pid))
    if not handle:
        if ctypes.get_last_error() == 87:
            return None
        raise ctypes.WinError(ctypes.get_last_error())
    K.CloseHandle(handle)
    value = identity(pid)
    if not value:
        raise OSError('Cannot inspect live listener identity')
    return value


class Operator:
    def __init__(self, config):
        self.config = dict(config)
        self.thread = str(uuid.UUID(config['threadId']))
        for key in ('runtime', 'listenLock', 'asrConfig'):
            if not Path(config[key]).is_absolute():
                raise ValueError('Operator configuration requires absolute paths')
        self.dialog_seconds = config.get('dialogSeconds', 14400)
        if type(self.dialog_seconds) is not int or not 1 <= self.dialog_seconds <= 14400:
            raise ValueError('Dialog duration must be within1..14400seconds')
        self.root = external(config['runtime'])
        self.lock = external(config['listenLock'])
        self.binding = self.root / 'binding.json'
        self.root.mkdir(parents=True, exist_ok=True)

    def health(self, session, expected=None):
        session = external(session)
        h = json.loads((session / 'health.json').read_text(encoding='utf-8'))
        owner = json.loads(self.lock.read_text(encoding='utf-8'))
        ident = process_identity(owner['pid'])
        if (not ident or owner.get('protocol') != 'whole-utterance-v2'
                or h.get('pid') != ident['pid'] or not h.get('ok')
                or not h.get('captureActive') or h.get('replay')
                or not 0 <= time.time() - h['checkedAt'] <= 5
                or Path(h['heard']).resolve() != session / 'heard.jsonl'):
            raise ValueError('Listener health/identity/queue unavailable or mismatched')
        pinned = expected or owner.get('identity')
        if pinned and ident != pinned:
            raise ValueError('Listener process identity changed')
        if not pinned:
            # Explicit legacy attachment only. Lock time must agree with birth;
            # never attach to a reused/uninspectable PID, never terminate it.
            birth = ident['birth'] / 10000000 - 11644473600
            if not 0 <= owner['at'] - birth <= 10:
                raise ValueError('Legacy listener PID/birth inconsistent')
        return h, ident

    def begin(self, binding, owner_ref, seconds=14400):
        if not owner_ref.strip() or type(seconds) is not int or not 0 <= seconds <= 14400:
            raise ValueError('Direct owner reference and bounded dialog duration required')
        h, _ = self.health(binding['session'], binding['identity'])
        if h.get('operatorThread') != self.thread:
            return {'status': 'legacy_listener_requires_ordinary_address',
                    'note': 'No restart/hot upgrade; a natural addressed phrase opens its gate'}
        request = {'id': uuid.uuid4().hex, 'threadId': self.thread, 'at': time.time(),
                   'ownerRef': owner_ref, 'seconds': seconds}
        atomic(Path(binding['session']) / 'conversation-request.json', request)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            h, _ = self.health(binding['session'], binding['identity'])
            if h.get('conversationControlId') == request['id']:
                return {'status': 'conversation_open' if seconds else 'conversation_closed',
                        'requestId': request['id'], 'microphoneStopped': False}
            time.sleep(.1)
        raise TimeoutError('Conversation control not acknowledged; do not claim open')

    def ensure(self, owner_ref):
        """Start once, or reuse an exact healthy binding; archive only proven dead locks."""
        if not owner_ref.strip():
            raise ValueError('Direct owner game-start reference required')
        with locked(self.root / 'preparation', wait=.25):
            if self.binding.exists():
                binding = json.loads(self.binding.read_text(encoding='utf-8'))
                if binding['threadId'] != self.thread:
                    raise ValueError('Binding belongs to another operator')
                if process_identity(binding['identity']['pid']):
                    h, _ = self.health(binding['session'], binding['identity'])
                    Inbox(binding['inbox'], self.thread, lock_wait=.25).status()
                    return {**binding, 'status': 'reused', 'health': h,
                            'conversation': self.begin(binding, owner_ref, self.dialog_seconds)}
                # Never overwrite the old binding/cursor; it remains evidence.
                prior = self.root / ('binding-ended-' + uuid.uuid4().hex + '.json')
                os.rename(self.binding, prior)
            session, inbox = None, None
            if self.lock.exists():
                before = self.lock.read_bytes()
                owner = json.loads(before)
                live = process_identity(owner['pid'])
                if live:
                    existing = self.config.get('existing')
                    if not existing or existing['pid'] != live['pid']:
                        raise ValueError('Live singleton exists: explicitly bind its exact session/inbox; no takeover')
                    session, inbox = external(existing['session']), external(existing['inbox'])
                    self.health(session)
                    # Do not invent a baseline for a running queue.
                    box = Inbox(inbox, self.thread, lock_wait=.25)
                    state = box.status()
                    if Path(state['heard']).resolve() != session / 'heard.jsonl' or state['schemaVersion'] != 2:
                        raise ValueError('Existing operator inbox/queue mismatch')
                else:
                    with locked(self.lock.parent / 'whole-utterance-listener', wait=.25):
                        if self.lock.read_bytes() != before or process_identity(owner['pid']):
                            raise ValueError('Singleton changed during reconciliation')
                        archive = self.root / ('dead-singleton-' + uuid.uuid4().hex + '.json')
                        os.rename(self.lock, archive)
            if session is None:
                # Any competing start still loses the listener's original shared lock.
                stamp = uuid.uuid4().hex
                session, inbox = self.root / ('session-' + stamp), self.root / ('inbox-' + stamp)
                argv = [sys.executable, '-X', 'utf8', '-m', 'skyrim_autotest.voice_listener',
                        '--asr-config', str(external(self.config['asrConfig'])),
                        '--session', str(session), '--device', self.config['device'],
                        '--listen-lock', str(self.lock), '--wake', self.config.get('wake', 'полигон'),
                        '--operator-thread', self.thread]
                for key, option in [('pause', '--pause'), ('threshold', '--threshold')]:
                    if key in self.config:
                        argv += [option, str(self.config[key])]
                if 'port' in self.config:
                    port = self.config['port']
                    if type(port) is not int or not 0 <= port <= 65535:
                        raise ValueError('Invalid local health port')
                    argv += ['--serve', str(port)]
                with (self.root / ('spawn-' + stamp + '.log')).open('xb') as out:
                    child = subprocess.Popen(argv, cwd=str(Path(__file__).resolve().parents[1]),
                        stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise ValueError('Listener exited; inspect retained spawn log, no blind retry')
                    if (session / 'health.json').exists():
                        h = json.loads((session / 'health.json').read_text(encoding='utf-8'))
                        if h.get('captureActive') and h.get('capturedSamples', 0) > 0:
                            break
                    time.sleep(.1)
                else:
                    raise TimeoutError('Listener startup unconfirmed; preserve singleton/process, no repeat')
                h, ident = self.health(session)
                if ident['pid'] != child.pid:
                    raise ValueError('Spawned listener identity mismatch')
                Inbox(inbox, self.thread, lock_wait=.25).init(session / 'heard.jsonl', 0, buffered=True)
            h, ident = self.health(session)
            binding = {'schemaVersion': 1, 'threadId': self.thread, 'session': str(session),
                       'inbox': str(inbox), 'identity': ident, 'ownerRef': owner_ref,
                       'createdAt': time.time()}
            atomic(self.binding, binding)
            return {**binding, 'status': 'ready', 'health': h,
                    'conversation': self.begin(binding, owner_ref, self.dialog_seconds),
                    'note': 'Capture readiness is separate from fresh ASR/actual operator reply qualification'}

    def poll(self, wait=0):
        if not math.isfinite(wait) or not 0 <= wait <= 30:
            raise ValueError('Poll wait must be finite and within0..30seconds')
        binding = json.loads(self.binding.read_text(encoding='utf-8'))
        if binding['threadId'] != self.thread:
            raise ValueError('Foreign operator binding')
        deadline = time.monotonic() + wait
        box = Inbox(binding['inbox'], self.thread, lock_wait=.25)
        while True:
            self.health(binding['session'], binding['identity'])
            result = box.receive_local()
            if result['status'] == 'delivered' or time.monotonic() >= deadline:
                return {**result, 'inbox': binding['inbox'], 'threadId': self.thread}
            time.sleep(min(.25, max(0, deadline - time.monotonic())))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    ensure = commands.add_parser('ensure')
    ensure.add_argument('--owner-ref', required=True)
    poll = commands.add_parser('poll')
    poll.add_argument('--wait', type=float, default=0)
    args = parser.parse_args(argv)
    try:
        op = Operator(json.loads(args.config.read_text(encoding='utf-8')))
        result = op.ensure(args.owner_ref) if args.command == 'ensure' else op.poll(args.wait)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except InboxBusy as error:
        print(json.dumps({'status': 'busy', 'reason': str(error), 'retryable': True}))
        return 3
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
