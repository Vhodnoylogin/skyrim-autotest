"""Generic pinned actor scenes, owned fixture actions and bounded native capture."""
import copy
import math
import re
import time
import uuid
from .actor_domain import form, bounded

READS={'actor.scene','scene.node','actor.skeleton_physics','actor.contact_capture','actor.contacts'}
ACTIONS={'prepare_fixture_actor','set_fixture_actor_movement','push_fixture_actor'}
JOINTS={'NPC L Thigh [LThg]':'leftThigh','NPC R Thigh [RThg]':'rightThigh'}


def selector(spec):
    if (not isinstance(spec,dict) or set(spec)!={'plugin','localId'} or
        not isinstance(spec['plugin'],str) or not re.fullmatch(r'[A-Za-z0-9 _.-]+\.(esp|esm)',spec['plugin'],re.I) or
        not isinstance(spec['localId'],str) or not re.fullmatch(r'[0-9a-fA-F]{1,6}',spec['localId']) or int(spec['localId'],16)==0):
        raise ValueError('Actor scene requires exact plugin and nonzero localId')
    return spec['plugin'].lower()+':'+f'{int(spec["localId"],16):06X}'


def validate(operation,req):
    kind=req.get('observation') if operation=='world.read' else req.get('action')
    if kind not in READS|ACTIONS:return False
    if operation!=('world.read' if kind in READS else 'object.perform'):raise ValueError('Wrong actor scene operation')
    keys={'actor.scene':{'observation','actor'},'scene.node':{'observation','actor','nodeName','perspective'},
          'actor.skeleton_physics':{'observation','actor','nodeNames','perspective'},
          'actor.contact_capture':{'observation','actor','afterSequence','captureWindowSeconds','maximumSamples'},
          'actor.contacts':{'observation','actor','afterSequence','maximumSamples'},
          'prepare_fixture_actor':{'action','actor','equipment','expectedScale','expectedWeightPercent','movement'},
          'set_fixture_actor_movement':{'action','actor','movement'},
          'push_fixture_actor':{'action','source','target','strength'}}[kind]
    if set(req)!=keys:raise ValueError('Unsupported/missing actor scene request fields')
    selector(req.get('actor',req.get('target')))
    if 'perspective' in req and req['perspective']!='third-person':raise ValueError('Actor scene requires explicit third-person')
    names=[req['nodeName']] if 'nodeName' in req else req.get('nodeNames',[])
    if 'nodeNames' in req and (not isinstance(names,list) or not 1<=len(names)<=16):
        raise ValueError('Actor nodes require1..16unique names')
    if any(not isinstance(n,str) or not 1<=len(n.encode('utf-8'))<=128 or '\0' in n for n in names):raise ValueError('Invalid node name')
    if len(set(names))!=len(names):raise ValueError('Actor node names must be unique')
    if 'maximumSamples' in req and (type(req['maximumSamples']) is not int or not 1<=req['maximumSamples']<=256):raise ValueError('Contact sample limit outside1..256')
    if 'afterSequence' in req and (type(req['afterSequence']) is not int or not 0<=req['afterSequence']<=2**64-1):raise ValueError('Invalid contact cursor')
    if 'captureWindowSeconds' in req:
        seconds=bounded(req['captureWindowSeconds'],.1,60)
        if abs(seconds*1000-round(seconds*1000))>1e-6:raise ValueError('Capture window requires whole milliseconds')
    if 'movement' in req and req['movement'] not in ('enabled','disabled'):raise ValueError('Explicit fixture movement policy required')
    if kind=='prepare_fixture_actor':
        if req['equipment']!='unequip_all':raise ValueError('Unsupported fixture equipment policy')
        bounded(req['expectedScale'],.1,3);bounded(req['expectedWeightPercent'],0,100)
        if abs(req['expectedScale']*100-round(req['expectedScale']*100))>1e-6:raise ValueError('Native reference scale requires whole percent')
    if kind=='push_fixture_actor':
        if req['source']!='player':raise ValueError('Only player-origin fixture push supported')
        bounded(req['strength'],.01,10)
    return True


