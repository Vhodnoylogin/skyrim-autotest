"""Meaningful safety checks for delayed fixture startup menus; no game launch."""
import unittest
from unittest.mock import patch
from skyrim_autotest.vr_probe import guard_fixture_modal

class FakeSession:
    def __init__(self,body,buttons):
        self.body=body;self.buttons=buttons;self.open=True;self.accepts=[]
        self.state={}
    def tool(self,name,args):
        if name=='papyrus':
            if args['action']=='describe':
                return {'name':'UI','globalFunctions':[
                    {'name':function,'params':[{'type':t} for t in types]}
                    for function,types in {'GetString':['string','string'],'GetInt':['string','string'],
                                           'GetBool':['string','string']}.items()]}
            function=args['function'];path=args['args'][1]
            if function=='GetString':
                return {'returned': self.body if path.endswith('.Message.text') else
                        'Button0' if path.endswith('._name') else self.buttons[0]}
            if function=='GetInt':return {'returned':len(self.buttons)}
            if function=='GetBool':return {'returned':False}
        if args['action']=='list':return {'messageBoxOpen':self.open}
        if args['action']=='describe':return {'bodyText':self.body,'buttons':self.buttons}
        if args['action']=='accept':
            self.accepts.append(args);self.open=False;return {'queued':True}
        raise AssertionError(args)
    def log(self,*args,**kwargs):pass

