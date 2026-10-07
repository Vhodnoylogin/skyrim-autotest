"""Owned startup and world loading, completed before subject scenario dispatch."""
import json
import time

from . import hardware, vr_probe


def advance_calibration(session):
    """Bounded physical candidates only while the exact calibration stays open."""
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
    end = min(time.monotonic()+20, getattr(session, 'deadline', float('inf')))
    from .readiness_reads import ReadinessSession
    # Expiry must prevent another press, never the local neutral release.
    release_session = session.session if isinstance(session, ReadinessSession) else session
    session = ReadinessSession(session, end)

    def current_screen():
        current = session.tool('menu', {'action': 'list'})
        if current.get('messageBoxOpen'):
            vr_probe.guard_fixture_modal(session)
            current = session.tool('menu', {'action': 'list'})
        if 'CalibrationOptionMenu' not in current.get('openMenus', []):
            session.log('gameplay-startup-screen-cleared', menus=current)
        return current

    candidates = (('right','trigger'), ('left','trigger'),
                  ('right','grip'), ('left','grip'))
    for attempt, (hand, button) in enumerate(candidates, 1):
        # Every candidate needs a new known-screen observation and owned scene
        # read; a different world or unknown dialog never receives input.
        while True:
            current = current_screen()
            while 'Fader Menu' in current.get('openMenus', []):
                if time.monotonic() >= end:
                    raise AssertionError('Startup fade remained active; no further calibration input sent')
                time.sleep(.25)
                current = current_screen()
            if 'CalibrationOptionMenu' not in current.get('openMenus', []):
                return True
            scene = session.tool('inspect', {'kind':'scene'})
            current = current_screen()
            if 'CalibrationOptionMenu' not in current.get('openMenus', []):
                return True
            if 'Fader Menu' not in current.get('openMenus', []):
                break
        unexpected = set(current.get('openMenus', []))-{'CalibrationOptionMenu','HUD Menu'}
        if (current.get('messageBoxOpen') or unexpected or
                scene.get('cell',{}).get('editorId') != 'VRPlayroom01'):
            raise AssertionError('Calibration screen identity changed; no further startup input sent')
        if time.monotonic() >= end:
            raise TimeoutError('Startup calibration input deadline exhausted')
        session.log('gameplay-startup-screen', menus=current, scene=scene,
                    attempt=attempt, hand=hand, button=button)
        frame = hardware.neutral()
        mask = 1 << (33 if button == 'trigger' else 2)
        frame[hand]['controller'].update(pressed=mask, touched=mask,
            axes=[[0,0], [1 if button == 'trigger' else 0,0], [0,0], [0,0], [0,0]])
        try:
            publication = session.tool('driver', {'action':'publish','holdSeconds':2,'frame':frame})
            time.sleep(min(.35, max(0,end-time.monotonic())))
            acknowledgement = session.tool('driver', {'action':'status'})
            session.log('gameplay-startup-input-observed', attempt=attempt, hand=hand, button=button,
                        publication=publication, driverStatus=acknowledgement,
                        basis='Driver acknowledgement is separate from actual menu closure')
        finally:
            release_session.tool('driver', {'action':'release'})
        observe_end = min(end,time.monotonic()+2)
        while time.monotonic() < observe_end:
            current = current_screen()
            if 'CalibrationOptionMenu' not in current.get('openMenus', []):
                return True
            time.sleep(min(.25,max(0,observe_end-time.monotonic())))
    raise AssertionError('Startup calibration remained open after bounded observed trigger/grip candidates')


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
    session.log('new-game-loaded-plugins', result=session.tool('inspect', {'kind': 'mods'}))
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
                  and isinstance(event.get('data', {}).get('cell'), str)
                  and event['data']['cell'] not in ('', 'VRPlayroom01')]
        initial_scene = session.tool('inspect', {'kind':'scene'}) if closed and loading and loaded else {}
        transition = new_game_transition(closed, loading, loaded, initial_scene)
        if transition:
            initial_menus = session.tool('menu', {'action':'list','includeFlags':True})
            if {'Main Menu','Loading Menu'} & set(initial_menus.get('openMenus',[])):
                time.sleep(.5)
                continue
            session.state['newGameStarted'] = {'events': fresh, 'selection': matches[0],
                                              'evidenceBasis': 'Identified NEW confirmation and fresh menu/loading/cell transition',
                                              'initialScene': initial_scene, 'initialMenus': initial_menus,
                                              'requestedFixtureCell': cell,
                                              'lifecycleNewGameObserved': any(
                                                  e.get('topic') == 'lifecycle' and e.get('data', {}).get('event') == 'newGame'
                                                  for e in fresh),
                                              'saveLoaded': False, 'consoleBootstrap': False}
            check = {'name': 'new game world transition observed', 'result': 'passed',
                     'observation': session.state['newGameStarted'],
                     'provenance': {'schemaVersion': 1, 'component': 'skyrim-autotest',
                                    'stage': 'bootstrap', 'role': 'tooling',
                                    'runId': session.state['id'],
                                    'checkId': 'new-game-world-transition'}}
            session.state.setdefault('checks', []).append(check)
            session.save()
            # A report consumer must corroborate this same-run identity in both
            # retained state and the durable event log, never trust its name alone.
            session.log('executor-check', name=check['name'], result=check['result'],
                        provenance=check['provenance'])
            session.log('gameplay-new-game-started', events=loaded)
            return
        time.sleep(.5)
    session.log('new-game-transition-timeout', events=events,
                menus=session.tool('menu', {'action': 'list'}),
                scene=session.tool('inspect', {'kind': 'scene'}))
    raise AssertionError('New Game request had no verified fresh world transition')


