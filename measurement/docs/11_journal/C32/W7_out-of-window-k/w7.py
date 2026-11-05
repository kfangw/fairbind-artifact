#!/usr/bin/env python3
"""W7 (post hoc, calc-rules.md): the seller-epoch multiple k chosen in one window and applied in another, and the
sensitivity of the fit statements to the threshold (5%, 10%, 20% of revenue).

P11_posthoc/p11.py is imported for its functions only (its main() is not run). p11.P11() loads K11/k11b.py unchanged
through P9's Env; set_base('V1u') gives the manuscript's measured-gas cost with the real-USDC constants. No file
outside this folder is written.

    python3 -I w7.py --out results
"""
import argparse, hashlib, json, math, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent.parent                                   # docs/11_journal
for _d in (J / 'P9_posthoc', J / 'P10_fit-conditions', J / 'P11_posthoc', J / 'P6_posthoc'):
    if str(_d) not in sys.path: sys.path.insert(0, str(_d))
import p9    # noqa: E402
import p10   # noqa: E402
import p11   # noqa: E402

P11J = J / 'P11_posthoc' / 'results' / 'p11.json'
P10UJ = J / 'P10u_real-USDC' / 'results' / 'p10u.json'
PER = ('busy', 'median', 'quiet')                       # time order (calc-rules.md 0.2)
ORD = {p: i for i, p in enumerate(PER)}
PAIRS = [(a, b) for a in PER for b in PER if a != b]
MAIN = {('busy', 'median'), ('busy', 'quiet'), ('median', 'quiet')}
HEAD = {'median': 'busy', 'quiet': 'median', 'busy': 'median'}   # head source per target; busy only as auxiliary
LABS = ('lo', 'fac')
THS = (0.05, 0.10, 0.20)
PRICES = {'same': p11.FI_POINTS['same'], 'own_45615': p11.FI_POINTS['own_a'], 'own_81311': p11.FI_POINTS['own_bind_b']}
assert PRICES == {'same': 86_824, 'own_45615': 45_615, 'own_81311': 81_311}, PRICES
TOL = 1e-12


def jsonable(x): return json.loads(json.dumps(x, allow_nan=True, ensure_ascii=False))


# ================================================================== per-window arrays
def window_arrays(X, kind, p, lab):
    """FairBind and FI (k x seller) totals at w0 for the three prices; FairBind keeps the measured call (P11 mode 'fi')."""
    env = X.env; fb = env.fb(kind + ':' + p, 1.0, lab)
    if not fb.ok: return None
    fi = env.fi(kind + ':' + p, lab)
    assert list(fb.a_) == list(fi.a_)
    out = dict(names=list(fb.a_), R=np.asarray(fb.R, float), KS=list(X.g['KS']))
    tb0 = fb.total(X.g['W0'])
    out['fb'] = tb0
    out['fi'] = {}
    for pr, gg in PRICES.items():
        tb, tf = p11.named_terms(X, fb, fi, dict(kind='g', mode='fi', g=gg))
        assert np.array_equal(tb, tb0)
        out['fi'][pr] = tf
    # the proof term of FI does not depend on k (calc-rules.md 2.2)
    v = fi.c0parts['verify']; assert np.allclose(v, v[0][None, :], rtol=0, atol=0)
    return out


def repro(X, A):
    """calc-rules.md 0.3 (2): in-window values against p11.json V1u p9cells."""
    P = json.load(open(P11J, encoding='utf-8'))['bases']['V1u']['p9cells']
    mx = 0.0; kbad = 0; n = 0
    for (kind, p, lab), a in A.items():
        c = P['%s|1|%s|%s' % (kind, p, lab)]
        ki = np.argmin(a['fb'], axis=0); kf = np.argmin(a['fi']['same'], axis=0); j = np.arange(len(a['names']))
        xb = a['fb'][ki, j]; xf = a['fi']['same'][kf, j]
        agg = float((xb * a['R']).sum() / a['R'].sum()); mx = max(mx, abs(agg - c['agg'])); n += 1
        for jj, nm in enumerate(a['names']):
            mx = max(mx, abs(xb[jj] - c['per'][nm][0]), abs(xf[jj] - c['fi_per'][nm][0]), abs(a['R'][jj] - c['per'][nm][2]))
            kbad += int(a['KS'][ki[jj]] != c['per'][nm][1]) + int(a['KS'][kf[jj]] != c['fi_per'][nm][1]); n += 1
    return dict(maxdiff=mx, kdiff=kbad, cells=n, ok=bool(mx <= TOL and kbad == 0))


