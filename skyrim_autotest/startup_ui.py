"""Direct fenced native startup UI, usable before Papyrus begins running."""
import time

CONTRACT = 'devbench-startup-ui/1'


def listener_baseline(session, cursor):
    """Fresh owned menu/epoch proof without queuing an ordinary game task."""
    from .runner import request, native
    game = session.state.get('game')
    admission = session.state.get('seStartupAdmission', {})
    if (not isinstance(game, dict) or admission.get('completed') is not True or
            admission.get('game') != game or type(cursor) is not int or cursor < 0 or not native.alive(game)):
        raise ValueError('Owned native Main Menu admission is unavailable; no startup action')
    end = time.monotonic() + 6
    health = request(session.state['port'], 'api/health', timeout=3)
    if (health.get('ok') is not True or health.get('pid') != game.get('pid') or
            type(health.get('frame')) is not int or health['frame'] < 0):
        raise ValueError('Owned startup listener health identity/frame changed')
    for _ in range(3):
        remaining = end - time.monotonic()
        if remaining <= 0: break
        envelope = request(session.state['port'], 'api/events?since=' + str(cursor), timeout=min(3, remaining))
        events, head = envelope.get('events'), envelope.get('headSeq')
        if not isinstance(events, list) or type(head) is not int or head < cursor:
            raise ValueError('Startup listener stream reset or malformed')
        for event in events:
            if (not isinstance(event, dict) or type(event.get('seq')) is not int or
                    event['seq'] != cursor + 1 or event['seq'] > head or not isinstance(event.get('data'), dict)):
                raise ValueError('Startup listener event gap or malformed event')
            cursor = event['seq']; data = event['data']
            if event.get('topic') == 'lifecycle' and data.get('event') in ('newGame', 'preLoadGame', 'postLoadGame'):
                raise ValueError('Unexpected world transition before native NEW confirmation; no replay')
            if event.get('topic') == 'menu' and data.get('name') == 'Main Menu' and data.get('opening') is not True:
                raise ValueError('Native Main Menu admission closed or changed before confirmation')
        if cursor == head and time.monotonic() <= end:
            session.log('startup-ui-listener-baseline', health=health, cursor=cursor,
                        basis='owned listener identity and contiguous admitted Main Menu; not gameplay readiness')
            return health, cursor
    raise ValueError('Startup listener head not fully observed before deadline')


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
    from .bootstrap import wait_new_game_transition
    session.phase('gameplay-new-game-menu', 45)
    _, cursor = listener_baseline(session, session.state.get('seStartupAdmission', {}).get('cursor'))
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
    before, cursor = listener_baseline(session, cursor)
    session.log('new-game-request', selection=entry, before=before, afterSeq=cursor, transport=CONTRACT)
    session.phase('gameplay-new-game-load', 120)
    mutate(session, 'confirm-new')
    return wait_new_game_transition(session, cell, entry, before, cursor)
