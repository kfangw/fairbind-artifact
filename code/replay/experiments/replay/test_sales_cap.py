"""Sales cap grid of the second edition (D2-7 (b)): the small buckets, the claim that a bucket admits at most S in a
span Lambda, and the least cap that rejects nothing in a record.
"""
import math
import random
from fractions import Fraction

import numpy as np

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import design2  # noqa: E402
import engine  # noqa: E402
import test_design2 as td  # noqa: E402
from d2_testlib import GRID, make2, trace_arrays  # noqa: E402


class SalesCapBuckets(unittest.TestCase):
    """D2-7 (b): the small buckets (q_S, r_S) and the claim that they admit at most S in a span Lambda."""
    LAM = 62_146

    def test_the_table_of_the_rules(self):
        want = {10: (1, 144), 30: (1, 466), 100: (4, 1544), 300: (13, 4618), 1000: (42, 15415)}
        for S, qr in want.items():
            self.assertEqual(design2.small_bucket(S, 3245, 137, self.LAM), qr, S)
        d = make2()
        self.assertEqual(d.lam, self.LAM)
        self.assertEqual({S: (d.cap_spec(S, 'x')['capacity'], d.cap_spec(S, 'x')['refill_ppm']) for S in want}, want)
        main = d.cap_spec(3245, 'x')
        self.assertEqual((main['capacity'], main['refill_ppm'], main['scale']), (137, 50_000, 1))
        triple = d.cap_spec(3 * 3245, 'x')
        self.assertEqual((triple['capacity'], triple['refill_ppm'], triple['scale'], triple['n']), (137, 50_000, 3, 3))

    def test_cap_q_rounds_half_up_and_is_at_least_one(self):
        self.assertEqual(design2.small_bucket(10, 3245, 137, self.LAM)[0], 1)       # 0.42 -> 1, never 0
        self.assertEqual(design2.small_bucket(3245, 3245, 137, self.LAM)[0], 137)
        # 2 * S * q + S_main over 2 * S_main is the half-up rounding of S * q / S_main
        for S in range(1, 3245, 37):
            exact = Fraction(S * 137, 3245)
            self.assertEqual(design2.small_bucket(S, 3245, 137, self.LAM)[0],
                             max(1, math.floor(exact + Fraction(1, 2))), S)

    def test_every_cap_admits_at_most_S_in_a_span_lambda(self):
        for S in GRID[:-1]:
            q, r = design2.small_bucket(S, 3245, 137, self.LAM)
            self.assertEqual(design2.cap_admits(S, q, r, self.LAM), S)           # ceil(q + r * Lambda) = S
            blocks = np.arange(3 * self.LAM, dtype=np.int64)                      # one settlement per block, from full
            admitted = engine.admit(blocks, q, r, 1, 0)
            c = np.r_[0, np.cumsum(admitted)]
            for width in (self.LAM, self.LAM + 1):
                worst = max(int(c[i + width] - c[i]) for i in range(0, len(blocks) - width, 997))
                self.assertLessEqual(worst, S, (S, width))
            self.assertEqual(int(c[self.LAM + 1] - c[0]), S - 1)                  # the first span is the tightest one

    def test_caps_grow_with_S(self):
        d = make2()
        specs = [d.cap_spec(S, 'x') for S in GRID]
        for lo, hi in zip(specs, specs[1:]):
            self.assertLessEqual(lo['capacity'], hi['capacity'])
            self.assertLess(lo['refill_ppm'], hi['refill_ppm'])
            self.assertLess(lo['k'], hi['k'])

    def test_off_grid_caps_are_refused(self):
        d = make2()
        for S in (0, 5, 11, 3000, 3246, 4000):
            with self.assertRaises(ValueError):
                d.cap_spec(S, 'x')
        with self.assertRaises(ValueError):
            make2(sales_cap=500)

    def test_lambda_follows_the_hold_period_and_the_window(self):
        self.assertEqual(make2().lam, 2 * 31_073)
        d = make2(chain='solana', block_seconds='0.4')
        self.assertEqual(d.hold, 155_365)
        self.assertEqual(d.lam, 310_730)


def brute_force_cap(d, blocks):
    """Least cap of the grid with zero rejection, by running the contract bucket of engine.admit."""
    blocks = np.sort(np.asarray(blocks, dtype=np.int64))
    if len(blocks) == 0:
        return d.no_record_cap
    for S in d.small_grid:
        s = d.cap_spec(S, 'x')
        if engine.admit(blocks, s['capacity'], s['refill_ppm'], 1, int(blocks[0])).all():
            return S
    n = 1
    while not engine.admit(blocks, d.main_capacity, d.refill_main, n, int(blocks[0])).all():
        n += 1
    return 3245 * n