# ================================================================== (a) out-of-window k
def cross(A, kind, lab):
    """Every ordered pair (source, target): per seller k_A, k_B, out-of-window and in-window cost, FI likewise."""
    res = {}
    for (sa, tb) in PAIRS:
        a = A.get((kind, sa, lab)); b = A.get((kind, tb, lab))
        if a is None or b is None: continue
        KS = b['KS']; per = {}
        num = {'in': 0.0, 'out': 0.0}; numfi = {pr: {'in': 0.0, 'out': 0.0} for pr in PRICES}
        for j, nm in enumerate(b['names']):
            kb = int(np.argmin(b['fb'][:, j])); src = nm in a['names']
            ka = int(np.argmin(a['fb'][:, a['names'].index(nm)])) if src else kb
            cin = float(b['fb'][kb, j]); cout = float(b['fb'][ka, j]); R = float(b['R'][j])
            row = dict(k_src=KS[ka], k_in=KS[kb], out=cout, inw=cin, diff=cout - cin, R=R, src_missing=not src, fi={})
            for pr in PRICES:
                fb_ = b['fi'][pr]; kfb = int(np.argmin(fb_[:, j]))
                kfa = int(np.argmin(a['fi'][pr][:, a['names'].index(nm)])) if src else kfb
                fin, fout = float(fb_[kfb, j]), float(fb_[kfa, j])
                row['fi'][pr] = dict(k_src=KS[kfa], k_in=KS[kfb], out=fout, inw=fin,
                                     fb_cheaper_in=bool(cin <= fin), fb_cheaper_out=bool(cout <= fout))
                numfi[pr]['in'] += fin * R; numfi[pr]['out'] += fout * R
            num['in'] += cin * R; num['out'] += cout * R
            per[nm] = row
        RT = float(b['R'].sum())
        res['%s>%s' % (sa, tb)] = dict(src=sa, tgt=tb, main=(sa, tb) in MAIN, per=per,
                                       agg_in=num['in'] / RT, agg_out=num['out'] / RT,
                                       fi_agg={pr: dict(inw=v['in'] / RT, out=v['out'] / RT) for pr, v in numfi.items()})
    # worst of the two other windows per target
    for tb in PER:
        ks = [k for k, v in res.items() if v['tgt'] == tb]
        if not ks: continue
        per = {}
        for nm in res[ks[0]]['per']:
            best = max(ks, key=lambda k: res[k]['per'][nm]['out'])
            per[nm] = dict(res[best]['per'][nm], from_pair=best)
        RT = sum(r['R'] for r in per.values())
        res['worst>%s' % tb] = dict(src='worst', tgt=tb, main=False, per=per,
                                    agg_in=res[ks[0]]['agg_in'], agg_out=sum(r['out'] * r['R'] for r in per.values()) / RT)
    return res


