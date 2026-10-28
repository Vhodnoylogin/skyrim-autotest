"""Bounded SE gameplay over native input, with separate witnessed fixtures.

Input acknowledgements are retained separately from actual game observations.
Equipment uses an explicit native Papyrus operation; it is not menu navigation.
All fixture tags expire on a load, even if the game later reuses their FormIDs.
"""
from __future__ import annotations

import copy
import math
import re
import uuid

from .actor_domain import bounded, form, returned_form
from .readiness_state import gameplay_ready, menus_block_gameplay

DOMAIN = 'se-gameplay'
ACTIONS = frozenset(('move', 'inventory-open', 'inventory-close', 'pickup', 'equip',
                     'unequip', 'weapon-draw', 'weapon-sheathe', 'attack',
                     'create-pickup-fixture', 'create-combat-fixture'))
FIXTURES = frozenset(('create-pickup-fixture', 'create-combat-fixture'))
INPUT_CONTRACT = {'name': 'devbench.input', 'version': {'major': 2, 'minor': 0}}
PLAYER = '0x00000014'
CONTROLS = {'forward': 'Forward', 'back': 'Back', 'left': 'Strafe Left', 'right': 'Strafe Right'}


def _tag(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', value):
        raise ValueError('SE gameplay requires a bounded fixture tag')


def _selector(value, item=False):
    if (type(value) is not dict or set(value) != ({'plugin', 'localId', 'type'} if item else {'plugin', 'localId'})
            or not isinstance(value['plugin'], str)
            or not re.fullmatch(r'[A-Za-z0-9 _.-]+\.(esm|esp)', value['plugin'], re.I)
            or not isinstance(value['localId'], str) or not re.fullmatch(r'[0-9a-fA-F]{1,6}', value['localId'])
            or not int(value['localId'], 16) or item and value['type'] not in ('WEAP', 'ARMO', 'MISC')):
        raise ValueError('SE gameplay requires an exact static plugin/local form selector')


def validate(operation, request):
    """Claim only this domain; reject unknown fields before any provider access."""
    if type(request) is not dict or request.get('domain') != DOMAIN:
        return False
    if operation == 'world.read':
        if (request.get('observation') != 'snapshot' or not {'domain', 'observation'} <= set(request)
                or set(request) - {'domain', 'observation', 'item'}):
            raise ValueError('SE gameplay read supports one current snapshot and optional item')
        if 'item' in request: _selector(request['item'], True)
        return True
    action = request.get('action')
    if action not in ACTIONS or operation != ('object.perform' if action in FIXTURES else 'input.perform'):
        raise ValueError('Unsupported SE gameplay operation/action')
    fields = {
        'move': {'direction', 'durationSeconds'},
        'pickup': {'referenceTag'}, 'equip': {'referenceTag', 'mechanism'},
        'unequip': {'referenceTag', 'mechanism'}, 'attack': {'actorTag', 'durationSeconds'},
        'create-pickup-fixture': {'referenceTag', 'item', 'distanceGameUnits'},
        'create-combat-fixture': {'actorTag', 'base', 'distanceGameUnits'},
    }.get(action, set())
    if set(request) != {'domain', 'action'} | fields:
        raise ValueError('Unsupported/missing SE gameplay request fields')
    for name in ('referenceTag', 'actorTag'):
        if name in request: _tag(request[name])
    if action == 'move':
        if request['direction'] not in CONTROLS: raise ValueError('Unsupported movement direction')
        bounded(request['durationSeconds'], .05, 1)
    if action == 'attack': bounded(request['durationSeconds'], .01, .15)
    if action in ('equip', 'unequip') and request['mechanism'] != 'papyrus-native':
        raise ValueError('Equipment requires the explicit papyrus-native mechanism')
    if action == 'create-pickup-fixture':
        _selector(request['item'], True); bounded(request['distanceGameUnits'], 50, 120)
    if action == 'create-combat-fixture':
        _selector(request['base']); bounded(request['distanceGameUnits'], 60, 100)
    return True


def _guard(b):
    from .fixture_actors import _owned
    if b.s.state.get('configuration', {}).get('game_edition') != 'se':
        raise ValueError('SE gameplay is unavailable for another game edition')
    _owned(b, b.s.state.get('game'))


def _pap(b, script, function, params, result, args=(), target=None, *, nullable=False):
    """Verify the exact actual native metadata, then issue one typed call."""
    from .interactive_bindings import _metadata, _native_call
    entry = {'script': script, 'function': function, 'scope': 'member' if target else 'global',
             'params': params, 'returnType': result}
    _metadata(b, entry)
    _guard(b)
    if nullable:
        # An empty crosshair is a valid native None, not a form identity.
        response = b.call('papyrus', {'action': 'call', 'script': script, 'function': function,
                         'args': list(args), 'timeoutMs': max(1, min(6000, int(b.remaining() * 1000)))})
        b.remaining()
        returned_type = str(response.get('returnedType', '')).casefold()
        if (response.get('called') is not True or 'returned' not in response
                or returned_type not in (result, 'none')
                or returned_type == 'none' and response['returned'] is not None):
            raise ValueError('Typed native nullable read unavailable')
        if response['returned'] is None: return None
        returned_form(response['returned'])
        return response['returned']
    return _native_call(b, entry, list(args), target)


def _menus(b, inventory=False):
    raw = b.call('menu', {'action': 'list', 'includeFlags': True})
    names, states = raw.get('openMenus'), raw.get('menuStates')
    if (not isinstance(names, list) or not isinstance(states, list)
            or any(not isinstance(n, str) for n in names)
            or any(not isinstance(r, dict) or not isinstance(r.get('name'), str) for r in states)
            or len(names) != len(set(names)) or len(names) != len(states)
            or set(names) != {r['name'] for r in states}):
        raise ValueError('Complete current native menu identities unavailable')
    opened = 'InventoryMenu' in raw.get('openMenus', [])
    filtered = copy.deepcopy(raw)
    filtered['openMenus'] = [name for name in raw.get('openMenus', []) if name != 'InventoryMenu']
    filtered['menuStates'] = [row for row in raw.get('menuStates', []) if row.get('name') != 'InventoryMenu']
    if menus_block_gameplay(filtered) or (opened and not inventory):
        raise ValueError('SE gameplay is blocked by an unexpected menu')
    # Validate the inventory menu's own native flag record as well.
    if opened:
        rows = [row for row in raw.get('menuStates', []) if row.get('name') == 'InventoryMenu']
        keys = ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause')
        if len(rows) != 1 or rows[0].get('available') is not True or any(type(rows[0].get(k)) is not bool for k in keys):
            raise ValueError('Actual inventory menu flag state unavailable')
    return raw, opened


def _ready(b, inventory=False):
    _guard(b)
    scene = b.call('inspect', {'kind': 'scene'})
    menus, opened = _menus(b, inventory)
    filtered = copy.deepcopy(menus)
    if inventory:
        filtered['openMenus'] = [n for n in menus['openMenus'] if n != 'InventoryMenu']
        filtered['menuStates'] = [r for r in menus['menuStates'] if r['name'] != 'InventoryMenu']
    if not gameplay_ready(scene, filtered): raise ValueError('Current owned gameplay world is not ready')
    return scene, opened


def _ref(b, reference):
    raw = b.call('inspect', {'kind': 'refs', 'formId': reference})
    rows = raw.get('refs')
    if not isinstance(rows, list) or len(rows) != 1 or form(rows[0].get('formId')) != reference:
        raise ValueError('Exact native reference readback unavailable')
    return rows[0]


def _vector(value):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError('Actual native position/rotation unavailable')
    return [bounded(v, -1e7, 1e7) for v in value]


def _inventory(b):
    raw = b.call('inspect', {'kind': 'inventory', 'formId': PLAYER, 'limit': 256})
    rows = raw.get('items')
    if (not isinstance(raw.get('owner'), dict) or form(raw['owner'].get('formId')) != PLAYER
            or not isinstance(rows, list) or raw.get('truncated') is not False
            or type(raw.get('count')) is not int or raw['count'] != len(rows)
            or type(raw.get('returned')) is not int or raw['returned'] != len(rows)):
        raise ValueError('Complete actual player inventory unavailable')
    ids = set()
    for row in rows:
        fid = form(row.get('formId'))
        if fid in ids or type(row.get('count')) is not int or row['count'] <= 0:
            raise ValueError('Actual inventory item identity/count unavailable')
        ids.add(fid)
    return raw


def _item_count(raw, base):
    rows = [r for r in raw['items'] if form(r['formId']) == base]
    return rows[0]['count'] if rows else 0


def _player(b):
    raw = b.call('inspect', {'kind': 'player'})
    if raw.get('playerLoaded') is not True: raise ValueError('Actual player readback unavailable')
    bounded(raw.get('actorValues', {}).get('health', {}).get('current'), 0, 1e7)
    if type(raw.get('equipped')) is not dict: raise ValueError('Actual player equipment unavailable')
    for hand in ('right', 'left', 'ammo'):
        value = raw['equipped'].get(hand)
        if value is not None:
            if not isinstance(value, dict): raise ValueError('Actual equipped identity unavailable')
            form(value.get('formId'))
        elif hand not in raw['equipped']: raise ValueError('Actual equipped identity unavailable')
    return raw


def _drawn(raw):
    hands = raw.get('hands', {})
    state = hands.get('weaponState')
    if state not in ('sheathed', 'drawing', 'drawn', 'sheathing', 'wantToDraw', 'wantToSheathe'):
        raise ValueError('Actual weapon state unavailable')
    return state == 'drawn', state == 'sheathed'


def _tap(b, control, seconds=.05, *, inventory=False, target=None):
    """Use observed control mapping and native game queue; no desktop input."""
    _guard(b)
    caps = b.call('input', {'action': 'capabilities'})
    keyboard = caps.get('capabilities', {}).get('keyboard', {})
    if (caps.get('contract') != INPUT_CONTRACT or type(keyboard.get('version')) is not int or keyboard['version'] != 1
            or keyboard.get('available') is not True or keyboard.get('ready') is not True
            or keyboard.get('injection') != 'Skyrim.BSInputEventQueue'
            or keyboard.get('encoding') != 'DirectInputScanCode' or 'tap' not in keyboard.get('actions', [])):
        raise ValueError('Qualified native SE input contract unavailable')
    code = _pap(b, 'Input', 'GetMappedKey', ['string', 'int'], 'int', [control, 0])
    if type(code) is not int or not 1 <= code <= 255:
        code = _pap(b, 'Input', 'GetMappedKey', ['string', 'int'], 'int', [control, 1])
        if type(code) is not int or not 256 <= code <= 258:
            raise ValueError('Control has no supported actual keyboard/mouse mapping: ' + control)
    keys = [r for r in keyboard.get('keys', []) if r.get('scancode') == code]
    if len(keys) != 1: raise ValueError('Observed mapped key is missing from native input catalog')
    owner = 'autotest-' + b.s.state['id']
    status = b.call('input', {'action': 'status'})
    if (status.get('contract') != INPUT_CONTRACT or status.get('ready') is not True
            or not isinstance(status.get('held'), list) or status['held']):
        raise ValueError('Native input must start with no held synthetic controls')
    args = {'device': 'keyboard', 'action': 'tap', 'key': code, 'owner': owner,
            'durationMs': max(10, round(seconds * 1000))}
    # Mapping/metadata/status are separate native reads. Recheck the owned scene,
    # current menus and target after those roundtrips, immediately before input.
    if _ready(b, inventory)[1] is not inventory:
        raise ValueError('Inventory state changed before the native input pulse')
    if target is not None: _crosshair(b, target)
    _guard(b)
    receipt = b.call('input', args)  # Once, including a lost/uncertain callback.
    b.s.log('se-gameplay-input', control=control, request=args, receipt=receipt, gameplayProven=False)
    if (receipt.get('contract') != INPUT_CONTRACT or receipt.get('action') != 'tap'
            or receipt.get('scancode') != code or receipt.get('stalled', False) is not False
            or type(receipt.get('down', {}).get('generation')) is not int or receipt['down']['generation'] <= 0
            or receipt.get('up', {}).get('generation') != receipt['down']['generation']
            or any(receipt.get(part, {}).get('owner') != owner
                   or receipt[part].get('accepted') is not True or receipt[part].get('pending') is not False
                   or receipt[part].get('scancode') != code for part in ('down', 'up'))
            or receipt['up'].get('released') is not True):
        raise ValueError('Native input completion/release unavailable; never replay')
    final = b.call('input', {'action': 'status'})
    if (final.get('contract') != INPUT_CONTRACT or final.get('ready') is not True
            or not isinstance(final.get('held'), list) or final['held']):
        raise ValueError('Native input release readback unavailable')
    _guard(b)
    return receipt


def _wait(b, sample, accepted):
    while True:
        _guard(b)
        result = sample()
        if accepted(result): return result
        b.pause(.1)


def _entry(b, tag, kind, *, picked=False):
    _guard(b)
    row = b.s.state.get('seGameplayFixtures', {}).get(tag)
    if (not isinstance(row, dict) or row.get('status') != ('picked-up' if picked else 'created')
            or row.get('kind') != kind or row.get('runId') != b.s.state.get('id')
            or row.get('game') != b.s.state.get('game')
            or row.get('worldGeneration') != b.s.state.get('ownedWorldGeneration')):
        raise ValueError('SE fixture has no current same-run/world creation witness')
    if not picked:
        if b.reference_incarnation(row['reference']) != row.get('incarnation'):
            raise ValueError('SE fixture incarnation changed')
        actual = _ref(b, row['reference'])
        if form(actual.get('base', {}).get('formId')) != row['base']:
            raise ValueError('SE fixture base identity changed')
    return row


def _crosshair(b, ref):
    value = _pap(b, 'Game', 'GetCurrentCrosshairRef', [], 'objectreference', nullable=True)
    if value is None or returned_form(value) != ref:
        raise ValueError('Actual crosshair does not select the exact owned fixture; no input issued')


def _combat_state(b, row):
    # The qualified SE Observer exposes identity, not the VR actorState domain.
    # Native SetRestrained completion is fixture preparation only; do not invent
    # a restraint readback. DevBench's native actor snapshot supplies live health.
    raw = _ref(b, row['reference'])
    if form(raw.get('base', {}).get('formId')) != row['base']:
        raise ValueError('Actual combat fixture base differs from its creation witness')
    state = raw.get('actor', {})
    bounded(state.get('health'), 0, 1e7)
    if state.get('alive') is not True or state.get('loaded3D') is not True:
        raise ValueError('Bounded controlled target is not alive/loaded')
    return state


def _create(b, request):
    action = request['action']; pickup = action == 'create-pickup-fixture'
    tag = request['referenceTag' if pickup else 'actorTag']
    _ready(b)
    records = b.s.state.setdefault('seGameplayFixtures', {})
    if tag in records or len(records) >= 8: raise ValueError('SE fixture tag already attempted or bound8 reached; no replay')
    selector = request['item'] if pickup else dict(request['base'], type='NPC_')
    base = form(b.resolve(selector))
    actual = _ref(b, base)
    if actual.get('formType') != selector['type'] or int(base, 16) >> 24 >= 0xFE:
        raise ValueError('Resolved static fixture type is unavailable or differs')
    player = _ref(b, PLAYER); pos = _vector(player.get('position')); rotation = _vector(player.get('rotation'))
    row = {'kind': 'pickup' if pickup else 'combat', 'runId': b.s.state['id'],
           'game': copy.deepcopy(b.s.state['game']), 'worldGeneration': b.s.state['ownedWorldGeneration'],
           'creationId': uuid.uuid4().hex, 'status': 'creating', 'base': base,
           'baseType': selector['type'], 'steps': {}}
    records[tag] = row; b.s.save()

    def mutate(script, fn, params, args, target=PLAYER, result='none'):
        row['steps'][fn] = 'intent'; b.s.save(); _guard(b)
        value = _pap(b, script, fn, params, result, args, target)
        row['steps'][fn] = 'returned'; b.s.save()
        return value

    ref = returned_form(mutate('ObjectReference', 'PlaceAtMe', ['form', 'int', 'bool', 'bool'],
                              [{'form': base}, 1, False, False], result='objectreference'))
    if int(ref, 16) >> 24 != 0xFF or any(r.get('reference') == ref for r in records.values()):
        raise ValueError('PlaceAtMe did not return a distinct created dynamic reference')
    row['reference'] = ref; b.s.save()
    _wait(b, lambda: _pap(b, 'ObjectReference', 'Is3DLoaded', [], 'bool', target=ref), lambda v: v is True)
    row['incarnation'] = b.reference_incarnation(ref); b.s.save()
    distance = float(request['distanceGameUnits']); yaw, pitch = rotation[2], rotation[0]
    if pickup:
        camera = b.call('camera', {'action': 'get'})
        if camera.get('freeCam') is not False: raise ValueError('Pickup fixture requires a normal gameplay camera')
        if camera.get('pov') != 'first':
            row['steps']['setPov'] = 'intent'; b.s.save()
            b.call('camera', {'action': 'setPov', 'pov': 'first'})
            camera = _wait(b, lambda: b.call('camera', {'action': 'get'}), lambda r: r.get('pov') == 'first' and r.get('freeCam') is False)
            row['steps']['setPov'] = 'returned'; b.s.save()
        eye = [bounded(camera.get('cam' + axis), -1e7, 1e7) for axis in 'XYZ']
        destination = [eye[0] + math.sin(yaw) * math.cos(pitch) * distance,
                       eye[1] + math.cos(yaw) * math.cos(pitch) * distance,
                       eye[2] - math.sin(pitch) * distance]
        mutate('ObjectReference', 'SetMotionType', ['int', 'bool'], [4, False], ref)
        mutate('ObjectReference', 'SetPosition', ['float'] * 3, destination, ref)
        row['fixturePolicy'] = 'keyframed item at measured first-person eye/player heading; exact crosshair still required'
    else:
        destination = [pos[0] + math.sin(yaw) * distance, pos[1] + math.cos(yaw) * distance, pos[2]]
        mutate('Actor', 'SetRestrained', ['bool'], [True], ref)
        mutate('Actor', 'SetActorValue', ['string', 'float'], ['Health', 1000.0], ref)
        mutate('Actor', 'RestoreActorValue', ['string', 'float'], ['Health', 1000.0], ref)
        mutate('ObjectReference', 'MoveTo', ['objectreference', 'float', 'float', 'float', 'bool'],
               [{'form': PLAYER}, destination[0] - pos[0], destination[1] - pos[1], 0.0, False], ref)
        row['fixturePolicy'] = 'one nonpersistent NPC; SetRestrained native call completed, actual restraint flag unavailable;1000 observed health, collisions retained, no damage mutation'
    placed = _wait(b, lambda: _ref(b, ref), lambda r: math.dist(_vector(r.get('position')), destination) <= 4)
    b.pause(.2)
    settled = _vector(_ref(b, ref).get('position'))
    if math.dist(settled, destination) > 4 or math.dist(settled, _vector(placed.get('position'))) > 1:
        raise ValueError('Created fixture position did not remain stable across200ms')
    if form(_ref(b, ref).get('base', {}).get('formId')) != base or b.reference_incarnation(ref) != row['incarnation']:
        raise ValueError('Created fixture identity changed during placement')
    if not pickup:
        health = _combat_state(b, row)['health']
        if abs(health - 1000) > 1: raise ValueError('Actual prepared combat target health is not1000')
    row['status'] = 'created'; row['position'] = destination; b.s.save()
    return {'fixture': {'created': True, 'kind': row['kind'], 'reference': ref, 'base': base},
            'fixturePolicy': row['fixturePolicy']}


def observe(b, request):
    validate('world.read', request)
    scene, opened = _ready(b, True)
    player, inventory = _player(b), _inventory(b)
    equipment = {hand: form(player['equipped'][hand]['formId']) if player['equipped'][hand] is not None else None
                 for hand in ('right', 'left', 'ammo')}
    result = {'gameplay': {'completed': True, 'observation': 'snapshot'},
              'player': {'currentHealthPoints': player['actorValues']['health']['current'],
                         'positionGameUnits': _vector(scene.get('position'))},
              'inventory': {'open': opened, 'items': copy.deepcopy(inventory['items'])}, 'equipment': equipment}
    if 'item' in request:
        base = form(b.resolve(request['item']))
        rows = [r for r in inventory['items'] if form(r['formId']) == base]
        if rows and type(rows[0].get('equipped')) is not bool: raise ValueError('Actual item worn/equipped state unavailable')
        result['item'] = {'runtimeId': base, 'quantityItems': _item_count(inventory, base),
                          'equipped': rows[0]['equipped'] if rows else False}
    _guard(b)
    return result


def perform(b, request):
    action = request.get('action')
    validate('object.perform' if action in FIXTURES else 'input.perform', request)
    _ready(b, action == 'inventory-close')
    if action in FIXTURES:
        result = _create(b, request)
    elif action == 'move':
        before = _vector(_ref(b, PLAYER).get('position'))
        receipt = _tap(b, CONTROLS[request['direction']], request['durationSeconds'])
        after = _wait(b, lambda: _vector(_ref(b, PLAYER).get('position')), lambda p: math.dist(before[:2], p[:2]) >= 1)
        result = {'movement': {'beforeGameUnits': before, 'afterGameUnits': after,
                              'distanceGameUnits': math.dist(before[:2], after[:2])}, 'inputReceipt': receipt}
    elif action in ('inventory-open', 'inventory-close'):
        want = action == 'inventory-open'
        if _menus(b, True)[1] is want: raise ValueError('Inventory action requires the opposite actual starting state')
        receipt = _tap(b, 'Quick Inventory', inventory=not want)
        _wait(b, lambda: _menus(b, True), lambda pair: pair[1] is want)
        result = {'inventory': {'open': want}, 'inputReceipt': receipt}
    elif action in ('weapon-draw', 'weapon-sheathe'):
        want = action == 'weapon-draw'
        before = _drawn(_player(b))
        if not before[1 if want else 0]: raise ValueError('Weapon action requires the opposite settled native starting state')
        receipt = _tap(b, 'Ready Weapon')
        _wait(b, lambda: _player(b), lambda p: _drawn(p)[0 if want else 1])
        result = {'weapon': {'drawn': want}, 'inputReceipt': receipt}
    elif action == 'pickup':
        row = _entry(b, request['referenceTag'], 'pickup')
        before = _item_count(_inventory(b), row['base'])
        _ref(b, row['reference'])
        _crosshair(b, row['reference'])
        row['pickupAttempted'] = True; row['status'] = 'pickup-intent'; b.s.save()
        receipt = _tap(b, 'Activate', target=row['reference'])
        inventory = _wait(b, lambda: _inventory(b), lambda inv: _item_count(inv, row['base']) != before)
        after = _item_count(inventory, row['base'])
        if after - before != 1: raise ValueError('Pickup did not produce the exact actual inventory delta1')
        # A consumed world reference must cease having loaded3D; no missing row is coerced to success.
        _wait(b, lambda: _pap(b, 'ObjectReference', 'Is3DLoaded', [], 'bool', target=row['reference']), lambda v: v is False)
        row['status'] = 'picked-up'; row['quantityBeforePickup'] = before; row['quantityAfterPickup'] = after; b.s.save()
        result = {'pickup': {'reference': row['reference'], 'quantityDeltaItems': after - before}, 'inputReceipt': receipt}
    elif action in ('equip', 'unequip'):
        row = _entry(b, request['referenceTag'], 'pickup', picked=True)
        if row.get('equipmentAttempt', {}).get('status') == 'intent':
            raise ValueError('Previous equipment mutation is uncertain; never replay')
        before = _inventory(b); items = [r for r in before['items'] if form(r['formId']) == row['base']]
        want = action == 'equip'
        if len(items) != 1 or type(items[0].get('equipped')) is not bool or items[0]['equipped'] is want:
            raise ValueError('Equipment action requires one owned inventory base in the opposite actual state')
        row['equipmentAttempt'] = {'status': 'intent', 'action': action}; b.s.save()
        _pap(b, 'Actor', 'EquipItem' if want else 'UnequipItem', ['form', 'bool', 'bool'], 'none',
             [{'form': row['base']}, False, False], PLAYER)
        def equipment_state():
            inventory = _inventory(b); player = _player(b)
            matches = [r for r in inventory['items'] if form(r['formId']) == row['base']]
            if len(matches) != 1 or type(matches[0].get('equipped')) is not bool:
                raise ValueError('Equipment readback lost the exact owned inventory item')
            if _item_count(inventory, row['base']) != _item_count(before, row['base']):
                raise ValueError('Equip/unequip changed the actual inventory quantity')
            hands = [form(v['formId']) for v in player['equipped'].values() if v is not None]
            state = matches[0]['equipped'] is want
            if row['baseType'] == 'WEAP': state = state and ((row['base'] in hands) is want)
            return state
        _wait(b, equipment_state, lambda v: v)
        row['equipmentAttempt']['status'] = 'completed'; b.s.save()
        result = {'equipment': {'equipped': want, 'runtimeId': row['base'], 'mechanism': 'papyrus-native', 'menuSelectionProven': False}}
    elif action == 'attack':
        row = _entry(b, request['actorTag'], 'combat')
        if row.get('attackAttempted'): raise ValueError('One attack per owned target; an attempted input is never replayed')
        if not _drawn(_player(b))[0]: raise ValueError('Controlled attack requires an actually settled drawn weapon')
        before = _combat_state(b, row); health = bounded(before['health'], 1, 1e7)
        b.pause(.2)
        _entry(b, request['actorTag'], 'combat')
        settled = _combat_state(b, row)
        if abs(settled['health'] - health) > .01:
            raise ValueError('Controlled target health changed before attack; no input issued')
        _crosshair(b, row['reference'])
        row['attackAttempted'] = True; b.s.save()
        receipt = _tap(b, 'Right Attack/Block', request['durationSeconds'], target=row['reference'])
        def health_state():
            _entry(b, request['actorTag'], 'combat')
            return _combat_state(b, row)
        after = _wait(b, health_state, lambda r: r['health'] < health)
        result = {'combat': {'reference': row['reference'], 'healthBeforePoints': health,
                             'healthAfterPoints': after['health'], 'healthDeltaPoints': after['health'] - health,
                             'targetAlive': True, 'attackInputs': 1,
                             'stableHealthBeforeInputSeconds': .2, 'matchedPlayerHitObserved': False,
                             'damageBasis': 'stable preattack health and exact-target health delta after one native player attack pulse; no matched hit-event provider'},
                  'inputReceipt': receipt}
    else:
        raise ValueError('Unsupported SE gameplay action')
    _guard(b)
    result['gameplay'] = {'completed': True, 'action': action}
    b.s.log('se-gameplay-observation', request=request, result=result, mutationReplayAllowed=False)
    return result
