"""The main-menu path must never require VM startup or replay a UI mutation."""
import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import startup_ui, bootstrap, runner


class Session:
    def __init__(self):
        game={'pid':12,'birth':34,'path':'SkyrimSE.exe'}
        self.state={'port':99,'game':game,'seStartupAdmission':{'completed':True,'game':dict(game),'cursor':9}}
        self.calls=[];self.logs=[]
        self.data={'contract':startup_ui.CONTRACT,'menu':'Main Menu','state':'Main',
                   'entries':[dict(position=0,index=1,text='$NEW',disabled=False)],
                   'selected':dict(index=1,text='$NEW',disabled=False)}
        self.timeout=False
    def phase(self,*args):pass
    def log(self,name,**kwargs):self.logs.append((name,kwargs))
    def tool(self,name,args):
        self.calls.append((name,args))
        if name!='menu' or args.get('action')!='startup':raise AssertionError('VM/unsupported path used')
        op=args['startupOperation']
        if op=='snapshot':return copy.deepcopy(self.data)
        if self.timeout:raise TimeoutError('May have executed; do not replay')
        if op=='select-new':self.data['state']='MainConfirm'
        return {'contract':startup_ui.CONTRACT,'operation':op,'completed':True}


class StartupUITests(unittest.TestCase):
    @staticmethod
    def listener(port,route,**kwargs):
        return {'ok':True,'pid':12,'frame':10} if route=='api/health' else {'events':[],'headSeq':9}

    def test_new_game_uses_native_reads_one_select_one_confirm_then_actual_transition_gate(self):
        s=Session()
        with patch.object(runner,'request',side_effect=self.listener),patch.object(runner.native,'alive',return_value=True),patch.object(bootstrap,'wait_new_game_transition')as wait:
            startup_ui.start_new_game(s,'QASmoke')
        self.assertEqual([x[1]['startupOperation']for x in s.calls if x[0]=='menu'and x[1]['startupOperation']!='snapshot'],
                         ['select-new','confirm-new'])
        self.assertFalse(any(x[0]=='papyrus'for x in s.calls))
        self.assertEqual(wait.call_args.args[1],'QASmoke')
        self.assertEqual(wait.call_args.args[3],{'ok':True,'pid':12,'frame':10})
        self.assertEqual(wait.call_args.args[4],9)
        self.assertTrue(all(name=='menu' for name,args in s.calls))
        self.assertNotIn('newGameStarted',s.state)

    def test_uncertain_selection_invocation_is_never_replayed_or_followed_by_confirmation(self):
        s=Session();s.timeout=True
        with patch.object(runner,'request',side_effect=self.listener),patch.object(runner.native,'alive',return_value=True),self.assertRaises(TimeoutError):startup_ui.start_new_game(s,'QASmoke')
        mutations=[x[1]['startupOperation']for x in s.calls if x[0]=='menu'and x[1]['startupOperation']!='snapshot']
        self.assertEqual(mutations,['select-new'])

    def test_wrong_native_contract_or_typed_list_never_mutates(self):
        for field,value in [('contract','other'),('entries',[dict(position=0,index=True,text='$NEW',disabled=False)])]:
            s=Session();s.data[field]=value
            with patch.object(runner,'request',side_effect=self.listener),patch.object(runner.native,'alive',return_value=True),self.subTest(field=field),self.assertRaises(ValueError):startup_ui.start_new_game(s,'QASmoke')
            self.assertEqual([x[1]['startupOperation']for x in s.calls],['snapshot'])

    def test_confirmation_for_continue_or_missing_selection_is_refused(self):
        for selected in (None,dict(index=0,text='$CONTINUE',disabled=False)):
            s=Session();s.data['state']='MainConfirm';s.data['selected']=selected
            with self.assertRaises(ValueError):startup_ui.selection(s.data,'MainConfirm',selected=True)

    def test_fresh_listener_wrong_pid_gap_or_closed_menu_never_selects(self):
        replies=[{'ok':True,'pid':99,'frame':10},
            {'events':[{'seq':11,'topic':'menu','data':{'name':'Other','opening':True}}],'headSeq':11},
            {'events':[{'seq':10,'topic':'menu','data':{'name':'Main Menu','opening':False}}],'headSeq':10}]
        for bad in replies:
            s=Session()
            def reply(port,route,**kwargs):
                if ('pid'in bad)==(route=='api/health'):return bad
                return self.listener(port,route,**kwargs)
            with patch.object(runner,'request',side_effect=reply),patch.object(runner.native,'alive',return_value=True),self.assertRaises(ValueError):
                startup_ui.start_new_game(s,'QASmoke')
            self.assertFalse(s.calls)

    def test_world_transition_after_selection_blocks_confirmation_without_replay(self):
        s=Session();reads=0
        def reply(port,route,**kwargs):
            nonlocal reads
            if route.startswith('api/events'):
                reads+=1
                if reads==2:return {'events':[{'seq':10,'topic':'lifecycle','data':{'event':'newGame'}}],'headSeq':10}
            return self.listener(port,route,**kwargs)
        with patch.object(runner,'request',side_effect=reply),patch.object(runner.native,'alive',return_value=True),self.assertRaisesRegex(ValueError,'Unexpected world transition'):
            startup_ui.start_new_game(s,'QASmoke')
        self.assertEqual([args['startupOperation']for name,args in s.calls if args['startupOperation']!='snapshot'],['select-new'])

    def test_listener_newer_head_is_drained_without_ordinary_tasks(self):
        s=Session();events=iter([{'events':[],'headSeq':10},
            {'events':[{'seq':10,'topic':'menu','data':{'name':'Cursor Menu','opening':True}}],'headSeq':10}])
        def reply(port,route,**kwargs):
            return next(events) if route.startswith('api/events') else self.listener(port,route,**kwargs)
        with patch.object(runner,'request',side_effect=reply),patch.object(runner.native,'alive',return_value=True):
            before,cursor=startup_ui.listener_baseline(s,9)
        self.assertEqual(cursor,10);self.assertEqual(before['frame'],10);self.assertFalse(s.calls)


if __name__=='__main__':unittest.main()
