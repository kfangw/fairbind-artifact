#!/usr/bin/env python3
"""R14 (registration R14_preregistration.md): R12 and R13 cells recomputed on the seller sets that pass the D3 wash filters.

No new replay. Per-seller outputs of R12 (r12_addr_<w>.csv), R13 (r13_addr_<w>.csv), P1 (p1_sellers_<w>.csv) are
summed over the filtered sets. The D3 filter quantities are recomputed from the committed aggregates with the D3
definition copied below (d3_concentration.py seller_q and passes, unchanged in logic), because d3_results.json does
not store per-seller verdicts; the copy is checked against the stored D3 set metrics (registration 7, C1).
The sum-over-sellers Monte Carlo distribution T_m is recomputed with the R13 code and R13 seeds, so that the
replicate totals restricted to S1r equal the stored r13_totals_<w>.csv exactly (C4).

Run (repository root):
  python3 -I docs/11_journal/R14/r14_compute.py repro --raw $RAW   # checks only, prints booleans
  python3 -I docs/11_journal/R14/r14_compute.py run --raw $RAW     # writes results/
"""
import argparse, csv, gzip, hashlib, importlib.util, json, math, os, sys, time
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
REPO = J.parent.parent
AGG = REPO / 'data' / 'processed' / 'agg_2026-10-21'
OUT = HERE / 'results'

WINS = ['median', 'busy']
WIDX = {'median': 0, 'busy': 1}          # R13 6.2 seed component w
FILTERS = ['main', 'strict']
LAGS = ['own', 'k1']
V = 1_000_000
B = 1_000_000
S_ = 86_400
LF1 = 2251
THR = Fraction(6, 5)
MS = [1, 2, 4, 8]
BR = '0xe9030014f5dae217d0a152f02a043567b16c1abf'
UNIT_HI = Fraction('0.851522')

INPUTS = {
    'R12/results/r12_addr_median.csv': '0c182d3006c97666e89f5801f6d542717b8286ae0bd3b956c6719c938a8f2bf8',
    'R12/results/r12_addr_busy.csv': 'b88714b5e5a63377ab7496fd4eab682ea50c47d7732ebcd61fa2cd2e9dd93459',
    'R12/results/r12_results.json': '3b372f03969dee99bbe4b78bf1dfba6352ffaae2946544f8842781858ebe71df',
    'R12/results/r12_k_median.csv': '1e4bb05eeb4ab3f6f0c12771e2fa35821812096bc0915cf465872f3745ea64e7',
    'R12/results/r12_k_busy.csv': '0e9708fe97b2e67cb74cf1b2d67ac78dc2c8f82cf31bd5c975c12f63cbcf2be8',
    'R13/results/r13_addr_median.csv': 'd0ca50fe06794b4f9e0811e1e0fdb7a5a0943ed9e63bb90183197332ddc198f7',
    'R13/results/r13_addr_busy.csv': '211ae4f1bc2dcbc0cc56518f6cce0aa8a224e951b19ef2be65eee6f53d2a8718',
    'R13/results/r13_results.json': '0a87b87d702101003690275ce68531511daffbe818194e39a7c4153559d5037d',
    'R13/results/r13_totals_median.csv': '123d27eccff87ee35bba58c70bac24bbfcb9bf535971a8ad49919746a055c56b',
    'R13/results/r13_totals_busy.csv': '2cbdbf7e21819fc43c7c5b1cdbc12b9850499d095ed33fafa2bb018e15c2f387',
    'R13/r13_sim.py': '4bdb86c2c413ad678211ce7cd3b7ca5249d5ce2edf33468dc7c51c190564ad10',
    'D3/out/d3_results.json': '0e0bc05f07fdee18abcfdbd3fb5b8957ec29d3da8ac5024d22eb46124dd04758',
    'D3/d3_concentration.py': '6647eeba321c0933ef756be03c49d5a0582a6d86a87bac2daeea667b85e352f0',
    'R10/results/r10_addr_main_median_v0.2.csv': 'ad7e33490f732295bf4ccc6301caef8b81eb777728bf35ebc42a4075ea7af41f',
    'R10/results/r10_addr_main_busy_v0.2.csv': 'd8ae707181fa16426e3daec3ec4f759a4f4cadc7e98788103c6be55d53a649a4',
    'P1_posthoc/results/p1_sellers_median.csv': '6595ef7fa3171cf915a86d5be86fea9b212a6d8c1689755c7b944d208714b578',
    'P1_posthoc/results/p1_sellers_busy.csv': '69b91592c98dca0c50d889fb260d0665ea4b45c4bbce2c8535ae9e148e5643b9',
    'P1_posthoc/results/p1_results.json': 'a085801c2954b9fb948ffac4a45fa2935bf4522d78517371e62820dec5bdab41',
    'agg/pairs_median.csv.gz': '8ada60b07831c0d9f24c9760a4824f23c65a12b785aac968a685bf7953c43902',
    'agg/pairs_busy.csv.gz': 'a717687f17c23395cb8d5ca1f065e04960b828f23ee075ae3e579254cab9086c',
    'agg/days_median.csv.gz': '2f6ab6ac5a96035de60ea1a591a4906fc824f7f41c092be20f629c50b3b0cde4',
    'agg/days_busy.csv.gz': '6eaf55c4e19b78b768b35b3aeac7f2d7c10d1056bfad989482ef08819b1b4b7f',
    'agg/values_median.csv.gz': '9b232a55b364317a49c33186c5de84bb778ae62eedfbab1215fe12fda7741062',
    'agg/values_busy.csv.gz': '35a2fcc5bae39045f4f68b8e9b416a088c229e6200573ef7b4393faa51a0ecc8',
}

