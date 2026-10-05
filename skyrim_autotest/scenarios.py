"""Declarative bounded test steps with explicit assertions and saved observations."""
import time
from pathlib import Path
import json
import math
import re


def validate(scenario):
    """Reject malformed or observation-only tests before launching or mutating files."""
    if scenario.get('schemaVersion') != 1:
        raise ValueError('Unsupported scenario schema')
    if 'cell' in scenario and not re.fullmatch(r'[A-Za-z0-9_]+', scenario.get('cell', '')):
        raise ValueError('Initial cell needs a safe editor id')
    if 'allowBackgroundVR' in scenario and (type(scenario['allowBackgroundVR']) is not bool or scenario.get('kind') not in ('vr-hand-probe', 'vr-mobility-probe')):
        raise ValueError('allowBackgroundVR is a boolean option for physical VR probes only')
    fixture = scenario.get('fixture')
    if 'startMode' in scenario and scenario['startMode'] != 'new-game':
        raise ValueError('Unsupported initial startMode')
    if scenario.get('startMode') == 'new-game' and (fixture or not scenario.get('cell')):
        raise ValueError('New Game requires a declared cell and cannot load a save fixture')
    if fixture:
        if not isinstance(fixture, dict) or not re.fullmatch(r'[A-Za-z0-9_-]+', fixture.get('saveStem', '')) or any(not re.fullmatch(r'[0-9a-f]{64}', fixture.get(ext + 'Sha256', '')) for ext in ('ess', 'skse')):
            raise ValueError('Fixture needs safe saveStem and pinned ESS/SKSE hashes')
    if scenario.get('kind') == 'vr-mobility-probe':
        if not re.fullmatch(r'[A-Za-z0-9_]+', scenario.get('cell', '')):
            raise ValueError('Mobility probe needs a safe cell editor id')
        for key in ('physicalGrab', 'observer', 'keyboardDiagnostics', 'controllerJumpRequired', 'recordPickupInput', 'recordPickupHandlers'):
            if key in scenario and type(scenario[key]) is not bool:
                raise ValueError(key + ' must be boolean')
        return
    if scenario.get('kind') == 'vr-hand-probe':
        if not re.fullmatch(r'[A-Za-z0-9_]+', scenario.get('cell', '')):
            raise ValueError('Hand probe needs a safe cell editor id')
        if scenario.get('button', 'grip') not in ('grip', 'trigger'):
            raise ValueError('Unsupported physical controller button')
        if scenario.get('postSteps'):
            validate({'schemaVersion': 1, 'steps': scenario['postSteps']})
        return
    steps = scenario.get('steps')
    if not isinstance(steps, list) or not steps:
        raise ValueError('Scenario needs nonempty steps')
    assertion_count = 0
    for step in steps:
        if not isinstance(step.get('name'), str) or not step['name'] or not isinstance(step.get('tool'), str):
            raise ValueError('Each step needs a name and tool')
        validate_refs(step.get('args', {}))
        timeout = step.get('timeout', 20)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 180:
            raise ValueError('Step timeout must be finite and within (0, 180]')
        rules = step.get('assert', [])
        if not isinstance(rules, list):
            raise ValueError('Step assertions must be a list')
        if not rules and (step.get('observe') is not True or step.get('poll')):
            raise ValueError('A step needs assertions, or explicit non-polling observe:true')
        for rule in rules:
            operators = [k for k in ('equals', 'contains', 'min', 'max', 'exists') if k in rule]
            if len(operators) != 1 or not isinstance(rule.get('path', ''), str):
                raise ValueError('Assertion needs exactly one operator and a string path')
            if 'exists' in rule and type(rule['exists']) is not bool:
                raise ValueError('exists assertion needs a boolean')
            for operator in ('min', 'max'):
                if operator in rule and (type(rule[operator]) not in (int, float) or not math.isfinite(rule[operator])):
                    raise ValueError(operator + ' assertion needs a finite number')
        if step['tool'] != 'driver':
            assertion_count += len(rules)
        if step['tool'] == 'driver':
            validate_driver(step.get('args', {}))
        if step.get('poll'):
            args = step.get('args', {})
            readonly = (step['tool'] == 'driver' and args.get('action') == 'status') or step['tool'] == 'inspect' or (step['tool'] == 'menu' and args.get('action') in ('list', 'describe')) or (step['tool'] == 'input' and args.get('action') in ('status', 'capabilities'))
            if not readonly:
                raise ValueError('Polling is limited to known read-only inspection/status tools')
    if not assertion_count:
        raise ValueError('Observation-only or driver-publication-only scenario cannot establish a passing test')


def field(value, path):
    for part in path.split('.') if path else []:
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def check(value, rule):
    actual = field(value, rule.get('path', ''))
    if 'equals' in rule:
        return actual == rule['equals']
    if 'contains' in rule:
        return rule['contains'] in actual
    if 'min' in rule:
        return type(actual) in (int, float) and math.isfinite(actual) and actual >= rule['min']
    if 'max' in rule:
        return type(actual) in (int, float) and math.isfinite(actual) and actual <= rule['max']
    if 'exists' in rule:
        return (actual is not None) == rule['exists']
    raise ValueError('Assertion needs equals, contains, min or exists')


def retryable_observer_read(step, error):
    from .runner import ToolError
    args = step.get('args', {})
    return (isinstance(error, ToolError) and error.tool == 'inspect' and
            step.get('poll') is True and step.get('tool') == 'inspect' and
            args.get('kind') == 'world_observer' and
            args.get('action', 'snapshot') == 'snapshot' and
            error.args_value.get('kind') == 'world_observer' and
            error.args_value.get('action', 'snapshot') == 'snapshot' and
            error.result.get('ok') is False and
            error.result.get('outcome') == 'abandoned_before_start')


