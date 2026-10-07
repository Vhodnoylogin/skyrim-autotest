import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap

class Clock:
    now = 0
    def monotonic(self): return self.now
    def sleep(self, value): self.now += value

class CharacterSession:
    def __init__(self, bad=False, stale=False, stock_confirmation=False, hidden=False):
        self.state = {}; self.calls = []; self.stage = 'character'; self.name = ''
        self.bad = bad; self.stale = stale
        self.stock_confirmation = stock_confirmation
        self.hidden = hidden
    def log(self, *args, **kwargs): pass
    def tool(self, tool, args):
        self.calls.append((tool, args))
        if tool == 'menu':
            if args['action'] == 'list':
                return {'openMenus': ['RaceSex Menu'] if self.stage != 'closed' else ['HUD Menu'],
                        'messageBoxOpen': self.stage == 'confirm'}
            if args['action'] == 'describe':
                return {'bodyText': 'Different choice' if self.bad else 'Finish?',
                        'buttons': ['OK', 'Cancel'] if self.stock_confirmation else ['Yes', 'No'],
                        'cancelIndex': -1 if self.stock_confirmation else 1}
            if args['action'] == 'accept': self.stage = 'name'; return {}
        if tool == 'papyrus':
            if args['action'] == 'describe': return {}
            function = args['function']; path = args['args'][0 if args['script']=='Game' else 1]
            if args['script'] == 'Game':
                return {'returned': {'sYes':'Yes', 'sNo':'No', 'sRSMConfirm':'Finish?',
                                     'sRSMFinishedWarning':'Other known warning',
                                     'sOK':'OK','sCancel':'Cancel'}[path]}
            if function == 'GetString':
                value = ('bottomBar' if path.endswith('.bottomBar._name') else
                         'textEntry' if path.endswith('.textEntry._name') else
                         'TextInputInstance' if path.endswith('.TextInputInstance._name') else
                         self.name if path.endswith('.text') else '')
                return {'returned': value}
            if function == 'GetBool': return {'returned': self.stage == 'name' and not self.hidden}
            if function == 'InvokeBool': self.hidden = False
            if function == 'SetString':
                if not self.stale: self.name = args['args'][2]
            if function == 'InvokeInt':
                if path.endswith('onDoneClicked'): self.stage = 'confirm'
                elif path.endswith('onAccept'): self.stage = 'closed'
            return {'returned': None}
        raise AssertionError((tool,args))

class CharacterTests(unittest.TestCase):
    def invoke(self, session):
        clock=Clock()
        with patch('skyrim_autotest.api_contract.validate_description'), \
             patch.object(bootstrap.vr_probe,'ensure_owned_focus', side_effect=AssertionError('Native UI must not require foreground')), \
             patch.object(bootstrap.time,'monotonic',clock.monotonic), \
             patch.object(bootstrap.time,'sleep',clock.sleep):
            bootstrap.complete_character_creation(session)
    def test_known_confirmation_name_readback_and_menu_close(self):
        session=CharacterSession(); self.invoke(session)
        self.assertTrue(session.state['characterCreationCompleted'])
        self.assertEqual(session.name,'Autotest')
        self.assertEqual(sum(a.get('action')=='accept' for t,a in session.calls if t=='menu'),1)
    def test_unknown_confirmation_is_never_answered(self):
        session=CharacterSession(bad=True)
        with self.assertRaisesRegex(AssertionError,'Unclassified'): self.invoke(session)
        self.assertFalse(any(a['action']=='accept' for t,a in session.calls if t=='menu'))
    def test_actual_ok_cancel_confirmation_uses_exact_live_labels(self):
        session=CharacterSession(stock_confirmation=True); self.invoke(session)
        self.assertTrue(session.state['characterCreationCompleted'])
    def test_hidden_vr_keyboard_uses_identified_frontend_once_after_confirmation(self):
        session=CharacterSession(stock_confirmation=True,hidden=True); self.invoke(session)
        self.assertTrue(session.state['characterCreationCompleted'])
        frontend=[a for t,a in session.calls if a.get('function')=='InvokeBool']
        self.assertEqual(len(frontend),1)
        self.assertTrue(frontend[0]['args'][1].endswith('ShowTextEntry'))
    def test_failed_name_write_is_not_accepted(self):
        session=CharacterSession(stale=True)
        with self.assertRaisesRegex(AssertionError,'write not confirmed'): self.invoke(session)
        self.assertFalse(any(a.get('function')=='InvokeInt' and a['args'][1].endswith('onAccept')
                             for t,a in session.calls if t=='papyrus'))
    def test_late_character_menu_resets_stability_before_readiness(self):
        clock=Clock(); session=CharacterSession(); session.stage='closed'; session.logs=[]
        original=session.tool
        def tool(name,args, **kwargs):
            if name=='inspect': return {'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}
            if name=='menu' and args['action']=='list':
                names=['RaceSex Menu'] if 1<=clock.now<2 else ['HUD Menu']
                return {'openMenus':names, 'messageBoxOpen':False,
                        'menuStates':[dict(name=n,available=True,alwaysOpen=True,pausesGame=False,
                                           modal=False,usesCursor=False,usesMenuContext=False,
                                           freezeFramePause=False) for n in names]}
            return original(name,args)
        session.tool=tool
        with patch.object(bootstrap.time,'monotonic',clock.monotonic), \
             patch.object(bootstrap.time,'sleep',clock.sleep), \
             patch.object(bootstrap,'complete_character_creation',side_effect=lambda s:clock.sleep(2)) as finish:
            bootstrap.wait_gameplay_ready(session,'RealmLorkhan',True)
        finish.assert_called_once()
        self.assertIs(finish.call_args.args[0].session,session)
        self.assertGreaterEqual(clock.now,11)
