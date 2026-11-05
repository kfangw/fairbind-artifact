"""Tests of r11_compute.py (the R11 aggregation) and of the G0 gate of run_r11.sh, on synthetic fixtures."""
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import r11_compute as rc  # noqa: E402

CODE = 'c' * 40
A, B, C = (f'0x{0xa000 + i:040x}' for i in range(3))
FIRST, LAST, HOLD, RATE = 1000, 1999, 100, 1000
# address -> list of (block, value, release, sampled, accepted)
SALES = {A: [(1050, 100_000, 1150, False, False), (1200, 300_000, 1400, True, False), (1900, 50_000, 2500, False, False)],
         B: [],
         C: [(1500, 20_000, 1700, False, False)]}
COLUMNS = ['address', 'scale', 'attempted_count', 'attempted_value', 'accepted_count', 'accepted_value', 'sample_count',
           'cap_rejected_count', 'rate_rejected_count', 'sales_cap_S', 'deduction_b', 'epochs_with_settlement',
           'H_time_average', 'H_max', 'H_ledger_list_max_abs_diff', 'admission', 'sales_cap_method',
           'H_cont_sum_blocks', 'H_cont_average', 'H_cont_average_from_hold', 'has_revenue', 'hold_released_count',
           'hold_open_count', 'hold_open_value', 'hold_mean', 'hold_value_mean', 'hold_p50', 'hold_p90', 'hold_max',
           'hold_histogram', 'revenue_per_hold', 'buyer_accepted_count', 'buyer_accepted_value', 'unsigned_count',
           'sampled_accepted_count', 'over_cap_accepted_count', 'over_cap_accepted_value']


