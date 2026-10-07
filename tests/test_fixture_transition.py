"""Save lifecycle cannot authorize an overlapping or redundant cell transition."""
import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap, runner


class FixtureTransitionTests(unittest.TestCase):
    def test_loaded_fixture_stabilizes_before_optional_single_cell_transition(self):
        for loaded_cell in ('QASmoke', 'OtherCell'):
            with self.subTest(loaded_cell=loaded_cell):
                timeline = []
                class Session:
                    state = {'port': 1}
                    def phase(self, *args): pass
                    def log(self, *args, **kwargs): pass
                    def save(self): pass
                    def tool(self, name, args, **kwargs):
                        timeline.append((name, args))
                        return {'cell': {'editorId': 'VRPlayroom01'}, 'frame': 100}
                ready_scene = {'playerLoaded': True, 'cell': {'editorId': 'QASmoke'}}
                def ready(session, cell, new_game):
                    timeline.append(('stable', cell))
                    return ({'playerLoaded': True, 'cell': {'editorId': loaded_cell}}
                            if cell is None else ready_scene), {'openMenus': ['HUD Menu']}
                with patch.object(bootstrap, 'advance_calibration', return_value=True), \
                     patch.object(bootstrap, 'wait_gameplay_ready', side_effect=ready), \
                     patch.object(bootstrap.vr_probe, 'guard_fixture_modal', return_value=False), \
                     patch.object(bootstrap.vr_probe, 'wait_test_cell', return_value=ready_scene), \
                     patch.object(runner, 'request', return_value={'events': [
                         {'topic': 'lifecycle', 'event': 'postLoadGame', 'frame': 101}]}):
                    session = Session()
                    session.state = {'port': 1}
                    bootstrap.prepare_gameplay(session, {'cell': 'QASmoke', 'fixture': {'saveStem': 'pinned'}})
                transitions = [row for row in timeline if row[0] == 'console']
                self.assertEqual(len(transitions), 0 if loaded_cell == 'QASmoke' else 1)
                self.assertEqual(len([row for row in timeline if row[0] == 'game']), 1)
                if transitions:
                    self.assertLess(timeline.index(('stable', None)), timeline.index(transitions[0]))
                self.assertTrue(session.state['gameplayBootstrap']['completed'])


if __name__ == '__main__': unittest.main()
