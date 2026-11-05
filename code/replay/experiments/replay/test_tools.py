"""input_stats.py, m1_predictions.py and baseline.py on synthetic lists."""
import csv
import json
import sys
import tempfile
import textwrap
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import baseline  # noqa: E402
import input_stats  # noqa: E402
import inputs  # noqa: E402
import m1_predictions  # noqa: E402
import replay  # noqa: E402
import rules  # noqa: E402
from test_replay import synthetic, run_cli  # noqa: E402

FAKE_R1 = textwrap.dedent('''
    import csv
    from bond_gap2 import load_config2  # the real script imports its helper module
    HOURS_IN_WINDOW = 336.0
    CALLS = []

    def load_sellers(path):
        with open(path, newline="") as f:
            return [{"seller_id": r["seller_id"], "settlements": float(r["settlements"]),
                     "active_hours": 340.0 if i == 0 else 10.0, "rate_per_active_hour": 1.0,
                     "rate_per_hour_peak": 2.0} for i, r in enumerate(csv.DictReader(f))]

    def simulate_seller(seller, lam_max, q):
        CALLS.append((seller["seller_id"], lam_max, q))
        return {"demanded": 100.0, "accepted": 90.0, "rejected": 10.0, "fraction_rejected": 0.1}
''')


class Tools(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.s = synthetic(cls.tmp.name)
        cls.cond = inputs.load_conditions(cls.s['conditions'])
        cls.rows = list(csv.reader(open(cls.s['csv'])))[1:]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_input_stats_counts_values_above_the_cap(self):
        out = Path(self.tmp.name) / 'stats.json'
        self.assertEqual(input_stats.main(['--settlements', str(self.s['csv']), '--conditions-file',
                                           str(self.s['conditions']), '--out', str(out)]), 0)
        r = json.loads(out.read_text())
        values = [int(x[7]) for x in self.rows]
        self.assertEqual(r['cap_atomic'], 10_000)
        self.assertEqual(r['total_count'], len(values))
        self.assertEqual(r['total_value_atomic'], sum(values))
        # Strictly above the cap: the 10,000 rows are at the cap and do not count.
        self.assertEqual(r['above_cap_count'], sum(1 for v in values if v > 10_000))
        self.assertEqual(r['above_cap_value_atomic'], sum(v for v in values if v > 10_000))
        self.assertAlmostEqual(r['above_cap_count_share'], r['above_cap_count'] / len(values))
        self.assertEqual(r['settlements']['period'], 'replay_period')

    def test_m1_predictions_use_the_replay_bucket(self):
        r1 = Path(self.tmp.name) / 'r1.py'
        r1.write_text(FAKE_R1)
        out = Path(self.tmp.name) / 'm1.csv'
        self.assertEqual(m1_predictions.main(['--r1', str(r1), '--reference-dir', str(self.s['dir']),
                                              '--conditions-file', str(self.s['conditions']), '--out', str(out)]), 0)
        rows = list(csv.DictReader(open(out)))
        self.assertEqual(len(rows), 44)
        meta = json.loads(out.with_suffix('.json').read_text())
        self.assertEqual(meta['output']['sha256'], inputs.sha256_file(out))
        self.assertEqual(len(meta['active_hours_clamped']), 1)
        mod = sys.modules['r1_model']
        for (sid, lam, q), r in zip(mod.CALLS, rows):
            n = int(r['scale'])
            # Refill n * r_fill per hour (0.05 per block, 1,800 blocks) and capacity n * qX.
            self.assertEqual((lam, q), (n * 90.0, n * 137))
            self.assertEqual(float(r['predicted_rejection_rate']), 0.1)
        # The file is what rules.py reads.
        preds = {r['address'].lower(): float(r['predicted_rejection_rate']) for r in rules.read_csv(out)}
        self.assertEqual(len(preds), 44)

    def test_baseline_list_only(self):
        prefix = Path(self.tmp.name) / 'baseline'
        self.assertEqual(baseline.main(['list-only', '--settlements', str(self.s['csv']), '--reference-dir',
                                        str(self.s['dir']), '--conditions-file', str(self.s['conditions']),
                                        '--out', str(prefix)]), 0)
        doc = json.loads(Path(str(prefix) + '.json').read_text())
        prm = doc['parameters']
        self.assertEqual((prm['k'], prm['g_atomic'], prm['ceil_inv_p'], prm['B_atomic'], prm['L_main_T_case'],
                          prm['L_V_path']), (27, 10_000, 25, 10_000_000, 58_994, 29_680))
        rows = {r['address']: r for r in doc['addresses']}
        top400, _, groups, _, _, _ = replay.build_groups(self.cond, self.s['dir'])
        replayed = set(groups['all400']) | set(groups['C'])
        self.assertEqual(set(rows), replayed)
        # Independent recount for the heaviest address.
        a = max(rows, key=lambda x: rows[x]['settlements'])
        mine = [x for x in self.rows if x[5].lower() == a]
        hours = {}
        for x in mine:
            h = inputs.utc_seconds(x[1]) // 3600
            hours[h] = hours.get(h, 0) + 1
        peak = max(hours.values())
        r = rows[a]
        self.assertEqual((r['settlements'], r['peak_hour']), (len(mine), peak))
        ceil = lambda f: -(-f.numerator // f.denominator)  # noqa: E731
        self.assertEqual(r['B_vel_main'], 27 * 10_000 * (25 + ceil(Fraction(peak * 58_994, 1800))))
        self.assertEqual(r['B_vel_V-path'], 27 * 10_000 * (25 + ceil(Fraction(peak * 29_680, 1800))))
        self.assertEqual(r['B_vel_V-mean'], 27 * 10_000 * (25 + ceil(Fraction(len(mine) * 58_994, self.s['span']))))
        vbar = Fraction(sum(int(x[7]) for x in mine), len(mine))
        self.assertAlmostEqual(r['B_vel_V-amount'], float(27 * vbar * (25 + ceil(Fraction(peak * 58_994, 1800)))))
        self.assertEqual(r['fairbind_bond_nB'], r['scale'] * 10_000_000)
        self.assertEqual(r['fairbind_deterrence_min'], r['scale'] * 6_750_000)
        self.assertAlmostEqual(r['ratio_main'], r['B_vel_main'] / (r['scale'] * 10_000_000))
        g = doc['groups']
        self.assertEqual(g['replayed']['addresses'], len(replayed))
        self.assertEqual(g['A']['addresses'], 44)
        self.assertEqual(g['A']['B_vel_main_sum'], g['rank1']['B_vel_main_sum'] + g['rank2']['B_vel_main_sum']
                         + g['ranks3_44']['B_vel_main_sum'])
        self.assertEqual(g['replayed']['B_vel_main_sum'], sum(x['B_vel_main'] for x in rows.values()))
        ratios = sorted(x['ratio_main'] for x in rows.values())
        self.assertEqual((g['replayed']['ratio_main']['min'], g['replayed']['ratio_main']['max']),
                         (ratios[0], ratios[-1]))
        with open(str(prefix) + '.csv') as f:
            self.assertEqual(len(list(csv.DictReader(f))), len(replayed))

    def test_baseline_compare_reads_a_finished_run(self):
        prefix = Path(self.tmp.name) / 'b2'
        baseline.main(['list-only', '--settlements', str(self.s['csv']), '--reference-dir', str(self.s['dir']),
                       '--conditions-file', str(self.s['conditions']), '--out', str(prefix)])
        run = Path(self.tmp.name) / 'run'
        saved = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)
        try:
            run_cli(['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                     '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(run), '--draws', '2',
                     '--conditions', '1,2,3,4,5'])
        finally:
            replay.git_state = saved
        doc = baseline.compare(str(prefix) + '.json', run)
        obs = {r['address']: r for r in rules.read_csv(run / 'condition-01-seed-0' / 'addresses_observed.csv')}
        r = next(x for x in doc['addresses'] if x['address'] in obs)
        self.assertEqual(len(r['nB_plus_H_max_per_seed']), 3)
        self.assertEqual(r['nB_plus_H_max_per_seed'][0], float(obs[r['address']]['nB_plus_H_max']))
        # A run that is not reportable is refused.
        env = json.loads((run / 'run.json').read_text())
        env['reportable'] = False
        (run / 'run.json').write_text(json.dumps(env))
        self.assertEqual(baseline.main(['compare', str(run), '--baseline', str(prefix) + '.json']), 2)


if __name__ == '__main__':
    unittest.main()
