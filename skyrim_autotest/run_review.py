"""Collect bounded per-run executor evidence and suggest follow-up from it."""
from collections import Counter
from datetime import datetime
import json
import ntpath
from pathlib import Path
import re
import sys

from .exit_projection import terminal_exit_observation
from .collected_fault import collected_game_faults
from .readiness_reads import _abandoned_timeout


HTTP_ERROR = re.compile(r'^HTTP ([45][0-9]{2})\b(?: api/tool/([^:\s]+):)?')
DRIVER_COMMAND = re.compile(r'[a-f0-9]{32}')
SCENARIO_GATE_CODE = re.compile(r'[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*')


def driver_tick(value):
    return value if type(value) is int and 0 <= value < 2**63 else None


def record_driver(row, phase, counts, publications, acknowledgements):
    """Count file-driver writes and their matching acceptance receipts."""
    result = row.get('result')
    action = row.get('action')
    if not isinstance(result, dict) or result.get('protocolVersion') != 2:
        return
    if action in ('publish', 'release') and result.get('published') is True:
        counts[phase, action] += 1
        publication = result.get('publication')
        valid = False
        if isinstance(publication, dict) and publication.get('version') == 2:
            command, sequence = publication.get('command'), publication.get('sequence')
            if (isinstance(command, str) and DRIVER_COMMAND.fullmatch(command)
                    and type(sequence) is int and 0 < sequence < 2**63):
                tick = driver_tick(publication.get('publishedTickMs'))
                publications.setdefault(command, []).append((phase, sequence, tick))
                valid = True
        if not valid:
            counts[phase, 'uncorrelated'] += 1
    elif action == 'status':
        counts[phase, 'status'] += 1
    command, sequence = result.get('command'), result.get('sequence')
    if (action in ('publish', 'release', 'status') and result.get('acknowledgedByDriver') is True
            and isinstance(command, str) and command in publications
            and type(sequence) is int and 0 < sequence < 2**63):
        writes = publications[command]
        if len(writes) == 1 and sequence >= writes[0][1]:
            _, issued_sequence, published = writes[0]
            observed = driver_tick(result.get('observedTickMs'))
            delay = observed - published if observed is not None and published is not None and observed >= published else None
            if command not in acknowledgements or acknowledgements[command] is None:
                acknowledgements[command] = None if delay is None else (sequence == issued_sequence, delay)


def native_sampling_window(row, phase):
    name = row.get('name')
    keys = ('samples', 'producerSpanNs', 'minSpanNs', 'maxGapNs', 'maxAllowedGapNs')
    measured = {key: row.get(key) for key in keys}
    if (not isinstance(name, str) or not 0 < len(name) <= 120
            or any(type(value) is not int or not 0 <= value < 2**63 for value in measured.values())):
        return None
    samples, span, minimum, gap, maximum = measured.values()
    if not (samples and minimum and maximum and gap <= span):
        return None
    return {'phase': phase, 'name': name, **measured,
            'meetsDeclaredTiming': samples >= 2 and span >= minimum and 0 < gap <= maximum}


def scenario_gate(row, phase):
    name, code = row.get('name'), row.get('reasonCode')
    disposition, required = row.get('disposition'), row.get('required')
    if (disposition not in ('passed', 'blocked', 'failed', 'unavailable') or type(required) is not bool
            or not all(isinstance(value, str) and len(value) <= 96 and SCENARIO_GATE_CODE.fullmatch(value)
                       for value in (name, code))):
        return None
    return {'phase': phase, 'name': name, 'disposition': disposition, 'reasonCode': code, 'required': required}


def native_papyrus_refusal(args, result):
    """Recognize a provider refusal inside a successfully returned typed call."""
    if (not isinstance(args, dict) or args.get('action') != 'call'
            or not isinstance(result, dict) or result.get('called') is not True
            or result.get('returnedType') != 'string' or result.get('error') or result.get('isError')):
        return None
    script, function = args.get('script'), args.get('function')
    if not all(isinstance(name, str) and len(name) <= 96 and name.isidentifier() for name in (script, function)):
        return None
    raw = result.get('returned')
    if not isinstance(raw, str) or len(raw) > 16384 or not raw.lstrip().startswith('{'):
        return None
    try:
        reply = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    version, reason = reply.get('schemaVersion'), reply.get('reason')
    if (reply.get('status') == 'refused' and type(version) is int and version > 0
            and isinstance(reason, str) and len(reason) <= 96 and SCENARIO_GATE_CODE.fullmatch(reason)):
        return script, function, reason
    return None


