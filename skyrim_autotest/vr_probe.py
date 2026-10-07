"""Live hand integration probe; observations distinguish input from mod behavior."""
import copy
import json
import math
import time


def wait_test_cell(session, cell):
    """Observe exact cell identity and late startup dialogs; never repeat coc."""
    from .runner import HTTPResponseError, ToolError
    end = time.monotonic() + 90
    stable_since = None
    attempts, retries = 0, 0
    last_error = None
    consecutive_server_errors = 0
    while time.monotonic() < end:
        # Notifications can open during save/coc transitions, before scene data
        # becomes readable. Classify them in the common executor, not in orders.
        menus = session.tool('menu', {'action': 'list'}, deadline=end)
        if menus.get('messageBoxOpen'):
            guard_fixture_modal(session)
            stable_since = None
            continue
        attempts += 1
        try:
            scene = session.tool('inspect', {'kind': 'scene'}, timeout=12, deadline=end)
        except Exception as error:
            diagnostic = (error.body if isinstance(error, HTTPResponseError) else str(error))
            if ('json.exception.type_error.316' in diagnostic or
                    'invalid UTF-8 in tool output' in diagnostic):
                session.log('bootstrap-scene-terminal', attempt=attempts,
                            reason='provider-text-serialization', error=str(error))
                raise
            # These are candidate readiness failures, not proof of a transient
            # server condition. They cannot pass unless stable scene data follows.
            retryable = (
                isinstance(error, HTTPResponseError) and
                error.route == 'api/tool/inspect' and
                error.status in (500, 502, 503, 504)) or (
                isinstance(error, ToolError) and error.tool == 'inspect' and
                error.args_value == {'kind': 'scene'} and
                error.result.get('ok') is False and
                error.result.get('outcome') == 'abandoned_before_start')
            if not retryable:
                raise
            consecutive_server_errors = (consecutive_server_errors + 1
                                         if isinstance(error, HTTPResponseError) and error.status == 500 else 0)
            if consecutive_server_errors >= 3:
                session.log('bootstrap-scene-terminal', attempt=attempts,
                            reason='persistent-server-error', error=str(error), body=error.body)
                raise
            stable_since = None
            retries += 1
            last_error = str(error)
            details = ({'status': error.status, 'route': error.route, 'body': error.body}
                       if isinstance(error, HTTPResponseError) else {'result': error.result})
            session.log('bootstrap-scene-retry', attempt=attempts, error=last_error,
                        remainingSeconds=max(0, end - time.monotonic()), **details)
        else:
            consecutive_server_errors = 0
            now = time.monotonic()
            session.log('bootstrap-scene', result=scene, attempt=attempts)
            if now > end:
                session.log('bootstrap-scene-timeout', attempts=attempts, retries=retries,
                            reason='response-after-deadline', lastError=last_error)
                raise TimeoutError('Test cell response arrived after readiness deadline')
            identity = scene.get('cell')
            matches = (isinstance(identity, dict) and scene.get('playerLoaded') is True and
                       any(isinstance(identity.get(key), str) and
                           identity[key].casefold() == cell.casefold() for key in ('editorId', 'formId')))
            if matches:
                if stable_since is None:
                    stable_since = now
                if now - stable_since > 4:
                    session.log('bootstrap-scene-ready', attempts=attempts, retries=retries)
                    return scene
            else:
                stable_since = None
        time.sleep(min(1, max(0, end - time.monotonic())))
    session.log('bootstrap-scene-timeout', attempts=attempts, retries=retries, lastError=last_error)
    raise AssertionError('Test cell readiness could not be verified within 90 seconds' +
                         ('; last readiness error: ' + last_error if last_error else ''))


def log_modal_queue(session, name):
    """Temporary read-only diagnostic; never an alternate way to answer a menu."""
    from . import modal_debug
    try:
        value = modal_debug.snapshot(session.state['game'])
    except Exception as error:
        value = {'available': False, 'reason': str(error), 'diagnosticOnly': True}
    session.log(name, result=value)
    return value


