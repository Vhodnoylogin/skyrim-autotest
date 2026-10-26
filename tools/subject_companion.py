"""Bounded external subject sequencer transport for an unchanged owned RC6 run.

The pinned origin owns assertions. This client owns only exact-target delivery,
durable raw evidence and deadline enforcement. It never starts/stops a game.
"""
from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import importlib
import importlib.machinery
import json
import math
import multiprocessing
import os
from pathlib import Path
import re
import sys
import time
import traceback
import types
import uuid

MAX_JSON = 32 * 1024 * 1024
MAX_ARTIFACT = 16 * 1024 * 1024
MAX_STEPS = 128 * 1024 * 1024
MAX_COMMANDS = 2048
STATE_READ_SECONDS = .75
STATE_READ_ATTEMPTS = 16
OUTCOMES = {'passed': 'passed', 'mismatch': 'failed', 'unavailable': 'unavailable', 'not_run': 'not_run'}


class CompanionError(RuntimeError):
    pass


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def decoded(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise CompanionError('Duplicate JSON field')
            value[key] = item
        return value

    def invalid(_):
        raise CompanionError('Nonfinite JSON token')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def absolute(value, label, external=True):
    if not isinstance(value, (str, Path)) or not Path(value).is_absolute():
        raise CompanionError(label + ' must be an absolute path')
    path = Path(value)
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if item.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise CompanionError(label + ' refuses symlink/reparse ancestors')
    path = path.resolve()
    if external and any((item / '.git').exists() for item in (path, *path.parents)):
        raise CompanionError(label + ' must be outside Git')
    return path


def read_bytes(path, maximum=MAX_JSON):
    absolute(path, 'input')
    with Path(path).open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise CompanionError('Input exceeds its explicit size bound')
    return raw


def pinned(path, sha256, maximum=MAX_JSON):
    path = absolute(path, 'pinned input')
    if not isinstance(sha256, str) or not re.fullmatch('[0-9a-f]{64}', sha256):
        raise CompanionError('Pinned input requires lowercase SHA256')
    raw = read_bytes(path, maximum)
    if digest(raw) != sha256:
        raise CompanionError('Pinned input bytes changed')
    return path, raw


def identity(value):
    if isinstance(value, str):
        value = decoded(value.encode('utf-8'))
    if (type(value) is not dict or set(value) != {'pid', 'birth', 'path'} or
            type(value['pid']) is not int or not 0 < value['pid'] < 2**32 or
            type(value['birth']) is not int or not 0 < value['birth'] < 2**64):
        raise CompanionError('Exact process PID/birth/path identity required')
    result = dict(value)
    result['path'] = str(absolute(value['path'], 'process executable', external=False))
    return result


def exclusive(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def load_backend(executor, inventory):
    """Use a private package namespace; never reuse the caller's module cache."""
    alias = '_subject_rc6_' + uuid.uuid4().hex
    package = types.ModuleType(alias)
    package.__path__ = [str(executor / 'skyrim_autotest')]
    package.__spec__ = importlib.machinery.ModuleSpec(alias, loader=None, is_package=True)
    sys.modules[alias] = package
    previous = sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True  # Never add caches to the frozen runtime.
        modules = [importlib.import_module(alias + '.' + name)
                   for name in ('command_bus_http', 'native', 'runner_monitor')]
    finally:
        sys.dont_write_bytecode = previous
    for name, module in list(sys.modules.items()):
        if name.startswith(alias + '.'):
            path = Path(module.__file__).resolve()
            if (not path.is_relative_to(executor / 'skyrim_autotest') or
                    str(path) not in inventory or digest(read_bytes(path)) != inventory[str(path)]):
                raise CompanionError('Imported RC6 module is missing or differs from the pinned inventory')
    return types.SimpleNamespace(client=modules[0].CommandHTTPClient,
                                 alive=modules[1].alive, heartbeat=modules[2].read,
                                 process_identity=modules[1].identity)


def sequencer_worker(connection, path, expected_sha256):
    """Only this retained child executes pinned origin code; no game lifecycle."""
    sys.dont_write_bytecode = True
    try:
        path, raw = pinned(path, expected_sha256)
        namespace = {'__name__': '_pinned_subject_sequencer', '__file__': str(path)}
        exec(compile(raw, str(path), 'exec'), namespace)

        def callback(kind, value):
            raw = encoded({'kind': kind, 'value': value})
            if len(raw) > MAX_JSON:
                raise CompanionError('Sequencer callback exceeds its size bound')
            connection.send_bytes(raw)
            reply = decoded(connection.recv_bytes(MAX_JSON))
            if reply.get('ok') is not True:
                raise CompanionError('Companion callback refused: ' + str(reply.get('error', 'unavailable')))
            return reply.get('value')

        result = namespace['run'](lambda value: callback('exchange', value),
                                  lambda value: callback('emit', value))
        connection.send_bytes(encoded({'kind': 'return', 'value': result}))
    except BaseException as error:
        try:
            connection.send_bytes(encoded({'kind': 'error', 'errorType': type(error).__name__, 'error': str(error)}))
        except (OSError, EOFError):
            pass
    finally:
        connection.close()


class Companion:
    def __init__(self, args, *, backend=None, clock=time.monotonic, wall=time.time, pause=time.sleep):
        self.clock, self.wall, self.pause = clock, wall, pause
        self.executor = absolute(args.executor, 'executor')
        self.runtime = absolute(args.runtime, 'runtime')
        self.channel = absolute(args.channel_config, 'channel configuration')
        self.output = absolute(args.output, 'report')
        self.worker, self.game = identity(args.worker_identity), identity(args.game_identity)
        self.order_id, self.attempt_id = args.order_id, args.attempt_id
        for value in (self.order_id, self.attempt_id):
            if not isinstance(value, str) or not 1 <= len(value) <= 200 or any(ord(c) < 33 for c in value):
                raise CompanionError('Explicit bounded order/attempt identifiers required')
        if not (self.executor / 'run.py').is_file():
            raise CompanionError('Executor must be the frozen portable root')
        if any(path.is_relative_to(self.executor) for path in (self.runtime, self.channel, self.output)):
            raise CompanionError('Runtime/channel/report must remain outside the frozen executor')
        manifest_path, manifest_raw = pinned(args.executor_manifest, args.executor_manifest_sha256)
        manifest = decoded(manifest_raw)
        if (type(manifest) is not dict or set(manifest) != {'schemaVersion', 'files'} or
                manifest['schemaVersion'] != 1 or not isinstance(manifest['files'], list) or
                not 4 <= len(manifest['files']) <= 10000):
            raise CompanionError('Executor inventory requires schemaVersion1 and bounded files array')
        self.inventory = {}
        for item in manifest['files']:
            if type(item) is not dict or set(item) != {'path', 'sha256'}:
                raise CompanionError('Executor inventory needs exact path/SHA256 pairs')
            path, _ = pinned(item['path'], item['sha256'])
            if not path.is_relative_to(self.executor) or str(path) in self.inventory:
                raise CompanionError('Executor inventory has duplicate or foreign paths')
            self.inventory[str(path)] = item['sha256']
        for name in ('command_bus.py', 'command_bus_http.py', 'native.py', 'runner_monitor.py'):
            if str(self.executor / 'skyrim_autotest' / name) not in self.inventory:
                raise CompanionError('Executor inventory lacks a required client module')
        self.plan_path, plan_raw = pinned(args.plan, args.plan_sha256)
        self.sequencer_path, _ = pinned(args.sequencer, args.sequencer_sha256)
        plan = decoded(plan_raw)
        if not isinstance(plan, dict):
            raise CompanionError('Pinned execution plan must be an object')
        cases, key = (plan['checks'], 'name') if 'checks' in plan else (plan.get('cases'), 'id')
        if (not isinstance(cases, list) or not 1 <= len(cases) <= 1000 or
                any(type(row) is not dict or not isinstance(row.get(key), str) or
                    not re.fullmatch('[A-Za-z0-9_.-]{1,160}', row[key]) or
                    (key == 'name' and row.get('role') != 'subject') for row in cases)):
            raise CompanionError('Pinned plan requires bounded subject checks.name (or cases.id)')
        self.case_ids = [row[key] for row in cases]
        if 'checks' in plan and 'cases' in plan and [row.get('id') for row in plan['cases']] != self.case_ids:
            raise CompanionError('Pinned plan has conflicting case inventories')
        if len(set(self.case_ids)) != len(self.case_ids):
            raise CompanionError('Pinned plan has duplicate case ids')
        bounds = plan.get('bounds', {})
        self.expected_cell = plan.get('fixture', {}).get('cell')
        if self.expected_cell is not None and not isinstance(self.expected_cell, str):
            raise CompanionError('Declared initial cell must be a string')
        maximum = bounds.get('maximumSeconds')
        if type(maximum) not in (int, float) or not math.isfinite(maximum) or not 0 < maximum <= 14400:
            raise CompanionError('Pinned plan needs finite maximumSeconds in (0,14400]')
        self.maximum = min(maximum, args.maximum_seconds) if args.maximum_seconds is not None else maximum
        if not math.isfinite(self.maximum) or not 0 < self.maximum <= maximum:
            raise CompanionError('Client deadline cannot extend the pinned plan')
        self.max_commands = bounds.get('maximumCommands', MAX_COMMANDS)
        if type(self.max_commands) is not int or not 1 <= self.max_commands <= MAX_COMMANDS:
            raise CompanionError('maximumCommands must be an integer in 1..2048')
        self.wait_seconds = args.wait_seconds
        if not math.isfinite(self.wait_seconds) or not 0 < self.wait_seconds <= 360:
            raise CompanionError('waitSeconds must be finite in (0,360]')
        self.backend = backend or load_backend(self.executor, self.inventory)
        self.client = self.backend.client(self.channel, timeout=5)
        self.folder = self.output.parent / 'evidence'
        self.events_path = self.output.parent / 'events.jsonl'
        if self.output.exists() or self.folder.exists() or self.events_path.exists():
            raise CompanionError('Companion output exists; reconnect/reset/replay is forbidden')
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.folder.mkdir()
        exclusive(self.events_path, b'')
        self.report = {'schemaVersion': 1, 'kind': 'subject-companion-report', 'orderId': self.order_id,
            'attemptId': self.attempt_id, 'worker': self.worker, 'game': self.game,
            'plan': {'path': str(self.plan_path), 'sha256': args.plan_sha256},
            'sequencer': {'path': str(self.sequencer_path), 'sha256': args.sequencer_sha256},
            'executorManifest': {'path': str(manifest_path), 'sha256': args.executor_manifest_sha256},
            'transport': {'path': str(Path(__file__).resolve()), 'sha256': digest(Path(__file__).read_bytes())},
            'caseIds': self.case_ids, 'cases': [{'id': item, 'status': 'not_run', 'commandIds': [], 'evidence': []}
                                             for item in self.case_ids],
            'subjectStart': None, 'subjectStarted': False, 'actions': [], 'evidence': [], 'done': False,
            'completed': False, 'status': 'waiting', 'uncertain': False, 'startedAt': self.wall(),
            'gameLifecycleOwned': False, 'audioOpened': False, 'actionsRetried': False}
        self.report_hash = None
        self.event_bytes, self.event_hash = 0, digest(b'')
        self.event_hasher = hashlib.sha256()
        self.event_stat = self.events_path.stat()
        self.serial, self.cursor, self.measurement_sequence = 0, 0, 0
        self.active_case, self.pending, self.current_action = None, None, None
        self.started_cases, self.finished_cases, self.assertions = set(), set(), {}
        self.commands, self.bus_events = {}, []
        self.poisoned, self.finish_attempted, self.finish_completed = False, False, False
        self.state_path, self.run_dir, self.end = None, None, None
        self.save()

    def retain(self, label, value=None, raw=None):
        self.serial += 1
        raw = encoded(value) if raw is None else raw
        if len(raw) > MAX_JSON:
            raise CompanionError('Retained evidence exceeds its explicit size bound')
        path = self.folder / (f'{self.serial:06d}-' + label + '.json')
        exclusive(path, raw)
        pin = {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}
        self.report['evidence'].append(pin)
        return pin

    def event(self, kind, **fields):
        absolute(self.events_path, 'event evidence')
        current = self.events_path.stat()
        previous = self.event_stat
        if ((current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) !=
                (previous.st_dev, previous.st_ino, previous.st_size, previous.st_mtime_ns)):
            raise CompanionError('Companion event evidence changed externally')
        raw = encoded({'recordedAt': self.wall(), 'kind': kind, **fields}) + b'\n'
        if self.event_bytes + len(raw) > MAX_STEPS:
            raise CompanionError('Companion event evidence bound exhausted')
        with self.events_path.open('ab') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        self.event_bytes += len(raw)
        self.event_hasher.update(raw)
        self.event_hash = self.event_hasher.hexdigest()
        self.event_stat = self.events_path.stat()

    def save(self):
        if self.report_hash is not None and digest(read_bytes(self.output)) != self.report_hash:
            raise CompanionError('Companion report changed externally')
        self.report['events'] = {'path': str(self.events_path), 'sha256': self.event_hash, 'bytes': self.event_bytes}
        raw = encoded(self.report)
        if self.report_hash is None:
            exclusive(self.output, raw)
        else:
            temporary = self.output.with_name(self.output.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                exclusive(temporary, raw)
                os.replace(temporary, self.output)
            finally:
                temporary.unlink(missing_ok=True)
        self.report_hash = digest(raw)

    def verify_inventory(self):
        for path, sha256 in self.inventory.items():
            if digest(read_bytes(Path(path))) != sha256:
                raise CompanionError('Frozen executor bytes changed')

    def read_live_state(self, path, deadline=None):
        """Retry only an owned mutable state read, never an action or pinned input."""
        path = Path(path)
        if path.name != 'state.json' or path.parent.parent != self.runtime / 'runs':
            raise CompanionError('Live-state read requires the exact runtime run path')
        end = self.clock() + STATE_READ_SECONDS
        for bound in (deadline, self.end):
            if bound is not None:
                end = min(end, bound)
        last_error = None
        for attempt in range(1, STATE_READ_ATTEMPTS + 1):
            if self.clock() >= end:
                if last_error is not None:
                    self.event('live-state-read-exhausted', operation='read-live-state', path=str(path),
                        attempts=attempt - 1, errno=last_error.errno,
                        winerror=getattr(last_error, 'winerror', None), diagnostic=str(last_error),
                        traceback=''.join(traceback.format_exception(last_error)))
                    raise last_error
                raise CompanionError('Live-state read deadline expired; no continuation')
            try:
                value = decoded(read_bytes(path))
            except PermissionError as error:
                if error.errno != errno.EACCES and getattr(error, 'winerror', None) not in (5, 32, 33):
                    raise
                last_error = error
                remaining = end - self.clock()
                exhausted = attempt == STATE_READ_ATTEMPTS or remaining <= 0
                self.event('live-state-read-denied', operation='read-live-state', path=str(path),
                    errno=error.errno, winerror=getattr(error, 'winerror', None), attempt=attempt,
                    exhausted=exhausted, diagnostic=str(error), traceback=traceback.format_exc())
                if exhausted:
                    raise
                self.pause(min(.05, remaining))
            else:
                if self.clock() >= end:
                    raise CompanionError('Live-state read deadline expired; no continuation')
                if last_error is not None:
                    self.event('live-state-read-recovered', operation='read-live-state', path=str(path),
                               attempt=attempt)
                if self.clock() >= end:
                    raise CompanionError('Live-state read deadline expired; no continuation')
                return value
        raise last_error  # The finite attempt bound never resets an action deadline.

    def wait_ready(self):
        end = self.clock() + self.wait_seconds
        while self.clock() < end:
            matches = []
            for path in (self.runtime / 'runs').glob('*/state.json'):
                value = self.read_live_state(path, deadline=end)
                if isinstance(value, dict) and value.get('order', {}).get('id') == self.order_id:
                    matches.append((path, value))
            if len(matches) > 1:
                raise CompanionError('Multiple native runs match this exact order; no adoption')
            if matches:
                path, state = matches[0]
                if state.get('done') or state.get('result') in ('failed', 'blocked'):
                    raise CompanionError('Matching native run already ended')
                if state.get('interactiveSession', {}).get('ready') is True:
                    if (not isinstance(state.get('id'), str) or path.parent.name != state['id'] or
                            not re.fullmatch('[A-Za-z0-9_.-]{1,160}', state['id'])):
                        raise CompanionError('Native run id differs from its exact runtime directory')
                    self.state_path, self.run_dir, self.run_id = path, path.parent, state['id']
                    self.session_id = 'game-' + self.run_id
                    self.binding = {'provider': 'skyrim-autotest', 'conversationId': self.run_id,
                                    'agentId': 'owned-game-executor'}
                    self.bootstrap = copy.deepcopy(state.get('gameplayBootstrap'))
                    self.executor_hashes = copy.deepcopy(state.get('executorHashes'))
                    self.check_state(state, deadline=end)
                    remaining = state['deadline'] - self.wall() - 5
                    self.end = self.clock() + min(self.maximum, remaining)
                    if self.end <= self.clock():
                        raise CompanionError('Original interactive deadline has expired')
                    self.verify_inventory()
                    status = self.client.call('status', {'sessionId': self.session_id})
                    self.retain('initial-channel-status', status)
                    if status.get('binding') != self.binding or status.get('commands') != {}:
                        raise CompanionError('Interactive channel is not exact, fresh and empty')
                    if self.clock() >= min(end, self.end):
                        raise CompanionError('Original interactive startup deadline expired; no continuation')
                    claim = self.run_dir / 'subject-companion.claim.json'
                    exclusive(claim, encoded({'orderId': self.order_id, 'attemptId': self.attempt_id,
                        'runId': self.run_id, 'report': str(self.output), 'transport': self.report['transport']}))
                    self.report.update(runId=self.run_id, sessionId=self.session_id, binding=self.binding,
                        statePath=str(path), status='running', readyState=self.retain('ready-state', state))
                    self.poll()
                    self.save()
                    return
            self.pause(.1)
        raise CompanionError('No unique matching owned interactive run became ready within the wait bound')

    def check_state(self, state=None, finishing=False, deadline=None):
        state = self.read_live_state(self.state_path, deadline=deadline) if state is None else state
        metadata = state.get('interactiveSession', {})
        configuration = state.get('configuration', {})
        settings = configuration.get('interactive_session', {})
        if (state.get('id') != self.run_id or state.get('order', {}).get('id') != self.order_id or
                state.get('runner') != self.worker or state.get('game') != self.game or
                metadata.get('sessionId') != self.session_id or metadata.get('binding') != self.binding or
                settings.get('sourceId') != 'operator.actions' or
                absolute(settings.get('channelConfig', ''), 'native channel') != self.channel or
                state.get('gameplayBootstrap') != self.bootstrap or not isinstance(self.bootstrap, dict) or
                self.bootstrap.get('completed') is not True or state.get('executorHashes') != self.executor_hashes or
                configuration.get('game_edition') != 'se' or
                not any(row.get('role') == 'game' and row.get('identity') == self.game for row in state.get('owned', [])) or
                (self.expected_cell is not None and str(self.bootstrap.get('cell', '')).casefold() != self.expected_cell.casefold())):
            raise CompanionError('Exact owned run/bootstrap/session/world pins changed')
        if (not finishing and (state.get('done') or state.get('phase') != 'interactive-session' or
                               metadata.get('ready') is not True)):
            raise CompanionError('Native interactive window ended or changed')
        maximum = settings.get('maximumSeconds')
        native_deadline = state.get('deadline')
        if (type(maximum) is not int or not 1 <= maximum <= 14400 or maximum != metadata.get('maximumSeconds') or
                type(native_deadline) not in (int, float) or not math.isfinite(native_deadline) or
                (not finishing and native_deadline <= self.wall())):
            raise CompanionError('Original finite interactive deadline is unavailable')
        if (not isinstance(self.executor_hashes, dict) or not self.executor_hashes or
                any(self.inventory.get(str(self.executor / 'skyrim_autotest' / name)) != sha256
                    for name, sha256 in self.executor_hashes.items())):
            raise CompanionError('Native executor hashes differ from the frozen inventory')
        # Once finish is submitted, only its durable completion is read. The
        # owned runner may already be closing the game or exiting normally.
        if not finishing:
            if not self.backend.alive(self.worker) or not self.backend.alive(self.game):
                raise CompanionError('Owned worker/game identity is no longer alive')
            pulse = self.backend.heartbeat(self.run_dir, state)
            if (not isinstance(pulse, dict) or pulse.get('healthy') is not True or
                    type(pulse.get('at')) not in (int, float) or not math.isfinite(pulse['at']) or
                    not 0 <= self.wall() - pulse['at'] <= 10):
                raise CompanionError('Exact worker heartbeat is unavailable/stale')
        if self.end is not None and self.clock() >= self.end:
            raise CompanionError('Companion shared deadline expired; no continuation')
        if deadline is not None and self.clock() >= deadline:
            raise CompanionError('Exact completion deadline expired; never retry or reconnect')
        return state

    def poll(self, finishing=False, deadline=None):
        self.check_state(finishing=finishing, deadline=deadline)
        response = self.client.call('events', {'sessionId': self.session_id, 'afterId': self.cursor, 'limit': 500})
        terminal = None
        for event in response.get('events', []):
            if (type(event) is not dict or type(event.get('id')) is not int or event['id'] <= self.cursor or
                    event.get('sessionId') != self.session_id or type(event.get('data')) is not dict):
                raise CompanionError('Channel events are not ordered/exact-session records')
            self.cursor = event['id']
            kind, command = event.get('type'), event['data'].get('commandId')
            if kind == 'command.received' and command not in self.commands:
                raise CompanionError('Another producer used this owned machine session')
            if kind in ('command.uncertain', 'command.reconciled'):
                terminal = 'Uncertain/reconciled delivery is terminal; no replay'
            if kind == 'session.bound' and event['data'].get('binding') != self.binding:
                raise CompanionError('Channel binding changed')
            self.bus_events.append(event)
            self.event('command-event', event=event)
            if kind == 'command.delivered' and command in self.commands:
                self.delivered(self.commands[command])
        if response.get('nextAfterId') != self.cursor:
            raise CompanionError('Channel cursor differs from its ordered event stream')
        if terminal:
            for action in self.commands.values():
                if self.matching_event(action['commandId'], 'command.delivered'):
                    self.delivered(action)
            raise CompanionError(terminal)

    def case(self, case_id):
        return next(row for row in self.report['cases'] if row['id'] == case_id)

    def emit(self, record):
        if type(record) is not dict:
            raise CompanionError('Origin emit requires one JSON object')
        record = decoded(encoded(record))
        kind, case_id = record.get('kind'), record.get('caseId')
        if case_id is not None and case_id not in self.case_ids:
            raise CompanionError('Origin event names an undeclared case')
        evidence = self.retain('origin-emit', record)
        self.event('origin', record=record, evidence=evidence)
        if case_id is not None:
            self.case(case_id)['evidence'].append(evidence)
        if kind == 'check-start':
            if (record.get('role') != 'subject' or case_id is None or case_id in self.started_cases or
                    self.active_case is not None or self.pending is not None or
                    case_id != next((item for item in self.case_ids if item not in self.finished_cases), None)):
                raise CompanionError('Case start is duplicated, out of order or not a declared subject case')
            self.started_cases.add(case_id)
            self.active_case = case_id
        elif kind == 'measurement' and record.get('delivery') == 'intent':
            sequence = record.get('sequence')
            envelope = record.get('request')
            if (self.pending is not None or type(sequence) is not int or sequence != self.measurement_sequence + 1 or
                    sequence > self.max_commands or type(envelope) is not dict or
                    case_id != self.active_case or (case_id is None and envelope.get('operation') != 'finish')):
                raise CompanionError('Measurement intent lacks one current case/sequence/envelope')
            self.measurement_sequence = sequence
            self.pending = copy.deepcopy(record)
        elif kind == 'measurement':
            action = next((row for row in self.report['actions'] if row['sequence'] == record.get('sequence')), None)
            if (record.get('delivery') not in ('completed', 'unavailable') or
                    record.get('sequence') != self.measurement_sequence or self.pending is not None or
                    (action is not None and (action['caseId'] != case_id or action['envelope'] != record.get('request')))):
                raise CompanionError('Measurement result differs from its exact origin action')
            if record['delivery'] == 'completed' and (action is None or action['status'] != 'completed' or
                    'rawResult' not in record or decoded(read_bytes(Path(action['rawResult']['path']))) != record['rawResult']):
                raise CompanionError('Origin measurement differs from its verified raw result')
        elif kind == 'assertion':
            if case_id != self.active_case or case_id is None or record.get('outcome') not in ('passed', 'mismatch'):
                raise CompanionError('Assertion lacks the active declared case/outcome')
            self.assertions.setdefault(case_id, []).append(record['outcome'])
        elif kind == 'check-result':
            outcome = record.get('outcome')
            if case_id is None or case_id in self.finished_cases or outcome not in OUTCOMES or self.pending is not None:
                raise CompanionError('Case result is duplicated or invalid')
            if outcome != 'not_run' and case_id != self.active_case:
                raise CompanionError('Completed case lacks its preceding origin start')
            actions = [row for row in self.report['actions'] if row['caseId'] == case_id]
            assertions = self.assertions.get(case_id, [])
            if outcome == 'passed' and (not actions or any(row['status'] != 'completed' for row in actions) or
                                        not assertions or any(item != 'passed' for item in assertions)):
                raise CompanionError('Passed case requires pinned assertions and actual completed calls')
            if outcome == 'mismatch' and 'mismatch' not in assertions:
                raise CompanionError('Failed case requires its pinned mismatch assertion')
            if outcome == 'not_run' and (case_id in self.started_cases or actions):
                raise CompanionError('An attempted case cannot be relabeled not_run')
            self.case(case_id).update(status=OUTCOMES[outcome], reason=str(record.get('detail', '')))
            self.finished_cases.add(case_id)
            if self.active_case == case_id:
                self.active_case = None
        self.save()

    def matching_event(self, command_id, kind):
        return next((event for event in self.bus_events if event['type'] == kind and
                     event['data'].get('commandId') == command_id), None)

    def delivered(self, action):
        if action.get('deliveredEvidence'):
            return True
        raw = read_bytes(self.run_dir / 'steps.jsonl', MAX_STEPS)
        matches = []
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b'\n'):
                continue  # A writer may still be appending this one row.
            row = decoded(line)
            if row.get('kind') == 'interactive-action-delivered' and row.get('commandId') == action['commandId']:
                matches.append((row, line))
        if len(matches) > 1:
            raise CompanionError('Duplicate native action-delivered rows')
        if not matches:
            return False
        row, line = matches[0]
        if row.get('request') != action['envelope']:
            raise CompanionError('Native delivered request differs from origin intent')
        pin = self.retain('native-action-delivered', raw=line)
        action.update(status='delivered', deliveredEvidence=pin)
        self.event('action-delivered', caseId=action['caseId'], commandId=action['commandId'],
                   sourceEventId=action['sourceEventId'], executorLog=row, evidence=pin)
        if action['caseId'] is not None:
            self.case(action['caseId'])['evidence'].append(pin)
            if self.report['subjectStart'] is None:
                if action['caseId'] != self.case_ids[0]:
                    raise CompanionError('First factual delivery is not the first declared source case')
                self.report['subjectStart'] = {key: action[key] for key in
                    ('caseId', 'commandId', 'sourceEventId', 'deliveredEvidence')}
                self.report['subjectStarted'] = True
        self.save()
        return True

    def unwrap(self, command_id, value, action, deadline=None):
        if isinstance(value, dict) and value.get('outcome') == 'rejected':
            raise CompanionError('Native action was rejected; no tool result/assertion is available')
        if isinstance(value, dict) and value.get('outcome') == 'result-recorded':
            evidence = value.get('evidence', {})
            expected = self.run_dir / 'interactive-results' / (command_id + '.json')
            if (set(value) != {'outcome', 'evidence'} or type(evidence) is not dict or
                    set(evidence) != {'path', 'sha256', 'bytes', 'format'} or evidence.get('format') != 'json' or
                    type(evidence.get('bytes')) is not int or not 0 < evidence['bytes'] <= MAX_ARTIFACT or
                    absolute(evidence.get('path', ''), 'raw result artifact') != expected):
                raise CompanionError('Raw result artifact is outside the exact owned run/command path')
            raw = read_bytes(expected, MAX_ARTIFACT)
            if len(raw) != evidence['bytes'] or digest(raw) != evidence['sha256']:
                raise CompanionError('Raw result artifact bytes/hash differ from the completion receipt')
            state = self.read_live_state(self.state_path, deadline=deadline)
            self.check_state(state=state, deadline=deadline)
            if dict(evidence, commandId=command_id) not in state.get('interactiveArtifacts', []):
                raise CompanionError('Raw result artifact is absent from the exact run registry')
            action['artifactCopy'] = self.retain('verified-native-artifact', raw=raw)
            action['artifact'] = dict(evidence)
            value = decoded(raw)
        action['rawResult'] = self.retain('raw-result', value)
        return value

    def exchange(self, envelope):
        if self.poisoned or self.finish_attempted:
            raise CompanionError('Transport already stopped/finished; no replay or further commands')
        try:
            self.check_state()
            envelope = decoded(encoded(envelope))
            if (type(envelope) is not dict or type(envelope.get('schemaVersion')) is not int or
                    envelope['schemaVersion'] != 1 or envelope.get('operation') not in ('tool', 'binding', 'fixture-create', 'finish')):
                raise CompanionError('Exchange requires an existing schema1 RC6 machine envelope')
            if self.pending is None or envelope != self.pending['request']:
                raise CompanionError('Exchange differs from the durable origin measurement intent')
            sequence, case_id = self.pending['sequence'], self.pending.get('caseId')
            self.pending = None
            finishing = envelope.get('operation') == 'finish'
            if finishing:
                if set(envelope) != {'schemaVersion', 'operation'} or envelope.get('schemaVersion') != 1:
                    raise CompanionError('Finish must use its exact existing RC6 envelope')
                self.finish_attempted = True
            else:
                timeout = envelope.get('timeoutSeconds')
                if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 30:
                    raise CompanionError('Origin action timeout must be finite in (0,30]')
                if timeout > self.end - self.clock():
                    raise CompanionError('Origin action deadline does not fit the remaining original window')
            source_event_id = 'subject-' + digest(encoded([self.order_id, self.attempt_id, self.run_id]))[:32] + ':' + str(sequence)
            request = {'sessionId': self.session_id, 'expectedBinding': self.binding, 'sourceId': 'operator.actions',
                       'sourceEventId': source_event_id, 'kind': 'text', 'text': encoded(envelope).decode('utf-8'),
                       'metadata': {'subjectOrder': self.order_id, 'attemptId': self.attempt_id,
                                    'caseId': case_id, 'sequence': sequence}}
            action = {'sequence': sequence, 'caseId': case_id, 'sourceEventId': source_event_id,
                      'envelope': envelope, 'status': 'intent', 'request': self.retain('request-intent', request)}
            self.current_action = action
            self.report['actions'].append(action)
            self.event('request-intent', sequence=sequence, caseId=case_id, sourceEventId=source_event_id,
                       envelope=envelope, request=action['request'])
            self.report['uncertain'] = True  # Durable before the one HTTP ingress attempt.
            self.save()
            ack = self.client.call('submit', request)  # Never client.submit(): no retry helper.
            action['ack'] = self.retain('ingress-ack', ack)
            command = ack.get('command', {})
            if (ack.get('acknowledged') is not True or ack.get('duplicate') is not False or
                    not isinstance(command.get('id'), str) or not re.fullmatch('[0-9a-f]{32}', command['id']) or
                    command.get('binding') != self.binding or any(command.get(key) != value
                        for key, value in request.items() if key != 'expectedBinding')):
                raise CompanionError('Ingress ACK differs from this new exact-target request')
            command_id = command['id']
            if command_id in self.commands:
                raise CompanionError('Duplicate command UUID in this attempt')
            action.update(commandId=command_id, status='received')
            self.commands[command_id] = action
            if case_id is not None:
                self.case(case_id)['commandIds'].append(command_id)
                self.case(case_id)['evidence'].extend([action['request'], action['ack']])
            self.save()
            end = min(self.end, self.clock() + (5 if finishing else envelope['timeoutSeconds'] + 5))
            while self.clock() < end:
                self.poll(finishing=finishing, deadline=end)
                delivered = self.matching_event(command_id, 'command.delivered')
                if delivered is not None:
                    self.delivered(action)
                complete = self.matching_event(command_id, 'command.completed')
                if complete is not None:
                    action['completion'] = self.retain('command-completed', complete)
                    if delivered is None:
                        raise CompanionError('Completion lacks distinct durable delivery')
                    result = self.unwrap(command_id, complete['data']['result'], action, deadline=end)
                    if not self.delivered(action):
                        raise CompanionError('Completion lacks exact native action-delivered evidence')
                    if self.clock() >= end:
                        raise CompanionError('Exact completion deadline expired; never retry or reconnect')
                    action['status'] = 'completed'
                    if case_id is not None:
                        self.case(case_id)['evidence'].extend([action['completion'], action['rawResult']])
                    self.report['uncertain'] = False
                    if finishing:
                        if result != {'outcome': 'owner-finished'}:
                            raise CompanionError('Finish lacks its exact native completion')
                        self.finish_completed = True
                    self.current_action = None
                    self.save()
                    return result
                self.pause(.05)
            raise CompanionError('Exact completion deadline expired; never retry or reconnect')
        except BaseException:
            self.poisoned = True
            if self.current_action is not None:
                # One bounded read can retain an actual factual start after a
                # lost ingress ACK. It never supplies a completion or replays
                # the request, and uncertainty remains terminal.
                action = self.current_action
                if 'commandId' not in action:
                    try:
                        response = self.client.call('events', {'sessionId': self.session_id,
                            'afterId': self.cursor, 'limit': 500})
                        self.retain('lost-ack-event-observation', response)
                        matches = [event for event in response.get('events', []) if
                            event.get('sessionId') == self.session_id and event.get('type') == 'command.received' and
                            event.get('data', {}).get('sourceId') == 'operator.actions' and
                            event.get('data', {}).get('sourceEventId') == action['sourceEventId']]
                        if len(matches) == 1:
                            command_id = matches[0]['data']['commandId']
                            if not isinstance(command_id, str) or not re.fullmatch('[0-9a-f]{32}', command_id):
                                raise CompanionError('Lost-ACK observation has invalid command identity')
                            action['commandId'] = command_id
                            self.commands[command_id] = action
                            if action['caseId'] is not None:
                                self.case(action['caseId'])['commandIds'].append(command_id)
                            self.delivered(action)
                    except Exception:
                        pass  # Diagnostic only; the original unknown outcome wins.
                self.current_action['status'] = 'uncertain'
                self.report['uncertain'] = True
            self.save()
            raise

    def execute(self):
        self.wait_ready()
        parent, child = multiprocessing.get_context('spawn').Pipe()
        process = multiprocessing.get_context('spawn').Process(target=sequencer_worker,
            args=(child, str(self.sequencer_path), self.report['sequencer']['sha256']))
        self.report['sequencerProcess'] = {'pid': None, 'identity': None, 'returnCode': None, 'stoppedByClient': False}
        returned, started = False, False
        try:
            process.start()
            started = True
            child.close()
            child_identity = self.backend.process_identity(process.pid)
            self.report['sequencerProcess'].update(pid=process.pid, identity=child_identity)
            if child_identity is None or identity(child_identity)['pid'] != process.pid:
                raise CompanionError('Exact owned sequencer child identity is unavailable')
            self.save()
            while self.clock() < self.end:
                self.check_state(finishing=self.finish_completed)
                if parent.poll(.1):
                    message = decoded(parent.recv_bytes(MAX_JSON))
                    kind = message.get('kind')
                    if kind == 'return':
                        if type(message.get('value')) is not dict:
                            raise CompanionError('Pinned sequencer must return its JSON result object')
                        self.report['originResult'] = self.retain('origin-return', message.get('value'))
                        returned = True
                        break
                    if kind == 'error':
                        raise CompanionError('Pinned sequencer stopped: ' + str(message.get('error')))
                    if kind not in ('emit', 'exchange') or set(message) != {'kind', 'value'}:
                        raise CompanionError('Invalid sequencer callback protocol')
                    try:
                        result = self.emit(message['value']) if kind == 'emit' else self.exchange(message['value'])
                        parent.send_bytes(encoded({'ok': True, 'value': result}))
                    except BaseException as error:
                        # Allow the pinned origin to emit its unavailable/not_run
                        # outcomes, but never allow another exchange after failure.
                        self.poisoned = True
                        parent.send_bytes(encoded({'ok': False, 'error': str(error)}))
                elif not process.is_alive():
                    raise CompanionError('Sequencer exited without its durable return record')
            if (not returned or self.poisoned or not self.finish_completed or self.pending is not None or
                    self.finished_cases != set(self.case_ids)):
                raise CompanionError('Sequencer/transport did not finish every declared outcome and known lifecycle')
            self.verify_inventory()
            pinned(self.plan_path, self.report['plan']['sha256'])
            pinned(self.sequencer_path, self.report['sequencer']['sha256'])
            if digest(read_bytes(self.events_path, MAX_STEPS)) != self.event_hash:
                raise CompanionError('Event evidence differs from its complete append history')
            self.report.update(status='completed', completed=True)
        except BaseException as error:
            self.report.update(status='stopped', reason=str(error), errorType=type(error).__name__)
        finally:
            parent.close()
            child.close()
            if started:
                process.join(timeout=1)
                if process.is_alive():
                    process.terminate()  # Only our retained sequencer child; never a game.
                    self.report['sequencerProcess']['stoppedByClient'] = True
                    process.join(timeout=3)
                self.report['sequencerProcess']['returnCode'] = process.exitcode
                if process.exitcode != 0 or self.report['sequencerProcess']['stoppedByClient']:
                    self.report.update(status='stopped', completed=False,
                        reason='Owned sequencer child did not exit normally with code zero')
            self.report.update(done=True, finishedAt=self.wall())
            if self.active_case is not None and self.active_case not in self.finished_cases:
                self.case(self.active_case).update(status='unavailable', verdictSource='transport',
                    reason=self.report.get('reason', 'Transport stopped'))
            self.save()
        return 0 if self.report['completed'] else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('executor', 'executor-manifest', 'executor-manifest-sha256', 'runtime', 'channel-config',
                 'order-id', 'attempt-id', 'worker-identity', 'game-identity', 'sequencer', 'sequencer-sha256',
                 'plan', 'plan-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--wait-seconds', type=float, default=30)
    parser.add_argument('--maximum-seconds', type=float)
    args = parser.parse_args(argv)
    companion = None
    try:
        companion = Companion(args)
        result = companion.execute()
        print(encoded({'status': companion.report['status'], 'report': str(companion.output)}).decode('utf-8'))
        return result
    except BaseException as error:
        if companion is not None:
            companion.report.update(done=True, status='stopped', reason=str(error), errorType=type(error).__name__)
            try:
                companion.save()
            except Exception:
                pass
        print(encoded({'status': 'stopped', 'errorType': type(error).__name__, 'reason': str(error)}).decode('utf-8'), file=sys.stderr)
        return 2


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(main())
