import itertools
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import d2_deter as dd  # noqa: E402
import engine  # noqa: E402


class Released(unittest.TestCase):
    blocks = [10, 20, 30]
    values = [1, 2, 4]

    def test_boundary_released_when_equal(self):
        # hold 100: releases at 110, 120, 130; a failure at 120 frees the first two, the third is frozen
        self.assertEqual(dd.released_value(self.blocks, self.values, 120, 100, 1000), 3)
        self.assertEqual(dd.released_value(self.blocks, self.values, 119, 100, 1000), 1)
        self.assertEqual(dd.released_value(self.blocks, self.values, 129, 100, 1000), 3)

    def test_no_failure_counts_up_to_the_window_end(self):
        self.assertEqual(dd.released_value(self.blocks, self.values, None, 100, 1000), 7)
        self.assertEqual(dd.released_value(self.blocks, self.values, None, 100, 125), 3)
        self.assertEqual(dd.released_value(self.blocks, self.values, None, 100, 109), 0)

    def test_failure_before_any_release_gives_zero(self):
        self.assertEqual(dd.released_value(self.blocks, self.values, 50, 100, 1000), 0)

    def test_same_boundary_as_the_replayer(self):
        # evaluate_failures freezes an entry when blocks > f - hold, i.e. releases it when blocks + hold <= f
        blocks = np.array([10, 20, 30], dtype=np.int64)
        values = np.array([1, 2, 4], dtype=np.int64)
        for f in (109, 110, 120, 129, 130, 500):
            r = engine.evaluate_failures(blocks, values, np.array([f]), hold=100, reentry=0, claim_probs=[1], share=0,
                                         rng=None, start=0, end=1000, fw_edges=np.array([0, 1000]), claim_window=0)[0]
            by_replayer = int(values.sum()) - r['principal'] - int(values[blocks > f].sum())
            self.assertEqual(dd.released_value(blocks, values, f, 100, 1000), by_replayer, f)


class FirstFailure(unittest.TestCase):
    def test_earliest_detected_case_plus_delay(self):
        self.assertEqual(dd.first_failure([100, 200, 300], [False, True, True], 50, 1000), 250)

    def test_none_detected(self):
        self.assertIsNone(dd.first_failure([100, 200], [False, False], 50, 1000))
        self.assertIsNone(dd.first_failure([], [], 50, 1000))

    def test_failure_after_window_is_dropped(self):
        self.assertIsNone(dd.first_failure([990], [True], 50, 1000))
        self.assertEqual(dd.first_failure([950], [True], 50, 1000), 1000)

    def test_detection_threshold_is_strict(self):
        self.assertEqual(list(dd.detections([0.39, 0.4, 0.41], 0.4)), [True, False, False])


def brute_force(blocks, values, s_prob, f_sale, p0, hold, end):
    """E[X] by enumerating every sampled-and-detected pattern of the sales (probability p0 * s each)."""
    n = len(blocks)
    total = 0.0
    for pattern in itertools.product((0, 1), repeat=n):
        prob = 1.0
        for hit, s in zip(pattern, s_prob):
            prob *= p0 * s if hit else 1 - p0 * s
        f = min((f_sale[i] for i in range(n) if pattern[i]), default=None)
        if f is not None and f > end:
            f = None
        total += prob * dd.released_value(blocks, values, f, hold, end)
    return total


class ExactExpectation(unittest.TestCase):
    def test_matches_enumeration(self):
        blocks = np.array([5, 9, 14, 14, 30, 41])
        values = np.array([3, 1, 4, 1, 5, 9])
        s = np.array([0.5, 1.0, 0.25, 0.75, 0.1, 0.6])
        f_sale = blocks + 12          # a failure 12 blocks after the sale
        for p0, hold, end in ((0.4, 20, 60), (0.35, 20, 60), (0.4, 7, 45), (0.4, 40, 60), (0.9, 15, 50)):
            got = dd.exact_expectation(blocks, values, s, f_sale, p0, hold, end)
            want = brute_force(list(blocks), values, s, list(f_sale), p0, hold, end)
            self.assertAlmostEqual(got, want, places=9, msg=(p0, hold, end))

    def test_single_sale_by_hand(self):
        # one sale of value 10 at block 0, hold 5, end 100: its own failure (block 3) precedes its release (block 5),
        # so it is released with probability 1 - 0.4 * 0.5 = 0.8
        self.assertAlmostEqual(dd.exact_expectation([0], [10], [0.5], [3], 0.4, 5, 100), 8.0)

    def test_two_sales_by_hand(self):
        # sale 0 (value 1) at block 0, sale 1 (value 2) at block 1, hold 10, failure of a sale at its block + 4.
        # sale 0 is released at 10; the failures at 4 (its own) and 5 (sale 1's) both precede it.
        # sale 1 is released at 11; the failures at 4 and 5 both precede it, so both factors count there too.
        p0, s0, s1 = 0.4, 0.5, 0.25
        want = 1 * (1 - p0 * s1) * (1 - p0 * s0) + 2 * (1 - p0 * s0) * (1 - p0 * s1)
        # sale 0: failures before 10 are sale 0 (4) and sale 1 (5) -> both factors
        got = dd.exact_expectation([0, 1], [1, 2], [s0, s1], [4, 5], p0, 10, 100)
        self.assertAlmostEqual(got, want)

    def test_nothing_released_before_the_window_end(self):
        self.assertEqual(dd.exact_expectation([95], [10], [0.5], [99], 0.4, 10, 100), 0.0)


