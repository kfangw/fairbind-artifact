#!/usr/bin/env python3
"""C34 (post hoc, calc-rules.md 1): StableEnrich's proof call priced at the 36,440-gas enclave-receipt sketch (with its
L1 fee, as BlockRun is priced) instead of the measured tier-1a call of 86,824 gas; FairBind against full inspection
(FI) in three windows, lower, upper and facilitator-gas estimates, same call and own call.

P11_posthoc/p11.py is imported for its functions only (its main() is not run); set_base('V1u') gives the manuscript's
measured-gas cost. No file outside this folder is written.

    python3 -I c34.py --out results
"""
import argparse, hashlib, json, sys, time
from pathlib import Path
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
J = HERE.parent                                          # docs/11_journal
for _d in (J / 'P9_posthoc', J / 'P10_fit-conditions', J / 'P11_posthoc', J / 'P6_posthoc'):
    if str(_d) not in sys.path: sys.path.insert(0, str(_d))
import p9    # noqa: E402,F401
import p11   # noqa: E402

P11J = J / 'P11_posthoc' / 'results' / 'p11.json'
PER = ('busy', 'median', 'quiet')
LABS = ('lo', 'up', 'fac')
TH = 0.10
TOL = 1e-12
G_OWN = (p11.FI_POINTS['own_a'], p11.FI_POINTS['own_bind_b'])            # 45,615 and 81,311
assert G_OWN == (45_615, 81_311)
KEEP = (p11.OWN_KEEP[0], p11.OWN_KEEP[1] + p11.BIND)                    # 14,300 and 49,996 (FI bookkeeping)
assert KEEP == (14_300, 49_996) and p11.FB_SHARE == 55_509
MANU_B = {'busy': ((4.31, 6.56), (11.25, 14.06)), 'median': ((4.44, 6.80), (30.90, 34.75)),
          'quiet': ((6.53, 9.82), (21.45, 25.47))}                         # manuscript tab:cost (B), StableEnrich; six


def is_se(nm): return nm.startswith('StableEnrich')


def scen(prm, names, ck, cp, variant):
    ck = list(ck); cp = np.asarray(cp, float).copy()
    se = [i for i, n in enumerate(names) if is_se(n)]; assert len(se) == 1; s = se[0]
    if variant == 'base':
        fb = cp.copy(); same = cp.copy()
        own = [p11.cp_shift(prm.gusd, ck, cp, g) for g in G_OWN]
        return dict(fb=fb, same=same, own_a=own[0], own_b=own[1], se_gas=dict(fb=p11.G_FB_1A, same=p11.G_FB_1A, own=list(G_OWN)))
    tee = prm.cpu('TEE')
    ck2 = ck.copy(); ck2[s] = 'TEE'; cp2 = cp.copy(); cp2[s] = tee
    if variant == 'T':
        own = [p11.cp_shift(prm.gusd, ck2, cp2, g) for g in G_OWN]          # TEE entry unchanged (P3 FI-min)
        assert all(o[s] == tee for o in own)
        return dict(fb=cp2.copy(), same=cp2.copy(), own_a=own[0], own_b=own[1],
                    se_gas=dict(fb=36_440, same=36_440, own=[36_440, 36_440]))
    if variant == 'W':
        w = p11.cp_teeW(prm.gusd, ck2, cp2)
        own = [p11.cp_shift(prm.gusd, ck2, cp2, g) for g in G_OWN]
        for o, kk in zip(own, KEEP): o[s] = tee + prm.gusd(kk)
        return dict(fb=w.copy(), same=w.copy(), own_a=own[0], own_b=own[1],
                    se_gas=dict(fb=36_440 + p11.FB_SHARE, same=36_440 + p11.FB_SHARE, own=[36_440 + k for k in KEEP]))
    raise ValueError(variant)


