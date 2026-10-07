import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap


class Clock:
    now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class Session:
    def __init__(self, menus=None, scene=None):
        self.calls = []
        self.menus = menus or dict(messageBoxOpen=False, openMenus=['WSActivateRollover'],
                                  menuStates=[dict(name='WSActivateRollover', available=True,
                                                   alwaysOpen=False, pausesGame=False, modal=False,
                                                   usesCursor=False, usesMenuContext=False,
                                                   freezeFramePause=False)])
        self.scene = scene or dict(playerLoaded=True, cell=dict(editorId='QASmoke'))
    def tool(self, tool, args):
        self.calls.append((tool, args))
        return copy.deepcopy(self.menus if tool == 'menu' else self.scene)
    def log(self, *args, **kwargs): pass


class ReadinessTests(unittest.TestCase):
    def run_ready(self, session, clock, deadline=12):
        with patch.object(bootstrap.time, 'monotonic', clock.monotonic), \
             patch.object(bootstrap.time, 'sleep', clock.sleep):
            return bootstrap.wait_gameplay_ready(session, 'QASmoke', False, deadline=deadline)

    def test_native_nonblocking_overlay_allows_eight_second_stable_world(self):
        session, clock = Session(), Clock()
        self.run_ready(session, clock)
        self.assertEqual(clock.now, 8)
        self.assertTrue(all(a.get('includeFlags') is True for t,a in session.calls if t == 'menu'))

    def test_native_blocking_flags_and_unknown_flags_reject_readiness(self):
        for flag in ('pausesGame', 'modal', 'usesCursor', 'usesMenuContext', 'freezeFramePause', 'unknown'):
            with self.subTest(flag=flag):
                session = Session()
                if flag == 'unknown': del session.menus['menuStates'][0]['modal']
                else: session.menus['menuStates'][0][flag] = True
                with self.assertRaisesRegex(AssertionError, 'not ready'):
                    self.run_ready(session, Clock())

    def test_loaded_player_and_actual_nonempty_requested_cell_are_required(self):
        for scene in (dict(playerLoaded=1, cell=dict(editorId='QASmoke')),
                      dict(playerLoaded=True, cell={}),
                      dict(playerLoaded=True, cell=dict(editorId='VRPlayroom01')),
                      dict(playerLoaded=True, cell=dict(editorId='OtherCell'))):
            with self.subTest(scene=scene), self.assertRaisesRegex(AssertionError, 'not ready'):
                self.run_ready(Session(scene=scene), Clock())

    def test_late_native_pause_resets_stable_interval(self):
        session, clock = Session(), Clock()
        original = session.tool
        def tool(name, args):
            result = original(name, args)
            if name == 'menu': result['menuStates'][0]['pausesGame'] = 3 <= clock.now < 4
            return result
        session.tool = tool
        self.run_ready(session, clock, deadline=15)
        self.assertEqual(clock.now, 12)
