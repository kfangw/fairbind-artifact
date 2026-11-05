#!/usr/bin/env python3
"""P11 (post hoc, calc-rules.md): full inspection under measured gas as a function of the proof gas g, sensitivity of the
cost and fit to the wrongful-failure rate w with a correlated failure (one sequencer stall of the BASE1 size per
window), and P9's V1 with the real-USDC gas constants (V1u).

K11/k11b.py is loaded unchanged through P9_posthoc/p9.py (load_k11b, Env). P10_fit-conditions/p10.py (closed form, stylised
sellers, Base payees) and P6_posthoc/p6.py (epochs, deadlines, loss of one failure) are imported for their functions;
their main() is not run. P3_posthoc/p3.py runs its whole calculation at import and is not imported: P3's FI is P9's
Env.GridFI and P3's FB_SHARE is checked by text. Constants are switched by setting module variables (p9.REL_MEAS,
p9.ANC_MEAS, p10.REL, p10.ANC) and clearing the Grid cache; no file outside this folder is written.

    (a) FI-same, FI-own (five points), FI-batch (family G_B + g_b m), FI-W; the grid of g in two modes ('fi': FairBind
         keeps the measured call, 'both': both designs pay g); per-seller crossing gas g*_FI and g*.
    (b) w grid; one stall of L = 2,279 blocks per window at a uniformly drawn start; P10 thresholds under both.
    (c) V1u: P9 V1 with release and anchor constants from release-units/run-logs_USDC/.

    python3 -I p11.py --check-only      # reproduction of values already seen (prints booleans only)
    python3 -I p11.py --out results        # the whole calculation (run only when told to)
"""
import argparse, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
P9D, P10D, P6D, P3D = J / 'P9_posthoc', J / 'P10_fit-conditions', J / 'P6_posthoc', J / 'P3_posthoc'
for _d in (P9D, P10D, P6D):
    if str(_d) not in sys.path: sys.path.insert(0, str(_d))
import p9    # noqa: E402  (functions only)
import p10   # noqa: E402
import p6    # noqa: E402

P9J = P9D / 'results' / 'p9.json'
P10J = P10D / 'results' / 'p10.json'
P3J = P3D / 'results' / 'p3.json'
P3S = P3D / 'results' / 'p3_supp.json'
P6J = P6D / 'results' / 'p6.json'
USDC = J / 'release-units' / 'run-logs_USDC'
FIT_CMP = USDC / 'usdc-vs-mock-gas-fit.txt'
FIT_REL = USDC / 'release-gas-fit-usdc.txt'
FIT_ANC = USDC / 'anchor-gas-fit-usdc.txt'

TH = 0.10
PER = p9.PER
LABS = p9.LABS
KINDS = p9.KINDS
W0 = 0.00173
TOL = 1e-12

# ================================================================== (c) real-USDC constants (calc-rules.md 3.1)
# release-units/run-logs_USDC/usdc-vs-mock-gas-fit.txt 30-60 (line) (fits rounded to gas as P9)
REL1_F_U, REL1_M_U = 87_993, 16_920          # inline (31, 32 (line); release-gas-fit-usdc.txt 20 (line))
RELU_CHK_U = (73_697, 9_888)                 # check (36, 37 (line); release 5 (line))
RELU_PAY_U = (70_153, 12_965)                # payunit (38, 39 (line); release 14 (line))
REL_CUR_U = 69_391                           # pass (33 (line); release 26 (line))
REL1_PROVEN_U = (88_961, 16_044)             # inline_proven (34, 35 (line); release 23 (line))
ANC_UNIT_U = {'plain': (279_844, 16_785), 'marked': (286_868, 19_634), 'accepted': (260_004, 28_127)}       # 40-43, 16 (line)
ANC_COMPLETE_U = {'plain': (288_481, 5_135), 'marked': (304_790, 19_873), 'accepted': (320_654, 11_557)}   # 44-49 (line)
ANC_CHUNK_U = {'plain': (41_128, 5_135), 'marked': (59_124, 19_873), 'accepted': (71_637, 11_557)}         # 50-55 (line)
ANC_PULLSALE_U = {'marked': 77_008, 'accepted': 82_006}                                                     # 56-57 (line)


def rel_meas(f1, m1, chk, pay, cur, proven, N=p9.N_REL):
    """P9's REL_MEAS (p9.py 73-74) from the measured release rows."""
    return dict(N=float(N), F1=f1, M1=m1, FU=chk[0] + pay[0], MU=chk[1] + pay[1], FC=cur, K=proven[1] - m1)


def anc_meas(unit, complete, N=p9.N_UNIT):
    """P9's ANC_MEAS (p9.py 87-92) from the measured anchor rows (sigma mixes plain and accepted leaves)."""
    return dict(N=float(N), FU={0: unit['plain'][0], 1: unit['accepted'][0]}, MU={0: unit['plain'][1], 1: unit['accepted'][1]},
                FC={0: complete['plain'][0], 1: complete['plain'][0] + unit['accepted'][1] - unit['plain'][1]},
                MC={0: complete['plain'][1], 1: complete['plain'][1]}, FL=None)


REL_MEAS_U = rel_meas(REL1_F_U, REL1_M_U, RELU_CHK_U, RELU_PAY_U, REL_CUR_U, REL1_PROVEN_U)
ANC_MEAS_U = anc_meas(ANC_UNIT_U, ANC_COMPLETE_U)
REL_MEAS_V1 = p9.REL_MEAS                    # the mock-token values as p9.py defines them (captured at import)
ANC_MEAS_V1 = p9.ANC_MEAS
P10_REL0, P10_ANC0 = p10.REL, p10.ANC
CONSTS = {'V1': (REL_MEAS_V1, ANC_MEAS_V1), 'V1u': (REL_MEAS_U, ANC_MEAS_U)}
BASES = ('V1u', 'V1')
# (file, line, text that must be on that line) for every constant (checked in test_p11.py)
SOURCES = [(FIT_CMP, 31, 'REL1_F (inline fixed)                   75331 ->      87993'),
           (FIT_CMP, 32, 'REL1_M (inline per sale)                16920 ->      16920'),
           (FIT_CMP, 33, 'REL_CUR (pass)                          69391 ->      69391'),
           (FIT_CMP, 34, 'REL1_PROVEN fixed                       76299 ->      88961'),
           (FIT_CMP, 35, 'REL1_PROVEN per sale                    16044 ->      16044'),
           (FIT_CMP, 36, 'RELU_CHK fixed                          73697 ->      73697'),
           (FIT_CMP, 37, 'RELU_CHK per sale                        9888 ->       9888'),
           (FIT_CMP, 38, 'RELU_PAY fixed                          57491 ->      70153'),
           (FIT_CMP, 39, 'RELU_PAY per sale                       12965 ->      12965'),
           (FIT_CMP, 40, 'ANC_UNIT plain fixed                   279842 ->     279844'),
           (FIT_CMP, 41, 'ANC_UNIT plain per leaf                 16784 ->      16785'),
           (FIT_CMP, 42, 'ANC_UNIT accepted fixed                260025 ->     260004'),
           (FIT_CMP, 43, 'ANC_UNIT accepted per leaf              28126 ->      28127'),
           (FIT_CMP, 44, 'ANC_COMPLETE plain fixed               288468 ->     288481'),
           (FIT_CMP, 45, 'ANC_COMPLETE plain per record            5135 ->       5135'),
           (FIT_CMP, 46, 'ANC_COMPLETE marked fixed              296283 ->     304790'),
           (FIT_CMP, 47, 'ANC_COMPLETE marked per record          15711 ->      19873'),
           (FIT_CMP, 48, 'ANC_COMPLETE accepted fixed            308017 ->     320654'),
           (FIT_CMP, 49, 'ANC_COMPLETE accepted per record        11557 ->      11557'),
           (FIT_CMP, 52, 'ANC_CHUNK marked fixed                  50624 ->      59124'),
           (FIT_CMP, 53, 'ANC_CHUNK marked per record             15711 ->      19873'),
           (FIT_CMP, 54, 'ANC_CHUNK accepted fixed                58975 ->      71637'),
           (FIT_CMP, 56, 'ANC_PULLSALE marked                     64346 ->      77008'),
           (FIT_CMP, 57, 'ANC_PULLSALE accepted                   69344 ->      82006'),
           (FIT_CMP, 58, 'REL FU (check + payunit fixed)         131188 ->     143850'),
           (FIT_CMP, 59, 'REL MU (check + payunit per sale)     22853.1 ->    22853.1'),
           (FIT_CMP, 60, 'ANC FC signed (P9\'s derived term)      299810 ->     299823'),
           (FIT_CMP, 16, 'unit_marked            286824   19633.5 |     286868   19634.4'),
           (FIT_REL, 20, 'fixed 87993, per sale 16920.2'), (FIT_REL, 23, 'fixed 88961, per sale 16044.1'),
           (FIT_REL, 5, 'fixed 73697, per sale 9888.3'), (FIT_REL, 14, 'fixed 70153, per sale 12964.7'),
           (FIT_REL, 26, 'fixed 69391, per sale 0.0'),
           (FIT_ANC, 37, 'fixed 279844, per record 16784.8'), (FIT_ANC, 31, 'fixed 260004, per record 28126.6'),
           (FIT_ANC, 22, 'fixed 288481, per record 5134.9'), (FIT_ANC, 19, 'fixed 304790, per record 19872.6'),
           (FIT_ANC, 34, 'fixed 286868, per record 19634.4'), (FIT_ANC, 16, 'fixed 320654, per record 11556.7')]

