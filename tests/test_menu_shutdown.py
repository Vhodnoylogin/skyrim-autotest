"""SE menu exit state transitions and non-replay boundaries, without a game."""
import copy
import unittest
from contextlib import ExitStack
from unittest.mock import Mock, patch

from skyrim_autotest import config, game_shutdown, menu_shutdown

GAME = {'pid': 42, 'birth': 1234, 'path': 'D:/Game/SkyrimSE.exe'}


class Clock:
    now = 0.
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Session:
    def __init__(self, clock):
        self.clock, self.main, self.confirm, self.quit_at = clock, False, False, None
        self.crosshair, self.angles, self.aim_clears = None, [0., 5., 90.], True
        self.state = {'configuration': {'game_edition': 'se'}, 'port': 123,
                      'game': copy.deepcopy(GAME), 'owned': [{'role': 'game', 'identity': copy.deepcopy(GAME)}]}
        self.saved, self.calls = [], []
        self.guard_shutdown, self.log = Mock(), Mock()
        self.tool = Mock(side_effect=self.call)
    def alive(self, _): return self.quit_at is None or self.clock.now < self.quit_at
    def save(self): self.saved.append(copy.deepcopy(self.state))
    def observe_game_exit(self, stage):
        self.state.setdefault('gameProcessObservations', []).append({'identity': copy.deepcopy(GAME),
            'expectedIdentity': copy.deepcopy(GAME), 'identityVerified': True, 'status': 'exited',
            'exitCodeAvailable': True, 'exitCode': 0, 'stage': stage})
    def snapshot(self):
        return {'contract': menu_shutdown.CONTRACT, 'menu': 'Main Menu',
                'state': 'MainConfirm' if self.confirm else 'Main',
                'entries': [{'position': 0, 'index': 1, 'text': '$NEW', 'disabled': False},
                            {'position': 1, 'index': 9, 'text': '$QUIT', 'disabled': False}],
                'selected': {'index': 9 if self.confirm else 1, 'text': '$QUIT' if self.confirm else '$NEW', 'disabled': False}}
    def call(self, name, args, **kwargs):
        self.calls.append((name, copy.deepcopy(args)))
        self.assert_saved_before_mutation(args)
        if name == 'menu' and args['action'] == 'list':
            return {'openMenus': ['Main Menu'] if self.main else ['HUD Menu'], 'messageBoxOpen': False}
        if name == 'papyrus' and args['action'] == 'describe':
            if args['script'] == 'Game':
                return {'name': 'Game', 'globalFunctions': [
                    {'name': 'QuitToMainMenu', 'params': [], 'returnType': 'None', 'native': True},
                    {'name': 'GetCurrentCrosshairRef', 'params': [], 'returnType': 'ObjectReference', 'native': True}]}
            return {'name': 'ObjectReference', 'memberFunctions': [
                {'name': 'SetAngle', 'params': [{'type': 'float'}] * 3, 'returnType': 'none', 'native': True},
                *[{'name': 'GetAngle' + axis, 'params': [], 'returnType': 'float', 'native': True} for axis in 'XYZ']]}
        if name == 'papyrus':
            function = args['function']
            if function == 'GetCurrentCrosshairRef':
                return {'called': True, 'returned': self.crosshair, 'returnedType': 'objectreference' if self.crosshair else 'none'}
            if function.startswith('GetAngle'):
                assert args['self'] == {'form': '0x00000014'}
                return {'called': True, 'returned': self.angles['XYZ'.index(function[-1])], 'returnedType': 'float'}
            if function == 'SetAngle':
                assert args['self'] == {'form': '0x00000014'} and len(args['args']) == 3
                self.angles = list(args['args'])
                if self.aim_clears: self.crosshair = None
            else:
                assert function == 'QuitToMainMenu'
                self.main = True
            return {'called': True, 'returned': None, 'returnedType': 'none'}
        op = args['startupOperation']
        if op == 'snapshot': return self.snapshot()
        if op == 'select-quit': self.confirm = True
        if op == 'confirm-quit': self.quit_at = self.clock.now + .4
        return {'contract': menu_shutdown.CONTRACT, 'operation': op, 'completed': True}
    def assert_saved_before_mutation(self, args):
        stage = ('crosshairAim' if args.get('function') == 'SetAngle' else
                 'mainMenuReturn' if args.get('function') == 'QuitToMainMenu' else
                 'quitSelection' if args.get('startupOperation') == 'select-quit' else
                 'desktopQuit' if args.get('startupOperation') == 'confirm-quit' else None)
        if stage:
            assert self.saved[-1]['gracefulGameExit'][stage]['requestAttempted'] is True
    def request(self, port, route, **kwargs):
        if route == 'api/events': return {'events': [], 'headSeq': 20}
        return {'events': [{'seq': 21, 'topic': 'menu', 'data': {'name': 'Main Menu', 'opening': True}}], 'headSeq': 21}