# ================================================================== (b) thresholds on the observed sellers
def regions_obs(A, kind, lab, mode):
    """mode 'in': in-window k; 'head': k of the head source window (HEAD) for FairBind and FI alike."""
    out = {}
    for p in PER:
        b = A.get((kind, p, lab))
        if b is None: continue
        src = b if mode == 'in' else A[(kind, HEAD[p], lab)]
        for pr in PRICES:
            xb, xf = [], []
            for j, nm in enumerate(b['names']):
                js = src['names'].index(nm)
                xb.append(float(b['fb'][int(np.argmin(src['fb'][:, js])), j]))
                xf.append(float(b['fi'][pr][int(np.argmin(src['fi'][pr][:, js])), j]))
            xb = np.array(xb); xf = np.array(xf); R = b['R']; RT = float(R.sum())
            for th in THS:
                A_ = [j for j in range(len(R)) if xb[j] <= xf[j] and xb[j] <= th]
                within = [j for j in range(len(R)) if xb[j] <= th]
                out['%s|%s|%g' % (p, pr, th)] = dict(
                    n_A=len(A_), share_A=float(sum(R[j] for j in A_) / RT), names_A=[b['names'][j] for j in A_],
                    n_within=len(within), share_within=float(sum(R[j] for j in within) / RT),
                    agg_fb=float((xb * R).sum() / RT), agg_fi=float((xf * R).sum() / RT),
                    agg_le=bool((xb * R).sum() / RT <= th), agg_fb_le_fi=bool((xb * R).sum() <= (xf * R).sum()),
                    per={b['names'][j]: [float(xb[j]), float(xf[j]), p11.region(float(xb[j]), float(xf[j]), th)] for j in range(len(R))})
    return out


# ================================================================== (b) stylised fit region
def regmap(X):
    M = X.M; prm = M.prm['lo']; gu = prm.gusd
    ms_ = np.logspace(0, 4, 97); vs_ = np.logspace(-3.5, 0.5, 81)
    FB = np.zeros((len(vs_), len(ms_))); FI = {pr: np.zeros_like(FB) for pr in PRICES}
    cp = prm.cpu('RS3')
    for i, v in enumerate(vs_):
        for j, m in enumerate(ms_):
            s = p10.stylised(m, v); st = p10.structure(M, s, 21)
            fb, fi, tf, ti = p10.costs(M, s, st, 'lo')
            FB[i, j] = float(tf.min())
            n, R = float(s['n']), float(s['R'])
            for pr, gg in PRICES.items():
                c = p11.cp_shift(gu, ['RS3'], [cp], gg)[0]
                FI[pr][i, j] = float((ti - fi['verify'] + c * n / R).min())
    return ms_, vs_, FB, FI


def regmap_check(ms_, vs_, FB, FI):
    R = json.load(open(P10UJ, encoding='utf-8'))['V1u']['regmap']
    ok = np.allclose(ms_, R['m'], rtol=0, atol=0) and np.allclose(vs_, R['v'], rtol=0, atol=0)
    F0 = np.array(R['fb']); Z0 = np.array(R['Z'])
    rel = float(np.max(np.abs(FB - F0) / np.maximum(np.abs(F0), 1e-300)))
    Z = np.where((FB <= FI['same']) & (FB <= 0.10), 0, np.where((FI['same'] < FB) & (FI['same'] <= 0.10), 1, 2))
    zbad = int(np.sum(Z != Z0))
    return dict(grid_same=bool(ok), fb_maxrel=rel, z_mismatch=zbad, ok=bool(ok and rel <= TOL and zbad == 0))


def fit_regions(X, ms_, vs_, FB, FI):
    M = X.M; out = {}
    for th in THS:
        cf = p10.closed_form_threshold(M, 0.1, 'lo', 1, th)
        edge = cf['b'] / (th - cf['a']) if th > cf['a'] else math.inf
        ii, _ = np.nonzero(FB <= th)
        row = dict(within_cells=int(len(ii)), within_vmin=float(vs_[ii].min()) if len(ii) else None,
                   within_vmax=float(vs_[ii].max()) if len(ii) else None, edge_closed=edge, joint={})
        for pr in PRICES:
            ii, jj = np.nonzero((FB <= FI[pr]) & (FB <= th))
            if len(ii) == 0: row['joint'][pr] = None; continue
            byv = {}
            for i in sorted(set(ii.tolist())):
                js = jj[ii == i]; byv['%.5g' % vs_[i]] = [float(ms_[js].min()), float(ms_[js].max())]
            row['joint'][pr] = dict(cells=int(len(ii)), m_min=float(ms_[jj].min()), m_max=float(ms_[jj].max()),
                                    v_min=float(vs_[ii].min()), v_max=float(vs_[ii].max()), by_v=byv)
        out['%g' % th] = row
    return out