def world_observer_availability(row, phase, counts):
    args, result = row.get('args'), row.get('result')
    if (not isinstance(args, dict) or args.get('kind') != 'world_observer'
            or args.get('action', 'snapshot') != 'snapshot' or not isinstance(result, dict)
            or type(result.get('schemaVersion')) is not int or result['schemaVersion'] != 1
            or result.get('ok') is not True or result.get('phase') != 'skse_main_thread_task'):
        return
    for domain in ('physics', 'render'):
        entry = result.get(domain)
        status = entry.get('status') if isinstance(entry, dict) else None
        if status in ('available', 'partial', 'unavailable'):
            counts[phase, domain, status, domain == 'physics' and 'physics' in args] += 1


def capture_receipt(row, phase):
    args, result = row.get('args'), row.get('result')
    if (not isinstance(args, dict) or args.get('action', 'capture') not in ('capture', 'screenshot')
            or not isinstance(result, dict) or result.get('kind') != 'screenshot' or result.get('ok') is not True):
        return None
    flags = {key: result.get(key) for key in ('ok', 'sceneMismatch', 'inconclusive', 'uiExcluded')}
    checkpoint = result.get('checkpointId')
    if (not all(type(value) is bool for value in flags.values()) or not isinstance(checkpoint, str)
            or not checkpoint or args.get('checkpointId', checkpoint) != checkpoint):
        return None
    requested, provider = args.get('kind', 'auto'), result.get('provider')
    if (not isinstance(provider, str) or not provider or provider in ('auto', 'providers', 'extensions')
            or requested not in ('auto', provider)):
        return None
    if provider == 'native' and requested == 'auto' and args.get('allowNative') is not True:
        return None
    elapsed = result.get('captureElapsedMs')
    return {'phase': phase, 'method': 'native' if provider == 'native' else 'extension', **flags,
            'captureElapsedMs': elapsed if type(elapsed) is int and elapsed >= 0 else None}


def capture_operation_interval(row, phase):
    timing = row.get('captureOperationInterval')
    if not isinstance(timing, dict) or type(timing.get('schemaVersion')) is not int or timing['schemaVersion'] != 1:
        return None
    status = timing.get('status')
    clock_fields = {}
    if status == 'measured':
        ticks = {key: timing.get(key) for key in ('qpcFrequency', 'requestQpc', 'responseQpc')}
        if (timing.get('clock') != 'windows-qpc'
                or any(type(value) is not int or not 0 <= value < 2**63 for value in ticks.values())
                or ticks['qpcFrequency'] == 0 or ticks['requestQpc'] > ticks['responseQpc']):
            return None
        clock_fields = {'clock': 'windows-qpc', **ticks}
    elif status != 'unavailable':
        return None
    outcome = 'request-error' if row['kind'] == 'tool-error' else 'reply'
    result = row.get('result')
    if outcome == 'reply' and isinstance(result, dict) and (result.get('ok') is False or result.get('isError') or result.get('error')):
        outcome = 'rejected-reply'
    return {'phase': phase, 'status': status, 'outcome': outcome, **clock_fields}


def provider_timeout_body(tool, error):
    prefix = f'HTTP 504 api/tool/{tool}: '
    if not error.startswith(prefix):
        return None
    try:
        # HTTPResponseError may append separate response headers to the JSON body.
        body, _ = json.JSONDecoder().raw_decode(error[len(prefix):].lstrip())
    except (ValueError, RecursionError):
        return None
    if isinstance(body, dict) and type(body.get('code')) is int and body['code'] == 504:
        return body
    return None


def dispatched_papyrus_timeout(args, error):
    """Recognize DevBench's explicit dispatch receipt for this recorded call."""
    if not isinstance(args, dict) or args.get('action') != 'call':
        return False
    script, function = args.get('script'), args.get('function')
    timeout = args.get('timeoutMs', 3000)
    if not all(isinstance(name, str) and name for name in (script, function)) or type(timeout) is not int or timeout <= 0:
        return False
    body = provider_timeout_body('papyrus', error)
    if body is None:
        return False
    message = body.get('error')
    expected = (f"papyrus call '{script}.{function}' was dispatched but did not complete within {timeout}ms "
                "(latent call or VM stalled?); it may still run, so check its effect before calling again")
    return isinstance(message, str) and (message == expected or message.startswith(expected + '; omitted args filled: '))