def new_game_transition(closed, loading, loaded, scene):
    """Alternate starts choose the initial cell; the fixture cell comes afterward."""
    if not closed or not loading or scene.get('playerLoaded') is not True: return False
    current = scene.get('cell', {}).get('editorId')
    if not isinstance(current, str) or not current or current == 'VRPlayroom01': return False
    return any(closed[0]['seq'] <= loading[0]['seq'] < event['seq']
               and event.get('data', {}).get('cell') == current for event in loaded)


def complete_character_creation(session):
    """Finish the identified character menu, preserving its current appearance."""
    from .api_contract import validate_description
    validate_description('UI', session.tool('papyrus', {'action': 'describe', 'script': 'UI'}),
                         'globalFunctions', {'GetString': ['string', 'string'],
                         'GetBool': ['string', 'string'], 'GetInt': ['string', 'string'],
                         'SetString': ['string', 'string', 'string'],
                         'SetBool': ['string', 'string', 'bool'],
                         'InvokeBool': ['string', 'string', 'bool'],
                         'InvokeInt': ['string', 'string', 'int']})
    validate_description('Game', session.tool('papyrus', {'action': 'describe', 'script': 'Game'}),
                         'globalFunctions', {'GetGameSettingString': ['string']})
    menu = 'RaceSex Menu'
    root = '_root.RaceSexMenuBaseInstance.RaceSexPanelsInstance'
    def ui(function, path, *values):
        return session.tool('papyrus', {'action': 'call', 'script': 'UI',
                            'function': function, 'args': [menu, path, *values]})['returned']
    identity = {'core': ui('GetString', root + '.bottomBar._name'),
                'stock': ui('GetString', root + '.NameEntryInstance._name')}
    session.log('startup-waiting-for-input', menu=menu, identity=identity,
                reason='Character creation must finish before scenario input')
    core = identity['core'] == 'bottomBar'
    stock = identity['stock'] == 'NameEntryInstance'
    if core == stock:
        raise AssertionError('Unidentified or ambiguous character creation UI')
    entry = root + ('.textEntry' if core else '.NameEntryInstance')
    field_identity = {'entry': ui('GetString', entry + '._name'),
                      'input': ui('GetString', entry + '.TextInputInstance._name')}
    session.log('character-name-field-identity', result=field_identity)
    if field_identity != {'entry': 'textEntry' if core else 'NameEntryInstance',
                          'input': 'TextInputInstance'}:
        raise AssertionError('Character name field identity unavailable; no completion input sent')
    settings = {}
    for key in ('sRSMConfirm', 'sRSMFinishedWarning', 'sYes', 'sNo', 'sOK', 'sCancel'):
        settings[key] = session.tool('papyrus', {'action': 'call', 'script': 'Game',
                                   'function': 'GetGameSettingString', 'args': [key]})['returned']
    session.log('character-creation-settings', values=settings)
    # These calls execute inside the owned game's UI/Papyrus transport; no
    # desktop keyboard or mouse is sent. Foreground policy must not prevent
    # an otherwise verified native character-creation transition.
    session.log('character-creation-native-routing', transport='papyrus-ui-and-native-menu',
                foregroundRequired=False, acceptedAsReadinessProof=False)
    if menu not in session.tool('menu', {'action': 'list'}).get('openMenus', []):
        raise AssertionError('Character menu changed before completion request')
    ui('InvokeInt', root + '.onDoneClicked', 0)
    deadline = time.monotonic() + 15
    text_entry_requested = False
    while time.monotonic() < deadline:
        menus = session.tool('menu', {'action': 'list'})
        if menus.get('messageBoxOpen'):
            modal = session.tool('menu', {'action': 'describe'})
            session.log('character-creation-confirmation', result=modal)
            candidates = [settings[key] for key in ('sRSMConfirm', 'sRSMFinishedWarning')
                          if isinstance(settings[key], str) and settings[key]]
            cancel = modal.get('cancelIndex')
            known_buttons = ((settings['sYes'], settings['sNo'], 1),
                             (settings['sOK'], settings['sCancel'], -1))
            matched_buttons = any(all(isinstance(x, str) and x for x in (yes, no))
                                  and modal.get('buttons') == [yes, no] and cancel == index
                                  for yes, no, index in known_buttons)
            if modal.get('bodyText') not in candidates or not matched_buttons:
                raise AssertionError('Unclassified character confirmation; no answer sent')
            fresh = session.tool('menu', {'action': 'describe'})
            if fresh != modal:
                raise AssertionError('Character confirmation changed before answer')
            session.tool('menu', {'action': 'accept', 'index': 0})
            break
        time.sleep(.25)
    else:
        raise AssertionError('Character completion did not expose its identified confirmation')
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        menus = session.tool('menu', {'action': 'list'})
        if not menus.get('messageBoxOpen'):
            session.state['lastClosedStartupModal'] = {'bodyText': modal['bodyText'],
                                                       'buttons': modal['buttons']}
            shown = (ui('GetBool', entry + '._visible') and ui('GetBool', entry + '.enabled')
                     if core else ui('GetInt', root + '.Mode') == 0)
            session.log('character-name-entry', shown=shown, menus=menus)
            if shown:
                break
            if not text_entry_requested:
                if menu not in menus.get('openMenus', []):
                    raise AssertionError('Character menu closed before verified name entry')
                # Stock VR may request SteamVR's headset keyboard. Use the
                # identified movie's own text-entry frontend instead; the native
                # confirmation already advanced the engine to its naming stage.
                if core:
                    ui('InvokeBool', root + '.ShowTextEntry', True)
                else:
                    ui('SetBool', root + '.bShowTextEntry', True)
                ui('InvokeInt', root + '.ShowTextEntryField', 0)
                text_entry_requested = True
                session.log('character-name-frontend-request', layout='core' if core else 'stock',
                            acceptedAsReadinessProof=False)
        time.sleep(.25)
    else:
        raise AssertionError('Character confirmation did not expose name entry')
    ui('SetString', entry + '.TextInputInstance.text', 'Autotest')
    if ui('GetString', entry + '.TextInputInstance.text') != 'Autotest':
        raise AssertionError('Character name write not confirmed; no accept sent')
    if core:
        ui('InvokeInt', entry + '.onAccept', 0)
    else:
        # Stock VR's NameEntry sprite has no onAccept implementation. Its
        # headset keyboard delivers the registered ChangeName delegate instead.
        # SKSE InvokeStringA passes positional values; the delegate's opaque
        # response id is followed by the one verified name argument.
        validate_description('UI', session.tool('papyrus', {'action': 'describe', 'script': 'UI'}),
                             'globalFunctions', {'InvokeStringA': ['string', 'string', 'string[]']})
        if menu not in session.tool('menu', {'action': 'list'}).get('openMenus', []) or \
                ui('GetInt', root + '.Mode') != 0 or \
                ui('GetString', entry + '.TextInputInstance.text') != 'Autotest':
            raise AssertionError('Stock name entry changed before its native delegate')
        ui('InvokeStringA', '_global.flash.external.ExternalInterface.call',
           ['ChangeName', 'autotest-name', 'Autotest'])
        session.log('character-stock-name-delegate', name='Autotest',
                    readinessProof=False, reason='Stock VR native keyboard name handler')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        menus = session.tool('menu', {'action': 'list'})
        if menu not in menus.get('openMenus', []):
            session.log('character-creation-completed', name='Autotest', menus=menus)
            session.state['characterCreationCompleted'] = True
            return
        time.sleep(.25)
    raise AssertionError('Character menu remained open after one verified name acceptance')


