"""Owned startup and world loading, completed before subject scenario dispatch."""
import json
import time

from . import hardware, vr_probe


def advance_calibration(session):
    """One physical button only for the identified VR calibration screen."""
    menus = session.tool('menu', {'action': 'list'})
    if 'CalibrationOptionMenu' not in menus.get('openMenus', []):
        return False
    if menus.get('messageBoxOpen'):
        vr_probe.guard_fixture_modal(session)
        menus = session.tool('menu', {'action': 'list'})
    scene = session.tool('inspect', {'kind': 'scene'})
    if menus.get('messageBoxOpen') or scene.get('cell', {}).get('editorId') != 'VRPlayroom01':
        raise AssertionError('Calibration screen identity is ambiguous; no startup input sent')
    if session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file':
        raise AssertionError('Known calibration screen requires qualified physical input backend')
    session.phase('gameplay-startup-calibration-button', 25)
    end = time.monotonic() + 8
    while 'Fader Menu' in menus.get('openMenus', []):
        if time.monotonic() >= end:
            raise AssertionError('Startup fade remained active; no calibration input sent')
        time.sleep(.25)
        menus = session.tool('menu', {'action': 'list'})
        if menus.get('messageBoxOpen'):
            vr_probe.guard_fixture_modal(session)
            menus = session.tool('menu', {'action': 'list'})
    if 'CalibrationOptionMenu' not in menus.get('openMenus', []):
        return True
    session.log('gameplay-startup-screen', menus=menus, scene=scene)
    frame = hardware.neutral()
    frame['right']['controller'].update(pressed=1 << 33, touched=1 << 33,
                                        axes=[[0, 0], [1, 0], [0, 0], [0, 0], [0, 0]])
    try:
        session.tool('driver', {'action': 'publish', 'holdSeconds': 2, 'frame': frame})
        time.sleep(.15)
    finally:
        session.tool('driver', {'action': 'release'})
    end = time.monotonic() + 12
    while time.monotonic() < end:
        current = session.tool('menu', {'action': 'list'})
        if current.get('messageBoxOpen'):
            # A late known startup notification can consume UI input. Collect
            # its exact text; unknown choices remain terminal, never guessed.
            vr_probe.guard_fixture_modal(session)
            current = session.tool('menu', {'action': 'list'})
        if 'CalibrationOptionMenu' not in current.get('openMenus', []):
            session.log('gameplay-startup-screen-cleared', menus=current)
            return True
        time.sleep(.25)
    raise AssertionError('Startup calibration remained open after one physical button')


def start_new_game(session, cell):
    """Select the actual NEW item and confirm it through the live stock VR UI."""
    from .api_contract import validate_description
    from .runner import request
    methods = {'GetString': ['string', 'string'], 'GetInt': ['string', 'string'],
               'GetBool': ['string', 'string'], 'SetInt': ['string', 'string', 'int'],
               'InvokeInt': ['string', 'string', 'int'],
               'InvokeBool': ['string', 'string', 'bool']}
    description = session.tool('papyrus', {'action': 'describe', 'script': 'UI'})
    checked = validate_description('UI', description, 'globalFunctions', methods)
    session.log('new-game-ui-api-qualified', methods=checked)
    menu = 'Main Menu'
    root = '_root.MenuHolder.Menu_mc'

    def ui(function, target, *values):
        return session.tool('papyrus', {'action': 'call', 'script': 'UI',
                                      'function': function,
                                      'args': [menu, target, *values]})['returned']

    def main_state():
        menus = session.tool('menu', {'action': 'list'})
        if menus.get('messageBoxOpen'):
            vr_probe.guard_fixture_modal(session)
            menus = session.tool('menu', {'action': 'list'})
        if menu not in menus.get('openMenus', []):
            return None
        return ui('GetString', root + '.strCurrentState')

    session.phase('gameplay-new-game-menu', 45)
    end = time.monotonic() + 20
    while main_state() != 'Main':
        if time.monotonic() >= end:
            raise AssertionError('Identified main menu did not become ready for New Game')
        time.sleep(.25)
    count = ui('GetInt', root + '.MainList.entryList.length')
    if type(count) is not int or not 1 <= count <= 12:
        raise AssertionError('New Game menu list metadata unavailable')
    entries = []
    for index in range(count):
        path = root + '.MainList.entryList.' + str(index)
        entries.append({'position': index, 'text': ui('GetString', path + '.text'),
                        'index': ui('GetInt', path + '.index'),
                        'disabled': ui('GetBool', path + '.disabled')})
    session.log('new-game-menu-items', entries=entries)
    matches = [entry for entry in entries if entry['text'] == '$NEW'
               and entry['index'] == 1 and entry['disabled'] is False]
    if len(matches) != 1:
        raise AssertionError('Unique enabled NEW entry was not identified')
    ui('SetInt', root + '.MainList.selectedIndex', matches[0]['position'])

    def selected_new():
        return (ui('GetInt', root + '.MainList.selectedEntry.index') == 1
                and ui('GetString', root + '.MainList.selectedEntry.text') == '$NEW')

    if main_state() != 'Main' or not selected_new():
        raise AssertionError('New Game selection changed before activation')
    ui('InvokeInt', root + '.MainList.onItemPress', 0)
    end = time.monotonic() + 10
    while main_state() != 'MainConfirm':
        if time.monotonic() >= end:
            raise AssertionError('New Game did not expose its confirmation state')
        time.sleep(.25)
    if not selected_new():
        raise AssertionError('Main menu confirmation is for a different action')
    before = session.tool('inspect', {'kind': 'state'})
    baseline = request(session.state['port'], 'api/events')
    last_seq = max([event.get('seq', 0) for event in baseline.get('events', [])] + [0])
    session.log('new-game-request', selection=matches[0], before=before, afterSeq=last_seq)
    session.phase('gameplay-new-game-load', 120)
    ui('InvokeBool', root + '.onAcceptPress', False)
    end = time.monotonic() + 90
    last_logged_seq = last_seq
    while time.monotonic() < end:
        events = request(session.state['port'], 'api/events')
        fresh = [event for event in events.get('events', [])
                  if event.get('seq', 0) > last_seq
                  and event.get('frame', 0) >= before['frame']]
        if fresh and fresh[-1].get('seq', 0) != last_logged_seq:
            last_logged_seq = fresh[-1]['seq']
            session.log('new-game-transition-events', events=fresh)
        if any(event.get('topic') == 'lifecycle' and
               event.get('data', {}).get('event') in ('preLoadGame', 'postLoadGame')
               for event in fresh):
            raise AssertionError('New Game unexpectedly used a save-load transition')
        closed = [event for event in fresh if event.get('topic') == 'menu'
                  and event.get('data') == {'name': 'Main Menu', 'opening': False}]
        loading = [event for event in fresh if event.get('topic') == 'menu'
                   and event.get('data') == {'name': 'Loading Menu', 'opening': True}]
        loaded = [event for event in fresh if event.get('topic') == 'scene.cellLoaded'
                  and event.get('data', {}).get('cell') == cell]
        if closed and loading and loaded and closed[0]['seq'] <= loading[0]['seq'] < loaded[0]['seq']:
            session.state['newGameStarted'] = {'events': fresh, 'selection': matches[0],
                                              'evidenceBasis': 'Identified NEW confirmation and fresh menu/loading/cell transition',
                                              'lifecycleNewGameObserved': any(
                                                  e.get('topic') == 'lifecycle' and e.get('data', {}).get('event') == 'newGame'
                                                  for e in fresh),
                                              'saveLoaded': False, 'consoleBootstrap': False}
            session.state.setdefault('checks', []).append({
                'name': 'new game world transition observed', 'result': 'passed',
                'observation': session.state['newGameStarted']})
            session.save()
            session.log('gameplay-new-game-started', events=loaded)
            return
        time.sleep(.5)
    session.log('new-game-transition-timeout', events=events,
                menus=session.tool('menu', {'action': 'list'}),
                scene=session.tool('inspect', {'kind': 'scene'}))
    raise AssertionError('New Game request had no verified fresh world transition')


