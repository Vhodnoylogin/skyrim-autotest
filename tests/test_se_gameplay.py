"""SE actions must observe an effect and never replay an uncertain mutation."""
import copy
import unittest
from unittest.mock import patch

from skyrim_autotest import se_gameplay as domain


ITEM = {'plugin': 'Skyrim.esm', 'localId': '1397E', 'type': 'WEAP'}
BASE = '0x0001397E'
ACTOR_BASE = '0x00013478'


def request(action, **fields):
    return {'domain': domain.DOMAIN, 'action': action, **fields}


class Session:
    def __init__(self):
        self.state = {'id': 'owned-run', 'game': {'pid': 42, 'birth': 123, 'path': 'SkyrimSE.exe'},
                      'configuration': {'game_edition': 'se'}, 'testProfile': 'Autotest-owned',
                      'ownedWorldGeneration': 1, 'gameplayBootstrap': {'completed': True}}
        self.saved, self.logs = [], []
    def save(self): self.saved.append(copy.deepcopy(self.state))
    def log(self, event, **fields): self.logs.append((event, fields))


class Backend:
    signatures = {
        'Input': {'GetMappedKey': (['string', 'int'], 'int')},
        'Game': {'GetCurrentCrosshairRef': ([], 'objectreference')},
        'ObjectReference': {'PlaceAtMe': (['form', 'int', 'bool', 'bool'], 'objectreference'),
            'Is3DLoaded': ([], 'bool'), 'SetMotionType': (['int', 'bool'], 'none'),
            'SetPosition': (['float'] * 3, 'none'),
            'MoveTo': (['objectreference', 'float', 'float', 'float', 'bool'], 'none')},
        'Actor': {'EquipItem': (['form', 'bool', 'bool'], 'none'),
            'UnequipItem': (['form', 'bool', 'bool'], 'none'), 'SetRestrained': (['bool'], 'none'),
            'SetActorValue': (['string', 'float'], 'none'), 'RestoreActorValue': (['string', 'float'], 'none')},
    }
    def __init__(self):
        self.s, self.calls, self.budget = Session(), [], 4
        self.position, self.rotation = [10., 20., 30.], [0., 0., 0.]
        self.open, self.drawn, self.equipped = False, False, False
        self.inventory, self.world, self.crosshair = {}, {}, None
        self.controls = {'Forward': 17, 'Back': 31, 'Strafe Left': 30, 'Strafe Right': 32,
                         'Quick Inventory': 23, 'Activate': 18, 'Ready Weapon': 19, 'Right Attack/Block': 256}
        self.effect, self.held, self.input_error, self.mutation_error = True, [], None, None
        self.native_ready, self.release_pending = True, False
        self.next_id, self.health_damage, self.corrupt_receipt = 0xFF000001, 8., False
        self.pickup_removes_reference, self.pickup_keeps_loaded, self.pickup_delta = False, False, 1
    def remaining(self):
        if self.budget <= 0: raise TimeoutError('original absolute deadline exhausted')
        return self.budget
    def pause(self, seconds): self.budget -= seconds; self.remaining()
    def guard_world(self): self.remaining()
    def reference_incarnation(self, ref):
        self.remaining()
        if not self.world[ref]['loaded']: raise ValueError('not loaded')
        return {'sessionId': 'native-owner', 'loadGeneration': 1, 'runtimeHandle': int(ref, 16)}
    def resolve(self, spec):
        return ACTOR_BASE if spec.get('type') == 'NPC_' else BASE
    def menus(self):
        names = ['InventoryMenu'] if self.open else []
        states = [{'name': n, 'available': True, 'alwaysOpen': False, 'pausesGame': True,
                   'modal': False, 'usesCursor': True, 'usesMenuContext': True, 'freezeFramePause': False} for n in names]
        return {'messageBoxOpen': False, 'openMenus': names, 'menuStates': states}
    def ref(self, ref):
        if ref == domain.PLAYER:
            return {'formId': ref, 'position': list(self.position), 'rotation': list(self.rotation)}
        if ref in (BASE, ACTOR_BASE): return {'formId': ref, 'formType': 'WEAP' if ref == BASE else 'NPC_'}
        value = self.world[ref]
        result = {'formId': ref, 'base': {'formId': value['base']}, 'position': value['position'], 'rotation': [0., 0., 0.]}
        if value['base'] == ACTOR_BASE:
            result['actor'] = {'alive': value['health'] > 0, 'health': value['health'], 'loaded3D': value['loaded']}
        return result
    def call(self, tool, args):
        self.remaining(); self.calls.append((tool, copy.deepcopy(args)))
        if tool == 'menu': return self.menus()
        if tool == 'camera':
            return {'pov': 'first', 'freeCam': False, 'camX': 10., 'camY': 20., 'camZ': 90.}
        if tool == 'inspect':
            if args['kind'] == 'scene': return {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}, 'position': list(self.position)}
            if args['kind'] == 'refs':
                ref = args['formId']
                if ref not in (domain.PLAYER, BASE, ACTOR_BASE) and ref not in self.world:
                    return {'count': 0, 'refs': []}
                return {'count': 1, 'refs': [self.ref(ref)]}
            if args['kind'] == 'world_observer':
                ref = args['refs'][0]; value = self.world[ref]
                return {'ok': True, 'refs': [{'status': 'available', 'identity': {'form': ref},
                    'baseForm': value['base'], 'loaded3D': value['loaded'],
                    'actorState': {'status': 'available', 'restrained': value.get('restrained', False)}}]}
            if args['kind'] == 'player':
                return {'playerLoaded': True, 'actorValues': {'health': {'current': 100.}},
                        'equipped': {'right': {'formId': BASE} if self.equipped else None, 'left': None, 'ammo': None},
                        'hands': {'weaponState': 'drawn' if self.drawn else 'sheathed'}}
            if args['kind'] == 'inventory':
                items = [{'formId': base, 'formType': 'WEAP', 'count': count, 'equipped': self.equipped}
                         for base, count in self.inventory.items() if count]
                return {'owner': {'formId': domain.PLAYER}, 'items': items,
                        'count': len(items), 'returned': len(items), 'truncated': False}
        if tool == 'input':
            if args['action'] == 'capabilities':
                return {'contract': copy.deepcopy(domain.INPUT_CONTRACT), 'capabilities': {'keyboard': {
                    'version': 1, 'available': True, 'ready': self.native_ready, 'injection': 'Skyrim.BSInputEventQueue',
                    'encoding': 'DirectInputScanCode', 'actions': ['tap'],
                    'keys': [{'scancode': value} for value in self.controls.values()]}}}
            if args['action'] == 'status': return {'contract': copy.deepcopy(domain.INPUT_CONTRACT), 'ready': True, 'held': self.held}
            if args['action'] == 'tap':
                if self.input_error: raise self.input_error
                key = args['key']
                if self.effect:
                    if key in (17, 31, 30, 32): self.position[1] += 20.
                    if key == 23: self.open = not self.open
                    if key == 19: self.drawn = not self.drawn
                    if key == 18:
                        if self.pickup_removes_reference: del self.world[self.crosshair]
                        else: self.world[self.crosshair]['loaded'] = self.pickup_keeps_loaded
                        self.inventory[BASE] = self.inventory.get(BASE, 0) + self.pickup_delta
                    if key == 256: self.world[self.crosshair]['health'] -= self.health_damage
                part = {'owner': args['owner'], 'generation': 1, 'accepted': True,
                        'pending': self.release_pending, 'released': True, 'scancode': key}
                receipt = {'contract': copy.deepcopy(domain.INPUT_CONTRACT), 'action': 'tap', 'scancode': key,
                           'down': copy.deepcopy(part), 'up': copy.deepcopy(part)}
                if self.corrupt_receipt: receipt['up']['generation'] = 2
                return receipt
        if tool == 'papyrus':
            script = args['script']
            if args['action'] == 'describe':
                methods = [{'name': fn, 'params': [{'type': p} for p in params], 'returnType': result, 'native': True}
                           for fn, (params, result) in self.signatures[script].items()]
                return {'name': script, 'globalFunctions': methods, 'memberFunctions': methods}
            fn, values, target = args['function'], args['args'], args.get('self', {}).get('form')
            result_type = self.signatures[script][fn][1]
            returned = None
            if fn == 'GetMappedKey':
                code = self.controls[values[0]]
                returned = code if (values[1] == 1) == (code >= 256) else -1
            elif fn == 'GetCurrentCrosshairRef': returned = {'formId': self.crosshair} if self.crosshair else None
            elif fn == 'PlaceAtMe':
                if self.mutation_error: raise self.mutation_error
                ref = f'0x{self.next_id:08X}'; self.next_id += 1
                self.world[ref] = {'base': values[0]['form'], 'position': list(self.position), 'loaded': True, 'health': 100.}
                self.crosshair = ref; returned = {'formId': ref}
            elif fn == 'Is3DLoaded': returned = self.world[target]['loaded']
            elif fn == 'SetPosition': self.world[target]['position'] = values
            elif fn == 'MoveTo': self.world[target]['position'] = [self.position[i] + values[1 + i] for i in range(3)]
            elif fn == 'SetActorValue': self.world[target]['health'] = values[1]
            elif fn == 'SetRestrained': self.world[target]['restrained'] = values[0]
            elif fn == 'EquipItem' and self.effect: self.equipped = True
            elif fn == 'UnequipItem' and self.effect: self.equipped = False
            return {'called': True, 'returnedType': result_type, 'returned': returned}
        raise AssertionError((tool, args))


