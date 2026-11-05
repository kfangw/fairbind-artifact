#!/usr/bin/env python3
"""P10u (post hoc, calc-rules.md): P10's analyses A and B with the real-USDC release and anchor constants (V1u of
P11) next to the mock-token constants (V1).

P10_fit-conditions/p10.py and P11_posthoc/p11.py are imported for their functions and constants only; their main() is not
run. The constants are switched through the module variables p9.REL_MEAS, p9.ANC_MEAS, p10.REL, p10.ANC (as P11
does) and k11b's Grid cache is cleared. No file outside this folder is written.

    python3 -I p10u.py --out results
"""
import argparse, hashlib, importlib.util, json, math, shutil, sys, tempfile, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent
for _d in (J / 'P9_posthoc', J / 'P10_fit-conditions', J / 'P11_posthoc', J / 'P6_posthoc'):
    if str(_d) not in sys.path: sys.path.insert(0, str(_d))
import p9    # noqa: E402
import p10   # noqa: E402
import p11   # noqa: E402

P10J = J / 'P10_fit-conditions' / 'results' / 'p10.json'
P11J = J / 'P11_posthoc' / 'results' / 'p11.json'
P9J = J / 'P9_posthoc' / 'results' / 'p9.json'
REDRAW = J.parent / 'figures' / 'fig_fit_redraw.py'
CONSTS = {'V1': (p11.REL_MEAS_V1, p11.ANC_MEAS_V1), 'V1u': (p11.REL_MEAS_U, p11.ANC_MEAS_U)}
LABS = p10.LABS
REL_TOL = 1e-12


def set_base(M, name):
    rel, anc = CONSTS[name]
    p9.REL_MEAS = rel; p9.ANC_MEAS = anc; p10.REL = rel; p10.ANC = anc
    M.g['_G'].clear()


def restore(M):
    set_base(M, 'V1')


def jsonable(x): return json.loads(json.dumps(x, allow_nan=True, ensure_ascii=False))


def tdiff(a, b, path=''):
    """(largest relative-or-absolute float difference, list of mismatching paths); ints, str, bool exact."""
    if isinstance(a, bool) or isinstance(b, bool) or isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return (0.0, []) if a == b else (math.inf, [path])
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, int) and isinstance(b, int): return (0.0, []) if a == b else (math.inf, [path])
        a, b = float(a), float(b)
        if math.isnan(a) and math.isnan(b): return 0.0, []
        if a == b: return 0.0, []
        d = min(abs(a - b), abs(a - b) / max(abs(a), abs(b)))
        return (d, []) if d <= REL_TOL else (d, [path])
    if isinstance(a, dict) and isinstance(b, dict):
        if set(a) != set(b): return math.inf, [path + ' keys']
        mx, bad = 0.0, []
        for k in a:
            d, bb = tdiff(a[k], b[k], path + '/' + str(k)); mx = max(mx, d); bad += bb
        return mx, bad
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b): return math.inf, [path + ' len']
        mx, bad = 0.0, []
        for i, (x, y) in enumerate(zip(a, b)):
            d, bb = tdiff(x, y, path + '[%d]' % i); mx = max(mx, d); bad += bb
        return mx, bad
    return math.inf, [path + ' type']