def snapshot(b,spec,nodes=(),physics=None,details=False):
    key=selector(spec);b.guard_world();ref=form(b.resolve(spec))
    args={'kind':'world_observer','refs':[ref]}
    if nodes:args['nodes']=[{'ref':ref,'name':n,'firstPerson':False} for n in nodes]
    if physics is not None:args['physics']={'refs':[ref],**physics}
    if details:args['actorState']=True
    raw=b.call('inspect',args)
    if (not isinstance(raw,dict) or raw.get('ok') is not True or raw.get('phase')!='skse_main_thread_task' or
        not isinstance(raw.get('sessionId'),str) or not raw['sessionId'] or
        type(raw.get('loadGeneration')) is not int or raw['loadGeneration']<=0 or
        not isinstance(raw.get('refs'),list) or len(raw['refs'])!=1):raise ValueError('Actor native scene unavailable')
    row=raw['refs'][0]
    if not isinstance(row,dict) or not isinstance(row.get('identity'),dict):raise ValueError('Actor native identity unavailable')
    identity=row['identity']
    if (row.get('status')!='available' or row.get('deleted') is not False or row.get('disabled') is not False or
        type(row.get('loaded3D')) is not bool or form(identity.get('form'))!=ref or
        type(identity.get('loadGeneration')) is not int or identity['loadGeneration']!=raw['loadGeneration'] or
        type(identity.get('runtimeHandle')) is not int or identity['runtimeHandle']<=0 or
        not isinstance(identity.get('sourcePlugin'),str) or identity['sourcePlugin'].lower()!=spec['plugin'].lower() or
        not isinstance(identity.get('localFormId'),str) or not re.fullmatch(r'0x[0-9A-Fa-f]{1,8}',identity['localFormId']) or
        int(identity['localFormId'],16)!=int(spec['localId'],16)):
        raise ValueError('Exact actor plugin/reference/incarnation unavailable')
    incarnation={'sessionId':raw['sessionId'],'loadGeneration':raw['loadGeneration'],'runtimeHandle':identity['runtimeHandle']}
    old=b.s.state.setdefault('sceneActorIncarnations',{}).get(key)
    if old is not None and old!=incarnation:raise ValueError('Actor scene incarnation changed')
    b.guard_world();b.s.state['sceneActorIncarnations'][key]=incarnation;b.s.save()
    actor={'reference':ref,'loaded3D':row['loaded3D'],'identity':{'plugin':identity['sourcePlugin'],
           'localId':f'{int(identity["localFormId"],16):06X}','runtimeId':ref},'incarnation':incarnation}
    return actor,row,raw


def node(raw,ref,name):
    rows=[r for r in raw.get('nodes',[]) if r.get('name')==name and r.get('firstPerson') is False and form(r.get('form'))==ref]
    if len(rows)!=1:raise ValueError('Exact requested actor node outcome unavailable')
    row=rows[0]
    if row.get('status')!='available':return {'available':False,'reason':row.get('reason','Node unavailable')}
    ident=row.get('identity',{});owner=raw['refs'][0]['identity']
    if ident!=owner:raise ValueError('Actor node incarnation differs from reference')
    bound=row.get('worldBound',{});radius=bounded(bound.get('radius'),0,1e12);centre=bound.get('center')
    if not isinstance(centre,list) or len(centre)!=3:raise ValueError('Native node bound center unavailable')
    for v in centre:bounded(v,-1e12,1e12)
    if raw.get('space')!='world' or raw.get('units')!='skyrim_engine_units':raise ValueError('Actor node space/units unavailable')
    world=row.get('world',{})
    if not isinstance(world,dict) or set(world)!={'translation','rotationRowMajor','scale'}:raise ValueError('Native node transform unavailable')
    for field,length in (('translation',3),('rotationRowMajor',9)):
        values=world[field]
        if not isinstance(values,list) or len(values)!=length:raise ValueError('Native node transform shape unavailable')
        for v in values:bounded(v,-1e12,1e12)
    bounded(world['scale'],0,1e12)
    return {'available':True,'name':name,'worldTransform':copy.deepcopy(row['world']),
            'worldBound':{'radius':{'gameUnits':radius},'center':{'gameUnits':centre}},
            'basis':'actual engine NiAVObject worldBound; not file bounds/collision geometry/render visibility'}


