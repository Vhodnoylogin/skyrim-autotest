"""Offline modal admission cases: localization, refusal evidence and no replay."""
import copy
import unittest

from skyrim_autotest import load_modal


SETTINGS = {'sConfirmLoad': 'Загрузить сохранение?', 'sLoadWhilePlaying': 'Изменения будут потеряны. Продолжить?',
            'sLoadFromMainMenu': 'Начать загрузку?', 'sYes': 'Да', 'sNo': 'Нет',
            'sOK': 'Принять', 'sCancel': 'Отмена'}


def modal(body=None, buttons=None, cancel=1):
    return {'messageBoxOpen': True, 'bodyText': SETTINGS['sLoadWhilePlaying'] if body is None else body,
            'buttons': [SETTINGS['sYes'], SETTINGS['sNo']] if buttons is None else buttons, 'cancelIndex': cancel}


class Session:
    def __init__(self):
        self.saved = []
        self.logs = []
        self.transition = {'saveTag': 'case-save', 'completed': False}

    def save(self): self.saved.append(copy.deepcopy(self.transition))
    def log(self, event, **data): self.logs.append((event, copy.deepcopy(data)))


class Backend:
    def __init__(self, descriptions=None, opened=True):
        self.s = Session()
        self.end = 12345
        self.opened = opened
        self.descriptions = [modal(), modal()] if descriptions is None else copy.deepcopy(descriptions)
        self.calls = []
        self.settings = copy.deepcopy(SETTINGS)
        self.receipt = {'queued': True, 'action': 'accept', 'index': 0}
        self.error = None

    def remaining(self): return 10

    def call(self, tool, args):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == 'papyrus':
            if args['action'] == 'describe':
                return {'name': 'Game', 'globalFunctions': [{'name': 'GetGameSettingString', 'native': True,
                        'params': [{'type': 'String'}], 'returnType': 'String'}]}
            key = 'sOK' if args['args'][0] == 'sOk' else args['args'][0]
            return {'called': True, 'returned': self.settings[key], 'returnedType': 'String'}
        if tool != 'menu': raise AssertionError('Unexpected tool')
        if args['action'] == 'list': return {'messageBoxOpen': self.opened, 'openMenus': ['MessageBoxMenu'] if self.opened else []}
        if args['action'] == 'describe': return self.descriptions.pop(0)
        if args != {'action': 'accept', 'index': 0}: raise AssertionError('Unexpected menu action')
        intent = self.s.saved[-1]['blockingModal']['answerIntent']
        assert intent['index'] == 0 and intent['loadCompletionProven'] is False
        if self.error: raise self.error
        return self.receipt

    def answers(self): return [args for tool, args in self.calls if tool == 'menu' and args['action'] == 'accept']


