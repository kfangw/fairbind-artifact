#!/usr/bin/env python3
"""W4 (post hoc, calc-rules.md): the deterrence margin with the honest seller's per-sale cost share theta, and the cost of
a deduction b = cV under the measured-gas cost model (P11 base V1u, the state of the manuscript's cost table).

P11_posthoc/p11.py (and through it P9, P10, P6 and K11/k11b.py) is imported for its functions only; no file outside this
folder is written. The deduction is changed as in P8_posthoc/p8.py with_b: a shallow copy of a cached Grid with b
multiplied; b enters only Grid.loss (w n_s b / R) and Grid.cap (r b d/365 / R).

    python3 -I w4.py --out results
"""
import argparse, copy, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent.parent                                  # docs/11_journal
P11D = J / 'P11_posthoc'
if str(P11D) not in sys.path: sys.path.insert(0, str(P11D))
import p11   # noqa: E402  (functions only; its main() is not run)
p9 = p11.p9

P11J = P11D / 'results' / 'p11.json'
P8J = J / 'P8_posthoc' / 'results' / 'p8.json'

TH = 0.10
PER = ('busy', 'median', 'quiet')
LABS = ('lo', 'up', 'fac')
KINDS = ('T01t', 'BR')
VS = (1.0, 0.2)
THETAS = (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)     # calc-rules.md 1.4
XS = (0.0, 0.5, 1.0)                                    # margin targets in units of V
CS_FIXED = (1.0, 2.0, 4.0)
VBAR_STYL = (0.001, 0.01, 0.1)                          # Figure 4 mean sale amounts
TOL = 1e-12


# ================================================================== (a) deterrence (calc-rules.md 1.3)
def margin(c, theta, v, V=1.0):
    """m(c, theta, v, V) = cV + (1 - theta) v - theta (V - v)^+ : the lower bound on fraud's expected loss per
    detected episode, against honest service of the same sales."""
    return c * V + (1.0 - theta) * v - theta * max(V - v, 0.0)


def c_required(theta, x=0.0, v_over_V=0.0):
    """Least c with m >= x V for v < V: c = theta + x - v/V."""
    return theta + x - v_over_V


def mc_check(theta, c, v, V, n=1_000_000, seed=20261105):
    """Always-cheating seller with fixed amount v and cap V: sales are sampled with q = min(1, v/V); the episode ends at
    the first sampled sale. Delta = theta X - (1 - theta) v - c V with X = v * (sales paid before detection)."""
    q = min(1.0, v / V)
    rng = np.random.default_rng(seed)
    paid = rng.geometric(q, size=n) - 1                 # undetected fraudulent sales before the first detection
    X = v * paid.astype(float)
    d = theta * X - (1.0 - theta) * v - c * V
    return float(d.mean()), float(d.std() / math.sqrt(n)), -margin(c, theta, v, V)


def deter_tables():
    T = {}
    T['c_req'] = {('%g|%g' % (th, x)): c_required(th, x) for th in THETAS for x in XS}
    T['c_req_alt'] = {('%g|%g' % (th, x)): c_required(min(th, 1.0), x) for th in THETAS for x in XS}
    T['margin_fixed_c'] = {('%g|%g' % (th, c)): margin(c, th, 0.0) for th in THETAS for c in CS_FIXED}
    T['margin_fixed_c_alt'] = {('%g|%g' % (th, c)): margin(c, min(th, 1.0), 0.0) for th in THETAS for c in CS_FIXED}
    pts = [(1.0, 1.0, 0.01, 1.0), (0.5, 1.0, 0.01, 1.0), (0.0, 1.0, 0.05, 1.0), (1.5, 2.0, 0.1, 1.0), (0.25, 2.0, 0.2, 0.2),
           (1.0, 1.0, 1.5, 1.0)]
    T['mc'] = [dict(theta=th, c=c, v=v, V=V, **dict(zip(('mean', 'se', 'closed'), mc_check(th, c, v, V))))
               for th, c, v, V in pts]
    return T


# ================================================================== (b) cost of b = cV
def with_b(gr, mult):
    """P8_posthoc/p8.py with_b: shallow copy with b multiplied; the cached grid is not changed."""
    gb = copy.copy(gr)
    gb.b = mult * gr.b
    return gb


