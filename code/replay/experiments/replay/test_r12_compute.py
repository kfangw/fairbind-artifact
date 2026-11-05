"""Registration R12: the aggregation r12_compute.py on synthetic data only (no window data is read).

Three kinds of test:
  * the registered block and the record comparison (the self-check that R11's JX11 defect asked for: a key present on
    one side only, such as `mode`, must fail the comparison; the block parsed from the registration must equal the
    code's constant key by key);
  * the pieces (exact sums, history caps, the rate-cap admission, exposure, union lengths, lags, k choice) against
    brute force;
  * an end-to-end run: the real replayer with the registered flags on the synthetic list of test_replay (k in
    {1, 2, 4, 8, 16, 32} and the bridge), then `compute`, then per-address brute force of the comparator cells and of
    the FairBind numerators from sales.npz, and the registered verdict paths in the output.
`synthetic_end_to_end` is also what `r12_compute.py selfcheck` runs before any real replay.
"""
import copy
import csv
import json
import random
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import numpy as np  # noqa: E402

import r12_compute as rc  # noqa: E402

PRIOR_BLOCKS = 14 * 43_200


def _dict_rows(path):
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def registration_text(block=None, extra_block=False):
    body = json.dumps(rc.REGISTERED if block is None else block, indent=1)
    t = '# R12 synthetic registration\n\ntext\n\n' + rc.FENCE + '\n' + body + '\n```\n\nmore text\n'
    if extra_block:
        t += rc.FENCE + '\n{}\n```\n'
    return t


# ---------------------------------------------------------------- registered block and records

