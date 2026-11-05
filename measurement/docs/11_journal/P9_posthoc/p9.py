#!/usr/bin/env python3
"""P9 (post hoc, calc-rules.md, amended in 7 (sec.)): the cost model recomputed with the gas measured on the reference
implementation.

K11/k11b.py is read and executed unchanged in its own namespace (only its final output write is redirected and its
prints are swallowed), and the reproduction of K11/k11b_output.md is checked byte for byte. The variants change two
namespace constants (CL_REQ, CL_BILL), the sample-value path of the lower and facilitator cases, and switch the
'release' and 'anchor' terms of Grid._c0 to the contract's measured structure (calc-rules.md 7.2, 7.3):

    V0 : the model (K11b, manuscript Table 4)
    V1 : all measured = VRF + release + anchor
    V2 : VRF only   (Chainlink VRF v2.5 in every case, request 151,629 gas, billed fulfillment gas 170,701)
    V3 : release only (the contract's two branches: one call for a seller epoch of at most 256 sales, else units)
    V4 : anchor only  (units of at most 256 leaves, completing unit with the first pull)
    V1t1 (sensitivity, aggregates only): V1 with the billed gas of one hash-to-curve try, 165,162

Full inspection FI is P3's GridFI (P3_posthoc/p3.py class GridFI, as re-implemented in P4_posthoc/p4.py), without VRF or
anchor, so only the release change reaches it. FR is K14's fixed-rate variant through K14/k14.py install_fr
(k14.main() is not run); it is FairBind with another n_s, so every change reaches it.

    python3 -I p9.py --check-only      # reproduction checks only (prints booleans)
    python3 -I p9.py --out results        # the whole calculation (run only when told to)

The functions above main() are unit-tested in test_p9.py, on synthetic inputs or as reproduction checks.
"""
import argparse, contextlib, copy, hashlib, io, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
K11 = J / 'K11'
K14D = J / 'K14'
P3J = J / 'P3_posthoc' / 'results' / 'p3.json'
P4J = J / 'P4_posthoc' / 'results' / 'p4.json'
K14J = K14D / 'results' / 'k14.json'
RU = J / 'release-units'
REL_FIT = RU / 'run-logs_anchor' / 'release-gas-fit.txt'      # release re-measured at 7c571a8 (README 27 (line))
ANC_FIT = RU / 'run-logs_anchor' / 'anchor-gas-fit.txt'       # anchor, completion and pulls at 7c571a8

TH = 0.10
PER = ('busy', 'median', 'quiet')
LABS = ('lo', 'up', 'fac')
VS = (1.0, 0.2)
KINDS = ('T01t', 'BR')
FR_VARS = ('main', 'lo')

# ------------------------------------------------------------------ VRF constants (calc-rules.md 1, unchanged)
# model values in the k11b namespace after set_gas('new'), with the k11b.py line that sets them
MODEL = {'CL_REQ': 119_160, 'CL_BILL': 157_644}
MODEL_LINE = {'CL_REQ': '702 (new_values; 215 is the K11 value 96,000)', 'CL_BILL': '206-214'}
CL_REQ_MEAS = 151_629      # VRF/run-logs/fork_isolate.log 7, 116 (line): requestSample tx through the Base coordinator
FULFILL_TX = 156_468       # same log 128, 249, 287 (line): fulfillRandomWords tx, callback included (paid by the node)
CB_REF = 36_998            # same log 258 (line): the reference contract's callback frame inside that fulfillment
CB_MIN = 6_812             # G10_gas/G10d_gas.md 150 (line): the minimal consumer's callback frame (slot overwritten)
CL_BILL_FIT = (129_437, 5_539)   # k11b.py 206-207: G10d native billed gas = 129,437 + 5,539 t (t hash-to-curve tries)
TRIES_MAIN = 2             # expected tries (G10d 150 (line)), as k11b's CL_BILL_EXP (208 (line))
TRIES_SENS = 1             # tries of the one measured fulfillment (fork_isolate.log 130 (line))

# the stage-1 release constant, kept only for the check that the namespace machinery still gives P4 base B
REL_M_P4B = 16_800         # SDK/k-multiple_implementation.md 5.3 (164 (line)); P3 (b), P4 base B

# ------------------------------------------------------------------ release, measured at 7c571a8 (calc-rules.md 7.2)
# release-units/run-logs_anchor/release-gas-fit.txt (forge --isolate, tx gas incl. 21,000, mock token), fits rounded to gas
N_REL = 256                # contract N_REL: a seller epoch of at most 256 settlements is released by one call
REL1_F, REL1_M = 75_331, 16_920        # 'inline' (20 (line)): one cursor call doing check, pass and payment
RELU_CHK = (73_697, 9_888)             # 'check' (5 (line)): release unit, unsampled sales
RELU_PAY = (57_491, 12_965)            # 'payunit' (14 (line)): payment unit
REL_CUR = 69_391                       # 'pass' (26 (line)): the cursor's pass once units are done
REL1_PROVEN = (76_299, 16_044)         # 'inline_proven' (23 (line)): every sale a closed case
REL_K_MEAS = REL1_PROVEN[1] - REL1_M   # -876 per closed case (one-call branch; the unit branch is -2,857, not used)
REL_MEAS = dict(N=float(N_REL), F1=REL1_F, M1=REL1_M, FU=RELU_CHK[0] + RELU_PAY[0], MU=RELU_CHK[1] + RELU_PAY[1],
                FC=REL_CUR, K=REL_K_MEAS)

