import unittest

from return_edge import CROSS, HOLD, PASS, Rect, ReturnEdge, arrival_position, edge_offset, union


class FakeClock:
    def __init__(self, now=0.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


# A 1080p monitor hanging off the left of a 1440p primary, so the bounding box
# starts at x=-1920 and the primary is not its origin.
LEFT = Rect(-1920, 200, 1920, 1080)
PRIMARY = Rect(0, 0, 2560, 1440)
ARRANGEMENT = [PRIMARY, LEFT]
BOUNDS = union(ARRANGEMENT)


class GeometryTests(unittest.TestCase):
    def test_union_spans_a_negative_origin(self):
        self.assertEqual(BOUNDS, Rect(-1920, 0, 4480, 1440))
        self.assertEqual(BOUNDS.right, 2559)
        self.assertEqual(BOUNDS.bottom, 1439)

    def test_offset_is_measured_along_the_edge_against_the_bounding_box(self):
        self.assertAlmostEqual(edge_offset(BOUNDS, "left", (-1920, 720)), 0.5)
        self.assertAlmostEqual(edge_offset(BOUNDS, "top", (-1920 + 1120, 0)), 0.25)
        self.assertEqual(edge_offset(BOUNDS, "right", (2559, 99999)), 1.0)

    def test_arrival_lands_on_the_monitor_owning_each_edge(self):
        # left: the monitor with the smallest x, offset against the whole box
        # then clamped into that monitor's own span.
        self.assertEqual(arrival_position(ARRANGEMENT, "left", 0.5), (-1920, 720))
        self.assertEqual(arrival_position(ARRANGEMENT, "left", 0.0), (-1920, 200))
        # right: the primary, at its last pixel column.
        self.assertEqual(arrival_position(ARRANGEMENT, "right", 0.5), (2559, 720))
        # top: the primary is the only monitor reaching y=0; 10% of 4480 from
        # x=-1920 is in the left monitor's column range, so it clamps to x=0.
        self.assertEqual(arrival_position(ARRANGEMENT, "top", 0.1), (0, 0))
        self.assertEqual(arrival_position(ARRANGEMENT, "top", 0.75), (1440, 0))
        # bottom: the primary reaches y=1439; the left monitor stops at 1279.
        self.assertEqual(arrival_position(ARRANGEMENT, "bottom", 1.0), (2559, 1439))


class PressureTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.edge = ReturnEdge("left", resistance_px=120, clock=self.clock)

    def feed(self, pointer, dx, dy=0, after=0.0):
        self.clock.advance(after)
        return self.edge.feed(ARRANGEMENT, pointer, dx, dy)

    def test_movement_away_from_the_edge_passes_through(self):
        self.assertEqual(self.feed((-1000, 500), -40).action, PASS)
        self.assertEqual(self.feed((-1920, 500), 5).action, PASS)
        self.assertEqual(self.edge.pressure, 0.0)

    def test_outward_push_at_the_edge_holds_and_accumulates(self):
        outcome = self.feed((-1920, 500), -30, 4)
        self.assertEqual(outcome.action, HOLD)
        self.assertAlmostEqual(outcome.pressure, 0.25)
        # Pinned to the edge; the lateral component still slides along it.
        self.assertEqual(outcome.position, (-1920, 504))
        outcome = self.feed((-1920, 504), -30)
        self.assertAlmostEqual(outcome.pressure, 0.5)

    def test_inward_movement_subtracts(self):
        self.feed((-1920, 500), -60)
        outcome = self.feed((-1920, 500), 24)
        self.assertEqual(outcome.action, PASS)
        self.assertAlmostEqual(self.edge.pressure, 0.3)

    def test_pressure_decays_to_nothing_over_400ms(self):
        self.feed((-1920, 500), -60)
        self.assertAlmostEqual(self.feed((-1920, 500), 0, after=0.2).pressure, 0.0)
        self.feed((-1920, 500), -60)
        self.assertAlmostEqual(self.feed((-1920, 500), 0, after=0.1).pressure, 0.25)

    def test_breakthrough_sends_the_opposite_edge_and_the_offset(self):
        self.feed((-1920, 720), -100)
        outcome = self.feed((-1920, 720), -20)
        self.assertEqual(outcome.action, CROSS)
        self.assertEqual(outcome.edge, "right")
        self.assertAlmostEqual(outcome.offset, 0.5)
        self.assertEqual(outcome.pressure, 1.0)
        # Disarmed until the Mac's next switch: deltas still in flight pass.
        self.assertFalse(self.edge.armed)
        self.assertEqual(self.feed((-1920, 720), -200).action, PASS)

    def test_zero_resistance_crosses_on_contact(self):
        edge = ReturnEdge("bottom", resistance_px=0, clock=self.clock)
        outcome = edge.feed(ARRANGEMENT, (100, 1439), 0, 1)
        self.assertEqual(outcome.action, CROSS)
        self.assertEqual(outcome.edge, "top")

    def test_a_shorter_monitors_outer_edge_counts(self):
        # The left monitor stops at y=1279, well short of the box's 1439, with
        # nothing below it: the pointer is stopped there, so it is a way home.
        edge = ReturnEdge("bottom", resistance_px=120, clock=self.clock)
        self.assertEqual(edge.feed(ARRANGEMENT, (-1000, 1279), 0, 50).action, HOLD)
        self.assertEqual(edge.feed(ARRANGEMENT, (1000, 1439), 0, 50).action, HOLD)
        top = ReturnEdge("top", resistance_px=120, clock=self.clock)
        self.assertEqual(top.feed(ARRANGEMENT, (-1000, 200), 0, -50).action, HOLD)

    def test_an_edge_shared_with_another_monitor_does_not_count(self):
        # x=0 on the primary meets the left monitor between y=200 and 1279.
        edge = ReturnEdge("left", resistance_px=120, clock=self.clock)
        self.assertEqual(edge.feed(ARRANGEMENT, (0, 500), -50, 0).action, PASS)
        self.assertEqual(edge.feed(ARRANGEMENT, (0, 100), -50, 0).action, HOLD)

    def test_rejects_an_unknown_edge(self):
        with self.assertRaises(ValueError):
            ReturnEdge("sideways")


if __name__ == "__main__":
    unittest.main()