# ================================================================== (a) proof-call gas (calc-rules.md 1.2)
G_FB_1A = 86_824                 # G11 t1a.tsv.gz row 1; namespace CPG['RS3'] (k11b.py 704, 712)
G_VERIFIER = 31_315              # G10b 'G10-3 Pyth Lazer-shaped update, 1 feed(s)' (k11b.py 170, CPG['PY1'])
FB_SHARE = G_FB_1A - G_VERIFIER  # 55,509: G11_gas.md 147 (line), p3.py 41 (line)
OWN_KEEP = (14_300, 41_300)      # P3_posthoc/independent-check.md 4.2 table: FairBind part kept by the simplest FI (estimate)
SELF_SIGNED = (882_687, 363_102)     # G11 selfsub.tsv.gz: one unit, m = 32 and 8, all signed (tx gas)
SELF_UNSIGNED = (605_045, 294_165)   # same, none signed


def binding_gas():
    """Per-sale anchor gas of a signed sale minus an unsigned one in the G11 rows (P3 independent-check 4.2: about 8,700)."""
    return int(round((SELF_SIGNED[0] - SELF_SIGNED[1]) / 24 - (SELF_UNSIGNED[0] - SELF_UNSIGNED[1]) / 24))


BIND = binding_gas()             # 8,696
FI_POINTS = {'same': G_FB_1A, 'own_lo': G_VERIFIER, 'own_a': G_VERIFIER + OWN_KEEP[0], 'own_b': G_VERIFIER + OWN_KEEP[1],
             'own_bind_a': G_VERIFIER + OWN_KEEP[0] + BIND, 'own_bind_b': G_VERIFIER + OWN_KEEP[1] + BIND}
G_GRID = tuple(sorted(set(range(20_000, 120_001, 5_000)) | set(FI_POINTS.values())))
MODES = ('fi', 'both')
GB_GRID = (21_000, 31_315, 55_509, 86_824)
GM_GRID = (1_000, 2_500, 5_000, 10_315, 20_000, 31_315)
TX_CAP = 2 ** 24


def cp_shift(gusd, cks, cp, g1a):
    """Proof price per sale when the tier-1a call is g1a gas (calc-rules.md 1.2): s = 86,824 - g1a gas removed from tier 1a
    ('RS3') and tier 0 ('SP0') alike, the TEE call unchanged (P3 FI-min, p3.py 76 (line)); L1 of the measured call kept."""
    s = G_FB_1A - g1a
    return np.array([c if k == 'TEE' else c - gusd(s) for c, k in zip(cp, cks)], float)


def cp_teeW(gusd, cks, cp):
    """P3 FI-W (calc-rules.md 1.2): the FairBind share added to the TEE call."""
    return np.array([c + gusd(FB_SHARE) if k == 'TEE' else c for c, k in zip(cp, cks)], float)


def own_call_gas(g, ck, up):
    """The seller's own proof-call gas without tier 0's history read (P3 p3_tables.py 161 (line))."""
    if ck == 'SP0': return float(g['SP0_UP'] if up else g['CPG']['SP0'][0])
    return float(g['CPG'][ck][0])


def gstar(xb, xf, R, n, ns, gu1, g_own, mode):
    """Crossing gas (calc-rules.md 1.4): mode 'fi' moves only FI's call, 'both' moves the call of both designs."""
    den = n if mode == 'fi' else (n - ns)
    return g_own + (xb - xf) * R / (den * gu1)


def batch_cap(GB, gb): return float(math.floor((TX_CAP - GB) / gb))


def batch_tx(g, gr, cap):
    """Batch proof transactions T(k) = E(k) + X(k; cap) per (k, seller) of a k11b grid (calc-rules.md 1.2 FI-batch);
    X from per-epoch counts (splits_from_counts, k11b.py 372) or the bound (splits_bound); upper case: the k = 1 grouping."""
    KS = g['KS']; T = np.empty_like(gr.E)
    for i, k in enumerate(KS):
        for j, s in enumerate(gr.S):
            if s['cnt'] is not None: x = g['splits_from_counts'](s['cnt'], k, cap)
            else: x = g['splits_bound'](s['n'], gr.E[i, j], s['m1'], k, cap)
            T[i, j] = gr.E[i, j] + x
    if gr.prm.up and gr.prm.curpe: T[:] = T[0][None, :]
    return T


def verify_batch(g, gr, GB, gb, cks):
    """FI-batch proof term (share of revenue) for the tier-1a sellers; other sellers keep their per-sale term."""
    prm = gr.prm; T = batch_tx(g, gr, batch_cap(GB, gb))
    w1 = prm.wusd(g['CPG']['RS3'][1])
    vb = (prm.gusd(GB) * T + (prm.gusd(gb) + w1) * gr.n[None, :]) / gr.R[None, :]
    is1a = np.array([c == 'RS3' for c in cks])
    return np.where(is1a[None, :], vb, gr.c0parts['verify'])


def pick(tot):
    ki = np.argmin(tot, axis=0); j = np.arange(tot.shape[1])
    return ki, tot[ki, j]


def region(xb, xf, th=TH):
    """P10 calc-rules 3.4: A FairBind cheaper or equal and <= th, B FI cheaper and <= th, else C (with the cheaper)."""
    if xb <= xf and xb <= th: return 'A'
    if xf < xb and xf <= th: return 'B'
    return 'C_fb' if xb <= xf else 'C_fi'


def summarize(names, R, xb, xf, kb, kf, KS):
    """One scenario on one set of sellers."""
    Rs = float(R.sum()); reg = [region(float(a), float(b)) for a, b in zip(xb, xf)]
    sh = lambda key: float(sum(R[j] for j, r in enumerate(reg) if r == key) / Rs)
    return dict(agg_fb=float((xb * R).sum() / Rs), agg_fi=float((xf * R).sum() / Rs),
                agg_mix=float((np.minimum(xb, xf) * R).sum() / Rs),
                share_A=sh('A'), share_B=sh('B'), names_A=[names[j] for j, r in enumerate(reg) if r == 'A'],
                names_B=[names[j] for j, r in enumerate(reg) if r == 'B'], n_fi_cheaper=int(sum(1 for a, b in zip(xb, xf) if b < a)),
                share_fi_cheaper=float(sum(R[j] for j in range(len(R)) if xf[j] < xb[j]) / Rs),
                per={names[j]: [float(xb[j]), int(KS[kb[j]]), float(xf[j]), int(KS[kf[j]]), reg[j]] for j in range(len(R))})


