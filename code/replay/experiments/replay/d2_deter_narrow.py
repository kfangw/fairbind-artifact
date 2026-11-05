#!/usr/bin/env python3
"""Deterrence replay under the narrow freeze (journal item J7, pre-registration J7_prereg).

    d2_deter_narrow.py run --settlements LIST.csv --reference-dir REF --conditions-file COND.json
                           --prereg J7_prereg.md --prereg-hash-file HASH.txt --stored-run DIR
                           --det-per-seed DIR --out OUT [--replicates 1000] [--jobs 4]
    d2_deter_narrow.py analyze --out OUT --reference-dir REF --conditions-file COND.json --prereg ... \
                           --prereg-hash-file ... --det-per-seed DIR

The replay, the fraud model and the seeds are those of d2_deter.py (registration DET). Only the freeze changes:
at the first confirmed failure f the account stops, but only the held sales settled at or after the failed
sampled sale (settlement block c) are frozen. Held sales settled before c are released on their own schedule,
s + T_hold, if that is inside the window. This is the scope 'detected-onward' of engine.narrow_lost restricted to
the first failure; later failures cannot freeze anything earlier than c (a sale before c belongs to an epoch no
later than that of c, so a detected case of it fails no later than f).

The full freeze of DET is computed alongside from the same draws (variant 'full'); for replicates 0..99 it must
equal the stored DET replicates exactly. Nothing in d2_deter.py, the replayer or its outputs is changed.
"""
import argparse
import csv
import json
import os
import resource
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import d2_deter as dd  # noqa: E402
import inputs  # noqa: E402
import replay  # noqa: E402

ROOT = HERE.parents[1]

# Filled in from the sealed registration (J7_prereg.md); the run aborts if the file differs.
PREREG_SHA256 = 'ec2fcc9e3dc3d93951c2a1b9f2dca60480232fd6e7a6c93ab54e04093963f8cd'
HOLD_ALT = 34673            # T_hold with the 3,600-block waiting margin (manuscript), variant 'narrow_hold34673'
VARIANTS = ('narrow', 'full', 'narrow_p035', 'narrow_settle', 'narrow_cap', 'narrow_hold34673')
ALLOWED_NEW_FILES = ('d2_deter.py', 'test_d2_deter.py', 'd2_deter_narrow.py', 'test_d2_deter_narrow.py',
                     'test_freeze_scope.py', 'run_j7.sh')
ALLOWED_MODIFIED = ('experiments/replay/engine.py', 'experiments/replay/replay.py')   # 10fd112, not used here
DET_COMPARE_REPS = 100


# ---------------------------------------------------------------- the narrow-freeze model (pure functions)

def first_failure_narrow(open_blocks, detected, settled, delay, end):
    """(f, c): block of the first confirmed failure and the smallest settlement block among the detected cases that
    fail at f; (None, None) if no failure inside the window. `open_blocks` are case openings (non-decreasing in the
    case order is not required), `settled` the settlement block of each case's sale."""
    open_blocks = np.asarray(open_blocks, dtype=np.int64)
    detected = np.asarray(detected, dtype=bool)
    settled = np.asarray(settled, dtype=np.int64)
    if len(open_blocks) == 0 or not detected.any():
        return None, None
    o = int(open_blocks[detected].min())
    f = o + int(delay)
    if f > end:
        return None, None
    c = int(settled[detected & (open_blocks == o)].min())
    return f, c


