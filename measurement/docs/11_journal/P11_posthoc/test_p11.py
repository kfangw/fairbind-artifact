#!/usr/bin/env python3
"""Tests of p11.py (calc-rules.md 5). Every formula is tested on synthetic inputs: pure functions against brute force,
and the k11b namespace with an injected synthetic window 'SYNW' (sellers as in P9's tests plus a seller part with
address counts), synthetic Base payees and stylised sellers. On real sellers only the reproduction checks of
calc-rules.md 0.4 are run (values already seen); no V1u, (a) or (b) value of a real seller is computed. Output: pass / fail.

    python3 -I test_p11.py
"""
import hashlib, itertools, math, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import p11  # noqa: E402
import p9, p10, p6  # noqa: E402  (the same modules p11 imported)

X = None
NEP = 21 * 144
ROOT = HERE.parent.parent.parent
MS = ROOT / 'docs' / 'manuscript'   # not in this bundle


def setUpModule():
    global X
    X = p11.P11(tag='k11b_p11_test')
    g = X.g
    g['PDAYS']['SYNW'] = 21
    orig = g['t13_sellers']
    g['t13_sellers'] = lambda st, p, V: synthetic(st, V) if p == 'SYNW' else orig(st, p, V)
    c = addr_counts()
    g['LCNT'][('SYNW', 'SynAddr')] = c
    g['SUMALL']['SYNW'] = [dict(seller='SynAddr', sales=str(int(c.sum())))]


def tearDownModule():
    X.restore()


def S(a, R, n, ns, E1, m1, tier0=False, cnt=None, base=None):
    return dict(a=a, base=base or a, R=float(R), n=n, ns=float(ns), E1=E1, m1=m1, cnt=cnt, tier0=tier0, rs=0.25)


def syn_counts():
    c = np.zeros(NEP)
    for e, m in ((3, 300), (4, 20), (40, 600), (41, 255), (42, 2), (700, 257), (701, 1), (2000, 90), (2001, 170)):
        c[e] = m
    return c


def addr_counts():
    """Per-epoch counts of the address SynAddr, of which the seller part SynP holds 40%."""
    c = np.zeros(NEP)
    for e, m in ((10, 5), (11, 3), (500, 12), (1200, 1), (1201, 4), (2500, 30)):
        c[e] = m
    return c


def synthetic(kind, V):
    f = 1.0 if V == 1.0 else 5.0
    if kind == 'T01t':
        c = syn_counts(); ca = addr_counts()
        L = [S('StableEnrich(syn)', 120.0, 6_000, 210.0, 1_500, 12), S('SynB', 25.0, 3_000, 14.0, 800, 8, tier0=True),
             S('SynC', 0.9, 80, 1.5, 60, 3), S('SynD', 400.0, 40_000, 900.0, 900, 400),
             S('SynE', 30.0, int(c.sum()), 40.0, int((c > 0).sum()), int(c.max()), cnt=c),
             S('SynP', 1.6, int(0.4 * ca.sum()), 1.0, int((ca > 0).sum()), 12, base='SynAddr')]
    elif kind == 'BR':
        L = [S('SynT', 900.0, 90_000, 1_800.0, 3_000, 60)]
    else:
        return []
    for s in L: s['ns'] = min(float(s['n']), s['ns'] * f)
    return L


def payees(p):
    """Synthetic Base payees in p10.recipients' format (sparse per-epoch counts)."""
    out = []
    rng = np.random.default_rng(7)
    specs = (('0xaa01', 0.02, 40, 3000), ('0xaa02', 0.1, 15, 1500), ('0xaa03', 0.003, 5, 300), ('0xaa04', 0.5, 2, 400),
             ('0xaa05', 2.0, 1, 50), ('notevm', 0.05, 10, 100), ('0xaa06', 0.01, 300, 2900))
    for a, v, m, E in specs:
        idx = np.sort(rng.choice(NEP, size=E, replace=False)); c = np.maximum(1, rng.poisson(m, size=E)).astype(float)
        n = float(c.sum()); R = v * n
        out.append(dict(a=a, R=R, n=n, ns=n * min(1.0, v), E1=E, m1=float(c.max()), idx=idx, c=c, maxep=float(c.max() * v),
                        ck='RS3', tier0=False))
    return out


