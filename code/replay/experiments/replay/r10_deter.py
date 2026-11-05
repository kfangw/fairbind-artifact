#!/usr/bin/env python3
"""Fraud replay under the edition-10 release (release10, --release fixed10) with s = 1 (registration R10).

    r10_deter.py run --settlements LIST.csv --reference-dir REF --conditions-file COND.json --out OUT
                     [--replicates 500] [--jobs 4] [--registered-list-sha256 HEX]
    r10_deter.py analyze --out OUT

The replay and the seeds are those of d2_deter.py (registration DET, the configuration of the main result: V 0.2,
auto-zero-reject, condition 1, replicate r has seed run_seed(base_seed, seed_scope, 1, r)): every replayed address
sells only fraudulent goods. With the detection floor s = 1 of tiers 0 and 1 every sampled sale fails: its proof
is missing at the deadline M_e + T_p and the release call processes the failure at M_e + T_p + 1. The replicates
differ only in the sampling beacon. X (released fraudulent proceeds) of an address is release10.fraud_x: the
sales not accepted by their buyer, settled before the first sampled sale, paid by the end of the window.

Variants: the buyer acceptance share a = 0 ('r10', the main variant), 0.5 ('r10_a05') and 0.9 ('r10_a09'); the
acceptance rule is the fixed hash of release10, so the replicates share the accepted sets. The bound of theorem 1
is V / s = 0.2 USDC for every variant. The closed form E[X] = sum_j v_j 1{not accepted_j} 1{R_j <= end}
prod_{l: s_l <= s_j} (1 - pi_l) is written for replicate 0.

Output: OUT/per_seed/rep_NNNN.json (one record per address: rep, seed, address, accepted, accepted_value, sampled,
X_<variant>, f_<variant> in atomic units, f = -1 without a failure in the window), OUT/exact_expectation.json,
OUT/run_log.txt, OUT/status.json; `analyze` writes OUT/summary.json and OUT/addresses_<variant>.csv.
"""
import argparse
import csv
import json
import math
import os
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import numpy as np  # noqa: E402

import d2_deter as dd  # noqa: E402
import engine  # noqa: E402
import release10  # noqa: E402

VARIANTS = {'r10': 0, 'r10_a05': 500_000, 'r10_a09': 900_000}
UPPER = 0.2                      # V / s, USDC
TAIL_X = [round(0.01 * i, 2) for i in range(1, 101)]   # x = 0.01 .. 1.00 USDC
_CTX = None


def x_variants(arr, timing, epoch_start, epoch_blocks, end, address, want_exact=False):
    """{variant: (X, f)} and, with want_exact, {variant: closed form} for one address (arrays from replay_address)."""
    blocks, values, epochs, smp = arr['blocks'], arr['values'], arr['epochs'], arr['sampled']
    out, exact = {}, {}
    for name, ppm in VARIANTS.items():
        t = release10.Timing10(**dict(timing.describe(), accept_ppm=ppm))
        signed, acc = release10.buyer_flags(address, arr['rows'], t)
        rel, _ = release10.epoch_release(blocks, epochs, smp, acc, signed, epoch_start, epoch_blocks, t)
        x, f, _ = release10.fraud_x(blocks, values, rel, epochs, smp, acc, epoch_start, epoch_blocks, t, end)
        out[name] = (x, f)
        if want_exact:
            exact[name] = release10.exact_expectation(blocks, values, arr['s_prob'], rel, acc, end) / 1e6
    return out, exact


class Context(dd.Context):
    """The configuration of the DET main result, replayed with the edition-10 release (main path values)."""

    def __init__(self, a):
        super().__init__(a)
        timing = release10.Timing10(accept_over_cap=bool(getattr(a, 'accept_over_cap', False)),
                                    seller_epoch_k=int(getattr(a, 'seller_epoch_k', 1) or 1),
                                    dispute_from=getattr(a, 'dispute_from', None) or 'settlement',
                                    anchor_delay=int(getattr(a, 'anchor_delay', None) or 100))
        self.release = release10.Release10(timing=timing)
        release10.check_epoch_length(self.release.timing, self.p['epochBlocks'])

    def epoch_start(self, e):
        return self.p['epochOrigin'] + e * self.p['epochBlocks'] - self.local_origin + self.start

    def replay_one(self, address, seed):
        d2, caps, p = self.d2, self.caps[address], self.p
        return engine.replay_address(
            address, self.data.per[address], seed=seed, p=p, capacity=caps['capacity'], scale=self.scale[address],
            origin_ledger=self.start, local_origin=self.local_origin, end_ledger=self.end,
            block_size=self.data.block_size, window_blocks=self.window, first_seconds=self.data.first_seconds,
            observed=True, cap=d2.vmax, sample_tau=d2.vmax, rounding=d2.rounding,
            segments=self.segments.get(address), refill_ppm=caps['refill_ppm'], align=d2.align,
            hour_blocks=d2.hour_blocks, block_seconds=d2.block_seconds, release=self.release,
            unlimited=caps.get('unlimited', False))


