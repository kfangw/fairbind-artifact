"""The edition-10 release (release10.py, --release fixed10), with the cursor8 and hold outputs left unchanged."""
import csv
import hashlib
import itertools
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
import r10_deter  # noqa: E402
import release10 as r10  # noqa: E402
import replay  # noqa: E402
import test_replay as tr  # noqa: E402

GOLDEN8 = HERE / 'testdata_release8_cursor_hashes.json'
FILES = ('addresses_observed.csv', 'groups_observed.csv', 'addresses_injection.csv', 'groups_injection.csv',
         'condition.json')
T = r10.Timing10()                       # registered main values: d_A 100, tau_V 100, T_V 50, T_p 1800, T_c 1800, w_b 300
EB = 300


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


class Schedule(unittest.TestCase):
    def test_deadlines(self):
        # Epoch 0 starts at 1000: A = 1000 + 299 + 100, M = A + 100 + 1 + 50, P = M + 1800.
        self.assertEqual(r10.schedule(1000, EB, T), (1399, 1550, 3350, 3350))
        self.assertEqual(r10.schedule(1000, EB, r10.Timing10(proof_delay=30)), (1399, 1550, 1580, 3350))

    def test_validation(self):
        with self.assertRaises(ValueError):
            r10.Timing10(proof_delay=1801)
        with self.assertRaises(ValueError):
            r10.Timing10(accept_ppm=1_000_001)
        with self.assertRaises(ValueError):
            r10.check_epoch_length(r10.Timing10(vrf_response=250), EB)
        r10.check_epoch_length(T, EB)


class Release(unittest.TestCase):
    def test_path_lengths(self):
        # Epoch 0: a sampled sale at 1010 and an open one at 1200 -> the proof deadline 3351 binds.
        # Epoch 1: an unsampled sale at 1350 would pass at 1350 + 1801 = 3151 but waits for epoch 0 (R4).
        # Epoch 3: an unsampled sale at 1950 passes at its dispute window 3751.
        out, d = rel([1010, 1200, 1350, 1950], sampled=[1, 0, 0, 0])
        self.assertEqual(out.tolist(), [3351, 3351, 3351, 3751])
        self.assertEqual([d[e]['why'] for e in (0, 1, 3)], ['proof', 'cursor', 'dispute'])
        self.assertEqual((out - np.array([1010, 1200, 1350, 1950])).tolist(), [2341, 2151, 2001, 1801])

    def test_longest_hold_is_bounded(self):
        # A sampled epoch with a sale at its first block: hold d_A + 299 + tau_V + 1 + T_V + T_p + 1 = 2351.
        out, _ = rel([1000], sampled=[1])
        self.assertEqual(int(out[0]) - 1000, 299 + 100 + 100 + 1 + 50 + 1800 + 1)
        # Unsampled: the dispute window alone, T_c + 1.
        out, _ = rel([1299])
        self.assertEqual(int(out[0]) - 1299, 1801)

    def test_keeper_and_prompt_proof(self):
        out, _ = rel([1010, 1200], sampled=[1, 0], timing=r10.Timing10(keeper_delay=3))
        self.assertEqual(out.tolist(), [3354, 3354])
        out, d = rel([1010, 1200], sampled=[1, 0], timing=r10.Timing10(proof_delay=30))
        self.assertEqual(out.tolist(), [3001, 3001])               # the dispute window 1200 + 1801 now binds
        self.assertEqual(d[0]['why'], 'dispute')

    def test_acceptance(self):
        # An accepted sale is paid in the anchor transaction (A = 1399) and leaves the dispute term.
        out, d = rel([1010, 1200], sampled=[1, 0], accepted=[0, 1])
        self.assertEqual(out.tolist(), [3351, 1399])
        out, d = rel([1010, 1290], accepted=[0, 1])
        self.assertEqual(out.tolist(), [2811, 1399])                # 1010 + 1801, not 1290 + 1801
        # A sampled accepted sale still holds the cursor for the rest of its epoch (decision 4).
        out, d = rel([1010, 1200], sampled=[0, 1], accepted=[0, 1])
        self.assertEqual(out.tolist(), [3351, 1399])
        # Every sale accepted and none sampled: the cursor passes at M + 1 and holds nothing.
        out, d = rel([1010, 1200], accepted=[1, 1])
        self.assertEqual(out.tolist(), [1399, 1399])
        self.assertEqual(d[0]['R'], 1551)
        with self.assertRaises(ValueError):
            rel([1010], accepted=[1], signed=[0])

    def test_unsigned_bind_window(self):
        short = r10.Timing10(dispute_window=100)
        out, d = rel([1010], signed=[0], timing=short)
        self.assertEqual(out.tolist(), [1550 + 300 + 1])
        self.assertEqual(d[0]['why'], 'bind')
        out, _ = rel([1010], signed=[1], timing=short)
        self.assertEqual(out.tolist(), [1551])                      # signed: the sample value binds (1111 < 1551)
        out, _ = rel([1010], signed=[0])
        self.assertEqual(out.tolist(), [2811])                      # main T_c: W_e = 1851 does not bind

    def test_order_free(self):
        b = [1950, 1010, 1350, 1200]
        out, _ = rel(sorted(b), sampled=[1, 0, 0, 0])
        o2, _ = r10.epoch_release(np.array(b), (np.array(b) - 1000) // EB, np.array([0, 1, 0, 0], bool),
                                  np.zeros(4, bool), np.ones(4, bool), start, EB, T)
        self.assertEqual(dict(zip(b, o2.tolist())), dict(zip(sorted(b), out.tolist())))


