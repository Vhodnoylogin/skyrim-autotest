"""Unqualified semantic morph-preset adapter; admission is never application proof."""
import math
from . import actor_domain
from .api_contract import validate_description

SCRIPT = 'CLAWDistributionNative'
READS = {'morph-preset-catalog', 'morph-preset-state'}
ACTIONS = {'assign-morph-preset', 'clear-morph-preset', 'configure-morph-link', 'disable-morph-link', 'refresh-morph-preset'}
SIGNATURES = {
    'GetPresetNames': (['bool'], 'string[]'),
    'GetAssigned': (['actor'], 'string'),
    'GetStatus': (['actor'], 'int'),
    'GetLastError': (['actor'], 'string'),
    'AssignPreset': (['actor', 'string'], 'bool'),
    'ClearOwn': (['actor'], 'bool'),
    'Refresh': (['actor'], 'bool'),
    'ConfigureMorphLink': (['actor', 'string', 'string[]', 'string[]', 'float[]', 'float[]'], 'bool'),
    'DisableMorphLink': (['actor'], 'bool'),
}
STATUS = {0:'unknown', 1:'pending', 2:'coefficients-read-update-requested', 3:'unloaded',
          4:'error', 5:'human', 6:'explicitly-cleared', 7:'provider-unavailable'}


def text(value):
    if (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 160
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Bounded nonempty UTF-8 identifier required')
    return value


def validate(operation, req):
    selector = req.get('quantity') if operation == 'world.read' else req.get('action')
    # Recognized selectors on the wrong operation must not fall through.
    candidate = req.get('quantity') or req.get('action')
    if candidate not in READS | ACTIONS: return False
    if selector != candidate or operation != ('world.read' if candidate in READS else 'object.perform'):
        raise ValueError('Wrong morph-preset operation')
    fields = {'morph-preset-catalog': {'quantity','sex'},
              'morph-preset-state': {'quantity','actor'},
              'assign-morph-preset': {'action','actor','presetName'},
              'clear-morph-preset': {'action','actor'},
              'refresh-morph-preset': {'action','actor'},
              'disable-morph-link': {'action','actor'},
              'configure-morph-link': {'action','actor','profile','rows'}}[candidate]
    if set(req) != fields: raise ValueError('Unsupported/missing morph-preset fields')
    if 'actor' in req: actor_domain.actor_spec(req['actor'])
    if 'sex' in req and req['sex'] not in ('male','female'): raise ValueError('Explicit catalog sex required')
    if 'presetName' in req: text(req['presetName'])
    if 'rows' in req:
        text(req['profile']); rows=req['rows']
        if not isinstance(rows,list) or not 1 <= len(rows) <= 32: raise ValueError('Require1..32 morph rows')
        pairs=set(); caps={}
        for row in rows:
            if not isinstance(row,dict) or set(row) != {'sourceMorph','targetMorph','gain','cap'}:
                raise ValueError('Exact morph-link row required')
            source,target=text(row['sourceMorph']),text(row['targetMorph'])
            if source.startswith('CLAW'): raise ValueError('Own-key feedback source refused')
            for name in ('gain','cap'):
                value=row[name]
                if type(value) not in (int,float) or abs(value)>3.4028234663852886e38 or not math.isfinite(value):
                    raise ValueError('Finite native float required')
            if not 0 < row['cap'] <= 1: raise ValueError('Morph cap must be in(0,1]')
            pair=(source,target)
            if pair in pairs or target in caps and caps[target] != row['cap']:
                raise ValueError('Duplicate rule/inconsistent target cap')
            pairs.add(pair); caps[target]=row['cap']
    return True


def metadata(b, names):
    raw=b.call('papyrus', {'action':'describe','script':SCRIPT})
    checked=validate_description(SCRIPT,raw,'globalFunctions',{n:SIGNATURES[n][0] for n in names})
    for row in checked:
        if row.get('native') is not True or str(row.get('returnType','')).casefold() != SIGNATURES[row['function']][1]:
            raise ValueError('Native morph-preset return signature unavailable')
    return checked


def same_actor(b, observed):
    if actor_domain.anchor(b,observed['actor']['reference'])[0] != observed['incarnation']:
        raise ValueError('Actor incarnation changed across morph-preset request')


def observe(b, req):
    if not validate('world.read',req): raise ValueError('Unknown morph-preset read')
    if req['quantity']=='morph-preset-catalog':
        metadata(b,['GetPresetNames'])
        names=b.pap(SCRIPT,'GetPresetNames',[req['sex']=='female'])
        if not isinstance(names,list) or len(names)>4096: raise ValueError('Native string array unavailable')
        for name in names: text(name)
        if len(set(names)) != len(names): raise ValueError('Duplicate catalog names')
        return {'catalog':{'sex':req['sex'],'presetNames':names,'emptyAvailabilityUnknown':not names},
                'basis':'Actual native string-array return; empty result cannot distinguish unavailable catalog'}
    metadata(b,['GetAssigned','GetStatus','GetLastError'])
    observed=actor_domain.observe_actor(b,req['actor']); actor={'form':observed['actor']['reference']}
    assigned=b.pap(SCRIPT,'GetAssigned',[actor]); status=b.pap(SCRIPT,'GetStatus',[actor]); error=b.pap(SCRIPT,'GetLastError',[actor])
    if not isinstance(assigned,str) or not isinstance(error,str) or type(status) is not int or status not in STATUS:
        raise ValueError('Native preset state types unavailable')
    same_actor(b,observed)
    observed['preset']={'name':assigned,'status':status,'statusName':STATUS[status],'lastError':error}
    observed['basis']='Sequential native subject state, not atomic or independent rendering proof'
    return observed


def perform(b, req):
    if not validate('object.perform',req): raise ValueError('Unknown morph-preset action')
    fn={'assign-morph-preset':'AssignPreset','clear-morph-preset':'ClearOwn',
        'configure-morph-link':'ConfigureMorphLink','disable-morph-link':'DisableMorphLink',
        'refresh-morph-preset':'Refresh'}[req['action']]
    metadata(b,[fn])
    observed=actor_domain.observe_actor(b,req['actor'])
    if observed['actor']['loaded3D'] is not True: raise ValueError('Loaded actor required')
    args=[{'form':observed['actor']['reference']}]
    if fn=='AssignPreset': args.append(req['presetName'])
    if fn=='ConfigureMorphLink':
        rows=req['rows']; args.extend([req['profile'],[r['sourceMorph'] for r in rows],
            [r['targetMorph'] for r in rows],[float(r['gain']) for r in rows],[float(r['cap']) for r in rows]])
    admitted=b.pap(SCRIPT,fn,args)  # Mutation exactly once; unknown outcomes never replay.
    if type(admitted) is not bool: raise ValueError('Native queue-admission boolean unavailable')
    same_actor(b,observed)
    observed['action']={'admitted':admitted}
    observed['basis']='Queue admission only; separately read state and independent keyed SKEE coefficients'
    b.s.log('platform-morph-preset-admission',request=req,admitted=admitted)
    return observed
