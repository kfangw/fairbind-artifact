#!/usr/bin/env python3
"""R13: FairBind's realized fraud payout on the R12 replay sales (registration R13_preregistration.md).

For every seller i of the judged set S1r of a window, every sale from a start sale j0 on is fraudulent (s = 1: a
sampled fraudulent sale has no passing proof by T_p and fails). The sampling is the ideal VRF of rule v0.8 R4 (a):
each sale j is sampled independently with probability pi_j = min(1, v_j / V). With c the first sampled fraudulent
sale (in list order),

  G   = sum of v_j over fraudulent sales j with block s_j < s_c      (paid to the seller: R7 (b) freezes the sales
                                                                      settled at or after s_c that are not yet paid)
  D   = 1 if some fraudulent sale of the window is sampled
  N   = max(0, G - V * D)                                             (net of the deduction b(V) = V, R7 (c))

and with no sampled fraudulent sale in the window, G = N = all fraudulent revenue of the window and D = 0.
The failure of c is processed at f_c = F + 300 e_c + 2,251 (M_e + T_p + 1, the profile epoch e_c of c), when the
account is suspended. Report-only splits: G_pre(k) (paid before f_c: seller epochs before that of c), G_post(k)
(paid at the cursor pass after f_c: earlier sales of the seller epoch of c), frozen (sales settled in [s_c, f_c)).

The start set J_i is the first sale of every profile epoch with a sale of i. Per seller and per quantity
m in {G, N}, the start is the one with the largest exact expectation E[m] (ties: the earliest). At that start the
exact distribution gives the mean and the quantiles, and R = 10,000 Monte Carlo replicates (per-sale uniforms,
fixed seeds) give the mean, median, 95th percentile and maximum, and the totals over sellers per replicate.

Commands:
  r13_sim.py run --raw RAW --r12 R12_RESULTS_DIR --out OUT --registration REG.md --seal REG.sha256
  r13_sim.py selfcheck --out DIR          (synthetic inputs only)
"""
import argparse
import csv
import hashlib
import json
import math
import sys
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

REGISTERED = {
    'V_atomic': 1_000_000,
    'b_atomic': 1_000_000,
    'epoch_blocks': 300,
    'delta_f': 2251,                 # 299 + a_A 120 + (M_e - A_e) 31 + T_p 1,800 + 1: f_c = F + 300 e_c + delta_f
    'k_grid': [1, 2, 4, 8, 16, 32],
    'replicates': 10_000,
    'seed': 20261030,
    'horizon': 50.0,                 # truncate a start's distribution where sum of pi from j0 reaches 50 (S <= e^-50)
    'mc_chunk': 512,
    'quantiles': {'median': 0.5, 'p95': 0.95},
    'scale': 86_400,
    'windows': ['median', 'busy'],
    'S1r_counts': {'median': 289, 'busy': 178},
    'lags': ['own', 'k1'],
    'inputs': {
        'median': {'sales_npz': '92a74193b21d2db38b47036d810afa445ccad528c11398f1cf835ccb7d3c60c1',
                   'sales_addresses': 'b19259d7ebeb37fde98c0fe6c3b9f021b2e28bb3883c10d663da05b182bb3635',
                   'r12_addr': '0c182d3006c97666e89f5801f6d542717b8286ae0bd3b956c6719c938a8f2bf8'},
        'busy': {'sales_npz': '5863e172f21144d076262fff4bca87f24b11ba2f984c040c5944c522ddd54a0e',
                 'sales_addresses': 'b19259d7ebeb37fde98c0fe6c3b9f021b2e28bb3883c10d663da05b182bb3635',
                 'r12_addr': 'b88714b5e5a63377ab7496fd4eab682ea50c47d7732ebcd61fa2cd2e9dd93459'},
        'r12_results': '3b372f03969dee99bbe4b78bf1dfba6352ffaae2946544f8842781858ebe71df',
    },
    'outputs': ['r13_results.json', 'r13_addr_median.csv', 'r13_addr_busy.csv', 'r13_totals_median.csv',
                'r13_totals_busy.csv', 'r13_tables.md', 'r13_inputs_sha256.txt'],
}

