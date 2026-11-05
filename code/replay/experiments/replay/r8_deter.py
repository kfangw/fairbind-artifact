#!/usr/bin/env python3
"""Fraud replay under the release cursor of rule edition 8 (D2-39) with the narrow freeze (D2-6 (a) 2).

    r8_deter.py run --settlements LIST.csv --reference-dir REF --conditions-file COND.json --out OUT
                    [--replicates 1000] [--jobs 4] [--case-length N] [--registered-list-sha256 HEX]
    r8_deter.py analyze --out OUT [--j7-narrow J7_OUT/addresses_narrow.csv]

The replay, the fraud model and the seeds are those of d2_deter.py and d2_deter_narrow.py (registrations DET and
J7): every replayed address sells only fraudulent goods, a sampled case is detected with probability p0 (the same
uniform numbers, tag 'deter'), a detected case fails `confirm_delay` blocks after its opening, and the account
stops at the first failure f. Only the release changes: a sale is paid when the release cursor passes its epoch
(release8.epoch_release on the replay's prompt path), not at s + T_hold.

X (released proceeds) of one episode: without a failure inside the window, the sales with release R <= end; with a
failure at f whose failed sampled sale settled at c, the sales settled before c with R' <= end, where R' is R except
that the epoch of c cannot be passed before its failed case is final (R' = max(R, f + 1 + keeper delay)). No sale
settled at or after c is paid before f: its epoch is that of c or later, and the cursor waits for the failed case.

Variants: 'r8' (p0 0.40), 'r8_p035' (p0 0.35, same draws), and 'narrow7' (the J7 variant 'narrow', hold 31,073,
the same draws; its per-address means must equal the stored J7 output, a check that the release switch leaves the
replay unchanged). With the case length equal to the confirmation delay (the default) the expectation of 'r8' has
the closed form sum_j v_j 1{R_j <= end} prod_{l: s_l <= s_j} (1 - p0 s(v_l)), written for replicate 0.

Output: OUT/per_seed/rep_NNNN.json (one record per address: rep, seed, address, accepted, accepted_value, sampled,
X_<variant>, f_<variant> in atomic units, f = -1 without a failure), OUT/exact_expectation.json, OUT/run_log.txt,
OUT/status.json; `analyze` writes OUT/summary.json and OUT/addresses_<variant>.csv.
"""
import argparse
import csv
import json
import os
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import d2_deter as dd  # noqa: E402
import d2_deter_narrow as dn  # noqa: E402
import engine  # noqa: E402
import release8  # noqa: E402

VARIANTS = ('r8', 'r8_p035', 'narrow7')
UPPER = {'r8': 0.5, 'r8_p035': 0.5, 'narrow7': 0.5}
_CTX = None


# ---------------------------------------------------------------- the model (pure functions)

def released_value_cursor(blocks, values, release, epochs, f, c, end, keeper_delay=0):
    """X under the cursor and the narrow freeze for sorted `blocks` and their `release` and `epochs`."""
    blocks = np.asarray(blocks, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)
    release = np.asarray(release, dtype=np.int64)
    if f is None:
        return int(values[release <= end].sum())
    before = blocks < c
    if not before.any():
        return 0
    e_c = int(np.asarray(epochs)[np.searchsorted(blocks, c, side='left')])
    r = np.where(np.asarray(epochs) == e_c, np.maximum(release, f + 1 + keeper_delay), release)
    return int(values[before & (r <= end)].sum())


def exact_expectation_cursor(blocks, values, s_prob, release, p0, end):
    """sum_j v_j 1{R_j <= end} prod_{l: s_l <= s_j} (1 - p0 s_l), exact when a failed case ends where a passed one
    does (case length = confirmation delay)."""
    blocks = np.asarray(blocks, dtype=np.int64)
    q = 1.0 - p0 * np.asarray(s_prob, dtype=np.float64)
    prefix = np.r_[1.0, np.cumprod(q)]
    k = np.searchsorted(blocks, blocks, side='right')
    return float((np.asarray(values, dtype=np.float64) * (np.asarray(release) <= end) * prefix[k]).sum())


def model_address(arr, *, seed, address, delay, hold, end, keeper_delay=0):
    """{variant: (X atomic, f or -1)} for one address and one replay (`arr` from engine.replay_address with a
    cursor release)."""
    blocks, values, release, epochs = arr['blocks'], arr['values'], arr['release'], arr['epochs']
    cases, case_settled = arr['cases'], arr['case_settled']
    u = dd.draw_u(seed, 'deter', address, len(cases))
    out = {}
    for name, p0 in (('r8', dd.P0_MAIN), ('r8_p035', dd.P0_BETA)):
        f, c = dn.first_failure_narrow(cases, dd.detections(u, p0), case_settled, delay, end)
        out[name] = (released_value_cursor(blocks, values, release, epochs, f, c, end, keeper_delay),
                     -1 if f is None else f)
    f, c = dn.first_failure_narrow(cases, dd.detections(u, dd.P0_MAIN), case_settled, delay, end)
    out['narrow7'] = (dn.released_value_narrow(blocks, values, f, c, hold, end), -1 if f is None else f)
    return out