def cell(X, kind, p, V, lab, c, base_gr=None):
    gr = X.env.fb(kind + ':' + p, V, lab) if base_gr is None else base_gr
    if not gr.ok: return None
    assert abs(gr.b - V) < TOL, (kind, p, V, lab, gr.b)
    gb = with_b(gr, c)
    W0 = X.g['W0']
    o = gb.opt(W0)
    j = np.arange(gb.N); ki = o['ki']
    frz, ded = gb.loss(W0); cp = gb.cap(0.10)
    Rs = gb.R.sum()
    agg_term = lambda a: float((a[ki, j] * gb.R).sum() / Rs)
    return dict(agg=o['agg'], med=o['med'], ki=[int(X.g['KS'][i]) for i in ki], ded=agg_term(np.broadcast_to(ded, frz.shape)),
                cap=agg_term(cp), frz=agg_term(frz), N=int(gb.N),
                per={gb.a_[i]: [float(o['tot'][i]), int(X.g['KS'][ki[i]]), float(gb.R[i])] for i in range(gb.N)})


def cost_cells(X, cs):
    out = {}
    for kind in KINDS:
        for V in VS:
            for p in PER:
                for lab in LABS:
                    gr = X.env.fb(kind + ':' + p, V, lab)
                    if not gr.ok: continue
                    out['%s|%g|%s|%s' % (kind, V, p, lab)] = {('%g' % c): cell(X, kind, p, V, lab, c, gr) for c in cs}
    return out


def seller_amounts(X):
    """Mean sale amount R/n, revenue, and the expected revenue frozen at one failure R Delta_f / W_b (V = 1, lower)."""
    out = {}
    for kind in KINDS:
        for p in PER:
            gr = X.env.fb(kind + ':' + p, 1.0, 'lo')
            if not gr.ok: continue
            DF = float(gr.DFk[0, 0])
            out['%s|%s' % (kind, p)] = dict(DF=DF, Wb=float(gr.Wb), sellers={
                gr.a_[i]: dict(R=float(gr.R[i]), n=float(gr.n[i]), vbar=float(gr.R[i] / gr.n[i]),
                               frozen=float(gr.R[i] * DF / gr.Wb)) for i in range(gr.N)})
    return out


# ================================================================== checks (calc-rules.md 2.2)
MS = {  # manuscript table cost strings, % (busy, median, quiet)
    ('T01t', 1.0, 'lo'): ('9.21', '11.70', '11.92'), ('T01t', 1.0, 'up'): ('9.50', '12.06', '12.34'),
    ('T01t', 1.0, 'fac'): ('14.16', '18.45', '18.96'), ('T01t', 0.2, 'lo'): ('12.39', '14.30', '14.44'),
    ('T01t', 0.2, 'up'): ('12.81', '14.84', '15.05'), ('T01t', 0.2, 'fac'): ('17.33', '21.05', '21.49'),
    ('BR', 1.0, 'lo'): ('48.26', '35.42', '3.91'), ('BR', 1.0, 'up'): ('48.30', '35.45', '4.02'),
    ('BR', 1.0, 'fac'): ('61.81', '39.26', '5.42')}