def observe(b,req):
    kind=req['observation'];spec=req['actor']
    if kind in ('actor.contact_capture','actor.contacts'):return contacts(b,req)
    nodes=[req['nodeName']] if kind=='scene.node' else req.get('nodeNames',[])
    actor,row,raw=snapshot(b,spec,nodes,{} if kind=='actor.skeleton_physics' else None,details=kind=='actor.scene')
    if kind=='actor.scene' and row.get('actorState',{}).get('status')!='available':raise ValueError('Actual actor state unavailable')
    result={'actor':actor,'providerObservation':raw,'atomicPhysicsSceneSnapshot':False}
    if kind=='scene.node':result['scene']={'node':node(raw,actor['reference'],nodes[0])}
    if kind=='actor.skeleton_physics':
        physics=raw.get('physics',{});result['physics']=physics;result['skeleton']={'nodes':{}}
        for name in nodes:
            part={'node':node(raw,actor['reference'],name),'bodies':[v for v in physics.get('bodies',[]) if v.get('node')==name and form(v.get('form'))==actor['reference']],
                  'bodyMappingBasis':'exact native source node name only; absent body mapping is unavailable'}
            result['skeleton']['nodes'][name]=part
            if name in JOINTS:result['skeleton'][JOINTS[name]]=part
    return result


def owned(b,spec):
    from .config import P
    key=selector(spec)
    if key not in [selector(v) for v in P.value.get('fixture_actor_allowlist',[])]:raise ValueError('Actor is not explicitly allowed as disposable fixture')
    if not b.s.state.get('testProfile') or not b.s.state.get('gameplayBootstrap',{}).get('completed'):
        raise ValueError('Fixture actor mutation requires owned disposable gameplay profile')
    actor,row,raw=snapshot(b,spec,details=True)
    if int(actor['reference'],16)==0x14 or not actor['loaded3D']:raise ValueError('Fixture actor must be loaded non-player')
    status=row.get('actorState',{})
    if (status.get('status')!='available' or type(status.get('restrained')) is not bool or
        not isinstance(status.get('wornForms'),list) or len(status['wornForms'])>256 or
        type(status.get('lifeState')) is not int or type(status.get('knockState')) is not int or
        any(k not in status for k in ('equippedLeft','equippedRight'))):
        raise ValueError('Native fixture actor/equipment/movement readback unavailable')
    for v in status['wornForms']+[status['equippedLeft'],status['equippedRight']]:
        if v is not None:form(v)
    if status['restrained'] is not (status['lifeState']==6):raise ValueError('Inconsistent native actor restraint state')
    return actor,row,raw


