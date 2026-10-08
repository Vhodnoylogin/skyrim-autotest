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
        self._reach_rig={'head':[0,0,120],'left':[-20,0,10],'right':[20,0,10]}
    def pap(self,script,function,*a,**k):return False if function=='IsSneaking' else self.held
    def xyz(self,*a):return [0,0,0]
    def guard_world(self):pass
    def pause(self,*a):pass
    def remaining(self):return 30
    def publish(self,frame,*a):
        self.calls.append(copy.deepcopy(frame))
        if self.response:
            self._reach_rig['head'][2]-=.7
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

    def test_common_vertical_rig_shift_is_not_misread_as_large_hmd_input(self):
        b=Fake();original=b.publish
        def publish(*a):
            original(*a)
            if len(b.calls)==1:
                for point in b._reach_rig.values():point[2]-=14
                for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=14
        b.publish=publish
        with patch('time.monotonic',side_effect=[i*.1 for i in range(1000)]):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertGreater(len(b.calls),0)

    def test_missing_rig_and_disagreeing_wands_never_prove_crouch_consumption(self):
        b=Fake();b._reach_rig=None
        with self.assertRaisesRegex(ValueError,'rig origins unavailable'):self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(b.calls,[])
        b=Fake();original=b.publish
        def publish(*a):original(*a);b._reach_rig['left'][2]-=7
        b.publish=publish
        with self.assertRaisesRegex(ValueError,'controllers disagree'):self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(len(b.calls),1)

    def test_common_rig_motion_still_obeys_actual_body_and_player_bounds(self):
        b=Fake();original=b.publish
        def publish(*a):
            original(*a)
            for point in b._reach_rig.values():point[2]-=56
            for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=56
        b.publish=publish
        with self.assertRaisesRegex(ValueError,'total posture bound'):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(len(b.calls),1)

    def test_legitimate_rig_transition_may_settle_after_two_seconds_without_republication(self):
        b=Fake();publish=b.publish;reads=[]
        def command(*a):
            publish(*a)
            if len(b.calls)==1:
                for point in b._reach_rig.values():point[2]-=14
                for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=14
        def read(*a):
            reads.append(len(b.calls))
            if len(reads)<=7:
                for point in b._reach_rig.values():point[2]-=.5
                for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=.5
            return [0,0,0]
        b.publish=command;b.reach_target=read
        with patch('time.monotonic',side_effect=[i*.3 for i in range(1000)]):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(reads[:9],[1]*9)

    def test_original_remaining_deadline_caps_transition_wait(self):
        b=Fake();b.remaining=lambda:.5;publish=b.publish;reads=[]
        def command(*a):
            publish(*a)
            for point in b._reach_rig.values():point[2]-=14
            for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=14
        def read(*a):
            reads.append(1)
            for point in b._reach_rig.values():point[2]-=.5
            for key in ('head','shoulder','elbow','armHand'):b._reach_body[key][2]-=.5
            return [0,0,0]
        b.publish=command;b.reach_target=read
        with patch('time.monotonic',side_effect=[i*.2 for i in range(1000)]),self.assertRaisesRegex(ValueError,'transition did not settle'):
            self.posture(b).ensure('R','right',[0,0,0])
        self.assertEqual(len(b.calls),1)
        b=Fake();b.xyz=lambda *a:([0,0,0] if not b.calls else [7,0,0])
        with self.assertRaisesRegex(ValueError,'Player origin moved'):
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
