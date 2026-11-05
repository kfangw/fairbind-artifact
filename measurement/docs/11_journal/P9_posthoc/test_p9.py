#!/usr/bin/env python3
"""Tests of p9.py (calc-rules.md 7.8). Pure helpers on synthetic inputs; the real k11b namespace is loaded only to
check reproduction (V0, every V1 code path with the model's constants set back, the stage-1 REL_M machinery against
P4 base B and P3 (b), all of which are values already seen) and to run the variants on SYNTHETIC sellers (an
injected window 'SYNW'). No grid of real sellers is built under V1, V1t1, V2, V3 or V4. Output: pass / fail only.

    python3 -I test_p9.py
"""
import copy, hashlib, itertools, math, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import p9  # noqa: E402

ENV = None; REPRO = None
W = 0.00173
NEP = 21 * 144


def setUpModule():
    global ENV, REPRO
    g, REPRO = p9.load_k11b('k11b_p9_test')
    ENV = p9.Env(g)
    g['PDAYS']['SYNW'] = 21
    orig = g['t13_sellers']
    g['t13_sellers'] = lambda st, p, V: synthetic(st, V) if p == 'SYNW' else orig(st, p, V)


def S(a, R, n, ns, E1, m1, tier0=False, cnt=None):
    return dict(a=a, base=a, R=float(R), n=n, ns=float(ns), E1=E1, m1=m1, cnt=cnt, tier0=tier0, rs=0.25)


def syn_counts():
    """Per-profile-epoch counts of SynE: epochs above 256 (one above 512) and small ones, at fixed positions."""
    c = np.zeros(NEP)
    for e, m in ((3, 300), (4, 20), (40, 600), (41, 255), (42, 2), (700, 257), (701, 1), (2000, 90), (2001, 170)):
        c[e] = m
    return c


def synthetic(kind, V):
    """Synthetic sellers (as P4, plus SynE with per-epoch counts). SynD (400 sales in its busiest epoch) and SynE take
    the release unit branch and several anchor units; SynC (3 per epoch) stays in the one-call branch."""
    f = 1.0 if V == 1.0 else 5.0
    if kind == 'T01t':
        c = syn_counts()
        L = [S('StableEnrich(syn)', 120.0, 6_000, 210.0, 1_500, 12), S('SynB', 25.0, 3_000, 14.0, 800, 8, tier0=True),
             S('SynC', 0.9, 80, 1.5, 60, 3), S('SynD', 400.0, 40_000, 900.0, 900, 400),
             S('SynE', 30.0, int(c.sum()), 40.0, int((c > 0).sum()), int(c.max()), cnt=c)]
    elif kind == 'BR':
        L = [S('SynT', 900.0, 90_000, 1_800.0, 3_000, 60)]
    else:
        return []
    for s in L: s['ns'] = min(float(s['n']), s['ns'] * f)
    return L


def close(a, b, rel=1e-12, ab=1e-18):
    a = np.asarray(a, float); b = np.asarray(b, float)
    return bool(np.all(np.abs(a - b) <= ab + rel * np.maximum(np.abs(a), np.abs(b))))


CASES = [(st, V, lab) for st in ('T01t:SYNW', 'BR:SYNW') for V in p9.VS for lab in p9.LABS]
VAR_FLAGS = {v: d for v, d in p9.VARIANTS.items()}


def build(var, st, V, lab, **kw):
    ENV.set_variant(var, **kw); gr = ENV.fb(st, V, lab)
    frz, ded = gr.loss(W)
    return gr, dict(gr.c0parts, frozen=frz, deduct=ded, capital=gr.cap(0.10))


# ---------------------------------------------------------------- brute force per epoch (independent of p9's sums)
def rel_epoch(m, closed, par):
    if m <= 0: return 0.0
    if m <= par['N']: return par['F1'] + par['M1'] * m + par['K'] * closed
    return par['FU'] * math.ceil(m / par['N']) + par['FC'] + par['MU'] * m + par['K'] * closed


def anc_epoch(m, sg, par):
    if m <= 0: return 0.0
    mix = lambda d: (1 - sg) * d[0] + sg * d[1]
    u = math.ceil(m / par['N'])
    return (u - 1) * mix(par['FU']) + (m - 1) * mix(par['MU']) + mix(par['FC']) + mix(par['MC']) * min(m, 256)


def fake_grid(sellers, k_rows, E, up=False, cap=None, sig=1.0):
    S_ = [dict(s) for s in sellers]
    n = np.array([float(s['n']) for s in S_]); ns = np.array([float(s['ns']) for s in S_])
    prm = SimpleNamespace(up=up, curpe=True, sig=sig, pe=True, mode='k10d', a=0.0, rd='ledger')
    return SimpleNamespace(S=S_, N=len(S_), n=n, ns=ns, E=np.asarray(E, float), prm=prm, kind='T01t',
                           capR=np.full(len(S_), 5_000.0 if cap is None else cap))


