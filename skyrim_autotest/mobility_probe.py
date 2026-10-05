"""Bounded gameplay input observations independent of VRIK/HIGGS in a minimal world."""
import copy
import json
import math
import time

from . import hardware, runner, vr_probe


def tracked_xyz(device):
    if not isinstance(device, dict) or device.get('valid') is not True:
        raise AssertionError('Game-observed virtual device unavailable')
    matrix = device.get('matrix')
    if not isinstance(matrix, list) or len(matrix) != 12:
        raise AssertionError('Game-observed pose schema unavailable')
    values = [matrix[index] for index in (3, 7, 11)]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise AssertionError('Game-observed pose is not finite')
    return values


def keyboard_hold(session, key, seconds, sample=None):
    """One owned down/up pair; bounded server lease survives client loss."""
    owner = 'autotest-' + session.state['id']
    session.tool('input', {'device': 'keyboard', 'action': 'down', 'key': key,
                           'owner': owner, 'maxHoldMs': 4000})
    try:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if sample:
                sample()
            time.sleep(min(.05, max(0, end - time.monotonic())))
    finally:
        session.tool('input', {'device': 'keyboard', 'action': 'up', 'key': key, 'owner': owner})


def place_owned_fixture(papyrus, ref, xyz):
    """ObjectReference exposes one SetPosition(x,y,z), not per-axis setters."""
    if not isinstance(ref, str) or int(ref, 16) == 0x14:
        raise ValueError('Fixture placement must not move the player')
    if len(xyz) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in xyz):
        raise ValueError('Fixture position needs three finite coordinates')
    return papyrus('ObjectReference', 'SetPosition', list(xyz), target=ref)


