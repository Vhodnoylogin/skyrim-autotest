import copy
import unittest
from unittest.mock import patch
from skyrim_autotest import body_stroke,body_scene,platform,hardware


class StrokeTests(unittest.TestCase):
    def request(self):
        return {'action':'grip_and_withdraw_from_body_slot','hand':'right','slot':13,'grip':'closed',
                'offset':{'units':'metres','xyz':[0,0,0]},'targetBasis':body_scene.TARGET_BASIS,
                'avoidMouth':True,'withdrawal':{'units':'metres','xyz':[0,0,-.3]},
                'motionSeconds':1.25,'durationSeconds':.2}

    def run_stroke(self,req=None,overhead=.005,head=None,budget=10):
        class Backend:
            def __init__(self):
                self.clock=0.;self.frames=[];self.logs=[];self.s=self
            def log(self,*a,**kw):self.logs.append((a,kw))
            def remaining(self):return budget-self.clock
            def pause(self,n):self.clock+=n
            def publish(self,f,d):self.frames.append(copy.deepcopy(f));self.clock+=overhead;return {'published':True}
        b=Backend();start=hardware.neutral();start['left']['controller']['pressed']=4
        with patch.object(body_stroke.time,'monotonic',side_effect=lambda:b.clock):
            body_stroke.withdraw(b,req or self.request(),start,[[70,0,0],[0,70,0],[0,0,70]],
                                 [0,0,30],[0,0,15],[0,0,0],head or [0,0,40],[0,0,0])
        return b,start

    def test_incremental_stroke_keeps_other_hand_head_and_closed_grip(self):
        b,start=self.run_stroke();previous=start
        self.assertEqual(len(b.frames),31)
        for f in b.frames:
            self.assertEqual(f['left'],start['left']);self.assertEqual(f['hmd'],start['hmd'])
            self.assertEqual(f['right']['controller']['pressed'],4)
            self.assertLessEqual(abs(f['right']['matrix'][11]-previous['right']['matrix'][11]),.0100001)
            previous=f
        self.assertAlmostEqual(b.frames[-1]['right']['matrix'][11],start['right']['matrix'][11]-.3)
        issued=[x[1] for x in b.logs if x[0]==('platform-body-withdrawal-issued',)][0]
        self.assertLess(issued['elapsedSeconds'],1.25)
        self.assertIsNone(issued['observedGameplaySuccess'])

    def test_slow_publication_fails_without_replay_or_deadline_extension(self):
        with self.assertRaisesRegex(TimeoutError,'motion budget'):self.run_stroke(overhead=.1)

    def test_crossing_mouth_or_extreme_reach_rejected_before_any_edge(self):
        for head,displacement in (([0,0,-10],[0,0,-.3]),([0,0,40],[0,0,-2])):
            req=self.request();req['withdrawal']['xyz']=displacement
            with self.subTest(displacement=displacement),self.assertRaises(ValueError):self.run_stroke(req,head=head)

    def test_no_time_for_whole_stroke_rejected(self):
        with self.assertRaisesRegex(TimeoutError,'Insufficient'):self.run_stroke(budget=1)

    def test_withdrawal_workspace_uses_tp_hand_independent_of_fp_servo_hand(self):
        # A distant physical hand cannot lengthen the actual body arm chain.
        b=type('Backend',(),{'remaining':lambda self:10})()
        with self.assertRaisesRegex(ValueError,'body reach envelope'):
            body_stroke.withdraw(b,self.request(),hardware.neutral(),[[70,0,0],[0,70,0],[0,0,70]],
                                 [0,0,30],[0,0,15],[0,0,-300],[0,0,40],[0,0,0])

    def test_public_contract_rejects_unsafe_or_ambiguous_requests(self):
        req=self.request();platform.validate({'operation':'controller.perform','request':req})
        for change in ({'grip':'open'},{'motionSeconds':0},{'motionSeconds':True},
                       {'withdrawal':{'units':'metres','xyz':[0,0,0]}},
                       {'withdrawal':{'units':'metres','xyz':[0,0,-.6]},'motionSeconds':.25},
                       {'unexpected':1}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                platform.validate({'operation':'controller.perform','request':dict(req,**change)})

    def test_combined_action_keeps_grip_open_until_all_readiness_and_geometry_reads(self):
        class Backend:
            def __init__(self):
                self.s=self;self.events=[];self.state={};self.pose=hardware.neutral();self.end=100
            def frame(self):return copy.deepcopy(self.pose)
            def hand_xyz(self,hand):
                return [self.pose[hand]['matrix'][i] for i in (3,7,11)]
            def publish(self,frame,duration):
                self.pose=copy.deepcopy(frame);self.events.append(('publish',frame['right']['controller']['pressed']))
                return {}
            def pause(self,n):pass
            def call(self,tool,args):self.events.append(('read',self.pose['right']['controller']['pressed']));return {}
            def recover_input_gate(self,menus):pass
            def log(self,*a,**kw):pass
        b=Backend();req=self.request();b.pose['right']['controller']['pressed']=4
        def centres(backend,*args):
            self.assertEqual(backend.pose['right']['controller']['pressed'],0)
            point=backend.hand_xyz('right');nodes={
                ('NPC R UpperArm [RUar]',False):{'translation':[point[0],point[1]+.3,point[2]]},
                ('NPC R Forearm [RLar]',False):{'translation':[point[0],point[1]+.15,point[2]]},
                ('NPC R Hand [RHnd]',False):{'translation':point},
                ('NPC R Hand [RHnd]',True):{'translation':point},
                (body_scene.HEAD,False):{'translation':[point[0],point[1]+.5,point[2]]}}
            return {13:point},nodes
        def withdraw(*args):
            self.assertEqual(b.pose['right']['controller']['pressed'],0)
            b.events.append(('stroke',4));return {'inputIssued':True}
        with patch('skyrim_autotest.vr_probe.ensure_owned_focus'),patch('skyrim_autotest.tracking_basis.calibrate',return_value=([[1,0,0],[0,1,0],[0,0,1]],b.hand_xyz('right'))),patch.object(body_scene,'centres',side_effect=centres),patch.object(body_stroke,'withdraw',side_effect=withdraw):
            self.assertTrue(body_scene.pose(b,req)['inputIssued'])
        stroke=next(i for i,x in enumerate(b.events) if x[0]=='stroke')
        self.assertTrue(any(x[0]=='read' for x in b.events[:stroke]))
        self.assertTrue(all(x[1]==0 for x in b.events[:stroke] if x[0]=='publish'))


if __name__=='__main__':unittest.main()