# ================================================================== (b) w grid and the stall (calc-rules.md 2)
W_GRID = (('0', 0.0), ('w0/10', W0 / 10), ('wf1', 0.000217), ('w0/3', W0 / 3), ('w0', W0), ('0.002', 0.002),
          ('3w0', 3 * W0), ('0.005', 0.005), ('0.01', 0.01), ('10w0', 10 * W0))
STALL_L = p6.GAP[1] - p6.GAP[0] + 1          # 2,279 blocks (supp:base1; p6.py 33 (line))
STALL_W = (('0', 0.0), ('w0', W0))
EPB = 300


def rel_deadlines(nep, a_A, sv, tp):
    """last(e) (phase 0, p6.epoch_bounds with F = 0, t0 = 0), A_e, P_e and FI's D_e = last(e) + T_p, in window blocks."""
    last = np.array([p6.epoch_bounds(e, 0, 0)[1] for e in range(nep)], np.int64)
    A, M, P = p6.deadlines(last, a_A, sv, tp)
    return last, A, P, last + tp


def cover(D, L, S):
    """Number of starts s in [0, S] with s <= D <= s + L - 1."""
    D = np.asarray(D, np.int64)
    return np.maximum(np.minimum(D, S) - np.maximum(D - L + 1, 0) + 1, 0)


def mean_fail(D, x, L, S):
    """Mean over s in [0, S] of 1 - exp(sum of x over the points D in [s, s + L - 1]); x = -inf marks a certain failure."""
    D = np.asarray(D, np.int64); x = np.asarray(x, float)
    lo = np.maximum(D - L + 1, 0); hi = np.minimum(D, S); ok = lo <= hi
    D, x, lo, hi = D[ok], x[ok], lo[ok], hi[ok]
    cert = np.isneginf(x)
    dl = np.zeros(S + 2); dc = np.zeros(S + 2)
    np.add.at(dl, lo[~cert], x[~cert]); np.add.at(dl, hi[~cert] + 1, -x[~cert])
    np.add.at(dc, lo[cert], 1.0); np.add.at(dc, hi[cert] + 1, -1.0)
    ls = np.cumsum(dl)[:S + 1]; cc = np.cumsum(dc)[:S + 1]
    pf = np.where(cc > 0.5, 1.0, -np.expm1(np.minimum(ls, 0.0)))
    return float(pf.mean())


def fail_points(c, pi, q, A, P):
    """Deadline points and log-survival weights (P6 2.1, 2.2): anchors c_e ln(1 - pi), proofs c_e ln(1 - pi q)."""
    c = np.asarray(c, float); act = c > 0; x = min(1.0, pi * min(1.0, q))
    la = np.full(int(act.sum()), -np.inf) if pi >= 1.0 else c[act] * math.log1p(-pi)
    lb = np.full(int(act.sum()), -np.inf) if x >= 1.0 else c[act] * math.log1p(-x)
    return np.concatenate([A[act], P[act]]), np.concatenate([la, lb])


def stall_fb(c, pi, q, nep, L, a_A, sv, tp):
    """calc-rules.md 2.2: mean failure probability of a seller over the stall's start, the expected anchor deadlines covered
    (epochs with a sale) and the expected sampled sales whose proof deadline is covered."""
    Wb = nep * EPB; S = Wb - L
    _, A, P, _ = rel_deadlines(nep, a_A, sv, tp)
    c = np.asarray(c, float); assert len(c) == nep, (len(c), nep)
    D, x = fail_points(c, pi, q, A, P)
    act = c > 0
    return dict(P=mean_fail(D, x, L, S), anchors=float(cover(A[act], L, S).sum() / (S + 1)),
                proofs=float((c * pi * min(1.0, q) * cover(P, L, S)).sum() / (S + 1)), src='counts')


def stall_fb_bounds(E1, ns, nep, L):
    """Without per-epoch counts: E1 consecutive active epochs (lower) and the union bound (upper)."""
    S1 = nep * EPB - L + 1
    lo = min(1.0, ((E1 - 1) * EPB + L) / S1) if E1 >= 1 else 0.0
    up = min(1.0, (E1 + ns) * L / S1)
    return dict(P=up, P_lo=lo, P_up=up, anchors=None, proofs=None, src='bound')


def stall_fi(c, pi, nep, L, tp):
    """Expected share of a seller's sales whose FI proof deadline D_e = last(e) + T_p is covered."""
    Wb = nep * EPB; S = Wb - L
    _, _, _, D = rel_deadlines(nep, 120, 31, tp)
    c = np.asarray(c, float) * pi
    return float((c * cover(D, L, S)).sum() / ((S + 1) * c.sum()))


def stall_fi_bound(nep, L): return L / (nep * EPB - L + 1)


def stall_inputs(g, p, s, n):
    """Per-epoch counts and the part share pi of a seller (calc-rules.md 2.2)."""
    if s.get('cnt') is not None: return np.asarray(s['cnt'], float), 1.0, 'own'
    key = (p, s['base'])
    if key in g['LCNT'] and p in g['SUMALL']:
        addr = {r['seller']: int(r['sales']) for r in g['SUMALL'][p]}
        if s['base'] in addr: return np.asarray(g['LCNT'][key], float), float(n) / addr[s['base']], 'address'
    return None, None, 'bound'


def stall_seller(g, p, gr, j, L=STALL_L):
    """Stall terms of seller j of a FairBind grid gr: FB share P l / R and FI share f (+ failure gas in the upper case)."""
    prm = gr.prm; s = gr.S[j]; nep = gr.days * 144
    n, ns, R = float(gr.n[j]), float(gr.ns[j]), float(gr.R[j])
    c, pi, src = stall_inputs(g, p, s, n)
    q = ns / n
    if c is not None:
        fb = stall_fb(c, pi, q, nep, L, prm.DA, prm.SV, prm.TP); fb['src'] = src
        f = stall_fi(c, pi, nep, L, prm.TP)
    else:
        fb = stall_fb_bounds(float(s['E1']), ns, nep, L); f = stall_fi_bound(nep, L)
    DF = float(gr.DFk[0, 0]); assert np.all(gr.DFk == DF)
    gasf = prm.gusd(g['G_FAIL']) if prm.up else 0.0
    loss = p6.loss_per_failure(R, float(gr.Wb), DF, float(gr.b), a=float(prm.a), gasf=gasf)
    fi_gas = f * n * prm.gusd(g['G_FAIL']) / R if prm.up else 0.0
    return dict(fb, pi=pi, q=q, loss=loss['total'], fb_add=fb['P'] * loss['total'] / R, fi_frac=f, fi_add=f + fi_gas)


def thresholds_gen(ev, v, lab, d, ths=p10.TH, hi=1e5):
    """p10.thresholds (P10 calc-rules 3.2) with the cost function ev(R_e) -> dict(fb, fi, kfb) as an argument."""
    lo = v * 1.0; cache = {}
    def e(Re):
        if Re not in cache: cache[Re] = ev(Re)
        return cache[Re]
    out = dict(v=v, lab=lab, d=d)
    for th in ths:
        r, xs, ys = p10.roots(lambda x: e(x)['fb'] - th, lo, hi)
        out['th%g' % th] = [dict(Re=x, m=x / v, dir=dr, k=e(x)['kfb']) for x, dr in r]
        out['below_at_lo_%g' % th] = bool(ys[0] <= 0)
    r, xs, ys = p10.roots(lambda x: e(x)['fb'] - e(x)['fi'], lo, hi)
    out['cross'] = [dict(Re=x, m=x / v, dir=('FairBind becomes cheaper' if dr == 'down' else 'FI becomes cheaper'),
                         share=e(x)['fb']) for x, dr in r]
    out['fb_cheaper_at_lo'] = bool(ys[0] <= 0)
    out['min_fb'] = float(min(e(x)['fb'] for x in xs))
    return out