VERDICTS = {
    # name: (quantity m, statistic, comparator)
    'JF13': ('N', 'E', 'H'), 'JF13t': ('N', 't', 'H'), 'JF13s': ('N', 's', 'H'),
    'JF13r': ('N', 'E', 'Ru'), 'JF13rt': ('N', 't', 'Ru'), 'JF13rs': ('N', 's', 'Ru'),
    'JG13': ('G', 'E', 'H'), 'JG13t': ('G', 't', 'H'), 'JG13s': ('G', 's', 'H'),
    'JG13r': ('G', 'E', 'Ru'), 'JG13rt': ('G', 't', 'Ru'), 'JG13rs': ('G', 's', 'Ru'),
}

ADDR_COLUMNS = ['address', 'k_star', 'n_sales', 'revenue', 'n_starts',
                'start_G_block', 'start_N_block',
                'EG', 'EN', 'q50_G', 'q95_G', 'q50_N', 'q95_N', 'P_det_G', 'P_det_N',
                'E_frozen_N', 'E_undet_N', 'E_pre_kstar_N', 'E_post_kstar_N', 'E_pre_k1_N', 'E_post_k1_N',
                'mc_mean_G', 'mc_median_G', 'mc_p95_G', 'mc_max_G', 'mc_mean_N', 'mc_median_N', 'mc_p95_N',
                'mc_max_N', 'mc_se_G', 'mc_se_N', 'max_EG_any_start',
                'X_H_own', 'X_H_k1', 'X_Ru_own', 'X_Ru_k1']


# ---------------------------------------------------------------- helpers

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sample_quantile(x, q):
    """Lower empirical quantile: the element of rank ceil(q R) (1-based) of the sorted sample."""
    x = np.sort(np.asarray(x))
    r = max(1, math.ceil(q * len(x) - 1e-12))
    return x[r - 1]


def dist_quantile(values, probs, q):
    """min{x : P(X <= x) >= q} for a distribution given by non-decreasing support values and their probabilities."""
    cdf = np.cumsum(probs)
    i = int(np.searchsorted(cdf, q, side='left'))
    return values[min(i, len(values) - 1)]


# ---------------------------------------------------------------- one seller

