"""Atomic leased physical OpenVR device frames for the external driver adapter."""
import math
import time
from pathlib import Path
import os
import threading
from . import runner

PATH = Path(os.environ['PROGRAMDATA']) / 'SkyrimVR Autotest/frame.txt'
_PUBLISH_LOCK = threading.RLock()


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
        _publish(frame)


def _publish(frame):
    values = [int(frame.get('seq', 1)), time.time()+5]
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
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(.01)


def release(frame):
    for role in ('left', 'right'):
        frame[role]['controller'].update(pressed=0, touched=0, axes=[[0, 0] for _ in range(5)])
