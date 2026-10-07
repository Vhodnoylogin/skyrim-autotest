"""Observed VRIK slot centres and bounded physical approaches; no subject routing."""
import copy
import math
from .platform_math import world_bounds_center,world_translation,fixture_offset,solve3,body_reach_envelope

# VRIK's public14-slot skeleton binding, also used by BodyPouches Game::Body.
BONES=('NPC COM [COM ]','NPC Pelvis [Pelv]','NPC L Thigh [LThg]','NPC R Thigh [RThg]',
       'NPC L Calf [LClf]','NPC R Calf [RClf]','NPC L UpperArm [LUar]','NPC R UpperArm [RUar]',
       'NPC L Forearm [LLar]','NPC R Forearm [RLar]','NPC L Clavicle [LClv]','NPC R Clavicle [RClv]',
       'NPC Spine1 [Spn1]','NPC Spine2 [Spn2]')
HEAD='NPC Head [Head]'
PLACEMENT='settled reachable surface away from pouch and mouth'
TARGET_BASIS='actual loaded VRIK body-slot centre transformed to controller tracking space'


def transforms(b, nodes):
    b.guard_world()
    query=[{'ref':'0x14','name':name,'firstPerson':first} for name,first in nodes]
    raw=b.call('inspect',{'kind':'world_observer','nodes':query})
    if (raw.get('ok') is not True or raw.get('space')!='world' or raw.get('units')!='skyrim_engine_units' or
            not isinstance(raw.get('sessionId'),str) or not raw['sessionId'] or
            type(raw.get('loadGeneration')) is not int or raw['loadGeneration']<=0):
        raise ValueError('Observed body scene session/generation/units unavailable')
    result={};handle=None
    for name,first in nodes:
        rows=[row for row in raw.get('nodes',[]) if row.get('name')==name and row.get('firstPerson') is first and
              int(row.get('form','0'),16)==0x14]
        if len(rows)!=1 or rows[0].get('status')!='available':raise ValueError('Exact observed body node unavailable: '+name)
        row=rows[0];identity=row.get('identity',{})
        if (int(identity.get('form','0'),16)!=0x14 or identity.get('loadGeneration')!=raw['loadGeneration'] or
                type(identity.get('runtimeHandle')) is not int or identity['runtimeHandle']<=0):
            raise ValueError('Observed body node incarnation unavailable')
        if handle is not None and handle!=identity['runtimeHandle']:raise ValueError('Body nodes belong to different incarnations')
        handle=identity['runtimeHandle']
        transform=row.get('world',{})
        # Node world origins (head clearance / arm chain) need translation only.
        # Consumers applying a local offset must separately validate the full
        # rotation/scale via world_bounds_center; never normalize native data.
        world_translation(transform)
        result[(name,first)]=transform
    key=(raw['sessionId'],raw['loadGeneration'],handle)
    if hasattr(b,'_body_scene_identity') and b._body_scene_identity!=key:
        raise ValueError('Body scene incarnation changed during action')
    b._body_scene_identity=key
    b.guard_world();b.s.log('platform-body-scene',snapshot=raw,atomicWithSettings=False,
                          validationBasis='exact native incarnation/units and finite world origins; local-offset consumers separately require rigid rotation/scale')
    return result


def offsets(b, slots):
    calls=[{'script':'VRIK','function':'VrikGetSlot','args':['pos'+axis+str(slot)]} for slot in slots for axis in 'XYZ']
    values=[]
    for start in range(0,len(calls),16):values.extend(b.pap_read_batch(calls[start:start+16]))
    if any(type(v) not in (int,float) or not math.isfinite(v) or abs(v)>100000 for v in values):
        raise ValueError('Loaded VRIK slot offset unavailable')
    return {slot:values[i*3:i*3+3] for i,slot in enumerate(slots)}


def centres(b, slots, extra=()):
    before=offsets(b,slots)
    nodes=list(dict.fromkeys([(BONES[slot-1],False) for slot in slots]+[(HEAD,False)]+list(extra)))
    observed=transforms(b,nodes)
    if offsets(b,slots)!=before:raise ValueError('VRIK slot settings changed during scene read')
    points={slot:world_bounds_center({'min':before[slot],'max':before[slot]},observed[(BONES[slot-1],False)]) for slot in slots}
    return points,observed


def exclusion(b, point):
    points,nodes=centres(b,list(range(1,15)))
    distances={str(slot):math.dist(point,center) for slot,center in points.items()}
    mouth=math.dist(point,nodes[(HEAD,False)]['translation'])
    result={'slotCentreDistancesGameUnits':distances,'headDistanceGameUnits':mouth,
            'minimumClearanceGameUnits':20,'basis':'observed all14 VRIK slot centres and head; geometric clearance, not contact proof'}
    return min(distances.values())>=20 and mouth>=20,result


def plan_placement(b, specification):
    if specification!=PLACEMENT:raise ValueError('Unsupported generic fixture placement')
    player=b.xyz('0x14');heading=math.radians(b.pap('ObjectReference','GetAngleZ',target='0x14'))
    for index in range(len(b.s.state.get('platformReferences',{})),16):
        offset=fixture_offset(index,heading);point=[a+c for a,c in zip(player,offset)]
        clear,evidence=exclusion(b,point)
        if clear:
            b._generic_placement_index=index
            b.s.log('platform-generic-placement-plan',pointGameUnits=point,index=index,evidence=evidence)
            return
    raise ValueError('No bounded reachable fixture point clears observed body slots/head')