# ================================================================== pure helpers and sources
class Pure(unittest.TestCase):
    def test_cl_bill_meas(self):
        self.assertEqual(p9.cl_bill_meas(1), 165_162); self.assertEqual(p9.cl_bill_meas(2), 170_701)
        self.assertEqual(p9.MEAS['CL_BILL'], 170_701)
        self.assertLess(abs(p9.cl_bill_meas(1) / 165_000 - 1), 0.005); self.assertLess(abs(p9.cl_bill_meas(2) / 171_000 - 1), 0.005)
        self.assertEqual(p9.cl_bill_meas(2) - p9.cl_bill_meas(1), p9.CL_BILL_FIT[1])
        self.assertEqual(p9.cl_bill_meas(2, fit=(10, 1), cb_ref=5, cb_min=2), 15)

    def test_variant_values_synthetic(self):
        model = dict(CL_REQ=100, CL_BILL=200); meas = dict(CL_REQ=150, CL_BILL=230)
        vv = lambda **kw: p9.variant_values(model, meas=meas, **kw)
        for rel, vrf, anc in itertools.product((False, True), repeat=3):
            d = vv(rel=rel, vrf=vrf, anc=anc)
            self.assertEqual(d, dict(CL_REQ=150 if vrf else 100, CL_BILL=230 if vrf else 200, lower_rnd='cl' if vrf else 'ecvrf',
                                     rel='meas' if rel else None, anc='meas' if anc else None))
        sb = p9.setback_values(model)
        self.assertEqual(sb, dict(model, lower_rnd='ecvrf', rel='model', anc='model'))
        d = p9.variant_values(p9.MODEL, True, True, True, tries=1)
        self.assertEqual((d['CL_REQ'], d['CL_BILL'], d['rel'], d['anc']), (151_629, 165_162, 'meas', 'meas'))
        self.assertEqual(model, dict(CL_REQ=100, CL_BILL=200))                    # inputs not mutated

    def test_variants_table(self):
        vv = {v: p9.variant_values(p9.MODEL, **d) for v, d in p9.VARIANTS.items()}
        self.assertEqual(vv['V0'], dict(p9.MODEL, lower_rnd='ecvrf', rel=None, anc=None))
        self.assertEqual(vv['V1'], dict(CL_REQ=151_629, CL_BILL=170_701, lower_rnd='cl', rel='meas', anc='meas'))
        self.assertEqual(vv['V2'], dict(CL_REQ=151_629, CL_BILL=170_701, lower_rnd='cl', rel=None, anc=None))
        self.assertEqual(vv['V3'], dict(p9.MODEL, lower_rnd='ecvrf', rel='meas', anc=None))
        self.assertEqual(vv['V4'], dict(p9.MODEL, lower_rnd='ecvrf', rel=None, anc='meas'))
        self.assertEqual(vv['V1t1'], dict(vv['V1'], CL_BILL=165_162))
        self.assertEqual(set(p9.MAIN_VARS), set(p9.VARIANTS) - {'V1t1'})

    def test_measured_constants(self):
        r = p9.REL_MEAS
        self.assertEqual((r['N'], r['F1'], r['M1'], r['FU'], r['MU'], r['FC'], r['K']),
                         (256.0, 75_331, 16_920, 73_697 + 57_491, 9_888 + 12_965, 69_391, -876))
        a = p9.ANC_MEAS
        self.assertEqual((a['N'], a['FU'], a['MU'], a['MC'], a['FL']),
                         (256.0, {0: 279_842, 1: 260_025}, {0: 16_784, 1: 28_126}, {0: 5_135, 1: 5_135}, None))
        self.assertEqual(a['FC'], {0: 288_468, 1: 288_468 + 28_126 - 16_784})

    def test_source_lines(self):
        """Each measured value appears on the source line cited in calc-rules.md 1 and 7."""
        def line(path, i): return path.read_text(encoding='utf-8').split('\n')[i - 1]
        J = p9.J
        if (J / 'SDK' / 'k-multiple_implementation.md').exists(): self.assertIn('16,800', line(J / 'SDK' / 'k-multiple_implementation.md', 164))
        log = J / 'VRF' / 'run-logs' / 'fork_isolate.log'
        self.assertIn('requestSample tx gas (real coordinator): 151629', line(log, 7))
        self.assertIn('callback included): 156468', line(log, 128))
        self.assertIn('[36998] SampledSettlement::fallback', line(log, 258))
        self.assertIn('hash-to-curve tries: 1', line(log, 130))
        self.assertIn('L1 fee in the payment (wei): 4321371668', line(log, 132))
        self.assertIn('billed gas of the fulfillment: 0', line(log, 129))
        if (J / 'G10_gas' / 'G10d_gas.md').exists(): self.assertIn('6,812', line(J / 'G10_gas' / 'G10d_gas.md', 150))
        rf = p9.REL_FIT
        for i, s in ((4, 'check '), (5, 'fixed 73697, per sale 9888.3'), (13, 'payunit'), (14, 'fixed 57491, per sale 12964.7'),
                     (19, 'inline '), (20, 'fixed 75331, per sale 16920.2'), (22, 'inline_proven'), (23, 'fixed 76299, per sale 16044.1'),
                     (25, 'pass '), (26, 'fixed 69391, per sale 0.0')):
            self.assertIn(s, line(rf, i), i)
        af = p9.ANC_FIT
        for i, s in ((6, 'chunk_accepted'), (7, 'fixed 58975, per record 11557.4'), (9, 'chunk_marked'), (10, 'fixed 50624, per record 15711.4'),
                     (12, 'chunk_plain'), (13, 'fixed 41128, per record 5134.9'), (15, 'complete_accepted'), (16, 'fixed 308017, per record 11556.8'),
                     (18, 'complete_marked'), (19, 'fixed 296283, per record 15710.7'), (21, 'complete_plain'), (22, 'fixed 288468, per record 5135.0'),
                     (24, 'pullsale_accepted'), (25, 'mean 69344'), (27, 'pullsale_marked'), (28, 'mean 64346'),
                     (30, 'unit_accepted'), (31, 'fixed 260025, per record 28125.8'), (33, 'unit_marked'), (34, 'fixed 286824, per record 19633.5'),
                     (36, 'unit_plain'), (37, 'fixed 279842, per record 16783.8')):
            self.assertIn(s, line(af, i), i)
        rd = J / 'release-units' / 'README.md'
        for s in (('75,331', '16,920', '73,697 + 9,888', '57,491 + 12,965', '69,391', '7c571a8') if rd.exists() else ()):
            self.assertIn(s, line(rd, 27) + line(rd, 23), s)
        k = p9.K11 / 'k11b.py'
        self.assertIn('REL_M, REL_K = 2_930, 2_083', line(k, 184))
        self.assertIn("REL_F = {'pool': 105_742, 'ledger': 105_742 + 8_882}", line(k, 185))
        self.assertIn('CAP_GAS = {1: 924, 0: 1_564}', line(k, 191))
        self.assertIn('CL_BILL_FIT = (int(round(_b[1])), int(round(_b[0])))', line(k, 207))
        self.assertIn('CL_BILL = CL_BILL_EXP + CL_NEWSLOT', line(k, 214))
        self.assertIn('def anc_lin(sg, x):', line(k, 486)); self.assertIn('np.maximum(ex, fl)', line(k, 489))
        self.assertIn('def cap_anchor(prm):', line(k, 500))
        self.assertIn('capR = np.floor((TX_CAP - REL_F[prm.rd]) / (REL_M + REL_K', line(k, 539))
        self.assertIn("parts['anchor'] = prm.gusd(A * ag) / R", line(k, 602))
        self.assertIn("parts['sampvrf'] = Ep * prm.rand_usd() / R", line(k, 603))
        self.assertIn("parts['release'] = prm.gusd(Ru * REL_F[prm.rd] + REL_M * n[None, :] + REL_K * ns[None, :]) / R", line(k, 609))
        self.assertIn('dep = depth_of(self.capA)', line(k, 616))
        self.assertIn("d['G10B_M'] = M; d['G10B_F']", line(k, 699))
        self.assertIn("d['CL_REQ'] = gg(VRFC)", line(k, 702))
        self.assertIn('CL_REQ = 96_000', line(k, 215))
        self.assertIn('def cl_usd(self)', line(k, 283))

    def test_floor_never_binds_on_measured_calls(self):
        """EIP-7623: 10 gas per token, a nonzero byte is 4 tokens, so the floor is at most 40 gas per calldata byte
        plus 21,000. That bound is below the measured execution per leaf and per unit (and the release and pull
        calls carry under 100 bytes), so max(execution, floor) is the measured execution (calc-rules.md 7.3)."""
        for kind in ('plain', 'marked', 'accepted'):
            self.assertLess(p9.FLOOR_PER_BYTE * p9.LEAF_BYTES[kind], p9.ANC_UNIT[kind][1], kind)
            self.assertLess(p9.unit_floor_bound(0), min(p9.ANC_UNIT[kind][0], p9.ANC_COMPLETE[kind][0]), kind)
        self.assertEqual(p9.LEAF_BYTES['plain'], 32 + 8 * 32 + 32 + 32 + 32 + 32)
        self.assertEqual(p9.LEAF_BYTES['accepted'], p9.LEAF_BYTES['plain'] + 96)
        s_max = (min(f for f, _ in p9.ANC_UNIT.values()) - p9.unit_floor_bound(0)) // (32 * p9.FLOOR_PER_BYTE)
        self.assertGreater(s_max, 100)                                        # snapshot addresses needed to bind
        for f in (p9.REL1_F, p9.RELU_CHK[0], p9.RELU_PAY[0], p9.REL_CUR, min(f for f, _ in p9.ANC_CHUNK.values())):
            self.assertLess(21_000 + p9.FLOOR_PER_BYTE * 100, f)

    def test_release_formula_against_epochs(self):
        """rel_gas from per-epoch counts equals the per-epoch brute force, for both branches, every k."""
        c = syn_counts(); n = float(c.sum()); KS = ENV.g['KS']
        sel = [dict(n=n, ns=0.0, cnt=c, m1=int(c.max()))]
        for k in KS:
            m = np.bincount(np.arange(len(c)) // k, weights=c); m = m[m > 0]
            E = np.full((len(KS), 1), float(len(m)))
            for par in (dict(p9.REL_MEAS), dict(N=300.0, F1=7, M1=3, FU=11, MU=5, FC=2, K=0)):
                gr = fake_grid(sel, KS, E); gr.prm.up = False
                pr = dict(par, N=np.array([par['N']]))
                got = p9.rel_gas(ENV.g, gr, pr, np.array([0.0]))[KS.index(k), 0]
                want = sum(rel_epoch(x, 0.0, par) for x in m)
                self.assertTrue(close(got, want, rel=1e-12), (k, par['N'], got, want))
        # closed cases enter at K each; the upper case with curpe uses the k = 1 grouping for every k
        gr = fake_grid(sel, KS, np.full((len(KS), 1), 9.0)); gr.prm.up = True
        out = p9.rel_gas(ENV.g, gr, dict(p9.REL_MEAS, N=np.array([256.0])), np.array([10.0]))
        self.assertTrue(np.all(out == out[0]))
        gr.prm.up = False
        out2 = p9.rel_gas(ENV.g, gr, dict(p9.REL_MEAS, N=np.array([256.0])), np.array([0.0]))
        self.assertTrue(close(out[0, 0] - out2[0, 0], 10 * p9.REL_K_MEAS))

    def test_release_bound_covers_every_arrangement(self):
        """Without per-epoch counts, rel_gas (measured) is at least the brute force of any arrangement of n sales in
        E seller epochs of at most min(k m1, n) sales, and equals it when min(k m1, n) <= 256."""
        rng = np.random.default_rng(7); par = dict(p9.REL_MEAS); KS = ENV.g['KS']
        for trial in range(300):
            k = int(rng.choice(KS)); E = int(rng.integers(1, 12)); cap_m = int(rng.integers(1, 800))
            m = rng.integers(1, cap_m + 1, size=E); n = int(m.sum())
            m1 = int(math.ceil(m.max() / k)) if trial % 2 else int(m.max())       # profile-epoch maximum, k m1 >= m.max()
            if k * m1 < m.max(): m1 = int(math.ceil(m.max() / k))
            gr = fake_grid([dict(n=n, ns=0.0, cnt=None, m1=m1)], KS, np.full((len(KS), 1), float(E))); gr.prm.up = False
            got = p9.rel_gas(ENV.g, gr, dict(par, N=np.array([256.0])), np.array([0.0]))[KS.index(k), 0]
            want = sum(rel_epoch(int(x), 0.0, par) for x in m)
            self.assertGreaterEqual(got, want - 1e-6, (trial, k, E, m1, list(m)))
            if min(k * m1, n) <= 256: self.assertTrue(close(got, want), (trial, got, want))

    def test_anchor_formula_against_epochs(self):
        """anc_gas from per-epoch counts equals the per-epoch brute force (units of 256, completing unit and first
        pull), for sigma 0, 1 and between, with Ua from k11b's splits at the unit cap."""
        c = syn_counts(); n = float(c.sum()); m = c[c > 0]
        for sg in (0.0, 0.3, 1.0):
            Ua0 = ENV.g['splits_from_counts'](c, 1, 256.0)
            gr = fake_grid([dict(n=n, ns=0.0, cnt=c, m1=int(c.max()))], ENV.g['KS'], np.full((6, 1), float(len(m))), sig=sg)
            gr.Ua = np.full((6, 1), Ua0)
            ag, fb = p9.anc_gas(ENV.g, gr, p9.ANC_MEAS)
            want = sum(anc_epoch(int(x), sg, p9.ANC_MEAS) for x in m)
            self.assertTrue(close(ag, want), (sg, ag[0, 0], want)); self.assertFalse(fb.any())
        self.assertEqual(Ua0, sum(math.ceil(x / 256) - 1 for x in m))

    def test_setback_formulas_are_k11b(self):
        """With the model's constants the measured code gives k11b's formulas: release Ru REL_F + REL_M n + REL_K ns
        with Ru = E + splits at capR; anchor A max(F + M x, FL_F + FL_M x) with x = n / A."""
        g = ENV.g; c = syn_counts(); n = float(c.sum()); KS = g['KS']
        sel = [dict(n=n, ns=37.0, cnt=c, m1=int(c.max()))]
        for cap in (200.0, 256.0, 5_686.0):
            E = np.array([[float(len(np.bincount(np.arange(len(c)) // k, weights=c).nonzero()[0]))] for k in KS])
            gr = fake_grid(sel, KS, E, cap=cap); gr.prm.up = False
            par = p9.rel_params(g, gr, 'model')
            got = p9.rel_gas(g, gr, par, gr.ns)
            Ur = np.array([[g['splits_from_counts'](c, k, cap)] for k in KS])
            want = (E + Ur) * g['REL_F']['ledger'] + g['REL_M'] * n + g['REL_K'] * 37.0
            self.assertTrue(close(got, want), cap)
        for sg in (0.0, 1.0):
            A_ex = g['splits_from_counts'](c, 1, 924.0); E0 = float((c > 0).sum())
            gr = fake_grid(sel, KS, np.full((6, 1), E0), sig=sg); gr.Ua = np.full((6, 1), A_ex)
            ag, _ = p9.anc_gas(g, gr, p9.anc_params(g, 'model'))
            A = E0 + A_ex; mod, _ = g['anc_lin'](sg, np.array([n / A]))
            self.assertTrue(close(ag[0, 0], A * mod[0], rel=1e-12), sg)


# ================================================================== real namespace: reproduction and structure only
class Reproduction(unittest.TestCase):
    def test_k11b_bytes(self): self.assertTrue(REPRO)

    def test_model_values(self):
        g = ENV.g
        self.assertEqual(ENV.model, p9.MODEL)
        self.assertEqual(g['CL_BILL'], g['CL_BILL_EXP'] + g['CL_NEWSLOT']); self.assertEqual(g['CL_NEWSLOT'], 17_129)
        self.assertEqual(g['CL_L1_CHARGED'], 4_321_371_668)          # the kept L1 charge equals the fork log's (132 (line))
        self.assertEqual(g['CL_PREM'], 1.60)
        self.assertEqual((g['REL_F']['ledger'], g['REL_M'], g['REL_K']), (114_624, 2_930, 2_083))
        self.assertEqual(g['CAP_GAS'], {1: 924, 0: 1_564})
        self.assertEqual((round(g['G10B_F'][1]), round(g['G10B_M'][1], 3)), (189_907, 21_649.375))   # active after set_gas('new')
        self.assertEqual((round(g['G10B_F'][0], 3), round(g['G10B_M'][0], 3)), (190_538.333, 12_953.333))
        p = g['LOm']('N'); self.assertEqual((p.sig, p.a, p.pe, p.cap, p.anc), (1.0, 0.0, True, 'gas', 'lin'))

    def test_only_intended_names_change(self):
        g = ENV.g
        def ok(v, d=0):
            if isinstance(v, (bool, int, float, str)): return True
            if d > 3: return False
            if isinstance(v, (tuple, list)): return len(v) <= 64 and all(ok(x, d + 1) for x in v)
            if isinstance(v, dict): return len(v) <= 64 and all(ok(x, d + 1) for x in v.values())
            return False
        def plain(): return {n: copy.deepcopy(v) for n, v in g.items() if not n.startswith('_') and n != 'out' and ok(v)}
        ENV.reset(); before = plain(); p_lo, p_up, p_fac = (ENV.prm(l) for l in p9.LABS)
        for v, fl in VAR_FLAGS.items():
            ENV.set_variant(v); after = plain()
            changed = {n for n in before if before[n] != after.get(n)}
            self.assertEqual(changed, {'CL_REQ', 'CL_BILL'} if fl['vrf'] else set(), v)
            self.assertEqual((ENV.rel, ENV.anc), ('meas' if fl['rel'] else None, 'meas' if fl['anc'] else None), v)
            q_lo, q_up, q_fac = (ENV.prm(l) for l in p9.LABS)
            self.assertEqual(q_up.key, p_up.key, v)                                  # the upper case keeps its own path
            for a, b in ((p_lo, q_lo), (p_fac, q_fac)):
                da = dict(a.key); db = dict(b.key)
                self.assertEqual({k for k in da if da[k] != db[k]}, {'rnd'} if fl['vrf'] else set(), v)
            self.assertEqual(g['cap_anchor'](p_lo), 256.0 if fl['anc'] else 924.0, v)
        ENV.reset(); self.assertEqual(plain(), before); self.assertEqual((ENV.lower_rnd, ENV.rel, ENV.anc), ('ecvrf', None, None))

    def test_table4_v0(self):
        ENV.reset(); t = p9.table4_check(ENV)
        self.assertEqual(len(t), 21); self.assertTrue(all(v['ok'] for v in t.values()), [k for k, v in t.items() if not v['ok']])

    def test_table4_with_model_constants_in_every_v1_path(self):
        ENV.set_values(p9.setback_values(ENV.model)); t = p9.table4_check(ENV); ENV.reset()
        self.assertTrue(all(v['ok'] for v in t.values()), [k for k, v in t.items() if not v['ok']])

    def test_v0_fi_fr_reproduce_p3_k14(self):
        r = p9.repro_v0(ENV); self.assertTrue(r['fi_ok'] and r['fr_ok'], r)

    def test_stage1_machinery_reproduces_p4_base_b(self):
        r = p9.repro_p4b(ENV)
        self.assertTrue(r['p4b_ok'], {k: r[k] for k in ('p4b_maxdiff', 'p4b_kdiff', 'p4b_cells')})
        self.assertEqual(r['p4b_cells'], 36 - len(r['p4b_missing']))
        self.assertEqual((ENV.var, ENV.g['REL_M']), ('V0', 2_930))


# ================================================================== synthetic sellers
class Synthetic(unittest.TestCase):
    def test_v0_is_unmodified_grid(self):
        ENV.reset(); orig_c0 = ENV._orig[0]
        for st, V, lab in CASES:
            a = ENV.fb(st, V, lab)
            self.assertEqual(a.capA, ENV._orig[1](a.prm))
            parts = orig_c0(a)
            for t in parts: self.assertTrue(np.array_equal(parts[t], a.c0parts[t]), (st, V, lab, t))

    def test_setback_equals_v0_on_synthetic(self):
        for st, V, lab in CASES:
            g0, t0 = build('V0', st, V, lab)
            ENV.set_values(p9.setback_values(ENV.model)); g1 = ENV.fb(st, V, lab); frz, ded = g1.loss(W)
            t1 = dict(g1.c0parts, frozen=frz, deduct=ded, capital=g1.cap(0.10))
            for t in t0: self.assertTrue(close(t0[t], t1[t], rel=1e-12), (st, V, lab, t))
            self.assertTrue(np.array_equal(g0.opt(W)['ki'], g1.opt(W)['ki']))
        ENV.reset()

    def test_v2_moves_only_the_sample_term(self):
        g = ENV.g
        for st, V, lab in CASES:
            g0, t0 = build('V0', st, V, lab)
            g2, t2 = build('V2', st, V, lab)
            pr = g2.prm
            cl = pr.gusd(151_629) + pr.wusd(g['W_REQ']) + 1.60 * (pr.gusd(170_701) + pr.wusd(g['CL_L1_CHARGED']))
            self.assertTrue(close(t2['sampvrf'], g2.Ep * cl / g2.R), (st, V, lab))
            if lab == 'up':
                d = pr.gusd(151_629 - 119_160) + 1.60 * pr.gusd(170_701 - 157_644)
                self.assertTrue(close(t2['sampvrf'] - t0['sampvrf'], g0.Ep * d / g0.R, rel=1e-9), (st, V))
            else:
                ec = g0.prm.gusd(g['G_REQ'] + g['G_VRF_EXP']) + g0.prm.wusd(g['W_REQ'] + g['W_VRF'])
                self.assertTrue(close(t0['sampvrf'], g0.Ep * ec / g0.R), (st, V, lab))
            self.assertTrue(np.all(t2['sampvrf'] > t0['sampvrf']))
            for t in t0:
                if t != 'sampvrf': self.assertTrue(np.array_equal(t0[t], t2[t]), (st, V, lab, t))
        ENV.reset()

    def test_v3_moves_only_release(self):
        g = ENV.g; branches = set()
        for st, V, lab in CASES:
            g0, t0 = build('V0', st, V, lab)
            g3, t3 = build('V3', st, V, lab)
            want = g3.prm.gusd(p9.rel_gas(g, g3, dict(p9.REL_MEAS, N=np.full(g3.N, 256.0)), g3.ns)) / g3.R
            self.assertTrue(close(t3['release'], want), (st, V, lab))
            for t in t0:
                if t != 'release': self.assertTrue(np.array_equal(t0[t], t3[t]), (st, V, lab, t))
            for j, s in enumerate(g3.S):
                branches.add((s['cnt'] is not None, min(s['m1'], s['n']) > 256))
            if lab == 'lo' and V == 1.0 and st.startswith('T01t'):     # SynC: one call per seller epoch at k = 1
                j = g3.a_.index('SynC')
                one = g3.prm.gusd(75_331 * g3.E[0, j] + 16_920 * g3.n[j] - 876 * g3.ns[j]) / g3.R[j]
                self.assertTrue(close(t3['release'][0, j], one))
        ENV.reset()
        self.assertTrue({(True, True), (False, True), (False, False)} <= branches, branches)

    def test_v4_moves_anchor_l1_and_depth_only(self):
        g = ENV.g
        for st, V, lab in CASES:
            g0, t0 = build('V0', st, V, lab)
            g4, t4 = build('V4', st, V, lab)
            self.assertEqual((g0.capA, g4.capA), (924.0, 256.0))
            self.assertTrue(np.all(g4.Ua[0] >= g0.Ua[0]))
            ag, _ = p9.anc_gas(g, g4, p9.ANC_MEAS)
            self.assertTrue(close(t4['anchor'], g4.prm.gusd(ag) / g4.R), (st, V, lab))
            self.assertTrue(np.all(t4['anchor'] > t0['anchor']), (st, V, lab))
            dA = (g4.Ua[0] - g0.Ua[0])[None, :] * g4.prm.wusd(g['L1W_F'][1]) / g4.R           # sigma 1: extra anchor txs
            self.assertTrue(close(t4['l1'] - t0['l1'], np.broadcast_to(dA, t0['l1'].shape), rel=1e-9, ab=1e-15), (st, V, lab))
            if lab == 'up':
                d = g0.prm.gusd((10 - 8) * g['G_LVL'] * g0.ns) / g0.R                            # depth 10 -> 8
                self.assertTrue(close(t0['detincl'] - t4['detincl'], np.broadcast_to(d, t0['detincl'].shape), rel=1e-9))
            for t in t0:
                if t not in ('anchor', 'l1', 'detincl'): self.assertTrue(np.array_equal(t0[t], t4[t]), (st, V, lab, t))
        ENV.reset()

    def test_v1_is_v2_plus_v3_plus_v4(self):
        r = p9.additivity(ENV, pers=('SYNW',))
        self.assertLessEqual(r['max_rel'], 1e-12, r); self.assertEqual(r['other_terms_changed'], [])
        self.assertGreater(r['cells'], 0); self.assertGreater(r['anchor_units_changed'], 0)
        for st, V, lab in CASES:
            a = {v: build(v, st, V, lab)[0].opt(W)['agg'] for v in p9.MAIN_VARS + ('V1t1',)}
            self.assertTrue(a['V0'] < a['V2'] and a['V1t1'] <= a['V1'], (st, V, lab))
        ENV.reset()

    def test_path_switch_with_model_constants(self):
        """The lower-path switch alone (model constants) changes only the lower and facilitator sample term, from the
        ECVRF price to the model's Chainlink price; the upper case is untouched."""
        for st, V, lab in CASES:
            g0, t0 = build('V0', st, V, lab)
            ENV.set_values(p9.variant_values(ENV.model, False, True, False, meas=dict(ENV.model), switch_path=True))
            g1 = ENV.fb(st, V, lab); frz, ded = g1.loss(W); t1 = dict(g1.c0parts, frozen=frz, deduct=ded, capital=g1.cap(0.10))
            for t in t0:
                if t != 'sampvrf' or lab == 'up': self.assertTrue(np.array_equal(t0[t], t1[t]), (st, V, lab, t))
            if lab != 'up': self.assertTrue(close(t1['sampvrf'], g1.Ep * g1.prm.cl_usd() / g1.R))
        ENV.reset()

    def test_fi_gets_the_release_change_only(self):
        g = ENV.g
        for st in ('T01t:SYNW', 'BR:SYNW'):
            for lab in p9.LABS:
                f = {}
                for v in p9.MAIN_VARS:
                    ENV.set_variant(v); f[v] = ENV.fi(st, lab)
                self.assertTrue(np.array_equal(f['V0'].total(W), f['V2'].total(W)), (st, lab))
                self.assertTrue(np.array_equal(f['V0'].total(W), f['V4'].total(W)), (st, lab))
                self.assertTrue(np.array_equal(f['V1'].total(W), f['V3'].total(W)), (st, lab))
                self.assertNotIn('sampvrf', f['V1'].c0parts); self.assertNotIn('anchor', f['V1'].c0parts)
                fi = f['V3']; want = fi.prm.gusd(p9.rel_gas(g, fi, dict(p9.REL_MEAS, N=np.full(fi.N, 256.0)), fi.n)) / fi.R
                self.assertTrue(close(fi.c0parts['release'], want), (st, lab))         # every sale a closed case
                for t in fi.c0parts:
                    if t != 'release': self.assertTrue(np.array_equal(fi.c0parts[t], f['V0'].c0parts[t]), (st, lab, t))
        ENV.reset()

    def test_fr_follows_the_variant(self):
        """On the synthetic window the K14 wrapper is bypassed, so FR is FairBind itself; this checks that GridFR is
        built with the variant's constants, lower path and release and anchor structure."""
        for v in p9.MAIN_VARS:
            ENV.set_variant(v)
            for var in p9.FR_VARS:
                a = ENV.fr('T01t:SYNW', 'lo', var); b = ENV.fb('T01t:SYNW', 1.0, 'lo')
                self.assertTrue(np.array_equal(a.total(W), b.total(W)), (v, var))
                self.assertEqual(a.prm.rnd, 'cl' if VAR_FLAGS[v]['vrf'] else 'ecvrf')
                self.assertEqual(a.capA, 256.0 if VAR_FLAGS[v]['anc'] else 924.0)
        ENV.reset()


class PipelineSmoke(unittest.TestCase):
    """run(), additivity(), tables() and write_outputs() on the synthetic window only (p9.PER replaced)."""
    def test_pipeline(self):
        per0, wn0 = p9.PER, p9.WN
        try:
            p9.PER = ('SYNW',); p9.WN = dict(wn0, SYNW='synthetic')
            V = p9.run(ENV)
            self.assertEqual(set(V), set(p9.VARIANTS)); self.assertEqual(ENV.var, 'V0')
            x = V['V1']['T01t|1|SYNW|lo']
            for k in ('agg', 'per', 'le10', 'fi', 'fi_per', 'fi_cheaper', 'agg_mix', 'fr', 'fr_above_fb', 'se'): self.assertIn(k, x)
            self.assertNotIn('fi', V['V1t1']['T01t|1|SYNW|lo'])
            self.assertEqual(len(V['V1']), 2 * 2 * 3)
            self.assertTrue(close(sum(t * r for t, _, r in x['per'].values()) / x['R'], x['agg']))
            self.assertEqual(V['V1']['T01t|1|SYNW|lo']['fi'], V['V3']['T01t|1|SYNW|lo']['fi'])
            self.assertEqual(V['V4']['T01t|1|SYNW|lo']['fi'], V['V0']['T01t|1|SYNW|lo']['fi'])
            g = ENV.g
            M = dict(k11b_reproduced=True, table4_ok=True, table4_back_ok=True, model=p9.MODEL, model_line=p9.MODEL_LINE, meas=p9.MEAS,
                     cl_bill_t1=p9.cl_bill_meas(1), repro=dict(fi_maxdiff=0.0, fr_maxdiff=0.0, p4b_maxdiff=0.0, p4b_kdiff=0),
                     release_meas=p9.REL_MEAS, anchor_meas={k: (v if not isinstance(v, dict) else {str(a): b for a, b in v.items()})
                                                            for k, v in p9.ANC_MEAS.items()},
                     model_anchor=dict(G10B_F={str(a): b for a, b in g['G10B_F'].items()}, G10B_M={str(a): b for a, b in g['G10B_M'].items()},
                                       CAP_GAS={str(a): b for a, b in g['CAP_GAS'].items()}),
                     model_release=dict(REL_F=g['REL_F']['ledger'], REL_M=g['REL_M'], REL_K=g['REL_K']),
                     additivity=p9.additivity(ENV))
            R = dict(meta=M, variants=V)
            txt = p9.tables(R)
            for s in ('## 1.', '## 2.', '## 3.', '## 4.', '## 5.', 'V1 all measured', 'V4 anchor only', 'synthetic', 'SynD', 'SynE', '75,331', '260,025'):
                self.assertIn(s, txt)
            with tempfile.TemporaryDirectory() as td:
                p9.write_outputs(R, Path(td))
                sums = (Path(td) / 'SHA256SUMS.txt').read_text(encoding='ascii').split('\n')
                for line, f in zip(sums, ('p9.json', 'p9_tables.md')):
                    self.assertEqual(line, '%s  %s' % (hashlib.sha256((Path(td) / f).read_bytes()).hexdigest(), f))
        finally:
            p9.PER, p9.WN = per0, wn0
            ENV.reset()


if __name__ == '__main__':
    unittest.main(verbosity=2)
