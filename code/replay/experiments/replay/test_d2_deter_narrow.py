"""Tests of the narrow-freeze deterrence model (d2_deter_narrow.py)."""
import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import d2_deter as dd  # noqa: E402
import d2_deter_narrow as dn  # noqa: E402
import engine  # noqa: E402


def random_case(rng, n, hold, end_pad=0):
    blocks = np.sort(rng.integers(0, 60, size=n)).astype(np.int64)
    values = rng.integers(1, 10, size=n).astype(np.int64)
    # failure block of each sale if it were sampled and detected: non-decreasing, after the sale
    gap = rng.integers(1, hold, size=n)
    f_sale = np.maximum.accumulate(blocks + gap).astype(np.int64)
    s_prob = rng.uniform(0.1, 1.0, size=n)
    end = int(blocks.max() + hold + end_pad)
    return blocks, values, f_sale, s_prob, end


def episode(blocks, values, f_sale, hit, hold, end):
    """X of one outcome `hit` (sales that are sampled and detected) under both freezes."""
    if not hit.any():
        f = None
    else:
        f = int(f_sale[hit].min())
        if f > end:
            f = None
    if f is None:
        xn = dn.released_value_narrow(blocks, values, None, None, hold, end)
        xf = dd.released_value(blocks, values, None, hold, end)
        return xn, xf
    c = int(blocks[hit & (f_sale == f)].min())
    return (dn.released_value_narrow(blocks, values, f, c, hold, end),
            dd.released_value(blocks, values, f, hold, end))


class NarrowModelTest(unittest.TestCase):

    def test_tiny_constructed_case(self):
        # sales at 0, 10, 20, 30; hold 25; the sale at 20 fails at 40 (c = 20); window end 100
        blocks = np.array([0, 10, 20, 30])
        values = np.array([1, 2, 4, 8])
        # full: released iff s + 25 <= 40 -> sales 0, 10 -> 3
        self.assertEqual(dd.released_value(blocks, values, 40, 25, 100), 3)
        # narrow: 0, 10 released before f; 20 and 30 are at or after c and held at f -> frozen; nothing else -> 3
        self.assertEqual(dn.released_value_narrow(blocks, values, 40, 20, 25, 100), 3)
        # with hold 35: full releases only s + 35 <= 40 -> sale 0 -> 1; narrow also releases 10 later (10 < c) -> 3
        self.assertEqual(dd.released_value(blocks, values, 40, 35, 100), 1)
        self.assertEqual(dn.released_value_narrow(blocks, values, 40, 20, 35, 100), 3)
        # but not if its release falls after the window end
        self.assertEqual(dn.released_value_narrow(blocks, values, 40, 20, 35, 44), 1)
        # sales after f are not counted
        self.assertEqual(dn.released_value_narrow(np.array([0, 50]), np.array([1, 2]), 40, 0, 5, 100), 1)

    def test_no_failure_is_the_same_for_both(self):
        rng = np.random.default_rng(1)
        for _ in range(200):
            blocks, values, f_sale, s_prob, end = random_case(rng, 6, 30)
            self.assertEqual(dn.released_value_narrow(blocks, values, None, None, 30, end),
                             dd.released_value(blocks, values, None, 30, end))

    def test_matches_engine_narrow_lost(self):
        """Frozen set of the first failure equals engine.narrow_lost with that one failure."""
        rng = np.random.default_rng(2)
        for _ in range(500):
            hold = int(rng.integers(5, 40))
            blocks, values, f_sale, s_prob, end = random_case(rng, 8, hold, end_pad=50)
            j = int(rng.integers(0, len(blocks)))
            f, c = int(f_sale[j]), int(blocks[j])
            lost, _ = engine.narrow_lost(blocks, np.array([f]), np.array([c]), hold)
            before = blocks <= f
            expect = int(values[before & ~lost & ((blocks + hold <= f) | (blocks + hold <= end))].sum())
            # engine releases a not-lost entry at its own schedule; inside the episode only s <= f counts
            got = dn.released_value_narrow(blocks, values, f, c, hold, end)
            self.assertEqual(got, expect)

    def test_narrow_never_below_full(self):
        rng = np.random.default_rng(3)
        for _ in range(500):
            hold = int(rng.integers(5, 40))
            blocks, values, f_sale, s_prob, end = random_case(rng, 7, hold, end_pad=int(rng.integers(0, 40)))
            hit = rng.random(len(blocks)) < 0.4
            xn, xf = episode(blocks, values, f_sale, hit, hold, end)
            self.assertGreaterEqual(xn, xf)

    def test_closed_form_by_enumeration(self):
        """exact_expectation_narrow equals the expectation over every detection outcome (independent sales,
        P(hit_l) = p0 * s_l), and dd.exact_expectation does the same for the full freeze."""
        rng = np.random.default_rng(4)
        p0 = 0.4
        for trial in range(60):
            n = int(rng.integers(1, 9))
            hold = int(rng.integers(5, 50))
            blocks, values, f_sale, s_prob, end = random_case(rng, n, hold, end_pad=int(rng.integers(-20, 40)))
            end = max(end, int(blocks.max()))
            q = p0 * s_prob
            en = ef = 0.0
            for bits in itertools.product((0, 1), repeat=n):
                hit = np.array(bits, dtype=bool)
                pr = float(np.prod(np.where(hit, q, 1 - q)))
                xn, xf = episode(blocks, values, f_sale, hit, hold, end)
                en += pr * xn
                ef += pr * xf
            self.assertAlmostEqual(dn.exact_expectation_narrow(blocks, values, s_prob, f_sale, p0, hold, end), en,
                                   places=9, msg=f'narrow trial {trial}')
            self.assertAlmostEqual(dd.exact_expectation(blocks, values, s_prob, f_sale, p0, hold, end), ef,
                                   places=9, msg=f'full trial {trial}')

    def test_bound_holds_when_hold_exceeds_failure_delay(self):
        """With value-proportional sampling s = v / V and hold > max(f_l - s_l), E[X_narrow] <= V / p0."""
        rng = np.random.default_rng(5)
        V, p0 = 10.0, 0.4
        for _ in range(300):
            n = int(rng.integers(1, 40))
            blocks = np.sort(rng.integers(0, 500, size=n)).astype(np.int64)
            values = rng.integers(1, 11, size=n).astype(np.int64)
            f_sale = np.maximum.accumulate(blocks + rng.integers(1, 30, size=n)).astype(np.int64)
            hold = int((f_sale - blocks).max()) + 1
            e = dn.exact_expectation_narrow(blocks, values, values / V, f_sale, p0, hold, int(blocks.max() + hold))
            self.assertLessEqual(e, V / p0 + 1e-9)

    def test_first_failure_narrow_picks_smallest_sale_of_the_first_opening(self):
        opens = np.array([100, 100, 130, 100])
        settled = np.array([5, 3, 1, 7])
        det = np.array([True, False, True, True])
        f, c = dn.first_failure_narrow(opens, det, settled, 10, 1000)
        self.assertEqual((f, c), (110, 5))
        self.assertEqual(dn.first_failure_narrow(opens, det, settled, 10, 105), (None, None))
        self.assertEqual(dn.first_failure_narrow(opens, np.zeros(4, bool), settled, 10, 1000), (None, None))


if __name__ == '__main__':
    unittest.main()
