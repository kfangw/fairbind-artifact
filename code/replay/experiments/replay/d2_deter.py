#!/usr/bin/env python3
"""Deterrence replay: a fraudulent seller injected into the recorded sale columns of the design-2 replay.

    d2_deter.py run --settlements LIST.csv --reference-dir REF --conditions-file COND.json
                    --prereg DET_prereg.md --prereg-hash-file HASH.txt --stored-run DIR --out OUT
                    [--replicates 100] [--jobs 2]
    d2_deter.py analyze --out OUT --prereg ...

Every replayed address is read as a seller whose every received sale is fraudulent. The replay itself
(admission, sampling by value, case opening) is `engine.replay_address`, unchanged, with the configuration of
the main result (Base, v_max 0.2, auto-zero-reject, condition 1, confirmation delay `case`, k-w 0.015). This file
adds only the fraud model on top of what that call returns:

- a sampled case is detected with probability p0 (uniform numbers from `engine.draw_rng(seed, 'deter', a, 0)`,
  one per case in opening order); a detected case is a confirmed failure `confirm_delay` blocks after its opening;
- the account stops at the first confirmed failure f (no failure inside the window: the window end);
- X = value of the sales released before the end of the episode, a sale settled at s is released at s + T_hold
  (released when s + T_hold <= T*, the boundary of `engine.evaluate_failures`).

Variants: p0 = 0.35; amounts replaced by the cap with every sale sampled; confirmation at the settlement of the
sampled sale + L_actual. The rules, settings and seeds are those of the pre-registration (DET_prereg), whose
SHA-256 the script checks before it computes anything. Nothing here changes the replayer or its outputs.
"""
import argparse
import csv
import hashlib
import json
import os
import resource
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import replay  # noqa: E402  (also puts the repository's experiments directory on the path)
import design2  # noqa: E402
import engine  # noqa: E402
import injection as inj  # noqa: E402
import inputs  # noqa: E402
from bucket import PPM  # noqa: E402
from controller.scenario import run_seed  # noqa: E402

ROOT = HERE.parents[1]
REGISTERED = dict(
    prereg_sha256='0c3d1ebb8cc7cfa45efcfd8e2063fbe12424d58f1e6db4c3551533547006c1ce',
    window_list_sha256='091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a',
    prior_list_sha256='5f701f738aae2cbcb935443e1545aa61d470325bcfceff2a2520f06bac2d9486',
    conditions_sha256='5e58da679e9dcf8d04ab0f750d955cde95156a66900b910e614f42840ac56e8c',
    top400_sha256='3f255ef8174bf502cbc1f7d14e6ec84a011f6d5e8599779b11cd04e5c9bcae91',
    all4400_sha256='bb7ee6f57f87b990b665fb65739b1bae32c14cc98b5852b079dd625d9d53b124',
    head='e57bd833dd33e75b71da45ff098c80b41cd9ed3d',
    rows=4539137, first_block=49030927, last_block=49938126,
    confirm_delay=7512, hold=31073, l_actual=30573, vmax=200000, p0_ppm=400000,
    seed_args=(20260928, 'R20', 1))
P0_MAIN, P0_BETA = 0.40, 0.35
UPPER_MAIN = 0.5            # V / p0 = 0.2 / 0.40 USDC
UPPER_BETA_TRUE = 0.2 / 0.35
VARIANTS = ('main', 'p035', 'cap', 'settle')
TIGHTNESS = 0.987
CAP_THEORY = 0.6 * UPPER_MAIN
HOURS = 504


# ---------------------------------------------------------------- the fraud model (pure functions)

def first_failure(open_blocks, detected, delay, end):
    """Block of the first confirmed failure, or None. `open_blocks` are the case opening blocks, `detected`
    the boolean detection of each case, `delay` the confirmation delay; a failure after `end` is dropped."""
    open_blocks = np.asarray(open_blocks)
    detected = np.asarray(detected, dtype=bool)
    if len(open_blocks) == 0 or not detected.any():
        return None
    f = int(open_blocks[detected].min()) + int(delay)
    return f if f <= end else None


