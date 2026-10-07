"""Bounded semantic operations over the existing owned game/tool providers.

No subject-name routing. Normalized fields come from observed game state, never
requested target values. Offline validation is not platform qualification.
"""
import copy
import math
import re
import time

READS = {'state.read', 'player.read', 'world.read', 'menu.read'}
ACTIONS = {
    'controller.perform': {'pose_and_grip', 'reach_and_grip_reference', 'release_reference', 'release_all'},
    'object.perform': {'create_fixture_reference', 'place_fixture_reference_in_hand',
                       'set_fixture_inventory_quantity', 'set_fixture_health'},
}
OBSERVATIONS = {'form.identity', 'body_slot.settings', 'body_slot.display',
                'hand.held_item', 'inventory.quantity', 'inventory.alchemy',
                'reference.state', 'reference.physics', 'form.alchemy'}


def menus_block_gameplay(observation):
    """Require actual native flags; never infer blocking from a mod menu name."""
    if observation.get('messageBoxOpen') is not False:
        return True
    names, states = observation.get('openMenus'), observation.get('menuStates')
    if not isinstance(names, list) or not isinstance(states, list):
        return True
    if len(states) != len(names) or {row.get('name') for row in states} != set(names):
        return True
    for row in states:
        fields = ('alwaysOpen', 'pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause')
        if row.get('available') is not True or any(type(row.get(key)) is not bool for key in fields):
            return True
        if (row.get('name') == 'Console' or row['pausesGame'] or row['modal'] or row['freezeFramePause']
                or (not row['alwaysOpen'] and (row['usesCursor'] or row['usesMenuContext']))):
            return True
    return False


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('Semantic numeric value outside bounded domain')
    return value


def vector(value):
    if not isinstance(value, dict) or set(value) != {'units', 'xyz'} or value['units'] != 'metres':
        raise ValueError('Tracking position requires explicit metres')
    if not isinstance(value['xyz'], list) or len(value['xyz']) != 3:
        raise ValueError('Tracking position needs three values')
    return [number(v, -5, 5) for v in value['xyz']]