class FixtureModalTests(unittest.TestCase):
    def test_native_answer_may_target_one_exact_box_behind_proved_closed_stale_view(self):
        class Stale(FakeSession):
            def tool(self,name,args):
                if name=='papyrus' and args.get('function')=='GetString' and args['args'][1].endswith('.Message.text'):
                    return {'returned':'Speech Broker на связи: old closed box'}
                return super().tool(name,args)
        session=Stale('Speech Broker на связи: new native box',['OK'])
        session.state['lastClosedStartupModal']={'bodyText':'Speech Broker на связи: old closed box','buttons':['OK']}
        before=self.queue(['A'],session.body)
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
             patch('skyrim_autotest.vr_probe.log_modal_queue',return_value=before), \
             patch('skyrim_autotest.vr_probe.time.monotonic',side_effect=[0,4,5,5.1]):
            self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(len(session.accepts),1)
    def test_closed_character_view_needs_all_old_labels_and_one_exact_native_box(self):
        class CharacterView(FakeSession):
            def __init__(self, second):
                super().__init__('Speech Broker на связи: current native', ['OK'])
                self.second = second
                self.state['lastClosedStartupModal'] = {'bodyText':'Finish and name?',
                                                        'buttons':['OK','Cancel']}
            def tool(self, name, args):
                if name=='papyrus' and args.get('action')=='call':
                    path=args['args'][1]; function=args['function']
                    if function=='GetInt': return {'returned':2}
                    if function=='GetString' and path.endswith('.Message.text'):
                        return {'returned':'Finish and name?'}
                    if function=='GetString' and 'Button1.ButtonText' in path:
                        return {'returned':self.second}
                return super().tool(name,args)
        for second, allowed in [('Cancel',True),('Unrelated choice',False)]:
            session=CharacterView(second); before=self.queue(['A'],session.body)
            with self.subTest(second=second), \
                 patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
                 patch('skyrim_autotest.vr_probe.log_modal_queue',return_value=before), \
                 patch('skyrim_autotest.vr_probe.time.monotonic',side_effect=[0,4,5,5.1]):
                if allowed: self.assertTrue(guard_fixture_modal(session))
                else:
                    with self.assertRaisesRegex(AssertionError,'does not match'):
                        guard_fixture_modal(session)
            self.assertEqual(len(session.accepts),1 if allowed else 0)
    def test_delayed_visible_text_is_read_only_until_matching_native_identity(self):
        class Delayed(FakeSession):
            reads=0
            def tool(self,name,args):
                if name=='papyrus' and args.get('function')=='GetString' and args['args'][1].endswith('.Message.text'):
                    self.reads+=1
                    return {'returned':'Previous notice' if self.reads==1 else self.body}
                if name=='menu' and args['action']=='accept':
                    if self.reads<2:raise AssertionError('Premature answer before visible identity')
                return super().tool(name,args)
        session=Delayed('Speech Broker на связи',['OK'])
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'),patch('skyrim_autotest.vr_probe.time.sleep'):
            self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(session.reads,2)
        self.assertEqual(len(session.accepts),1)
    def test_realm_begin_requires_exact_body_button_and_fresh_character_world(self):
        from skyrim_autotest.vr_probe import classify_startup_modal
        modal={'bodyText':'You find yourself someplace unknown... Somewhere outside of time and space.',
               'buttons':['Begin'],'cancelIndex':-1}
        session=FakeSession(modal['bodyText'],modal['buttons'])
        session.state={'newGameStarted':True,'characterCreationCompleted':True}
        with patch.object(session,'tool',return_value={'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}):
            self.assertEqual(classify_startup_modal(session,modal),'realm-new-game-begin')
            session.state['gameplayBootstrap']={'completed':True}
            self.assertIsNone(classify_startup_modal(session,modal))
            session.state.pop('gameplayBootstrap')
            self.assertIsNone(classify_startup_modal(session,{**modal,'buttons':['Continue']}))
        with patch.object(session,'tool',return_value={'playerLoaded':True,'cell':{'editorId':'Other'}}):
            self.assertIsNone(classify_startup_modal(session,modal))
    def queue(self, ids, body='Speech Broker на связи'):
        return {'available':True,'depth':len(ids),
                'queued':[{'id':i,'bodyText':body,'buttons':['OK']} for i in ids]}
    def test_two_identical_notifications_each_answered_once_then_menu_closes(self):
        class Duplicate(FakeSession):
            def tool(self,name,args):
                if name=='menu' and args['action']=='accept':
                    self.accepts.append(args);self.open=len(self.accepts)<2;return {'queued':True}
                return super().tool(name,args)
        session=Duplicate('Speech Broker на связи',['OK'])
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
                patch('skyrim_autotest.vr_probe.log_modal_queue',side_effect=[
                    self.queue(['A','B']),self.queue(['A']),self.queue(['A']),self.queue([])]):
            self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(len(session.accepts),2)
        self.assertFalse(session.open)
    def test_unknown_next_notification_is_collected_without_answer(self):
        class UnknownNext(FakeSession):
            def tool(self,name,args):
                if name=='menu' and args['action']=='accept':
                    self.accepts.append(args);self.body='Unknown choice';return {'queued':True}
                return super().tool(name,args)
        session=UnknownNext('Speech Broker на связи',['OK'])
        before=self.queue(['A'],'Unknown choice');before['queued']+=self.queue(['B'])['queued'];before['depth']=2
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
                patch('skyrim_autotest.vr_probe.log_modal_queue',side_effect=[before,self.queue(['A'],'Unknown choice')]):
            with self.assertRaisesRegex(AssertionError,'unclassified modal'):
                guard_fixture_modal(session)
        self.assertEqual(len(session.accepts),1)
    def test_unchanged_native_identity_does_not_allow_a_second_answer(self):
        class StillOpen(FakeSession):
            def tool(self,name,args):
                if name=='menu' and args['action']=='accept':
                    self.accepts.append(args);return {'queued':True}
                return super().tool(name,args)
        session=StillOpen('Speech Broker на связи',['OK'])
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
                patch('skyrim_autotest.vr_probe.log_modal_queue',return_value=self.queue(['A'])), \
                patch('skyrim_autotest.vr_probe.time.monotonic',side_effect=[0,0,4]), \
                patch('skyrim_autotest.vr_probe.time.sleep'):
            with self.assertRaisesRegex(AssertionError,'did not close'):
                guard_fixture_modal(session)
        self.assertEqual(len(session.accepts),1)
    def test_late_known_message_is_closed_with_exact_body(self):
        session=FakeSession('Speech Broker на связи: fixture startup',['OK'])
        with patch('skyrim_autotest.vr_probe.time.sleep'), patch('skyrim_autotest.vr_probe.ensure_owned_focus'):
            self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(session.accepts,[{'action':'accept','index':0}])
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
    def test_queued_ack_is_not_closure_and_answer_is_not_replayed(self):
        class StillOpen(FakeSession):
            def tool(self,name,args):
                if name=='menu' and args['action']=='accept':
                    self.accepts.append(args);return {'queued':True}
                return super().tool(name,args)
        session=StillOpen('Speech Broker на связи',['OK'])
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'), \
                patch('skyrim_autotest.vr_probe.time.monotonic',side_effect=[0,0,4]), \
                patch('skyrim_autotest.vr_probe.time.sleep'):
            with self.assertRaisesRegex(AssertionError,'did not close'):
                guard_fixture_modal(session)
        self.assertEqual(session.accepts,[{'action':'accept','index':0}])
        self.assertTrue(session.open)

if __name__=='__main__':unittest.main()


class NativeModalRoutingTests(unittest.TestCase):
    def test_known_native_notice_requires_no_os_focus_or_keyboard(self):
        session=FakeSession('Speech Broker на связи',['OK'])
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus',side_effect=AssertionError('OS focus must not be requested')):
            self.assertTrue(guard_fixture_modal(session))
        self.assertEqual(len(session.accepts),1)