# ================================================================== tables
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet', 'worst': 'worse side'}
PN = {'same': 'same call 86,824', 'own_45615': 'own call 45,615', 'own_81311': 'own call 81,311'}
SH = {'StableEnrich': 'StableEnrich', 'OneSource': 'OneSource', 'CoinMarketCap': 'CoinMarketCap', 'StableApify': 'StableApify'}


def pc(x): return '-' if x is None else '%.2f' % (100 * x)
def short(nm): return nm.split('(')[0]


def tables(RES):
    L = []; P = L.append
    C = RES['cross']
    for lab, labn in (('lo', 'lower estimated'), ('fac', 'facilitator gas estimated')):
        P('\n### per seller window outside k, %s (V = 1, revenue relative to %%)\n' % labn)
        P('| applied window | source window | main/auxiliary | seller | k source | k same window | window outside | same window | difference(%p) |')
        P('|---|---|---|---|---|---|---|---|---|')
        for tb in PER:
            for sa in [x for x in PER if x != tb] + ['worst']:
                c = C['T01t|%s' % lab].get('%s>%s' % (sa, tb))
                if c is None: continue
                for nm, r in c['per'].items():
                    P('| %s | %s | %s | %s | %d | %d | %s | %s | %+.2f |' % (WN[tb], WN[sa] if sa != 'worst' else 'worse side(%s)' % WN[r.get('from_pair', '>').split('>')[0]],
                      'main' if c['main'] else 'auxiliary', short(nm), r['k_src'], r['k_in'], pc(r['out']), pc(r['inw']), 100 * r['diff']))
        P('\n### set value, %s (six data seller sum, BlockRun)\n' % labn)
        P('| set | applied window | same window | source busy | source median | source quiet | worse side |')
        P('|---|---|---|---|---|---|---|')
        for kind, kn in (('T01t', 'six sum'), ('BR', 'BlockRun')):
            cc = C['%s|%s' % (kind, lab)]
            for tb in PER:
                cells = []
                for sa in PER:
                    c = cc.get('%s>%s' % (sa, tb))
                    cells.append('-' if c is None else ('%s%s' % (pc(c['agg_out']), '*' if c['agg_out'] > 0.10 else '') + (' (main)' if c['main'] else '')))
                w = cc.get('worst>%s' % tb); a0 = cc['%s>%s' % ([x for x in PER if x != tb][0], tb)]['agg_in']
                P('| %s | %s | %s%s | %s | %s |' % (kn, WN[tb], pc(a0), '*' if a0 > 0.10 else '', ' | '.join(cells), pc(w['agg_out']) + ('*' if w['agg_out'] > 0.10 else '')))
        P('\n\\* 10% over.')
    # StableEnrich
    P('\n### StableEnrich (lower estimated, V = 1)\n')
    P('| applied window | source window | k | FB | FB ≤ 10% | FI same call (k) | FI 45,615 | FI 81,311 | FB cheaper price |')
    P('|---|---|---|---|---|---|---|---|---|')
    cc = C['T01t|lo']
    for tb in PER:
        se = [nm for nm in cc['%s>%s' % ([x for x in PER if x != tb][0], tb)]['per'] if nm.startswith('StableEnrich')][0]
        r0 = cc['%s>%s' % ([x for x in PER if x != tb][0], tb)]['per'][se]
        rows = [('same window', r0['k_in'], r0['inw'], {pr: (r0['fi'][pr]['inw'], r0['fi'][pr]['k_in'], r0['fi'][pr]['fb_cheaper_in']) for pr in PRICES})]
        for sa in [x for x in PER if x != tb]:
            r = cc['%s>%s' % (sa, tb)]['per'][se]
            rows.append((WN[sa] + (' (main)' if (sa, tb) in MAIN else ''), r['k_src'], r['out'],
                         {pr: (r['fi'][pr]['out'], r['fi'][pr]['k_src'], r['fi'][pr]['fb_cheaper_out']) for pr in PRICES}))
        for nm, k, x, fi in rows:
            ch = ', '.join(PN[pr].split(' ')[-1] for pr in PRICES if fi[pr][2]) or 'none'
            P('| %s | %s | %d | %s | %s | %s (%d) | %s | %s | %s |' % (WN[tb], nm, k, pc(x), 'yes' if x <= 0.10 else 'no',
              pc(fi['same'][0]), fi['same'][1], pc(fi['own_45615'][0]), pc(fi['own_81311'][0]), ch))
    # FI aggregates
    P('\n### six sum FB and FI (lower estimated; window outside FB and FI all source window k)\n')
    P('| applied window | source window | FB | FI same call | FI 45,615 | FI 81,311 |')
    P('|---|---|---|---|---|---|')
    for tb in PER:
        first = cc['%s>%s' % ([x for x in PER if x != tb][0], tb)]
        P('| %s | same window | %s | %s | %s | %s |' % (WN[tb], pc(first['agg_in']), *[pc(first['fi_agg'][pr]['inw']) for pr in PRICES]))
        for sa in [x for x in PER if x != tb]:
            c = cc['%s>%s' % (sa, tb)]
            P('| %s | %s%s | %s | %s | %s | %s |' % (WN[tb], WN[sa], ' (main)' if c['main'] else '', pc(c['agg_out']), *[pc(c['fi_agg'][pr]['out']) for pr in PRICES]))
    # thresholds
    for kind, kn in (('T01t', 'six data seller'), ('BR', 'BlockRun')):
        P('\n### per threshold region A (FB ≤ θand FB ≤ FI), %s, lower estimated\n' % kn)
        P('| k | window | price | θ = 5%: count; share | θ = 10%: count; share | θ = 20%: count; share | FB ≤ θthat is seller count (5/10/20) | six sum ≤ θ (5/10/20) |')
        P('|---|---|---|---|---|---|---|---|')
        for mode, mn in (('in', 'same window'), ('head', 'window outside')):
            T = RES['thr']['%s|lo|%s' % (kind, mode)]
            for p in PER:
                for pr in PRICES:
                    k5, k10, k20 = (T['%s|%s|%g' % (p, pr, th)] for th in THS)
                    lbl = mn if mode == 'in' else 'window outside(%s)' % WN[HEAD[p]]
                    P('| %s | %s | %s | %d; %s%% | %d; %s%% | %d; %s%% | %d / %d / %d | %s |' % (
                        lbl, WN[p], PN[pr], k5['n_A'], pc(k5['share_A']), k10['n_A'], pc(k10['share_A']), k20['n_A'], pc(k20['share_A']),
                        k5['n_within'], k10['n_within'], k20['n_within'], ' / '.join('yes' if x['agg_le'] else 'no' for x in (k5, k10, k20))))
    P('\n### region A seller name (six data seller, lower)\n')
    P('| k | window | price | 5% | 10% | 20% |')
    P('|---|---|---|---|---|---|')
    for mode, mn in (('in', 'same window'), ('head', 'window outside')):
        T = RES['thr']['T01t|lo|%s' % mode]
        for p in PER:
            for pr in PRICES:
                P('| %s | %s | %s | %s |' % (mn, WN[p], PN[pr], ' | '.join(', '.join(short(n) for n in T['%s|%s|%g' % (p, pr, th)]['names_A']) or 'none' for th in THS)))
    # fit region
    P('\n### stylised seller fit region (Figure fit (b) grid, d = 1, lower, V = 1, w = 0.00173)\n')
    P('| θ | FB ≤ θ cell count | FB ≤ θof v̄ min (grid) | closed form v̄ lower | price | joint region cell count | m range | v̄ range |')
    P('|---|---|---|---|---|---|---|---|')
    for th in THS:
        r = RES['fit']['%g' % th]
        for pr in PRICES:
            jn = r['joint'][pr]
            P('| %g%% | %d | %s | %s | %s | %s | %s | %s |' % (100 * th, r['within_cells'], '%.4f' % r['within_vmin'] if r['within_vmin'] else '-',
              '%.4f' % r['edge_closed'] if math.isfinite(r['edge_closed']) else 'none', PN[pr],
              'none' if jn is None else jn['cells'], '-' if jn is None else '%.1f–%.1f' % (jn['m_min'], jn['m_max']),
              '-' if jn is None else '%.4f–%.4f' % (jn['v_min'], jn['v_max'])))
    return '\n'.join(L) + '\n'


