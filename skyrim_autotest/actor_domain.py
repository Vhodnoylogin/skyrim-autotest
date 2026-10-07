"""Candidate actor/base/morph adapter. Native readback, never command ACKs."""
import math
import re

READS = {'actor-base-identity', 'actor-base-weight', 'body-morph-storage'}
ACTIONS = {'set-race', 'set-sex', 'set-weight', 'set-body-morph', 'update-body-model'}


def form(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,8}', value):
        raise ValueError('Actor domain requires explicit hexadecimal form identity')
    number = int(value, 16)
    if not number: raise ValueError('Null actor identity')
    return f'0x{number:08X}'


def actor_spec(value):
    if not isinstance(value, dict) or set(value) != {'reference', 'base'}:
        raise ValueError('Actor requires exact reference and base')
    return {key: form(value[key]) for key in ('reference', 'base')}


def bounded(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Actor numeric value unavailable or out of bounds')
    return value


def validate(operation, req):
    selector = req.get('quantity') if operation == 'world.read' else req.get('action')
    if selector not in READS | ACTIONS: return False
    if operation != ('world.read' if selector in READS else 'object.perform'):
        raise ValueError('Wrong operation for actor selector')
    required = {
        'actor-base-identity': {'quantity', 'record'},
        'actor-base-weight': {'quantity', 'actor'},
        'body-morph-storage': {'quantity', 'actor', 'morph', 'key'},
        'set-race': {'action', 'actor', 'race'},
        'set-sex': {'action', 'actor', 'sex'},
        'set-weight': {'action', 'actor', 'weight', 'units'},
        'set-body-morph': {'action', 'actor', 'morph', 'key', 'value', 'units'},
        'update-body-model': {'action', 'actor'},
    }[selector]
    if set(req) != required: raise ValueError('Unsupported/missing actor request fields')
    if 'actor' in req: actor_spec(req['actor'])
    if 'record' in req:
        record = req['record']
        if (not isinstance(record, dict) or set(record) != {'plugin', 'localFormId'} or
                not isinstance(record['plugin'], str) or
                not re.fullmatch(r'[A-Za-z0-9 _.-]+\.(esm|esp)', record['plugin'], re.I) or
                int(form(record['localFormId']), 16) > 0xFFFFFF):
            raise ValueError('Actor base record requires plugin and local form ID')
    if 'race' in req: form(req['race'])
    if 'sex' in req and req['sex'] not in ('male', 'female'): raise ValueError('Unknown actor sex')
    if selector == 'set-sex' and actor_spec(req['actor'])['reference'] != '0x00000014':
        raise ValueError('Native sex toggle currently qualified only for disposable player')
    for key in ('morph', 'key'):
        if key in req and (not isinstance(req[key], str) or not re.fullmatch(r'[A-Za-z0-9 _.-]{1,96}', req[key])):
            raise ValueError('Invalid morph/key name')
    if 'weight' in req:
        bounded(req['weight'], 0, 100)
        if req['units'] != 'Skyrim actor-base weight 0..100': raise ValueError('Wrong weight units')
    if 'value' in req:
        bounded(req['value'], -10, 10)
        if req['units'] != 'dimensionless morph coefficient': raise ValueError('Wrong morph units')
    return True


def returned_form(value):
    if not isinstance(value, dict): raise ValueError('Native form result unavailable')
    return form(value.get('formId'))


def anchor(b, ref):
    raw = b.call('inspect', {'kind': 'world_observer', 'refs': [ref]})
    rows = raw.get('refs', [])
    if raw.get('ok') is not True or len(rows) != 1: raise ValueError('Actor observer unavailable')
    row = rows[0]; ident = row.get('identity', {})
    if (row.get('status') != 'available' or row.get('deleted') is not False or
            row.get('disabled') is not False or form(ident.get('form')) != ref or
            type(row.get('loaded3D')) is not bool or
            type(ident.get('runtimeHandle')) is not int or ident['runtimeHandle'] <= 0 or
            type(raw.get('loadGeneration')) is not int or ident.get('loadGeneration') != raw['loadGeneration'] or
            not isinstance(raw.get('sessionId'), str) or not raw['sessionId']):
        raise ValueError('Actor incarnation/session/generation unavailable')
    return {'sessionId': raw['sessionId'], 'loadGeneration': raw['loadGeneration'],
            'runtimeHandle': ident['runtimeHandle']}, row, raw


def base_state(b, base):
    sex = b.pap('ActorBase', 'GetSex', target=base)
    if type(sex) is not int or sex not in (0, 1): raise ValueError('Native actor-base sex unavailable')
    race = returned_form(b.pap('ActorBase', 'GetRace', target=base))
    weight = bounded(b.pap('ActorBase', 'GetWeight', target=base), 0, 100)
    return {'sex': ('male', 'female')[sex], 'race': race, 'weight': weight}


def observe_actor(b, spec):
    spec = actor_spec(spec); ref = spec['reference']
    before, row, raw = anchor(b, ref)
    base = returned_form(b.pap('Actor', 'GetActorBase', target=ref))
    if base != spec['base']: raise ValueError('Observed actor base differs from required identity')
    result = dict(reference=ref, base=base, loaded3D=row['loaded3D'], **base_state(b, base))
    # Actor race can differ from its base during transformations.
    result['race'] = returned_form(b.pap('Actor', 'GetRace', target=ref))
    after, final_row, final = anchor(b, ref)
    if before != after: raise ValueError('Actor incarnation changed across native observation')
    result['loaded3D'] = row['loaded3D'] and final_row['loaded3D']
    b.s.log('platform-actor-observation', actor=result, incarnation=after,
            sampleId=final.get('sampleId'), atomicSnapshot=False)
    return {'actor': result, 'incarnation': after, 'providerObservation': raw}


def observe(b, req):
    kind = req['quantity']
    if kind == 'actor-base-identity':
        spec = req['record']
        base = b.resolve({'plugin': spec['plugin'], 'localId': f'{int(spec["localFormId"],16):06X}'})
        return {'actorBase': dict(base=base, **base_state(b, base))}
    result = observe_actor(b, req['actor'])
    if kind == 'body-morph-storage':
        value = b.pap('NiOverride', 'GetBodyMorph', [{'form': result['actor']['reference']}, req['morph'], req['key']])
        bounded(value, -1000000, 1000000)
        if anchor(b, result['actor']['reference'])[0] != result['incarnation']:
            raise ValueError('Actor incarnation changed across morph read')
        result['morph'] = {'value': value}
    return result


def perform(b, req):
    before = observe_actor(b, req['actor']); actor = before['actor']
    if actor['loaded3D'] is not True: raise ValueError('Actor mutation requires loaded 3D')
    ref, base = actor['reference'], actor['base']; action = req['action']
    if action == 'set-race':
        b.pap('Actor', 'SetRace', [{'form': form(req['race'])}], ref)
    elif action == 'set-sex' and actor['sex'] != req['sex']:
        receipt = b.call('console', {'action': 'exec', 'command': 'player.sexchange', 'capture': True})
        if receipt.get('completed') is not True or receipt.get('queued') is not False:
            raise ValueError('Sex-change native execution fence unavailable; never replay')
    elif action == 'set-weight':
        b.pap('ActorBase', 'SetWeight', [float(req['weight'])], base)
    elif action == 'set-body-morph':
        b.pap('NiOverride', 'SetBodyMorph', [{'form': ref}, req['morph'], req['key'], float(req['value'])])
    elif action == 'update-body-model':
        b.pap('NiOverride', 'UpdateModelWeight', [{'form': ref}])
    # Repeated reads only. The mutation above is executed at most once.
    while True:
        result = observe_actor(b, req['actor']); now = result['actor']
        if result['incarnation'] != before['incarnation']:
            raise ValueError('Actor incarnation changed during mutation')
        matched = now['loaded3D'] is True
        if action == 'set-race': matched &= now['race'] == form(req['race'])
        if action == 'set-sex': matched &= now['sex'] == req['sex']
        if action == 'set-weight': matched &= abs(now['weight'] - req['weight']) <= 1e-6
        if action == 'set-body-morph':
            value = b.pap('NiOverride', 'GetBodyMorph', [{'form': ref}, req['morph'], req['key']])
            bounded(value, -1000000, 1000000)
            matched &= abs(value - req['value']) <= 1e-6
            result['morph'] = {'value': value}
            if anchor(b, ref)[0] != before['incarnation']:
                raise ValueError('Actor incarnation changed across morph mutation readback')
        if matched:
            result['action'] = {'completed': True}
            result['completionBasis'] = ('Native Papyrus callback and loaded actor readback; model update is function completion, not renderer/mesh deformation proof')
            b.s.log('platform-actor-action-completed', request=req, observation=result)
            return result
        b.pause(.2)
