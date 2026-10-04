"""Meaningful safety checks for delayed fixture startup menus; no game launch."""
import unittest
from skyrim_autotest.vr_probe import guard_fixture_modal

class FakeSession:
    def __init__(self,body,buttons):
        self.body=body;self.buttons=buttons;self.open=True;self.accepts=[]
    def tool(self,name,args):
        if args['action']=='list':return {'messageBoxOpen':self.open}
        if args['action']=='describe':return {'bodyText':self.body,'buttons':self.buttons}
        if args['action']=='accept':
            self.accepts.append(args);self.open=False;return {'ok':True}
        raise AssertionError(args)
    def log(self,*args,**kwargs):pass

class FixtureModalTests(unittest.TestCase):
    def test_late_known_message_is_closed_with_exact_body(self):
        session=FakeSession('Speech Broker на связи: fixture startup',['OK'])
        self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(session.accepts,[{'action':'accept','matchBody':session.body}])
        self.assertFalse(guard_fixture_modal(session))
    def test_unknown_or_choice_prompt_is_not_accepted(self):
        for body,buttons in [('Unknown confirmation',['OK']),('Speech Broker на связи',['Yes','No'])]:
            with self.subTest(body=body,buttons=buttons):
                session=FakeSession(body,buttons)
                with self.assertRaisesRegex(AssertionError,'unclassified modal'):guard_fixture_modal(session)
                self.assertEqual(session.accepts,[])

if __name__=='__main__':unittest.main()