def one_replicate(ctx, rep, want_exact=False):
    seed = ctx.seed_of(rep)
    out, exact = [], {}
    for a in ctx.groups['replayed']:
        row, arr = ctx.replay_one(a, seed)
        m, ex = x_variants(arr, ctx.release.timing, ctx.epoch_start, ctx.p['epochBlocks'], ctx.end, a,
                           want_exact=want_exact and row['accepted_count'] > 0)
        rec = dict(rep=rep, seed=seed, address=a, accepted=int(row['accepted_count']),
                   accepted_value=int(row['accepted_value']), sampled=int(row['sample_count']))
        for name in VARIANTS:
            rec[f'X_{name}'], rec[f'f_{name}'] = m[name]
        out.append(rec)
        if ex:
            exact[a] = dict(ex, hold_value_mean=row.get('hold_value_mean'), hold_p90=row.get('hold_p90'))
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
        dd.write_json(out / 'exact_expectation.json', dict(release10=ctx.release.describe(), variants=VARIANTS,
                                                           sales_cap=ctx.args.sales_cap, addresses=exact))
        dd.write_json(seed0, recs)
    todo = [r for r in range(1, a.replicates) if not (out / 'per_seed' / f'rep_{r:04d}.json').exists()]
    done0 = a.replicates - len(todo)
    dd.log(out, f'replicates to compute: {len(todo)} (R = {a.replicates}, already done {done0}), jobs {a.jobs}')
    write_status(out, R=a.replicates, done=done0, jobs=a.jobs, state='running', pid=os.getpid())
    import multiprocessing
    t_loop = time.time()
    n = 0
    if todo:
        with multiprocessing.get_context('fork').Pool(a.jobs) as pool:
            for r, secs, mem in pool.imap_unordered(_worker, todo, chunksize=1):
                n += 1
                dd.log(out, f'replicate {r} done in {secs} s (worker peak {mem} MiB)')
                per = (time.time() - t_loop) / n
                write_status(out, R=a.replicates, done=done0 + n, jobs=a.jobs, last=r, state='running',
                             pid=os.getpid(), eta_hours=round(per * (len(todo) - n) / 3600, 2))
    write_status(out, R=a.replicates, done=a.replicates, jobs=a.jobs, state='finished', pid=os.getpid())
    dd.log(out, 'all replicates finished')
    return 0


def load(out, replicates=None):
    files = sorted((Path(out) / 'per_seed').glob('rep_*.json'))
    if replicates is not None:
        files = files[:replicates]
    reps = [json.loads(p.read_text()) for p in files]
    for i, rep in enumerate(reps):
        if any(e['rep'] != i for e in rep):
            raise SystemExit(f'replicate file {files[i].name} out of order')
    return reps


def tail_counts(X, idx, upper):
    """Points (address x TAIL_X) where P^(X >= x) exceeds exp(-x / upper): by the estimate, by more than 3 SE, and
    by a one-sided binomial test at the Bonferroni level 0.05 / points (normal approximation)."""
    R = X.shape[0]
    pts = len(idx) * len(TAIL_X)
    z = abs(_norm_ppf(0.05 / max(pts, 1)))
    over = over3 = overb = 0
    worst = 0.0
    for i in idx:
        col = X[:, i]
        for x in TAIL_X:
            b = math.exp(-x / upper)
            p = float((col >= x - 1e-12).mean())
            se = math.sqrt(max(p * (1 - p), 0.0) / R)
            sb = math.sqrt(b * (1 - b) / R)
            over += p > b
            over3 += p > b + 3 * se
            overb += (p - b) > z * sb
            worst = max(worst, p - b)
    return dict(points=pts, above_bound=int(over), above_bound_3se=int(over3), above_bound_bonferroni=int(overb),
                max_excess=worst, bound='exp(-x / (V / s)) with V / s = 0.2 USDC', x_grid=[TAIL_X[0], TAIL_X[-1], 0.01])