def abandoned_inspect_timeout(args, error):
    """Recognize an explicit before-start cancellation for a direct scene read."""
    return args in ({'kind': 'state'}, {'kind': 'scene'}) and _abandoned_timeout(
        provider_timeout_body('inspect', error), startup_snapshot=False, main_menu_read=False)


def graceful_exit_summary(state):
    record = state.get('gracefulGameExit')
    if not state.get('game') or not isinstance(record, dict) or record.get('game') != state['game']:
        return None
    route = record.get('command')
    if route not in ('qqq', 'window-close', 'menu-main-quit'):
        return None
    acknowledgement = record.get('requestAcknowledgement')
    attempted = record.get('requestAttempted') is True
    queued = (attempted and route == 'qqq' and isinstance(acknowledgement, dict)
              and acknowledgement.get('command') == 'qqq' and acknowledgement.get('queued') is True)
    gone = record.get('observedGone')
    observation = None
    start, deadline, end = (record.get(key) for key in ('startedMonotonic', 'deadlineMonotonic', 'waitFinishedMonotonic'))
    if (type(gone) is bool and all(type(value) in (int, float) and 0 <= value < 2**53 for value in (start, deadline, end))
            and 0 < deadline - start <= 30 and end >= start):
        observation = {'elapsedSeconds': end - start, 'graceSeconds': deadline - start,
                       'processGoneByDeadline': gone and end <= deadline}
    return {'route': route, 'requestAttempted': attempted, 'queueAcknowledged': True if queued else None,
            'observedGone': gone if type(gone) is bool else None, 'waitObservation': observation}


def first_exit_epoch(termination):
    if termination is not None:
        try:
            first = datetime.fromisoformat(termination.get('firstExitObservedAtUtc'))
            last = datetime.fromisoformat(termination.get('observedAtUtc'))
            if first.tzinfo is not None and last.tzinfo is not None and first <= last:
                return first.timestamp()
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return None


def bridge_launch_key(boot, record):
    if isinstance(boot, str) and boot and isinstance(record, str) and record.startswith(boot + ':'):
        return boot, record
    return None


def bridge_game_observation(row, phase, launches, game, first_exit_at):
    """Project the recorded Bridge state independently of the native exit result."""
    observation = row.get('observation')
    if not isinstance(game, dict) or not isinstance(observation, dict) or observation.get('game') != game:
        return None
    operation = observation.get('operation')
    if not isinstance(operation, dict) or operation.get('route') != '/run':
        return None
    boot, record = observation.get('serverBootId'), operation.get('id')
    launch = operation.get('launch')
    if (bridge_launch_key(boot, record) not in launches or operation.get('serverBootId') != boot
            or not isinstance(launch, dict) or launch.get('operationRecordId') != record):
        return None
    children = launch.get('gameChildren')
    if not isinstance(children, list) or not isinstance(game.get('path'), str):
        return None
    matches = [child for child in children if isinstance(child, dict)
               and type(child.get('pid')) is int and child['pid'] == game.get('pid')
               and type(child.get('creationTime')) is int and child['creationTime'] == game.get('birth')
               and isinstance(child.get('path'), str) and ntpath.normcase(child['path']) == ntpath.normcase(game['path'])]
    if len(matches) != 1:
        return None
    child = matches[0]
    status, code = launch.get('gameExitStatus'), launch.get('gameExit')
    if status == 'observed':
        if (len(children) != 1 or child.get('alive') is not False or launch.get('gameAlive') is not False
                or type(code) is not int or not 0 <= code <= 0xffffffff
                or type(child.get('exit')) is not int or child['exit'] != code):
            return None
    elif status == 'running':
        if (child.get('alive') is not True or launch.get('gameAlive') is not True
                or child.get('exit') is not None or code is not None):
            return None
    elif status != 'unknown' or code is not None:
        return None
    op_state, terminal = operation.get('state'), operation.get('terminal')
    if op_state not in ('accepted', 'running', 'succeeded', 'refused', 'failed') or type(terminal) is not bool:
        return None
    at = row.get('at')
    offset = None
    if first_exit_at is not None and type(at) in (int, float) and 0 <= at < 2**53:
        offset = round(1000 * (at - first_exit_at))
    return {'phase': phase, 'operationState': op_state, 'operationTerminal': terminal,
            'gameExitStatus': status, 'gameExitCode': code, 'msFromFirstNativeExitObservation': offset}


