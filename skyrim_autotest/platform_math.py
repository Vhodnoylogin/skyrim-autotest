"""Small measured-tracking coordinate solve; no requested pose-as-state shortcut."""
import math


def solve3(columns, value):
    rows = [[columns[c][r] for c in range(3)] + [value[r]] for r in range(3)]
    if any(not math.isfinite(v) for row in rows for v in row):
        raise ValueError('Nonfinite measured tracking transform')
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-5:
            raise ValueError('Tracking-to-skeleton transform is singular/unobserved')
        rows[col], rows[pivot] = rows[pivot], rows[col]
        divisor = rows[col][col]
        rows[col] = [v/divisor for v in rows[col]]
        for row in range(3):
            if row != col:
                factor = rows[row][col]
                rows[row] = [a-factor*b for a,b in zip(rows[row], rows[col])]
    return [row[3] for row in rows]


def pose_frames(start, target):
    """Interpolate valid rigid poses, preserving grip until the endpoint."""
    import copy
    from .hardware import quaternion
    roles = ('hmd', 'left', 'right')
    pairs = {}
    steps = 1
    for role in roles:
        a, b = start[role]['matrix'], target[role]['matrix']
        qa, qb = quaternion(a), quaternion(b)
        dot = sum(x*y for x,y in zip(qa,qb))
        if dot < 0: qb = [-v for v in qb]; dot = -dot
        angle = 2*math.acos(min(1., max(-1., dot)))
        distance = math.dist([a[i] for i in (3,7,11)], [b[i] for i in (3,7,11)])
        steps = max(steps, math.ceil(distance/.01), math.ceil(angle/.01))
        pairs[role] = (a,b,qa,qb)
    for step in range(1, steps+1):
        t = step/steps
        frame = copy.deepcopy(start)
        for role, (a,b,qa,qb) in pairs.items():
            q = [(1-t)*x+t*y for x,y in zip(qa,qb)]
            norm = math.sqrt(sum(v*v for v in q)); w,x,y,z = [v/norm for v in q]
            xyz = [(1-t)*a[i]+t*b[i] for i in (3,7,11)]
            frame[role]['matrix'] = [1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w),xyz[0],
                                     2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w),xyz[1],
                                     2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y),xyz[2]]
        yield frame
