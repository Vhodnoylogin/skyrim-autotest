import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from skyrim_autotest import subject_state as domain,config,platform


class Backend:
    def __init__(self,root):
        class Session:
            def save(self):pass
            def log(self,*a,**k):pass
        self.s=Session();self.s.state={'game':{'pid':17,'birth':123},'snapshots':[],'gameplayBootstrap':{'completed':True}}
        self.remaining=lambda:10;self.guard_world=lambda:None
        self.raw={'schemaVersion':1,'provider':'custom_state','readOnly':True,'ok':True,'available':True,
            'process':{'pid':17,'identityAvailable':True,'createdFileTime100ns':123},
            'sample':{'phase':'skse_main_thread_task','sequence':1,'lifecycleEpoch':0},
            'subject':{'available':True,'loadGeneration':0,'callbackFrame':1,
                'settings':{'language':'english','logLevel':'info','mayEnableSlots':False,'pouches':[], 'inputHandedness':'right'},
                'runtime':{'assignmentCount':0,'assignmentCountUnits':'assigned_pouches'},
                'bodySlots':[{'slot':13,'suspendedAvailable':True,'suspended':False}]}}
        def call(*args):
            self.raw['sample']['sequence']+=1
            return copy.deepcopy(self.raw)
        self.call=call


class SubjectStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        p=patch.object(config.P,'value',{'overwrite':str(self.root),'subject_state_bindings':{'Any Subject':{'inspectKind':'custom_state'}}})
        p.start();self.addCleanup(p.stop)

    def test_native_snapshot_preserves_actual_empty_settings_and_zero_assignments(self):
        b=Backend(self.root);value=domain.observe(b,'Any Subject')
        self.assertEqual(value['subject']['settings']['pouches'],[])
        self.assertEqual(value['subject']['runtime']['assignmentCount'],0)
        self.assertFalse(domain.slot_suspended(b,13))
        with self.assertRaises(ValueError):domain.observe(b,'Unbound Subject')

    def test_stale_native_process_missing_settings_and_wrong_types_never_default(self):
        for mutate in (lambda x:x['process'].update(createdFileTime100ns=124),lambda x:x.update(available=False),
                       lambda x:x['subject'].pop('settings'),lambda x:x['subject']['runtime'].update(assignmentCount=False),
                       lambda x:x['subject']['settings'].update(inputHandedness=None),lambda x:x.update(schemaVersion=True)):
            b=Backend(self.root);mutate(b.raw)
            with self.subTest(raw=b.raw):
                with self.assertRaises(ValueError):domain.observe(b,'Any Subject')

    def test_atomic_override_requires_initial_snapshot_and_rejects_foreign_edits(self):
        b=Backend(self.root);target=self.root/'SKSE/Plugins/settings.json';target.parent.mkdir(parents=True);target.write_bytes(b'original')
        temp=target.with_name(target.name+'.autotest-fixture.tmp')
        b.s.state['snapshots']=[{'path':str(target),'exists':True,'sha256':hashlib.sha256(b'original').hexdigest()},
                                {'path':str(temp),'exists':False}]
        domain.atomic_write(b,target,b'first');domain.atomic_write(b,target,b'second')
        self.assertEqual(target.read_bytes(),b'second');self.assertFalse(temp.exists())
        target.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'outside this owner'):domain.atomic_write(b,target,b'third')
        self.assertEqual(target.read_bytes(),b'foreign')
        b.s.state['snapshots']=[]
        with self.assertRaisesRegex(ValueError,'snapshotted'):domain.atomic_write(b,target,b'third')

    def test_slot_ini_edits_only_requested_keys_and_rejects_duplicates(self):
        data=b'; comment\r\nallowSmallSlot14 = 0\r\nvisibleSlot14 = 0\r\nallowSmallSlot13 = 1\r\n'
        fixture=[{'slot':14,'allowSmall':True,'visible':True}]
        actual=domain.slot_ini(data,fixture)
        self.assertIn(b'allowSmallSlot14 = 1',actual);self.assertIn(b'visibleSlot14 = 1',actual)
        self.assertIn(b'allowSmallSlot13 = 1',actual);self.assertIn(b'; comment',actual)
        with self.assertRaises(ValueError):domain.slot_ini(data+b'visibleSlot14=0\n',fixture)
        self.assertEqual(domain.slot_ini(data,[]),data)

    def test_replayed_native_sample_is_not_fresh_readiness_or_state(self):
        b=Backend(self.root);frozen=copy.deepcopy(b.raw);b.call=lambda *a:frozen
        domain.observe(b,'Any Subject')
        with self.assertRaisesRegex(ValueError,'Replayed'):domain.observe(b,'Any Subject')

    def test_restart_fixture_validation_rejects_ambiguous_slots_and_source_scope(self):
        req={'action':domain.ACTION,'subject':'Any Subject','saveTag':'baseline','scope':'owned-disposable-profile',
             'settings':{'language':'english','logLevel':'info','mayEnableSlots':False},'inputHandedness':'left',
             'bodySlotFixtures':[],'restoration':domain.RESTORATION}
        platform.validate({'operation':'object.perform','request':req})
        for change in ({'scope':'source-profile'},{'inputHandedness':'unknown'},
                       {'bodySlotFixtures':[{'slot':True,'allowSmall':True,'visible':True}]},
                       {'settings':dict(req['settings'],inputHandedness='left')}):
            with self.assertRaises(ValueError):domain.validate('object.perform',dict(req,**change))

    def test_restart_variants_use_pinned_baseline_and_read_actual_not_requested_settings(self):
        b=Backend(self.root);profile=self.root/'profiles/Test';profile.mkdir(parents=True)
        (profile/'skyrimprefs.ini').write_text('[VRInput]\nbLeftHandedMode=0\n')
        baseline=self.root/'baseline.ini';baseline.write_bytes(b'allowSmallSlot14=0\r\nvisibleSlot14=0\r\n')
        binding={'inspectKind':'custom_state','settingsDestination':'SKSE/Plugins/settings.json',
            'handednessProfileIni':'skyrimprefs.ini','bodySlotsDestination':'SKSE/Plugins/slots.ini',
            'bodySlotsSource':{'path':str(baseline),'sha256':hashlib.sha256(baseline.read_bytes()).hexdigest()}}
        config.P.value.update(profiles=str(profile.parent),subject_state_bindings={'Any Subject':binding})
        b.s.state.update(testProfile=str(profile),testProfileName='Test',preflight={'profile':'Owner'})
        for name in ('settings.json','slots.ini'):
            target=self.root/'SKSE/Plugins'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'original')
            b.s.state['snapshots'].extend([{'path':str(target),'exists':True,'sha256':hashlib.sha256(b'original').hexdigest()},
                {'path':str(target)+'.autotest-fixture.tmp','exists':False}])
        req={'action':domain.ACTION,'subject':'Any Subject','saveTag':'baseline','scope':'owned-disposable-profile',
            'settings':{'language':'russian','logLevel':'debug','mayEnableSlots':True,'pouches':[]},'inputHandedness':'left',
            'bodySlotFixtures':[{'slot':14,'allowSmall':True,'visible':True}],'restoration':domain.RESTORATION}
        def restart(backend,request,restart_prepare):
            restart_prepare();return {'lifecycle':{'worldReady':True}}
        with patch('skyrim_autotest.owned_saves.perform',side_effect=restart),patch('skyrim_autotest.native.processes',return_value=[]):
            first=domain.perform(b,req)
            self.assertEqual(first['subject']['settings']['language'],'english')
            self.assertEqual(first['subject']['settings']['inputHandedness'],'right')
            self.assertIn('bLeftHandedMode=1',(profile/'skyrimprefs.ini').read_text())
            self.assertIn(b'allowSmallSlot14= 1',(self.root/'SKSE/Plugins/slots.ini').read_bytes())
            domain.perform(b,dict(req,bodySlotFixtures=[]))
        self.assertEqual((self.root/'SKSE/Plugins/slots.ini').read_bytes(),baseline.read_bytes())
        self.assertEqual(len(b.s.state['fixtureSettingsHistory']),2)
        self.assertTrue(all(row['completed'] for row in b.s.state['fixtureSettingsHistory']))


if __name__=='__main__':unittest.main()