def accept_known_vr_modal(session, modal, answered_ids):
    """One deferred native menu answer after matching the notification and button."""
    from .api_contract import validate_description
    description = session.tool('papyrus', {'action': 'describe', 'script': 'UI'})
    validate_description('UI', description, 'globalFunctions', {
        'GetString': ['string', 'string'], 'GetInt': ['string', 'string'],
        'GetBool': ['string', 'string']})

    def ui(function, path, *values):
        return session.tool('papyrus', {'action': 'call', 'script': 'UI',
                                      'function': function,
                                      'args': ['MessageBoxMenu', path, *values]})['returned']

    root = '_root.MessageMenu'
    def lines(value):
        return value.replace('\r\n', '\n').replace('\r', '\n') if isinstance(value, str) else None
    button = root + '.Buttons.Button0'
    end = time.monotonic() + 3
    while True:
        current = session.tool('menu', {'action': 'describe'})
        if current.get('bodyText') != modal['bodyText'] or current.get('buttons') != modal['buttons']:
            raise AssertionError('Startup modal changed during visible UI readiness; no answer sent')
        observed = {'bodyText': ui('GetString', root + '.Message.text'),
                    'buttonCount': ui('GetInt', root + '.MessageButtons.length'),
                    'buttonText': ui('GetString', button + '.ButtonText.text'),
                    'buttonName': ui('GetString', button + '._name'),
                    'buttonDisabled': ui('GetBool', button + '._disabled')}
        session.log('startup-modal-ui-identity', result=observed)
        if (lines(observed['bodyText']) == lines(modal['bodyText']) and observed['buttonCount'] == 1
                and observed['buttonText'] == modal['buttons'][0] and observed['buttonName'] == 'Button0'
                and observed['buttonDisabled'] is False):
            break
        if time.monotonic() >= end:
            break
        time.sleep(.1)
    coherent = (lines(observed['bodyText']) == lines(modal['bodyText'])
                and observed['buttonCount'] == 1 and observed['buttonText'] == modal['buttons'][0]
                and observed['buttonName'] == 'Button0' and observed['buttonDisabled'] is False)
    current = session.tool('menu', {'action': 'describe'})
    if current.get('bodyText') != modal['bodyText'] or current.get('buttons') != modal['buttons']:
        raise AssertionError('Startup modal changed before deferred answer; input not sent')
    # DevBench1.25 documents index:0 as SKSE AddTask, distinct from synchronous
    # matchBody. ACK is retained only as a request; the caller verifies closure.
    before = log_modal_queue(session, 'startup-modal-native-queue-before')
    if before.get('available'):
        queued = before.get('queued', [])
        if not queued or queued[-1]['id'] in answered_ids:
            raise AssertionError('Startup notification identity missing or already answered; no replay')
        if queued[-1]['bodyText'] != modal['bodyText'] or queued[-1]['buttons'] != modal['buttons']:
            raise AssertionError('Native notification identity does not match described modal')
    if not coherent:
        previous = getattr(session, 'state', {}).get('lastClosedStartupModal', {})
        prior_buttons = previous.get('buttons')
        stale_known_view = (lines(previous.get('bodyText')) == lines(observed['bodyText'])
                           and isinstance(prior_buttons, list) and 1 <= len(prior_buttons) <= 2
                           and observed['buttonCount'] == len(prior_buttons)
                           and prior_buttons[0] == observed['buttonText']
                           and observed['buttonName'] == 'Button0'
                           and observed['buttonDisabled'] is False)
        if stale_known_view:
            # A closed character confirmation has two buttons. Match every
            # retained label; a matching first button alone is insufficient.
            observed['buttonTexts'] = [observed['buttonText']] + [
                ui('GetString', root + '.Buttons.Button' + str(index) + '.ButtonText.text')
                for index in range(1, len(prior_buttons))]
            stale_known_view = observed['buttonTexts'] == prior_buttons
        if not stale_known_view or not before.get('available') or before.get('depth') != 1:
            raise AssertionError('Startup modal visible UI does not match classified single-button notification')
        # This operation answers native queue data, not the displayed movieclip.
        # Permit only a proved closed prior view and one exact current native box.
        session.log('startup-modal-stale-closed-view', previous=previous, displayed=observed,
                    native=before, answerTarget='single current native queue entry',
                    rendererQualified=False)
        fresh = session.tool('menu', {'action': 'describe'})
        again = log_modal_queue(session, 'startup-modal-native-target-recheck')
        if fresh.get('bodyText') != modal['bodyText'] or fresh.get('buttons') != modal['buttons'] or again != before:
            raise AssertionError('Native notification target changed before answer; no input sent')
    # This is a DevBench native queued answer, not OS keyboard/mouse input.
    # Foreground is irrelevant to its exact notification target and closure.
    # Keep all identity/replay guards and re-read immediately before mutation.
    session.log('startup-modal-native-answer-routing', foregroundRequired=False,
                route='owned DevBench native menu queue; no OS input')
    current = session.tool('menu', {'action': 'describe'})
    if current.get('bodyText') != modal['bodyText'] or current.get('buttons') != modal['buttons']:
        raise AssertionError('Startup modal changed before native answer; no answer sent')
    response = session.tool('menu', {'action': 'accept', 'index': 0})
    session.log('startup-modal-button-request', action='deferred native menu answer', index=0,
                body=modal['bodyText'], response=response, acceptedAsClosureProof=False)
    return before


