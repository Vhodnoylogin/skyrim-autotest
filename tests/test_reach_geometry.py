import copy
import math
import time
import unittest
from unittest.mock import patch
from skyrim_autotest.platform_math import world_bounds_center, body_reach_envelope, fixture_offset, solve3, palm_cast_target
from skyrim_autotest.platform import Backend


class ObservedReachTests(unittest.TestCase):
    def test_recorded_hand_rotation_places_cast_endpoint_on_requested_stack(self):
        transform={'rotationRowMajor':[-.75489831,-.14217383,-.64024562,-.13020155,.98927778,-.06616315,.64278746,.03341424,-.76531482],
                   'scale':.85,'translation':[-407.09384,2049.22119,6990.13037]}
        geometry={'palmPositionGameUnits':[0,-2.4,6],'palmDirection':[-.018,-.965,.261],'nearCastDistanceMetres':.15}
        columns=[[-11.897583,68.981934,0],[0,0,70],[68.981934,11.899414,0]]
        center=[-419.139904,2048.486985,6980.112382]
        target=palm_cast_target(center,transform,geometry,columns,'right')
        rotation=transform['rotationRowMajor']
        offset=[.85*sum(rotation[i*3+j]*geometry['palmPositionGameUnits'][j] for j in range(3)) for i in range(3)]
        direction=[sum(rotation[i*3+j]*geometry['palmDirection'][j] for j in range(3)) for i in range(3)]
        norm=math.sqrt(sum(v*v for v in direction));direction=[v/norm for v in direction]
        distance=.15/math.sqrt(sum(v*v for v in solve3(columns,direction)))
        endpoint=[target[i]+offset[i]+direction[i]*distance for i in range(3)]
        self.assertLess(math.dist(endpoint,center),1e-6)
        old_endpoint=[transform['translation'][i]+offset[i]+direction[i]*distance for i in range(3)]
        self.assertGreater(math.dist(old_endpoint,center),10)

    def test_grip_geometry_config_requires_explicit_valid_units_and_vectors(self):
        from skyrim_autotest.config import configure,template,ConfigurationError
        config=template();geometry={'palmPositionGameUnits':[0,-2.4,6],'palmDirection':[-.018,-.965,.261],'nearCastDistanceMetres':.15}
        config['physical_grip_geometry']=geometry
        configure(config)
        for key,value in [('palmDirection',[0,0,0]),('nearCastDistanceMetres',float('nan')),('palmPositionGameUnits',[0,False,6])]:
            bad=copy.deepcopy(config);bad['physical_grip_geometry'][key]=value
            with self.assertRaises(ConfigurationError):configure(bad)

    def test_runtime_near_distance_must_match_and_is_never_set(self):
        s=self.snapshot();b=self.backend(s)
        geometry={'palmPositionGameUnits':[0,-2.4,6],'palmDirection':[-.018,-.965,.261],'nearCastDistanceMetres':.15}
        b.s.state={'probeObjectLive':True,'configuration':{'physical_grip_geometry':geometry}}
        calls=[]
        b.pap=lambda script,function,args:(calls.append(function) or .15)
        b.reach_target('0xFF001234','right',[[70,0,0],[0,70,0],[0,0,70]])
        self.assertEqual(calls,['GetSetting'])
        b=self.backend(s);b.s.state={'configuration':{'physical_grip_geometry':geometry}};b.pap=lambda *a:.10
        with self.assertRaisesRegex(ValueError,'near distance differs'):b.reach_target('0xFF001234','right',[[70,0,0],[0,70,0],[0,0,70]])

    def test_rotated_scaled_asymmetric_bounds_use_observed_matrix(self):
        bounds={'min':[-4,-4,0],'max':[4,4,16]}
        transform={'translation':[10,20,30],'scale':2,
                   'rotationRowMajor':[1,0,0,0,0,-1,0,1,0]}
        self.assertEqual(world_bounds_center(bounds,transform),[10,4,30])
        for key,value in [('scale',float('nan')),('rotationRowMajor',[1]*9),('translation',[0,0])]:
            bad=copy.deepcopy(transform);bad[key]=value
            with self.assertRaises(ValueError):world_bounds_center(bounds,bad)

    def test_body_workspace_accepts_recorded_point_seven_metre_travel(self):
        columns=[[-11.897583,68.981934,0],[0,0,70],[68.981934,11.896973,0]]
        hand=[-393.634155,2025.104492,6993.490234]
        target=[-437.014149,2047.797160,6992.239258]
        shoulder=[-405,2025,7040];elbow=[-395,2025,7015]
        self.assertGreater(math.sqrt(sum(v*v for v in solve3(columns,[a-b for a,b in zip(target,hand)]))),.5)
        self.assertGreater(body_reach_envelope(columns,shoulder,elbow,hand,target)['bodyEnvelopeRadiusMetres'],.7)
        with self.assertRaisesRegex(ValueError,'body reach envelope'):
            body_reach_envelope(columns,shoulder,elbow,hand,[-1000,2025,6992])
        with self.assertRaisesRegex(ValueError,'arm geometry'):
            body_reach_envelope(columns,shoulder,shoulder,hand,target)

    def test_fixture_slots_are_distinct_after_arbitrary_heading(self):
        for angle in (0,.7,2.8):
            points=[fixture_offset(i,angle) for i in range(16)]
            for i,a in enumerate(points):
                for b in points[i+1:]:self.assertGreaterEqual(math.dist(a,b),19.9999)
        with self.assertRaises(ValueError):fixture_offset(16,0)

    def snapshot(self):
        identity={'form':'0xFF001234','runtimeHandle':44,'loadGeneration':2}
        world={'translation':[10,20,30],'rotationRowMajor':[1,0,0,0,1,0,0,0,1],'scale':1}
        node_identity={'form':'0x00000014','runtimeHandle':1,'loadGeneration':2}
        return {'ok':True,'units':'skyrim_engine_units','space':'world','sessionId':'session-a','loadGeneration':2,
                'sampleId':10,'refs':[{'identity':identity,'loaded3D':True,'deleted':False,'disabled':False,
                                     'status':'available','sceneTransform':world}],
                'nodes':[{'form':'0x00000014','identity':copy.deepcopy(node_identity),'name':name,
                          'firstPerson':first,'status':'available','world':dict(world,translation=point)}
                         for name,first,point in [('NPC R UpperArm [RUar]',False,[0,0,60]),
                                            ('NPC R Forearm [RLar]',False,[0,0,35]),
                                            ('NPC R Hand [RHnd]',False,[0,0,10]),
                                            ('NPC R Hand [RHnd]',True,[0,0,10])]]}

    def backend(self,snapshot):
        class Session:
            state={'probeObjectLive':True}
            def validate_probe_reference(self,**kwargs):pass
            def log(self,*a,**kwargs):pass
        b=Backend(Session(),time.monotonic()+30)
        b.call=lambda tool,args: (snapshot if args['kind']=='world_observer' else
            {'refs':[{'formId':'0xFF001234','bounds':{'min':[-4,-4,0],'max':[4,4,16]}}]})
        return b

    def test_exact_nodes_and_reference_share_generation_and_dynamic_transform(self):
        snapshot=self.snapshot();b=self.backend(snapshot)
        self.assertEqual(b.reference_center('0xFF001234','right'),[10,20,38])
        snapshot['refs'][0]['sceneTransform']['translation'][0]=15
        self.assertEqual(b.reference_center('0xFF001234','right'),[15,20,38])
        self.assertEqual(b._reach_body['hand'],[0,0,10])
        snapshot['refs'][0]['identity']['runtimeHandle']=45
        with self.assertRaisesRegex(ValueError,'incarnation'):b.reference_center('0xFF001234','right')

    def test_missing_reference_extents_use_only_matching_actual_native_base_bounds(self):
        from skyrim_autotest.config import P
        snapshot=self.snapshot();b=self.backend(snapshot)
        b.call=lambda tool,args:(snapshot if args['kind']=='world_observer' else
            {'refs':[{'formId':'0xFF001234','base':{'formId':'0xFF002345'}}]})
        base={'runtimeId':'0xFF002345','bounds':{'min':[-4,-4,0],'max':[4,4,16]}}
        with patch.dict(P.value,{'native_runtime_fixtures':True}), \
             patch('skyrim_autotest.runtime_items.identity',return_value=base) as identity:
            self.assertEqual(b.reference_center('0xFF001234'),[10,20,38])
        identity.assert_called_once_with(b,'0xFF001234',reference=True)
        for bad in ({'runtimeId':'0xFF009999','bounds':base['bounds']},
                    {'runtimeId':'0xFF002345'},
                    {'runtimeId':'0xFF002345','bounds':{'min':[0,0,0],'max':[0,0,0]}},
                    {'runtimeId':'0xFF002345','bounds':{'min':[0,0,0],'max':[float('nan'),0,0]}}):
            b=self.backend(snapshot)
            b.call=lambda tool,args:(snapshot if args['kind']=='world_observer' else
                {'refs':[{'formId':'0xFF001234','base':{'formId':'0xFF002345'}}]})
            with self.subTest(bad=bad),patch.dict(P.value,{'native_runtime_fixtures':True}), \
                 patch('skyrim_autotest.runtime_items.identity',return_value=bad),self.assertRaises(ValueError):
                b.reference_center('0xFF001234')

    def test_wrong_units_nodes_identity_or_generation_never_fall_back_to_origin(self):
        cases=[lambda s:s.update(units='havok'),
               lambda s:s['nodes'][0].update(status='unavailable'),
               lambda s:s['nodes'][0]['identity'].update(loadGeneration=9),
               lambda s:s['refs'][0]['identity'].update(form='0xFF009999'),
               lambda s:s['nodes'][0]['world'].update(translation=[float('nan'),0,0])]
        for change in cases:
            s=self.snapshot();change(s)
            with self.subTest(snapshot=s),self.assertRaises(ValueError):self.backend(s).reference_center('0xFF001234','right')

    def test_body_workspace_does_not_follow_translated_first_person_hand(self):
        snapshot=self.snapshot();b=self.backend(snapshot)
        columns=[[70,0,0],[0,70,0],[0,0,70]]
        def envelope():
            b.reference_center('0xFF001234','right')
            arm=b._reach_body
            return body_reach_envelope(columns,arm['shoulder'],arm['elbow'],arm['armHand'],[0,0,0])
        original=envelope()
        snapshot['nodes'][-1]['world']['translation']=[0,0,110]
        self.assertEqual(envelope(),original)
        self.assertEqual(b._reach_body['hand'],[0,0,110])
        self.assertEqual(b._reach_hand_transform['translation'],[0,0,110])
        # The same body workspace still rejects an actually extreme target.
        arm=b._reach_body
        with self.assertRaisesRegex(ValueError,'body reach envelope'):
            body_reach_envelope(columns,arm['shoulder'],arm['elbow'],arm['armHand'],[700,0,0])

    def test_missing_or_mismatched_third_person_arm_never_uses_fp_chain(self):
        for change in (lambda s:s['nodes'][0].update(firstPerson=True),
                       lambda s:s['nodes'][1]['identity'].update(runtimeHandle=999),
                       lambda s:s['nodes'][2]['identity'].update(loadGeneration=3),
                       lambda s:s['nodes'][2].update(status='unavailable')):
            snapshot=self.snapshot();change(snapshot)
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.backend(snapshot).reference_center('0xFF001234','right')

    def test_tp_workspace_and_fp_palm_share_one_exact_observer_query(self):
        snapshot=self.snapshot();b=self.backend(snapshot);queries=[];call=b.call
        def observe(tool,args):
            queries.append(copy.deepcopy(args));return call(tool,args)
        b.call=observe;b.reference_center('0xFF001234','right')
        queries=[q for q in queries if q['kind']=='world_observer']
        self.assertEqual(len(queries),1)
        self.assertEqual([n['firstPerson'] for n in queries[0]['nodes']],[False,False,False,True])


if __name__=='__main__':unittest.main()
