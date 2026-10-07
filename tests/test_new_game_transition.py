import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap


class NewGameTransitionTests(unittest.TestCase):
    def test_actual_alternate_start_cell_not_requested_fixture(self):
        scene={'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}
        self.assertTrue(bootstrap.new_game_transition([{'seq':10}],[{'seq':11}],
            [{'seq':37,'data':{'cell':'RealmLorkhan'}}],scene))

    def test_scene_identity_player_and_event_order_are_required(self):
        scene={'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}
        args=([{'seq':10}],[{'seq':11}],[{'seq':37,'data':{'cell':'RealmLorkhan'}}])
        for bad in ({'playerLoaded':False,'cell':scene['cell']}, {'playerLoaded':1,'cell':scene['cell']},
                    {'playerLoaded':True,'cell':{'editorId':'Other'}}, {'playerLoaded':True,'cell':{'editorId':'VRPlayroom01'}}):
            self.assertFalse(bootstrap.new_game_transition(*args,bad))
        self.assertFalse(bootstrap.new_game_transition([{'seq':12}],args[1],args[2],scene))
        self.assertFalse(bootstrap.new_game_transition([],args[1],args[2],scene))

    def prepare(self, initial_cell):
        class Session:
            def __init__(self): self.state={}; self.calls=[]
            def phase(self,*a):pass
            def save(self):pass
            def log(self,*a,**kw):pass
            def tool(self,tool,args):self.calls.append((tool,args));return {}
        s=Session(); order=[]
        initial={'playerLoaded':True,'cell':{'editorId':initial_cell}}
        final={'playerLoaded':True,'cell':{'editorId':'QASmoke'}}
        def ready(session,cell,new_game):
            order.append(('ready',cell,new_game,len(s.calls)))
            return (initial if cell is None else final),{}
        with patch.object(bootstrap,'prepare_startup_screen'),patch.object(bootstrap,'start_new_game') as start, \
             patch.object(bootstrap,'wait_gameplay_ready',side_effect=ready), \
             patch.object(bootstrap.vr_probe,'guard_fixture_modal',return_value=False), \
             patch.object(bootstrap.vr_probe,'wait_test_cell',return_value=final):
            bootstrap.prepare_gameplay(s,{'cell':'QASmoke','startMode':'new-game'})
            start.assert_called_once_with(s,'QASmoke')
        return s,order

    def test_character_completion_and_initial_ready_precede_one_fixture_transition(self):
        s,order=self.prepare('RealmLorkhan')
        self.assertEqual(order[0],('ready',None,True,0))
        self.assertEqual(s.calls,[('console',{'action':'exec','command':'coc QASmoke'})])
        self.assertEqual(order[1],('ready','QASmoke',False,1))
        self.assertTrue(s.state['gameplayBootstrap']['completed'])

    def test_no_duplicate_coc_when_new_game_already_in_fixture_cell(self):
        s,order=self.prepare('QASmoke')
        self.assertEqual(s.calls,[])
        self.assertEqual(order,[('ready',None,True,0),('ready','QASmoke',False,0)])


if __name__=='__main__':unittest.main()