# ================================================================== the environment
class P11:
    """One k11b namespace with P9's Env (FairBind, FI, FR) and a P10 Model on the same namespace; the base variant
    (V0, V1 or V1u) is switched through the module variables of p9 and p10."""

    def __init__(self, with_fr=True, tag='k11b_p11'):
        g, repro = p9.load_k11b(tag)
        self.g = g; self.repro = repro
        self.env = p9.Env(g, with_fr=with_fr)
        self.set_base('V1')
        M = p10.Model.__new__(p10.Model)
        M.g = g; M.env = self.env; M.KS = list(g['KS']); M.W0 = g['W0']
        M.prm = {lab: self.env.prm(lab) for lab in LABS}
        M.dep = g['depth_of'](float(p9.N_UNIT))
        assert g['cap_anchor'](M.prm['lo']) == float(p9.N_UNIT) and self.env.lower_rnd == 'cl'
        self.M = M
        assert g['W0'] == W0 and g['CPG']['RS3'][0] == G_FB_1A and g['CPG']['PY1'][0] == G_VERIFIER

    def set_base(self, name):
        rel, anc = CONSTS['V1'] if name == 'V0' else CONSTS[name]
        p9.REL_MEAS = rel; p9.ANC_MEAS = anc; p10.REL = rel; p10.ANC = anc
        self.env.set_variant('V0' if name == 'V0' else 'V1')
        self.base = name

    def set_consts(self, rel, anc):
        """Arbitrary release and anchor constants under the V1 code path (tests and the mock set-back)."""
        p9.REL_MEAS = rel; p9.ANC_MEAS = anc; p10.REL = rel; p10.ANC = anc
        self.env.set_variant('V1'); self.base = 'custom'

    @staticmethod
    def restore():
        p9.REL_MEAS = REL_MEAS_V1; p9.ANC_MEAS = ANC_MEAS_V1; p10.REL = P10_REL0; p10.ANC = P10_ANC0


# ================================================================== reproduction checks (calc-rules.md 0.4)
def tree_diff(a, b, path=''):
    """Largest absolute difference of numbers and the list of structural mismatches between two JSON-like trees."""
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return (0.0, []) if a == b else (math.inf, [path])
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int): return (0.0, []) if a == b else (math.inf, [path])
        if math.isnan(a) and math.isnan(b): return 0.0, []
        d = abs(a - b); return (d, []) if d <= TOL else (d, [path])
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b): return math.inf, [path + ' keys']
        mx, bad = 0.0, []
        for k in a:
            d, bb = tree_diff(a[k], b[k], path + '/' + str(k)); mx = max(mx, d); bad += bb
        return mx, bad
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b): return math.inf, [path + ' len']
        mx, bad = 0.0, []
        for i, (x, y) in enumerate(zip(a, b)):
            d, bb = tree_diff(x, y, path + '[%d]' % i); mx = max(mx, d); bad += bb
        return mx, bad
    return math.inf, [path + ' type']


def jsonable(x): return json.loads(json.dumps(x, allow_nan=True))


def check_v1_p9(X):
    """0.4 (2): V1 through the P11 constant switch reproduces p9.json variants.V1."""
    X.set_base('V1')
    with open(P9J, encoding='utf-8') as fh: want = json.load(fh)['variants']['V1']
    got = jsonable(p9.cells(X.env))
    mx, bad = tree_diff(got, want)
    return dict(v1_p9_maxdiff=mx, v1_p9_bad=bad[:10], v1_p9_ok=(not bad))


def fi_cells_shift(X, mode, g1a=None, tee=False):
    """FI aggregates and per-seller totals with the proof price changed (P3 compare() layout)."""
    g = X.g; W = g['W0']; KS = g['KS']; out = {}
    for p in PER:
        for lab in LABS:
            rows = {}
            for kind in KINDS:
                st = kind + ':' + p; fb = X.env.fb(st, 1.0, lab)
                if not fb.ok: continue
                fi = X.env.fi(st, lab); prm = fi.prm
                cp = fi.cp
                if tee: cp = cp_teeW(prm.gusd, fi.ck, cp)
                if g1a is not None: cp = cp_shift(prm.gusd, fi.ck, cp, g1a)
                tf = fi.total(W) - fi.c0parts['verify'] + (cp * fi.n / fi.R)[None, :]
                tb = fb.total(W)
                if tee: tb = tb - fb.c0parts['verify'] + (cp_teeW(prm.gusd, fb.ck, fb.cp) * fb.ns / fb.R)[None, :]
                kb, xb = pick(tb); kf, xf = pick(tf)
                for j, a in enumerate(fb.a_):
                    rows[a] = dict(kind=kind, R=float(fb.R[j]), fb=float(xb[j]), fi=float(xf[j]), fb_k=int(KS[kb[j]]), fi_k=int(KS[kf[j]]))
            six = {a: r for a, r in rows.items() if r['kind'] == 'T01t'}
            RS = sum(r['R'] for r in six.values())
            out['%s|%s' % (p, lab)] = dict(rows=rows, agg_fi=sum(r['fi'] * r['R'] for r in six.values()) / RS,
                                           agg_fb=sum(r['fb'] * r['R'] for r in six.values()) / RS)
    return out


def check_p3(X):
    """0.4 (4): at V0, g = 31,315 gives P3 FI_min and the TEE call plus 55,509 in both designs gives P3 FI_W; at V1,
    g = 86,824 equals the unchanged FI."""
    with open(P3J, encoding='utf-8') as fh: P3 = json.load(fh)
    X.set_base('V0'); o = {}
    for key, kw in (('FI_min', dict(mode='fi', g1a=G_VERIFIER)), ('FI_W', dict(mode='both', tee=True)), ('FI', dict(mode='fi'))):
        got = fi_cells_shift(X, **kw); mx = 0.0; kd = 0
        for c, want in P3[key].items():
            x = got[c]; mx = max(mx, abs(x['agg_fi'] - want['agg_fi']), abs(x['agg_fb'] - want['agg_fb']))
            for r in want['rows']:
                y = x['rows'][r['a']]
                mx = max(mx, abs(y['fi'] - r['fi']), abs(y['fb'] - r['fb'])); kd += int(y['fi_k'] != r['fi_k']) + int(y['fb_k'] != r['fb_k'])
        o[key] = dict(maxdiff=mx, kdiff=kd, ok=(mx <= TOL and kd == 0))
    X.set_base('V1')
    with open(P9J, encoding='utf-8') as fh: V1 = json.load(fh)['variants']['V1']
    got = fi_cells_shift(X, mode='fi', g1a=G_FB_1A); mx = 0.0
    for c, x in got.items():
        p, lab = c.split('|')
        for kind in KINDS:
            w = V1.get('%s|1|%s|%s' % (kind, p, lab))
            if w is None: continue
            for a, v in w['fi_per'].items(): mx = max(mx, abs(x['rows'][a]['fi'] - v[0]))
    o['same_v1'] = dict(maxdiff=mx, ok=mx <= TOL)
    return o


def check_gstar(X):
    """0.4 (5): at V0 the closed form gives P3's gstar (p3_supp.json) and StableEnrich's g*_FI of P3 independent-check 2.2."""
    with open(P3S, encoding='utf-8') as fh: S = json.load(fh)
    X.set_base('V0'); gs = gstar_cells_p(X, 'lo', PER); mx = 0.0; n = 0
    for key, v in S.items():
        if not key.startswith('gstar|'): continue
        _, p, a = key.split('|'); mx = max(mx, abs(gs['%s|%s' % (p, a)]['both'] - v)); n += 1
    se = [int(round(gs['%s|StableEnrich(Out candidates excluded)' % p]['fi'])) for p in PER]
    X.set_base('V1')
    return dict(gstar_maxdiff=mx, gstar_n=n, gstar_ok=(mx <= 1e-6 and n == 21), se_fi=se, se_fi_ok=(se == [49_734, 52_253, 41_406]))


def check_p10(X):
    """0.4 (6): p10.check at V1 and the general threshold function against p10.json (lower, d = 1, v 0.1 and 0.02)."""
    X.set_base('V1'); M = X.M
    ch = p10.check(M, verbose=False)
    with open(P10J, encoding='utf-8') as fh: T = json.load(fh)['thresholds']
    mx = 0.0; bad = []
    for v in (0.1, 0.02):
        want = [t for t in T if t['lab'] == 'lo' and t['d'] == 1.0 and t['v'] == v][0]
        got = jsonable(thresholds_gen(lambda Re, v=v: p10.share_at(M, Re, v, 'lo', 1.0), v, 'lo', 1.0))
        d, b = tree_diff_rel(got, want); mx = max(mx, d); bad += b
    return dict(p10_check_ok=bool(ch['ok']), thr_maxrel=mx, thr_bad=bad, thr_ok=(not bad))


