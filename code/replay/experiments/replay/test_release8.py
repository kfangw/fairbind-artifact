"""The cursor release of rule edition 8 (release8.py, --release cursor8) and the edition-7 hold left unchanged."""
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
import r8_deter  # noqa: E402
import release8  # noqa: E402
import replay  # noqa: E402
import test_replay as tr  # noqa: E402

GOLDEN = HERE / 'testdata_release8_hold_hashes.json'
FILES = ('addresses_observed.csv', 'groups_observed.csv', 'addresses_injection.csv', 'groups_injection.csv',
         'condition.json')


def read_rows(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


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

    def run_replay(self, name, *extra, design2_args=True, expect=0):
        out = self.d / name
        argv = ['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '3',
                '--conditions', '1', '--repetitions', '1']
        if design2_args:
            argv += ['--design', '2', '--d2-config', str(self.d / 'design2.json'), '--vmax', '0.01',
                     '--sales-cap', 'auto-zero-reject']
        if expect:
            with self.assertRaises(SystemExit):
                tr.run_cli(argv + list(extra))
            return None
        code, _ = tr.run_cli(argv + list(extra))
        self.assertEqual(code, 0)
        return out / 'condition-01-seed-0'

    def hashes(self, cdir):
        return {f: hashlib.sha256((cdir / f).read_bytes()).hexdigest() for f in FILES}

    def test_hold_outputs_are_those_before_the_cursor_release(self):
        """Edition 7 (no switch, or --release hold) writes byte for byte what the code wrote before release8."""
        golden = json.loads(GOLDEN.read_text())
        for name, extra, d2 in (('full', [], True), ('narrow', ['--freeze-scope', 'detected-onward'], True),
                                ('design1', [], False)):
            got = self.hashes(self.run_replay('g_' + name, *extra, design2_args=d2))
            self.assertEqual(got, golden[name], name)
        got = self.hashes(self.run_replay('g_explicit', '--release', 'hold'))
        self.assertEqual(got, golden['full'])

    def test_cursor_run_columns_and_checks(self):
        cdir = self.run_replay('r8', '--release', 'cursor8', '--freeze-scope', 'detected-onward',
                               '--r8-hold-window', '31372')
        hold = self.run_replay('r8_hold', '--freeze-scope', 'detected-onward')
        rows = read_rows(cdir / 'addresses_observed.csv')
        rows7 = {r['address']: r for r in read_rows(hold / 'addresses_observed.csv')}
        for c in replay.R8_ROW_COLUMNS:
            self.assertIn(c, rows[0])
        self.assertNotIn('hold_mean', next(iter(rows7.values())))
        for r in rows:
            r7 = rows7[r['address']]
            # Admission, sampling and case counts do not depend on the release (the cap does not bind here).
            for c in ('accepted_count', 'accepted_value', 'sample_count', 'rate_rejected_count', 'cap_rejected_count'):
                self.assertEqual(r[c], r7[c], (r['address'], c))
            self.assertEqual(r['hold_cap_rejected_count'], '0')
            self.assertEqual(float(r['H_ledger_list_max_abs_diff'] or 0), 0.0)
            if int(r['accepted_count']):
                self.assertLessEqual(float(r['H_time_average']), float(r7['H_time_average']) + 1e-9)
        meta = json.loads((cdir / 'condition.json').read_text())
        self.assertEqual(meta['release8']['case_length'], 7512)          # the confirmation delay of the profile
        env = json.loads((cdir.parent / 'run.json').read_text())
        self.assertEqual(env['parameters']['release8']['mode'], 'cursor8')
        self.assertTrue(env['parameters']['options']['release'].startswith('R8-cursor'))

    def test_cursor_needs_the_narrow_freeze_and_design_2(self):
        self.run_replay('bad1', '--release', 'cursor8', expect=1)
        self.run_replay('bad2', '--release', 'cursor8', '--freeze-scope', 'detected-onward', design2_args=False,
                        expect=1)
        self.run_replay('bad3', '--r8-hold-window', '100', expect=1)


TIMING = release8.CursorTiming(case_length=100, buyer_window=50)
OPEN = {0: 1000, 1: 1300, 2: 1600}


class HandCounted(unittest.TestCase):
    """Small examples counted by hand."""

    def test_three_epochs_one_sampled_case(self):
        # epoch 0: 10, 20 (no case): max(seal 1001, buyer 20 + 50 + 1) = 1001
        # epoch 1: 310 (sampled), 350: max(seal 1301, case 1300 + 100 + 1, buyer 401) = 1401
        # epoch 2: 620: max(seal 1601, buyer 671) = 1601
        blocks = [10, 20, 310, 350, 620]
        epochs = [0, 0, 1, 1, 2]
        smp = [False, False, True, False, False]
        r, detail = release8.epoch_release(blocks, epochs, smp, OPEN, TIMING)
        self.assertEqual(r.tolist(), [1001, 1001, 1401, 1401, 1601])
        self.assertEqual({e: w for e, (_, w) in detail.items()}, {0: 'seal', 1: 'case', 2: 'seal'})
        # keeper delay and the unsigned bind window W_e = (open - 1) + w_b
        t = release8.CursorTiming(case_length=100, buyer_window=50, bind_window=600, keeper_delay=3)
        r, _ = release8.epoch_release(blocks, epochs, smp, OPEN, t)
        self.assertEqual(r.tolist(), [1603, 1603, 1903, 1903, 2203])

    def test_cursor_blocked_by_an_earlier_case(self):
        """The case of epoch 1 runs to 5,000: epoch 2, ready at 1,601, waits for it (R4)."""
        blocks, epochs, smp = [10, 310, 620, 640], [0, 1, 2, 2], [False, True, False, False]
        end = [-1, 5000, -1, -1]
        r, detail = release8.epoch_release(blocks, epochs, smp, OPEN, TIMING, case_end=end)
        self.assertEqual(r.tolist(), [1001, 5001, 5001, 5001])
        self.assertEqual(detail[2], (5001, 'cursor'))

    def test_pass_and_fail(self):
        """One sampled case at the sale of block 310 (epoch 1). PASS: every sale is paid by its epoch's R. FAIL at
        f = 1,400 (narrow freeze from c = 310): 310, 350 and 620 are unpaid at f and frozen; 10 and 20 are paid at
        1,001. Under a fixed hold of 500 the same failure freezes nothing (310 + 500 <= 1,400)."""
        blocks = np.array([10, 20, 310, 350, 620], dtype=np.int64)
        values = np.array([5, 7, 11, 13, 17], dtype=np.int64)
        epochs = np.array([0, 0, 1, 1, 2])
        r, _ = release8.epoch_release(blocks, epochs, [False, False, True, False, False], OPEN, TIMING)
        # PASS: no failure, the fraud replay releases everything with R <= end
        self.assertEqual(r8_deter.released_value_cursor(blocks, values, r, epochs, None, None, end=1500), 5 + 7 + 11 + 13)
        self.assertEqual(r8_deter.released_value_cursor(blocks, values, r, epochs, None, None, end=2000), 53)
        # FAIL at 1,400 of the case of the sale at 310
        self.assertEqual(r8_deter.released_value_cursor(blocks, values, r, epochs, 1400, 310, end=2000), 12)
        f = np.array([1400], dtype=np.int64)
        kw = dict(reentry=0, claim_probs=[1.0], share=3, rng=np.random.default_rng(0), start=0, end=2000,
                  fw_edges=np.array([0, 2000]), claim_window=100, scope='detected-onward', f_settled=np.array([310]))
        cursor = engine.evaluate_failures(blocks, values, f, hold=replay.R8_FREEZE_HOLD, **kw)[0]
        self.assertEqual(cursor['principal'], 11 + 13 + 17)
        fixed = engine.evaluate_failures(blocks, values, f, hold=500, **kw)[0]
        self.assertEqual(fixed['principal'], 0)
        # with a case shorter than the failure, the epoch of c still waits for the failed case: R' = f + 1
        short = release8.CursorTiming(case_length=10, buyer_window=50)
        r2, _ = release8.epoch_release(blocks[:2], epochs[:2], [False, False], OPEN, short)
        self.assertEqual(r2.tolist(), [1001, 1001])
        self.assertEqual(r8_deter.released_value_cursor(blocks[:2], values[:2], r2, epochs[:2], 1400, 20, end=1400), 0)
        self.assertEqual(r8_deter.released_value_cursor(blocks[:2], values[:2], r2, epochs[:2], 1400, 20, end=1401), 5)

    def test_closed_form_equals_enumeration(self):
        """exact_expectation_cursor against every detection pattern of four sales (case length = delay)."""
        blocks = np.array([10, 20, 310, 620], dtype=np.int64)
        values = np.array([30_000, 50_000, 70_000, 20_000], dtype=np.int64)
        epochs = np.array([0, 0, 1, 2])
        s_prob = np.array([0.15, 0.25, 0.35, 0.1])
        p0, delay = 0.4, TIMING.case_length
        r, _ = release8.epoch_release(blocks, epochs, [True] * 4, OPEN, TIMING)
        for end in (1200, 1450, 2000):
            total = 0.0
            for det in itertools.product((0, 1), repeat=4):
                pr = np.prod([q if d else 1 - q for q, d in zip(p0 * s_prob, det)])
                det = np.array(det, dtype=bool)
                opens = np.array([OPEN[int(e)] for e in epochs])
                f, c = (None, None)
                if det.any():
                    f = int(opens[det].min()) + delay
                    c = int(blocks[det & (opens == opens[det].min())].min())
                    if f > end:
                        f, c = None, None
                total += pr * r8_deter.released_value_cursor(blocks, values, r, epochs, f, c, end)
            exact = r8_deter.exact_expectation_cursor(blocks, values, s_prob, r, p0, end)
            self.assertAlmostEqual(total, exact, places=6)


class HoldCap(unittest.TestCase):
    """The held-settlement cap N_h (D2-42)."""

    def test_formula(self):
        self.assertEqual(release8.hold_cap(2, 50_000, 1, 31_372), 1571)       # ceil(2 + 0.05 * 31,372)
        self.assertEqual(release8.hold_cap(137, 50_000, 2, 31_372), 3412)     # ceil(274 + 0.1 * 31,372)
        self.assertIsNone(release8.hold_cap(2, 50_000, 1, None))

    def test_rejections(self):
        """A large bucket and N_h = 3: in epoch 0 the fourth and fifth sales are rejected; once epoch 0 is paid at
        1,001 the sales of epoch 1 are accepted again. A rejected sale does not consume the bucket."""
        blocks = np.array([1, 2, 3, 4, 5, 1100, 1101], dtype=np.int64)
        epochs = np.array([0, 0, 0, 0, 0, 3, 3])
        smp = np.zeros(7, dtype=bool)
        open_ = {0: 1000, 3: 1900}
        acc, capped = release8.admit_cursor(blocks, epochs, smp, open_, TIMING, capacity=100, refill_ppm=0, scale=1,
                                            registered_block=0, local_blocks=blocks, n_cap=3)
        self.assertEqual(acc.tolist(), [True, True, True, False, False, True, True])
        self.assertEqual(capped.tolist(), [False, False, False, True, True, False, False])
        # a bucket of three: the cap rejects first, the bucket still has room for epoch 3
        acc, capped = release8.admit_cursor(blocks, epochs, smp, open_, TIMING, capacity=4, refill_ppm=0, scale=1,
                                            registered_block=0, local_blocks=blocks, n_cap=3)
        self.assertEqual(acc.tolist(), [True, True, True, False, False, True, False])
        self.assertEqual(capped.tolist(), [False, False, False, True, True, False, False])

    def test_held_count_waits_for_a_blocked_cursor(self):
        """N_h = 2, case length 2,000. 10 and 310 are held, so 311 is rejected. Epoch 0 is paid at 1,001: the sale at
        1,000 is rejected, the one at 1,001 accepted. Epoch 1's case ends at 3,300, so epochs 1 and 3 are paid at
        3,301 (epoch 3 is ready at 1,901 but the cursor waits): 3,300 is rejected and 3,301 accepted."""
        t = release8.CursorTiming(case_length=2000, buyer_window=50)
        blocks = np.array([10, 310, 311, 1000, 1001, 3300, 3301], dtype=np.int64)
        epochs = np.array([0, 1, 1, 3, 3, 11, 11])
        smp = np.array([False, True, False, False, False, False, False])
        open_ = {0: 1000, 1: 1300, 3: 1900, 11: 4300}
        acc, capped = release8.admit_cursor(blocks, epochs, smp, open_, t, capacity=100, refill_ppm=0, scale=1,
                                            registered_block=0, local_blocks=blocks, n_cap=2)
        self.assertEqual(acc.tolist(), [True, True, False, False, True, False, True])
        self.assertEqual(capped.tolist(), [False, False, True, True, False, True, False])

    def test_without_a_cap_admission_is_engine_admit(self):
        rng = np.random.default_rng(3)
        local = np.sort(rng.integers(1000, 40_000, 3000))
        epochs = (local - 1000) // 300
        open_ = {int(e): int(1000 + (e + 2) * 300 + 869) for e in np.unique(epochs)}
        acc, capped = release8.admit_cursor(local, epochs, rng.random(3000) < 0.1, open_, TIMING, capacity=5,
                                            refill_ppm=40_000, scale=2, registered_block=1000, local_blocks=local,
                                            n_cap=None)
        self.assertEqual(acc.tolist(), engine.admit(local, 5, 40_000, 2, 1000).tolist())
        self.assertFalse(capped.any())


class Engine(unittest.TestCase):
    """engine.replay_address with the cursor release on one address."""

    def replay(self, release, n=600):
        rng = np.random.default_rng(5)
        blocks = np.sort(rng.choice(np.arange(50_000, 120_000), n, replace=False)).astype(np.int64)
        values = rng.integers(1, 9_000, n).astype(np.int64)
        arrays = (blocks, values, np.arange(n, dtype=np.int64), np.zeros(n, dtype=np.int64))
        p = tr.prof.load_profile(tr.PROFILE_FILE, 'data-api-fast-v1')['parameters']
        p = dict(p, deferBlocks=31_073)
        return engine.replay_address('0xabc', arrays, seed=7, p=p, capacity=137, scale=1, origin_ledger=50_000,
                                     local_origin=p['epochOrigin'], end_ledger=120_000, block_size={},
                                     window_blocks=70_001, first_seconds=0, cap=10_000, sample_tau=10_000,
                                     rounding='ceil', refill_ppm=50_000, release=release)

    def test_same_admission_and_cases_shorter_holds(self):
        row7, arr7 = self.replay(None)
        rel = release8.Release8(timing=release8.CursorTiming(case_length=7512), h_n=31_372)
        row8, arr8 = self.replay(rel)
        for c in ('accepted_count', 'accepted_value', 'sample_count', 'epochs_with_settlement'):
            self.assertEqual(row7[c], row8[c])
        self.assertEqual(arr7['cases'].tolist(), arr8['cases'].tolist())
        self.assertEqual(arr7['case_settled'].tolist(), arr8['case_settled'].tolist())
        self.assertEqual(row8['hold_cap_rejected_count'], 0)
        self.assertEqual(row8['H_ledger_list_max_abs_diff'], 0)
        self.assertLess(row8['H_time_average'], row7['H_time_average'])
        self.assertLessEqual(row8['hold_max'], 300 + 1469 + 7512 + 1)       # epoch + prompt opening + case + 1
        h = arr8['release'] - arr8['blocks']
        self.assertTrue((h > 1860).all())                                    # buyer window
        self.assertEqual(int(np.sum(row8['hold_histogram'])), row8['hold_released_count'])
        # every sampled sale's epoch is released after its case: open + 7,512 + 1
        for e, s in zip(arr8['epochs'][arr8['sampled']], arr8['release'][arr8['sampled']]):
            o = engine.case_open_block(int(e), dict(tr.prof.load_profile(tr.PROFILE_FILE, 'data-api-fast-v1')['parameters']))
            self.assertGreaterEqual(int(s), o - 1000 + 50_000 + 7512 + 1)

    def test_a_tight_cap_rejects(self):
        rel = release8.Release8(timing=release8.CursorTiming(case_length=7512), h_n=0)
        row, _ = self.replay(rel, n=3000)
        self.assertEqual(row['hold_cap_N_h'], 137)
        self.assertGreater(row['hold_cap_rejected_count'], 0)
        self.assertEqual(row['attempted_count'], row['accepted_count'] + row['cap_rejected_count']
                         + row['rate_rejected_count'] + row['hold_cap_rejected_count'])


if __name__ == '__main__':
    unittest.main()


class FraudReplay(unittest.TestCase):
    """r8_deter.py on the synthetic list: the 'narrow7' variant is the J7 'narrow' variant on the same draws."""

    def test_narrow7_equals_j7_model(self):
        import argparse
        import d2_deter as dd
        import d2_deter_narrow as dn
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            s = tr.synthetic(d)
            out = d / 'out'
            argv = ['--settlements', str(s['csv']), '--reference-dir', str(s['dir']), '--conditions-file',
                    str(s['conditions']), '--out', str(out)]
            self.assertEqual(r8_deter.main(['run', *argv[:-2], '--out', str(out), '--replicates', '2', '--jobs', '1']), 0)
            ctx = dd.Context(argparse.Namespace(settlements=str(s['csv']), reference_dir=str(s['dir']),
                                                conditions_file=str(s['conditions']), out=str(out)))
            for rep in range(2):
                recs, _, _ = dn.one_replicate(ctx, rep)
                mine = json.loads((out / 'per_seed' / f'rep_{rep:04d}.json').read_text())
                self.assertEqual([(x['address'], x['X_narrow'], x['f_narrow']) for x in recs],
                                 [(y['address'], y['X_narrow7'], y['f_narrow7']) for y in mine])
                # the cursor pays no sale later than the failure blocks it, and none after the window
                for y in mine:
                    self.assertEqual(y['f_r8'], y['f_narrow7'])
            exact = json.loads((out / 'exact_expectation.json').read_text())
            self.assertTrue(exact['closed_form_exact'])
            self.assertTrue(all(v['r8'] <= 0.5 + 1e-12 for v in exact['addresses'].values()))
