"""Owned SE world teardown, then the identified stock main-menu QUIT flow.

Every mutation has a durable, non-replayable intent. This helper never closes a
window or terminates a process; the caller retains its guarded fallback.
"""
import copy
import math
import time

from . import game_shutdown as exit_observation


CONTRACT = 'devbench-startup-ui/1'


def selection(snapshot, state, selected=False):
    if (not isinstance(snapshot, dict) or snapshot.get('contract') != CONTRACT
            or snapshot.get('menu') != 'Main Menu' or snapshot.get('state') != state):
        raise ValueError('Identified main-menu state unavailable for owned exit')
    rows = snapshot.get('entries')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 12:
        raise ValueError('Typed main-menu entries unavailable for owned exit')
    for i, row in enumerate(rows):
        if (not isinstance(row, dict) or type(row.get('position')) is not int or row['position'] != i
                or type(row.get('index')) is not int or not isinstance(row.get('text'), str)
                or type(row.get('disabled')) is not bool):
            raise ValueError('Malformed native main-menu entry')
    matches = [r for r in rows if r['text'] == '$QUIT' and r['index'] == 9 and not r['disabled']]
    if len(matches) != 1:
        raise ValueError('Unique enabled stock QUIT entry unavailable')
    current = snapshot.get('selected')
    if selected and (not isinstance(current, dict) or type(current.get('index')) is not int
                     or current['index'] != 9 or current.get('text') != '$QUIT'
                     or current.get('disabled') is not False):
        raise ValueError('Main-menu confirmation does not belong to QUIT')
    return matches[0]


