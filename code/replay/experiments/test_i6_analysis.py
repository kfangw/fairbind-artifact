"""Tests of experiments/i6_analysis.py: the statistical routines against hand-computed and published
values, and the decision rules on synthetic run sets (result envelopes and observation documents built
here) in both directions."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import i6_analysis as ia  # noqa: E402
from controller import scenario as scn  # noqa: E402

SCENARIO = HERE / 'scenarios' / 'I6.yaml'
G = 10_000
RESAMPLES = 1000


# ---------------------------------------------------------------------------------------------
# Statistics


class Statistics(unittest.TestCase):
    def test_binomial_tails(self):
        self.assertAlmostEqual(ia.binom_sf(1, 10, 0.1), 1 - 0.9 ** 10, places=12)
        self.assertAlmostEqual(ia.binom_cdf(0, 30, 0.1), 0.9 ** 30, places=12)
        # P(X >= 2), n = 5, p = 0.5: 26/32.
        self.assertAlmostEqual(ia.binom_sf(2, 5, 0.5), 26 / 32, places=12)
        self.assertAlmostEqual(ia.binom_cdf(2, 5, 0.5), 16 / 32, places=12)
        self.assertEqual(ia.binom_sf(0, 5, 0.3), 1.0)
        self.assertEqual(ia.binom_cdf(5, 5, 0.3), 1.0)
        # Large n stays finite (log-space sums).
        self.assertAlmostEqual(ia.binom_sf(1, 100_000, 1e-6), 1 - (1 - 1e-6) ** 100_000, places=9)

    def test_clopper_pearson_published(self):
        # x = 0 and x = n have closed forms.
        lo, hi = ia.clopper_pearson(0, 30)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 1 - 0.025 ** (1 / 30), places=10)
        lo, hi = ia.clopper_pearson(30, 30)
        self.assertAlmostEqual(lo, 0.025 ** (1 / 30), places=10)
        self.assertEqual(hi, 1.0)
        # 5 of 20 (R binom.test: 0.08657147, 0.49104587).
        lo, hi = ia.clopper_pearson(5, 20)
        self.assertAlmostEqual(lo, 0.08657147, places=7)
        self.assertAlmostEqual(hi, 0.49104587, places=7)
        # One-sided bound for x = 0: 1 - 0.05^(1/n) (the "0/30, upper bound 0.095" of the V grid).
        self.assertAlmostEqual(ia.clopper_pearson(0, 30, sides=1)[1], 1 - 0.05 ** (1 / 30), places=10)
        self.assertAlmostEqual(ia.clopper_pearson(0, 30, sides=1)[1], 0.0950, places=4)
        with self.assertRaises(ValueError):
            ia.clopper_pearson(1, 0)

    def test_holm_textbook(self):
        adj = ia.holm({'a': 0.01, 'b': 0.04, 'c': 0.03, 'd': 0.005})
        self.assertAlmostEqual(adj['d'][0], 0.02)
        self.assertAlmostEqual(adj['a'][0], 0.03)
        self.assertAlmostEqual(adj['c'][0], 0.06)
        self.assertAlmostEqual(adj['b'][0], 0.06)
        self.assertEqual([k for k in 'abcd' if adj[k][1]], ['a', 'd'])
        # Monotone: a later step never has a smaller adjusted p.
        adj = ia.holm({'x': 0.001, 'y': 0.2, 'z': 0.03})
        self.assertEqual(adj['x'][0], 0.003)
        self.assertAlmostEqual(adj['z'][0], 0.06)
        self.assertAlmostEqual(adj['y'][0], 0.2)
        self.assertEqual(ia.holm({}), {})

    def test_quantile_and_bootstrap(self):
        self.assertEqual(ia.quantile([0, 10], 0.25), 2.5)
        self.assertEqual(ia.quantile([1, 2, 3, 4, 5], 0.5), 3)
        s = ia.mean_summary([3.0] * 10, 500, 1, threshold=3.0)
        self.assertEqual(s['interval_95'], [3.0, 3.0])
        self.assertEqual(s['p'], 1.0)  # H0 E <= 3 holds at the boundary
        s = ia.mean_summary([10.0, 11.0, 12.0], 500, 1, threshold=0.0)
        self.assertEqual(s['p'], 0.0)
        self.assertAlmostEqual(s['mean'], 11.0)
        s = ia.mean_summary([10.0, 11.0, 12.0], 500, 1, threshold=100.0, direction='lower')
        self.assertEqual(s['p'], 0.0)
        # Resampled means of {0, 1} with n = 2: 0, 0.5, 0.5, 1 with probability 1/4, 1/2, 1/4.
        boot = ia.bootstrap_means([0.0, 1.0], 20000, 7)
        self.assertAlmostEqual(sum(1 for b in boot if b == 0.5) / len(boot), 0.5, delta=0.02)
        self.assertEqual(ia.bootstrap_means([1.0, 2.0, 4.0], 100, 3), ia.bootstrap_means([1.0, 2.0, 4.0], 100, 3))
        self.assertEqual(ia.mean_summary([], 100, 1, 0)['n'], 0)

    def test_slope(self):
        self.assertAlmostEqual(ia.ols_slope([0, 1, 2, 3], [1, 3, 5, 7]), 2.0)
        self.assertIsNone(ia.ols_slope([1, 1], [2, 3]))
        s = ia.slope_summary([(0, 1), (1, 3), (2, 5), (3, 7)], 200, 1)
        self.assertAlmostEqual(s['slope'], 2.0)
        self.assertAlmostEqual(s['interval_95'][0], 2.0)

    def test_verdicts(self):
        s = dict(n=3, interval_95=[1.0, 2.0])
        self.assertEqual(ia.verdict_of(s, 3.0, 'upper', False, 'interval_95'), 'certified')
        self.assertEqual(ia.verdict_of(s, 1.5, 'upper', False, 'interval_95'), 'withheld')
        self.assertEqual(ia.verdict_of(s, 1.5, 'upper', True, 'interval_95'), 'excess_detected')
        self.assertEqual(ia.verdict_of(s, 0.5, 'lower', False, 'interval_95'), 'certified')
        self.assertEqual(ia.verdict_of(dict(n=0), 0.5, 'lower', False, 'interval_95'), 'no_data')


# ---------------------------------------------------------------------------------------------
# Synthetic runs

OP_VALUES = dict(alpha=0.01, beta=0.05, c=0.1, h=0.67, p_ceiling=0.04, pi=0.1, bucket_capacity=20,
                 refill_per_block=0.05, lambda_max_per_block=0.06, L_min_blocks=1168, L_blocks=9380,
                 L_actual_blocks=29680, failureLimit=16, g_atomic=G, v_atomic=G, caseHorizon_blocks=58994,
                 keeper_margin_blocks=1006, delta_F_blocks=3971)
SC = scn.load_scenario(SCENARIO)
POINTS = ia.plan_points(SC)


def point(cell, **swept):
    for p in POINTS:
        if p['cell'] == cell and all(str(p['parameters'][k]) == str(v) for k, v in swept.items()):
            return p
    raise KeyError((cell, swept))


class RunSet:
    """Writes run directories in the controller's layout under a temporary output directory."""

    def __init__(self, root):
        self.root = Path(root)

    def add(self, p, rep, *, op='a' * 64, k=16, g=G, B=None, t_hold=60000, t_case=58994, margin=500, n=1,
            kappa=0, episodes=(), y_f=None, reportable=True, smoke=None, status='completed', dirty=False,
            fault=(), mismatch=0, kappa_max=None, case_paths=(), sales=None, honest_windows=None, extra=None,
            rows_only=False, sealed=None, judgment_delay=9380, params=None, doc_run=None):
        rid = f'I6-p{p["index"]:02d}-r{rep}' + ('-smoke' if smoke else '')
        B = k * g * 25 if B is None else B
        eps = list(episodes)
        metrics = dict(
            episode_exposure=[e.get('X', 0) for e in eps], episode_net_gain=[e.get('net', 0) for e in eps],
            post_detection_leak=[e.get('L', 0) for e in eps],
            episode_end_mode=[e.get('mode', 'with_detection') for e in eps],
            buyer_refund_paid=[e.get('refund', 0) for e in eps], buyer_unrecovered_amount=[e.get('unrec', 0) for e in eps],
            first_detection_index=[dict(K=e.get('K', 1), censored=e.get('mode') == 'without_detection') for e in eps],
            y_f=[] if y_f is None else [y_f], case_path_blocks=[c[0] for c in case_paths],
            case_path_minus_keeper=[c[0] - c[1] for c in case_paths], keeper_delay_sum_blocks=[c[1] for c in case_paths],
            injection_draw_mismatch_count=mismatch,
            fault_observed=[dict(item=name, applicable=True, ok=ok, reason='') for name, ok in
                            (list(fault) or [('injection_log', True)])],
            achieved_settlement_rate=0.05, configured_settlement_rate=0.05, released_exposure=sum(e.get('X', 0) for e in eps),
            honest_windows=honest_windows or [], operating_point_k=k, rejected_settlement_count=0)
        if kappa_max is not None:
            metrics['keeper_delay_sum_max_blocks'] = kappa_max
        elif case_paths:
            metrics['keeper_delay_sum_max_blocks'] = max(c[1] for c in case_paths)
        metrics.update(extra or {})
        run_info = dict(run_id=rid, g=g, v=G, seller_penalty=B, failure_limit=k, deduction=B // k, t_hold=t_hold,
                        t_case=t_case, margin_blocks=margin, keeper_margin=t_hold - t_case, kappa=kappa, seller_id=1)
        run_info.update(doc_run or {})
        doc = dict(format='fairbind-run-observations/v1', run=run_info, metrics=metrics,
                   sales=sales if sales is not None else [],
                   cases=[dict(nonce=f'0x{i:064x}', case_path_blocks=c[0], case_path_minus_keeper=c[0] - c[1],
                               keeper_delay_sum_blocks=c[1]) for i, c in enumerate(case_paths)])
        parameters = dict(p['parameters'], scale_factor=n, keeper_delay_budget_blocks=kappa)
        parameters.update(params or {})
        env = dict(kind='fairbind-scenario-run', scenario='I6', run_id=rid, status=status, dirty=dirty,
                   reportable=reportable and not dirty and status == 'completed' and not smoke, smoke=smoke,
                   cell=dict(name=p['cell']), parameters=parameters, judgment_delay_blocks=judgment_delay,
                   effective_hold_period_blocks=t_hold,
                   operating_point=dict(sha256=op, profile=p['profile'], values=dict(OP_VALUES, failureLimit=k)),
                   operating_point_k=dict(value=k))
        (self.root / 'results').mkdir(parents=True, exist_ok=True)
        (self.root / 'results' / f'{rid}.json').write_text(json.dumps(env))
        obs = self.root / 'runs' / rid / 'observations'
        obs.mkdir(parents=True, exist_ok=True)
        if rows_only:
            (obs / 'collector.jsonl').write_text(''.join(json.dumps(dict(metric=m, value=v, observation_id=rid)) + '\n'
                                                         for m, v in sorted(metrics.items())))
        else:
            (obs / 'collector.json').write_text(json.dumps(doc))
        if sealed is not None:
            (self.root / 'runs' / rid / 'ledger.json').write_text(json.dumps(dict(events=[
                dict(event='EpochSealed', args=dict(epoch=e, sellerId=1), block=1, logIndex=0) for e in sealed])))
        return rid