class Flags(unittest.TestCase):
    def test_hash_rule(self):
        addr = '0x' + 'ab' * 20
        rows = np.arange(6000)
        s0, a0 = r10.buyer_flags(addr, rows, r10.Timing10())
        self.assertTrue(s0.all() and not a0.any())
        s1, a1 = r10.buyer_flags(addr, rows, r10.Timing10(accept_ppm=1_000_000))
        self.assertTrue(a1.all())
        s5, a5 = r10.buyer_flags(addr, rows, r10.Timing10(accept_ppm=500_000))
        s9, a9 = r10.buyer_flags(addr, rows, r10.Timing10(accept_ppm=900_000))
        self.assertAlmostEqual(a5.mean(), 0.5, delta=0.03)
        self.assertAlmostEqual(a9.mean(), 0.9, delta=0.03)
        self.assertFalse((a5 & ~a9).any())                          # nested in the share
        su, au = r10.buyer_flags(addr, rows, r10.Timing10(accept_ppm=900_000, unsigned_ppm=500_000))
        self.assertAlmostEqual((~su).mean(), 0.5, delta=0.03)
        self.assertFalse((au & ~su).any())
        self.assertTrue((au == (a9 & su)).all())
        # The rule written out: accepted iff SHA-256("fairbind/R10/accept|<address>|<row>") < ceil(a 2^256 / 10^6).
        thr = -(-500_000 * 2 ** 256 // 10 ** 6)
        for r in (0, 1, 2, 977):
            d = int.from_bytes(hashlib.sha256(f'fairbind/R10/accept|{addr}|{r}'.encode()).digest(), 'big')
            self.assertEqual(bool(a5[r]), d < thr)


class Fraud(unittest.TestCase):
    B = [1010, 1100, 1200, 1350, 1950]
    V = [10, 20, 30, 40, 50]

    def x(self, sampled, accepted=None, end=10_000):
        b = np.array(self.B)
        ep = (b - 1000) // EB
        acc = np.zeros(5, bool) if accepted is None else np.asarray(accepted, bool)
        out, _ = r10.epoch_release(b, ep, np.asarray(sampled, bool), acc, np.ones(5, bool), start, EB, T)
        return r10.fraud_x(b, self.V, out, ep, sampled, acc, start, EB, T, end)

    def test_narrow_freeze(self):
        # The sampled sale at 1200 fails at P_fail(0) + 1 = 3351: 1200 and later are frozen, 1010 and 1100 are paid.
        self.assertEqual(self.x([0, 0, 1, 0, 0]), (30, 3351, 1200))
        self.assertEqual(self.x([0, 0, 1, 0, 0], accepted=[0, 1, 0, 0, 0]), (10, 3351, 1200))
        # An accepted sampled sale also fails and freezes what follows it.
        self.assertEqual(self.x([0, 1, 0, 0, 0], accepted=[0, 1, 0, 0, 0]), (10, 3351, 1100))
        # No sample: every open sale paid by the end.
        self.assertEqual(self.x([0] * 5), (150, -1, -1))
        # The failure lands after the end: nothing is paid by 3000 (epoch 0 waits for its case).
        self.assertEqual(self.x([0, 0, 1, 0, 0], end=3000), (0, -1, 1200))

    def test_closed_form_equals_enumeration(self):
        b = np.array([1010, 1010, 1100, 1350, 1700, 1950], dtype=np.int64)
        v = np.array([50_000, 20_000, 200_000, 10_000, 100_000, 70_000], dtype=np.int64)
        V = 200_000
        pi = np.minimum(1.0, v / V)
        acc = np.array([0, 1, 0, 0, 0, 1], bool)
        ep = (b - 1000) // EB
        end = 100_000
        total = 0.0
        for pattern in itertools.product((0, 1), repeat=len(b)):
            smp = np.array(pattern, bool)
            w = float(np.prod(np.where(smp, pi, 1 - pi)))
            if w == 0:
                continue
            out, _ = r10.epoch_release(b, ep, smp, acc, np.ones(len(b), bool), start, EB, T)
            total += w * r10.fraud_x(b, v, out, ep, smp, acc, start, EB, T, end)[0]
        out0, _ = r10.epoch_release(b, ep, np.zeros(len(b), bool), acc, np.ones(len(b), bool), start, EB, T)
        self.assertAlmostEqual(r10.exact_expectation(b, v, pi, out0, acc, end), total, places=6)
        self.assertLessEqual(total, V)                               # E[X] <= V / s with s = 1


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

    def run_replay(self, name, *extra, expect=0):
        out = self.d / name
        argv = ['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '3',
                '--conditions', '1', '--repetitions', '1', '--design', '2', '--d2-config', str(self.d / 'design2.json'),
                '--vmax', '0.01', '--sales-cap', 'auto-zero-reject']
        if expect:
            with self.assertRaises(SystemExit):
                tr.run_cli(argv + list(extra))
            return None
        code, _ = tr.run_cli(argv + list(extra))
        self.assertEqual(code, 0)
        return out / 'condition-01-seed-0'

    def hashes(self, cdir):
        import hashlib as h
        return {f: h.sha256((cdir / f).read_bytes()).hexdigest() for f in FILES}

    def test_cursor8_outputs_unchanged(self):
        golden = json.loads(GOLDEN8.read_text())
        base = ['--release', 'cursor8', '--freeze-scope', 'detected-onward', '--r8-hold-window', '31372']
        self.assertEqual(self.hashes(self.run_replay('c8', *base)), golden['cursor8'])
        self.assertEqual(self.hashes(self.run_replay('c8s', *base, '--r8-open-offset', '1131', '--r8-case-length',
                                                     '2402', '--r8-bind-window', '600')), golden['cursor8_short'])

    def test_fixed10_run(self):
        nf = ('--freeze-scope', 'detected-onward')
        c10 = self.run_replay('f10', '--release', 'fixed10', *nf)
        c10a = self.run_replay('f10a', '--release', 'fixed10', *nf, '--r10-accept-ppm', '900000')
        c7 = self.run_replay('f7', *nf)
        rows = {r['address']: r for r in read_rows(c10 / 'addresses_observed.csv')}
        rows_a = {r['address']: r for r in read_rows(c10a / 'addresses_observed.csv')}
        rows7 = {r['address']: r for r in read_rows(c7 / 'addresses_observed.csv')}
        first = next(iter(rows.values()))
        for c in replay.R10_ROW_COLUMNS:
            self.assertIn(c, first)
        self.assertNotIn('hold_cap_N_h', first)
        n_acc = n_buyer = 0
        for a, r in rows.items():
            r7, ra = rows7[a], rows_a[a]
            for c in ('accepted_count', 'accepted_value', 'sample_count', 'rate_rejected_count', 'cap_rejected_count',
                      'epochs_with_settlement'):
                self.assertEqual(r[c], r7[c], (a, c))
                self.assertEqual(ra[c], r7[c], (a, c))
            self.assertEqual(float(r['H_ledger_list_max_abs_diff'] or 0), 0.0)
            self.assertEqual(float(ra['H_ledger_list_max_abs_diff'] or 0), 0.0)
            self.assertEqual(r['buyer_accepted_count'], '0')
            if int(r['accepted_count']):
                self.assertLessEqual(float(r['H_time_average']), float(r7['H_time_average']) + 1e-9)
                self.assertLessEqual(float(ra['H_time_average']), float(r['H_time_average']) + 1e-9)
                if r['hold_max']:                                       # some sale released by the end
                    self.assertLessEqual(int(r['hold_max']), 2351)
                    self.assertGreaterEqual(int(r['hold_p50']), 1801 if r['sample_count'] == '0' else 0)
                n_acc += int(ra['accepted_count'])
                n_buyer += int(ra['buyer_accepted_count'])
        self.assertAlmostEqual(n_buyer / n_acc, 0.9, delta=0.03)
        meta = json.loads((c10a / 'condition.json').read_text())
        self.assertEqual(meta['release10']['accept_ppm'], 900000)
        self.assertEqual(meta['release10']['proof_window'], 1800)
        self.assertNotIn('release8', meta)
        env = json.loads((c10.parent / 'run.json').read_text())
        self.assertEqual(env['parameters']['release10']['mode'], 'fixed10')
        self.assertTrue(env['parameters']['options']['release'].startswith('R10-fixed'))

    def test_over_cap(self):
        c = self.run_replay('f10o', '--release', 'fixed10', '--freeze-scope', 'detected-onward', '--r10-accept-over-cap')
        rows = read_rows(c / 'addresses_observed.csv')
        over = sum(int(r['over_cap_accepted_count']) for r in rows)
        self.assertGreater(over, 0)
        for r in rows:
            self.assertGreaterEqual(int(r['sample_count']), int(r['over_cap_accepted_count']))

    def test_switch_checks(self):
        self.run_replay('e1', '--release', 'fixed10', expect=1)                          # needs the narrow freeze
        self.run_replay('e2', '--r10-proof-window', '300', expect=1)                     # r10 switch without fixed10
        self.run_replay('e3', '--release', 'cursor8', '--freeze-scope', 'detected-onward', '--r10-accept-ppm', '1',
                        expect=1)
        self.run_replay('e4', '--release', 'fixed10', '--freeze-scope', 'detected-onward', '--r8-case-length', '9',
                        expect=1)
        self.run_replay('e5', '--release', 'fixed10', '--freeze-scope', 'detected-onward', '--r10-vrf-response',
                        '400', expect=1)                                                  # T_epoch < tau_V + 1 + T_V


class EngineFraud(unittest.TestCase):
    """engine.replay_address with the edition-10 release on one address, and the fraud model of r10_deter."""

    def replay(self, seed, n=400, timing=T):
        rng = np.random.default_rng(5)
        blocks = np.sort(rng.choice(np.arange(50_000, 90_000), n, replace=False)).astype(np.int64)
        values = rng.integers(1, 1_500, n).astype(np.int64)
        arrays = (blocks, values, np.arange(n, dtype=np.int64), np.zeros(n, dtype=np.int64))
        p = tr.prof.load_profile(tr.PROFILE_FILE, 'data-api-fast-v1')['parameters']
        p = dict(p, deferBlocks=31_073)
        self.p = p
        return engine.replay_address('0xabc', arrays, seed=seed, p=p, capacity=137, scale=1, origin_ledger=50_000,
                                     local_origin=p['epochOrigin'], end_ledger=90_000, block_size={},
                                     window_blocks=40_001, first_seconds=0, cap=10_000, sample_tau=10_000,
                                     rounding='ceil', refill_ppm=50_000, release=r10.Release10(timing=timing))

    def start_of(self, e):
        return self.p['epochOrigin'] + e * self.p['epochBlocks'] - self.p['epochOrigin'] + 50_000

    def test_release_arrays_and_mean_against_closed_form(self):
        row, arr = self.replay(11)
        self.assertEqual(len(arr['release']), row['accepted_count'])
        self.assertTrue((arr['release'] > arr['blocks']).all())
        self.assertEqual(row['buyer_accepted_count'], 0)
        m, ex = r10_deter.x_variants(arr, T, self.start_of, 300, 90_000, '0xabc', want_exact=True)
        self.assertLessEqual(ex['r10_a09'], ex['r10_a05'] + 1e-12)
        self.assertLessEqual(ex['r10_a05'], ex['r10'] + 1e-12)
        self.assertLessEqual(ex['r10'], 0.2)
        xs = []
        for seed in range(300):
            _, a = self.replay(1000 + seed)
            xs.append(r10_deter.x_variants(a, T, self.start_of, 300, 90_000, '0xabc')[0]['r10'][0] / 1e6)
        xs = np.array(xs)
        se = xs.std(ddof=1) / np.sqrt(len(xs))
        self.assertLess(abs(xs.mean() - ex['r10']), 4 * se + 1e-4)

    def test_acceptance_shortens_holds(self):
        row0, _ = self.replay(11)
        row9, arr9 = self.replay(11, timing=r10.Timing10(accept_ppm=900_000))
        self.assertGreater(row9['buyer_accepted_count'], 0.8 * row9['accepted_count'])
        self.assertLess(row9['H_time_average'], row0['H_time_average'])
        self.assertEqual(row9['sample_count'], row0['sample_count'])
        acc = arr9['accepted']
        # An accepted sale is paid at its anchor deadline: last block of its epoch + 100.
        e = arr9['epochs'][acc]
        self.assertTrue((arr9['release'][acc] == np.array([self.start_of(int(x)) + 299 + 100 for x in e])).all())

    def test_tail_counts(self):
        X = np.zeros((50, 2))
        X[:, 1] = 1.0
        t = r10_deter.tail_counts(X, [0, 1], 0.2)
        self.assertEqual(t['points'], 200)
        self.assertEqual(t['above_bound'], 100)            # the address with X = 1 always exceeds exp(-5x)
        self.assertAlmostEqual(r10_deter._norm_ppf(0.025), -1.959964, places=4)


if __name__ == '__main__':
    unittest.main()