def checks(X, C_u, C_0):
    ch = dict(k11b_reproduced=bool(X.repro))
    P = json.load(open(P11J))['bases']['V1u']['p9cells']
    mx = 0.0; miss = []
    for key, cc in C_u.items():
        if key not in P: miss.append(key); continue
        mx = max(mx, abs(cc['1']['agg'] - P[key]['agg']))
    ch['v1u_vs_p11_maxdiff'] = mx; ch['v1u_vs_p11_missing'] = miss
    ch['v1u_vs_p11_ok'] = bool(mx <= TOL and not miss)
    bad = []
    for (kind, V, lab), s in MS.items():
        for p, want in zip(PER, s):
            got = '%.2f' % (100 * C_u['%s|%g|%s|%s' % (kind, V, p, lab)]['1']['agg'])
            if got != want: bad.append(((kind, V, p, lab), got, want))
    ch['manuscript_cost_bad'] = bad; ch['manuscript_cost_ok'] = not bad
    D5 = json.load(open(P8J))['D5']['cells']
    mx = 0.0; miss = []
    for k8, v8 in D5.items():
        st, V, lab = k8.split('|'); kind, p = st.split(':')
        key = '%s|%g|%s|%s' % (kind, float(V), p, lab)
        if key not in C_0: miss.append(key); continue
        mx = max(mx, abs(C_0[key]['1']['agg'] - v8['agg1']), abs(C_0[key]['2']['agg'] - v8['agg2']))
    ch['v0_vs_p8_maxdiff'] = mx; ch['v0_vs_p8_missing'] = miss
    ch['v0_vs_p8_ok'] = bool(mx <= TOL and not miss and len(D5) > 0)
    ch['all_ok'] = bool(ch['k11b_reproduced'] and ch['v1u_vs_p11_ok'] and ch['manuscript_cost_ok'] and ch['v0_vs_p8_ok'])
    return ch


# ================================================================== tables
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator gas'}
KN = {'T01t': 'six seller sum', 'BR': 'BlockRun'}


def pc(x): return '%.2f' % (100 * x)


