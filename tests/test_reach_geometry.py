import copy
import math
import time
import unittest
from skyrim_autotest.platform_math import world_bounds_center, body_reach_envelope, fixture_offset, solve3
from skyrim_autotest.platform import Backend


class ObservedReachTests(unittest.TestCase):
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
                          'firstPerson':True,'status':'available','world':dict(world,translation=point)}
                         for name,point in [('NPC R UpperArm [RUar]',[0,0,60]),
                                            ('NPC R Forearm [RLar]',[0,0,35]),
                                            ('NPC R Hand [RHnd]',[0,0,10])]]}

    def backend(self,snapshot):
        class Session:
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

    def test_wrong_units_nodes_identity_or_generation_never_fall_back_to_origin(self):
        cases=[lambda s:s.update(units='havok'),
               lambda s:s['nodes'][0].update(status='unavailable'),
               lambda s:s['nodes'][0]['identity'].update(loadGeneration=9),
               lambda s:s['refs'][0]['identity'].update(form='0xFF009999'),
               lambda s:s['nodes'][0]['world'].update(translation=[float('nan'),0,0])]
        for change in cases:
            s=self.snapshot();change(s)
            with self.subTest(snapshot=s),self.assertRaises(ValueError):self.backend(s).reference_center('0xFF001234','right')


if __name__=='__main__':unittest.main()
