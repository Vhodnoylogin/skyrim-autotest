"""Owned startup and world loading, completed before subject scenario dispatch."""
import json
import time

from . import hardware, vr_probe


def advance_calibration(session):
    """One physical button only for the identified VR calibration screen."""
    menus = session.tool('menu', {'action': 'list'})
    if 'CalibrationOptionMenu' not in menus.get('openMenus', []):
        return False
    scene = session.tool('inspect', {'kind': 'scene'})
    if menus.get('messageBoxOpen') or scene.get('cell', {}).get('editorId') != 'VRPlayroom01':
        raise AssertionError('Calibration screen identity is ambiguous; no startup input sent')
    if session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file':
        raise AssertionError('Known calibration screen requires qualified physical input backend')
    session.phase('gameplay-startup-calibration-button', 25)
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
        if 'CalibrationOptionMenu' not in current.get('openMenus', []):
            session.log('gameplay-startup-screen-cleared', menus=current)
            return True
        time.sleep(.25)
    raise AssertionError('Startup calibration remained open after one physical button')


def prepare_gameplay(session, scenario):
    """Resolve the declared initial state once, without knowing a subject mod."""
    cell = scenario.get('cell')
    fixture = scenario.get('fixture')
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
        session.tool('console', {'action': 'exec', 'command': 'coc ' + cell})
        scene = vr_probe.wait_test_cell(session, cell)
    else:
        scene = session.tool('inspect', {'kind': 'scene'})
    menus = session.tool('menu', {'action': 'list'})
    blocked = {'CalibrationOptionMenu', 'Main Menu', 'Loading Menu', 'RaceSex Menu'}
    if (not scene.get('playerLoaded') or scene.get('cell', {}).get('editorId') == 'VRPlayroom01'
            or blocked.intersection(menus.get('openMenus', [])) or menus.get('messageBoxOpen')):
        raise AssertionError('Initialized gameplay is not ready: ' + json.dumps({'scene': scene, 'menus': menus}))
    session.state['gameplayBootstrap'] = {'completed': True, 'cell': cell,
                                          'loadedFixture': bool(fixture), 'scene': scene, 'menus': menus}
    session.save()
    session.log('gameplay-ready', scene=scene, menus=menus)