def released_value_narrow(blocks, values, f, c, hold, end):
    """X under the narrow freeze. Without a failure: sales with s + hold <= end. With a failure at f (<= end) whose
    failed sale settled at c: sales with s <= f that are released before f (s + hold <= f), plus sales settled before
    c that are released later inside the window (s + hold <= end). Sales after f are not counted (the account stopped).
    Boundaries are those of engine.evaluate_failures and engine.narrow_lost: frozen iff c <= s and s + hold > f."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    if f is None:
        return int(values[blocks + hold <= end].sum())
    rel = blocks + hold
    keep = (blocks <= f) & ((rel <= f) | ((blocks < c) & (rel <= end)))
    return int(values[keep].sum())


def exact_expectation_narrow(blocks, values, s_prob, f_sale, p0, hold, end):
    """Closed form under the narrow freeze:
    sum_j v_j 1{s_j + hold <= end} prod_{l: s_l <= s_j, f_l < s_j + hold} (1 - p0 s_l).
    Both index sets are prefixes of the sale order (blocks and f_sale are non-decreasing), so the product is the
    cumulative product up to the shorter prefix."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.float64)
    f_sale = np.asarray(f_sale, dtype=np.int64)
    q = 1.0 - p0 * np.asarray(s_prob, dtype=np.float64)
    prefix = np.r_[1.0, np.cumprod(q)]
    release = blocks + hold
    m = np.searchsorted(f_sale, release, side='left')
    k = np.searchsorted(blocks, blocks, side='right')
    return float((values * (release <= end) * prefix[np.minimum(m, k)]).sum())


def model_address_narrow(arr, *, seed, address, p, start, end, local_origin, delay, hold, l_actual, vmax):
    """All variants for one address and one replay. Same draws as d2_deter.model_address (tags 'deter' and
    'deter-cap'), so the variant 'full' equals DET's 'main'. Returns {variant: (X atomic, f or -1)}."""
    blocks, values = arr['blocks'], arr['values']
    cases, case_settled = arr['cases'], arr['case_settled']
    out = {}
    u = dd.draw_u(seed, 'deter', address, len(cases))
    det40, det35 = dd.detections(u, dd.P0_MAIN), dd.detections(u, dd.P0_BETA)
    f, c = first_failure_narrow(cases, det40, case_settled, delay, end)
    out['narrow'] = (released_value_narrow(blocks, values, f, c, hold, end), -1 if f is None else f)
    out['narrow_hold34673'] = (released_value_narrow(blocks, values, f, c, HOLD_ALT, end), -1 if f is None else f)
    f_full = dd.first_failure(cases, det40, delay, end)
    out['full'] = (dd.released_value(blocks, values, f_full, hold, end), -1 if f_full is None else f_full)
    f, c = first_failure_narrow(cases, det35, case_settled, delay, end)
    out['narrow_p035'] = (released_value_narrow(blocks, values, f, c, hold, end), -1 if f is None else f)
    f, c = first_failure_narrow(case_settled, det40, case_settled, l_actual, end)
    out['narrow_settle'] = (released_value_narrow(blocks, values, f, c, hold, end), -1 if f is None else f)
    n = len(blocks)
    u_cap = dd.draw_u(seed, 'deter-cap', address, n)
    opens = dd.sale_open_blocks(blocks, p, start, local_origin)
    f, c = first_failure_narrow(opens, dd.detections(u_cap, dd.P0_MAIN), blocks, delay, end)
    out['narrow_cap'] = (released_value_narrow(blocks, np.full(n, vmax, dtype=np.int64), f, c, hold, end),
                         -1 if f is None else f)
    return out


def exact_all_narrow(arr, *, p, start, end, local_origin, delay, hold, l_actual, vmax):
    blocks, values, s_prob = arr['blocks'], arr['values'], arr['s_prob']
    f_open = dd.sale_open_blocks(blocks, p, start, local_origin) + delay
    n = len(blocks)
    out = dict(
        narrow=exact_expectation_narrow(blocks, values, s_prob, f_open, dd.P0_MAIN, hold, end),
        narrow_hold34673=exact_expectation_narrow(blocks, values, s_prob, f_open, dd.P0_MAIN, HOLD_ALT, end),
        full=dd.exact_expectation(blocks, values, s_prob, f_open, dd.P0_MAIN, hold, end),
        narrow_p035=exact_expectation_narrow(blocks, values, s_prob, f_open, dd.P0_BETA, hold, end),
        narrow_settle=exact_expectation_narrow(blocks, values, s_prob, blocks + l_actual, dd.P0_MAIN, hold, end),
        narrow_cap=exact_expectation_narrow(blocks, np.full(n, vmax), np.ones(n), f_open, dd.P0_MAIN, hold, end))
    return {k: v / 1e6 for k, v in out.items()}


