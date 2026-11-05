#!/usr/bin/env python3
"""Synthetic tests of r13_sim.py (registration R13_preregistration.md section 9). No real replay input is read.

  python3 test_r13.py -v
"""
import itertools
import json
import math
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import r13_sim as rs  # noqa: E402

V = 1_000_000
F = 0
EB = 300
DF = 2251


# ------------------------------------------------------------ an independent step-by-step model of the rule

def ref_release(blocks, epochs, sampled, k):
    """Payment block of every sale on the honest path of v0.8 R6 (a) with dispute windows from the anchor, a = 0,
    u = 0, keeper delay 0: per seller epoch E the cursor passes at the largest of M + 1, A + T_c + 1 and, for a
    profile epoch with a sampled sale, P + 1, over the profile epochs of E with a sale, and never before the
    previous seller epoch."""
    out = [None] * len(blocks)
    prev = None
    for E in sorted(set(e // k for e in epochs)):
        terms = []
        for e in sorted(set(e for e in epochs if e // k == E)):
            start = F + EB * e
            A = start + EB - 1 + 120
            M = A + 10 + 1 + 20
            P = M + 1800
            terms += [M + 1, A + 1800 + 1]
            if any(sampled[j] for j in range(len(blocks)) if epochs[j] == e):
                terms.append(P + 1)
        R = max(terms)
        if prev is not None and prev > R:
            R = prev
        prev = R
        for j in range(len(blocks)):
            if epochs[j] // k == E:
                out[j] = R
    return out


def ref_outcome(blocks, values, j0, sampled, k):
    """Gross paid fraud, net, paid before the failure, frozen, by stepping through the rule: honest sales (< j0) pass,
    the first sampled fraudulent sale c fails at f = P_fail(e_c) + 1, the account stops at f (no sale at a block
    >= f), the failure freezes every unpaid sale settled at or after s_c, the other sales are paid at their cursor
    pass (the seller epoch of c at max(R, f): the reading unfavourable to FairBind)."""
    epochs = [(b - F) // EB for b in blocks]
    fraud = [j >= j0 for j in range(len(blocks))]
    cands = [j for j in range(len(blocks)) if fraud[j] and sampled[j]]
    if not cands:
        W = sum(values[j] for j in range(len(blocks)) if fraud[j])
        return dict(det=False, G=W, N=W, pre=0, frozen=0)
    c = cands[0]
    f = F + EB * epochs[c] + DF
    live = [j for j in range(len(blocks)) if blocks[j] < f]          # suspension at f
    rel = ref_release([blocks[j] for j in live], [epochs[j] for j in live], [sampled[j] for j in live], k)
    G = pre = frozen = 0
    for t, j in enumerate(live):
        if not fraud[j]:
            continue
        if rel[t] < f:
            G += values[j]
            pre += values[j]
        elif blocks[j] >= blocks[c]:
            frozen += values[j]
        else:
            G += values[j]
    return dict(det=True, G=G, N=max(0, G - V), pre=pre, frozen=frozen)


class FixedRng:
    """random(shape) returns the next values of a fixed sequence (one replicate)."""

    def __init__(self, seq):
        self.seq = list(seq)

    def random(self, shape):
        r, n = shape
        assert r == 1
        out, self.seq = self.seq[:n], self.seq[n:]
        out += [0.999999] * (n - len(out))
        return np.array([out])


def hand_seller():
    # (block, value): pi = 0.2, 0.3, 0.5, 1 (v > V), 0.1
    blocks = [100, 100, 150, 400, 700]
    values = [200_000, 300_000, 500_000, 1_500_000, 100_000]
    return rs.Seller(blocks, values, rows=[0, 1, 2, 3, 4], first_block=F, epoch_blocks=EB, V=V)


class HandCases(unittest.TestCase):
    def test_sampled_in_first_block_freezes_the_same_block(self):
        s = hand_seller()
        c = s.first_sampled(0, 1, FixedRng([0.5, 0.2]))[0]
        self.assertEqual(c, 1)                       # U 0.2 < pi 0.3
        o = s.outcome(0, int(c), delta_f=DF, ks=(1, 2))
        # sale 0 shares block 100 with c: settled at s_c, frozen, not paid
        self.assertEqual(o['G'], 0)
        self.assertEqual(o['N'], 0)
        self.assertEqual(o['frozen'], 2_600_000)    # blocks 100 .. 700 < f = 2,251
        self.assertTrue(o['det'])

    def test_cap_exceeding_sale_is_always_sampled(self):
        s = hand_seller()
        c = s.first_sampled(0, 1, FixedRng([0.9, 0.9, 0.9, 0.99999]))[0]
        self.assertEqual(c, 3)                       # pi = 1
        o = s.outcome(0, int(c), delta_f=DF, ks=(1, 2))
        self.assertEqual(o['G'], 1_000_000)
        self.assertEqual(o['N'], 0)                  # deduction V
        self.assertEqual(o['pre'][1], 1_000_000)     # k = 1: epoch 0 is passed at 0 + 2,220 < f = 2,551
        self.assertEqual(o['pre'][2], 0)             # k = 2: epochs 0 and 1 form seller epoch 0, paid after f
        self.assertEqual(o['frozen'], 1_600_000)     # blocks 400 and 700 < 2,551
        dist = s.distribution(0, horizon=1e9, delta_f=DF, ks=(1,))
        self.assertAlmostEqual(dist['p'].sum(), 1.0, places=12)
        self.assertFalse((~dist['det']).any() and dist['p'][~dist['det']].sum() > 0)

    def test_hand_expectation(self):
        s = hand_seller()
        # P(first sampled = 0) .2 -> G 0; = 1 .8*.3 -> G 0; = 2 .8*.7*.5 = .28 -> G 500k (blocks < 150); = 3 .28 -> G 1M
        EG, EN = s.expectations(0, horizon=1e9)
        self.assertAlmostEqual(EG, 0.28 * 500_000 + 0.28 * 1_000_000, places=6)
        self.assertAlmostEqual(EN, 0.0, places=9)
        # start at epoch 1 (sale 3, pi = 1): G = 0 surely
        self.assertEqual(list(s.starts), [0, 3, 4])
        self.assertEqual(s.expectations(3, horizon=1e9), (0.0, 0.0))

    def test_undetected_seller_keeps_everything_without_deduction(self):
        s = rs.Seller([10, 20], [100_000, 200_000], [0, 1], F, EB, V)
        d = s.distribution(0, horizon=1e9, delta_f=DF)
        self.assertAlmostEqual(d['p'][-1], 0.9 * 0.8, places=12)
        self.assertEqual(d['G'][-1], 300_000)
        self.assertEqual(d['N'][-1], 300_000)
        self.assertFalse(d['det'][-1])
        # quantiles: P(N = 0) = .28, then N = 300k: median 300k, P(G <= 100k) = .1 + .9*.2 ... check by enumeration
        self.assertEqual(rs.dist_quantile(d['N'], d['p'], 0.5), 300_000)
        self.assertEqual(rs.dist_quantile(d['N'], d['p'], 0.2), 0)

    def test_quantile_rules(self):
        self.assertEqual(rs.sample_quantile(list(range(1, 10001)), 0.95), 9500)
        self.assertEqual(rs.sample_quantile(list(range(1, 10001)), 0.5), 5000)
        self.assertEqual(rs.dist_quantile(np.array([0, 5, 9]), np.array([0.5, 0.45, 0.05]), 0.95), 5)
        self.assertEqual(rs.dist_quantile(np.array([0, 5, 9]), np.array([0.5, 0.44, 0.06]), 0.95), 9)


def random_seller(rng, n, span=3_000, big=True):
    blocks = np.sort(rng.integers(0, span, n))
    choices = [20_000, 100_000, 300_000, 700_000] + ([1_200_000] if big else [])
    values = rng.choice(choices, n)
    return blocks.tolist(), values.tolist()


class AgainstTheRuleModel(unittest.TestCase):
    def test_exact_distribution_equals_enumeration(self):
        rng = np.random.default_rng(1)
        for trial in range(25):
            n = int(rng.integers(1, 9))
            blocks, values = random_seller(rng, n)
            s = rs.Seller(blocks, values, list(range(n)), F, EB, V)
            pis = [min(1.0, v / V) for v in s.values.tolist()]
            for j0 in s.starts.tolist():
                d = s.distribution(j0, horizon=1e9, delta_f=DF, ks=(1, 2, 4))
                EG = EN = EF = 0.0
                EP = {1: 0.0, 2: 0.0, 4: 0.0}
                for bits in itertools.product([0, 1], repeat=n):
                    p = math.prod(pis[j] if bits[j] else 1 - pis[j] for j in range(n))
                    if p == 0:
                        continue
                    o = {k: ref_outcome(s.blocks.tolist(), s.values.tolist(), j0, bits, k) for k in (1, 2, 4)}
                    # gross and net do not depend on k (R7 (b): the freeze starts at s_c whatever k)
                    self.assertEqual(len({(x['G'], x['N'], x['frozen']) for x in o.values()}), 1)
                    EG += p * o[1]['G']
                    EN += p * o[1]['N']
                    EF += p * o[1]['frozen']
                    for k in EP:
                        EP[k] += p * o[k]['pre']
                self.assertAlmostEqual(float(np.dot(d['p'], d['G'])), EG, delta=1e-6)
                self.assertAlmostEqual(float(np.dot(d['p'], d['N'])), EN, delta=1e-6)
                self.assertAlmostEqual(float(np.dot(d['p'], d['frozen'])), EF, delta=1e-6)
                for k in EP:
                    got = float(np.dot(d['p'], np.where(d['det'], d['pre'][k], 0)))
                    self.assertAlmostEqual(got, EP[k], delta=1e-6)

    def test_outcome_equals_rule_model_for_every_first_sale(self):
        rng = np.random.default_rng(2)
        for trial in range(40):
            n = int(rng.integers(2, 30))
            blocks, values = random_seller(rng, n, span=12_000)
            s = rs.Seller(blocks, values, list(range(n)), F, EB, V)
            for j0 in s.starts.tolist()[:4]:
                for c in list(range(j0, n)) + [n]:
                    # honest sales before j0 sampled at random: they pass and change only release timing
                    sampled = [bool(rng.random() < 0.3) if j < j0 else (j == c) for j in range(n)]
                    for k in (1, 2, 4, 8):
                        ref = ref_outcome(s.blocks.tolist(), s.values.tolist(), j0, sampled, k)
                        got = s.outcome(j0, c, delta_f=DF, ks=(k,))
                        self.assertEqual((got['G'], got['N'], got['det']), (ref['G'], ref['N'], ref['det']))
                        if ref['det']:
                            self.assertEqual(got['pre'][k], ref['pre'])
                            self.assertEqual(got['frozen'], ref['frozen'])

    def test_theorem_bound_on_expectation(self):
        rng = np.random.default_rng(3)
        for trial in range(30):
            n = int(rng.integers(1, 400))
            blocks, values = random_seller(rng, n, span=40_000)
            s = rs.Seller(blocks, values, list(range(n)), F, EB, V)
            tG, tN, EG, EN = rs.worst_start(s, 50.0)
            self.assertTrue((EG <= V * (1 + 1e-9)).all())
            self.assertTrue((EN <= EG + 1e-6).all())

    def test_worst_start_ties_take_the_earliest(self):
        # two identical epochs far apart, nothing after: the last two starts tie only if their futures agree
        s = rs.Seller([0, 300], [V, V], [0, 1], F, EB, V)       # pi = 1: G = 0 at every start
        tG, tN, EG, EN = rs.worst_start(s, 50.0)
        self.assertEqual((tG, tN), (0, 0))
        s = rs.Seller([0, 10, 300], [400_000, 400_000, 400_000], [0, 1, 2], F, EB, V)
        tG, tN, EG, EN = rs.worst_start(s, 50.0)
        self.assertEqual(tG, int(np.argmax(EG)))
        self.assertGreater(EG[0], EG[1])                          # an earlier start has more sales ahead


class MonteCarlo(unittest.TestCase):
    def test_mc_agrees_with_exact(self):
        rng = np.random.default_rng(4)
        blocks, values = random_seller(rng, 300, span=60_000, big=False)
        s = rs.Seller(blocks, values, list(range(300)), F, EB, V)
        R = 20_000
        G, N = s.mc(0, R, rs.rng_for(1, 0, 0, 0), chunk=64)
        d = s.distribution(0, horizon=50.0, delta_f=DF)
        for x, key in ((G, 'G'), (N, 'N')):
            exact = float(np.dot(d['p'], d[key]))
            se = x.std(ddof=1) / math.sqrt(R)
            self.assertLess(abs(x.mean() - exact), 4 * se + 1e-9)
            q = rs.sample_quantile(x, 0.95)
            cdf_at_q = float(d['p'][d[key] <= q].sum())
            self.assertGreater(cdf_at_q, 0.94)
            q_exact = rs.dist_quantile(d[key], d['p'], 0.95)
            self.assertLessEqual(float(d['p'][d[key] < q_exact].sum()), 0.95)
            self.assertGreaterEqual(float(d['p'][d[key] <= q_exact].sum()), 0.95)

    def test_seeds_are_fixed(self):
        rng = np.random.default_rng(5)
        blocks, values = random_seller(rng, 100, big=False)
        s = rs.Seller(blocks, values, list(range(100)), F, EB, V)
        a = s.mc(0, 500, rs.rng_for(20261030, 1, 7, 0))
        b = s.mc(0, 500, rs.rng_for(20261030, 1, 7, 0))
        c = s.mc(0, 500, rs.rng_for(20261030, 1, 8, 0))
        self.assertTrue(np.array_equal(a[0], b[0]))
        self.assertFalse(np.array_equal(a[0], c[0]))

    def test_chunking_does_not_change_the_first_sampled_sale_distribution(self):
        s = hand_seller()
        for seq, want in (([0.5, 0.2], 1), ([0.1], 0), ([0.9, 0.9, 0.4, 0.0], 2), ([0.9, 0.9, 0.9, 0.9], 3)):
            for chunk in (1, 2, 512):
                self.assertEqual(int(s.first_sampled(0, 1, FixedRng(seq), chunk=chunk)[0]), want)
        s = rs.Seller([10, 20], [100_000, 200_000], [0, 1], F, EB, V)
        self.assertEqual(int(s.first_sampled(0, 1, FixedRng([0.5, 0.5]))[0]), 2)   # none sampled: n


class VerdictsAndPipeline(unittest.TestCase):
    def test_strict_comparison(self):
        self.assertFalse(Fraction(1_000_000) * 86_400 < 86_400_000_000)
        self.assertTrue(Fraction(999_999.9) * 86_400 < 86_400_000_000)

    def test_selfcheck_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            rc = rs.main(['selfcheck', '--out', d, '--reps', '400'])
            self.assertEqual(rc, 0)
            out = Path(d) / 'result'
            for p in rs.REGISTERED['outputs']:
                self.assertTrue((out / p).exists(), p)
            doc = json.loads((out / 'r13_results.json').read_text())
            self.assertEqual(set(doc['verdicts']), set(rs.VERDICTS))
            for w in rs.REGISTERED['windows']:
                agg = doc['windows'][w]['agg']
                self.assertLessEqual(agg['sum_EG'], agg['nV'] * (1 + 1e-9))
                self.assertLessEqual(agg['sum_EN'], agg['sum_EG'] + 1e-6)
                self.assertLessEqual(agg['sum_q95_N'], agg['sum_q95_G'])
                cells = doc['windows'][w]['verdict_cells']
                for name, (m, st, comp) in rs.VERDICTS.items():
                    for lag in ('own', 'k1'):
                        want = Fraction(cells[name]['value_atomic']) * 86_400 < agg['X_sums_scaled'][lag][comp]
                        self.assertEqual(cells[name][lag], want)
            header = (out / 'r13_addr_median.csv').read_text().splitlines()[0].split(',')
            self.assertEqual(header, rs.ADDR_COLUMNS)

    def test_seal_check(self):
        with tempfile.TemporaryDirectory() as d:
            reg = Path(d) / 'R13_preregistration.md'
            reg.write_text('x\n')
            seal = Path(d) / 'R13_preregistration.sha256'
            seal.write_text(f'{rs.sha256(reg)}  R13_preregistration.md\n{rs.sha256(rs.__file__)}  r13_sim.py\n')
            self.assertEqual(rs.check_seal(reg, seal)[1], [])
            reg.write_text('y\n')
            self.assertEqual(rs.check_seal(reg, seal)[1], ['R13_preregistration.md'])

    def test_registered_constants(self):
        self.assertEqual(rs.REGISTERED['delta_f'], 299 + 120 + 31 + 1800 + 1)
        self.assertEqual(rs.REGISTERED['replicates'], 10_000)
        self.assertEqual(len(rs.VERDICTS), 12)


if __name__ == '__main__':
    unittest.main()
