#!/usr/bin/env python3
"""K14 (registered, K14_preregistration.md): fixed-rate sampling variant FR against value-proportional sampling FB.

K11/k11b.py is read and executed unchanged in its own namespace (only its final output write is redirected) and the
reproduction of K11/k11b_output.md is checked byte for byte (P3 calc-rules.md 0.1). FB is the unchanged Grid. FR changes
one input only, the expected sample count n_s of each seller (registration sec. 3):

    FR main : v^ = upper edge of the highest non-empty value bin, p = v^ / (V + v^), p = 1 if that edge is inf
    FR-lo   : v^ = mean amount of that bin (bin USDC / bin sales),   p = v^ / (V + v^)
    FR-eq   : p = min(1, v^_main / V)                                    (sensitivity, sec. 3.2)
    FR-hyb  : sales in bins above V always sampled; sales in bins up to V with p from FR main on those bins only
    n_s^FR = n x p   (FR-hyb: n_>V + n_<=V x p_<=V)

The value bins are the ones t13_entry of k11b.py reads for that seller entry, with the same partial sets
(StableEnrich <= 0.5, Exa <= 0.001, CoinStats <= 0.01). The variant is injected by wrapping the namespace function
t13_sellers while a GridFR instance is being built, so every term that uses self.ns (verify, release REL_K, release
capacity, detincl, frozen, deduction, G_FAIL) moves together, and nothing else changes.

    python3 -I k14.py --out results

The functions above main() are pure and are unit-tested on synthetic bins in test_k14.py.
"""
import argparse, hashlib, json, math, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
K11 = HERE.parent / 'K11'

EDGES0 = [0.0, 0.001, 0.01, 0.1, 0.2, 0.5, 1.0, 5.0, math.inf]      # must equal k11b EDGES (checked in main)
PART0 = {'StableEnrich': 0.5, 'Exa': 0.001, 'CoinStats': 0.01}       # must equal k11b SCANPART (checked in main)
VARS = ('main', 'lo', 'eq', 'hyb')
TH_A = 1.25            # JK14a: sum n_s^FR / sum n_s^FB >= 1.25
TH_B = 0.0025          # JK14b: aggregate cost FR - FB >= 0.25 percentage points
NWIN = 2               # ... in at least two of the three windows
TOL = 1e-12            # same tolerance as k11b ns_group and t13_entry


# ================================================================== pure functions (unit-tested)
def lower_edge(up, edges=EDGES0):
    return edges[edges.index(up) - 1]


def entry_bins(val, p, base, part):
    """The bins t13_entry uses: VAL[(p, seller)], filtered to upper <= part when the entry is a partial set."""
    B = list(val.get((p, base), []))
    if part is not None: B = [b for b in B if b[0] <= part + TOL]
    return B


def fb_ns_from_bins(bins, V, ns_group, edges=EDGES0):
    """FB n_s exactly as t13_entry sums it (same order, same ns_group)."""
    return sum(ns_group(c, u, lower_edge(up, edges), up, V) for up, c, u in bins)


def top_bin(bins):
    """Highest bin (by upper edge) with at least one sale, or None."""
    ne = [b for b in bins if b[1] > 0]
    return max(ne, key=lambda b: b[0]) if ne else None


def vhat_from_bins(bins):
    """(v^_main, v^_lo): upper edge of the highest non-empty bin (may be inf) and the mean amount of that bin."""
    t = top_bin(bins)
    if t is None: return None, None
    up, c, u = t
    return up, u / c


def p_fixed(vhat, V):
    """Equal-bound fixed rate: v^ (1 - p) / p = V  <=>  p = v^ / (V + v^); p = 1 for an unbounded v^."""
    if vhat is None: return 0.0
    if vhat == math.inf: return 1.0
    return vhat / (V + vhat)


def p_eq(vhat, V):
    if vhat is None: return 0.0
    if vhat == math.inf: return 1.0
    return min(1.0, vhat / V)


