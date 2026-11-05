"""Second edition of the design-2 overlay: unit deduction b and the k table, rule editions, the fixed windows,
confirmed failures in the injection (D2-6, 94a) and the chain block time.
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
import inputs  # noqa: E402
import replay  # noqa: E402
import test_design2 as td  # noqa: E402
import test_replay as tr  # noqa: E402
from bucket import PPM  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402
from d2_testlib import GRID, K, VMAX, make2, trace_arrays  # noqa: E402


class UnitBond(unittest.TestCase):
    """D2-5 (b), (e): b = ceil((40/27) v_max / p0), B = k b."""

    def test_b_values(self):
        d = {v: make2(vmax_usdc=v) for v in VMAX}
        self.assertEqual({v: x.b for v, x in d.items()}, {'0.1': 370_371, '0.2': 740_741, '1': 3_703_704})
        for v, x in d.items():
            self.assertEqual(x.bond, 87 * x.b)
            self.assertEqual(x.bond // x.k, x.b)                    # the deduction floor(B / k) is exactly b
            self.assertEqual(x.bond_rule, 'integer-b')

    def test_b_is_the_ceiling_of_the_exact_fraction(self):
        margin = Fraction(40, 27)
        rng = random.Random(8)
        for _ in range(300):
            v = rng.randrange(1, 5_000_000)
            b = design2.unit_b(v, 400_000, margin)
            exact = margin * v * PPM / 400_000
            self.assertGreaterEqual(b, exact)
            self.assertLess(b - 1, exact)
            self.assertGreaterEqual(b * 400_000, v * PPM)           # b >= v_max / p0 (deterrence, D2-5 (c))

    def test_the_table_of_the_rules_to_two_decimals(self):
        want = {
            ('0.015', '0.1'): [1.85, 2.59, 4.07, 7.04, 14.07, 32.22], ('0.015', '0.2'): [3.70, 5.19, 8.15, 14.07, 28.15, 64.44],
            ('0.015', '1'): [18.52, 25.93, 40.74, 70.37, 140.74, 322.22],
            ('0.004728', '0.1'): [1.48, 1.85, 2.96, 4.07, 7.41, 14.44], ('0.004728', '0.2'): [2.96, 3.70, 5.93, 8.15, 14.81, 28.89],
            ('0.004728', '1'): [14.81, 18.52, 29.63, 40.74, 74.07, 144.44]}
        for (w, v), row in want.items():
            d = make2(vmax_usdc=v, k_w=w)
            self.assertEqual([d.k_table[S] for S in GRID], K[w])
            self.assertEqual([round(d.cap_spec(S, 'x')['bond_unit'] / 1e6, 2) for S in GRID], row, (w, v))

    def test_multiples_of_the_main_cap_pay_n_times_the_main_bond(self):
        d = make2()
        for n in (1, 2, 10, 26):
            spec = d.cap_spec(3245 * n, 'x')
            self.assertEqual((spec['bond_unit'], spec['bond'], spec['k']), (d.bond, n * d.bond, 87))

    def test_first_edition_bond_is_still_selectable(self):
        d = td.make_d2(vmax_usdc='0.2')
        self.assertEqual((d.edition, d.bond_rule, d.bond, d.b), (1, 'floor-fraction', 20_000_000, 20_000_000 // 27))
        mixed = make2(bond_rule='floor-fraction', k=27)
        self.assertEqual(mixed.bond, 20_000_000)

    def test_k_overrides(self):
        self.assertEqual(make2(k=40).k_table, {S: 40 for S in GRID})
        self.assertEqual(make2(k=40).bond, 40 * 740_741)
        table = {10: 1, 30: 2, 100: 3, 300: 4, 1000: 5, 3245: 6}
        d = make2(k_table=table)
        self.assertEqual((d.k, d.cap_spec(100, 'x')['k']), (6, 3))
        with self.assertRaises(ValueError):
            make2(k_table={10: 1})
        self.assertEqual(design2.parse_k('27'), (27, None))
        self.assertEqual(design2.parse_k('10:5,3245:87'), (None, {10: 5, 3245: 87}))
        self.assertEqual(design2.parse_k(None), (None, None))
        with self.assertRaises(ValueError):
            design2.parse_k('ten')
        with self.assertRaises(ValueError):
            make2(k_w='0.5')

    def test_every_cap_pays_at_least_the_deterrence_floor(self):
        for v in VMAX:
            d = make2(vmax_usdc=v)
            for S in GRID:
                spec = d.cap_spec(S, 'x')
                self.assertGreaterEqual(spec['bond_unit'] * 400_000, spec['k'] * VMAX[v] * PPM)
                self.assertGreaterEqual(spec['b'] * 400_000, VMAX[v] * PPM)


class Editions(unittest.TestCase):
    def test_second_edition_defaults(self):
        d = make2()
        self.assertEqual((d.edition, d.hold, d.failure_window, d.rounding, d.align, d.l_actual),
                         (2, 31_073, 31_073, 'ceil', 'absolute', 30_573))
        self.assertEqual((d.k, d.k_w, d.chain), (87, '0.015', 'base'))

    def test_first_edition_defaults_are_unchanged(self):
        d = td.make_d2()
        self.assertEqual((d.hold, d.rounding, d.align, d.l_actual, d.k), (30_180, 'contract', 'first-block', 29_680, 27))
        d1 = design2.Design2(design2.load_config(), opt.load(replay.default_operating_point(inputs.load_conditions())),
                             tau_usdc='0.1', source='prior14', edition=1)
        self.assertEqual((d1.hold, d1.failure_window, d1.vmax), (30_180, 30_180, 100_000))

    def test_the_first_edition_hold_periods_are_not_second_edition_choices(self):
        for hold in (30_180, 51_780, 60_000):
            with self.assertRaises(ValueError):
                make2(hold=hold)
        with self.assertRaises(ValueError):
            make2(failure_window=60_000)
        self.assertEqual(make2(hold=31_073, failure_window=31_073).hold, 31_073)
        with self.assertRaises(ValueError):
            td.make_d2(hold=31_073)                       # edition 1 keeps its own list

    def test_cap_and_multiplier_exclude_each_other_and_one_is_needed(self):
        with self.assertRaises(ValueError):
            make2(source='prior14')
        with self.assertRaises(ValueError):
            make2(sales_cap=None)
        with self.assertRaises(ValueError):
            design2.Design2(design2.load_config(), opt.load(replay.default_operating_point(inputs.load_conditions())),
                            vmax_usdc='0.2', edition=2)
        with self.assertRaises(ValueError):
            td.make_d2(sales_cap='auto-zero-reject', source=None)      # edition 1 has no sales cap
        with self.assertRaises(ValueError):
            make2(sales_cap='auto-zero-reject', margin='1.5')
        legacy = make2(sales_cap=None, source='insample')
        self.assertEqual((legacy.sales_cap, legacy.source), (None, 'insample'))

    def test_vmax_choices_and_the_old_name(self):
        for v in VMAX:
            self.assertEqual(make2(vmax_usdc=v).vmax, VMAX[v])
        with self.assertRaises(ValueError):
            make2(vmax_usdc='0.3')
        self.assertEqual(make2(vmax_usdc=None, tau_usdc='0.1').vmax_usdc, '0.1')
        self.assertEqual(design2.tau_atomic('0.2', 6), design2.vmax_atomic('0.2', 6))

    def test_operating_point_check_with_the_longest_path_30573(self):
        base = prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')
        op = opt.load(replay.default_operating_point(inputs.load_conditions()))
        for v in VMAX:
            d = make2(vmax_usdc=v)
            p2 = d.apply_profile(base)
            op2 = d.apply_op(op, 'data-api-fast-v1', p2, prof.case_horizon(p2))
            self.assertEqual(design2.check(op2, p2, d), [], v)
            e = op2['profiles']['data-api-fast-v1']
            self.assertEqual(e['L_actual_blocks']['value'], 30_573)
            self.assertEqual(e['hold_period_blocks']['value'] - e['L_actual_blocks']['value'], 500)
            notes = design2.keeper_notes(op2, p2)
            self.assertEqual(notes['keeper_slack_over_L_actual_blocks'], 500)
            self.assertEqual(p2['parameters']['sellerPenalty'], str(d.bond))
            self.assertEqual(p2['parameters']['failureLimit'], 87)
        # a hold period one block short of the longest path is refused
        d = make2()
        p2 = d.apply_profile(base)
        for key in ('deferBlocks', 'retentionBlocks', 'claimWindowBlocks'):
            p2['parameters'][key] = 30_572
        op2 = d.apply_op(op, 'data-api-fast-v1', p2, prof.case_horizon(p2))
        self.assertTrue(any('longest path' in e for e in design2.check(op2, p2, d)))

    def test_first_edition_longest_path_is_unchanged(self):
        base = prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')
        op = opt.load(replay.default_operating_point(inputs.load_conditions()))
        d = td.make_d2()
        p2 = d.apply_profile(base)
        op2 = d.apply_op(op, 'data-api-fast-v1', p2, prof.case_horizon(p2))
        self.assertEqual(op2['profiles']['data-api-fast-v1']['L_actual_blocks']['value'], 29_680)


class ConfirmedFailures(unittest.TestCase):
    """D2-6 (a)/(b) and decision 94a in the replay: only FINAL(FAIL) draws are confirmed failures."""

    def test_deduction_is_b_per_confirmed_failure_and_nothing_else(self):
        blocks = np.arange(0, 2000, 10, dtype=np.int64)
        values = np.full(len(blocks), 5_000, dtype=np.int64)
        f = np.array([300, 900, 1500], dtype=np.int64)
        res = engine.evaluate_failures(blocks, values, f, hold=500, reentry=0, claim_probs=[1], share=740_741,
                                       rng=np.random.default_rng(1), start=0, end=2000, fw_edges=np.array([0, 1000, 2000]),
                                       claim_window=500)[0]
        self.assertEqual(res['failures'], 3)
        self.assertEqual(res['penalty'], 3 * 740_741)
        self.assertEqual(res['fw_failures'].tolist(), [2, 1])

    def test_windows_below_n_min_add_no_failure_and_no_deduction(self):
        # A window with fewer than minJudgedCount judgments is counted (R20-F4) but is not an event of
        # the injection: with w = 0 there is no failure and no deduction however many windows are below.
        p = dict(td.replay_params(), inconclusiveWindowBlocks=1000, minJudgedCount=30)
        blocks = np.arange(0, 20_000, 7, dtype=np.int64)
        arrays = trace_arrays(blocks)
        row, arr = engine.replay_address('a', arrays, seed=1, p=p, capacity=5000, scale=1, origin_ledger=0,
                                         local_origin=p['epochOrigin'], end_ledger=19_999, block_size={},
                                         window_blocks=20_000, first_seconds=0, cap=100, sample_tau=100,
                                         align='absolute')
        self.assertGreater(row['judgment_windows_below'], 0)
        fw = np.array([0, 5000, 10000, 15000, 20000], dtype=np.int64)
        accum = replay.GroupAccumulator()
        settings = [dict(name='zero', h=None, c=None, alpha=None, w1=None, w=0.0)]
        rows = replay.inject_address('a', arr, seed=1, settings=settings, draws=3, p=p, scale=1, k=5, reentries=[0],
                                     claims=[1], start=0, end=19_999, fw_edges=fw, rate_blocks=20_000, accum=accum,
                                     groups_of=[], share=740_741, bond=5 * 740_741)
        self.assertEqual(rows[0]['failures_mean'], 0)
        self.assertEqual(rows[0]['penalty_loss_mean'], 0)
        self.assertEqual(rows[0]['principal_loss_mean'], 0)

    def test_deduction_and_formula_use_the_cap_of_the_address(self):
        p = td.replay_params()
        blocks = np.arange(0, 60_000, 3, dtype=np.int64)
        arrays = trace_arrays(blocks)
        row, arr = engine.replay_address('a', arrays, seed=1, p=p, capacity=137, scale=1, origin_ledger=0,
                                         local_origin=p['epochOrigin'], end_ledger=59_999, block_size={}, window_blocks=60_000,
                                         first_seconds=0, cap=100, sample_tau=10)       # every settlement is a sample
        settings = [dict(name='w', h=None, c=None, alpha=None, w1=None, w=0.2)]
        fw = np.array([0, 30_000, 60_000], dtype=np.int64)
        rows = replay.inject_address('a', arr, seed=1, settings=settings, draws=20, p=dict(p, deferBlocks=500), scale=1,
                                     k=7, reentries=[0], claims=[1], start=0, end=59_999, fw_edges=fw, rate_blocks=60_000,
                                     accum=replay.GroupAccumulator(), groups_of=[], share=370_371, bond=7 * 370_371)
        r = rows[0]
        self.assertEqual(r['k'], 7)
        self.assertGreater(r['failures_mean'], 0)
        self.assertAlmostEqual(r['penalty_loss_mean'] / r['failures_mean'], 370_371)
        # formula value: B / k = b
        s, w, rate, v = 1.0, 0.2, row['accepted_count'] / 60_000, 10.0
        self.assertAlmostEqual(r['formula_value'], 1 - math.exp(-s * w * rate * 500) + s * w * 370_371 / v, places=6)

    def test_confirmation_delay_sensitivity(self):
        # w = 1: every sampled case ends in a confirmed failure, so the failures that fit before the end of
        # the replay are counted exactly. Default: case opening + judgment and appeal horizon; sensitivity:
        # settlement of the sampled entry + the longest measured path (D2-8, both inside the hold period).
        p = dict(td.replay_params(), deferBlocks=31_073)
        blocks = np.arange(0, 120_000, 5, dtype=np.int64)
        row, arr = engine.replay_address('a', trace_arrays(blocks), seed=1, p=p, capacity=500, scale=1, origin_ledger=0,
                                         local_origin=p['epochOrigin'], end_ledger=119_999, block_size={},
                                         window_blocks=120_000, first_seconds=0, cap=100, sample_tau=10,
                                         refill_ppm=1_000_000)
        settings = [dict(name='all', h=None, c=None, alpha=None, w1=None, w=1.0)]
        kw = dict(seed=1, settings=settings, draws=2, p=p, scale=1, k=5, reentries=[0], claims=[1], start=0, end=119_999,
                  fw_edges=np.array([0, 60_000, 120_000], dtype=np.int64), rate_blocks=120_000, groups_of=[])
        default = replay.inject_address('a', arr, accum=replay.GroupAccumulator(), **kw)[0]
        later = replay.inject_address('a', arr, accum=replay.GroupAccumulator(), confirm_from_settlement=30_573, **kw)[0]
        delay = replay.confirm_delay(p)
        self.assertEqual(delay, 7_512)
        self.assertEqual(default['failures_mean'], int((arr['cases'] + delay <= 119_999).sum()))
        self.assertEqual(later['failures_mean'], int((arr['case_settled'] + 30_573 <= 119_999).sum()))
        self.assertLess(later['failures_mean'], default['failures_mean'])
        self.assertLess(30_573, p['deferBlocks'])

    def test_a_sampled_purchase_is_one_sample_whatever_its_path(self):
        # Decision 94a: a purchase that ended delivered is still a sample event. The replay has no purchaser
        # dispute, every accepted settlement is drawn once from (epoch, row, seed, rate), so the number of
        # inspections is the number of draws below threshold.
        epochs = np.zeros(2000, dtype=np.int64)
        rows = np.arange(2000, dtype=np.int64)
        a = engine.sampled('0xabc', epochs, rows, 4, np.full(2000, 400_000))
        b = engine.sampled('0xabc', epochs, rows, 4, np.full(2000, 400_000))
        self.assertTrue((a == b).all())
        self.assertAlmostEqual(a.mean(), 0.4, delta=0.05)


class ChainTime(unittest.TestCase):
    def test_profile_durations_keep_their_seconds(self):
        base = prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')
        p0 = base['parameters']
        same = design2.scale_profile_time(base, 2, 2)
        self.assertEqual(same, base)
        fast = design2.scale_profile_time(base, 2, Fraction('0.4'))
        p = fast['parameters']
        self.assertEqual(p['epochBlocks'], 5 * p0['epochBlocks'])
        self.assertEqual(p['beaconDelayBlocks'], 5 * p0['beaconDelayBlocks'])
        self.assertEqual(p['deadlineConfig']['judgeBlocks'], 5 * p0['deadlineConfig']['judgeBlocks'])
        self.assertEqual(p['refillPpmPerBlock'], p0['refillPpmPerBlock'] // 5)
        self.assertEqual(p['maxRatePpmPerBlock'], p0['maxRatePpmPerBlock'] // 5)
        for key in ('bucketCapacity', 'minJudgedCount', 'maxAssignments', 'failureLimit'):
            self.assertEqual(p[key], p0[key])
        slow = design2.scale_profile_time(base, 2, Fraction('1.5'))
        self.assertEqual(slow['parameters']['epochBlocks'], 400)
        self.assertEqual(slow['parameters']['refillPpmPerBlock'], 37_500)
        self.assertEqual(base['parameters']['epochBlocks'], 300)          # the input is not touched
        # a duration is never shortened by rounding
        odd = design2.scale_profile_time(base, 2, Fraction('0.3'))
        for key in ('anchorBlocks', 'responseBlocks', 'serveBlocks'):
            self.assertGreaterEqual(odd['parameters']['deadlineConfig'][key] * Fraction('0.3'),
                                    p0['deadlineConfig'][key] * 2)

    def test_block_time_text(self):
        for text, want in (('2', '2'), ('0.4', '0.4'), ('1.5', '1.5'), ('0.3', '0.3'), ('0.25', '0.25')):
            self.assertEqual(design2.decimal_text(Fraction(text)), want)
        self.assertEqual(design2.decimal_text(Fraction(1, 3)), '1/3')

    def test_hold_in_blocks_and_in_time(self):
        self.assertEqual(make2().hold, 31_073)
        for chain, bt, hold in (('polygon', '2', 31_073), ('polygon', '1.5', 41_431), ('solana', '0.4', 155_365),
                                ('solana', '0.3', 207_154)):
            d = make2(chain=chain, block_seconds=bt)
            self.assertEqual(d.hold, hold, (chain, bt))
            self.assertGreaterEqual(d.hold * Fraction(bt), 31_073 * 2)              # at least 62,146 seconds
            self.assertLess((d.hold - 1) * Fraction(bt), 31_073 * 2)
            self.assertEqual(d.failure_window, d.hold)
            self.assertEqual(d.hour_blocks, int(3600 / Fraction(bt)))
        self.assertEqual(make2(chain='solana').block_seconds, Fraction('0.4'))
        self.assertEqual(make2(chain='solana', block_seconds='0.3').block_seconds, Fraction('0.3'))
        with self.assertRaises(ValueError):
            make2(chain='ethereum')
        with self.assertRaises(ValueError):
            make2(block_seconds='0')
        with self.assertRaises(ValueError):
            make2(chain='solana', hold=31_073)             # the Base block count is not the Solana hold

    def test_the_cap_grid_has_the_same_sustained_rates_per_second(self):
        base, sol = make2(), make2(chain='solana', block_seconds='0.4')
        for S in GRID:
            qb, rb = base.cap_spec(S, 'x')['capacity'], base.cap_spec(S, 'x')['refill_ppm']
            qs, rs = sol.cap_spec(S, 'x')['capacity'], sol.cap_spec(S, 'x')['refill_ppm']
            self.assertEqual(qb, qs)
            per_second_base = Fraction(rb, PPM) / 2
            per_second_sol = Fraction(rs, PPM) / Fraction('0.4')
            self.assertAlmostEqual(float(per_second_sol / per_second_base), 1.0, delta=0.04, msg=S)
            self.assertEqual(design2.cap_admits(S, qs, rs, sol.lam) if S < 3245 else S, S)

    def test_the_overlay_of_a_chain_passes_the_operating_point_check(self):
        base = prof.load_profile(tr.REPLAY_PROFILE_FILE, 'data-api-fast-v1')
        op = opt.load(replay.default_operating_point(inputs.load_conditions()))
        for chain, bt in (('base', '2'), ('polygon', '1.5'), ('polygon', '2'), ('solana', '0.4'), ('solana', '0.3')):
            d = make2(chain=chain, block_seconds=bt)
            p2 = d.apply_profile(base)
            op2 = d.apply_op(op, 'data-api-fast-v1', p2, prof.case_horizon(p2))
            self.assertEqual(design2.check(op2, p2, d), [], (chain, bt))
            e = op2['profiles']['data-api-fast-v1']
            self.assertGreaterEqual(e['hold_period_blocks']['value'], e['L_actual_blocks']['value'])
            self.assertEqual(d.l_actual, math.ceil(Fraction(30_573) * 2 / Fraction(bt)))
        # the shared profile and operating point are not changed by an overlay
        self.assertEqual(base['parameters']['epochBlocks'], 300)
        self.assertEqual(op['chain']['block_seconds'], 2)

    def test_address_case(self):
        self.assertEqual(make2().address_case, 'lower')
        self.assertEqual(make2(chain='solana').address_case, 'keep')
        try:
            inputs.set_address_case('keep')
            self.assertEqual(inputs.normalize('AbC'), 'AbC')
            inputs.set_address_case('lower')
            self.assertEqual(inputs.normalize('AbC'), 'abc')
            with self.assertRaises(ValueError):
                inputs.set_address_case('upper')
        finally:
            inputs.set_address_case('lower')


# ---------------------------------------------------------------- chain inputs


if __name__ == '__main__':
    unittest.main()