def one_replicate(ctx, rep, want_exact=False, keep_rows=False):
    seed = ctx.seed_of(rep)
    out, rows, exact = [], {}, {}
    for a in ctx.groups['replayed']:
        row, arr = ctx.replay_one(a, seed)
        if keep_rows:
            rows[a] = ctx.full_row(a, row)
        m = model_address_narrow(arr, seed=seed, address=a, p=ctx.p, start=ctx.start, end=ctx.end,
                                 local_origin=ctx.local_origin, delay=ctx.delay, hold=ctx.hold,
                                 l_actual=ctx.l_actual, vmax=ctx.d2.vmax)
        rec = dict(rep=rep, seed=seed, address=a, accepted=int(row['accepted_count']),
                   accepted_value=int(row['accepted_value']), sampled=int(row['sample_count']))
        for name in VARIANTS:
            rec[f'X_{name}'], rec[f'f_{name}'] = m[name]
        out.append(rec)
        if want_exact and row['accepted_count'] > 0:
            exact[a] = exact_all_narrow(arr, p=ctx.p, start=ctx.start, end=ctx.end, local_origin=ctx.local_origin,
                                        delay=ctx.delay, hold=ctx.hold, l_actual=ctx.l_actual, vmax=ctx.d2.vmax)
    return out, rows, exact


# ---------------------------------------------------------------- checks

def check_prereg(prereg, hash_file):
    got = dd.sha256_file(prereg)
    stated = None
    for tok in Path(hash_file).read_text(encoding='utf-8').split():
        if len(tok) == 64 and all(ch in '0123456789abcdef' for ch in tok):
            stated = tok
            break
    if PREREG_SHA256 is None or got != PREREG_SHA256 or got != stated:
        raise SystemExit(f'registration hash mismatch: file {got}, hash file {stated}, expected {PREREG_SHA256}')
    return got


