"""Direct fenced native startup UI, usable before Papyrus begins running."""
import time

CONTRACT = 'devbench-startup-ui/1'


def snapshot(session):
    data = session.tool('menu', {'action': 'startup', 'startupOperation': 'snapshot'})
    if data.get('contract') != CONTRACT or data.get('menu') != 'Main Menu' or not isinstance(data.get('state'), str):
        raise ValueError('Direct startup UI contract unavailable; no Papyrus fallback')
    entries = data.get('entries')
    if not isinstance(entries, list) or len(entries) > 12:
        raise ValueError('Actual native startup list unavailable')
    for i, row in enumerate(entries):
        if (not isinstance(row, dict) or row.get('position') != i or type(row.get('position')) is not int or
                type(row.get('index')) is not int or not isinstance(row.get('text'), str) or type(row.get('disabled')) is not bool):
            raise ValueError('Typed startup menu entries unavailable')
    return data


def selection(data, state, selected=False):
    matches = [x for x in data['entries'] if x['index'] == 1 and x['text'] == '$NEW' and x['disabled'] is False]
    if data['state'] != state or len(matches) != 1:
        raise ValueError('Unique enabled native NEW selection/state unavailable')
    current = data.get('selected')
    if selected and (not isinstance(current, dict) or type(current.get('index')) is not int or
                     current.get('index') != 1 or current.get('text') != '$NEW' or current.get('disabled') is not False):
        raise ValueError('Native startup confirmation is for a different selection')
    return matches[0]


def mutate(session, operation):
    # One invocation only; timeout may have executed and is never replayed.
    receipt = session.tool('menu', {'action': 'startup', 'startupOperation': operation})
    if (receipt.get('contract') != CONTRACT or receipt.get('operation') != operation or
            receipt.get('completed') is not True):
        raise ValueError('Native startup invocation completion unavailable; do not replay')
    session.log('startup-ui-invocation', operation=operation, receipt=receipt, acceptedAsWorldReadiness=False)


def start_new_game(session, cell):
    from .runner import request
    from .bootstrap import wait_new_game_transition
    session.phase('gameplay-new-game-menu', 45)
    end = time.monotonic() + 20
    data = snapshot(session)
    while data['state'] != 'Main':
        if time.monotonic() >= end:
            raise ValueError('Native Main menu did not settle; no startup mutation')
        time.sleep(.25); data = snapshot(session)
    entry = selection(data, 'Main')
    session.log('new-game-native-menu', snapshot=data, papyrusUsed=False)
    mutate(session, 'select-new')
    end = time.monotonic() + 10
    data = snapshot(session)
    while data['state'] != 'MainConfirm':
        if time.monotonic() >= end:
            raise ValueError('Native NEW confirmation did not settle; selection not replayed')
        time.sleep(.25); data = snapshot(session)
    selection(data, 'MainConfirm', selected=True)
    before = session.tool('inspect', {'kind': 'state'})
    baseline = request(session.state['port'], 'api/events')
    cursor = max([e.get('seq', 0) for e in baseline.get('events', [])] + [0])
    session.log('new-game-request', selection=entry, before=before, afterSeq=cursor, transport=CONTRACT)
    session.phase('gameplay-new-game-load', 120)
    mutate(session, 'confirm-new')
    return wait_new_game_transition(session, cell, entry, before, cursor)
