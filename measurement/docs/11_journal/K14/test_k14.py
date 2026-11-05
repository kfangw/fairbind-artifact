#!/usr/bin/env python3
"""Unit tests of k14.py on SYNTHETIC bins only. No real data is read: k11b.py is parsed (not executed) to take its
ns_group function, and the injection test uses a fake namespace.

    python3 -I test_k14.py
"""
import ast, math, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.dont_write_bytecode = True
import k14  # noqa: E402

INF = math.inf


def load_ns_group():
    """ns_group from K11/k11b.py, compiled alone from its AST (the rest of k11b.py is not run)."""
    src = (HERE.parent / 'K11' / 'k11b.py').read_text(encoding='utf-8')
    fn = [n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == 'ns_group']
    assert len(fn) == 1
    ns = {}
    exec(compile(ast.Module(body=fn, type_ignores=[]), 'k11b.py:ns_group', 'exec'), ns)
    return ns['ns_group']


NSG = load_ns_group()


def fb_ns(bins, V): return k14.fb_ns_from_bins(bins, V, NSG)


class OnePrice(unittest.TestCase):
    """(a) all sales at v = 0.01 in bin (0.001, 0.01]."""
    n, v = 1000, 0.01
    B = [(0.01, 1000, 1000 * 0.01)]

    def test_fb_is_n_v_over_V(self):
        for V in (1.0, 0.2):
            self.assertAlmostEqual(fb_ns(self.B, V), self.n * self.v / V, places=12)

    def test_fr_main_p_and_fewer_samples(self):
        for V in (1.0, 0.2):
            fr = k14.fr_seller(self.B, V)
            self.assertEqual(fr['v_main'], 0.01)
            self.assertAlmostEqual(fr['p_main'], 0.01 / (V + 0.01), places=15)
            self.assertAlmostEqual(fr['ns']['main'], self.n * 0.01 / (V + 0.01), places=12)
            self.assertLess(fr['ns']['main'], fb_ns(self.B, V))            # FR draws fewer: v/(V+v) < v/V
            self.assertAlmostEqual(fr['ns']['main'] / fb_ns(self.B, V), V / (V + 0.01), places=12)

    def test_lo_equals_main_when_price_is_edge(self):
        fr = k14.fr_seller(self.B, 1.0)
        self.assertAlmostEqual(fr['v_lo'], 0.01, places=15)
        self.assertAlmostEqual(fr['ns']['lo'], fr['ns']['main'], places=12)

    def test_lo_below_main_when_price_inside_bin(self):
        B = [(0.01, 1000, 1000 * 0.004)]                                    # all at 0.004
        fr = k14.fr_seller(B, 1.0)
        self.assertAlmostEqual(fr['v_lo'], 0.004, places=15)
        self.assertAlmostEqual(fr['p_lo'], 0.004 / 1.004, places=15)
        self.assertLess(fr['ns']['lo'], fr['ns']['main'])
        self.assertAlmostEqual(fb_ns(B, 1.0), 4.0, places=12)
        self.assertAlmostEqual(fr['ns']['lo'] / fb_ns(B, 1.0), 1 / 1.004, places=12)


class TwoPrice(unittest.TestCase):
    """(b) 900 sales at 0.001 and 100 sales at 0.5: FR must sample everything at the top rate, so ratio > 1."""
    B = [(0.001, 900, 0.9), (0.5, 100, 50.0)]

    def test_ratio_above_one(self):
        V = 1.0
        fb = fb_ns(self.B, V)
        self.assertAlmostEqual(fb, 0.9 + 50.0, places=12)
        fr = k14.fr_seller(self.B, V)
        self.assertEqual(fr['v_main'], 0.5)
        self.assertAlmostEqual(fr['p_main'], 0.5 / 1.5, places=15)
        self.assertAlmostEqual(fr['ns']['main'], 1000 / 3, places=10)
        self.assertGreater(fr['ns']['main'] / fb, 1.25)
        self.assertAlmostEqual(fr['ns']['main'] / fb, (1000 / 3) / 50.9, places=12)
        self.assertAlmostEqual(fr['v_lo'], 0.5, places=15)                  # mean of the top bin

    def test_v02_top_bin_above_V(self):
        V = 0.2                                                              # bin (0.2, 0.5] lies above V
        fb = fb_ns(self.B, V)
        self.assertAlmostEqual(fb, 0.9 / 0.2 + 100, places=10)              # ns_group: u/V for <=V, c for >=V
        fr = k14.fr_seller(self.B, V)
        self.assertAlmostEqual(fr['ns']['main'], 1000 * 0.5 / 0.7, places=10)
        self.assertAlmostEqual(fr['ns']['eq'], 1000.0, places=12)           # min(1, 0.5/0.2) = 1
        # hyb: 100 above V always sampled, 900 at p = 0.001 / 1.001
        self.assertAlmostEqual(fr['ns']['hyb'], 100 + 900 * 0.001 / 0.201, places=10)

    def test_top_bin_mean_inside(self):
        B = [(0.001, 900, 0.9), (0.5, 100, 30.0)]                           # top bin mean 0.3
        fr = k14.fr_seller(B, 1.0)
        self.assertAlmostEqual(fr['v_lo'], 0.3, places=15)
        self.assertAlmostEqual(fr['ns']['lo'], 1000 * 0.3 / 1.3, places=10)
        self.assertLess(fr['ns']['lo'], fr['ns']['main'])


