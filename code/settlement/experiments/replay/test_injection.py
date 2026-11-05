import math
import random
import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import injection as inj  # noqa: E402


class LossModel(unittest.TestCase):
    def test_overlapping_failures_count_each_entry_once(self):
        # One settlement per block from 1 to 100, released after 50 blocks.
        settlements = [(b, 1) for b in range(1, 101)]
        r = inj.seller_loss(settlements, [60, 70], t_hold=50, penalty_share=0)
        # First failure: entries 11..60 are unreleased. Second: only 61..70, settled after the
        # previous freeze block. The old definition counted 21..70 again (50 entries).
        self.assertEqual(r['per_failure_principal'], [50, 10])
        self.assertEqual(r['principal_loss'], 60)
        self.assertTrue(r['counted_once'])

    def test_released_entries_are_not_lost_and_penalty_is_per_failure(self):
        settlements = [(b, 2) for b in range(1, 11)]
        r = inj.seller_loss(settlements, [100], t_hold=50, penalty_share=7)
        # Entries settled at 1..10 are released by block 60; nothing is frozen at 100.
        self.assertEqual(r['principal_loss'], 0)
        self.assertEqual(r['penalty_loss'], 7)

    def test_suspension_rejects_until_reentry(self):
        settlements = [(b, 1) for b in range(1, 21)]
        r = inj.seller_loss(settlements, [10], t_hold=100, penalty_share=0, reentry_delay=3)
        # Blocks 11..13 fall between the failure and re-entry at 14: lost sales, not loss.
        self.assertEqual(r['lost_sales'], 3)
        self.assertEqual(r['revenue'], 17)
        self.assertEqual(r['principal_loss'], 10)

    def test_principal_never_exceeds_revenue(self):
        rng = random.Random(7)
        settlements = [(b, rng.randint(1, 5)) for b in range(1, 2001)]
        for _ in range(20):
            failures = sorted(rng.sample(range(1, 2100), 30))
            r = inj.seller_loss(settlements, failures, t_hold=300, penalty_share=0)
            self.assertLessEqual(r['principal_loss'], r['revenue'])

    def test_formula_value_matches_the_recomputed_bucket_point(self):
        # Data API at the bucket rate r_fill = 0.05 per block: frozen share 0.758 (V2 recomputation).
        first = inj.formula_value(0.1, 0.004728, 0.05, 60_000, 0, 16, 1)
        self.assertAlmostEqual(first, 1 - math.exp(-0.1 * 0.004728 * 0.05 * 60_000), places=12)
        self.assertAlmostEqual(first, 0.758, places=3)
        # The B/k term is linear in B / (k v) and is the only part that can exceed one.
        with_penalty = inj.formula_value(0.1, 0.004728, 0.05, 60_000, 16 * 63.45, 16, 1)
        self.assertAlmostEqual(with_penalty - first, 0.1 * 0.004728 * 63.45, places=12)

    def test_injection_mean_tracks_the_formula(self):
        # Constant rate: the Monte Carlo mean lies near the formula value.
        t_hold, rate = 600, 1
        settlements = [(b, 1) for b in range(1, 60_001)]
        cases = [b for b, _ in settlements if b % 10 == 0]  # s = 0.1
        row = inj.injection_row(settlements, cases, s=0.1, w=0.01, t_hold=t_hold, bond=0, k=16,
                                confirm_delay=0, draws=200, seed=1, window_blocks=60_000)
        self.assertAlmostEqual(row['formula_value'], 1 - math.exp(-0.1 * 0.01 * rate * t_hold), places=3)
        self.assertLess(abs(row['ratio_to_formula'] - 1), 0.1)

    def test_formula_rate_uses_the_replay_window_and_accepted_settlements(self):
        # A seller active only in the first 1,000 blocks of the 14-day window: the formula rate is
        # its accepted count over 604,800 blocks, not over its own 1,000-block span.
        settlements = [(b, 2) for b in range(1, 1001)]
        row = inj.injection_row(settlements, [], s=0.1, w=0.01, t_hold=100, bond=0, k=16,
                                confirm_delay=0, draws=5, seed=1)
        self.assertEqual(row['accepted_rate_per_block'], 1000 / inj.REPLAY_BLOCKS)
        self.assertAlmostEqual(row['formula_value'],
                               1 - math.exp(-0.1 * 0.01 * 1000 / inj.REPLAY_BLOCKS * 100), places=15)
        # Settlements rejected during suspension leave the rate and the mean value: w = 1 confirms
        # the only case at block 10, and blocks 11..13 (value 100 each) fall before re-entry at 14.
        settlements = [(b, 100 if 11 <= b <= 13 else 1) for b in range(1, 21)]
        row = inj.injection_row(settlements, [10], s=0.1, w=1.0, t_hold=100, bond=0, k=16,
                                confirm_delay=0, draws=3, seed=1, reentry_delay=3, window_blocks=20)
        self.assertEqual(row['accepted_rate_per_block'], 17 / 20)
        self.assertEqual(row['accepted_mean_value'], 1)


