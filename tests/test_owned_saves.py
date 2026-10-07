import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import owned_saves, platform
from skyrim_autotest.platform_mapping import operations


class Backend:
    def __init__(self, root):
        class Session: pass
        self.s=Session();profile=root/'Autotest-unit';target=profile/'saves';target.mkdir(parents=True)
        self.s.state={'id':'unit-01','testProfile':str(profile),'testProfileName':profile.name,
                      'ownedSaveDirectory':str(target),'configuration':{'allow_owned_save_load':True,'profiles':str(root)},
                      'preflight':{'profile':'Original'},'game':{'pid':17,'birth':123},'port':99,
                      'gameplayBootstrap':{'completed':True},'scenario':{},
                      'platformReferences':{'old-tag':{'id':'0xFF001234'}},'probeObjectLive':True}
        self.s.save=lambda:None;self.s.capture_probe_cursor=lambda:0
        self.s.invalidate_probe_reference=lambda reason:self.s.state.update(probeObjectLive=False)
        self.s.log=lambda *a,**k:None
        self.calls=[];self.end=100
        self.s.tool=lambda *a,**k:{}
        self.pause=lambda seconds:None
        self.remaining=lambda:30
        self.pap=lambda *a,**k:str(target)
    def call(self, tool, args):
        self.calls.append((tool,args))
        if tool=='game' and args['action']=='save':
            target=Path(self.s.state['ownedSaveDirectory'])
            (target/(args['name']+'.ess')).write_bytes(b'TESV_SAVEGAMEtest')
            (target/(args['name']+'.skse')).write_bytes(b'SKSEtest')
        if tool=='inspect':return {'playerLoaded':True,'cell':{'editorId':'QASmoke'}}
        if tool=='menu':return {'messageBoxOpen':False,'openMenus':[],'menuStates':[]}
        return {'queued':True}


def event(seq, name):return {'seq':seq,'topic':'lifecycle','data':{'event':name}}


class OwnedSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.b=Backend(Path(self.tmp.name))
    def request(self, action='save_game'):
        return {'action':action,'saveTag':'stocked-a','scope':'owned-disposable-profile'}
    def complete(self):
        replies=[{'headSeq':1,'events':[event(1,'saveGame')]},{'headSeq':1,'events':[]}]
        with patch('skyrim_autotest.runner.request',side_effect=replies),patch.object(owned_saves.time,'monotonic',side_effect=[0,0,2]):
            return owned_saves.perform(self.b,self.request())
    def test_completion_requires_native_event_and_owned_pair(self):
        result=self.complete()
        self.assertTrue(result['save']['completed'])
        self.assertEqual(len(result['save']['essSha256']),64)
        self.assertEqual(sum(tool=='game' and args['action']=='save' for tool,args in self.b.calls),1)
    def test_queued_save_without_event_never_claims_completion_or_retries(self):
        self.b.pause=lambda value:(_ for _ in ()).throw(TimeoutError('stop'))
        with patch('skyrim_autotest.runner.request',return_value={'headSeq':0,'events':[]}):
            with self.assertRaises(TimeoutError):owned_saves.perform(self.b,self.request())
        self.assertFalse(self.b.s.state['ownedSaves']['stocked-a']['completed'])
        self.assertEqual(len(self.b.calls),1)
    def test_duplicate_save_tag_is_refused_before_game_mutation(self):
        self.complete();count=len(self.b.calls)
        with self.assertRaisesRegex(ValueError,'already used'):owned_saves.perform(self.b,self.request())
        self.assertEqual(len(self.b.calls),count)
    def test_save_scope_optin_and_native_path_guard(self):
        self.b.s.state['configuration']['allow_owned_save_load']=False
        with self.assertRaisesRegex(ValueError,'not enabled'):owned_saves.perform(self.b,self.request())
        self.b.s.state['configuration']['allow_owned_save_load']=True
        self.b.pap=lambda *a: self.tmp.name
        with self.assertRaisesRegex(ValueError,'Native save path'):owned_saves.perform(self.b,self.request())
        self.assertEqual(self.b.calls,[])
    def test_changed_completed_pair_is_not_loaded(self):
        self.complete();record=self.b.s.state['ownedSaves']['stocked-a'];before=len(self.b.calls)
        (Path(self.b.s.state['ownedSaveDirectory'])/(record['stem']+'.ess')).write_bytes(b'TESV_SAVEGAMEchanged')
        with self.assertRaisesRegex(ValueError,'changed'):owned_saves.perform(self.b,self.request('load_game'))
        self.assertEqual(len(self.b.calls),before)
    def test_same_process_load_requires_ordered_events_common_readiness_and_old_tag_invalidation(self):
        self.complete()
        native=[event(1,'preLoadGame'),event(2,'postLoadGame')]
        with patch('skyrim_autotest.runner.request',side_effect=[{'headSeq':2,'events':native},{'headSeq':2,'events':[]}]), \
             patch('skyrim_autotest.bootstrap.wait_gameplay_ready',return_value=({'playerLoaded':True,'cell':{'editorId':'QASmoke'}},{})) as common, \
             patch('skyrim_autotest.platform.initialize_controllers'):
            value=owned_saves.perform(self.b,self.request('load_game'))['lifecycle']
        self.assertTrue(value['worldReady']);self.assertTrue(value['generationChanged'])
        self.assertFalse(value['pidChanged']);self.assertTrue(value['oldReferenceTagsInvalidated'])
        self.assertEqual(self.b.s.state['platformReferences'],{})
        self.assertIn('old-tag',self.b.s.state['invalidatedReferenceTags'])
        common.assert_called_once()
        self.assertEqual(common.call_args.kwargs['deadline'],self.b.end)
    def test_unordered_postload_cannot_be_completion(self):
        self.complete()
        with patch('skyrim_autotest.runner.request',return_value={'headSeq':1,'events':[event(1,'postLoadGame')]}):
            with self.assertRaisesRegex(ValueError,'unique ordered'):owned_saves.perform(self.b,self.request('load_game'))
        self.assertFalse(self.b.s.state['gameplayBootstrap']['completed'])
    def test_lifecycle_gap_and_leading_head_are_not_skipped(self):
        with patch('skyrim_autotest.runner.request',return_value={'headSeq':2,'events':[event(2,'saveGame')]}):
            with self.assertRaisesRegex(ValueError,'gap'):owned_saves.Events(self.b,0).read()
        with patch('skyrim_autotest.runner.request',side_effect=[{'headSeq':1,'events':[]},{'headSeq':1,'events':[event(1,'saveGame')]}]):
            self.assertEqual(len(owned_saves.Events(self.b,0).read()),1)
    def test_flat_names_and_valid_pair_headers_required(self):
        directory=Path(self.b.s.state['ownedSaveDirectory'])
        with self.assertRaisesRegex(ValueError,'flat'):owned_saves.pair(directory,'../foreign')
        (directory/'bad.ess').write_bytes(b'not-a-save');(directory/'bad.skse').write_bytes(b'SKSEtest')
        with self.assertRaisesRegex(ValueError,'header'):owned_saves.pair(directory,'bad')
    def test_schema_maps_exact_save_and_lifecycle_requests(self):
        platform.validate({'operation':'input.perform','request':self.request()})
        self.assertIn('input.perform',operations())
        self.assertIn('save.essSha256',operations()['world.read']['fields'])
        for tag in ('../foreign','',True):
            req=self.request();req['saveTag']=tag
            with self.assertRaises(ValueError):platform.validate({'operation':'input.perform','request':req})

    @unittest.skipUnless(os.name=='nt','Windows writer sharing contract')
    def test_exclusive_pair_read_refuses_open_writer(self):
        target=Path(self.b.s.state['ownedSaveDirectory'])
        (target/'locked.ess').write_bytes(b'TESV_SAVEGAMEtest')
        (target/'locked.skse').write_bytes(b'SKSEtest')
        with (target/'locked.ess').open('ab'):
            self.assertIsNone(owned_saves.pair(target,'locked'))
        self.assertIsNotNone(owned_saves.pair(target,'locked'))