def read_steps(path, *, game=None, first_exit_at=None):
    """Summarize the retained tool log without copying arguments or response bodies."""
    phases = []
    failures = []
    errors = Counter()
    malformed = 0
    bridge_requests = 0
    bridge_starts = 0
    bridge_launches = set()
    bridge_observations = []
    window_close = []
    console_quit = {'acknowledged': 0, 'notQueued': 0, 'unknown': 0}
    task_queue = {'waitingObservations': 0, 'readyObservations': 0, 'recoveredWaits': 0}
    waiting_for_queue = False
    abandoned_reads = Counter()
    gateway_requests = Counter()
    resolved_gateways = set()
    dispatched_timeouts = 0
    direct_abandonments = 0
    driver_counts = Counter()
    driver_publications = {}
    driver_acknowledgements = {}
    sampling_windows = []
    scenario_gates = []
    native_refusals = Counter()
    observer_availability = Counter()
    capture_receipts = []
    capture_operation_intervals = []
    try:
        with path.open(encoding='utf-8') as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(row, dict):
                    malformed += 1
                    continue
                kind = row.get('kind')
                phase = phases[-1] if phases else None
                request_id = row.get('clientRequestId')
                correlation = (phase, row.get('tool'), request_id) if isinstance(request_id, str) and request_id else None
                if kind == 'phase' and isinstance(row.get('name'), str):
                    phases.append(row['name'])
                    waiting_for_queue = False
                if kind in ('exception', 'execution-blocked'):
                    exception_type = row.get('exceptionType')
                    failures.append({
                        'phase': phase,
                        'disposition': 'blocked' if kind == 'execution-blocked' else 'failed',
                        'exceptionType': exception_type if isinstance(exception_type, str)
                        and exception_type.isidentifier() else None,
                    })
                if kind == 'task-queue-not-ready':
                    task_queue['waitingObservations'] += 1
                    waiting_for_queue = True
                if kind == 'task-queue-ready':
                    task_queue['readyObservations'] += 1
                    task_queue['recoveredWaits'] += int(waiting_for_queue)
                    waiting_for_queue = False
                if kind == 'common-readiness-abandoned-read' and isinstance(row.get('tool'), str):
                    abandoned_reads[(phase, row['tool'])] += 1
                    if correlation in gateway_requests:
                        resolved_gateways.add(correlation)
                if kind == 'tool-error' and isinstance(row.get('tool'), str):
                    error = row.get('error')
                    http = HTTP_ERROR.match(error) if isinstance(error, str) else None
                    status = int(http.group(1)) if http else None
                    errors[(phase, row['tool'], status)] += 1
                    if status in (502, 503, 504) and http.group(2) in (None, row['tool']):
                        if row['tool'] == 'papyrus' and dispatched_papyrus_timeout(row.get('args'), error):
                            dispatched_timeouts += 1
                        elif row['tool'] == 'inspect' and abandoned_inspect_timeout(row.get('args'), error):
                            direct_abandonments += 1
                        else:
                            # Only requests without their own disposition can be resolved by a later decision.
                            gateway_requests[correlation] += 1
                if kind == 'mo2-launch' and isinstance(row.get('result'), dict):
                    bridge_requests += 1
                    response = row['result']
                    if response.get('started') is True and response.get('applied') is not False:
                        bridge_starts += 1
                        key = bridge_launch_key(response.get('serverBootId'), response.get('operationRecordId'))
                        if key is not None:
                            bridge_launches.add(key)
                if kind in ('mo2-bridge-observation', 'private-vr-bridge-observation'):
                    observation = bridge_game_observation(row, phase, bridge_launches, game, first_exit_at)
                    if observation is not None:
                        bridge_observations.append(observation)
                if kind == 'driver':
                    record_driver(row, phase, driver_counts, driver_publications, driver_acknowledgements)
                if kind == 'native-sampling-window':
                    window = native_sampling_window(row, phase)
                    if window is not None:
                        sampling_windows.append(window)
                if kind == 'scenario-gate':
                    gate = scenario_gate(row, phase)
                    if gate is not None:
                        scenario_gates.append(gate)
                if kind == 'tool' and row.get('tool') == 'papyrus':
                    refusal = native_papyrus_refusal(row.get('args'), row.get('result'))
                    if refusal is not None:
                        native_refusals[(phase, *refusal)] += 1
                if kind == 'tool' and row.get('tool') == 'inspect':
                    world_observer_availability(row, phase, observer_availability)
                if kind == 'tool' and row.get('tool') == 'capture':
                    captured = capture_receipt(row, phase)
                    if captured is not None:
                        capture_receipts.append(captured)
                if kind in ('tool', 'tool-error') and row.get('tool') == 'capture':
                    interval = capture_operation_interval(row, phase)
                    if interval is not None:
                        capture_operation_intervals.append(interval)
                if (phase == 'stop-and-restore' and kind in ('tool', 'tool-error')
                        and row.get('tool') == 'console'
                        and row.get('args') == {'action': 'exec', 'command': 'qqq'}):
                    result = row.get('result')
                    queued = None
                    if (kind == 'tool' and isinstance(result, dict) and result.get('command') == 'qqq'
                            and not (result.get('error') or result.get('isError'))):
                        queued = result.get('queued')
                    disposition = 'acknowledged' if queued is True else 'notQueued' if queued is False else 'unknown'
                    console_quit[disposition] += 1
                if kind == 'owned-game-window-close' and type(row.get('requested')) is bool and type(row.get('accepted')) is bool:
                    window_close.append({'requested': row['requested'], 'accepted': row['accepted']})
    except (OSError, UnicodeError):
        return {'available': False, 'phases': [], 'failures': None, 'toolErrors': [], 'bridgeLaunchRequests': None,
                'bridgeStartAcknowledgements': None, 'ownedGameWindowClose': None, 'malformedRows': None,
                'bridgeGameObservations': None, 'shutdownConsoleRequests': None,
                'taskQueue': None, 'abandonedStartupReads': None, 'gatewayDispositions': None,
                'driver': None, 'driverAcknowledgementTiming': None, 'nativeSamplingWindows': None,
                'scenarioGates': None, 'nativePapyrusRefusals': None,
                'worldObserverAvailability': None, 'captureReceipts': None,
                'captureOperationIntervals': None}
    joined = sum(gateway_requests[key] == 1 for key in resolved_gateways if key is not None)
    driver_timing = {}
    for command, writes in driver_publications.items():
        if len(writes) != 1:
            for phase, _, _ in writes:
                driver_counts[phase, 'uncorrelated'] += 1
            continue
        phase = writes[0][0]
        if command not in driver_acknowledgements:
            driver_counts[phase, 'acknowledgement-unobserved'] += 1
            continue
        driver_counts[phase, 'acknowledged'] += 1
        timing = driver_acknowledgements[command]
        if timing is not None:
            exact_sequence, delay = timing
            driver_timing.setdefault((phase, exact_sequence), []).append(delay)
    return {'available': True, 'phases': phases, 'failures': failures,
            'toolErrors': [{'phase': phase, 'tool': tool, 'httpStatus': status, 'count': count}
                           for (phase, tool, status), count in errors.items()],
            'taskQueue': task_queue,
            'abandonedStartupReads': [{'phase': phase, 'tool': tool, 'count': count}
                                      for (phase, tool), count in abandoned_reads.items()],
            'gatewayDispositions': {'abandonedBeforeStart': direct_abandonments + joined,
                                    'dispatchedCompletionUnknown': dispatched_timeouts,
                                    'unresolved': sum(gateway_requests.values()) - joined},
            'driver': [{'phase': phase, 'operation': operation, 'count': count}
                       for (phase, operation), count in driver_counts.items()],
            'driverAcknowledgementTiming': [{'phase': phase, 'exactSequence': exact, 'samples': len(delays),
                                            'minMs': min(delays), 'maxMs': max(delays)}
                                           for (phase, exact), delays in driver_timing.items()],
            'nativeSamplingWindows': sampling_windows,
            'scenarioGates': scenario_gates,
            'nativePapyrusRefusals': [{'phase': phase, 'script': script, 'function': function,
                                      'reasonCode': reason, 'count': count}
                                     for (phase, script, function, reason), count in native_refusals.items()],
            'worldObserverAvailability': [
                {'phase': phase, 'domain': domain, 'status': status, 'requested': requested, 'count': count}
                for (phase, domain, status, requested), count in observer_availability.items()],
            'captureReceipts': capture_receipts,
            'captureOperationIntervals': capture_operation_intervals,
            'bridgeLaunchRequests': bridge_requests, 'bridgeStartAcknowledgements': bridge_starts,
            'bridgeGameObservations': bridge_observations,
            'shutdownConsoleRequests': console_quit,
            'ownedGameWindowClose': window_close, 'malformedRows': malformed}