def perform(b,req):
    spec=req.get('actor',req.get('target'));actor,row,raw=owned(b,spec);ref=actor['reference'];action=req['action']
    if action=='prepare_fixture_actor':
        if row['actorState']['lifeState'] not in (0,6):raise ValueError('Fixture actor is not alive/restrained')
        base=b.pap('Actor','GetActorBase',target=ref)
        if not isinstance(base,dict):raise ValueError('Native actor base unavailable')
        base=form(base.get('formId'))
        if base!=form(row.get('baseForm')):raise ValueError('Actor base changed across fixture preparation')
        expected_reference_percent=round(req['expectedScale']*100)
        before_effective=bounded(row.get('scale'),.001,100)
        before_weight=bounded(b.pap('ActorBase','GetWeight',target=base),0,100)
        if type(row['actorState'].get('referenceScalePercent')) is not int:
            raise ValueError('Native reference scale percent unavailable; effective scale is a different quantity')
        if row['actorState']['referenceScalePercent']!=expected_reference_percent or abs(before_weight-req['expectedWeightPercent'])>1e-6:
            raise ValueError('Fixture initial weight/reference scale differs; preparation never rewrites them')
        b.pap('Actor','SetRestrained',[req['movement']=='disabled'],ref)
        b.pap('Actor','UnequipAll',target=ref)
    elif action=='set_fixture_actor_movement':b.pap('Actor','SetRestrained',[req['movement']=='disabled'],ref)
    else:
        b.pap('ObjectReference','PushActorAway',[{'form':ref},float(req['strength'])],'0x14')
    # Every mutation above is issued once. Only bounded state reads may repeat.
    while True:
        now,current,final=owned(b,spec)
        if now['incarnation']!=actor['incarnation']:raise ValueError('Actor changed across fixture mutation')
        state=current['actorState'];fixture={}
        if action=='push_fixture_actor':
            fixture={'pushCompleted':True,'completionBasis':'native Papyrus callback and same live target; not proof of displacement/contact/solver effect'}
            matched=True
        else:
            matched=state['restrained'] is (req['movement']=='disabled')
            fixture={'movementEnabled':not state['restrained'],'movementBasis':'actual native restrained life state; not a promise against external physics'}
            if action=='prepare_fixture_actor':
                weight=bounded(b.pap('ActorBase','GetWeight',target=base),0,100)
                effective=bounded(current.get('scale'),.001,100)
                percent=state.get('referenceScalePercent')
                if type(percent) is not int:raise ValueError('Native fixture reference scale percent unavailable')
                scale=percent/100.
                matched &= not state['wornForms'] and state['equippedLeft'] is None and state['equippedRight'] is None
                if (form(current.get('baseForm'))!=base or percent!=expected_reference_percent or
                    abs(weight-before_weight)>1e-6 or abs(effective-before_effective)>1e-6):
                    raise ValueError('Fixture weight/reference/effective scale changed during equipment/movement preparation')
                fixture.update(prepared=bool(matched),weightPercent=weight,scale=scale,referenceScalePercent=percent,
                               effectiveScale=effective,scaleBasis='actual native reference percent; effective actor scale retained separately',
                               weightAndScalesUnchanged=True,wornForms=state['wornForms'])
        if matched:
            b.guard_world();return {'fixture':{'actor':fixture},'actor':now,'providerObservation':final}
        b.pause(.1)


def persist(s):
    from .runner import atomic_json
    atomic_json(s.dir/'actor-captures.json',{'schemaVersion':1,'runId':s.state['id'],'captures':s.state.get('actorCaptures',{})})
    s.save()


def record(b,entry,raw):
    from .runner import atomic_json,sha
    number=len(entry.setdefault('reads',[]))+1
    path=b.s.dir/f'actor-capture-{entry["id"]}-{number:03}.json'
    atomic_json(path,raw);entry['reads'].append({'name':path.name,'sha256':sha(path)})
    persist(b.s)


