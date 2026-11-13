"""Direct fenced native startup UI, usable before Papyrus begins running."""
import math
import time

CONTRACT = 'devbench-gfx-main-menu/1'
MOVIE = '_root.MenuHolder.Menu_mc'


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


def _integer(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value != int(value) or abs(value) >= 10000:
        raise ValueError('Unexpected integral startup movie value')
    return int(value)


def _get(call, path, depth=2, limit=12):
    value = call('gfx', {'op': 'get', 'menu': 'Main Menu', 'path': path, 'depth': depth, 'limit': limit})
    if not isinstance(value, dict) or value.get('ok') is not True or value.get('truncated') is not False or 'value' not in value:
        raise ValueError('Complete official startup movie read unavailable')
    return value['value']


def snapshot_call(call):
    state = _get(call, MOVIE + '.strCurrentState')
    if not isinstance(state, str):
        raise ValueError('Identified startup movie state unavailable')
    data = {'contract': CONTRACT, 'menu': 'Main Menu', 'state': state, 'entries': [], 'selected': None}
    if state not in ('Main', 'MainConfirm'):
        return data
    count = _integer(_get(call, MOVIE + '.MainList.entryList.length'))
    if not 1 <= count <= 12:
        raise ValueError('Actual native startup list unavailable')
    rows = _get(call, MOVIE + '.MainList.entryList', depth=2)
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError('Complete actual startup entry list unavailable')
    for position, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get('text'), str) or type(row.get('disabled')) is not bool:
            raise ValueError('Typed startup menu entries unavailable')
        data['entries'].append({'position': position, 'index': _integer(row.get('index')),
                                'text': row['text'], 'disabled': row['disabled']})
    selected = _get(call, MOVIE + '.MainList.selectedEntry', depth=2)
    if selected not in (None, '<undefined>'):
        if not isinstance(selected, dict) or not isinstance(selected.get('text'), str) or type(selected.get('disabled')) is not bool:
            raise ValueError('Typed actual startup selection unavailable')
        data['selected'] = {'index': _integer(selected.get('index')), 'text': selected['text'], 'disabled': selected['disabled']}
    if _get(call, MOVIE + '.strCurrentState') != state:
        raise ValueError('Startup movie changed while read; no mutation')
    return data


def snapshot(session):
    return snapshot_call(session.tool)


def invocation_packet(operation):
    if operation in ('select-new', 'select-quit'):
        return {'op': 'call', 'menu': 'Main Menu', 'path': MOVIE + '.MainList.onItemPress', 'args': [0]}
    if operation in ('confirm-new', 'confirm-quit'):
        return {'op': 'call', 'menu': 'Main Menu', 'path': MOVIE + '.onAcceptPress', 'args': []}
    raise ValueError('Unsupported bounded startup operation')


def selection(data, state, selected=False):
    matches = [x for x in data['entries'] if x['index'] == 1 and x['text'] == '$NEW' and x['disabled'] is False]
    if data['state'] != state or len(matches) != 1:
        raise ValueError('Unique enabled native NEW selection/state unavailable')
    current = data.get('selected')
    if selected and (not isinstance(current, dict) or type(current.get('index')) is not int or
                     current.get('index') != 1 or current.get('text') != '$NEW' or current.get('disabled') is not False):
        raise ValueError('Native startup confirmation is for a different selection')
    return matches[0]


def mutate(session, operation, deadline):
    # One mutation invocation only. A lost acknowledgement never permits replay.
    def call(name, args):
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Original startup stage deadline exhausted; no invocation or replay')
        return session.tool(name, args, timeout=min(12, remaining), deadline=deadline)

    selecting = operation == 'select-new'
    if operation not in ('select-new', 'confirm-new'):
        raise ValueError('Unexpected new-game operation')
    before = snapshot_call(call)
    entry = selection(before, 'Main' if selecting else 'MainConfirm', selected=not selecting)
    if selecting:
        packet = {'op': 'set', 'menu': 'Main Menu', 'path': MOVIE + '.MainList.selectedIndex', 'value': entry['position']}
        session.log('startup-ui-intent', operation='set-new-selection', tool='gfx', arguments=packet)
        receipt = call('gfx', packet)
        if not isinstance(receipt, dict) or receipt.get('ok') is not True:
            raise ValueError('Startup selection write unavailable; do not replay')
        selection(snapshot_call(call), 'Main', selected=True)
    packet = invocation_packet(operation)
    session.log('startup-ui-intent', operation=operation, tool='gfx', arguments=packet)
    receipt = call('gfx', packet)
    if not isinstance(receipt, dict) or receipt.get('ok') is not True:
        raise ValueError('Native startup invocation completion unavailable; do not replay')
    session.log('startup-ui-invocation', operation=operation, transport=CONTRACT, receipt=receipt, acceptedAsWorldReadiness=False)
    if time.monotonic() >= deadline:
        raise TimeoutError('Native startup invocation returned after original stage deadline; no replay')


def start_new_game(session, cell):
    from .bootstrap import wait_new_game_transition
    from .readiness_reads import ReadinessSession
    session.phase('gameplay-new-game-menu', 45)
    _, cursor = listener_baseline(session, session.state.get('seStartupAdmission', {}).get('cursor'))
    end = time.monotonic() + 20
    reads = ReadinessSession(session, end)
    data = snapshot(reads)
    while data['state'] != 'Main':
        if time.monotonic() >= end:
            raise ValueError('Native Main menu did not settle; no startup mutation')
        time.sleep(min(.25, max(0, end-time.monotonic()))); data = snapshot(reads)
    entry = selection(data, 'Main')
    session.log('new-game-native-menu', snapshot=data, papyrusUsed=False)
    mutate(session, 'select-new', end)
    end = time.monotonic() + 10
    reads = ReadinessSession(session, end)
    data = snapshot(reads)
    while data['state'] != 'MainConfirm':
        if time.monotonic() >= end:
            raise ValueError('Native NEW confirmation did not settle; selection not replayed')
        time.sleep(min(.25, max(0, end-time.monotonic()))); data = snapshot(reads)
    selection(data, 'MainConfirm', selected=True)
    before, cursor = listener_baseline(session, cursor)
    session.log('new-game-request', selection=entry, before=before, afterSeq=cursor, transport=CONTRACT)
    session.phase('gameplay-new-game-load', 120)
    mutate(session, 'confirm-new', end)
    return wait_new_game_transition(session, cell, entry, before, cursor)