def split_at_V(bins, V, edges=EDGES0):
    """(bins with upper <= V, bins with lower >= V). A bin straddling V is an error (cannot occur for the k11b EDGES
    and V in {1, 0.2})."""
    lo, hi = [], []
    for b in bins:
        if b[0] <= V + TOL: lo.append(b)
        elif lower_edge(b[0], edges) >= V - TOL: hi.append(b)
        else: raise ValueError('bin (%g, %g] straddles V = %g' % (lower_edge(b[0], edges), b[0], V))
    return lo, hi


def fr_seller(bins, V, edges=EDGES0):
    """All FR quantities of one seller entry from its bins [(upper_edge, count, usdc), ...]."""
    n = float(sum(b[1] for b in bins))
    vm, vl = vhat_from_bins(bins)
    pm, pl, pe = p_fixed(vm, V), p_fixed(vl, V), p_eq(vm, V)
    blo, bhi = split_at_V(bins, V, edges)
    n_hi = float(sum(b[1] for b in bhi)); n_lo = float(sum(b[1] for b in blo))
    vh, _ = vhat_from_bins(blo)
    ph = p_fixed(vh, V)
    return dict(n=n, v_main=vm, v_lo=vl, p_main=pm, p_lo=pl, p_eq=pe, p_hyb_le=ph, n_gtV=n_hi, n_leV=n_lo,
                ns=dict(main=n * pm, lo=n * pl, eq=n * pe, hyb=n_hi + n_lo * ph))


def ns_fr(bins, V, var, edges=EDGES0):
    return fr_seller(bins, V, edges)['ns'][var]


def windows_meeting(vals, pred):
    return sum(1 for v in vals if v is not None and pred(v))


def judge_a(ratios, th=TH_A, need=NWIN):
    """ratios: sum n_s^FR / sum n_s^FB for the three windows."""
    k = windows_meeting(ratios, lambda r: r >= th)
    return dict(windows=k, holds=k >= need, values=list(ratios))


def judge_b(diffs, th=TH_B, need=NWIN):
    """diffs: aggregate cost FR - FB (fraction of revenue) for the three windows."""
    k = windows_meeting(diffs, lambda d: d >= th)
    return dict(windows=k, holds=k >= need, values=list(diffs))


def judge_c(per_window, windows):
    """per_window: {window: {seller: FR - FB}}. Sellers cheaper under FR (diff < 0) in every one of the windows.
    A seller missing from a window cannot be cheaper in all of them and is listed under 'missing'."""
    sellers = sorted(set().union(*[set(per_window[w]) for w in windows]))
    cheaper = [a for a in sellers if all(a in per_window[w] and per_window[w][a] < 0 for w in windows)]
    missing = [a for a in sellers if not all(a in per_window[w] for w in windows)]
    return dict(count=len(cheaper), sellers=cheaper, holds=len(cheaper) == 0, missing=missing)


def agg_cost(tot, R):
    return float(sum(t * r for t, r in zip(tot, R)) / sum(R))


def r3(x):
    """round to three significant digits (for the w* cells of Table 4)"""
    if isinstance(x, str) or x == 0: return x
    return float('%.3g' % x)


