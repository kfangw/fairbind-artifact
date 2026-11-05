#!/usr/bin/env python3
"""P10 (post hoc, calc-rules.md): the fit-condition curve of FairBind's cost under P9's V1 (measured gas), and the
block-filling margin of the swap-proof part of the bound per seller.

K11/k11b.py is loaded unchanged through P9_posthoc/p9.py (load_k11b, Env) and set to P9's variant V1. The cost of a
seller is written in closed form (calc-rules.md 2) from the seller's inputs (R, n, n_s, E1, m1, per-epoch counts), so
that the same function gives the curve of a stylised seller and the value at an observed seller.

    python3 -I p10.py --check     # reproduction against p9.json V1 and against P9's Env on stylised sellers
    python3 -I p10.py --out results  # the whole calculation (writes p10.json, p10_tables.md, fig_fit.pdf/png)

Nothing outside this folder is written. No existing results file is changed.
"""
import argparse, csv, gzip, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
P9D = J / 'P9_posthoc'
P9J = P9D / 'results' / 'p9.json'
ROOT = J.parent.parent
AGG = ROOT / 'data' / 'processed' / 'agg_2026-10-21'
sys.path.insert(0, str(P9D))
import p9                                                            # noqa: E402  (functions only; p9.main() is not run)

TH = (0.10, 0.05)
PER = ('busy', 'median', 'quiet')
LABS = ('lo', 'up', 'fac')
V = 1.0
TOL_PT = 0.05                    # calc-rules.md 3.5: reproduction tolerance in percentage points
N_UNIT = p9.N_UNIT               # 256 leaves per anchor unit
REL = p9.REL_MEAS                # measured release (p9.py 66-74)
ANC = p9.ANC_MEAS                # measured anchor (p9.py 79-92), sigma = 1 -> index 1
# The aggregates' quiet window is s1b's (CDP) data, which holds only 22 Sep of the quiet window
# (F/data-review/target_sellers_all_README.md 5 (line): BlockRun 1,553 against s1c's 28,710); k11b's quiet window is s1c.
# The busy and median windows of the aggregates match k11b's sellers (agg_match in p10.json).
AGG_SAME = ('busy', 'median')
VGRID = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0)

# ------------------------------------------------------------------ block filling (P5_posthoc/p5.py 32-33, 49-51)
GAS_LIMIT = 400_000_000
FEES = (('lo', 0.005), ('mid', 0.0100), ('hi', 0.0161))
ETH_FILL = 2_401.44
FILL_W = (('swap62', 62, 'swap proof window, most short admission length(T_sw = 31, to fill block 62)'),
          ('swap331', 331, 'swap proof window T_sw = 300(to fill block 331)'),
          ('swap1800', 1_800, 'evaluation profile(swap proof window proof deadline and together ends, P5 1,800 block)'),
          ('anchor120', 120, 'reference only: anchor window a_A = 120(P8 D1)'))


def fill_cost(W, p_gwei, eth=ETH_FILL, gas_limit=GAS_LIMIT):
    """USD to fill W blocks at price p (gwei): W * gas_limit * p * 1e-9 * eth (P5_posthoc/p5.py 49-51)."""
    return W * gas_limit * p_gwei * 1e-9 * eth


# ================================================================== the model namespace at V1
class Model:
    def __init__(self):
        g, repro = p9.load_k11b('k11b_p10')
        assert repro, 'k11b_output.md not reproduced'
        self.g = g; self.env = p9.Env(g, with_fr=False); self.env.set_variant('V1')
        assert self.env.lower_rnd == 'cl' and self.env.rel == 'meas' and self.env.anc == 'meas'
        self.KS = list(g['KS']); self.W0 = g['W0']
        self.prm = {lab: self.env.prm(lab) for lab in LABS}
        assert g['cap_anchor'](self.prm['lo']) == float(N_UNIT)
        self.dep = g['depth_of'](float(N_UNIT))

    def capR_fb(self, q):
        g = self.g
        return math.floor((g['TX_CAP'] - g['REL_F']['ledger']) / (g['REL_M'] + g['REL_K'] * min(q, 1.0)))

    def capR_fi(self):
        g = self.g
        return math.floor((g['TX_CAP'] - g['REL_F']['ledger']) / (g['REL_M'] + g['REL_K']))