def tree_diff_rel(a, b, path=''):
    """tree_diff with a relative tolerance for floats."""
    if isinstance(a, float) and isinstance(b, float):
        d = abs(a - b) / max(abs(a), abs(b), 1e-300); return (d, []) if d <= TOL else (d, [path])
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b): return math.inf, [path + ' keys']
        mx, bad = 0.0, []
        for k in a:
            d, bb = tree_diff_rel(a[k], b[k], path + '/' + str(k)); mx = max(mx, d); bad += bb
        return mx, bad
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): return math.inf, [path + ' len']
        mx, bad = 0.0, []
        for i, (x, y) in enumerate(zip(a, b)):
            d, bb = tree_diff_rel(x, y, path + '[%d]' % i); mx = max(mx, d); bad += bb
        return mx, bad
    return tree_diff(a, b, path)


def fail_at(D, x, s, L):
    """Failure probability for one stall start s (the point version of mean_fail)."""
    D = np.asarray(D, np.int64); x = np.asarray(x, float); inn = (D >= s) & (D <= s + L - 1)
    if np.any(np.isneginf(x[inn])): return 1.0
    return float(-np.expm1(x[inn].sum()))


def check_p6(X):
    """0.4 (7): the stall machinery at the real BASE1 gap with P6's inputs (address counts, pi, q, busy-window phase)
    gives p6.json's per-seller failure probability and loss."""
    with open(P6J, encoding='utf-8') as fh: P6 = json.load(fh)
    X.set_base('V0'); g = X.g; C = p6.consts(g); t0 = P6['t0']; F = p6.F_BUSY; nep = 21 * 144
    last = np.array([p6.epoch_bounds(e, F, t0)[1] for e in range(nep)], np.int64)
    A, Mx, Pd = p6.deadlines(last, C['a_A'], C['SV'], C['TP'])
    addr_n = {r['seller']: int(r['sales']) for r in g['SUMALL']['busy']}
    mx = 0.0; n = 0
    for kind in KINDS:
        gr = g['G'](kind + ':busy', 1.0, g['LOm']('N')); o = gr.opt(g['W0'])
        rows = {r['seller']: r for r in P6[kind]['rows']}
        for j, s in enumerate(gr.S):
            c = g['LCNT'][('busy', s['base'])]; pi = float(gr.n[j]) / addr_n[s['base']]; q = float(gr.ns[j]) / float(gr.n[j])
            D, x = fail_points(c, pi, q, A, Pd)
            Pany = fail_at(D, x, p6.GAP[0], STALL_L)
            i = int(o['ki'][j])
            loss = p6.loss_per_failure(float(gr.R[j]), float(gr.Wb), float(gr.DFk[i, 0]), float(gr.b))['total']
            r = rows[gr.a_[j]]; mx = max(mx, abs(Pany - r['gap']['Pany']), abs(loss - r['loss']['total'])); n += 1
    X.set_base('V1')
    return dict(p6_maxdiff=mx, p6_n=n, p6_ok=(mx <= TOL and n > 0))


def checks(X):
    o = dict(k11b_reproduced=bool(X.repro))
    o.update(check_v1_p9(X))
    X.set_base('V0'); r0 = p9.repro_v0(X.env); o['v0_fi_fr_ok'] = bool(r0['fi_ok'] and r0['fr_ok'])
    P3c = check_p3(X); o['p3'] = P3c; o['p3_ok'] = all(v['ok'] for v in P3c.values())
    o.update(check_gstar(X))
    o.update(check_p10(X))
    o.update(check_p6(X))
    X.set_base('V1')
    o['all_ok'] = bool(o['k11b_reproduced'] and o['v1_p9_ok'] and o['v0_fi_fr_ok'] and o['p3_ok'] and o['gstar_ok'] and o['se_fi_ok']
                       and o['p10_check_ok'] and o['thr_ok'] and o['p6_ok'])
    return o


# ================================================================== (a) computation (stage 2 on real data)
def scenarios():
    """Scenario keys of (a): FI points, the g grid in two modes, FI-batch, FI-W."""
    S = [('pt|' + k, dict(kind='g', mode='fi', g=v)) for k, v in FI_POINTS.items()]
    S += [('g|%s|%d' % (m, gg), dict(kind='g', mode=m, g=gg)) for m in MODES for gg in G_GRID]
    S += [('batch|%d|%d' % (GB, gb), dict(kind='batch', GB=GB, gb=gb)) for GB in GB_GRID for gb in GM_GRID]
    S += [('teeW', dict(kind='teeW'))]
    return S


def named_terms(X, fb, fi, sc):
    """(FB total, FI total) arrays of one scenario on a pair of k11b grids at w0."""
    g = X.g; W = g['W0']; prm = fb.prm
    tb = fb.total(W); tf = fi.total(W)
    if sc['kind'] == 'g':
        tf = tf - fi.c0parts['verify'] + (cp_shift(prm.gusd, fi.ck, fi.cp, sc['g']) * fi.n / fi.R)[None, :]
        if sc['mode'] == 'both':
            tb = tb - fb.c0parts['verify'] + (cp_shift(prm.gusd, fb.ck, fb.cp, sc['g']) * fb.ns / fb.R)[None, :]
    elif sc['kind'] == 'batch':
        tf = tf - fi.c0parts['verify'] + verify_batch(g, fi, sc['GB'], sc['gb'], fi.ck)
    elif sc['kind'] == 'teeW':
        tf = tf - fi.c0parts['verify'] + (cp_teeW(prm.gusd, fi.ck, fi.cp) * fi.n / fi.R)[None, :]
        tb = tb - fb.c0parts['verify'] + (cp_teeW(prm.gusd, fb.ck, fb.cp) * fb.ns / fb.R)[None, :]
    return tb, tf


def fi_named(X, pers=PER):
    g = X.g; KS = g['KS']; out = {}; SC = scenarios()
    for p in pers:
        for kind in KINDS:
            for lab in LABS:
                st = kind + ':' + p; fb = X.env.fb(st, 1.0, lab)
                if not fb.ok: continue
                fi = X.env.fi(st, lab); cell = {}
                for key, sc in SC:
                    tb, tf = named_terms(X, fb, fi, sc)
                    kb, xb = pick(tb); kf, xf = pick(tf)
                    cell[key] = summarize(fb.a_, fb.R, xb, xf, kb, kf, KS)
                out['%s|%s|%s' % (kind, p, lab)] = cell
    return out


def payee_base(M, s, st, lab='lo'):
    """P10's closed-form terms of one payee or seller (computed once) and its per-k sale groups for FI-batch."""
    fb, fi, tf, ti = p10.costs(M, s, st, lab)
    cnt = s.get('cnt')
    if 'idx' in s: idx, c = np.asarray(s['idx']), np.asarray(s['c'], float)
    elif cnt is not None:
        cnt = np.asarray(cnt, float); idx = np.nonzero(cnt > 0)[0]; c = cnt[idx]
    else: idx = c = None
    groups = None if idx is None else [p10.groups(idx, c, k) for k in M.KS]
    return dict(fb=fb, fi=fi, tf=tf, ti=ti, groups=groups, st=st, lab=lab)


def p10_batch_tx(M, s, pb, cap):
    """Batch transactions per k in P10's structure: E(k) + extra transactions at the batch capacity (upper: k = 1)."""
    st = pb['st']; T = np.empty(len(M.KS))
    for i, k in enumerate(M.KS):
        if pb['groups'] is not None: x = p10.splits(pb['groups'][i], cap)
        else: x = p10.splits_bound(float(s['n']), st['E'][i], s['m1'], k, cap)
        T[i] = st['E'][i] + x
    if M.prm[pb['lab']].up: T[:] = T[0]
    return T