class Registration(unittest.TestCase):
    def test_block_round_trip(self):
        self.assertEqual(rc.registration_block(registration_text()), rc.REGISTERED)

    def test_check_registration_passes_and_fails(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'reg.md'
            p.write_text(registration_text())
            sha, block = rc.check_registration(p)
            self.assertEqual(len(sha), 64)
            changed = copy.deepcopy(rc.REGISTERED)
            changed['release10']['cost']['vrf_slack'] = 21
            p.write_text(registration_text(changed))
            with self.assertRaises(SystemExit):
                rc.check_registration(p)
            dropped = copy.deepcopy(rc.REGISTERED)
            del dropped['release10']['cost']['mode']
            p.write_text(registration_text(dropped))
            with self.assertRaises(SystemExit):
                rc.check_registration(p)
            p.write_text(registration_text(extra_block=True))
            with self.assertRaises(ValueError):
                rc.check_registration(p)

    def test_compare_record_counts_every_key(self):
        exp = rc.expected_release10('cost', 4)
        self.assertTrue(rc.compare_record(exp, dict(exp))['ok'])
        # the R11 JX11 case: the written record carries `mode`, the expectation lost it
        no_mode = {k: v for k, v in exp.items() if k != 'mode'}
        r = rc.compare_record(no_mode, exp)
        self.assertFalse(r['ok'])
        self.assertEqual(r['extra'], ['mode'])
        r = rc.compare_record(exp, no_mode)
        self.assertFalse(r['ok'])
        self.assertEqual(r['missing'], ['mode'])
        r = rc.compare_record(exp, dict(exp, seller_epoch_k=2))
        self.assertEqual([d[0] for d in r['differing']], ['seller_epoch_k'])
        r = rc.compare_record(exp, dict(exp, accept_over_cap=1))     # 1 == True but not the same type
        self.assertFalse(r['ok'])
        self.assertFalse(rc.compare_record(exp, None)['ok'])

    def test_no_key_exclusion_in_the_source(self):
        # the comparison code must not skip keys; R11's defect was `if k != 'mode'`
        src = (HERE / 'r12_compute.py').read_text()
        self.assertNotIn("!= 'mode'", src)
        self.assertNotIn('!= "mode"', src)

    def test_lags_and_suffixes_come_from_the_block(self):
        self.assertEqual(set(rc.REGISTERED['lags']), set(rc.REGISTERED['verdict_suffix']))
        names = {p.split('/')[1] for p in rc.REGISTERED['verdict_paths']}
        self.assertEqual(names, {n + rc.REGISTERED['verdict_suffix'][lag] for n in ('JL12', 'JEH12', 'JER12')
                                 for lag in rc.REGISTERED['lags']})
        src = (HERE / 'r12_compute.py').read_text()
        self.assertNotIn("('own', 'k1')", src)
        for key in rc.REGISTERED:      # every key of the block is read somewhere in the code
            self.assertGreaterEqual(src.count(f"REGISTERED['{key}']"), 1, key)

    def test_expected_records_and_lags(self):
        self.assertEqual(rc.expected_release10('cost', 8)['seller_epoch_k'], 8)
        self.assertEqual(rc.expected_release10('bridge', 1)['seller_epoch_k'], 1)
        cost = rc.expected_release10('cost', 1)
        self.assertEqual([rc.lag_of(cost, k) for k in rc.REGISTERED['ks']],
                         [2251, 2551, 3151, 4351, 6751, 11551])
        self.assertEqual(rc.lag_of(rc.expected_release10('bridge', 1), 1), 2371)
        self.assertEqual(rc.replay_flags('cost')[-6:], ['--r10-vrf-response', '10', '--r10-vrf-slack', '20',
                                                          '--r10-bind-window', '1800'])
        self.assertNotIn('--r10-vrf-response', rc.replay_flags('bridge'))

    def test_bridge_record_is_the_r11_main_setting(self):
        import r11_compute as r11
        self.assertTrue(rc.compare_record(dict(r11.BASE), rc.expected_release10('bridge', 1))['ok'])

    def test_release_cost(self):
        want = 114624 * 0.010e-9 * 2401.44 + 945606403.8667e-18 * 2401.44
        self.assertAlmostEqual(rc.release_cost_usd(), want, places=12)


# ---------------------------------------------------------------- pieces against brute force

class Pieces(unittest.TestCase):
    def test_exact_sum(self):
        rng = np.random.default_rng(1)
        a = rng.integers(0, 2 ** 62, size=5000, dtype=np.int64)
        self.assertEqual(rc.exact_sum(a), sum(int(x) for x in a))
        self.assertEqual(rc.exact_sum(np.zeros(0, dtype=np.int64)), 0)
        with self.assertRaises(ValueError):
            rc.exact_sum(np.array([-1]))

    def test_history_caps(self):
        daily = {-14: 5, -3: 7, 0: 2, 1: 9, 15: 1}
        caps, prior = rc.history_caps(daily, 17)
        self.assertEqual(prior, 7)
        self.assertEqual(caps[0], 7)            # days -14 .. -1
        self.assertEqual(caps[1], 7)            # days -13 .. 0
        self.assertEqual(caps[2], 9)
        self.assertEqual(caps[11], 9)           # day -3 left, day 1 still in
        self.assertEqual(caps[15], 9)           # days 1 .. 14
        self.assertEqual(caps[16], 1)           # days 2 .. 15
        self.assertEqual(rc.history_caps({}, 3), ([0, 0, 0], 0))

    def test_prior_coverage(self):
        t0 = 86_400 * 1000 + 1
        meta = dict(first_block=1_000_000, first_time=t0)
        dates = [rc.date_of(t0 - 86_400 * (14 - i)) for i in range(14)]
        good = dict(first_block=1_000_000 - 14 * 43_200, last_block=1_000_000 - 3, rows=10, dates=dates)
        ok, d = rc.prior_coverage(good, meta)
        self.assertTrue(ok)
        self.assertEqual(d['gap_blocks'], 2)                    # last row two blocks short of the window: fine
        self.assertFalse(rc.prior_coverage(dict(good, dates=dates[:5] + dates[6:]), meta)[0])    # a missing day
        self.assertFalse(rc.prior_coverage(dict(good, dates=dates[1:]), meta)[0])
        self.assertFalse(rc.prior_coverage(dict(good, last_block=1_000_000), meta)[0])
        self.assertFalse(rc.prior_coverage(dict(good, first_block=1_000_000 - 14 * 43_200 - 1), meta)[0])
        spec = dict(rows=10, first_date=dates[0], last_date=dates[-1])
        self.assertTrue(rc.prior_coverage(good, meta, spec)[0])
        self.assertFalse(rc.prior_coverage(good, meta, dict(spec, rows=11))[0])

    def test_compare_csv_columns(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / 'a.csv', Path(d) / 'b.csv'
            a.write_text('address,n,x,t\n0xa,3,0.1,u\n')
            b.write_text('address,n,x,t\n0xa,3,0.10000000000000001,u\n')
            self.assertTrue(rc.compare_csv_columns(a, b)['ok'])
            b.write_text('address,n,x,t\n0xa,4,0.1,u\n')
            self.assertFalse(rc.compare_csv_columns(a, b)['ok'])
            b.write_text('address,n,x,t\n0xa,3,0.1000001,u\n')
            self.assertFalse(rc.compare_csv_columns(a, b)['ok'])
            b.write_text('address,n,y,t\n0xa,3,0.1,u\n')
            self.assertFalse(rc.compare_csv_columns(a, b)['ok'])

    def test_k_cost_is_exact(self):
        c = dict(NE=3, Ifull=10 ** 6)
        self.assertIsInstance(rc.k_cost(c), Fraction)
        self.assertEqual(rc.k_cost(c), 3 * rc.release_cost_exact() + rc.capital_per_block_exact())

    def test_lower_median(self):
        self.assertEqual(rc.lower_median([4, 1, 3, 2]), 2)
        self.assertEqual(rc.lower_median([5, 1, 3]), 3)
        self.assertIsNone(rc.lower_median([]))

    def brute_admit(self, blocks, values, L, cap, scale):
        keep = []
        for j in range(len(blocks)):
            tot = sum(values[m] for m in range(j) if keep[m] and blocks[j] - L < blocks[m] <= blocks[j])
            keep.append(scale * (tot + values[j]) <= cap)
        return keep

    def test_rate_cap_admission(self):
        rng = random.Random(3)
        for _ in range(30):
            n = rng.randrange(1, 60)
            blocks = sorted(rng.randrange(0, 400) for _ in range(n))
            values = [rng.choice((0, 5, 10, 40)) for _ in range(n)]
            L = rng.choice((1, 7, 50, 300))
            cap = rng.randrange(0, 2000)
            got = rc.admit_rate_cap(np.array(blocks, dtype=np.int64), np.array(values, dtype=np.int64), L, cap, 3)
            self.assertEqual(got.tolist(), self.brute_admit(blocks, values, L, cap, 3))

    def test_window_exposure_brute(self):
        first = 10_000
        win = rc.Window(first, first + 31_073 + 499, 86_400 * 100 + 86_390)   # the day turns after 5 blocks
        self.assertEqual(win.n_days, 2)
        self.assertEqual(int(win.day[4]), 0)
        self.assertEqual(int(win.day[5]), 1)
        rng = random.Random(5)
        blocks = np.array(sorted(first + rng.randrange(win.N) for _ in range(300)), dtype=np.int64)
        values = np.array([rng.choice((1, 2, 3, 50)) for _ in blocks], dtype=np.int64)
        caps = [4, 11]
        out = rc.address_bonds(win, blocks, values, caps, 6, 2 * 2 * 6, 40, win.N, 1000, int(values.sum()))
        sH = sRu = sM = mH = 0
        for t in range(win.first + win.a0, win.last + 1):
            E = int(values[(blocks > t - 40) & (blocks <= t)].sum())
            d = int(win.day[t - win.first])
            uh = max(0, 86_400 * E - 2 * 2 * caps[d] * 40)
            sH += uh
            mH = max(mH, uh)
            sRu += max(0, 86_400 * E - 24 * 40)
            sM += max(0, win.N * E - (1000 * win.N + int(values.sum()) * 40))
        self.assertEqual(out['Usum_H'], sH)
        self.assertEqual(out['X_H'], mH)
        self.assertEqual(out['Usum_Ru'], sRu)
        self.assertEqual(out['Usum_M'], sM)
        self.assertEqual(out['X_Rr'], 0)
        self.assertEqual(out['Usum_Rr'], 0)

    def test_union_length(self):
        rng = random.Random(7)
        for _ in range(50):
            n = rng.randrange(0, 30)
            s = [rng.randrange(0, 100) for _ in range(n)]
            e = [x + rng.randrange(0, 40) for x in s]
            lo, hi = rng.randrange(0, 50), rng.randrange(50, 140)
            want = len({t for a, b in zip(s, e) for t in range(a, b) if lo <= t <= hi})
            self.assertEqual(rc.union_length(np.array(s, dtype=np.int64), np.array(e, dtype=np.int64), lo, hi), want)

    def test_interval_numerators(self):
        s = np.array([0, 5, 10], dtype=np.int64)
        e = np.array([20, 6, 10], dtype=np.int64)
        w = np.array([2, 3, 7], dtype=np.int64)
        idx = np.array([0, 1, 1], dtype=np.int64)
        out = rc.interval_numerators(s, e, w, idx, 2, 4, 12)
        self.assertEqual(out.tolist(), [2 * 9, 3 * 1])

    def test_choose_k_ties_to_smaller(self):
        cells = {k: dict(NE=0, Ifull=0) for k in rc.REGISTERED['ks']}
        self.assertEqual(rc.choose_k(cells), 1)
        cells = {k: dict(NE=1000 // k, Ifull=10 ** 6 * k) for k in rc.REGISTERED['ks']}
        c_rel = rc.release_cost_usd()
        per_block = 0.10 * 2 / 31_536_000
        want = min(rc.REGISTERED['ks'], key=lambda k: (c_rel * (1000 // k) + per_block * k, k))
        self.assertEqual(rc.choose_k(cells), want)


# ---------------------------------------------------------------- end to end on the synthetic list

def retime(s, first_time):
    """Rewrites the synthetic list so that its first row is at `first_time` (2-second blocks), updates the
    registered hash in the conditions file."""
    import inputs
    import test_replay as tr
    with open(s['csv'], newline='') as f:
        rows = list(csv.reader(f))
    first = int(rows[1][0])
    for r in rows[1:]:
        r[1] = tr._fmt(first_time + 2 * (int(r[0]) - first))
    with open(s['csv'], 'w', newline='') as f:
        csv.writer(f, lineterminator='\n').writerows(rows)
    cond = json.loads(Path(s['conditions']).read_text())
    cond['inputs']['replay_period']['sha256'] = inputs.sha256_file(s['csv'])
    Path(s['conditions']).write_text(json.dumps(cond, indent=1))
    return first


def write_prior(path, first_block, first_time, addrs, seed=11, end_gap=0):
    """14 days of synthetic sales before block first_block, for the first 300 addresses only, one row on every day.
    With end_gap > 0 the last row is end_gap blocks before first_block - 1 (the busy window of the real data has no
    settlement in the last two blocks before the window)."""
    import test_replay as tr
    rng = random.Random(seed)
    last = first_block - 1 - end_gap
    recs = []
    for i, a in enumerate(addrs[:300]):
        for _ in range(rng.randrange(0, 5)):
            recs.append((last - rng.randrange(PRIOR_BLOCKS - end_gap), a))
    recs += [(first_block - PRIOR_BLOCKS + 43_200 * d + 7, addrs[1]) for d in range(14)]
    recs.sort()
    recs = [(first_block - PRIOR_BLOCKS, addrs[0])] + recs + [(last, addrs[0])]
    with open(path, 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        w.writerow(tr.COLUMNS)
        for n, (b, a) in enumerate(recs):
            w.writerow([b, tr._fmt(first_time - 2 * (first_block - b)), f'0x{n:064x}', 0, '', a,
                        f'0x{1:040x}', rng.choice((1000, 10000, 50000)), tr.FACILITATORS[0]])


def synthetic_end_to_end(work, reg_path=None):
    """Synthetic list, prior list, replays for every registered k and the bridge, then compute. Returns the
    results dict. The aggregation reads a synthetic registration carrying the code's block (with the synthetic
    address count); the real registration is checked by the caller (`selfcheck`)."""
    import r11_k_sweep
    import replay
    import test_replay as tr
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    s = tr.synthetic(work)
    first_time = 1_757_289_601                       # 2025-09-08 00:00:01 UTC: the previous block is on 09-07
    first = retime(s, first_time)
    addrs = sorted({r['recipient'].lower() for r in _dict_rows(s['csv'])})
    raw, lists = work / 'raw', work / 'lists'
    old_git = replay.git_state
    replay.git_state = lambda: dict(revision='0' * 40, dirty=False)
    try:
        for w in rc.REGISTERED['windows']:
            ld = lists / Path(rc.REGISTERED['lists'][w]['file']).parent
            ld.mkdir(parents=True, exist_ok=True)
            (lists / rc.REGISTERED['lists'][w]['file']).write_bytes(Path(s['csv']).read_bytes())
            write_prior(lists / rc.REGISTERED['prior_lists'][w]['file'], first, first_time, addrs,
                        end_gap=2 if w == 'busy' else 0)
            base = ['--settlements', str(s['csv']), '--conditions-file', str(s['conditions']),
                    '--reference-dir', str(s['dir']), '--d2-config', str(HERE / 'design2.json')]
            for kind in ('cost', 'bridge'):
                flags = rc.replay_flags(kind)                # exactly the registered flags (S1)
                ks = rc.REGISTERED['ks'] if kind == 'cost' else [1]
                out = raw / Path(rc.REGISTERED['run_dirs'][kind].format(window=w, k=1)).parent
                with tr.redirect_stdout(tr.io.StringIO()), tr.redirect_stderr(tr.io.StringIO()):
                    r11_k_sweep.main(['--k', ','.join(map(str, ks)), '--out', str(out), '--'] + base + flags)
    finally:
        replay.git_state = old_git
    bexp = {}
    for w in rc.REGISTERED['windows']:
        c = raw / rc.REGISTERED['run_dirs']['bridge'].format(window=w) / 'condition-01-seed-0'
        bexp[w] = dict(addresses_observed_sha256=rc.sha256(c / 'addresses_observed.csv'),
                       sales_npz_sha256=rc.sha256(c / 'sales.npz'))
    n_addr = len(json.loads((raw / rc.REGISTERED['run_dirs']['cost'].format(window='median', k=1)
                             / 'condition-01-seed-0' / 'sales_addresses.json').read_text()))
    old_n = rc.REGISTERED['addresses']
    rc.REGISTERED['addresses'] = n_addr
    try:
        R = rc.compute(_synthetic_reg(work, n_addr), raw, lists, None, work / 'out', '0' * 40, stored_loader=None, check_hashes=False,
                       bridge_expect=bexp)
    finally:
        rc.REGISTERED['addresses'] = old_n
    return R


def _synthetic_reg(work, n_addr):
    block = copy.deepcopy(rc.REGISTERED)
    block['addresses'] = n_addr
    p = Path(work) / 'R12_synthetic_n.md'
    p.write_text(registration_text(block))
    return p


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        cls.R = synthetic_end_to_end(cls.work)
        cls.out = cls.work / 'out'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_reportable_and_paths(self):
        for w in rc.REGISTERED['windows']:
            W = self.R['windows'][w]
            self.assertEqual(W['problems'], [], w)
            self.assertTrue(W['reportable'])
            self.assertTrue(W['bridge']['equal'])
            self.assertEqual(W['list_date_mismatches'], 0)
            self.assertTrue(W['prior_coverage']['dates_ok'])
        for p in rc.REGISTERED['verdict_paths']:
            self.assertIn(rc.get_path(self.R, p), (True, False))
        for name in rc.REGISTERED['outputs']:
            self.assertTrue((self.out / name).exists(), name)

    def test_lag_keys_and_prior_gap(self):
        for w in rc.REGISTERED['windows']:
            self.assertEqual(set(self.R['windows'][w]['lag']), set(rc.REGISTERED['lags']))
        self.assertEqual(self.R['windows']['busy']['prior_coverage']['gap_blocks'], 2)
        self.assertEqual(self.R['windows']['median']['prior_coverage']['gap_blocks'], 0)
        self.assertTrue(self.R['windows']['busy']['reportable'])

    def test_run_record_and_epoch_checks(self):
        run_dir = self.work / 'raw' / rc.REGISTERED['run_dirs']['cost'].format(window='median', k=2)
        old = dict(rc.REGISTERED['run_record'])
        try:
            rc.REGISTERED['run_record']['meta/design2/vmax_atomic'] = 200_000
            _, p = rc.load_run(run_dir, rc.expected_release10('cost', 2), '0' * 40, None)
            self.assertTrue(any('vmax_atomic' in x for x in p))
        finally:
            rc.REGISTERED['run_record'].clear()
            rc.REGISTERED['run_record'].update(old)
        run, p = rc.load_run(run_dir, rc.expected_release10('cost', 2), '0' * 40, None)
        self.assertEqual(p, [])
        old_e = rc.REGISTERED['epoch_blocks']
        try:
            rc.REGISTERED['epoch_blocks'] = 600
            _, p = rc.fairbind_cells(run, 2)
            self.assertTrue(any('epoch' in x for x in p))
        finally:
            rc.REGISTERED['epoch_blocks'] = old_e

    def test_a_changed_record_is_caught(self):
        run_dir = self.work / 'raw' / rc.REGISTERED['run_dirs']['cost'].format(window='median', k=2)
        _, p = rc.load_run(run_dir, rc.expected_release10('cost', 2), '0' * 40, None)
        self.assertEqual(p, [])
        _, p = rc.load_run(run_dir, rc.expected_release10('cost', 4), '0' * 40, None)
        self.assertTrue(any('G3' in x for x in p))
        bad = {k: v for k, v in rc.expected_release10('cost', 2).items() if k != 'dispute_from'}
        _, p = rc.load_run(run_dir, bad, '0' * 40, None)
        self.assertTrue(any('G3' in x for x in p))

    def test_fairbind_numerators_brute(self):
        w = 'busy'
        rows = {r['address']: r for r in _dict_rows(self.out / f'r12_addr_{w}.csv')}
        W = self.R['windows'][w]
        lo, hi = W['first_block'] + rc.REGISTERED['avg_offset_blocks'], W['last_block']
        for k in (1, 8, 32):
            c = self.work / 'raw' / rc.REGISTERED['run_dirs']['cost'].format(window=w, k=k) / 'condition-01-seed-0'
            z = np.load(c / 'sales.npz')
            addrs = json.loads((c / 'sales_addresses.json').read_text())
            for i in range(0, len(addrs), 37):
                m = z['address_index'] == i
                b, v, rl = z['block'][m].tolist(), z['value'][m].tolist(), z['release'][m].tolist()
                H = sum(x * max(0, min(r, hi + 1) - max(s, lo)) for s, x, r in zip(b, v, rl))
                O = sum(max(0, min(r, hi + 1) - max(s, lo)) for s, r in zip(b, rl))
                NE = len({((s - W['first_block']) // 300) // k for s in b})
                self.assertEqual(int(rows[addrs[i]][f'Hnum_k{k}']), H)
                self.assertEqual(int(rows[addrs[i]][f'Onum_k{k}']), O)
                self.assertEqual(int(rows[addrs[i]][f'NE_k{k}']), NE)

    def test_k_chain_and_kstar(self):
        rows = list(_dict_rows(self.out / 'r12_addr_median.csv'))
        ks = rc.REGISTERED['ks']
        for r in rows:
            vals = [int(r[f'Ifull_k{k}']) for k in ks]
            self.assertEqual(vals, sorted(vals))
            cells = {k: dict(NE=int(r[f'NE_k{k}']), Ifull=int(r[f'Ifull_k{k}'])) for k in ks}
            self.assertEqual(int(r['k_star']), rc.choose_k(cells))
            self.assertEqual(int(r['L_own']), rc.lag_of(rc.expected_release10('cost', 1), int(r['k_star'])))

    def test_comparators_brute(self):
        w = 'median'
        W = self.R['windows'][w]
        rows = {r['address']: r for r in _dict_rows(self.out / f'r12_addr_{w}.csv')}
        lst = list(_dict_rows(self.work / 'lists' / rc.REGISTERED['lists'][w]['file']))
        pri = list(_dict_rows(self.work / 'lists' / rc.REGISTERED['prior_lists'][w]['file']))
        t0 = rc.utc_seconds(lst[0]['block_time_utc'])
        day0 = t0 // 86400
        lo, hi = W['first_block'] + rc.REGISTERED['avg_offset_blocks'], W['last_block']
        checked = 0
        for a in list(rows)[::29]:
            daily = {}
            for r in pri + lst:
                if r['recipient'].lower() == a:
                    d = rc.utc_seconds(r['block_time_utc']) // 86400 - day0
                    daily[d] = daily.get(d, 0) + int(r['value_atomic'])
            prior = max([daily.get(d, 0) for d in range(-14, 0)])
            self.assertEqual(int(rows[a]['C_prior']), prior)
            sales = [(int(r['block_number']), int(r['value_atomic'])) for r in lst if r['recipient'].lower() == a]
            L = int(rows[a]['L_own'])
            rho2 = int(rows[a]['rho2'])
            XH = XR = 0
            for t in range(lo, hi + 1, 97):          # a sample of blocks bounds the stored maxima from below
                E = sum(v for b, v in sales if t - L < b <= t)
                d = (t0 + 2 * (t - W['first_block'])) // 86400 - day0
                cap = max([daily.get(x, 0) for x in range(d - 14, d)])
                XH = max(XH, 86_400 * E - 2 * 2 * cap * L)
                XR = max(XR, 86_400 * E - rho2 * L)
            self.assertGreaterEqual(int(rows[a]['X_H_own']), XH)
            self.assertGreaterEqual(int(rows[a]['X_Ru_own']), XR)
            # the rejecting variant against the brute admission
            keep = Pieces().brute_admit([b for b, _ in sales], [v for _, v in sales], L, rho2 * L, 86_400)
            self.assertEqual(int(rows[a]['rej_value_Rr_own']), sum(v for (b, v), k in zip(sales, keep) if not k))
            checked += 1
        self.assertGreater(checked, 5)
        # rho_0 is the lower median of the declared rates with a history
        decl = sorted(2 * 2 * int(r['C_prior']) for r in rows.values() if int(r['C_prior']) > 0)
        self.assertEqual(W['rho2_0'], decl[(len(decl) - 1) // 2])
        no_prior = [r for r in rows.values() if int(r['C_prior']) == 0]
        self.assertTrue(no_prior)
        self.assertTrue(all(int(r['rho2']) == W['rho2_0'] for r in no_prior))

    def test_set_sums_match_address_file(self):
        w = 'busy'
        W = self.R['windows'][w]
        rows = list(_dict_rows(self.out / f'r12_addr_{w}.csv'))
        S = [r for r in rows if r['in_S1r'] == '1']
        c = W['lag']['own']['S1r']
        self.assertEqual(c['n'], len(S))
        self.assertAlmostEqual(c['X_sum_H'], sum(int(r['X_H_own']) for r in S) / 86_400 / 1e6, places=9)
        held = sum(int(r[f"Hnum_k{r['k_star']}"]) for r in S) / W['n_avg'] / 1e6
        self.assertAlmostEqual(c['held'], held, places=9)
        CM = sum(Fraction(rc.REGISTERED['b_atomic'] * W['rate_blocks'] + int(r['revenue']) * int(r['L_own']),
                          W['rate_blocks']) for r in S) / 10 ** 6
        self.assertAlmostEqual(c['sumC_M'], float(CM), places=9)
        self.assertAlmostEqual(c['FB_bound'], len(S) * rc.REGISTERED['V_atomic'] / 1e6)

    def test_verdict_rules(self):
        v = rc.verdicts(self.R)
        for w in rc.REGISTERED['windows']:
            c = self.R['windows'][w]['lag']['own']['S1r']
            self.assertEqual(v['JL12']['values'][w], c['ratio_LFB_CM'])
        self.assertEqual(v['JEH12']['holds'], all(self.R['windows'][w]['lag']['own']['S1r']['X_sum_H']
                                                  > self.R['windows'][w]['lag']['own']['S1r']['FB_bound']
                                                  for w in rc.REGISTERED['windows']))
        for w in rc.REGISTERED['windows']:
            c = self.R['windows'][w]['lag']['k1']['S1r']
            self.assertEqual(v['JL12d']['values'][w], c['ratio_LFB_CM'])
            self.assertEqual(v['JER12d']['values'][w], [c['X_sum_Ru'], c['FB_bound']])
        self.assertEqual(sorted(v), sorted(p.split('/')[1] for p in rc.REGISTERED['verdict_paths']))
        c = self.R['windows']['median']['lag']['own']['S1r']
        self.assertEqual(c['X_sum_H_scaled'] > c['FB_bound_scaled'], c['X_sum_H'] > c['FB_bound'])
        rv = self.R['windows']['median']['reserve_vs_seller']['S1r']
        self.assertEqual(rv['n'], c['n'])


if __name__ == '__main__':
    unittest.main()