# ================================================================== main
def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    args = ap.parse_args(); T0 = time.time()
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT
    X = p11.P11(with_fr=False)
    try:
        X.set_base('V1u')
        CH = dict(k11b_reproduced=bool(X.repro))
        A = {}
        for kind in ('T01t', 'BR'):
            for p in PER:
                for lab in LABS + ('up',):
                    a = window_arrays(X, kind, p, lab)
                    if a is not None: A[(kind, p, lab)] = a
        CH['upper_k_free'] = all(np.allclose(a['fb'], a['fb'][0][None, :], rtol=1e-12, atol=0) for (kd, p, lab), a in A.items() if lab == 'up')
        CH['p11'] = repro(X, {k: v for k, v in A.items() if k[2] in LABS})
        print('arrays %.0fs; reproduces p11 V1u: %s' % (time.time() - T0, CH['p11']['ok']), flush=True)
        ms_, vs_, FB, FI = regmap(X)
        CH['p10u'] = regmap_check(ms_, vs_, FB, FI)
        print('regmap %.0fs; reproduces p10u V1u regmap: %s' % (time.time() - T0, CH['p10u']['ok']), flush=True)
        CH['ok'] = bool(CH['k11b_reproduced'] and CH['p11']['ok'] and CH['p10u']['ok'])
        OUT.mkdir(parents=True, exist_ok=True)
        if not CH['ok']:
            (OUT / 'w7.json').write_text(json.dumps(dict(status='withheld: reproduction failure', checks=CH), indent=1, ensure_ascii=False, default=str), encoding='utf-8')
            print('reproduction failed: no values reported'); sys.exit(2)
        RES = dict(checks=CH)
        RES['cross'] = {'%s|%s' % (kind, lab): cross(A, kind, lab) for kind in ('T01t', 'BR') for lab in LABS}
        RES['thr'] = {'%s|%s|%s' % (kind, lab, mode): regions_obs(A, kind, lab, mode) for kind in ('T01t', 'BR') for lab in LABS for mode in ('in', 'head')}
        RES['fit'] = fit_regions(X, ms_, vs_, FB, FI)
        RES['meta'] = dict(prices=PRICES, thresholds=THS, pairs_main=sorted('%s>%s' % x for x in MAIN), head=HEAD,
                           sha256={f: (hashlib.sha256((HERE / f).read_bytes()).hexdigest() if (HERE / f).exists() else 'absent') for f in ('w7.py', 'calc-rules.md')},
                           p11_sha256=hashlib.sha256((J / 'P11_posthoc' / 'p11.py').read_bytes()).hexdigest(),
                           k11b_sha256=hashlib.sha256((J / 'K11' / 'k11b.py').read_bytes()).hexdigest())
        RES = jsonable(RES)
        (OUT / 'w7.json').write_text(json.dumps(RES, indent=1, ensure_ascii=False, allow_nan=True), encoding='utf-8')
        (OUT / 'w7_tables.md').write_text(tables(RES), encoding='utf-8')
        (OUT / 'SHA256SUMS.txt').write_text(''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f)
                                                    for f in ('w7.json', 'w7_tables.md')), encoding='ascii')
        print('wrote', OUT, '%.0fs' % (time.time() - T0))
    finally:
        X.restore()


if __name__ == '__main__':
    main()
