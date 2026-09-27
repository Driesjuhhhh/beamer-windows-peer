import unittest

try:
    import edge_glow
except ImportError:  # PySide6 is only in the Windows build venv
    edge_glow = None


@unittest.skipIf(edge_glow is None, "PySide6 is not installed")
class BeamMathsTests(unittest.TestCase):
    def test_comet_travels_faster_as_pressure_builds(self):
        self.assertEqual(edge_glow.traverse_seconds(0.0), edge_glow.SLOW_TRAVERSE_S)
        self.assertAlmostEqual(edge_glow.traverse_seconds(1.0), edge_glow.FAST_TRAVERSE_S)
        self.assertLess(edge_glow.traverse_seconds(0.7), edge_glow.traverse_seconds(0.2))

    def test_edge_is_brightest_at_the_comet_and_dim_away_from_it(self):
        self.assertEqual(edge_glow.comet_alpha(0.5, 0.5, 0.0), 1.0)
        self.assertEqual(edge_glow.comet_alpha(0.0, 0.5, 0.0), edge_glow.BEAM_BASE)

    def test_breakthrough_lights_the_whole_edge(self):
        self.assertEqual(edge_glow.comet_alpha(0.0, 0.5, 1.0), 1.0)


@unittest.skipIf(edge_glow is None, "PySide6 is not installed")
class GlowStateTests(unittest.TestCase):
    def test_a_breakthrough_flashes_then_fades_out(self):
        state = edge_glow.GlowState()
        state.push(0.6, False)
        state.push(1.0, True)
        self.assertEqual((state.pressure, state.flash, state.finish), (0.0, 1.0, 1.0))
        self.assertTrue(state.step(0.1, stale=True))
        self.assertFalse(state.step(5.0, stale=True))

    def test_pressure_holds_while_the_push_keeps_arriving(self):
        state = edge_glow.GlowState()
        state.push(0.5, False)
        state.step(0.2, stale=False)
        self.assertEqual(state.pressure, 0.5)


@unittest.skipIf(edge_glow is None, "PySide6 is not installed")
class PreviewScriptTests(unittest.TestCase):
    def test_the_push_builds_goes_through_and_rests(self):
        self.assertEqual(edge_glow.preview_frame(0.0), (0.0, "push"))
        level, phase = edge_glow.preview_frame(edge_glow.PUSH_S * 0.9)
        self.assertEqual(phase, "push")
        self.assertGreater(level, 0.8)
        self.assertEqual(edge_glow.preview_frame(edge_glow.PUSH_S + 0.1), (0.0, "after"))
        self.assertEqual(edge_glow.preview_frame(edge_glow.PUSH_S + edge_glow.AFTER_S + 0.1), (0.0, "rest"))

    def test_it_loops(self):
        loop = edge_glow.PUSH_S + edge_glow.AFTER_S + edge_glow.REST_S
        self.assertEqual(edge_glow.preview_frame(loop + 0.5), edge_glow.preview_frame(0.5))


if __name__ == "__main__":
    unittest.main()
