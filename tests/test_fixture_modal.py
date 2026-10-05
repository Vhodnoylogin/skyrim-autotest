"""Meaningful safety checks for delayed fixture startup menus; no game launch."""
import unittest
from skyrim_autotest.vr_probe import guard_fixture_modal

class FakeSession:
    def __init__(self,body,buttons):
        self.body=body;self.buttons=buttons;self.open=True;self.accepts=[]
    def tool(self,name,args):
        if name=='papyrus':
            if args['action']=='describe':
                return {'name':'UI','globalFunctions':[
                    {'name':function,'params':[{'type':t} for t in types]}
                    for function,types in {'GetString':['string','string'],'GetInt':['string','string'],
                                           'GetBool':['string','string'],'InvokeInt':['string','string','int']}.items()]}
            function=args['function'];path=args['args'][1]
            if function=='GetString':return {'returned':self.body if path.endswith('.Message.text') else self.buttons[0]}
            if function=='GetInt':return {'returned':len(self.buttons)}
            if function=='GetBool':return {'returned':False}
            if function=='InvokeInt':self.accepts.append(args);self.open=False;return {'returned':None}
        if args['action']=='list':return {'messageBoxOpen':self.open}
        if args['action']=='describe':return {'bodyText':self.body,'buttons':self.buttons}
        raise AssertionError(args)
    def log(self,*args,**kwargs):pass

class FixtureModalTests(unittest.TestCase):
    def test_late_known_message_is_closed_with_exact_body(self):
        session=FakeSession('Speech Broker на связи: fixture startup',['OK'])
        self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(session.accepts,[{'action':'call','script':'UI','function':'InvokeInt',
                                         'args':['MessageBoxMenu','_root.MessageMenu.MessageButtons.0.handleMousePress',0]}])
        self.assertFalse(guard_fixture_modal(session))
    def test_unknown_or_choice_prompt_is_not_accepted(self):
        for body,buttons in [('Unknown confirmation',['OK']),('Speech Broker на связи',['Yes','No'])]:
            with self.subTest(body=body,buttons=buttons):
                session=FakeSession(body,buttons)
                with self.assertRaisesRegex(AssertionError,'unclassified modal'):guard_fixture_modal(session)
                self.assertEqual(session.accepts,[])
    def test_changed_visible_body_cannot_answer_a_different_window(self):
        class Changed(FakeSession):
            def tool(self,name,args):
                if name=='papyrus' and args.get('function')=='GetString' and args['args'][1].endswith('.Message.text'):
                    return {'returned':'Different dialog'}
                return super().tool(name,args)
        session=Changed('Speech Broker на связи',['OK'])
        with self.assertRaisesRegex(AssertionError,'does not match'):
            guard_fixture_modal(session)
        self.assertEqual(session.accepts,[])

if __name__=='__main__':unittest.main()
