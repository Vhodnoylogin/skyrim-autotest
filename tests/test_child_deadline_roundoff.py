"""Use real deadline producers/consumers on simulated Windows coarse clock ticks."""
import math
import unittest
from unittest.mock import patch

from skyrim_autotest import interactive_bindings as bindings, npc_persistence


class ChildDeadlineRoundoffTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = patch.object(bindings.time, 'monotonic', side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)

    def consume(self, deadline, maximum):
        if maximum == 30:
            bindings.bounded_deadline(deadline)
        npc_persistence._deadline(deadline, maximum)

    def child(self, parent, maximum):
        child = bindings.child_deadline(parent, maximum)
        self.assertLessEqual(child, parent)
        self.assertTrue(0 < child - self.now <= maximum)
        self.consume(child, maximum)
        return child

    def test_real_helper_passes_same_tick_at_reported_power_crossing(self):
        self.now = 16354.006
        parent = self.now + 120
        self.assertGreater((self.now + 30) - self.now, 30)
        self.child(parent, 30)
        self.assertEqual(parent, self.now + 120)

    def test_millisecond_ticks_crossing_power_boundary_for_both_caps(self):
        for maximum in (30, 90):
            overshoots = 0
            for milliseconds in range(30000):
                self.now = 16384 - maximum + milliseconds / 1000
                overshoots += (self.now + maximum) - self.now > maximum
                self.child(self.now + 180, maximum)
            self.assertGreater(overshoots, 0)

    def test_integer_and_fractional_coarse_ticks_across_multiple_powers(self):
        for exponent in (5, 10, 14, 20, 30, 40, 48, 52, 55, 56):
            for maximum in (30, 90):
                for offset in (-maximum, -maximum + .006, -.015625, 0, .015625, .123):
                    self.now = float(2 ** exponent) + offset
                    with self.subTest(exponent=exponent, maximum=maximum, now=self.now):
                        child = self.child(self.now + 180, maximum)
                        # The next validator can read the same tick or a later tick.
                        self.now += .015625
                        self.consume(child, maximum)

    def test_short_parent_is_preserved_exactly_including_next_float(self):
        for now in (0.0, 1000.123, 16354.006, float(2 ** 40)):
            self.now = now
            for parent in (math.nextafter(now, math.inf), now + .125, now + 12):
                for maximum in (30, 90):
                    with self.subTest(now=now, parent=parent, maximum=maximum):
                        self.assertEqual(self.child(parent, maximum), parent)

    def test_parent_expiry_between_creation_and_consumption_never_refreshes(self):
        for maximum in (30, 90):
            self.now = 16354.006
            parent = self.now + .125
            child = self.child(parent, maximum)
            self.now = parent
            with self.assertRaises(ValueError):
                self.consume(child, maximum)
            with self.assertRaises(ValueError):
                bindings.child_deadline(parent, maximum)
            self.assertEqual(child, parent)

    def test_unrepresentable_positive_child_budget_refuses(self):
        for now in (float(2 ** 59), float(2 ** 60), 1e300):
            self.now = now
            for maximum in (30, 90):
                with self.subTest(now=now, maximum=maximum), self.assertRaises(ValueError):
                    bindings.child_deadline(math.nextafter(now, math.inf), maximum)

    def test_consumers_still_reject_even_one_float_above_public_caps(self):
        self.now = 1000.0
        for maximum in (30, 90):
            deadline = math.nextafter(self.now + maximum, math.inf)
            self.assertGreater(deadline - self.now, maximum)
            with self.assertRaises(ValueError):
                self.consume(deadline, maximum)
            self.consume(self.now + maximum, maximum)


if __name__ == '__main__':
    unittest.main()