def git_info():
    def g(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()
    return dict(head=g('rev-parse', 'HEAD'), dirty=bool(g('status', '--porcelain', '--untracked-files=no')),
                changed_since_registered_head=g('diff', '--name-status', dd.REGISTERED['head'], 'HEAD').splitlines())


def code_check(git):
    bad = []
    for ln in git['changed_since_registered_head']:
        st, path = ln.split('\t')[0], ln.split('\t')[-1]
        if st == 'A' and path.endswith(ALLOWED_NEW_FILES):
            continue
        if st == 'M' and path in ALLOWED_MODIFIED:
            continue
        bad.append(ln)
    return bad


def compare_full_to_det(recs, det_file):
    """Variant 'full' of one replicate against DET's stored X_main and f_main for the same replicate."""
    det = json.loads(Path(det_file).read_text(encoding='utf-8'))
    dmap = {r['address']: r for r in det}
    diff = [r['address'] for r in recs if r['address'] not in dmap
            or (r['X_full'], r['f_full']) != (dmap[r['address']]['X_main'], dmap[r['address']]['f_main'])]
    return dict(addresses=len(recs), det_addresses=len(det), different=len(diff), first_different=diff[:5])


def monotone_violations(recs):
    """Narrow freezes a subset of what full freezes, so X_narrow >= X_full for every address (code check)."""
    return [r['address'] for r in recs if r['X_narrow'] < r['X_full']]


# ---------------------------------------------------------------- run

_CTX = None


def _worker(rep):
    t0 = time.time()
    recs, _, _ = one_replicate(_CTX, rep)
    path = Path(_CTX.args.out) / 'per_seed' / f'rep_{rep:04d}.json'
    dd.write_json(f'{path}.tmp', recs)
    os.replace(f'{path}.tmp', path)
    return rep, round(time.time() - t0, 1), round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def log(out, text):
    dd.log(out, text)


def write_status(out, **kw):
    """Small status file for the monitoring session: done count, last replicate, time, rate."""
    st = dict(updated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **kw)
    p = Path(out) / 'status.json'
    dd.write_json(f'{p}.tmp', st)
    os.replace(f'{p}.tmp', p)


def cmd_run(a):
    global _CTX
    t_start = time.time()
    out = Path(a.out)
    (out / 'per_seed').mkdir(parents=True, exist_ok=True)
    checks = dict(started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_start)))
    checks['prereg_sha256'] = check_prereg(a.prereg, a.prereg_hash_file)
    log(out, f"J7 check 1 registration hash ok {checks['prereg_sha256']}")
    hashes = dict(window_list=dd.sha256_file(a.settlements), conditions=dd.sha256_file(a.conditions_file),
                  top400=dd.sha256_file(Path(a.reference_dir) / 'sellers_dune_top400.csv'),
                  all4400=dd.sha256_file(Path(a.reference_dir) / 'sellers_dune_all4400.csv'))
    expect = dict(window_list=dd.REGISTERED['window_list_sha256'], conditions=dd.REGISTERED['conditions_sha256'],
                  top400=dd.REGISTERED['top400_sha256'], all4400=dd.REGISTERED['all4400_sha256'])
    for k in hashes:
        if hashes[k] != expect[k]:
            raise SystemExit(f'input hash mismatch {k}: {hashes[k]} != {expect[k]}')
    checks['input_hashes'] = hashes
    log(out, 'J7 check 2 input hashes ok')
    git = checks['git'] = git_info()
    bad = code_check(git)
    if bad or git['dirty']:
        raise SystemExit(f'code check failed: dirty={git["dirty"]}, unexpected changes against e57bd83: {bad}')
    log(out, f"J7 check 3 code ok: HEAD {git['head']}")
    ctx = _CTX = dd.Context(a)
    log(out, f'inputs loaded in {ctx.load_seconds:.0f} s; replayed addresses {len(ctx.groups["replayed"])}')
    R = dd.REGISTERED
    if ctx.delay != R['confirm_delay'] or ctx.hold != R['hold'] or ctx.l_actual != R['l_actual'] \
            or ctx.d2.vmax != R['vmax'] or ctx.d2.p0_ppm != R['p0_ppm'] \
            or (ctx.data.first_block, ctx.data.last_block, ctx.data.total_rows) != (R['first_block'], R['last_block'], R['rows']) \
            or (ctx.cond['base_seed'], ctx.cond['seed_scope'], 1) != R['seed_args']:
        raise SystemExit('constants differ from the registration')
    checks['constants'] = dict(confirm_delay=ctx.delay, hold=ctx.hold, hold_alt=HOLD_ALT, l_actual=ctx.l_actual,
                               vmax=ctx.d2.vmax, first_block=ctx.start, last_block=ctx.end, rows=ctx.data.total_rows)
    log(out, f'J7 check 5 constants ok {checks["constants"]}')
    seed0 = out / 'per_seed' / 'rep_0000.json'
    if not seed0.exists() or not (out / 'check_seed0_vs_stored.json').exists():
        t0 = time.time()
        recs, rows, exact = one_replicate(ctx, 0, want_exact=True, keep_rows=True)
        rep = dd.compare_to_stored(ctx, rows, Path(a.stored_run) / 'condition-01-seed-0' / 'addresses_observed.csv')
        run_json = json.loads((Path(a.stored_run) / 'run.json').read_text(encoding='utf-8'))
        rep['seed_equal'] = run_json['runs'][0]['seed'] == ctx.seed_of(0)
        rep['seconds'] = round(time.time() - t0, 1)
        rep['pass'] = (rep['seed_equal'] and not rep['addresses_missing']
                       and rep['addresses_stored'] == rep['addresses_replayed'] and rep['cells_text_different'] == 0)
        det0 = compare_full_to_det(recs, Path(a.det_per_seed) / 'rep_000.json')
        mono = monotone_violations(recs)
        checks['seed0_vs_stored'] = rep
        checks['rep0_full_vs_det'] = det0
        checks['rep0_monotone_violations'] = mono
        dd.write_json(out / 'check_seed0_vs_stored.json', rep)
        dd.write_json(out / 'exact_expectation.json', exact)
        log(out, f"J7 check 4 seed 0 vs stored: pass={rep['pass']}, cells {rep['cells_compared']}, "
                 f"text differences {rep['cells_text_different']}")
        log(out, f"J7 check 6 replicate 0 full vs DET: different {det0['different']} of {det0['addresses']}; "
                 f"monotone violations {len(mono)}")
        if not rep['pass'] or det0['different'] or mono:
            dd.write_json(out / 'checks.json', checks)
            raise SystemExit('a start check failed; computation not continued')
        dd.write_json(seed0, recs)
        dd.write_json(out / 'checks.json', checks)
    else:
        log(out, 'resuming: replicate 0 and the start checks are already on disk')
    todo = [r for r in range(1, a.replicates) if not (out / 'per_seed' / f'rep_{r:04d}.json').exists()]
    done0 = a.replicates - len(todo)
    log(out, f'replicates to compute: {len(todo)} (R = {a.replicates}, already done {done0}), jobs {a.jobs}')
    write_status(out, R=a.replicates, done=done0, jobs=a.jobs, last=None, mean_seconds_per_replicate=None,
                 eta_hours=None, pid=os.getpid(), state='running')
    import multiprocessing
    timings = []
    t_loop = time.time()
    with multiprocessing.get_context('fork').Pool(a.jobs) as pool:
        for r, secs, mem in pool.imap_unordered(_worker, todo, chunksize=1):
            timings.append((r, secs, mem))
            log(out, f'replicate {r} done in {secs} s (worker peak {mem} MiB)')
            done = done0 + len(timings)
            wall_per = (time.time() - t_loop) / len(timings)
            write_status(out, R=a.replicates, done=done, jobs=a.jobs, last=r,
                         mean_seconds_per_replicate=round(float(np.mean([t[1] for t in timings])), 1),
                         eta_hours=round(wall_per * (a.replicates - done) / 3600, 2), pid=os.getpid(), state='running')
    dd.write_json(out / f'timing_{time.strftime("%Y%m%dT%H%M%S", time.gmtime())}.json', dict(
        wall_seconds=round(time.time() - t_start, 1), load_seconds=round(ctx.load_seconds, 1), jobs=a.jobs,
        replicates_computed=len(todo),
        peak_memory_mib_children=round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
        replicate_seconds=sorted(timings)))
    write_status(out, R=a.replicates, done=a.replicates, jobs=a.jobs, last=None, mean_seconds_per_replicate=None,
                 eta_hours=0, pid=os.getpid(), state='finished')
    log(out, 'all replicates finished')
    return 0