class MenuExitTests(unittest.TestCase):
    def setUp(self):
        self.stack, self.clock = ExitStack(), Clock()
        self.addCleanup(self.stack.close)
        self.s = Session(self.clock)
        self.stack.enter_context(patch.object(menu_shutdown.time, 'monotonic', self.clock.monotonic))
        self.stack.enter_context(patch.object(menu_shutdown.time, 'sleep', self.clock.sleep))
        self.stack.enter_context(patch.object(game_shutdown.native, 'alive', side_effect=self.s.alive))
        self.stack.enter_context(patch.object(game_shutdown.native, 'identity', side_effect=lambda pid: GAME if self.s.alive(GAME) else None))
        self.close = self.stack.enter_context(patch.object(game_shutdown.native, 'close'))
        self.kill = self.stack.enter_context(patch.object(game_shutdown.native, 'terminate'))
        self.stack.enter_context(patch('skyrim_autotest.runner.request', side_effect=self.s.request))
        self.addCleanup(self.check_no_process_actions)
    def check_no_process_actions(self): self.close.assert_not_called(); self.kill.assert_not_called()
    def test_world_return_then_quit_requires_actual_exit_and_durable_each_intent(self):
        self.assertTrue(menu_shutdown.request_and_wait(self.s))
        r = self.s.state['gracefulGameExit']
        self.assertTrue(r['mainMenuOpenedObserved']); self.assertTrue(r['desktopQuit']['requestAttempted'])
        self.assertEqual(r['desktopQuit']['game'], GAME)
        self.assertEqual(r['deadlineMonotonic'], 45.)
        self.assertEqual(game_shutdown.classify_exit(self.s)['kind'], 'normal_close')
        actions = [a.get('startupOperation') or a.get('function') for _, a in self.s.calls]
        self.assertEqual([a for a in actions if a in ('QuitToMainMenu', 'select-quit', 'confirm-quit')],
                         ['QuitToMainMenu', 'select-quit', 'confirm-quit'])
    def test_already_main_menu_never_calls_papyrus(self):
        self.s.main = True
        self.assertTrue(menu_shutdown.request_and_wait(self.s))
        self.assertFalse(any(n == 'papyrus' for n, _ in self.s.calls))
        self.assertTrue(self.s.state['gracefulGameExit']['mainMenuAlreadyOpen'])
    def test_unknown_confirmation_never_selects_or_confirms_quit(self):
        self.s.main = self.s.confirm = True
        self.assertFalse(menu_shutdown.request_and_wait(self.s))
        self.assertFalse(any(a.get('startupOperation') in ('select-quit', 'confirm-quit') for _, a in self.s.calls))
    def test_event_gap_preserves_uncertainty_and_no_desktop_quit(self):
        with patch('skyrim_autotest.runner.request', side_effect=[{'headSeq': 20}, {'events': [{'seq': 22}], 'headSeq': 22}]):
            self.assertFalse(menu_shutdown.request_and_wait(self.s))
        self.assertNotIn('desktopQuit', self.s.state['gracefulGameExit'])
    def test_uncertain_selection_is_not_repeated_by_recovery(self):
        normal = self.s.call
        def call(n, a, **kw):
            result = normal(n, a, **kw)
            if a.get('startupOperation') == 'select-quit': raise TimeoutError('receipt lost')
            return result
        self.s.tool.side_effect = call
        self.assertFalse(menu_shutdown.request_and_wait(self.s))
        self.assertGreaterEqual(self.clock.now, 45.)
        count = self.s.tool.call_count
        self.assertFalse(menu_shutdown.request_and_wait(self.s))
        self.assertEqual(self.s.tool.call_count, count)
        self.assertFalse(self.s.state['gracefulGameExit']['requestAttempted'])
    def test_uncertain_return_to_menu_keeps_original_grace_before_fallback(self):
        normal = self.s.call
        def call(n, a, **kw):
            result = normal(n, a, **kw)
            if a.get('function') == 'QuitToMainMenu': raise TimeoutError('native callback receipt lost')
            return result
        self.s.tool.side_effect = call
        self.assertFalse(menu_shutdown.request_and_wait(self.s, seconds=1))
        self.assertGreaterEqual(self.clock.now, 1.)
        self.assertNotIn('desktopQuit', self.s.state['gracefulGameExit'])
        count = self.s.tool.call_count
        self.assertFalse(menu_shutdown.request_and_wait(self.s, seconds=1))
        self.assertEqual(self.s.tool.call_count, count)
    def test_uncertain_desktop_response_can_only_wait_for_observed_exit(self):
        normal = self.s.call
        def call(n, a, **kw):
            result = normal(n, a, **kw)
            if a.get('startupOperation') == 'confirm-quit': raise ConnectionResetError('game exited')
            return result
        self.s.tool.side_effect = call
        self.assertTrue(menu_shutdown.request_and_wait(self.s))
        self.assertEqual(game_shutdown.classify_exit(self.s)['kind'], 'normal_close')
        self.assertEqual(sum(a.get('startupOperation') == 'confirm-quit' for _, a in self.s.calls), 1)
    def test_no_exit_is_timeout_not_success_or_second_input(self):
        normal = self.s.call
        def call(n, a, **kw):
            result = normal(n, a, **kw)
            if a.get('startupOperation') == 'confirm-quit': self.s.quit_at = None
            return result
        self.s.tool.side_effect = call
        self.assertFalse(menu_shutdown.request_and_wait(self.s, seconds=.5))
        self.assertEqual(self.s.state['gracefulGameExit']['status'], 'grace-expired')
    def test_main_menu_only_and_wrong_desktop_identity_never_prove_normal_close(self):
        self.s.observe_game_exit('test')
        r = {'game': copy.deepcopy(GAME), 'command': 'menu-main-quit', 'requestAttempted': True}
        self.s.state['gracefulGameExit'] = r
        self.assertEqual(game_shutdown.classify_exit(self.s)['kind'], 'unknown')
        r['desktopQuit'] = {'game': dict(GAME, birth=99), 'requestAttempted': True}
        self.assertEqual(game_shutdown.classify_exit(self.s)['kind'], 'unknown')
    def test_old_or_foreign_route_never_replays(self):
        self.s.state['gracefulGameExit'] = {'game': GAME, 'command': 'qqq'}
        with self.assertRaises(RuntimeError): menu_shutdown.request_and_wait(self.s)
        self.s.tool.assert_not_called()
    def test_signature_must_be_native_noarg_none(self):
        normal = self.s.call
        def call(n, a, **kw):
            result = normal(n, a, **kw)
            if a.get('action') == 'describe': result['globalFunctions'][0]['native'] = False
            return result
        self.s.tool.side_effect = call
        self.assertFalse(menu_shutdown.request_and_wait(self.s))
        self.assertFalse(any(a.get('function') == 'QuitToMainMenu' for _, a in self.s.calls))
    def test_retained_crosshair_released_before_world_teardown_with_native_three_angle_call(self):
        self.s.crosshair = {'formId': '0xFF000001'}
        self.assertTrue(menu_shutdown.request_and_wait(self.s))
        r = self.s.state['gracefulGameExit']['crosshairRelease']
        self.assertTrue(r['released']); self.assertEqual(self.s.angles, [-85., 5., 90.])
        self.assertEqual([v['returned'] for v in r['samples'][-2:]], [None, None])
        functions = [a.get('function') for _, a in self.s.calls]
        self.assertLess(functions.index('SetAngle'), functions.index('QuitToMainMenu'))
        self.assertEqual(functions.count('SetAngle'), 1)
    def test_crosshair_remaining_never_requests_world_teardown_or_repeats_pitch(self):
        self.s.crosshair, self.s.aim_clears = {'formId': '0xFF000001'}, False
        self.assertFalse(menu_shutdown.request_and_wait(self.s))
        functions = [a.get('function') for _, a in self.s.calls]
        self.assertEqual(functions.count('SetAngle'), 1)
        self.assertNotIn('QuitToMainMenu', functions)
        self.assertNotIn('desktopQuit', self.s.state['gracefulGameExit'])
        self.assertGreaterEqual(self.clock.now, 45.)
    def test_already_clear_crosshair_requires_no_angle_mutation(self):
        self.assertTrue(menu_shutdown.request_and_wait(self.s))
        self.assertTrue(self.s.state['gracefulGameExit']['crosshairRelease']['released'])
        self.assertFalse(any(a.get('function') == 'SetAngle' for _, a in self.s.calls))
    def test_malformed_or_duplicate_quit_is_refused(self):
        for change in ('disabled', 'index', 'duplicate', 'bool-position'):
            snapshot = self.s.snapshot()
            if change == 'disabled': snapshot['entries'][1]['disabled'] = True
            if change == 'index': snapshot['entries'][1]['index'] = 8
            if change == 'duplicate': snapshot['entries'].append(dict(snapshot['entries'][1], position=2))
            if change == 'bool-position': snapshot['entries'][0]['position'] = False
            with self.subTest(change=change), self.assertRaises(ValueError): menu_shutdown.selection(snapshot, 'Main')
    def test_invalid_bounds_or_vr_never_send_input(self):
        for value in (True, 0, -1, 61, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError): menu_shutdown.request_and_wait(self.s, value)
        self.s.state['configuration']['game_edition'] = 'vr'
        with self.assertRaises(ValueError): menu_shutdown.request_and_wait(self.s)
        self.s.tool.assert_not_called()
    def test_config_policy_is_explicit_and_se_only(self):
        for mode in ('main-menu-v1', 'console-qqq'):
            value = config.template('se'); value['se_shutdown'] = mode
            self.assertEqual(config.configure(value)['se_shutdown'], mode)
        for edition, mode in (('vr', 'main-menu-v1'), ('se', True), ('se', 'unknown')):
            value = config.template(edition); value['se_shutdown'] = mode
            with self.assertRaises(config.ConfigurationError): config.configure(value)


if __name__ == '__main__': unittest.main()
