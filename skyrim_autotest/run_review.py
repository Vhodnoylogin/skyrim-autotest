"""Collect bounded per-run executor evidence and suggest follow-up from it."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

from .exit_projection import terminal_exit_observation
from .collected_fault import collected_game_faults
from .readiness_reads import _abandoned_timeout


HTTP_ERROR = re.compile(r'^HTTP ([45][0-9]{2})\b(?: api/tool/([^:\s]+):)?')
DRIVER_COMMAND = re.compile(r'[a-f0-9]{32}')


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


def read_steps(path):
    """Summarize the retained tool log without copying arguments or response bodies."""
    phases = []
    failures = []
    errors = Counter()
    malformed = 0
    bridge_requests = 0
    bridge_starts = 0
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
                if kind == 'driver':
                    record_driver(row, phase, driver_counts, driver_publications, driver_acknowledgements)
                if kind == 'native-sampling-window':
                    window = native_sampling_window(row, phase)
                    if window is not None:
                        sampling_windows.append(window)
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
                'shutdownConsoleRequests': None,
                'taskQueue': None, 'abandonedStartupReads': None, 'gatewayDispositions': None,
                'driver': None, 'driverAcknowledgementTiming': None, 'nativeSamplingWindows': None}
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
            'bridgeLaunchRequests': bridge_requests, 'bridgeStartAcknowledgements': bridge_starts,
            'shutdownConsoleRequests': console_quit,
            'ownedGameWindowClose': window_close, 'malformedRows': malformed}


def summarize(state, steps_path):
    """Keep scenario, OS exit and restoration facts visible in one terminal review."""
    log = read_steps(Path(steps_path))
    termination = terminal_exit_observation(state.get('gameProcessObservations'), state.get('game'))
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
