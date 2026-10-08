"""One coordinated physical grip exchange, never a native scheduler or hand seed."""
import re

ACTION = 'exchange_grip'


def validate(operation, request):
    if request.get('action') != ACTION:
        return False
    if operation != 'controller.perform' or set(request) != {
            'action', 'fromHand', 'toHand', 'referenceTag', 'settleSeconds'}:
        raise ValueError('Grip exchange requires explicit hands, reference tag and settling')
    if (not isinstance(request['fromHand'], str) or not isinstance(request['toHand'], str) or
            {request['fromHand'], request['toHand']} != {'left', 'right'}):
        raise ValueError('Grip exchange requires two different physical hands')
    tag = request['referenceTag']
    if not isinstance(tag, str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', tag):
        raise ValueError('Grip exchange requires a valid live reference tag')
    from .platform import number
    number(request['settleSeconds'], .1, 2)
    return True


def held(backend, hand):
    value = backend.pap('HiggsVR', 'GetGrabbedObject', [hand == 'left'])
    if value is None:
        return None
    from .actor_domain import form
    if not isinstance(value, dict):
        raise ValueError('Native grip-exchange held identity unavailable')
    return form(value.get('formId'))


def perform(backend, request):
    from .actor_domain import form
    from .vr_probe import ensure_owned_focus
    from .readiness_state import menus_block_gameplay

    validate('controller.perform', request)
    backend.remaining()
    if backend.s.state.get('inputBackend') != 'driver' or backend.s.state.get('driverBackend') != 'file':
        raise ValueError('Grip exchange requires the owned physical file driver')
    ensure_owned_focus(backend.s, {}, 'platform-grip-exchange-owned-focus', deadline=backend.end)
    backend.recover_input_gate(backend.call('menu', {'action': 'list', 'includeFlags': True}))
    menus = backend.call('menu', {'action': 'list', 'includeFlags': True})
    if menus_block_gameplay(menus):
        raise ValueError('Gameplay blocked before grip exchange')
    source, target = request['fromHand'], request['toHand']
    reference = form(backend.tagged(request))
    incarnation = backend.reference_incarnation(reference)
    before = {source: held(backend, source), target: held(backend, target)}
    if before[source] != reference or before[target] is not None:
        raise ValueError('Grip exchange requires exact source ownership and an empty target')
    if backend.pap('HiggsVR', 'CanGrabObject', [target == 'left']) is not True:
        raise ValueError('Native receiving hand is not ready to grab')
    if backend.reference_incarnation(reference) != incarnation:
        raise ValueError('Grip-exchange reference incarnation changed before input')
    frame = backend.frame()
    # No neutralizing frame, hand movement, trigger edge or fixture seed is hidden here.
    # A source grip and an open receiver must already have been prepared normally.
    for hand, pressed in ((source, 4), (target, 0)):
        controller = frame[hand]['controller']
        if (type(controller.get('pressed')) is not int or controller['pressed'] != pressed or
                controller.get('touched') != 0 or controller.get('axes') != [[0, 0] for _ in range(5)]):
            raise ValueError('Grip exchange requires source grip-only and neutral receiver input')
    if request['settleSeconds'] >= backend.remaining():
        raise TimeoutError('Insufficient original deadline for grip exchange')
    backend.guard_world()
    frame[source]['controller']['pressed'] = 0
    frame[target]['controller']['pressed'] = 4
    backend.s.log('platform-grip-exchange-prepared', sourceHand=source, targetHand=target,
                  reference=reference, incarnation=incarnation, sampledOwnership=before,
                  sameCommand=True, consumerAtomicityProven=False, nativeRaceProven=False)
    # Exactly one full-device command. The driver's per-component publication is
    # not an atomic engine consumption claim; only native causal evidence can hit a race.
    publication = backend.publish(frame, request['settleSeconds'])
    backend.pause(request['settleSeconds'])
    backend.guard_world()
    return {'inputIssued': True, 'observedGameplaySuccess': None, 'publication': publication,
            'gripExchange': {'singlePublication': True, 'fromHand': source, 'toHand': target,
                             'reference': reference, 'incarnation': incarnation,
                             'posesUnchanged': True, 'nativeRaceProven': False,
                             'consumerAtomicityProven': False,
                             'basis': 'one physical full-frame command; subsequent exact held and native causal observations required'}}