# ================================================================== P10's main() sequence for one base
def p10_outputs(M, cells):
    """The outputs of p10.main() (calc-rules.md 1.1) under the constants now set; cells are the P9-path seller costs."""
    R = {}
    TT = []
    for lab in LABS:
        for v in p10.VGRID:
            for d in (1.0, 0.1):
                TT.append(p10.thresholds(M, v, lab, d))
    R['thresholds'] = TT
    R['closed_form'] = [dict(lab=lab, v=v, k=k, th=th, **p10.closed_form_threshold(M, v, lab, k, th))
                        for lab in ('lo',) for v in (0.02, 0.05, 0.1, 0.2) for k in (1, 8, 32) for th in p10.TH]
    curves = {}
    for v in (0.001, 0.01, 0.1):
        xs = np.logspace(math.log10(v), math.log10(3e2), 160)
        ev = [p10.share_at(M, x, v, 'lo') for x in xs]
        curves[v] = (xs, np.array([e['fb'] for e in ev]), np.array([e['fi'] for e in ev]))
    R['curves'] = {str(v): dict(Re=c[0].tolist(), fb=c[1].tolist(), fi=c[2].tolist()) for v, c in curves.items()}
    ms_ = np.logspace(0, 4, 97); vs_ = np.logspace(-3.5, 0.5, 81)
    Z = np.zeros((len(vs_), len(ms_))); F = np.zeros_like(Z)
    for i, v in enumerate(vs_):
        for j, m in enumerate(ms_):
            e = p10.evaluate(M, p10.stylised(m, v), 21, 'lo')
            F[i, j] = e['fb']
            Z[i, j] = 0 if (e['fb'] <= e['fi'] and e['fb'] <= 0.10) else (1 if (e['fi'] < e['fb'] and e['fi'] <= 0.10) else 2)
    R['regmap'] = dict(m=ms_.tolist(), v=vs_.tolist(), Z=Z.tolist(), fb=F.tolist())
    obs = []
    for p, kind, s in p10.observed(M):
        days = M.g['PDAYS'][p]
        for lab in LABS:
            e = p10.evaluate(M, s, days, lab); c = cells['%s|1|%s|%s' % (kind, p, lab)]
            sty = p10.share_at(M, s['R'] / e['E0'], s['R'] / s['n'], lab, d=e['E0'] / (days * 144), days=days)
            obs.append(dict(win=p, kind=kind, seller=s['a'], short=p10.SHORT[s['base']], lab=lab, R=s['R'], n=s['n'], E0=e['E0'],
                            Re=s['R'] / e['E0'], m=s['n'] / e['E0'], v=s['R'] / s['n'], k=e['kfb'], Rk=s['R'] / e['Ek'],
                            fb=c['per'][s['a']][0], fi=c['fi_per'][s['a']][0], kfi=c['fi_per'][s['a']][1],
                            fb_closed=e['fb'], fi_closed=e['fi'], fb_stylised=sty['fb'], fi_stylised=sty['fi'],
                            parts=e['fbparts'], fiparts=e['fiparts']))
    R['observed'] = obs
    REG = {}
    for lab in LABS:
        REG[lab], per = p10.region_counts(M, lab)
        if lab == 'lo': R['recipients_lo'] = {p: [list(r) for r in rows] for p, rows in per.items()}
    R['regions'] = REG
    R['margins'] = p10.margins(M)
    return jsonable(R), curves, (ms_, vs_, Z, F)


# ================================================================== derived values (calc-rules.md 1.2)
def min_gap(M, v, d):
    """Least FairBind - FI over R_e in [v, 1e5] (p10 scan grid, refined by golden section around the grid minimum)."""
    f = lambda Re: (lambda e: e['fb'] - e['fi'])(p10.share_at(M, Re, v, 'lo', d))
    xs, ys = p10.scan(f, v, 1e5)
    i = int(np.argmin(ys)); a = math.log(xs[max(i - 1, 0)]); b = math.log(xs[min(i + 1, len(xs) - 1)])
    g = (math.sqrt(5) - 1) / 2; c1 = b - g * (b - a); c2 = a + g * (b - a); f1 = f(math.exp(c1)); f2 = f(math.exp(c2))
    for _ in range(50):
        if f1 < f2: b, c2, f2 = c2, c1, f1; c1 = b - g * (b - a); f1 = f(math.exp(c1))
        else: a, c1, f1 = c1, c2, f2; c2 = a + g * (b - a); f2 = f(math.exp(c2))
    return min(float(ys.min()), f1, f2)


def fi_edge(M, d, lo, hi, it=30):
    """Mean sale above which FI is cheaper at every R_e (min gap > 0)."""
    assert min_gap(M, lo, d) <= 0 < min_gap(M, hi, d)
    for _ in range(it):
        mid = math.sqrt(lo * hi)
        if min_gap(M, mid, d) <= 0: lo = mid
        else: hi = mid
    return math.sqrt(lo * hi)


