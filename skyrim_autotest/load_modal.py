"""Exact localized discard-changes confirmation during an already requested load.

The caller owns the SE load and its original deadline/lifecycle cursor. Answering
a recognized modal submits one UI action; it never establishes load completion.
"""
from __future__ import annotations

import copy

KEYS = ('sConfirmLoad', 'sLoadWhilePlaying', 'sLoadFromMainMenu',
        'sYes', 'sNo', 'sOK', 'sCancel')
LOAD_KEYS = KEYS[:3]


def _settings(settings):
    if (not isinstance(settings, dict) or set(settings) != set(KEYS)
            or any(not isinstance(settings[key], str) or not settings[key].strip()
                   or '\x00' in settings[key] or len(settings[key]) > 4096 for key in KEYS)
            or settings['sYes'] == settings['sNo'] or settings['sOK'] == settings['sCancel']):
        raise ValueError('Exact nonempty localized native load settings are unavailable')
    return settings


def prepare(backend):
    """Read all seven actual native GMST strings without changing game state."""
    from .interactive_bindings import _metadata, _native_call
    entry = {'script': 'Game', 'function': 'GetGameSettingString', 'scope': 'global',
             'params': ['string'], 'returnType': 'string'}
    _metadata(backend, entry)
    # sOk is the actual GMST editor ID; retain the common sOK result label.
    settings = {key: _native_call(backend, entry, ['sOk' if key == 'sOK' else key], None) for key in KEYS}
    _settings(settings)
    backend.remaining()
    backend.s.log('owned-load-localized-settings', settings=copy.deepcopy(settings),
                  basis='actual typed native Game.GetGameSettingString; no translated text guesses')
    return settings


def _retain(backend, transition, menus, descriptor, stage):
    record = transition.setdefault('blockingModal', {'status': 'observed', 'observations': []})
    if not isinstance(record, dict) or not isinstance(record.get('observations'), list):
        raise ValueError('Prior owned-load modal evidence is malformed; no answer')
    observation = {'stage': stage, 'menus': copy.deepcopy(menus), 'descriptor': copy.deepcopy(descriptor)}
    record['observations'].append(observation)
    record.setdefault('descriptor', copy.deepcopy(descriptor))
    record['latestDescriptor'] = copy.deepcopy(descriptor)
    backend.s.save()
    backend.s.log('owned-load-blocking-modal', saveTag=transition.get('saveTag'), **observation)
    return record


def _recognized(descriptor, settings):
    try:
        _settings(settings)
    except ValueError as error:
        raise ValueError(str(error) + '; rawDescriptor=' + repr(descriptor)) from error
    if (not isinstance(descriptor, dict) or descriptor.get('messageBoxOpen') is not True
            or not isinstance(descriptor.get('bodyText'), str) or not descriptor['bodyText']
            or not isinstance(descriptor.get('buttons'), list)
            or any(not isinstance(button, str) for button in descriptor['buttons'])
            or type(descriptor.get('cancelIndex')) is not int):
        raise ValueError('Actual native load confirmation descriptor is unavailable; rawDescriptor=' + repr(descriptor))
    if descriptor['bodyText'] not in [settings[key] for key in LOAD_KEYS]:
        raise ValueError('Unknown blocking modal during owned load; rawDescriptor=' + repr(descriptor))
    if ((descriptor['buttons'] == [settings['sYes'], settings['sNo']] and descriptor['cancelIndex'] == 1)
            or (descriptor['buttons'] == [settings['sOK'], settings['sCancel']] and descriptor['cancelIndex'] == -1)):
        return
    raise ValueError('Load confirmation buttons/cancel semantics differ; rawDescriptor=' + repr(descriptor))


def handle(backend, transition, settings):
    """Observe and, for one exact confirmation only, queue its affirmative option.

    Call only after the current owned SE load emitted a MessageBox opening event.
    Unknown callbacks, changed dialogs and repeated intents never replay input.
    """
    if not isinstance(transition, dict) or transition.get('completed') is not False:
        raise ValueError('Load modal handling requires the current incomplete owned transition')
    backend.remaining()
    menus = backend.call('menu', {'action': 'list'})
    if not isinstance(menus, dict) or type(menus.get('messageBoxOpen')) is not bool:
        raise ValueError('Current native message-box menu state unavailable')
    if menus['messageBoxOpen'] is False:
        return False
    descriptor = backend.call('menu', {'action': 'describe'})
    record = _retain(backend, transition, menus, descriptor, 'initial')
    if 'answerIntent' in record:
        raise ValueError('Owned-load modal already has an answer intent; never repeat an uncertain action')
    _recognized(descriptor, settings)
    current = backend.call('menu', {'action': 'describe'})
    _retain(backend, transition, menus, current, 'pre-answer-recheck')
    if current != descriptor:
        record['status'] = 'changed-before-answer'
        backend.s.save()
        raise ValueError('Owned-load modal changed before answer; both native descriptors retained')
    _recognized(current, settings)
    backend.remaining()
    record['answerIntent'] = {'index': 0, 'descriptor': copy.deepcopy(current),
                              'basis': 'exact current localized load body, button pair and cancel index',
                              'loadCompletionProven': False}
    record['status'] = 'answer-intent'
    backend.s.save()
    backend.s.log('owned-load-modal-answer-intent', saveTag=transition.get('saveTag'),
                  answer=copy.deepcopy(record['answerIntent']))
    try:
        receipt = backend.call('menu', {'action': 'accept', 'index': 0})
        record['answerReceipt'] = copy.deepcopy(receipt)
        backend.remaining()
        if (not isinstance(receipt, dict) or receipt.get('queued') is not True
                or receipt.get('action') != 'accept' or type(receipt.get('index')) is not int
                or receipt['index'] != 0):
            raise ValueError('Native load-confirmation answer receipt unavailable; never replay')
    except BaseException as error:
        record['status'] = 'answer-uncertain'
        record['answerError'] = str(error)
        backend.s.save()
        backend.s.log('owned-load-modal-answer-uncertain', saveTag=transition.get('saveTag'), error=str(error))
        raise
    record['status'] = 'answer-queued'
    backend.s.save()
    backend.s.log('owned-load-modal-answer-queued', saveTag=transition.get('saveTag'),
                  receipt=copy.deepcopy(receipt), loadCompletionProven=False)
    return True