def prepare_gameplay(session, scenario):
    """Resolve the declared initial state once, without knowing a subject mod."""
    cell = scenario.get('cell')
    fixture = scenario.get('fixture')
    new_game = scenario.get('startMode') == 'new-game'
    if new_game and fixture:
        raise AssertionError('New Game cannot load a save fixture')
    if not cell and not fixture:
        raise AssertionError('Gameplay scenario requires an initial cell or pinned save')
    session.phase('gameplay-startup-screen', 35)
    end = time.monotonic() + 15
    while True:
        scene = session.tool('inspect', {'kind': 'scene'})
        if scene.get('cell', {}).get('editorId') != 'VRPlayroom01':
            break
        if advance_calibration(session):
            break
        if time.monotonic() >= end:
            raise AssertionError('VR playroom did not expose the supported startup screen')
        time.sleep(.25)
    if new_game:
        start_new_game(session, cell)
    if fixture:
        from .runner import request
        session.phase('gameplay-load-pinned-fixture', 120)
        before = session.tool('inspect', {'kind': 'state'})
        session.tool('game', {'action': 'load', 'name': fixture['saveStem']})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            events = request(session.state['port'], 'api/events')
            loaded = [event for event in events.get('events', [])
                      if event.get('topic') == 'lifecycle' and 'postLoadGame' in json.dumps(event)
                      and event.get('frame', 0) >= before['frame']]
            if loaded:
                session.log('gameplay-fixture-loaded', events=loaded)
                break
            time.sleep(1)
        else:
            raise AssertionError('Common gameplay fixture did not finish loading')
    session.phase('gameplay-world-ready', 120)
    vr_probe.guard_fixture_modal(session)
    if cell:
        if not new_game:
            session.tool('console', {'action': 'exec', 'command': 'coc ' + cell})
        scene = vr_probe.wait_test_cell(session, cell)
    else:
        scene = session.tool('inspect', {'kind': 'scene'})
    menus = session.tool('menu', {'action': 'list'})
    blocked = {'CalibrationOptionMenu', 'Main Menu', 'Loading Menu', 'RaceSex Menu'}
    if 'RaceSex Menu' in menus.get('openMenus', []):
        session.log('new-game-character-menu', menus=menus,
                    modal=session.tool('menu', {'action': 'describe'}))
    if (not scene.get('playerLoaded') or scene.get('cell', {}).get('editorId') == 'VRPlayroom01'
            or blocked.intersection(menus.get('openMenus', [])) or menus.get('messageBoxOpen')):
        raise AssertionError('Initialized gameplay is not ready: ' + json.dumps({'scene': scene, 'menus': menus}))
    session.state['gameplayBootstrap'] = {'completed': True, 'cell': cell,
                                          'loadedFixture': bool(fixture), 'startMode': scenario.get('startMode'),
                                          'scene': scene, 'menus': menus}
    session.save()
    session.log('gameplay-ready', scene=scene, menus=menus)
