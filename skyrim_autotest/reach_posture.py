"""Observed, incremental body lowering for an otherwise unreachable low object."""
import math
import copy
import time
from .platform_math import body_reach_envelope, solve3, TargetProgress


class ReachPosture:
    def __init__(self, backend, frame, columns):
        self.b, self.frame, self.columns = backend, frame, columns
        self.start_height = frame['hmd']['matrix'][7]
        self.body_progress = TargetProgress()
        self.initial_head = None

    def relative(self, a, b):
        return solve3(self.columns, [x-y for x,y in zip(a,b)])

    def envelope(self, target):
        arm=self.b._reach_body
        return body_reach_envelope(self.columns,arm['shoulder'],arm['elbow'],arm['armHand'],target)

    def ensure(self, ref, hand, target):
        while True:
            try:
                return target,self.envelope(target)
            except ValueError as error:
                if str(error)!='Target outside observed body reach envelope':raise
            b=self.b;arm=b._reach_body
            relative=self.relative(target,arm['shoulder'])
            if relative[1]>=-.1 or math.hypot(relative[0],relative[2])>2:
                raise ValueError('Target outside observed body reach envelope; crouch cannot address this direction')
            # Body movement cannot silently alter a held-item interaction.
            for side in ('left','right'):
                controls=self.frame[side]['controller']
                if controls['pressed'] or controls['touched'] or any(v for axis in controls['axes'] for v in axis):
                    raise ValueError('Low reach posture requires neutral controller inputs')
                if b.pap('HiggsVR','GetGrabbedObject',[side=='left']) is not None:
                    raise ValueError('Low reach posture requires both actual hands empty')
            head=list(arm['head']);feet=b.xyz('0x14');b.guard_world()
            rig=copy.deepcopy(getattr(b,'_reach_rig',None))
            if not isinstance(rig,dict):raise ValueError('Exact native VR rig origins unavailable for crouch')
            if self.initial_head is None:self.initial_head=list(head)
            height=self.relative(head,feet)[1]
            if not math.isfinite(height) or height<=.61:
                raise ValueError('Observed head too low for another crouch increment')
            travel=self.start_height-self.frame['hmd']['matrix'][7]
            if travel+.01>.750001:
                raise ValueError('Low reach exhausted bounded body lowering')
            distance=math.sqrt(sum(v*v for v in relative))
            if not self.body_progress.observe(distance,time.monotonic()):
                raise ValueError('Body lowering made no observed shoulder-to-target progress')
            self.frame['hmd']['matrix'][7]-=.01
            b.s.log('platform-reach-crouch-command',hand=hand,reference=ref,
                    incrementMetres=.01,totalLoweringMetres=travel+.01,
                    headBeforeGameUnits=head,playerOriginGameUnits=feet,
                    nativeRigBefore=rig,
                    observedHeadHeightMetres=height,otherDevicePosesAndInputsPreserved=True,
                    consumptionProven=False)
            b.publish(self.frame,10);b.pause(.1)
            # A publication cannot authorize a further body step. Wait only
            # for read-only evidence of this actual head lowering, never replay.
            end=time.monotonic()+min(2.,b.remaining())
            settle=None;last=None;transition=False
            while True:
                target=b.reach_target(ref,hand,self.columns)
                after=b._reach_body['head']
                delta=self.relative(after,head)
                actual=getattr(b,'_reach_rig',None)
                if not isinstance(actual,dict):raise ValueError('Native VR rig origins lost during crouch')
                moves={role:self.relative(actual[role],rig[role]) for role in ('head','left','right')}
                if math.dist(moves['left'],moves['right'])>.005:
                    raise ValueError('Unchanged native controllers disagree on VR rig translation')
                common=[(a+c)/2 for a,c in zip(moves['left'],moves['right'])]
                consumed=[a-c for a,c in zip(moves['head'],common)]
                if math.hypot(common[0],common[2])>.05 or common[1]>.05:
                    raise ValueError('Unexpected native VR rig translation during crouch')
                if consumed[1]<=-.003 and delta[1]<=-.003:
                    # Input displacement is relative to both unchanged wand
                    # origins. Engine crouch can translate the entire VR rig;
                    # a raw skeletal head delta is not the HMD input delta.
                    if math.hypot(consumed[0],consumed[2])>.05 or consumed[1]<-.05 or math.hypot(delta[0],delta[2])>.05:
                        raise ValueError('Observed body motion differs from bounded vertical crouch')
                    actual_feet=b.xyz('0x14');b.guard_world()
                    if math.sqrt(sum(v*v for v in self.relative(actual_feet,feet)))>.05:
                        raise ValueError('Player origin moved during bounded crouch')
                    if self.relative(after,actual_feet)[1]<.6:
                        raise ValueError('Observed crouch crossed minimum body height')
                    if self.relative(self.initial_head,after)[1]>.75:
                        raise ValueError('Observed body lowering exceeds total posture bound')
                    transition=transition or abs(common[1])>.05
                    now=time.monotonic()
                    if transition:
                        # Freeze commands during an actual common rig shift.
                        # Wait for two quiet reads; never widen the input guard.
                        if last is None or math.dist(after,last)>.35:settle=None
                        else:settle=settle if settle is not None else now
                        last=list(after)
                        if settle is None or now-settle<.2:
                            if now>=end:raise ValueError('Native crouch rig transition did not settle')
                            b.pause(.1);continue
                    sneaking=b.pap('Actor','IsSneaking',target='0x14')
                    if type(sneaking) is not bool:raise ValueError('Native crouch state unavailable')
                    b.s.log('platform-reach-crouch-observed',hand=hand,reference=ref,
                            headAfterGameUnits=after,headDeltaMetres=delta,
                            nativeRigAfter=actual,nativeRigCommonDeltaMetres=common,
                            consumedHmdRelativeToWandsMetres=consumed,nativeSneaking=sneaking,
                            rigTransitionSettled=transition,
                            shoulderGameUnits=b._reach_body['shoulder'],targetHandGameUnits=target,
                            basis='actual same-incarnation third-person body response; publication alone is insufficient')
                    break
                if time.monotonic()>=end:
                    raise ValueError('Crouch publication produced no observed body lowering')
                b.pause(.1)