def numerator(sales, lo, hi):
    return sum(v * max(0, min(r, hi + 1) - max(b, lo)) for b, v, r, _, _ in sales)


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def address_rows(sales_by_addr, admission='unlimited', vmax=200_000, release_shift=0):
    rows = []
    for a, sales in sales_by_addr.items():
        sales = [(b, v, r + release_shift, s, ac) for b, v, r, s, ac in sales]
        acc_v = sum(v for _, v, _, _, _ in sales)
        over_v = sum(v for _, v, _, _, _ in sales if v > vmax)
        holds = [r - b for b, _, r, _, _ in sales if r <= LAST]
        open_v = sum(v for b, v, r, _, _ in sales if r > LAST)
        points = range(FIRST + HOLD, LAST + 1, 1800)
        hourly = [sum(v for b, v, r, _, _ in sales if b <= t < r) for t in points]
        rows.append(dict(
            address=a, scale=1, attempted_count=len(sales), attempted_value=acc_v, accepted_count=len(sales),
            accepted_value=acc_v, sample_count=sum(1 for s in sales if s[3]), cap_rejected_count=0,
            rate_rejected_count=0, sales_cap_S='', deduction_b=vmax, epochs_with_settlement=len({(b - FIRST) // 300 for b, *_ in sales}),
            H_time_average=sum(hourly) / len(hourly), H_max=max([v for _, v, _, _, _ in sales] + [0]),
            H_ledger_list_max_abs_diff=0.0, admission=admission,
            sales_cap_method='none-unlimited' if admission == 'unlimited' else 'min-zero-insample',
            H_cont_sum_blocks=numerator(sales, FIRST, LAST), H_cont_average=numerator(sales, FIRST, LAST) / (LAST - FIRST + 1),
            H_cont_average_from_hold=numerator(sales, FIRST + HOLD, LAST) / (LAST - FIRST - HOLD + 1),
            has_revenue='true' if acc_v > 0 else 'false', hold_released_count=len(holds),
            hold_open_count=len(sales) - len(holds), hold_open_value=open_v,
            hold_mean=(sum(holds) / len(holds)) if holds else '', hold_value_mean=(sum(holds) / len(holds)) if holds else '',
            hold_p50=(sorted(holds)[len(holds) // 2]) if holds else '', hold_p90=(max(holds)) if holds else '',
            hold_max=(max(holds)) if holds else '', hold_histogram=json.dumps([len(holds)] + [0] * (len(rc.HIST_EDGES) - 1)),
            revenue_per_hold=acc_v, buyer_accepted_count=sum(1 for s in sales if s[4]), buyer_accepted_value=0,
            unsigned_count=0, sampled_accepted_count=0,
            over_cap_accepted_count=sum(1 for s in sales if s[1] > vmax), over_cap_accepted_value=over_v))
    return rows


def write_sales_npz(cdir, sales_by_addr, release_shift=0):
    idx, blk, val, rel, ep, row, smp, acc = [], [], [], [], [], [], [], []
    n = 0
    for i, (a, sales) in enumerate(sales_by_addr.items()):
        for b, v, r, s, ac in sales:
            idx.append(i); blk.append(b); val.append(v); rel.append(r + release_shift); ep.append((b - FIRST) // 300)
            row.append(n); smp.append(s); acc.append(ac); n += 1
    np.savez_compressed(cdir / 'sales.npz', address_index=np.array(idx, np.int32), block=np.array(blk, np.int64),
                        value=np.array(val, np.int64), release=np.array(rel, np.int64), epoch=np.array(ep, np.int64),
                        row=np.array(row, np.int64), sampled=np.array(smp, bool), accepted=np.array(acc, bool),
                        signed=np.ones(n, bool))
    (cdir / 'sales_addresses.json').write_text(json.dumps(list(sales_by_addr)))


def write_run(run_dir, sales_by_addr, release10, admission='unlimited', preset='r11-main', release_shift=0, rows=None):
    cdir = run_dir / 'condition-01-seed-0'
    cdir.mkdir(parents=True, exist_ok=True)
    rows = rows or address_rows(sales_by_addr, admission, release_shift=release_shift)
    write_csv(cdir / 'addresses_observed.csv', rows, COLUMNS)
    write_sales_npz(cdir, sales_by_addr, release_shift)
    meta = dict(release10=release10, admission=[admission], sales_file='sales.npz', rate_blocks=RATE, hold_blocks=HOLD,
                hour_readings=len(range(FIRST + HOLD, LAST + 1, 1800)),
                addresses_with_revenue=sum(1 for r in rows if r['has_revenue'] == 'true'))
    if preset:
        meta['preset'] = preset
    (cdir / 'condition.json').write_text(json.dumps(meta))
    (run_dir / 'run.json').write_text(json.dumps(dict(
        reportable=True, code=dict(revision=CODE, dirty=False),
        parameters=dict(freeze_scope='detected-onward', preset=preset, release10=release10),
        inputs=dict(settlements=dict(first_block=FIRST, last_block=LAST)))))
    return cdir


class Fixture:
    """A research docs tree, a raw tree with the main V 0.2 run of the median window, the lists and a registration."""

    def __init__(self, root):
        self.root = Path(root)
        self.docs = self.root / 'docs'
        self.raw = self.root / 'raw'
        self.lists = self.root / 'lists'
        self.out = self.root / 'summary'
        self.e8_addr = {A: dict(att_v=150_000, W_v=150_000, q=1, r=0, n=1), B: dict(att_v=0, W_v=0, q=0, r=0, n=0),
                        C: dict(att_v=20_000, W_v=20_000, q=1, r=0, n=1)}
        self.build()

    def build(self):
        d = self.docs
        # E8b per-address and per-row outputs for the median window, every V
        for v in rc.VS:
            rows = [dict(address=a, **x) for a, x in self.e8_addr.items()]
            write_csv(d / rc.E8B_DIR / f'e8_addr_median_v{v}_lf{rc.LF7}.csv', rows, ['address', 'att_v', 'W_v', 'q', 'r', 'n'])
            brows = [dict(address=a, baseline='B', m=m, att_v=x['att_v'], rej_v=0) for a, x in self.e8_addr.items()
                     for m in rc.MARGIN_NAMES]
            write_csv(d / rc.E8B_DIR / f'e8_rows_median_v{v}_lf{rc.LF7}.csv', brows, ['address', 'baseline', 'm', 'att_v', 'rej_v'])
        res = d / rc.E8B_RESULTS[0]
        res.parent.mkdir(parents=True, exist_ok=True)
        res.write_text('{"synthetic": true}')
        rc.E8B_RESULTS = (rc.E8B_RESULTS[0], sha(res))
        # the stored edition-7 output of V 0.2 (scale and accepted value define the sets)
        stored = [dict(address=A, scale=1, accepted_value=150_000), dict(address=B, scale=1, accepted_value=0),
                  dict(address=C, scale=100, accepted_value=20_000)]
        sp = d / 'stored_v0.2' / 'condition-01-seed-0' / 'addresses_observed.csv'
        write_csv(sp, stored, ['address', 'scale', 'accepted_value'])
        rc.STORED = {('median', '0.2'): ('stored_v0.2', sha(sp))}
        # the settlement list
        lp = self.lists / rc.LISTS['median']
        lp.parent.mkdir(parents=True, exist_ok=True)
        lrows = sorted((b, a, v) for a, s in SALES.items() for b, v, *_ in s)
        with open(lp, 'w', newline='') as f:
            w = csv.writer(f, lineterminator='\n')
            w.writerow(['block_number', 'recipient', 'value_atomic'])
            w.writerows(lrows)
        # the main V 0.2 run
        self.main = write_run(self.raw / 'median' / 'base_v0.2_none', SALES, rc.BASE)
        # the registration and its hash
        self.reg = self.root / 'R11_preregistration.md'
        self.reg.write_text('# sealed\n')
        self.reg.with_suffix('.sha256').write_text(f'{sha(self.reg)}  R11_preregistration.md\n')

    def argv(self):
        return ['--raw', str(self.raw), '--lists', str(self.lists), '--out', str(self.out), '--code-commit', CODE,
                '--docs', str(self.docs), '--registration', str(self.reg), '--addresses', '3']

    def run(self):
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            code = rc.main(self.argv())
        return code, json.loads((self.out / 'r11_results.json').read_text())


class HandValues(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved = (rc.E8B_RESULTS, rc.STORED)
        cls.fx = Fixture(cls.tmp.name)
        cls.code, cls.R = cls.fx.run()

    @classmethod
    def tearDownClass(cls):
        rc.E8B_RESULTS, rc.STORED = cls.saved
        cls.tmp.cleanup()

    def test_sets_and_gates(self):
        self.assertEqual(self.code, 0)
        W = self.R['main']['median']
        self.assertTrue(W['reportable_0.2'], W.get('problems_0.2'))
        self.assertEqual(W['set_sizes'], dict(S1r=1, S1=2, S2=3, S3=1, S1a=1, S2a=2))
        X = W['V']['0.2']
        self.assertTrue(X['G2_admission']['ok'])
        self.assertTrue(X['G4_cont_average']['ok'])
        self.assertTrue(X['G6_e8b_att']['ok'])            # in-cap accepted value (over-cap sale excluded) = att_v
        self.assertEqual(X['L_F11'], 2371)
        self.assertFalse(self.R['main']['busy']['reportable_0.2'])

    def test_held_money_three_definitions(self):
        lock = self.R['main']['median']['V']['0.2']['lock']
        whole = numerator(SALES[A], FIRST, LAST)                     # 1e7 + 6e7 + 5e6
        self.assertEqual(whole, 75_000_000)
        from_hold = numerator(SALES[A], FIRST + HOLD, LAST)          # 5e6 + 6e7 + 5e6
        self.assertEqual(from_hold, 70_000_000)
        self.assertAlmostEqual(lock['cont_window']['S1r']['held'], whole / 1000 / 1e6, places=9)
        self.assertAlmostEqual(lock['cont_from_hold']['S1r']['held'], from_hold / 900 / 1e6, places=9)
        self.assertEqual(lock['cont_from_hold']['S1r']['n'], 1)
        self.assertAlmostEqual(lock['cont_from_hold']['S1r']['P_FB'], 0.2)
        # S1 adds B (no revenue): the deduction b only
        self.assertAlmostEqual(lock['cont_from_hold']['S1']['P_FB'], 0.4)
        self.assertAlmostEqual(lock['cont_from_hold']['S1']['held'], lock['cont_from_hold']['S1r']['held'])
        # S2 adds C
        self.assertAlmostEqual(lock['cont_window']['S2']['held'], (whole + numerator(SALES[C], FIRST, LAST)) / 1000 / 1e6)

    def test_baselines_include_over_cap_sales(self):
        k = self.R['main']['median']['V']['0.2']['lock']['cont_from_hold']['S1r']
        b, lf = 200_000, 2371
        CM = b + Fraction(450_000 * lf, RATE)                        # revenue including the 0.3 USDC sale
        self.assertAlmostEqual(k['sumC_M'], float(CM) / 1e6, places=9)
        self.assertAlmostEqual(k['sumC_W'], (b + 450_000) / 1e6)      # sliding window over every sale
        L = 0.2 + 70_000_000 / 900 / 1e6
        self.assertAlmostEqual(k['L_FB'], L, places=9)
        self.assertAlmostEqual(k['rhoL_M'], L / (float(CM) / 1e6), places=9)
        self.assertAlmostEqual(k['rhoL_W'], L / 0.65, places=9)
        cells = k['cells']
        self.assertAlmostEqual(cells['B|1']['sumC'], 0.4)             # b + ceil(1 * 1 * 1) * V
        self.assertAlmostEqual(cells['B|3/2']['sumC'], 0.6)
        self.assertAlmostEqual(cells['B|4']['sumC'], 1.0)
        self.assertAlmostEqual(cells['B|1']['rhoL_same_upper'], L / 0.4, places=9)
        # the reference cells at L_F 29,454 use E8b's in-cap values
        self.assertAlmostEqual(k['ref_lf29454']['sumC_W'], (b + 150_000) / 1e6)

    def test_verdicts_and_outputs(self):
        v = self.R['verdicts']
        self.assertEqual(v['windows'], ['median'])
        self.assertEqual(v['judgement_set'], 'S1r')
        self.assertEqual(v['held_money_definition'], 'H_cont_average_from_hold')
        self.assertTrue(v['JA11']['holds'])
        self.assertTrue(v['JD11']['holds'])
        self.assertTrue(v['JM11']['holds_replay'])
        self.assertIsNone(v['JM11']['holds'])
        self.assertIsNone(v['JX11']['holds'])
        out = self.fx.out
        self.assertTrue((out / 'r11_tables.md').exists())
        self.assertTrue((out / 'r11_addr_main_median_v0.2.csv').exists())
        self.assertTrue((out / 'r11_k_median.csv').exists())
        hashes = (out / 'r11_sales_sha256.txt').read_text().split()
        self.assertEqual(hashes[0], sha(self.fx.main / 'sales.npz'))
        self.assertEqual(self.R['main']['median']['V']['0.2']['sales_sha256'], hashes[0])
        # hold lengths: the two released sales of A (100 and 200 blocks), one open
        hd = self.R['main']['median']['V']['0.2']['hold']['S1r']
        self.assertEqual(hd['released'], 2)
        self.assertEqual(hd['open_count'], 1)
        self.assertAlmostEqual(hd['open_value'], 0.05)
        self.assertEqual(self.R['k']['median']['reported_k'], [])


class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (rc.E8B_RESULTS, rc.STORED)
        self.fx = Fixture(self.tmp.name)

    def tearDown(self):
        rc.E8B_RESULTS, rc.STORED = self.saved
        self.tmp.cleanup()

    def rewrite_rows(self, edit):
        p = self.fx.main / 'addresses_observed.csv'
        rows = rc.read_csv(p)
        for r in rows:
            edit(r)
        write_csv(p, rows, COLUMNS)

    def test_registration_hash_gate(self):
        self.fx.reg.write_text('# changed after sealing\n')
        with self.assertRaises(SystemExit):
            self.fx.run()

    def test_g4_numerator_mismatch(self):
        def edit(r):
            if r['address'] == A:
                r['H_cont_sum_blocks'] = str(int(r['H_cont_sum_blocks']) + 1)
        self.rewrite_rows(edit)
        _, R = self.fx.run()
        W = R['main']['median']
        self.assertFalse(W['reportable_0.2'])
        self.assertTrue(any('G4' in p for p in W['problems_0.2']))
        self.assertNotIn('lock', W['V']['0.2'])

    def test_g2_admission_mismatch(self):
        def edit(r):
            if r['address'] == C:
                r['rate_rejected_count'] = '1'
        self.rewrite_rows(edit)
        _, R = self.fx.run()
        self.assertTrue(any('G2' in p for p in R['main']['median']['problems_0.2']))

    def test_g3_release_record_mismatch(self):
        cdir = self.fx.main
        meta = json.loads((cdir / 'condition.json').read_text())
        meta['release10'] = dict(rc.BASE, anchor_delay=100)
        (cdir / 'condition.json').write_text(json.dumps(meta))
        _, R = self.fx.run()
        self.assertTrue(any('G3' in p for p in R['main']['median']['problems_0.2']))

    def test_g6_e8b_mismatch(self):
        def edit(r):
            if r['address'] == A:
                r['over_cap_accepted_value'] = '0'          # in-cap value would then be 450,000, not 150,000
        self.rewrite_rows(edit)
        _, R = self.fx.run()
        self.assertTrue(any('G6' in p for p in R['main']['median']['problems_0.2']))

    def test_other_configuration_and_sampled_flags(self):
        # the dispute-settlement variant: same sales, earlier payment of the unsampled sales
        shifted = {a: [(b, v, r - 10 if not s else r, s, ac) for b, v, r, s, ac in sales] for a, sales in SALES.items()}
        write_run(self.fx.raw / 'median_dsettle' / 'base_v0.2_none', shifted, dict(rc.BASE, dispute_from='settlement'))
        # the legacy bucket: one sale fewer; sampled flags of the common sales agree
        legacy = {A: SALES[A][1:], B: [], C: SALES[C]}
        write_run(self.fx.raw / 'median_legacy' / 'base_v0.2_auto-zero-reject', legacy, rc.BASE, admission='bucket',
                  preset=None)
        # the legacy rows' list row numbers must be those of the main run: rewrite them
        z = dict(np.load(self.fx.raw / 'median_legacy' / 'base_v0.2_auto-zero-reject' / 'condition-01-seed-0' / 'sales.npz'))
        z['row'] = np.array([1, 2, 3])
        np.savez_compressed(self.fx.raw / 'median_legacy' / 'base_v0.2_auto-zero-reject' / 'condition-01-seed-0' / 'sales.npz', **z)
        _, R = self.fx.run()
        ds = R['configs']['dsettle']['median']
        self.assertNotIn('problems', ds)
        self.assertTrue(ds['G2_sampled_flags']['ok'])
        self.assertLess(ds['lock']['cont_window']['S1r']['held'], R['main']['median']['V']['0.2']['lock']['cont_window']['S1r']['held'])
        lg = R['configs']['legacy']['median']
        self.assertTrue(lg['G2_sampled_flags']['ok'])
        self.assertEqual(lg['G2_sampled_flags']['common'], 3)
        # the legacy variant's in-cap value differs from E8b (one sale fewer): G6 marks it
        self.assertTrue(any('G6' in p for p in lg['problems']))

    def test_sampled_flag_mismatch_detected(self):
        main = dict(row=np.array([0, 1, 2]), sampled=np.array([False, True, False]))
        other = dict(row=np.array([1, 2]), sampled=np.array([True, True]))
        g = rc.gate_sampled_flags(main, other)
        self.assertFalse(g['ok'])
        self.assertEqual(g['mismatches'], 1)
        self.assertFalse(rc.gate_sampled_flags(main, dict(row=np.array([5]), sampled=np.array([True])))['ok'])
        self.assertTrue(rc.gate_sampled_flags(main, dict(row=np.array([2, 0]), sampled=np.array([False, False])))['ok'])


class KSweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (rc.E8B_RESULTS, rc.STORED)
        self.fx = Fixture(self.tmp.name)

    def tearDown(self):
        rc.E8B_RESULTS, rc.STORED = self.saved
        self.tmp.cleanup()

    def write_k(self, k, shift):
        write_run(self.fx.raw / 'median_ksweep' / f'k{k}', SALES, dict(rc.BASE, seller_epoch_k=k), release_shift=shift)

    def test_monotone_and_ratios(self):
        for k, shift in ((1, 0), (2, 300), (3, 600), (6, 1500)):
            self.write_k(k, shift)
        _, R = self.fx.run()
        K = R['k']['median']
        self.assertEqual(K['reported_k'], [1, 2, 3, 6])
        self.assertEqual(K['problems'], [])
        self.assertTrue(all(K['monotone'].values()))
        self.assertTrue(K['k1_equals_main']['ok'])
        self.assertEqual(K['per_k']['2']['L_F11'], 2371 + 300)
        self.assertGreater(K['per_k']['2']['ratio_to_k1']['S1r'], 1)
        self.assertAlmostEqual(K['per_k']['1']['ratio_to_k1']['S1r'], 1)
        # held money at k = 2 by hand: every release 300 blocks later, the open sale stays open
        shifted = [(b, v, r + 300, s, ac) for b, v, r, s, ac in SALES[A]]
        self.assertAlmostEqual(K['per_k']['2']['lag_k']['cont_from_hold']['S1r']['held'],
                               numerator(shifted, FIRST + HOLD, LAST) / 900 / 1e6, places=9)
        # the lag-k baseline is larger than the lag-1 baseline, so rho at lag k is smaller
        self.assertLess(K['per_k']['2']['lag_k']['cont_from_hold']['S1r']['rhoL_M'],
                        K['per_k']['2']['lag_k1']['cont_from_hold']['S1r']['rhoL_M'])
        rows = rc.read_csv(self.fx.out / 'r11_k_median.csv')
        self.assertEqual(len(rows), 4 * 2 * 3)

    def test_non_monotone_is_a_problem(self):
        self.write_k(1, 0)
        self.write_k(2, -20)          # paid earlier at k = 2: impossible under the rule
        _, R = self.fx.run()
        K = R['k']['median']
        self.assertFalse(K['monotone']['per_address_H_cont_sum_blocks'])
        self.assertTrue(any('G4' in p for p in K['problems']))

    def test_monotone_helper(self):
        self.assertTrue(rc.monotone([1, 1, 2]))
        self.assertFalse(rc.monotone([1, 0.5]))
        self.assertFalse(rc.monotone([1, None, 2]))
        self.assertTrue(rc.monotone([3]))


class Fraud(unittest.TestCase):
    def write(self, raw, sub, release, cap, R=500, above=0, max_exact=0.19):
        d = Path(raw) / sub
        d.mkdir(parents=True)
        (d / 'summary.json').write_text(json.dumps(dict(R=R, release10=release, r10=dict(
            above_3se=above, max_mean=0.18, max_exact=max_exact), r10_a05={}, r10_a09={})))
        (d / 'exact_expectation.json').write_text(json.dumps(dict(release10=release, sales_cap=cap, addresses={})))

    def test_fraud_records_and_jx11(self):
        with tempfile.TemporaryDirectory() as t:
            main = {k: v for k, v in rc.BASE.items() if k != 'mode'}
            self.write(t, 'deter', main, 'none')
            self.write(t, 'deter_r10style', dict(main, anchor_delay=100, accept_over_cap=False, dispute_from='settlement'),
                       'auto-zero-reject', above=2, max_exact=0.21)
            F = rc.fraud(t)
            self.assertEqual(F['main']['problems'], [])
            self.assertEqual(F['r10style']['problems'], [])
            R = dict(main={w: {"reportable_0.2": False, "V": {}} for w in rc.WINDOWS}, fraud=F)
            v = rc.verdicts(R)
            self.assertTrue(v['JX11']['holds'])
            self.assertEqual(v['JX11']['r10style_variant']['above_3se'], 2)
            self.assertFalse(v['JA11']['holds'])                     # no reportable window
        with tempfile.TemporaryDirectory() as t:
            main = {k: v for k, v in rc.BASE.items() if k != 'mode'}
            self.write(t, 'deter', dict(main, anchor_delay=100), 'none', R=499)
            F = rc.fraud(t)
            self.assertEqual(len(F['main']['problems']), 2)
            self.assertIn('problems', F['r10style'])
            R = dict(main={w: {"reportable_0.2": False, "V": {}} for w in rc.WINDOWS}, fraud=F)
            self.assertIsNone(rc.verdicts(R)['JX11']['holds'])

    def test_jx11_fails_above_bound(self):
        with tempfile.TemporaryDirectory() as t:
            main = {k: v for k, v in rc.BASE.items() if k != 'mode'}
            self.write(t, 'deter', main, 'none', above=1)
            R = dict(main={w: {"reportable_0.2": False, "V": {}} for w in rc.WINDOWS}, fraud=rc.fraud(t))
            self.assertFalse(rc.verdicts(R)['JX11']['holds'])
            self.write(t, 'deter2', main, 'none', max_exact=0.2001)
            shutil.rmtree(Path(t) / 'deter'); (Path(t) / 'deter2').rename(Path(t) / 'deter')
            R = dict(main={w: {"reportable_0.2": False, "V": {}} for w in rc.WINDOWS}, fraud=rc.fraud(t))
            self.assertFalse(rc.verdicts(R)['JX11']['holds'])


class Lf(unittest.TestCase):
    def test_lf11(self):
        self.assertEqual(rc.lf11(rc.BASE), 2371)                         # 299 + 120 + 151 + 1,800 + 1
        self.assertEqual(rc.lf11(dict(rc.BASE, anchor_delay=100)), 2351)  # R10
        self.assertEqual(rc.lf11(rc.BASE, 3), 2371 + 600)
        self.assertEqual(rc.B11['0.2'], 200_000)                          # b = V / s, s = 1


def git(*args, cwd):
    return subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


SEALED = '# sealed registration\n\nreplayer commit ' + 'd' * 40 + '\n'


class Gate0(unittest.TestCase):
    """run_r11.sh gate against a local research clone whose origin is a bare repository."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bare = root / 'origin.git'
        self.research = root / 'research'
        self.scratch = root / 'scratch'
        git('init', '-q', '--bare', '-b', 'main', str(self.bare), cwd=root)
        git('init', '-q', '-b', 'main', str(self.research), cwd=root)
        git('config', 'user.email', 't@example.com', cwd=self.research)
        git('config', 'user.name', 't', cwd=self.research)
        git('remote', 'add', 'origin', str(self.bare), cwd=self.research)
        self.reg = self.research / 'docs' / '11_journal' / 'R11' / 'R11_preregistration.md'
        self.reg.parent.mkdir(parents=True)
        self.reg.write_text(SEALED)
        self.reg.with_suffix('.sha256').write_text(f'{sha(self.reg)}  R11_preregistration.md\n')
        git('add', '-A', cwd=self.research)
        git('commit', '-q', '-m', 'seal', cwd=self.research)
        git('push', '-q', 'origin', 'main', cwd=self.research)

    def tearDown(self):
        self.tmp.cleanup()

    def gate(self, head='d' * 40):
        env = dict(os.environ, RESEARCH=str(self.research), SCRATCH=str(self.scratch), EXPECT_HEAD=head)
        return subprocess.run(['bash', str(HERE / 'run_r11.sh'), 'gate'], env=env, capture_output=True, text=True)

    def test_passes_when_sealed_commit_is_on_origin_main(self):
        r = self.gate()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        g0 = json.loads((self.scratch / 'summary' / 'g0.json').read_text())
        self.assertEqual(g0['registration_sha256'], sha(self.reg))
        self.assertEqual(g0['origin_main'], git('rev-parse', 'HEAD', cwd=self.research).strip())

    def test_fails_without_replayer_commit(self):
        r = self.gate(head='SET-AT-SEAL')
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('EXPECT_HEAD', r.stdout + r.stderr)

    def test_fails_when_local_file_changed(self):
        self.reg.write_text('# changed\n')
        r = self.gate()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('hash differs', r.stdout + r.stderr)

    def test_fails_when_registration_does_not_name_the_commit(self):
        r = self.gate(head='e' * 40)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('does not name the replayer commit', r.stdout + r.stderr)

    def test_fails_when_origin_main_moved_past_the_sealed_file(self):
        self.reg.write_text(SEALED + '\nchanged after sealing\n')
        self.reg.with_suffix('.sha256').write_text(f'{sha(self.reg)}  R11_preregistration.md\n')
        git('commit', '-q', '-am', 'edit after seal', cwd=self.research)
        git('push', '-q', 'origin', 'main', cwd=self.research)
        # a consistent edit, re-hashed and pushed, is a new seal: it passes
        self.assertEqual(self.gate().returncode, 0)
        # the local files state the old seal while origin/main carries the edit: it fails
        self.reg.write_text(SEALED)
        self.reg.with_suffix('.sha256').write_text(f'{sha(self.reg)}  R11_preregistration.md\n')
        r = self.gate()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('origin/main carries', r.stdout + r.stderr)

    def test_fails_when_not_pushed(self):
        self.reg.write_text(SEALED + '\nsealed but not pushed\n')
        self.reg.with_suffix('.sha256').write_text(f'{sha(self.reg)}  R11_preregistration.md\n')
        git('commit', '-q', '-am', 'local seal', cwd=self.research)
        r = self.gate()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('origin/main carries', r.stdout + r.stderr)


class RealReplay(unittest.TestCase):
    """The gates on real replayer output: the synthetic list of test_replay under the main preset and the legacy bucket."""

    @classmethod
    def setUpClass(cls):
        import design2
        import replay
        import test_replay as tr
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.tmp.name)
        cls.s = tr.synthetic(d)
        config = design2.load_config()
        config['vmax_choices_usdc'] = ['0.01'] + config['vmax_choices_usdc']
        (d / 'design2.json').write_text(json.dumps(config))
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision=CODE, dirty=False)
        cls.tr = tr
        base = ['--settlements', str(cls.s['csv']), '--conditions-file', str(cls.s['conditions']),
                '--reference-dir', str(cls.s['dir']), '--qx', '137', '--draws', '3', '--conditions', '1',
                '--repetitions', '1', '--design', '2', '--d2-config', str(d / 'design2.json'), '--vmax', '0.01',
                '--preset', 'r11-main', '--r10-anchor-delay', str(rc.ANCHOR_DELAY)]
        code, _ = tr.run_cli(base + ['--sales-cap', 'none', '--out', str(d / 'main')])
        assert code == 0
        code, _ = tr.run_cli(base + ['--sales-cap', 'auto-zero-reject', '--out', str(d / 'legacy')])
        assert code == 0

    @classmethod
    def tearDownClass(cls):
        import replay
        replay.git_state = cls._git
        cls.tmp.cleanup()

    def test_gates_on_real_output(self):
        run, prob = rc.load_condition(self.d / 'main', rc.BASE, CODE, 'unlimited', None)
        self.assertEqual(prob, [])
        sales, addrs = rc.load_sales(run)
        self.assertTrue(rc.gate_cont_average(run, sales, addrs)['ok'])
        self.assertTrue(rc.gate_main_admission(run)['ok'])
        legacy, prob = rc.load_condition(self.d / 'legacy', rc.BASE, CODE, 'bucket', None, preset=None)
        self.assertEqual(prob, [])
        lsales, laddrs = rc.load_sales(legacy)
        self.assertTrue(rc.gate_cont_average(legacy, lsales, laddrs)['ok'])
        g = rc.gate_sampled_flags(sales, lsales)
        self.assertTrue(g['ok'], g)
        self.assertEqual(g['common'], len(lsales['row']))
        self.assertLess(g['common'], len(sales['row']))
        # the main run with the wrong expected record is a G3 problem
        _, prob = rc.load_condition(self.d / 'main', dict(rc.BASE, anchor_delay=100), CODE, 'unlimited', None)
        self.assertTrue(any('G3' in p for p in prob))
        # the hold columns and the lists read back consistently
        lists = rc.load_list(self.s['csv'], set(run['rows']))
        self.assertEqual(sum(len(b) for b, _ in lists.values()), sum(int(r['attempted_count']) for r in run['rows'].values()))
        hd = rc.hold_distribution(run, set(run['rows']))
        self.assertGreater(hd['released'], 0)
        self.assertLessEqual(hd['seller_max_max'], rc.lf11(rc.BASE))


if __name__ == '__main__':
    unittest.main()
