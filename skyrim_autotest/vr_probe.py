"""Live hand integration probe; observations distinguish input from mod behavior."""
import copy
import json
import math
import time


def guard_fixture_modal(session):
    """A startup message can arrive after the first load-ready observation."""
    menus = session.tool('menu', {'action': 'list'})
    if not menus.get('messageBoxOpen'):
        return False
    modal = session.tool('menu', {'action': 'describe'})
    session.log('fixture-modal', result=modal)
    if len(modal.get('buttons', [])) != 1 or not modal.get('bodyText', '').startswith('Speech Broker на связи'):
        raise AssertionError('Fixture is gated by an unclassified modal: ' + json.dumps(modal))
    session.tool('menu', {'action': 'accept', 'matchBody': modal['bodyText']})
    end = time.monotonic() + 3
    while time.monotonic() < end:
        if not session.tool('menu', {'action': 'list'}).get('messageBoxOpen'):
            session.log('fixture-modal-cleared', body=modal['bodyText'])
            return True
        time.sleep(.1)
    raise AssertionError('Recognized fixture modal did not close')


def execute(session, scenario):
    if scenario.get('fixture'):
        session.phase('load-pinned-fixture', 120)
        before = session.tool('inspect', {'kind': 'state'})
        session.tool('game', {'action': 'load', 'name': scenario['fixture']['saveStem']})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            events = __import__('skyrim_autotest.runner', fromlist=['request']).request(session.state['port'], 'api/events')
            lifecycle = [e for e in events.get('events', []) if e.get('topic') == 'lifecycle' and 'postLoadGame' in json.dumps(e) and e.get('frame', 0) >= before['frame']]
            if lifecycle:
                session.log('fixture-loaded', events=lifecycle)
                break
            time.sleep(1)
        else:
            raise AssertionError('Pinned fixture did not finish loading')
    session.phase('bootstrap-test-cell', 120)
    if guard_fixture_modal(session):
        time.sleep(1)
    if not scenario.get('fixture'):
        # A fresh game's alternate-start quest can change cells after the first
        # coc. Initialize that world, then deliberately enter the test cell.
        session.tool('console', {'action': 'exec', 'command': 'coc ' + scenario['cell']})
        time.sleep(8)
    session.tool('console', {'action': 'exec', 'command': 'coc ' + scenario['cell']})
    end = time.monotonic() + 90
    stable_since = None
    while time.monotonic() < end:
        scene = session.tool('inspect', {'kind': 'scene'})
        session.log('bootstrap-scene', result=scene)
        if scenario['cell'].casefold() in json.dumps(scene).casefold():
            stable_since = stable_since or time.monotonic()
            if time.monotonic() - stable_since > 4:
                break
        else:
            stable_since = None
        time.sleep(1)
    else:
        raise AssertionError('Test cell did not load')
    session.state['checks'].append({'name': 'test cell loaded', 'result': 'passed', 'observation': scene})
    session.save()

    def papyrus(script, function, args=None, target=None):
        call = {'action': 'call', 'script': script, 'function': function, 'args': args or []}
        if target:
            call['self'] = {'form': target}
        return session.tool('papyrus', call)['returned']

    from . import native
    ensure_owned_focus(session, scenario, 'owned-game-focus')
    papyrus('Game', 'EnablePlayerControls', [True] * 8 + [0])
    time.sleep(.5)
    controls = {name: papyrus('Game', 'Is' + name + 'ControlsEnabled') for name in ('Movement', 'Fighting', 'Looking', 'Activate')}
    if not all(controls.values()):
        raise AssertionError('Player controls not ready: ' + json.dumps(controls))
    session.log('player-controls', controls=controls)

    def node_position():
        positions = {str(first): [papyrus('NetImmerse', 'GetNodeWorldPosition' + axis,
                        [{'form': '0x14'}, 'NPC R Hand [RHnd]', first]) for axis in 'XYZ'] for first in (False, True)}
        session.log('hand-node-positions', positions=positions)
        return positions

    def record(name, observation):
        session.state['checks'].append({'name': name, 'result': 'passed', 'observation': observation})
        session.save()

    # This fixture isolates physical HIGGS input from holster gestures. Body tracking
    # remains enabled. Change runtime settings only; never call VrikSaveSlots.
    for name, value in scenario.get('runtimeSlots', {}).items():
        previous = papyrus('VRIK', 'VrikGetSlot', [name])
        papyrus('VRIK', 'VrikSetSlot', [name, float(value)])
        current = papyrus('VRIK', 'VrikGetSlot', [name])
        if current != value:
            raise AssertionError('VRIK fixture setting did not apply: ' + name)
        record('VRIK runtime fixture setting', {'name': name, 'before': previous, 'during': current, 'persisted': False})
    for name, value in scenario.get('runtimeHiggs', {}).items():
        previous = papyrus('HiggsVR', 'GetSetting', [name])
        applied = papyrus('HiggsVR', 'SetSetting', [name, float(value)])
        current = papyrus('HiggsVR', 'GetSetting', [name])
        if not applied or abs(current - value) > .0001:
            raise AssertionError('HIGGS fixture setting did not apply: ' + name)
        record('HIGGS runtime fixture setting', {'name': name, 'before': previous, 'during': current, 'persisted': False})

    def start_pose(frame, duration=60000):
        if session.state.get('inputBackend') == 'driver':
            from . import hardware
            with session.lock:
                session.state['hardwareFrame'] = copy.deepcopy(frame)
                session.state['hardwareHoldUntil'] = time.time() + duration / 1000
                session.save()
                hardware.publish(frame)
            session.log('hardware-frame', frame=frame, durationMs=duration)
            return
        if session.state.get('vrControlToken'):
            stop_pose()
        last = copy.deepcopy(frame)
        frame['tMs'], frame['seq'] = 0, 1
        last['tMs'], last['seq'] = duration, 2
        result = session.tool('input', {'device': 'vrTrackedSet', 'action': 'sequence',
                                       'frames': [frame, last], 'tailMs': 1000})
        session.state['vrControlToken'] = result['controlToken']
        session.save()
        return result

    def stop_pose():
        if session.state.get('inputBackend') == 'driver':
            from . import hardware
            with session.lock:
                hardware.release(session.state['hardwareFrame'])
                session.save()
                hardware.publish(session.state['hardwareFrame'])
            return
        token = session.state.get('vrControlToken')
        if token:
            session.tool('input', {'device': 'vrTrackedSet', 'action': 'stop', 'controlToken': token})
            session.state.pop('vrControlToken', None)
            session.save()
            end = time.monotonic() + 5
            while time.monotonic() < end:
                status = session.tool('input', {'device': 'vrTrackedSet', 'action': 'status'})
                if not status.get('active') and not status.get('restoring') and not status.get('starting'):
                    return
                time.sleep(.1)
            raise AssertionError('VR sequence did not restore controller indices')

    def pose(device, xyz):
        device['matrix'] = [1, 0, 0, xyz[0], 0, 1, 0, xyz[1], 0, 0, 1, xyz[2]]

    session.phase('calibrate-neutral-pose', 60)
    frame = copy.deepcopy(session.tool('input', {'device': 'vrTrackedSet', 'action': 'observe'})['frame'])
    for role in ('hmd', 'left', 'right'):
        if not frame[role].get('valid'):
            raise AssertionError('Invalid virtual device: ' + role)
    pose(frame['hmd'], [0, 1.65, 0])
    pose(frame['left'], [-.3, 1.2, -.35])
    pose(frame['right'], [.3, 1.2, -.35])
    for role in ('left', 'right'):
        frame[role]['controller'].update(pressed=0, touched=0, packetNumber=1000, axes=[[0, 0]] * 5)
    start_pose(copy.deepcopy(frame))
    try:
        time.sleep(2)
        guard_fixture_modal(session)
        present = papyrus('NetImmerse', 'HasNode', [{'form': '0x14'}, 'NPC R Hand [RHnd]', session.state['driverBackend'] != 'file'])
        if not present:
            raise AssertionError('Player hand skeleton node is unavailable')
        initial_nodes = node_position()
        initial_hand = initial_nodes['True']
        record('neutral hand pose', initial_nodes)
    finally:
        stop_pose()
    moved = copy.deepcopy(frame)
    moved['right']['matrix'][3] += .2
    moved['right']['controller']['packetNumber'] = 1100
    session.phase('prove-hand-movement', 60)
    start_pose(copy.deepcopy(moved))
    try:
        time.sleep(1)
        end = time.monotonic() + 5
        while True:
            guard_fixture_modal(session)
            moved_nodes = node_position()
            moved_hand = moved_nodes['True']
            distance = math.dist(initial_hand, moved_hand)
            body_distance = math.dist(initial_nodes['False'], moved_nodes['False'])
            if distance >= 5 and body_distance >= 5 or time.monotonic() >= end:
                break
            time.sleep(.2)
        if distance < 5:
            raise AssertionError(f'Synthetic 20cm movement did not move the skeleton hand: {distance}')
        record('first-person hand responds to pose', {'before': initial_hand, 'after': moved_hand, 'distance': distance})
        session.state['checks'].append({'name': 'third-person hand responds to pose', 'result': 'passed' if body_distance >= 5 else 'failed',
                                      'observation': {'before': initial_nodes['False'], 'after': moved_nodes['False'], 'distance': body_distance}})
        session.save()
        if body_distance < 5:
            raise AssertionError('Third-person hand remained frozen after bounded readiness checks')
        session.log('probe-menus', result=session.tool('menu', {'action': 'list'}))
        try:
            providers = session.tool('capture', {'kind': 'providers'})
            session.log('capture-providers', result=providers)
            args = {'kind': 'auto', 'allowNative': False, 'checkpointId': session.state['id'] + '-hand', 'timeoutMs': 8000}
            session.log('probe-capture', result=session.tool('capture', args, timeout=12))
        except Exception as error:
            session.log('probe-capture-unavailable', error=str(error))
        if scenario.get('poseOnly'):
            if body_distance < 5:
                raise AssertionError('Third-person VRIK hand did not respond to physical pose')
            return
        if not papyrus('HiggsVR', 'CanGrabObject', [False]):
            raise AssertionError('HIGGS right hand is not ready to grab')
        # Spawn one owned test object, independent of whatever personal scene was saved.
        # Build physics at the target position rather than moving an already active
        # rigid body whose render and collision transforms may temporarily diverge.
        cursor = session.capture_probe_cursor()
        obj = papyrus('ObjectReference', 'PlaceAtMe', [{'form': scenario['object']}, 1, True, True], '0x14')
        ref = obj['formId']
        session.bind_probe_reference(ref, cursor)
        player_pos = [papyrus('ObjectReference', 'GetPosition' + axis, target='0x14') for axis in 'XYZ']
        # Place within the palm's near cast. The small forward offset avoids forcing
        # a contact impulse before the grip transition.
        finger_base = [papyrus('NetImmerse', 'GetNodeWorldPosition' + axis,
                       [{'form': '0x14'}, 'NPC R Finger11 [RF11]', True]) for axis in 'XYZ']
        if math.dist(finger_base, moved_hand) > 20:
            raise AssertionError('Palm landmark is inconsistent with the hand node')
        # Let the object settle on the floor, then bring the virtual hand to it.
        # HIGGS excludes keyframed clutter; floating dynamic items can be knocked
        # away during setup. A settled dynamic reference avoids both problems.
        right_axis = [(moved_hand[i] - initial_hand[i]) / distance for i in range(3)]
        forward_axis = [-right_axis[1], right_axis[0], 0]
        position = [player_pos[i] + forward_axis[i] * 42 + (20 if i == 2 else 0) for i in range(3)]
        papyrus('ObjectReference', 'MoveTo', [{'form': '0x14'}, *[position[i] - player_pos[i] for i in range(3)], False], ref)
        papyrus('ObjectReference', 'Enable', [False], ref)
        ready_end = time.monotonic() + 5
        while not papyrus('ObjectReference', 'Is3DLoaded', target=ref):
            if time.monotonic() > ready_end:
                raise AssertionError('Spawned test object has no loaded 3D')
            time.sleep(.05)
        # Loaded render nodes can precede Havok bodies. Wait for measurable mass
        # before changing motion type; an acknowledged setter is not readiness.
        mass_end = time.monotonic() + 5
        while True:
            mass = papyrus('ObjectReference', 'GetMass', target=ref)
            if isinstance(mass, (int, float)) and math.isfinite(mass) and mass > 0:
                break
            if time.monotonic() >= mass_end:
                raise AssertionError('Test object has no measurable physics mass: ' + str(mass))
            time.sleep(.1)
        record('test object has physics mass', mass)
        settled_end = time.monotonic() + 8
        last_pos, stable_since = None, None
        while time.monotonic() < settled_end:
            position = [papyrus('ObjectReference', 'GetPosition' + axis, target=ref) for axis in 'XYZ']
            if last_pos is not None and math.dist(last_pos, position) < .2:
                stable_since = stable_since or time.monotonic()
                if time.monotonic() - stable_since >= .5:
                    break
            else:
                stable_since = None
            last_pos = position
            time.sleep(.1)
        else:
            raise AssertionError('Dynamic test object did not settle')
        record('dynamic test object settled', {'form': ref, 'position': position})
        scale = distance / .2
        desired_hand = [position[i] - forward_axis[i] * 21 + (10 if i == 2 else 0) for i in range(3)]
        current_hand = moved_hand
        for _ in range(3):
            delta = [desired_hand[i] - current_hand[i] for i in range(3)]
            moved['right']['matrix'][3] += sum(delta[i] * right_axis[i] for i in range(3)) / scale
            moved['right']['matrix'][7] += delta[2] / scale
            moved['right']['matrix'][11] -= sum(delta[i] * forward_axis[i] for i in range(3)) / scale
            start_pose(copy.deepcopy(moved))
            time.sleep(.3)
            current_hand = node_position()['True']
            if math.dist(desired_hand, current_hand) < 3:
                break
        else:
            raise AssertionError('Virtual hand did not reach the settled object fixture')
        moved_hand = current_hand
        record('hand reached settled dynamic object', {'hand': moved_hand, 'objectPosition': position})
        loaded_3d = papyrus('ObjectReference', 'Is3DLoaded', target=ref)
        if not loaded_3d:
            raise AssertionError('Spawned test object has no loaded 3D')
        record('test object has loaded 3D', loaded_3d)
        session.log('object-position', form=ref, position=[papyrus('ObjectReference', 'GetPosition' + axis, target=ref) for axis in 'XYZ'])
        record('test object placed near hand', {'form': ref, 'hand': moved_hand, 'objectPosition': position})
    finally:
        stop_pose()
    gripping = copy.deepcopy(moved)
    button = scenario.get('button', 'grip')
    mask = {'grip': 4, 'trigger': 1 << 33}[button]
    gripping['right']['controller'].update(pressed=mask, touched=mask, packetNumber=1200)
    if button == 'trigger':
        gripping['right']['controller']['axes'][1] = [1, 0]
    session.phase('prove-controller-grab', 60)
    ensure_owned_focus(session, scenario, 'owned-game-focus-before-grab')
    # Give the game a complete neutral interval before the tested rising edge.
    start_pose(copy.deepcopy(moved))
    time.sleep(.5)
    guard_fixture_modal(session)
    start_pose(copy.deepcopy(gripping))
    try:
        session.log('grip-menus', result=session.tool('menu', {'action': 'list'}))
        end = time.monotonic() + 8
        held = None
        while time.monotonic() < end:
            held = papyrus('HiggsVR', 'GetGrabbedObject', [False])
            if isinstance(held, dict) and held.get('formId') == ref:
                break
            time.sleep(.2)
        else:
            session.log('failed-grip-hand-state', rightCanGrab=papyrus('HiggsVR', 'CanGrabObject', [False]),
                        rightGrabbedNode=papyrus('HiggsVR', 'GetGrabbedNodeName', [False]),
                        leftGrabbed=papyrus('HiggsVR', 'GetGrabbedObject', [True]),
                        ownedObjectPosition=[papyrus('ObjectReference', 'GetPosition' + axis, target=ref) for axis in 'XYZ'])
            # ReadController can dispatch mod callbacks; avoid perturbing input
            # edges during the assertion interval. Diagnose only after failure.
            session.log('failed-grip-observed', result=session.tool('input', {'device': 'vrTrackedSet', 'action': 'observe'}))
            if scenario.get('diagnoseScriptedGrab'):
                # Diagnostic only: the physical assertion already failed. Preserve
                # that failure even if the native API can force the object into hand.
                try:
                    papyrus('HiggsVR', 'GrabObject', [{'form': ref}, False])
                    time.sleep(1)
                    session.log('diagnostic-scripted-grab', acceptedAsPhysicalProof=False,
                                result=papyrus('HiggsVR', 'GetGrabbedObject', [False]))
                except Exception as error:
                    session.log('diagnostic-scripted-grab-error', error=str(error))
            raise AssertionError(f'Controller {button} did not grab the owned object {ref}: {held}')
        record('controller ' + button + ' causes HIGGS grab', held)
        # A competing mod can auto-equip a weapon within one physics frame.
        # A fleeting held reference is insufficient evidence of stable holding.
        stable_end = time.monotonic() + 1
        while time.monotonic() < stable_end:
            held = papyrus('HiggsVR', 'GetGrabbedObject', [False])
            if not isinstance(held, dict) or held.get('formId') != ref:
                raise AssertionError('Owned reference did not remain held while button stayed down: ' + str(held))
            time.sleep(.1)
        record('owned reference remains held with button down', held)
        if session.state.get('fault') == 'while-held':
            __import__('os')._exit(99)  # Guardian must recover with live input held.
    finally:
        stop_pose()
    session.phase('prove-controller-release', 60)
    start_pose(copy.deepcopy(moved))
    try:
        time.sleep(1)
        released = papyrus('HiggsVR', 'GetGrabbedObject', [False])
        if released is not None:
            raise AssertionError('HIGGS hand is not empty after release: ' + str(released))
        record('controller release causes HIGGS drop', released)
        dropped_3d = papyrus('ObjectReference', 'Is3DLoaded', target=ref)
        if dropped_3d is not True:
            raise AssertionError('Released test reference is not in the loaded world; pickup/equip is not a drop')
        record('released reference remains in the loaded world', {'form': ref, 'loaded3D': dropped_3d})
        finish_probe_reference(session, scenario, papyrus, ref)
    finally:
        stop_pose()
    if body_distance < 5:
        raise AssertionError('Grip/release finished, but third-person hand movement remains unproved')


def ensure_owned_focus(session, scenario, checkpoint):
    """Background VR is explicit and still requires unchanged physical assertions."""
    from . import native
    background = scenario.get('allowBackgroundVR', False)
    if background and (session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file'):
        raise ValueError('Background VR requires the physical file-adapter backend')
    result = native.focus_owned(session.state['game'])
    session.log(checkpoint, result=result)
    if not result['focused']:
        if not background:
            raise AssertionError('Windows did not grant foreground to the owned game')
        session.log('background-vr-attempt', checkpoint=checkpoint, foreground=result,
                    physicalAssertionsRequired=True, acceptedAsInputProof=False)
    return result


def finish_probe_reference(session, scenario, papyrus, ref):
    if scenario.get('postSteps'):
        # The continuation owns this exact live entity. The copied, non-saving
        # session is closed afterwards; never delete its old FormID after a load.
        session.save()
        session.log('probe-fixture-retained', form=ref, cleanup='owned-game-close')
        return
    session.validate_probe_reference()
    papyrus('ObjectReference', 'Disable', [False], ref)
    papyrus('ObjectReference', 'Delete', target=ref)
    session.state['probeObjectLive'] = False
    session.save()