def dismiss_navigation_gate(session, menus, attempted, deadline):
    """One native hide per known navigation menu; never answer arbitrary choices."""
    safe = {'Console', 'TweenMenu', 'Journal Menu', 'InventoryMenu', 'MagicMenu',
            'MapMenu', 'StatsMenu', 'FavoritesMenu'}
    if menus.get('messageBoxOpen') is not False: return False
    fields = ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause')
    for row in menus.get('menuStates', []):
        name = row.get('name')
        if name not in safe or row.get('available') is not True: continue
        if any(type(row.get(key)) is not bool for key in fields): continue
        from .readiness_state import menus_block_gameplay, world_loaded, gameplay_ready
        if not menus_block_gameplay(dict(messageBoxOpen=False,openMenus=[name],menuStates=[row])):
            continue
        if name in attempted: raise AssertionError('Navigation menu persisted or reopened after one close: '+name)
        fresh = session.tool('menu', {'action':'list','includeFlags':True})
        if any(fresh.get(key) != menus.get(key) for key in ('openMenus','menuStates','messageBoxOpen')):
            return False
        if time.monotonic() >= deadline: return False
        attempted.add(name)  # Durable log records intent before one mutation, never replay.
        session.log('gameplay-navigation-recovery-request', menu=name, observed=fresh,
                    policy='native hide known navigation only; verify closure and quiet world before input')
        response = session.tool('menu', {'action':'close','name':name})
        session.log('gameplay-navigation-recovery-receipt', menu=name, response=response,
                    acceptedAsReadinessProof=False)
        end = min(time.monotonic()+3, deadline)
        while time.monotonic() < end:
            current = session.tool('menu', {'action':'list','includeFlags':True})
            if name not in current.get('openMenus', []):
                session.log('gameplay-navigation-recovery-closed', menu=name, menus=current)
                return True
            time.sleep(.1)
        raise AssertionError('Navigation menu did not close after one native request: '+name)
    return False


