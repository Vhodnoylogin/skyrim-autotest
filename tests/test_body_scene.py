import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import body_scene as domain,platform


def transform(x=0,scale=1):
    return {'translation':[x,0,100],'rotationRowMajor':[0,-1,0,1,0,0,0,0,1],'scale':scale}


class Backend:
    def __init__(self):
        class Session:
            def __init__(self):self.state={}
            def log(self,*a,**kw):pass
        self.s=Session();self.guard_world=lambda:None
        self.values=[2,3,4]
        self.pap_read_batch=lambda calls:self.values
        self.raw={'ok':True,'space':'world','units':'skyrim_engine_units','sessionId':'S','loadGeneration':1,'nodes':[]}
        for name in (domain.BONES[13],domain.HEAD):
            self.raw['nodes'].append({'name':name,'firstPerson':False,'form':'0x00000014','status':'available',
                'identity':{'form':'0x00000014','loadGeneration':1,'runtimeHandle':7},'world':transform(10,2)})
        self.call=lambda *a:copy.deepcopy(self.raw)


class BodySceneTests(unittest.TestCase):
    def test_slot_point_uses_observed_rotation_scale_and_actual_loaded_offset(self):
        b=Backend();points,nodes=domain.centres(b,[14])
        self.assertEqual(points[14],[4,4,108])
        self.assertEqual(nodes[(domain.HEAD,False)]['translation'],[10,0,100])

    def test_changed_slot_settings_during_scene_read_are_unavailable(self):
        b=Backend();b.pap_read_batch=lambda calls:next(b.results);b.results=iter([[2,3,4],[3,3,4]])
        with self.assertRaisesRegex(ValueError,'settings changed'):domain.centres(b,[14])

    def test_wrong_skeleton_generation_or_missing_bone_cannot_supply_target(self):
        for change in (lambda b:b.raw['nodes'][0].update(firstPerson=True),
                       lambda b:b.raw['nodes'][0]['identity'].update(loadGeneration=2),
                       lambda b:b.raw['nodes'][0].update(status='unavailable'),
                       lambda b:b.raw['nodes'][0]['world'].update(scale=0)):
            b=Backend();change(b)
            with self.assertRaises(ValueError):domain.centres(b,[14])

    def test_clearance_checks_all_slots_and_head_in_measured_engine_units(self):
        b=Backend();points={i:[100,0,0] for i in range(1,15)};nodes={(domain.HEAD,False):{'translation':[0,100,0]}}
        with patch.object(domain,'centres',return_value=(points,nodes)):
            self.assertTrue(domain.exclusion(b,[0,0,0])[0])
            points[14]=[5,0,0];self.assertFalse(domain.exclusion(b,[0,0,0])[0])
            points[14]=[100,0,0];self.assertFalse(domain.exclusion(b,[0,95,0])[0])

    def test_body_slot_request_uses_explicit_target_basis_and_mouth_policy(self):
        req={'action':'pose_hand_at_body_slot','hand':'right','slot':14,'grip':'closed',
             'offset':{'units':'metres','xyz':[0,0,0]},'durationSeconds':1.2,'targetBasis':domain.TARGET_BASIS,'avoidMouth':True}
        platform.validate({'operation':'controller.perform','request':req})
        for change in ({'slot':0},{'avoidMouth':False},{'targetBasis':'requested coordinate'},{'offset':{'xyz':[0,0,0]}}):
            with self.assertRaises(ValueError):platform.validate({'operation':'controller.perform','request':dict(req,**change)})


if __name__=='__main__':unittest.main()
