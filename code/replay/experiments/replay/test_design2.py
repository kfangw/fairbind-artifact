"""Design-2 switches of the replay: amount cap, per-row sampling, unit bond, envelope multiplier,
holding period, the design-2 mode of the operating-point check, and a run on a synthetic list."""
import csv
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import design2  # noqa: E402
import engine  # noqa: E402
import inputs  # noqa: E402
import replay  # noqa: E402
import rules  # noqa: E402
import test_replay as tr  # noqa: E402
from bucket import PPM  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402

REFILL = 50_000
TAU = {'0.1': 100_000, '0.2': 200_000, '1': 1_000_000}


def replay_params():
    return prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')['parameters']


def make_d2(**kw):
    config = design2.load_config()
    op = opt.load(replay.default_operating_point(inputs.load_conditions()))
    args = dict(vmax_usdc='0.2', k=27, hold=30180, failure_window=30180, source='insample', margin='1',
                rounding='contract', floor_rule='product', edition=1)
    args.update(kw)
    return design2.Design2(config, op, **args)


class SamplingRate(unittest.TestCase):
    def test_s_ppm_at_the_cap_and_one_atomic_unit(self):
        for tau in TAU.values():
            self.assertEqual(design2.s_ppm(tau, tau), PPM)                      # v = tau: always sampled
            self.assertEqual(design2.s_ppm(tau + 5, tau), PPM)                  # clipped at 1
            self.assertEqual(design2.s_ppm(1, tau), -(-PPM // tau))             # v = 1 atomic unit, rounded up
        self.assertEqual([design2.s_ppm(1, t) for t in TAU.values()], [10, 5, 1])
        # tau not dividing 10^6: ceil, never floor (D2-2 (b)).
        self.assertEqual(design2.s_ppm(1, 300_000), 4)
        self.assertEqual(design2.s_ppm(150_000, 300_000), 500_000)
        self.assertEqual(design2.s_ppm(150_001, 300_000), 500_004)

    def test_ceil_never_below_proportional(self):
        rng = random.Random(3)
        for _ in range(200):
            tau = rng.randrange(1, 2_000_000)
            v = rng.randrange(1, tau + 1)
            s = design2.s_ppm(v, tau)
            self.assertGreaterEqual(s * tau, v * PPM)
            if s < PPM:
                self.assertLess((s - 1) * tau, v * PPM)
        arr = design2.s_ppm(np.array([1, 10_000, 100_000, 300_000], dtype=np.int64), 100_000)
        self.assertEqual(arr.tolist(), [10, 100_000, PPM, PPM])

    def test_tau_one_tenth_gives_todays_threshold_at_one_cent(self):
        p = replay_params()
        s = design2.s_ppm(10_000, TAU['0.1'])
        self.assertEqual(s, p['samplePpm'])
        self.assertEqual(design2.threshold_of(s, 'contract'), engine.probability_threshold(p['samplePpm']))
        self.assertEqual(design2.threshold_contract(PPM), 2**256 - 1)
        self.assertEqual(design2.threshold_contract(0), 0)
        for ppm in (1, 10, 100_000, 999_999):
            self.assertEqual(design2.threshold_contract(ppm), engine.probability_threshold(ppm))
            self.assertLessEqual(design2.threshold_ceil(ppm) - design2.threshold_contract(ppm), 1)
            self.assertGreaterEqual(design2.threshold_ceil(ppm), design2.threshold_contract(ppm))

    def test_same_draw_as_design_one_for_rows_at_one_cent(self):
        rng = random.Random(5)
        epochs = np.array([rng.randrange(0, 40) for _ in range(3000)], dtype=np.int64)
        rows = np.arange(3000, dtype=np.int64)
        values = np.full(3000, 10_000, dtype=np.int64)
        a = engine.sampled('0xabc', epochs, rows, 7, 100_000)
        b = engine.sampled('0xabc', epochs, rows, 7, design2.s_ppm(values, TAU['0.1']))
        self.assertTrue((a == b).all())
        self.assertTrue(a.any() and not a.all())
        # The ceil rounding of D2-3 changes no draw on three thousand rows (it differs in one of 2^256 values).
        c = engine.sampled('0xabc', epochs, rows, 7, design2.s_ppm(values, TAU['0.1']), 'ceil')
        self.assertTrue((a == c).all())

    def test_value_at_the_cap_is_always_sampled_and_rates_follow_value(self):
        n = 4000
        epochs = np.zeros(n, dtype=np.int64)
        rows = np.arange(n, dtype=np.int64)
        for tau in TAU.values():
            at_cap = engine.sampled('0xabc', epochs, rows, 1, design2.s_ppm(np.full(n, tau, dtype=np.int64), tau))
            self.assertTrue(at_cap.all())
        tau = TAU['0.2']
        half = engine.sampled('0xabc', epochs, rows, 1, design2.s_ppm(np.full(n, tau // 2, dtype=np.int64), tau))
        self.assertAlmostEqual(half.mean(), 0.5, delta=0.05)
        tiny = engine.sampled('0xabc', epochs, rows, 1, design2.s_ppm(np.full(n, 2_000, dtype=np.int64), tau))
        self.assertAlmostEqual(tiny.mean(), 0.01, delta=0.01)


class UnitBond(unittest.TestCase):
    def test_bond_table(self):
        margin = make_d2().bond_margin
        self.assertEqual(margin, design2.Fraction(40, 27))
        p0 = 400_000
        self.assertEqual([design2.unit_bond(27, t, p0, margin) for t in TAU.values()], [10_000_000, 20_000_000, 100_000_000])
        # k = 40 at tau = 0.2: 29.63 USDC.
        self.assertEqual(design2.unit_bond(40, TAU['0.2'], p0, margin), 29_629_629)
        self.assertEqual(design2.unit_bond(100, TAU['0.2'], p0, margin), 74_074_074)

    def test_deduction_per_failure_is_nearly_independent_of_k(self):
        margin = make_d2().bond_margin
        for k in (27, 54, 81):
            d = make_d2(k=k)
            self.assertAlmostEqual(d.bond / k, design2.unit_bond(27, d.tau, 400_000, margin) / 27, delta=1)

    def test_floor_rules(self):
        self.assertEqual(design2.penalty_floor2(200_000, 400_000, 'product'), 500_000)   # 2.5 tau
        self.assertEqual(design2.penalty_floor2(200_000, 400_000, 'ratio'), 600_000)     # 3 tau
        for tau in TAU.values():
            self.assertGreaterEqual(design2.unit_bond(27, tau, 400_000, design2.Fraction(40, 27)),
                                    27 * design2.penalty_floor2(tau, 400_000, 'ratio'))

    def test_tau_must_be_whole_atomic_units(self):
        self.assertEqual(design2.tau_atomic('0.2', 6), 200_000)
        with self.assertRaises(ValueError):
            design2.tau_atomic('0.0000001', 6)
        with self.assertRaises(ValueError):
            make_d2(vmax_usdc='0.3')


class AmountCap(unittest.TestCase):
    def run_address(self, values, blocks, cap, capacity=1, scale=1, **kw):
        p = replay_params()
        n = len(values)
        arrays = (np.array(blocks, dtype=np.int64), np.array(values, dtype=np.int64),
                  np.arange(n, dtype=np.int64), np.zeros(n, dtype=np.int64))
        row, _ = engine.replay_address('0xabc', arrays, seed=1, p=p, capacity=capacity, scale=scale, origin_ledger=0,
                                       local_origin=p['epochOrigin'], end_ledger=2000, block_size={},
                                       window_blocks=2000, first_seconds=0, observed=False, cap=cap, **kw)
        return row

    def test_cap_rejections_are_counted_apart_and_do_not_use_the_bucket(self):
        # Bucket of one token, refill 0.05 per block: the capped settlements must not take the token.
        row = self.run_address([300, 300, 10, 10], [0, 1, 2, 3], cap=100)
        self.assertEqual((row['cap_rejected_count'], row['cap_rejected_value']), (2, 600))
        self.assertEqual((row['accepted_count'], row['rate_rejected_count']), (1, 1))
        self.assertEqual(row['rejected_count'], row['rate_rejected_count'])
        self.assertEqual(row['attempted_count'], 4)
        self.assertEqual(row['rate_rejected_value'], 10)
        self.assertEqual(row['accepted_value'], 10)

    def test_value_equal_to_the_cap_passes(self):
        row = self.run_address([100, 101], [0, 100], cap=100)
        self.assertEqual((row['cap_rejected_count'], row['accepted_count']), (1, 1))

    def test_without_cap_the_row_is_the_design_one_row(self):
        row = self.run_address([300, 300, 10, 10], [0, 1, 2, 3], cap=None)
        self.assertNotIn('cap_rejected_count', row)
        self.assertEqual((row['accepted_count'], row['rejected_count']), (1, 3))

    def test_counts_add_up(self):
        rng = random.Random(9)
        blocks = sorted(rng.sample(range(1500), 300))
        values = [rng.choice((10, 50, 500)) for _ in blocks]
        capped = self.run_address(values, blocks, cap=100, capacity=5)
        self.assertEqual(capped['attempted_count'], capped['accepted_count'] + capped['cap_rejected_count']
                         + capped['rate_rejected_count'])
        self.assertEqual(capped['cap_rejected_count'], sum(v > 100 for v in values))


class EnvelopeMultiplier(unittest.TestCase):
    q = 10

    def test_synthetic_burst(self):
        self.assertEqual(design2.fit_scale([5] * 100, self.q, REFILL), 10)
        self.assertEqual(design2.fit_scale([5] * 101, self.q, REFILL), 11)
        # a second burst after 20 blocks: 200 settlements in a window worth q + 0.05 * 20 = 11 per unit.
        trace = [0] * 100 + [20] * 100
        self.assertEqual(design2.fit_scale(trace, self.q, REFILL), 19)
        self.assertFalse(design2.all_admitted(np.array(trace), self.q, REFILL, 18))
        self.assertTrue(design2.all_admitted(np.array(trace), self.q, REFILL, 19))
        self.assertEqual(design2.fit_scale([], self.q, REFILL), 1)
        self.assertEqual(design2.fit_scale([7], self.q, REFILL), 1)

    def test_steady_rate(self):
        trace = list(range(2000))
        n = design2.fit_scale(trace, self.q, REFILL)
        self.assertEqual(n, design2.envelope_scale_bruteforce(trace, self.q, REFILL))
        self.assertGreaterEqual(n, 18)
        self.assertLessEqual(n, 20)

    def test_bisection_equals_the_closed_form_envelope(self):
        rng = random.Random(21)
        for _ in range(60):
            m = rng.randrange(1, 120)
            span = rng.choice((5, 60, 400))
            trace = sorted(rng.randrange(span) for _ in range(m))
            for q in (1, 3, 10):
                self.assertEqual(design2.fit_scale(trace, q, REFILL), design2.envelope_scale_bruteforce(trace, q, REFILL))

    def test_margin_rounds_up(self):
        m15, m2 = design2.parse_margin('1.5'), design2.parse_margin('2')
        self.assertEqual([design2.margin_scale(n, m15) for n in (1, 2, 3, 10)], [2, 3, 5, 15])
        self.assertEqual([design2.margin_scale(n, m2) for n in (1, 7)], [2, 14])
        self.assertEqual(design2.margin_scale(7, design2.parse_margin('1')), 7)
        with self.assertRaises(ValueError):
            design2.parse_margin('0.5')

    def arrays(self, blocks, values):
        return (np.array(blocks, dtype=np.int64), np.array(values, dtype=np.int64))

    def test_sources(self):
        tau = 100
        replay_rows = self.arrays([0] * 50 + [2000] * 30, [10] * 80)
        prior = type('P', (), {})()
        prior.per = {'a': self.arrays([0] * 100, [10] * 100), 'b': self.arrays([], [])}
        plan = design2.MultiplierPlan('prior14', design2.parse_margin('1'), tau, prior=prior, mid_block=1000, first_block=0)
        self.assertEqual(plan.scale('a', replay_rows, self.q, REFILL), (10, None))
        self.assertEqual(plan.scale('b', replay_rows, self.q, REFILL), (1, None))      # no fitting record: n = 1
        ins = design2.MultiplierPlan('insample', design2.parse_margin('1'), tau, mid_block=1000, first_block=0)
        self.assertEqual(ins.scale('a', replay_rows, self.q, REFILL), (5, None))
        # cross: the first half (50 at block 0) runs with the multiplier fitted on the second half (30 -> 3).
        cross = design2.MultiplierPlan('cross', design2.parse_margin('1'), tau, mid_block=1000, first_block=0)
        self.assertEqual(cross.scale('a', replay_rows, self.q, REFILL), (5, [(0, 3), (1000, 5)]))
        marg = design2.MultiplierPlan('insample', design2.parse_margin('1.5'), tau, mid_block=1000, first_block=0)
        self.assertEqual(marg.scale('a', replay_rows, self.q, REFILL), (8, None))
        self.assertEqual(marg.name, 'nE-insample-m1.5')
        self.assertEqual(plan.name, 'nE-prior14-m1')

    def test_records_above_the_cap_do_not_enter_the_fit(self):
        plan = design2.MultiplierPlan('insample', design2.parse_margin('1'), 100, mid_block=10, first_block=0)
        rows = self.arrays([0] * 100, [500] * 50 + [10] * 50)
        self.assertEqual(plan.scale('a', rows, self.q, REFILL)[0], 5)

    def test_in_sample_multiplier_leaves_no_rate_rejection(self):
        rng = random.Random(4)
        p = replay_params()
        blocks = sorted(rng.sample(range(1500), 400))
        values = [rng.choice((10, 50, 500)) for _ in blocks]
        arrays = (np.array(blocks, dtype=np.int64), np.array(values, dtype=np.int64),
                  np.arange(400, dtype=np.int64), np.zeros(400, dtype=np.int64))
        plan = design2.MultiplierPlan('insample', design2.parse_margin('1'), 100, mid_block=750, first_block=0)
        n, seg = plan.scale('a', arrays, 3, p['refillPpmPerBlock'])
        kw = dict(seed=2, p=p, capacity=3, origin_ledger=0, local_origin=p['epochOrigin'], end_ledger=2000,
                  block_size={}, window_blocks=2000, first_seconds=0, observed=False, cap=100)
        row, _ = engine.replay_address('a', arrays, scale=n, segments=seg, **kw)
        self.assertEqual(row['rate_rejected_count'], 0)
        self.assertGreater(row['cap_rejected_count'], 0)
        # one multiplier less rejects (the fit is the least n)
        row2, _ = engine.replay_address('a', arrays, scale=n - 1, **kw)
        self.assertGreater(row2['rate_rejected_count'], 0)

    def test_segments_restart_the_bucket_at_each_part(self):
        p = replay_params()
        blocks = np.array([0] * 4 + [1000] * 4, dtype=np.int64)
        arrays = (blocks, np.full(8, 10, dtype=np.int64), np.arange(8, dtype=np.int64), np.zeros(8, dtype=np.int64))
        kw = dict(seed=1, p=p, capacity=2, origin_ledger=0, local_origin=p['epochOrigin'], end_ledger=2000,
                  block_size={0: 4, 1000: 4}, window_blocks=2000, first_seconds=0, observed=False, cap=100)
        both = engine.replay_address('a', arrays, scale=2, segments=[(0, 2), (1000, 2)], **kw)[0]
        self.assertEqual(both['accepted_count'], 8)
        second_small = engine.replay_address('a', arrays, scale=2, segments=[(0, 2), (1000, 1)], **kw)[0]
        self.assertEqual(second_small['accepted_count'], 6)


class HoldingPeriod(unittest.TestCase):
    def setUp(self):
        self.cond = inputs.load_conditions()
        self.op = opt.load(replay.default_operating_point(self.cond))
        self.base = prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')

    def overlay(self, **kw):
        d2 = make_d2(**kw)
        p2 = d2.apply_profile(self.base)
        return d2, p2, d2.apply_op(self.op, 'data-api-fast-v1', p2, prof.case_horizon(p2))

    def test_one_switch_sets_the_three_windows_and_another_the_failure_windows(self):
        d2, p2, _ = self.overlay(hold=30180, failure_window=60000)
        p = p2['parameters']
        self.assertEqual({p['deferBlocks'], p['retentionBlocks'], p['claimWindowBlocks']}, {30180})
        self.assertEqual({p['failureWindowBlocks'], p['inconclusiveWindowBlocks']}, {60000})
        with self.assertRaises(ValueError):
            make_d2(hold=1234)
        with self.assertRaises(ValueError):
            make_d2(failure_window=40000)
        self.assertEqual(self.base['parameters']['deferBlocks'], 60000)       # the base profile is not touched

    def test_design_one_check_refuses_a_negative_keeper_margin_design_two_names_it(self):
        d2, p2, op2 = self.overlay()
        self.assertEqual(op2['profiles']['data-api-fast-v1']['keeper_margin_blocks']['value'], 30180 - 58994)
        errors1 = opt.check(op2, p2)
        self.assertTrue(any('negative keeper margin' in e for e in errors1), errors1)
        self.assertEqual(design2.check(op2, p2, d2), [])
        notes = design2.keeper_notes(op2, p2)
        self.assertEqual(notes['keeper_margin_blocks'], -28814)
        self.assertEqual(notes['keeper_slack_over_L_actual_blocks'], 500)

    def test_design_two_mode_still_checks_the_hold_period(self):
        d2, p2, op2 = self.overlay()
        bad = json.loads(json.dumps(p2))
        for key in ('deferBlocks', 'retentionBlocks', 'claimWindowBlocks'):
            bad['parameters'][key] = 29000
        op_bad = json.loads(json.dumps(op2))
        e = op_bad['profiles']['data-api-fast-v1']
        e['hold_period_blocks']['value'] = 29000
        e['keeper_margin_blocks']['value'] = 29000 - 58994
        errors = design2.check(op_bad, bad, d2)
        self.assertTrue(any('longest path' in x for x in errors), errors)
        op_off = json.loads(json.dumps(op2))
        op_off['profiles']['data-api-fast-v1']['hold_period_blocks']['value'] = 60000
        self.assertTrue(design2.check(op_off, p2, d2))
        p_off = json.loads(json.dumps(p2))
        p_off['parameters']['retentionBlocks'] = 31000
        self.assertTrue(design2.check(op2, p_off, d2))
        p_win = json.loads(json.dumps(p2))
        p_win['parameters']['failureWindowBlocks'] = 12345
        self.assertTrue(any('window length' in x for x in design2.check(op2, p_win, d2)))

    def test_design_one_values_still_pass_design_one_check(self):
        self.assertEqual(opt.check(self.op, self.base), [])
        with self.assertRaises(opt.OperatingPointError):
            opt.check(self.op, self.base, mode='design-3')

    def test_every_tau_and_hold_choice_is_consistent(self):
        config = design2.load_config()
        for tau in config['vmax_choices_usdc']:
            for hold in config['hold_choices_blocks']:
                for fw in config['failure_window_choices_blocks']:
                    for rule in ('product', 'ratio'):
                        d2, p2, op2 = self.overlay(vmax_usdc=tau, hold=hold, failure_window=fw, floor_rule=rule)
                        self.assertEqual(design2.check(op2, p2, d2), [], (tau, hold, fw, rule))
                        e = op2['profiles']['data-api-fast-v1']
                        self.assertEqual(e['pi']['value'], 1.0)
                        self.assertAlmostEqual(e['p_ceiling']['value'], 0.4)
                        self.assertLessEqual(e['p_ceiling']['value'], e['p_ceiling']['bound'])


class DesignTwoRun(unittest.TestCase):
    """Runs on the synthetic list (values 1000, 10000 and 50000 atomic units)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.s = tr.synthetic(d)
        (d / 'prior_dir').mkdir()
        cls.prior_csv = tr.synthetic(d / 'prior_dir', seed=2)['csv']
        cond = json.loads(Path(cls.s['conditions']).read_text())
        cond['inputs']['prior_period']['sha256'] = inputs.sha256_file(cls.prior_csv)
        cls.conditions = d / 'conditions_with_prior.json'
        cls.conditions.write_text(json.dumps(cond, indent=1))
        config = design2.load_config()
        config['vmax_choices_usdc'] = ['0.01'] + config['vmax_choices_usdc']
        cls.config = d / 'design2.json'
        cls.config.write_text(json.dumps(config))
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)

    @classmethod
    def tearDownClass(cls):
        replay.git_state = cls._git
        cls.tmp.cleanup()

    def argv(self, out, conditions_file=None, *extra):
        return ['--settlements', str(self.s['csv']), '--conditions-file', str(conditions_file or self.conditions),
                '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '3',
                '--conditions', '1', '--repetitions', '1', '--design', '2', '--d2-edition', '1', '--d2-config', str(self.config), *extra]

    def run_replay(self, name, *extra):
        out = Path(self.tmp.name) / name
        c, _ = tr.run_cli(self.argv(out, None, *extra))
        self.assertEqual(c, 0)
        return out, json.loads((out / 'run.json').read_text())

    def rows(self, out, name='addresses_observed.csv', cond='condition-01-seed-0'):
        return list(csv.DictReader(tr._open(out / cond / name)))

    def test_cap_rejections_and_columns(self):
        out, env = self.run_replay('cap', '--tau', '0.01', '--multiplier-source', 'insample')
        self.assertEqual(env['design'], 'design-2')
        self.assertEqual(env['operating_point_errors'], [])
        rows = self.rows(out)
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertIsNone(meta['sample_rate'])
        self.assertEqual(meta['sample_rule']['tau_atomic'], 10_000)
        self.assertEqual(meta['scale_rule'], 'nE-insample-m1')
        self.assertEqual(meta['hold_blocks'], 30180)
        self.assertEqual(meta['sellerPenalty'], design2.unit_bond(27, 10_000, 400_000, design2.Fraction(40, 27)))
        self.assertGreater(sum(int(r['cap_rejected_count']) for r in rows), 0)
        for r in rows:
            self.assertEqual(int(r['attempted_count']), int(r['accepted_count']) + int(r['cap_rejected_count'])
                             + int(r['rate_rejected_count']))
            self.assertEqual(int(r['rejected_count']), int(r['rate_rejected_count']))
            self.assertEqual(int(r['rate_rejected_count']), 0)       # in-sample multiplier
            self.assertEqual(int(r['bond_B']), meta['sellerPenalty'])
        above = sum(1 for line in tr._open(self.s['csv']).read().splitlines()[1:] if int(line.split(',')[7]) > 10_000)
        self.assertEqual(meta['list_rows'] - meta['list_cap_pass_rows'], above)
        groups = {r['group']: r for r in self.rows(out, 'groups_observed.csv')}
        self.assertEqual(int(groups['replayed']['cap_rejected_count']), sum(int(r['cap_rejected_count']) for r in rows))
        self.assertEqual(int(groups['replayed']['bond_sum']), sum(int(r['nB']) for r in rows))

    def test_sampling_check_uses_the_poisson_binomial_and_rules_run(self):
        out, env = self.run_replay('rules', '--tau', '0.1', '--multiplier-source', 'prior14',
                                   '--prior-settlements', str(self.prior_csv))
        self.assertTrue(env['reportable'], env['not_reportable_reasons'])
        self.assertEqual(env['design2_prior_input']['sha256'], inputs.sha256_file(self.prior_csv))
        res = rules.evaluate([out], conditions_path=self.conditions)
        seed0 = res['runs'][0]['seeds'][0]
        self.assertEqual(seed0['R20-C2-samples']['distribution'], 'poisson binomial (per-row sampling rates)')
        self.assertLess(abs(seed0['R20-C2-samples']['statistic']), 4)
        self.assertEqual(seed0['R20-C3']['verdict'], 'pass')
        self.assertIsNotNone(seed0['R20-C1']['statistic'])
        self.assertIn('not evaluated', seed0['R20-M1']['verdict'])
        inj = self.rows(out, 'addresses_injection.csv')
        self.assertTrue(all(r['s_rate_per_block'] != '' for r in inj))

    def test_design_two_is_not_blocked_by_design_one_scales_but_design_one_still_is(self):
        cond = json.loads(self.conditions.read_text())
        cond['expected_scales']['nF'][tr.addr(0)] = 2      # a registered design-1 scale the run does not give
        tampered = Path(self.tmp.name) / 'conditions_tampered.json'
        tampered.write_text(json.dumps(cond))
        base = ['--settlements', str(self.s['csv']), '--conditions-file', str(tampered), '--reference-dir',
                str(self.s['dir']), '--qx', '137', '--draws', '2', '--conditions', '1', '--repetitions', '1']
        with self.assertRaises(SystemExit) as ctx:
            tr.run_cli(base + ['--out', str(Path(self.tmp.name) / 'd1x')])
        self.assertIn('scale check failed', str(ctx.exception))
        code, _ = tr.run_cli(base + ['--out', str(Path(self.tmp.name) / 'd2x'), '--design', '2',
                                     '--d2-config', str(self.config), '--tau', '0.1', '--multiplier-source', 'insample'])
        self.assertEqual(code, 0)

    def test_the_nR_scale_check_still_applies_in_design_two(self):
        cond = json.loads(self.conditions.read_text())
        cond['expected_scales']['nR'][tr.addr(0)] = 2
        tampered = Path(self.tmp.name) / 'conditions_tampered_nR.json'
        tampered.write_text(json.dumps(cond))
        with self.assertRaises(SystemExit):
            tr.run_cli(self.argv(Path(self.tmp.name) / 'nRx', tampered, '--tau', '0.1', '--multiplier-source', 'insample'))

    def test_hold_and_window_switches_reach_the_run(self):
        out, env = self.run_replay('hold', '--tau', '0.1', '--multiplier-source', 'insample', '--hold', '60000',
                                   '--failure-window', '30180')
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual(meta['hold_blocks'], 60000)
        self.assertEqual(meta['design2']['failure_window_blocks'], 30180)
        self.assertEqual(meta['failure_window_edges'][1] - meta['failure_window_edges'][0], 30180)
        self.assertEqual(env['operating_point_errors'], [])

    def test_cross_source_and_margin(self):
        out, env = self.run_replay('cross', '--tau', '0.1', '--multiplier-source', 'cross', '--multiplier-margin', '2')
        rows = self.rows(out)
        self.assertTrue(any(r['scale_segments'] for r in rows))
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual(meta['scale_rule'], 'nE-cross-m2')

    def test_switches_without_design_two_and_a_wrong_prior_list_are_refused(self):
        with self.assertRaises(SystemExit):
            tr.run_cli(['--settlements', str(self.s['csv']), '--conditions-file', str(self.conditions), '--reference-dir',
                        str(self.s['dir']), '--qx', '137', '--out', str(Path(self.tmp.name) / 'x'), '--tau', '0.1'])
        with self.assertRaises(SystemExit):
            tr.run_cli(self.argv(Path(self.tmp.name) / 'y', None, '--tau', '0.1', '--multiplier-source', 'prior14',
                                 '--prior-settlements', str(self.s['csv'])))

    def test_report_columns_add_up(self):
        import d2_report
        out, _ = self.run_replay('rep', '--tau', '0.01', '--multiplier-source', 'prior14',
                                 '--prior-settlements', str(self.prior_csv))
        r = d2_report.report(out, 1, 0, 'A')
        for g in ('replayed', 'A'):
            x = r[g]
            self.assertEqual(x['attempted_count'], x['accepted_count'] + x['cap_rejected_count'] + x['rate_rejected_count'])
            self.assertAlmostEqual(x['accepted_value_usdc'] + x['cap_rejected_value_usdc'] <= x['attempted_value_usdc'] + 1e-9, True)
            self.assertGreater(x['cap_rejected_count'], 0)
            self.assertGreater(x['inspections_expected'], 0)
        self.assertEqual(r['design'], 2)
        self.assertEqual(r['unit_bond_usdc'], design2.unit_bond(27, 10_000, 400_000, design2.Fraction(40, 27)) / 1e6)

    def test_design_two_run_is_deterministic(self):
        a, _ = self.run_replay('det1', '--tau', '0.2', '--multiplier-source', 'insample')
        b, _ = self.run_replay('det2', '--tau', '0.2', '--multiplier-source', 'insample')
        for f in sorted(p.relative_to(a) for p in a.rglob('*.csv')):
            self.assertEqual((a / f).read_bytes(), (b / f).read_bytes(), f)


class DesignOneUnchanged(unittest.TestCase):
    def test_design_one_rows_have_no_design_two_keys(self):
        p = replay_params()
        arrays = (np.array([0, 5], dtype=np.int64), np.array([10, 20], dtype=np.int64),
                  np.arange(2, dtype=np.int64), np.zeros(2, dtype=np.int64))
        row, arr = engine.replay_address('a', arrays, seed=1, p=p, capacity=3, scale=1, origin_ledger=0,
                                         local_origin=p['epochOrigin'], end_ledger=100000, block_size={},
                                         window_blocks=100000, first_seconds=0)
        self.assertNotIn('cap_rejected_count', row)
        self.assertNotIn('s_prob', arr)
        self.assertNotIn('cap_rejected_count', replay.OBS_COLUMNS)

    def test_source_has_no_design_two_literals(self):
        src = (HERE / 'design2.py').read_text() + (HERE / 'replay.py').read_text() + (HERE / 'engine.py').read_text()
        for literal in ('30180', '30_180', '51780', '400000', '400_000'):
            self.assertNotIn(literal, src)


if __name__ == '__main__':
    unittest.main()
