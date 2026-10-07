import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import runtime_items as domain,config,platform


class Backend:
    def __init__(self):
        class Session:
            def save(self):pass
            def log(self,*a,**kw):pass
        self.s=Session();self.s.state={'game':{'pid':17,'birth':123},'ownedWorldGeneration':2}
        self.guard_world=lambda:None;self.remaining=lambda:10
        self.raw={'schemaVersion':1,'pid':17,'frame':4,'requestedFormId':'0xFF001234','referenceBase':False,'item':{'runtimeId':'0xFF001234','formType':'ALCH',
            'runtimeCreated':True,'sourceFiles':[],'sourceFileCount':0,'sourceFilePolicy':'absent','plugin':None,'localId':None}}
        self.call=lambda *a:self.raw


class RuntimeItemTests(unittest.TestCase):
    def setUp(self):
        p=patch.object(config.P,'value',{'native_runtime_fixtures':True});p.start();self.addCleanup(p.stop)

    def test_runtime_form_identity_reads_native_source_policy_and_rejects_inconsistency(self):
        b=Backend();observed=domain.identity(b,'0xFF001234')
        self.assertTrue(observed['runtimeCreated']);self.assertIsNone(observed['plugin'])
        for change in ({'runtimeCreated':False},{'sourceFileCount':1},{'sourceFilePolicy':'inherited-template-file'},
                       {'localId':'001234'},{'plugin':'Skyrim.esm'}):
            b=Backend();b.raw['item'].update(change)
            with self.assertRaises(ValueError):domain.identity(b,'0xFF001234')

    def test_tag_cannot_cross_owned_game_or_load_generation(self):
        b=Backend();b.s.state['runtimeItems']={'crafted':{'status':'completed','game':copy.deepcopy(b.s.state['game']),
            'worldGeneration':2,'item':copy.deepcopy(b.raw['item'])}}
        self.assertEqual(domain.resolve(b,{'runtimeItemTag':'crafted','type':'ALCH'}),'0xFF001234')
        b.s.state['ownedWorldGeneration']=3
        with self.assertRaises(ValueError):domain.resolve(b,{'runtimeItemTag':'crafted','type':'ALCH'})
        b.s.state['ownedWorldGeneration']=2;b.s.state['game']['birth']=124
        with self.assertRaises(ValueError):domain.resolve(b,{'runtimeItemTag':'crafted','type':'ALCH'})

    def test_identity_is_bound_to_requested_reference_or_base_form(self):
        for change in ({'requestedFormId':'0xFF002222'},{'referenceBase':True}):
            b=Backend();b.raw.update(change)
            with self.assertRaises(ValueError):domain.identity(b,'0xFF001234')
        b=Backend();b.raw['item']['runtimeId']='0xFF002222'
        with self.assertRaisesRegex(ValueError,'different base form'):domain.identity(b,'0xFF001234')
        b.raw['referenceBase']=True
        self.assertEqual(domain.identity(b,'0xFF001234',reference=True)['runtimeId'],'0xFF002222')

    def test_unconfigured_native_provider_does_not_infer_dynamic_source_from_id(self):
        with patch.object(config.P,'value',{}):
            with self.assertRaisesRegex(ValueError,'not configured'):domain.identity(Backend(),'0xFF001234')

    def test_runtime_selector_and_factory_require_exact_native_contract(self):
        req={'action':domain.ACTION,'runtimeItemTag':'crafted','referenceTag':'seed',
             'templateItem':{'plugin':'Skyrim.esm','localId':'03EADD','type':'ALCH'},'quantityItems':1,
             'sourceFilePolicy':'absent','creationRequirement':domain.REQUIREMENT,'placement':domain.PLACEMENT}
        platform.validate({'operation':'object.perform','request':req})
        for change in ({'quantityItems':True},{'sourceFilePolicy':'guess'},{'creationRequirement':'REFR only'}):
            with self.assertRaises(ValueError):domain.validate('object.perform',dict(req,**change))
        for value in ({'runtimeItemTag':'crafted','type':'WEAP'},{'runtimeItemTag':'crafted','type':'ALCH','plugin':'X.esp'}):
            with self.assertRaises(ValueError):domain.selector(value)

    def test_uncertain_allocation_retains_intent_and_never_replays(self):
        req={'action':domain.ACTION,'runtimeItemTag':'crafted','referenceTag':'seed',
             'templateItem':{'plugin':'Skyrim.esm','localId':'03EADD','type':'ALCH'},'quantityItems':1,
             'sourceFilePolicy':'absent','creationRequirement':domain.REQUIREMENT,'placement':domain.PLACEMENT}
        b=Backend();b.resolve=lambda spec:'0x0003EADD';calls=[]
        def call(*args):calls.append(args);raise TimeoutError('native allocation outcome uncertain')
        b.call=call
        with patch('skyrim_autotest.body_scene.plan_placement'),patch.object(domain,'identity',return_value={}):
            with self.assertRaises(TimeoutError):domain.create(b,req)
            with self.assertRaisesRegex(ValueError,'already attempted'):domain.create(b,req)
        self.assertEqual(len(calls),1);self.assertEqual(b.s.state['runtimeItems']['crafted']['status'],'creating')


if __name__=='__main__':unittest.main()