def contacts(b,req):
    key=selector(req['actor']);records=b.s.state.setdefault('actorCaptures',{})
    if req['observation']=='actor.contact_capture':
        if key in records:raise ValueError('Actor capture already attempted; never replay')
        cap=b.call('inspect',{'kind':'world_observer','action':'capabilities'})
        if cap.get('physics',{}).get('boundedCapture') is not True:
            return {'physics':{'capture':{'available':False,'reason':'Native bounded capture provider unavailable'}}}
        entry={'id':uuid.uuid4().hex,'status':'starting','actor':copy.deepcopy(req['actor']),
               'maximumSamples':req['maximumSamples'],'afterSequence':req['afterSequence'],
               'windowSeconds':req['captureWindowSeconds'],'hostDeadline':time.monotonic()+req['captureWindowSeconds']+3}
        records[key]=entry;persist(b.s)
        args={'captureAction':'start','captureId':entry['id'],'captureWindowMs':round(req['captureWindowSeconds']*1000),
              'afterSequence':req['afterSequence'],'maximumSamples':req['maximumSamples']}
    else:
        entry=records.get(key)
        if not entry or entry['status'] not in ('active','finished'):raise ValueError('Actor capture is not available; read never starts/rearms it')
        if req['maximumSamples']!=entry['maximumSamples'] or req['afterSequence']<entry['afterSequence']:raise ValueError('Capture read bounds/cursor differ')
        args={'captureAction':'read','captureId':entry['id'],'afterSequence':req['afterSequence'],'maximumSamples':req['maximumSamples']}
    try:
        actor,row,raw=snapshot(b,req['actor'],physics=args);record(b,entry,raw)
    except Exception as error:
        entry['status']='unavailable';entry['reason']=str(error);persist(b.s)
        raise
    domain=raw.get('physics',{});native=domain.get('capture') or {}
    coverage=domain.get('coverage',{})
    valid=(domain.get('status') in ('available','partial') and domain.get('contactPhase')=='havok_contact_point_callback' and
           type(domain.get('worldId')) is int and domain['worldId']>0 and
           type(coverage.get('subscriptionEpoch')) is int and coverage['subscriptionEpoch']>0 and
           native.get('id')==entry['id'] and native.get('readExtendedLease') is False and
           type(native.get('windowComplete')) is bool and type(native.get('bodySelectionChanged')) is bool and
           type(native.get('startedNs')) is int and type(native.get('endNs')) is int and
           native['endNs']-native['startedNs']==round(entry['windowSeconds']*1000)*1000000 and
           type(domain.get('sampleMonotonicNs')) is int and
           native['windowComplete'] is (domain['sampleMonotonicNs']>=native['endNs']) and
           coverage.get('armedFromNs')==native['startedNs'] and coverage.get('armedUntilNs')==native['endNs'])
    identity={'actor':actor['incarnation'],'worldId':domain.get('worldId'),'subscriptionEpoch':domain.get('coverage',{}).get('subscriptionEpoch')}
    if entry.get('identity') is not None and entry['identity']!=identity:raise ValueError('Capture session/world/epoch changed')
    if valid:
        if req['observation']=='actor.contact_capture':
            # A conservative host scheduling bound from the received start, not
            # a claimed mapping between Python's and the producer's clocks.
            entry['hostDeadline']=time.monotonic()+entry['windowSeconds']+.5
        entry['identity']=identity;entry['status']='finished' if native.get('windowComplete') is True else 'active'
    else:entry['status']='unavailable'
    persist(b.s)
    values=domain.get('contacts',[])
    if not isinstance(values,list) or len(values)>entry['maximumSamples']:raise ValueError('Native contact sample bounds unavailable')
    initial=native.get('initialBodies',[])
    watched={v['bodyUid'] for v in initial if isinstance(v,dict) and v.get('status')=='available' and
             v.get('form')==actor['reference'] and v.get('worldId')==domain.get('worldId') and type(v.get('bodyUid')) is int}
    if valid and (not watched or len(watched)!=len(initial)):raise ValueError('Initial native capture body mapping unavailable')
    last=req['afterSequence']
    for v in values:
        if (not isinstance(v,dict) or v.get('status')!='available' or type(v.get('sequence')) is not int or v['sequence']<=last or
            v.get('worldId')!=domain.get('worldId') or v.get('loadGeneration')!=raw['loadGeneration'] or
            type(v.get('producerMonotonicNs')) is not int or not valid or
            not native['startedNs']<=v['producerMonotonicNs']<native['endNs'] or
            v.get('phase')!='havok_contact_point_callback' or
            type(v.get('bodyA')) is not int or type(v.get('bodyB')) is not int or
            not ({v['bodyA'],v['bodyB']}&watched)):
            raise ValueError('Native contact provenance/sequence/body/window unavailable')
        bounded(v.get('signedSeparation'),-1e12,1e12)
        for name in ('position','normalBtoA'):
            if not isinstance(v.get(name),list) or len(v[name])!=3:raise ValueError('Native contact vector unavailable')
            for n in v[name]:bounded(n,-1e12,1e12)
        if type(v.get('speculative')) is not bool or v['speculative'] is not (v['signedSeparation']>0):raise ValueError('Native speculative contact status unavailable')
        if v.get('disabled') is not None and type(v['disabled']) is not bool:raise ValueError('Native disabled contact status unavailable')
        last=v['sequence']
    sample_available=(valid and native.get('bodySelectionChanged') is False and bool(values) and
                      not coverage.get('cursorAhead',True))
    conversion=domain.get('sceneUnitConversion',{});samples=[]
    if conversion.get('status')=='available':
        forward=bounded(conversion.get('havokUnitsPerGameUnit'),1e-12,1e12)
        inverse=bounded(conversion.get('gameUnitsPerHavokUnit'),1e-12,1e12)
        if abs(forward*inverse-1)>=.001:raise ValueError('Native physics unit conversion inconsistent')
    for value in values:
        item=copy.deepcopy(value)
        if conversion.get('status')=='available' and type(value.get('signedSeparation')) in (int,float):
            item['signedSeparationGameUnits']=value['signedSeparation']*conversion['gameUnitsPerHavokUnit']
        samples.append(item)
    return {'actor':actor,'physics':{'capture':{'available':valid,'windowComplete':native.get('windowComplete',False),
        'native':native,'requestedWindowSeconds':entry['windowSeconds'],'reason':domain.get('reason')},
        'contacts':{'sample':{'available':sample_available,'phase':'havok_contact_point_callback' if sample_available else None},
                    'samples':samples,'coverage':coverage,'units':domain.get('units'),'sceneUnitConversion':conversion,
                    'sampleLimitTruncated':domain.get('sampleLimitTruncated'),'absenceProven':False,'solverUseProven':False}},
        'providerObservation':raw}


