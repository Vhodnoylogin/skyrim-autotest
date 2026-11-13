"""One explicitly matched confirmation while an owned pinned fixture is loading."""
import copy
import hashlib
import json
import time


def validate_policy(value):
    if (not isinstance(value, dict) or set(value) != {'bodyText', 'buttons', 'index'}
            or not isinstance(value['bodyText'], str) or not 1 <= len(value['bodyText']) <= 8192
            or not isinstance(value['buttons'], list) or len(value['buttons']) != 2
            or any(not isinstance(button, str) or not 1 <= len(button) <= 256 for button in value['buttons'])
            or value['buttons'][0] == value['buttons'][1]
            or type(value['index']) is not int or value['index'] not in (0, 1)):
        raise ValueError('Owned fixture confirmation requires exact bodyText, two distinct buttons and one index')
    return copy.deepcopy(value)


def fingerprint(value):
    fields = {key: value[key] for key in ('bodyText', 'buttons')}
    encoded = json.dumps(fields, sort_keys=True, ensure_ascii=True, separators=(',', ':')).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def confirm_pending_fixture(session, deadline):
    raw_policy = session.state.get('configuration', {}).get('owned_fixture_confirmation')
    if raw_policy is None:
        return False
    policy = validate_policy(raw_policy)
    intent = session.state.get('initialFixtureLoadIntent', {})
    transition = session.state.get('initialWorldTransition', {})
    if (session.state.get('configuration', {}).get('game_edition') != 'se'
            or session.state.get('configuration', {}).get('allow_owned_save_load') is not True
            or intent.get('requestAttempted') is not True or intent.get('acknowledged') is not True
            or intent.get('game') != session.state.get('game')
            or intent.get('fixture') != session.state.get('scenario', {}).get('fixture')
            or transition.get('mode') != 'fixture' or transition.get('completed') is not False
            or transition.get('beforeGame') != session.state.get('game')):
        raise ValueError('Expected confirmation is outside the pending owned fixture load')

    def call(arguments):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Original fixture-load deadline expired; no confirmation')
        return session.tool('menu', arguments, timeout=min(4, remaining), deadline=deadline)

    menus = call({'action': 'list'})
    if not isinstance(menus, dict) or type(menus.get('messageBoxOpen')) is not bool:
        raise ValueError('Actual fixture-load menu state unavailable')
    if menus['messageBoxOpen'] is False:
        return False

    def describe():
        observed = call({'action': 'describe'})
        if (not isinstance(observed, dict) or observed.get('messageBoxOpen') is not True
                or observed.get('bodyText') != policy['bodyText'] or observed.get('buttons') != policy['buttons']):
            raise ValueError('Fixture-load confirmation differs from the exact authorized message')
        return observed

    before = describe()
    previous = session.state.get('initialFixtureConfirmation')
    if previous is not None:
        if (not isinstance(previous, dict) or previous.get('game') != intent['game']
                or previous.get('fingerprint') != fingerprint(policy)):
            raise ValueError('Fixture confirmation intent belongs to another message or game')
        return False  # A queued callback or lost reply never permits another accept.
    from .se_startup import pinned_owned_fixture
    if not pinned_owned_fixture(session):
        raise ValueError('Pinned owned fixture is unavailable during confirmation')
    fresh = describe()
    record = {'game': copy.deepcopy(intent['game']), 'fixture': copy.deepcopy(intent['fixture']),
              'fingerprint': fingerprint(policy), 'index': policy['index'], 'before': copy.deepcopy(before),
              'freshBefore': copy.deepcopy(fresh), 'requestAttempted': True, 'acknowledged': False}
    session.state['initialFixtureConfirmation'] = record
    session.save()
    session.log('owned-fixture-confirmation-intent', intent=copy.deepcopy(record))
    acknowledgement = call({'action': 'accept', 'index': policy['index']})
    if (not isinstance(acknowledgement, dict) or acknowledgement.get('queued') is not True
            or acknowledgement.get('index') != policy['index']):
        raise ValueError('Fixture confirmation acknowledgement unavailable; do not replay')
    record.update(acknowledged=True, receipt=copy.deepcopy(acknowledgement), after=copy.deepcopy(call({'action': 'list'})))
    session.save()
    session.log('owned-fixture-confirmation-observed', receipt=copy.deepcopy(record), acceptedAsLoadCompletion=False)
    return True


