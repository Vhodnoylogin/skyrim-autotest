"""Timed hand-only grip withdrawal after an observed open-hand slot approach."""
import copy
import math
import time
from .platform_math import solve3, body_reach_envelope


def withdraw(b, req, frame, columns, shoulder, elbow, current, head):
    displacement=req['withdrawal']['xyz'];duration=req['motionSeconds'];hand=req['hand']
    delta=[sum(columns[j][i]*displacement[j] for j in range(3)) for i in range(3)]
    target=[a+c for a,c in zip(current,delta)]
    envelope=body_reach_envelope(columns,shoulder,elbow,current,target)
    head_delta=solve3(columns,[h-c for h,c in zip(head,current)])
    length2=sum(v*v for v in displacement)
    closest=max(0.,min(1.,sum(a*c for a,c in zip(head_delta,displacement))/length2))
    if math.dist(head_delta,[closest*v for v in displacement])<.18:
        raise ValueError('Withdrawal path approaches observed head/mouth exclusion')
    if duration+req['durationSeconds']+.1>=b.remaining():
        raise TimeoutError('Insufficient operation time for timed withdrawal')
    steps=math.ceil(math.sqrt(length2)/.01)
    start=copy.deepcopy(frame);start[hand]['controller'].update(pressed=4,touched=0,axes=[[0,0] for _ in range(5)])
    b.s.log('platform-body-withdrawal-plan',slot=req['slot'],hand=hand,steps=steps,
            motionSeconds=duration,maximumStepMetres=.01,withdrawalMetres=displacement,
            fromHandGameUnits=current,targetHandGameUnits=target,bodyEnvelope=envelope,
            otherHandInputPreserved=True,hmdPreserved=True,
            geometryBasis='pre-edge observed nodes/calibration; path not a native contact stream')
    began=time.monotonic();publication=b.publish(start,duration+req['durationSeconds'])
    b.pause(.05)  # Preserve a distinct closed edge before the first increment.
    for step in range(1,steps+1):
        if time.monotonic()-began>=duration:
            raise TimeoutError('Timed withdrawal motion budget exhausted; no action replay')
        changed=copy.deepcopy(start)
        for index,change in zip((3,7,11),displacement):changed[hand]['matrix'][index]+=change*step/steps
        publication=b.publish(changed,duration+req['durationSeconds'])
        elapsed=time.monotonic()-began
        if elapsed>duration:
            raise TimeoutError('Timed withdrawal publication exceeded motion budget')
        scheduled=.05+(duration-.1)*step/steps
        if scheduled>elapsed:b.pause(scheduled-elapsed)
    elapsed=time.monotonic()-began
    b.s.log('platform-body-withdrawal-issued',hand=hand,slot=req['slot'],elapsedSeconds=elapsed,
            publication=publication,observedGameplaySuccess=None)
    b.pause(req['durationSeconds'])
    return {'inputIssued':True,'publication':publication,'observedGameplaySuccess':None}