def finish_captures(session):
    from .platform import Backend
    for entry in session.state.get('actorCaptures',{}).values():
        if entry['status']!='active':continue
        session.phase('finish bounded native contact capture',max(1,entry['hostDeadline']-time.monotonic())+15)
        while time.monotonic()<entry['hostDeadline']:
            from . import native
            if session.heartbeat_failed.is_set() or not native.alive(session.state.get('game')):
                raise ValueError('Game/heartbeat ended during bounded capture')
            time.sleep(max(0,min(.5,entry['hostDeadline']-time.monotonic())))
        response=contacts(Backend(session,time.monotonic()+10),{'observation':'actor.contacts','actor':entry['actor'],
                           'afterSequence':entry['afterSequence'],'maximumSamples':entry['maximumSamples']})
        if response['physics']['capture']['windowComplete'] is not True or entry['status']!='finished':
            raise ValueError('Bounded native capture did not finish its requested window')
        session.log('actor-contact-capture-finished',captureId=entry['id'],windowSeconds=entry['windowSeconds'],
                    completeWindow=True,absenceProven=False,solverUseProven=False)


def collect(session,copy_file):
    records=session.state.get('actorCaptures',{})
    if not records:return
    for entry in records.values():
        if entry['status'] in ('active','starting'):
            entry['status']='interrupted';entry['reason']='Executor ended before complete bounded native capture; no absence/complete-window claim'
    persist(session)
    copy_file(session.dir/'actor-captures.json','actor-captures.json','actor-contact-capture',True)
    from .runner import sha
    for entry in records.values():
        for value in entry.get('reads',[]):
            if not re.fullmatch(r'actor-capture-'+re.escape(entry['id'])+r'-[0-9]{3,}\.json',value['name']):
                raise ValueError('Capture evidence path unavailable')
            path=session.dir/value['name']
            if sha(path)!=value['sha256']:raise ValueError('Capture raw evidence changed')
            copy_file(path,path.name,'actor-contact-capture',True)
