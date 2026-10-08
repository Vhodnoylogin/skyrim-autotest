"""Opt-in tool-owned reads at reviewed, exact scenario boundaries.

This records responses, not subject acceptance. Host cursors/clocks never stand
in for native callbacks, consumer acknowledgements or renderer/physics frames.
"""
import copy
import hashlib
import json
import math
import re
import time


OBSERVATIONS = {'subject.settings', 'hand.held_item', 'inventory.quantity',
                'inventory.alchemy', 'body_slot.settings', 'body_slot.display',
                'reference.state', 'reference.physics'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def validate(plan, scenario=None, scenario_sha256=None):
    if (not isinstance(plan, dict) or set(plan) != {'schemaVersion', 'scenarioSha256',
            'boundaryBudgetSeconds', 'requests'} or type(plan['schemaVersion']) is not int or
            plan['schemaVersion'] != 1 or not isinstance(plan['scenarioSha256'], str) or
            not re.fullmatch('[0-9a-f]{64}', plan['scenarioSha256'])):
        raise ValueError('Boundary collection requires an exact scenario pin and schema1')
    budget = plan['boundaryBudgetSeconds']
    if type(budget) not in (int, float) or not math.isfinite(budget) or not 0 < budget <= 30:
        raise ValueError('Boundary collection budget must be finite in (0,30]')
    rows = plan['requests']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 128:
        raise ValueError('Boundary collection requires1..128 explicit requests')
    seen, reviews = set(), {}
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'id', 'after', 'before', 'review', 'args', 'timeout'} or
                not isinstance(row['id'], str) or not re.fullmatch('[A-Za-z0-9_-]{1,64}', row['id']) or row['id'] in seen):
            raise ValueError('Boundary collection requires unique safe request ids')
        seen.add(row['id'])
        for key in ('after', 'before'):
            anchor = row[key]
            if (not isinstance(anchor, dict) or set(anchor) != {'index', 'name', 'stepSha256'} or
                    type(anchor['index']) is not int or anchor['index'] < 0 or
                    not isinstance(anchor['name'], str) or not anchor['name'] or
                    not isinstance(anchor['stepSha256'], str) or not re.fullmatch('[0-9a-f]{64}', anchor['stepSha256'])):
                raise ValueError('Boundary anchor needs exact index, name and step hash')
        if row['before']['index'] != row['after']['index'] + 1:
            raise ValueError('Boundary collection requires adjacent main checkpoints')
        review = row['review']
        if (not isinstance(review, dict) or set(review) != {'settled', 'reason'} or
                review['settled'] is not True or not isinstance(review['reason'], str) or not review['reason'].strip()):
            raise ValueError('Explicit settled-boundary review required; narrow race windows are forbidden')
        anchor_key = row['after']['index']
        current = (row['after'], row['before'], review)
        if anchor_key in reviews and reviews[anchor_key] != current:
            raise ValueError('Conflicting boundary anchor or safety review')
        reviews[anchor_key] = current
        args = row['args']
        if (not isinstance(args, dict) or not isinstance(args.get('request', {}), dict) or
                args.get('operation') not in ('player.read', 'world.read') or
                (args['operation'] == 'world.read' and args.get('request', {}).get('observation') not in OBSERVATIONS)):
            raise ValueError('Boundary collection only supports explicit non-mutating semantic reads')
        from .platform import validate as validate_request
        validate_request(args)
        if args.get('request', {}).get('continuityWindowSeconds', 0) != 0:
            raise ValueError('A boundary read cannot open a timed ownership window')
        timeout = row['timeout']
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 20:
            raise ValueError('Boundary request timeout must be finite in (0,20]')
    if scenario is not None:
        if scenario.get('kind') in ('vr-hand-probe', 'vr-mobility-probe') or not isinstance(scenario.get('steps'), list):
            raise ValueError('Boundary collection requires a generic top-level scenario')
        if scenario_sha256 != plan['scenarioSha256']:
            raise ValueError('Boundary collection scenario pin mismatch')
        for row in rows:
            for key in ('after', 'before'):
                a = row[key]
                if (a['index'] >= len(scenario['steps']) or
                        scenario['steps'][a['index']].get('name') != a['name'] or
                        digest(scenario['steps'][a['index']]) != a['stepSha256']):
                    raise ValueError('Boundary collection checkpoint mismatch')


def persist(session):
    from .runner import atomic_json
    atomic_json(session.dir / 'boundary-collection.json', session.state['boundaryCollection'])
    session.save()


def initialize(session, plan):
    if not plan:
        return
    if 'boundaryCollection' in session.state:
        raise ValueError('Boundary collection cannot be reinitialized or replayed')
    from .runner import atomic_json
    atomic_json(session.dir / 'boundary-collection-plan.json', plan)
    session.state['boundaryCollection'] = {
        'schemaVersion': 1, 'runId': session.state['id'], 'planSha256': digest(plan),
        'scenarioSha256': plan['scenarioSha256'], 'sequence': 0,
        'basis': 'Executor boundary reads; sequential non-atomic observations, not subject acceptance',
        'requests': [{'id': r['id'], 'status': 'not_run', 'reason': 'Boundary not reached',
                      'after': copy.deepcopy(r['after']), 'before': copy.deepcopy(r['before'])}
                     for r in plan['requests']]}
    persist(session)


