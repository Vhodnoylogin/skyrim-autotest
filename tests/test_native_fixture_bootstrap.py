"""Native transfer remains a common executor stage before fixture/test actions."""
import unittest
from unittest.mock import patch

from skyrim_autotest import bootstrap, fixture_anchor


class NativeFixtureBootstrapTests(unittest.TestCase):
    def test_native_transfer_has_no_console_fallback_and_needs_actual_destination(self):
        realm = {'playerLoaded': True, 'cell': {'editorId': 'RealmLorkhan', 'formId': '0x0701A5C6'}}
        target = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke', 'formId': fixture_anchor.CELL}}
        timeline = []
        class Session:
            def __init__(self):
                self.state = {'configuration': {'game_edition': 'se', 'se_new_game_ui': True,
                    'se_fixture_anchor': fixture_anchor.RECIPE, 'se_fixture_transition': fixture_anchor.TRANSITION_RECIPE},
                    'game': {'pid': 123, 'birth': 456, 'path': 'C:/Game/SkyrimSE.exe'}}
            def save(self): pass
            def phase(self, name, seconds):
                self.state['phase'] = name
                self.state['phaseBudget'] = seconds
            def log(self, *args, **kwargs): pass
            def wait_task_queue(self): pass
            def tool(self, tool, args, **kwargs): raise AssertionError('Unexpected direct tool/fallback: ' + tool)
        session = Session()
        def transfer(s, deadline, read):
            timeline.append('native-transfer')
            self.assertEqual(read(), ['newGame'])
            s.state['fixtureTransition'] = {'recipe': fixture_anchor.TRANSITION_RECIPE, 'status': 'returned',
                'nativeCallbackReturned': True, 'game': dict(s.state['game'])}
        def destination(*args):
            self.assertEqual(session.state['phase'], 'gameplay-native-fixture-destination')
            self.assertGreater(session.state['phaseBudget'], 90)
            timeline.append('actual-destination')
            return target
        with patch('skyrim_autotest.initial_world.InitialWorld') as initial, \
             patch.object(bootstrap, 'start_new_game'), \
             patch.object(bootstrap, 'wait_gameplay_ready', side_effect=[(realm, {}), (target, {}), (target, {})]), \
             patch.object(bootstrap.vr_probe, 'guard_fixture_modal', return_value=False), \
             patch.object(bootstrap.vr_probe, 'wait_test_cell', side_effect=destination), \
             patch.object(fixture_anchor, 'transition_to_anchor', side_effect=transfer), \
             patch.object(fixture_anchor, 'prepare_anchor', return_value={'status': 'prepared'}):
            initial.return_value.read.return_value = ['newGame']
            bootstrap.prepare_gameplay(session, {'cell': 'QASmoke', 'startMode': 'new-game'})
        self.assertEqual(timeline, ['native-transfer', 'actual-destination'])
        self.assertTrue(session.state['fixtureTransition']['cellReadinessVerified'])
        self.assertEqual(session.state['fixtureTransition']['status'], 'arrived')
        self.assertTrue(session.state['gameplayBootstrap']['completed'])
