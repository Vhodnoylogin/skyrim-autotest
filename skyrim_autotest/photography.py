"""Generic disposable NPC photography. Source support is not live qualification.

All engine mutations execute once after durable intent. Metadata is measured;
provider-eye equivalence and rendered visibility need separate live qualification.
"""
import copy
import hashlib
import math
from pathlib import Path
import re
import time

from .actor_domain import anchor, base_state, bounded, form, returned_form
from .actor_scene import selector

ACTIONS = {'create_fixture_actor', 'configure_fixture_actor', 'set_fixture_body_morphs',
           'update_fixture_body_model', 'clear_fixture_body_morph_key', 'frame_fixture_actor',
           'capture_fixture_photo', 'restore_fixture_photography_state'}
READS = {'fixture-actor-state', 'fixture-body-morphs'}


def name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,79}', value):
        raise ValueError('Unique single-segment photography tag required')
    return value


def morph_name(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9 _.-]{1,96}', value):
        raise ValueError('Invalid morph/key name')


def actor_selector(value):
    if not isinstance(value, dict) or set(value) != {'referenceTag'}:
        raise ValueError('Photography actor requires exact referenceTag')
    name(value['referenceTag'])


def validate(operation, req):
    kind = req.get('action', req.get('observation'))
    if kind not in ACTIONS | READS: return False
    if operation != ('world.read' if kind in READS else 'object.perform'):
        raise ValueError('Wrong photography operation')
    fields = {
        'create_fixture_actor': {'action','actorBase','referenceTag','placement','scope','onUncertainCompletion'},
        'configure_fixture_actor': {'action','actor','movement','aiEnabled','aggression','combat','collisionPolicy'},
        'set_fixture_body_morphs': {'action','actor','key','values','units','otherKeys'},
        'update_fixture_body_model': {'action','actor'},
        'clear_fixture_body_morph_key': {'action','actor','key'},
        'frame_fixture_actor': {'action','actor','framing'},
        'capture_fixture_photo': {'action','actor','photoId','format','minimumWidthPixels','minimumHeightPixels',
                                 'configuration','requireActualMetadata','settleSeconds','qualityPolicy'},
        'restore_fixture_photography_state': {'action','scope','restore','leavePhysicsEnabled'},
        'fixture-actor-state': {'observation','actor'},
        'fixture-body-morphs': {'observation','actor','key','morphs'},
    }[kind]
    if set(req) != fields: raise ValueError('Unsupported/missing photography fields')
    if 'actor' in req: actor_selector(req['actor'])
    if 'scope' in req and req['scope'] != 'owned-disposable-profile': raise ValueError('Disposable scope required')
    if 'key' in req: morph_name(req['key'])
    if kind == 'create_fixture_actor':
        selector(req['actorBase']); name(req['referenceTag'])
        p=req['placement']
        if not isinstance(p,dict) or set(p)!={'basis','forwardGameUnits','rightGameUnits'} or p['basis']!='player-horizontal-forward':
            raise ValueError('Explicit horizontal player-relative placement required')
        bounded(p['forwardGameUnits'],100,2000);bounded(p['rightGameUnits'],-2000,2000)
        if req['onUncertainCompletion']!='stop-without-replay':raise ValueError('Uncertain creation must stop')
    if kind == 'configure_fixture_actor':
        if (req['movement']!='disabled' or req['aiEnabled'] is not True or type(req['aggression']) is not int or
            req['aggression']!=0 or req['combat']!='stopped' or req['collisionPolicy']!='preserve-enabled'):
            raise ValueError('Stationary photography preserves enabled AI/collisions and stops combat')
    if kind == 'set_fixture_body_morphs':
        values(req['values'])
        if req['units']!='dimensionless morph coefficient' or req['otherKeys']!='preserve':raise ValueError('Key-scoped morph units/policy required')
    if kind == 'fixture-body-morphs':
        names=req['morphs']
        if not isinstance(names,list) or not 1<=len(names)<=64 or len(set(names))!=len(names):raise ValueError('1..64unique morph names required')
        for v in names:morph_name(v)
    if kind == 'frame_fixture_actor':
        f=req['framing']
        keys={'targetRegion','azimuthDegrees','azimuthBasis','elevationDegrees','rollDegrees','comparisonGroup',
              'framingPolicy','includeWholeTarget','marginFraction','background','hud'}
        if not isinstance(f,dict) or set(f)!=keys:raise ValueError('Unsupported framing fields')
        if (f['targetRegion']!='full-body' or f['azimuthBasis']!='actor-front-clockwise' or
            f['framingPolicy']!='fixed-camera-per-comparison-group' or f['includeWholeTarget'] is not True or
            f['background']!='existing-cell' or f['hud']!='hidden' or f['elevationDegrees']!=0 or f['rollDegrees']!=0):
            raise ValueError('Unsupported framing policy')
        bounded(f['azimuthDegrees'],0,360);bounded(f['marginFraction'],.01,.3);name(f['comparisonGroup'])
    if kind == 'capture_fixture_photo':
        name(req['photoId']);c=req['configuration']
        if not isinstance(c,dict) or set(c)!={'morphKey','expectedMorphs'}:raise ValueError('Explicit configuration required')
        morph_name(c['morphKey']);values(c['expectedMorphs'])
        for k in ('minimumWidthPixels','minimumHeightPixels'):
            if type(req[k]) is not int or not 1<=req[k]<=8192:raise ValueError('Bounded original image dimensions required')
        bounded(req['settleSeconds'],0,5)
        if req['format']!='png' or req['requireActualMetadata'] is not True or req['qualityPolicy']!='original-render-no-upscale':
            raise ValueError('Original measured PNG required')
    if kind == 'restore_fixture_photography_state' and (req['restore']!=['camera','hud'] or req['leavePhysicsEnabled'] is not True):
        raise ValueError('Camera/UI restoration must preserve physics')
    return True