def confirm_pending_owned_load(backend, transition, record):
    """Accept the exact configured message only for this acknowledged owned load.

    The caller has just observed its MessageBox opening event. Files are pinned
    again before the one action; only ordered lifecycle events prove the load.
    """
    session, state = backend.s, backend.s.state
    raw_policy = state.get('configuration', {}).get('owned_fixture_confirmation')
    if raw_policy is None:
        return False
    policy = validate_policy(raw_policy)
    intent = transition.get('loadIntent', {})
    if (state.get('configuration', {}).get('game_edition') != 'se'
            or state.get('configuration', {}).get('allow_owned_save_load') is not True
            or transition is not state.get('ownedLoadTransition')
            or transition.get('completed') is not False
            or intent.get('requestAttempted') is not True or intent.get('acknowledged') is not True
            or intent.get('game') != state.get('game')
            or intent.get('saveTag') != transition.get('saveTag')
            or state.get('ownedSaves', {}).get(intent.get('saveTag')) is not record
            or record.get('completed') is not True or record.get('ownedByAttempt') is not True
            or intent.get('stem') != record.get('stem') or intent.get('files') != record.get('files')
            or intent.get('directory') != state.get('ownedSaveDirectory')):
        raise ValueError('Exact confirmation is outside this acknowledged owned save load')
    backend.remaining()
    descriptor = backend.call('menu', {'action': 'describe'})
    if (not isinstance(descriptor, dict) or descriptor.get('messageBoxOpen') is not True
            or descriptor.get('bodyText') != policy['bodyText'] or descriptor.get('buttons') != policy['buttons']):
        return False
    if descriptor.get('cancelIndex') != -1:
        raise ValueError('Configured owned load confirmation cancel semantics changed')
    previous = transition.get('exactConfirmation')
    if previous is not None:
        raise ValueError('Owned save confirmation already attempted; never replay')
    from pathlib import Path
    from .owned_saves import pair
    if pair(Path(intent['directory']), intent['stem']) != intent['files']:
        raise ValueError('Owned save pair changed before exact confirmation')
    fresh = backend.call('menu', {'action': 'describe'})
    if fresh != descriptor:
        raise ValueError('Owned save confirmation changed before answer')
    answer = {'game': copy.deepcopy(intent['game']), 'saveTag': intent['saveTag'],
              'stem': intent['stem'], 'files': copy.deepcopy(intent['files']),
              'fingerprint': fingerprint(policy), 'index': policy['index'],
              'before': copy.deepcopy(descriptor), 'freshBefore': copy.deepcopy(fresh),
              'requestAttempted': True, 'acknowledged': False}
    transition['exactConfirmation'] = answer
    session.save()
    session.log('owned-save-exact-confirmation-intent', intent=copy.deepcopy(answer))
    receipt = backend.call('menu', {'action': 'accept', 'index': policy['index']})
    if (not isinstance(receipt, dict) or receipt.get('queued') is not True
            or receipt.get('action') != 'accept' or type(receipt.get('index')) is not int
            or receipt['index'] != policy['index']):
        raise ValueError('Owned save confirmation reply unavailable; never replay')
    answer.update(acknowledged=True, receipt=copy.deepcopy(receipt),
                  after=copy.deepcopy(backend.call('menu', {'action': 'list'})))
    session.save()
    session.log('owned-save-exact-confirmation-observed', receipt=copy.deepcopy(answer),
                acceptedAsLoadCompletion=False)
    return True