# ---------------------------------------------------------------- analysis

def load_replicates(out):
    files = {int(p.stem.split('_')[1]) for p in (Path(out) / 'per_seed').glob('rep_*.json')}
    r = 0
    while r in files:
        r += 1
    return r, [json.loads((Path(out) / 'per_seed' / f'rep_{i:04d}.json').read_text(encoding='utf-8')) for i in range(r)]


def judgment_3se(reps, order, name, upper):
    """Primary rule of J7: an address is 'below the bound' if mean + 3 SE < upper."""
    X = np.array([[rec[f'X_{name}'] for rec in rep] for rep in reps], dtype=np.float64) / 1e6
    acc = np.array([rec['accepted'] for rec in reps[0]])
    R = len(reps)
    mean = X.mean(axis=0)
    se = X.std(axis=0, ddof=1) / np.sqrt(R)
    idx = np.flatnonzero(acc > 0)
    below = mean[idx] + 3 * se[idx] < upper
    i_max = idx[int(np.argmax(mean[idx]))]
    return dict(upper=upper, M=int(len(idx)), below_3se=int(below.sum()), not_below_3se=int((~below).sum()),
                not_below_addresses=[order[i] for i in idx[~below]],
                max_mean=float(mean[i_max]), se_at_max=float(se[i_max]), address_at_max=order[i_max],
                max_mean_plus_3se=float((mean[idx] + 3 * se[idx]).max()), max_se=float(se[idx].max()))