class Simulation(unittest.TestCase):
    def test_simulated_mean_matches_the_closed_form(self):
        rng = np.random.default_rng(7)
        blocks = np.sort(rng.integers(0, 300, 40))
        values = rng.integers(1, 5, 40)
        s = rng.choice([0.2, 0.5, 1.0], 40)
        f_sale = blocks + 12
        hold, end, p0 = 30, 320, 0.4
        exact = dd.exact_expectation(blocks, values, s, f_sale, p0, hold, end)
        total, reps = 0.0, 20000
        for _ in range(reps):
            hit = rng.random(40) < p0 * s
            f = dd.first_failure(f_sale, hit, 0, end)
            total += dd.released_value(blocks, values, f, hold, end)
        self.assertAlmostEqual(total / reps, exact, delta=0.05 * exact)


class ModelAddress(unittest.TestCase):
    """model_address on a hand-made replay result: cap variant and settlement variant by hand."""

    P = dict(epochOrigin=0, epochBlocks=100, deadlineConfig=dict(anchorBlocks=3), beaconDelayBlocks=4)

    def test_open_blocks_follow_the_epoch(self):
        # epoch of block 250 is 2; case_open_block = origin + 4 * 100 - 1 + 3 + 1 + 4 + 1
        got = dd.sale_open_blocks([250, 10], self.P, 0, 0)
        want = [engine.case_open_block(2, self.P), engine.case_open_block(0, self.P)]
        self.assertEqual(list(got), want)

    def test_cap_variant_counts_sales_at_the_cap(self):
        blocks = np.array([0, 50, 120, 400], dtype=np.int64)
        values = np.array([10, 20, 30, 40], dtype=np.int64)
        arr = dict(blocks=blocks, values=values, cases=np.zeros(0, dtype=np.int64), case_settled=np.zeros(0, dtype=np.int64),
                   s_prob=np.ones(4))
        m = dd.model_address(arr, seed=1, address='0xabc', p=self.P, start=0, end=1000, local_origin=0, delay=7,
                             hold=200, l_actual=300, vmax=200000)
        # no sampled case: the main model never fails; every sale released before 1000 (400 + 200 = 600)
        self.assertEqual(m['main'], (100, -1))
        self.assertEqual(m['p035'], (100, -1))
        self.assertEqual(m['settle'], (100, -1))
        # cap variant: every sale replaced by 200000; failure iff some uniform is below 0.4
        u = dd.draw_u(1, 'deter-cap', '0xabc', 4)
        opens = dd.sale_open_blocks(blocks, self.P, 0, 0)
        f = dd.first_failure(opens, u < 0.4, 7, 1000)
        want = dd.released_value(blocks, np.full(4, 200000), f, 200, 1000)
        self.assertEqual(m['cap'], (want, -1 if f is None else f))

    def test_main_variant_by_hand(self):
        blocks = np.array([0, 50, 120, 400], dtype=np.int64)
        values = np.array([10, 20, 30, 40], dtype=np.int64)
        cases = np.array([150, 500], dtype=np.int64)
        settled = np.array([120, 400], dtype=np.int64)
        arr = dict(blocks=blocks, values=values, cases=cases, case_settled=settled, s_prob=np.ones(4))
        u = dd.draw_u(5, 'deter', '0xabc', 2)
        m = dd.model_address(arr, seed=5, address='0xabc', p=self.P, start=0, end=1000, local_origin=0, delay=7,
                             hold=100, l_actual=30, vmax=200000)
        for name, p0 in (('main', 0.4), ('p035', 0.35)):
            det = u < p0
            f = None if not det.any() else int(cases[det].min()) + 7
            f = f if f is not None and f <= 1000 else None
            t = 1000 if f is None else f
            want = int(values[blocks + 100 <= t].sum())
            self.assertEqual(m[name], (want, -1 if f is None else f))
        det = u < 0.4
        f = None if not det.any() else int(settled[det].min()) + 30
        t = 1000 if f is None else f
        self.assertEqual(m['settle'][0], int(values[blocks + 100 <= t].sum()))


class Registration(unittest.TestCase):
    def test_wrong_hash_aborts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a.md', Path(d) / 'h.txt'
            a.write_text('changed')
            b.write_text('x ' + dd.REGISTERED['prereg_sha256'])
            with self.assertRaises(SystemExit):
                dd.check_prereg(a, b)


if __name__ == '__main__':
    unittest.main()
