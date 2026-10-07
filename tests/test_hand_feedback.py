import math
import unittest
from skyrim_autotest.platform_math import feedback_increment,TargetProgress


class FeedbackTests(unittest.TestCase):
    columns=[[0,70,0],[0,0,70],[70,0,0]]

    def test_blocked_hand_sideways_wobble_stops_before_further_commands(self):
        command=[0,0,0];guard=TargetProgress();issued=0
        for i in range(100):
            # The old movement-only guard renewed on this transverse motion.
            observed=[10,20+(.5 if i%2 else -.5),30]
            error=math.dist(observed,[80,20,30])/70
            if not guard.observe(error,i*.5):break
            delta,meta=feedback_increment(self.columns,[0,0,0],[10,20,30],command,observed,[80,20,30])
            self.assertLessEqual(math.sqrt(sum(v*v for v in delta)),.01000001)
            command=[a+b for a,b in zip(command,delta)];issued+=1
        self.assertEqual(issued,11)
        self.assertEqual(i,11)

    def test_changing_avatar_response_does_not_create_false_equilibrium(self):
        command=[0,0,0];observed=[0,0,0];guard=TargetProgress()
        for i in range(100):
            error=abs(35-observed[0])/70
            self.assertTrue(guard.observe(error,i*.4))
            if error<.001:break
            delta,meta=feedback_increment(self.columns,[0,0,0],[0,0,0],command,observed,[35,0,0])
            self.assertLessEqual(math.sqrt(sum(v*v for v in delta)),.01000001)
            command=[a+b for a,b in zip(command,delta)]
            m=command[2]
            actual=m if m<=.1 else .1+.7*(m-.1)
            observed=[70*actual,0,0]
        self.assertLess(abs(35-observed[0])/70,.001)

    def test_following_hand_continues_across_large_distance_with_increment_bound(self):
        command=[.2,.3,.4];origin=list(command);baseline=[10,20,30];observed=list(baseline)
        for _ in range(60):
            delta,meta=feedback_increment(self.columns,origin,baseline,command,observed,[45,20,30])
            self.assertLessEqual(math.sqrt(sum(v*v for v in delta)),.01000001)
            command=[a+b for a,b in zip(command,delta)]
            observed=[baseline[i]+sum(self.columns[j][i]*(command[j]-origin[j]) for j in range(3)) for i in range(3)]
        self.assertAlmostEqual(observed[0],45)

    def test_observed_overshoot_reverses_increment_and_rejects_nonfinite_output(self):
        delta,meta=feedback_increment(self.columns,[0,0,0],[0,0,0],[0,0,.5],[70,0,0],[0,0,0])
        self.assertAlmostEqual(delta[2],-.01)
        self.assertEqual(meta['trackingLeadMetres'],[0,0,-.5])
        with self.assertRaises(ValueError):feedback_increment(self.columns,[0,0,0],[0,0,0],[0,0,0],[float('nan'),0,0],[0,0,0])