# ---------------------------------------------------------------- replay

class Context(dd.Context):
    """The configuration of the DET / J7 main result, replayed with the cursor release."""

    def __init__(self, a):
        super().__init__(a)
        case_length = self.delay if a.case_length is None else a.case_length
        self.release = release8.Release8(timing=release8.CursorTiming(case_length=case_length,
                                                                      keeper_delay=a.keeper_delay))

    def replay_one(self, address, seed):
        d2, caps, p = self.d2, self.caps[address], self.p
        return engine.replay_address(
            address, self.data.per[address], seed=seed, p=p, capacity=caps['capacity'], scale=self.scale[address],
            origin_ledger=self.start, local_origin=self.local_origin, end_ledger=self.end,
            block_size=self.data.block_size, window_blocks=self.window, first_seconds=self.data.first_seconds,
            observed=True, cap=d2.vmax, sample_tau=d2.vmax, rounding=d2.rounding,
            segments=self.segments.get(address), refill_ppm=caps['refill_ppm'], align=d2.align,
            hour_blocks=d2.hour_blocks, block_seconds=d2.block_seconds, release=self.release)


def one_replicate(ctx, rep, want_exact=False):
    seed = ctx.seed_of(rep)
    out, exact = [], {}
    kd = ctx.release.timing.keeper_delay
    for a in ctx.groups['replayed']:
        row, arr = ctx.replay_one(a, seed)
        m = model_address(arr, seed=seed, address=a, delay=ctx.delay, hold=ctx.hold, end=ctx.end, keeper_delay=kd)
        rec = dict(rep=rep, seed=seed, address=a, accepted=int(row['accepted_count']),
                   accepted_value=int(row['accepted_value']), sampled=int(row['sample_count']))
        for name in VARIANTS:
            rec[f'X_{name}'], rec[f'f_{name}'] = m[name]
        out.append(rec)
        if want_exact and row['accepted_count'] > 0:
            exact[a] = dict(
                r8=exact_expectation_cursor(arr['blocks'], arr['values'], arr['s_prob'], arr['release'], dd.P0_MAIN,
                                            ctx.end) / 1e6,
                narrow7=dn.exact_expectation_narrow(arr['blocks'], arr['values'], arr['s_prob'],
                                                    dd.sale_open_blocks(arr['blocks'], ctx.p, ctx.start,
                                                                        ctx.local_origin) + ctx.delay,
                                                    dd.P0_MAIN, ctx.hold, ctx.end) / 1e6,
                hold_value_mean=row.get('hold_value_mean'), hold_p90=row.get('hold_p90'))
    return out, exact


def _worker(rep):
    t0 = time.time()
    recs, _ = one_replicate(_CTX, rep)
    path = Path(_CTX.args.out) / 'per_seed' / f'rep_{rep:04d}.json'
    dd.write_json(f'{path}.tmp', recs)
    os.replace(f'{path}.tmp', path)
    return rep, round(time.time() - t0, 1), round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)


def write_status(out, **kw):
    st = dict(updated_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **kw)
    p = Path(out) / 'status.json'
    dd.write_json(f'{p}.tmp', st)
    os.replace(f'{p}.tmp', p)


def cmd_run(a):
    global _CTX
    out = Path(a.out)
    (out / 'per_seed').mkdir(parents=True, exist_ok=True)
    if a.registered_list_sha256:
        got = dd.sha256_file(a.settlements)
        if got != a.registered_list_sha256:
            raise SystemExit(f'settlement list hash {got} is not the registered {a.registered_list_sha256}')
    ctx = _CTX = Context(a)
    dd.log(out, f'inputs loaded in {ctx.load_seconds:.0f} s; replayed addresses {len(ctx.groups["replayed"])}; '
                f'release {ctx.release.describe()}')
    seed0 = out / 'per_seed' / 'rep_0000.json'
    if not seed0.exists():
        recs, exact = one_replicate(ctx, 0, want_exact=True)
        dd.write_json(out / 'exact_expectation.json', dict(release8=ctx.release.describe(),
                                                           closed_form_exact=ctx.release.timing.case_length == ctx.delay,
                                                           addresses=exact))
        dd.write_json(seed0, recs)
    todo = [r for r in range(1, a.replicates) if not (out / 'per_seed' / f'rep_{r:04d}.json').exists()]
    done0 = a.replicates - len(todo)
    dd.log(out, f'replicates to compute: {len(todo)} (R = {a.replicates}, already done {done0}), jobs {a.jobs}')
    write_status(out, R=a.replicates, done=done0, jobs=a.jobs, state='running', pid=os.getpid())
    import multiprocessing
    t_loop = time.time()
    n = 0
    with multiprocessing.get_context('fork').Pool(a.jobs) as pool:
        for r, secs, mem in pool.imap_unordered(_worker, todo, chunksize=1):
            n += 1
            dd.log(out, f'replicate {r} done in {secs} s (worker peak {mem} MiB)')
            per = (time.time() - t_loop) / n
            write_status(out, R=a.replicates, done=done0 + n, jobs=a.jobs, last=r, state='running', pid=os.getpid(),
                         eta_hours=round(per * (len(todo) - n) / 3600, 2))
    write_status(out, R=a.replicates, done=a.replicates, jobs=a.jobs, state='finished', pid=os.getpid())
    dd.log(out, 'all replicates finished')
    return 0