def wait_gameplay_ready(session, cell, new_game, deadline=None, lifecycle_poll=None):
    """Require a quiet startup interval; late menus reset readiness."""
    from .readiness_state import menus_block_gameplay, world_loaded, gameplay_ready
    deadline = min(time.monotonic() + 90, deadline) if deadline is not None else time.monotonic() + 90
    from .readiness_reads import ReadinessSession
    session = ReadinessSession(session, deadline)
    stable_since = None
    character_seen = False
    navigation_attempts = set()
    while time.monotonic() < deadline:
        if lifecycle_poll is not None:
            lifecycle_poll()
        menus = session.tool('menu', {'action': 'list', 'includeFlags': True})
        if menus.get('messageBoxOpen'):
            vr_probe.guard_fixture_modal(session)
            stable_since = None
            continue
        opened = set(menus.get('openMenus', []))
        if 'RaceSex Menu' in opened:
            if not new_game or character_seen:
                raise AssertionError('Unexpected or repeated character creation menu')
            character_seen = True
            complete_character_creation(session)
            stable_since = None
            continue
        scene = session.tool('inspect', {'kind': 'scene'})
        current_cell = scene.get('cell', {}).get('editorId')
        loaded = world_loaded(scene, cell)
        blocked = menus_block_gameplay(menus)
        if loaded and blocked and dismiss_navigation_gate(session, menus, navigation_attempts, deadline):
            stable_since = None
            continue
        ready = gameplay_ready(scene, menus, cell)
        session.log('gameplay-readiness-observation', scene=scene, menus=menus, ready=bool(ready))
        if ready:
            if stable_since is None:
                stable_since = time.monotonic()
            if time.monotonic() - stable_since >= 8:
                return scene, menus
        else:
            stable_since = None
        time.sleep(.5)
    raise AssertionError('Initialized gameplay is not ready after stable startup/menu checks')


