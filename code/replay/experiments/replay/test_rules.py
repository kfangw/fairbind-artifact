"""Decision rules on synthetic result files, in both directions."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rules  # noqa: E402
from replay import OBS_COLUMNS, INJ_COLUMNS  # noqa: E402


def obs_row(i, *, group_a, h_max, h_formula, attempted, rejected, ws, ws_below, accepted=1000, samples=100):
    groups = ['A', 'replayed'] if group_a else ['B', 'replayed']
    return dict(address=f'0x{i:040x}', rank=i + 1, groups=json.dumps(groups), under_assigned='false',
                attempted_count=attempted, rejected_count=rejected, accepted_count=accepted, sample_count=samples,
                H_max=h_max, H_formula=h_formula, rejection_rate=rejected / attempted,
                judgment_window_settlements=ws, judgment_window_settlements_below=ws_below)


def inj_row(i, ratio, *, setting='main', reentry=0, claim=1, principal_over_revenue=0.5):
    return dict(address=f'0x{i:040x}', setting=setting, reentry_delay_blocks=reentry, claim_probability=claim,
                k=23, draws=10, ratio_to_formula=ratio, principal_over_revenue_max=principal_over_revenue,
                window_failures_mean='[1.0, 2.0]', window_failures_sd='[1.0, 1.0]',
                window_failures_expected='[1.1, 2.1]')


def write(path, rows, columns):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator='\n')
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, '') for c in columns})


def make_run(root, seeds, *, reportable=True):
    """seeds: list of (observed rows, injection rows), one per seed of condition 1."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    runs = []
    for rep, (obs, injr) in enumerate(seeds):
        d = root / f'condition-01-seed-{rep}'
        d.mkdir()
        write(d / 'addresses_observed.csv', obs, OBS_COLUMNS)
        write(d / 'addresses_injection.csv', injr, INJ_COLUMNS)
        (d / 'condition.json').write_text(json.dumps(dict(sample_rate=0.1, settings=[])))
        runs.append(dict(condition=1, repetition=rep, directory=d.name))
    (root / 'run.json').write_text(json.dumps(dict(reportable=reportable, not_reportable_reasons=[] if reportable
                                                   else ['timing-only pass'], runs=runs,
                                                   parameters=dict(k={'data-api-fast-v1': 23}, k_role='default'))))
    return root


def seed(*, f1_over, f3_rejected, f4_below, d1_ratio):
    obs = []
    for i in range(44):
        obs.append(obs_row(i, group_a=True, h_max=130 if i < f1_over else 110, h_formula=100, attempted=1000,
                           rejected=f3_rejected if i == 0 else 0, ws=100, ws_below=f4_below if i == 0 else 0))
    obs.append(obs_row(44, group_a=False, h_max=500, h_formula=1, attempted=10, rejected=10, ws=100, ws_below=0))
    injr = [inj_row(i, d1_ratio) for i in range(44)] + [inj_row(44, 99.0)]
    injr += [inj_row(i, 99.0, setting='collusion_worst') for i in range(44)]
    return obs, injr


class Rules(unittest.TestCase):
    def evaluate(self, seeds, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp) / 'run', seeds, **kw)
            return rules.evaluate([run])

    def test_nothing_met(self):
        out = self.evaluate([seed(f1_over=10, f3_rejected=100, f4_below=100, d1_ratio=1.0)] * 3)
        self.assertEqual(out['rules']['R20-F1'], rules.NOT_MET)
        self.assertEqual(out['rules']['R20-F3'], rules.NOT_MET)   # 100 / 44,000 < 1 %
        self.assertEqual(out['rules']['R20-F4'], rules.NOT_MET)   # 100 / 4,500 < 10 %
        self.assertEqual(out['rules']['R20-D1'], rules.NOT_MET)
        s = out['runs'][0]['seeds'][0]
        self.assertAlmostEqual(s['R20-F1']['statistic'], 10 / 44)
        self.assertEqual(s['R20-C3']['verdict'], 'pass')
        self.assertTrue(s['R20-M1']['verdict'].startswith('not evaluated'))

    def test_everything_met(self):
        out = self.evaluate([seed(f1_over=23, f3_rejected=441, f4_below=451, d1_ratio=2.5)] * 3)
        for name in ('R20-F1', 'R20-F3', 'R20-F4', 'R20-D1'):
            self.assertEqual(out['rules'][name], rules.MET, name)

    def test_thresholds_are_strict(self):
        # Exactly half of A over 1.25, exactly 1 % rejected, exactly 10 %, median exactly 2: not met.
        out = self.evaluate([seed(f1_over=22, f3_rejected=440, f4_below=450, d1_ratio=2.0)])
        for name in ('R20-F1', 'R20-F3', 'R20-F4', 'R20-D1'):
            self.assertEqual(out['rules'][name], rules.NOT_MET, name)
        out = self.evaluate([seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=0.49)])
        self.assertEqual(out['rules']['R20-D1'], rules.MET)

    def test_seed_dependent_counts_as_met(self):
        out = self.evaluate([seed(f1_over=30, f3_rejected=0, f4_below=0, d1_ratio=1.0),
                             seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=1.0)])
        self.assertTrue(out['rules']['R20-F1'].startswith('seed dependent'))

    def test_counted_twice_fails_c3(self):
        obs, injr = seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=1.0)
        injr[3]['principal_over_revenue_max'] = 1.2
        out = self.evaluate([(obs, injr)])
        self.assertTrue(out['runs'][0]['seeds'][0]['R20-C3']['verdict'].startswith('fail'))

    def test_m1_with_predictions(self):
        obs, injr = seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=1.0)
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp) / 'run', [(obs, injr)])
            far = {r['address']: (0.2 if i < 10 else 0.0) for i, r in enumerate(obs)}
            self.assertEqual(rules.evaluate([run], far)['rules']['R20-M1'], rules.MET)  # 10 / 44 > 0.2
            near = {r['address']: 0.0 for r in obs}
            self.assertEqual(rules.evaluate([run], near)['rules']['R20-M1'], rules.NOT_MET)

    def test_refuses_a_run_that_is_not_reportable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp) / 'run', [seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=1.0)],
                           reportable=False)
            with self.assertRaises(rules.NotReportable):
                rules.evaluate([run])
            self.assertEqual(rules.main([str(run)]), 2)