# ------------------------------------------------------------------ anchor, measured at 7c571a8 (calc-rules.md 7.3)
# release-units/run-logs_anchor/anchor-gas-fit.txt, fits rounded to gas; kinds: plain (unsigned, answered), marked (u_n = 1),
# accepted (sigma_B, a = 1)
N_UNIT = 256               # contract N_UNIT: leaves per anchor unit
ANC_UNIT = {'plain': (279_842, 16_784), 'marked': (286_824, 19_634), 'accepted': (260_025, 28_126)}       # 31-37 (line)
ANC_COMPLETE = {'plain': (288_468, 5_135), 'marked': (296_283, 15_711), 'accepted': (308_017, 11_557)}   # 15-22 (line)
ANC_CHUNK = {'plain': (41_128, 5_135), 'marked': (50_624, 15_711), 'accepted': (58_975, 11_557)}         # 6-13 (line)
ANC_PULLSALE = {'marked': 64_346, 'accepted': 69_344}                                                     # 24-28 (line)
# model leaf kinds (sigma = share of buyer-signed leaves; a = 0 in every P9 case) to contract kinds:
#   unsigned -> plain; buyer-signed -> accepted in the anchor unit (the only measured kind that checks sigma_B);
#   the completion pull moves nothing for a leaf that is not accepted or marked, so it is priced as plain.
ANC_MEAS = dict(N=float(N_UNIT),
                FU={0: ANC_UNIT['plain'][0], 1: ANC_UNIT['accepted'][0]},
                MU={0: ANC_UNIT['plain'][1], 1: ANC_UNIT['accepted'][1]},
                FC={0: ANC_COMPLETE['plain'][0], 1: ANC_COMPLETE['plain'][0] + ANC_UNIT['accepted'][1] - ANC_UNIT['plain'][1]},
                MC={0: ANC_COMPLETE['plain'][1], 1: ANC_COMPLETE['plain'][1]},
                FL=None)
# EIP-7623 floor of the measured calls, bounded from the ABI size of their calldata at 40 gas per byte (every byte
# nonzero): a leaf is 416 bytes (array offset, 8-word receipt, u_n, a, sigB offset and length) or 512 with a 65-byte
# sigB; a unit's other calldata is 580 + 32 s bytes (s snapshot addresses), plus 21,000.
FLOOR_PER_BYTE = 40
LEAF_BYTES = {'plain': 416, 'marked': 416, 'accepted': 512}
UNIT_HEAD_BYTES = 580


def unit_floor_bound(s_snapshot=0): return 21_000 + FLOOR_PER_BYTE * (UNIT_HEAD_BYTES + 32 * s_snapshot)


def cl_bill_meas(t, fit=CL_BILL_FIT, cb_ref=CB_REF, cb_min=CB_MIN):
    """Billed gas of a fulfillment for the reference contract (calc-rules.md 1.2): the G10d billed-gas line at t tries
    with the minimal consumer's callback replaced by the reference contract's measured callback. The new-slot
    increment CL_NEWSLOT is not added: the measured callback already writes the epoch's value to a fresh slot."""
    return fit[0] + fit[1] * t + (cb_ref - cb_min)


MEAS = {'CL_REQ': CL_REQ_MEAS, 'CL_BILL': cl_bill_meas(TRIES_MAIN)}
VARIANTS = {'V0': dict(rel=False, vrf=False, anc=False), 'V1': dict(rel=True, vrf=True, anc=True),
            'V2': dict(rel=False, vrf=True, anc=False), 'V3': dict(rel=True, vrf=False, anc=False),
            'V4': dict(rel=False, vrf=False, anc=True), 'V1t1': dict(rel=True, vrf=True, anc=True, tries=TRIES_SENS)}
MAIN_VARS = ('V0', 'V1', 'V2', 'V3', 'V4')
SINGLE = {'V2': 'vrf', 'V3': 'rel', 'V4': 'anc'}
SUBST = ('CL_REQ', 'CL_BILL')          # the only namespace constants a variant writes
TERMS = {'vrf': ('sampvrf',), 'rel': ('release',), 'anc': ('anchor', 'l1', 'detincl')}   # terms each component may move


def variant_values(model, rel, vrf, anc, tries=TRIES_MAIN, meas=None, switch_path=True, struct='meas'):
    """Namespace values, the lower-case sample-value path and the release and anchor structures of a variant.
    meas overrides the measured VRF values; switch_path False keeps the ECVRF path of the lower estimate; struct
    'model' runs the measured release and anchor code with the model's constants (the set-back check)."""
    m = dict(MEAS, CL_BILL=cl_bill_meas(tries)) if meas is None else dict(meas)
    return dict(CL_REQ=m['CL_REQ'] if vrf else model['CL_REQ'],
                CL_BILL=m['CL_BILL'] if vrf else model['CL_BILL'],
                lower_rnd='cl' if (vrf and switch_path) else 'ecvrf',
                rel=struct if rel else None, anc=struct if anc else None)


def setback_values(model):
    """Every code path of V1 with the model's constants and the ECVRF lower path: must give V0."""
    return variant_values(model, True, True, True, meas=dict(model), switch_path=False, struct='model')


# ================================================================== measured release and anchor gas
def _mix(d, sg): return (1 - sg) * d[0] + sg * d[1]


def rel_params(g, gr, struct):
    """Release parameters per seller. 'meas': the contract (6.2). 'model': the model written in the same structure
    (one call up to the release capacity, extra transactions of REL_F beyond it), which gives k11b's term."""
    if struct == 'meas': return dict(REL_MEAS, N=np.full(gr.N, REL_MEAS['N']))
    F = g['REL_F'][gr.prm.rd]
    return dict(N=np.asarray(gr.capR, float), F1=F, M1=g['REL_M'], FU=F, MU=g['REL_M'], FC=0, K=g['REL_K'])


