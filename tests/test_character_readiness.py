"""Native name requests must not stand in for actual menu completion."""
import unittest
from unittest.mock import patch
from skyrim_autotest import bootstrap

class Clock:
    now = 0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds

class CharacterSession:
    def __init__(self, closes=False, array_type='string[]'):
        self.state = {}; self.closed = False; self.closes = closes
        self.array_type = array_type; self.confirmed = False
        self.dialog = False; self.name = ''; self.delegates = []
    def log(self, *args, **kwargs): pass
    def tool(self, tool, args):
        if tool == 'menu':
            action = args['action']
            if action == 'list':
                return {'messageBoxOpen':self.dialog,
                        'openMenus':['HUD Menu'] + ([] if self.closed else ['RaceSex Menu'])}
            if action == 'describe':
                return {'bodyText':'Finish and name?', 'buttons':['OK','Cancel'], 'cancelIndex':-1}
            if action == 'accept': self.dialog=False; self.confirmed=True; return {}
        if tool != 'papyrus': raise AssertionError(tool)
        if args['action'] == 'describe':
            types = ({'GetGameSettingString':['string']} if args['script']=='Game' else
                     {'GetString':['string','string'], 'GetBool':['string','string'],
                      'GetInt':['string','string'], 'SetString':['string','string','string'],
                      'SetBool':['string','string','bool'], 'InvokeBool':['string','string','bool'],
                      'InvokeInt':['string','string','int'],
                      'InvokeStringA':['string','string',self.array_type]})
            return {'name':args['script'], 'globalFunctions':[
                {'name':n,'params':[{'type':t} for t in ts]} for n,ts in types.items()]}
        function=args['function']; values=args['args']; path=values[1] if len(values)>1 else ''
        result=None
        if function=='GetGameSettingString':
            result={'sRSMConfirm':'Finish and name?', 'sRSMFinishedWarning':'Finish?',
                    'sYes':'Yes','sNo':'No','sOK':'OK','sCancel':'Cancel'}[values[0]]
        elif function=='GetString':
            result=('' if path.endswith('bottomBar._name') else 'NameEntryInstance'
                    if path.endswith('NameEntryInstance._name') else 'TextInputInstance'
                    if path.endswith('TextInputInstance._name') else self.name)
        elif function=='GetInt': result=0 if self.confirmed else 1
        elif function=='SetString': self.name=values[2]
        elif function=='InvokeInt':
            if path.endswith('onDoneClicked'): self.dialog=True
            else: raise AssertionError('Nonexistent stock acceptance handler must not be invoked')
        elif function=='InvokeStringA':
            self.delegates.append(values); self.closed=self.closes
        return {'returned':result}

class CharacterReadinessTests(unittest.TestCase):
    def run_character(self, session):
        clock=Clock()
        with patch.object(bootstrap.time,'monotonic',clock.monotonic), \
             patch.object(bootstrap.time,'sleep',clock.sleep), \
             patch.object(bootstrap.vr_probe,'ensure_owned_focus', side_effect=AssertionError('Native UI must not require foreground')):
            bootstrap.complete_character_creation(session)
    def test_native_name_ack_without_closure_never_means_ready(self):
        session=CharacterSession()
        with self.assertRaisesRegex(AssertionError,'remained open'):
            self.run_character(session)
        self.assertEqual(len(session.delegates),1)
        self.assertNotIn('characterCreationCompleted',session.state)
    def test_observed_closure_completes_stock_character_creation(self):
        session=CharacterSession(closes=True)
        self.run_character(session)
        self.assertTrue(session.state['characterCreationCompleted'])
    def test_wrong_live_array_signature_prevents_native_name_request(self):
        session=CharacterSession(array_type='int[]')
        with self.assertRaisesRegex(AssertionError,'parameter mismatch'):
            self.run_character(session)
        self.assertEqual(session.delegates,[])

if __name__=='__main__': unittest.main()