def detection_sales(detected, undetected, epoch=0):
    rows = [dict(bad=True, epoch=epoch, case_state='FINAL', final_verdict='FAIL', effective_detection='FAIL',
                 case_trigger=1, settled_block=i) for i in range(detected)]
    rows += [dict(bad=True, epoch=epoch, case_state=None, effective_detection=None, case_trigger=None,
                  settled_block=detected + i) for i in range(undetected)]
    return rows


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.rs = RunSet(self.tmp)

    def analyze(self, **kw):
        kw.setdefault('resamples', RESAMPLES)
        return ia.analyze(self.tmp, SCENARIO, ia.Options(**kw))

    @staticmethod
    def members(res, condition, point_label=None):
        out = [m for f in res['conditions'][condition]['families'] for m in f['members']]
        return [m for m in out if point_label is None or m['label'] == point_label]


# ---------------------------------------------------------------------------------------------
# Decision rules


class ExposureRules(Base):
    def test_f1_certified_and_triggered(self):
        ok = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        bad = point('M1-high-admissible', D_holding_blocks='T_case', Lambda_cheater='bucket_max')
        for i in range(30):
            self.rs.add(ok, i, episodes=[dict(X=0), dict(X=0)])
            self.rs.add(bad, i, episodes=[dict(X=40 * G + (i % 3) * G)], t_hold=58994)
        res = self.analyze()
        m_ok = self.members(res, 'I6-F1', ok['label'])
        m_bad = self.members(res, 'I6-F1', bad['label'])
        self.assertTrue(all(m['threshold'] == 25 * G for m in m_ok + m_bad))
        # Episode 1 and 2 of the good point are certified; the bad point has no second episode.
        self.assertTrue(all(m['verdict'] in ('certified', 'no_data') for m in m_ok))
        self.assertIn('certified', [m['verdict'] for m in m_ok])
        self.assertIn('excess_detected', [m['verdict'] for m in m_bad])
        self.assertEqual(res['conditions']['I6-F1']['verdict'], 'triggered')
        fam = next(f for f in res['conditions']['I6-F1']['families'] if f['episode'] == 1 and f['rate_class'] == 'high')
        self.assertEqual(fam['size'], 2)
        self.assertEqual(fam['registered_size'], 28)
        self.assertFalse(fam['size_matches'])

    def test_f1_not_triggered_below_threshold(self):
        p = point('M1-low-admissible', D_holding_blocks='T_hold')
        for i in range(60):
            self.rs.add(p, i, episodes=[dict(X=(i % 40) * G)])  # mean 19.25 g < 25 g
        res = self.analyze()
        self.assertTrue(res['conditions']['I6-F1']['verdict'].startswith('not_triggered'))

    def test_second_episode_needs_thirty_finished(self):
        p = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        for i in range(30):
            second = dict(X=100 * G, mode='with_detection' if i < 29 else 'open')
            self.rs.add(p, i, episodes=[dict(X=0), second])
        res = self.analyze()
        fam2 = next(f for f in res['conditions']['I6-F1']['families'] if f['episode'] == 2 and f['rate_class'] == 'high')
        m = fam2['members'][0]
        self.assertIn('not_judged', m)
        self.assertEqual(m['verdict'], 'no_data')
        self.assertEqual(res['completeness']['second_episode_not_judged'][0]['finished_second_episodes'], 29)

    def test_f4_only_bond_at_k_cells_and_f5_threshold_from_k(self):
        low = point('P3', bond_fraction_of_g_over_p='1.0')
        full = point('P3', bond_fraction_of_g_over_p='failureLimit')
        for i in range(60):
            # P3: g = v/2; B = g/p = 125,000 and k * g * ceil(1/p) = 2,000,000.
            self.rs.add(low, i, g=G // 2, B=125_000, episodes=[dict(net=5000)])
            self.rs.add(full, i, g=G // 2, B=2_000_000, episodes=[dict(net=-100_000)])
        res = self.analyze()
        f4 = self.members(res, 'I6-F4')
        self.assertEqual({m['label'] for m in f4}, {full['label']})
        f5 = {m['label']: m['threshold'] for m in self.members(res, 'I6-F5') if m['summary']['n']}
        self.assertAlmostEqual(f5[low['label']], 125_000 - 125_000 / 16)
        self.assertAlmostEqual(f5[full['label']], 125_000 - 2_000_000 / 16)
        self.assertTrue(res['conditions']['I6-F4']['verdict'].startswith('not_triggered'))

    def test_thresholds_follow_the_recorded_k(self):
        p = point('M2-high', D_holding_blocks='T_hold', bond_fraction_of_g_over_p='1.0', Lambda_cheater='bucket_max')
        for i in range(30):
            self.rs.add(p, i, k=23, B=250_000, episodes=[dict(net=0)], op='b' * 64)
        res = self.analyze()
        m = self.members(res, 'I6-F5', p['label'])[0]
        self.assertAlmostEqual(m['threshold'], 250_000 - 250_000 / 23)
        checks = {c['name']: c for c in res['threshold_checks']}
        self.assertTrue(checks['k_default']['match'])

    def test_registered_k_mismatch_flagged(self):
        p = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        for i in range(3):
            self.rs.add(p, i, k=16, episodes=[dict(X=0)])
        res = self.analyze()
        checks = {c['name']: c for c in res['threshold_checks']}
        self.assertFalse(checks['k_default']['match'])
        self.assertEqual(checks['bond_k_g_ceil_inv_p']['computed'], 4_000_000)
        self.assertEqual(checks['bond_k_g_ceil_inv_p']['registered'], 5_750_000)
        self.assertFalse(checks['bond_k_g_ceil_inv_p']['match'])
        self.assertTrue(checks['g_over_p']['match'])
        self.assertTrue(checks['p_L']['match'])
        self.assertTrue(checks['three_w1_sq']['match'])
        self.assertTrue(checks['T_case_minus_margin']['match'])

    def test_two_operating_points_are_separate_families(self):
        p = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        for i in range(30):
            self.rs.add(p, i, op='a' * 64, episodes=[dict(X=0)])
        other = RunSet(self.tmp / 'second')
        for i in range(30):
            other.add(p, i, op='c' * 64, k=23, episodes=[dict(X=100 * G)])
        res = self.analyze()
        fams = [f for f in res['conditions']['I6-F1']['families'] if f['episode'] == 1 and f['rate_class'] == 'high']
        self.assertEqual(sorted(f['name'][-8:] for f in fams), ['aaaaaaaa', 'cccccccc'])
        verdicts = {f['name'][-8:]: f['members'][0]['verdict'] for f in fams}
        self.assertEqual(verdicts['aaaaaaaa'], 'certified')
        self.assertEqual(verdicts['cccccccc'], 'excess_detected')

    def test_f3_threshold_uses_observed_kappa(self):
        p = point('M1-high-comparison', D_holding_blocks='T_min/2', Lambda_cheater='bucket_max')
        # l = T_catch + kappa_hat - T_hold = 9380 + 0 - 584; threshold g(25 + (20 + 0.05 l)).
        thr = G * (25 + (20 + 0.05 * (9380 - 584)))
        for i in range(30):
            self.rs.add(p, i, t_hold=584, episodes=[dict(X=int(thr * 2))])
        res = self.analyze()
        m = self.members(res, 'I6-F3', p['label'])[0]
        self.assertAlmostEqual(m['threshold'], thr)
        self.assertEqual(m['verdict'], 'excess_detected')
        pred = res['conditions']['I6-F3']['point_predictions'][0]
        self.assertAlmostEqual(pred['point_prediction'], G * (25 + 0.06 * (9380 - 584)))

    def test_f6_lower_bound_both_directions_and_dispute_scope(self):
        pr = point('M3-high', Lambda_cheater='bucket_max')
        pm = point('M3-high', Lambda_cheater='rate:mean_14d_p99_top400')
        # threshold g(0.05 (1168 - 584) - 1) = 28.2 g
        for i in range(30):
            self.rs.add(pr, i, t_hold=584, episodes=[dict(X=2 * G)])            # far below: falsifies
            self.rs.add(pm, i, t_hold=584, episodes=[dict(X=60 * G)])           # above: certified
        dispute = [dict(bad=True, case_trigger=3, epoch=0)]
        self.rs.add(pm, 30, t_hold=584, episodes=[dict(X=0)], sales=dispute)
        res = self.analyze()
        by = {m['label']: m for m in self.members(res, 'I6-F6')}
        self.assertAlmostEqual(by[pr['label']]['threshold'], G * (0.05 * (1168 - 584) - 1))
        self.assertEqual(by[pr['label']]['verdict'], 'excess_detected')
        self.assertEqual(by[pm['label']]['verdict'], 'certified')
        self.assertEqual(by[pm['label']]['runs_without_disputes'], 30)
        self.assertEqual(res['conditions']['I6-F6']['verdict'], 'triggered')
        lit = {m['label']: m['verdict'] for m in self.members(self.analyze(f6_rule='upper_bound'), 'I6-F6')}
        self.assertEqual(lit, {pr['label']: 'excess_detected', pm['label']: 'certified'})

    def test_m4_worst_ignores_keeper_margin_and_reports_long_cases(self):
        p = point('M4-worst', Lambda_cheater='bucket_max')
        for i in range(10):
            paths = [(60000 + (5 if i == 0 else 0), 30320)]
            self.rs.add(p, i, kappa=30320, case_paths=paths, episodes=[dict(X=9 * G)])
        res = self.analyze()
        self.assertEqual(res['runs']['premise_outside'], {})
        sens = res['conditions']['I6-F1']['m4_worst_without_runs_over_T_hold']
        s1 = next(s for s in sens if s['episode'] == 1)
        self.assertEqual(s1['runs_over_T_hold'], ['I6-p%02d-r0' % p['index']])
        self.assertEqual(s1['largest_excess_blocks'], 5)
        self.assertEqual(s1['summary']['n'], 9)


class RateRules(Base):
    def test_f10_detection_from_ledger_both_directions(self):
        lo = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        hi = point('M1-high-admissible', D_holding_blocks='T_case', Lambda_cheater='bucket_max')
        for i in range(30):
            # 1 of 100 detected (well below p_L = 0.0405); 10 of 100 detected (above).
            self.rs.add(lo, i, episodes=[dict(X=0)], sales=detection_sales(1 if i < 10 else 0, 100 - (1 if i < 10 else 0)),
                        sealed=[0])
            self.rs.add(hi, i, t_hold=58994, episodes=[dict(X=0)], sales=detection_sales(10, 90), sealed=[0])
        res = self.analyze()
        by = {m['label']: m for m in self.members(res, 'I6-F10')}
        self.assertEqual(by[lo['label']]['detections'], 10)
        self.assertEqual(by[lo['label']]['eligible'], 3000)
        self.assertAlmostEqual(by[lo['label']]['p_L'], 0.1 * (0.67 * 0.95) ** 2)
        self.assertEqual(by[lo['label']]['verdict'], 'excess_detected')
        self.assertEqual(by[hi['label']]['verdict'], 'certified')
        self.assertEqual(res['conditions']['I6-F10']['verdict'], 'triggered')
        # I6-F2 uses the same counts: threshold g / (exact lower bound of 10/3000).
        f2 = {m['label']: m for m in self.members(res, 'I6-F2')}
        self.assertAlmostEqual(f2[lo['label']]['p_star_L'], ia.clopper_pearson(10, 3000)[0])

    def test_f10_eligible_flag_and_missing_counts(self):
        p = point('M1-high-admissible', D_holding_blocks='T_hold', Lambda_cheater='bucket_max')
        sales = detection_sales(5, 95)
        for r in sales:
            r['detection_eligible'] = True
        self.rs.add(p, 0, episodes=[dict(X=0)], sales=sales)
        self.rs.add(p, 1, episodes=[dict(X=0)], sales=detection_sales(5, 95))  # no ledger, no flag
        res = self.analyze()
        m = self.members(res, 'I6-F10', p['label'])[0]
        self.assertEqual((m['detections'], m['eligible']), (5, 100))
        self.assertEqual(m['runs_without_counts'], ['I6-p%02d-r1' % p['index']])
        self.assertIn('I6-p%02d-r1' % p['index'], res['completeness']['required_fields']['I6-F10']['absent']['detection_counts'])

    def test_f8_rare_event_and_f9(self):
        hs = [point('H', scale_factor=n) for n in (1, 3, 7)]
        for p in hs:
            for i in range(10):
                wins = [dict(start=100 + j * 1000, end=1099 + j * 1000, wrongful_confirmed_failures=1, sanctioned=0)
                        for j in range(5)]
                sales = [dict(bad=False, case_trigger=1, case_state='FINAL', final_verdict='PASS', settled_block=200 + j)
                         for j in range(98)]
                sales += [dict(bad=False, case_trigger=1, case_state='FINAL', final_verdict='FAIL', settled_block=400)] * 2
                self.rs.add(p, i, n=p['parameters']['scale_factor'], honest_windows=wins, sales=sales,
                            extra=dict(honest_top_up_count=1, honest_max_window_scale=p['parameters']['scale_factor']))
        res = self.analyze()
        f8 = res['conditions']['I6-F8']
        self.assertEqual(f8['families'][0]['W'], 150)
        self.assertEqual(f8['families'][0]['Z'], 0)
        self.assertEqual(f8['verdict'], 'not_rejected')
        f9 = self.members(res, 'I6-F9')
        self.assertEqual(len(f9), 3)
        # 20 wrongful final FAILs of 1,000 sampled honest cases: 0.02 > 3 w1^2 = 0.004728.
        self.assertTrue(all(m['wrongful_final_fail'] == 20 and m['sampled_cases'] == 1000 for m in f9))
        self.assertAlmostEqual(f9[0]['three_w1_sq'], 3 * (0.67 * 0.01 + 0.33 * 0.1) ** 2)
        self.assertTrue(all(m['verdict'] == 'excess_detected' for m in f9))
        self.assertEqual(res['conditions']['I6-F9']['verdict'], 'triggered')
        self.assertEqual([m['k_n'] for m in f9], [16, 48, 112])

    def test_f8_one_sanction_rejects(self):
        p = point('H', scale_factor=1)
        for i in range(10):
            wins = [dict(start=100, end=1099, wrongful_confirmed_failures=0, sanctioned=1 if i == 3 else 0)]
            self.rs.add(p, i, honest_windows=wins)
        res = self.analyze()
        f = res['conditions']['I6-F8']['families'][0]
        self.assertEqual((f['W'], f['Z']), (10, 1))
        self.assertAlmostEqual(f['p_bound'], 1e-5)
        self.assertEqual(f['verdict'], 'rejected')
        self.assertEqual(len(f['evidence']), 1)


class InvariantRules(Base):
    def test_f11_counts_runs_outside_the_premise(self):
        p = point('P1-high', scale_factor=3)
        self.rs.add(p, 0, episodes=[dict(X=0)], case_paths=[(58_495, 0)], fault=[('injection_log', False)])
        self.rs.add(p, 1, episodes=[dict(X=0)], case_paths=[(59_000, 0)])
        self.rs.add(p, 2, episodes=[dict(X=0, L=G)], case_paths=[(20_000, 0)])
        self.rs.add(p, 3, episodes=[dict(X=0)], case_paths=[(20_000, 0)])
        res = self.analyze()
        a, b = res['conditions']['I6-F11a'], res['conditions']['I6-F11b']
        self.assertEqual(a['verdict'], 'violated')
        self.assertEqual(sorted(e['run_id'][-2:] for e in a['evidence']), ['r0', 'r1'])
        self.assertEqual(a['evidence'][0]['excluded_from_premise'], ['fault_observed:injection_log'])
        clauses = sorted((e['run_id'][-2:], e['clause']) for e in b['evidence'])
        self.assertEqual(clauses, [('r1', 'path_over_T_case'), ('r2', 'leak_within_margin')])
        leak = next(e for e in b['evidence'] if e['clause'] == 'leak_within_margin')
        self.assertEqual(leak['attributed_to'], 'freeze_at_confirmed_failure')

    def test_f11_not_violated(self):
        p = point('P1-high', scale_factor=3)
        for i in range(3):
            self.rs.add(p, i, episodes=[dict(X=0)], case_paths=[(29_680, 0)])
        res = self.analyze()
        self.assertEqual(res['conditions']['I6-F11a']['verdict'], 'not_violated')
        self.assertEqual(res['conditions']['I6-F11b']['verdict'], 'not_violated')

    def test_f12a_both_directions_and_post_switch_exclusion(self):
        up = point('F-stop', finite_attack_cheat_sales=1)
        down = point('F-exit', finite_attack_cheat_sales=25)
        sw = point('F-switch', finite_attack_cheat_sales=5)
        for i in range(100):
            self.rs.add(up, i, y_f=G if i % 10 else G // 2, episodes=[dict(net=G, mode='without_detection')],
                        params=dict(finite_attack_cheat_sales=1))
            self.rs.add(down, i, y_f=-250_000, episodes=[dict(net=-250_000)], params=dict(finite_attack_cheat_sales=25),
                        extra=dict(bond_exit_finalized_block=[5000], bond_exit_deferred_balance=[0],
                                   bond_exit_open_sampled_cases=[0]))
        self.rs.add(sw, 0, y_f=-G, episodes=[dict(net=-G)], fault=[('post_switch_no_confirmed_failure', False)],
                    extra=dict(post_switch_confirmed_failures=[dict(FAIL=1, UNSERVED=0)]))
        self.rs.add(sw, 1, y_f=-G, episodes=[dict(net=-G)], fault=[('post_switch_no_confirmed_failure', False)],
                    extra=dict(post_switch_confirmed_failures=[dict(FAIL=0, UNSERVED=2)]))
        self.rs.add(sw, 2, y_f=-G, episodes=[dict(net=-G)])
        res = self.analyze()
        by = {m['label']: m for m in self.members(res, 'I6-F12a')}
        self.assertEqual(by[up['label']]['verdict'], 'excess_detected')
        self.assertEqual(by[down['label']]['verdict'], 'certified')
        self.assertEqual(by[sw['label']]['summary']['n'], 1)
        self.assertEqual(by[sw['label']]['excluded_reasons'], {'post_switch_confirmed_failure:FAIL': 1,
                                                               'post_switch_confirmed_failure:UNSERVED': 1})
        self.assertEqual(by[sw['label']]['post_switch_confirmed_failures'], dict(FAIL=1, UNSERVED=2))
        # (1 - (1 - p)^m)(g/p - B/k) is 0 at B = k g ceil(1/p); predicted mean with p* = 0.0582.
        self.assertAlmostEqual(by[up['label']]['upper_bound'], 0.0)
        self.assertAlmostEqual(by[up['label']]['predicted_mean'] / G, -0.51, places=2)
        self.assertAlmostEqual(by[down['label']]['predicted_mean'] / G, -13.83, places=2)
        self.assertEqual(res['conditions']['I6-F12a']['verdict'], 'triggered')
        self.assertEqual(res['conditions']['I6-F12b']['verdict'], 'not_violated')

    def test_f12b_violation(self):
        p = point('F-exit', finite_attack_cheat_sales=1)
        self.rs.add(p, 0, y_f=G, extra=dict(bond_exit_finalized_block=[5000], bond_exit_deferred_balance=[10_000],
                                            bond_exit_open_sampled_cases=[0]))
        self.rs.add(p, 1, y_f=G, extra=dict(bond_exit_finalized_block=[], bond_exit_deferred_balance=[],
                                            bond_exit_open_sampled_cases=[]))
        res = self.analyze()
        b = res['conditions']['I6-F12b']
        self.assertEqual(b['verdict'], 'violated')
        self.assertEqual(b['runs_checked'], 2)
        self.assertEqual(b['evidence'][0]['deferred_balance'], 10_000)

    def test_positive_controls(self):
        over = point('P5-over')
        short = point('P5-short-hold')
        for i in range(30):
            self.rs.add(over, i, kappa=30420, episodes=[dict(X=0, L=5 * G if i < 20 else 0)], case_paths=[(60100, 30420)])
            self.rs.add(short, i, t_hold=29580, episodes=[dict(X=0, L=0)])
        res = self.analyze()
        by = {c['label']: c for c in res['conditions']['I6-PC']['cells']}
        design = {c['label']: c['premise_by_design'] for c in res['cells']}
        self.assertEqual(design[over['label']], ['keeper_delay_above_margin'])
        self.assertEqual(design[short['label']], ['hold_below_T_case'])
        self.assertEqual(by[over['label']]['verdict'], 'passed_cause_under_investigation')
        self.assertEqual(by[over['label']]['runs_with_leak'], 20)
        self.assertEqual(len(by[over['label']]['runs_with_zero_leak']), 10)
        self.assertEqual(by[short['label']]['verdict'], 'failed')
        self.assertEqual(res['conditions']['I6-PC']['verdict'], 'failed')
        # The keeper delay above the margin is by design: no keeper-margin exclusion in these cells.
        self.assertEqual(res['runs']['premise_outside'], {})

    def test_availability(self):
        p = point('V-9')
        sales = [dict(bad=True, case_trigger=1, settled_block=i, index=i, nonce=f'n{i}', case_state='INCONCLUSIVE')
                 for i in range(40)]
        fails = [dict(nonce=f'n{i}', stage='tiebreak', cause='liability_or_draw') for i in range(10)]
        fails.append(dict(nonce='n35', stage='initial', cause='participation'))  # after the first 30
        self.rs.add(p, 0, sales=sales, params=dict(assignable_verifiers=9),
                    extra=dict(assignment_failure=fails, verifier_removed_count=3, verifier_replacement_count=3))
        res = self.analyze()
        v = res['conditions']['I6-V']['cells'][0]
        self.assertEqual((v['cases'], v['assignment_failures']), (30, 10))
        self.assertEqual(v['interval_95'], ia.clopper_pearson(10, 30))
        self.assertAlmostEqual(v['prediction'], (8 / 9) ** 9)
        self.assertEqual(v['registered_prediction'], 0.346)
        self.assertEqual(v['stages'], {'tiebreak': 10})


# ---------------------------------------------------------------------------------------------
# Selection, exclusion, missing data, determinism


class Selection(Base):
    def test_exclusion_handling(self):
        p = point('P1-high', scale_factor=3)
        self.rs.add(p, 0, episodes=[dict(X=0)])
        self.rs.add(p, 1, episodes=[dict(X=0)], smoke={'episodes': 1})
        self.rs.add(p, 2, episodes=[dict(X=0)], dirty=True)
        self.rs.add(p, 3, episodes=[dict(X=0)], status='failed')
        self.rs.add(p, 4, episodes=[dict(X=0)], fault=[('kappa_sigma', False), ('bad_responses', True)])
        self.rs.add(p, 5, episodes=[dict(X=0)], mismatch=2)
        self.rs.add(p, 6, episodes=[dict(X=0)], kappa_max=1007)
        self.rs.add(p, 7, episodes=[dict(X=0)], kappa_max=1006)
        self.rs.add(p, 8, episodes=[dict(X=0)])
        res = ia.analyze(self.tmp, SCENARIO, ia.Options(resamples=100, manual_exclusions={
            'I6-p%02d-r8' % p['index']: 'service restart in the log'}))
        rid = lambda r: 'I6-p%02d-r%d' % (p['index'], r)  # noqa: E731
        self.assertEqual(res['runs']['dropped']['smoke'], [rid(1) + '-smoke'])
        self.assertEqual(res['runs']['dropped']['dirty'], [rid(2)])
        self.assertEqual([f['run_id'] for f in res['runs']['failed']], [rid(3)])
        out = res['runs']['premise_outside']
        self.assertEqual(out[rid(4)], ['fault_observed:kappa_sigma'])
        self.assertEqual(out[rid(5)], ['injection_draw_mismatch'])
        self.assertEqual(out[rid(6)], ['keeper_margin_exceeded'])
        self.assertEqual(out[rid(8)], ['manual:service restart in the log'])
        self.assertNotIn(rid(7), out)
        cell = next(c for c in res['cells'] if c['point'] == p['index'])
        self.assertEqual(cell['runs']['included'], 2)
        self.assertEqual(cell['runs']['failed'], 1)
        comp = next(c for c in res['completeness']['points'] if c['point'] == p['index'])
        # Smoke and dirty runs are not planned runs: their repetitions stay missing.
        self.assertEqual(comp['missing_repetitions'], [1, 2] + list(range(9, 30)))
        # --ignore-fault-item takes the item out of the premise rule.
        res2 = ia.analyze(self.tmp, SCENARIO, ia.Options(resamples=100, ignore_fault_items=['kappa_sigma']))
        self.assertNotIn(rid(4), res2['runs']['premise_outside'])

    def test_rows_only_and_missing_fields(self):
        p = point('P1-high', scale_factor=3)
        self.rs.add(p, 0, episodes=[dict(X=0)], rows_only=True)
        res = self.analyze()
        self.assertEqual(res['runs']['without_full_document'], ['I6-p%02d-r0' % p['index']])
        absent = res['completeness']['required_fields']['I6-F1']['absent']
        self.assertIn('run.g', absent)
        self.assertNotIn('op.p_ceiling', absent)  # the operating point comes from the envelope
        self.assertEqual(self.members(res, 'I6-F1', p['label'])[0]['verdict'], 'no_data')
        self.assertTrue(res['completeness']['points_without_runs'])
        self.assertEqual(res['cap_off_check']['runs'], 0)

    def test_open_episode_option(self):
        p = point('P1-high', scale_factor=3)
        for i in range(10):
            self.rs.add(p, i, episodes=[dict(X=G, mode='open' if i < 5 else 'with_detection')])
        inc = self.members(self.analyze(), 'I6-F1', p['label'])[0]['summary']['n']
        exc = self.members(self.analyze(open_episodes='exclude'), 'I6-F1', p['label'])[0]['summary']['n']
        self.assertEqual((inc, exc), (10, 5))

    def test_deterministic_outputs(self):
        p = point('P1-high', scale_factor=7)
        q = point('F-stop', finite_attack_cheat_sales=5)
        for i in range(30):
            self.rs.add(p, i, episodes=[dict(X=(i * 7919) % 50 * 1000, net=-i * 100)])
            self.rs.add(q, i, y_f=(i % 4 - 2) * G)
        out1, out2 = self.tmp / 'o1', self.tmp / 'o2'
        opts = dict(resamples=500)
        ia.write_outputs(ia.analyze(self.tmp / 'results' / '..', SCENARIO, ia.Options(**opts)), out1)
        ia.write_outputs(ia.analyze(self.tmp, SCENARIO, ia.Options(**opts)), out2)
        names = sorted(x.name for x in out1.iterdir())
        self.assertEqual(names, sorted(x.name for x in out2.iterdir()))
        self.assertIn('i6_results.json', names)
        self.assertIn('i6_tables.md', names)
        self.assertIn('table_I6-5_finite_attack.csv', names)
        for n in names:
            self.assertEqual((out1 / n).read_bytes(), (out2 / n).read_bytes(), n)
        # The order in which run envelopes are added does not change the result.
        a = ia.Analysis(SC, ia.Options(**opts))
        for path, env in reversed(ia.find_envelopes(self.tmp)):
            a.add(path, env)
        self.assertEqual(json.dumps(a.result(), sort_keys=True, default=str),
                         json.dumps(ia.analyze(self.tmp, SCENARIO, ia.Options(**opts)), sort_keys=True, default=str))
        text = (out1 / 'i6_results.json').read_text()
        self.assertNotIn(str(self.tmp), text)
        md = (out1 / 'i6_tables.md').read_text()
        self.assertIn('## I6-5_finite_attack', md)

    def test_cli(self):
        p = point('P1-high', scale_factor=3)
        self.rs.add(p, 0, episodes=[dict(X=0)])
        out = self.tmp / 'cli'
        code = ia.main(['--runs', str(self.tmp), '--scenario', str(SCENARIO), '--out', str(out), '--allow-dirty',
                        '--resamples', '200', '--p-star', 'data-api-fast-v1=0.06', '--v-rounds', '9:14,12:14,20:14,40:14'])
        self.assertEqual(code, 0)
        res = json.loads((out / 'i6_results.json').read_text())
        self.assertEqual(res['options']['p_star']['data-api-fast-v1'], 0.06)
        self.assertEqual(res['options']['v_rounds']['12'], 14)
        self.assertIn('source', res)


if __name__ == '__main__':
    unittest.main()