def payee_terms(M, s, pb, sc):
    """(FB total, FI total) of one scenario in P10's closed form from payee_base pb."""
    prm = M.prm[pb['lab']]; R = float(s['R']); n = float(s['n']); ns = float(s['ns']); ck = s.get('ck', 'RS3')
    cp = prm.cpu(ck); fb, fi = pb['fb'], pb['fi']
    tb, tf = pb['tf'], pb['ti']
    if sc['kind'] == 'g':
        c = cp_shift(prm.gusd, [ck], [cp], sc['g'])[0]
        tf = tf - fi['verify'] + c * n / R
        if sc['mode'] == 'both': tb = tb - fb['verify'] + c * ns / R
    elif sc['kind'] == 'batch' and ck == 'RS3':
        T = p10_batch_tx(M, s, pb, batch_cap(sc['GB'], sc['gb']))
        vb = (prm.gusd(sc['GB']) * T + (prm.gusd(sc['gb']) + prm.wusd(M.g['CPG']['RS3'][1])) * n) / R
        tf = tf - fi['verify'] + vb
    elif sc['kind'] == 'teeW':
        c = cp_teeW(prm.gusd, [ck], [cp])[0]
        tf = tf - fi['verify'] + c * n / R; tb = tb - fb['verify'] + c * ns / R
    return tb, tf


def fi_payees(X, pers=('busy', 'median'), recipients=None, lab='lo'):
    """(a) on the Base payees (0x, mean sale <= V), lower case: counts and revenue shares of the regions."""
    M = X.M; SC = scenarios(); out = {}
    rec_fn = recipients or p10.recipients
    for p in pers:
        days = X.g['PDAYS'][p] if p in X.g['PDAYS'] else 21
        acc = {key: {'A': [0, 0.0], 'B': [0, 0.0], 'C_fb': [0, 0.0], 'C_fi': [0, 0.0]} for key, _ in SC}
        N = 0; RT = 0.0
        for s in rec_fn(p):
            if 'evm_vle' not in p10.subset_of(s['a'], s['R'] / s['n']): continue
            st = p10.structure_sparse(M, s, days) if 'idx' in s else p10.structure(M, s, days)
            N += 1; RT += s['R']
            pb = payee_base(M, s, st, lab)
            for key, sc in SC:
                tb, tf = payee_terms(M, s, pb, sc)
                xb, xf = float(tb.min()), float(tf.min())
                r = region(xb, xf); acc[key][r][0] += 1; acc[key][r][1] += s['R']
        out[p] = dict(N=N, R=RT, sc={key: {r: dict(n=v[0], R=v[1], share=(v[1] / RT if RT else 0.0)) for r, v in a.items()}
                                     for key, a in acc.items()})
    return out


def gstar_all(X, pers=PER):
    out = {}
    for lab in LABS:
        for key, v in gstar_cells_p(X, lab, pers).items(): out['%s|%s' % (lab, key)] = v
    return out


def gstar_cells_p(X, lab, pers):
    g = X.g; W = g['W0']; out = {}
    for p in pers:
        for kind in KINDS:
            st = kind + ':' + p; fb = X.env.fb(st, 1.0, lab)
            if not fb.ok: continue
            fi = X.env.fi(st, lab); prm = fb.prm; gu1 = prm.gusd(1.0)
            _, xb = pick(fb.total(W)); _, xf = pick(fi.total(W))
            for j, a in enumerate(fb.a_):
                go = own_call_gas(g, fb.ck[j], prm.up)
                out['%s|%s' % (p, a)] = dict(ck=fb.ck[j], g_own=go, both=float(gstar(xb[j], xf[j], fb.R[j], fb.n[j], fb.ns[j], gu1, go, 'both')),
                                             fi=float(gstar(xb[j], xf[j], fb.R[j], fb.n[j], fb.ns[j], gu1, go, 'fi')))
    return out


# ================================================================== (b) computation
def w_named(X, pers=PER):
    """w grid on the named sellers (V 1): FairBind and FI totals, aggregates, per seller."""
    g = X.g; KS = g['KS']; out = {}
    for p in pers:
        for kind in KINDS:
            for lab in LABS:
                st = kind + ':' + p; fb = X.env.fb(st, 1.0, lab)
                if not fb.ok: continue
                fi = X.env.fi(st, lab); cell = {}
                for wn, w in W_GRID:
                    kb, xb = pick(fb.total(w)); kf, xf = pick(fi.total(w))
                    x = summarize(fb.a_, fb.R, xb, xf, kb, kf, KS); x['le10'] = bool(x['agg_fb'] <= TH); cell[wn] = x
                out['%s|%s|%s' % (kind, p, lab)] = cell
    return out


def stall_named(X, pers=PER):
    """One stall per window on the named sellers (V 1) at w = 0 and w0."""
    g = X.g; KS = g['KS']; out = {}
    for p in pers:
        for kind in KINDS:
            for lab in LABS:
                st = kind + ':' + p; fb = X.env.fb(st, 1.0, lab)
                if not fb.ok: continue
                fi = X.env.fi(st, lab)
                terms = [stall_seller(g, p, fb, j) for j in range(fb.N)]
                ab = np.array([t['fb_add'] for t in terms]); af = np.array([t['fi_add'] for t in terms])
                cell = dict(sellers={fb.a_[j]: {k: v for k, v in t.items()} for j, t in enumerate(terms)})
                for wn, w in STALL_W:
                    kb, xb = pick(fb.total(w) + ab[None, :]); kf, xf = pick(fi.total(w) + af[None, :])
                    x = summarize(fb.a_, fb.R, xb, xf, kb, kf, KS); x['le10'] = bool(x['agg_fb'] <= TH); cell[wn] = x
                out['%s|%s|%s' % (kind, p, lab)] = cell
    return out


THR_V = (0.1, 0.02)


_STY = {}


def stall_stylised(M, Re, v, lab, d=1.0, days=21, L=STALL_L, cache=True):
    """Stall shares (FB, FI) of a stylised seller (P10 calc-rules 1). Its active epochs and the FI share f depend on d,
    not on m; when the anchor deadlines of its active epochs alone cover every stall start, P = 1 for every m, so that
    case and f are cached per (v, case, d, days)."""
    s = p10.stylised(Re / v, v, d, days); prm = M.prm[lab]; nep = days * 144
    key = (v, lab, d, days, L)
    if not cache or key not in _STY:
        _, A, _, _ = rel_deadlines(nep, prm.DA, prm.SV, prm.TP)
        act = s['cnt'] > 0
        full = mean_fail(A[act], np.full(int(act.sum()), -np.inf), L, nep * EPB - L) == 1.0
        _STY[key] = (full, stall_fi(s['cnt'], 1.0, nep, L, prm.TP))
    full, f = _STY[key]
    P = 1.0 if (cache and full) else stall_fb(s['cnt'], 1.0, s['ns'] / s['n'], nep, L, prm.DA, prm.SV, prm.TP)['P']
    gasf = prm.gusd(M.g['G_FAIL']) if prm.up else 0.0
    loss = p6.loss_per_failure(s['R'], nep * EPB, prm.DF(1), 1.0, a=prm.a, gasf=gasf)['total']
    fi_gas = f * s['n'] * prm.gusd(M.g['G_FAIL']) / s['R'] if prm.up else 0.0
    return P * loss / s['R'], f + fi_gas


def thr_w(X, w, v, lab='lo', d=1.0, stall=False):
    M = X.M
    def ev(Re):
        M.W0 = w
        try:
            e = p10.share_at(M, Re, v, lab, d)
            if stall:
                a, b = stall_stylised(M, Re, v, lab, d); e = dict(e, fb=e['fb'] + a, fi=e['fi'] + b)
            return e
        finally: M.W0 = W0
    return thresholds_gen(ev, v, lab, d)


def thresholds_all(X, vs=THR_V):
    out = {}
    for v in vs:
        for wn, w in W_GRID: out['%g|%s' % (v, wn)] = thr_w(X, w, v)
        out['%g|stall_w0' % v] = thr_w(X, W0, v, stall=True)
    return out