class InfBin(unittest.TestCase):
    """(c) a sale above 5 USDC: FR main p = 1."""
    B = [(0.01, 10, 0.1), (INF, 2, 20.0)]

    def test_inf(self):
        fr = k14.fr_seller(self.B, 1.0)
        self.assertEqual(fr['v_main'], INF)
        self.assertEqual(fr['p_main'], 1.0)
        self.assertEqual(fr['ns']['main'], 12.0)
        self.assertEqual(fr['p_eq'], 1.0)
        self.assertAlmostEqual(fr['v_lo'], 10.0)                             # FR-lo: mean of the inf bin, finite
        self.assertAlmostEqual(fr['p_lo'], 10.0 / 11.0)
        self.assertEqual(fr['n_gtV'], 2.0)
        self.assertAlmostEqual(fr['ns']['hyb'], 2 + 10 * 0.01 / 1.01, places=12)
        self.assertAlmostEqual(fb_ns(self.B, 1.0), 0.1 + 2, places=12)
        self.assertEqual(k14.p_fixed(INF, 0.2), 1.0)


class EqAndHyb(unittest.TestCase):
    def test_eq_equals_fb_one_price_at_edge(self):
        """(d) one price v equal to the bin's upper edge: FR-eq p = v/V, so n_s^FR-eq = n v / V = FB n_s."""
        for up, V in ((0.01, 1.0), (0.1, 1.0), (0.1, 0.2), (0.2, 0.2), (1.0, 1.0)):
            B = [(up, 77, 77 * up)]
            fr = k14.fr_seller(B, V)
            self.assertAlmostEqual(fr['ns']['eq'], fb_ns(B, V), places=10, msg=(up, V))

    def test_hyb_equals_main_without_sales_above_V(self):
        B = [(0.001, 50, 0.04), (0.1, 20, 1.2), (0.5, 5, 1.5)]
        fr = k14.fr_seller(B, 1.0)
        self.assertEqual(fr['n_gtV'], 0.0)
        self.assertEqual(fr['ns']['hyb'], fr['ns']['main'])

    def test_straddle_raises(self):
        with self.assertRaises(ValueError):
            k14.split_at_V([(0.5, 3, 1.0)], 0.3)


class Bins(unittest.TestCase):
    def test_empty_bins_ignored_for_top(self):
        B = [(0.01, 4, 0.03), (0.5, 0, 0.0)]
        self.assertEqual(k14.vhat_from_bins(B)[0], 0.01)

    def test_no_sales(self):
        fr = k14.fr_seller([], 1.0)
        self.assertEqual(fr['n'], 0.0)
        self.assertEqual(fr['ns'], dict(main=0.0, lo=0.0, eq=0.0, hyb=0.0))

    def test_entry_bins_partial_sets(self):
        val = {('w', 'S'): [(0.001, 1, 0.001), (0.01, 2, 0.02), (0.5, 3, 1.2), (1.0, 4, 3.6), (INF, 1, 9.0)]}
        self.assertEqual(len(k14.entry_bins(val, 'w', 'S', None)), 5)
        self.assertEqual([b[0] for b in k14.entry_bins(val, 'w', 'S', 0.5)], [0.001, 0.01, 0.5])
        self.assertEqual([b[0] for b in k14.entry_bins(val, 'w', 'S', 0.001)], [0.001])
        self.assertEqual([b[0] for b in k14.entry_bins(val, 'w', 'S', 0.01)], [0.001, 0.01])
        self.assertEqual(k14.entry_bins(val, 'x', 'S', None), [])
        # partial set drops the top bins, so v^ comes from the partial set only
        self.assertEqual(k14.vhat_from_bins(k14.entry_bins(val, 'w', 'S', 0.5))[0], 0.5)

    def test_lower_edge(self):
        self.assertEqual(k14.lower_edge(0.01), 0.001)
        self.assertEqual(k14.lower_edge(INF), 5.0)
        self.assertEqual(k14.lower_edge(0.001), 0.0)


