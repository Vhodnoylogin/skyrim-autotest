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


def feedback_increment(columns, origin, baseline, commanded, observed, target):
    """Local measured-error servo, bounded per update, not a rigid IK model.

    The skeleton response can change with pose/grip. Its initial calibration
    cannot supply an absolute controller position. TargetProgress separately
    stops nonprogress before further commands; tracking lead is diagnostic.
    """
    actual=solve3(columns,[a-b for a,b in zip(observed,baseline)])
    error=solve3(columns,[a-b for a,b in zip(target,observed)])
    distance=math.sqrt(sum(v*v for v in error))
    fraction=min(1.,.01/distance) if distance else 0.
    change=[v*fraction for v in error]
    lead=[a-b-c for a,b,c in zip(commanded,origin,actual)]
    return change,{'targetDistanceMetres':distance,'trackingLeadMetres':lead,
                    'basis':'local observed target error; initial calibration is not an absolute rigid controller-to-skeleton model'}


class TargetProgress:
    """Lateral wobble must not renew a stalled target-distance deadline."""
    def __init__(self):
        self.best=None
        self.at=None

    def observe(self, distance, now):
        if not math.isfinite(distance) or distance<0 or not math.isfinite(now):
            raise ValueError('Invalid observed feedback progress')
        if self.best is None or distance<self.best-.005:
            self.best=distance
            self.at=now
        return now-self.at<=5


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


def world_translation(transform):
    """Observed world origin; orientation and scale do not participate."""
    value = transform.get('translation')
    if (not isinstance(value, list) or len(value) != 3 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in value)):
        raise ValueError('Scene world translation unavailable')
    return list(value)


def world_bounds_center(bounds, transform):
    """Observed scene-root transform of native local model bounds, not collision COM."""
    def finite(values, count):
        if not isinstance(values,list) or len(values)!=count or any(type(v) not in (int,float) or not math.isfinite(v) for v in values):
            raise ValueError('Bounds/scene transform numeric data unavailable')
        return values
    lower,upper=finite(bounds.get('min'),3),finite(bounds.get('max'),3)
    if any(a>b or b-a>512 for a,b in zip(lower,upper)):
        raise ValueError('Model bounds invalid or outside bounded grip domain')
    local=[(a+b)/2 for a,b in zip(lower,upper)]
    rotation=finite(transform.get('rotationRowMajor'),9)
    translation=world_translation(transform)
    scale=transform.get('scale')
    if type(scale) not in (int,float) or not math.isfinite(scale) or not 0<scale<=100:
        raise ValueError('Scene transform scale unavailable')
    rows=[rotation[i:i+3] for i in (0,3,6)]
    if any(abs(sum(a*b for a,b in zip(rows[i],rows[j]))-(1 if i==j else 0))>.001 for i in range(3) for j in range(3)):
        raise ValueError('Scene rotation is not orthonormal')
    determinant=sum(rows[0][i]*(rows[1][(i+1)%3]*rows[2][(i+2)%3]-rows[1][(i+2)%3]*rows[2][(i+1)%3]) for i in range(3))
    if abs(determinant-1)>.001:raise ValueError('Scene rotation handedness unavailable')
    return [translation[i]+scale*sum(rows[i][j]*local[j] for j in range(3)) for i in range(3)]


def body_reach_envelope(columns, shoulder, elbow, hand, target):
    """Generous observed-body workspace, not anatomical IK or a travel budget."""
    def metres(a, b):
        return math.sqrt(sum(v*v for v in solve3(columns, [x-y for x,y in zip(a,b)])))
    upper, lower = metres(shoulder, elbow), metres(elbow, hand)
    if not .05 <= upper <= 1.2 or not .05 <= lower <= 1.2 or not .2 <= upper+lower <= 1.4:
        raise ValueError('Observed arm geometry unavailable or extreme')
    # Permit bending/repositioning and scaled VR avatars. This deliberately
    # rejects only extremes, not normal reach from a previously distant pose.
    radius = min(2., 2*(upper+lower)+.2)
    distance = metres(shoulder, target)
    if distance > radius:
        raise ValueError('Target outside observed body reach envelope')
    return {'shoulderToTargetMetres': distance, 'armChainMetres': upper+lower,
            'bodyEnvelopeRadiusMetres': radius, 'basis': 'observed arm chain with generous bending margin; not anatomical IK'}


def fixture_offset(index, heading):
    """Distinct initial slots for up to16 small disposable fixture references."""
    if type(index) is not int or not 0 <= index < 16:
        raise ValueError('Fixture placement slot unavailable')
    lateral = (-30., -10., 10., 30.)[index % 4]
    forward = 42. + 20.*(index // 4)
    return [math.sin(heading)*forward + math.cos(heading)*lateral,
            math.cos(heading)*forward - math.sin(heading)*lateral, 20.]


def palm_cast_target(center, transform, geometry, columns, hand):
    """Put the requested model center at the configured near-cast endpoint."""
    position=list(geometry['palmPositionGameUnits'])
    direction=list(geometry['palmDirection'])
    if hand=='left':position[0]*=-1;direction[0]*=-1
    # Reuse strict observed rigid-transform validation without assuming an Euler order.
    world_bounds_center({'min':[0,0,0],'max':[0,0,0]},transform)
    rotation=transform['rotationRowMajor'];scale=transform['scale']
    offset=[scale*sum(rotation[i*3+j]*position[j] for j in range(3)) for i in range(3)]
    ray=[sum(rotation[i*3+j]*direction[j] for j in range(3)) for i in range(3)]
    norm=math.sqrt(sum(v*v for v in ray))
    if norm<.1:raise ValueError('Palm direction unavailable')
    ray=[v/norm for v in ray]
    metres_per_unit=math.sqrt(sum(v*v for v in solve3(columns,ray)))
    distance=geometry['nearCastDistanceMetres']/metres_per_unit
    return [center[i]-offset[i]-ray[i]*distance for i in range(3)]