def execute(session, scenario):
    if session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file':
        raise ValueError('Mobility probe requires the physical file adapter')
    failed = []

    def record(name, passed, observation):
        session.state['checks'].append({'name': name, 'result': 'passed' if passed else 'failed',
                                         'observation': observation})
        session.save()
        if not passed:
            failed.append(name)

    def papyrus(script, function, args=None, target=None):
        value = {'action': 'call', 'script': script, 'function': function, 'args': args or []}
        if target:
            value['self'] = {'form': target}
        return session.tool('papyrus', value)['returned']

    def position():
        return [papyrus('ObjectReference', 'GetPosition' + axis, target='0x14') for axis in 'XYZ']

    def observed():
        return session.tool('input', {'device': 'vrTrackedSet', 'action': 'observe'})['frame']

    def publish(frame, seconds=6):
        session.tool('driver', {'action': 'publish', 'holdSeconds': seconds, 'frame': frame})

    fixture = scenario.get('fixture')
    initialized = session.state.get('gameplayBootstrap', {})
    if fixture and not initialized.get('loadedFixture'):
        session.phase('mobility-load-fixture', 120)
        before = session.tool('inspect', {'kind': 'state'})
        session.tool('game', {'action': 'load', 'name': fixture['saveStem']})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            events = runner.request(session.state['port'], 'api/events')
            loaded = [event for event in events.get('events', [])
                      if event.get('topic') == 'lifecycle' and 'postLoadGame' in json.dumps(event)
                      and event.get('frame', 0) >= before['frame']]
            if loaded:
                session.log('fixture-loaded', events=loaded)
                break
            time.sleep(1)
        else:
            raise AssertionError('Mobility fixture did not finish loading')
    try:
        if initialized.get('completed') and initialized.get('cell') == scenario['cell']:
            scene = initialized['scene']
        else:
            raise AssertionError('Common gameplay bootstrap must complete before mobility actions')
    except AssertionError as error:
        record('mobility cell ready', False, {'reason': str(error)})
        raise
    record('mobility cell ready', True, scene)
    vr_probe.ensure_owned_focus(session, scenario, 'mobility-owned-focus')
    papyrus('Game', 'EnablePlayerControls', [True] * 8 + [0])
    controls = {name: papyrus('Game', 'Is' + name + 'ControlsEnabled')
                for name in ('Movement', 'Fighting', 'Looking', 'Activate')}
    record('mobility controls enabled', all(controls.values()), controls)
    caps = session.tool('input', {'action': 'capabilities'})
    session.log('mobility-input-capabilities', result=caps)

    frame = hardware.neutral()
    publish(frame)
    try:
        time.sleep(1)
        before = observed()
        moved = copy.deepcopy(frame)
        moved['left']['matrix'][3] -= .2
        moved['right']['matrix'][3] += .2
        publish(moved)
        time.sleep(1)
        after = observed()
        for role in ('left', 'right'):
            distance = math.dist(tracked_xyz(before[role]), tracked_xyz(after[role]))
            record('tracked ' + role + ' hand moves', .15 <= distance <= .3,
                   {'before': before[role], 'after': after[role], 'distanceMetres': distance,
                    'domain': 'game-accessed OpenVR tracking; not rendered skeleton proof'})
    finally:
        session.tool('driver', {'action': 'release'})
    publish(frame)
    try:
        session.phase('mobility-controller-forward', 35)
        start = position()
        forward = copy.deepcopy(frame)
        forward['left']['controller'].update(pressed=1 << 32, touched=1 << 32,
                                              axes=[[0, 1], [0, 0], [0, 0], [0, 0], [0, 0]])
        publish(forward, 4)
        time.sleep(1.5)
        end = position()
        distance = math.dist(start[:2], end[:2])
        record('controller forward movement', distance >= 10,
               {'start': start, 'end': end, 'horizontalDistanceEngineUnits': distance,
                'input': 'left Vive trackpad north pressed/touched; no teleport or scripted translation'})
    finally:
        session.tool('driver', {'action': 'release'})

    if scenario.get('keyboardDiagnostics', True):
        session.phase('mobility-keyboard-forward', 35)
        start = position()
        keyboard_hold(session, 'W', 1.5)
        end = position()
        record('keyboard forward movement', math.dist(start[:2], end[:2]) >= 10,
               {'start': start, 'end': end, 'horizontalDistanceEngineUnits': math.dist(start[:2], end[:2]),
                'input': 'DevBench BSInputEventQueue W; independent diagnostic, not physical-controller proof'})
        session.phase('mobility-keyboard-jump', 35)
        start = position()
        samples = []
        keyboard_hold(session, 'SPACE', .12, lambda: samples.append(position()))
        end_time = time.monotonic() + 1.2
        while time.monotonic() < end_time:
            samples.append(position())
            time.sleep(.05)
        rise = max([p[2] for p in samples] + [start[2]]) - start[2]
        record('keyboard jump changes height', rise >= 5,
               {'start': start, 'samples': samples, 'maxRiseEngineUnits': rise,
                'input': 'one DevBench SPACE down/up, no scripted jump'})

    session.phase('mobility-controller-jump', 35)
    start = position()
    jump = copy.deepcopy(frame)
    jump['right']['controller'].update(pressed=1 << 32, touched=1 << 32,
                                       axes=[[0, 1], [0, 0], [0, 0], [0, 0], [0, 0]])
    samples = []
    publish(jump, 2)
    try:
        time.sleep(.12)
    finally:
        session.tool('driver', {'action': 'release'})
    end_time = time.monotonic() + 1.2
    while time.monotonic() < end_time:
        samples.append(position())
        time.sleep(.05)
    rise = max([p[2] for p in samples] + [start[2]]) - start[2]
    record('controller jump changes height', rise >= 5,
           {'start': start, 'samples': samples, 'maxRiseEngineUnits': rise,
            'input': 'one right Vive trackpad north press/release; binding candidate explicitly tested'})

    if scenario.get('observer', True):
        session.phase('mobility-observer', 35)
        value = session.tool('inspect', {'kind': 'world_observer', 'refs': ['0x14']})
        record('mobility observer player available', value.get('ok') is True and
               value.get('refs', [{}])[0].get('status') == 'available', value)

    session.phase('mobility-vanilla-pickup', 60)
    base = {'form': '0x0006F993'}
    item_count = papyrus('ObjectReference', 'GetItemCount', [base], target='0x14')
    placed = papyrus('ObjectReference', 'PlaceAtMe', [base, 1, False, False], target='0x14')
    ref = placed.get('formId') if isinstance(placed, dict) else None
    if not isinstance(ref, str):
        raise AssertionError('Vanilla pickup fixture returned no exact reference')
    origin = position()
    heading = math.radians(papyrus('ObjectReference', 'GetAngleZ', target='0x14'))
    # One declared fixture placement in front of the neutral right-hand ray.
    target = [origin[0] + 21 * math.cos(heading) + 38 * math.sin(heading),
              origin[1] - 21 * math.sin(heading) + 38 * math.cos(heading), origin[2] + 84]
    place_owned_fixture(papyrus, ref, target)
    publish(frame)
    try:
        time.sleep(.5)
        crosshair = papyrus('Game', 'GetCurrentCrosshairRef')
        exact = isinstance(crosshair, dict) and str(crosshair.get('formId', '')).casefold() == ref.casefold()
        if exact:
            activate = copy.deepcopy(frame)
            activate['right']['controller'].update(pressed=1 << 33, touched=1 << 33,
                                                  axes=[[0, 0], [1, 0], [0, 0], [0, 0], [0, 0]])
            publish(activate, 2)
            time.sleep(.25)
            session.tool('driver', {'action': 'release'})
            time.sleep(.5)
            current = papyrus('ObjectReference', 'GetItemCount', [base], target='0x14')
            record('vanilla physical inventory pickup', current > item_count,
                   {'reference': ref, 'crosshair': crosshair, 'beforeCount': item_count,
                    'afterCount': current, 'input': 'one right Vive trigger press/release',
                    'domain': 'inventory acquisition, not HIGGS physical hold'})
        else:
            # Never activate another target or turn a scripted Activate into input proof.
            session.state['checks'].append({'name': 'vanilla physical inventory pickup',
                                            'result': 'unavailable', 'observation': {
                                                'reference': ref, 'crosshair': crosshair,
                                                'reason': 'Exact fixture not selected by the vanilla activation ray; input not sent'}})
            session.save()
    finally:
        session.tool('driver', {'action': 'release'})

    # HIGGS physical holding is unavailable in a pure Realm profile. It must not be
    # replaced with ObjectReference.Activate/MoveTo or counted as a passing grab.
    session.log('mobility-object-domain', physicalGrab=scenario.get('physicalGrab', False),
                minimalUnavailableReason=None if scenario.get('physicalGrab') else
                'Pure Realm profile has no HIGGS physical holding provider; no scripted substitute')
    if scenario.get('physicalGrab'):
        session.phase('mobility-physical-grab-fixture', 120)
        grab = {'schemaVersion': 1, 'kind': 'vr-hand-probe', 'cell': 'QASmoke',
                'allowBackgroundVR': scenario.get('allowBackgroundVR', False),
                'runtimeHiggs': {'NearCastRadius': .5}, 'button': 'grip'}
        if fixture:
            grab['fixture'] = fixture
        vr_probe.execute(session, grab)
    if failed:
        raise AssertionError('Mobility smoke mismatches: ' + ', '.join(failed))
