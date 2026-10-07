"""Atomic leased physical OpenVR device frames for the external driver adapter."""
import math
import time
from pathlib import Path
import os
import threading
import uuid
import re
from . import runner

PATH = Path(os.environ['PROGRAMDATA']) / 'SkyrimVR Autotest/frame.txt'
_PUBLISH_LOCK = threading.RLock()
_OWNER = uuid.uuid4().hex
_SEQUENCES = {}


def tick_ms():
    if os.name == 'nt':
        import ctypes
        fn=ctypes.windll.kernel32.GetTickCount64
        fn.restype=ctypes.c_ulonglong
        return fn()
    return time.monotonic_ns()//1_000_000


def quaternion(matrix):
    r = [matrix[0:3], matrix[4:7], matrix[8:11]]
    for i in range(3):
        for j in range(3):
            if abs(sum(r[i][k]*r[j][k] for k in range(3)) - (1 if i == j else 0)) > .001:
                raise ValueError('Pose rotation must be orthonormal')
    det = sum(r[0][i]*(r[1][(i+1)%3]*r[2][(i+2)%3]-r[1][(i+2)%3]*r[2][(i+1)%3]) for i in range(3))
    if abs(det - 1) > .001:
        raise ValueError('Pose rotation must preserve handedness')
    trace = r[0][0] + r[1][1] + r[2][2]
    if trace > 0:
        s = math.sqrt(trace + 1) * 2
        return [s/4, (r[2][1]-r[1][2])/s, (r[0][2]-r[2][0])/s, (r[1][0]-r[0][1])/s]
    i = max(range(3), key=lambda i: r[i][i])
    j, k = (i+1) % 3, (i+2) % 3
    s = math.sqrt(1+r[i][i]-r[j][j]-r[k][k]) * 2
    q = [0.] * 4
    q[0] = (r[k][j]-r[j][k])/s
    q[i+1], q[j+1], q[k+1] = s/4, (r[j][i]+r[i][j])/s, (r[k][i]+r[i][k])/s
    return q


def neutral():
    frame = {'seq': 1, 'tMs': 0, 'originCode': 1}
    for role, xyz in [('hmd', [0, 1.65, 0]), ('left', [-.3, 1.2, -.35]), ('right', [.3, 1.2, -.35])]:
        frame[role] = {'matrix': [1, 0, 0, xyz[0], 0, 1, 0, xyz[1], 0, 0, 1, xyz[2]],
                       'controller': {'pressed': 0, 'touched': 0, 'axes': [[0, 0] for _ in range(5)]}}
    return frame


def publish(frame):
    # Session.lock orders frame selection/lease updates. This lock also protects
    # the file transaction if independent callers publish on separate threads.
    with _PUBLISH_LOCK:
        return _publish(frame)


def _publish(frame):
    owner=frame.setdefault('_owner', _OWNER)
    command=frame.setdefault('_command', uuid.uuid4().hex)
    if any(not isinstance(v,str) or not re.fullmatch(r'[0-9a-f]{32}',v) for v in (owner,command)):
        raise ValueError('Driver owner/command token must be32lowercase hex digits')
    tick=tick_ms()
    sequence=max(tick*1024,_SEQUENCES.get(owner,0)+1)
    # A recovered executor keeps the same owner but starts a fresh Python process.
    # The durable atomic file carries the last sequence across that handoff.
    try:
        if PATH.stat().st_size<=8192:
            previous=PATH.read_text(encoding='ascii').split()
            if previous[:3]==['SKYRIM_AUTOTEST','2',owner] and len(previous)>3:
                sequence=max(sequence,int(previous[3])+1)
    except (OSError,UnicodeError,ValueError):pass
    if not 0<sequence<2**63:raise ValueError('Driver publication sequence outside domain')
    values = ['SKYRIM_AUTOTEST',2,owner,sequence,tick,5000,command]
    for role in ('hmd', 'left', 'right'):
        m = frame[role]['matrix']
        if len(m) != 12 or not all(math.isfinite(v) for v in m):
            raise ValueError('Pose must contain twelve finite values')
        values.extend([m[3], m[7], m[11], *quaternion(m)])
        if role != 'hmd':
            c = frame[role]['controller']
            if any(type(c[k]) is not int or not 0 <= c[k] < 2**64 for k in ('pressed', 'touched')):
                raise ValueError('Controller masks must be unsigned 64-bit integers')
            if len(c['axes']) != 5 or any(len(pair) != 2 or any(not math.isfinite(v) or abs(v) > 1 for v in pair) for pair in c['axes']):
                raise ValueError('Controller needs five finite axis pairs in [-1, 1]')
            values.extend([c['pressed'], c['touched'], *[v for pair in c['axes'] for v in pair]])
    text = ' '.join(str(v) for v in values)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PATH.with_suffix('.tmp')
    temp.write_text(text, encoding='ascii')
    for attempt in range(40):
        try:
            os.replace(temp, PATH)
            _SEQUENCES[owner]=sequence
            frame['_publication']={'version':2,'owner':owner,'sequence':sequence,'command':command,
                                   'publishedTickMs':tick,'expiresTickMs':tick+5000}
            return frame['_publication']
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(.01)


def acknowledgement(frame):
    expected=frame.get('_publication',{})
    result={'acknowledgedByDriver':False,'gameConsumptionProven':False,'protocolVersion':2}
    path=PATH.with_name('ack.txt')
    try:
        if path.stat().st_size>1024:raise ValueError('Oversized driver acknowledgement')
        raw=path.read_text(encoding='ascii')
        if len(raw)>1024:raise ValueError('Growing driver acknowledgement exceeds bound')
        fields=raw.split()
        result.update(rawAcknowledgement=raw,observedTickMs=tick_ms())
        if len(fields)!=11 or fields[:2]!=['SKYRIM_AUTOTEST_ACK','2']:
            raise ValueError('Unknown driver acknowledgement format')
        instance,owner,sequence,command,at,until,roles,errors,expired=fields[2:]
        if not re.fullmatch(r'[1-9][0-9]*-[1-9][0-9]*',instance):raise ValueError('Driver identity unavailable')
        sequence,at,until,roles,errors,expired=map(int,(sequence,at,until,roles,errors,expired))
        now=tick_ms()
        if (owner!=expected.get('owner') or command!=expected.get('command') or
                sequence<expected.get('sequence',2**63) or not 0<=now-at<=2000 or
                not now<until<=now+5000 or not 0<=roles<=7 or not 0<=errors<=7 or expired not in (0,1)):
            raise ValueError('Stale, foreign, expired or mismatched driver acknowledgement')
        result.update(driverInstance=instance,sequence=sequence,command=command,rolesUpdated=roles,
                      errorRoles=errors,expired=bool(expired),acknowledgedByDriver=roles==7 and errors==0 and expired==0,
                      basis='Exact version/owner/command/sequence; driver submitted pose and successful component updates. Game consumption is separate.')
    except (OSError,UnicodeError,ValueError) as error:result['unavailableReason']=str(error)
    return result


def release(frame):
    changed=any(frame[role]['controller']['pressed'] or frame[role]['controller']['touched'] or
                any(v for pair in frame[role]['controller']['axes'] for v in pair) for role in ('left','right'))
    for role in ('left', 'right'):
        frame[role]['controller'].update(pressed=0, touched=0, axes=[[0, 0] for _ in range(5)])
    if changed:frame['_command']=uuid.uuid4().hex
