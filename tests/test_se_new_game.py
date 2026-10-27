"""Explicit platform-owned SE initialization without changing subject fixtures."""
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import bootstrap, config, editions, runner
from skyrim_autotest.initial_world import InitialWorld
import tests.test_initial_world as fixtures


class SENewGameTests(unittest.TestCase):
    def test_policy_is_explicit_boolean_se_only_and_does_not_replace_pinned_save(self):
        value = config.template('se')
        for key in config.REQUIRED - {'openvr_paths'}: value[key] = 'C:/Fixture/'+key
        for selected in (1, 'true', None):
            with self.subTest(selected=selected), self.assertRaises(config.ConfigurationError):
                config.configure(dict(value, se_new_game_ui=selected))
        with self.assertRaises(config.ConfigurationError):
            config.configure(dict(value, game_edition='vr', openvr_paths='C:/VR', se_new_game_ui=True))
        before = config.P.snapshot(); self.addCleanup(lambda: setattr(config.P, 'value', before))
        self.assertTrue(config.configure(dict(value, se_new_game_ui=True))['se_new_game_ui'])
        editions.validate_scenario(dict(value, se_new_game_ui=True), {'cell': 'QASmoke'}, 'none', 'devbench')
        for scenario in ({}, {'cell': 'QASmoke', 'fixture': {'saveStem': 'pinned'}}):
            with self.assertRaises(ValueError):
                editions.validate_scenario(dict(value, se_new_game_ui=True), scenario, 'none', 'devbench')
        with self.assertRaises(ValueError):
            editions.validate_scenario(value, {'startMode': 'new-game', 'cell': 'QASmoke'}, 'none', 'devbench')

    def test_platform_policy_runs_real_new_game_path_before_original_cell(self):
        session = fixtures.Session()
        session.state['configuration'] = {'game_edition': 'se', 'se_new_game_ui': True}
        order=[]
        session.wait_task_queue=Mock(side_effect=lambda:order.append('normal-task-readiness'))
        scenario = {'cell': 'QASmoke'}
        def ready(*args,**kwargs):
            order.append('gameplay-readiness');return fixtures.SCENE,fixtures.MENUS
        with patch.object(bootstrap, 'prepare_startup_screen')as screen, \
             patch.object(bootstrap, 'start_new_game',side_effect=lambda *args:order.append('native-new-game-transition')) as start, \
             patch.object(bootstrap, 'wait_gameplay_ready', side_effect=ready), \
             patch.object(bootstrap.vr_probe, 'guard_fixture_modal', return_value=False), \
             patch.object(bootstrap.vr_probe, 'wait_test_cell', return_value=fixtures.SCENE), \
             patch('skyrim_autotest.initial_world.InitialWorld') as initial:
            initial.return_value.read.return_value = ['newGame']
            bootstrap.prepare_gameplay(session, scenario)
        start.assert_called_once_with(session, 'QASmoke')
        screen.assert_not_called()
        session.wait_task_queue.assert_called_once_with()
        self.assertEqual(order[:3],['native-new-game-transition','normal-task-readiness','gameplay-readiness'])
        self.assertEqual(initial.call_args.args[1], 'new-game')
        self.assertEqual(scenario, {'cell': 'QASmoke'})
        self.assertEqual(session.state['gameplayBootstrap']['startupSelection'], 'platform')
        self.assertEqual(session.state['gameplayBootstrap']['startMode'], 'new-game')
        self.assertFalse(any(c.args[0] in ('game', 'console') for c in session.tool.call_args_list))

    def test_uncertain_ui_transition_never_attempts_normal_queue_or_fixture_actions(self):
        session=fixtures.Session();session.state['configuration']={'game_edition':'se','se_new_game_ui':True}
        session.wait_task_queue=Mock()
        with patch.object(bootstrap,'prepare_startup_screen')as screen,patch('skyrim_autotest.initial_world.InitialWorld'),\
             patch.object(bootstrap,'start_new_game',side_effect=TimeoutError('Unknown confirm result')),\
             patch.object(bootstrap,'wait_gameplay_ready')as ready,self.assertRaises(TimeoutError):
            bootstrap.prepare_gameplay(session,{'cell':'QASmoke'})
        screen.assert_not_called();session.wait_task_queue.assert_not_called();ready.assert_not_called();session.tool.assert_not_called()

    def test_post_new_game_task_readiness_failure_blocks_gameplay_and_fixture(self):
        session=fixtures.Session();session.state['configuration']={'game_edition':'se','se_new_game_ui':True}
        session.wait_task_queue=Mock(side_effect=runner.Blocked('Normal queue unavailable'))
        with patch('skyrim_autotest.initial_world.InitialWorld'),patch.object(bootstrap,'start_new_game')as start,\
             patch.object(bootstrap,'wait_gameplay_ready')as ready,self.assertRaises(runner.Blocked):
            bootstrap.prepare_gameplay(session,{'cell':'QASmoke'})
        start.assert_called_once();ready.assert_not_called();session.tool.assert_not_called()

    def test_se_requires_native_new_game_even_if_menu_and_world_are_present(self):
        for native_new_game in (False, True):
            with self.subTest(native_new_game=native_new_game):
                session = fixtures.Session()
                session.state['configuration'] = {'game_edition': 'se', 'se_new_game_ui': True}
                events = [dict(seq=11, topic='menu', data=dict(name='Main Menu', opening=False)),
                          dict(seq=12, topic='menu', data=dict(name='Loading Menu', opening=True))]
                if native_new_game: events.append(fixtures.event(13, 'newGame'))
                events.append(dict(seq=13+int(native_new_game), topic='scene.cellLoaded', data=dict(cell='QASmoke')))
                session.state['newGameStarted'] = dict(events=events, saveLoaded=False,
                    consoleBootstrap=False, initialScene=fixtures.SCENE)
                initial = InitialWorld(session, 'new-game')
                with patch.object(runner, 'request', return_value=dict(headSeq=events[-1]['seq'], events=events)):
                    if native_new_game:
                        initial.complete(fixtures.SCENE, fixtures.MENUS)
                        self.assertTrue(initial.record['completed'])
                    else:
                        with self.assertRaisesRegex(ValueError, 'actual unique native newGame'):
                            initial.complete(fixtures.SCENE, fixtures.MENUS)
                        self.assertFalse(initial.record['completed'])


if __name__ == '__main__': unittest.main()