R13_VERDICTS = {  # R13 7.1, same (quantity, statistic, comparator)
    'JF14': ('N', 'E', 'H'), 'JF14t': ('N', 't', 'H'), 'JF14s': ('N', 's', 'H'),
    'JF14r': ('N', 'E', 'Ru'), 'JF14rt': ('N', 't', 'Ru'), 'JF14rs': ('N', 's', 'Ru'),
    'JG14': ('G', 'E', 'H'), 'JG14t': ('G', 't', 'H'), 'JG14s': ('G', 's', 'H'),
    'JG14r': ('G', 'E', 'Ru'), 'JG14rt': ('G', 't', 'Ru'), 'JG14rs': ('G', 's', 'Ru'),
}


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def path_of(key):
    return (AGG / key.split('/', 1)[1]) if key.startswith('agg/') else (J / key)


def check_inputs(raw):
    bad = [k for k, v in INPUTS.items() if sha(path_of(k)) != v]
    r13 = load_r13_module()
    for w in WINS:
        cdir = Path(raw) / f'{w}_r12cost' / 'k1' / 'condition-01-seed-0'
        if sha(cdir / 'sales.npz') != r13.REGISTERED['inputs'][w]['sales_npz']:
            bad.append(f'{w} sales.npz')
        if sha(cdir / 'sales_addresses.json') != r13.REGISTERED['inputs'][w]['sales_addresses']:
            bad.append(f'{w} sales_addresses.json')
    return bad


def load_r13_module():
    spec = importlib.util.spec_from_file_location('r13_sim', J / 'R13' / 'r13_sim.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- D3 filter (copied from D3/d3_concentration.py)

def rd(name):
    return list(csv.DictReader(gzip.open(AGG / (name + '.csv.gz'), 'rt', newline='')))


def _blank():
    return dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, means={}, days=0, band=0)


def seller_q(w):
    Q = {}
    edges = set()
    pairs = rd('pairs_' + w)
    for r in pairs:
        edges.add((r['recipient'].lower(), r['payer'].lower()))
    for r in pairs:
        rec, pay = r['recipient'].lower(), r['payer'].lower()
        n, v = int(r['n']), int(r['value_atomic_sum'])
        q = Q.setdefault(rec, _blank())
        if pay == rec:
            q['self'] += n; continue
        q['n'] += n; q['payers'] += 1; q['mx'] = max(q['mx'], n)
        if n >= 2: q['repeat'] += 1
        if (pay, rec) in edges: q['loop'] += 1
        if v % n == 0:
            m = v // n; q['means'][m] = q['means'].get(m, 0) + n
    for r in rd('days_' + w):
        if int(r['n']) >= 1:
            Q.setdefault(r['recipient'].lower(), _blank())['days'] += 1
    for r in rd('values_' + w):
        if 3 <= int(r['log10_bin']) <= 5:
            Q.setdefault(r['recipient'].lower(), _blank())['band'] += int(r['n'])
    for q in Q.values():
        q['top'] = q['mx'] / q['n'] if q['n'] else float('nan')
        if q['means']:
            mstar = sorted(q['means'].items(), key=lambda t: (-t[1], t[0]))[0][0]
            q['mstar'] = mstar; q['fix'] = q['means'][mstar] / q['n']
        else:
            q['mstar'] = None; q['fix'] = 0.0
        q['mint'] = q['fix'] >= 0.90 and q['payers'] >= 100 and (q['mstar'] or 0) >= 500_000
        del q['means']
    return Q