def request_and_wait(session, seconds=45):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 60:
        raise ValueError('Menu exit needs a finite original bound in (0,60]seconds')
    if session.state.get('configuration', {}).get('game_edition') != 'se':
        raise ValueError('Native main-menu exit is SE-only')
    game = exit_observation._identity(session.state.get('game'))
    record = session.state.get('gracefulGameExit')
    if record is not None and (not isinstance(record, dict) or record.get('game') != game
                               or record.get('command') != 'menu-main-quit'):
        raise RuntimeError('Existing exit intent belongs to another process or route')
    if not exit_observation._alive(session, game, before_request=record is None):
        return exit_observation._capture_exited(session, game)
    if record is None:
        started = time.monotonic()
        record = {'game': game, 'command': 'menu-main-quit', 'status': 'preparing',
                  'startedMonotonic': started, 'deadlineMonotonic': started + seconds,
                  'graceSeconds': seconds, 'requestAttempted': False}
        session.state['gracefulGameExit'] = record
        session.save()

        def remaining():
            value = record['deadlineMonotonic'] - time.monotonic()
            if value <= 0:
                raise TimeoutError('Original menu exit bound expired; no further action')
            return value

        def call(name, args):
            return session.tool(name, args, timeout=min(4, remaining()), deadline=record['deadlineMonotonic'])

        def menus():
            value = call('menu', {'action': 'list'})
            if not isinstance(value, dict) or not isinstance(value.get('openMenus'), list):
                raise ValueError('Native open-menu state unavailable during exit')
            return value

        def snapshot():
            return call('menu', {'action': 'startup', 'startupOperation': 'snapshot'})

        def mutate(stage, name, args, *, desktop=False):
            remaining()
            if not exit_observation._alive(session, game, before_request=True):
                raise RuntimeError('Owned game ended before the next menu exit action')
            remaining()
            intent = {'game': copy.deepcopy(game), 'requestAttempted': True, 'arguments': copy.deepcopy(args)}
            record[stage] = intent
            if desktop:
                record['requestAttempted'] = True
            session.save()
            session.log('menu-game-exit-intent', stage=stage, intent=copy.deepcopy(intent))
            answer = call(name, args)
            intent['acknowledgement'] = copy.deepcopy(answer)
            session.save()
            return answer

        try:
            current = menus()
            if current.get('messageBoxOpen'):
                raise ValueError('Unknown message box prevents owned menu exit')
            if 'Main Menu' not in current['openMenus']:
                from .api_contract import validate_description
                description = call('papyrus', {'action': 'describe', 'script': 'Game'})
                api = validate_description('Game', description, 'globalFunctions', {'QuitToMainMenu': []})
                if api[0].get('native') is not True or str(api[0].get('returnType')).casefold() != 'none':
                    raise ValueError('Native Game.QuitToMainMenu signature unavailable')
                from .runner import request
                envelope = request(session.state['port'], 'api/events', timeout=min(3, remaining()))
                cursor = envelope.get('headSeq')
                if type(cursor) is not int or cursor < 0:
                    raise ValueError('Fresh exit lifecycle cursor unavailable')
                record['cursorBeforeMainMenu'] = cursor
                record['mainMenuApi'] = api
                session.save()
                answer = mutate('mainMenuReturn', 'papyrus', {'action': 'call', 'script': 'Game',
                    'function': 'QuitToMainMenu', 'args': []})
                if not isinstance(answer, dict) or 'returned' not in answer or answer['returned'] is not None:
                    raise ValueError('QuitToMainMenu completion unavailable; no replay')
                opened = False
                while True:
                    if not exit_observation._alive(session, game):
                        raise RuntimeError('Game ended before desktop quit was requested')
                    envelope = request(session.state['port'], 'api/events?since=' + str(cursor),
                                       timeout=min(3, remaining()))
                    events, head = envelope.get('events'), envelope.get('headSeq')
                    if not isinstance(events, list) or type(head) is not int or head < cursor:
                        raise ValueError('Exit event stream reset or malformed')
                    for event in events:
                        if (not isinstance(event, dict) or type(event.get('seq')) is not int
                                or event['seq'] != cursor + 1 or event['seq'] > head
                                or not isinstance(event.get('data'), dict)):
                            raise ValueError('Exit event stream has a gap')
                        cursor = event['seq']
                        data = event['data']
                        if event.get('topic') == 'lifecycle' and data.get('event') in ('newGame', 'preLoadGame', 'postLoadGame'):
                            raise ValueError('Unexpected world load during owned menu exit')
                        if event.get('topic') == 'menu' and data.get('name') == 'Main Menu':
                            if type(data.get('opening')) is not bool:
                                raise ValueError('Malformed Main Menu transition')
                            opened = data['opening']
                    record['mainMenuCursor'] = cursor
                    if opened and cursor == head and 'Main Menu' in menus()['openMenus']:
                        record['mainMenuOpenedObserved'] = True
                        session.save()
                        break
                    time.sleep(min(.2, remaining()))
            else:
                record['mainMenuAlreadyOpen'] = True
                session.save()
            # Movie animation can settle without repeating the world transition.
            while True:
                before = snapshot()
                if before.get('state') == 'Main':
                    selection(before, 'Main')
                    break
                if before.get('state') == 'MainConfirm':
                    raise ValueError('Unexpected existing confirmation; no exit selection')
                time.sleep(min(.2, remaining()))
            record['selectionBefore'] = copy.deepcopy(before)
            answer = mutate('quitSelection', 'menu', {'action': 'startup', 'startupOperation': 'select-quit'})
            if (not isinstance(answer, dict) or answer.get('contract') != CONTRACT
                    or answer.get('operation') != 'select-quit' or answer.get('completed') is not True):
                raise ValueError('QUIT selection completion unavailable; no replay')
            while True:
                before = snapshot()
                if before.get('state') == 'MainConfirm':
                    selection(before, 'MainConfirm', selected=True)
                    break
                time.sleep(min(.2, remaining()))
            record['desktopConfirmationBefore'] = copy.deepcopy(before)
            # The process may exit before its HTTP acknowledgement. The exact
            # durable desktop intent and retained exit handle are separate proof.
            try:
                answer = mutate('desktopQuit', 'menu', {'action': 'startup', 'startupOperation': 'confirm-quit'}, desktop=True)
                if (not isinstance(answer, dict) or answer.get('contract') != CONTRACT
                        or answer.get('operation') != 'confirm-quit' or answer.get('completed') is not True):
                    raise ValueError('Desktop quit acknowledgement unavailable; no replay')
            except Exception as error:
                record['desktopRequestError'] = {'type': type(error).__name__, 'message': str(error)}
            record['status'] = 'waiting'
            session.save()
        except Exception as error:
            record.update(status='menu-flow-unavailable', error={'type': type(error).__name__, 'message': str(error)})
            session.save()
            session.log('menu-game-exit-unavailable', record=copy.deepcopy(record), noReplay=True)
            return False
    started, deadline = record.get('startedMonotonic'), record.get('deadlineMonotonic')
    if (type(started) not in (int, float) or type(deadline) not in (int, float)
            or not math.isfinite(started) or not math.isfinite(deadline) or not 0 < deadline - started <= 60):
        raise RuntimeError('Original menu exit deadline unavailable; no replay')
    desktop = record.get('desktopQuit', {})
    if record.get('requestAttempted') is not True or desktop.get('requestAttempted') is not True or desktop.get('game') != game:
        return False
    while True:
        alive = exit_observation._alive(session, game)
        gone = exit_observation._capture_exited(session, game) if not alive else False
        remaining = deadline - time.monotonic()
        if gone or remaining <= 0:
            record.update(status='observed-gone' if gone else 'grace-expired', observedGone=gone,
                          waitFinishedMonotonic=time.monotonic())
            session.save()
            session.log('menu-game-exit-wait-finished', record=copy.deepcopy(record))
            return gone
        time.sleep(min(.2, remaining))