def classify_startup_modal(session, modal):
    """Recognize notices, never choices about the subject mod."""
    if len(modal.get('buttons', [])) != 1:
        return None
    if isinstance(modal.get('bodyText'), str) and modal['bodyText'].startswith('Speech Broker на связи'):
        return 'speech-broker-notice'
    # Realm overrides Skyrim.esm MQ101TempChooseSidesMessage (000947D2).
    # Verified MESG/DSD pairs, restricted to its fresh character-completed world.
    realm = {
        'You find yourself someplace unknown... Somewhere outside of time and space.': ['Begin'],
        'Вы очутились в неизвестном месте... Где-то вне времени и пространства.': ['Начать']}
    state = getattr(session, 'state', {})
    if (realm.get(modal.get('bodyText')) == modal.get('buttons')
            and modal.get('cancelIndex') == -1 and state.get('newGameStarted')
            and state.get('characterCreationCompleted') and not state.get('gameplayBootstrap', {}).get('completed')
            and not state.get('realmStartupAcknowledged')):
        scene = session.tool('inspect', {'kind': 'scene'})
        if scene.get('playerLoaded') and scene.get('cell', {}).get('editorId') == 'RealmLorkhan':
            return 'realm-new-game-begin'
    return None


def guard_fixture_modal(session):
    """A startup message can arrive after the first load-ready observation."""
    menus = session.tool('menu', {'action': 'list'})
    if not menus.get('messageBoxOpen'):
        return False
    answered_ids = set()
    for _ in range(8):  # Finite startup work; never repeat one notification id.
        modal = session.tool('menu', {'action': 'describe'})
        session.log('fixture-modal', result=modal)
        session.log('startup-waiting-for-input', menu='MessageBoxMenu',
                    bodyText=modal.get('bodyText'), buttons=modal.get('buttons'),
                    reason='Blocking dialog requires an answer; tool responsiveness is not gameplay readiness')
        classification = classify_startup_modal(session, modal)
        if classification is None:
            raise AssertionError('Fixture is gated by an unclassified modal: ' + json.dumps(modal))
        session.log('startup-modal-classified', classification=classification)
        before = accept_known_vr_modal(session, modal, answered_ids)
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if not session.tool('menu', {'action': 'list'}).get('messageBoxOpen'):
                log_modal_queue(session, 'startup-modal-native-queue-after')
                session.log('fixture-modal-cleared', body=modal['bodyText'])
                if hasattr(session, 'state'):
                    session.state['lastClosedStartupModal'] = {'bodyText': modal['bodyText'],
                                                               'buttons': modal['buttons']}
                if classification == 'realm-new-game-begin':
                    session.state['realmStartupAcknowledged'] = True
                return True
            if before.get('available'):
                after = log_modal_queue(session, 'startup-modal-native-queue-after')
                if after.get('available'):
                    old_ids = [x['id'] for x in before['queued']]
                    new_ids = [x['id'] for x in after['queued']]
                    if new_ids == old_ids[:-1] and after['depth'] == before['depth'] - 1:
                        answered_ids.add(old_ids[-1])
                        session.log('startup-notification-answered', notificationId=old_ids[-1],
                                    remainingDepth=after['depth'], menuStillOpen=True)
                        if new_ids:
                            break  # Different queued notification; classify it from scratch.
                    elif new_ids != old_ids:
                        raise AssertionError('Startup queue changed outside the single answered notification')
            time.sleep(.1)
        else:
            following = session.tool('menu', {'action': 'describe'})
            log_modal_queue(session, 'startup-modal-native-queue-after')
            session.log('startup-modal-button-not-resolved', before=modal, after=following)
            raise AssertionError('Recognized fixture modal did not close: ' + json.dumps(following))
    raise AssertionError('Recognized startup notification queue exceeded bounded handling')