# ================================================================== seller structure
def groups(idx, c, k):
    """Per-seller-epoch sales from sparse per-profile-epoch counts (idx, c): sales of each nonempty group idx // k."""
    if len(idx) == 0: return np.zeros(0)
    m = np.bincount(idx // k, weights=c); return m[m > 0]


def splits(m, cap): return float(np.sum(np.maximum(np.ceil(m / cap) - 1, 0)))


def splits_bound(n, E, m1, k, cap):
    """k11b.py 378-383 (no per-epoch counts)."""
    mk = min(k * m1, n)
    if mk <= cap: return 0.0
    return float(min(math.ceil(n / cap) - 1, E * (math.ceil(mk / cap) - 1)))


def structure(M, s, days):
    """Counts of seller s per k (calc-rules.md 2): E_k, the release unit counts X, J, S (N = 256), the model release
    capacity's extra transactions Ur (FairBind and FI capacities), and k-free E0, U_a, P."""
    KS = M.KS; Nep = days * 144
    n = float(s['n']); ns = float(s['ns']); m1 = s['m1']; E1 = s['E1']
    cnt = s.get('cnt')
    if cnt is not None:
        cnt = np.asarray(cnt, float); idx = np.nonzero(cnt > 0)[0]; c = cnt[idx]
    capFB = M.capR_fb(ns / n); capFI = M.capR_fi(); N = REL['N']
    E = np.array([min(E1, math.ceil(Nep / k)) for k in KS], float)
    X = np.zeros(len(KS)); Jn = np.zeros(len(KS)); S = np.zeros(len(KS)); UrFB = np.zeros(len(KS)); UrFI = np.zeros(len(KS))
    for i, k in enumerate(KS):
        if cnt is not None:
            m = groups(idx, c, k)
            X[i] = splits(m, N); big = m > N; Jn[i] = float(big.sum()); S[i] = min(n, float(m[big].sum()))
            UrFB[i] = splits(m, capFB); UrFI[i] = splits(m, capFI)
        else:
            X[i] = splits_bound(n, E[i], m1, k, N)
            mk = min(k * m1, n)
            Jn[i] = 0.0 if mk <= N else float(min(X[i], E[i], math.floor(n / (N + 1))))
            S[i] = min(n, Jn[i] * mk)
            UrFB[i] = splits_bound(n, E[i], m1, k, capFB); UrFI[i] = splits_bound(n, E[i], m1, k, capFI)
    E0 = E[0]
    if cnt is not None:
        Ua = splits(c, float(N_UNIT)); P = min(n, float(np.minimum(c, N_UNIT).sum()))
    else:
        Ua = splits_bound(n, E0, m1, 1, float(N_UNIT)); P = n if m1 <= N_UNIT else min(n, N_UNIT * E0)
    return dict(E=E, E0=E0, X=X, J=Jn, S=S, UrFB=UrFB, UrFI=UrFI, Ua=Ua, P=P, days=days)


# ================================================================== the closed form (calc-rules.md 2)
def costs(M, s, st, lab, Vc=V):
    """Cost shares of FairBind (V1) and FI (V1) for every k, as dicts of term arrays (length len(KS)), and the totals."""
    g = M.g; prm = M.prm[lab]; KS = M.KS; nk = len(KS)
    R = float(s['R']); n = float(s['n']); ns = float(s['ns']); days = st['days']; Wb = days * 43_200
    gu, wu = prm.gusd, prm.wusd
    cp = prm.cpu(s['ck'])
    E, E0 = st['E'], st['E0']
    up, fac = prm.up, prm.fac
    one = np.ones(nk)
    rows = np.zeros(nk, int) if up else np.arange(nk)          # upper case: k = 1 grouping at every k (K10h (d))

    def rel(closed):
        F1, M1, K, FU, MU, FC = REL['F1'], REL['M1'], REL['K'], REL['FU'], REL['MU'], REL['FC']
        Ei, Xi, Ji, Si = E[rows], st['X'][rows], st['J'][rows], st['S'][rows]
        return gu(F1 * Ei + M1 * n + K * closed + FU * Xi + (FU + FC - F1) * Ji + (MU - M1) * Si) / R

    # ---------------- FairBind
    fb = {}
    fb['verify'] = one * cp * ns / R
    fb['anchor'] = one * gu(st['Ua'] * ANC['FU'][1] + (n - E0) * ANC['MU'][1] + E0 * ANC['FC'][1] + ANC['MC'][1] * st['P']) / R
    fb['sampvrf'] = one * E0 * prm.cl_usd() / R
    fb['release'] = rel(ns)
    A = E0 + st['Ua']
    Ru = (E0 + st['UrFB'][0]) * one if up else E + st['UrFB']
    fb['l1'] = wu(A * g['L1W_F'][1] + n * g['L1W_M'][1] + Ru * g['RW_F'] + g['RW_M'] * n) / R
    Ef = min(E0, n)
    if fac: fb['facil'] = one * gu(Ef * g['SETTLE']['ledger']['first'] + (n - Ef) * g['SETTLE']['ledger']['later']) / R
    if up:
        fb['detincl'] = one * gu(g['G_DET'] * ns + max(M.dep - g['DEP0'], 0) * prm.glvl * ns) / R
        fb['failpath'] = one * gu(g['G_FAIL']) / R
    fb['frozen'] = one * (1 - prm.a) * (1 - math.exp(-M.W0 * ns * prm.DF(1) / Wb))
    fb['deduct'] = one * (M.W0 * ns * Vc / R + (M.W0 * ns * gu(g['G_FAIL']) / R if up else 0.0))
    H = np.array([prm.H(k) for k in KS], float)
    fb['capital'] = 0.10 * (Vc + (1 - prm.a) * R / Wb * H) * (days / 365.0) / R

    # ---------------- FI (P3 1.1 as P9's GridFI)
    fi = {}
    fi['verify'] = one * cp * n / R
    fi['release'] = rel(n)
    RuI = (E0 + st['UrFI'][0]) * one if up else E + st['UrFI']
    fi['l1'] = wu(RuI * g['RW_F'] + g['RW_M'] * n) / R
    if fac: fi['facil'] = fb['facil'].copy()
    if up: fi['detincl'] = one * gu(g['G_DET'] * n) / R
    fi['deduct'] = one * (M.W0 + (M.W0 * n * gu(g['G_FAIL']) / R if up else 0.0))
    HF = np.array([300 * k + prm.TP for k in KS], float)
    fi['capital'] = 0.10 * HF / Wb * (days / 365.0)
    return fb, fi, sum(fb.values()), sum(fi.values())


def best(tot):
    i = int(np.argmin(tot)); return float(tot[i]), i


def evaluate(M, s, days, lab):
    st = structure(M, s, days)
    fb, fi, tf, ti = costs(M, s, st, lab)
    xb, ib = best(tf); xi, ii = best(ti)
    return dict(fb=xb, kfb=M.KS[ib], fi=xi, kfi=M.KS[ii], fbparts={k: float(v[ib]) for k, v in fb.items()},
                fiparts={k: float(v[ii]) for k, v in fi.items()}, E0=st['E0'], Ek=float(st['E'][ib]))


# ================================================================== stylised seller (calc-rules.md 1)
def stylised(m, v, d=1.0, days=21, Vc=V, ck='RS3'):
    Nep = days * 144; E0 = max(1, int(round(d * Nep)))
    cnt = np.zeros(Nep); cnt[:E0] = m
    n = m * E0
    return dict(a='syn', base='syn', R=m * v * E0, n=n, ns=n * min(1.0, v / Vc), E1=E0, m1=m, cnt=cnt, ck=ck, tier0=False, rs=1.0)


def share_at(M, Re, v, lab, d=1.0, days=21):
    s = stylised(Re / v, v, d, days); return evaluate(M, s, days, lab)


# ================================================================== observed sellers
def ck_of(kind, s): return 'TEE' if kind == 'BR' else ('SP0' if s['tier0'] else 'RS3')


def observed(M):
    out = []
    for p in PER:
        for kind in ('T01t', 'BR'):
            S = M.g['t13_sellers'](kind, p, V)
            for s in S:
                s = dict(s, ck=ck_of(kind, s)); out.append((p, kind, s))
    return out


def check(M, verbose=True):
    """calc-rules.md 3.5: closed form at the observed sellers against p9.json V1, and against P9's Env on stylised sellers."""
    with open(P9J, encoding='utf-8') as fh: P9 = json.load(fh)['variants']['V1']
    res = dict(rows=[], max_fb=0.0, max_fi=0.0, kdiff=0)
    for p, kind, s in observed(M):
        days = M.g['PDAYS'][p]
        for lab in LABS:
            e = evaluate(M, s, days, lab)
            c = P9['%s|1|%s|%s' % (kind, p, lab)]
            wfb, kfb = c['per'][s['a']][:2]; wfi, kfi = c['fi_per'][s['a']]
            dfb = 100 * abs(e['fb'] - wfb); dfi = 100 * abs(e['fi'] - wfi)
            res['max_fb'] = max(res['max_fb'], dfb); res['max_fi'] = max(res['max_fi'], dfi)
            res['kdiff'] += int(e['kfb'] != kfb) + int(e['kfi'] != kfi)
            res['rows'].append(dict(win=p, kind=kind, seller=s['a'], lab=lab, fb=e['fb'], fb_p9=wfb, fi=e['fi'], fi_p9=wfi,
                                    k=e['kfb'], k_p9=kfb, kfi=e['kfi'], kfi_p9=kfi))
    res['observed_ok'] = res['max_fb'] <= TOL_PT and res['max_fi'] <= TOL_PT
    # stylised sellers through P9's Env (the injected window, as test_p9.py does)
    g = M.g; env = M.env
    syn = [stylised(m, v, d) for m, v, d in ((3, 0.01, 1.0), (20, 0.05, 1.0), (300, 0.01, 1.0), (40, 0.2, 0.3),
                                              (2, 1.0, 0.05), (600, 0.002, 1.0), (8, 0.5, 1.0))]
    for i, s in enumerate(syn): s['a'] = 'syn%d' % i
    g['PDAYS']['P10SYN'] = 21
    orig = g['t13_sellers']
    g['t13_sellers'] = lambda st_, p_, V_: [dict(x) for x in syn] if p_ == 'P10SYN' else orig(st_, p_, V_)
    g['_G'].clear(); mx = 0.0; kd = 0
    try:
        for lab in LABS:
            gr = env.fb('T01t:P10SYN', V, lab); o = gr.opt(M.W0)
            fo = env.fi('T01t:P10SYN', lab).opt(M.W0)
            for j, s in enumerate(syn):
                e = evaluate(M, dict(s, ck='RS3'), 21, lab)
                mx = max(mx, 100 * abs(e['fb'] - o['tot'][j]), 100 * abs(e['fi'] - fo['tot'][j]))
                kd += int(e['kfb'] != M.KS[o['ki'][j]]) + int(e['kfi'] != M.KS[fo['ki'][j]])
    finally:
        g['t13_sellers'] = orig; g['_G'].clear(); del g['PDAYS']['P10SYN']
    res['syn_max'] = mx; res['syn_kdiff'] = kd; res['syn_ok'] = mx <= TOL_PT
    res['ok'] = res['observed_ok'] and res['syn_ok']
    if verbose:
        print('observed sellers vs p9.json V1: max |diff| FairBind %.2e pt, FI %.2e pt, k mismatches %d -> %s' % (
            res['max_fb'], res['max_fi'], res['kdiff'], res['observed_ok']))
        print('stylised sellers vs P9 Env V1: max |diff| %.2e pt, k mismatches %d -> %s' % (mx, kd, res['syn_ok']))
    return res


# ================================================================== thresholds and crossings
def scan(f, lo, hi, npts=400):
    xs = np.logspace(math.log10(lo), math.log10(hi), npts); ys = np.array([f(x) for x in xs]); return xs, ys


def bisect(f, a, b, it=60):
    fa = f(a) > 0
    for _ in range(it):
        mid = math.sqrt(a * b)
        if (f(mid) > 0) == fa: a = mid
        else: b = mid
    return math.sqrt(a * b)


def roots(f, lo, hi, npts=400):
    xs, ys = scan(f, lo, hi, npts); out = []
    for i in range(len(xs) - 1):
        if (ys[i] > 0) != (ys[i + 1] > 0):
            r = bisect(f, xs[i], xs[i + 1]); out.append((r, 'down' if ys[i] > 0 else 'up'))
    return out, xs, ys


def thresholds(M, v, lab, d=1.0):
    """R_e where FairBind's cost share crosses each theta (down = enters below, up = leaves), and the FI crossings."""
    lo, hi = v * 1.0, 1e5                 # m >= 1 sale per active profile epoch
    cache = {}
    def ev(Re):
        if Re not in cache: cache[Re] = share_at(M, Re, v, lab, d)
        return cache[Re]
    out = dict(v=v, lab=lab, d=d)
    for th in TH:
        r, xs, ys = roots(lambda x: ev(x)['fb'] - th, lo, hi)
        out['th%g' % th] = [dict(Re=x, m=x / v, dir=dr, k=ev(x)['kfb']) for x, dr in r]
        out['below_at_lo_%g' % th] = bool(ys[0] <= 0)
    r, xs, ys = roots(lambda x: ev(x)['fb'] - ev(x)['fi'], lo, hi)
    out['cross'] = [dict(Re=x, m=x / v, dir=('FairBind becomes cheaper' if dr == 'down' else 'FI becomes cheaper'),
                         share=ev(x)['fb']) for x, dr in r]
    out['fb_cheaper_at_lo'] = bool(ys[0] <= 0)
    out['min_fb'] = float(min(ev(x)['fb'] for x in xs))
    return out


def closed_form_threshold(M, v, lab, k, th):
    """calc-rules.md 2 closed form without the frozen and capital terms, d = 1, m k <= 256, v <= V."""
    g = M.g; prm = M.prm[lab]; gu, wu = prm.gusd, prm.wusd
    a = prm.cpu('RS3') / V + M.W0 + gu(REL['K']) / V
    b = gu(ANC['MU'][1] + ANC['MC'][1] + REL['M1']) + wu(g['L1W_M'][1] + g['RW_M'])   # P = n here, so MC is per sale (P10_independent-check.md 2 grade 1)
    c = gu(ANC['FC'][1] - ANC['MU'][1]) + prm.cl_usd() + wu(g['L1W_F'][1]) + (gu(REL['F1']) + wu(g['RW_F'])) / k
    den = th - a - b / v
    return dict(a=a, b=b, c=c, Re=(c / den if den > 0 else math.inf))


# ================================================================== all recipients from the aggregates
def read_agg(win):
    E = {}
    with gzip.open(AGG / ('epochs_%s.csv.gz' % win), 'rt') as fh:
        for r in csv.DictReader(fh):
            E.setdefault(r['recipient'].lower(), []).append((int(r['epoch']), int(r['n']), int(r['value_atomic_sum'])))
    Vb = {}
    with gzip.open(AGG / ('values_%s.csv.gz' % win), 'rt') as fh:
        for r in csv.DictReader(fh):
            Vb.setdefault(r['recipient'].lower(), []).append((int(r['log10_bin']), int(r['n']), int(r['value_atomic_sum'])))
    return E, Vb


def recipients(win):
    """Every recipient with positive revenue: n, R, n_s at V = 1 (log10 bins below 6 give u / V, bins 6 and up count),
    per-epoch counts, E1, m1, and the largest profile-epoch revenue."""
    E, Vb = read_agg(win); out = []
    for a, rows in E.items():
        ep = np.array([x[0] for x in rows]); c = np.array([x[1] for x in rows], float); val = np.array([x[2] for x in rows], float) / 1e6
        order = np.argsort(ep); ep, c, val = ep[order], c[order], val[order]
        n = float(c.sum()); R = float(val.sum())
        if n <= 0 or R <= 0: continue
        B = Vb.get(a, [])
        nb = sum(x[1] for x in B); Rb = sum(x[2] for x in B) / 1e6
        assert nb == n and abs(Rb - R) < 1e-6 * max(1.0, R), (win, a)
        ns = sum((x[2] / 1e6 / V) if x[0] < 6 else x[1] for x in B)
        u, inv = np.unique(ep, return_inverse=True)
        cc = np.bincount(inv, weights=c); vv = np.bincount(inv, weights=val)
        out.append(dict(a=a, R=R, n=n, ns=float(min(ns, n)), E1=int(len(u)), m1=float(cc.max()), idx=u, c=cc,
                        maxep=float(vv.max()), ck='RS3', tier0=False))
    return out


def structure_sparse(M, s, days):
    """structure() for sparse counts (same formulas)."""
    full = np.zeros(days * 144); full[s['idx']] = s['c']
    return structure(M, dict(s, cnt=full), days)


SUBSETS = (('evm', 'Base(0x) payee'), ('evm_vle', 'Base(0x) payee, mean sales amount V or less'), ('all', 'all payee(0x not address included)'))


def subset_of(a, v):
    evm = a.startswith('0x')
    return [k for k, ok in (('evm', evm), ('evm_vle', evm and v <= V), ('all', True)) if ok]


def region_counts(M, lab='lo'):
    """calc-rules.md 3.4. Regions (A) FairBind cheaper or equal and <= 10%, (B) FI cheaper and <= 10%, (C) neither <= 10%
    (split by the cheaper design), per window and subset (Base addresses, Base addresses with mean sale <= V, all)."""
    res = {}; per = {}
    for p in PER:
        days = M.g['PDAYS'][p]; rec = recipients(p); rows = []
        cnt = {sb: {'A': [0, 0.0], 'B': [0, 0.0], 'C_fb': [0, 0.0], 'C_fi': [0, 0.0]} for sb, _ in SUBSETS}
        tot = {sb: [0, 0.0] for sb, _ in SUBSETS}
        for s in rec:
            st = structure_sparse(M, s, days)
            _, _, tf, ti = costs(M, s, st, lab)
            xb, _ = best(tf); xi, _ = best(ti)
            if xb <= xi and xb <= 0.10: key = 'A'
            elif xi < xb and xi <= 0.10: key = 'B'
            else: key = 'C_fb' if xb <= xi else 'C_fi'
            for sb in subset_of(s['a'], s['R'] / s['n']):
                cnt[sb][key][0] += 1; cnt[sb][key][1] += s['R']; tot[sb][0] += 1; tot[sb][1] += s['R']
            rows.append((s['a'], s['R'], s['R'] / st['E0'], s['R'] / s['n'], xb, xi, key))
        res[p] = {sb: dict(N=tot[sb][0], R=tot[sb][1], counts={k: dict(n=v[0], R=v[1], share=(v[1] / tot[sb][1] if tot[sb][1] else 0.0))
                                                                for k, v in cnt[sb].items()}) for sb, _ in SUBSETS}
        per[p] = rows
    return res, per


# ================================================================== analysis B
def max_epoch_revenue():
    """Largest profile-epoch revenue of each named seller's recipient address in each window (whole address)."""
    addr = {}
    out = {}
    for p in PER:
        E, _ = read_agg(p); out[p] = {}
        for nm, a in p9_addr().items():
            rows = E.get(a.lower(), [])
            if not rows: continue
            d = {}
            for e, n, v in rows: d[e] = d.get(e, 0.0) + v / 1e6
            out[p][nm] = max(d.values())
    return out


_ADDR = None
def p9_addr(): return _ADDR


def margins(M):
    mx = max_epoch_revenue(); out = []
    for p, kind, s in observed(M):
        days = M.g['PDAYS'][p]; Nep = days * 144
        E0 = min(s['E1'], Nep); Re = s['R'] / E0
        Rmax = mx[p].get(s['base']) if p in AGG_SAME else None
        row = dict(win=p, seller=s['a'], base=s['base'], R=s['R'], E0=E0, Re=Re, Rmax=Rmax, part=(s['a'] != s['base']), m={})
        for wl, W, _ in FILL_W:
            for fl, pg in FEES:
                c = fill_cost(W, pg)
                row['m']['%s|%s' % (wl, fl)] = dict(fill=c, mean=c / Re, max=(c / Rmax if Rmax else None))
        out.append(row)
    return out


def klass(x):
    if x is None: return '-'
    return '<1' if x < 1 else ('1~10' if x < 10 else '>=10')


# ================================================================== figure
def figure(M, curves, obs, regmap, OUT):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    plt.rcParams.update({'font.family': 'serif', 'font.serif': ['DejaVu Serif'], 'font.size': 7.5, 'axes.labelsize': 7.5,
                         'legend.fontsize': 6.5, 'xtick.labelsize': 7, 'ytick.labelsize': 7, 'axes.linewidth': 0.6,
                         'lines.linewidth': 1.0, 'pdf.fonttype': 42, 'ps.fonttype': 42})
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(3.5, 5.4), gridspec_kw=dict(height_ratios=[1.0, 0.95]))
    # (a) cost share vs revenue per active profile epoch, lower estimate
    grays = {0.001: '0.0', 0.01: '0.35', 0.1: '0.6'}
    for v in (0.001, 0.01, 0.1):
        xs, fb, fi = curves[v]
        ax.plot(xs, 100 * fb, '-', color=grays[v], lw=1.1)
        ax.plot(xs, 100 * fi, '--', color=grays[v], lw=0.9)
        if v == 0.001:
            ax.annotate(r'$\bar v$=%g' % v, (xs[-1], 100 * fb[-1]), xytext=(-2, 5), textcoords='offset points', fontsize=6, ha='right')
        else:
            ax.annotate(r'$\bar v$=%g' % v, (xs[0], 100 * fb[0]), xytext=(-2, 0), textcoords='offset points', fontsize=6, ha='right', va='center')
    for th in (10, 5): ax.axhline(th, color='0.5', lw=0.5, ls=':')
    mk = {'busy': 'o', 'median': 's', 'quiet': '^'}
    for o in obs:
        if o['lab'] != 'lo': continue
        fc = 'k' if o['kind'] == 'BR' else 'white'
        ax.plot(o['Re'], 100 * o['fb'], mk[o['win']], ms=3.6, mfc=fc, mec='k', mew=0.6, zorder=5)
    for o in obs:
        if o['lab'] == 'lo' and o['win'] == 'busy' and o['short'] in ('SE', 'BR', 'OS', 'Exa'):
            ax.annotate(o['short'], (o['Re'], 100 * o['fb']), xytext=(3, 3), textcoords='offset points', fontsize=5.5)
    ax.set_xscale('log'); ax.set_yscale('log')
    ax.set_xlim(1e-3, 3e2); ax.set_ylim(1, 2500)
    ax.set_xlabel('Revenue per active profile epoch $R_e$ (USDC)')
    ax.set_ylabel('Cost share of revenue (%)')
    ax.set_yticks([1, 5, 10, 100, 1000]); ax.set_yticklabels(['1', '5', '10', '100', '1000'])
    h = [Line2D([], [], color='k', ls='-', label='FairBind'), Line2D([], [], color='k', ls='--', label='Full inspection'),
         Line2D([], [], ls='', marker='o', mfc='white', mec='k', ms=3.6, label='busy'),
         Line2D([], [], ls='', marker='s', mfc='white', mec='k', ms=3.6, label='median'),
         Line2D([], [], ls='', marker='^', mfc='white', mec='k', ms=3.6, label='quiet'),
         Line2D([], [], ls='', marker='o', mfc='k', mec='k', ms=3.6, label='BlockRun (filled)')]
    ax.legend(handles=h, loc='upper right', ncol=2, frameon=False, handlelength=1.8, columnspacing=0.8)
    ax.set_title('(a) Lower estimate, measured gas, $V$ = 1', fontsize=7.5)
    # (b) regions in (m, v)
    ms_, vs_, Z, F = regmap
    from matplotlib.colors import ListedColormap
    cmap = ListedColormap(['0.80', '0.55', '1.0'])
    bx.pcolormesh(ms_, vs_, Z, cmap=cmap, vmin=-0.5, vmax=2.5, shading='nearest', rasterized=True)
    bx.contour(ms_, vs_, F, levels=[0.05, 0.10], colors=['k', 'k'], linestyles=[':', '-'], linewidths=0.7)
    for o in obs:
        if o['lab'] != 'lo': continue
        fc = 'k' if o['kind'] == 'BR' else 'white'
        bx.plot(o['m'], o['v'], mk[o['win']], ms=3.6, mfc=fc, mec='k', mew=0.6, zorder=5)
    bx.set_xscale('log'); bx.set_yscale('log')
    bx.set_xlabel('Sales per active profile epoch $m$')
    bx.set_ylabel(r'Mean sale value $\bar v$ (USDC)')
    from matplotlib.patches import Patch
    h2 = [Patch(fc='0.80', ec='k', lw=0.4, label='FairBind cheaper, $\\leq$10%'), Patch(fc='0.55', ec='k', lw=0.4, label='FI cheaper, $\\leq$10%'),
          Patch(fc='1.0', ec='k', lw=0.4, label='neither $\\leq$10%'),
          Line2D([], [], color='k', ls='-', lw=0.7, label='FairBind 10%'), Line2D([], [], color='k', ls=':', lw=0.7, label='FairBind 5%')]
    bx.legend(handles=h2, loc='upper right', frameon=True, framealpha=0.9, edgecolor='0.7', fancybox=False)
    bx.set_title('(b) Regions, continuously active stylised seller', fontsize=7.5)
    fig.tight_layout(h_pad=0.8)
    fig.savefig(OUT / 'fig_fit.pdf'); fig.savefig(OUT / 'fig_fit.png', dpi=300)
    plt.close(fig)