def released_value(blocks, values, f, hold, end):
    """X of one episode: total value of the sales with blocks + hold <= T*, T* = f (or the window end without a
    failure). Same boundary as engine.evaluate_failures: settled + hold > f is frozen, equal is released."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    t_star = end if f is None else min(f, end)
    return int(values[blocks + hold <= t_star].sum())


def detections(u, p0):
    return np.asarray(u) < p0


def draw_u(seed, tag, address, n):
    return engine.draw_rng(seed, tag, address, 0).random(n)


def sale_open_blocks(blocks, p, start, local_origin):
    """Case opening ledger block of the epoch of each sale (engine.case_open_block)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    if len(blocks) == 0:
        return np.zeros(0, dtype=np.int64)
    local = blocks - start + local_origin
    epochs = engine.epoch_of(local, p)
    uniq, inv = np.unique(epochs, return_inverse=True)
    open_local = np.array([engine.case_open_block(int(e), p) for e in uniq.tolist()], dtype=np.int64)
    return (open_local - local_origin + start)[inv]


def model_address(arr, *, seed, address, p, start, end, local_origin, delay, hold, l_actual, vmax):
    """The four variants for one address and one replay (`arr` is the second value of engine.replay_address).
    Returns a dict of X in atomic units and the first failure block (-1 for none) per variant."""
    blocks, values = arr['blocks'], arr['values']
    cases, case_settled = arr['cases'], arr['case_settled']
    out = {}
    u = draw_u(seed, 'deter', address, len(cases))
    for name, p0 in (('main', P0_MAIN), ('p035', P0_BETA)):
        f = first_failure(cases, detections(u, p0), delay, end)
        out[name] = (released_value(blocks, values, f, hold, end), -1 if f is None else f)
    f = first_failure(case_settled, detections(u, P0_MAIN), l_actual, end)
    out['settle'] = (released_value(blocks, values, f, hold, end), -1 if f is None else f)
    # amounts replaced by the cap: every admitted sale is sampled, one detection number per sale
    n = len(blocks)
    u_cap = draw_u(seed, 'deter-cap', address, n)
    opens = sale_open_blocks(blocks, p, start, local_origin)
    f = first_failure(opens, detections(u_cap, P0_MAIN), delay, end)
    out['cap'] = (released_value(blocks, np.full(n, vmax, dtype=np.int64), f, hold, end), -1 if f is None else f)
    return out