class Seller:
    """Sales of one address sorted by (block, list row), with the prefix sums the formulas use."""

    def __init__(self, blocks, values, rows, first_block, epoch_blocks=300, V=1_000_000):
        order = np.lexsort((np.asarray(rows, dtype=np.int64), np.asarray(blocks, dtype=np.int64)))
        self.blocks = np.asarray(blocks, dtype=np.int64)[order]
        self.values = np.asarray(values, dtype=np.int64)[order]
        self.n = len(self.blocks)
        self.V = int(V)
        self.F = int(first_block)
        self.epoch_blocks = int(epoch_blocks)
        self.epochs = (self.blocks - self.F) // self.epoch_blocks
        self.pi = np.minimum(1.0, self.values.astype(np.float64) / self.V)
        self.prefv = np.r_[0, np.cumsum(self.values)].astype(np.int64)          # prefv[i] = sum v_l, l < i
        self.prefpi = np.r_[0.0, np.cumsum(self.pi)]
        self.fb = np.searchsorted(self.blocks, self.blocks, side='left')         # first index of the same block
        self.starts = np.flatnonzero(np.r_[True, self.epochs[1:] != self.epochs[:-1]]) if self.n else np.zeros(0, int)

    def revenue(self):
        return int(self.prefv[-1])

    def slice_end(self, j0, horizon):
        """Exclusive end of the sales whose first-sampled probability is kept; == n means the tail is exact."""
        target = self.prefpi[j0] + horizon
        idx = int(np.searchsorted(self.prefpi, target, side='left'))
        return min(self.n, idx)

    def distribution(self, j0, horizon=50.0, delta_f=2251, ks=(1,), full=True):
        """Exact distribution of the outcome for start j0: dict of arrays over the support (first sampled sale c in
        [j0, end), then the undetected atom when end == n), non-decreasing in G and in N. With full=False only p, G,
        N and det."""
        end = self.slice_end(j0, horizon)
        c = np.arange(j0, end)
        pis = self.pi[j0:end]
        surv = np.cumprod(1.0 - pis)
        prev = np.r_[1.0, surv[:-1]] if len(surv) else np.zeros(0)
        p = prev * pis
        lo = np.maximum(self.fb[c], j0)
        base = int(self.prefv[j0])
        G = (self.prefv[lo] - base).astype(np.int64)
        N = np.maximum(0, G - self.V)
        if not full:
            det = np.ones(len(c), dtype=bool)
            if end == self.n:
                W = int(self.prefv[self.n]) - base
                p = np.r_[p, float(surv[-1]) if len(surv) else 1.0]
                G, N, det = np.r_[G, W], np.r_[N, W], np.r_[det, False]
            return dict(p=p, G=G, N=N, det=det, end=end)
        f = self.F + self.epoch_blocks * self.epochs[c] + delta_f
        idx_f = np.searchsorted(self.blocks, f, side='left')
        frozen = (self.prefv[idx_f] - self.prefv[lo]).astype(np.int64)
        pre = {}
        for k in ks:
            se_first = np.searchsorted(self.epochs, (self.epochs[c] // k) * k, side='left')
            cut = np.maximum(np.minimum(se_first, lo), j0)
            pre[k] = (self.prefv[cut] - base).astype(np.int64)
        det = np.ones(len(c), dtype=bool)
        if end == self.n:
            p_und = float(surv[-1]) if len(surv) else 1.0
            W = int(self.prefv[self.n]) - base
            p = np.r_[p, p_und]
            G = np.r_[G, W]
            N = np.r_[N, W]
            frozen = np.r_[frozen, 0]
            for k in ks:
                pre[k] = np.r_[pre[k], 0]
            det = np.r_[det, False]
        return dict(p=p, G=G, N=N, frozen=frozen, pre=pre, det=det, end=end)

    def expectations(self, j0, horizon=50.0):
        """(E[G], E[N]) for start j0, from the exact distribution (float, atomic units)."""
        d = self.distribution(j0, horizon=horizon, full=False)
        return float(np.dot(d['p'], d['G'])), float(np.dot(d['p'], d['N']))

    def outcome(self, j0, c, delta_f=2251, ks=(1,)):
        """Outcome for start j0 and first sampled fraudulent sale c (c == n: none sampled)."""
        base = int(self.prefv[j0])
        if c >= self.n:
            W = int(self.prefv[self.n]) - base
            return dict(det=False, G=W, N=W, frozen=0, pre={k: 0 for k in ks})
        lo = max(int(self.fb[c]), j0)
        G = int(self.prefv[lo]) - base
        f = self.F + self.epoch_blocks * int(self.epochs[c]) + delta_f
        idx_f = int(np.searchsorted(self.blocks, f, side='left'))
        pre = {}
        for k in ks:
            se_first = int(np.searchsorted(self.epochs, (int(self.epochs[c]) // k) * k, side='left'))
            pre[k] = int(self.prefv[max(min(se_first, lo), j0)]) - base
        return dict(det=True, G=G, N=max(0, G - self.V), frozen=int(self.prefv[idx_f]) - int(self.prefv[lo]), pre=pre)

    def first_sampled(self, j0, R, rng, chunk=512):
        """Index of the first sampled sale >= j0 for R replicates (n when none): per-sale uniforms U_j < pi_j, drawn
        in sale order, chunk by chunk, for the replicates still without a sampled sale (row order = replicate order)."""
        c = np.full(R, self.n, dtype=np.int64)
        active = np.arange(R)
        pos = j0
        while active.size and pos < self.n:
            hi = min(self.n, pos + chunk)
            U = rng.random((active.size, hi - pos))
            hit = U < self.pi[pos:hi]
            anyhit = hit.any(axis=1)
            first = hit.argmax(axis=1)
            c[active[anyhit]] = pos + first[anyhit]
            active = active[~anyhit]
            pos = hi
        return c

    def mc(self, j0, R, rng, chunk=512):
        """(G, N) arrays over R replicates."""
        c = self.first_sampled(j0, R, rng, chunk=chunk)
        base = int(self.prefv[j0])
        W = int(self.prefv[self.n]) - base
        det = c < self.n
        cc = np.where(det, c, 0)
        lo = np.maximum(self.fb[cc], j0)
        G = np.where(det, self.prefv[lo] - base, W).astype(np.int64)
        N = np.where(det, np.maximum(0, G - self.V), G).astype(np.int64)
        return G, N


def rng_for(seed, widx, pos, j0):
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([int(seed), int(widx), int(pos), int(j0)])))


def worst_start(seller, horizon):
    """Per quantity, the start with the largest exact expectation (ties: the earliest) and all start expectations."""
    EG = np.zeros(len(seller.starts))
    EN = np.zeros(len(seller.starts))
    for t, j0 in enumerate(seller.starts):
        EG[t], EN[t] = seller.expectations(int(j0), horizon=horizon)
    tG = int(np.argmax(EG)) if len(EG) else -1     # argmax returns the first maximum
    tN = int(np.argmax(EN)) if len(EN) else -1
    return tG, tN, EG, EN


def seller_cells(seller, k_star, widx, pos, reg=REGISTERED):
    """Every per-seller cell (atomic units) and the MC replicate arrays of G and N at their worst starts."""
    V, R, H, df = reg['V_atomic'], reg['replicates'], reg['horizon'], reg['delta_f']
    tG, tN, EG_all, EN_all = worst_start(seller, H)
    out = dict(k_star=int(k_star), n_sales=seller.n, revenue=seller.revenue(), n_starts=len(seller.starts))
    reps = {}
    draws = {}
    for m, t in (('G', tG), ('N', tN)):
        j0 = int(seller.starts[t])
        ks = tuple(sorted({1, int(k_star)}))
        d = seller.distribution(j0, horizon=H, delta_f=df, ks=ks)
        vals = d[m]
        out[f'start_{m}_block'] = int(seller.blocks[j0])
        out[f'E{m}'] = float(np.dot(d['p'], vals))
        out[f'q50_{m}'] = int(dist_quantile(vals, d['p'], reg['quantiles']['median']))
        out[f'q95_{m}'] = int(dist_quantile(vals, d['p'], reg['quantiles']['p95']))
        out[f'P_det_{m}'] = float(d['p'][d['det']].sum())
        if m == 'N':
            out['E_frozen_N'] = float(np.dot(d['p'], d['frozen']))
            out['E_undet_N'] = float(np.dot(d['p'][~d['det']], d['G'][~d['det']]))
            for lab, k in (('kstar', int(k_star)), ('k1', 1)):
                pre = np.where(d['det'], d['pre'][k], 0)
                post = np.where(d['det'], d['G'] - d['pre'][k], 0)
                out[f'E_pre_{lab}_N'] = float(np.dot(d['p'], pre))
                out[f'E_post_{lab}_N'] = float(np.dot(d['p'], post))
        if j0 not in draws:
            draws[j0] = seller.mc(j0, R, rng_for(reg['seed'], widx, pos, j0), chunk=reg['mc_chunk'])
        g, n = draws[j0]
        x = g if m == 'G' else n
        reps[m] = x
        out[f'mc_mean_{m}'] = float(x.mean())
        out[f'mc_median_{m}'] = int(sample_quantile(x, reg['quantiles']['median']))
        out[f'mc_p95_{m}'] = int(sample_quantile(x, reg['quantiles']['p95']))
        out[f'mc_max_{m}'] = int(x.max())
        out[f'mc_se_{m}'] = float(x.std(ddof=1) / math.sqrt(R)) if R > 1 else 0.0
    out['max_EG_any_start'] = float(EG_all.max())
    out['theorem_ok'] = bool((EG_all <= V * (1 + 1e-9)).all())
    return out, reps


# ---------------------------------------------------------------- inputs

def load_window(raw, r12dir, w, check_hashes=True):
    cdir = Path(raw) / f'{w}_r12cost' / 'k1' / 'condition-01-seed-0'
    npz, adr = cdir / 'sales.npz', cdir / 'sales_addresses.json'
    acsv = Path(r12dir) / f'r12_addr_{w}.csv'
    rjson = Path(r12dir) / 'r12_results.json'
    hashes = {'sales_npz': sha256(npz), 'sales_addresses': sha256(adr), 'r12_addr': sha256(acsv),
              'r12_results': sha256(rjson)}
    problems = []
    if check_hashes:
        exp = REGISTERED['inputs'][w]
        for key in ('sales_npz', 'sales_addresses', 'r12_addr'):
            if hashes[key] != exp[key]:
                problems.append(f'{w}: {key} hash {hashes[key]} is not the registered {exp[key]} (C0)')
        if hashes['r12_results'] != REGISTERED['inputs']['r12_results']:
            problems.append(f'r12_results.json hash {hashes["r12_results"]} is not registered (C0)')
    z = np.load(npz)
    sales = {k: z[k] for k in z.files}
    addrs = json.loads(adr.read_text())
    res = json.loads(rjson.read_text())['windows'][w]
    F, Z = int(res['first_block']), int(res['last_block'])
    rows = {}
    with open(acsv, newline='') as f:
        for r in csv.DictReader(f):
            rows[r['address']] = r
    S1r = [a for a in addrs if a in rows and rows[a]['in_S1r'] == '1']
    sums = {lag: {c: int(res['lag'][lag]['S1r'][f'X_sum_{c}_scaled']) for c in ('H', 'Ru')}
            for lag in REGISTERED['lags']}
    n_r12 = int(res['lag']['own']['S1r']['n'])
    # C5: the R12 sums equal the per-address columns
    for lag in REGISTERED['lags']:
        for c in ('H', 'Ru'):
            s = sum(int(rows[a][f'X_{c}_{lag}']) for a in S1r)
            if s != sums[lag][c]:
                problems.append(f'{w}: sum of X_{c}_{lag} over S1r {s} differs from r12_results {sums[lag][c]} (C5)')
    if len(S1r) != n_r12:
        problems.append(f'{w}: S1r has {len(S1r)} addresses, r12_results n = {n_r12} (C4)')
    # C1: epochs and window bounds
    b = sales['block'].astype(np.int64)
    if len(b) and (b.min() < F or b.max() > Z):
        problems.append(f'{w}: a sale lies outside [{F}, {Z}] (C1)')
    if 'epoch' in sales and not np.array_equal(sales['epoch'].astype(np.int64), (b - F) // REGISTERED['epoch_blocks']):
        problems.append(f'{w}: sales.npz epoch is not floor((block - F) / 300) (C1)')
    return dict(sales=sales, addrs=addrs, rows=rows, S1r=S1r, sums=sums, F=F, Z=Z, hashes=hashes), problems


def sellers_of(win):
    s = win['sales']
    idx = s['address_index'].astype(np.int64)
    order = np.argsort(idx, kind='stable')
    bounds = np.searchsorted(idx[order], np.arange(len(win['addrs']) + 1))
    out = {}
    for pos, a in enumerate(win['addrs']):
        if a not in win['S1r']:
            continue
        sl = order[bounds[pos]:bounds[pos + 1]]
        out[a] = (pos, Seller(s['block'][sl], s['value'][sl], s['row'][sl], win['F'],
                              REGISTERED['epoch_blocks'], REGISTERED['V_atomic']))
    return out


# ---------------------------------------------------------------- compute

def compute_window(win, widx, reg=REGISTERED, log=print):
    problems = []
    sellers = sellers_of(win)
    cells = {}
    repsG = np.zeros(reg['replicates'], dtype=np.int64)
    repsN = np.zeros(reg['replicates'], dtype=np.int64)
    t0 = time.time()
    for a in win['S1r']:
        pos, s = sellers[a]
        r = win['rows'][a]
        c, reps = seller_cells(s, int(r['k_star']), widx, pos, reg)
        for col in ('X_H_own', 'X_H_k1', 'X_Ru_own', 'X_Ru_k1'):
            c[col] = int(r[col])
        cells[a] = c
        repsG += reps['G']
        repsN += reps['N']
        if not c['theorem_ok']:
            problems.append(f'{a}: an exact E[G] exceeds V (C2, code error)')
    log(f'window {widx}: {len(cells)} sellers in {time.time() - t0:.0f} s')
    V, R, scale = reg['V_atomic'], reg['replicates'], reg['scale']
    agg = dict(n=len(cells), nV=len(cells) * V)
    for m in ('G', 'N'):
        agg[f'sum_E{m}'] = float(sum(c[f'E{m}'] for c in cells.values()))
        agg[f'sum_q95_{m}'] = int(sum(c[f'q95_{m}'] for c in cells.values()))
        agg[f'sum_q50_{m}'] = int(sum(c[f'q50_{m}'] for c in cells.values()))
        agg[f'sum_mc_mean_{m}'] = float(sum(c[f'mc_mean_{m}'] for c in cells.values()))
        agg[f'sum_mc_p95_{m}'] = int(sum(c[f'mc_p95_{m}'] for c in cells.values()))
        agg[f'sum_mc_max_{m}'] = int(sum(c[f'mc_max_{m}'] for c in cells.values()))
        tot = repsG if m == 'G' else repsN
        agg[f'total_mean_{m}'] = float(tot.mean())
        agg[f'total_median_{m}'] = int(sample_quantile(tot, reg['quantiles']['median']))
        agg[f'total_p95_{m}'] = int(sample_quantile(tot, reg['quantiles']['p95']))
        agg[f'total_max_{m}'] = int(tot.max())
        se = float(tot.std(ddof=1) / math.sqrt(R)) if R > 1 else 0.0
        agg[f'total_se_{m}'] = se
        # C3: MC agrees with the exact expectation
        if abs(agg[f'total_mean_{m}'] - agg[f'sum_E{m}']) > 4 * se + 1e-6:
            problems.append(f'MC total mean of {m} {agg[f"total_mean_{m}"]} is more than 4 SE from the exact '
                            f'{agg[f"sum_E{m}"]} (C3)')
        for lag in reg['lags']:
            for comp in ('H', 'Ru'):
                agg[f'P_total_{m}_ge_X{comp}_{lag}'] = float(
                    (tot.astype(object) * scale >= win['sums'][lag][comp]).mean())
    for m in ('G', 'N'):
        for lag in reg['lags']:
            for comp in ('H', 'Ru'):
                col = f'X_{comp}_{lag}'
                agg[f'sellers_q95_{m}_gt_{col}'] = int(sum(c[f'q95_{m}'] * scale > c[col] for c in cells.values()))
                agg[f'sellers_E{m}_gt_{col}'] = int(sum(Fraction(c[f'E{m}']) * scale > c[col] for c in cells.values()))
                agg[f'excess_E{m}_over_{col}'] = float(sum(max(Fraction(0), Fraction(c[f'E{m}']) - Fraction(c[col], scale))
                                                           for c in cells.values()))
    agg['E_frozen_N'] = float(sum(c['E_frozen_N'] for c in cells.values()))
    agg['E_undet_N'] = float(sum(c['E_undet_N'] for c in cells.values()))
    for lab in ('kstar', 'k1'):
        agg[f'E_pre_{lab}_N'] = float(sum(c[f'E_pre_{lab}_N'] for c in cells.values()))
        agg[f'E_post_{lab}_N'] = float(sum(c[f'E_post_{lab}_N'] for c in cells.values()))
    agg['X_sums_scaled'] = win['sums']
    stats = {'E': lambda m: agg[f'sum_E{m}'], 't': lambda m: agg[f'sum_q95_{m}'], 's': lambda m: agg[f'total_p95_{m}']}
    vcells = {}
    for name, (m, st, comp) in VERDICTS.items():
        q = stats[st](m)
        vcells[name] = dict(value_atomic=q, **{lag: bool(Fraction(q) * scale < win['sums'][lag][comp])
                                               for lag in reg['lags']})
    return dict(cells=cells, agg=agg, verdict_cells=vcells, totals=dict(G=repsG, N=repsN)), problems


def write_outputs(out, results, wins, reg=REGISTERED, extra=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    doc = dict(registration=extra or {}, registered=reg, windows={}, verdicts={})
    for w, r in results.items():
        doc['windows'][w] = dict(reportable=r['reportable'], problems=r['problems'], agg=r['agg'],
                                 verdict_cells=r['verdict_cells'], F=wins[w]['F'], Z=wins[w]['Z'])
        with open(out / f'r13_addr_{w}.csv', 'w', newline='') as f:
            wr = csv.writer(f)
            wr.writerow(ADDR_COLUMNS)
            for a, c in r['cells'].items():
                wr.writerow([a] + [c[k] for k in ADDR_COLUMNS[1:]])
        with open(out / f'r13_totals_{w}.csv', 'w', newline='') as f:
            wr = csv.writer(f)
            wr.writerow(['rep', 'total_G', 'total_N'])
            for i, (g, n) in enumerate(zip(r['totals']['G'].tolist(), r['totals']['N'].tolist())):
                wr.writerow([i, g, n])
    rep = [w for w, r in results.items() if r['reportable']]
    for name in VERDICTS:
        holds = bool(rep) and all(results[w]['verdict_cells'][name][lag] for w in rep for lag in reg['lags'])
        doc['verdicts'][name] = dict(holds=holds, windows=rep)
    (out / 'r13_results.json').write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
    lines = ['# R13 tables (USDC)', '']
    for w, r in results.items():
        a = r['agg']
        lines += [f'## {w} (n = {a["n"]}, n x V = {a["nV"] / 1e6:.2f}, reportable {r["reportable"]})', '',
                  '| cell | G (gross) | N (net of b) |', '|---|---|---|']
        for lab, key in (('sum of E', 'sum_E'), ('sum of exact p95', 'sum_q95_'), ('sum of MC mean', 'sum_mc_mean_'),
                         ('sum of MC p95', 'sum_mc_p95_'), ('sum of MC max', 'sum_mc_max_'),
                         ('total over sellers: mean', 'total_mean_'), ('total: p95', 'total_p95_'),
                         ('total: max', 'total_max_')):
            lines.append(f'| {lab} | {a[key + "G"] / 1e6:.2f} | {a[key + "N"] / 1e6:.2f} |')
        for lag in reg['lags']:
            lines.append(f'| R12 sum X^H, X^Ru ({lag}) | {a["X_sums_scaled"][lag]["H"] / 86400e6:.2f} | '
                         f'{a["X_sums_scaled"][lag]["Ru"] / 86400e6:.2f} |')
        lines.append('')
    lines += ['| verdict | holds |', '|---|---|'] + [f'| {k} | {v["holds"]} |' for k, v in doc['verdicts'].items()]
    (out / 'r13_tables.md').write_text('\n'.join(lines) + '\n')
    ih = [f'{h}  {w}/{k}' for w in wins for k, h in wins[w]['hashes'].items()]
    (out / 'r13_inputs_sha256.txt').write_text('\n'.join(ih) + '\n')
    need = ['r13_results.json', 'r13_tables.md', 'r13_inputs_sha256.txt']
    need += [f'r13_{t}_{w}.csv' for w in results for t in ('addr', 'totals')]
    missing = [p for p in need if not (out / p).exists()]
    if missing:
        raise SystemExit(f'outputs missing: {missing}')
    sums = [f'{sha256(out / p)}  {p}' for p in sorted(x.name for x in out.iterdir() if x.is_file()
                                                         and x.name != 'SHA256SUMS.txt')]
    (out / 'SHA256SUMS.txt').write_text('\n'.join(sums) + '\n')
    return doc


def check_seal(registration, seal):
    """G0: the registration and this script hash to the lines of the seal file."""
    want = {}
    for line in Path(seal).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 64:
            want[Path(parts[1]).name] = parts[0]
    got = {Path(registration).name: sha256(registration), Path(__file__).name: sha256(__file__)}
    bad = [n for n, h in got.items() if want.get(n) != h]
    return got, bad


def cmd_run(a):
    got, bad = check_seal(a.registration, a.seal)
    if bad:
        raise SystemExit(f'G0: {bad} do not match the seal file {a.seal}; not running')
    wins, results = {}, {}
    for w in a.windows.split(','):
        widx = REGISTERED['windows'].index(w)          # the seed key does not depend on which windows are run
        win, prob = load_window(a.raw, a.r12, w, check_hashes=True)
        wins[w] = win
        if prob:
            results[w] = dict(reportable=False, problems=prob, agg={}, verdict_cells={},
                              cells={}, totals=dict(G=np.zeros(0, int), N=np.zeros(0, int)))
            print('\n'.join(prob))
            continue
        r, p2 = compute_window(win, widx)
        r['problems'] = p2
        r['reportable'] = not p2
        results[w] = r
    doc = write_outputs(a.out, results, wins, extra=dict(seal=got, numpy=np.__version__, python=sys.version.split()[0]))
    print(json.dumps({k: v['holds'] for k, v in doc['verdicts'].items()}))
    return 0


# ---------------------------------------------------------------- synthetic selfcheck

def synthetic_inputs(root, seed=7, n_addr=6, F=1_000_000, n_blocks=30_000):
    """A raw folder and an R12 results folder in the layout run() reads, from random sales (no real data)."""
    root = Path(root)
    rng = np.random.default_rng(seed)
    addrs = [f'0x{i:040x}' for i in range(n_addr)]
    raw, r12 = root / 'raw', root / 'r12'
    r12.mkdir(parents=True, exist_ok=True)
    res = {'windows': {}}
    for w in REGISTERED['windows']:
        cdir = raw / f'{w}_r12cost' / 'k1' / 'condition-01-seed-0'
        cdir.mkdir(parents=True, exist_ok=True)
        cols = {k: [] for k in ('address_index', 'block', 'value', 'row', 'epoch')}
        row = 0
        rows = []
        for i, a in enumerate(addrs):
            n = int(rng.integers(0, 400)) if i else 0
            b = np.sort(rng.integers(F, F + n_blocks, n))
            v = rng.choice([1_000, 10_000, 50_000, 200_000, 1_500_000], n, p=[.4, .3, .2, .09, .01])
            cols['address_index'].append(np.full(n, i, np.int32)); cols['block'].append(b); cols['value'].append(v)
            cols['row'].append(np.arange(row, row + n)); cols['epoch'].append((b - F) // 300)
            row += n
            xs = {f'X_{c}_{lag}': int(rng.integers(0, 3_000_000)) * 86_400 for c in ('H', 'Ru') for lag in ('own', 'k1')}
            rows.append(dict(address=a, in_S1r='1' if n else '0', in_S1='1', k_star=str(rng.choice([1, 4, 32])), **xs))
        np.savez_compressed(cdir / 'sales.npz', **{k: np.concatenate(v) for k, v in cols.items()})
        (cdir / 'sales_addresses.json').write_text(json.dumps(addrs) + '\n')
        with open(r12 / f'r12_addr_{w}.csv', 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
        s1r = [r for r in rows if r['in_S1r'] == '1']
        res['windows'][w] = dict(first_block=F, last_block=F + n_blocks - 1, lag={
            lag: {'S1r': dict(n=len(s1r), **{f'X_sum_{c}_scaled': sum(r[f'X_{c}_{lag}'] for r in s1r)
                                            for c in ('H', 'Ru')})} for lag in ('own', 'k1')})
    (r12 / 'r12_results.json').write_text(json.dumps(res) + '\n')
    return raw, r12


def cmd_selfcheck(a):
    out = Path(a.out)
    raw, r12 = synthetic_inputs(out / 'synthetic')
    reg = dict(REGISTERED, replicates=int(a.reps))
    wins, results = {}, {}
    for widx, w in enumerate(REGISTERED['windows']):
        win, prob = load_window(raw, r12, w, check_hashes=False)
        wins[w] = win
        assert not prob, prob
        r, p2 = compute_window(win, widx, reg=reg)
        r['problems'], r['reportable'] = p2, not p2
        results[w] = r
    doc = write_outputs(out / 'result', results, wins, reg=reg,
                        extra=dict(synthetic=True, changed_for_synthetic=['input hashes not checked', 'S1r counts not checked',
                                                                          f'replicates {reg["replicates"]}']))
    ok = all(r['reportable'] for r in results.values()) and set(doc['verdicts']) == set(VERDICTS)
    (out / 'selfcheck.json').write_text(json.dumps(dict(ok=ok, problems={w: r['problems'] for w, r in results.items()}),
                                                   indent=1) + '\n')
    print('selfcheck', 'ok' if ok else 'FAILED')
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--raw', required=True)
    r.add_argument('--r12', required=True)
    r.add_argument('--out', required=True)
    r.add_argument('--registration', required=True)
    r.add_argument('--seal', required=True)
    r.add_argument('--windows', default=','.join(REGISTERED['windows']))
    s = sub.add_parser('selfcheck')
    s.add_argument('--out', required=True)
    s.add_argument('--reps', default=2000)
    a = p.parse_args(argv)
    return cmd_run(a) if a.cmd == 'run' else cmd_selfcheck(a)


if __name__ == '__main__':
    sys.exit(main())