def close(a, b, rel=1e-12, ab=1e-15):
    a = np.asarray(a, float); b = np.asarray(b, float)
    return bool(np.all(np.abs(a - b) <= ab + rel * np.maximum(np.abs(a), np.abs(b))))


CASES = [(kind, lab) for kind in p11.KINDS for lab in p11.LABS]


# ================================================================== pure functions and sources
class Pure(unittest.TestCase):
    def test_usdc_constants(self):
        r = p11.REL_MEAS_U
        self.assertEqual((r['N'], r['F1'], r['M1'], r['FU'], r['MU'], r['FC'], r['K']),
                         (256.0, 87_993, 16_920, 73_697 + 70_153, 9_888 + 12_965, 69_391, -876))
        self.assertEqual(r['FU'], 143_850)
        a = p11.ANC_MEAS_U
        self.assertEqual((a['FU'], a['MU'], a['MC']), ({0: 279_844, 1: 260_004}, {0: 16_785, 1: 28_127}, {0: 5_135, 1: 5_135}))
        self.assertEqual(a['FC'], {0: 288_481, 1: 299_823})
        # the builders give P9's own mock constants back
        self.assertEqual(p11.anc_meas(p9.ANC_UNIT, p9.ANC_COMPLETE), p11.ANC_MEAS_V1)
        self.assertEqual(p11.rel_meas(p9.REL1_F, p9.REL1_M, p9.RELU_CHK, p9.RELU_PAY, p9.REL_CUR, p9.REL1_PROVEN), p11.REL_MEAS_V1)
        self.assertIs(p11.CONSTS['V1'][0], p11.REL_MEAS_V1)
        # V1u differs from V1 only in these entries
        d = {k for k in r if r[k] != p11.REL_MEAS_V1[k]}
        self.assertEqual(d, {'F1', 'FU'})
        self.assertEqual(r['F1'] - p11.REL_MEAS_V1['F1'], 12_662); self.assertEqual(r['FU'] - p11.REL_MEAS_V1['FU'], 12_662)

    def test_sources(self):
        for f, line, text in p11.SOURCES:
            got = f.read_text(encoding='utf-8').split('\n')[line - 1]
            self.assertIn(text, got, (f.name, line))
        p3 = (HERE.parent / 'P3_posthoc' / 'p3.py').read_text(encoding='utf-8').split('\n')
        self.assertIn('FB_SHARE = 86_824 - 31_315', p3[40])
        self.assertIn('[0.0 if c == \'TEE\' else prm.gusd(FB_SHARE) for c in self.ck]', p3[75])
        icp = HERE.parent / 'P3_posthoc' / 'independent-check.md'
        ic = icp.read_text(encoding='utf-8') if icp.exists() else None   # working document, not in this bundle
        if ic is not None: self.assertIn('| 14,300~41,300 |', ic); self.assertIn('about 45,600~72,600 gas', ic); self.assertIn('about 54,300~81,300 gas', ic)
        if MS.exists():   # manuscript text checks; the manuscript is not part of this bundle
            ev = (MS / 'sections' / 'sec_eval.tex').read_text(encoding='utf-8')
            for t in ('about 54,300 to 81,300', 'about 45,600 to 72,600', '31,315; full inspection cheaper', '86,824', '49,734', '52,253', '41,406'):
                self.assertIn(t, ev)
            self.assertIn('2,279 blocks', (MS / 'supp_body.tex').read_text(encoding='utf-8'))
            self.assertIn('one stall of 2,279 blocks', (MS / 'sections' / 'sec_discussion.tex').read_text(encoding='utf-8'))
        k11 = (HERE.parent / 'K11' / 'k11b.py').read_text(encoding='utf-8').split('\n')
        self.assertEqual(k11[749], 'W0 = 0.00173')
        self.assertIn('def DF(self, k): return EPB * k + self.DA + self.SV + self.TP', k11[293])
        self.assertIn("parts['verify'] = np.broadcast_to(self.cp * ns / R, E.shape).copy()", k11[578])
        self.assertIn('def splits_from_counts(c, k, cap):', k11[371]); self.assertIn('def splits_bound(n, E, m1, k, cap):', k11[377])
        self.assertIn("'G10-3 Pyth Lazer-shaped update, 1 feed(s), tx gas'", k11[169])
        import gzip
        with gzip.open(HERE.parent / 'G11_gas' / 'logs' / 't1a.tsv.gz', 'rt') as fh: self.assertIn('\t86824\t', fh.readline())
        with gzip.open(HERE.parent / 'G11_gas' / 'logs' / 'selfsub.tsv.gz', 'rt') as fh: t = fh.read()
        for v in ('882687', '363102', '605045', '294165'): self.assertIn('\t%s' % v, t)
        self.assertEqual(p6.GAP, (47_806_547, 47_808_825))

    def test_fi_points(self):
        self.assertEqual(p11.BIND, 8_696)
        self.assertEqual(p11.FI_POINTS, dict(same=86_824, own_lo=31_315, own_a=45_615, own_b=72_615, own_bind_a=54_311, own_bind_b=81_311))
        self.assertEqual(p11.FB_SHARE, 55_509)
        self.assertTrue(set(p11.FI_POINTS.values()) <= set(p11.G_GRID)); self.assertEqual(list(p11.G_GRID), sorted(p11.G_GRID))
        self.assertEqual(len(p11.scenarios()), 6 + 2 * len(p11.G_GRID) + len(p11.GB_GRID) * len(p11.GM_GRID) + 1)
        self.assertEqual(p11.batch_cap(21_000, 1_000), math.floor((2 ** 24 - 21_000) / 1_000))

    def test_cp_shift(self):
        gu = lambda x: 1e-8 * x
        cp = np.array([0.002, 0.015, 0.0009]); ck = ['RS3', 'SP0', 'TEE']
        self.assertTrue(close(p11.cp_shift(gu, ck, cp, 86_824), cp))
        x = p11.cp_shift(gu, ck, cp, 31_315)
        self.assertTrue(close(x, [0.002 - gu(55_509), 0.015 - gu(55_509), 0.0009]))
        x = p11.cp_shift(gu, ck, cp, 100_000)
        self.assertTrue(close(x, [0.002 + gu(13_176), 0.015 + gu(13_176), 0.0009]))
        self.assertTrue(close(p11.cp_teeW(gu, ck, cp), [0.002, 0.015, 0.0009 + gu(55_509)]))

    def test_gstar_closed_form_against_bisection(self):
        """Linear costs in g with a k-independent proof term: the closed form equals the bisection root."""
        rng = np.random.default_rng(3); gu1 = 2.4e-8
        for _ in range(200):
            R = rng.uniform(1, 100); n = rng.integers(50, 5000); ns = rng.uniform(1, n - 1)
            ob = rng.uniform(0.01, 0.3, 6); of = rng.uniform(0.01, 0.3, 6); go = rng.choice([86_824, 604_522, 36_440])
            fb = lambda gg, mode: (ob + (gg * gu1 * ns / R if mode == 'both' else go * gu1 * ns / R)).min()
            fi = lambda gg: (of + gg * gu1 * n / R).min()
            xb, xf = fb(go, 'both'), fi(go)
            for mode in ('fi', 'both'):
                gs = p11.gstar(xb, xf, R, n, ns, gu1, go, mode)
                f = lambda gg: fb(gg, mode) - fi(gg)
                lo, hi = -1e9, 1e9
                for _ in range(200):
                    mid = 0.5 * (lo + hi)
                    if f(mid) > 0: lo = mid
                    else: hi = mid
                self.assertLess(abs(gs - 0.5 * (lo + hi)), 1e-3)

    def test_region(self):
        self.assertEqual(p11.region(0.05, 0.06), 'A'); self.assertEqual(p11.region(0.05, 0.05), 'A')
        self.assertEqual(p11.region(0.06, 0.05), 'B'); self.assertEqual(p11.region(0.2, 0.3), 'C_fb')
        self.assertEqual(p11.region(0.3, 0.2), 'C_fi'); self.assertEqual(p11.region(0.12, 0.09), 'B')

    def test_cover_and_fail_at(self):
        rng = np.random.default_rng(5)
        for _ in range(50):
            L = int(rng.integers(1, 60)); S = int(rng.integers(L, 300)); D = rng.integers(-20, S + 80, size=30)
            brute = [sum(1 for s in range(S + 1) if s <= d <= s + L - 1) for d in D]
            self.assertEqual(list(p11.cover(D, L, S)), brute)

    def brute_stall(self, c, pi, q, nep, L, a_A=120, sv=31, tp=1800):
        """Average of p6.seller_gap over every stall start (F = 0, phase 0)."""
        S = nep * 300 - L; Ps = []; pa = 0.0; pb = 0.0
        last = np.array([p6.epoch_bounds(e, 0, 0)[1] for e in range(nep)])
        A = last + a_A; P = A + sv + tp; D = last + tp
        fi = 0.0
        for s in range(S + 1):
            gap = (s, s + L - 1)
            Ea = [e for e in range(nep) if gap[0] <= A[e] <= gap[1]]; Eb = [e for e in range(nep) if gap[0] <= P[e] <= gap[1]]
            r = p6.seller_gap(c, pi, q, Ea, Eb); Ps.append(r['Pany']); pb += r['exp_b']
            pa += sum(1 for e in Ea if c[e] > 0)
            fi += sum(c[e] for e in range(nep) if gap[0] <= D[e] <= gap[1]) / c.sum()
        return np.mean(Ps), pa / (S + 1), pb / (S + 1), fi / (S + 1)

    def test_stall_bruteforce(self):
        rng = np.random.default_rng(11)
        for nep, L in ((12, 700), (10, 2_279), (9, 150)):
            for pi, q in ((1.0, 0.3), (0.4, 0.2), (1.0, 1.0), (0.25, 1.5)):
                c = np.where(rng.random(nep) < 0.5, rng.integers(1, 6, nep), 0).astype(float); c[0] = max(c[0], 1)
                P, pa, pb, fi = self.brute_stall(c, pi, q, nep, L)
                x = p11.stall_fb(c, pi, q, nep, L, 120, 31, 1800)
                self.assertTrue(close(x['P'], P, rel=1e-10, ab=1e-12), (nep, L, pi, q, x['P'], P))
                self.assertTrue(close(x['anchors'], pa, rel=1e-10, ab=1e-12)); self.assertTrue(close(x['proofs'], pb, rel=1e-10, ab=1e-12))
                self.assertTrue(close(p11.stall_fi(c, pi, nep, L, 1800), fi, rel=1e-10, ab=1e-12))

    def test_fail_at_matches_p6(self):
        rng = np.random.default_rng(13); nep = 40; L = 2_279
        last = np.array([p6.epoch_bounds(e, 0, 0)[1] for e in range(nep)])
        A, M_, P = p6.deadlines(last, 120, 31, 1800)
        for _ in range(40):
            c = np.where(rng.random(nep) < 0.4, rng.integers(1, 9, nep), 0).astype(float)
            pi, q = float(rng.choice([1.0, 0.3])), float(rng.uniform(0.01, 1.2)); s = int(rng.integers(0, nep * 300 - L))
            gap = (s, s + L - 1)
            E = p6.gap_epochs(nep, 0, 0, gap, 120, 31, 1800)
            want = p6.seller_gap(c, pi, q, E['a'], E['b'])['Pany']
            D, x = p11.fail_points(c, pi, q, A, P)
            self.assertTrue(close(p11.fail_at(D, x, s, L), want, ab=1e-14))

    def test_stall_bounds(self):
        """Without counts: the lower and upper bounds hold around the exact value for random placements."""
        rng = np.random.default_rng(17); nep = 200; L = 2_279
        for _ in range(60):
            E1 = int(rng.integers(1, 40)); c = np.zeros(nep)
            if rng.random() < 0.5: st = int(rng.integers(0, nep - E1)); c[st:st + E1] = rng.integers(1, 5, E1)
            else: c[rng.choice(nep, E1, replace=False)] = rng.integers(1, 5, E1)
            q = float(rng.uniform(0.001, 0.3)); ns = q * c.sum()
            ex = p11.stall_fb(c, 1.0, q, nep, L, 120, 31, 1800)['P']
            b = p11.stall_fb_bounds(E1, ns, nep, L)
            self.assertLessEqual(ex, b['P_up'] + 1e-12); self.assertEqual(b['P'], b['P_up'])
            # the lower bound ignores edge effects; it holds for placements away from the window's end
            if np.nonzero(c)[0].max() * 300 + 300 + 120 + L < nep * 300: self.assertGreaterEqual(ex + 1e-12, b['P_lo'])
            self.assertLessEqual(p11.stall_fi(c, 1.0, nep, L, 1800), p11.stall_fi_bound(nep, L) + 1e-15)

    def test_batch_tx_bruteforce(self):
        g = X.g; KS = g['KS']
        c = syn_counts()
        sell = [S('a', 10.0, int(c.sum()), 5.0, int((c > 0).sum()), int(c.max()), cnt=c), S('b', 3.0, 900, 2.0, 30, 90)]
        E = np.array([[min(s['E1'], math.ceil(NEP / k)) for s in sell] for k in KS], float)
        for up in (False, True):
            gr = SimpleNamespace(S=sell, E=E, prm=SimpleNamespace(up=up, curpe=True))
            for cap in (7.0, 100.0, 256.0, 5_000.0):
                T = p11.batch_tx(g, gr, cap)
                for i, k in enumerate(KS):
                    ii = 0 if up else i; kk = KS[ii]
                    m = np.bincount(np.arange(NEP) // kk, weights=c); m = m[m > 0]
                    self.assertEqual(T[i, 0], E[ii, 0] + sum(max(math.ceil(x / cap) - 1, 0) for x in m))
                    self.assertEqual(T[i, 1], E[ii, 1] + g['splits_bound'](900, E[ii, 1], 90, kk, cap))


# ================================================================== the namespace on synthetic sellers
def grids(kind, lab):
    st = kind + ':SYNW'
    return X.env.fb(st, 1.0, lab), X.env.fi(st, lab)


class Namespace(unittest.TestCase):
    def tearDown(self): X.set_base('V1u')

    def test_base_switch_terms(self):
        """V1u and V1 differ only in FairBind's release and anchor terms and FI's release term; switching back gives
        the same arrays; the module variables are restored by restore()."""
        for kind, lab in CASES:
            X.set_base('V1'); b1, f1 = grids(kind, lab); A1 = dict(b1.c0parts); F1 = dict(f1.c0parts)
            X.set_base('V1u'); bu, fu = grids(kind, lab)
            for t in A1:
                same = np.array_equal(A1[t], bu.c0parts[t])
                self.assertEqual(same, t not in ('release', 'anchor'), (kind, lab, t))
            for t in F1:
                self.assertEqual(np.array_equal(F1[t], fu.c0parts[t]), t != 'release', (kind, lab, t))
            self.assertTrue(np.array_equal(b1.loss(p11.W0)[0], bu.loss(p11.W0)[0]))
            X.set_base('V1'); b2, f2 = grids(kind, lab)
            for t in A1: self.assertTrue(np.array_equal(A1[t], b2.c0parts[t]))
        X.set_base('V1u'); self.assertIs(p9.REL_MEAS, p11.REL_MEAS_U); self.assertIs(p10.ANC, p11.ANC_MEAS_U)
        X.restore(); self.assertIs(p9.REL_MEAS, p11.REL_MEAS_V1); self.assertIs(p10.REL, p11.P10_REL0)

    def test_v1u_release_and_anchor_by_hand(self):
        """SynC (no counts, at most 256 sales per seller epoch): the V1u - V1 release difference is 12,662 gas per
        active seller epoch for FairBind and FI; the anchor difference is the hand formula of the unit constants."""
        for lab in ('lo', 'fac'):
            X.set_base('V1'); b1, f1 = grids('T01t', lab); X.set_base('V1u'); bu, fu = grids('T01t', lab)
            j = bu.a_.index('SynC'); prm = bu.prm
            want = prm.gusd(12_662 * bu.E[:, j]) / bu.R[j]
            self.assertTrue(close(bu.c0parts['release'][:, j] - b1.c0parts['release'][:, j], want))
            self.assertTrue(close(fu.c0parts['release'][:, j] - f1.c0parts['release'][:, j], want))
            n = bu.n[j]; E0 = bu.E[0, j]; Ua = bu.Ua[0, j]; P = n          # m1 <= 256: P = n
            dg = Ua * (260_004 - 260_025) + (n - E0) * (28_127 - 28_126) + E0 * (299_823 - 299_810)
            self.assertTrue(close(bu.c0parts['anchor'][:, j] - b1.c0parts['anchor'][:, j], prm.gusd(dg) / bu.R[j], rel=1e-9, ab=1e-15))

    def test_two_paths_agree(self):
        """Every (a) scenario through P9's grids and through P10's closed form gives the same totals (V1u, SYNW)."""
        X.set_base('V1u'); M = X.M; KS = X.g['KS']
        for kind, lab in CASES:
            fb, fi = grids(kind, lab)
            for j, s in enumerate(fb.S):
                s = dict(s, ck=fb.ck[j])
                st = p10.structure(M, s, 21); pb = p11.payee_base(M, s, st, lab)
                for key, sc in p11.scenarios():
                    tb, tf = p11.named_terms(X, fb, fi, sc)
                    pb_b, pb_f = p11.payee_terms(M, s, pb, sc)
                    self.assertTrue(close(tb[:, j], pb_b, rel=1e-11, ab=1e-14), (kind, lab, s['a'], key))
                    self.assertTrue(close(tf[:, j], pb_f, rel=1e-11, ab=1e-14), (kind, lab, s['a'], key))

    def test_scenarios_identity_and_scope(self):
        X.set_base('V1u'); W = X.g['W0']
        for kind, lab in CASES:
            fb, fi = grids(kind, lab)
            tb0, tf0 = fb.total(W), fi.total(W)
            tb, tf = p11.named_terms(X, fb, fi, dict(kind='g', mode='fi', g=86_824))
            self.assertTrue(close(tb, tb0) and close(tf, tf0))
            tb, tf = p11.named_terms(X, fb, fi, dict(kind='g', mode='both', g=86_824))
            self.assertTrue(close(tb, tb0) and close(tf, tf0))
            tb, tf = p11.named_terms(X, fb, fi, dict(kind='teeW'))
            for j, c in enumerate(fb.ck):
                self.assertEqual(np.array_equal(tf[:, j], tf0[:, j]), c != 'TEE')
            tb, tf = p11.named_terms(X, fb, fi, dict(kind='batch', GB=21_000, gb=5_000))
            self.assertTrue(np.array_equal(tb, tb0))
            for j, c in enumerate(fb.ck):
                if c != 'RS3': self.assertTrue(np.array_equal(tf[:, j], tf0[:, j]))
            # FI-own lower limit on tier 1a: FI falls by gusd(55,509) n / R for every k
            tb, tf = p11.named_terms(X, fb, fi, dict(kind='g', mode='fi', g=31_315))
            for j, c in enumerate(fb.ck):
                d = 0.0 if c == 'TEE' else fb.prm.gusd(55_509) * fi.n[j] / fi.R[j]
                self.assertTrue(close(tf0[:, j] - tf[:, j], d, rel=1e-9, ab=1e-15))

    def test_batch_by_hand(self):
        """FI-batch for SynE (per-epoch counts): G_B T(k) + g_b n plus the call's L1 per sale, at k = 1 by hand."""
        X.set_base('V1u'); fb, fi = grids('T01t', 'lo'); j = fi.a_.index('SynE'); prm = fi.prm; g = X.g
        GB, gb = 55_509, 20_000; cap = math.floor((2 ** 24 - GB) / gb)
        c = syn_counts(); m = c[c > 0]
        T = fi.E[0, j] + sum(max(math.ceil(x / cap) - 1, 0) for x in m)
        want = (prm.gusd(GB) * T + (prm.gusd(gb) + prm.wusd(g['CPG']['RS3'][1])) * fi.n[j]) / fi.R[j]
        vb = p11.verify_batch(g, fi, GB, gb, fi.ck)
        self.assertTrue(close(vb[0, j], want))

    def test_gstar_on_grids(self):
        """g*_FI and g* make the two designs' selected totals equal (SYNW, every case)."""
        X.set_base('V1u'); W = X.g['W0']
        gs = p11.gstar_cells_p(X, 'lo', ('SYNW',))
        for lab in p11.LABS:
            gs = p11.gstar_cells_p(X, lab, ('SYNW',))
            for kind in p11.KINDS:
                fb, fi = grids(kind, lab)
                for j, a in enumerate(fb.a_):
                    v = gs['SYNW|%s' % a]
                    for mode in ('fi', 'both'):
                        # move the seller's own call to g*: shift s = g_own - g*
                        dlt = v['g_own'] - v[mode]; gu = fb.prm.gusd
                        tf = fi.total(W)[:, j] - gu(dlt) * fi.n[j] / fi.R[j]
                        tb = fb.total(W)[:, j] - (gu(dlt) * fb.ns[j] / fb.R[j] if mode == 'both' else 0.0)
                        self.assertTrue(close(tb.min(), tf.min(), rel=1e-9, ab=1e-13), (lab, a, mode))

    def test_w_path(self):
        X.set_base('V1u')
        for kind, lab in CASES:
            fb, fi = grids(kind, lab)
            t0 = fb.total(0.0); self.assertTrue(close(t0, np.where(fb.bad, np.inf, fb.c0 + fb.cap(0.10))))
            self.assertTrue(close(fi.total(0.0), fi.c0 + fi.cap(0.10)))
            prev_b, prev_f = None, None
            for _, w in sorted(p11.W_GRID, key=lambda x: x[1]):
                b = fb.opt(w)['tot']; f = fi.opt(w)['tot']
                if prev_b is not None:
                    self.assertTrue(np.all(b >= prev_b - 1e-15) and np.all(f >= prev_f - 1e-15))
                prev_b, prev_f = b, f
        W = p11.w_named(X, ('SYNW',))
        x = W['T01t|SYNW|lo']['w0']; fb, fi = grids('T01t', 'lo')
        self.assertTrue(close(x['agg_fb'], fb.opt(p11.W0)['agg'])); self.assertTrue(close(x['agg_fi'], fi.opt(p11.W0)['agg']))
        self.assertEqual(set(W['T01t|SYNW|lo']), {n for n, _ in p11.W_GRID})

    def test_stall_named(self):
        """Sources (own counts, address counts with pi, bound), the hand formula of the FB share and the totals."""
        X.set_base('V1u'); g = X.g
        Sx = p11.stall_named(X, ('SYNW',))
        for kind, lab in CASES:
            fb, fi = grids(kind, lab); c = Sx['%s|SYNW|%s' % (kind, lab)]
            for j, a in enumerate(fb.a_):
                t = c['sellers'][a]
                want_src = 'own' if a == 'SynE' else ('address' if a == 'SynP' else 'bound')
                self.assertEqual(t['src'], want_src)
                DF = 300 + 120 + 31 + 1800
                loss = fb.R[j] * DF / fb.Wb + 1.0 + (fb.prm.gusd(g['G_FAIL']) if fb.prm.up else 0.0)
                self.assertTrue(close(t['loss'], loss)); self.assertTrue(close(t['fb_add'], t['P'] * loss / fb.R[j]))
                self.assertTrue(0.0 <= t['P'] <= 1.0 and 0.0 <= t['fi_frac'] <= 1.0)
                if a == 'SynP': self.assertTrue(close(t['pi'], fb.n[j] / addr_counts().sum()))
            for wn, w in p11.STALL_W:
                add = np.array([c['sellers'][a]['fb_add'] for a in fb.a_])
                tot = fb.opt(w)['tot'] + add
                self.assertTrue(close(c[wn]['agg_fb'], float((tot * fb.R).sum() / fb.R.sum())))
                self.assertEqual([v[1] for v in c[wn]['per'].values()], [int(g['KS'][i]) for i in fb.opt(w)['ki']])

    def test_stall_stylised(self):
        X.set_base('V1u'); M = X.M
        for v, Re in ((0.1, 0.5), (0.02, 1.3)):
            a, b = p11.stall_stylised(M, Re, v, 'lo')
            s = p10.stylised(Re / v, v)
            self.assertTrue(close(a, (s['R'] * 2_251 / (21 * 43_200) + 1.0) / s['R']))
            a2, b2 = p11.stall_stylised(M, Re, v, 'lo', cache=False)
            self.assertTrue(close(a, a2) and close(b, b2))
        a, b = p11.stall_stylised(M, 0.4, 0.05, 'lo', d=0.1); a2, b2 = p11.stall_stylised(M, 0.4, 0.05, 'lo', d=0.1, cache=False)
        self.assertTrue(close(a, a2) and close(b, b2))
        s = p10.stylised(0.4 / 0.05, 0.05, 0.1); full = (s['R'] * 2_251 / (21 * 43_200) + 1.0) / s['R']
        self.assertTrue(0.0 < a < full)                                 # an active share d = 0.1: P < 1

    def test_thresholds_gen_equals_p10(self):
        X.set_base('V1'); M = X.M
        for v in (0.05, 0.2):
            a = p11.thresholds_gen(lambda Re: p10.share_at(M, Re, v, 'lo', 1.0), v, 'lo', 1.0)
            b = p10.thresholds(M, v, 'lo', 1.0)
            self.assertEqual(p11.jsonable(a), p11.jsonable(b))
        t0 = p11.thr_w(X, p11.W0, 0.05); self.assertEqual(p11.jsonable(t0), p11.jsonable(p10.thresholds(M, 0.05, 'lo', 1.0)))
        self.assertEqual(M.W0, p11.W0)

    def test_payees(self):
        X.set_base('V1u')
        P = p11.fi_payees(X, ('SYNW',), payees)
        x = P['SYNW']
        self.assertEqual(x['N'], 5)                                   # 0x and mean sale <= 1: aa05 (2.0) and notevm out
        for key, _ in p11.scenarios():
            self.assertEqual(sum(v['n'] for v in x['sc'][key].values()), 5)
            self.assertTrue(close(sum(v['share'] for v in x['sc'][key].values()), 1.0))


class Reproduction(unittest.TestCase):
    """calc-rules.md 0.4 on real sellers (values already seen), and mutation checks (booleans only)."""
    def test_checks(self):
        CH = p11.checks(X)
        for k in ('k11b_reproduced', 'v1_p9_ok', 'v0_fi_fr_ok', 'p3_ok', 'gstar_ok', 'se_fi_ok', 'p10_check_ok', 'thr_ok', 'p6_ok', 'all_ok'):
            self.assertTrue(CH[k], k)
        self.assertEqual(CH['gstar_n'], 21); self.assertEqual(CH['se_fi'], [49_734, 52_253, 41_406])

    def test_mutations(self):
        g0 = p11.G_FB_1A
        try:
            p11.G_FB_1A = g0 + 1; self.assertFalse(p11.check_p3(X)['FI_min']['ok'])
        finally: p11.G_FB_1A = g0
        L0 = p11.STALL_L
        try:
            p11.STALL_L = L0 // 2; self.assertFalse(p11.check_p6(X)['p6_ok'])
        finally: p11.STALL_L = L0
        sb = X.set_base                       # V0 (values already seen) in place of V1: the p9.json check must fail
        try:
            X.set_base = lambda name: sb('V0'); self.assertFalse(p11.check_v1_p9(X)['v1_p9_ok'])
        finally: del X.set_base; X.set_base('V1u')


class Pipeline(unittest.TestCase):
    def test_pipeline(self):
        """run_all, tables and write_outputs on the synthetic window and payees only."""
        wn0 = p9.WN
        try:
            p9.WN = dict(wn0, SYNW='synthetic')
            R = p11.run_all(X, pers=('SYNW',), payee_pers=('SYNW',), recipients=payees, thr_vs=(0.1,))
            self.assertEqual(set(R), set(p11.BASES)); self.assertEqual(X.base, 'V1u')
            for b in p11.BASES:
                B = R[b]
                self.assertEqual(set(B), {'p9cells', 'fi_named', 'gstar', 'fi_payees', 'w_named', 'stall_named', 'thresholds'})
                self.assertTrue(all('|SYNW|' in k for k in B['p9cells']))
                self.assertEqual(len(B['fi_named']), 6); self.assertEqual(len(B['thresholds']), len(p11.W_GRID) + 1)
                x = B['p9cells']['T01t|1|SYNW|lo']
                y = B['fi_named']['T01t|SYNW|lo']['pt|same']
                self.assertTrue(close(x['agg'], y['agg_fb']) and close(x['fi'], y['agg_fi']))
            CH = dict(k11b_reproduced=True, v1_p9_ok=True, v1_p9_maxdiff=0.0, v0_fi_fr_ok=True, p3_ok=True, gstar_ok=True, gstar_maxdiff=0.0,
                      se_fi=[49_734, 52_253, 41_406], p10_check_ok=True, thr_ok=True, p6_ok=True, all_ok=True)
            RES = dict(meta=p11.meta(X, CH), bases=R)
            txt = p11.tables(RES)
            for s in ('## 1. (c)', '## 2. (a)', '## 3. (b)', 'synthetic', 'SynE', 'own_bind_b', 'batch', 'P10 threshold', 'stall'):
                self.assertIn(s, txt)
            with tempfile.TemporaryDirectory() as td:
                p11.write_outputs(RES, Path(td))
                sums = (Path(td) / 'SHA256SUMS.txt').read_text(encoding='ascii').split('\n')
                for line, f in zip(sums, ('p11.json', 'p11_tables.md')):
                    self.assertEqual(line, '%s  %s' % (hashlib.sha256((Path(td) / f).read_bytes()).hexdigest(), f))
        finally:
            p9.WN = wn0; X.set_base('V1u')


if __name__ == '__main__':
    unittest.main(verbosity=2)
