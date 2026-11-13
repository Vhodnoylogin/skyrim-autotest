"""The main-menu path must never require VM startup or replay a UI mutation."""
import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import startup_ui, bootstrap, runner


class Session:
    def __init__(self):
        game={'pid':17,'birth':3,'path':'SkyrimSE.exe'}
        self.state={'port':99,'game':game,'seStartupAdmission':{'completed':True,'game':game,'cursor':0}};self.calls=[];self.logs=[]
        self.data={'contract':startup_ui.CONTRACT,'menu':'Main Menu','state':'Main',
                   'entries':[dict(position=0,index=1,text='$NEW',disabled=False)],
                   'selected':dict(index=1,text='$NEW',disabled=False)}
        self.timeout=False;self.timeout_on=None;self.read_ok=True
    def phase(self,*args):pass
    def log(self,name,**kwargs):self.logs.append((name,kwargs))
    def tool(self,name,args,**kwargs):
        self.calls.append((name,copy.deepcopy(args)))
        if name!='gfx':raise AssertionError('VM/unsupported path used')
        if args['op']=='get':
            suffix=args['path'].removeprefix(startup_ui.MOVIE)
            values={'.strCurrentState':self.data['state'],'.MainList.entryList.length':len(self.data['entries']),
                    '.MainList.entryList':self.data['entries'],'.MainList.selectedEntry':self.data['selected']}
            return {'ok':self.read_ok,'truncated':False,'value':copy.deepcopy(values[suffix])}
        if self.timeout or args['op']==self.timeout_on:raise TimeoutError('May have executed; do not replay')
        if args['op']=='set':self.data['selected']=copy.deepcopy(self.data['entries'][args['value']])
        elif args['op']=='call' and args['path'].endswith('.onItemPress'):self.data['state']='MainConfirm'
        return {'ok':True}


def request(port,path,**kwargs):
    if path=='api/health':return {'ok':True,'pid':17,'frame':10}
    if path.startswith('api/events'):return {'headSeq':0,'events':[]}
    raise AssertionError('Unexpected listener request')



class StartupUITests(unittest.TestCase):
    def test_new_game_uses_native_reads_one_select_one_confirm_then_actual_transition_gate(self):
        s=Session()
        with patch.object(runner,'request',side_effect=request),patch.object(runner.native,'alive',return_value=True),patch.object(bootstrap,'wait_new_game_transition')as wait:
            startup_ui.start_new_game(s,'QASmoke')
        self.assertEqual([x[1]['path'].split('.')[-1] for x in s.calls if x[1]['op']=='call'],['onItemPress','onAcceptPress'])
        self.assertEqual(len([x for x in s.calls if x[1]['op']=='set']),1)
        self.assertFalse(any(x[0]=='papyrus'for x in s.calls))
        self.assertEqual(wait.call_args.args[1],'QASmoke')
        self.assertEqual(wait.call_args.args[3],{'ok':True,'pid':17,'frame':10})
        self.assertNotIn('newGameStarted',s.state)

    def test_uncertain_selection_write_is_never_replayed_or_followed_by_invocation(self):
        s=Session();s.timeout=True
        with patch.object(runner,'request',side_effect=request),patch.object(runner.native,'alive',return_value=True),self.assertRaises(TimeoutError):startup_ui.start_new_game(s,'QASmoke')
        mutations=[x[1]['op'] for x in s.calls if x[1]['op']!='get']
        self.assertEqual(mutations,['set'])

    def test_uncertain_selection_invocation_is_never_replayed_or_followed_by_confirmation(self):
        s=Session();s.timeout_on='call'
        with patch.object(runner,'request',side_effect=request),patch.object(runner.native,'alive',return_value=True),self.assertRaises(TimeoutError):
            startup_ui.start_new_game(s,'QASmoke')
        mutations=[(args['op'],args['path'].split('.')[-1]) for _,args in s.calls if args['op']!='get']
        self.assertEqual(mutations,[('set','selectedIndex'),('call','onItemPress')])

    def test_lost_owner_identity_refuses_before_listener_or_movie_access(self):
        s=Session()
        with patch.object(runner,'request') as listener,patch.object(runner.native,'alive',return_value=False),self.assertRaisesRegex(ValueError,'admission is unavailable'):
            startup_ui.start_new_game(s,'QASmoke')
        listener.assert_not_called();self.assertEqual(s.calls,[])

    def test_wrong_gfx_contract_or_typed_list_never_mutates(self):
        for bad_receipt,bad_index in [(True,False),(False,True)]:
            s=Session();s.read_ok=not bad_receipt
            if bad_index:s.data['entries'][0]['index']=True
            with patch.object(runner,'request',side_effect=request),patch.object(runner.native,'alive',return_value=True),self.assertRaises(ValueError):startup_ui.start_new_game(s,'QASmoke')
            self.assertTrue(s.calls);self.assertTrue(all(args['op']=='get' for _,args in s.calls))

    def test_confirmation_for_continue_or_missing_selection_is_refused(self):
        for selected in (None,dict(index=0,text='$CONTINUE',disabled=False)):
            s=Session();s.data['state']='MainConfirm';s.data['selected']=selected
            with self.assertRaises(ValueError):startup_ui.selection(s.data,'MainConfirm',selected=True)


if __name__=='__main__':unittest.main()
