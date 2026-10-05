import unittest
from unittest.mock import patch

from skyrim_autotest import bootstrap, mobility_probe, scenarios


class MobilityProbeTests(unittest.TestCase):
    def vr_sample(self, sample=1):
        return {'ok':True,'sessionId':'owned-world','loadGeneration':1,'sampleId':sample,
                'vrPicking':{'status':'available','phase':'skse_main_thread_task',
                    'units':'skyrim_engine_units','space':'world',
                    'nodes':{'primaryAim':{'status':'available','world':{
                        'translation':[14.7,10,84],'rotationRowMajor':[1,0,0,0,1,0,0,0,1]}}},
                    'devices':{'right':{'targetStatus':'available',
                        'target':{'form':'0xFF000801','loadGeneration':1}}}}}

    def test_fixture_uses_measured_world_pose_and_requires_exact_fresh_right_target(self):
        before,after=self.vr_sample(),self.vr_sample(2)
        self.assertEqual(mobility_probe.primary_aim_fixture_position(before),[14.7,60,84])
        self.assertTrue(mobility_probe.exact_right_pick(before,after,'0xff000801'))
        self.assertFalse(mobility_probe.exact_right_pick(before,after,'0xff000802'))
        self.assertFalse(mobility_probe.exact_right_pick(before,before,'0xff000801'))
        after['sessionId']='later-game'
        self.assertFalse(mobility_probe.exact_right_pick(before,after,'0xff000801'))
        after['sessionId']='owned-world';after['loadGeneration']=2
        self.assertFalse(mobility_probe.exact_right_pick(before,after,'0xff000801'))

    def test_actual_aim_offset_is_used_instead_of_wand_horizontal_direction(self):
        sample=self.vr_sample()
        sample['vrPicking']['nodes']['primaryAim']['world']={
            'translation':[0,0,100],
            'rotationRowMajor':[1,0,0,0,.5,.8660254,0,-.8660254,.5]}
        result=mobility_probe.primary_aim_fixture_position(sample)
        self.assertAlmostEqual(result[1],25,places=4)
        self.assertAlmostEqual(result[2],56.69873,places=4)

    def test_input_hand_target_cannot_be_replaced_with_other_hand_target(self):
        before,after=self.vr_sample(),self.vr_sample(2)
        after['vrPicking']['devices']['left']={'targetStatus':'none','target':None}
        self.assertTrue(mobility_probe.exact_device_pick(before,after,'0xff000801','right'))
        self.assertFalse(mobility_probe.exact_device_pick(before,after,'0xff000801','left'))
        after['vrPicking']['devices']['left']=after['vrPicking']['devices']['right']
        self.assertTrue(mobility_probe.exact_device_pick(before,after,'0xff000801','left'))
        self.assertFalse(mobility_probe.exact_device_pick(before,after,'0xff000802','left'))
    def test_secondary_aim_uses_its_actual_transform_and_never_falls_back_to_primary(self):
        sample=self.vr_sample()
        with self.assertRaisesRegex(AssertionError,'secondaryAim'):
            mobility_probe.aim_fixture_position(sample,'secondaryAim')
        sample['vrPicking']['nodes']['secondaryAim']={'status':'available','world':{
            'translation':[-14.7,10,84], 'rotationRowMajor':[1,0,0,0,1,0,0,0,1]}}
        self.assertEqual(mobility_probe.aim_fixture_position(sample,'secondaryAim'),[-14.7,60,84])
    def test_loaded_combined_activate_uses_secondary_trackpad_not_attack_trigger(self):
        sample=self.vr_sample();picking=sample['vrPicking']
        picking['nodes'].update({'rightWand':{'status':'available','world':{'translation':[14.7,10,84]}},
                                'leftWand':{'status':'available','world':{'translation':[-14.7,10,84]}}})
        picking['gameplayBindings']={'status':'available','context':'gameplay','devices':{
            'vivePrimary':{'Activate':[{'key':255,'modifier':0,'linked':False}]},
            'viveSecondary':{'Teleport Or Activate':[{'key':32,'modifier':0,'linked':False}]}}}
        binding=mobility_probe.vive_activation(sample)
        self.assertEqual((binding['role'],binding['key'],binding['event']),('left',32,'Teleport Or Activate'))
        picking['gameplayBindings']['devices']['viveSecondary']['Teleport Or Activate'][0]['linked']=True
        with self.assertRaises(AssertionError):mobility_probe.vive_activation(sample)
        picking['nodes']['leftWand']['world']['translation']=[14.7,10,84]
        with self.assertRaisesRegex(AssertionError,'identity unavailable'):mobility_probe.vive_activation(sample)

    def test_unsafe_pose_or_missing_device_target_cannot_authorize_input(self):
        for field,value in [('units','openvr_metres'),('space','local'),('status','unavailable')]:
            before,after=self.vr_sample(),self.vr_sample(2)
            after['vrPicking'][field]=value
            self.assertFalse(mobility_probe.exact_right_pick(before,after,'0xff000801'))
            with self.assertRaises(AssertionError):mobility_probe.primary_aim_fixture_position(after)
        sample=self.vr_sample();sample['vrPicking']['nodes']['primaryAim']['world']['translation'][0]=float('nan')
        with self.assertRaises(AssertionError):mobility_probe.primary_aim_fixture_position(sample)
        before,after=self.vr_sample(),self.vr_sample(2)
        after['vrPicking']['devices']['right']={'targetStatus':'none','target':None}
        self.assertFalse(mobility_probe.exact_right_pick(before,after,'0xff000801'))

    def test_combined_activation_does_not_use_dead_or_teleport_zone(self):
        binding={'event':'Teleport Or Activate','key':32}
        settings={'fDeadzonePercent:VRInput':.15,
                  'fThumbstickTeleportActivateZone:VRInput':.6}
        point=mobility_probe.activation_trackpad(binding,settings)
        self.assertEqual(point[0],0)
        self.assertGreater(point[1],.15)
        self.assertLess(point[1],.6)
        self.assertEqual(mobility_probe.activation_trackpad({'event':'Activate','key':33},{}),[0,0])

    def test_unknown_or_empty_activation_interval_blocks_physical_input(self):
        binding={'event':'Teleport Or Activate','key':32}
        for lower,upper in ((None,.6),(.6,.4),(.6,.6),(.59,.6),(-.1,.6),
                            (float('nan'),.6),(.15,True),(.15,1.1)):
            with self.subTest(lower=lower,upper=upper), self.assertRaises(AssertionError):
                mobility_probe.activation_trackpad(binding,{
                    'fDeadzonePercent:VRInput':lower,
                    'fThumbstickTeleportActivateZone:VRInput':upper})

    def test_fixture_position_uses_supported_atomic_native_signature(self):
        def native(script,function,args,target):
            self.assertEqual((script,function),('ObjectReference','SetPosition'))
            self.assertEqual(args,[1,2,3]);self.assertEqual(target,'0xff000801')
        mobility_probe.place_owned_fixture(native,'0xff000801',[1,2,3])

    def test_fixture_position_cannot_move_player_or_publish_invalid_coordinates(self):
        for ref,xyz in [('0x14',[1,2,3]),('0x00000014',[1,2,3]),
                        ('0xff000801',[1,float('nan'),3]),('0xff000801',[1,True,3])]:
            with self.subTest(ref=ref,xyz=xyz),self.assertRaises(ValueError):
                mobility_probe.place_owned_fixture(lambda *a,**k:self.fail('must not mutate'),ref,xyz)

    def test_common_bootstrap_verifies_world_before_marking_ready(self):
        class Session:
            state={}
            def __init__(self):self.calls=[]
            def phase(self,*args):pass
            def log(self,*args,**kwargs):pass
            def save(self):pass
            def tool(self,name,args):
                self.calls.append((name,args))
                if name=='inspect':return ({'cell':{'editorId':'VRPlayroom01'}} if len(self.calls)==1 else
                                          {'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}})
                if name=='menu':return {'openMenus':['HUD Menu']}
        session=Session();scene={'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}
        with patch.object(bootstrap,'advance_calibration',return_value=True), \
                patch.object(bootstrap.vr_probe,'guard_fixture_modal',return_value=False), \
                patch.object(bootstrap.vr_probe,'wait_test_cell',return_value=scene), \
                patch.object(bootstrap.time,'monotonic',side_effect=iter(range(100))), \
                patch.object(bootstrap.time,'sleep'):
            bootstrap.prepare_gameplay(session,{'cell':'RealmLorkhan'})
        self.assertTrue(session.state['gameplayBootstrap']['completed'])
        self.assertEqual(session.state['gameplayBootstrap']['scene'],scene)
        self.assertEqual([args['command'] for name,args in session.calls if name=='console'],['coc RealmLorkhan'])

    def test_common_bootstrap_does_not_treat_main_menu_as_gameplay(self):
        class Session:
            state={}
            def phase(self,*args):pass
            def log(self,*args,**kwargs):pass
            def save(self):pass
            def tool(self,name,args):
                return {'cell':{'editorId':'Other'}} if name=='inspect' else {'openMenus':['Main Menu']}
        session=Session()
        with patch.object(bootstrap.vr_probe,'guard_fixture_modal'), \
                patch.object(bootstrap.vr_probe,'wait_test_cell',return_value={'playerLoaded':True,'cell':{'editorId':'RealmLorkhan'}}), \
                patch.object(bootstrap.time,'monotonic',side_effect=iter(range(1000))), \
                patch.object(bootstrap.time,'sleep'):
            with self.assertRaisesRegex(AssertionError,'not ready'):
                bootstrap.prepare_gameplay(session,{'cell':'RealmLorkhan'})
        self.assertNotIn('gameplayBootstrap',session.state)

    def test_common_bootstrap_requires_explicit_initial_state(self):
        with self.assertRaisesRegex(AssertionError,'initial cell or pinned save'):
            bootstrap.prepare_gameplay(object(),{})

    def test_unknown_startup_screen_does_not_receive_input(self):
        class Session:
            def __init__(self): self.calls = []
            def tool(self, name, args):
                self.calls.append((name, args))
                return {'openMenus': ['Main Menu']}
        session=Session()
        self.assertFalse(bootstrap.advance_calibration(session))
        self.assertEqual(len(session.calls), 1)

    def test_calibration_input_requires_playroom_identity(self):
        class Session:
            def __init__(self): self.calls=[]
            def tool(self, name, args):
                self.calls.append((name,args))
                return {'openMenus':['CalibrationOptionMenu']} if name=='menu' else {'cell':{'editorId':'Other'}}
        session=Session()
        with self.assertRaisesRegex(AssertionError, 'ambiguous'):
            bootstrap.advance_calibration(session)
        self.assertFalse(any(name=='driver' for name,_ in session.calls))

    def test_calibration_button_releases_and_requires_observed_menu_transition(self):
        class Session:
            state={'inputBackend':'driver','driverBackend':'file'}
            def __init__(self): self.calls=[];self.menus=0
            def phase(self,name,seconds):pass
            def log(self,*args,**kwargs):pass
            def tool(self,name,args):
                self.calls.append((name,args))
                if name=='menu':
                    self.menus+=1
                    return {'openMenus':['CalibrationOptionMenu'] if self.menus==1 else ['Main Menu']}
                if name=='inspect':return {'cell':{'editorId':'VRPlayroom01'}}
        session=Session()
        with patch.object(bootstrap.time,'sleep'):
            self.assertTrue(bootstrap.advance_calibration(session))
        driver=[args for name,args in session.calls if name=='driver']
        self.assertEqual([args['action'] for args in driver],['publish','release'])
        self.assertEqual(driver[0]['frame']['right']['controller']['pressed'],1<<33)

    def test_calibration_sampling_exception_still_releases_button(self):
        class Session:
            state={'inputBackend':'driver','driverBackend':'file'}
            def __init__(self):self.calls=[]
            def phase(self,*args):pass
            def log(self,*args,**kwargs):pass
            def tool(self,name,args):
                self.calls.append((name,args))
                return {'openMenus':['CalibrationOptionMenu']} if name=='menu' else {'cell':{'editorId':'VRPlayroom01'}}
        session=Session()
        with patch.object(bootstrap.time,'sleep',side_effect=RuntimeError('client interrupted')):
            with self.assertRaises(RuntimeError):bootstrap.advance_calibration(session)
        self.assertEqual([args['action'] for name,args in session.calls if name=='driver'],['publish','release'])

    def test_minimal_probe_does_not_require_higgs_or_a_save(self):
        scenarios.validate({'schemaVersion': 1, 'kind': 'vr-mobility-probe',
                            'cell': 'RealmLorkhan', 'physicalGrab': False,
                            'allowBackgroundVR': True})

    def test_invalid_scope_parameters_fail_before_launch(self):
        for key, value in [('cell', 'QASmoke;qqq'), ('physicalGrab', 1),
                           ('observer', 'yes'), ('keyboardDiagnostics', []), ('allowBackgroundVR', 1)]:
            scenario = {'schemaVersion': 1, 'kind': 'vr-mobility-probe', 'cell': 'RealmLorkhan', key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                scenarios.validate(scenario)

    def test_published_frame_is_not_accepted_as_observed_tracking(self):
        with self.assertRaises(AssertionError):
            mobility_probe.tracked_xyz({'published': True, 'acknowledgedByDriver': False})

    def test_unavailable_or_malformed_tracking_fails(self):
        for device in [{'valid': False}, {'valid': True, 'matrix': [0] * 11},
                       {'valid': True, 'matrix': [float('nan')] * 12},
                       {'valid': True, 'matrix': [True] * 12}]:
            with self.subTest(device=device), self.assertRaises(AssertionError):
                mobility_probe.tracked_xyz(device)

    def test_sampling_failure_still_releases_exact_owned_key(self):
        class Session:
            state = {'id': 'test-owner'}
            def __init__(self): self.calls = []
            def tool(self, name, args): self.calls.append((name, args))
        session = Session()
        def fail(): raise RuntimeError('read failed')
        with self.assertRaisesRegex(RuntimeError, 'read failed'):
            mobility_probe.keyboard_hold(session, 'W', 1, fail)
        self.assertEqual([args['action'] for _, args in session.calls], ['down', 'up'])
        self.assertEqual(session.calls[-1][1]['owner'], 'autotest-test-owner')
        self.assertEqual(session.calls[-1][1]['key'], 'W')
        self.assertNotIn('force', session.calls[-1][1])
        self.assertEqual(session.calls[0][1]['maxHoldMs'], 4000)

    def test_failed_acquire_does_not_release_another_owner(self):
        class Session:
            state = {'id': 'test-owner'}
            def __init__(self): self.calls = []
            def tool(self, name, args):
                self.calls.append(args)
                raise RuntimeError('conflicting owner')
        session = Session()
        with self.assertRaisesRegex(RuntimeError, 'conflicting owner'):
            mobility_probe.keyboard_hold(session, 'SPACE', .1)
        self.assertEqual(len(session.calls), 1)

    def test_probe_rejects_diagnostic_backend_before_any_mutation(self):
        class Session:
            state = {'inputBackend': 'devbench', 'driverBackend': 'file'}
        with self.assertRaisesRegex(ValueError, 'physical file adapter'):
            mobility_probe.execute(Session(), {'kind': 'vr-mobility-probe'})