def validate(args):
    operation = args.get('operation')
    if set(args) - {'operation', 'request'} or operation not in READS | ACTIONS.keys():
        raise ValueError('Unsupported platform operation')
    req = args.get('request', {})
    if not isinstance(req, dict):
        raise ValueError('Semantic request must be an object')
    if operation in ('state.read', 'player.read') and req:
        raise ValueError('State/player read takes no request')
    if operation == 'world.read' and req.get('observation') not in OBSERVATIONS:
        raise ValueError('Unsupported world observation')
    if operation in ACTIONS and req.get('action') not in ACTIONS[operation]:
        raise ValueError('Unsupported semantic action')
    selectors = {
        'form.identity': ({'observation', 'form'}, set()),
        'form.alchemy': ({'observation', 'form'}, set()),
        'body_slot.settings': ({'observation', 'slot'}, set()),
        'body_slot.display': ({'observation', 'slot'}, set()),
        'hand.held_item': ({'observation', 'hand', 'continuityWindowSeconds'}, {'referenceTag'}),
        'inventory.quantity': ({'observation', 'owner', 'item', 'units'}, set()),
        'inventory.alchemy': ({'observation', 'owner'}, set()),
        'reference.state': ({'observation', 'referenceTag'}, set()),
        'reference.physics': ({'observation', 'referenceTag'}, set()),
        'pose_and_grip': ({'action', 'hand', 'grip', 'durationSeconds', 'trackingPosition',
                           'trackingOrientation', 'otherHandPosition', 'referenceHeadPosition'}, set()),
        'reach_and_grip_reference': ({'action', 'hand', 'grip', 'holdSeconds', 'maximumReachMetres', 'referenceTag'}, set()),
        'release_reference': ({'action', 'hand', 'referenceTag', 'settleSeconds', 'zone'}, set()),
        'release_all': ({'action'}, {'settleSeconds'}),
        'create_fixture_reference': ({'action', 'item', 'quantityItems', 'referenceTag', 'placement'}, set()),
        'place_fixture_reference_in_hand': ({'action', 'hand', 'referenceTag', 'keepGripClosed', 'settleSeconds'}, set()),
        'set_fixture_inventory_quantity': ({'action', 'item', 'owner', 'quantityItems'}, set()),
        'set_fixture_health': ({'action', 'actor', 'baseHealthPoints', 'damageHealthPoints', 'restoreBeforeDamage'}, set()),
    }
    selector = req.get('action', req.get('observation'))
    if selector:
        required, optional = selectors[selector]
        if not required <= set(req) or set(req) - required - optional:
            raise ValueError('Semantic request contains unsupported/missing fields')
    if 'owner' in req and req['owner'] != 'player': raise ValueError('Only player inventory supported')
    if operation == 'menu.read' and req: raise ValueError('Only unfiltered menu read supported')
    if req.get('action') == 'create_fixture_reference' and req.get('placement') != 'settled reachable surface away from slot 13 and mouth':
        raise ValueError('Unsupported fixture placement specification')
    if req.get('action') == 'place_fixture_reference_in_hand' and req.get('keepGripClosed') is not True:
        raise ValueError('Fixture hand seed requires explicit closed grip')
    if req.get('action') == 'release_reference' and req.get('zone') != 'outside body slot 13 and mouth':
        raise ValueError('Unsupported release zone')
    if req.get('action') == 'set_fixture_health' and (req.get('actor') != 'player' or req.get('restoreBeforeDamage') is not True):
        raise ValueError('Unsupported health fixture target/policy')
    if 'hand' in req and req['hand'] not in ('left', 'right'):
        raise ValueError('Explicit left/right hand required')
    if 'grip' in req and req['grip'] not in ('closed', 'open'):
        raise ValueError('Explicit open/closed grip required')
    if 'referenceTag' in req and not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', req['referenceTag']):
        raise ValueError('Invalid reference tag')
    if 'slot' in req and (type(req['slot']) is not int or not 0 <= req['slot'] <= 31):
        raise ValueError('Unsupported body slot')
    for key in ('item', 'form'):
        if key in req:
            form = req[key]
            if not isinstance(form, dict) or not re.fullmatch(r'[A-Za-z0-9 _.-]+\.(esm|esp)', form.get('plugin', ''), re.I) or not re.fullmatch(r'[0-9a-fA-F]{1,6}', form.get('localId', '')):
                raise ValueError('Form requires plugin and local hex ID')
    if 'quantityItems' in req and (type(req['quantityItems']) is not int or not 0 <= req['quantityItems'] <= 1000):
        raise ValueError('Bounded item quantity required')
    for key in ('durationSeconds', 'holdSeconds', 'settleSeconds', 'continuityWindowSeconds'):
        if key in req: number(req[key], 0, 10)
    if 'maximumReachMetres' in req: number(req['maximumReachMetres'], .01, 1)
    if req.get('action') == 'pose_and_grip':
        for key in ('trackingPosition', 'otherHandPosition', 'referenceHeadPosition'): vector(req[key])
        q = req.get('trackingOrientation', {}).get('quaternionXYZW')
        if not isinstance(q, list) or len(q) != 4 or abs(sum(number(v, -1, 1)**2 for v in q) - 1) > .001:
            raise ValueError('Normalized tracking quaternion required')
    if req.get('action') == 'set_fixture_health':
        number(req['baseHealthPoints'], 1, 10000)
        number(req['damageHealthPoints'], 0, req['baseHealthPoints'] - 1)