ZERO = dict(self=0, n=0, payers=0, mx=0, repeat=0, loop=0, days=0, band=0, top=float('nan'), mstar=None, fix=0.0,
            mint=False)


def passes(q, col, acc_count):
    ok = (q['self'] == 0 and q['loop'] == 0 and not q['mint']
          and (acc_count >= 1 if acc_count is not None else True) and q['band'] >= 1
          and q['payers'] >= 10 and q['n'] > 0 and q['top'] <= 0.50 and q['repeat'] >= 1)
    if col == 'main':
        return ok
    return ok and q['payers'] >= 30 and q['top'] <= 0.20 and q['days'] >= 7


def filter_verdicts():
    """verdict[w][address] = {'main': bool, 'strict': bool} for the 415 R10 addresses, and the D3 reproduction."""
    out, repro = {}, {}
    d3 = json.load(open(J / 'D3' / 'out' / 'd3_results.json'))
    for w in WINS:
        Q = seller_q(w)
        r10 = {r['address'].lower(): r for r in csv.DictReader(open(J / 'R10' / 'results' / f'r10_addr_main_{w}_v0.2.csv'))}
        out[w] = {a: {c: passes(Q.get(a, ZERO), c, int(r['accepted_count'])) for c in FILTERS} for a, r in r10.items()}
        rev = {a: float(r['accepted_value'] or 0) / 1e6 for a, r in r10.items()}
        ok = True
        for c in FILTERS:
            s = {a for a in r10 if out[w][a][c]}
            for vn, S in (('ALL', s), ('-BR', s - {BR})):
                st = d3['R'][w][f'{c}|{vn}']
                ok &= len(S) == st['n']
                ok &= sum(1 for a in S if rev[a] > 0) == st['n_rev']
                ok &= abs(sum(rev[a] for a in S) - st['rev']) <= 1e-9 * max(1.0, st['rev'])
        for nm, a in (('StableEnrich', '0x325bdf6f7efab24a2210c48c1b64cab2eae1d430'), ('BlockRun', BR)):
            for c in FILTERS:
                ok &= out[w][a][c] == d3['named'][w][nm][c]
        repro[w] = ok
    return out, repro


# ---------------------------------------------------------------- R12 cells on a set

def read_rows(p):
    return {r['address']: r for r in csv.DictReader(open(p, newline=''))}