# ---------------------------------------------------------------- analysis (E1 under the cursor)

def load(out):
    files = sorted((Path(out) / 'per_seed').glob('rep_*.json'))
    reps = [json.loads(p.read_text()) for p in files]
    for i, rep in enumerate(reps):
        if any(e['rep'] != i for e in rep):
            raise SystemExit(f'replicate file {files[i].name} out of order')
    return reps


def cmd_analyze(a):
    out = Path(a.out)
    reps = load(out)
    R = len(reps)
    order = [e['address'] for e in reps[0]]
    acc = np.array([e['accepted'] for e in reps[0]])
    exact = json.loads((out / 'exact_expectation.json').read_text())
    summary = dict(R=R, addresses=len(order), with_sales=int((acc > 0).sum()), release8=exact['release8'])
    for name in VARIANTS:
        X = np.array([[e[f'X_{name}'] for e in rep] for rep in reps], dtype=np.float64) / 1e6
        F = np.array([[e[f'f_{name}'] for e in rep] for rep in reps])
        mean = X.mean(axis=0)
        se = X.std(axis=0, ddof=1) / np.sqrt(R) if R > 1 else np.zeros(len(order))
        idx = np.flatnonzero(acc > 0)
        below = mean[idx] + 3 * se[idx] < UPPER[name]
        above = mean[idx] - 3 * se[idx] > UPPER[name]
        ex = np.array([exact['addresses'].get(x, {}).get(name if name != 'r8_p035' else '_', np.nan) for x in order])
        res = dict(upper=UPPER[name], M=int(len(idx)), below_3se=int(below.sum()), not_below_3se=int((~below).sum()),
                   above_3se=int(above.sum()), max_mean=float(mean[idx].max()) if len(idx) else None,
                   above_bound_no_se=int((mean[idx] > UPPER[name]).sum()),
                   mean_of_means=float(mean[idx].mean()) if len(idx) else None,
                   p_fail_mean=float((F[:, idx] >= 0).mean()) if len(idx) else None)
        if name in ('r8', 'narrow7') and len(idx):
            e = ex[idx]
            res.update(max_exact=float(np.nanmax(e)), exact_above_upper=int((e > UPPER[name]).sum()),
                       exact_outside_3se=int((np.abs(mean[idx] - e) > 3 * se[idx] + 1e-12).sum()))
        summary[name] = res
        with open(out / f'addresses_{name}.csv', 'w', newline='') as fh:
            w = csv.writer(fh, lineterminator='\n')
            w.writerow(['address', 'accepted', 'mean_X', 'se', 'max_X', 'p_fail', 'exact_X'])
            for i, x in enumerate(order):
                w.writerow([x, int(acc[i]), repr(float(mean[i])), repr(float(se[i])), repr(float(X[:, i].max())),
                            repr(float((F[:, i] >= 0).mean())), '' if np.isnan(ex[i]) else repr(float(ex[i]))])
    if a.j7_narrow:
        with open(a.j7_narrow, newline='') as fh:
            j7 = {r['address']: r for r in csv.DictReader(fh)}
        X = np.array([[e['X_narrow7'] for e in rep] for rep in reps], dtype=np.float64) / 1e6
        mean = X.mean(axis=0)
        diffs = [abs(mean[i] - float(j7[x]['mean_X'])) for i, x in enumerate(order) if x in j7]
        summary['narrow7_vs_j7'] = dict(addresses=len(diffs), missing=[x for x in order if x not in j7],
                                        max_abs_diff=max(diffs) if diffs else None,
                                        equal=bool(diffs) and max(diffs) < 1e-9 and R == 1000)
    dd.write_json(out / 'summary.json', summary)
    print(json.dumps(summary, indent=1)[:4000])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='r8_deter.py')
    sub = ap.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--settlements', required=True)
    r.add_argument('--reference-dir', required=True)
    r.add_argument('--conditions-file', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--replicates', type=int, default=1000)
    r.add_argument('--jobs', type=int, default=4)
    r.add_argument('--case-length', type=int, default=None, help='default: the confirmation delay')
    r.add_argument('--keeper-delay', type=int, default=0)
    r.add_argument('--registered-list-sha256', default=None)
    s = sub.add_parser('analyze')
    s.add_argument('--out', required=True)
    s.add_argument('--j7-narrow', default=None, help='J7 out/addresses_narrow.csv (the narrow7 check)')
    a = ap.parse_args(argv)
    return cmd_run(a) if a.command == 'run' else cmd_analyze(a)


if __name__ == '__main__':
    sys.exit(main())