class Backend:
    def __init__(self, session, deadline):
        self.s = session
        self.end = deadline

    def remaining(self):
        remaining = self.end - time.monotonic()
        if remaining <= 0: raise TimeoutError('Semantic operation deadline exhausted')
        return remaining

    def call(self, tool, args):
        return self.s.tool(tool, args, timeout=min(12, self.remaining()), deadline=self.end)

    def pap(self, script, function, values=None, target=None, *, fill_neutral=False):
        args = {'action': 'call', 'script': script, 'function': function, 'args': values or [],
                'timeoutMs': max(1, min(6000, int(self.remaining()*1000)))}
        if target: args['self'] = {'form': target}
        if fill_neutral: args['fillNeutral'] = True
        response = self.call('papyrus', args)
        if 'returned' not in response: raise ValueError('Papyrus return value unavailable')
        return response['returned']

    def pause(self, seconds):
        if seconds >= self.remaining(): raise TimeoutError('Insufficient operation time for settling')
        time.sleep(seconds)

    def resolve(self, spec):
        observed = self.pap('Game', 'GetFormFromFile', [int(spec['localId'], 16), spec['plugin']])
        if not isinstance(observed, dict) or not observed.get('formId'):
            raise ValueError('Required form not resolved from installed plugin')
        if spec.get('type'):
            rows = self.call('inspect', {'kind': 'refs', 'formId': observed['formId']})['refs']
            if len(rows) != 1 or rows[0].get('formType') != spec['type']:
                raise ValueError('Resolved form has unexpected type')
        return observed['formId']

    def item(self, reference):
        base = self.pap('ObjectReference', 'GetBaseObject', target=reference)
        if not isinstance(base, dict) or not base.get('formId'):
            raise ValueError('Reference base identity unavailable')
        fid = int(base['formId'], 16)
        if fid >> 24 >= 0xFE: raise ValueError('Dynamic/light base identity not supported by this qualified adapter')
        plugin = self.pap('Game', 'GetModName', [fid >> 24])
        if not isinstance(plugin, str) or not plugin: raise ValueError('Base plugin identity unavailable')
        return {'plugin': plugin, 'localId': f'{fid & 0xFFFFFF:06X}', 'runtimeId': base['formId']}

    def tagged(self, req):
        self.s.validate_probe_reference(timeout=min(3, self.remaining()))
        entry = self.s.state.get('platformReferences', {}).get(req['referenceTag'])
        if not entry or not entry.get('id'):
            raise ValueError('Reference tag is unavailable in this world generation')
        return entry['id']

    def frame(self):
        from .hardware import neutral
        return copy.deepcopy(self.s.state.get('hardwareFrame') or neutral())

    def publish(self, frame, duration):
        return self.call('driver', {'action': 'publish', 'frame': frame,
                                   'holdSeconds': 30})

    def xyz(self, target):
        return [self.pap('ObjectReference', 'GetPosition' + a, target=target) for a in 'XYZ']

    def hand_xyz(self, hand):
        node = 'NPC L Hand [LHnd]' if hand == 'left' else 'NPC R Hand [RHnd]'
        return [self.pap('NetImmerse', 'GetNodeWorldPosition' + a, [{'form': '0x14'}, node, True]) for a in 'XYZ']

    def held(self, req):
        if 'probeObject' in self.s.state:
            self.s.validate_probe_reference(timeout=min(3, self.remaining()))
        window = req.get('continuityWindowSeconds', 0)
        first = None
        samples = []
        finish = None
        while True:
            current = self.pap('HiggsVR', 'GetGrabbedObject', [req['hand'] == 'left'])
            if current is not None and (not isinstance(current, dict) or not current.get('formId')):
                raise ValueError('Held-reference identity is unavailable, not an empty hand')
            if 'probeObject' in self.s.state:
                self.s.validate_probe_reference(timeout=min(3, self.remaining()))
            fid = current.get('formId') if isinstance(current, dict) else None
            samples.append({'monotonicSeconds': time.monotonic(), 'referenceId': fid})
            if len(samples) == 1:
                first = fid
                finish = samples[0]['monotonicSeconds'] + window
            if fid != first: raise AssertionError('Held reference changed within requested continuity window')
            if time.monotonic() >= finish: break
            self.pause(min(.1, max(0, finish - time.monotonic())))
        value = {'occupied': first is not None, 'reference': {'id': first},
                 'samples': samples, 'sampledContinuitySeconds': samples[-1]['monotonicSeconds']-samples[0]['monotonicSeconds'],
                 'continuityBasis': 'bounded sampled HIGGS references; intervals unobserved'}
        gaps = [b['monotonicSeconds']-a['monotonicSeconds'] for a,b in zip(samples, samples[1:])]
        value['continuousHold'] = {'seconds': value['sampledContinuitySeconds'] if first else 0,
                                   'basis': 'same exact reference at every bounded sample; not an atomic event stream',
                                   'maximumSampleGapSeconds': max(gaps, default=0),
                                   'unobservedIntervals': True}
        if window and max(gaps, default=0) > .5:
            raise ValueError('Held-reference sampler gap exceeds qualified maximum .5 seconds')
        if first:
            value['item'] = self.item(first)
            raw = self.call('inspect', {'kind': 'refs', 'formId': first})
            rows = [row for row in raw.get('refs', [])
                    if int(row.get('formId', '0'), 16) == int(first, 16)]
            if len(rows) != 1 or type(rows[0].get('quantityItems')) is not int or rows[0]['quantityItems'] < 1:
                raise ValueError('Actual held-reference quantity unavailable')
            value['quantity'] = {'items': rows[0]['quantityItems']}
            value['quantityBasis'] = 'native reference count after held sampling; sequential non-atomic read'
            value['quantityProviderObservation'] = raw
        if 'referenceTag' in req: value['matchesRequestedReference'] = first == self.tagged(req)
        return {'hand': value}

    def alchemy(self, spec):
        # The ALCH check is mandatory even if the caller omitted form.type:
        # native null/wrong-self defaults must not masquerade as observations.
        form = self.resolve(dict(spec, type='ALCH'))
        flags = {}
        for key, function in (('poison', 'IsPoison'), ('hostile', 'IsHostile'), ('food', 'IsFood')):
            value = self.pap('Potion', function, target=form)
            if type(value) is not bool:
                raise ValueError('Actual alchemy flag unavailable: ' + key)
            flags[key] = value
        count = self.pap('Potion', 'GetNumEffects', target=form)
        if type(count) is not int or not 0 <= count <= 32:
            raise ValueError('Alchemy effect count unavailable or exceeds bound32')
        effects = []
        for index in range(count):
            effect = self.pap('Potion', 'GetNthEffectMagicEffect', [index], form)
            if not isinstance(effect, dict) or not effect.get('formId'):
                raise ValueError('Actual magic effect identity unavailable')
            eid = effect['formId']
            rows = self.call('inspect', {'kind': 'refs', 'formId': eid}).get('refs', [])
            if len(rows) != 1 or rows[0].get('formType') != 'MGEF':
                raise ValueError('Actual magic effect type unavailable')
            harmful = self.pap('MagicEffect', 'IsEffectFlagSet', [4], eid)
            hostile = self.pap('MagicEffect', 'IsEffectFlagSet', [1], eid)
            if type(harmful) is not bool or type(hostile) is not bool:
                raise ValueError('Actual magic effect flags unavailable')
            magnitude = self.pap('Potion', 'GetNthEffectMagnitude', [index], form)
            area = self.pap('Potion', 'GetNthEffectArea', [index], form)
            duration = self.pap('Potion', 'GetNthEffectDuration', [index], form)
            number(magnitude, -1e12, 1e12)
            if any(type(v) is not int or not 0 <= v <= 0xFFFFFFFF for v in (area, duration)):
                raise ValueError('Actual magic effect area/duration unavailable')
            effects.append({'index': index, 'runtimeId': eid, 'detrimental': harmful,
                            'hostile': hostile, 'magnitude': magnitude,
                            'area': area, 'durationSeconds': duration})
        return {'alchemy': {'runtimeId': form, **flags, 'effectCount': count,
                            'effects': effects, 'hasDetrimentalEffect': any(e['detrimental'] for e in effects),
                            'basis': 'native Potion and MagicEffect queries; sequential non-atomic snapshot'}}

    def observe(self, req):
        kind = req['observation']
        if kind == 'hand.held_item': return self.held(req)
        if kind == 'form.alchemy': return self.alchemy(req['form'])
        if kind == 'form.identity': return {'form': {'runtimeId': self.resolve(req['form'])}}
        if kind == 'inventory.alchemy':
            raw = self.call('inspect', {'kind': 'inventory', 'formType': 'ALCH', 'limit': 100})
            return {'inventory': {'entries': raw['items']}, 'providerObservation': raw}
        if kind == 'inventory.quantity':
            if req.get('owner') != 'player' or req.get('units') != 'items': raise ValueError('Unsupported inventory owner/units')
            count = self.pap('ObjectReference', 'GetItemCount', [{'form': self.resolve(req['item'])}], '0x14')
            if type(count) is not int or count < 0: raise ValueError('Inventory count unavailable')
            return {'inventory': {'quantity': {'items': count}}}
        if kind == 'body_slot.display':
            shown = self.pap('VRIK', 'VrikGetSlotDisplayed', [req['slot']])
            if type(shown) is not bool: raise ValueError('Slot display state unavailable')
            return {'body_slot': {'displayed': shown}}
        if kind == 'body_slot.settings':
            slot = req['slot']
            allow = self.pap('VRIK', 'VrikGetSlot', ['allowSmallSlot' + str(slot)])
            coords = {axis.lower(): {'gameUnits': self.pap('VRIK', 'VrikGetSlot', ['pos' + axis + str(slot)])} for axis in 'XYZ'}
            if allow not in (0, 1) or type(allow) not in (int, float):
                raise ValueError('Slot boolean value is not exactly zero or one')
            for coordinate in coords.values(): number(coordinate['gameUnits'], -100000, 100000)
            return {'body_slot': {'allowSmall': bool(allow), 'position': coords}}
        ref = self.tagged(req)
        if kind == 'reference.physics':
            raw = self.call('inspect', {'kind': 'world_observer', 'physics': {'refs': [ref]}})
            return {'reference': {'id': ref, 'physics': raw}}
        raw = self.call('inspect', {'kind': 'refs', 'formId': ref})
        rows = raw.get('refs', [])
        entry = next((r for r in rows if int(r.get('formId', '0'), 16) == int(ref, 16)), None)
        if entry is None or type(entry.get('quantityItems')) is not int:
            raise ValueError('Exact native reference/stack-count observation unavailable')
        loaded = self.pap('ObjectReference', 'Is3DLoaded', target=ref)
        return {'reference': {'id': ref, 'existsInLoadedWorld': loaded is True,
                              'quantity': {'items': entry['quantityItems']}, 'item': self.item(ref)},
                'providerObservation': raw}

    def controller(self, req):
        action = req['action']
        if action == 'release_all':
            observed = self.call('driver', {'action': 'release'})
            self.pause(req.get('settleSeconds', 0))
            return observed
        from .vr_probe import ensure_owned_focus
        self.remaining()
        ensure_owned_focus(self.s, {}, 'platform-controller-owned-focus', deadline=self.end)
        frame = self.frame()
        hand = req['hand']
        other = 'right' if hand == 'left' else 'left'
        if action == 'pose_and_grip':
            xyz = vector(req['trackingPosition'])
            qx, qy, qz, qw = req['trackingOrientation']['quaternionXYZW']
            frame[hand]['matrix'] = [1-2*(qy*qy+qz*qz), 2*(qx*qy-qz*qw), 2*(qx*qz+qy*qw), xyz[0],
                                     2*(qx*qy+qz*qw), 1-2*(qx*qx+qz*qz), 2*(qy*qz-qx*qw), xyz[1],
                                     2*(qx*qz-qy*qw), 2*(qy*qz+qx*qw), 1-2*(qx*qx+qy*qy), xyz[2]]
            for role, point in [('hmd', vector(req['referenceHeadPosition'])), (other, vector(req['otherHandPosition']))]:
                frame[role]['matrix'] = [1,0,0,point[0],0,1,0,point[1],0,0,1,point[2]]
            frame[other]['controller'].update(pressed=0, touched=0, axes=[[0,0] for _ in range(5)])
        if action == 'reach_and_grip_reference':
            ref = self.tagged(req)
            frame[hand]['controller'].update(pressed=0, touched=0, axes=[[0,0] for _ in range(5)])
            self.publish(frame, 10)
            self.pause(.5)
            baseline = self.hand_xyz(hand)
            columns = []
            # Measure the local tracking-to-skeleton Jacobian through physical poses.
            for index in (3,7,11):
                probe = copy.deepcopy(frame)
                probe[hand]['matrix'][index] += .05
                self.publish(probe, 10)
                self.pause(.25)
                measured = self.hand_xyz(hand)
                columns.append([(measured[i]-baseline[i])/.05 for i in range(3)])
                self.publish(frame, 10)
                self.pause(.15)
            target = self.xyz(ref)
            reference_position = list(target)
            heading = math.radians(self.pap('ObjectReference', 'GetAngleZ', target='0x14'))
            # The old 21-unit landmark was observed with long firewood. It can
            # leave a small bottle outside the near cast. The 7/7 candidate
            # pushed the bottle before grip in run20261007-105504-b826e7:
            # it moved once the hand node came within about15 game units.
            # Keep a12-behind/10-above stand-off candidate (15.6units),
            # retaining the exact-reference physical-grip assertion.
            # This is not a measured palm/collision transform or selection ACK.
            target[0] -= math.sin(heading)*12
            target[1] -= math.cos(heading)*12
            target[2] += 10
            from .platform_math import solve3
            start_tracking = [frame[hand]['matrix'][index] for index in (3,7,11)]
            self.s.log('platform-reach-geometry', reference=ref, referencePositionGameUnits=reference_position,
                       targetPalmGameUnits=target, trackingStartMetres=start_tracking,
                       measuredGameUnitsPerMetre=columns, maximumReachMetres=req['maximumReachMetres'],
                       approachBasis='close hand landmark candidate; palm/selection unobserved')
            for _ in range(80):
                # Track the actual dynamic target, rather than pressing at a
                # stale point after a teleported hand has displaced it.
                target = self.xyz(ref)
                target[0] -= math.sin(heading)*12
                target[1] -= math.cos(heading)*12
                target[2] += 10
                current = self.hand_xyz(hand)
                if math.dist(current, target) < 2: break
                delta = solve3(columns, [target[i]-current[i] for i in range(3)])
                total = [frame[hand]['matrix'][index] + change - origin
                         for index, change, origin in zip((3,7,11), delta, start_tracking)]
                if math.sqrt(sum(v*v for v in total)) > req['maximumReachMetres']:
                    raise ValueError('Physical reach exceeds declared maximum')
                distance = math.sqrt(sum(v*v for v in delta))
                fraction = min(1., .01/distance)
                delta = [v*fraction for v in delta]
                self.s.log('platform-reach-position', handPositionGameUnits=current,
                           targetHandGameUnits=target, totalTrackingDisplacementMetres=total,
                           trackingIncrementMetres=delta)
                for index, change in zip((3,7,11), delta): frame[hand]['matrix'][index] += change
                self.publish(frame, 10)
                self.pause(.1)
            else: raise AssertionError('Controller could not reach exact fixture reference')
        if action == 'release_reference': self.tagged(req)
        grip = req.get('grip', 'open') if action != 'release_reference' else 'open'
        if action == 'reach_and_grip_reference':
            # Pose delivery can work while game input is suspended. Recheck the
            # owned foreground and neutral interval before the single rising edge.
            ensure_owned_focus(self.s, {}, 'platform-grip-owned-focus', deadline=self.end)
            self.publish(frame, .5)
            self.pause(.5)
            menus = self.call('menu', {'action': 'list', 'includeFlags': True})
            can_grab = self.pap('HiggsVR', 'CanGrabObject', [hand == 'left'])
            hand_position, reference_position = self.hand_xyz(hand), self.xyz(ref)
            current_target = [reference_position[0]-math.sin(heading)*12,
                              reference_position[1]-math.cos(heading)*12,
                              reference_position[2]+10]
            self.s.log('platform-grip-readiness', menus=menus, canGrab=can_grab,
                       handPositionGameUnits=hand_position,
                       referencePositionGameUnits=reference_position,
                       currentTargetHandGameUnits=current_target)
            if menus_block_gameplay(menus):
                raise AssertionError('Gameplay input blocked by an open menu')
            if can_grab is not True:
                raise AssertionError('HIGGS hand is not ready for physical acquisition')
            if math.dist(hand_position, current_target) >= 3:
                raise AssertionError('Fixture reference moved away before physical grip')
        frame[hand]['controller'].update(pressed=4 if grip == 'closed' else 0,
                                         touched=4 if grip == 'closed' else 0,
                                         axes=[[0,0] for _ in range(5)])
        if action == 'pose_and_grip':
            from .platform_math import pose_frames
            start = self.frame()
            frames = list(pose_frames(start, frame))
            if len(frames)*.05 + req.get('durationSeconds', 1) >= self.remaining():
                raise TimeoutError('Insufficient operation time for bounded pose motion')
            self.s.log('platform-smooth-pose', frames=len(frames), maximumStepMetres=.01,
                       gripPolicy='preserve previous buttons during motion; requested grip at endpoint')
            for intermediate in frames:
                self.publish(intermediate, 10)
                self.pause(.05)
        duration = req.get('durationSeconds', req.get('holdSeconds', req.get('settleSeconds', 1)))
        response = self.publish(frame, duration)
        self.pause(duration)
        if action == 'reach_and_grip_reference':
            held = self.pap('HiggsVR', 'GetGrabbedObject', [hand == 'left'])
            self.s.log('platform-physical-grip-observation', requestedReference=ref, held=held,
                       acceptedAsSubjectResult=False)
            if not isinstance(held, dict) or held.get('formId') != ref:
                # ReadController may dispatch callbacks: diagnose only after the
                # requested grip interval, never before its tested rising edge.
                self.s.log('platform-failed-grip-input',
                           observation=self.call('input', {'device': 'vrTrackedSet', 'action': 'observe'}),
                           acceptedAsAcquisitionProof=False)
        return {'inputIssued': True, 'observedGameplaySuccess': None, 'publication': response}

    def mutate(self, req):
        action = req['action']
        if action == 'set_fixture_inventory_quantity':
            base = self.resolve(req['item'])
            before = self.pap('ObjectReference', 'GetItemCount', [{'form': base}], '0x14')
            if type(before) is not int or before < 0: raise ValueError('Fixture inventory unavailable')
            delta = req['quantityItems'] - before
            if delta > 0: self.pap('ObjectReference', 'AddItem', [{'form': base}, delta, True], '0x14')
            # DevBench accepts no JSON-null argument. Omit only the trailing
            # akOtherContainer, whose reviewed ObjectReference.psc default is
            # None, and explicitly permit its neutral VM default.
            if delta < 0: self.pap('ObjectReference', 'RemoveItem', [{'form': base}, -delta, True], '0x14', fill_neutral=True)
            after = self.pap('ObjectReference', 'GetItemCount', [{'form': base}], '0x14')
            if after != req['quantityItems']: raise AssertionError('Fixture inventory quantity did not settle')
            return {'inventory': {'quantity': {'items': after}}, 'beforeItems': before}
        if action == 'set_fixture_health':
            self.pap('Actor', 'SetActorValue', ['Health', float(req['baseHealthPoints'])], '0x14')
            self.pap('Actor', 'RestoreActorValue', ['Health', 10000.], '0x14')
            self.pap('Actor', 'DamageActorValue', ['Health', float(req['damageHealthPoints'])], '0x14')
            return {'player': {'health': {'points': self.pap('Actor', 'GetActorValue', ['Health'], '0x14')}}}
        if action == 'place_fixture_reference_in_hand':
            ref = self.tagged(req)
            frame = self.frame()
            frame[req['hand']]['controller'].update(pressed=4, touched=4)
            self.publish(frame, req.get('settleSeconds', 1.2))
            self.pap('HiggsVR', 'GrabObject', [{'form': ref}, req['hand'] == 'left'])
            self.pause(req.get('settleSeconds', 1.2))
            return self.held({'hand': req['hand'], 'referenceTag': req['referenceTag']})
        references = self.s.state.get('platformReferences', {})
        if req['referenceTag'] in references:
            raise ValueError('Fixture reference tag already exists; mutation refused')
        if len(references) >= 16:
            raise ValueError('Fixture reference limit16 reached')
        if references:
            self.s.validate_probe_reference(timeout=min(3, self.remaining()))
        if req['quantityItems'] not in (1, 5): raise ValueError('Only fixture reference quantities1or5 are supported')
        base = self.resolve(req['item'])
        cursor = self.s.capture_probe_cursor() if not references else None
        if req['quantityItems'] == 1:
            observed = self.pap('ObjectReference', 'PlaceAtMe', [{'form': base}, 1, True, True], '0x14')
        else:
            # Owned disposable fixture only. DropObject returns one actual ref;
            # its native quantity, never its requested count, gates acceptance.
            before = self.pap('ObjectReference', 'GetItemCount', [{'form': base}], '0x14')
            if type(before) is not int or before < 0:
                raise ValueError('Fixture pre-drop inventory quantity unavailable')
            self.pap('ObjectReference', 'AddItem', [{'form': base}, 5, True], '0x14')
            after_add = self.pap('ObjectReference', 'GetItemCount', [{'form': base}], '0x14')
            if type(after_add) is not int or after_add != before + 5:
                raise ValueError('Fixture stack inventory staging did not produce exact delta5')
            observed = self.pap('ObjectReference', 'DropObject', [{'form': base}, 5], '0x14')
            after_drop = self.pap('ObjectReference', 'GetItemCount', [{'form': base}], '0x14')
            if type(after_drop) is not int or after_drop != before:
                raise ValueError('Fixture stack drop did not restore exact inventory baseline')
        if not isinstance(observed, dict) or not observed.get('formId'): raise ValueError('Fixture spawn identity missing')
        ref = observed['formId']
        if any(int(entry['id'], 16) == int(ref, 16) for entry in references.values()):
            raise ValueError('Fixture reference ID reused; incarnation cannot be established')
        if not references:
            self.s.bind_probe_reference(ref, cursor)
        else:
            # Keep the original world cursor, including creation-time events.
            # probeObject is a legacy lifecycle anchor, never an existence check.
            self.s.validate_probe_reference(timeout=min(3, self.remaining()))
        self.s.state.setdefault('platformReferences', {})[req['referenceTag']] = {'id': ref}
        self.s.save()
        if req['quantityItems'] == 5:
            raw = self.call('inspect', {'kind': 'refs', 'formId': ref})
            rows = [row for row in raw.get('refs', [])
                    if int(row.get('formId', '0'), 16) == int(ref, 16)]
            if len(rows) != 1 or type(rows[0].get('quantityItems')) is not int or rows[0]['quantityItems'] != 5:
                raise ValueError('Actual single-reference stack quantity is not5')
        heading = math.radians(self.pap('ObjectReference', 'GetAngleZ', target='0x14'))
        self.pap('ObjectReference', 'MoveTo', [{'form': '0x14'}, math.sin(heading)*42, math.cos(heading)*42, 20., False], ref)
        self.pap('ObjectReference', 'Enable', [False], ref)
        last, stable = None, None
        while True:
            if self.pap('ObjectReference', 'Is3DLoaded', target=ref) is True:
                mass = self.pap('ObjectReference', 'GetMass', target=ref)
                point = self.xyz(ref)
                if type(mass) in (int, float) and mass > 0 and last and math.dist(last, point) < .2:
                    stable = stable or time.monotonic()
                    if time.monotonic()-stable >= .5: break
                else: stable = None
                last = point
            self.pause(.1)
        self.s.validate_probe_reference(timeout=min(3, self.remaining()))
        return {'reference': {'id': ref, 'settledPositionGameUnits': last}}