def r12_cells(rows, S, lag, n_avg, rate_blocks):
    n = len(S)
    I = lambda a, c: int(rows[a][c])
    P = Fraction(n * B, 10 ** 6)
    held = Fraction(sum(I(a, f"Hnum_k{I(a, 'k_star')}") for a in S), n_avg * 10 ** 6)
    LFB = P + held
    Lof = (lambda a: I(a, 'L_kstar')) if lag == 'own' else (lambda a: LF1)
    CM = sum((Fraction(B * rate_blocks + I(a, 'revenue') * Lof(a), rate_blocks) for a in S), Fraction(0)) / 10 ** 6
    BH = Fraction(sum(I(a, f'Bsum_H_{lag}') for a in S), S_ * n_avg * 10 ** 6)
    BR_ = sum((Fraction(I(a, 'rho2') * Lof(a), S_) for a in S), Fraction(0)) / 10 ** 6
    XH = sum(I(a, f'X_H_{lag}') for a in S)
    XRu = sum(I(a, f'X_Ru_{lag}') for a in S)
    rev = sum(I(a, 'revenue') for a in S)
    rej = sum(I(a, f'rej_value_Rr_{lag}') for a in S)
    onum = Fraction(sum(I(a, f"Onum_k{I(a, 'k_star')}") for a in S), n_avg)
    return dict(
        n=n, revenue=rev / 1e6, P_FB=float(P), held=float(held), L_FB=float(LFB), sumC_M=float(CM),
        ratio_LFB_CM=float(LFB / CM) if CM else None, ratio_LFB_CM_le_threshold=bool(CM and LFB <= THR * CM),
        ratio_exact=(LFB / CM) if CM else None,
        sumB_H=float(BH), sumB_R=float(BR_), ratio_LFB_BH=float(LFB / BH) if BH else None,
        ratio_LFB_BR=float(LFB / BR_) if BR_ else None,
        X_sum_H=XH / S_ / 1e6, X_sum_Ru=XRu / S_ / 1e6, X_sum_H_scaled=XH, X_sum_Ru_scaled=XRu,
        X_sum_M=sum(I(a, f'X_M_{lag}') / rate_blocks for a in S) / 1e6,
        FB_bound=n * V / 1e6, FB_bound_scaled=n * V * S_,
        JEH_cell=XH > n * V * S_, JER_cell=XRu > n * V * S_,
        X_gt_V_H=sum(1 for a in S if I(a, f'X_H_{lag}') > V * S_),
        X_gt_V_Ru=sum(1 for a in S if I(a, f'X_Ru_{lag}') > V * S_),
        X_gt_V_M=sum(1 for a in S if I(a, f'X_M_{lag}') > V * rate_blocks),
        U_avg_H=sum(I(a, f'Usum_H_{lag}') for a in S) / S_ / n_avg / 1e6,
        U_avg_Ru=sum(I(a, f'Usum_Ru_{lag}') for a in S) / S_ / n_avg / 1e6,
        U_avg_M=sum(I(a, f'Usum_M_{lag}') / rate_blocks for a in S) / n_avg / 1e6,
        E_avg=sum(I(a, f'Esum_{lag}') for a in S) / n_avg / 1e6,
        reject_value_Rr=rej / 1e6, reject_share_Rr=float(Fraction(rej, rev)) if rev else None,
        no_prior=sum(1 for a in S if I(a, 'C_prior') == 0),
        open_purchases_avg=float(onum), reserve_usd=float(onum * UNIT_HI),
    )


def r12_kcurve(rows, S, n_avg, rate_blocks):
    I = lambda a, c: int(rows[a][c])
    out = {}
    P = Fraction(len(S) * B)
    CM1 = sum((Fraction(B * rate_blocks + I(a, 'revenue') * LF1, rate_blocks) for a in S), Fraction(0))
    for k in (1, 2, 4, 8, 16, 32):
        Lk = LF1 + 300 * (k - 1)
        held = Fraction(sum(I(a, f'Hnum_k{k}') for a in S), n_avg)
        CMk = sum((Fraction(B * rate_blocks + I(a, 'revenue') * Lk, rate_blocks) for a in S), Fraction(0))
        out[str(k)] = dict(L_F=Lk, L_FB=float((P + held) / 10 ** 6), sumC_M_lag_k=float(CMk / 10 ** 6),
                           sumC_M_lag_1=float(CM1 / 10 ** 6),
                           ratio_lag_k=float((P + held) / CMk) if CMk else None,
                           ratio_lag_1=float((P + held) / CM1) if CM1 else None,
                           ratio_lag_1_exact=((P + held) / CM1) if CM1 else None)
    return out


def rel_ok(g, e, tol=1e-9):
    if e is None or g is None:
        return g is e
    return g == e or abs(g - e) <= tol * max(abs(e), 1e-300)


def repro_r12(rows, rw, kcsv, n_avg, rate_blocks):
    S = [a for a in rows if rows[a]['in_S1r'] == '1']
    ok = True
    for lag in LAGS:
        got, exp = r12_cells(rows, S, lag, n_avg, rate_blocks), rw['lag'][lag]['S1r']
        for key in ('n', 'held', 'L_FB', 'sumC_M', 'sumB_H', 'sumB_R', 'X_sum_H', 'X_sum_Ru', 'X_sum_M', 'X_gt_V_H',
                    'X_gt_V_Ru', 'X_gt_V_M', 'U_avg_H', 'U_avg_Ru', 'U_avg_M', 'E_avg', 'reject_share_Rr',
                    'no_prior', 'open_purchases_avg', 'reserve_usd', 'X_sum_H_scaled', 'X_sum_Ru_scaled',
                    'FB_bound_scaled', 'ratio_LFB_CM', 'ratio_LFB_CM_le_threshold'):
            ok &= rel_ok(got[key], exp[key])
    kc = r12_kcurve(rows, S, n_avg, rate_blocks)
    for r in kcsv:
        if r['set'] != 'S1r':
            continue
        g = kc[r['k']]
        for key in ('L_FB', 'sumC_M_lag_k', 'sumC_M_lag_1', 'ratio_lag_k', 'ratio_lag_1'):
            ok &= rel_ok(g[key], float(r[key]))
    return ok


