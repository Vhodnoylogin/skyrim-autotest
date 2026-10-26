"""The main-menu path must never require VM startup or replay a UI mutation."""
import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import startup_ui, bootstrap, runner


class Session:
    def __init__(self):
        self.state={'port':99};self.calls=[];self.logs=[]
        self.data={'contract':startup_ui.CONTRACT,'menu':'Main Menu','state':'Main',
                   'entries':[dict(position=0,index=1,text='$NEW',disabled=False)],
                   'selected':dict(index=1,text='$NEW',disabled=False)}
        self.timeout=False
    def phase(self,*args):pass
    def log(self,name,**kwargs):self.logs.append((name,kwargs))
    def tool(self,name,args):
        self.calls.append((name,args))
        if name=='inspect':return {'frame':10}
        if name!='menu' or args.get('action')!='startup':raise AssertionError('VM/unsupported path used')
        op=args['startupOperation']
        if op=='snapshot':return copy.deepcopy(self.data)
        if self.timeout:raise TimeoutError('May have executed; do not replay')
        if op=='select-new':self.data['state']='MainConfirm'
        return {'contract':startup_ui.CONTRACT,'operation':op,'completed':True}


class StartupUITests(unittest.TestCase):
    def test_new_game_uses_native_reads_one_select_one_confirm_then_actual_transition_gate(self):
        s=Session()
        with patch.object(runner,'request',return_value={'events':[]}),patch.object(bootstrap,'wait_new_game_transition')as wait:
            startup_ui.start_new_game(s,'QASmoke')
        self.assertEqual([x[1]['startupOperation']for x in s.calls if x[0]=='menu'and x[1]['startupOperation']!='snapshot'],
                         ['select-new','confirm-new'])
        self.assertFalse(any(x[0]=='papyrus'for x in s.calls))
        self.assertEqual(wait.call_args.args[1],'QASmoke')
        self.assertEqual(wait.call_args.args[3],{'frame':10})
        self.assertNotIn('newGameStarted',s.state)

    def test_uncertain_selection_invocation_is_never_replayed_or_followed_by_confirmation(self):
        s=Session();s.timeout=True
        with self.assertRaises(TimeoutError):startup_ui.start_new_game(s,'QASmoke')
        mutations=[x[1]['startupOperation']for x in s.calls if x[0]=='menu'and x[1]['startupOperation']!='snapshot']
        self.assertEqual(mutations,['select-new'])

    def test_wrong_native_contract_or_typed_list_never_mutates(self):
        for field,value in [('contract','other'),('entries',[dict(position=0,index=True,text='$NEW',disabled=False)])]:
            s=Session();s.data[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):startup_ui.start_new_game(s,'QASmoke')
            self.assertEqual([x[1]['startupOperation']for x in s.calls],['snapshot'])

    def test_confirmation_for_continue_or_missing_selection_is_refused(self):
        for selected in (None,dict(index=0,text='$CONTINUE',disabled=False)):
            s=Session();s.data['state']='MainConfirm';s.data['selected']=selected
            with self.assertRaises(ValueError):startup_ui.selection(s.data,'MainConfirm',selected=True)


if __name__=='__main__':unittest.main()
