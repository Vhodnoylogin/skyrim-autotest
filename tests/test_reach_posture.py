import copy
import unittest
from unittest.mock import patch
from skyrim_autotest.hardware import neutral
from skyrim_autotest.reach_posture import ReachPosture


class Fake:
    def __init__(self):
        class Session:
            def log(self,*a,**k):pass
        self.s=Session();self.calls=[];self.held=None;self.response=True
        self.frame=neutral();self.start=self.frame['hmd']['matrix'][7]
        self._reach_body={'shoulder':[0,0,100],'elbow':[0,0,86],
                          'armHand':[0,0,72],'hand':[0,0,10],'head':[0,0,115]}
    def pap(self,*a):return self.held
    def xyz(self,*a):return [0,0,0]
    def guard_world(self):pass
    def pause(self,*a):pass
    def remaining(self):return 30
    def publish(self,frame,*a):
        self.calls.append(copy.deepcopy(frame))
        if self.response:
            for key in ('shoulder','elbow','armHand','head'):
                self._reach_body[key][2]-=.7
    def reach_target(self,*a):return [0,0,0]


class ReachPostureTests(unittest.TestCase):
    columns=[[70,0,0],[0,0,70],[0,70,0]]
    def posture(self,b):return ReachPosture(b,b.frame,self.columns)

    def test_real_observed_body_lowering_restores_workspace_in_one_cm_steps(self):
        b=Fake();original=copy.deepcopy(b.frame)
        target,envelope=self.posture(b).ensure('0xFF001234','right',[0,0,0])
        self.assertEqual(target,[0,0,0]);self.assertGreater(len(b.calls),1)
        for i,frame in enumerate(b.calls,1):
            expected=copy.deepcopy(original);expected['hmd']['matrix'][7]-=.01*i
            for role in ('left','right'):self.assertEqual(frame[role],expected[role])
            self.assertAlmostEqual(frame['hmd']['matrix'][7],expected['hmd']['matrix'][7])
        self.assertLessEqual(envelope['shoulderToTargetMetres'],envelope['bodyEnvelopeRadiusMetres'])
        self.assertLessEqual(b.start-b.frame['hmd']['matrix'][7],.75)

    def test_reachable_target_has_no_body_or_input_mutation(self):
        b=Fake();self.posture(b).ensure('R','right',[0,0,65]);self.assertEqual(b.calls,[])

    def test_held_object_or_unavailable_held_identity_prevents_body_motion(self):
        for held in ({'formId':'0xFF001234'},False,{},'unknown'):
            b=Fake();b.held=held
            with self.subTest(held=held),self.assertRaisesRegex(ValueError,'hands empty'):
                self.posture(b).ensure('R','right',[0,0,0])
            self.assertEqual(b.calls,[])

    def test_upper_horizontal_and_extreme_targets_do_not_trigger_crouch(self):
        for target in ([200,0,100],[200,0,-100],[0,0,200]):
            b=Fake()
            with self.subTest(target=target),self.assertRaises(ValueError):
                self.posture(b).ensure('R','right',target)
            self.assertEqual(b.calls,[])

    def test_publication_without_observed_head_response_is_not_replayed(self):
        b=Fake();b.response=False
        with patch('time.monotonic',side_effect=[0,0,3]),self.assertRaisesRegex(ValueError,'no observed body lowering'):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(len(b.calls),1)

    def test_non_neutral_other_controller_input_cannot_be_silently_released(self):
        b=Fake();b.frame['left']['controller']['pressed']=4
        with self.assertRaisesRegex(ValueError,'neutral controller inputs'):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(b.calls,[])
        self.assertEqual(b.frame['left']['controller']['pressed'],4)

    def test_floor_height_and_total_body_travel_stop_without_extra_publication(self):
        b=Fake();b._reach_body['head']=[0,0,42]
        with self.assertRaisesRegex(ValueError,'head too low'):self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(b.calls,[])
        b=Fake();p=self.posture(b);b.frame['hmd']['matrix'][7]-=.75
        with self.assertRaisesRegex(ValueError,'bounded body lowering'):p.ensure('R','right',[0,0,0])
        self.assertEqual(b.calls,[])

    def test_invalid_native_arm_geometry_never_authorizes_crouch(self):
        b=Fake();b._reach_body['elbow']=b._reach_body['shoulder']
        with self.assertRaisesRegex(ValueError,'arm geometry'):self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(b.calls,[])

    def test_unexpected_consumed_body_motion_stops_after_one_publication(self):
        b=Fake();original=b.publish
        def publish(*a):original(*a);b._reach_body['head'][0]+=10
        b.publish=publish
        with self.assertRaisesRegex(ValueError,'differs from bounded vertical'):self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(len(b.calls),1)


if __name__=='__main__':unittest.main()