def identity(session):
    state = session.state
    return copy.deepcopy({'game': state.get('game'),
        'executorWorldGeneration': state.get('ownedWorldGeneration'),
        'referenceTags': state.get('platformReferences', {}),
        'nativeSubjectCursors': state.get('subjectStateReadCursors', {}),
        'lifecycleCursor': (state.get('ownedLoadTransition') or state.get('initialWorldTransition', {})).get('cursor'),
        'probeLifecycle': {k: state[k] for k in ('probeObject', 'probeObjectLive', 'probeWorldCursor') if k in state}})


def after_step(session, index, step):
    plan = session.state.get('configuration', {}).get('boundary_collection')
    if not plan:
        return
    rows = [(n, r) for n, r in enumerate(plan['requests']) if r['after']['index'] == index]
    if not rows:
        return
    validate(plan, session.state['scenario'], session.state['scenarioHash'])
    accounting = session.state.get('boundaryCollection', {})
    if (accounting.get('runId') != session.state['id'] or accounting.get('planSha256') != digest(plan) or
            accounting.get('scenarioSha256') != session.state['scenarioHash']):
        raise ValueError('Boundary collection durable plan/run identity mismatch')
    if step.get('name') != rows[0][1]['after']['name'] or digest(step) != rows[0][1]['after']['stepSha256']:
        raise ValueError('Completed checkpoint differs from boundary anchor')
    from .runner import atomic_json, sha
    from .platform import Backend
    end = time.monotonic() + plan['boundaryBudgetSeconds']
    session.phase('boundary-collection after: ' + step['name'], plan['boundaryBudgetSeconds'] + 15)
    for n, row in rows:
        accounting = session.state['boundaryCollection']
        record = accounting['requests'][n]
        if record['status'] != 'not_run' or record['reason'] != 'Boundary not reached':
            raise ValueError('Boundary requests cannot be replayed')
        remaining = end - time.monotonic()
        if remaining <= .12:
            record['reason'] = 'Shared boundary deadline exhausted before request; never replayed later'
            persist(session)
            continue
        accounting['sequence'] += 1
        sequence = accounting['sequence']
        deadline = min(end, time.monotonic() + row['timeout'])
        record.update(status='started', reason='Request started; no completed evidence yet', sequence=sequence)
        persist(session)
        evidence = {'schemaVersion': 1, 'runId': session.state['id'], 'requestId': row['id'],
                    'sequence': sequence, 'request': copy.deepcopy(row), 'before': identity(session),
                    'hostClock': {'basis': 'python_monotonic_ns; not mapped to native clock',
                                  'startedNs': time.monotonic_ns()},
                    'nativeEvidence': 'Only fields actually returned by providers; missing native identity/phase/clock is unavailable'}
        failure = None
        try:
            Backend(session, deadline).guard_world()
            evidence['response'] = session.tool('platform', copy.deepcopy(row['args']),
                                                timeout=min(12, max(.001, deadline-time.monotonic())), deadline=deadline)
            Backend(session, deadline).guard_world()
            evidence['after'] = identity(session)
            before, after = evidence['before'], evidence['after']
            if (before['game'] != after['game'] or before['executorWorldGeneration'] != after['executorWorldGeneration']):
                raise ValueError('Game/world identity changed during boundary read')
            if time.monotonic() > deadline:
                raise TimeoutError('Boundary response arrived after its absolute deadline')
            record.update(status='response_recorded', reason='Raw response retained; availability and semantic sufficiency are not inferred')
        except Exception as error:
            failure = error
            evidence['error'] = {'type': type(error).__name__, 'message': str(error)}
            if hasattr(error, 'result'):
                evidence['error']['providerResponse'] = error.result
            evidence['after'] = identity(session)
            record.update(status='unavailable', reason='Technical read failed; no retry or next subject action')
        evidence['hostClock']['endedNs'] = time.monotonic_ns()
        evidence['status'] = record['status']
        target = session.dir / ('boundary-' + row['id'] + '.json')
        if target.exists():
            raise ValueError('Boundary evidence path already exists')
        atomic_json(target, evidence)
        record['evidence'] = {'name': target.name, 'sha256': sha(target)}
        persist(session)
        session.log('boundary-observation', requestId=row['id'], status=record['status'], evidence=record['evidence'])
        if failure is not None:
            raise failure


def finalize(session):
    """An interrupted read is unknown, not a response or a success."""
    if 'boundaryCollection' not in session.state:
        return
    for record in session.state['boundaryCollection']['requests']:
        if record['status'] == 'started':
            record.update(status='unavailable', reason='Interrupted after start; completed response was not durably accounted')
            target = session.dir / ('boundary-' + record['id'] + '.json')
            if target.exists():
                from .runner import sha
                record['evidence'] = {'name': target.name, 'sha256': sha(target)}
                record['reason'] += '; uncommitted raw envelope preserved for independent review'
    persist(session)