def install_fr(g, parts):
    """Wrap g['t13_sellers'] so that, while a GridFR instance is being built, each seller entry of the sets in `parts`
    carries n_s^FR of the requested variant instead of k11b's n_s. Returns (GridFR, INFO); INFO[(set, window, V, label)]
    holds the fr_seller values of every entry seen, with k11b's own n_s as 'ns_fb'. Every call checks that the bins
    give back the entry's n, R and FB n_s exactly, so FR uses the same bins as k11b."""
    orig_t13 = g['t13_sellers']; VAL = g['VAL']; NSG = g['ns_group']; EDG = g['EDGES']
    FRV = {'var': None}
    INFO = {}

    def t13_k14(st, p, V):
        o = orig_t13(st, p, V)
        if st not in parts: return o                    # other sets are untouched
        for e in o:
            B = entry_bins(VAL, p, e['base'], parts[st].get(e['base']))
            assert sum(b[1] for b in B) == e['n'] and abs(sum(b[2] for b in B) - e['R']) < 1e-9, (st, p, e['a'])
            assert fb_ns_from_bins(B, V, NSG, EDG) == e['ns'], (st, p, e['a'])     # same bins as k11b's own n_s
            fr = fr_seller(B, V, EDG); fr['ns_fb'] = e['ns']; fr['bins_n'] = len(B)
            INFO[(st, p, V, e['a'])] = fr
        if FRV['var'] is None: return o
        out = []
        for e in o:
            e2 = dict(e); e2['ns'] = INFO[(st, p, V, e['a'])]['ns'][FRV['var']]; out.append(e2)
        return out
    g['t13_sellers'] = t13_k14

    class GridFR(g['Grid']):
        """Grid with n_s replaced by the FR variant `var`; everything else is the unchanged Grid."""
        def __init__(self, st, V, prm, var):
            assert var in VARS
            self.var = var
            FRV['var'] = var
            try: super().__init__(st, V, prm)
            finally: FRV['var'] = None
    return GridFR, INFO


