"""Measure native tracking/world coordinates independently of hand IK/physics."""
import copy
import math
import time
from .platform_math import world_translation, solve3


def sample(b, hand):
    from .body_scene import transforms, HEAD
    name='NPC L Hand [LHnd]' if hand=='left' else 'NPC R Hand [RHnd]'
    observed=transforms(b,[(name,True),(HEAD,False)])
    raw=b._body_scene_snapshot
    picking=raw.get('vrPicking',{})
    if (picking.get('status')!='available' or picking.get('space')!='world' or
            picking.get('units')!='skyrim_engine_units'):
        raise ValueError('Native tracking calibration rig unavailable')
    rig={}
    for key,role,expected in [('head','uprightHmd','UprightHmdNode'),
                              ('left','leftWand','LeftWandNode'),('right','rightWand','RightWandNode')]:
        row=picking.get('nodes',{}).get(role,{})
        if row.get('status')!='available' or row.get('name')!=expected:
            raise ValueError('Exact native tracking calibration node unavailable')
        rig[key]=world_translation(row.get('world',{}))
    return {'rig':rig,'hand':world_translation(observed[(name,True)])}


def differential(before, after, hand):
    moves={role:[a-c for a,c in zip(after['rig'][role],before['rig'][role])]
           for role in ('head','left','right')}
    other='left' if hand=='right' else 'right'
    if math.dist(moves['head'],moves[other])>.35:
        raise ValueError('Unchanged native devices disagree during tracking calibration')
    common=[(a+c)/2 for a,c in zip(moves['head'],moves[other])]
    if math.dist(common,[0,0,0])>.35:
        raise ValueError('Native world rig moved during hand-only calibration')
    return [a-c for a,c in zip(moves[hand],common)]


def calibrate(b, frame, hand):
    """Bounded physical probes preserve all inputs, HMD and the other controller.

    Native wand displacement supplies units/axes. The FP hand is only raw
    nonlinear physical feedback, never an anatomical length or world scale.
    Each probe and return is observed before a subsequent publication.
    """
    columns=[]
    def held():
        result=[]
        for side in ('left','right'):
            value=b.pap('HiggsVR','GetGrabbedObject',[side=='left'])
            if value is not None and (not isinstance(value,dict) or not isinstance(value.get('formId'),str)):
                raise ValueError('Native held reference unavailable during tracking calibration')
            result.append(int(value['formId'],16) if value else None)
        return result
    ownership=held()
    def unchanged_ownership():
        if held()!=ownership:raise ValueError('Held reference changed during tracking calibration')
    origin=sample(b,hand)
    baseline=origin
    for index in (3,7,11):
        unchanged_ownership()
        probe=copy.deepcopy(frame);probe[hand]['matrix'][index]+=.025
        b.publish(probe,10);b.pause(.15)
        end=time.monotonic()+min(2.,b.remaining())
        last=None;quiet=None
        while True:
            measured=sample(b,hand)
            delta=differential(baseline,measured,hand)
            now=time.monotonic()
            if math.dist(delta,[0,0,0])>.05:
                if last is not None and math.dist(delta,last)<=.05:
                    quiet=now if quiet is None else quiet
                    if now-quiet>=.1:break
                else:quiet=None
            last=delta
            if now>=end:raise ValueError('Native calibration probe consumption unavailable')
            b.pause(.1)
        column=[v/.025 for v in delta]
        length=math.sqrt(sum(v*v for v in column))
        if not 20<=length<=300:raise ValueError('Native tracking calibration scale unavailable or extreme')
        columns.append(column)
        unchanged_ownership()
        b.s.log('platform-native-tracking-calibration',hand=hand,trackingAxis=index,
                probeMetres=.025,nativeDifferentialGameUnits=delta,
                measuredGameUnitsPerMetre=column,rawFpHandBeforeGameUnits=baseline['hand'],
                rawFpHandAfterGameUnits=measured['hand'],skeletalResponseUsedAsMetric=False,
                snapshotIdentity=b._body_scene_identity,otherDevicePosesAndInputsPreserved=True)
        b.publish(frame,10);b.pause(.1)
        end=time.monotonic()+min(2.,b.remaining())
        while True:
            baseline=sample(b,hand)
            if math.dist(differential(origin,baseline,hand),[0,0,0])<=.35:break
            if time.monotonic()>=end:raise ValueError('Native calibration return consumption unavailable')
            b.pause(.1)
        unchanged_ownership()
    lengths=[math.sqrt(sum(v*v for v in column)) for column in columns]
    if max(lengths)/min(lengths)>1.03 or any(
            abs(sum(a*c for a,c in zip(columns[i],columns[j])))/(lengths[i]*lengths[j])>.03
            for i in range(3) for j in range(i)):
        raise ValueError('Native tracking calibration basis is nonrigid')
    solve3(columns,[1,0,0])
    return columns,baseline['hand']
