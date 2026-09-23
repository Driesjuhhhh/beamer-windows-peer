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


if __name__ == "__main__":
    unittest.main()