class Judgments(unittest.TestCase):
    """(e) judgment functions on hand-made aggregates."""
    def test_a(self):
        self.assertTrue(k14.judge_a([1.30, 1.20, 1.26])['holds'])
        self.assertEqual(k14.judge_a([1.30, 1.20, 1.26])['windows'], 2)
        self.assertTrue(k14.judge_a([1.25, 1.25, 1.0])['holds'])                 # >= 1.25 counts
        self.assertFalse(k14.judge_a([1.2499999, 1.25, 1.0])['holds'])
        self.assertFalse(k14.judge_a([2.0, 1.0, 0.9])['holds'])                  # one window is not enough
        self.assertTrue(k14.judge_a([2.0, 3.0, 4.0])['holds'])

    def test_b(self):
        self.assertTrue(k14.judge_b([0.0025, 0.0030, -0.01])['holds'])           # 0.25%p as a fraction of revenue
        self.assertFalse(k14.judge_b([0.0024999, 0.0030, 0.0])['holds'])
        self.assertFalse(k14.judge_b([0.10, -0.10, -0.10])['holds'])
        self.assertEqual(k14.judge_b([0.003, 0.003, 0.003])['windows'], 3)
        self.assertEqual(k14.TH_B, 0.0025)

    def test_c(self):
        W = ['busy', 'median', 'quiet']
        pw = {'busy': {'A': -0.001, 'B': 0.002, 'C': -0.1},
              'median': {'A': -0.0001, 'B': -0.002, 'C': 0.0},
              'quiet': {'A': -0.01, 'B': -0.002}}
        r = k14.judge_c(pw, W)
        self.assertEqual(r['sellers'], ['A'])                                    # B not in busy, C zero in median, C missing in quiet
        self.assertEqual(r['count'], 1); self.assertFalse(r['holds'])
        self.assertEqual(r['missing'], ['C'])
        r0 = k14.judge_c({w: {'A': 0.0, 'B': 0.01} for w in W}, W)
        self.assertEqual(r0['count'], 0); self.assertTrue(r0['holds'])

    def test_agg_cost(self):
        self.assertAlmostEqual(k14.agg_cost([0.1, 0.3], [3.0, 1.0]), 0.15)


class Injection(unittest.TestCase):
    """The t13_sellers wrap reaches Grid.__init__ through its module globals, as when k11b.py is exec'd in a dict."""
    SRC = '''
import math
inf = math.inf
EDGES = %r
def ns_group(c, u, lo_e, up_e, V, end='hi'):
    return u / V if up_e <= V else float(c)
VAL = {('w', 'One'): [(0.01, 100, 1.0)], ('w', 'Two'): [(0.001, 900, 0.9), (0.5, 100, 50.0)], ('w', 'Big'): [(0.01, 10, 0.1), (5.0, 1, 2.0)]}
def t13_sellers(st, p, V):
    o = []
    for nm, part in (('One', None), ('Two', None), ('Big', 0.01)):
        B = [b for b in VAL[(p, nm)] if part is None or b[0] <= part + 1e-12]
        o.append(dict(a=nm, base=nm, n=sum(b[1] for b in B), R=sum(b[2] for b in B),
                      ns=sum(ns_group(c, u, EDGES[EDGES.index(up) - 1], up, V) for up, c, u in B)))
    return o
class Grid:
    def __init__(self, st, V, prm):
        kind, _, per = st.partition(':')
        S = t13_sellers(kind, per, V)
        self.ns = [s['ns'] for s in S]; self.n = [s['n'] for s in S]
        self.q = [a / b for a, b in zip(self.ns, self.n)]       # stands for capR, verify, loss
''' % (k14.EDGES0,)

    def test_wrap(self):
        g = {'__name__': 'fake'}
        exec(self.SRC, g)
        GridFR, INFO = k14.install_fr(g, {'T01t': {'Big': 0.01}})
        fb = g['Grid']('T01t:w', 1.0, None)
        self.assertEqual(fb.ns, [1.0, 50.9, 0.1])                                # unchanged outside a GridFR
        fr = GridFR('T01t:w', 1.0, None, 'main')
        self.assertAlmostEqual(fr.ns[0], 100 * 0.01 / 1.01)
        self.assertAlmostEqual(fr.ns[1], 1000 / 3)
        self.assertAlmostEqual(fr.ns[2], 10 * 0.01 / 1.01)                       # partial set: top bin 0.01 only
        self.assertAlmostEqual(fr.q[1], 1 / 3)                                    # every ns-derived term sees FR
        self.assertEqual(g['Grid']('T01t:w', 1.0, None).ns, [1.0, 50.9, 0.1])    # switched off again afterwards
        self.assertEqual(INFO[('T01t', 'w', 1.0, 'Two')]['ns_fb'], 50.9)
        fl = GridFR('T01t:w', 1.0, None, 'lo')
        self.assertAlmostEqual(fl.ns[1], 1000 * 0.5 / 1.5)

    def test_wrap_detects_bin_mismatch(self):
        g = {'__name__': 'fake'}
        exec(self.SRC, g)
        GridFR, _ = k14.install_fr(g, {'T01t': {}})                              # wrong part for Big
        with self.assertRaises(AssertionError):
            GridFR('T01t:w', 1.0, None, 'main')


