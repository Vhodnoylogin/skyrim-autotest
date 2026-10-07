import math
import unittest
from skyrim_autotest.platform_math import feedback_increment


class FeedbackTests(unittest.TestCase):
    columns=[[0,70,0],[0,0,70],[70,0,0]]

    def test_blocked_hand_does_not_integrate_repeated_forward_requests(self):
        command=[0,0,0]
        for _ in range(100):
            delta,meta=feedback_increment(self.columns,[0,0,0],[10,20,30],command,[10,20,30],[80,20,30])
            self.assertLessEqual(math.sqrt(sum(v*v for v in delta)),.01000001)
            command=[a+b for a,b in zip(command,delta)]
        self.assertAlmostEqual(command[2],.01)
        self.assertAlmostEqual(math.sqrt(sum(v*v for v in meta['trackingLeadMetres'])),.01)

    def test_following_hand_continues_across_large_distance_with_increment_bound(self):
        command=[.2,.3,.4];origin=list(command);baseline=[10,20,30];observed=list(baseline)
        for _ in range(60):
            delta,meta=feedback_increment(self.columns,origin,baseline,command,observed,[45,20,30])
            self.assertLessEqual(math.sqrt(sum(v*v for v in delta)),.01000001)
            command=[a+b for a,b in zip(command,delta)]
            observed=[baseline[i]+sum(self.columns[j][i]*(command[j]-origin[j]) for j in range(3)) for i in range(3)]
        self.assertAlmostEqual(observed[0],45)

    def test_existing_overdrive_unwinds_incrementally_and_preserves_finite_output(self):
        delta,meta=feedback_increment(self.columns,[0,0,0],[0,0,0],[0,0,.5],[0,0,0],[70,0,0])
        self.assertAlmostEqual(delta[2],-.01)
        self.assertEqual(meta['trackingLeadMetres'],[0,0,.5])
        with self.assertRaises(ValueError):feedback_increment(self.columns,[0,0,0],[0,0,0],[0,0,0],[float('nan'),0,0],[0,0,0])