# ================================================================== run
def p9_cells(X, pers=PER):
    """p9.cells (P9 calc-rules 3) over the windows pers (p9.cells reads the module variable p9.PER)."""
    per0 = p9.PER
    try:
        p9.PER = tuple(pers); return jsonable(p9.cells(X.env))
    finally: p9.PER = per0


def run_base(X, base, pers=PER, payee_pers=('busy', 'median'), recipients=None, thr_vs=THR_V):
    X.set_base(base); R = {}
    R['p9cells'] = p9_cells(X, pers)                                  # (c) every P9 cell at this base
    R['fi_named'] = fi_named(X, pers)                                 # (a)
    R['gstar'] = gstar_all(X, pers)
    R['fi_payees'] = fi_payees(X, payee_pers, recipients)
    R['w_named'] = w_named(X, pers)                                   # (b)
    R['stall_named'] = stall_named(X, pers)
    R['thresholds'] = thresholds_all(X, thr_vs)
    return R


def run_all(X, pers=PER, payee_pers=('busy', 'median'), recipients=None, bases=BASES, thr_vs=THR_V):
    out = {b: run_base(X, b, pers, payee_pers, recipients, thr_vs) for b in bases}
    X.set_base('V1u'); return out


def meta(X, CH):
    return dict(checks=CH, consts={b: dict(rel=CONSTS[b][0], anc={k: (v if not isinstance(v, dict) else {str(a): c for a, c in v.items()})
                                                                  for k, v in CONSTS[b][1].items()}) for b in BASES},
                usdc_rows=dict(unit=ANC_UNIT_U, complete=ANC_COMPLETE_U, chunk=ANC_CHUNK_U, pullsale=ANC_PULLSALE_U,
                               rel=dict(F1=REL1_F_U, M1=REL1_M_U, chk=RELU_CHK_U, pay=RELU_PAY_U, cur=REL_CUR_U, proven=REL1_PROVEN_U)),
                fi_points=FI_POINTS, fb_share=FB_SHARE, bind=BIND, g_grid=G_GRID, gb_grid=GB_GRID, gm_grid=GM_GRID,
                w_grid=W_GRID, stall_L=STALL_L, w0=W0,
                sha256={f: hashlib.sha256((HERE / f).read_bytes()).hexdigest() for f in ('p11.py', 'calc-rules.md') if (HERE / f).exists()},
                k11b_sha256=hashlib.sha256((J / 'K11' / 'k11b.py').read_bytes()).hexdigest())


def write_outputs(RES, OUT):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / 'p11.json', 'w') as fh: json.dump(RES, fh, indent=1, ensure_ascii=False, allow_nan=True)
    (OUT / 'p11_tables.md').write_text(tables(RES), encoding='utf-8')
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in ('p11.json', 'p11_tables.md'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out'); ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args(); T0 = time.time()
    X = P11()
    try:
        CH = checks(X)
        for k in ('k11b_reproduced', 'v1_p9_ok', 'v0_fi_fr_ok', 'p3_ok', 'gstar_ok', 'se_fi_ok', 'p10_check_ok', 'thr_ok', 'p6_ok', 'all_ok'):
            print('%s: %s' % (k, CH[k]), flush=True)
        if args.check_only: return
        assert args.out, '--out or --check-only'
        OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT
        if not CH['all_ok']:
            OUT.mkdir(parents=True, exist_ok=True)
            with open(OUT / 'p11.json', 'w') as fh: json.dump(dict(meta=meta(X, CH), verdict='withheld: reproduction failure'), fh, indent=1, ensure_ascii=False)
            print('reproduction failed: no values reported'); sys.exit(2)
        RES = dict(meta=meta(X, CH), bases=run_all(X))
        write_outputs(RES, OUT)
        print('wrote', OUT, '%.0fs' % (time.time() - T0))
    finally:
        X.restore()


# ================================================================== tables (rounding: calc-rules.md 0.5)
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet', 'SYNW': 'synthetic'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator'}
KN = {'T01t': 'six seller sum', 'BR': 'BlockRun'}


def pc(x): return '-' if x is None else ('%s' % x if isinstance(x, str) else '%.2f' % (100 * x))
def star(x): return pc(x) + ('*' if x is not None and not isinstance(x, str) and x > TH else '')
def gi(x): return format(int(round(x)), ',') if x is not None and math.isfinite(x) else '-'


def _pers(B):
    return [p for p in list(WN) if any(k.split('|')[1] == p for k in B['fi_named'])]


