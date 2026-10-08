"""Observed, incremental body lowering for an otherwise unreachable low object."""
import math
from .platform_math import body_reach_envelope, solve3, TargetProgress


class ReachPosture:
    def __init__(self, backend, frame, columns):
        self.b, self.frame, self.columns = backend, frame, columns
        self.start_height = frame['hmd']['matrix'][7]
        self.body_progress = TargetProgress()

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
            height=self.relative(head,feet)[1]
            if not math.isfinite(height) or height<=.61:
                raise ValueError('Observed head too low for another crouch increment')
            travel=self.start_height-self.frame['hmd']['matrix'][7]
            if travel+.01>.750001:
                raise ValueError('Low reach exhausted bounded body lowering')
            import time
            distance=math.sqrt(sum(v*v for v in relative))
            if not self.body_progress.observe(distance,time.monotonic()):
                raise ValueError('Body lowering made no observed shoulder-to-target progress')
            self.frame['hmd']['matrix'][7]-=.01
            b.s.log('platform-reach-crouch-command',hand=hand,reference=ref,
                    incrementMetres=.01,totalLoweringMetres=travel+.01,
                    headBeforeGameUnits=head,playerOriginGameUnits=feet,
                    observedHeadHeightMetres=height,otherDevicePosesAndInputsPreserved=True,
                    consumptionProven=False)
            b.publish(self.frame,10);b.pause(.1)
            # A publication cannot authorize a further body step. Wait only
            # for read-only evidence of this actual head lowering, never replay.
            end=time.monotonic()+min(2.,b.remaining())
            while True:
                target=b.reach_target(ref,hand,self.columns)
                after=b._reach_body['head']
                delta=self.relative(after,head)
                if delta[1]<=-.003:
                    if math.hypot(delta[0],delta[2])>.05 or delta[1]<-.05:
                        raise ValueError('Observed body motion differs from bounded vertical crouch')
                    if self.relative(after,b.xyz('0x14'))[1]<.6:
                        raise ValueError('Observed crouch crossed minimum body height')
                    b.s.log('platform-reach-crouch-observed',hand=hand,reference=ref,
                            headAfterGameUnits=after,headDeltaMetres=delta,
                            shoulderGameUnits=b._reach_body['shoulder'],targetHandGameUnits=target,
                            basis='actual same-incarnation third-person body response; publication alone is insufficient')
                    break
                if time.monotonic()>=end:
                    raise ValueError('Crouch publication produced no observed body lowering')
                b.pause(.1)
