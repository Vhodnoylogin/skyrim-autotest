"""Actor scenes and passive capture fail closed. Never launches a game."""
import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from skyrim_autotest import actor_scene as a, config, platform
from skyrim_autotest import runner  # Resolve normal default runtime before per-test config.

SPEC={'plugin':'fixture.esp','localId':'000900'}
REF='0x12000900'


class Session:
    def __init__(self,path):
        self.dir=path
        self.state={'id':'unit','testProfile':'owned-profile','gameplayBootstrap':{'completed':True},
                    'game':{'pid':123,'birth':1,'path':'game'}}
        self.heartbeat_failed=threading.Event()
    def save(self):pass
    def log(self,*a,**kw):pass
    def phase(self,*a):pass


class ActorSceneTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.s=Session(Path(self.temp.name));self.b=platform.Backend(self.s,time.monotonic()+5)
        self.b.guard_world=lambda:None;self.b.resolve=lambda spec:REF
        self.ident={'form':REF,'runtimeHandle':42,'loadGeneration':1,'sourcePlugin':'fixture.esp','localFormId':'0x00000900'}
        self.actor={'status':'available','identity':self.ident,'loaded3D':True,'deleted':False,'disabled':False,'scale':1.,
                    'actorState':{'status':'available','lifeState':0,'restrained':False,'knockState':0,
                                  'wornForms':[],'equippedLeft':None,'equippedRight':None}}
        self.raw={'ok':True,'phase':'skse_main_thread_task','sessionId':'native-session','loadGeneration':1,
                  'space':'world','units':'skyrim_engine_units','refs':[self.actor],'nodes':[]}
        self.calls=[];self.paps=[]
        self.b.call=self.call;self.b.pap=self.pap
        self.original=copy.deepcopy(config.P.value);self.addCleanup(setattr,config.P,'value',self.original)
        config.P.value={'fixture_actor_allowlist':[SPEC]}
    def call(self,tool,args):
        self.calls.append(copy.deepcopy(args))
        if args.get('action')=='capabilities':return {'physics':{'boundedCapture':True}}
        physics=args.get('physics')
        if physics and 'captureAction' in physics:
            if physics['captureAction']=='start':
                self.capture={'id':physics['captureId'],'startedNs':1000,'endNs':60000001000,'windowComplete':False,
                              'bodySelectionChanged':False,'readExtendedLease':False,
                              'initialBodies':[{'status':'available','bodyUid':2,'form':REF,'worldId':1}]}
            self.raw['physics']={'status':'available','worldId':1,'contactPhase':'havok_contact_point_callback',
                'coverage':{'armedFromNs':1000,'armedUntilNs':60000001000,'subscriptionEpoch':1,'cursorAhead':False},
                'capture':copy.deepcopy(self.capture),'contacts':copy.deepcopy(getattr(self,'events',[])),
                'sampleMonotonicNs':60000001000 if self.capture['windowComplete'] else 1002,
                'sceneUnitConversion':{'status':'available','havokUnitsPerGameUnit':.02,'gameUnitsPerHavokUnit':50}}
            if hasattr(self,'alter'):self.alter(self.raw['physics'])
        return copy.deepcopy(self.raw)
    def pap(self,script,function,values=None,target=None,**kw):
        self.paps.append((script,function,values,target))
        if function=='GetActorBase':return {'formId':'0x12000800'}
        if function=='GetWeight':return 100.
        if function=='SetRestrained':
            self.actor['actorState'].update(restrained=values[0],lifeState=6 if values[0] else 0)
        return None
    def read(self,kind,**kw):return self.b.observe({'observation':kind,'actor':SPEC,**kw})
    def start(self):return self.read('actor.contact_capture',afterSequence=0,captureWindowSeconds=60,maximumSamples=256)
    def sample(self):return self.read('actor.contacts',afterSequence=0,maximumSamples=256)
    def event(self):
        return {'status':'available','sequence':1,'producerMonotonicNs':1001,'worldId':1,'loadGeneration':1,
                'bodyA':2,'bodyB':3,'phase':'havok_contact_point_callback','signedSeparation':-.1,
                'position':[0.,1.,2.],'normalBtoA':[0.,0.,1.],'disabled':False,'speculative':False}
    def addnode(self):
        self.raw['nodes']=[{'form':REF,'name':'3BA','firstPerson':False,'identity':copy.deepcopy(self.ident),
            'status':'available','world':{'translation':[1,2,3],'rotationRowMajor':[1,0,0,0,1,0,0,0,1],'scale':1},
            'worldBound':{'radius':12.,'center':[1,2,3]}}]
    def test_validate_actor_domains_and_reject_malformed_nodes(self):
        platform.validate({'operation':'world.read','request':{'observation':'actor.scene','actor':SPEC}})
        for names in ([{}],['x','x'],[],['\0'],True):
            with self.subTest(names=names),self.assertRaises(ValueError):
                platform.validate({'operation':'world.read','request':{'observation':'actor.skeleton_physics','actor':SPEC,
                                                                    'nodeNames':names,'perspective':'third-person'}})
        with self.assertRaises(ValueError):
            a.validate('world.read',{'observation':'actor.contact_capture','actor':SPEC,'afterSequence':0,
                                    'captureWindowSeconds':.1005,'maximumSamples':256})
    def test_actual_actor_identity_and_incarnation_are_retained(self):
        self.assertEqual(self.read('actor.scene')['actor']['identity']['localId'],'000900')
        self.ident['runtimeHandle']=43
        with self.assertRaisesRegex(ValueError,'incarnation'):self.read('actor.scene')
    def test_wrong_plugin_nonactor_generation_or_deleted_never_passes(self):
        for key,value in (('sourcePlugin','other.esp'),('localFormId','0x901'),('loadGeneration',2)):
            old=copy.deepcopy(self.ident);self.ident[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.read('actor.scene')
            self.ident.clear();self.ident.update(old)
        self.actor['actorState']={'status':'unavailable'}
        with self.assertRaisesRegex(ValueError,'actor state'):self.read('actor.scene')
        self.actor['deleted']=True
        with self.assertRaises(ValueError):self.read('actor.scene')
    def test_node_reads_actual_world_bound_and_preserves_matrix(self):
        self.addnode();result=self.read('scene.node',nodeName='3BA',perspective='third-person')
        self.assertEqual(result['scene']['node']['worldBound']['radius']['gameUnits'],12.)
        self.assertEqual(result['scene']['node']['worldTransform'],self.raw['nodes'][0]['world'])
        self.raw['nodes'][0]['world']['rotationRowMajor'][0]=float('nan')
        with self.assertRaises(ValueError):self.read('scene.node',nodeName='3BA',perspective='third-person')
    def test_node_identity_cannot_rebind_to_another_handle(self):
        self.addnode();self.raw['nodes'][0]['identity']['runtimeHandle']=99
        with self.assertRaises(ValueError):self.read('scene.node',nodeName='3BA',perspective='third-person')
    def test_skeleton_without_bodies_never_invents_body_mapping(self):
        self.addnode();self.raw['nodes'][0]['name']='NPC L Thigh [LThg]'
        result=self.read('actor.skeleton_physics',nodeNames=['NPC L Thigh [LThg]'],perspective='third-person')
        self.assertTrue(result['skeleton']['leftThigh']['node']['available'])
        self.assertEqual(result['skeleton']['leftThigh']['bodies'],[])
    def test_fixture_mutations_require_allowlist_and_owned_profile(self):
        req={'action':'set_fixture_actor_movement','actor':SPEC,'movement':'disabled'}
        config.P.value={}
        with self.assertRaises(ValueError):self.b.mutate(req)
        config.P.value={'fixture_actor_allowlist':[SPEC]};self.s.state['testProfile']=''
        with self.assertRaises(ValueError):self.b.mutate(req)
        self.assertFalse(self.paps)
    def test_prepare_reads_equipment_scale_weight_and_restraint(self):
        result=self.b.mutate({'action':'prepare_fixture_actor','actor':SPEC,'equipment':'unequip_all',
            'expectedScale':1,'expectedWeightPercent':100,'movement':'disabled'})
        self.assertTrue(result['fixture']['actor']['prepared'])
        self.assertEqual([v[1] for v in self.paps],['GetActorBase','UnequipAll','SetScale','SetWeight','SetRestrained','GetWeight'])
    def test_successful_callback_cannot_replace_equipment_postcondition(self):
        self.actor['actorState']['wornForms']=['0x123']
        self.b.pause=lambda seconds:(_ for _ in ()).throw(TimeoutError('readback unchanged'))
        with self.assertRaises(TimeoutError):self.b.mutate({'action':'prepare_fixture_actor','actor':SPEC,'equipment':'unequip_all',
            'expectedScale':1,'expectedWeightPercent':100,'movement':'disabled'})
        self.assertEqual(sum(v[1]=='UnequipAll' for v in self.paps),1)
    def test_push_callback_explicitly_is_not_effect_or_solver_proof(self):
        result=self.b.mutate({'action':'push_fixture_actor','source':'player','target':SPEC,'strength':5})
        self.assertTrue(result['fixture']['actor']['pushCompleted'])
        self.assertIn('not proof',result['fixture']['actor']['completionBasis'])
        self.assertEqual(sum(v[1]=='PushActorAway' for v in self.paps),1)
    def test_capture_start_once_read_keeps_fixed_end_and_no_absence_claim(self):
        result=self.start();self.assertTrue(result['physics']['capture']['available'])
        self.assertFalse(result['physics']['contacts']['sample']['available'])
        result=self.sample();self.assertFalse(result['physics']['contacts']['absenceProven'])
        self.assertEqual(self.calls[-1]['physics']['captureAction'],'read')
        self.assertNotIn('captureWindowMs',self.calls[-1]['physics'])
        with self.assertRaisesRegex(ValueError,'never replay'):self.start()
        self.assertEqual(sum(v.get('physics',{}).get('captureAction')=='start' for v in self.calls),1)
    def test_capture_read_never_starts_missing_capture(self):
        with self.assertRaises(ValueError):self.sample()
        self.assertFalse(self.calls)
    def test_actual_contact_conversion_retains_raw_flags_and_phase(self):
        self.start();self.events=[self.event()];result=self.sample()['physics']['contacts']
        self.assertTrue(result['sample']['available'])
        self.assertEqual(result['samples'][0]['signedSeparationGameUnits'],-5.)
        self.assertEqual(result['samples'][0]['signedSeparation'],-.1)
        self.assertFalse(result['solverUseProven'])
    def test_malformed_contact_provenance_never_passes(self):
        self.start()
        for key,value in (('worldId',2),('loadGeneration',2),('bodyA',99),('phase','post_step'),
                          ('producerMonotonicNs',60000001000),('signedSeparation',float('nan')),('disabled',1)):
            self.events=[self.event()];self.events[0][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.sample()
    def test_native_rearm_changed_epoch_or_bad_units_rejected(self):
        self.start()
        self.alter=lambda domain:domain['coverage'].update(subscriptionEpoch=2)
        with self.assertRaisesRegex(ValueError,'epoch'):self.sample()
        self.alter=lambda domain:domain['sceneUnitConversion'].update(gameUnitsPerHavokUnit=1)
        with self.assertRaisesRegex(ValueError,'conversion'):self.sample()
    def test_changed_bodies_do_not_prove_valid_actor_contact(self):
        self.start();self.capture['bodySelectionChanged']=True;self.events=[self.event()]
        self.assertFalse(self.sample()['physics']['contacts']['sample']['available'])
    def test_drain_waits_native_window_completion_before_collect(self):
        self.start();entry=self.s.state['actorCaptures'][a.selector(SPEC)]
        entry['hostDeadline']=time.monotonic()-1;self.capture['windowComplete']=True
        with patch.object(platform,'Backend',return_value=self.b):a.finish_captures(self.s)
        self.assertEqual(entry['status'],'finished')
        names=[];a.collect(self.s,lambda path,name,*args:names.append(name))
        self.assertEqual(len(names),3)
    def test_drain_refuses_premature_native_completion_and_retains_interruption(self):
        self.start();entry=self.s.state['actorCaptures'][a.selector(SPEC)]
        entry['hostDeadline']=time.monotonic()-1
        with patch.object(platform,'Backend',return_value=self.b),self.assertRaises(ValueError):a.finish_captures(self.s)
        a.collect(self.s,lambda *args:None)
        self.assertEqual(entry['status'],'interrupted')
        index=json.loads((self.s.dir/'actor-captures.json').read_text())
        self.assertEqual(index['captures'][a.selector(SPEC)]['status'],'interrupted')
    def test_tampered_raw_capture_fails_collection(self):
        self.start();entry=self.s.state['actorCaptures'][a.selector(SPEC)]
        (self.s.dir/entry['reads'][0]['name']).write_text('{}')
        with self.assertRaisesRegex(ValueError,'changed'):a.collect(self.s,lambda *args:None)

if __name__=='__main__':unittest.main()