def prepare_startup_screen(session, deadline=None):
    """Common application-start transition, also used by an owned game restart."""
    session.phase('gameplay-startup-screen', 35)
    from .readiness_reads import ReadinessSession
    end = min(time.monotonic()+35,deadline) if deadline is not None else time.monotonic()+35
    session = ReadinessSession(session, end)
    while True:
        scene = session.tool('inspect', {'kind': 'scene'})
        if scene.get('cell', {}).get('editorId') != 'VRPlayroom01':
            break
        if advance_calibration(session):
            break
        if time.monotonic() >= end:
            raise AssertionError('VR playroom did not expose the supported startup screen')
        time.sleep(.25)


def prepare_gameplay(session, scenario):
    """Resolve the declared initial state once, without knowing a subject mod."""
    cell = scenario.get('cell')
    fixture = scenario.get('fixture')
    new_game = scenario.get('startMode') == 'new-game'
    if new_game and fixture:
        raise AssertionError('New Game cannot load a save fixture')
    if not cell and not fixture:
        raise AssertionError('Gameplay scenario requires an initial cell or pinned save')
    prepare_startup_screen(session)
    from .initial_world import InitialWorld
    initial = InitialWorld(session, 'fixture' if fixture else 'new-game' if new_game else 'cell')
    if new_game:
        start_new_game(session, cell)
        session.phase('gameplay-new-game-initial-world', 120)
        loaded_scene, _ = wait_gameplay_ready(session, None, True, lifecycle_poll=initial.read)
        session.log('gameplay-new-game-initial-world-ready', scene=loaded_scene,
                    requestedFixtureCell=cell, subjectStarted=False)
    if fixture:
        session.phase('gameplay-load-pinned-fixture', 120)
        session.tool('game', {'action': 'load', 'name': fixture['saveStem']})
        end = time.monotonic() + 90
        while time.monotonic() < end:
            if initial.fixture_loaded():
                session.log('gameplay-fixture-loaded', events=initial.record['events'])
                break
            time.sleep(1)
        else:
            raise AssertionError('Common gameplay fixture did not finish loading')
        # postLoadGame is a lifecycle signal, not settled render/gameplay state.
        # Never overlap a second world transition with save initialization.
        session.phase('gameplay-loaded-fixture-stabilization', 120)
        loaded_scene, _ = wait_gameplay_ready(session, None, False, lifecycle_poll=initial.read)
        session.log('gameplay-fixture-stable', scene=loaded_scene)
    session.phase('gameplay-world-ready', 120)
    vr_probe.guard_fixture_modal(session)
    if cell:
        already_in_cell = ((fixture or new_game) and loaded_scene.get('playerLoaded') is True and
                           loaded_scene.get('cell', {}).get('editorId') == cell)
        if not already_in_cell:
            session.tool('console', {'action': 'exec', 'command': 'coc ' + cell})
            session.log('gameplay-fixture-cell-requested', cell=cell,
                        afterInitialNewGameWorld=bool(new_game), subjectStarted=False)
        elif already_in_cell:
            session.log('gameplay-cell-transition-skipped', cell=cell,
                        reason='initialized fixture/new game already loaded in declared cell')
        scene = vr_probe.wait_test_cell(session, cell)
    else:
        scene = session.tool('inspect', {'kind': 'scene'})
    if vr_probe.guard_fixture_modal(session):
        # New-game scripts may post their notification only after cell loading.
        # Re-read the world after answering a classified notification.
        scene = session.tool('inspect', {'kind': 'scene'})
    scene, menus = wait_gameplay_ready(session, cell, False, lifecycle_poll=initial.read)
    initial.complete(scene, menus)
    session.state['gameplayBootstrap'] = {'completed': True, 'cell': cell,
                                          'loadedFixture': bool(fixture), 'startMode': scenario.get('startMode'),
                                          'scene': scene, 'menus': menus}
    session.save()
    session.log('gameplay-ready', scene=scene, menus=menus)