def cell(X, p, lab, variant):
    env = X.env; W = X.g['W0']; KS = list(X.g['KS'])
    fb = env.fb('T01t:' + p, 1.0, lab); fi = env.fi('T01t:' + p, lab)
    assert fb.ok and list(fb.a_) == list(fi.a_) and list(fb.ck) == list(fi.ck) and np.array_equal(fb.cp, fi.cp)
    names = list(fb.a_); R = np.asarray(fb.R, float); RT = float(R.sum()); prm = fb.prm
    P = scen(prm, names, fb.ck, fb.cp, variant)
    tb = fb.total(W) - fb.c0parts['verify'] + (P['fb'] * fb.ns / fb.R)[None, :]
    out = dict(names=names, R=R.tolist(), se_gas=P['se_gas'])
    kb = np.argmin(tb, axis=0); j = np.arange(len(names)); xb = tb[kb, j]
    out['fb'] = dict(per={n: [float(xb[i]), KS[kb[i]]] for i, n in enumerate(names)}, agg=float((xb * R).sum() / RT))
    for pr in ('same', 'own_a', 'own_b'):
        tf = fi.total(W) - fi.c0parts['verify'] + (P[pr] * fi.n / fi.R)[None, :]
        kf = np.argmin(tf, axis=0); xf = tf[kf, j]
        cheaper_fi = [i for i in range(len(names)) if xf[i] < xb[i]]
        out[pr] = dict(per={n: [float(xf[i]), KS[kf[i]]] for i, n in enumerate(names)}, agg=float((xf * R).sum() / RT),
                       fi_cheaper_n=len(cheaper_fi), fi_cheaper_share=float(sum(R[i] for i in cheaper_fi) / RT),
                       min_design=float((np.minimum(xb, xf) * R).sum() / RT),
                       agg_wo_os=float(sum(xf[i] * R[i] for i in range(len(names)) if names[i] != 'OneSource') /
                                       sum(R[i] for i in range(len(names)) if names[i] != 'OneSource')),
                       region={n: p11.region(float(xb[i]), float(xf[i]), TH) for i, n in enumerate(names)})
    out['fb']['agg_wo_os'] = float(sum(xb[i] * R[i] for i in range(len(names)) if names[i] != 'OneSource') /
                                   sum(R[i] for i in range(len(names)) if names[i] != 'OneSource'))
    s = [n for n in names if is_se(n)][0]
    out['se'] = dict(name=s, fb=out['fb']['per'][s], **{pr: out[pr]['per'][s] for pr in ('same', 'own_a', 'own_b')})
    # calc-rules 1.4 (4): the replaced price equals prm.cpu('TEE') and BlockRun's
    if variant == 'T':
        br = env.fb('BR:' + p, 1.0, lab)
        out['tee_check'] = bool(P['fb'][names.index(s)] == prm.cpu('TEE') and (not br.ok or float(br.cp[0]) == prm.cpu('TEE')))
    return out


def checks(X, C):
    P = json.load(open(P11J, encoding='utf-8'))['bases']['V1u']['p9cells']
    mx = 0.0; kbad = 0; n = 0
    for p in PER:
        for lab in LABS:
            c = P['T01t|1|%s|%s' % (p, lab)]; b = C[('base', p, lab)]
            mx = max(mx, abs(b['fb']['agg'] - c['agg'])); n += 1
            for nm in b['names']:
                mx = max(mx, abs(b['fb']['per'][nm][0] - c['per'][nm][0]), abs(b['same']['per'][nm][0] - c['fi_per'][nm][0]))
                kbad += int(b['fb']['per'][nm][1] != c['per'][nm][1]) + int(b['same']['per'][nm][1] != c['fi_per'][nm][1]); n += 1
    manu = True; got = {}
    for p in PER:
        b = C[('base', p, 'lo')]
        se = (round(100 * b['se']['own_a'][0], 2), round(100 * b['se']['own_b'][0], 2))
        six = (round(100 * b['own_a']['agg'], 2), round(100 * b['own_b']['agg'], 2))
        got[p] = dict(se=se, six=six); manu &= (se == MANU_B[p][0] and six == MANU_B[p][1])
    tee = all(v.get('tee_check', True) for k, v in C.items())
    return dict(p11_maxdiff=mx, p11_kdiff=kbad, p11_cells=n, p11_ok=bool(mx <= TOL and kbad == 0),
                manuscript_B=got, manuscript_B_ok=bool(manu), tee_ok=bool(tee))


def pc(x): return '%.2f' % (100 * x)