class GameplayTests(unittest.TestCase):
    def setUp(self):
        self.native = patch('skyrim_autotest.fixture_actors.native.alive', return_value=True)
        self.native.start(); self.addCleanup(self.native.stop)
        self.b = Backend()
    def perform(self, action, **fields): return domain.perform(self.b, request(action, **fields))
    def create_item(self):
        return self.perform('create-pickup-fixture', referenceTag='dagger', item=ITEM, distanceGameUnits=75)
    def create_actor(self):
        return self.perform('create-combat-fixture', actorTag='target', base={'plugin': 'Skyrim.esm', 'localId': '13478'}, distanceGameUnits=80)
    def taps(self): return [a for t, a in self.b.calls if t == 'input' and a['action'] == 'tap']
    def test_owned_full_sequence_uses_native_inputs_and_actual_health_delta(self):
        moved = self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(moved['movement']['distanceGameUnits'], 20.)
        self.create_item(); picked = self.perform('pickup', referenceTag='dagger')
        self.assertEqual(picked['pickup']['quantityDeltaItems'], 1)
        self.assertTrue(self.perform('inventory-open')['inventory']['open'])
        self.assertFalse(self.perform('inventory-close')['inventory']['open'])
        equipped = self.perform('equip', referenceTag='dagger', mechanism='papyrus-native')
        self.assertTrue(equipped['equipment']['equipped']); self.assertFalse(equipped['equipment']['menuSelectionProven'])
        self.perform('weapon-draw'); self.create_actor()
        combat = self.perform('attack', actorTag='target', durationSeconds=.05)['combat']
        self.assertEqual(combat['healthDeltaPoints'], -8.); self.assertTrue(combat['targetAlive'])
        self.perform('weapon-sheathe'); self.perform('unequip', referenceTag='dagger', mechanism='papyrus-native')
        self.assertFalse(self.b.equipped)
        self.assertTrue(all(r['owner'] == 'autotest-owned-run' for r in self.taps()))
        self.assertFalse(any(t == 'console' for t, _ in self.b.calls))
        damage_calls = [a for t, a in self.b.calls if t == 'papyrus' and a.get('function') == 'DamageActorValue']
        self.assertEqual(damage_calls, [])
    def test_ack_without_movement_is_failure_and_tap_is_never_repeated(self):
        self.b.effect = False
        with self.assertRaises(TimeoutError): self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(len(self.taps()), 1)
    def test_lost_input_callback_is_terminal(self):
        self.b.input_error = OSError('uncertain native callback')
        with self.assertRaises(OSError): self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(len(self.taps()), 1)
    def test_uncertain_spawn_records_intent_and_same_tag_cannot_replay(self):
        self.b.mutation_error = OSError('lost spawn callback')
        with self.assertRaises(OSError): self.create_item()
        self.assertEqual(self.b.s.state['seGameplayFixtures']['dagger']['steps']['PlaceAtMe'], 'intent')
        with self.assertRaisesRegex(ValueError, 'already attempted'): self.create_item()
        self.assertEqual(len([a for t, a in self.b.calls if t == 'papyrus' and a.get('function') == 'PlaceAtMe']), 1)
    def test_wrong_crosshair_never_activates_or_attacks(self):
        self.create_item(); self.b.crosshair = None
        with self.assertRaisesRegex(ValueError, 'exact owned fixture'): self.perform('pickup', referenceTag='dagger')
        self.assertEqual(self.taps(), [])
    def test_pickup_removed_reference_uses_explicit_native_absence_without_deleted_papyrus_self(self):
        self.create_item(); self.b.pickup_removes_reference = True
        value = self.perform('pickup', referenceTag='dagger')
        self.assertEqual(value['pickup']['quantityDeltaItems'], 1)
        self.assertEqual(value['pickup']['worldReferenceState'], 'absent')
        self.assertEqual(value['consumedReferenceObservation']['nativeLookup'], {'count': 0, 'refs': []})
        tap_index = next(i for i, (tool, args) in enumerate(self.b.calls) if tool == 'input' and args['action'] == 'tap')
        self.assertFalse(any(tool == 'papyrus' and args.get('function') == 'Is3DLoaded'
                             for tool, args in self.b.calls[tap_index + 1:]))
        self.assertEqual(len(self.taps()), 1)
    def test_pickup_extant_unloaded_reference_requires_actual_loaded3d_read(self):
        self.create_item(); value = self.perform('pickup', referenceTag='dagger')
        self.assertEqual(value['pickup']['worldReferenceState'], 'unloaded')
        self.assertIs(value['consumedReferenceObservation']['loaded3D'], False)
        self.assertEqual(len(self.taps()), 1)
    def test_pickup_inventory_delta_without_world_consumption_fails_without_repeated_input(self):
        self.create_item(); self.b.pickup_keeps_loaded = True
        with self.assertRaises(TimeoutError): self.perform('pickup', referenceTag='dagger')
        self.assertEqual(self.b.inventory[BASE], 1)
        self.assertEqual(self.b.s.state['seGameplayFixtures']['dagger']['status'], 'pickup-intent')
        self.assertEqual(len(self.taps()), 1)
    def test_pickup_malformed_native_absence_is_unavailable_without_repeated_input(self):
        invalid = [{}, {'count': False, 'refs': []}, {'count': 0, 'refs': [{}]},
                   {'count': 1, 'refs': []}, {'count': 2, 'refs': []},
                   {'count': 1, 'refs': [{'formId': '0xFF000099', 'base': {'formId': BASE}}]}]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.b = Backend(); created = self.create_item(); ref = created['fixture']['reference']
                original = self.b.call
                def intercepted(tool, args):
                    if tool == 'inspect' and args.get('kind') == 'refs' and args.get('formId') == ref and not self.b.world[ref]['loaded']:
                        return copy.deepcopy(payload)
                    return original(tool, args)
                self.b.call = intercepted
                with self.assertRaises(ValueError): self.perform('pickup', referenceTag='dagger')
                self.assertEqual(len(self.taps()), 1)
                self.assertEqual(self.b.s.state['seGameplayFixtures']['dagger']['status'], 'pickup-intent')
    def test_pickup_reference_transport_failure_never_becomes_absence(self):
        self.create_item(); original = self.b.call
        def intercepted(tool, args):
            if tool == 'inspect' and args.get('kind') == 'refs' and args['formId'] in self.b.world and not self.b.world[args['formId']]['loaded']:
                raise OSError('native lookup transport unavailable')
            return original(tool, args)
        self.b.call = intercepted
        with self.assertRaisesRegex(OSError, 'transport unavailable'): self.perform('pickup', referenceTag='dagger')
        self.assertEqual(len(self.taps()), 1)
    def test_pickup_wrong_quantity_cannot_pass_on_reference_disappearance_or_replay(self):
        self.create_item(); self.b.pickup_removes_reference = True; self.b.pickup_delta = 2
        with self.assertRaisesRegex(ValueError, 'delta1'): self.perform('pickup', referenceTag='dagger')
        with self.assertRaisesRegex(ValueError, 'same-run/world'): self.perform('pickup', referenceTag='dagger')
        self.assertEqual(len(self.taps()), 1)
    def test_stale_world_and_foreign_process_fixture_rejected_before_input(self):
        self.create_item(); self.b.s.state['ownedWorldGeneration'] = 2
        with self.assertRaisesRegex(ValueError, 'same-run/world'): self.perform('pickup', referenceTag='dagger')
        self.assertEqual(self.taps(), [])
        self.b.s.state['ownedWorldGeneration'] = 1; self.b.s.state['game']['birth'] += 1
        with self.assertRaisesRegex(ValueError, 'same-run/world'): self.perform('pickup', referenceTag='dagger')
    def test_pending_release_or_different_generation_cannot_pass_on_actual_effect(self):
        for name in ('release_pending', 'corrupt_receipt'):
            with self.subTest(name=name):
                self.b = Backend(); setattr(self.b, name, True)
                with self.assertRaisesRegex(ValueError, 'completion/release'): self.perform('move', direction='forward', durationSeconds=.2)
                self.assertEqual(len(self.taps()), 1)
    def test_native_readiness_or_foreign_hold_refuses_input(self):
        self.b.native_ready = False
        with self.assertRaisesRegex(ValueError, 'input contract'): self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(self.taps(), [])
        self.b.native_ready = True; self.b.held = [{'owner': 'someone-else', 'scancode': 17}]
        with self.assertRaisesRegex(ValueError, 'held synthetic'): self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(self.taps(), [])
    def test_attack_requires_damage_and_cannot_repeat_after_no_damage(self):
        self.create_actor(); self.b.drawn = True; self.b.health_damage = 0
        with self.assertRaises(TimeoutError): self.perform('attack', actorTag='target', durationSeconds=.05)
        self.b.budget = 4
        with self.assertRaisesRegex(ValueError, 'never replayed'): self.perform('attack', actorTag='target', durationSeconds=.05)
        self.assertEqual(len(self.taps()), 1)
    def test_snapshot_after_load_uses_new_static_resolution_without_old_tag(self):
        self.create_item(); self.perform('pickup', referenceTag='dagger')
        self.perform('equip', referenceTag='dagger', mechanism='papyrus-native')
        self.b.s.state['ownedWorldGeneration'] = 2
        snapshot = domain.observe(self.b, {'domain': domain.DOMAIN, 'observation': 'snapshot', 'item': ITEM})
        self.assertEqual(snapshot['item'], {'runtimeId': BASE, 'quantityItems': 1, 'equipped': True})
        self.assertEqual(snapshot['equipment']['right'], BASE)
        self.assertEqual(snapshot['player']['currentHealthPoints'], 100.)
    def test_equip_ack_without_actual_worn_state_is_not_success(self):
        self.create_item(); self.perform('pickup', referenceTag='dagger'); self.b.effect = False
        with self.assertRaises(TimeoutError): self.perform('equip', referenceTag='dagger', mechanism='papyrus-native')
        self.assertEqual(len([a for t, a in self.b.calls if t == 'papyrus' and a.get('function') == 'EquipItem']), 1)
    def test_vr_and_non_owned_process_refused(self):
        self.b.s.state['configuration']['game_edition'] = 'vr'
        with self.assertRaisesRegex(ValueError, 'edition'): self.perform('move', direction='forward', durationSeconds=.2)
        self.b.s.state['configuration']['game_edition'] = 'se'
        with patch('skyrim_autotest.fixture_actors.native.alive', return_value=False):
            with self.assertRaisesRegex(ValueError, 'owned disposable'): self.perform('move', direction='forward', durationSeconds=.2)
        self.assertEqual(self.taps(), [])


class ValidationTests(unittest.TestCase):
    def test_unknown_domains_are_not_claimed(self):
        self.assertFalse(domain.validate('input.perform', {'action': 'move'}))
    def test_extra_fields_nonfinite_booleans_wrong_operation_and_ui_claim_refused(self):
        for operation, req in [
            ('input.perform', request('move', direction='forward', durationSeconds=True)),
            ('input.perform', request('move', direction='forward', durationSeconds=float('nan'))),
            ('input.perform', request('move', direction='forward', durationSeconds=.2, key='grave')),
            ('object.perform', request('inventory-open')),
            ('input.perform', request('equip', referenceTag='dagger', mechanism='menu')),
            ('input.perform', request('attack', actorTag='target', durationSeconds=1)),
            ('object.perform', request('create-pickup-fixture', referenceTag='dagger', item=dict(ITEM, type='ALCH'), distanceGameUnits=75)),
            ('world.read', {'domain': domain.DOMAIN, 'observation': 'snapshot', 'reference': '0x14'}),
        ]:
            with self.subTest(request=req), self.assertRaises(ValueError): domain.validate(operation, req)


if __name__ == '__main__': unittest.main()
