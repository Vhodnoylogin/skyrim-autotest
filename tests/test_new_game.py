"""New-game readiness must use a verified NEW item and a fresh lifecycle."""
import unittest
from unittest.mock import patch

from skyrim_autotest import bootstrap, runner, scenarios


class Clock:
    now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Session:
    def __init__(self, selected=1):
        self.state = {'port': 1}
        self.calls = []
        self.mode = 'Main'
        self.selected = selected
        self.started = False
    def phase(self, *args): pass
    def save(self): pass
    def log(self, *args, **kwargs): pass
    def tool(self, name, args):
        self.calls.append((name, args))
        if name == 'menu': return {'openMenus': ['Main Menu']}
        if name == 'inspect': return {'frame': 10}
        if name != 'papyrus': raise AssertionError(name)
        if args['action'] == 'describe':
            return {'name': 'UI', 'globalFunctions': [
                {'name': function, 'params': [{'type': t} for t in types]}
                for function, types in {
                    'GetInt': ['String', 'String'], 'GetString': ['String', 'String'],
                    'GetBool': ['String', 'String'], 'SetInt': ['String', 'String', 'Int'],
                    'InvokeInt': ['String', 'String', 'Int'],
                    'InvokeBool': ['String', 'String', 'Bool']}.items()]}
        function = args['function']
        path = args['args'][1]
        if function == 'GetString':
            value = self.mode if path.endswith('strCurrentState') else '$NEW'
        elif function == 'GetInt':
            value = 1 if path.endswith('length') or 'entryList' in path else self.selected
        elif function == 'GetBool': value = False
        elif function == 'SetInt': value = None
        elif function == 'InvokeInt': self.mode = 'MainConfirm'; value = None
        elif function == 'InvokeBool': self.started = True; value = None
        else: raise AssertionError(function)
        return {'returned': value}


class NewGameTests(unittest.TestCase):
    def test_new_game_rejects_any_pinned_save_or_undeclared_world(self):
        for value in ({'fixture': {'saveStem': 'anything'}, 'cell': 'RealmLorkhan'}, {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'New Game'):
                scenarios.validate({'schemaVersion': 1, 'startMode': 'new-game',
                                    'kind': 'vr-mobility-probe', **value})

    def test_wrong_selection_never_confirms_or_starts_new_world(self):
        session = Session(selected=7)
        with self.assertRaisesRegex(AssertionError, 'selection changed'):
            bootstrap.start_new_game(session, 'RealmLorkhan')
        self.assertFalse(session.started)
        self.assertFalse(any(args.get('function', '').startswith('Invoke')
                             for _, args in session.calls))

    def test_request_must_produce_fresh_new_game_not_an_old_event(self):
        session = Session(); clock = Clock()
        old = {'events': [{'topic': 'lifecycle', 'data': {'event': 'newGame'},
                           'seq': 1, 'frame': 10}]}
        with patch.object(runner, 'request', return_value=old), \
                patch.object(bootstrap.time, 'monotonic', clock.monotonic), \
                patch.object(bootstrap.time, 'sleep', clock.sleep):
            with self.assertRaisesRegex(AssertionError, 'fresh world transition'):
                bootstrap.start_new_game(session, 'RealmLorkhan')
        self.assertNotIn('newGameStarted', session.state)
        self.assertEqual(sum(args.get('function') == 'InvokeBool'
                             for _, args in session.calls), 1)

    def test_verified_new_game_never_loads_a_save_or_uses_console_bootstrap(self):
        session = Session(); clock = Clock()
        events = {'events': [
            {'topic': 'menu', 'data': {'name': 'Main Menu', 'opening': False}, 'seq': 2, 'frame': 11},
            {'topic': 'menu', 'data': {'name': 'Loading Menu', 'opening': True}, 'seq': 3, 'frame': 11},
            {'topic': 'scene.cellLoaded', 'data': {'cell': 'RealmLorkhan'}, 'seq': 4, 'frame': 12}]}
        with patch.object(runner, 'request', side_effect=[{'events': []}, events]), \
                patch.object(bootstrap.time, 'monotonic', clock.monotonic), \
                patch.object(bootstrap.time, 'sleep', clock.sleep):
            bootstrap.start_new_game(session, 'RealmLorkhan')
        self.assertTrue(session.state['newGameStarted']['events'])
        self.assertFalse(session.state['newGameStarted']['saveLoaded'])
        self.assertFalse(session.state['newGameStarted']['lifecycleNewGameObserved'])
        self.assertFalse(any(name in ('game', 'console') for name, _ in session.calls))

    def test_cell_event_alone_or_wrong_world_does_not_establish_new_game(self):
        for cell, include_menus in [('RealmLorkhan', False), ('Other', True)]:
            session = Session(); clock = Clock()
            events = [{'topic': 'scene.cellLoaded', 'data': {'cell': cell}, 'seq': 4, 'frame': 12}]
            if include_menus:
                events = [
                    {'topic': 'menu', 'data': {'name': 'Main Menu', 'opening': False}, 'seq': 2, 'frame': 11},
                    {'topic': 'menu', 'data': {'name': 'Loading Menu', 'opening': True}, 'seq': 3, 'frame': 11}, *events]
            with self.subTest(cell=cell), patch.object(runner, 'request', side_effect=lambda *a: {
                    'events': events if session.started else []}), \
                    patch.object(bootstrap.time, 'monotonic', clock.monotonic), \
                    patch.object(bootstrap.time, 'sleep', clock.sleep):
                with self.assertRaisesRegex(AssertionError, 'fresh world transition'):
                    bootstrap.start_new_game(session, 'RealmLorkhan')
            self.assertNotIn('newGameStarted', session.state)

    def test_delayed_startup_modal_is_collected_without_a_second_button(self):
        class CalibrationSession:
            state = {'inputBackend': 'driver', 'driverBackend': 'file'}
            def __init__(self): self.lists = 0; self.actions = []
            def phase(self, *args): pass
            def log(self, *args, **kwargs): pass
            def tool(self, name, args):
                if name == 'inspect': return {'cell': {'editorId': 'VRPlayroom01'}}
                if name == 'driver': self.actions.append(args['action']); return {}
                self.lists += 1
                return {'openMenus': ['CalibrationOptionMenu'] if self.lists < 3 else ['Main Menu'],
                        'messageBoxOpen': self.lists == 2}
        session = CalibrationSession()
        with patch.object(bootstrap.time, 'sleep'), \
                patch.object(bootstrap.vr_probe, 'guard_fixture_modal') as modal:
            self.assertTrue(bootstrap.advance_calibration(session))
        modal.assert_called_once_with(session)
        self.assertEqual(session.actions, ['publish', 'release'])


if __name__ == '__main__': unittest.main()
