"""Collect bounded per-run executor evidence and suggest follow-up from it."""
from collections import Counter
import json
from pathlib import Path
import re
import sys

from .exit_projection import terminal_exit_observation


HTTP_ERROR = re.compile(r'^HTTP ([45][0-9]{2})\b(?: api/tool/([^:\s]+):)?')


def read_steps(path):
    """Summarize the retained tool log without copying arguments or response bodies."""
    phases = []
    errors = Counter()
    malformed = 0
    bridge_requests = 0
    bridge_starts = 0
    task_queue = {'waitingObservations': 0, 'readyObservations': 0, 'recoveredWaits': 0}
    waiting_for_queue = False
    abandoned_reads = Counter()
    gateway_requests = Counter()
    resolved_gateways = set()
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
                        gateway_requests[correlation] += 1
                if kind == 'mo2-launch' and isinstance(row.get('result'), dict):
                    bridge_requests += 1
                    response = row['result']
                    if response.get('started') is True and response.get('applied') is not False:
                        bridge_starts += 1
    except (OSError, UnicodeError):
        return {'available': False, 'phases': [], 'toolErrors': [], 'bridgeLaunchRequests': None,
                'bridgeStartAcknowledgements': None, 'malformedRows': None,
                'taskQueue': None, 'abandonedStartupReads': None, 'gatewayDispositions': None}
    joined = sum(gateway_requests[key] == 1 for key in resolved_gateways if key is not None)
    return {'available': True, 'phases': phases,
            'toolErrors': [{'phase': phase, 'tool': tool, 'httpStatus': status, 'count': count}
                           for (phase, tool, status), count in errors.items()],
            'taskQueue': task_queue,
            'abandonedStartupReads': [{'phase': phase, 'tool': tool, 'count': count}
                                      for (phase, tool), count in abandoned_reads.items()],
            'gatewayDispositions': {'abandonedBeforeStart': joined,
                                    'unresolved': sum(gateway_requests.values()) - joined},
            'bridgeLaunchRequests': bridge_requests, 'bridgeStartAcknowledgements': bridge_starts,
            'malformedRows': malformed}


def summarize(state, steps_path):
    """Keep scenario, OS exit and restoration facts visible in one terminal review."""
    log = read_steps(Path(steps_path))
    termination = terminal_exit_observation(state.get('gameProcessObservations'), state.get('game'))
    checks = Counter(row['result'] for row in (state.get('checks') or ())
                     if isinstance(row, dict) and isinstance(row.get('result'), str))
    collection = state.get('collectionComplete')
    restored = state.get('restored')
    improvements = []
    if termination is not None and termination['exitCode'] != 0:
        improvements.append({'area': 'shutdown', 'trigger': 'verified-nonzero-exit',
                             'suggestion': 'Report the scenario and the exact native exit separately.'})
    if log['available'] and log['gatewayDispositions']['unresolved']:
        improvements.append({'area': 'transport', 'trigger': 'gateway-tool-error',
                             'suggestion': 'Correlate each gateway error with the specific request disposition.'})
    if log['available'] and log['bridgeLaunchRequests'] > log['bridgeStartAcknowledgements']:
        improvements.append({'area': 'launch', 'trigger': 'bridge-did-not-confirm-start',
                             'suggestion': 'Correlate the Bridge request, selected profile and actual process start.'})
    if log['available'] and log['malformedRows']:
        improvements.append({'area': 'evidence', 'trigger': 'malformed-log-row',
                             'suggestion': 'Check the steps log writer and retain the incomplete raw log.'})
    if collection is False or restored is False:
        improvements.append({'area': 'recovery', 'trigger': 'incomplete-collection-or-restoration',
                             'suggestion': 'Retain the original snapshot and identify the failing cleanup stage.'})
    return {'schemaVersion': 1, 'runId': state.get('id'),
            'gameEdition': state.get('configuration', {}).get('game_edition', 'vr'),
            'result': state.get('result'), 'scenarioResult': state.get('scenarioResult'),
            'gameIdentityRecorded': bool(state.get('game')), 'checks': dict(checks),
            'nativeExit': None if termination is None else {
                'code': termination['exitCode'], 'hex': termination['exitCodeHex'],
                'stage': termination.get('stage'),
            }, 'windowsFault': state.get('windowsFault'), 'collectionComplete': collection, 'restored': restored,
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