class ScaleRules(unittest.TestCase):
    BLOCKS = 604_800  # 14 days of two-second blocks

    def per_block(self, per_hour):
        return per_hour * 336  # settlements over 14 days at a constant hourly rate

    def test_nF_is_the_main_rule_and_covers_the_mean_rate(self):
        # 556.8 per hour at r_fill 0.05 (90 per hour) needs 7; nR at r_max 0.06 (108 per hour) gives 6.
        n = Fraction(5568, 10) * 336
        self.assertEqual(inj.scale_nF(n, self.BLOCKS, Fraction(5, 100)), 7)
        self.assertEqual(inj.scale_nR(n, self.BLOCKS, Fraction(6, 100)), 6)
        self.assertTrue(inj.under_assigned(n, self.BLOCKS, 6, Fraction(5, 100)))
        self.assertFalse(inj.under_assigned(n, self.BLOCKS, 7, Fraction(5, 100)))

    def test_small_sellers_get_scale_one(self):
        self.assertEqual(inj.scale_nF(self.per_block(1), self.BLOCKS, Fraction(5, 100)), 1)
        self.assertEqual(inj.scale_nF(0, self.BLOCKS, Fraction(5, 100)), 1)

    def test_qx_is_p99_of_seven_day_peak_hours(self):
        counts = {f'a{i}': [0] * 167 + [i] for i in range(1, 201)}
        # 200 addresses with peaks 1..200: the nearest-rank p99 is the 198th value.
        self.assertEqual(inj.qx_statistic(counts), 198)
        with self.assertRaises(ValueError):
            inj.qx_statistic({'x': [1] * 169})
        self.assertEqual(inj.full_replay_q(90, 98), 98)

    def test_half_replay_feeds_only_rejection_columns(self):
        self.assertEqual(inj.column_source('rejection_rate'), 'half')
        self.assertEqual(inj.column_source('R20-F3'), 'half')
        for column in ('H_time_average', 'injection', 'windows_below_n_min'):
            self.assertEqual(inj.column_source(column), 'full')

    def test_input_check_tolerance(self):
        ok = inj.input_check(683_553 + 683, 683_553, {'a': (1001, 1000), 'b': (10, 9)})
        self.assertTrue(ok['within_tolerance'])
        self.assertEqual(ok['difference_sum'], 2)
        over_total = inj.input_check(683_553 + 684, 683_553, {'a': (1000, 1000)})
        self.assertFalse(over_total['within_tolerance'])
        # 0.5 percent of 1000 is 5; a difference of 6 is outside, 2 on a count of 9 is outside max(1, 0.045).
        over_address = inj.input_check(683_553, 683_553, {'a': (1006, 1000), 'b': (11, 9)})
        self.assertEqual(over_address['addresses_over_tolerance'], ['a', 'b'])


if __name__ == '__main__':
    unittest.main()
