"""Conditions, injection consistency, folds, input checks and determinism of the replay,
on synthetic settlement lists."""
import csv
import hashlib
import io
import json
import math
import os
import random
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import engine  # noqa: E402
import injection as inj  # noqa: E402
import inputs  # noqa: E402
import replay  # noqa: E402
import bucket as bucket_mod  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402

ROOT = HERE.parents[1]
PROFILE_FILE = ROOT / 'profiles' / 'local-evaluation-v1.json'
REPLAY_PROFILE_FILE = ROOT / 'experiments' / 'replay' / 'replay-profile-v1.json'
COLUMNS = ['block_number', 'block_time_utc', 'tx_hash', 'tx_index', 'trace_address', 'recipient', 'payer',
           'value_atomic', 'facilitator']
FACILITATORS = [f'0x{i:040x}' for i in range(1, 3)]
T0 = 1_757_289_603  # 2025-09-08 00:00:03 UTC, only a base for the synthetic clock


def addr(i):
    return f'0x{0xa000 + i:040x}'


def synthetic(dirpath, *, rows_per_top=(3000, 1500, 400), span=200_000, seed=1, first_block=1_000_000):
    """Writes a settlement list, a 400-address top list, an all-address list, a facilitator file
    and a conditions file that registers them. Returns the paths."""
    rng = random.Random(seed)
    d = Path(dirpath)
    counts = {}
    records = []
    for i in range(420):
        n = rows_per_top[i] if i < len(rows_per_top) else (rng.randrange(0, 6) if i < 400 else rng.randrange(1, 4))
        for _ in range(n):
            # Bursts: a third of the heavy address's rows land in a few blocks.
            if i == 0 and rng.random() < 0.3:
                b = first_block + rng.choice((5_000, 90_000, 150_000))
            else:
                b = first_block + rng.randrange(span)
            records.append((b, i))
        counts[addr(i)] = n
    records.sort()
    lines = io.StringIO()
    w = csv.writer(lines, lineterminator='\n')
    w.writerow(COLUMNS)
    tx_index = {}
    for n, (b, i) in enumerate(records):
        tx_index[b] = tx_index.get(b, -1) + 1
        t = T0 + 2 * (b - records[0][0])
        w.writerow([b, _fmt(t), f'0x{n:064x}', tx_index[b], '', addr(i), f'0x{rng.randrange(50):040x}',
                    rng.choice((1000, 10000, 50000)), FACILITATORS[n % 2]])
    csv_path = d / 'settlements.csv'
    csv_path.write_text(lines.getvalue(), encoding='ascii')
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top = ranked[:400]
    with open(d / 'top400.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['seller_id', 'settlements'])
        w.writerows(top)
    with open(d / 'all.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['recipient', 'settlements'])
        w.writerows([kv for kv in ranked if kv[1] > 0])
    with open(d / 'facilitators.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['facilitator', 'calls'])
        for fac in FACILITATORS:
            w.writerow([fac, sum(1 for n in range(len(records)) if FACILITATORS[n % 2] == fac)])
    cond = json.loads(inputs.CONDITIONS_PATH.read_text())
    rp = cond['inputs']['replay_period']
    rp.update(file_name='settlements.csv', sha256=inputs.sha256_file(csv_path), rows=len(records),
              first_block=records[0][0], last_block=records[-1][0])
    cond['inputs']['expected_total'] = len(records)
    cond['inputs']['top400'].update(file_name='top400.csv', sha256=inputs.sha256_file(d / 'top400.csv'))
    cond['inputs']['all_addresses'].update(file_name='all.csv', sha256=inputs.sha256_file(d / 'all.csv'))
    cond['inputs']['facilitators'] = dict(count=2, sha256_sorted_joined_no_trailing_newline=hashlib.sha256(
        '\n'.join(sorted(FACILITATORS)).encode()).hexdigest())
    # Register what the synthetic list gives: its span as the rate denominator, its scales and its
    # group hashes, so that a run on it can be reportable.
    cond['rate_blocks'] = records[-1][0] - records[0][0] + 1
    data = prof.load_profile(REPLAY_PROFILE_FILE, cond['expected_scales']['profile'])['parameters']
    top_counts = [(a.lower(), n) for a, n in top]
    for rule in ('nF', 'nR'):
        cond['expected_scales'][rule] = {a: n for a, n in replay.scales(top_counts, rule, data,
                                                                         cond['rate_blocks']).items() if n != 1}
    _, hashes, _ = inputs.groups(top_counts, [(a.lower(), n) for a, n in ranked if n > 0], cond)
    for name, h in hashes.items():
        cond['groups'][name]['sha256'] = h['sha256']
    (d / 'conditions.json').write_text(json.dumps(cond, indent=1))
    return dict(csv=csv_path, conditions=d / 'conditions.json', dir=d, rows=len(records), counts=counts,
                span=cond['rate_blocks'])


def _fmt(t):
    import time
    return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(t))


def _open(path):
    return io.StringIO(Path(path).read_text())


def run_cli(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = replay.main(argv)
    return code, out.getvalue()


class Conditions(unittest.TestCase):
    def setUp(self):
        self.cond = inputs.load_conditions()
        self.op = opt.load()
        self.data = prof.load_profile(PROFILE_FILE, 'data-api-fast-v1')['parameters']

    def test_ten_conditions_in_order(self):
        rows = [(c['id'], c['profile'], c['scale_rule'], c['q'], c['seeds']) for c in self.cond['conditions']]
        base = [('nF', 'qX', 3), ('n1', 'qX', 1), ('nF', 'q20', 1), ('nR', 'qX', 1), ('n1', 'q20', 1)]
        want = [(i + 1, 'data-api-fast-v1', *base[i]) for i in range(5)]
        want += [(i + 6, 'open-weights-standard-v1', r, q, 1) for i, (r, q, _) in enumerate(base)]
        self.assertEqual(rows, want)
        # The secondary rule nR is paired with qX only.
        self.assertEqual({c['q'] for c in self.cond['conditions'] if c['scale_rule'] == 'nR'}, {'qX'})

    def test_scale_rules_reproduce_the_precomputed_scales(self):
        top = [('a', 187_070), ('b', 170_689), ('c', 35_880), ('d', 30_000), ('e', 1)]
        nf = replay.scales(top, 'nF', self.data, 604_800)
        nr = replay.scales(top, 'nR', self.data, 604_800)
        self.assertEqual([nf[x] for x in 'abcde'], [7, 6, 2, 1, 1])
        self.assertEqual([nr[x] for x in 'abcde'], [6, 5, 1, 1, 1])
        self.assertEqual(set(replay.scales(top, 'n1', self.data, 604_800).values()), {1})

    def test_injection_settings(self):
        s = {x['name']: x for x in replay.settings_for(self.op, 'data-api-fast-v1', self.cond)}
        self.assertAlmostEqual(s['main']['w1'], 0.0397, places=10)
        self.assertAlmostEqual(s['main']['w'], 0.00472827, places=8)
        self.assertAlmostEqual(s['collusion_worst']['w1'], 0.3367, places=10)
        self.assertAlmostEqual(s['collusion_worst']['w'], 0.3401, places=4)
        self.assertAlmostEqual(s['operator_is_verifier']['w1'], 0.01, places=12)
        self.assertAlmostEqual(s['operator_is_verifier']['w'], 0.0003, places=12)
        extra = replay.settings_for(self.op, 'data-api-fast-v1', self.cond, alpha_upper=0.02)
        self.assertEqual(extra[-1]['name'], 'alpha_upper')

    def test_confirm_delay_is_judgment_delay_less_open_horizon(self):
        for name in ('data-api-fast-v1', 'open-weights-standard-v1'):
            p = prof.load_profile(PROFILE_FILE, name)
            self.assertEqual(replay.confirm_delay(p['parameters']),
                             prof.judgment_delay(p) - prof.open_horizon(p))
        self.assertEqual(replay.confirm_delay(self.data), 7512)

    def test_values_come_from_the_operating_point_and_profile(self):
        # failureLimit, hold periods and the placeholder capacity are read, not fixed in code.
        src = (HERE / 'replay.py').read_text() + (HERE / 'engine.py').read_text()
        for literal in ('60000', '132000', '60_000', '132_000', ' 16,', ' 27,', ' 23,', ' 37,', ' 45,', '619111',
                        '619_111', '13700', '13_700'):
            self.assertNotIn(literal, src)

    def test_case_opening_follows_the_anchor_deadline(self):
        p = self.data
        # Epoch 0: anchor base = origin + 2E - 1, deadline + 1 + beaconDelay is the beacon block.
        want = p['epochOrigin'] + 2 * p['epochBlocks'] - 1 + p['deadlineConfig']['anchorBlocks'] + 1 \
            + p['beaconDelayBlocks'] + 1
        self.assertEqual(engine.case_open_block(0, p), want)
        # The opening lies within the profile's open horizon from the start of the epoch.
        o = {'parameters': p}
        self.assertLessEqual(engine.case_open_block(0, p) - p['epochOrigin'], prof.open_horizon(o))


class InjectionConsistency(unittest.TestCase):
    def test_array_model_matches_seller_loss(self):
        rng = random.Random(11)
        for trial in range(40):
            n = rng.randrange(1, 400)
            blocks = np.array(sorted(rng.randrange(0, 5000) for _ in range(n)), dtype=np.int64)
            values = np.array([rng.randrange(1, 9) for _ in range(n)], dtype=np.int64)
            f = np.array(sorted(rng.randrange(0, 5200) for _ in range(rng.randrange(0, 12))), dtype=np.int64)
            hold = rng.choice((50, 300, 1000))
            for reentry in (0, 3, 60):
                ref = inj.seller_loss(list(zip(blocks.tolist(), values.tolist())), f.tolist(), hold, 7, reentry)
                got = engine.evaluate_failures(blocks, values, f, hold=hold, reentry=reentry, claim_probs=[1],
                                               share=7, rng=None, start=0, end=6000,
                                               fw_edges=np.array([0, 3000, 6000]), claim_window=hold)[0]
                self.assertEqual(got['principal'], ref['principal_loss'], (trial, reentry))
                self.assertEqual(got['lost_sales'], ref['lost_sales'])
                self.assertEqual(got['revenue'], ref['revenue'])
                self.assertEqual(got['penalty'], ref['penalty_loss'])
                self.assertEqual(got['refunded'] + got['forfeited'], got['principal'])
                self.assertEqual(int(np.sum(got['fw_loss'])), ref['principal_loss'] + 7 * len(f))

    def test_claim_probability_splits_principal(self):
        blocks = np.arange(1, 2001, dtype=np.int64)
        values = np.ones(2000, dtype=np.int64)
        f = np.array([1500], dtype=np.int64)
        r1, r5 = engine.evaluate_failures(blocks, values, f, hold=1000, reentry=0, claim_probs=[1, 0.5], share=0,
                                          rng=np.random.default_rng(1), start=0, end=3000,
                                          fw_edges=np.array([0, 3000]), claim_window=1000)
        self.assertEqual((r1['refunded'], r1['forfeited']), (1000, 0))
        self.assertEqual(r5['refunded'] + r5['forfeited'], 1000)
        self.assertLess(abs(r5['refunded'] - 500), 100)
        # Refund time: from the settle block to the failure block.
        self.assertEqual(r1['refund_time_max'], 1500 - 501)

    def test_union_length(self):
        rng = random.Random(5)
        for _ in range(200):
            starts = np.array(sorted(rng.randrange(0, 300) for _ in range(rng.randrange(0, 8))), dtype=np.int64)
            length, lo, hi = rng.randrange(1, 40), rng.randrange(0, 50), rng.randrange(200, 320)
            brute = len({x for s in starts.tolist() for x in range(s, s + length) if lo <= x <= hi})
            self.assertEqual(engine.union_length(starts, length, lo, hi), brute)

    def test_failure_draw_is_a_pure_function_of_its_seed(self):
        cases = np.arange(0, 10_000, 7, dtype=np.int64)
        a = engine.draw_failures(cases, 0.3, 10, 10**9, engine.draw_rng(1, 'main', '0xabc', 4))
        b = engine.draw_failures(cases, 0.3, 10, 10**9, engine.draw_rng(1, 'main', '0xabc', 4))
        c = engine.draw_failures(cases, 0.3, 10, 10**9, engine.draw_rng(1, 'main', '0xabc', 5))
        self.assertTrue(np.array_equal(a, b))
        self.assertFalse(np.array_equal(a, c))
        self.assertTrue(abs(len(a) / len(cases) - 0.3) < 0.05)
        # Failures after the last block are dropped.
        self.assertEqual(len(engine.draw_failures(cases, 1.0, 10, 100, engine.draw_rng(1, 'm', 'x', 0))),
                         len([x for x in cases if x + 10 <= 100]))


class Sampling(unittest.TestCase):
    def test_threshold_matches_contract_formula(self):
        top = 2**256 - 1
        for ppm in (1, 100_000, 999_999):
            self.assertEqual(engine.probability_threshold(ppm), (top // 10**6) * ppm + ((top % 10**6 + 1) * ppm) // 10**6)
        self.assertEqual(engine.probability_threshold(10**6), top)
        self.assertEqual(engine.probability_threshold(0), 0)

    def test_sample_rate_and_determinism(self):
        rows = np.arange(20_000, dtype=np.int64)
        epochs = rows // 50
        a = engine.sampled('0xabc', epochs, rows, 7, 100_000)
        self.assertTrue(np.array_equal(a, engine.sampled('0xabc', epochs, rows, 7, 100_000)))
        self.assertLess(abs(a.mean() - 0.1), 4 * math.sqrt(0.09 / len(rows)))

    def test_submission_order_is_a_seeded_permutation_within_blocks(self):
        blocks = np.array([5, 5, 5, 6, 7, 7], dtype=np.int64)
        pos = np.array([0, 2, 3, 1, 0, 1], dtype=np.int64)
        sizes = {5: 4, 6: 2, 7: 2}
        o1 = engine.submission_order(blocks, pos, 1, sizes)
        self.assertEqual(sorted(o1.tolist()), list(range(6)))
        self.assertTrue(np.all(np.diff(blocks[o1]) >= 0))
        self.assertTrue(np.array_equal(o1, engine.submission_order(blocks, pos, 1, sizes)))
        orders = {tuple(engine.submission_order(blocks, pos, s, sizes).tolist()) for s in range(40)}
        self.assertGreater(len(orders), 1)


class GroupC(unittest.TestCase):
    def test_closest_addresses_with_tie_breaks(self):
        cond = inputs.load_conditions()
        alla = [(f'0x{i:02x}', c) for i, c in enumerate([1] * 60 + [2] * 20 + [3] * 10 + [9] * 8 + [50, 70])]
        out = inputs.group_c(alla, cond)
        # p50 of the counts is 1: five addresses with one settlement, lowest address strings.
        self.assertEqual(out['p50']['addresses'], ['0x00', '0x01', '0x02', '0x03', '0x04'])
        # p90 is 3: the ten addresses with three settlements come first, by address string.
        self.assertEqual(out['p90']['addresses'], [f'0x{i:02x}' for i in range(80, 85)])
        self.assertEqual(len({a for v in out.values() for a in v['addresses']}), 15)


class Inputs(unittest.TestCase):
    def test_input_check_on_synthetic_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = synthetic(tmp)
            cond = inputs.load_conditions(s['conditions'])
            ref = inputs.load_all_addresses(s['dir'] / 'all.csv')
            top = inputs.load_top400(s['dir'] / 'top400.csv')
            r = inputs.check_input(s['csv'], cond, 'replay_period', reference_per_address=ref, top400=top,
                                   facilitators_path=s['dir'] / 'facilitators.csv')
            self.assertTrue(r['pass'], r)
            self.assertEqual(r['rows'], s['rows'])
            self.assertEqual(r['per_address']['all_reference_difference_sum'], 0)
            self.assertTrue(r['facilitators']['file_counts_match'])
            # Break the list: swap two rows and duplicate one.
            lines = s['csv'].read_text().splitlines()
            lines[5], lines[6] = lines[6], lines[5]
            lines.append(lines[10])
            bad = s['dir'] / 'bad.csv'
            bad.write_text('\n'.join(lines) + '\n')
            r = inputs.check_input(bad, cond, 'replay_period', reference_per_address=ref, top400=top)
            self.assertFalse(r['pass'])
            self.assertFalse(r['sha256_match'])
            self.assertGreaterEqual(r['duplicate_tx_trace'], 1)
            self.assertGreaterEqual(r['order_violations'], 1)

    def test_tolerance_rule(self):
        per = {'a': (1005, 1000), 'b': (10, 9)}
        # Per address: max(1, 0.5 percent); in total: 0.1 percent.
        self.assertTrue(inj.input_check(1009, 1009, per)['within_tolerance'])
        self.assertFalse(inj.input_check(1011, 1009, per)['within_tolerance'])
        per['a'] = (1006, 1000)
        self.assertFalse(inj.input_check(1009, 1009, per)['within_tolerance'])


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.s = synthetic(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def base(self, out, *extra):
        return ['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '4', *extra]

    def test_deterministic_results(self):
        d1, d2 = Path(self.tmp.name) / 'r1', Path(self.tmp.name) / 'r2'
        self.assertEqual(run_cli(self.base(d1, '--conditions', '1,4'))[0], 0)
        self.assertEqual(run_cli(self.base(d2, '--conditions', '1,4', '--jobs', '2'))[0], 0)
        files = sorted(p.relative_to(d1) for p in d1.rglob('*.csv')) + sorted(p.relative_to(d1) for p in d1.rglob('condition.json'))
        self.assertEqual(len([f for f in files if f.name == 'addresses_observed.csv']), 4)
        for f in files:
            self.assertEqual((d1 / f).read_bytes(), (d2 / f).read_bytes(), f)
        env = json.loads((d1 / 'run.json').read_text())
        self.assertFalse(env['reportable'])
        self.assertEqual([(r['condition'], r['repetition']) for r in env['runs']], [(1, 0), (1, 1), (1, 2), (4, 0)])
        # k of the profiles of the conditions run, read from the replay profile.
        self.assertEqual(env['parameters']['k'], {'data-api-fast-v1': prof.load_profile(
            REPLAY_PROFILE_FILE, 'data-api-fast-v1')['parameters']['failureLimit']})
        self.assertEqual(env['parameters']['k'], {'data-api-fast-v1': 27})
        self.assertEqual(env['parameters']['qX'], 137)
        rows = list(csv.DictReader(_open(d1 / 'condition-01-seed-0' / 'addresses_observed.csv')))
        self.assertEqual(len(rows), env['parameters']['replayed_addresses'])
        self.assertGreaterEqual(len(rows), 400)
        self.assertEqual(sum(int(r['attempted_count']) for r in rows),
                         sum(self.s['counts'][r['address']] for r in rows))
        for r in rows:
            self.assertEqual(int(r['attempted_count']), int(r['accepted_count']) + int(r['rejected_count']))
            self.assertEqual(r['H_ledger_list_max_abs_diff'], '0')
        # The bursty address is rejected at the bursts under the placeholder-free qX run too.
        inj_rows = list(csv.DictReader(_open(d1 / 'condition-01-seed-0' / 'addresses_injection.csv')))
        self.assertTrue(all(float(r['principal_over_revenue_max']) <= 1.0 for r in inj_rows))
        self.assertEqual(len({(r['setting'], r['reentry_delay_blocks'], r['claim_probability']) for r in inj_rows}), 12)

    def test_timing_only_writes_no_outcome(self):
        d = Path(self.tmp.name) / 't'
        code, out = run_cli(self.base(d, '--conditions', '2', '--timing-only'))
        self.assertEqual(code, 0)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ['timing.json'])
        env = json.loads((d / 'timing.json').read_text())
        keys = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k not in ('options', 'profile_overrides'):
                        keys.add(k)
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(env)
        walk(json.loads(out))
        for word in ('rejected', 'accepted', 'loss', 'H_', 'sample', 'revenue', 'rejection', 'failure'):
            self.assertFalse([k for k in keys if word in k], word)
        self.assertEqual(set(env['runs'][0]), {'attempted_rows', 'condition', 'peak_memory_mib', 'repetition',
                                               'seed', 'wall_seconds'})
        self.assertFalse(env['reportable'])
        self.assertIn('timing-only pass', env['not_reportable_reasons'])

    def test_folds_split_the_list_and_restart_full(self):
        whole = Path(self.tmp.name) / 'w'
        run_cli(self.base(whole, '--conditions', '2'))
        att = {}
        for fold in ('first', 'second'):
            d = Path(self.tmp.name) / f'f-{fold}'
            self.assertEqual(run_cli(self.base(d, '--conditions', '2', '--fold', fold))[0], 0)
            rows = list(csv.DictReader(_open(d / f'condition-02-fold-{fold}' / 'addresses_observed.csv')))
            att[fold] = {r['address']: int(r['attempted_count']) for r in rows}
            self.assertNotIn('H_max', rows[0])
            env = json.loads((d / 'run.json').read_text())
            self.assertEqual(env['column_source'], {'half': sorted(inj.HALF_REPLAY_COLUMNS)})
        rows = list(csv.DictReader(_open(whole / 'condition-02-seed-0' / 'addresses_observed.csv')))
        for r in rows:
            self.assertEqual(att['first'][r['address']] + att['second'][r['address']], int(r['attempted_count']))

    def test_check_input_command(self):
        code, out = run_cli(['check-input', '--settlements', str(self.s['csv']), '--period', 'replay_period',
                             '--conditions-file', str(self.s['conditions']), '--reference-dir', str(self.s['dir'])])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)['pass'])


class ReplayRun(unittest.TestCase):
    """Design V6: a run restricted to conditions 1-5 can be reportable; the envelope records the
    conditions not run, the design record under both keys, the M1 prediction hash and the profile
    overrides; rates divide by the list span."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.s = synthetic(cls.tmp.name)
        cls.design = Path(cls.tmp.name) / 'design.md'
        cls.design.write_text('# design\n', encoding='utf-8')
        cls.m1 = Path(cls.tmp.name) / 'm1.csv'
        cls.m1.write_text('address,predicted_rejection_rate\n', encoding='ascii')
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)

    @classmethod
    def tearDownClass(cls):
        replay.git_state = cls._git
        cls.tmp.cleanup()

    def run_replay(self, name, conditions, *extra):
        out = Path(self.tmp.name) / name
        code, _ = run_cli(['--settlements', str(self.s['csv']), '--conditions-file', str(self.s['conditions']),
                           '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', '3',
                           '--conditions', conditions, '--design-record', str(self.design), *extra])
        self.assertEqual(code, 0)
        return out, json.loads((out / 'run.json').read_text())

    def test_conditions_one_to_five_are_reportable(self):
        out, env = self.run_replay('five', '1,2,3,4,5', '--m1-predictions', str(self.m1))
        self.assertTrue(env['reportable'], env['not_reportable_reasons'])
        self.assertEqual([c['id'] for c in env['conditions']], [1, 2, 3, 4, 5])
        self.assertEqual([c['id'] for c in env['conditions_not_run']], [6, 7, 8, 9, 10])
        self.assertTrue(all('design 9.2' in c['reason'] for c in env['conditions_not_run']))
        self.assertEqual(env['preregistration'], env['inputs']['design_record'])
        self.assertEqual(env['preregistration']['sha256'], inputs.sha256_file(self.design))
        self.assertEqual(env['inputs']['m1_predictions']['sha256'], inputs.sha256_file(self.m1))
        self.assertEqual(env['parameters']['k'], {'data-api-fast-v1': 27})
        self.assertEqual(env['parameters']['rate_blocks'], self.s['span'])
        over = env['parameters']['profile_overrides']
        self.assertEqual(over['overrides']['data-api-fast-v1'],
                         {'enforcementBlocks': {'base': 10000, 'replay': 13700},
                          'failureLimit': {'base': 16, 'replay': 27}})
        self.assertTrue(over['base_unchanged'])
        self.assertEqual(env['parameters']['profile_capacity_admissible'],
                         {'data-api-fast-v1:qX': True, 'data-api-fast-v1:q20': True})
        self.assertTrue(env['parameters']['options']['window_denominator'].startswith('W344'))
        # Rates over the list span.
        rows = list(csv.DictReader(_open(out / 'condition-01-seed-0' / 'addresses_observed.csv')))
        for r in rows[:20]:
            self.assertAlmostEqual(float(r['rate_acc_per_hour']),
                                   int(r['accepted_count']) / self.s['span'] * engine.HOUR_BLOCKS)
        inj_rows = list(csv.DictReader(_open(out / 'condition-01-seed-0' / 'addresses_injection.csv')))
        acc = {r['address']: int(r['accepted_count']) for r in rows}
        for r in inj_rows[:50]:
            self.assertAlmostEqual(float(r['rate_acc_per_block']), acc[r['address']] / self.s['span'])
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual((meta['replay_blocks'], meta['rate_blocks']), (self.s['span'], self.s['span']))
        # rules.py evaluates the run, including C1 and the settlement-window C2.
        import rules
        res = rules.evaluate([out], conditions_path=self.s['conditions'])
        run = res['runs'][0]
        self.assertEqual(run['conditions_run'], [1, 2, 3, 4, 5])
        self.assertEqual([c['id'] for c in run['conditions_not_run']], [6, 7, 8, 9, 10])
        seed0 = run['seeds'][0]
        self.assertEqual(seed0['R20-C2-windows']['assignment'], ['settlement window'])
        self.assertIn(seed0['R20-C1']['verdict'], ('pass', 'fail: do not use the injection columns'))
        self.assertGreater(seed0['R20-C1']['checked'], 0)
        self.assertEqual(seed0['R20-C3']['verdict'], 'pass')

    def test_other_condition_sets_are_not_reportable(self):
        _, env = self.run_replay('one', '1')
        self.assertFalse(env['reportable'])
        self.assertTrue(any('registered set' in r for r in env['not_reportable_reasons']))
        self.assertEqual([c['id'] for c in env['conditions_not_run']], [2, 3, 4, 5, 6, 7, 8, 9, 10])

    def test_shared_operating_point_is_not_reportable(self):
        _, env = self.run_replay('shared', '1,2,3,4,5', '--operating-point',
                                 str(ROOT / 'experiments' / 'operating-point.json'))
        self.assertFalse(env['reportable'])
        reasons = env['not_reportable_reasons']
        self.assertTrue(any('replay operating point' in r for r in reasons), reasons)
        self.assertTrue(any('failureLimit 16 is not the pre-certification default 27' in r for r in reasons), reasons)
        self.assertEqual(env['parameters']['profile_capacity_admissible']['data-api-fast-v1:qX'], False)

    def test_scale_mismatch_stops_the_run(self):
        cond = json.loads(self.s['conditions'].read_text())
        cond['expected_scales']['nF'] = {addr(0): 9}
        bad = Path(self.tmp.name) / 'bad-conditions.json'
        bad.write_text(json.dumps(cond))
        with self.assertRaises(SystemExit) as ctx:
            run_cli(['--settlements', str(self.s['csv']), '--conditions-file', str(bad), '--reference-dir',
                     str(self.s['dir']), '--qx', '137', '--out', str(Path(self.tmp.name) / 'stop'), '--draws', '1',
                     '--conditions', '1'])
        self.assertIn('scale check failed', str(ctx.exception))


class ReplayProfile(unittest.TestCase):
    """The replay profile and operating point (design 9.1, 9.3)."""

    def setUp(self):
        self.cond = inputs.load_conditions()
        import replay_profile
        self.rp = replay_profile

    def test_committed_files_equal_the_build(self):
        self.assertEqual(self.rp.main([]), 0)
        doc, rop = self.rp.build(self.cond)
        self.assertEqual(json.loads((ROOT / self.cond['replay_profile']['profile_file']).read_text()), doc)
        self.assertEqual(json.loads((ROOT / self.cond['replay_profile']['operating_point']).read_text()), rop)

    def test_only_the_overrides_differ(self):
        base = json.loads(PROFILE_FILE.read_text())
        doc = json.loads(REPLAY_PROFILE_FILE.read_text())
        over = self.cond['replay_profile']['overrides']
        for b, r in zip(base['profiles'], doc['profiles']):
            changed = {k for k in b['parameters'] if b['parameters'][k] != r['parameters'][k]}
            self.assertEqual(changed, set(over[b['name']]), b['name'])
            self.assertEqual(r['parameterHash'], self.rp.parameter_hash(r['parameters']))
            self.assertNotEqual(r['parameterHash'], b['parameterHash'])
            self.assertEqual(b['analysis'], r['analysis'])
        # The shared profile keeps its derived failure limit and enforcement window.
        self.assertEqual([p['parameters']['failureLimit'] for p in base['profiles']], [16, 27])
        self.assertEqual(base['profiles'][0]['parameters']['enforcementBlocks'], 10000)

    def test_failure_limit_is_the_registered_default(self):
        for name, k in self.cond['k_default'].items():
            self.assertEqual(prof.load_profile(REPLAY_PROFILE_FILE, name)['parameters']['failureLimit'], k)
        self.assertEqual(self.cond['k_default'], {'data-api-fast-v1': 27, 'open-weights-standard-v1': 45})
        for name in self.cond['k_default']:
            self.assertEqual(prof.load_profile(REPLAY_PROFILE_FILE, name)['parameters']['sellerPenalty'],
                             prof.load_profile(PROFILE_FILE, name)['parameters']['sellerPenalty'])

    def test_operating_point_agrees_with_the_replay_profile(self):
        op = opt.load(ROOT / self.cond['replay_profile']['operating_point'])
        for name in ('data-api-fast-v1', 'open-weights-standard-v1'):
            self.assertEqual(opt.check(op, prof.load_profile(ROOT / op['profile_file'], name)), [])
        self.assertEqual(replay.default_operating_point(self.cond),
                         str(ROOT / self.cond['replay_profile']['operating_point']))

    def test_enforcement_window_admits_qx(self):
        qx = self.cond['q']['qX']
        data = prof.load_profile(REPLAY_PROFILE_FILE, 'data-api-fast-v1')
        base = prof.load_profile(PROFILE_FILE, 'data-api-fast-v1')
        self.assertTrue(bucket_mod.profile_admits_capacity(data['parameters'], qx))
        self.assertFalse(bucket_mod.profile_admits_capacity(base['parameters'], qx))
        # 13,700 is the least window that admits qX: (r_max - r_fill) * enforcementBlocks = qX.
        smaller = dict(data['parameters'], enforcementBlocks=13_699)
        self.assertFalse(bucket_mod.profile_admits_capacity(smaller, qx))
        # With bucketCapacity = qX the replay profile passes every admission rule of the contract mirror.
        data['parameters']['bucketCapacity'] = qx
        self.assertEqual(prof.admissibility(data), [])


class RateDenominator(unittest.TestCase):
    """W344 (design 9.5): the precomputed scales hold over the list span 619,111 blocks."""

    def test_list_span(self):
        rp = inputs.load_conditions()['inputs']['replay_period']
        self.assertEqual(replay.rate_blocks(inputs.load_conditions()), rp['last_block'] - rp['first_block'] + 1)
        self.assertEqual(replay.rate_blocks(inputs.load_conditions()), 619_111)

    def test_registered_scales_from_the_reference_counts(self):
        cond = inputs.load_conditions()
        data = {'data-api-fast-v1': prof.load_profile(REPLAY_PROFILE_FILE, 'data-api-fast-v1')}
        # Reference counts of the three addresses with a scale above 1 (sellers_dune_top400.csv),
        # and the fourth-ranked count's order of magnitude.
        top = [('0xa9dd7cc9cbf0e05551332209289f04be36bc2315', 187_070),
               ('0x7284d41b5b852f2bd4c99bdf95043d84452d299c', 170_689),
               ('0x5aae638ccd22a4117c0441331e8e86ca979d482e', 35_889), ('0x' + '1' * 40, 30_000)]
        self.assertEqual(replay.check_expected_scales(cond, top, data), [])
        bigger = [(a, n * 2) for a, n in top]
        self.assertEqual(len(replay.check_expected_scales(cond, bigger, data)), 2)
        p = data['data-api-fast-v1']['parameters']
        nf = replay.scales(top, 'nF', p, 619_111)
        self.assertEqual([nf[a] for a, _ in top], [7, 6, 2, 1])
        # Group C does not depend on the denominator.
        alla = [(f'0x{i:02x}', c) for i, c in enumerate([1] * 60 + [2] * 20 + [3] * 10 + [9] * 8 + [50, 70])]
        a = inputs.group_c(alla, dict(cond, rate_blocks=604_800))
        b = inputs.group_c(alla, cond)
        self.assertEqual({k: v['addresses'] for k, v in a.items()}, {k: v['addresses'] for k, v in b.items()})

    def test_group_c_hash_is_registered(self):
        self.assertEqual(inputs.load_conditions()['groups']['C']['sha256'],
                         'ca9f1b8e135094e459b56a511416fd071366eb17a95513cf96311df689ebc4c6')


class SettlementWindows(unittest.TestCase):
    """R20-C2 (design 9.6): a drawn failure carries the settlement block of its case."""

    def test_detail_uses_the_same_draw(self):
        cases = np.arange(1000, 50_000, 13, dtype=np.int64)
        settled = cases - 700
        f1 = engine.draw_failures(cases, 0.2, 5000, 40_000, engine.draw_rng(3, 'main', '0xab', 1))
        f2, s2 = engine.draw_failures_detail(cases, settled, 0.2, 5000, 40_000, engine.draw_rng(3, 'main', '0xab', 1))
        self.assertTrue(np.array_equal(f1, f2))
        # Settlement blocks of every drawn case, including the ones confirmed after the last block.
        self.assertGreater(len(s2), len(f2))
        self.assertTrue(np.array_equal(np.sort(s2 + 700 + 5000)[:len(f2)], f2))

    def test_failures_counted_in_the_settlement_window(self):
        # Ten cases settled in window 0 and opened late enough that every confirmation lands in window 1.
        cases = np.full(10, 950, dtype=np.int64)
        settled = np.arange(900, 910, dtype=np.int64)
        edges = np.array([0, 1000, 2000])
        rng = np.random.default_rng(0)
        f, s = engine.draw_failures_detail(cases, settled, 1.0, 100, 5000, rng)
        self.assertEqual(engine.bin_uniform(f, edges).tolist(), [0, 10])
        self.assertEqual(engine.bin_uniform(s, edges).tolist(), [10, 0])


if __name__ == '__main__':
    unittest.main()