def execute(session, scenario):
    if scenario.get('kind') == 'vr-mobility-probe':
        from .mobility_probe import execute as probe
        probe(session, scenario)
        return
    if scenario.get('kind') == 'vr-hand-probe':
        from .vr_probe import execute as probe
        probe(session, scenario)
        if scenario.get('postSteps'):
            session.state['postStepsActive'] = True
            session.save()
            try:
                execute(session, {'schemaVersion': 1, 'steps': scenario['postSteps']})
            finally:
                session.state['postStepsActive'] = False
                session.save()
        return
    for index, step in enumerate(scenario['steps']):
        name = step['name']
        timeout = float(step.get('timeout', 20))
        session.phase('scenario: ' + name, timeout + 15)
        end = time.monotonic() + timeout
        result = None
        def fail(reason):
            session.state['checks'].append({'name': name, 'result': 'failed', 'observation': result, 'reason': reason})
            session.save()
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                fail('Step deadline exceeded before request')
                raise TimeoutError('Step deadline exceeded: ' + name)
            try:
                if uses_probe_reference(step.get('args', {})):
                    session.validate_probe_reference(timeout=min(remaining, 3))
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Step deadline exceeded during reference validation')
                result = session.tool(step['tool'], resolve_args(step.get('args', {}), session.state), timeout=min(remaining, 12))
            except Exception as error:
                from .runner import ToolError
                if isinstance(error, ToolError):
                    result = error.result
                if retryable_observer_read(step, error):
                    remaining = end - time.monotonic()
                    if remaining <= 0:
                        fail('Observer read abandoned at or after step deadline')
                        raise TimeoutError('Step deadline exceeded: ' + name) from error
                    session.log('scenario-read-retry', step=name, result=result,
                                remainingSeconds=remaining, reason='abandoned_before_start')
                    time.sleep(min(1, remaining))
                    continue
                fail('Tool request failed: ' + str(error))
                raise
            # Even an affirmative response is not timely evidence if it arrives
            # after the absolute step deadline. Never accept it or retry mutation.
            if time.monotonic() > end:
                fail('Step response arrived after deadline')
                raise TimeoutError('Step response arrived after deadline: ' + name)
            try:
                passed = all(check(result, rule) for rule in step.get('assert', []))
            except (KeyError, IndexError, TypeError):
                passed = False
            if passed:
                break
            if not step.get('poll'):
                fail('Returned-state assertion failed')
                raise AssertionError(f'Assertion failed: {name}')
            time.sleep(min(1, max(0, end - time.monotonic())))
        session.state['checks'].append({'name': name, 'result': 'passed' if step.get('assert') else 'observed', 'observation': result})
        session.save()
        (session.dir / f'step-{index:03d}.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


def resolve_args(value, state):
    """Explicit typed state lookup; no interpolation, expressions or arbitrary code."""
    if isinstance(value, dict):
        if set(value) == {"$state"}:
            path = value["$state"]
            # Only explicitly documented scenario output may be referenced.
            if path not in ("probeObject", "id"):
                raise ValueError("Unsupported state reference: " + str(path))
            if path == 'probeObject' and state.get('probeObjectLive') is False:
                raise ValueError('Probe reference was deleted or invalidated by a world change')
            return state[path]
        return {k: resolve_args(v, state) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_args(v, state) for v in value]
    return value


def validate_driver(args):
    action = args.get('action')
    if action in ('status', 'release'):
        if set(args) != {'action'}:
            raise ValueError('Driver status/release take action only')
        return
    if action != 'publish' or set(args) != {'action', 'frame', 'holdSeconds'}:
        raise ValueError('Driver publish needs action, full frame, holdSeconds')
    duration = args['holdSeconds']
    if type(duration) not in (int, float) or not math.isfinite(duration) or not 0 < duration <= 30:
        raise ValueError('Driver holdSeconds must be finite in (0, 30]')
    frame = args['frame']
    if not isinstance(frame, dict) or any(role not in frame for role in ('hmd', 'left', 'right')):
        raise ValueError('Driver publish requires HMD and both controllers')
    from .hardware import quaternion
    for role in ('hmd', 'left', 'right'):
        matrix = frame[role].get('matrix', [])
        if len(matrix) != 12 or any(type(v) not in (int, float) or not math.isfinite(v) for v in matrix):
            raise ValueError('Driver matrix needs twelve finite values')
        quaternion(matrix)
        if role != 'hmd':
            controller = frame[role].get('controller', {})
            if any(type(controller.get(k)) is not int or not 0 <= controller[k] < 2**64 for k in ('pressed', 'touched')):
                raise ValueError('Driver masks must be unsigned 64-bit')
            axes = controller.get('axes', [])
            if len(axes) != 5 or any(not isinstance(pair, list) or len(pair) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1 for v in pair) for pair in axes):
                raise ValueError('Driver axes need five finite pairs in [-1, 1]')


def validate_refs(value):
    if isinstance(value, dict):
        if '$state' in value:
            if set(value) != {'$state'} or value['$state'] not in ('probeObject', 'id'):
                raise ValueError('State references must be exact objects for probeObject or id')
        else:
            for child in value.values():
                validate_refs(child)
    elif isinstance(value, list):
        for child in value:
            validate_refs(child)


def uses_probe_reference(value):
    if isinstance(value, dict):
        return value == {'$state': 'probeObject'} or any(uses_probe_reference(child) for child in value.values())
    if isinstance(value, list):
        return any(uses_probe_reference(child) for child in value)
    return False
