import unittest
from skyrim_autotest.readiness_state import world_loaded, gameplay_ready, menus_block_gameplay


class ReadinessTests(unittest.TestCase):
    def test_typed_cell_and_exact_expected_world(self):
        for cell in (None, '', False, 123, [], 'VRPlayroom01', 'wrong cell'):
            with self.subTest(cell=cell):
                self.assertFalse(world_loaded({'playerLoaded':True,'cell':{'editorId':cell}}))
        scene={'playerLoaded':True,'cell':{'editorId':'QASmoke'}}
        self.assertTrue(world_loaded(scene,'QASmoke'));self.assertFalse(world_loaded(scene,'Other'))
        self.assertFalse(world_loaded({'playerLoaded':1,'cell':{'editorId':'QASmoke'}}))

    def test_malformed_menu_records_are_unavailable_without_exception(self):
        good={'messageBoxOpen':False,'openMenus':[],'menuStates':[]}
        self.assertTrue(gameplay_ready({'playerLoaded':True,'cell':{'editorId':'QASmoke'}},good))
        for value in (None,{},dict(good,messageBoxOpen=0),dict(good,openMenus=[[]]),
                      dict(good,openMenus=['HUD'],menuStates=[{'name':[]}]),
                      dict(good,openMenus=['HUD','HUD'],menuStates=[{'name':'HUD'},{'name':'HUD'}])):
            with self.subTest(value=value):self.assertTrue(menus_block_gameplay(value))

    def test_real_modal_blocks_and_nonblocking_overlay_does_not(self):
        row=dict(name='Overlay',available=True,alwaysOpen=True,pausesGame=False,
                 modal=False,usesCursor=False,usesMenuContext=False,freezeFramePause=False)
        menus=dict(messageBoxOpen=False,openMenus=['Overlay'],menuStates=[row])
        self.assertFalse(menus_block_gameplay(menus))
        row['modal']=True;self.assertTrue(menus_block_gameplay(menus))
