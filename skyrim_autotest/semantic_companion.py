"""Standalone interpreter for an operator-compiled immutable semantic plan.

Only exchange/emit reach the owned session. Protocol wrapper cases do not change
the original roles, observation-only results or original factual-test boundary.
The Dashboard must independently project those from the pinned original plan.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import time

INTERFACE = 'held-semantic-plan/1'
OPERATORS = frozenset(('equals', 'contains', 'min', 'max', 'exists', 'type'))
READS = frozenset(('state.read', 'player.read', 'world.read', 'menu.read'))


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def field(value, path):
    for part in path.split('.') if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def json_equal(actual, expected):
    if type(actual) is bool or type(expected) is bool:
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, dict) or isinstance(expected, dict):
        return (isinstance(actual, dict) and isinstance(expected, dict) and actual.keys() == expected.keys() and
                all(json_equal(actual[key], expected[key]) for key in actual))
    if isinstance(actual, list) or isinstance(expected, list):
        return (isinstance(actual, list) and isinstance(expected, list) and len(actual) == len(expected) and
                all(json_equal(a, b) for a, b in zip(actual, expected)))
    return actual == expected


def result_type(value, expected):
    types = {'null': type(None), 'boolean': bool, 'integer': int, 'string': str, 'array': list, 'object': dict}
    if expected.endswith('[]'):
        return type(value) is list and all(result_type(item, expected[:-2]) for item in value)
    if expected == 'number':
        if type(value) not in (int, float): return False
        try: return math.isfinite(value)
        except OverflowError: return False
    if expected not in types: raise ValueError('Unsupported native result type assertion')
    return type(value) is types[expected]


def check(value, rule):
    """The native scenarios.check JSON semantics, including Bool/number identity."""
    actual = field(value, rule.get('path', ''))
    if 'type' in rule: return result_type(actual, rule['type'])
    if 'equals' in rule: return json_equal(actual, rule['equals'])
    if 'contains' in rule: return rule['contains'] in actual
    if 'min' in rule: return type(actual) in (int, float) and math.isfinite(actual) and actual >= rule['min']
    if 'max' in rule: return type(actual) in (int, float) and math.isfinite(actual) and actual <= rule['max']
    if 'exists' in rule: return (actual is not None) == rule['exists']
    raise ValueError('Assertion requires one supported native operator')


def assertion_results(value, rules):
    results = []
    for index, rule in enumerate(rules):
        operator = next(key for key in OPERATORS if key in rule)
        try:
            actual = field(value, rule.get('path', ''))
            passed = check(value, rule)
            available = True
        except (KeyError, IndexError, TypeError):
            actual, passed, available = None, False, False
        results.append({'index': index, 'rule': copy.deepcopy(rule), 'actual': copy.deepcopy(actual),
            'expected': copy.deepcopy(rule[operator]), 'available': available, 'passed': bool(passed)})
    return results


def _state_reference(value):
    if isinstance(value, dict):
        return '$state' in value or '$parameter' in value or any(_state_reference(item) for item in value.values())
    return isinstance(value, list) and any(_state_reference(item) for item in value)


def readonly(step):
    tool, args = step['tool'], step.get('args', {})
    return (tool == 'platform' and args.get('operation') in READS or tool == 'inspect' or
            tool == 'menu' and args.get('action') in ('list', 'describe') or tool == 'papyrus')


def validate_spec(spec):
    required = {'schemaVersion', 'interface', 'subjectOrderSha256', 'originalTesting', 'scenario', 'bounds', 'provenance'}
    if type(spec) is not dict or set(spec) != required or spec['schemaVersion'] != 1 or spec['interface'] != INTERFACE:
        raise ValueError('Exact held semantic spec required')
    if not isinstance(spec['subjectOrderSha256'], str) or len(spec['subjectOrderSha256']) != 64 or any(c not in '0123456789abcdef' for c in spec['subjectOrderSha256']):
        raise ValueError('Original canonical semantic order hash required')
    bounds = spec['bounds']
    if (type(bounds) is not dict or set(bounds) != {'maximumSeconds', 'maximumCommands'} or
            type(bounds['maximumSeconds']) is not int or not 1 <= bounds['maximumSeconds'] <= 1200 or
            type(bounds['maximumCommands']) is not int or not 1 <= bounds['maximumCommands'] <= 2048):
        raise ValueError('Finite held plan window and command bound required')
    scenario = spec['scenario']
    if (type(scenario) is not dict or scenario.get('schemaVersion') != 1 or
            set(scenario) - {'schemaVersion', 'steps', 'cell', 'startMode', 'fixture'} or
            type(scenario.get('steps')) is not list or not 1 <= len(scenario['steps']) <= 512):
        raise ValueError('Only an operator-compiled generic native scenario is supported')
    names = []
    for step in scenario['steps']:
        if type(step) is not dict or set(step) - {'name', 'tool', 'args', 'timeout', 'poll', 'assert', 'observe'}:
            raise ValueError('Unknown compiled native step field')
        name = step.get('name')
        if not isinstance(name, str) or not 1 <= len(name) <= 160 or any(ord(c) < 33 for c in name):
            raise ValueError('Bounded original step names required')
        names.append(name)
        tool, args = step.get('tool'), step.get('args', {})
        if tool not in ('platform', 'inspect', 'menu', 'papyrus') or type(args) is not dict or _state_reference(args):
            raise ValueError('Held bridge forbids startup/console/audio/physical-input tools and unresolved state selectors')
        if tool == 'platform':
            if args.get('operation') not in READS | {'object.perform'} or set(args) - {'operation', 'request'}:
                raise ValueError('Unsupported held semantic operation')
            request = args.get('request', {})
            if type(request) is not dict or request.get('action') in ('restart_game', 'load_game', 'save_game'):
                raise ValueError('Only the declared owned domain save/load route is supported')
        elif tool == 'inspect':
            if args.get('kind') not in ('state', 'scene', 'mods', 'player', 'world_observer') or args.get('action', 'snapshot') not in ('snapshot', 'capabilities'):
                raise ValueError('Unsupported read-only inspection')
        elif tool == 'menu':
            if args.get('action') not in ('list', 'describe'): raise ValueError('Only read-only menu access is supported')
        else:
            # Match the frozen interactive raw-Papyrus read boundary; subject
            # mutations must use typed platform bindings, never script selectors.
            allowed = {'Game': {'GetPlayer'}, 'Actor': {'GetActorValue', 'GetRace', 'GetActorBase', 'IsDead'},
                       'ObjectReference': {'GetPositionX', 'GetPositionY', 'GetPositionZ'}}
            if args.get('action') != 'call' or args.get('function') not in allowed.get(args.get('script'), set()):
                raise ValueError('Raw Papyrus is limited to the existing native read allowlist')
        timeout = step.get('timeout', 20)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 180:
            raise ValueError('Original step deadline must be finite in (0,180]')
        for flag in ('poll', 'observe'):
            if flag in step and type(step[flag]) is not bool: raise ValueError('Step flags require Booleans')
        if step.get('poll') and not readonly(step): raise ValueError('A mutation must never be polled or retried')
        rules = step.get('assert', [])
        if type(rules) is not list or (not rules and (step.get('observe') is not True or step.get('poll'))):
            raise ValueError('Every step requires assertions or explicit non-polling observation')
        for rule in rules:
            if type(rule) is not dict or len(set(rule) & OPERATORS) != 1 or set(rule) - OPERATORS - {'path'} or not isinstance(rule.get('path', ''), str):
                raise ValueError('Exact native assertion path and one operator required')
            if 'exists' in rule and type(rule['exists']) is not bool: raise ValueError('Exists requires a Boolean')
            if 'type' in rule: result_type(None, rule['type'])
            for operator in ('min', 'max'):
                if operator in rule and (type(rule[operator]) not in (int, float) or not math.isfinite(rule[operator])):
                    raise ValueError('Numeric assertions require finite actual units')
    testing = spec['originalTesting']
    if (len(set(names)) != len(names) or type(testing) is not dict or set(testing) != {'start', 'checks'} or
            type(testing['checks']) is not list or [row.get('name') for row in testing['checks']] != names or
            any(set(row) != {'name', 'role'} or row['role'] not in ('subject', 'fixture', 'tooling') for row in testing['checks']) or
            testing['start'].get('kind') != 'check' or testing['start'].get('name') not in names or
            next(row['role'] for row in testing['checks'] if row['name'] == testing['start']['name']) != 'subject'):
        raise ValueError('Exact unchanged original names, roles and subject boundary required')
    canonical_hash(spec)  # Reject non-JSON/nonfinite input; no mutable runtime lookup.
    return copy.deepcopy(spec)


def run_plan(spec, exchange, emit, *, clock=time.monotonic, pause=time.sleep, finish_owner=True):
    """Run one stage; only its caller may own finish when finish_owner=False."""
    if type(finish_owner) is not bool:
        raise ValueError('finish_owner requires an explicit boolean')
    spec = validate_spec(spec)
    roles = {row['name']: row['role'] for row in spec['originalTesting']['checks']}
    boundary = spec['originalTesting']['start']['name']
    steps, results = spec['scenario']['steps'], []
    sequence = 0; session_end = clock() + spec['bounds']['maximumSeconds']

    def call(case, envelope):
        nonlocal sequence
        if clock() >= session_end: raise TimeoutError('Original held semantic session deadline exhausted')
        if sequence >= spec['bounds']['maximumCommands']: raise TimeoutError('Original semantic command bound exhausted')
        sequence += 1
        emit({'kind': 'measurement', 'caseId': case, 'sequence': sequence, 'request': envelope, 'delivery': 'intent'})
        value = exchange(envelope)
        emit({'kind': 'measurement', 'caseId': case, 'sequence': sequence, 'request': envelope, 'delivery': 'completed', 'rawResult': value})
        return value

    def verdict(index, outcome, semantic, detail, attempts):
        step = steps[index]; name = step['name']
        value = {'name': name, 'role': roles[name], 'result': semantic, 'stepIndex': index, 'attempts': attempts,
                 'originalSubjectStart': name == boundary}
        results.append(value)
        emit({'kind': 'check-result', 'caseId': name, 'outcome': outcome, 'detail': detail,
              'semanticResult': semantic, 'semanticRole': roles[name], 'stepIndex': index})

    def remaining_not_run(index):
        for pending in range(index + 1, len(steps)):
            verdict(pending, 'not_run', 'not_run', 'Stopped after the preceding semantic step; never replayed', 0)

    for index, step in enumerate(steps):
        name = step['name']; attempts = 0; last_assertions = []
        emit({'kind': 'check-start', 'caseId': name, 'role': 'subject'})  # Transport protocol wrapper only.
        end = min(session_end, clock() + step.get('timeout', 20))
        try:
            while True:
                remaining = end - clock()
                if remaining <= 0:
                    if last_assertions: break
                    raise TimeoutError('Original semantic step deadline exhausted before request')
                args = copy.deepcopy(step.get('args', {}))
                load = (step['tool'] == 'platform' and args.get('operation') == 'object.perform' and
                        args.get('request', {}).get('domain') == 'save-state' and
                        args['request'].get('action') == 'load-owned-disposable-once')
                envelope = {'schemaVersion': 1, 'operation': 'tool', 'tool': step['tool'], 'args': args,
                            'timeoutSeconds': min(90 if load else 30, remaining)}
                if 'timeoutMs' in args:
                    args['timeoutMs'] = min(args['timeoutMs'], max(1, int(envelope['timeoutSeconds'] * 1000)))
                attempts += 1
                value = call(name, envelope)
                if clock() > end: raise TimeoutError('Step response arrived after its original absolute deadline')
                last_assertions = assertion_results(value, step.get('assert', []))
                if all(row['passed'] for row in last_assertions) or not step.get('poll'): break
                remaining = end - clock()
                if remaining <= 0: break
                pause(min(1.0, remaining))
            if last_assertions:
                for row in last_assertions:
                    emit({'kind': 'assertion', 'caseId': name, 'check': name + '/assert-' + str(row['index']),
                        'assertionRole': 'semantic', 'rule': row['rule'], 'actual': row['actual'], 'expected': row['expected'],
                        'available': row['available'], 'outcome': 'passed' if row['passed'] else 'mismatch'})
                passed = all(row['passed'] for row in last_assertions)
                verdict(index, 'passed' if passed else 'mismatch', 'passed' if passed else 'failed',
                        'Original assertions evaluated against actual returned state', attempts)
                if not passed:
                    remaining_not_run(index)
                    if finish_owner:
                        call(None, {'schemaVersion': 1, 'operation': 'finish'})
                    return {'interface': INTERFACE, 'outcome': 'mismatch', 'steps': results, 'originalTesting': spec['originalTesting'],
                            'subjectOrderSha256': spec['subjectOrderSha256'], 'originAcceptanceClaimed': False}
            else:
                # Satisfy the old transport's wrapper-case receipt requirement
                # while retaining the actual semantic result as observed only.
                emit({'kind': 'assertion', 'caseId': name, 'check': 'transport.receipt-recorded', 'assertionRole': 'transport',
                      'actual': True, 'expected': True, 'outcome': 'passed'})
                verdict(index, 'passed', 'observed', 'Transport receipt only; original step declares no business assertion', attempts)
        except BaseException as error:
            # An uncertain exchange is terminal; no finish, mutation or retry is
            # submitted after transport failure. Native lifetime remains owned.
            if len(results) <= index:
                verdict(index, 'unavailable', 'unavailable', type(error).__name__ + ': ' + str(error), attempts)
                remaining_not_run(index)
            raise
    if finish_owner:
        call(None, {'schemaVersion': 1, 'operation': 'finish'})
    return {'interface': INTERFACE, 'outcome': 'passed', 'steps': results, 'originalTesting': spec['originalTesting'],
            'subjectOrderSha256': spec['subjectOrderSha256'], 'originAcceptanceClaimed': False}


def render(spec):
    """Deterministic standalone program; the qualified executor needs no edits."""
    normalized = validate_spec(spec)
    source = Path(__file__).read_text(encoding='utf-8')
    payload = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return source + '\n_SEMANTIC_SPEC_JSON = ' + repr(payload) + '\n\ndef run(exchange, emit):\n    return run_plan(json.loads(_SEMANTIC_SPEC_JSON), exchange, emit)\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render-spec', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    spec = json.loads(args.render_spec.read_text(encoding='utf-8-sig'))
    with args.output.open('x', encoding='utf-8', newline='\n') as stream: stream.write(render(spec))


if __name__ == '__main__': main()