def execute(session, scenario):
    initialized = session.state.get('gameplayBootstrap', {})
    already_ready = initialized.get('completed') and initialized.get('cell') == scenario['cell']
    if scenario.get('fixture') and not already_ready:
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
    if already_ready:
        scene = initialized['scene']
    else:
        session.phase('bootstrap-test-cell', 120)
        if guard_fixture_modal(session):
            time.sleep(1)
    if not already_ready and not scenario.get('fixture') and not initialized.get('completed'):
        # A fresh game's alternate-start quest can change cells after the first
        # coc. Initialize that world, then deliberately enter the test cell.
        session.tool('console', {'action': 'exec', 'command': 'coc ' + scenario['cell']})
        time.sleep(8)
    if not already_ready:
        session.tool('console', {'action': 'exec', 'command': 'coc ' + scenario['cell']})
        scene = wait_test_cell(session, scenario['cell'])
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
        obj = papyrus('ObjectReference', 'PlaceAtMe', [{'form': scenario.get('object', '0x0006F993')}, 1, True, True], '0x14')
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
    gripping['right']['controller'].update(pressed=mask, touched=mask & (1 << 32), packetNumber=1200)
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


def ensure_owned_focus(session, scenario, checkpoint, deadline=None):
    """Bounded focus recovery, never replays a released physical action."""
    from . import native
    platform_background = (checkpoint.startswith('platform-') and
                           session.state.get('configuration', {}).get('allow_background_physical_vr') is True)
    background = scenario.get('allowBackgroundVR', False) or platform_background
    if background and (session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file'):
        raise ValueError('Background VR requires the physical file-adapter backend')
    end = time.monotonic() + 30
    if deadline is not None:
        end = min(end, deadline)
    if 'deadline' in session.state:
        end = min(end, time.monotonic() + max(0, session.state['deadline'] - time.time()))
    # Observe first: active input must be neutralized before any activation wait.
    result = (native.focus_owned(session.state['game'], timeout=max(.01, min(3, end-time.monotonic())))
              if background and not platform_background else native.focus_owned(session.state['game'], activate=False))
    session.log(checkpoint, result=result)
    if background:
        if not result['focused']:
            session.log('background-vr-attempt', checkpoint=checkpoint, foreground=result,
                        physicalAssertionsRequired=True, acceptedAsInputProof=False)
        return result
    paused, interrupted_input = False, False
    while not result['focused']:
        if not paused:
            interrupted_input = session.pause_focus_input()
            paused = True
        remaining = end - time.monotonic()
        if remaining <= 0:
            raise AssertionError('Windows did not grant foreground to the owned game within focus deadline')
        session.log('focus-waiting', checkpoint=checkpoint, remainingSeconds=remaining,
                    result=result, mutationsReplayed=False)
        time.sleep(min(.25, remaining))
        remaining = end - time.monotonic()
        if remaining <= 0:
            continue
        result = native.focus_owned(session.state['game'], timeout=min(2, remaining))
    if time.monotonic() > end:
        raise AssertionError('Owned game focus arrived after focus deadline')
    if paused:
        session.resume_focus_input()
        session.log('focus-recovered', checkpoint=checkpoint, mutationsReplayed=False)
        if interrupted_input:
            raise AssertionError('Focus recovered after active input was released; action not replayed')
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