class LoadModalTests(unittest.TestCase):
    def test_prepare_reads_actual_all_seven_localized_native_settings(self):
        b = Backend()
        self.assertEqual(load_modal.prepare(b), SETTINGS)
        calls = [args['args'][0] for tool, args in b.calls if tool == 'papyrus' and args['action'] == 'call']
        self.assertEqual(calls, ['sOk' if key == 'sOK' else key for key in load_modal.KEYS])
        self.assertFalse(b.answers())

    def test_exact_localized_confirmation_has_one_durable_answer_intent(self):
        for descriptor in (modal(), modal(SETTINGS['sConfirmLoad']),
                           modal(SETTINGS['sLoadFromMainMenu'], [SETTINGS['sOK'], SETTINGS['sCancel']], -1)):
            with self.subTest(descriptor=descriptor):
                b = Backend([descriptor, descriptor])
                self.assertTrue(load_modal.handle(b, b.s.transition, SETTINGS))
                self.assertEqual(len(b.answers()), 1)
                self.assertEqual(b.s.transition['blockingModal']['status'], 'answer-queued')
                self.assertFalse(b.s.transition['completed'])
                self.assertEqual(len(b.s.transition['blockingModal']['observations']), 2)

    def test_unknown_modals_preserve_raw_descriptor_and_never_answer(self):
        for descriptor in (modal('Save is corrupt.'), modal('Missing content; load anyway?'),
                           modal(SETTINGS['sConfirmLoad'] + ' extra'), modal('', [], -1),
                           {'messageBoxOpen': True, 'bodyText': 'unexpected', 'extra': {'raw': 17}}):
            with self.subTest(descriptor=descriptor):
                b = Backend([descriptor])
                with self.assertRaises(ValueError): load_modal.handle(b, b.s.transition, SETTINGS)
                self.assertEqual(b.s.saved[-1]['blockingModal']['descriptor'], descriptor)
                self.assertTrue(any(event == 'owned-load-blocking-modal' for event, _ in b.s.logs))
                self.assertFalse(b.answers())

    def test_changed_body_buttons_or_cancel_on_recheck_denies_answer_and_retains_both(self):
        for changed in (modal('Other modal'), modal(buttons=['Yes', 'No']), modal(cancel=-1),
                        {'messageBoxOpen': False}):
            b = Backend([modal(), changed])
            with self.assertRaisesRegex(ValueError, 'changed before answer'):
                load_modal.handle(b, b.s.transition, SETTINGS)
            self.assertFalse(b.answers())
            observations = b.s.transition['blockingModal']['observations']
            self.assertEqual(observations[0]['descriptor'], modal())
            self.assertEqual(observations[1]['descriptor'], changed)

    def test_prior_queued_or_uncertain_answer_is_never_repeated(self):
        for error in (None, TimeoutError('answer callback lost')):
            b = Backend([modal(), modal(), modal()])
            b.error = error
            if error:
                with self.assertRaises(TimeoutError): load_modal.handle(b, b.s.transition, SETTINGS)
                self.assertEqual(b.s.transition['blockingModal']['status'], 'answer-uncertain')
            else:
                load_modal.handle(b, b.s.transition, SETTINGS)
            with self.assertRaisesRegex(ValueError, 'never repeat'):
                load_modal.handle(b, b.s.transition, SETTINGS)
            self.assertEqual(len(b.answers()), 1)

    def test_menu_closed_is_noop(self):
        b = Backend(opened=False)
        self.assertFalse(load_modal.handle(b, b.s.transition, SETTINGS))
        self.assertNotIn('blockingModal', b.s.transition)
        self.assertEqual(len(b.calls), 1)

    def test_missing_empty_or_nonstring_native_setting_never_admits_answer(self):
        for key, bad in (('sYes', ''), ('sConfirmLoad', None), ('sCancel', 12)):
            b = Backend()
            b.settings[key] = bad
            with self.assertRaises(ValueError): load_modal.prepare(b)
            self.assertFalse(b.answers())
        for settings in ({}, dict(SETTINGS, sYes=None), dict(SETTINGS, sNo=SETTINGS['sYes'])):
            b = Backend([modal()])
            with self.assertRaises(ValueError): load_modal.handle(b, b.s.transition, settings)
            self.assertEqual(b.s.transition['blockingModal']['descriptor'], modal())
            self.assertFalse(b.answers())

    def test_wrong_cancel_semantics_or_button_order_never_answer(self):
        for descriptor in (modal(cancel=-1), modal(buttons=[SETTINGS['sNo'], SETTINGS['sYes']]),
                           modal(buttons=[SETTINGS['sOK'], SETTINGS['sCancel']], cancel=1), modal(cancel=True)):
            b = Backend([descriptor])
            with self.assertRaises(ValueError): load_modal.handle(b, b.s.transition, SETTINGS)
            self.assertFalse(b.answers())

    def test_bad_queue_receipt_retains_intent_and_refuses_replay(self):
        b = Backend([modal(), modal(), modal()])
        b.receipt = {'accepted': True, 'index': 0}
        with self.assertRaisesRegex(ValueError, 'never replay'):
            load_modal.handle(b, b.s.transition, SETTINGS)
        self.assertEqual(b.s.transition['blockingModal']['status'], 'answer-uncertain')
        with self.assertRaisesRegex(ValueError, 'never repeat'):
            load_modal.handle(b, b.s.transition, SETTINGS)
        self.assertEqual(len(b.answers()), 1)


if __name__ == '__main__': unittest.main()
