import unittest

from crossing import DECAY_S, CrossingEngine

BOUNDS = (0, 0, 1728, 1117)
RIGHT_X = 1727.0


def engine(**overrides):
    settings = dict(methods=("edge",), edge="right", resistance_px=120)
    settings.update(overrides)
    return CrossingEngine(**settings)


def drive(machine, x, y, dx, dy, times, bounds=BOUNDS, notch_range=None, dragging=False):
    """The pointer is already against an edge, so the OS keeps reporting it there while the
    deltas keep coming, 10ms apart. Returns the step that crossed, or the last one."""
    result = None
    for index in range(times):
        result = machine.feed(x, y, dx, dy, bounds, 1.0 + index * 0.01, notch_range, dragging)
        if result.crossed:
            break
    return result


def push_right(machine, times, dx=20, y=500.0, dragging=False):
    return drive(machine, RIGHT_X, y, dx, 0, times, dragging=dragging)


class TickStepsTests(unittest.TestCase):
    def test_which_quarter_ticks_are_felt(self):
        from crossing import tick_fires

        quarters = (0.25, 0.5, 0.75)
        self.assertTrue(all(tick_fires("quarters", p) for p in quarters))
        self.assertEqual([tick_fires("halves", p) for p in quarters], [False, True, False])
        self.assertFalse(any(tick_fires("breakthrough", p) for p in quarters))


class TouchingTests(unittest.TestCase):
    def test_touching_survives_pressure_draining_away_but_not_leaving(self):
        machine = engine()
        machine.feed(RIGHT_X, 500.0, 2, 0, BOUNDS, 1.0)
        # Half a second later with no outward travel: pressure has drained and released.
        step = machine.feed(RIGHT_X, 500.0, 0, 0, BOUNDS, 1.5)
        self.assertEqual(step.pressure, 0.0)
        self.assertIsNone(machine.pin)
        self.assertTrue(machine.touching)
        machine.feed(800.0, 500.0, -20, 0, BOUNDS, 1.6)
        self.assertFalse(machine.touching)


class ResistanceTests(unittest.TestCase):
    def test_outward_travel_accumulates_and_holds_the_pointer(self):
        machine = engine()
        first = machine.feed(RIGHT_X, 500.0, 20, 0, BOUNDS, 1.0)
        self.assertFalse(first.hold, "the first touch passes so the pointer visibly arrives")
        second = machine.feed(RIGHT_X, 500.0, 20, 0, BOUNDS, 1.01)
        self.assertTrue(second.hold)
        self.assertEqual(second.pin, (RIGHT_X, 500.0))
        self.assertEqual(second.mac_edge, "right")
        self.assertGreater(second.pressure, first.pressure)
        self.assertFalse(second.crossed)

    def test_arriving_at_the_edge_counts_only_the_overshoot(self):
        machine = engine()
        machine.feed(1700.0, 500.0, 0, 0, BOUNDS, 1.0)
        step = machine.feed(RIGHT_X, 500.0, 40, 0, BOUNDS, 1.01)
        self.assertAlmostEqual(machine.pressure, 13.0, places=3)
        self.assertFalse(step.hold)

    def test_pressure_decays_over_time(self):
        machine = engine()
        push_right(machine, 4)
        full = machine.pressure
        self.assertGreater(full, 0)
        self.assertLess(machine.pressure_at(1.03 + DECAY_S / 2), full / 120)
        self.assertEqual(machine.pressure_at(1.03 + DECAY_S * 2), 0.0)
        step = machine.feed(RIGHT_X, 500.0, 0, 0, BOUNDS, 1.03 + DECAY_S * 2)
        self.assertEqual(machine.pressure, 0.0)
        self.assertFalse(step.hold)

    def test_a_slow_lean_never_builds(self):
        machine = engine()
        step = push_right(machine, 200, dx=1)
        self.assertFalse(step.crossed)
        self.assertFalse(step.hold)

    def test_inward_movement_subtracts(self):
        machine = engine()
        push_right(machine, 4)
        before = machine.pressure
        step = machine.feed(RIGHT_X, 500.0, -30, 0, BOUNDS, 1.04)
        self.assertLess(machine.pressure, before)
        self.assertTrue(step.hold)
        released = machine.feed(RIGHT_X, 500.0, -200, 0, BOUNDS, 1.05)
        self.assertEqual(machine.pressure, 0.0)
        self.assertFalse(released.hold)
        self.assertIsNone(machine.pin)

    def test_movement_along_the_edge_does_not_count(self):
        machine = engine()
        push_right(machine, 3)
        before = machine.pressure
        machine.feed(RIGHT_X, 600.0, 0, 40, BOUNDS, 1.03)
        self.assertLess(machine.pressure, before, "only decay applied")

    def test_quarter_ticks_fire_once_each(self):
        machine = engine()
        ticks = 0
        for index in range(12):
            step = machine.feed(RIGHT_X, 500.0, 12, 0, BOUNDS, 1.0 + index * 0.005)
            ticks += step.tick
            if step.crossed:
                break
        self.assertTrue(step.crossed)
        self.assertEqual(ticks, 3)

    def test_a_quarter_boundary_does_not_tick_twice_when_decay_dips_under_it(self):
        machine = engine()
        machine.feed(RIGHT_X, 500.0, 30, 0, BOUNDS, 1.0)
        step = machine.feed(RIGHT_X, 500.0, 2, 0, BOUNDS, 1.02)
        self.assertLess(machine.pressure, 30.0)
        self.assertFalse(step.tick)
        step = machine.feed(RIGHT_X, 500.0, 10, 0, BOUNDS, 1.03)
        self.assertGreater(machine.pressure, 30.0)
        self.assertFalse(step.tick)