def tables(R):
    M = R['meta']; CH = M['checks']; L = []
    L.append('**all values post hoc calculations registered verdict none.** `p11.py` output. mode N, σ 1, r 10%, a 0, per seller optimal k, costs revenue relative to %, *  10% over. '
             'reference variant V1u(real USDC constant), comparison V1(mock).\n')
    L.append('reproduction check: k11b %s, V1 vs p9.json %s(max difference %.1e), V0 FI and FR %s, P3 FI_min / FI_W / FI %s, P3 g* %s(max difference %.1e gas), StableEnrich g*_FI %s, '
             'P10 check %s, P10 threshold %s, P6 %s.\n' % (CH['k11b_reproduced'], CH['v1_p9_ok'], CH['v1_p9_maxdiff'], CH['v0_fi_fr_ok'], CH['p3_ok'],
                                                     CH['gstar_ok'], CH['gstar_maxdiff'], CH['se_fi'], CH['p10_check_ok'], CH['thr_ok'], CH['p6_ok']))
    BS = [b for b in BASES if b in R['bases']]
    pers = _pers(R['bases'][BS[0]])
    # ---------------- (c)
    L.append('## 1. (c) V1u and V1: header numbers and FI comparison\n')
    L.append('| set | V | case | ' + ' | '.join('%s (%s)' % (b, ' / '.join(WN[p] for p in pers)) for b in BS) + ' | V1u − V1 (%p) |')
    L.append('|---|---|---|' + '---|' * len(BS) + '---|')
    for kind in KINDS:
        for V in (1.0, 0.2):
            for lab in LABS:
                cells = {b: [R['bases'][b]['p9cells'].get('%s|%g|%s|%s' % (kind, V, p, lab)) for p in pers] for b in BS}
                if all(x is None for x in cells[BS[0]]): continue
                row = [' / '.join('-' if x is None else star(x['agg']) for x in cells[b]) for b in BS]
                dif = ' / '.join('-' if (x is None or y is None) else '%+.2f' % (100 * (x['agg'] - y['agg']))
                                 for x, y in zip(cells[BS[0]], cells[BS[-1]]))
                L.append('| %s | %g | %s | %s | %s |' % (KN[kind], V, LN[lab], ' | '.join(row), dif))
    L.append('\nFI comparison(V 1): FB sum / FI sum, more cheaper side, FI cheaper seller count, its revenue share, per seller cheaper side mixed.\n')
    L.append('| reference | set | window | case | FB | FI | more cheaper side | FI cheaper count | share | mixed |'); L.append('|' + '---|' * 10)
    for b in BS:
        for kind in KINDS:
            for p in pers:
                for lab in LABS:
                    x = R['bases'][b]['p9cells'].get('%s|1|%s|%s' % (kind, p, lab))
                    if x is None or 'fi' not in x: continue
                    L.append('| %s | %s | %s | %s | %s | %s | %s | %d/%d | %s | %s |' % (b, KN[kind], WN[p], LN[lab], pc(x['agg']), pc(x['fi']),
                             'FairBind' if x['fb_cheaper_agg'] else 'FI', x['n_fi_cheaper'], x['N'], pc(x['share_fi_cheaper']), pc(x['agg_mix'])))
    # ---------------- (a)
    L.append('\n## 2. (a) measured gas full inspection\n')
    L.append('FI point(g, tier 1a): ' + ', '.join('%s %s' % (k, format(v, ',')) for k, v in M['fi_points'].items()) + '. tier 0 same share without TEE as is.\n')
    for b in BS:
        B = R['bases'][b]
        L.append('\n### %s: FI point, six seller sum (lower, V 1)\n' % b)
        L.append('| point | window | FB sum | FI sum | mixed | (A) FB cheaper and ≤10%: seller, revenue share | (B) FI cheaper and ≤10%: seller, revenue share |'); L.append('|' + '---|' * 7)
        for key in ['pt|' + k for k in FI_POINTS] + ['teeW']:
            for p in pers:
                x = B['fi_named'].get('T01t|%s|lo' % p, {}).get(key)
                if x is None: continue
                L.append('| %s | %s | %s | %s | %s | %s; %s | %s; %s |' % (key, WN[p], pc(x['agg_fb']), pc(x['agg_fi']), pc(x['agg_mix']),
                         ', '.join(x['names_A']) or 'none', pc(x['share_A']), ', '.join(x['names_B']) or 'none', pc(x['share_B'])))
        L.append('\n### %s: g grid (lower, V 1; form fi: FairBind measured call)\n' % b)
        L.append('| form | g | ' + ' | '.join('six (A) share / (B) share %s' % WN[p] for p in pers) + ' | BlockRun region | payee (A) count, share / (B) count, share |')
        L.append('|---|---|' + '---|' * len(pers) + '---|---|')
        for m in MODES:
            for gg in M['g_grid']:
                key = 'g|%s|%d' % (m, gg); cs = []
                for p in pers:
                    x = B['fi_named'].get('T01t|%s|lo' % p, {}).get(key)
                    cs.append('-' if x is None else '%s / %s' % (pc(x['share_A']), pc(x['share_B'])))
                br = []
                for p in pers:
                    x = B['fi_named'].get('BR|%s|lo' % p, {}).get(key)
                    if x is not None: br.append(list(x['per'].values())[0][4])
                py = []
                for p, X_ in B['fi_payees'].items():
                    s = X_['sc'][key]; py.append('%s %d, %s / %d, %s' % (WN.get(p, p), s['A']['n'], pc(s['A']['share']), s['B']['n'], pc(s['B']['share'])))
                L.append('| %s | %s | %s | %s | %s |' % (m, format(gg, ','), ' | '.join(cs), ', '.join(br) or '-', '; '.join(py) or '-'))
        L.append('\n### %s: per seller split gas (g*_FI: FairBind measured call, g*: same call; own call gas than split if large FI cheaper)\n' % b)
        L.append('| case | window | seller | tier | own call | g*_FI | g* |'); L.append('|' + '---|' * 7)
        for key, v in B['gstar'].items():
            lab, p, a = key.split('|')
            L.append('| %s | %s | %s | %s | %s | %s | %s |' % (LN[lab], WN.get(p, p), a, v['ck'], gi(v['g_own']), gi(v['fi']), gi(v['both'])))
        L.append('\n### %s: FI-batch (lower, V 1; tier 1a sellers only bundle, six FI sum / (A) share / (B) share, payee (A) share / (B) share)\n' % b)
        L.append('| G_B | g_b | ' + ' | '.join(WN[p] for p in pers) + ' | payee |'); L.append('|---|---|' + '---|' * len(pers) + '---|')
        for GB in M['gb_grid']:
            for gb in M['gm_grid']:
                key = 'batch|%d|%d' % (GB, gb); cs = []
                for p in pers:
                    x = B['fi_named'].get('T01t|%s|lo' % p, {}).get(key)
                    cs.append('-' if x is None else '%s / %s / %s' % (pc(x['agg_fi']), pc(x['share_A']), pc(x['share_B'])))
                py = '; '.join('%s %s / %s' % (WN.get(p, p), pc(X_['sc'][key]['A']['share']), pc(X_['sc'][key]['B']['share'])) for p, X_ in B['fi_payees'].items())
                L.append('| %s | %s | %s | %s |' % (format(GB, ','), format(gb, ','), ' | '.join(cs), py or '-'))
    # ---------------- (b)
    L.append('\n## 3. (b) w sensitivity and matter outage\n')
    for b in BS:
        B = R['bases'][b]
        L.append('\n### %s: w grid (V 1; six seller sum lower / upper / facilitator, per window; FI sum lower; BlockRun lower)\n' % b)
        L.append('| w | ' + ' | '.join('six %s' % WN[p] for p in pers) + ' | FI six lower | BlockRun lower |'); L.append('|---|' + '---|' * (len(pers) + 2))
        for wn, w in M['w_grid']:
            cs = []
            for p in pers:
                cs.append(' / '.join(star(B['w_named']['T01t|%s|%s' % (p, lab)][wn]['agg_fb']) for lab in LABS if 'T01t|%s|%s' % (p, lab) in B['w_named']))
            fi = ' / '.join(pc(B['w_named']['T01t|%s|lo' % p][wn]['agg_fi']) for p in pers if 'T01t|%s|lo' % p in B['w_named'])
            br = ' / '.join(star(B['w_named']['BR|%s|lo' % p][wn]['agg_fb']) for p in pers if 'BR|%s|lo' % p in B['w_named'])
            L.append('| %s (%.3g) | %s | %s | %s |' % (wn, w, ' | '.join(cs), fi, br or '-'))
        L.append('\n### %s: per window stall one (L = %s block; six sum lower / upper / facilitator, FI lower, BlockRun lower)\n' % (b, format(M['stall_L'], ',')))
        L.append('| w | window | six FB | six FI lower | BlockRun FB lower | BlockRun FI lower |'); L.append('|' + '---|' * 6)
        for wn, _ in STALL_W:
            for p in pers:
                c = B['stall_named']
                six = ' / '.join(star(c['T01t|%s|%s' % (p, lab)][wn]['agg_fb']) for lab in LABS if 'T01t|%s|%s' % (p, lab) in c)
                fi = pc(c['T01t|%s|lo' % p][wn]['agg_fi']) if 'T01t|%s|lo' % p in c else '-'
                br = c.get('BR|%s|lo' % p)
                L.append('| %s | %s | %s | %s | %s | %s |' % (wn, WN[p], six, fi, star(br[wn]['agg_fb']) if br else '-', pc(br[wn]['agg_fi']) if br else '-'))
        L.append('\nper seller stall term(lower): failure probability P̄(bound seller below~upper), loss USD, adding share, FI refund share.\n')
        L.append('| window | seller | source | P̄ | loss | FB added | FI added |'); L.append('|' + '---|' * 7)
        for p in pers:
            for kind in KINDS:
                c = B['stall_named'].get('%s|%s|lo' % (kind, p))
                if c is None: continue
                for a, t in c['sellers'].items():
                    pp = ('%.4f' % t['P']) if t['src'] != 'bound' else '%.4f~%.4f' % (t['P_lo'], t['P_up'])
                    L.append('| %s | %s | %s | %s | %.2f | %s | %s |' % (WN[p], a, t['src'], pp, t['loss'], pc(t['fb_add']), pc(t['fi_add'])))
        L.append('\n### %s: P10 threshold (lower, d 1; R_e USDC, in parentheses m, k)\n' % b)
        L.append('| v̄ | w | 10% below end | 10% upper end | 5% end | FI crossing | min cost share |'); L.append('|' + '---|' * 7)
        for key, t in B['thresholds'].items():
            v, wn = key.split('|')
            def e(th, dr):
                xs = [x for x in t['th%g' % th] if x['dir'] == dr]
                if not xs: return 'from the start below' if (dr == 'down' and t['below_at_lo_%g' % th]) else 'none'
                return '; '.join('%.4g (%.4g, %d)' % (x['Re'], x['m'], x['k']) for x in xs)
            five = '; '.join('%.4g %s' % (x['Re'], 'below' if x['dir'] == 'down' else 'upper') for x in t['th0.05']) or 'none'
            cr = '; '.join('%.4g → %s' % (x['Re'], 'FB' if x['dir'].startswith('FairBind') else 'FI') for x in t['cross']) or \
                ('none(increase FairBind)' if t['fb_cheaper_at_lo'] else 'none(increase FI)')
            L.append('| %s | %s | %s | %s | %s | %s | %s |' % (v, wn, e(0.10, 'down'), e(0.10, 'up'), five, cr, pc(t['min_fb'])))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