def derived(M, R):
    D = {}
    TT = {(t['lab'], t['v'], t['d']): t for t in R['thresholds']}
    def rng(xs, dr): return [x['Re'] for x in xs if x['dir'] == dr]
    rows = {}
    for v in (0.001, 0.01, 0.02, 0.05, 0.1, 1.0):
        t = TT[('lo', v, 1.0)]
        rows[str(v)] = dict(th10_down=rng(t['th0.1'], 'down'), th10_up=rng(t['th0.1'], 'up'), below10=t['below_at_lo_0.1'],
                            th5_down=rng(t['th0.05'], 'down'), th5_up=rng(t['th0.05'], 'up'), below5=t['below_at_lo_0.05'],
                            min_fb=t['min_fb'], cross=[(x['Re'], x['dir'], x['m']) for x in t['cross']], fb_cheaper_at_lo=t['fb_cheaper_at_lo'])
    D['table10A'] = rows
    t = TT[('lo', 0.1, 0.1)]
    D['d01_v01_th10'] = dict(down=rng(t['th0.1'], 'down'), up=rng(t['th0.1'], 'up'), cross=[(x['Re'], x['dir']) for x in t['cross']])
    cf = {(c['v'], c['k'], c['th']): c for c in R['closed_form']}
    D['c'] = {str(k): cf[(0.1, k, 0.1)]['c'] for k in (1, 8, 32)}
    D['b'] = cf[(0.1, 1, 0.1)]['b']; D['a'] = cf[(0.1, 1, 0.1)]['a']
    D['edge10'] = D['b'] / (0.10 - D['a']); D['edge5'] = D['b'] / (0.05 - D['a'])
    D['lower_cross_m'] = {str(v): TT[('lo', v, 1.0)]['cross'][0]['m'] for v in (0.001, 0.002, 0.005, 0.01, 0.02)}
    Z = np.array(R['regmap']['Z']); ms_ = np.array(R['regmap']['m']); vs_ = np.array(R['regmap']['v'])
    ii, jj = np.nonzero(Z == 0)
    D['joint'] = dict(m_min=float(ms_[jj].min()), m_max=float(ms_[jj].max()), v_min=float(vs_[ii].min()), v_max=float(vs_[ii].max()), cells=int(len(ii)))
    D['joint_by_v'] = {}
    for v in (0.0175, 0.02, 0.025, 0.03, 0.035, 0.04):     # P10_independent-check.md 3.4: the m range of the joint region per v
        t = p10.thresholds(M, v, 'lo', 1.0)
        dn = [x['Re'] for x in t['th0.1'] if x['dir'] == 'down']; up = [x['Re'] for x in t['th0.1'] if x['dir'] == 'up']
        cd = [x['Re'] for x in t['cross'] if x['dir'].startswith('FairBind')]; cu = [x['Re'] for x in t['cross'] if x['dir'].startswith('FI')]
        if dn and up and cd:
            lo_ = max(dn[0], cd[0]); hi_ = min(up[0], cu[0] if cu else math.inf)
            D['joint_by_v'][str(v)] = [lo_ / v, hi_ / v] if lo_ < hi_ else None
        else:
            D['joint_by_v'][str(v)] = None
    rg = R['regions']['lo']
    D['payees'] = {}
    for p in ('busy', 'median'):
        big = [100 * (r[5] - r[4]) for r in R['recipients_lo'][p] if r[6] == 'A' and r[0].startswith('0x') and r[3] > p10.V]
        D['payees'][p] = dict(A_n=rg[p]['evm']['counts']['A']['n'], A_share=rg[p]['evm']['counts']['A']['share'],
                              vle_n=rg[p]['evm_vle']['counts']['A']['n'], vle_share=rg[p]['evm_vle']['counts']['A']['share'],
                              B_share=rg[p]['evm_vle']['counts']['B']['share'], N=rg[p]['evm']['N'], N_vle=rg[p]['evm_vle']['N'],
                              big_n=len(big), big_med=float(np.median(big)), big_min=float(min(big)), big_max=float(max(big)))
    ob = R['observed']
    dd = [abs(o['fb_stylised'] - o['fb']) for o in ob]
    br = [o for o in ob if o['kind'] == 'BR' and o['win'] == 'median' and o['lab'] == 'lo'][0]
    D['stylised_vs_obs'] = dict(within=sum(1 for x in dd if x <= p10.TOL_PT / 100), cells=len(dd), max_pt=100 * max(dd),
                                br_median_obs=br['fb'], br_median_sty=br['fb_stylised'])
    D['table10B'] = {}
    for o in ob:
        if o['lab'] != 'lo': continue
        reg = 'FB' if (o['fb'] <= o['fi'] and o['fb'] <= 0.10) else ('FI' if (o['fi'] < o['fb'] and o['fi'] <= 0.10) else
                                                                      ('--(FB)' if o['fb'] <= o['fi'] else '--(FI)'))
        D['table10B']['%s|%s' % (o['seller'], o['win'])] = reg
    return D


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    args = ap.parse_args(); T0 = time.time()
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT; OUT.mkdir(parents=True, exist_ok=True)
    P10R = json.load(open(P10J, encoding='utf-8'))
    P11R = json.load(open(P11J, encoding='utf-8'))
    cells = {'V1': json.load(open(P9J, encoding='utf-8'))['variants']['V1'], 'V1u': P11R['bases']['V1u']['p9cells']}
    M = p10.Model(); p10._ADDR = dict(M.g['ADDR'])
    CH = {}
    res, curves, regmaps = {}, {}, {}
    try:
        # ---- V1
        set_base(M, 'V1')
        CH['p10_check_V1'] = bool(p10.check(M)['ok'])
        res['V1'], curves['V1'], regmaps['V1'] = p10_outputs(M, cells['V1'])
        keys = ('thresholds', 'curves', 'regmap', 'regions', 'recipients_lo', 'margins')
        rep = {}
        for k in keys:
            mx, bad = tdiff(res['V1'][k], P10R[k]); rep[k] = dict(max=mx, bad=bad[:5], n_bad=len(bad))
        oA = [{k: o[k] for k in P10R['observed'][0]} for o in res['V1']['observed']]
        mx, bad = tdiff(oA, P10R['observed']); rep['observed'] = dict(max=mx, bad=bad[:5], n_bad=len(bad))
        # p10.json's closed_form predates the MC fix of b (P10 results.md check applied 4): a and c are compared to p10.json,
        # the whole block through the re-issued p10_tables.md (results.md deviation 1)
        cfA = [{k: c[k] for k in ('lab', 'v', 'k', 'th', 'a', 'c')} for c in res['V1']['closed_form']]
        cfB = [{k: c[k] for k in ('lab', 'v', 'k', 'th', 'a', 'c')} for c in P10R['closed_form']]
        mx, bad = tdiff(cfA, cfB); rep['closed_form_a_c'] = dict(max=mx, bad=bad[:5], n_bad=len(bad))
        c1 = p10.check(M, verbose=False); set_base(M, 'V1')
        RT1 = dict(res['V1']); RT1['meta'] = dict(check={k: v for k, v in c1.items() if k != 'rows'})
        same = p10.tables(RT1) == (J / 'P10_fit-conditions' / 'results' / 'p10_tables.md').read_text(encoding='utf-8')
        rep['p10_tables_md_text'] = dict(max=0.0 if same else math.inf, bad=[] if same else ['text'], n_bad=0 if same else 1)
        CH['V1_reproduces_p10'] = rep
        CH['V1_ok'] = all(r['n_bad'] == 0 for r in rep.values())
        print('V1 done %.0fs, reproduces p10.json: %s' % (time.time() - T0, CH['V1_ok']), flush=True)
        res['V1_derived'] = derived(M, res['V1'])
        res['V1_derived']['fi_edge_d1'] = fi_edge(M, 1.0, 0.02, 0.06)
        res['V1_derived']['fi_edge_d01'] = fi_edge(M, 0.1, 0.05, 0.3)
        print('V1 derived %.0fs' % (time.time() - T0), flush=True)
        # ---- V1u
        set_base(M, 'V1u')
        tmp = Path(tempfile.mkdtemp())
        (tmp / 'p9u.json').write_text(json.dumps({'variants': {'V1': cells['V1u']}}), encoding='utf-8')
        old = p10.P9J; p10.P9J = tmp / 'p9u.json'
        try:
            cu = p10.check(M)
        finally:
            p10.P9J = old
        set_base(M, 'V1u')
        CH['V1u_closed_vs_p11'] = {k: v for k, v in cu.items() if k != 'rows'}
        CH['V1u_closed_ok'] = bool(cu['ok'] and cu['kdiff'] == 0 and cu['syn_kdiff'] == 0)
        res['V1u'], curves['V1u'], regmaps['V1u'] = p10_outputs(M, cells['V1u'])
        TT = {(t['lab'], t['v'], t['d']): t for t in res['V1u']['thresholds']}
        thr = {}
        for v in (0.1, 0.02):
            a = {k: TT[('lo', v, 1.0)][k] for k in P11R['bases']['V1u']['thresholds']['%g|w0' % v]}
            b = P11R['bases']['V1u']['thresholds']['%g|w0' % v]
            global REL_TOL
            old_tol = REL_TOL; REL_TOL = 1e-9
            mx, bad = tdiff(a, b); REL_TOL = old_tol
            thr[str(v)] = dict(max=mx, bad=bad)
        CH['V1u_thresholds_vs_p11'] = thr
        CH['V1u_thr_ok'] = all(not x['bad'] for x in thr.values())
        CH['margins_same'] = tdiff(res['V1u']['margins'], res['V1']['margins'])[0] == 0.0
        print('V1u done %.0fs' % (time.time() - T0), flush=True)
        res['V1u_derived'] = derived(M, res['V1u'])
        res['V1u_derived']['fi_edge_d1'] = fi_edge(M, 1.0, 0.02, 0.06)
        res['V1u_derived']['fi_edge_d01'] = fi_edge(M, 0.1, 0.05, 0.3)
        print('V1u derived %.0fs' % (time.time() - T0), flush=True)
        # ---- tables and figures for V1u
        CH['ok'] = bool(CH['p10_check_V1'] and CH['V1_ok'] and CH['V1u_closed_ok'] and CH['V1u_thr_ok'] and CH['margins_same'])
        meta = dict(checks=CH, consts={k: jsonable(v) for k, v in CONSTS.items()},
                    sha256={f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in (Path(__file__), P10J, P11J, P9J, J / 'P10_fit-conditions' / 'p10.py', J / 'P11_posthoc' / 'p11.py')})
        if not CH['ok']:
            (OUT / 'p10u.json').write_text(json.dumps(dict(status='withheld: reproduction failure', meta=meta), indent=1, ensure_ascii=False, default=str), encoding='utf-8')
            print('reproduction failed: no values reported'); sys.exit(1)
        out = dict(meta=meta, V1=res['V1'], V1u=res['V1u'], derived=dict(V1=res['V1_derived'], V1u=res['V1u_derived']))
        with open(OUT / 'p10u.json', 'w') as fh: json.dump(out, fh, indent=1, ensure_ascii=False, allow_nan=True)
        RT = dict(res['V1u']); RT['meta'] = dict(check=dict(max_fb=cu['max_fb'], max_fi=cu['max_fi'], kdiff=cu['kdiff'], syn_max=cu['syn_max'], syn_kdiff=cu['syn_kdiff']))
        txt = p10.tables(RT).replace('P9 V1(measured VRF, release, anchor)', 'P11 V1u(measured VRF, real USDC release and anchor)', 1).replace(
            'observed seller closed form vs p9.json V1', 'observed seller closed form vs p11.json V1u p9cells', 1).replace('## 2. observed seller (V1, V 1)', '## 2. observed seller (V1u, V 1)', 1)
        (OUT / 'p10u_tables.md').write_text(txt, encoding='utf-8')
        figd = Path(tempfile.mkdtemp())
        p10.figure(M, curves['V1u'], res['V1u']['observed'], regmaps['V1u'], figd)
        shutil.copy(figd / 'fig_fit.pdf', OUT / 'fig_fit_v1u.pdf'); shutil.copy(figd / 'fig_fit.png', OUT / 'fig_fit_v1u.png')
        # manuscript redraw (file unchanged; input and output paths switched)
        src = figd / 'p10_v1u.json'
        src.write_text(json.dumps(dict(curves=res['V1u']['curves'], regmap=res['V1u']['regmap'], observed=res['V1u']['observed'])), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('fig_fit_redraw_p10u', REDRAW); rd = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rd); rd.SRC = src; rd.HERE = figd / 'ms'; rd.HERE.mkdir()
        rd.main(); shutil.copy(rd.HERE / 'fig_fit.pdf', OUT / 'fig_fit_v1u_ms.pdf')
    finally:
        restore(M)
    files = ('p10u.json', 'p10u_tables.md', 'fig_fit_v1u.pdf', 'fig_fit_v1u.png', 'fig_fit_v1u_ms.pdf')
    (OUT / 'SHA256SUMS.txt').write_text(''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f) for f in files), encoding='ascii')
    print('wrote', OUT, '%.0fs' % (time.time() - T0))


if __name__ == '__main__':
    main()