def tables(R):
    L = ['**all values post hoc calculations registered verdict none.** `w4.py` output. rule `calc-rules.md`.\n']
    L.append('check: ' + ', '.join('%s %s' % (k, R['checks'][k]) for k in
                                 ('k11b_reproduced', 'v1u_vs_p11_ok', 'manuscript_cost_ok', 'v0_vs_p8_ok', 'all_ok')) +
             '; V1u vs p11.json max difference %.1e, V0 vs p8.json max difference %.1e.\n' % (R['checks']['v1u_vs_p11_maxdiff'], R['checks']['v0_vs_p8_maxdiff']))
    D = R['deter']
    L.append('## 1. deterrence: required c (conservative value, v/V → 0)\n')
    L.append('(a) honest service and comparison, (b) fraud not alternative among better side(θ > 1if not selling not) and comparison. margin target m ≥ xV.\n')
    L.append('| θ | (a) x 0 | (a) x 0.5 | (a) x 1 | (b) x 0 | (b) x 0.5 | (b) x 1 |')
    L.append('|---|---|---|---|---|---|---|')
    for th in THETAS:
        a = [D['c_req']['%g|%g' % (th, x)] for x in XS]; b = [D['c_req_alt']['%g|%g' % (th, x)] for x in XS]
        L.append('| %g | ' % th + ' | '.join('%.2f' % z for z in a + b) + ' |')
    L.append('\n## 2. deterrence: deduction multiple c margin m/V (v → 0)\n')
    L.append('| θ | c 1 (a) | c 2 (a) | c 4 (a) | c 1 (b) | c 2 (b) | c 4 (b) |')
    L.append('|---|---|---|---|---|---|---|')
    for th in THETAS:
        a = [D['margin_fixed_c']['%g|%g' % (th, c)] for c in CS_FIXED]; b = [D['margin_fixed_c_alt']['%g|%g' % (th, c)] for c in CS_FIXED]
        L.append('| %g | ' % th + ' | '.join('%.2f' % z for z in a + b) + ' |')
    L.append('\nMonte Carlo check(10^6 episodes, increase cheating seller):\n')
    L.append('| θ | c | v | V | simulated E[Δ] | standard error | closed form −m |')
    L.append('|---|---|---|---|---|---|---|')
    for r in D['mc']:
        L.append('| %g | %g | %g | %g | %.5f | %.5f | %.5f |' % (r['theta'], r['c'], r['v'], r['V'], r['mean'], r['se'], r['closed']))
    L.append('\n## 3. v/V correction and freeze revenue (V = 1, lower Grid)\n')
    L.append('| set | window | seller | R | sales n | mean v = v/V | failure one times freeze revenue R Δ_f / W_b (USDC = V multiple) |')
    L.append('|---|---|---|---|---|---|---|')
    for key, d in R['amounts'].items():
        kind, p = key.split('|')
        for a, s in d['sellers'].items():
            L.append('| %s | %s | %s | %.2f | %d | %.4g | %.4g |' % (KN[kind], WN[p], a, s['R'], round(s['n']), s['vbar'], s['frozen']))
    L.append('\nFigure 4 v̄ %s: required c by that much gives.\n' % ', '.join('%g' % v for v in VBAR_STYL))
    for name, C in (('measured gas model V1u (Table cost)', R['cost_V1u']), ('old model V0 (supplement Table, P8)', R['cost_V0'])):
        L.append('## 4. deduction cV cost: %s\n' % name)
        cs = sorted({float(c) for v in C.values() for c in v}, key=float)
        L.append('| set | V | estimated | window | ' + ' | '.join('c %g' % c for c in cs) + ' | c 2 − c 1 (%p) | c 4 − c 1 (%p) | k changed seller (c 2 / c 4) |')
        L.append('|---|---|---|---|' + '---|' * len(cs) + '---|---|---|')
        for key, v in C.items():
            kind, V, p, lab = key.split('|')
            def kch(cc): return sum(1 for a, b in zip(v['1']['ki'], v[cc]['ki']) if a != b)
            L.append('| %s | %s | %s | %s | ' % (KN[kind], V, LN[lab], WN[p]) +
                     ' | '.join(pc(v['%g' % c]['agg']) + ('*' if v['%g' % c]['agg'] > TH else '') for c in cs) +
                     ' | +%.2f | +%.2f | %d / %d |' % (100 * (v['2']['agg'] - v['1']['agg']), 100 * (v['4']['agg'] - v['1']['agg']), kch('2'), kch('4')))
        L.append('\n*  10% over.\n')
    L.append('## 5. increment decomposition (V1u, c 2 − c 1, %p): deduction term / capital term / freeze term\n')
    L.append('| set | V | estimated | window | deduction | capital | freeze | sum |')
    L.append('|---|---|---|---|---|---|---|---|')
    for key, v in R['cost_V1u'].items():
        kind, V, p, lab = key.split('|')
        a, b = v['1'], v['2']
        L.append('| %s | %s | %s | %s | %+.3f | %+.3f | %+.3f | %+.3f |' % (KN[kind], V, LN[lab], WN[p], 100 * (b['ded'] - a['ded']),
                 100 * (b['cap'] - a['cap']), 100 * (b['frz'] - a['frz']), 100 * (b['agg'] - a['agg'])))
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    args = ap.parse_args(); T0 = time.time()
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT
    deter = deter_tables()
    cs = sorted(set(CS_FIXED) | {round(z, 10) for z in list(deter['c_req'].values()) + list(deter['c_req_alt'].values()) if z >= 1.0})
    X = p11.P11(with_fr=False, tag='k11b_w4')
    try:
        X.set_base('V1u'); C_u = cost_cells(X, cs); amounts = seller_amounts(X)
        X.set_base('V0'); C_0 = cost_cells(X, (1.0, 2.0, 4.0))
        X.set_base('V1u')
        CH = checks(X, C_u, C_0)
    finally:
        X.restore()
    for k in ('k11b_reproduced', 'v1u_vs_p11_ok', 'manuscript_cost_ok', 'v0_vs_p8_ok', 'all_ok'): print(k, CH[k], flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    meta = dict(cs=cs, thetas=THETAS, xs=XS, w0=X.g['W0'],
                sha256={f: (hashlib.sha256((HERE / f).read_bytes()).hexdigest() if (HERE / f).exists() else 'absent') for f in ('w4.py', 'calc-rules.md')})
    if not CH['all_ok']:
        json.dump(dict(meta=meta, checks=CH, verdict='withheld: reproduction failure'), open(OUT / 'w4.json', 'w'), indent=1, ensure_ascii=False)
        print('reproduction failed: no values reported'); sys.exit(2)
    RES = dict(meta=meta, checks=CH, deter=deter, amounts=amounts, cost_V1u=C_u, cost_V0=C_0)
    json.dump(RES, open(OUT / 'w4.json', 'w'), indent=1, ensure_ascii=False)
    (OUT / 'w4_tables.md').write_text(tables(RES), encoding='utf-8')
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in ('w4.json', 'w4_tables.md'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


if __name__ == '__main__':
    main()