def cmd_analyze(a):
    out = Path(a.out)
    R, reps = load_replicates(out)
    if R < 20:
        dd.write_json(out / 'summary.json', dict(R=R, note='fewer than 20 complete replicates; no judgment'))
        raise SystemExit(f'only {R} complete replicates')
    order = [rec['address'] for rec in reps[0]]
    cond = inputs.load_conditions(a.conditions_file)
    top400, alla, groups, hashes, c_detail, rank = replay.build_groups(cond, Path(a.reference_dir))
    meta = {x: dict(rank=rank.get(x)) for x in order}
    exact = json.loads((out / 'exact_expectation.json').read_text(encoding='utf-8'))
    up = dd.UPPER_MAIN
    uppers_by = {v: dict(design_0_5=up) for v in VARIANTS}
    uppers_by['narrow_p035'] = dict(true_0_5714=dd.UPPER_BETA_TRUE, design_0_5=up)
    summary = dict(R=R, registered_R=a.replicates, variants=list(VARIANTS))
    # code checks over all replicates
    summary['monotone_violations'] = int(sum(len(monotone_violations(rep)) for rep in reps))
    det_cmp = []
    for r in range(min(R, DET_COMPARE_REPS)):
        det_file = Path(a.det_per_seed) / f'rep_{r:03d}.json'
        det_cmp.append(compare_full_to_det(reps[r], det_file)['different'] if det_file.exists() else None)
    summary['full_vs_det'] = dict(replicates_compared=sum(x is not None for x in det_cmp),
                                  replicates_missing=sum(x is None for x in det_cmp),
                                  addresses_different=int(sum(x for x in det_cmp if x)))
    for name in VARIANTS:
        res, rows = dd.analyze_variant(name, reps, order, meta, exact, uppers_by[name])
        res['judgment_3se'] = {k: judgment_3se(reps, order, name, u) for k, u in uppers_by[name].items()}
        summary[name] = res
        with open(out / f'addresses_{name}.csv', 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator='\n')
            w.writeheader()
            w.writerows(rows)
    # narrow against full, per address
    Xn = np.array([[rec['X_narrow'] for rec in rep] for rep in reps], dtype=np.float64) / 1e6
    Xf = np.array([[rec['X_full'] for rec in rep] for rep in reps], dtype=np.float64) / 1e6
    acc = np.array([rec['accepted'] for rec in reps[0]])
    idx = np.flatnonzero(acc > 0)
    d = Xn.mean(axis=0)[idx] - Xf.mean(axis=0)[idx]
    summary['narrow_minus_full'] = dict(dist=dd.dist(d), addresses_equal=int((np.abs(d) < 1e-12).sum()))
    dd.write_json(out / 'summary.json', summary)
    m = summary['narrow']
    j = m['judgment_3se']['design_0_5']
    line = (f"narrow freeze R={R}: upper 0.5 reference mean+3SE below {j['below_3se']}/{j['M']}, not {j['not_below_3se']}; "
            f"mean+2SE rule upper within {m['N_design_0_5']}/{m['M']}; E[X] max {m['max_mean']:.6f} USDC "
            f"(SE {j['se_at_max']:.6f})")
    (out / 'J7_summary_ko.md').write_text(line + '\n', encoding='utf-8')
    print(line)
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
        s.add_argument('--det-per-seed', required=True)
        s.add_argument('--replicates', type=int, default=1000)
        s.add_argument('--jobs', type=int, default=4)
    a = p.parse_args(argv)
    check_prereg(a.prereg, a.prereg_hash_file)
    if a.cmd == 'run':
        return cmd_run(a)
    return cmd_analyze(a)


if __name__ == '__main__':
    sys.exit(main())