class BreakthroughTests(unittest.TestCase):
    def test_breakthrough_carries_the_windows_edge_and_offset(self):
        machine = engine()
        step = push_right(machine, 8, dx=30, y=558.0)
        self.assertTrue(step.crossed)
        self.assertEqual(step.edge, "left")
        self.assertEqual(step.mac_edge, "right")
        self.assertAlmostEqual(step.offset, 0.5, places=3)
        self.assertEqual(machine.pressure, 0.0)
        self.assertIsNone(machine.pin)

    def test_offset_is_measured_from_where_the_push_started(self):
        machine = engine()
        machine.feed(RIGHT_X, 0.0, 20, 0, BOUNDS, 1.0)
        machine.feed(RIGHT_X, 0.0, 20, 0, BOUNDS, 1.01)
        step = machine.feed(RIGHT_X, 900.0, 200, 0, BOUNDS, 1.02)
        self.assertTrue(step.crossed)
        self.assertEqual(step.offset, 0.0)

    def test_zero_resistance_switches_on_contact(self):
        machine = engine(resistance_px=0)
        step = machine.feed(RIGHT_X, 100.0, 1, 0, BOUNDS, 1.0)
        self.assertTrue(step.crossed)
        self.assertEqual(step.edge, "left")

    def test_decayed_pressure_cannot_cross_without_a_push(self):
        machine = engine(resistance_px=10)
        machine.feed(RIGHT_X, 100.0, 9, 0, BOUNDS, 1.0)
        step = machine.feed(RIGHT_X, 100.0, 0, 0, BOUNDS, 1.001)
        self.assertFalse(step.crossed)

    def test_each_edge_maps_to_its_opposite_with_the_right_offset(self):
        cases = {
            "left": ((0.0, 279.0), (-30, 0), "right", 0.25),
            "top": ((431.75, 0.0), (0, -30), "bottom", 0.25),
            "bottom": ((1295.25, 1116.0), (0, 30), "top", 0.75),
        }
        for edge, ((x, y), (dx, dy), windows_edge, offset) in cases.items():
            with self.subTest(edge=edge):
                machine = engine(edge=edge)
                step = drive(machine, x, y, dx, dy, 8)
                self.assertTrue(step.crossed)
                self.assertEqual(step.edge, windows_edge)
                self.assertAlmostEqual(step.offset, offset, places=3)

    def test_home_edge(self):
        machine = engine(edge="right")
        self.assertEqual(machine.home_edge(), "left")
        self.assertEqual(machine.home_edge("top"), "bottom")

    def test_shortcut_home_edge_follows_the_method_that_is_on(self):
        # `edge` stays "right" in config with the edge method off; it must not arm Windows' left.
        self.assertEqual(engine(methods=("shortcut", "notch"), edge="right").home_edge(), "bottom")
        self.assertEqual(engine(methods=("corner",), corner="top_left").home_edge(), "right")
        self.assertIsNone(engine(methods=("shortcut",)).home_edge())

    def test_arrival_point_sits_just_inside_the_edge(self):
        self.assertEqual(CrossingEngine.arrival_point("left", 0.5, BOUNDS), (2.0, 558.0))
        self.assertEqual(CrossingEngine.arrival_point("right", 0.0, BOUNDS), (1725.0, 0.0))
        self.assertEqual(CrossingEngine.arrival_point("top", 1.0, BOUNDS), (1727.0, 2.0))
        self.assertEqual(CrossingEngine.arrival_point("bottom", 0.5, BOUNDS), (863.5, 1114.0))
        self.assertEqual(CrossingEngine.arrival_point("left", 7.0, BOUNDS)[1], 1116.0)