class TablesSmoke(unittest.TestCase):
    """tables() renders a synthetic result of the same shape main() writes (no real numbers)."""
    def test_render(self):
        import json
        PER = ['busy', 'median', 'quiet']
        def cell(bins_list, V, base):
            sel, tot = [], {}
            for a, B in bins_list:
                fr = k14.fr_seller(B, V); nfb = fb_ns(B, V)
                cost = {v: base + 0.001 * fr['ns'][v] / max(fr['n'], 1) for v in k14.VARS}
                sel.append(dict(a=a, ck='RS3', R=sum(b[2] for b in B), n=fr['n'], ns_fb=nfb,
                                v_main='inf' if fr['v_main'] == INF else fr['v_main'], v_lo=fr['v_lo'], p_main=fr['p_main'],
                                p_lo=fr['p_lo'], p_eq=fr['p_eq'], p_hyb_le=fr['p_hyb_le'], n_gtV=fr['n_gtV'], ns=fr['ns'],
                                ratio={v: fr['ns'][v] / nfb for v in k14.VARS}, cost_fb=base, k_fb=4, cost=cost,
                                k={v: 8 for v in k14.VARS}, diff={v: cost[v] - base for v in k14.VARS}))
            S = sum(s['ns_fb'] for s in sel)
            return dict(sellers=sel, sum=dict(ns_fb=S, ns={v: sum(s['ns'][v] for s in sel) for v in k14.VARS},
                                              ratio={v: sum(s['ns'][v] for s in sel) / S for v in k14.VARS}, agg_fb=base,
                                              agg={v: base + 0.002 for v in k14.VARS}, diff={v: 0.002 for v in k14.VARS},
                                              hyb_eq_main=True, any_gtV=False))
        six = [('A', [(0.01, 100, 1.0)]), ('B(0.5 or less)', [(0.001, 900, 0.9), (0.5, 100, 50.0)])]
        br = [('BlockRun', [(0.01, 10, 0.1), (INF, 2, 20.0)])]
        C = {}
        for V in (1.0, 0.2):
            for p in PER:
                for lab in ('lo', 'up', 'fac'):
                    C['T01t|%g|%s|%s' % (V, p, lab)] = cell(six, V, 0.05)
                    if p != 'quiet': C['BR|%g|%s|%s' % (V, p, lab)] = cell(br, V, 0.3)
        J = {v: dict(JK14a=k14.judge_a([1.3, 1.1, 1.3]), JK14b=k14.judge_b([0.002] * 3),
                     JK14c=k14.judge_c({p: {'A': -0.1, 'B': 0.1} for p in PER}, PER)) for v in ('main', 'lo')}
        J['verdict'] = dict(JK14a='holds', JK14b='does not hold not', JK14c='does not hold not(1)', binding='FR main', FR_lo='for verdicts not used not')
        RES = dict(meta=dict(k11b_reproduced=True, table4_ok=True), table4={'agg|1|lo': dict(want='x', got='x', ok=True)},
                   judgments=J, le10={'1|lo': dict(fb=3, main=3, lo=3, eq=3, hyb=3)}, cells=C)
        json.dumps(RES, ensure_ascii=False)
        md = k14.tables(RES, PER)
        self.assertIn('JK14a', md); self.assertIn('BlockRun', md); self.assertIn('(seller none)', md)
        self.assertIn('| inf |', md)


if __name__ == '__main__':
    unittest.main(verbosity=2)