def tables(C):
    L = ['# C34 Table (automatically generated)', '']
    for lab in LABS:
        L += ['## %s estimated' % dict(lo='lower', up='upper', fac='facilitator gas')[lab], '',
              '| price | window | SE gas (FB / FI same / FI own) | SE FB (k) | SE FI same (k) | SE FI own a | SE FI own b | SE region (same / a / b) | six FB | six FI same | six FI own a~b | FI cheaper seller count; share (same / a / b) | more cheaper design sum (same / a / b) | OneSource without FB / FI same / FI own a~b |',
              '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
        for v in ('base', 'T', 'W'):
            for p in PER:
                c = C[(v, p, lab)]; s = c['se']; g = c['se_gas']
                L.append('| %s | %s | %s / %s / %s | %s (%d) | %s (%d) | %s | %s | %s / %s / %s | %s | %s | %s~%s | %d; %s / %d; %s / %d; %s | %s / %s / %s | %s / %s / %s~%s |' % (
                    dict(base='reference 86,824', T='T 36,440', W='W 91,949')[v], p, format(g['fb'], ','), format(g['same'], ','),
                    '~'.join(format(x, ',') for x in g['own']),
                    pc(s['fb'][0]), s['fb'][1], pc(s['same'][0]), s['same'][1], pc(s['own_a'][0]), pc(s['own_b'][0]),
                    c['same']['region'][s['name']], c['own_a']['region'][s['name']], c['own_b']['region'][s['name']],
                    pc(c['fb']['agg']), pc(c['same']['agg']), pc(c['own_a']['agg']), pc(c['own_b']['agg']),
                    c['same']['fi_cheaper_n'], pc(c['same']['fi_cheaper_share']), c['own_a']['fi_cheaper_n'], pc(c['own_a']['fi_cheaper_share']),
                    c['own_b']['fi_cheaper_n'], pc(c['own_b']['fi_cheaper_share']),
                    pc(c['same']['min_design']), pc(c['own_a']['min_design']), pc(c['own_b']['min_design']),
                    pc(c['fb']['agg_wo_os']), pc(c['same']['agg_wo_os']), pc(c['own_a']['agg_wo_os']), pc(c['own_b']['agg_wo_os'])))
        L.append('')
    L += ['region: A = FairBind ≤ 10% FairBind ≤ FI (p11.region). own call a, b other sellers 45,615 and 81,311 gas.', '']
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True)
    args = ap.parse_args(); T0 = time.time()
    OUT = Path(args.out); OUT = OUT if OUT.is_absolute() else HERE / OUT
    X = p11.P11(with_fr=False)
    try:
        X.set_base('V1u')
        C = {(v, p, lab): cell(X, p, lab, v) for v in ('base', 'T', 'W') for p in PER for lab in LABS}
        CH = dict(k11b_reproduced=bool(X.repro), **checks(X, C))
        CH['ok'] = bool(CH['k11b_reproduced'] and CH['p11_ok'] and CH['manuscript_B_ok'] and CH['tee_ok'])
        print('checks', json.dumps(CH, ensure_ascii=False), '%.0fs' % (time.time() - T0), flush=True)
        OUT.mkdir(parents=True, exist_ok=True)
        if not CH['ok']:
            (OUT / 'c34.json').write_text(json.dumps(dict(status='withheld: reproduction failure', checks=CH), indent=1, ensure_ascii=False), encoding='utf-8')
            print('reproduction failed: no values reported'); sys.exit(2)
        RES = dict(checks=CH, cells={'%s|%s|%s' % k: v for k, v in C.items()},
                   meta=dict(sha256={f: (hashlib.sha256((HERE / f).read_bytes()).hexdigest() if (HERE / f).exists() else 'absent') for f in ('c34.py', 'calc-rules.md')},
                             p11_sha256=hashlib.sha256((J / 'P11_posthoc' / 'p11.py').read_bytes()).hexdigest(),
                             k11b_sha256=hashlib.sha256((J / 'K11' / 'k11b.py').read_bytes()).hexdigest()))
        (OUT / 'c34.json').write_text(json.dumps(RES, indent=1, ensure_ascii=False, allow_nan=True), encoding='utf-8')
        (OUT / 'c34_tables.md').write_text(tables(C), encoding='utf-8')
        (OUT / 'SHA256SUMS.txt').write_text(''.join('%s  %s\n' % (hashlib.sha256((OUT / f).read_bytes()).hexdigest(), f)
                                                    for f in ('c34.json', 'c34_tables.md')), encoding='ascii')
        print('wrote', OUT, '%.0fs' % (time.time() - T0))
    finally:
        X.restore()


if __name__ == '__main__':
    main()