def _norm_ppf(q):
    """Inverse standard normal (Acklam's rational approximation), enough for a test threshold."""
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    if q < 0.02425:
        t = math.sqrt(-2 * math.log(q))
        return (((((c[0] * t + c[1]) * t + c[2]) * t + c[3]) * t + c[4]) * t + c[5]) / \
            ((((d[0] * t + d[1]) * t + d[2]) * t + d[3]) * t + 1)
    if q > 1 - 0.02425:
        return -_norm_ppf(1 - q)
    t = q - 0.5
    r = t * t
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * t / \
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def cmd_analyze(a):
    out = Path(a.out)
    reps = load(out, a.replicates)
    R = len(reps)
    order = [e['address'] for e in reps[0]]
    acc = np.array([e['accepted'] for e in reps[0]])
    exact = json.loads((out / 'exact_expectation.json').read_text())
    summary = dict(R=R, addresses=len(order), with_sales=int((acc > 0).sum()), release10=exact['release10'],
                   upper=UPPER)
    idx = np.flatnonzero(acc > 0)
    for name in VARIANTS:
        X = np.array([[e[f'X_{name}'] for e in rep] for rep in reps], dtype=np.float64) / 1e6
        F = np.array([[e[f'f_{name}'] for e in rep] for rep in reps])
        mean = X.mean(axis=0)
        se = X.std(axis=0, ddof=1) / np.sqrt(R) if R > 1 else np.zeros(len(order))
        ex = np.array([exact['addresses'].get(x, {}).get(name, np.nan) for x in order])
        res = dict(M=int(len(idx)), below_3se=int((mean[idx] + 3 * se[idx] < UPPER).sum()),
                   above_3se=int((mean[idx] - 3 * se[idx] > UPPER).sum()),
                   above_bound_no_se=int((mean[idx] > UPPER).sum()),
                   max_mean=float(mean[idx].max()) if len(idx) else None,
                   mean_of_means=float(mean[idx].mean()) if len(idx) else None,
                   max_X=float(X[:, idx].max()) if len(idx) else None,
                   p_fail_mean=float((F[:, idx] >= 0).mean()) if len(idx) else None)
        if len(idx):
            e = ex[idx]
            res.update(max_exact=float(np.nanmax(e)), exact_above_upper=int((e > UPPER).sum()),
                       exact_outside_3se=int((np.abs(mean[idx] - e) > 3 * se[idx] + 1e-12).sum()))
            res['tail'] = tail_counts(X, idx, UPPER)
        summary[name] = res
        with open(out / f'addresses_{name}.csv', 'w', newline='') as fh:
            w = csv.writer(fh, lineterminator='\n')
            w.writerow(['address', 'accepted', 'mean_X', 'se', 'max_X', 'p_fail', 'exact_X'])
            for i, x in enumerate(order):
                w.writerow([x, int(acc[i]), repr(float(mean[i])), repr(float(se[i])), repr(float(X[:, i].max())),
                            repr(float((F[:, i] >= 0).mean())), '' if np.isnan(ex[i]) else repr(float(ex[i]))])
    dd.write_json(out / 'summary.json', summary)
    print(json.dumps(summary, indent=1)[:4000])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='r10_deter.py')
    sub = ap.add_subparsers(dest='command', required=True)
    r = sub.add_parser('run')
    r.add_argument('--settlements', required=True)
    r.add_argument('--reference-dir', required=True)
    r.add_argument('--conditions-file', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--replicates', type=int, default=500)
    r.add_argument('--jobs', type=int, default=4)
    r.add_argument('--registered-list-sha256', default=None)
    r.add_argument('--sales-cap', default='auto-zero-reject',
                   help='R11: none (no bucket, the rule as written) or auto-zero-reject (R10, legacy bucket)')
    r.add_argument('--accept-over-cap', action='store_true', help='R11: admit sales above V, sampled with probability 1')
    r.add_argument('--seller-epoch-k', type=int, default=1, help='R11: profile epochs per seller epoch (default 1)')
    r.add_argument('--anchor-delay', type=int, default=100,
                   help='R11: a_A, A_e = last epoch block + a_A (default 100, the R10 value; v0.7c proposes 120)')
    r.add_argument('--dispute-from', choices=release10.DISPUTE_FROM, default='settlement',
                   help='R11: dispute windows from the settlement (R10) or the anchor deadline (v0.6)')
    s = sub.add_parser('analyze')
    s.add_argument('--out', required=True)
    s.add_argument('--replicates', type=int, default=None, help='use the first N replicate files (default: all)')
    a = ap.parse_args(argv)
    return cmd_run(a) if a.command == 'run' else cmd_analyze(a)


if __name__ == '__main__':
    sys.exit(main())
