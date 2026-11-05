import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verifier_count as vc  # noqa: E402


class VerifierCount(unittest.TestCase):
    def test_margin_is_five_at_the_target(self):
        r = vc.derive(Fraction(1, 1000))
        self.assertEqual(r['margin'], 5)
        self.assertEqual([row['smallestCount'] for row in r['perMaxAssignments']], [7, 10, 14])
        for row in r['perMaxAssignments']:
            self.assertLessEqual(row['pLastUnderRule'], 1e-3)
            self.assertGreater(row['pLastOneBelow'], 1e-3)

    def test_former_bound(self):
        self.assertAlmostEqual(float(vc.p_last(8, 9, 9)), (8 / 9) ** 9)
        self.assertGreater(float(vc.p_last(8, 9, 9)), 0.34)

    def test_simulation_matches_the_formula(self):
        self.assertAlmostEqual(vc.monte_carlo(3, 14, 14, 50000, 1), float(vc.p_last(8, 14, 14)), delta=4e-4)


if __name__ == '__main__':
    unittest.main()