# ---------------------------------------------------------------- R13 cells on a set

def r13_mc(raw, w, r13, rows12):
    """Per-seller MC replicate arrays at the R13 worst starts, with the R13 seeds (R13 6.2)."""
    win, problems = r13.load_window(raw, J / 'R12' / 'results', w)
    assert not problems, problems
    sellers = r13.sellers_of(win)
    reps, cells = {}, {}
    for a in win['S1r']:
        pos, s = sellers[a]
        c, rp = r13.seller_cells(s, int(rows12[a]['k_star']), WIDX[w], pos)
        reps[a] = rp
        cells[a] = c
    return reps, cells


def r13_cells(rows13, rows12, reps, S, r13):
    out = dict(n=len(S))
    R = r13.REGISTERED['replicates']
    for m in ('G', 'N'):
        out[f'sum_E{m}'] = float(sum(float(rows13[a][f'E{m}']) for a in S))
        out[f'sum_q95_{m}'] = int(sum(int(rows13[a][f'q95_{m}']) for a in S))
        tot = sum((reps[a][m].astype('int64') for a in S), start=__import__('numpy').zeros(R, dtype='int64'))
        out[f'total_mean_{m}'] = float(tot.mean())
        out[f'total_p95_{m}'] = int(r13.sample_quantile(tot, 0.95))
        out[f'total_max_{m}'] = int(tot.max())
        out[f'_tot_{m}'] = tot
    for lag in LAGS:
        for comp in ('H', 'Ru'):
            col = f'X_{comp}_{lag}'
            X = {a: int(rows12[a][col]) for a in S}
            for m in ('G', 'N'):
                out[f'sellers_E{m}_gt_{col}'] = int(sum(Fraction(float(rows13[a][f'E{m}'])) * S_ > X[a] for a in S))
                out[f'excess_E{m}_over_{col}'] = float(sum(max(Fraction(0), Fraction(float(rows13[a][f'E{m}'])) -
                                                               Fraction(X[a], S_)) for a in S))
    return out


def r13_verdict_cells(c13, c12):
    stats = {'E': lambda m: c13[f'sum_E{m}'], 't': lambda m: c13[f'sum_q95_{m}'], 's': lambda m: c13[f'total_p95_{m}']}
    out = {}
    for name, (m, st, comp) in R13_VERDICTS.items():
        q = stats[st](m)
        out[name] = dict(value_atomic=q, **{lag: bool(Fraction(q) * S_ < c12[lag][f'X_sum_{comp}_scaled'])
                                            for lag in LAGS})
    return out


# ---------------------------------------------------------------- arm c (P1 multiples on a set, report only)

def p1_cells(prow, rows12, S, n_avg):
    out = {}
    for m in MS:
        out[str(m)] = {}
        for lag in LAGS:
            XH = sum(int(prow[a][f'X_H_m{m}_{lag}']) for a in S)
            BH = Fraction(sum(int(prow[a][f'Bsum_H_m{m}_{lag}']) for a in S), S_ * n_avg * 10 ** 6)
            LFB = Fraction(len(S) * B, 10 ** 6) + Fraction(
                sum(int(rows12[a][f"Hnum_k{rows12[a]['k_star']}"]) for a in S), n_avg * 10 ** 6)
            out[str(m)][lag] = dict(n=len(S), X_sum_H=XH / S_ / 1e6,
                                    X_gt_V_H=sum(1 for a in S if int(prow[a][f'X_H_m{m}_{lag}']) > V * S_),
                                    sumB_H=float(BH), ratio_LFB_BH=float(LFB / BH) if BH else None,
                                    nV=len(S) * V / 1e6)
    return out