def exact_expectation(blocks, values, s_prob, f_sale, p0, hold, end):
    """Closed form of section 9: sum_j v_j 1{s_j + hold <= end} prod_{l: f_l < s_j + hold} (1 - p0 s_l).
    `f_sale[l]` is the failure block if sale l is sampled and detected; it is non-decreasing in l."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.float64)
    f_sale = np.asarray(f_sale, dtype=np.int64)
    q = 1.0 - p0 * np.asarray(s_prob, dtype=np.float64)
    prefix = np.r_[1.0, np.cumprod(q)]
    release = blocks + hold
    m = np.searchsorted(f_sale, release, side='left')
    return float((values * (release <= end) * prefix[m]).sum())


def exact_all(arr, *, p, start, end, local_origin, delay, hold, l_actual, vmax):
    blocks, values, s_prob = arr['blocks'], arr['values'], arr['s_prob']
    f_open = sale_open_blocks(blocks, p, start, local_origin) + delay
    out = dict(
        main=exact_expectation(blocks, values, s_prob, f_open, P0_MAIN, hold, end),
        p035=exact_expectation(blocks, values, s_prob, f_open, P0_BETA, hold, end),
        settle=exact_expectation(blocks, values, s_prob, blocks + l_actual, P0_MAIN, hold, end),
        cap=exact_expectation(blocks, np.full(len(blocks), vmax), np.ones(len(blocks)), f_open, P0_MAIN, hold, end))
    return {k: v / 1e6 for k, v in out.items()}


# ---------------------------------------------------------------- setup (the main result's configuration)

def sha256_file(path):
    return inputs.sha256_file(path)


def check_prereg(prereg, hash_file):
    """Abort unless the registration file has the registered hash (also the one in the hash file)."""
    got = sha256_file(prereg)
    stated = None
    for tok in Path(hash_file).read_text(encoding='utf-8').split():
        if len(tok) == 64 and all(c in '0123456789abcdef' for c in tok):
            stated = tok
            break
    if got != REGISTERED['prereg_sha256'] or got != stated:
        raise SystemExit(f'registration hash mismatch: file {got}, hash file {stated}, expected {REGISTERED["prereg_sha256"]}')
    return got


def main_args(a):
    """The arguments of the main result: replay.py --design 2 --vmax 0.2 --sales-cap auto-zero-reject, condition 1,
    --k-w 0.015, confirmation delay `case` (the default)."""
    ns = argparse.Namespace(
        settlements=a.settlements, conditions_file=a.conditions_file, reference_dir=a.reference_dir,
        operating_point=None, qx=137, conditions='1', out=str(a.out), timing_only=False, fold='none', draws=None,
        addresses='full', alpha_upper=None, k_role='default', design_record=None, m1_predictions=None, jobs=1,
        repetitions=1, design=2, d2_config=None, d2_edition=None, vmax='0.2', d2_k=None, k_w='0.015', hold=None,
        failure_window=None, sales_cap=getattr(a, 'sales_cap', 'auto-zero-reject'), multiplier_source=None,
        multiplier_margin=None,
        prior_settlements=None, threshold_rounding=None, floor_rule=None, bond_rule=None, window_align=None,
        chain='base', block_time=None, confirm_delay=None, injection_settings=None)
    cond = inputs.load_conditions(ns.conditions_file)
    ns.draws = cond['injection']['draws']
    ns.operating_point = replay.default_operating_point(cond)
    return ns


class Context:
    """Everything the replay needs, built once as cmd_run builds it (condition 1, no injection)."""

    def __init__(self, a):
        args = main_args(a)
        self.args = args
        cond = self.cond = inputs.load_conditions(args.conditions_file)
        d2 = self.d2 = replay.build_design2(args)
        inputs.set_address_case(d2.address_case)
        op, profile_file, profiles, op_errors = replay.resolve(args, cond, [1], d2)
        if op_errors:
            raise SystemExit(f'operating point errors: {op_errors}')
        top400, alla, groups, hashes, c_detail, rank = replay.build_groups(cond, Path(args.reference_dir))
        replayed = groups['all400'] + groups['C']
        seen = set()
        groups['replayed'] = [x for x in replayed if not (x in seen or seen.add(x))]
        # the three addresses whose mean rate exceeds n * r_fill under nR, as cmd_run lists them (a label only)
        pd = profiles[self.c_profile_name(cond)]['parameters']
        nr = replay.scales(top400, 'nR', pd, replay.rate_blocks(cond))
        groups['three'] = [x for x, cnt in top400 if inj.under_assigned(
            cnt, replay.rate_blocks(cond), nr[x], Fraction(pd['refillPpmPerBlock'], engine.PPM))]
        groups['_sets'] = {g: set(v) for g, v in groups.items() if not g.startswith('_')}
        self.top400, self.groups, self.rank = top400, groups, rank
        self.c = next(c for c in cond['conditions'] if c['id'] == 1)
        self.p = profiles[self.c['profile']]['parameters']
        self.q = args.qx
        t0 = time.time()
        self.data = engine.load(args.settlements, cond['inputs']['columns'], groups['replayed'], inputs.iter_rows,
                                inputs.utc_seconds, cap=d2.vmax, norm=inputs.normalize)
        self.load_seconds = time.time() - t0
        self.plan, _ = replay.build_plan(args, cond, d2, self.data, groups['replayed'])
        self.start, self.end = self.data.first_block, self.data.last_block
        self.local_origin = self.p['epochOrigin']
        self.window = replay.rate_blocks(cond)
        self.hold = self.p['deferBlocks']
        self.delay = replay.confirm_delay(self.p)
        self.l_actual = d2.l_actual
        self.caps, self.segments, self.scale = {}, {}, {}
        for x in groups['replayed']:
            res, self.segments[x] = self.plan.scale(x, self.data.per[x], self.q, self.p['refillPpmPerBlock'])
            self.caps[x], self.scale[x] = res, res['scale']
        self.groups_of = {x: sorted(g for g in groups if not g.startswith('_') and x in groups['_sets'][g])
                          for x in groups['replayed']}

    @staticmethod
    def c_profile_name(cond):
        return next(c for c in cond['conditions'] if c['id'] == 1)['profile']

    def seed_of(self, rep):
        return run_seed(self.cond['base_seed'], self.cond['seed_scope'], 1, rep)

    def replay_one(self, address, seed):
        """engine.replay_address with the arguments of replay.run_condition, plus the columns it adds to the row."""
        d2, caps, p = self.d2, self.caps[address], self.p
        row, arr = engine.replay_address(
            address, self.data.per[address], seed=seed, p=p, capacity=caps['capacity'], scale=self.scale[address],
            origin_ledger=self.start, local_origin=self.local_origin, end_ledger=self.end,
            block_size=self.data.block_size, window_blocks=self.window, first_seconds=self.data.first_seconds,
            observed=True, cap=d2.vmax, sample_tau=d2.vmax, rounding=d2.rounding,
            segments=self.segments.get(address), refill_ppm=caps['refill_ppm'], align=d2.align,
            hour_blocks=d2.hour_blocks, block_seconds=d2.block_seconds)
        return row, arr

    def full_row(self, address, row):
        """The observed row as run_condition writes it (columns of addresses_observed.csv)."""
        d2, cs = self.d2, self.caps[address]
        counts = self.groups['_counts']
        ref_count = dict(self.top400).get(address)
        ref_count = ref_count if ref_count is not None else counts[address]
        row = dict(row)
        row['rank'] = self.rank.get(address)
        row['groups'] = self.groups_of[address]
        row['under_assigned'] = inj.under_assigned(ref_count, self.window, self.scale[address], Fraction(cs['refill_ppm'], engine.PPM))
        row['nB'] = cs['bond']
        row['bond_B'] = cs['bond_unit']
        row['deterrence_min'] = self.scale[address] * cs['k'] * d2.vmax * engine.PPM / d2.p0_ppm
        row.update(vmax_atomic=d2.vmax, sales_cap_S=cs['S'], sales_cap_method=cs['method'],
                   sales_cap_parts=cs.get('S_parts'), sales_cap_capacity=cs['capacity'],
                   sales_cap_refill_ppm=cs['refill_ppm'], k_address=cs['k'], deduction_b=cs['b'])
        for key in ('formula', 'time_average', 'max'):
            v = row[f'H_{key}']
            row[f'nB_plus_H_{key}'] = None if v is None else row['nB'] + v
        return row


def one_replicate(ctx, rep, want_exact=False, keep_rows=False):
    """All addresses for one replicate: per-address X of the four variants (and, for rep 0, the closed form)."""
    seed = ctx.seed_of(rep)
    out, rows, exact = [], {}, {}
    for a in ctx.groups['replayed']:
        row, arr = ctx.replay_one(a, seed)
        if keep_rows:
            rows[a] = ctx.full_row(a, row)
        m = model_address(arr, seed=seed, address=a, p=ctx.p, start=ctx.start, end=ctx.end,
                          local_origin=ctx.local_origin, delay=ctx.delay, hold=ctx.hold,
                          l_actual=ctx.l_actual, vmax=ctx.d2.vmax)
        rec = dict(rep=rep, seed=seed, address=a, accepted=int(row['accepted_count']),
                   accepted_value=int(row['accepted_value']), sampled=int(row['sample_count']),
                   expected_samples=row.get('expected_samples'))
        for name in VARIANTS:
            rec[f'X_{name}'], rec[f'f_{name}'] = m[name]
        out.append(rec)
        if want_exact and row['accepted_count'] > 0:
            exact[a] = exact_all(arr, p=ctx.p, start=ctx.start, end=ctx.end, local_origin=ctx.local_origin,
                                 delay=ctx.delay, hold=ctx.hold, l_actual=ctx.l_actual, vmax=ctx.d2.vmax)
    return out, rows, exact


# ---------------------------------------------------------------- checks against the stored main run

def compare_to_stored(ctx, rows, stored_csv):
    """Compare the replayed observed rows of seed 0 with the stored addresses_observed.csv of the main run, cell by
    cell (the text the replayer writes) and as numbers. Returns a report."""
    with open(stored_csv, newline='', encoding='ascii') as f:
        stored = list(csv.DictReader(f))
    cols = list(stored[0].keys())
    n_cells = n_text_diff = 0
    max_abs = {}
    text_diff_cols = {}
    missing = [r['address'] for r in stored if r['address'] not in rows]
    for r in stored:
        mine = rows.get(r['address'])
        if mine is None:
            continue
        for c in cols:
            if c == 'address':
                continue
            n_cells += 1
            theirs = r[c]
            mc = replay._cell(mine.get(c))
            if str(mc) != theirs:
                n_text_diff += 1
                text_diff_cols[c] = text_diff_cols.get(c, 0) + 1
            try:
                d = abs(float(mc) - float(theirs)) if mc != '' and theirs != '' else (0.0 if mc == theirs else float('inf'))
            except ValueError:
                d = 0.0 if str(mc) == theirs else float('inf')
            max_abs[c] = max(max_abs.get(c, 0.0), d)
    return dict(stored_file=str(stored_csv), stored_sha256=sha256_file(stored_csv), addresses_stored=len(stored),
                addresses_replayed=len(rows), addresses_missing=missing, columns=[c for c in cols if c != 'address'],
                cells_compared=n_cells, cells_text_different=n_text_diff, text_different_columns=text_diff_cols,
                max_abs_diff_overall=max(max_abs.values()) if max_abs else None, max_abs_diff_by_column=max_abs)


# ---------------------------------------------------------------- run

def git_info():
    def g(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return dict(head=g('rev-parse', 'HEAD'), dirty=bool(g('status', '--porcelain')),
                changed_since_registered_head=g('diff', '--name-status', REGISTERED['head'], 'HEAD').splitlines())


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True, default=replay._json_default) + '\n', encoding='utf-8')


_CTX = None


def _worker(rep):
    t0 = time.time()
    recs, _, _ = one_replicate(_CTX, rep)
    out_dir = Path(_CTX.args.out) / 'per_seed'
    path = out_dir / f'rep_{rep:03d}.json'
    write_json(f'{path}.tmp', recs)
    os.replace(f'{path}.tmp', path)
    return rep, round(time.time() - t0, 1), round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def log(out, text):
    line = time.strftime('%Y-%m-%dT%H:%M:%SZ ', time.gmtime()) + text
    print(line, flush=True)
    with open(Path(out) / 'run.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def cmd_run(a):
    global _CTX
    t_start = time.time()
    out = Path(a.out)
    (out / 'per_seed').mkdir(parents=True, exist_ok=True)
    checks = dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_start)))
    # 11.1 registration hash
    checks['prereg_sha256'] = check_prereg(a.prereg, a.prereg_hash_file)
    log(out, f"check 1 registration hash ok {checks['prereg_sha256']}")
    # 11.2 inputs
    hashes = dict(window_list=sha256_file(a.settlements), conditions=sha256_file(a.conditions_file),
                  top400=sha256_file(Path(a.reference_dir) / 'sellers_dune_top400.csv'),
                  all4400=sha256_file(Path(a.reference_dir) / 'sellers_dune_all4400.csv'))
    expect = dict(window_list=REGISTERED['window_list_sha256'], conditions=REGISTERED['conditions_sha256'],
                  top400=REGISTERED['top400_sha256'], all4400=REGISTERED['all4400_sha256'])
    for k in hashes:
        if hashes[k] != expect[k]:
            raise SystemExit(f'input hash mismatch {k}: {hashes[k]} != {expect[k]}')
    checks['input_hashes'] = hashes
    checks['prior_list'] = 'not available in this environment; registered hash ' + REGISTERED['prior_list_sha256'] + ' not checked (the run does not read it)'
    log(out, 'check 2 input hashes ok (prior list not present, not used)')
    # 11.3 code
    git = checks['git'] = git_info()
    changed = [ln for ln in git['changed_since_registered_head']]
    bad = [ln for ln in changed if not (ln.startswith('A\t') and ln.split('\t')[1].endswith(('d2_deter.py', 'test_d2_deter.py')))]
    if bad or git['dirty']:
        raise SystemExit(f'code check failed: dirty={git["dirty"]}, changes against e57bd83: {changed}')
    log(out, f"check 3 code ok: HEAD {git['head']}, only new files {changed}")
    ctx = _CTX = Context(a)
    log(out, f'inputs loaded in {ctx.load_seconds:.0f} s; replayed addresses {len(ctx.groups["replayed"])}')
    # 11.5 constants
    if ctx.delay != REGISTERED['confirm_delay'] or ctx.hold != REGISTERED['hold']:
        raise SystemExit(f'constants: confirm_delay {ctx.delay}, hold {ctx.hold}')
    if (ctx.data.first_block, ctx.data.last_block, ctx.data.total_rows) != (
            REGISTERED['first_block'], REGISTERED['last_block'], REGISTERED['rows']):
        raise SystemExit('list rows/blocks differ from the registration')
    if ctx.l_actual != REGISTERED['l_actual'] or ctx.d2.vmax != REGISTERED['vmax'] or ctx.d2.p0_ppm != REGISTERED['p0_ppm']:
        raise SystemExit('design constants differ from the registration')
    if (ctx.cond['base_seed'], ctx.cond['seed_scope'], 1) != REGISTERED['seed_args']:
        raise SystemExit('seed arguments differ from the registration')
    checks['constants'] = dict(confirm_delay=ctx.delay, hold=ctx.hold, l_actual=ctx.l_actual, vmax=ctx.d2.vmax,
                               first_block=ctx.start, last_block=ctx.end, rows=ctx.data.total_rows)
    log(out, f'check 5 constants ok {checks["constants"]}')
    # 11.4 replicate 0 against the stored main run (before anything else is computed)
    seed0_path = out / 'per_seed' / 'rep_000.json'
    t0 = time.time()
    recs, rows, exact = one_replicate(ctx, 0, want_exact=True, keep_rows=True)
    stored_run = Path(a.stored_run)
    rep = compare_to_stored(ctx, rows, stored_run / 'condition-01-seed-0' / 'addresses_observed.csv')
    run_json = json.loads((stored_run / 'run.json').read_text(encoding='utf-8'))
    rep['stored_seed'] = run_json['runs'][0]['seed']
    rep['replayed_seed'] = ctx.seed_of(0)
    rep['seed_equal'] = rep['stored_seed'] == rep['replayed_seed']
    rep['seconds'] = round(time.time() - t0, 1)
    rep['pass'] = (rep['seed_equal'] and not rep['addresses_missing'] and rep['addresses_stored'] == rep['addresses_replayed']
                   and rep['cells_text_different'] == 0)
    checks['seed0_vs_stored'] = rep
    write_json(out / 'check_seed0_vs_stored.json', rep)
    write_json(out / 'exact_expectation.json', exact)
    write_json(seed0_path, recs)
    log(out, f"check 4 seed 0 vs stored: pass={rep['pass']}, cells {rep['cells_compared']}, text differences "
             f"{rep['cells_text_different']}, max abs diff {rep['max_abs_diff_overall']}")
    if not rep['pass']:
        write_json(out / 'checks.json', checks)
        raise SystemExit('seed 0 does not match the stored run; computation not continued')
    write_json(out / 'checks.json', checks)
    # the replicates
    todo = [r for r in range(1, a.replicates) if not (out / 'per_seed' / f'rep_{r:03d}.json').exists()]
    log(out, f'replicates to compute: {len(todo)} (R = {a.replicates}), jobs {a.jobs}')
    import multiprocessing
    timings = []
    with multiprocessing.get_context('fork').Pool(a.jobs) as pool:
        for r, secs, mem in pool.imap_unordered(_worker, todo, chunksize=1):
            timings.append((r, secs, mem))
            log(out, f'replicate {r} done in {secs} s (worker peak {mem} MiB)')
    write_json(out / 'timing.json', dict(
        wall_seconds=round(time.time() - t_start, 1), load_seconds=round(ctx.load_seconds, 1), jobs=a.jobs,
        replicates_computed=len(todo) + 1,
        peak_memory_mib_parent=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        peak_memory_mib_children=round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
        replicate_seconds=sorted(timings)))
    log(out, 'all replicates finished')
    return 0


# ---------------------------------------------------------------- analysis

def load_replicates(out):
    """Largest R' such that replicates 0..R'-1 are all present (registration section 5)."""
    files = {int(p.stem.split('_')[1]) for p in (Path(out) / 'per_seed').glob('rep_*.json')}
    r = 0
    while r in files:
        r += 1
    return r, [json.loads((Path(out) / 'per_seed' / f'rep_{i:03d}.json').read_text(encoding='utf-8')) for i in range(r)]


def spearman(x, y):
    from scipy import stats
    if len(x) < 3 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return dict(rho=None, p=None, n=int(len(x)))
    r = stats.spearmanr(x, y)
    return dict(rho=float(r.statistic), p=float(r.pvalue), n=int(len(x)))


def dist(v):
    v = np.asarray(v, dtype=float)
    return dict(min=float(v.min()), q1=float(np.percentile(v, 25)), median=float(np.percentile(v, 50)),
                q3=float(np.percentile(v, 75)), max=float(v.max()), mean=float(v.mean()), n=int(len(v)))


def analyze_variant(name, reps, order, meta, exact, uppers):
    """Per-address statistics of one variant and the judgment rule of section 7."""
    R = len(reps)
    X = np.array([[rec[f'X_{name}'] for rec in rep] for rep in reps], dtype=np.float64) / 1e6      # R x A
    F = np.array([[rec[f'f_{name}'] for rec in rep] for rep in reps])
    acc = np.array([[rec['accepted'] for rec in rep] for rep in reps])
    mean = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1) if R > 1 else np.zeros(X.shape[1])
    se = sd / np.sqrt(R)
    pfail = (F >= 0).mean(axis=0)
    inM = acc[0] > 0
    rows = []
    for i, a in enumerate(order):
        m = meta[a]
        rows.append(dict(address=a, rank=m['rank'], accepted=int(acc[0, i]), mean_X=float(mean[i]), se=float(se[i]),
                         sd=float(sd[i]), max_X=float(X[:, i].max()), min_X=float(X[:, i].min()),
                         p_fail=float(pfail[i]), exact_X=exact.get(a, {}).get(name), in_M=bool(inM[i])))
    res = dict(variant=name, R=R, addresses_total=len(order), M=int(inM.sum()), uppers=uppers)
    idx = np.flatnonzero(inM)
    res['accepted_varies_across_replicates'] = int((acc != acc[0]).any(axis=0).sum())
    for label, up in uppers.items():
        inside = mean[idx] <= up + 2 * se[idx]
        res[f'N_{label}'] = int(inside.sum())
        res[f'K_{label}'] = int((~inside).sum())
        res[f'above_bound_no_se_{label}'] = int((mean[idx] > up).sum())
        res[f'max_ratio_{label}'] = float(mean[idx].max() / up)
        for r_ in rows:
            r_[f'inside_{label}'] = (r_['mean_X'] <= up + 2 * r_['se']) if r_['in_M'] else None
            r_[f'ratio_{label}'] = r_['mean_X'] / up
    res['mean_of_means'] = float(mean[idx].mean())
    res['max_mean'] = float(mean[idx].max())
    res['dist_of_means'] = dist(mean[idx])
    res['max_over_seeds_and_addresses'] = float(X[:, idx].max())
    res['n_mean_at_or_above_tightness'] = int((mean[idx] >= TIGHTNESS * UPPER_MAIN).sum())
    res['n_mean_above_cap_theory_0.3'] = int((mean[idx] > CAP_THEORY).sum())
    # exact expectation check (section 9)
    ex = np.array([exact.get(order[i], {}).get(name, np.nan) for i in idx])
    diff = np.abs(mean[idx] - ex)
    thr = 3 * se[idx]
    res['exact_check'] = dict(
        addresses_over_3se=int((diff > np.maximum(thr, 1e-9)).sum()), max_abs_diff=float(diff.max()),
        max_exact=float(ex.max()), mean_exact=float(ex.mean()),
        addresses_exact_above_upper={k: int((ex > up).sum()) for k, up in uppers.items()})
    # speed
    acc0 = acc[0][idx].astype(float)
    hourly = acc0 / HOURS
    sp = dict(spearman_count=spearman(acc0, mean[idx]), spearman_hourly=spearman(hourly, mean[idx]))
    pf = pfail[idx] >= 0.95
    sp['spearman_count_pfail_ge_0.95'] = spearman(acc0[pf], mean[idx][pf])
    sp['n_pfail_ge_0.95'] = int(pf.sum())
    qs = np.percentile(acc0, [25, 50, 75])
    bins = np.digitize(acc0, qs[:3], right=True)
    sp['by_count_quartile'] = []
    for qb in range(4):
        sel = bins == qb
        if sel.any():
            sp['by_count_quartile'].append(dict(quartile=qb + 1, n=int(sel.sum()), count_min=float(acc0[sel].min()),
                                                count_max=float(acc0[sel].max()), median_mean_X=float(np.median(mean[idx][sel])),
                                                max_mean_X=float(mean[idx][sel].max())))
    ranks = np.array([meta[order[i]]['rank'] if meta[order[i]]['rank'] is not None else 10**9 for i in idx])
    inA = ranks <= 44
    sp['group_A_ranks_1_44'] = dist(mean[idx][inA]) if inA.any() else dict(n=0)
    sp['rest'] = dist(mean[idx][~inA]) if (~inA).any() else dict(n=0)
    top5 = np.argsort(-acc0, kind='stable')[:5]
    sp['busiest_five'] = [dict(address=order[idx[t]], accepted=int(acc0[t]), mean_X=float(mean[idx][t]),
                               p_fail=float(pfail[idx][t])) for t in top5]
    res['speed'] = sp
    over = [r for r in rows if r['in_M'] and not r[f'inside_{list(uppers)[0]}']]
    res['over_addresses'] = [dict(address=r['address'], rank=r['rank'], accepted=r['accepted'], mean_X=r['mean_X'], se=r['se'],
                                  exact_X=r['exact_X'], p_fail=r['p_fail'], max_X=r['max_X']) for r in over]
    return res, rows


def cmd_analyze(a):
    out = Path(a.out)
    R, reps = load_replicates(out)
    if R < 20:
        write_json(out / 'summary.json', dict(R=R, note='fewer than 20 complete replicates; no judgment'))
        raise SystemExit(f'only {R} complete replicates')
    order = [rec['address'] for rec in reps[0]]
    cond = inputs.load_conditions(a.conditions_file)
    top400, alla, groups, hashes, c_detail, rank = replay.build_groups(cond, Path(a.reference_dir))
    meta = {x: dict(rank=rank.get(x)) for x in order}
    exact = json.loads((out / 'exact_expectation.json').read_text(encoding='utf-8'))
    uppers_by = dict(main=dict(design_0_5=UPPER_MAIN), p035=dict(true_0_5714=UPPER_BETA_TRUE, design_0_5=UPPER_MAIN),
                     cap=dict(design_0_5=UPPER_MAIN), settle=dict(design_0_5=UPPER_MAIN))
    summary = dict(R=R, replicates=list(range(R)), registered_R=100, constants=dict(
        tightness=TIGHTNESS, cap_theory_0_6=CAP_THEORY, hours=HOURS))
    files = dict(main='addresses_main.csv', p035='addresses_variant_p035.csv', cap='addresses_variant_cap.csv',
                 settle='addresses_variant_settle.csv')
    for name in VARIANTS:
        res, rows = analyze_variant(name, reps, order, meta, exact, uppers_by[name])
        summary[name] = res
        cols = list(rows[0].keys())
        with open(out / files[name], 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
    # the long replicate file
    with open(out / 'replicates_long.csv', 'w', newline='', encoding='utf-8') as f:
        cols = ['rep', 'seed', 'address', 'accepted', 'accepted_value', 'sampled'] + [f'{k}_{v}' for v in VARIANTS for k in ('X', 'f')]
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore', lineterminator='\n')
        w.writeheader()
        for rep in reps:
            w.writerows(rep)
    write_json(out / 'summary.json', summary)
    m = summary['main']
    print(f"upper within address {m['N_design_0_5']}/{m['M']}, over address {m['K_design_0_5']}, E[X] max {m['max_mean']:.6f} USDC")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('run', 'analyze'):
        s = sub.add_parser(name)
        s.add_argument('--out', required=True)
        s.add_argument('--reference-dir', required=True)
        s.add_argument('--conditions-file', required=True)
        s.add_argument('--settlements', default=None)
        s.add_argument('--prereg', required=True)
        s.add_argument('--prereg-hash-file', required=True)
        s.add_argument('--stored-run', default=None)
        s.add_argument('--replicates', type=int, default=100)
        s.add_argument('--jobs', type=int, default=2)
    a = p.parse_args(argv)
    check_prereg(a.prereg, a.prereg_hash_file)
    if a.cmd == 'run':
        return cmd_run(a)
    return cmd_analyze(a)


if __name__ == '__main__':
    sys.exit(main())