def rel_gas(g, gr, par, closed):
    """Release gas per (k, seller) (calc-rules.md 7.2). Per seller epoch of m sales: F1 + M1 m if m <= N, else
    FU ceil(m / N) + FC + MU m; plus K per closed case. Summed as
        F1 E + M1 n + K c + FU X + (FU + FC - F1) J + (MU - M1) S,
    X = sum max(ceil(m / N) - 1, 0), J = epochs above N, S = their sales; exact from per-epoch counts, else the
    bound of k11b's splits_bound for X and J <= min(X, E, floor(n / (N + 1))), S <= min(n, J min(k m1, n)).
    In the upper case with curpe the k = 1 grouping is used for every k (k11b's K10h (d))."""
    KS = g['KS']; nk = len(KS); out = np.empty((nk, gr.N))
    rows = [0] if (gr.prm.up and gr.prm.curpe) else list(range(nk))
    for i in rows:
        k = KS[i]
        for j, s in enumerate(gr.S):
            N = float(par['N'][j]); n = float(gr.n[j]); E = float(gr.E[i, j])
            if s['cnt'] is not None:
                X = g['splits_from_counts'](s['cnt'], k, N)
                m = np.bincount(np.arange(len(s['cnt'])) // k, weights=s['cnt']); m = m[m > 0]
                big = m > N; Jn = float(big.sum()); S = min(n, float(m[big].sum()))
            else:
                X = g['splits_bound'](s['n'], E, s['m1'], k, N)
                mk = min(k * s['m1'], n)
                Jn = 0.0 if mk <= N else float(min(X, E, math.floor(n / (N + 1))))
                S = min(n, Jn * mk)
            out[i, j] = (par['F1'] * E + par['M1'] * n + par['K'] * float(closed[j]) + par['FU'] * X
                         + (par['FU'] + par['FC'] - par['F1']) * Jn + (par['MU'] - par['M1']) * S)
    if rows == [0]: out[:] = out[0][None, :]
    return out


def anc_params(g, struct):
    if struct == 'meas': return ANC_MEAS
    F, M = g['G10B_F'], g['G10B_M']
    return dict(N=None, FU=dict(F), MU=dict(M), FC={s: F[s] + M[s] for s in (0, 1)}, MC={0: 0.0, 1: 0.0},
                FL=(dict(g['FL_F']), dict(g['FL_M'])))


def anc_gas(g, gr, par):
    """Anchor gas per (k, seller) (calc-rules.md 7.3), per active profile epoch (k11b's pe): u = ceil(m / N) units,
    u - 1 non-completing units, the completing unit carrying the completion and the first pull of min(m, 256)
    records:  Ua FU + (n - E0) MU + E0 FC + MC P,  Ua = A - E0 the extra units (k11b's Ua at the unit cap),
    P = sum min(m, 256). FU, MU, FC, MC are mixed by sigma as k11b's anc_lin. With the model's constants
    (FC = F + M, MC = 0, floor) this is k11b's A max(F + M x, FL_F + FL_M x)."""
    prm = gr.prm; sg = prm.sig
    assert prm.pe and prm.mode == 'k10d' and prm.a == 0.0 and gr.kind in ('T01t', 'BR'), 'measured anchor: P9 cases only'
    E0 = gr.E[0]; Ua0 = gr.Ua[0]; n = gr.n
    P = np.empty(gr.N)
    for j, s in enumerate(gr.S):
        if s['cnt'] is not None:
            c = np.asarray(s['cnt'], float); P[j] = min(n[j], float(np.minimum(c[c > 0], N_UNIT).sum()))
        else:
            P[j] = n[j] if s['m1'] <= N_UNIT else min(n[j], N_UNIT * E0[j])
    ex = Ua0 * _mix(par['FU'], sg) + (n - E0) * _mix(par['MU'], sg) + E0 * _mix(par['FC'], sg) + _mix(par['MC'], sg) * P
    fb = np.zeros(gr.N, bool)
    if par['FL'] is not None:
        fl = (E0 + Ua0) * _mix(par['FL'][0], sg) + n * _mix(par['FL'][1], sg)
        fb = fl > ex; ex = np.maximum(ex, fl)
    return np.broadcast_to(ex[None, :], gr.E.shape).copy(), np.broadcast_to(fb[None, :], gr.E.shape).copy()


# ================================================================== the environment over a k11b namespace
class Env:
    """A k11b namespace g with P3's GridFI and K14's GridFR installed, and the variant switch. Grid._c0 and
    cap_anchor are wrapped once: with the release and anchor switches off they return k11b's own results."""

    def __init__(self, g, with_fr=True):
        self.g = g
        self.model = {n: g[n] for n in SUBST}
        assert self.model == MODEL, self.model
        assert tuple(g['CL_BILL_FIT']) == CL_BILL_FIT, g['CL_BILL_FIT']
        assert g['KS'][0] == 1 and g['CAP_GAS'] == {1: 924, 0: 1_564}
        self.lower_rnd = 'ecvrf'; self.var = 'V0'; self.rel = None; self.anc = None
        Grid0 = g['Grid']; self.Grid0 = Grid0
        env = self

        # ---------------- the release and anchor switches (calc-rules.md 7.5)
        orig_c0 = Grid0._c0; orig_cap = g['cap_anchor']
        self._orig = (orig_c0, orig_cap)
        def _c0(gr):
            parts = orig_c0(gr)
            if env.rel is not None:
                parts['release'] = gr.prm.gusd(rel_gas(g, gr, rel_params(g, gr, env.rel), gr.ns)) / gr.R
            if env.anc is not None:
                ag, fb = anc_gas(g, gr, anc_params(g, env.anc)); gr.flb = fb
                parts['anchor'] = gr.prm.gusd(ag) / gr.R
            return parts
        def cap_anchor(prm):
            if env.anc == 'meas' and prm.cap == 'gas': return float(N_UNIT)
            return orig_cap(prm)
        Grid0._c0 = _c0; g['cap_anchor'] = cap_anchor

        # ---------------- P3_posthoc/p3.py class GridFI (P3 calc-rules.md 1.1), as in P4_posthoc/p4.py without the multiplier
        class GridFI(Grid0):
            FIMIN = False
            def __init__(self, st, V, prm):
                super().__init__(st, V, prm)
                if not self.ok: return
                cap = float(math.floor((g['TX_CAP'] - g['REL_F'][prm.rd]) / (g['REL_M'] + g['REL_K'])))   # q = 1
                self.capR = np.full(self.N, cap)
                for i, k in enumerate(g['KS']):
                    for j, s in enumerate(self.S):
                        if s['cnt'] is not None: self.Ur[i, j] = g['splits_from_counts'](s['cnt'], k, cap)
                        else: self.Ur[i, j] = g['splits_bound'](s['n'], self.E[i, j], s['m1'], k, cap)
                self.c0parts = self._c0(); self.c0 = sum(self.c0parts.values())

            def _c0(self):
                prm, R, n, E = self.prm, self.R, self.n, self.E
                cp = self.cp.copy()
                self.cp_fi = cp
                parts = {'verify': np.broadcast_to(cp * n / R, E.shape).copy()}
                if prm.up and prm.curpe: Ru = np.broadcast_to((E[0] + self.Ur[0])[None, :], E.shape).copy()
                else: Ru = E + self.Ur
                self.Ru = Ru; self.Ep = np.broadcast_to(E[0][None, :], E.shape).copy()
                rd = prm.rd
                if env.rel is None:
                    parts['release'] = prm.gusd(Ru * g['REL_F'][rd] + g['REL_M'] * n[None, :] + g['REL_K'] * n[None, :]) / R
                else:                                                # every sale is a closed case
                    parts['release'] = prm.gusd(rel_gas(g, self, rel_params(g, self, env.rel), n)) / R
                parts['l1'] = prm.wusd(Ru * g['RW_F'] + g['RW_M'] * n[None, :]) / R
                if prm.fac:
                    Ef = np.minimum(self.Ep if prm.fpe else E, n[None, :])
                    parts['facil'] = prm.gusd(Ef * g['SETTLE'][rd]['first'] + (n[None, :] - Ef) * g['SETTLE'][rd]['later']) / R
                if prm.up:
                    parts['detincl'] = np.broadcast_to(prm.gusd(g['G_DET'] * n) / R, E.shape).copy()
                return parts

            def loss(self, w):
                frz = np.zeros_like(self.E)
                ded = np.full_like(self.E, w)                       # refund of the failed sale only
                if self.prm.up: ded = ded + w * self.n[None, :] * self.prm.gusd(g['G_FAIL']) / self.R[None, :]
                return frz, ded

            def cap(self, r):
                H = np.array([300 * k + self.prm.TP for k in g['KS']], float)[:, None]
                return np.broadcast_to(r * H / self.Wb * (self.days / 365.0), self.E.shape).copy()

        self.GridFI = GridFI
        self.GridFR = None
        if with_fr:
            if str(K14D) not in sys.path: sys.path.insert(0, str(K14D))
            import k14                                   # functions only; k14.main() is not called
            self.k14 = k14
            self.GridFR, self.FRINFO = k14.install_fr(g, {'T01t': k14.PART0, 'BR': {}})
        g['_G'].clear()

    # ---------------- variants
    def set_values(self, d):
        g = self.g
        for n in SUBST: g[n] = d[n]
        assert d['lower_rnd'] in ('ecvrf', 'cl') and d['rel'] in (None, 'meas', 'model') and d['anc'] in (None, 'meas', 'model')
        self.lower_rnd = d['lower_rnd']; self.rel = d['rel']; self.anc = d['anc']
        g['_G'].clear()

    def set_variant(self, name, **kw):
        self.set_values(variant_values(self.model, **dict(VARIANTS[name], **kw))); self.var = name

    def reset(self): self.set_variant('V0')

    # ---------------- grids
    def prm(self, lab):
        g = self.g; kw = {} if self.lower_rnd == 'ecvrf' else dict(rnd='cl')
        if lab == 'lo': return g['LOm']('N', **kw)
        if lab == 'up': return g['UPm']('N')                 # the upper case is already on the Chainlink path
        return g['LOm']('N', True, **kw)

    def fb(self, st, V, lab):
        gr = self.g['G'](st, V, self.prm(lab))
        assert not gr.ok or np.all(gr.capR >= 1), 'release capacity below one sale'
        return gr

    def fi(self, st, lab):
        gr = self.GridFI(st, 1.0, self.prm(lab))
        assert not gr.ok or np.all(gr.capR >= 1), 'release capacity below one sale'
        return gr

    def fr(self, st, lab, var): return self.GridFR(st, 1.0, self.prm(lab), var)


# ================================================================== loading and reproduction checks
def load_k11b(tag='k11b_p9'):
    src = (K11 / 'k11b.py').read_text(encoding='utf-8')
    a1 = "HERE = os.path.dirname(os.path.abspath(__file__))"
    a2 = "open(HERE + '/k11b_output.md', 'w').write(txt)"
    assert src.count(a1) == 1 and src.count(a2) == 1
    src = src.replace(a1, "HERE = %r" % str(K11)).replace(a2, "_P9_TXT = txt")
    g = {'__name__': tag}
    with contextlib.redirect_stdout(io.StringIO()):       # k11b prints seller names and a 'wrote' line; nothing is written
        exec(compile(src, str(K11 / 'k11b.py'), 'exec'), g)
    repro = g['_P9_TXT'] == (K11 / 'k11b_output.md').read_text(encoding='utf-8')
    g['set_gas']('new')                                   # the state k11b.py ends in (as P4, P5, P8); clears _G
    return g, repro


def sig_equal(got, want):
    """got rounded to the significant digits of the manuscript string want equals want (P4)."""
    digits = want.replace('.', '').lstrip('0')
    return float('%.*g' % (len(digits), got)) == float(want)


def rng2(xs): return '%.2f–%.2f' % (100 * min(xs), 100 * max(xs))


# manuscript Table 4 (P3 calc-rules.md 0.3, P4 p4.py EXP and EXPW)
EXP = {('agg', 1.0, 'lo'): '4.84–5.97', ('agg', 1.0, 'up'): '6.84–8.51', ('agg', 1.0, 'fac'): '9.79–12.88',
       ('agg', 0.2, 'lo'): '8.05–8.59', ('agg', 0.2, 'up'): '10.20–11.34', ('agg', 0.2, 'fac'): '12.99–15.43',
       ('se', 1.0, 'lo'): '3.67–4.51', ('se', 1.0, 'up'): '4.89–6.04', ('se', 1.0, 'fac'): '7.62–10.25',
       ('med', 1.0, 'lo'): '24.18–73.40', ('med', 1.0, 'up'): '37.80–111.34', ('med', 1.0, 'fac'): '49.44–91.39',
       ('BRagg', 1.0, 'lo'): '33.60–42.05', ('BRagg', 1.0, 'up'): '33.64–42.10', ('BRagg', 1.0, 'fac'): '37.44–55.60'}
EXPW = {('T01t', 1.0, 'lo'): ('0.0130', '0.0143'), ('T01t', 1.0, 'up'): ('0.00585', '0.00895'),
        ('T01t', 0.2, 'lo'): ('0.00287', '0.00312'), ('T01t', 0.2, 'up'): ('0.00066', '0.00162'),
        ('BR', 1.0, 'lo'): ('0.000172', '0.000393'), ('BR', 1.0, 'up'): ('0.000169', '0.000391')}


def se_index(gr): return [i for i, a in enumerate(gr.a_) if a.startswith('StableEnrich')][0]


def table4_check(env):
    """The 21 Table 4 cells at the current namespace state (must be V0 or values equal to it)."""
    W0 = env.g['W0']; out = {}
    for (key, V, lab), want in EXP.items():
        if key == 'BRagg': xs = [env.fb('BR:' + p, V, lab).opt(W0)['agg'] for p in PER[:2]]
        else:
            xs = []
            for p in PER:
                gr = env.fb('T01t:' + p, V, lab); o = gr.opt(W0)
                xs.append(o['tot'][se_index(gr)] if key == 'se' else o[key])
        got = rng2(xs); out['%s|%g|%s' % (key, V, lab)] = dict(want=want, got=got, ok=got == want)
    for (kind, V, lab), want in EXPW.items():
        pers = PER[:2] if kind == 'BR' else PER
        xs = [env.fb(kind + ':' + p, V, lab).wstar('agg') for p in pers]
        num = all(not isinstance(x, str) for x in xs)
        ok = num and sig_equal(min(xs), want[0]) and sig_equal(max(xs), want[1])
        out['wstar|%s|%g|%s' % (kind, V, lab)] = dict(want=list(want), got=[x if isinstance(x, str) else float(x) for x in xs], ok=ok)
    return out


def repro_v0(env):
    """V0: FI against P3 p3.json ['FI'], FR and FB against K14 k14.json (absolute 1e-12)."""
    env.reset(); W0 = env.g['W0']; o = {}
    with open(P3J, encoding='utf-8') as fh: p3 = json.load(fh)['FI']
    mx = 0.0
    for p in PER:
        for lab in LABS:
            c = p3['%s|%s' % (p, lab)]
            mx = max(mx, abs(env.fb('T01t:' + p, 1.0, lab).opt(W0)['agg'] - c['agg_fb']),
                     abs(env.fi('T01t:' + p, lab).opt(W0)['agg'] - c['agg_fi']))
    o['fi_maxdiff'] = mx; o['fi_ok'] = mx <= 1e-12
    with open(K14J, encoding='utf-8') as fh: k14j = json.load(fh)['cells']
    mx = 0.0
    for p in PER:
        c = k14j['T01t|1|%s|lo' % p]
        for var in FR_VARS: mx = max(mx, abs(env.fr('T01t:' + p, 'lo', var).opt(W0)['agg'] - c[var]['agg']))
        mx = max(mx, abs(env.fb('T01t:' + p, 1.0, 'lo').opt(W0)['agg'] - c['fb']['agg']))
    o['fr_maxdiff'] = mx; o['fr_ok'] = mx <= 1e-12
    return o


def repro_p4b(env, wstar=True):
    """The stage-1 machinery against P4 base B at multiplier 1 (p4.json bases.na.kgrid['all|1']) and P3 (b) (p3.json
    'na', 'FI_na'): the namespace REL_M set to 16,800 with every switch off (stage 1's V3, no longer a P9 variant).
    Compares every aggregate cell (agg, med, n_le10, se, se_k, w*), every seller's total and k, and FI and FR.
    Returns maximal absolute differences and booleans only."""
    env.reset(); env.g['REL_M'] = REL_M_P4B; env.g['_G'].clear()
    try: return _repro_p4b(env, wstar)
    finally:
        env.g['REL_M'] = 2_930; env.reset()


def _repro_p4b(env, wstar):
    W0 = env.g['W0']; KS = env.g['KS']
    with open(P4J, encoding='utf-8') as fh: p4 = json.load(fh)['bases']['na']['kgrid']['all|1']
    with open(P3J, encoding='utf-8') as fh: p3 = json.load(fh)
    mx = 0.0; kbad = 0; ncell = 0; missing = []
    def d(a, b):
        if isinstance(a, str) or isinstance(b, str): return 0.0 if a == b else math.inf
        return abs(a - b)
    for key, c in p4.items():
        kind, V, p, lab = key.split('|')
        gr = env.fb(kind + ':' + p, float(V), lab)
        if not gr.ok: missing.append(key); continue
        o = gr.opt(W0); ncell += 1
        mx = max(mx, d(o['agg'], c['agg']), d(o['med'], c['med']))
        kbad += int(int((o['tot'] <= TH).sum()) != c['n_le10'])
        for i, a in enumerate(gr.a_):
            mx = max(mx, d(float(o['tot'][i]), c['per'][a][0])); kbad += int(int(KS[o['ki'][i]]) != c['per'][a][1])
        if kind == 'T01t':
            j = se_index(gr); mx = max(mx, d(float(o['tot'][j]), c['se'])); kbad += int(int(KS[o['ki'][j]]) != c['se_k'])
            if wstar and 'wstar' in c: mx = max(mx, d(gr.wstar('agg'), c['wstar']))
        if 'fi' in c: mx = max(mx, d(env.fi(kind + ':' + p, lab).opt(W0)['agg'], c['fi']))
        if 'fr' in c:
            for v in FR_VARS: mx = max(mx, d(env.fr(kind + ':' + p, lab, v).opt(W0)['agg'], c['fr'][v]))
    for key, c in p3['na'].items():
        kind, V, p, lab = key.split('|')
        if p not in PER: continue
        mx = max(mx, d(env.fb(kind + ':' + p, float(V), lab).opt(W0)['agg'], c['agg']))
    for p in PER:
        for lab in LABS:
            mx = max(mx, d(env.fi('T01t:' + p, lab).opt(W0)['agg'], p3['FI_na']['%s|%s' % (p, lab)]['agg_fi']))
    return dict(p4b_maxdiff=mx, p4b_kdiff=kbad, p4b_cells=ncell, p4b_missing=missing, p4b_ok=(mx <= 1e-12 and kbad == 0 and ncell > 0))


# ================================================================== cells (main path; real data only in stage 2)
def cells(env, fi_fr=True):
    """All report cells of calc-rules.md 3 at the current variant."""
    W0 = env.g['W0']; KS = env.g['KS']; c = {}
    for V in VS:
        for p in PER:
            for kind in KINDS:
                for lab in LABS:
                    gr = env.fb(kind + ':' + p, V, lab)
                    if not gr.ok: continue
                    o = gr.opt(W0)
                    x = dict(agg=o['agg'], med=o['med'], le10=bool(o['agg'] <= TH), n_le10=int((o['tot'] <= TH).sum()), N=gr.N,
                             R=float(gr.R.sum()),
                             per={gr.a_[i]: [float(o['tot'][i]), int(KS[o['ki'][i]]), float(gr.R[i])] for i in range(gr.N)})
                    if kind == 'T01t':
                        j = se_index(gr); x['se'] = float(o['tot'][j]); x['se_k'] = int(KS[o['ki'][j]])
                    if fi_fr and V == 1.0:
                        fo = env.fi(kind + ':' + p, lab).opt(W0)
                        x['fi'] = fo['agg']
                        x['fi_per'] = {gr.a_[i]: [float(fo['tot'][i]), int(KS[fo['ki'][i]])] for i in range(gr.N)}
                        ch = [a for a in gr.a_ if x['fi_per'][a][0] < x['per'][a][0]]
                        x['fi_cheaper'] = ch; x['n_fi_cheaper'] = len(ch)
                        x['share_fi_cheaper'] = float(sum(x['per'][a][2] for a in ch) / x['R'])
                        mix = sum(min(x['fi_per'][a][0], x['per'][a][0]) * x['per'][a][2] for a in gr.a_) / x['R']
                        x['agg_mix'] = float(mix); x['fb_cheaper_agg'] = bool(x['agg'] < x['fi'])
                        if kind == 'T01t' and lab == 'lo':
                            x['fr'] = {v: env.fr(kind + ':' + p, lab, v).opt(W0)['agg'] for v in FR_VARS}
                            x['fr_above_fb'] = {v: bool(x['fr'][v] > x['agg']) for v in FR_VARS}
                    c['%s|%g|%s|%s' % (kind, V, p, lab)] = x
    return c


def additivity(env, w=None, pers=None):
    """At the array level (every k, every seller), term by term, V1 - V0 = (V2 - V0) + (V3 - V0) + (V4 - V0), and each
    single-component variant moves only its own terms (TERMS: V2 'sampvrf', V3 'release', V4 'anchor', 'l1' and
    'detincl'). The components touch disjoint terms (calc-rules.md 7.5), so no cell is excluded. Returns the largest
    relative residual, the cells compared, the cells whose anchor units differ from V0 and any term moved outside
    its component."""
    W0 = env.g['W0'] if w is None else w
    mx = 0.0; n_cell = 0; n_unit = 0; only_bad = []
    for p in (PER if pers is None else pers):
        for kind in KINDS:
            for lab in LABS:
                for V in VS:
                    P = {}
                    for v in MAIN_VARS:
                        env.set_variant(v); gr = env.fb(kind + ':' + p, V, lab)
                        if not gr.ok: break
                        frz, ded = gr.loss(W0)
                        P[v] = (dict(gr.c0parts, frozen=frz, deduct=ded, capital=gr.cap(0.10)), gr.Ua[0].copy())
                    if len(P) < len(MAIN_VARS): continue
                    t0 = P['V0'][0]; n_cell += t0['verify'].size
                    n_unit += int(np.sum(P['V4'][1] != P['V0'][1]))
                    assert set(P['V1'][0]) == set(t0)
                    for t in t0:
                        d = (P['V1'][0][t] - t0[t]) - sum(P[v][0][t] - t0[t] for v in SINGLE)
                        sc = np.maximum(np.maximum(np.abs(t0[t]), np.abs(P['V1'][0][t])), 1e-300)
                        mx = max(mx, float(np.max(np.abs(d) / sc)))
                        for v, comp in SINGLE.items():
                            if t not in TERMS[comp] and not np.array_equal(P[v][0][t], t0[t]): only_bad.append((v, p, kind, lab, V, t))
    env.reset()
    return dict(max_rel=mx, cells=n_cell, anchor_units_changed=n_unit, other_terms_changed=only_bad)


def run(env, fi_fr=True):
    o = {}
    for v in VARIANTS:
        env.set_variant(v)
        o[v] = cells(env, fi_fr=fi_fr and v != 'V1t1')
    env.reset()
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out'); ap.add_argument('--check-only', action='store_true')
    args = ap.parse_args()
    T0 = time.time()
    g, repro = load_k11b()
    print('k11b_output.md reproduced byte for byte:', repro, flush=True)
    assert repro
    env = Env(g)
    env.reset()
    T4 = table4_check(env); t4ok = all(v['ok'] for v in T4.values())
    print('V0 Table 4 cells (%d):' % len(T4), t4ok, flush=True)
    env.set_values(setback_values(env.model)); T4b = table4_check(env); t4bok = all(v['ok'] for v in T4b.values()); env.reset()
    print('V1 code paths with the model constants (set back), Table 4:', t4bok, flush=True)
    RP = repro_v0(env); print('V0 FI (P3) and FR (K14):', RP['fi_ok'], RP['fr_ok'], flush=True)
    RP.update(repro_p4b(env)); print('REL_M 16,800 through the namespace = P4 base B and P3 (b):', RP['p4b_ok'], flush=True)
    META = dict(k11b_reproduced=repro, table4_ok=t4ok, table4_back_ok=t4bok, table4=T4, repro=RP,
                model=MODEL, model_line=MODEL_LINE, meas=MEAS, cl_bill_t1=cl_bill_meas(TRIES_SENS),
                release_meas=REL_MEAS, anchor_meas={k: (v if not isinstance(v, dict) else {str(a): b for a, b in v.items()})
                                                    for k, v in ANC_MEAS.items()},
                model_anchor=dict(G10B_F={str(a): b for a, b in g['G10B_F'].items()}, G10B_M={str(a): b for a, b in g['G10B_M'].items()},
                                  CAP_GAS={str(a): b for a, b in g['CAP_GAS'].items()}),
                model_release=dict(REL_F=g['REL_F']['ledger'], REL_M=g['REL_M'], REL_K=g['REL_K']),
                variants={v: variant_values(MODEL, **VARIANTS[v]) for v in VARIANTS},
                k11b_sha256=hashlib.sha256((K11 / 'k11b.py').read_bytes()).hexdigest(),
                p9_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if args.check_only: return
    assert args.out, '--out is required'
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT; OUT.mkdir(parents=True, exist_ok=True)
    if not (t4ok and t4bok and RP['fi_ok'] and RP['fr_ok'] and RP['p4b_ok']):
        with open(OUT / 'p9.json', 'w') as fh: json.dump(dict(meta=META, verdict='withheld: reproduction failure'), fh, indent=1, ensure_ascii=False)
        print('reproduction failed: no values reported'); sys.exit(2)
    ADD = additivity(env); META['additivity'] = ADD
    print('additivity:', ADD['max_rel'] <= 1e-12 and not ADD['other_terms_changed'], flush=True)
    if ADD['max_rel'] > 1e-12 or ADD['other_terms_changed']:
        with open(OUT / 'p9.json', 'w') as fh: json.dump(dict(meta=META, verdict='withheld: additivity check failure'), fh, indent=1, ensure_ascii=False)
        print('additivity check failed: no values reported'); sys.exit(2)
    RES = dict(meta=META, variants=run(env))
    write_outputs(RES, OUT)
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


def write_outputs(RES, OUT):
    with open(OUT / 'p9.json', 'w') as fh: json.dump(RES, fh, indent=1, ensure_ascii=False, allow_nan=True)
    (OUT / 'p9_tables.md').write_text(tables(RES), encoding='utf-8')
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in ('p9.json', 'p9_tables.md'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')


# ================================================================== tables (rounding: calc-rules.md 0.4)
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator'}
KN = {'T01t': 'six seller sum', 'BR': 'BlockRun'}
VN = {'V0': 'V0 model(K11b, Table 4)', 'V1': 'V1 all measured(VRF, release, anchor)', 'V2': 'V2 VRF only', 'V3': 'V3 release only',
      'V4': 'V4 anchor only', 'V1t1': 'V1, claim gas attempt 1 times(sensitivity)'}


def pc(x): return '-' if x is None else ('%s' % x if isinstance(x, str) else '%.2f' % (100 * x))
def star(x): return pc(x) + ('*' if x is not None and not isinstance(x, str) and x > TH else '')


def tables(R):
    M = R['meta']; RP = M['repro']; VR = R['variants']; pers = [p for p in PER]
    L = ['**all values post hoc calculations registered verdict none.** `p9.py` output. mode N, σ 1, r 10%, a 0, w 0.00173, per seller optimal k. '
         'costs revenue relative to %, *  10% over.\n']
    AD = M.get('additivity', {})
    L.append('k11b_output.md reproduction: %s. V0 Table 4 cell: %s. measured path model constants put in V1 Table 4 cell: %s. V0 FI(P3), FR(K14) max difference %.1e, %.1e. '
             'REL_M 16,800 vs P4 reference B and P3 (b) max difference %.1e(k mismatch %d). additivity check max relative difference %.1e(cell %d, anchor unit changed seller %d).\n' % (
                 M['k11b_reproduced'], M['table4_ok'], M['table4_back_ok'], RP['fi_maxdiff'], RP['fr_maxdiff'], RP['p4b_maxdiff'], RP['p4b_kdiff'],
                 AD.get('max_rel', float('nan')), AD.get('cells', -1), AD.get('anchor_units_changed', -1)))
    L.append('## 1. changed constant\n')
    L.append('| constant | k11b.py lines | model value | measured value | using variant |'); L.append('|---|---|---|---|---|')
    for n in SUBST:
        L.append('| %s | %s | %s | %s | V1, V2 |' % (n, M['model_line'][n], format(M['model'][n], ','), format(M['meas'][n], ',')))
    mr, rm = M['model_release'], M['release_meas']
    L.append('| release, seller epoch 256 items or less | 184~185, 539, 609 | fixed %s, per sale %s, closed per case %s | fixed %s, per sale %s, closed per case %s | V1, V3 |' % (
        format(mr['REL_F'], ','), format(mr['REL_M'], ','), format(mr['REL_K'], ','), format(rm['F1'], ','), format(rm['M1'], ','), format(rm['K'], ',')))
    L.append('| release, 256 items over | equal(capacity if over per transaction fixed) | equal | per unit %s, cursor %s, per sale %s | V1, V3 |' % (
        format(rm['FU'], ','), format(rm['FC'], ','), format(rm['MU'], ',')))
    ma, am = M['model_anchor'], M['anchor_meas']
    L.append('| anchor unit(signature leaf) | 697~699(new_values), 191 | fixed %s, per leaf %s, per transaction leaf %s | fixed %s, per leaf %s, per unit leaf %d | V1, V4 |' % (
        format(round(ma['G10B_F']['1']), ','), format(round(ma['G10B_M']['1']), ','), ma['CAP_GAS']['1'], format(am['FU']['1'], ','), format(am['MU']['1'], ','), am['N']))
    L.append('| completion unit and first pull | none | none | fixed %s, per record %s | V1, V4 |' % (format(am['FC']['1'], ','), format(am['MC']['1'], ',')))
    L.append('\nV1 and V2 lower and facilitator case sample values also ECVRF Chainlink VRF v2.5 changes. V1t1 CL_BILL %s. measured for anchors EIP-7623 lower bound not set not(calc-rules.md 7.3).\n' % format(M['cl_bill_t1'], ','))

    vars_main = [v for v in MAIN_VARS if v in VR]
    L.append('## 2. set value (window: %s)\n' % ' / '.join(WN[p] for p in pers))
    L.append('| set | V | case | ' + ' | '.join(VN[v] for v in list(VR)) + ' |'); L.append('|---|---|---|' + '---|' * len(VR))
    for kind in KINDS:
        for V in VS:
            for lab in LABS:
                row = []
                for v in VR:
                    xs = [VR[v].get('%s|%g|%s|%s' % (kind, V, p, lab)) for p in pers]
                    s = ' / '.join('-' if x is None else star(x['agg']) for x in xs)
                    n = sum(1 for x in xs if x is not None and x['le10']); m = sum(1 for x in xs if x is not None)
                    row.append('%s (10%% within %d/%d)' % (s, n, m))
                L.append('| %s | %g | %s | %s |' % (KN[kind], V, LN[lab], ' | '.join(row)))

    L.append('\n## 3. per seller total (revenue relative to %%, in parentheses chosen k; columns %s)\n' % ', '.join(VN[v] for v in vars_main))
    for kind in KINDS:
        for V in VS:
            L.append('\n### %s, V %g\n' % (KN[kind], V))
            L.append('| window | seller | case | ' + ' | '.join(vars_main) + ' |'); L.append('|---|---|---|' + '---|' * len(vars_main))
            for p in pers:
                for lab in LABS:
                    key = '%s|%g|%s|%s' % (kind, V, p, lab)
                    if key not in VR['V0']: continue
                    for a in VR['V0'][key]['per']:
                        cs = ['%s (%d)' % (star(VR[v][key]['per'][a][0]), VR[v][key]['per'][a][1]) for v in vars_main]
                        L.append('| %s | %s | %s | %s |' % (WN[p], a, LN[lab], ' | '.join(cs)))

    L.append('\n## 4. full inspection FI with comparison (V 1; FI V1 measured release, VRF and anchor none)\n')
    L.append('| set | window | case | V0 FB | V0 FI | V1 FB | V1 FB V 0.2 | V1 FI | V1 more cheaper side(sum) | V1 FI cheaper seller count | its revenue share | V1 per seller cheaper side mixed |')
    L.append('|' + '---|' * 12)
    for kind in KINDS:
        for p in pers:
            for lab in LABS:
                key = '%s|1|%s|%s' % (kind, p, lab); x1 = VR['V1'].get(key)
                if x1 is None: continue
                x0 = VR['V0'][key]; x02 = VR['V1'].get('%s|0.2|%s|%s' % (kind, p, lab))
                L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %d/%d | %s | %s |' % (
                    KN[kind], WN[p], LN[lab], pc(x0['agg']), pc(x0['fi']), pc(x1['agg']), pc(x02['agg'] if x02 else None), pc(x1['fi']),
                    'FairBind' if x1['fb_cheaper_agg'] else 'FI', x1['n_fi_cheaper'], x1['N'], pc(x1['share_fi_cheaper']), pc(x1['agg_mix'])))
    L.append('\nper seller (V1, V 1; FB total / FI total, in parentheses chosen k):\n')
    L.append('| set | window | seller | ' + ' | '.join(LN[l] for l in LABS) + ' |'); L.append('|' + '---|' * (3 + len(LABS)))
    for kind in KINDS:
        for p in pers:
            k0 = '%s|1|%s|lo' % (kind, p)
            if k0 not in VR['V1']: continue
            for a in VR['V1'][k0]['per']:
                cs = []
                for lab in LABS:
                    x = VR['V1']['%s|1|%s|%s' % (kind, p, lab)]
                    cs.append('%s (%d) / %s (%d)%s' % (pc(x['per'][a][0]), x['per'][a][1], pc(x['fi_per'][a][0]), x['fi_per'][a][1],
                                                       ' FI cheaper' if a in x['fi_cheaper'] else ''))
                L.append('| %s | %s | %s | %s |' % (KN[kind], WN[p], a, ' | '.join(cs)))

    L.append('\n## 5. fixed sampling rate FR order (K14 definition, six seller sum, lower, V 1)\n')
    L.append('| variant | window | FB | FR main | FR-lo | FR main − FB (%p) | FR-lo − FB (%p) | FR main > FB | FR-lo > FB |'); L.append('|' + '---|' * 9)
    for v in vars_main:
        for p in pers:
            x = VR[v].get('T01t|1|%s|lo' % p)
            if x is None or 'fr' not in x: continue
            L.append('| %s | %s | %s | %s | %s | %+.2f | %+.2f | %s | %s |' % (
                v, WN[p], pc(x['agg']), pc(x['fr']['main']), pc(x['fr']['lo']), 100 * (x['fr']['main'] - x['agg']),
                100 * (x['fr']['lo'] - x['agg']), x['fr_above_fb']['main'], x['fr_above_fb']['lo']))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