def verify_settled(b,reference):
    center=b.reference_center(reference)
    clear,evidence=exclusion(b,center)
    b.s.log('platform-generic-placement-settled',reference=reference,centerGameUnits=center,evidence=evidence)
    if not clear:raise ValueError('Settled fixture is inside observed body-slot/head clearance')


def pose(b, req):
    from .vr_probe import ensure_owned_focus
    ensure_owned_focus(b.s,{},'platform-body-slot-owned-focus',deadline=b.end)
    menus=b.call('menu',{'action':'list','includeFlags':True});b.recover_input_gate(menus)
    hand=req['hand'];frame=b.frame();baseline=b.hand_xyz(hand);columns=[]
    if req['action']=='grip_and_withdraw_from_body_slot':
        # Approach/calibrate with an empty open grip; the timed edge comes only
        # after all potentially slow geometry/readiness requests have ended.
        frame[hand]['controller'].update(pressed=0,touched=0,axes=[[0,0] for _ in range(5)])
        b.publish(frame,10);b.pause(.1);baseline=b.hand_xyz(hand)
    # Small physical probes preserve the existing grip and measure the current
    # avatar/world scale rather than assuming70engine units per metre.
    for index in (3,7,11):
        probe=copy.deepcopy(frame);probe[hand]['matrix'][index]+=.025
        b.publish(probe,10);b.pause(.15);measured=b.hand_xyz(hand)
        columns.append([(v-a)/.025 for v,a in zip(measured,baseline)])
        b.publish(frame,10);b.pause(.1)
    side='L' if hand=='left' else 'R'
    names=[f'NPC {side} UpperArm [{side}Uar]',f'NPC {side} Forearm [{side}Lar]',f'NPC {side} Hand [{side}Hnd]']
    progress_at=None;previous=None
    import time
    for _ in range(256):
        points,nodes=centres(b,[req['slot']],[(name,True) for name in names])
        shoulder,elbow,current=[nodes[(name,True)]['translation'] for name in names]
        target=[points[req['slot']][i]+sum(columns[j][i]*req['offset']['xyz'][j] for j in range(3)) for i in range(3)]
        head=nodes[(HEAD,False)]['translation']
        mouth_distance=math.sqrt(sum(v*v for v in solve3(columns,[a-c for a,c in zip(target,head)])))
        if mouth_distance<.18:raise ValueError('Body-slot target approaches observed head/mouth exclusion')
        envelope=body_reach_envelope(columns,shoulder,elbow,current,target)
        delta=solve3(columns,[a-c for a,c in zip(target,current)]);distance=math.sqrt(sum(v*v for v in delta))
        if distance<=.025:break
        now=time.monotonic()
        if previous is None or math.dist(previous,current)>=.25:previous=list(current);progress_at=now
        elif now-progress_at>5:raise ValueError('Body-slot approach made no observed progress for five seconds')
        fraction=min(1.,.01/distance)
        for index,change in zip((3,7,11),delta):frame[hand]['matrix'][index]+=fraction*change
        b.s.log('platform-body-slot-approach',slot=req['slot'],hand=hand,bodyEnvelope=envelope,
                targetGameUnits=target,handGameUnits=current,incrementMetres=[v*fraction for v in delta])
        b.publish(frame,10);b.pause(.1)
    else:raise ValueError('Body-slot approach exhausted bounded increments')
    # Common physical input gate before the requested edge. The other hand's
    # pose/grip is preserved; moving one hand must not silently drop its item.
    ensure_owned_focus(b.s,{},'platform-body-slot-grip-owned-focus',deadline=b.end)
    menus=b.call('menu',{'action':'list','includeFlags':True});b.recover_input_gate(menus)
    if req['action']=='grip_and_withdraw_from_body_slot':
        from .body_stroke import withdraw
        # Re-observe after the input gate; a recovered menu may have moved the
        # avatar. Never start a closed-grip stroke using the earlier geometry.
        points,nodes=centres(b,[req['slot']],[(name,True) for name in names])
        shoulder,elbow,current=[nodes[(name,True)]['translation'] for name in names]
        target=[points[req['slot']][i]+sum(columns[j][i]*req['offset']['xyz'][j] for j in range(3)) for i in range(3)]
        if math.sqrt(sum(v*v for v in solve3(columns,[a-c for a,c in zip(target,current)])))>.025:
            raise ValueError('Body-slot centre moved before withdrawal edge')
        result=withdraw(b,req,frame,columns,shoulder,elbow,current,nodes[(HEAD,False)]['translation'])
        # This is endpoint evidence only: no claim of an atomic path/contact or
        # native holster callback. Subject checks must inspect the actual item.
        points,after=centres(b,[req['slot']],[(name,True) for name in names])
        b.s.log('platform-body-withdrawal-observed',slot=req['slot'],hand=hand,
                handGameUnits=after[(names[-1],True)]['translation'],slotGameUnits=points[req['slot']],
                publication=b.call('driver',{'action':'status'}),observedGameplaySuccess=None)
        return result
    frame[hand]['controller'].update(pressed=4 if req['grip']=='closed' else 0,touched=0,axes=[[0,0] for _ in range(5)])
    publication=b.publish(frame,req['durationSeconds']);b.pause(req['durationSeconds'])
    b.s.log('platform-body-slot-pose-issued',slot=req['slot'],hand=hand,publication=publication,
            otherHandInputPreserved=True,observedGameplaySuccess=None)
    return {'inputIssued':True,'publication':publication,'observedGameplaySuccess':None}