def initialize_controllers(session, configuration):
    """Explicit platform initial pose, before subject steps and bounded reaches."""
    positions = configuration.get('controller_start_positions_metres')
    if positions is None: return
    if not session.state.get('gameplayBootstrap', {}).get('completed'):
        raise ValueError('Controller platform fixture must follow common gameplay readiness')
    if session.state.get('inputBackend') != 'driver' or session.state.get('driverBackend') != 'file':
        raise ValueError('Initial controller pose requires the owned file-driver backend')
    from .hardware import neutral
    frame = copy.deepcopy(session.state.get('hardwareFrame') or neutral())
    for hand in ('left', 'right'):
        for index, value in zip((3,7,11), positions[hand]): frame[hand]['matrix'][index] = value
        frame[hand]['controller'].update(pressed=0, touched=0, axes=[[0,0] for _ in range(5)])
    session.phase('platform-controller-initialization', 15)
    from .vr_probe import ensure_owned_focus
    ensure_owned_focus(session, {}, 'platform-initialization-owned-focus')
    backend = Backend(session, time.monotonic()+15)
    # Common executor setup, before any subject operation. Loading a save can
    # leave controls disabled even with a loaded player and HUD-only menus.
    backend.pap('Game', 'EnablePlayerControls', [True]*8+[0])
    controls = {name: backend.pap('Game', name) for name in (
        'IsMovementControlsEnabled', 'IsFightingControlsEnabled',
        'IsLookingControlsEnabled', 'IsActivateControlsEnabled')}
    session.log('platform-gameplay-controls', observed=controls, subjectAction=False)
    if any(value is not True for value in controls.values()):
        raise AssertionError('Gameplay controls remain disabled after common platform initialization')
    publication = session.tool('driver', {'action': 'publish', 'frame': frame, 'holdSeconds': 30})
    session.log('platform-controller-start-pose', positionsMetres=positions,
                publication=publication, subjectAction=False, consumedByGameNotProven=True)


def execute(session, args, deadline):
    validate(args)
    if not session.state.get('gameplayBootstrap', {}).get('completed'):
        raise ValueError('Common gameplay bootstrap must precede semantic actions')
    backend = Backend(session, deadline)
    op, req = args['operation'], args.get('request', {})
    if op == 'state.read':
        scene = backend.call('inspect', {'kind': 'scene'})
        menus = backend.call('menu', {'action': 'list', 'includeFlags': True})
        ready = (scene.get('playerLoaded') is True and scene.get('cell', {}).get('editorId') not in (None, 'VRPlayroom01')
                 and not menus_block_gameplay(menus))
        return {'world': {'ready': ready}, 'scene': scene, 'menus': menus}
    if op == 'player.read':
        raw = backend.call('inspect', {'kind': 'player'})
        return {'player': {'health': {'points': raw['actorValues']['health']['current']}}, 'providerObservation': raw}
    if op == 'world.read': return backend.observe(req)
    if op == 'menu.read': return backend.call('menu', {'action': 'list'})
    if op == 'controller.perform': return backend.controller(req)
    return backend.mutate(req)
