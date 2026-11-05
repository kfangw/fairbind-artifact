"""The report columns of section 5.2 (second edition) from a design-2 run."""
import json
import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import d2_report  # noqa: E402
from d2_testlib import ChainListFixture  # noqa: E402


class ReportColumns(ChainListFixture, unittest.TestCase):
    def test_columns_of_the_report(self):
        out, env = self.run_replay('sol_cols', '--vmax', '1', '--sales-cap', 'auto-zero-reject')
        r = d2_report.columns(out)
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        rows = d2_report.read_csv(out / 'condition-01-seed-0' / 'addresses_observed.csv')
        self.assertEqual((r['chain'], r['block_seconds'], r['vmax_usdc'], r['sales_cap_rule']),
                         ('solana', '0.4', '1', 'auto-zero-reject'))
        self.assertAlmostEqual(r['bond_sum_usdc']['replayed'], sum(int(x['nB']) for x in rows) / 1e6)
        self.assertAlmostEqual(r['bond_sum_usdc']['A'] + r['bond_sum_usdc']['rest'], r['bond_sum_usdc']['replayed'])
        self.assertEqual(sum(r['cap_distribution']['replayed'].values()), len(rows))
        for g in ('replayed', 'A', 'rest', 'list'):
            for k in ('count', 'value'):
                x = r['in_range_share'][g][k]
                self.assertTrue(0 <= x <= 1, (g, k, x))
        self.assertAlmostEqual(r['in_range_share']['list']['count'], meta['list_cap_pass_rows'] / meta['list_rows'])
        days = meta['replay_blocks'] * 0.4 / 86400
        self.assertAlmostEqual(r['replay_days'], days, places=3)
        for g in ('replayed', 'A', 'rest'):
            q = r['bond_days_of_revenue'][g]
            if q['n']:
                self.assertLessEqual(q['min'], q['q1'])
                self.assertLessEqual(q['q1'], q['median'])
                self.assertLessEqual(q['median'], q['q3'])
                self.assertLessEqual(q['q3'], q['max'])
        # two terms of the loss formula, a function of w: both grow with w, and total is their sum
        prev = None
        for w in ('0.0003', '0.004728', '0.011', '0.015'):
            x = r['loss_formula'][w]['replayed']
            self.assertAlmostEqual(x['total_share'], x['term1_share'] + x['term2_share'])
            self.assertAlmostEqual(x['total_usdc'], x['term1_usdc'] + x['term2_usdc'])
            if prev is not None:
                self.assertGreater(x['total_share'], prev)
            prev = x['total_share']
        self.assertEqual(set(r['injected_loss']), {'main', 'w_0.015'})
        self.assertAlmostEqual(r['injected_loss']['w_0.015']['w'], 0.015)
        ins = r['inspections']['replayed']
        self.assertAlmostEqual(ins['expected'], sum(float(x['expected_samples']) for x in rows))
        self.assertTrue(r['sample_count_check_pass'])
        self.assertEqual(r['rate_rejection']['replayed']['rate_rejected_count'], 0)
        mx, mean = r['held_proceeds_per_address_max']['replayed'], r['held_proceeds_per_address_mean']['replayed']
        self.assertEqual(mx['n'], mean['n'])
        self.assertGreaterEqual(mx['median'], mean['median'])
        self.assertGreaterEqual(mx['max'], mean['max'])
        flat = d2_report.flatten(r)
        self.assertIn('bond_sum_usdc.A', flat)
        table = d2_report.address_table(out)
        self.assertEqual(len(table), len(rows))
        self.assertEqual({t['vmax_usdc'] for t in table}, {1.0})

    def test_formula_terms_by_hand(self):
        row = dict(accepted_count='1000', s_bar='0.5', mean_value='20000')
        t1, t2 = d2_report.formula_terms(row, hold=31_073, rate_blocks=100_000, w=0.004728, deduction=740_741)
        self.assertAlmostEqual(t1, 1 - math.exp(-0.004728 * (1000 / 100_000) * 0.5 * 31_073))
        self.assertAlmostEqual(t2, 0.5 * 0.004728 * 740_741 / 20_000)
        self.assertIsNone(d2_report.formula_terms(dict(row, accepted_count='0'), 31_073, 100_000, 0.01, 1))


if __name__ == '__main__':
    unittest.main()