def repro_p1(prow, rows12):
    return all(int(prow[a][f'X_H_m2_{lag}']) == int(rows12[a][f'X_H_{lag}']) and
               int(prow[a][f'Bsum_H_m2_{lag}']) == int(rows12[a][f'Bsum_H_{lag}'])
               for a in rows12 if rows12[a]['in_S1r'] == '1' for lag in LAGS)


# ---------------------------------------------------------------- main

def build(raw, do_mc=True):
    t0 = time.time()
    bad = check_inputs(raw)
    fv, d3_repro = filter_verdicts()
    r12 = json.load(open(J / 'R12' / 'results' / 'r12_results.json'))
    r13 = load_r13_module()
    checks = dict(C0_inputs=not bad, C0_bad=bad, C1_d3_repro=d3_repro)
    W = {}
    for w in WINS:
        rows12 = read_rows(J / 'R12' / 'results' / f'r12_addr_{w}.csv')
        rows13 = read_rows(J / 'R13' / 'results' / f'r13_addr_{w}.csv')
        prow = read_rows(J / 'P1_posthoc' / 'results' / f'p1_sellers_{w}.csv')
        kcsv = list(csv.DictReader(open(J / 'R12' / 'results' / f'r12_k_{w}.csv')))
        rw = r12['windows'][w]
        n_avg, rate_blocks = rw['n_avg'], rw['rate_blocks']
        S1r = [a for a in rows12 if rows12[a]['in_S1r'] == '1']
        g0 = all(a in fv[w] for a in S1r)
        checks[f'G0_{w}'] = g0
        checks[f'C2_r12_repro_{w}'] = repro_r12(rows12, rw, kcsv, n_avg, rate_blocks)
        checks[f'C5_p1_repro_{w}'] = repro_p1(prow, rows12)
        sets = {'S1r': S1r}
        for c in FILTERS:
            sets[f'F_{c}'] = [a for a in S1r if fv[w][a][c]]
            sets[f'F_{c}_geV'] = [a for a in sets[f'F_{c}'] if int(rows12[a]['revenue']) >= V]
        W[w] = dict(sets=sets, rows12=rows12, rows13=rows13, prow=prow, n_avg=n_avg, rate_blocks=rate_blocks)
        if do_mc:
            reps, cells = r13_mc(raw, w, r13, rows12)
            tot = {m: sum((reps[a][m].astype('int64') for a in S1r), start=__import__('numpy').zeros(
                r13.REGISTERED['replicates'], dtype='int64')) for m in ('G', 'N')}
            stored = list(csv.DictReader(open(J / 'R13' / 'results' / f'r13_totals_{w}.csv')))
            ok = len(stored) == len(tot['G']) and all(int(r['total_G']) == int(tot['G'][i]) and
                                                      int(r['total_N']) == int(tot['N'][i]) for i, r in enumerate(stored))
            for a in S1r:
                for col in ('EG', 'EN', 'q95_G', 'q95_N'):
                    ok &= rel_ok(float(cells[a][col]), float(rows13[a][col]), 1e-12)
            checks[f'C4_r13_repro_{w}'] = ok
            W[w]['reps'] = reps
    checks['all_ok'] = all(v for k, v in checks.items() if k.startswith(('C0_inputs', 'G0', 'C2', 'C4', 'C5'))) \
        and all(d3_repro.values())
    checks['seconds'] = round(time.time() - t0, 1)
    return W, checks, r13


def compute(W, r13):
    res = {}
    for w, d in W.items():
        rows12, rows13, prow = d['rows12'], d['rows13'], d['prow']
        res[w] = dict(set_sizes={s: len(S) for s, S in d['sets'].items()},
                      revenue_share_of_S1r={s: (sum(int(rows12[a]['revenue']) for a in S) /
                                                sum(int(rows12[a]['revenue']) for a in d['sets']['S1r']))
                                            for s, S in d['sets'].items()},
                      sets={})
        for s, S in d['sets'].items():
            c12 = {lag: r12_cells(rows12, S, lag, d['n_avg'], d['rate_blocks']) for lag in LAGS}
            kc = r12_kcurve(rows12, S, d['n_avg'], d['rate_blocks'])
            c13 = r13_cells(rows13, rows12, d['reps'], S, r13)
            vc = r13_verdict_cells(c13, c12)
            for m in ('G', 'N'):
                for lag in LAGS:
                    for comp in ('H', 'Ru'):
                        c13[f'P_total_{m}_ge_X{comp}_{lag}'] = float(
                            (c13[f'_tot_{m}'].astype(object) * S_ >= c12[lag][f'X_sum_{comp}_scaled']).mean())
            res[w]['sets'][s] = dict(r12=c12, k=kc, r13={k: v for k, v in c13.items() if not k.startswith('_')},
                                     r13_verdict_cells=vc, armC=p1_cells(prow, rows12, S, d['n_avg']))
    return res