SHORT = {'StableEnrich': 'SE', 'OneSource': 'OS', 'CoinMarketCap': 'CMC', 'StableApify': 'SA', 'Exa': 'Exa', 'CoinStats': 'CS', 'BlockRun': 'BR'}


def main():
    global _ADDR
    ap = argparse.ArgumentParser(); ap.add_argument('--out'); ap.add_argument('--check', action='store_true')
    ap.add_argument('--fig-only', action='store_true', help='redraw the figure from <out>/p10.json')
    args = ap.parse_args(); T0 = time.time()
    if args.fig_only:
        OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT
        R = json.load(open(OUT / 'p10.json', encoding='utf-8'))
        curves = {float(v): (np.array(c['Re']), np.array(c['fb']), np.array(c['fi'])) for v, c in R['curves'].items()}
        rm = R['regmap']
        figure(None, curves, R['observed'], (np.array(rm['m']), np.array(rm['v']), np.array(rm['Z']), np.array(rm['fb'])), OUT)
        return
    M = Model(); _ADDR = dict(M.g['ADDR'])
    CH = check(M)
    if args.check:
        sys.exit(0 if CH['ok'] else 1)
    assert args.out, '--out or --check'
    assert CH['ok'], 'reproduction failed: no values reported'
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT; OUT.mkdir(parents=True, exist_ok=True)
    R = dict(meta=dict(check={k: v for k, v in CH.items() if k != 'rows'}, V=V, fees=FEES, eth=ETH_FILL, gas_limit=GAS_LIMIT,
                       p9_sha256=hashlib.sha256(P9J.read_bytes()).hexdigest(),
                       p10_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()),
             check_rows=CH['rows'])
    # ---- thresholds
    TT = []
    for lab in LABS:
        for v in VGRID:
            for d in (1.0, 0.1):
                TT.append(thresholds(M, v, lab, d))
    R['thresholds'] = TT
    R['closed_form'] = [dict(lab=lab, v=v, k=k, th=th, **closed_form_threshold(M, v, lab, k, th))
                        for lab in ('lo',) for v in (0.02, 0.05, 0.1, 0.2) for k in (1, 8, 32) for th in TH]
    print('thresholds done %.0fs' % (time.time() - T0), flush=True)
    # ---- curves for the figure (lower, d = 1)
    curves = {}
    for v in (0.001, 0.01, 0.1):
        xs = np.logspace(math.log10(v), math.log10(3e2), 160)
        ev = [share_at(M, x, v, 'lo') for x in xs]
        curves[v] = (xs, np.array([e['fb'] for e in ev]), np.array([e['fi'] for e in ev]))
    R['curves'] = {str(v): dict(Re=c[0].tolist(), fb=c[1].tolist(), fi=c[2].tolist()) for v, c in curves.items()}
    # ---- region map (lower, d = 1)
    ms_ = np.logspace(0, 4, 97); vs_ = np.logspace(-3.5, 0.5, 81)
    Z = np.zeros((len(vs_), len(ms_))); F = np.zeros_like(Z)
    for i, v in enumerate(vs_):
        for j, m in enumerate(ms_):
            e = evaluate(M, stylised(m, v), 21, 'lo')
            F[i, j] = e['fb']
            Z[i, j] = 0 if (e['fb'] <= e['fi'] and e['fb'] <= 0.10) else (1 if (e['fi'] < e['fb'] and e['fi'] <= 0.10) else 2)
    R['regmap'] = dict(m=ms_.tolist(), v=vs_.tolist(), Z=Z.tolist(), fb=F.tolist())
    print('region map done %.0fs' % (time.time() - T0), flush=True)
    # ---- observed sellers
    obs = []
    with open(P9J, encoding='utf-8') as fh: P9 = json.load(fh)['variants']['V1']
    for p, kind, s in observed(M):
        days = M.g['PDAYS'][p]
        for lab in LABS:
            e = evaluate(M, s, days, lab); c = P9['%s|1|%s|%s' % (kind, p, lab)]
            sty = share_at(M, s['R'] / e['E0'], s['R'] / s['n'], lab, d=e['E0'] / (days * 144), days=days)
            obs.append(dict(win=p, kind=kind, seller=s['a'], short=SHORT[s['base']], lab=lab, R=s['R'], n=s['n'], E0=e['E0'],
                            Re=s['R'] / e['E0'], m=s['n'] / e['E0'], v=s['R'] / s['n'], k=e['kfb'], Rk=s['R'] / e['Ek'],
                            fb=c['per'][s['a']][0], fi=c['fi_per'][s['a']][0], kfi=c['fi_per'][s['a']][1],
                            fb_closed=e['fb'], fi_closed=e['fi'], fb_stylised=sty['fb'], fi_stylised=sty['fi'],
                            parts=e['fbparts']))
    R['observed'] = obs
    # ---- all recipients
    REG = {}
    for lab in LABS:
        REG[lab], per = region_counts(M, lab)
        if lab == 'lo': R['recipients_lo'] = {p: [list(r) for r in rows] for p, rows in per.items()}
        print('regions %s done %.0fs' % (lab, time.time() - T0), flush=True)
    R['regions'] = REG
    AM = {}
    for p in PER:
        rec = {x['a']: x for x in recipients(p)}
        for kind in ('T01t', 'BR'):
            for x in M.g['t13_sellers'](kind, p, V):
                if x['a'] != x['base']: continue
                r = rec.get(M.g['ADDR'][x['base']].lower())
                AM['%s|%s' % (p, x['a'])] = dict(k11b=[x['n'], x['R']], agg=([r['n'], r['R']] if r else None))
    R['agg_match'] = AM
    # ---- analysis B
    R['margins'] = margins(M)
    with open(OUT / 'p10.json', 'w') as fh: json.dump(R, fh, indent=1, ensure_ascii=False, allow_nan=True)
    (OUT / 'p10_tables.md').write_text(tables(R), encoding='utf-8')
    figure(M, curves, obs, (ms_, vs_, Z, F), OUT)
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f)
                   for f in ('p10.json', 'p10_tables.md', 'fig_fit.pdf', 'fig_fit.png'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


# ================================================================== tables
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator'}


def pc(x): return '-' if x is None else '%.2f' % (100 * x)
def usd(x): return '-' if x is None or x == math.inf else ('%.4g' % x)


def tables(R):
    L = ['**all values post hoc calculations registered verdict none.** `p10.py` output. P9 V1(measured VRF, release, anchor), mode N, σ 1, r 10%, a 0, '
         'w 0.00173, V 1, per seller optimal k. costs revenue relative to %, R_e active profile per epoch revenue(USDC).\n']
    C = R['meta']['check']
    L.append('reproduction(`--check`): observed seller closed form vs p9.json V1 max difference FairBind %.1e%%p, FI %.1e%%p, k mismatch %d; '
             'stylised seller vs P9 Env max difference %.1e%%p, k mismatch %d. admission 0.05%%p.\n' % (C['max_fb'], C['max_fi'], C['kdiff'], C['syn_max'], C['syn_kdiff']))
    L.append('## 1. threshold (stylised seller, 21 days window, tier 1a proof)\n')
    L.append('R_e USDC, in parentheses sales count m and then k. "below" cost share threshold below entering R_e, "upper" freeze term because again over R_e. '
             'FI crossing two design cost share equalizing R_e(→ after its above more cheaper side).\n')
    L.append('| case | d | v̄ | 10% below | 10% upper | 5% below | 5% upper | min cost share | FI crossing |'); L.append('|---|---|---|---|---|---|---|---|---|')
    for t in R['thresholds']:
        def f(th, dr):
            xs = [x for x in t['th%g' % th] if x['dir'] == dr]
            if not xs: return ('from the start below' if (dr == 'down' and t['below_at_lo_%g' % th]) else 'none')
            return '; '.join('%s (m %s, k %d)' % (usd(x['Re']), usd(x['m']), x['k']) for x in xs)
        cr = '; '.join('%s → %s' % (usd(x['Re']), 'FB' if x['dir'].startswith('FairBind') else 'FI') for x in t['cross']) or \
            ('none(increase FairBind)' if t['fb_cheaper_at_lo'] else 'none(increase FI)')
        L.append('| %s | %g | %g | %s | %s | %s | %s | %s | %s |' % (LN[t['lab']], t['d'], t['v'], f(0.10, 'down'), f(0.10, 'up'),
                                                               f(0.05, 'down'), f(0.05, 'up'), pc(t['min_fb']), cr))
    L.append('\n### closed form, lower (freeze and capital without R_e* = c / (θ − a − b / v̄), d 1, m k ≤ 256, v̄ ≤ V; - θ ≤ a + b / v̄d threshold none)\n')
    L.append('| case | v̄ | k | θ | a | b (USDC/sales) | c (USDC/epoch) | R_e* |'); L.append('|---|---|---|---|---|---|---|---|')
    for c in R['closed_form']:
        L.append('| %s | %g | %d | %g | %.5f | %.3e | %.5f | %s |' % (LN[c['lab']], c['v'], c['k'], c['th'], c['a'], c['b'], c['c'], usd(c['Re'])))
    L.append('\n## 2. observed seller (V1, V 1)\n')
    L.append('| window | seller | case | R_e | m | v̄ | k* | R / E_k* | FairBind | FI | more cheaper side | stylised curve FairBind | stylised curve FI |')
    L.append('|' + '---|' * 13)
    for o in R['observed']:
        L.append('| %s | %s | %s | %s | %s | %s | %d | %s | %s | %s | %s | %s | %s |' % (
            WN[o['win']], o['seller'], LN[o['lab']], usd(o['Re']), usd(o['m']), usd(o['v']), o['k'], usd(o['Rk']), pc(o['fb']), pc(o['fi']),
            'FairBind' if o['fb'] <= o['fi'] else 'FI', pc(o['fb_stylised']), pc(o['fi_stylised'])))
    ob = [o for o in R['observed']]
    nin = sum(1 for o in ob if abs(o['fb_stylised'] - o['fb']) <= TOL_PT / 100)
    L.append('\nclosed form seller own input applied values all in cells P9 and equal(upper reproduction). stylised curve(same R_e, v̄, activity ratio d, per epoch same sales count) value '
             'P9 and 0.05%%p within cell %d / %d. difference per epoch sales count not chosen not(anchor unit, release branch) and k11b E_k from the rule comes.\n' % (nin, len(ob)))
    L.append('\n## 3. before payee region (tier 1a proof, per epoch sales count epochs, n_s values)\n')
    L.append('aggregate quiet window s1b(CDP) data 9/22 one day form, so(F/data-review/target_sellers_all_README.md 5 (line)) k11b quiet window(s1c) and differs. for reference only shown. '
             'busy window and median window name with seller n and R k11b and equal(`agg_match`).\n')
    L.append('(a) FairBind cheaper or equal and 10% or less, (b) FI cheaper and 10% or less, (c) two c 10% over(in parentheses: its among FairBind cheaper count / FI cheaper count).\n')
    L.append('| case | set | window | payee | revenue | (a) count | (a) revenue share | (b) count | (b) revenue share | (c) count | (c) revenue share |'); L.append('|' + '---|' * 11)
    SN = dict(SUBSETS)
    for lab, X in R['regions'].items():
        for sb, _ in SUBSETS:
            for p, xx in X.items():
                x = xx[sb]; c = x['counts']; nC = c['C_fb']['n'] + c['C_fi']['n']; sC = c['C_fb']['share'] + c['C_fi']['share']
                L.append('| %s | %s | %s | %d | %.2f | %d | %s | %d | %s | %d (%d / %d) | %s |' % (
                    LN[lab], SN[sb], WN[p] + ('(reference only)' if p not in AGG_SAME else ''), x['N'], x['R'], c['A']['n'], pc(c['A']['share']),
                    c['B']['n'], pc(c['B']['share']), nC, c['C_fb']['n'], c['C_fi']['n'], pc(sC)))
    L.append('\n## 4. fill margin (fill cost / epoch revenue)\n')
    L.append('fee 0.005 / 0.0100 / 0.0161 gwei. mean R / E0, max window within profile epoch revenue maximum(*: payee whole value, so endpoint partial upper bound; quiet window aggregate k11b data differ left empty). class most low fee(0.005 gwei) <1, 1~10, >=10.\n')
    for wl, W, desc in FILL_W:
        L.append('\n### %s\n' % desc)
        f = R['margins'][0]['m']
        L.append('fill cost USD: %s.\n' % ' / '.join('%.2f' % f['%s|%s' % (wl, fl)]['fill'] for fl, _ in FEES))
        L.append('| window | seller | R_e mean | R_e max | margin(mean) | margin(max) | class(mean, 0.005) | class(max, 0.005) |'); L.append('|' + '---|' * 8)
        for r in R['margins']:
            mm = [r['m']['%s|%s' % (wl, fl)] for fl, _ in FEES]
            L.append('| %s | %s | %s | %s%s | %s | %s | %s | %s |' % (
                WN[r['win']], r['seller'], usd(r['Re']), usd(r['Rmax']), '*' if r['part'] else '',
                ' / '.join(usd(x['mean']) for x in mm), ' / '.join(usd(x['max']) for x in mm), klass(mm[0]['mean']), klass(mm[0]['max'])))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