# ================================================================== main path (real data; run only after sealing)
def main():
    import numpy as np
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    args = ap.parse_args()
    OUT = Path(args.out)
    if not OUT.is_absolute(): OUT = HERE / OUT
    OUT.mkdir(parents=True, exist_ok=True)
    T0 = time.time()

    # ------------------------------------------------------------ run k11b.py unchanged (P3 0.1)
    src = (K11 / 'k11b.py').read_text(encoding='utf-8')
    a1 = "HERE = os.path.dirname(os.path.abspath(__file__))"
    a2 = "open(HERE + '/k11b_output.md', 'w').write(txt)"
    assert src.count(a1) == 1 and src.count(a2) == 1
    src = src.replace(a1, "HERE = %r" % str(K11)).replace(a2, "_K14_TXT = txt")
    g = {'__name__': 'k11b_k14'}
    exec(compile(src, str(K11 / 'k11b.py'), 'exec'), g)
    REPRO = g['_K14_TXT'] == (K11 / 'k11b_output.md').read_text(encoding='utf-8')
    print('k11b_output.md reproduced byte for byte:', REPRO, '%.0fs' % (time.time() - T0), flush=True)
    META = dict(k11b_reproduced=REPRO, k11b_sha256=hashlib.sha256((K11 / 'k11b.py').read_bytes()).hexdigest(),
                k14_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), TH_A=TH_A, TH_B=TH_B, NWIN=NWIN)
    if not REPRO:                                       # registration sec. 2 and 5: stop, report, no judgment
        json.dump(dict(meta=META, verdict='withheld: k11b reproduction failure'), open(OUT / 'k14.json', 'w'), indent=1, ensure_ascii=False)
        print('k11b reproduction failed: no judgment (withheld)'); sys.exit(2)

    assert g['EDGES'] == EDGES0, g['EDGES']
    assert g['SCANPART'] == PART0 and dict(g['T01T_PART'], **g['T01_PART']) == PART0, g['SCANPART']
    KS = g['KS']; W0 = g['W0']; PER = ['busy', 'median', 'quiet']
    assert W0 == 0.00173 and KS == [1, 2, 4, 8, 16, 32]
    PARTS = {'T01t': PART0, 'BR': {}}
    g['set_gas']('new')                                 # the state k11b.py ends in; clears the Grid cache _G as well
    assert not g['_G']

    GridFR, INFO = install_fr(g, PARTS)

    def PRM(lab):
        if lab == 'lo': return g['LOm']('N')
        if lab == 'up': return g['UPm']('N')
        return g['LOm']('N', True)
    LABS = ('lo', 'up', 'fac')

    # ------------------------------------------------------------ cells
    C = {}
    for V in (1.0, 0.2):
        for p in PER:
            for kind in ('T01t', 'BR'):
                st = kind + ':' + p
                for lab in LABS:
                    prm = PRM(lab)
                    fb = g['G'](st, V, prm)
                    if not fb.ok: continue
                    rf = fb.opt(W0)
                    cell = dict(N=fb.N, R=[float(x) for x in fb.R], a=list(fb.a_),
                                fb=dict(tot=[float(x) for x in rf['tot']], k=[int(KS[i]) for i in rf['ki']], agg=rf['agg'],
                                        med=rf['med'], ns=[float(x) for x in fb.ns]))
                    if lab in ('lo', 'up'):
                        ws = fb.wstar('agg'); cell['fb']['wstar'] = ws if isinstance(ws, str) else float(ws)
                    if kind == 'T01t':
                        j = [i for i, a in enumerate(fb.a_) if a.startswith('StableEnrich')][0]
                        cell['fb']['se'] = float(rf['tot'][j]); cell['fb']['se_k'] = int(KS[rf['ki'][j]])
                    for var in VARS:
                        gr = GridFR(st, V, prm, var)
                        assert gr.ok and gr.a_ == fb.a_ and np.array_equal(gr.n, fb.n) and np.array_equal(gr.R, fb.R)
                        assert np.array_equal(gr.cp, fb.cp) and gr.ck == fb.ck
                        r = gr.opt(W0)
                        cell[var] = dict(tot=[float(x) for x in r['tot']], k=[int(KS[i]) for i in r['ki']], agg=r['agg'],
                                         ns=[float(x) for x in gr.ns])
                    cell['sellers'] = []
                    for j, a in enumerate(fb.a_):
                        fr = INFO[(kind, p, V, a)]
                        assert fr['ns_fb'] == cell['fb']['ns'][j]
                        cell['sellers'].append(dict(
                            a=a, ck=fb.ck[j], R=float(fb.R[j]), n=float(fb.n[j]), ns_fb=float(fb.ns[j]),
                            v_main=('inf' if fr['v_main'] == math.inf else fr['v_main']), v_lo=fr['v_lo'], p_main=fr['p_main'], p_lo=fr['p_lo'], p_eq=fr['p_eq'],
                            p_hyb_le=fr['p_hyb_le'], n_gtV=fr['n_gtV'],
                            ns={v: cell[v]['ns'][j] for v in VARS},
                            ratio={v: (cell[v]['ns'][j] / fb.ns[j]) if fb.ns[j] > 0 else None for v in VARS},
                            cost_fb=cell['fb']['tot'][j], k_fb=cell['fb']['k'][j],
                            cost={v: cell[v]['tot'][j] for v in VARS}, k={v: cell[v]['k'][j] for v in VARS},
                            diff={v: cell[v]['tot'][j] - cell['fb']['tot'][j] for v in VARS}))
                    S_fb = float(sum(cell['fb']['ns']))
                    cell['sum'] = dict(ns_fb=S_fb,
                                       ns={v: float(sum(cell[v]['ns'])) for v in VARS},
                                       ratio={v: (float(sum(cell[v]['ns'])) / S_fb) if S_fb > 0 else None for v in VARS},
                                       agg_fb=cell['fb']['agg'], agg={v: cell[v]['agg'] for v in VARS},
                                       diff={v: cell[v]['agg'] - cell['fb']['agg'] for v in VARS},
                                       hyb_eq_main=bool(all(cell['hyb']['ns'][j] == cell['main']['ns'][j] for j in range(fb.N))),
                                       any_gtV=bool(any(s['n_gtV'] > 0 for s in cell['sellers'])))
                    C['%s|%g|%s|%s' % (kind, V, p, lab)] = cell
        print('V', V, '%.0fs' % (time.time() - T0), flush=True)

    # ------------------------------------------------------------ Table 4 check (P3 0.3)
    def rng2(xs): return '%.2f–%.2f' % (100 * min(xs), 100 * max(xs))
    def cl(kind, V, lab, key, per=PER): return [C['%s|%g|%s|%s' % (kind, V, p, lab)]['fb'][key] for p in per]
    EXP = {('agg', 1.0, 'lo'): '4.84–5.97', ('agg', 1.0, 'up'): '6.84–8.51', ('agg', 1.0, 'fac'): '9.79–12.88',
           ('agg', 0.2, 'lo'): '8.05–8.59', ('agg', 0.2, 'up'): '10.20–11.34', ('agg', 0.2, 'fac'): '12.99–15.43',
           ('se', 1.0, 'lo'): '3.67–4.51', ('se', 1.0, 'up'): '4.89–6.04', ('se', 1.0, 'fac'): '7.62–10.25',
           ('med', 1.0, 'lo'): '24.18–73.40', ('med', 1.0, 'up'): '37.80–111.34', ('med', 1.0, 'fac'): '49.44–91.39',
           ('BRagg', 1.0, 'lo'): '33.60–42.05', ('BRagg', 1.0, 'up'): '33.64–42.10', ('BRagg', 1.0, 'fac'): '37.44–55.60'}
    EXPW = {(1.0, 'lo'): (0.0130, 0.0143), (1.0, 'up'): (0.00585, 0.00895), (0.2, 'lo'): (0.00287, 0.00312),
            (0.2, 'up'): (0.00066, 0.00162), ('BR', 1.0, 'lo'): (0.000172, 0.000393), ('BR', 1.0, 'up'): (0.000169, 0.000391)}
    T4 = {}
    for (key, V, lab), want in EXP.items():
        got = rng2(cl('BR', V, lab, 'agg', PER[:2])) if key == 'BRagg' else rng2(cl('T01t', V, lab, key))
        T4['%s|%g|%s' % (key, V, lab)] = dict(want=want, got=got, ok=got == want)
    for kk, want in EXPW.items():
        if kk[0] == 'BR': xs = cl('BR', kk[1], kk[2], 'wstar', PER[:2]); nm = 'BRwstar|%g|%s' % kk[1:]
        else: xs = cl('T01t', kk[0], kk[1], 'wstar'); nm = 'wstar|%g|%s' % kk
        num = all(not isinstance(x, str) for x in xs)
        got = (r3(min(xs)), r3(max(xs))) if num else tuple(xs)
        T4[nm] = dict(want=list(want), got=list(got), ok=num and got == tuple(r3(w) for w in want))
    T4OK = all(v['ok'] for v in T4.values())
    META['table4_ok'] = T4OK

    # ------------------------------------------------------------ judgments (sec. 5): FR main binding, FR-lo reported alongside
    def judgments(var):
        cells = [C['T01t|1|%s|lo' % p] for p in PER]
        ja = judge_a([c['sum']['ratio'][var] for c in cells])
        jb = judge_b([c['sum']['diff'][var] for c in cells])
        jc = judge_c({p: {s['a']: s['diff'][var] for s in C['T01t|1|%s|lo' % p]['sellers']} for p in PER}, PER)
        return dict(JK14a=ja, JK14b=jb, JK14c=jc)
    J = {'main': judgments('main'), 'lo': judgments('lo')}
    if not T4OK:
        J['verdict'] = 'withheld: Table 4 cell mismatch'
    else:
        J['verdict'] = dict(JK14a='holds' if J['main']['JK14a']['holds'] else 'does not hold not',
                            JK14b='holds' if J['main']['JK14b']['holds'] else 'does not hold not',
                            JK14c='holds(0)' if J['main']['JK14c']['holds'] else 'does not hold not(%d)' % J['main']['JK14c']['count'],
                            binding='FR main', FR_lo='for verdicts not used not(side by side recorded)')

    # windows with aggregate <= 10% (sec. 4 item 2)
    LE10 = {}
    for V in (1.0, 0.2):
        for lab in LABS:
            cs = [C['T01t|%g|%s|%s' % (V, p, lab)] for p in PER]
            LE10['%g|%s' % (V, lab)] = dict(fb=sum(c['fb']['agg'] <= 0.10 for c in cs),
                                            **{v: sum(c[v]['agg'] <= 0.10 for c in cs) for v in VARS})

    RES = dict(meta=META, table4=T4, judgments=J, le10=LE10, cells=C)
    json.dump(RES, open(OUT / 'k14.json', 'w'), indent=1, ensure_ascii=False, allow_nan=True)
    (OUT / 'k14_tables.md').write_text(tables(RES, PER), encoding='utf-8')
    sums = ''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in ('k14.json', 'k14_tables.md'))
    (OUT / 'SHA256SUMS.txt').write_text(sums, encoding='ascii')
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