class Checks(unittest.TestCase):
    """R20-C1 (manuscript bound), R20-C2 by settlement window, and the M1 prediction hash."""

    def c1_row(self, mean, sd=0.001, *, rate=0.01, w=0.004728, tau=0, samples=None, address=1):
        return dict(address=f'0x{address:040x}', setting='main', reentry_delay_blocks=tau, claim_probability=1,
                    w=w, draws=1000, freeze_fraction_mean=mean, freeze_fraction_sd=sd, rate_acc_per_block=rate,
                    sample_count=samples if samples is not None else '')

    def test_c1_bound_both_directions(self):
        s = 0.1
        bound = rules.c1_bound(s, 0.01, 0.004728, 1800)
        self.assertAlmostEqual(bound, 0.1 * 0.01 * 0.004728 * 1801)
        ok = rules.check_c1([self.c1_row(bound, tau=1800)], s)
        self.assertEqual(ok['verdict'], 'pass')
        # Above the bound by less than the interval of the mean: pass; by more: fail.
        half = 1.959963984540054 * 0.001 / 1000 ** 0.5
        self.assertEqual(rules.check_c1([self.c1_row(bound + 0.9 * half, tau=1800)], s)['verdict'], 'pass')
        bad = rules.check_c1([self.c1_row(bound + 1.1 * half, tau=1800)], s)
        self.assertTrue(bad['verdict'].startswith('fail'))
        self.assertEqual(bad['statistic'], 1)

    def test_c1_leaves_out_bounds_above_one(self):
        r = rules.check_c1([self.c1_row(0.9, rate=0.5, w=0.34, tau=1800)], 0.1)
        self.assertEqual((r['checked'], r['excluded_bound_above_one'], r['verdict']), (0, 1, 'pass'))

    def test_c1_conditional_on_samples(self):
        # 2,000 sampled cases over 100,000 blocks where s * rate * blocks expects 1,000: the
        # registered bound flags, the diagnostic conditional on the samples does not.
        w, blocks = 0.004728, 100_000
        mean = 2000 * w / blocks
        r = rules.check_c1([self.c1_row(mean, sd=0.0, rate=0.1, samples=2000)], 0.1, blocks)
        self.assertTrue(r['verdict'].startswith('fail'))
        self.assertEqual(r['conditional_on_samples']['statistic'], 0)

    def test_c1_not_evaluated_without_columns(self):
        r = rules.check_c1([inj_row(0, 1.0)], 0.1)
        self.assertTrue(r['verdict'].startswith('not evaluated'))

    def test_c2_uses_the_settlement_window(self):
        row = inj_row(0, 1.0)
        # The confirmation-window counts are off; the settlement-window counts match.
        row.update(window_failures_mean='[0.0, 3.0]', window_failures_sd='[0.0, 0.5]',
                   window_failures_expected='[1.5, 1.5]', window_failures_by_settlement_mean='[1.5, 1.5]',
                   window_failures_by_settlement_sd='[1.0, 1.0]', window_samples_by_settlement='[300, 300]', w=0.005)
        r = rules.check_c2_windows([row])
        self.assertEqual((r['verdict'], r['assignment']), ('pass', ['settlement window']))
        row['window_failures_by_settlement_mean'] = '[3.0, 0.0]'
        r = rules.check_c2_windows([row])
        self.assertTrue(r['verdict'].startswith('fail'))
        self.assertEqual(r['statistic'], 2)
        # Without the per-settlement columns the confirmation windows are used and named.
        r = rules.check_c2_windows([inj_row(0, 1.0)])
        self.assertEqual(r['assignment'], ['confirmation window'])

    def test_c2_reads_string_list_cells(self):
        row = inj_row(0, 1.0)
        row.update(window_failures_by_settlement_mean='["1.5", "1.5"]', window_failures_by_settlement_sd='["1.0", "1.0"]',
                   window_failures_expected='["1.5", "1.5"]')
        self.assertEqual(rules.check_c2_windows([row])['verdict'], 'pass')

    def test_m1_prediction_must_match_the_envelope(self):
        obs, injr = seed(f1_over=0, f3_rejected=0, f4_below=0, d1_ratio=1.0)
        near = {r['address']: 0.0 for r in obs}
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp) / 'run', [(obs, injr)])
            env = json.loads((run / 'run.json').read_text())
            env['inputs'] = dict(m1_predictions=dict(path='m1.csv', sha256='ab' * 32))
            (run / 'run.json').write_text(json.dumps(env))
            out = rules.evaluate([run], near, predictions_sha256='ab' * 32)
            self.assertEqual(out['rules']['R20-M1'], rules.NOT_MET)
            out = rules.evaluate([run], near, predictions_sha256='cd' * 32)
            self.assertTrue(out['rules']['R20-M1'].startswith('not evaluated'))


if __name__ == '__main__':
    unittest.main()