def values(value):
    if not isinstance(value,dict) or not 1<=len(value)<=64:raise ValueError('1..64keyed morph values required')
    for k,v in value.items():morph_name(k);bounded(v,-10,10)


def configuration(value):
    if not isinstance(value,dict) or set(value)!={'captureProvider','distanceGameUnits','maximumPhotos'}:
        raise ValueError('Photography configuration needs captureProvider/distanceGameUnits/maximumPhotos')
    if not isinstance(value['captureProvider'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',value['captureProvider']) or value['captureProvider'] in ('auto','native','providers','extensions'):
        raise ValueError('Explicit registered original PNG provider required')
    bounded(value['distanceGameUnits'],300,10000)
    if type(value['maximumPhotos']) is not int or not 1<=value['maximumPhotos']<=32:raise ValueError('1..32photos required')


def enabled(b):
    from .config import P
    c=P.value.get('photography')
    configuration(c)
    if not b.s.state.get('testProfile') or b.s.state.get('gameplayBootstrap',{}).get('completed') is not True:
        raise ValueError('Photography requires owned disposable profile and common gameplay readiness')
    b.guard_world()
    return c


def state(b):return b.s.state.setdefault('photography',{'actors':{},'groups':{},'photos':{},'morphKeys':{}})


def save(b):
    from .runner import atomic_json
    b.s.save();atomic_json(b.s.dir/'photography.json',copy.deepcopy(state(b)))


def actor(b,spec):
    enabled(b);actor_selector(spec);entry=state(b)['actors'].get(spec['referenceTag'])
    if not entry or entry.get('status')!='created':raise ValueError('Tagged NPC creation unavailable or uncertain')
    ident,row,raw=anchor(b,entry['reference'])
    if ident!=entry['incarnation'] or form(row.get('baseForm'))!=entry['base'] or row['loaded3D'] is not True:
        raise ValueError('Tagged NPC base/incarnation changed or unloaded')
    b.guard_world();return entry,row,raw


def native(b,entry):
    raw=b.call('photography_readback',{'actor':entry['reference'],'timeoutMs':max(1,min(3000,int(b.remaining()*1000)))})
    a=raw.get('actor',{})
    if (raw.get('protocol')!='photography-readback/1' or raw.get('phase')!='skse_main_thread_task' or
        form(a.get('reference'))!=entry['reference'] or a.get('runtimeHandle')!=entry['incarnation']['runtimeHandle']):
        raise ValueError('Exact native photography measurement unavailable')
    for k in ('restrained','aiEnabled','collisionsEnabled'):
        if type(a.get(k)) is not bool:raise ValueError('Actual NPC state unavailable')
    if (raw.get('ui',{}).get('paused') is not False or raw.get('ui',{}).get('blockingMenu') is not False or
        raw.get('freezeTime') is not False):
        raise ValueError('Photography world is paused or freeze state unavailable/enabled')
    return raw


def lighting(b):
    raw=b.call('inspect',{'kind':'lights','scope':'scene','limit':128})
    items=raw.get('lights')
    if (raw.get('scope')!='scene' or raw.get('truncated') is not False or raw.get('coverage',{}).get('truncated') is not False or
        not isinstance(items,list) or len(items)>128 or type(raw.get('count')) is not int or raw['count']!=len(items)):
        raise ValueError('Complete sampled scene light configuration unavailable')
    normalized=[]
    for light in items:
        values={k:copy.deepcopy(light[k]) for k in ('name','path','type','position','diffuse','radius','fade','fadeAmount')}
        for key in ('position','diffuse'):
            if not isinstance(values[key],list) or len(values[key])!=3:raise ValueError('Native light vector unavailable')
            for value in values[key]:bounded(value,-1e9,1e9)
        for key in ('radius','fade','fadeAmount'):bounded(values[key],-1e9,1e9)
        normalized.append(values)
    normalized.sort(key=lambda v:(v['path'],v['name'],v['type'],v['position']))
    return {'sampledSceneLights':normalized,'atomicRenderSnapshot':False,'providerObservation':raw}


def measure(b,spec):
    e,row,raw=actor(b,spec);n=native(b,e)
    result={'reference':e['reference'],'base':e['base'],'loaded3D':row['loaded3D'],**base_state(b,e['base']),
            'movementEnabled':not n['actor']['restrained'],'aiEnabled':n['actor']['aiEnabled'],
            'collisionsEnabled':n['actor']['collisionsEnabled'],'aggression':b.pap('Actor','GetActorValue',['Aggression'],e['reference']),
            'inCombat':b.pap('Actor','IsInCombat',target=e['reference'])}
    result['race']=returned_form(b.pap('Actor','GetRace',target=e['reference']))
    actor(b,spec)
    return {'actor':result,'incarnation':copy.deepcopy(e['incarnation']),'providerObservation':raw,'nativePhotography':n,
            'cell':form(row.get('cellForm')),'lighting':lighting(b)}


def read_morphs(b,spec,key,names):
    e,_,_=actor(b,spec);out={}
    for k in names:
        v=b.pap('NiOverride','GetBodyMorph',[{'form':e['reference']},k,key]);out[k]=bounded(v,-1000000,1000000)
    actor(b,spec);return out


def observe(b,req):
    out=measure(b,req['actor'])
    if req['observation']=='fixture-body-morphs':
        out['morph']={'configuration':{'key':req['key'],'values':read_morphs(b,req['actor'],req['key'],req['morphs'])}}
    return out


def create(b,req):
    enabled(b)
    from .config import P
    if selector(req['actorBase']) not in [selector(v) for v in P.value.get('fixture_actor_base_allowlist',[])]:
        raise ValueError('NPC base not explicitly allowed by operator')
    records=state(b)['actors'];tag=req['referenceTag']
    if tag in records or len(records)>=16:raise ValueError('NPC tag already attempted or16actor bound reached; no replay')
    base=form(b.resolve(req['actorBase']))
    # Resolve and verify NPC base before the durable mutation intent.
    rows=b.call('inspect',{'kind':'refs','formId':base}).get('refs',[])
    if len(rows)!=1 or rows[0].get('formType') not in ('NPC_','NPC'):raise ValueError('Resolved fixture base is not NPC')
    players=b.call('inspect',{'kind':'refs','formId':'0x14'}).get('refs',[])
    if len(players)!=1:raise ValueError('Exact player reference unavailable')
    p=players[0];pos=p.get('position');angles=p.get('rotation')
    if not isinstance(pos,list) or len(pos)!=3 or not isinstance(angles,list) or len(angles)!=3:
        raise ValueError('Actual player position/heading unavailable')
    for v in pos+angles:bounded(v,-1e7,1e7)
    heading=angles[2];placement=req['placement'];forward=placement['forwardGameUnits'];right=placement['rightGameUnits']
    destination=[pos[0]+math.sin(heading)*forward+math.cos(heading)*right,
                 pos[1]+math.cos(heading)*forward-math.sin(heading)*right,pos[2]]
    records[tag]={'status':'creating','base':base,'actorBase':copy.deepcopy(req['actorBase']),
                  'destination':destination,'createdAt':time.time()};save(b)
    try:
        ref=returned_form(b.pap('ObjectReference','PlaceAtMe',[{'form':base},1,False,False],'0x14'))
        if int(ref,16)>>24!=0xff or ref in [e.get('reference') for e in records.values()]:raise ValueError('New distinct dynamic NPC not returned')
        records[tag]['reference']=ref;save(b)
        b.pap('ObjectReference','MoveTo',[{'form':'0x14'},destination[0]-pos[0],destination[1]-pos[1],0.,False],ref)
        b.pap('ObjectReference','SetAngle',[0.,0.,math.degrees(heading)],ref)
        while True:
            ident,row,raw=anchor(b,ref)
            if form(row.get('baseForm'))!=base:raise ValueError('Created NPC has wrong base')
            if row['loaded3D'] is True:break
            b.pause(.1)
        records[tag].update(status='created',incarnation=ident);save(b)
        return {'fixture':{'actor':{'created':True}},'actor':{'reference':ref,'base':base},'providerObservation':raw}
    except Exception as error:
        records[tag].update(status='uncertain',reason=str(error));save(b);raise


def same_pose(a,b):
    for key in ('position','angles'):
        x,y=a.get(key),b.get(key)
        if not isinstance(x,list) or not isinstance(y,list) or len(x)!=3 or len(y)!=3:return False
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in x+y):return False
        if any(abs(v-w)>1e-4 for v,w in zip(x,y)):return False
    return True


def in_frame(n,margin):
    points=n.get('camera',{}).get('projectedBoundCorners')
    if not isinstance(points,list) or len(points)!=8:raise ValueError('Measured whole-bound projection unavailable')
    for p in points:
        uv=p.get('uvDepth')
        if p.get('projected') is not True or not isinstance(uv,list) or len(uv)!=3:return False
        for v in uv:bounded(v,-1e12,1e12)
        if not margin<=uv[0]<=1-margin or not margin<=uv[1]<=1-margin or uv[2]<=0:return False
    return True


def camera_signature(n):
    c=n.get('camera',{})
    required={'world','worldToCam','frustum','eyeFrustums','viewport'}
    if not required<=set(c):raise ValueError('Actual camera/projection unavailable')
    return {k:copy.deepcopy(c[k]) for k in sorted(required)}


def close_numbers(a,b,tolerance=1e-4):
    if type(a)!=type(b) and not (type(a) in (float,int) and type(b) in (float,int)):return False
    if isinstance(a,dict):return a.keys()==b.keys() and all(close_numbers(a[k],b[k],tolerance) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(close_numbers(x,y,tolerance) for x,y in zip(a,b))
    if type(a) in (int,float):return math.isfinite(a) and math.isfinite(b) and abs(a-b)<=tolerance
    return a==b


def frame(b,req):
    c=enabled(b);e,_,_=actor(b,req['actor']);n=native(b,e);s=state(b);f=req['framing'];group=f['comparisonGroup']
    if 'initialCamera' not in s:
        prior=b.call('camera',{'action':'get'})
        if prior.get('freeCam') is not False or prior.get('freeCamBackend')!='vr-state':raise ValueError('Known normal VR camera required')
        s['initialCamera']=prior;s['initialUi']=copy.deepcopy(n['ui']);s['cameraStatus']='enabling';save(b)
        b.call('camera',{'action':'freecam','on':True})
        s['cameraStatus']='enabled';save(b)
    current=b.call('camera',{'action':'get'})
    if current.get('freeCam') is not True or current.get('freeCamOwned') is not True:raise ValueError('Owned VR free camera unavailable')
    previous=s['groups'].get(group)
    if previous:
        if previous.get('status')!='framed' or previous['actorTag']!=req['actor']['referenceTag'] or previous['framing']!=f or not same_pose(previous['actor'],n['actor']):
            raise ValueError('Comparison group/actor pose changed; never reframe a changed variant')
        command=previous['command']
    else:
        centre=n['actor']['bound']['center'];angle=n['actor']['angles'][2]+math.radians(f['azimuthDegrees']);distance=c['distanceGameUnits']
        command={'action':'drive','x':centre[0]+math.sin(angle)*distance,'y':centre[1]+math.cos(angle)*distance,
                 'z':centre[2],'pitch':0.,'yaw':(angle+math.pi)%(2*math.pi)}
        s['groups'][group]={'status':'driving','command':command,'actorTag':req['actor']['referenceTag'],
                            'framing':copy.deepcopy(f),'actor':copy.deepcopy(n['actor'])};save(b)
    b.call('camera',command)  # Once per requested framing; never retry a timeout.
    b.pause(.2);now=native(b,e);observed=b.call('camera',{'action':'get'})
    if observed.get('freeCamOwned') is not True or observed.get('camAngles')!='freeCameraState':raise ValueError('Native owned camera readback unavailable')
    for k,native_key in (('x','camX'),('y','camY'),('z','camZ'),('pitch','camPitch'),('yaw','camYaw')):
        if abs(bounded(observed.get(native_key),-1e7,1e7)-command[k])>1e-3:raise ValueError('Camera drive did not match readback')
    if not same_pose(n['actor'],now['actor']) or not in_frame(now,f['marginFraction']):raise ValueError('Actor moved or measured whole bound outside fixed frame')
    signature=camera_signature(now)
    if previous and not close_numbers(signature,previous['signature']):raise ValueError('Paired camera/projection differs from baseline')
    lights=lighting(b)
    if previous and not close_numbers(lights['sampledSceneLights'],previous['lighting']['sampledSceneLights']):
        raise ValueError('Paired sampled light configuration changed')
    s['groups'][group].update(status='framed',signature=signature,readback=now,lighting=lights)
    s['currentGroup']=group;save(b);actor(b,req['actor'])
    return {'camera':{'framing':{'completed':True},'target':{'inFrame':True}},'nativePhotography':now,
            'projectionBasis':'primary-camera enclosing bound; rendered provider alignment requires live qualification'}


def photo(b,req):
    c=enabled(b);s=state(b);photo_id=req['photoId']
    if photo_id in s['photos'] or len(s['photos'])>=c['maximumPhotos']:raise ValueError('Photo already attempted or limit reached; no replay')
    group=s['groups'].get(s.get('currentGroup'))
    if not group or group.get('status')!='framed' or group['actorTag']!=req['actor']['referenceTag']:raise ValueError('Exact actor framing unavailable')
    b.pause(req['settleSeconds']);before=measure(b,req['actor']);n=before['nativePhotography']
    key=req['configuration']['morphKey'];expected=req['configuration']['expectedMorphs']
    measured=read_morphs(b,req['actor'],key,list(expected))
    if not close_numbers(expected,measured,1e-6):raise ValueError('Actual morph configuration differs')
    if (not same_pose(n['actor'],group['actor']) or not close_numbers(camera_signature(n),group['signature']) or
        not in_frame(n,group['framing']['marginFraction'])):raise ValueError('Fixed camera/actor framing changed')
    if not close_numbers(before['lighting']['sampledSceneLights'],group['lighting']['sampledSceneLights']):
        raise ValueError('Sampled scene light configuration changed before capture')
    entry={'status':'capture_requested','actorTag':req['actor']['referenceTag'],'group':s['currentGroup'],
           'morphKey':key,'morphs':measured,'before':before,'at':time.time(),
           'runId':b.s.state['id'],'gameIdentity':copy.deepcopy(b.s.state.get('game')),
           'profile':b.s.state.get('profile'),'testProfileName':b.s.state.get('testProfileName')}
    s['photos'][photo_id]=entry;save(b)
    folder=b.s.dir/'photography-artifacts';folder.mkdir(exist_ok=True)
    try:
        expected_file=folder/'photography'/'original'/(photo_id+'.png')
        if expected_file.exists():raise ValueError('Capture path already exists; never adopt or overwrite old pixels')
        receipt=b.call('capture',{'kind':c['captureProvider'],'allowNative':False,'excludeUi':True,
            'checkpointId':photo_id,'recording':'photography','variant':'original','outDir':str(folder.resolve()),
            'resolveRealPath':True,'timeoutMs':max(1,min(8000,int(b.remaining()*1000)))})
        entry['receipt']=receipt;save(b)
        if (receipt.get('ok') is not True or receipt.get('provider')!=c['captureProvider'] or receipt.get('uiExcluded') is not True or
            receipt.get('inconclusive') is not False or receipt.get('degraded') or receipt.get('sceneMismatch') is not False):
            raise ValueError('Original UI-excluded provider capture unavailable/degraded')
        file=folder/'photography'/'original'/(photo_id+'.png')
        if file.is_symlink() or not file.resolve().is_relative_to(folder.resolve()) or not file.is_file():raise ValueError('External original PNG unavailable')
        if Path(receipt.get('path','')).resolve()!=file.resolve():raise ValueError('Provider returned a different capture path')
        if file.stat().st_size>32*1024*1024:raise ValueError('Image exceeds bounded decoder')
        data=file.read_bytes()
        entry.update(image=str(file),sha256=hashlib.sha256(data).hexdigest(),bytes=len(data));save(b)
        from .assisted_capture import image_info
        info=image_info(data)
        if info['format']!='png' or info['width']<req['minimumWidthPixels'] or info['height']<req['minimumHeightPixels']:raise ValueError('Original image resolution below request')
        after=measure(b,req['actor']);final=read_morphs(b,req['actor'],key,list(expected));now=after['nativePhotography']
        if (not close_numbers(final,measured,1e-6) or not same_pose(n['actor'],now['actor']) or
            not close_numbers(camera_signature(now),group['signature']) or not in_frame(now,group['framing']['marginFraction'])):
            raise ValueError('Configuration/camera/actor changed across capture')
        if after['cell']!=before['cell'] or not close_numbers(after['lighting']['sampledSceneLights'],before['lighting']['sampledSceneLights']):
            raise ValueError('Cell or sampled scene light configuration changed across capture')
        # Pair resolution is observed, not requested or resampled.
        peers=[v for v in s['photos'].values() if v is not entry and v.get('status')=='verified' and v['group']==entry['group']]
        if peers and any(p['imageInfo']!=info for p in peers):raise ValueError('Paired original resolution differs')
        entry.update(status='verified',image=str(file),imageInfo=info,sha256=hashlib.sha256(data).hexdigest(),after=after,
                     finishedAt=time.time(),renderedContentVerified=False,atomicRenderSnapshot=False)
        from .runner import atomic_json
        metadata=b.s.dir/('photo-'+photo_id+'.json');atomic_json(metadata,entry)
        entry['metadataName']=metadata.name;entry['metadataSha256']=hashlib.sha256(metadata.read_bytes()).hexdigest();save(b)
        return {'photo':{'saved':True,'decoded':True,'configuration':{'matchesReadback':True},
                         'camera':{'matchesReadback':True},'target':{'inFrame':True},'hud':{'hidden':True}},
                'artifact':copy.deepcopy(entry)}
    except Exception as error:
        entry.update(status='unavailable_or_uncertain',reason=str(error));save(b);raise


def perform(b,req):
    action=req['action'];enabled(b)
    if action=='create_fixture_actor':return create(b,req)
    if action=='frame_fixture_actor':return frame(b,req)
    if action=='capture_fixture_photo':return photo(b,req)
    if action=='restore_fixture_photography_state':return restore(b)
    mutations=state(b).setdefault('mutations',[])
    if any(v['status']!='completed' for v in mutations):raise ValueError('Prior NPC mutation uncertain; never replay or continue')
    intent={'status':'started','request':copy.deepcopy(req),'at':time.time()}
    mutations.append(intent);save(b)
    try:
        result=mutate_actor(b,req)
        intent['status']='completed';save(b);return result
    except Exception as error:
        intent.update(status='uncertain',reason=str(error));save(b);raise


def mutate_actor(b,req):
    action=req['action']
    e,_,_=actor(b,req['actor']);ref=e['reference']
    if action=='configure_fixture_actor':
        initial=measure(b,req['actor'])
        if initial['actor']['aiEnabled'] is not True or initial['actor']['collisionsEnabled'] is not True:
            raise ValueError('Fixture requires already enabled AI/collisions; no disable/enable workaround')
        b.pap('Actor','SetRestrained',[True],ref);b.pap('Actor','SetActorValue',['Aggression',0.],ref);b.pap('Actor','StopCombat',target=ref)
        final=measure(b,req['actor']);a=final['actor']
        if a['movementEnabled'] is not False or a['aiEnabled'] is not True or a['collisionsEnabled'] is not True or a['aggression']!=0 or a['inCombat'] is not False:
            raise ValueError('Actual stationary NPC state did not match')
        return {'fixture':{'actor':{'prepared':True}},**final}
    records=state(b)['morphKeys'];key=req.get('key')
    if action=='set_fixture_body_morphs':
        token=req['actor']['referenceTag']+':'+key
        if token not in records:
            old=read_morphs(b,req['actor'],key,list(req['values']))
            if any(v!=0 for v in old.values()):raise ValueError('Requested morph key already contains values; not owned')
            records[token]={'actor':copy.deepcopy(req['actor']),'key':key,'morphs':list(req['values']),'status':'owned'};save(b)
        if records[token]['morphs']!=list(req['values']) or records[token]['status']!='owned':raise ValueError('Owned morph names/key changed')
        for k,v in req['values'].items():b.pap('NiOverride','SetBodyMorph',[{'form':ref},k,key,float(v)])
        actual=read_morphs(b,req['actor'],key,list(req['values']))
        if not close_numbers(actual,req['values'],1e-6):raise ValueError('Actual keyed morph values differ')
    elif action=='clear_fixture_body_morph_key':
        token=req['actor']['referenceTag']+':'+key;r=records.get(token)
        if not r or r['status']!='owned':raise ValueError('Cannot clear a key not owned by this attempt')
        r['status']='clearing';save(b)
        b.pap('NiOverride','ClearBodyMorphKeys',[{'form':ref},key])
        actual=read_morphs(b,req['actor'],key,r['morphs'])
        if any(v!=0 for v in actual.values()):raise ValueError('Own key did not clear')
        r['status']='cleared';save(b)
    else:b.pap('NiOverride','UpdateModelWeight',[{'form':ref}])
    actor(b,req['actor']);return {'action':{'completed':True}}


def restore(b):
    s=state(b)
    if 'initialCamera' not in s:raise ValueError('Photography camera restoration has no prior state')
    current=b.call('camera',{'action':'get'})
    if current.get('freeCam') is not True or current.get('freeCamOwned') is not True:raise ValueError('Owned camera changed; do not restore another owner')
    s['cameraStatus']='restoring';save(b);b.call('camera',{'action':'freecam','on':False})
    final=b.call('camera',{'action':'get'})
    if final.get('freeCam') is not False or final.get('stateId')!=s['initialCamera']['stateId']:raise ValueError('Normal VR camera restoration failed')
    first=next((v for v in s['actors'].values() if v.get('status')=='created'),None)
    if not first:raise ValueError('No exact native actor for UI restoration readback')
    observed=native(b,first)
    if observed['ui']!=s['initialUi']:raise ValueError('UI state changed; photography does not toggle HUD/time/physics')
    s['cameraStatus']='restored';s['restorationReadback']=final;save(b)
    return {'camera':{'restored':True},'hud':{'restored':True}}


def cleanup(session):
    """Best-effort owned camera cleanup before game exit; file restoration still runs."""
    s=session.state.get('photography')
    if not s or 'initialCamera' not in s or s.get('cameraStatus') in ('restored','restoring'):return
    from .platform import Backend
    b=Backend(session,time.monotonic()+10)
    try:restore(b)
    except Exception as error:
        s['cleanupError']=str(error);session.save()
        session.log('photography-camera-cleanup-unavailable',error=str(error),gameExitAndFileRestorationStillRequired=True)


def collect(session,copy_file):
    s=session.state.get('photography')
    if s is None:return
    from .photo_index import write
    write(session)
    copy_file(session.dir/'photography-index.json','photography-index.json','photography-index',required=True)
    copy_file(session.dir/'photography-contact-sheet.png','photography-contact-sheet.png','photography-derived-preview',required=True)
    copy_file(session.dir/'photography.json','photography.json','photography-accounting',required=True)
    for photo_id,entry in s['photos'].items():
        name(photo_id)
        if 'image' in entry:
            image=Path(entry['image']);expected=session.dir/'photography-artifacts/photography/original'/(photo_id+'.png')
            if image.resolve()!=expected.resolve() or image.is_symlink():raise ValueError('Photo evidence path changed')
            result=copy_file(image,'photo-'+photo_id+'.png','photography-original',required=True)
            if result and result['sha256']!=entry['sha256']:raise ValueError('Photo evidence hash changed')
        if 'metadataName' in entry:
            expected='photo-'+photo_id+'.json'
            if entry['metadataName']!=expected:raise ValueError('Photo metadata name changed')
            result=copy_file(session.dir/expected,expected,'photography-metadata',required=True)
            if result and result['sha256']!=entry['metadataSha256']:raise ValueError('Photo metadata hash changed')
