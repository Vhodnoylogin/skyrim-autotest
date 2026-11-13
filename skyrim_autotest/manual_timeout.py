"""Read-only evidence after an uncertain manual action; never replay/reconcile it."""
import copy
import time

from . import actor_domain, native


def read_only(request):
    if request.get('operation') == 'finish':
        return True
    if request.get('operation') != 'tool':
        return False
    tool, args = request['tool'], request['args']
    return (tool in ('inspect', 'menu') or tool == 'platform' and
            args.get('operation') in ('state.read', 'player.read', 'world.read', 'menu.read'))


def observe(session, request, deadline):
    """One bounded native sample, with the original game/world/fixture guards.

    Matching race is observed state, not a causal completion receipt. An absent
    or different race cannot prove that a dispatched task will never run later.
    """
    game = copy.deepcopy(session.state.get('game'))
    generation = session.state.get('ownedWorldGeneration')
    result = {'commandOutcome': 'unknown', 'replayed': False, 'game': game,
              'worldGeneration': generation, 'effectObserved': None}
    try:
        if not game or not native.alive(game) or type(generation) is not int or generation < 1:
            raise ValueError('Exact original PID/birth/path is no longer alive')
        args = request.get('args', {})
        subject = args.get('request', {}) if request.get('tool') == 'platform' else request.get('self', {})
        actor = subject.get('actor', subject)
        entry = None
        if isinstance(actor, dict) and 'fixtureTag' in actor:
            entry = session.state.get('interactiveActorFixtures', {}).get(actor['fixtureTag'])
            if entry is None:
                raise ValueError('Original fixture tag has no same-run native creation witness')
        elif isinstance(actor, dict) and set(actor) == {'reference', 'base'}:
            entry = next((row for row in session.state.get('interactiveActorFixtures', {}).values()
                          if row.get('reference') == actor['reference'] and row.get('base') == actor['base']), None)
        if entry is not None:
            entry = copy.deepcopy(entry)
            if (entry.get('runId') != session.state['id'] or entry.get('game') != game or
                    entry.get('worldGeneration') != generation or entry.get('status') != 'created'):
                raise ValueError('Same-run native fixture identity is unavailable')
        query = {'kind': 'world_observer', 'refs': [entry['reference']] if entry else ['0x00000014'],
                 'actors': True, 'timeoutMs': 1000}
        def read(name, values):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Manual result observation deadline expired')
            return session.tool(name, values, timeout=min(2, remaining), deadline=deadline)
        result['scene'] = read('inspect', {'kind': 'scene'})
        raw = read('inspect', query)
        result['nativeObservation'] = raw
        if (session.state.get('game') != game or not native.alive(game) or
                session.state.get('ownedWorldGeneration') != generation):
            raise ValueError('Original game/world changed during manual result observation')
        if entry:
            rows = raw.get('refs', [])
            row = rows[0] if len(rows) == 1 else {}
            ident = row.get('identity', {})
            incarnation = {'sessionId': raw.get('sessionId'), 'loadGeneration': raw.get('loadGeneration'),
                           'runtimeHandle': ident.get('runtimeHandle')}
            current_actor = row.get('actor', {})
            # Session.tool verifies DevBench health PID and native process birth;
            # Observer's actual SE snapshot schema has no mandatory pid field.
            if (raw.get('ok') is not True or ('pid' in raw and raw['pid'] != game['pid']) or
                    type(raw.get('sampleId')) is not int or raw['sampleId'] <= 0 or
                    type(raw.get('producerMonotonicNs')) is not int or raw['producerMonotonicNs'] <= 0 or
                    incarnation != entry.get('incarnation') or ident.get('form') != entry['reference'] or
                    ident.get('loadGeneration') != raw.get('loadGeneration') or
                    row.get('status') != 'available' or row.get('deleted') is not False or
                    row.get('disabled') is not False or row.get('loaded3D') is not True or
                    actor_domain.form(row.get('baseForm')) != entry['base'] or
                    current_actor.get('status') != 'available' or current_actor.get('raceStatus') != 'available' or
                    actor_domain.form(current_actor.get('baseForm')) != entry['base']):
                raise ValueError('Fresh exact native actor/world/incarnation evidence is unavailable')
            result['actor'] = {'reference': entry['reference'], 'base': entry['base'],
                               'race': actor_domain.form(current_actor.get('race')), 'incarnation': incarnation}
            target = subject.get('race') if subject.get('domain') == 'actor-race' else None
            if target:
                result['effectObserved'] = result['actor']['race'] == actor_domain.form(target)
            result['basis'] = 'Fresh native state only; no causal receipt or proof a pending task cannot run later'
    except Exception as error:
        result.update(observationError=str(error), effectObserved=None)
    session.log('interactive-manual-result-observation', **result)
    return result