def verdicts(res):
    out = {}
    for c in FILTERS:
        s = f'F_{c}'
        ok = {w: res[w]['sets'][s]['r12']['own']['n'] > 0 for w in WINS}
        decidable = all(ok.values())
        cell = lambda name, f: {w: f(w) for w in WINS}
        v = {}
        v[f'JL14_{c}'] = cell('JL14', lambda w: res[w]['sets'][s]['r12']['own']['ratio_LFB_CM_le_threshold'])
        v[f'JL14d_{c}'] = cell('JL14d', lambda w: res[w]['sets'][s]['r12']['k1']['ratio_LFB_CM_le_threshold'])
        v[f'JL14a_{c}'] = cell('JL14a', lambda w: res[w]['sets'][s]['k']['1']['ratio_lag_1_exact'] is not None and
                               res[w]['sets'][s]['k']['1']['ratio_lag_1_exact'] < 1)
        for name in R13_VERDICTS:
            v[f'{name}_{c}'] = cell(name, lambda w, name=name: all(res[w]['sets'][s]['r13_verdict_cells'][name][lag]
                                                                    for lag in LAGS))
        for name, cells in v.items():
            out[name] = dict(cells=cells, holds=(all(cells.values()) if decidable else None), decidable=decidable)
    return out


def clean(x):
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items() if not k.endswith('_exact')}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, Fraction):
        return float(x)
    if hasattr(x, 'item'):
        return x.item()
    return x


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['repro', 'run'])
    ap.add_argument('--raw', required=True)
    ap.add_argument('--out', default=str(OUT))
    a = ap.parse_args(argv)
    W, checks, r13 = build(a.raw)
    print(json.dumps(clean(checks), ensure_ascii=False, indent=1))
    if a.cmd == 'repro':
        return 0 if checks['all_ok'] else 1
    if not checks['all_ok']:
        print('checks failed: no results written (registration 7)')
        return 1
    import numpy
    res = compute(W, r13)
    ver = verdicts(res)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    reg = HERE / 'R14_preregistration.md'
    doc = dict(registration_sha256=sha(reg) if reg.exists() else None, code_sha256=sha(__file__),
               environment=dict(python=sys.version.split()[0], numpy=numpy.__version__),
               checks=checks, windows=res, verdicts=ver)
    (out / 'r14_results.json').write_text(json.dumps(clean(doc), ensure_ascii=False, indent=1))
    # per-seller report file: membership and the per-seller cells used
    for w, d in W.items():
        with open(out / f'r14_sellers_{w}.csv', 'w', newline='') as f:
            wr = csv.writer(f, lineterminator='\n')
            wr.writerow(['address', 'in_F_main', 'in_F_strict', 'revenue', 'k_star', 'X_H_own', 'X_H_k1', 'X_Ru_own',
                         'X_Ru_k1', 'EG', 'EN', 'q95_G', 'q95_N', 'P_det_N'])
            for x in d['sets']['S1r']:
                r12r, r13r = d['rows12'][x], d['rows13'][x]
                wr.writerow([x, int(x in d['sets']['F_main']), int(x in d['sets']['F_strict']), r12r['revenue'],
                             r12r['k_star'], r12r['X_H_own'], r12r['X_H_k1'], r12r['X_Ru_own'], r12r['X_Ru_k1'],
                             r13r['EG'], r13r['EN'], r13r['q95_G'], r13r['q95_N'], r13r['P_det_N']])
    names = ['r14_results.json'] + [f'r14_sellers_{w}.csv' for w in WINS]
    (out / 'SHA256SUMS.txt').write_text(''.join(f'{sha(out / n)}  {n}\n' for n in names))
    print(json.dumps({k: v['holds'] for k, v in ver.items()}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