class LeastCapWithoutRejection(unittest.TestCase):
    def test_traces_land_on_the_expected_grid_value(self):
        d = make2()
        plan = design2.CapPlan(d, 'auto-zero-reject')
        # q_S admits that many settlements in one block: 1, 1, 4, 13, 42, 137 for S = 10 ... 3245
        cases = {
            'a single settlement': ([100], 10),
            'two at once': ([5] * 2, 100),
            'four at once': ([5] * 4, 100),
            'five at once': ([5] * 5, 300),
            'thirteen at once': ([5] * 13, 300),
            'fourteen at once': ([5] * 14, 1000),
            'forty two at once': ([5] * 42, 1000),
            'forty three at once': ([5] * 43, 3245),
            'the main bucket exactly': ([5] * 137, 3245),
            'one more than the main bucket': ([5] * 138, 2 * 3245),
            'one per 100 blocks (10,000 ppm per block)': (list(range(0, 3000, 100)), 1000),
            'one per 5 blocks, 20 settlements': (list(range(0, 100, 5)), 1000),
        }
        for name, (blocks, want) in cases.items():
            S, how = plan.fit_S(np.array(blocks, dtype=np.int64), np.full(len(blocks), 10, dtype=np.int64))
            self.assertEqual(S, brute_force_cap(d, blocks), name)
            self.assertEqual(S, want, name)

    def test_random_traces_agree_with_the_bucket(self):
        rng = random.Random(12)
        d = make2()
        plan = design2.CapPlan(d, 'auto-zero-reject')
        seen = set()
        for _ in range(120):
            m = rng.choice((0, 1, 5, 40, 120, 400, 900))
            span = rng.choice((10, 3_000, 100_000, 400_000))
            blocks = sorted(rng.randrange(span) for _ in range(m))
            values = np.full(m, 10, dtype=np.int64)
            S, _ = plan.fit_S(np.array(blocks, dtype=np.int64), values)
            self.assertEqual(S, brute_force_cap(d, blocks), (m, span))
            seen.add(S)
            if S > 10 and m:
                smaller = max(g for g in d.small_grid + [0] if g < S) if S <= 1000 else (1000 if S == 3245 else S - 3245)
                if S > 3245:
                    s = d.main_capacity, d.refill_main, S // 3245 - 1
                    self.assertFalse(engine.admit(np.array(blocks, dtype=np.int64), s[0], s[1], s[2], blocks[0]).all())
                elif smaller:
                    s = d.cap_spec(smaller, 'x')
                    self.assertFalse(engine.admit(np.array(blocks, dtype=np.int64), s['capacity'], s['refill_ppm'], 1,
                                                  blocks[0]).all(), (S, smaller))
        self.assertGreaterEqual(len(seen), 4)

    def test_rejection_is_zero_at_the_chosen_cap_in_a_replay(self):
        rng = random.Random(5)
        p = td.replay_params()
        d = make2(vmax_usdc='0.2')
        plan = design2.CapPlan(d, 'auto-zero-reject')
        for _ in range(12):
            m = rng.choice((20, 150, 700))
            blocks = sorted(set(rng.randrange(60_000) for _ in range(m)))
            values = [rng.choice((100, 50_000, 900_000)) for _ in blocks]     # a third of the rows are above v_max
            arrays = trace_arrays(blocks, values)
            spec, seg = plan.scale('a%d' % m, arrays, 137, p['refillPpmPerBlock'])
            self.assertIsNone(seg)
            kw = dict(seed=3, p=p, capacity=spec['capacity'], scale=spec['scale'], origin_ledger=0,
                      local_origin=p['epochOrigin'], end_ledger=70_000, block_size={}, window_blocks=70_000,
                      first_seconds=0, observed=False, cap=d.vmax, refill_ppm=spec['refill_ppm'])
            row, _ = engine.replay_address('a', arrays, **kw)
            self.assertEqual(row['rate_rejected_count'], 0)
            self.assertEqual(row['cap_rejected_count'], sum(1 for v in values if v > d.vmax))
            self.assertEqual(spec['method'], 'min-zero-insample')

    def test_a_cap_one_step_down_rejects(self):
        d = make2()
        plan = design2.CapPlan(d, 'auto-zero-reject')
        blocks = [5] * 12
        spec, _ = plan.scale('x', trace_arrays(blocks), 137, 50_000)
        self.assertEqual(spec['S'], 300)
        below = d.cap_spec(100, 'x')
        row, _ = engine.replay_address('x', trace_arrays(blocks), seed=1, p=td.replay_params(), capacity=below['capacity'],
                                       scale=1, origin_ledger=0, local_origin=1000, end_ledger=100, block_size={5: 12},
                                       window_blocks=100, first_seconds=0, observed=False, cap=d.vmax,
                                       refill_ppm=below['refill_ppm'])
        self.assertEqual(row['accepted_count'], 4)           # q_100 = 4 and no refill within one block
        self.assertEqual(row['rate_rejected_count'], 8)

    def test_records_above_v_max_and_empty_records(self):
        d = make2(vmax_usdc='0.1')
        plan = design2.CapPlan(d, 'auto-zero-reject')
        blocks = np.array([7] * 500, dtype=np.int64)
        big = np.full(500, 150_000, dtype=np.int64)                  # all above v_max = 100,000
        self.assertEqual(plan.fit_S(blocks, big), (10, 'no-record'))
        mixed = np.r_[np.full(1, 50, dtype=np.int64), big[:499]]
        self.assertEqual(plan.fit_S(blocks, mixed), (10, 'fit'))
        spec, _ = plan.scale('e', trace_arrays([], []), 137, 50_000)
        self.assertEqual((spec['S'], spec['method']), (10, 'no-record'))

    def test_large_burst_needs_a_multiple_of_the_main_cap(self):
        d = make2()
        plan = design2.CapPlan(d, 'auto-zero-reject')
        S, _ = plan.fit_S(np.array([5] * 2000, dtype=np.int64), np.full(2000, 10, dtype=np.int64))
        self.assertEqual(S, 3245 * 15)                              # 2000 / 137 = 14.6 -> n = 15
        self.assertEqual(S, brute_force_cap(d, [5] * 2000))
        spec = d.cap_spec(S, 'x')
        self.assertEqual((spec['n'], spec['scale'], spec['capacity']), (15, 15, 137))

    def test_prior_record_rule_and_cross_mode(self):
        d = make2()
        prior = type('P', (), {})()
        prior.per = {'a': (np.array([0] * 13, dtype=np.int64), np.full(13, 10, dtype=np.int64)),
                     'b': (np.array([], dtype=np.int64), np.array([], dtype=np.int64))}
        plan = design2.CapPlan(d, 'prior14', prior=prior)
        rows = trace_arrays([0] * 5)
        spec_a, seg = plan.scale('a', rows, 137, 50_000)
        self.assertEqual((spec_a['S'], spec_a['method'], seg), (300, 'prior14', None))
        spec_b, _ = plan.scale('b', rows, 137, 50_000)
        self.assertEqual((spec_b['S'], spec_b['method']), (10, 'prior14-no-record'))     # no record: the least cap
        with self.assertRaises(ValueError):
            design2.CapPlan(d, 'prior14')
        cross = design2.CapPlan(d, 'cross', mid_block=1000, first_block=0)
        replay_rows = trace_arrays([0] * 3 + [2000] * 12)
        spec, segments = cross.scale('a', replay_rows, 137, 50_000)
        # the first half (3 at once) runs with the cap fitted on the second half (12 at once -> 300);
        # the second half runs with the cap fitted on the first (3 at once -> 100)
        self.assertEqual(spec['S_parts'], [300, 100])
        self.assertEqual(spec['S'], 300)
        self.assertEqual([s[0] for s in segments], [0, 1000])
        self.assertEqual([s[2] for s in segments], [13, 4])
        row, _ = engine.replay_address('a', replay_rows, seed=1, p=td.replay_params(), capacity=137, scale=1,
                                       origin_ledger=0, local_origin=1000, end_ledger=3000, block_size={0: 3, 2000: 12},
                                       window_blocks=3000, first_seconds=0, observed=False, cap=d.vmax,
                                       segments=segments)
        self.assertEqual(row['accepted_count'], 3 + 4)         # q_300 = 13 admits the first three, q_100 = 4 of the twelve
        self.assertEqual(row['rate_rejected_count'], 8)

    def test_a_fixed_cap_is_the_same_for_every_address(self):
        d = make2(sales_cap=300)
        plan = design2.CapPlan(d, 300)
        for a in 'xyz':
            spec, _ = plan.scale(a, trace_arrays([1, 2, 3]), 137, 50_000)
            self.assertEqual((spec['S'], spec['method'], spec['k']), (300, 'fixed', 19))
        self.assertEqual(make2(sales_cap='300').sales_cap, 300)

    def test_the_grid_needs_the_main_capacity(self):
        plan = design2.CapPlan(make2(), 'auto-zero-reject')
        with self.assertRaises(ValueError):
            plan.scale('x', trace_arrays([1]), 20, 50_000)

    def test_monotone_in_the_cap(self):
        """The bucket condition is monotone in S: a larger cap never rejects what a smaller one admits."""
        d = make2()
        rng = random.Random(2)
        for _ in range(25):
            blocks = np.array(sorted(rng.randrange(20_000) for _ in range(rng.randrange(1, 300))), dtype=np.int64)
            admits = [engine.admit(blocks, d.cap_spec(S, 'x')['capacity'], d.cap_spec(S, 'x')['refill_ppm'], 1, 0).all()
                      for S in GRID]
            self.assertEqual(admits, sorted(admits))


if __name__ == '__main__':
    unittest.main()