class GuardTests(unittest.TestCase):
    def test_no_crossing_while_a_button_is_held(self):
        machine = engine()
        step = push_right(machine, 10, dx=40, dragging=True)
        self.assertFalse(step.crossed)
        self.assertFalse(step.hold)
        self.assertEqual(machine.pressure, 0.0)

    def test_dragging_is_allowed_when_the_block_is_off(self):
        machine = engine(block_while_dragging=False)
        step = push_right(machine, 10, dx=40, dragging=True)
        self.assertTrue(step.crossed)

    def test_an_internal_edge_between_two_mac_displays_never_triggers(self):
        wide = (0, 0, 1728 + 1920, 1117)
        machine = engine()
        step = drive(machine, RIGHT_X, 500.0, 40, 0, 10, bounds=wide)
        self.assertFalse(step.crossed)
        self.assertFalse(step.hold)
        self.assertEqual(machine.pressure, 0.0)

    def test_other_edges_are_inert(self):
        machine = engine(edge="right")
        step = drive(machine, 0.0, 500.0, -40, 0, 10)
        self.assertFalse(step.crossed)
        self.assertEqual(machine.pressure, 0.0)

    def test_shortcut_only_is_not_armed(self):
        self.assertFalse(engine(methods=("shortcut",)).armed)
        self.assertTrue(engine(methods=("shortcut", "notch")).armed)

    def test_reset_clears_the_push(self):
        machine = engine()
        push_right(machine, 4)
        machine.reset()
        self.assertEqual(machine.pressure, 0.0)
        self.assertEqual(machine.pressure_at(5.0), 0.0)


class CornerTests(unittest.TestCase):
    def test_diagonal_push_in_the_corner_box_crosses(self):
        machine = engine(methods=("corner",), corner="top_right")
        step = drive(machine, RIGHT_X, 0.0, 30, -30, 10)
        self.assertTrue(step.crossed)
        self.assertEqual(step.mac_edge, "right")
        self.assertEqual(step.edge, "left")
        self.assertEqual(step.offset, 0.0)
        self.assertEqual(step.via, "corner")

    def test_straight_push_in_the_corner_box_does_not_count(self):
        machine = engine(methods=("corner",), corner="top_right")
        step = drive(machine, RIGHT_X, 3.0, 40, 0, 10)
        self.assertFalse(step.crossed)
        self.assertEqual(machine.pressure, 0.0)

    def test_diagonal_push_outside_the_box_does_not_count(self):
        machine = engine(methods=("corner",), corner="top_right")
        step = drive(machine, RIGHT_X, 20.0, 30, -30, 10)
        self.assertFalse(step.crossed)
        self.assertEqual(machine.pressure, 0.0)

    def test_bottom_left_corner(self):
        machine = engine(methods=("corner",), corner="bottom_left")
        step = drive(machine, 0.0, 1116.0, -30, 30, 10)
        self.assertTrue(step.crossed)
        self.assertEqual(step.edge, "right")
        self.assertEqual(step.offset, 1.0)
        self.assertEqual(step.region, (0, 1109.0, 8.0, 8.0))


class NotchTests(unittest.TestCase):
    NOTCH = (771.0, 956.0)

    def test_push_up_within_the_notch_crosses(self):
        machine = engine(methods=("notch",))
        step = drive(machine, 860.0, 0.0, 0, -30, 10, notch_range=self.NOTCH)
        self.assertTrue(step.crossed)
        self.assertEqual(step.mac_edge, "top")
        self.assertEqual(step.edge, "bottom")
        self.assertEqual(step.region, (771.0, 0, 185.0, 1))
        self.assertEqual(step.via, "notch")

    def test_push_up_beside_the_notch_does_nothing(self):
        machine = engine(methods=("notch",))
        step = drive(machine, 400.0, 0.0, 0, -30, 10, notch_range=self.NOTCH)
        self.assertFalse(step.crossed)
        self.assertEqual(machine.pressure, 0.0)

    def test_no_notch_means_no_target(self):
        machine = engine(methods=("notch",))
        step = drive(machine, 860.0, 0.0, 0, -30, 10)
        self.assertFalse(step.crossed)


if __name__ == "__main__":
    unittest.main()
