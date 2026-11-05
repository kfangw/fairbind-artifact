"""Registration R11: the rule-as-written setting of the edition-10 release (sales above V admitted, no bucket), the
seller epoch multiple k, dispute windows from the anchor deadline, the continuous held-money average with the per-sale
payment file, the revenue flag, and the k sweep driver. The R10 path (k = 1, dispute from the settlement, bucket
admission) is left unchanged, which test_release10 and test_release10_bruteforce keep checking."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import numpy as np  # noqa: E402

import design2  # noqa: E402
import engine  # noqa: E402
import r11_k_sweep  # noqa: E402
import release10 as r10  # noqa: E402
import replay  # noqa: E402
import test_replay as tr  # noqa: E402

T = r10.Timing10()
EB = 300
FILES = ('addresses_observed.csv', 'groups_observed.csv', 'addresses_injection.csv', 'groups_injection.csv')


def start(e):
    return 1000 + EB * e


def rel(blocks, sampled=None, accepted=None, signed=None, timing=T):
    blocks = np.asarray(blocks, dtype=np.int64)
    n = len(blocks)
    epochs = (blocks - 1000) // EB
    sampled = np.zeros(n, bool) if sampled is None else np.asarray(sampled, bool)
    accepted = np.zeros(n, bool) if accepted is None else np.asarray(accepted, bool)
    signed = np.ones(n, bool) if signed is None else np.asarray(signed, bool)
    return r10.epoch_release(blocks, epochs, sampled, accepted, signed, start, EB, timing)


def read_rows(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


class SellerEpoch(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError):
            r10.Timing10(seller_epoch_k=0)
        with self.assertRaises(ValueError):
            r10.Timing10(dispute_from='epoch')
        self.assertEqual(r10.Timing10(seller_epoch_k=3).describe()['seller_epoch_k'], 3)
        self.assertEqual(T.describe()['dispute_from'], 'settlement')

    def test_k2_groups_two_profile_epochs(self):
        # Epoch 0: unsampled sale at 1299 (alone it passes at 1299 + 1801 = 3100); epoch 1: sampled sale at 1350
        # (proof deadline P(1) + 1 = 3651). With k = 2 both belong to seller epoch 0 and are paid together at 3651.
        out1, d1 = rel([1299, 1350], sampled=[0, 1])
        self.assertEqual(out1.tolist(), [3100, 3651])
        out2, d2 = rel([1299, 1350], sampled=[0, 1], timing=r10.Timing10(seller_epoch_k=2))
        self.assertEqual(out2.tolist(), [3651, 3651])
        self.assertEqual(d2[0]['why'], 'proof')
        self.assertEqual(d2[0]['epochs'], [0, 1])
        self.assertEqual(d2[0]['R'], 3651)
        # Epoch 3 (seller epoch 1) alone: a sale at 1950 passes at its dispute window 3751 (as with k = 1).
        out, d = rel([1299, 1350, 1950], sampled=[0, 1, 0], timing=r10.Timing10(seller_epoch_k=2))
        self.assertEqual(out.tolist(), [3651, 3651, 3751])
        self.assertEqual(sorted(d), [0, 1])
        self.assertEqual(d[1]['epochs'], [3])

    def test_accepted_sale_keeps_its_own_anchor(self):
        # An accepted sale of epoch 0 is paid at A(0) = 1399 even when its seller epoch (k = 2) waits for epoch 1.
        out, _ = rel([1010, 1350], sampled=[0, 1], accepted=[1, 0], timing=r10.Timing10(seller_epoch_k=2))
        self.assertEqual(out.tolist(), [1399, 3651])
        # Accepted in epoch 1: A(1) = 1699, not A(0).
        out, _ = rel([1010, 1350], sampled=[1, 0], accepted=[0, 1], timing=r10.Timing10(seller_epoch_k=2))
        self.assertEqual(out.tolist(), [3351, 1699])

    def test_unsigned_bind_per_profile_epoch(self):
        # Unsigned sale in epoch 1 with a short T_c: the bind term of epoch 1 (M(1) + 300 + 1 = 2151) sets R of the
        # seller epoch; the signed sale of epoch 0 waits for it under k = 2.
        short = r10.Timing10(dispute_window=100, seller_epoch_k=2)
        out, d = rel([1010, 1350], signed=[1, 0], timing=short)
        self.assertEqual(out.tolist(), [2151, 2151])
        self.assertEqual(d[0]['why'], 'bind')

    def test_k_never_pays_earlier(self):
        rng = np.random.default_rng(3)
        for trial in range(20):
            n = int(rng.integers(1, 60))
            blocks = np.sort(rng.integers(1000, 1000 + 12 * EB, n)).astype(np.int64)
            sampled = rng.random(n) < 0.3
            signed = rng.random(n) < 0.8
            accepted = signed & (rng.random(n) < 0.4)
            base, _ = rel(blocks, sampled, accepted, signed)
            for k in (2, 3, 5):
                out, d = rel(blocks, sampled, accepted, signed, timing=r10.Timing10(seller_epoch_k=k))
                self.assertTrue((out[~accepted] >= base[~accepted]).all(), (trial, k))
                self.assertTrue((out[accepted] == base[accepted]).all(), (trial, k))
                # One payment block per seller epoch, non-decreasing in the seller epoch.
                se = ((blocks - 1000) // EB) // k
                for E in np.unique(se):
                    self.assertEqual(len(set(out[(se == E) & ~accepted].tolist())) <= 1, True)
                rs = [d[E]['R'] for E in sorted(d)]
                self.assertEqual(rs, sorted(rs))

    def test_k1_is_the_r10_path(self):
        out, d = rel([1010, 1200, 1350, 1950], sampled=[1, 0, 0, 0])
        self.assertEqual(out.tolist(), [3351, 3351, 3351, 3751])
        self.assertEqual([d[e]['why'] for e in (0, 1, 3)], ['proof', 'cursor', 'dispute'])
        self.assertEqual(d[0]['epochs'], [0])


class DisputeFromAnchor(unittest.TestCase):
    A = r10.Timing10(dispute_from='anchor')

    def test_window_runs_from_anchor_deadline(self):
        # Unsampled epoch 0: R = A(0) + T_c + 1 = 1399 + 1801 = 3200 whatever the settlement block.
        out, d = rel([1000, 1150, 1299], timing=self.A)
        self.assertEqual(out.tolist(), [3200, 3200, 3200])
        self.assertEqual(d[0]['why'], 'dispute')
        self.assertEqual((out - np.array([1000, 1150, 1299])).tolist(), [2200, 2050, 1901])
        # Sampled epoch: the proof deadline (S + 2351) is later than A + T_c + 1 (S + 2200) under the main values.
        out, d = rel([1000, 1299], sampled=[1, 0], timing=self.A)
        self.assertEqual(out.tolist(), [3351, 3351])
        self.assertEqual(d[0]['why'], 'proof')
        # Accepted sales leave the dispute term: all accepted -> the sample value binds (M + 1 = 1551).
        out, d = rel([1000, 1299], accepted=[1, 1], timing=self.A)
        self.assertEqual(d[0]['R'], 1551)

    def test_settlement_origin_unchanged(self):
        out, _ = rel([1000, 1150, 1299])
        self.assertEqual(out.tolist(), [3100, 3100, 3100])          # 1299 + 1801

    def test_short_dispute_with_k(self):
        t = r10.Timing10(dispute_from='anchor', dispute_window=100, seller_epoch_k=2)
        out, d = rel([1010, 1350], timing=t)
        # Epoch 0: max(M + 1 = 1551, A + 101 = 1500) = 1551; epoch 1: max(1851, 1800) = 1851 -> seller epoch 1851.
        self.assertEqual(out.tolist(), [1851, 1851])
        self.assertEqual(d[0]['why'], 'sample')


class FraudSellerEpoch(unittest.TestCase):
    B = [1010, 1350]
    V = [10, 20]

    def x(self, timing, end):
        b = np.array(self.B)
        ep = (b - 1000) // EB
        smp = np.array([0, 1], bool)
        acc = np.zeros(2, bool)
        out, _ = r10.epoch_release(b, ep, smp, acc, np.ones(2, bool), start, EB, timing)
        return r10.fraud_x(b, self.V, out, ep, smp, acc, start, EB, timing, end)

    def test_seller_epoch_holds_earlier_profile_epoch(self):
        # The sampled sale c = 1350 (epoch 1) fails at P_fail(1) + 1 = 3651. With k = 1 the sale at 1010 (epoch 0) is
        # paid at 2811 and counts in X by end 3600; with k = 2 it is in the seller epoch of c and waits for 3651.
        # (f is -1 when the failure lands after `end`.)
        self.assertEqual(self.x(T, 3600), (10, -1, 1350))
        self.assertEqual(self.x(r10.Timing10(seller_epoch_k=2), 3600), (0, -1, 1350))
        self.assertEqual(self.x(r10.Timing10(seller_epoch_k=2), 10_000), (10, 3651, 1350))
        self.assertEqual(self.x(T, 10_000), (10, 3651, 1350))


class HeldBlocks(unittest.TestCase):
    def test_hand_values(self):
        # Sale of 5 settled at 10, paid at 15 (held at 10..14); sale of 7 settled at 20, paid at 22 (20, 21).
        self.assertEqual(engine.held_blocks([10, 20], [5, 7], [15, 22], 0, 100), 25 + 14)
        self.assertEqual(engine.held_blocks([10, 20], [5, 7], [15, 22], 12, 20), 15 + 7)
        # Not paid by the end: held to the end (inclusive).
        self.assertEqual(engine.held_blocks([10], [5], [10 ** 9], 0, 100), 5 * 91)
        self.assertEqual(engine.held_blocks([], [], [], 0, 100), 0)
        self.assertEqual(engine.held_blocks([10], [5], [15], 50, 40), 0)

    def test_matches_block_by_block(self):
        rng = np.random.default_rng(1)
        n = 200
        b = np.sort(rng.integers(0, 500, n))
        v = rng.integers(1, 1000, n)
        r = b + rng.integers(1, 300, n)
        lo, hi = 37, 420
        brute = sum(int(v[j]) for t in range(lo, hi + 1) for j in range(n) if b[j] <= t < r[j])
        self.assertEqual(engine.held_blocks(b, v, r, lo, hi), brute)


class EngineUnlimited(unittest.TestCase):
    def replay(self, **kw):
        rng = np.random.default_rng(7)
        n = 400
        blocks = np.sort(rng.choice(np.arange(50_000, 60_000), n, replace=False)).astype(np.int64)
        values = rng.integers(1, 15_000, n).astype(np.int64)      # some above the cap 10,000
        arrays = (blocks, values, np.arange(n, dtype=np.int64), np.zeros(n, dtype=np.int64))
        p = dict(tr.prof.load_profile(tr.PROFILE_FILE, 'data-api-fast-v1')['parameters'], deferBlocks=31_073)
        base = dict(seed=11, p=p, capacity=1, scale=1, origin_ledger=50_000, local_origin=p['epochOrigin'],
                    end_ledger=90_000, block_size={}, window_blocks=40_001, first_seconds=0, cap=10_000,
                    sample_tau=10_000, rounding='ceil', refill_ppm=10)
        base.update(kw)
        return engine.replay_address('0xabc', arrays, **base)

    def test_no_bucket_admits_everything_in_cap(self):
        row_b, _ = self.replay(release=r10.Release10(timing=T))
        self.assertGreater(row_b['rate_rejected_count'], 0)        # a tiny bucket rejects
        self.assertEqual(row_b['admission'], 'bucket')
        row, arr = self.replay(release=r10.Release10(timing=T), unlimited=True)
        self.assertEqual(row['admission'], 'unlimited')
        self.assertEqual(row['rate_rejected_count'], 0)
        self.assertEqual(row['accepted_count'] + row['cap_rejected_count'], row['attempted_count'])
        self.assertGreater(row['cap_rejected_count'], 0)
        self.assertTrue(row['has_revenue'])
        # Over-cap acceptance on top: every settlement is admitted, the ones above V are sampled with probability 1.
        row_o, arr_o = self.replay(release=r10.Release10(timing=r10.Timing10(accept_over_cap=True)), unlimited=True)
        self.assertEqual(row_o['accepted_count'], row_o['attempted_count'])
        self.assertEqual(row_o['cap_rejected_count'], 0)
        self.assertGreater(row_o['over_cap_accepted_count'], 0)
        self.assertGreaterEqual(row_o['sample_count'], row_o['over_cap_accepted_count'])
        # The continuous average: exact numerator over the window, equal to a direct recount from the arrays.
        self.assertEqual(row_o['H_cont_sum_blocks'],
                         engine.held_blocks(arr_o['blocks'], arr_o['values'], arr_o['release'], 50_000, 90_000))
        self.assertAlmostEqual(row_o['H_cont_average'], row_o['H_cont_sum_blocks'] / 40_001)

    def test_unlimited_needs_edition_10(self):
        with self.assertRaises(ValueError):
            self.replay(unlimited=True)


class Synthetic(unittest.TestCase):
    """Runs of replay.py on the synthetic list of test_replay."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.tmp.name)
        cls.s = tr.synthetic(d)
        config = design2.load_config()
        config['vmax_choices_usdc'] = ['0.01'] + config['vmax_choices_usdc']
        (d / 'design2.json').write_text(json.dumps(config))
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)

    @classmethod
    def tearDownClass(cls):
        replay.git_state = cls._git
        cls.tmp.cleanup()

    def base_argv(self, out, sales_cap='none'):
        argv = ['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '3',
                '--conditions', '1', '--repetitions', '1', '--design', '2', '--d2-config', str(self.d / 'design2.json'),
                '--vmax', '0.01']
        if sales_cap is not None:
            argv += ['--sales-cap', sales_cap]
        return argv

    def sweep_argv(self):
        argv = self.base_argv(self.d / 'unused')
        i = argv.index('--out')
        return argv[:i] + argv[i + 2:] + ['--preset', 'r11-main']

    def run_replay(self, name, *extra, sales_cap='none', expect=0):
        out = self.d / name
        argv = self.base_argv(out, sales_cap) + list(extra)
        if expect:
            with self.assertRaises(SystemExit):
                tr.run_cli(argv)
            return None
        code, _ = tr.run_cli(argv)
        self.assertEqual(code, 0)
        return out / 'condition-01-seed-0'

    def load_sales(self, cdir):
        z = np.load(cdir / 'sales.npz')
        addrs = json.loads((cdir / 'sales_addresses.json').read_text())
        return {k: z[k] for k in z.files}, addrs

    def test_main_setting(self):
        main = ('--release', 'fixed10', '--freeze-scope', 'detected-onward', '--r10-accept-over-cap',
                '--r10-dispute-from', 'anchor', '--r10-save-sales')
        c = self.run_replay('main', *main)
        rows = read_rows(c / 'addresses_observed.csv')
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r['admission'], 'unlimited')
            self.assertEqual(r['sales_cap_method'], 'none-unlimited')
            self.assertEqual(r['accepted_count'], r['attempted_count'])
            self.assertEqual(r['rate_rejected_count'], '0')
            self.assertEqual(r['cap_rejected_count'], '0')
            self.assertEqual(r['has_revenue'] == 'true', int(r['accepted_value']) > 0)
            self.assertEqual(float(r['H_ledger_list_max_abs_diff'] or 0), 0.0)
            if r['hold_max']:
                self.assertLessEqual(int(r['hold_max']), 2351)
        self.assertGreater(sum(int(r['over_cap_accepted_count']) for r in rows), 0)
        meta = json.loads((c / 'condition.json').read_text())
        self.assertEqual(meta['release10']['dispute_from'], 'anchor')
        self.assertEqual(meta['release10']['seller_epoch_k'], 1)
        self.assertTrue(meta['release10']['accept_over_cap'])
        self.assertEqual(meta['admission'], ['unlimited'])
        self.assertEqual(meta['sales_file'], 'sales.npz')
        self.assertEqual(meta['addresses_with_revenue'], sum(1 for r in rows if r['has_revenue'] == 'true'))
        self.assertEqual(meta['sales_caps'][rows[0]['address']]['method'], 'none-unlimited')
        env = json.loads((c.parent / 'run.json').read_text())
        self.assertTrue(env['parameters']['save_sales'])
        self.assertIn('seller_epoch', env['parameters']['options'])
        # The per-sale file: one row per accepted sale; the continuous average and the hourly average recomputed.
        z, addrs = self.load_sales(c)
        self.assertEqual(addrs, [r['address'] for r in rows])
        self.assertEqual(len(z['block']), sum(int(r['accepted_count']) for r in rows))
        first, last = env['inputs']['settlements']['first_block'], env['inputs']['settlements']['last_block']
        hold = meta['hold_blocks']
        points = np.arange(first + hold, last + 1, 1800)
        self.assertEqual(len(points), meta['hour_readings'])
        for i, r in enumerate(rows):
            m = z['address_index'] == i
            b, v, rl = z['block'][m], z['value'][m], z['release'][m]
            self.assertEqual(len(b), int(r['accepted_count']))
            if len(b) == 0:
                self.assertEqual(r['H_cont_sum_blocks'], '0')
                continue
            self.assertTrue((rl > b).all())
            # Continuous average, by a plain loop over the sales.
            num = sum(int(v[j]) * max(0, min(int(rl[j]), last + 1) - max(int(b[j]), first)) for j in range(len(b)))
            self.assertEqual(int(r['H_cont_sum_blocks']), num)
            self.assertAlmostEqual(float(r['H_cont_average']), num / (last - first + 1), delta=1e-6)
            # Hourly readings: H(t) = sum of v with settled <= t < release.
            h = [int(v[(b <= t) & (rl > t)].sum()) for t in points]
            self.assertAlmostEqual(float(r['H_time_average']), sum(h) / len(h), delta=1e-6)
            self.assertEqual(int(r['sample_count']), int(z['sampled'][m].sum()))
            self.assertEqual(int(r['buyer_accepted_count']), int(z['accepted'][m].sum()))
            # Dispute windows from the anchor deadline: a sale of an unsampled, unaccepted epoch is paid at
            # S(e) + 299 + 100 + 1800 + 1 = S(e) + 2200 or later (the cursor), never earlier.
            ep = z['epoch'][m]
            self.assertTrue((ep == (b - first) // 300).all())
            s_e = first + ep * 300                                   # S(e) of each sale
            self.assertTrue((rl[~z['accepted'][m]] >= (s_e + 2200)[~z['accepted'][m]]).all())

    def test_preset_equals_explicit_switches(self):
        explicit = self.run_replay('ex', '--release', 'fixed10', '--freeze-scope', 'detected-onward',
                                   '--r10-accept-over-cap', '--r10-dispute-from', 'anchor', '--r10-save-sales')
        preset = self.run_replay('pre', '--preset', 'r11-main', sales_cap=None)
        for f in FILES:
            self.assertEqual((explicit / f).read_bytes(), (preset / f).read_bytes(), f)
        a = json.loads((explicit / 'condition.json').read_text())
        b = json.loads((preset / 'condition.json').read_text())
        self.assertEqual(b.pop('preset'), 'r11-main')
        self.assertNotIn('preset', a)
        self.assertEqual(a, b)
        env = json.loads((preset.parent / 'run.json').read_text())
        self.assertEqual(env['parameters']['preset'], 'r11-main')
        self.assertEqual(env['parameters']['freeze_scope'], 'detected-onward')
        self.assertEqual(env['parameters']['release10']['dispute_from'], 'anchor')
        # An explicit switch wins over the preset.
        c = self.run_replay('pre2', '--preset', 'r11-main', '--r10-dispute-from', 'settlement', sales_cap=None)
        self.assertEqual(json.loads((c / 'condition.json').read_text())['release10']['dispute_from'], 'settlement')

    def test_legacy_bucket_variant(self):
        nf = ('--release', 'fixed10', '--freeze-scope', 'detected-onward', '--r10-accept-over-cap')
        legacy = self.run_replay('leg', *nf, sales_cap='auto-zero-reject')
        main = self.run_replay('leg_main', *nf)
        rl, rm = read_rows(legacy / 'addresses_observed.csv'), read_rows(main / 'addresses_observed.csv')
        for a, b in zip(rl, rm):
            self.assertEqual(a['address'], b['address'])
            self.assertEqual(a['admission'], 'bucket')
            self.assertIn(a['sales_cap_method'], ('min-zero-insample', 'no-record'))
            self.assertEqual(b['sales_cap_method'], 'none-unlimited')
            self.assertLessEqual(int(a['accepted_count']), int(b['accepted_count']))
            self.assertEqual(int(a['accepted_count']) + int(a['rate_rejected_count']), int(b['accepted_count']))
        self.assertEqual(json.loads((legacy / 'condition.json').read_text())['admission'], ['bucket'])

    def test_seller_epoch_k_runs_and_sweep(self):
        out = self.d / 'sweep'
        code = r11_k_sweep.main(['--k', '1,2', '--out', str(out), '--'] + self.sweep_argv())
        self.assertEqual(code, 0)
        c1, c2 = out / 'k1' / 'condition-01-seed-0', out / 'k2' / 'condition-01-seed-0'
        z1, a1 = self.load_sales(c1)
        z2, a2 = self.load_sales(c2)
        self.assertEqual(a1, a2)
        self.assertTrue((z1['block'] == z2['block']).all())
        self.assertTrue((z1['sampled'] == z2['sampled']).all())
        acc = z1['accepted']
        self.assertTrue((z2['release'][~acc] >= z1['release'][~acc]).all())
        self.assertTrue((z2['release'][acc] == z1['release'][acc]).all())
        self.assertGreater(int((z2['release'] > z1['release']).sum()), 0)
        r1 = {r['address']: r for r in read_rows(c1 / 'addresses_observed.csv')}
        r2 = {r['address']: r for r in read_rows(c2 / 'addresses_observed.csv')}
        for a in r1:
            self.assertEqual(r1[a]['accepted_count'], r2[a]['accepted_count'])
            self.assertGreaterEqual(int(r2[a]['H_cont_sum_blocks']), int(r1[a]['H_cont_sum_blocks']))
        self.assertEqual(json.loads((c2 / 'condition.json').read_text())['release10']['seller_epoch_k'], 2)
        sw = json.loads((out / 'k_sweep.json').read_text())
        self.assertEqual(sw['k'], [1, 2])
        s1 = sw['results']['1']['conditions']['condition-01-seed-0']
        s2 = sw['results']['2']['conditions']['condition-01-seed-0']
        self.assertGreaterEqual(s2['all']['sum_H_cont_average'], s1['all']['sum_H_cont_average'])
        self.assertEqual(s1['all']['sum_accepted_value'], s2['all']['sum_accepted_value'])
        self.assertEqual(s1['with_revenue']['addresses'], sum(1 for r in r1.values() if r['has_revenue'] == 'true'))
        self.assertAlmostEqual(s1['all']['sum_H_cont_average'],
                               sum(float(r['H_cont_average']) for r in r1.values()), delta=1e-6)
        with open(out / 'k_sweep.csv', newline='') as f:
            self.assertEqual(len(list(csv.DictReader(f))), 4)
        # Calling again skips the finished runs.
        self.assertEqual(r11_k_sweep.main(['--k', '1,2', '--out', str(out), '--'] + self.sweep_argv()), 0)

    def test_switch_checks(self):
        nf = ('--freeze-scope', 'detected-onward')
        self.run_replay('e1', *nf, expect=1)                                                # none without fixed10
        self.run_replay('e2', '--release', 'cursor8', *nf, '--r8-hold-window', '31372', expect=1)
        self.run_replay('e3', '--release', 'fixed10', *nf, '--r10-seller-epoch-k', '0', expect=1)
        self.run_replay('e4', '--r10-save-sales', *nf, sales_cap='auto-zero-reject', expect=1)
        self.run_replay('e5', '--release', 'fixed10', *nf, '--r10-dispute-from', 'anchor', '--r10-seller-epoch-k',
                        '3', sales_cap='auto-zero-reject')                                  # allowed with the bucket


if __name__ == '__main__':
    unittest.main()
