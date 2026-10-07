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

    def navigation(self, name='InventoryMenu'):
        session = Session()
        session.menus['openMenus'] = [name]
        session.menus['menuStates'][0].update(name=name,pausesGame=True)
        return session

    def test_known_navigation_is_closed_once_then_world_stable_verified(self):
        session, clock = self.navigation(), Clock()
        original=session.tool
        def tool(name,args):
            result=original(name,args)
            if name=='menu' and args['action']=='close':
                session.menus.update(openMenus=[],menuStates=[])
                return dict(queued=True)
            return result
        session.tool=tool
        self.run_ready(session,clock)
        self.assertEqual(sum(a.get('action')=='close' for t,a in session.calls),1)
        self.assertEqual(clock.now,8)

    def test_menu_close_ack_without_closure_never_replayed_or_ready(self):
        session=self.navigation()
        with self.assertRaisesRegex(AssertionError,'did not close'):
            self.run_ready(session,Clock())
        self.assertEqual(sum(a.get('action')=='close' for t,a in session.calls),1)

    def test_unknown_choice_is_not_hidden_and_loading_world_has_no_navigation_mutation(self):
        for name, scene in (('UnknownChoice',dict(playerLoaded=True,cell=dict(editorId='QASmoke'))),
                            ('InventoryMenu',dict(playerLoaded=False,cell=dict(editorId='QASmoke')))):
            session=self.navigation(name);session.scene=scene
            with self.subTest(name=name),self.assertRaisesRegex(AssertionError,'not ready'):
                self.run_ready(session,Clock())
            self.assertFalse(any(a.get('action')=='close' for t,a in session.calls))