def summarize(state, steps_path):
    """Keep scenario, OS exit and restoration facts visible in one terminal review."""
    game = state.get('game')
    termination = terminal_exit_observation(state.get('gameProcessObservations'), game)
    log = read_steps(Path(steps_path), game=game, first_exit_at=first_exit_epoch(termination))
    collected_faults = collected_game_faults(state, Path(steps_path).parent, termination)
    check_rows = [row for row in (state.get('checks') or ())
                  if isinstance(row, dict) and isinstance(row.get('result'), str)]
    checks = Counter(row['result'] for row in check_rows)
    failed_checks = [row['name'] for row in check_rows if row['result'] == 'failed'
                     and isinstance(row.get('name'), str) and row['name']]
    collection = state.get('collectionComplete')
    restored = state.get('restored')
    improvements = []
    if termination is not None and termination['exitCode'] != 0:
        improvements.append({'area': 'shutdown', 'trigger': 'verified-nonzero-exit',
                             'suggestion': 'Report the scenario and the exact native exit separately.'})
    if log['available'] and log['gatewayDispositions']['unresolved']:
        improvements.append({'area': 'transport', 'trigger': 'gateway-tool-error',
                             'suggestion': 'Correlate each gateway error with the specific request disposition.'})
    if log['available'] and log['gatewayDispositions']['dispatchedCompletionUnknown']:
        improvements.append({'area': 'transport', 'trigger': 'dispatched-tool-completion-unknown',
                             'suggestion': 'Preserve the dispatched attempt and verify its effect independently.'})
    if log['available'] and log['bridgeLaunchRequests'] > log['bridgeStartAcknowledgements']:
        improvements.append({'area': 'launch', 'trigger': 'bridge-did-not-confirm-start',
                             'suggestion': 'Correlate the Bridge request, selected profile and actual process start.'})
    if log['available'] and log['malformedRows']:
        improvements.append({'area': 'evidence', 'trigger': 'malformed-log-row',
                             'suggestion': 'Check the steps log writer and retain the incomplete raw log.'})
    if log['nativePapyrusRefusals']:
        improvements.append({'area': 'native-provider', 'trigger': 'typed-papyrus-refusal',
                             'suggestion': 'Use the provider reason code when diagnosing the failed scenario phase.'})
    if log['available'] and any(not row['meetsDeclaredTiming'] for row in log['nativeSamplingWindows']):
        improvements.append({'area': 'sampling', 'trigger': 'declared-native-window-timing-missed',
                             'suggestion': 'Use the source-clock span and largest gap to review sampling cadence.'})
    if collection is False or restored is False:
        improvements.append({'area': 'recovery', 'trigger': 'incomplete-collection-or-restoration',
                             'suggestion': 'Retain the original snapshot and identify the failing cleanup stage.'})
    return {'schemaVersion': 1, 'runId': state.get('id'),
            'gameEdition': state.get('configuration', {}).get('game_edition', 'vr'),
            'result': state.get('result'), 'scenarioResult': state.get('scenarioResult'),
            'gameIdentityRecorded': bool(state.get('game')), 'checks': dict(checks),
            'failedChecks': failed_checks,
            'nativeExit': None if termination is None else {
                'code': termination['exitCode'], 'hex': termination['exitCodeHex'],
                'stage': termination.get('stage'),
            }, 'gracefulExit': graceful_exit_summary(state), 'windowsFault': state.get('windowsFault'),
            'collectedGameFaults': collected_faults,
            'collectionComplete': collection, 'restored': restored,
            'execution': log, 'improvementCandidates': improvements}


def review_directory(directory, *, query_windows_fault=False):
    directory = Path(directory)
    state = json.loads((directory / 'state.json').read_bytes())
    if query_windows_fault:
        from .windows_fault import capture_windows_fault
        state['windowsFault'] = capture_windows_fault(state)
    return summarize(state, directory / 'steps.jsonl')


def main(args):
    from argparse import ArgumentParser
    parser = ArgumentParser(prog='python -m skyrim_autotest.run_review')
    parser.add_argument('directory')
    parser.add_argument('--query-windows-fault', action='store_true')
    options = parser.parse_args(args[1:])
    print(json.dumps(review_directory(options.directory, query_windows_fault=options.query_windows_fault), indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
