import json
import os
from pathlib import Path
import tempfile
import unittest
import hashlib
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
        self.s.phase=lambda *a:None
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
    def test_newgame_without_save_actions_skips_only_prelaunch_challenge(self):
        self.b.s.state['scenario']={'startMode':'new-game','steps':[{'tool':'platform','args':{'operation':'state.read'}}]}
        with patch.object(owned_saves,'prepare_mapping_probe') as prepare:
            owned_saves.prepare_required_mapping_probe(self.b.s,Path(self.b.s.state['ownedSaveDirectory']))
            prepare.assert_not_called()
        self.assertFalse(self.b.s.state['ownedSaveMappingRequired'])
        # A later unexpected save still cannot waive the native MO2 alias proof.
        (Path(self.b.s.state['testProfile'])/'settings.ini').write_text('[General]\nLocalSaves=true\nLocalSettings=true\n',encoding='utf-8')
        self.b.pap=lambda *a,**k:'__MO_Saves\\'
        with self.assertRaisesRegex(ValueError,'probe unavailable'):
            owned_saves.directory(self.b)

    def test_each_declared_save_action_and_poststep_requires_actual_probe(self):
        self.b.s.state.pop('game')
        for action in ('save_game','load_game','restart_game'):
            for key in ('steps','postSteps'):
                self.b.s.state['scenario']={'startMode':'new-game',key:[{'tool':'platform','args':{'operation':'input.perform','request':self.request(action)}}]}
                with self.assertRaisesRegex(ValueError,'Pinned owned fixture needed'):
                    owned_saves.prepare_required_mapping_probe(self.b.s,Path(self.b.s.state['ownedSaveDirectory']))
                self.assertTrue(self.b.s.state['ownedSaveMappingRequired'])

    def test_pinned_fixture_keeps_existing_mapping_challenge(self):
        self.b.s.state['scenario']={'fixture':{'saveStem':'existing'},'steps':[]}
        with patch.object(owned_saves,'prepare_mapping_probe') as prepare:
            owned_saves.prepare_required_mapping_probe(self.b.s,Path(self.b.s.state['ownedSaveDirectory']))
            prepare.assert_called_once()
        self.assertTrue(self.b.s.state['ownedSaveMappingRequired'])
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

    def test_restart_load_requires_new_process_common_startup_then_ordered_native_load(self):
        self.complete()
        def restart(b):
            b.s.state['game']={'pid':18,'birth':456}
            b.s.state['gameRestartTransition']={'completed':False,'stage':'loading'}
        native=[event(1,'preLoadGame'),event(2,'postLoadGame')]
        with patch('skyrim_autotest.game_restart.start',side_effect=restart), \
             patch('skyrim_autotest.bootstrap.prepare_startup_screen') as startup, \
             patch('skyrim_autotest.runner.request',side_effect=[{'headSeq':2,'events':native},{'headSeq':2,'events':[]}]), \
             patch('skyrim_autotest.bootstrap.wait_gameplay_ready',return_value=({'playerLoaded':True,'cell':{'editorId':'QASmoke'}},{})) as ready, \
             patch('skyrim_autotest.platform.initialize_controllers'):
            value=owned_saves.perform(self.b,self.request('restart_game'))['lifecycle']
        self.assertTrue(value['pidChanged']);self.assertTrue(value['worldReady'])
        self.assertTrue(self.b.s.state['gameRestartTransition']['completed'])
        startup.assert_called_once();ready.assert_called_once()
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

    def virtual_mapping(self, exposed=True):
        target=Path(self.b.s.state['ownedSaveDirectory'])
        contents=b'TESV_SAVEGAMEpinnedfixture'
        (target/'fixture.ess').write_bytes(contents)
        self.b.s.state['fixture']={'saveStem':'fixture','essSha256':hashlib.sha256(contents).hexdigest()}
        self.b.s.state['configuration']['skse_logs']=str(Path(self.tmp.name)/'MyGames/SKSE')
        (target.parent/'settings.ini').write_text('[General]\nLocalSaves=true\nLocalSettings=true\n')
        game=self.b.s.state.pop('game')
        owned_saves.prepare_mapping_probe(self.b.s,target)
        self.b.s.state['game']=game
        self.b.pap=lambda *a,**k:'__MO_Saves\\'
        def listing(tool,args):
            self.assertEqual(tool,'game');self.assertEqual(args['action'],'list')
            self.b.calls.append((tool,args))
            saves=[{'name':p.stem,'meta':{}} for p in target.glob(args['filter']+'*.ess')] if exposed else []
            return {'dir':str(Path(self.tmp.name)/'MyGames/__MO_Saves'),'truncated':False,
                    'count':len(saves),'returned':len(saves),'metaAvailable':bool(saves),'saves':saves}
        self.b.call=listing
        return target

    def test_mo2_alias_requires_live_read_of_unique_prelaunch_pinned_probe(self):
        target=self.virtual_mapping()
        self.assertEqual(owned_saves.directory(self.b),target)
        self.assertEqual(len(self.b.calls),1)
        self.assertEqual(len(list(target.glob('Autotest_Map_*'))),1)
        # No save/load request was used to establish the directory mapping.
        self.assertTrue(all(args['action']=='list' for tool,args in self.b.calls))

    def test_mo2_alias_without_actual_mapping_or_local_flags_stops_before_save(self):
        target=self.virtual_mapping(exposed=False)
        with self.assertRaisesRegex(ValueError,'cannot read exact'):owned_saves.directory(self.b)
        self.assertEqual(len(list(target.glob('Autotest_Map_*'))),1)
        (target.parent/'settings.ini').write_text('[General]\nLocalSaves=false\nLocalSettings=true\n')
        self.b.calls=[]
        with self.assertRaisesRegex(ValueError,'local saves/settings'):owned_saves.directory(self.b)
        self.assertEqual(self.b.calls,[])

    def test_mo2_mapping_never_accepts_generic_relative_save_directory(self):
        self.virtual_mapping();self.b.pap=lambda *a,**k:'Saves\\'
        with self.assertRaisesRegex(ValueError,'Native save path'):owned_saves.directory(self.b)
        self.assertEqual(self.b.calls,[])

    def test_mapping_probe_cannot_be_created_after_launch_or_changed_before_guard(self):
        target=self.virtual_mapping()
        with self.assertRaisesRegex(ValueError,'precede game launch'):owned_saves.prepare_mapping_probe(self.b.s,target)
        Path(self.b.s.state['ownedSaveMappingProbe']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'probe changed'):owned_saves.directory(self.b)
        self.assertEqual(self.b.calls,[])
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