# ================================================================== tables (rounding as P3 0.4)
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
LN = {'lo': 'lower', 'up': 'upper', 'fac': 'facilitator'}
VN = {'main': 'FR main', 'lo': 'FR-lo', 'eq': 'FR-eq', 'hyb': 'FR-hyb'}


def pc(x): return '-' if x is None else '%.2f' % (100 * x)
def pp(x): return '-' if x is None else '%+.2f' % (100 * x)
def rt(x): return '-' if x is None else '%.3f' % x
def vv(x): return '-' if x is None else ('inf' if x in (math.inf, 'inf') else '%.4g' % x)
def pr(x): return '-' if x is None else '%.4g' % x
def nn(x): return format(int(x), ',') if float(x) == int(x) else format(x, ',.1f')


def tables(R, PER):
    L = ['**registration calculation K14 (K14_preregistration.md).** `k14.py` output. mode N, σ 1, r 10%, a 0, w 0.00173, per seller optimal k(per design separately). '
         'costs revenue relative to %, difference FR − FB (%p).\n']
    M = R['meta']
    L.append('k11b_output.md reproduction: %s. Table 4 cell match: %s.\n' % (M['k11b_reproduced'], M['table4_ok']))
    L.append('| Table 4 cell | manuscript | calculation | equal |'); L.append('|---|---|---|---|')
    for k, v in R['table4'].items(): L.append('| %s | %s | %s | %s |' % (k, v['want'], v['got'], v['ok']))
    J = R['judgments']
    L.append('\n## 1. verdict (lower, V 1, six seller sum)\n')
    L.append('overall: %s\n' % (J['verdict'] if isinstance(J['verdict'], str) else ', '.join('%s %s' % kv for kv in J['verdict'].items())))
    L.append('| verdict | variant | per window value (busy, median, quiet) | threshold over window count | holds |'); L.append('|---|---|---|---|---|')
    for var, tag in (('main', 'FR main (verdict)'), ('lo', 'FR-lo (for verdicts not used not)')):
        a, b, c = J[var]['JK14a'], J[var]['JK14b'], J[var]['JK14c']
        L.append('| JK14a Σn_s^FR/Σn_s^FB ≥ 1.25 | %s | %s | %d | %s |' % (tag, ', '.join(rt(x) for x in a['values']), a['windows'], a['holds']))
        L.append('| JK14b sum cost difference ≥ 0.25%%p | %s | %s | %d | %s |' % (tag, ', '.join(pp(x) for x in b['values']), b['windows'], b['holds']))
        L.append('| JK14c three window all FR cheaper seller count = 0 | %s | %d persons: %s%s | - | %s |' % (
            tag, c['count'], ', '.join(c['sellers']) or 'none', ('; window missing seller ' + ', '.join(c['missing'])) if c['missing'] else '', c['holds']))
    L.append('\n## 2. six seller sum\n')
    L.append('| V | case | window | Σn_s FB | Σn_s FR main | ratio main | Σn_s FR-lo | ratio lo | sum FB | sum FR main | difference main | sum FR-lo | difference lo |')
    L.append('|' + '---|' * 13)
    for V in (1.0, 0.2):
        for lab in ('lo', 'up', 'fac'):
            for p in PER:
                s = R['cells']['T01t|%g|%s|%s' % (V, p, lab)]['sum']
                L.append('| %g | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
                    V, LN[lab], WN[p], nn(round(s['ns_fb'], 1)), nn(round(s['ns']['main'], 1)), rt(s['ratio']['main']),
                    nn(round(s['ns']['lo'], 1)), rt(s['ratio']['lo']), pc(s['agg_fb']), pc(s['agg']['main']), pp(s['diff']['main']),
                    pc(s['agg']['lo']), pp(s['diff']['lo'])))
    L.append('\nsum ≤ 10% window count (three window among)\n')
    L.append('| V | case | FB | FR main | FR-lo | FR-eq | FR-hyb |'); L.append('|---|---|---|---|---|---|---|')
    for k, v in R['le10'].items():
        V, lab = k.split('|')
        L.append('| %s | %s | %d | %d | %d | %d | %d |' % (V, LN[lab], v['fb'], v['main'], v['lo'], v['eq'], v['hyb']))

    def seller_table(kind, title):
        L.append('\n## %s\n' % title)
        L.append('| V | case | window | seller | n | n_s FB | v̂ main | v̂ lo | p main | p lo | n_s FR main | n_s FR-lo | ratio main | ratio lo | FB (k) | FR main (k) | difference main | cheaper side main | FR-lo (k) | difference lo | cheaper side lo |')
        L.append('|' + '---|' * 21)
        for V in (1.0, 0.2):
            for lab in ('lo', 'up', 'fac'):
                for p in PER:
                    key = '%s|%g|%s|%s' % (kind, V, p, lab)
                    if key not in R['cells']: L.append('| %g | %s | %s | (seller none) |' % (V, LN[lab], WN[p]) + ' |' * 17); continue
                    for s in R['cells'][key]['sellers']:
                        ch = lambda v: 'FR' if s['diff'][v] < 0 else ('equal' if s['diff'][v] == 0 else 'FB')
                        L.append('| %g | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s (%d) | %s (%d) | %s | %s | %s (%d) | %s | %s |' % (
                            V, LN[lab], WN[p], s['a'], nn(s['n']), nn(round(s['ns_fb'], 1)), vv(s['v_main']), vv(s['v_lo']),
                            pr(s['p_main']), pr(s['p_lo']), nn(round(s['ns']['main'], 1)), nn(round(s['ns']['lo'], 1)),
                            rt(s['ratio']['main']), rt(s['ratio']['lo']), pc(s['cost_fb']), s['k_fb'], pc(s['cost']['main']), s['k']['main'],
                            pp(s['diff']['main']), ch('main'), pc(s['cost']['lo']), s['k']['lo'], pp(s['diff']['lo']), ch('lo')))
    seller_table('T01t', '3. per seller (six data seller)')
    seller_table('BR', '4. BlockRun (separately)')
    L.append('\n## 5. sensitivity FR-eq, FR-hyb (for verdicts not used not; lower, V 1, six seller sum)\n')
    L.append('| window | Σn_s FB | Σn_s FR-eq | ratio eq | sum FB | sum FR-eq | difference eq | Σn_s FR-hyb | ratio hyb | sum FR-hyb | difference hyb | V over sales present | FR-hyb = FR main |')
    L.append('|' + '---|' * 13)
    for p in PER:
        s = R['cells']['T01t|1|%s|lo' % p]['sum']
        L.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            WN[p], nn(round(s['ns_fb'], 1)), nn(round(s['ns']['eq'], 1)), rt(s['ratio']['eq']), pc(s['agg_fb']), pc(s['agg']['eq']),
            pp(s['diff']['eq']), nn(round(s['ns']['hyb'], 1)), rt(s['ratio']['hyb']), pc(s['agg']['hyb']), pp(s['diff']['hyb']),
            'present' if s['any_gtV'] else 'none', 'equal' if s['hyb_eq_main'] else 'differs'))
    return '\n'.join(L) + '\n'


if __name__ == '__main__':
    main()
