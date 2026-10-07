"""Initial native world continuity must work without spawning a probe or reloading."""
import time
import unittest
from unittest.mock import Mock, patch

from skyrim_autotest import bootstrap, platform, runner
from skyrim_autotest.initial_world import InitialWorld


SCENE = dict(playerLoaded=True, cell=dict(editorId='QASmoke'))
MENUS = dict(messageBoxOpen=False, openMenus=[], menuStates=[])


def event(seq, name):
    return dict(seq=seq, topic='lifecycle', data=dict(event=name))


class Session:
    def __init__(self):
        self.state = dict(game=dict(pid=17, birth=3, path='SkyrimVR.exe'), port=1,
                          scenario=dict(cell='QASmoke'), probeObjectLive=False)
        self.save = Mock()
        self.log = Mock()
        self.phase = Mock()
        self.capture_probe_cursor = Mock(return_value=10)
        self.tool = Mock(return_value={})


class InitialWorldTests(unittest.TestCase):
    def test_actual_fixture_bootstrap_then_guard_without_probe_save_or_second_load(self):
        s = Session()
        calls = []
        def native_request(port, path, **kwargs):
            calls.append(path)
            if len(calls) == 1:
                return dict(headSeq=12, events=[event(11, 'preLoadGame'), event(12, 'postLoadGame')])
            return dict(headSeq=12, events=[])
        with patch.object(bootstrap, 'prepare_startup_screen'), \
             patch.object(bootstrap, 'wait_gameplay_ready', return_value=(SCENE, MENUS)), \
             patch.object(bootstrap.vr_probe, 'guard_fixture_modal', return_value=False), \
             patch.object(bootstrap.vr_probe, 'wait_test_cell', return_value=SCENE), \
             patch.object(runner, 'request', side_effect=native_request):
            bootstrap.prepare_gameplay(s, dict(cell='QASmoke', fixture=dict(saveStem='pinned')))
            platform.Backend(s, time.monotonic()+10).guard_world()
        self.assertEqual(s.state['ownedWorldGeneration'], 1)
        self.assertTrue(s.state['initialWorldTransition']['completed'])
        self.assertFalse(s.state['probeObjectLive'])
        self.assertNotIn('ownedLoadTransition', s.state)
        self.assertEqual(s.state['initialWorldTransition']['events'],
                         [event(11, 'preLoadGame'), event(12, 'postLoadGame')])
        s.tool.assert_called_once_with('game', dict(action='load', name='pinned'))
        self.assertTrue(any(c.kwargs.get('transition', {}).get('completed')
                            for c in s.log.call_args_list if c.args == ('initial-world-completed',)))

    def prepared(self):
        s = Session()
        w = InitialWorld(s, 'fixture')
        with patch.object(runner, 'request', return_value=dict(headSeq=12, events=[
                event(11, 'preLoadGame'), event(12, 'postLoadGame')])):
            w.complete(SCENE, MENUS)
        s.state['gameplayBootstrap'] = dict(completed=True)
        return s, w

    def test_late_load_gap_reset_or_incomplete_transition_cannot_be_accepted(self):
        replies = [dict(headSeq=11, events=[event(11, 'postLoadGame')]),
                   dict(headSeq=13, events=[event(13, 'preLoadGame')]),
                   dict(headSeq=9, events=[]),
                   dict(headSeq=11, events=[event(11, 'preLoadGame')]),
                   dict(headSeq=14, events=[event(11, 'preLoadGame'), event(12, 'postLoadGame'),
                                          event(13, 'preLoadGame'), event(14, 'postLoadGame')])]
        for reply in replies:
            with self.subTest(reply=reply):
                s = Session(); w = InitialWorld(s, 'fixture')
                with patch.object(runner, 'request', return_value=reply), self.assertRaises(ValueError):
                    w.complete(SCENE, MENUS)
                self.assertFalse(s.state['initialWorldTransition']['completed'])
                self.assertNotIn('ownedWorldGeneration', s.state)

    def test_later_event_invalidates_initial_guard_permanently(self):
        s, w = self.prepared()
        b = platform.Backend(s, time.monotonic()+10)
        with patch.object(runner, 'request', return_value=dict(headSeq=13, events=[event(13, 'preLoadGame')])), \
             self.assertRaisesRegex(ValueError, 'Later world'):
            b.guard_world()
        self.assertTrue(w.record['worldInvalidated'])
        with patch.object(runner, 'request') as request, self.assertRaises(ValueError):
            b.guard_world()
        request.assert_not_called()

    def test_incomplete_later_owned_load_never_falls_back_to_valid_initial_world(self):
        s, _ = self.prepared()
        s.state['ownedLoadTransition'] = dict(completed=False)
        with patch.object(runner, 'request') as request, self.assertRaises(ValueError):
            platform.Backend(s, time.monotonic()+10).guard_world()
        request.assert_not_called()

    def test_exact_process_epoch_and_native_readiness_are_required(self):
        for change in (lambda s:s.state['game'].update(birth=4),
                       lambda s:s.state.update(ownedWorldGeneration=2),
                       lambda s:s.state['gameplayBootstrap'].update(completed=False)):
            s, _ = self.prepared(); change(s)
            with patch.object(runner, 'request') as request, self.assertRaises(ValueError):
                platform.Backend(s, time.monotonic()+10).guard_world()
            request.assert_not_called()
        s = Session(); w = InitialWorld(s, 'fixture')
        with patch.object(runner, 'request', return_value=dict(headSeq=12, events=[
                event(11, 'preLoadGame'), event(12, 'postLoadGame')])), self.assertRaises(ValueError):
            w.complete(SCENE, dict(messageBoxOpen=True, openMenus=[], menuStates=[]))
        self.assertNotIn('ownedWorldGeneration', s.state)

    def test_cell_and_new_game_require_their_actual_native_transition_proofs(self):
        s = Session(); w = InitialWorld(s, 'cell')
        with patch.object(runner, 'request', return_value=dict(headSeq=10, events=[])), self.assertRaises(ValueError):
            w.complete(SCENE, MENUS)
        with patch.object(runner, 'request', return_value=dict(headSeq=11, events=[
                dict(seq=11, topic='scene.cellLoaded', data=dict(cell='QASmoke'))])):
            w.complete(SCENE, MENUS)
        self.assertEqual(s.state['ownedWorldGeneration'], 1)
        s = Session(); w = InitialWorld(s, 'new-game')
        with patch.object(runner, 'request', return_value=dict(headSeq=10, events=[])), self.assertRaises(ValueError):
            w.complete(SCENE, MENUS)

    def test_new_game_accepts_only_the_same_contiguous_native_menu_cell_proof(self):
        s = Session(); w = InitialWorld(s, 'new-game')
        fresh = [dict(seq=11, topic='menu', data=dict(name='Main Menu', opening=False)),
                 dict(seq=12, topic='menu', data=dict(name='Loading Menu', opening=True)),
                 dict(seq=13, topic='scene.cellLoaded', data=dict(cell='QASmoke'))]
        s.state['newGameStarted'] = dict(saveLoaded=False, consoleBootstrap=False,
                                         events=fresh, initialScene=SCENE)
        with patch.object(runner, 'request', return_value=dict(headSeq=13, events=fresh)):
            w.complete(SCENE, MENUS)
        with self.assertRaisesRegex(ValueError, 'no replay'):
            w.complete(SCENE, MENUS)
        with self.assertRaisesRegex(ValueError, 'no replay'):
            InitialWorld(s, 'new-game')


if __name__ == '__main__': unittest.main()
