#!/usr/bin/env python3
"""K13 (supplementary registration 1, report lines only; computation identical to k13_cost.py): seller cost with the anchor gas of the one-hash unit layouts (C1, C1r) measured on a Base fork.
Thin wrapper over K12/k12.py (registration K13_preregistration.md, sec. 5). k12.py is not changed: this file reads its source,
executes the model part (everything above the line MARK, i.e. constants, G11 rows, Prm, Grid, set_gas) in its own
namespace and then replaces only these cells:
  G10B_F, G10B_M  fixed and per-sale anchor gas of a self-submitted unit (signed s = 1, unsigned s = 0)
  FL_F, FL_M      EIP-7623 floor of the same rows
  WRAP            bundle header (scenario S); MX, MY bundle per-unit change (scenario M)
  CPG, SP0_UP     proof-call gas + d_prf (the preimage of the unit hash in the proof call)
  release         + d_cur x A_p (the preimage of every anchored unit in the cursor call), outside the bundle factor
Everything else (prices, k choice, release, VRF, frozen, deduction, capital, sets) is K12 as it stands.
Main form (sec. 5.2): each cell = the K12 (G11) cell + (variant - base), both measured on the same fork in the same
contract; the absolute measured cells and scenario M are auxiliary.
Run:
  python3 -I docs/11_journal/K13/k13_cost.py --gas docs/11_journal/K13/logs/k13_gas.tsv   (measured; writes k13_output.md, k13_results.json)
  python3 -I docs/11_journal/K13/k13_cost.py --hand    (the hand estimates of F_bundled-anchor_feasibility.md 5.3; writes k13_hand_output.md)
"""
import sys, os, json, math, csv, hashlib, statistics, argparse
sys.dont_write_bytecode = True
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
K12PY = os.path.abspath(os.path.join(HERE, '..', 'K12', 'k12.py'))
MARK = '# ================================================================== K12 report'
PER = ['busy', 'median', 'quiet']
WN = {'busy': 'busy', 'median': 'median', 'quiet': 'quiet'}
NS = [1, 4, 16, 64]
ALL7 = ['StableEnrich(Out candidates excluded)', 'OneSource', 'CoinMarketCap', 'StableApify', 'Exa(0.001 or less)', 'CoinStats(0.01 or less)', 'BlockRun']
TARGETS = ['StableApify', 'CoinStats(0.01 or less)', 'Exa(0.001 or less)', 'BlockRun', 'StableEnrich(Out candidates excluded)']
W0 = 0.00173
HAND_SAVE = {'c1': 110_500, 'c1r': 127_600}          # F_bundled-anchor_feasibility.md 5.3 (hand estimates, not measured)
DELTA_CAP = 5_000                                   # JK13d


def sha(p): return hashlib.sha256(open(p, 'rb').read()).hexdigest() if os.path.exists(p) else 'absent'


# ------------------------------------------------------------------ the K12 model, unchanged
def load_model():
    src = open(K12PY, encoding='utf-8').read()
    ns = {'__file__': K12PY, '__name__': 'k12_model'}
    exec(compile(src[:src.index(MARK)], K12PY, 'exec'), ns)
    ns['set_gas']('new')
    ns['K13_ORIG'] = dict(WRAP=ns['WRAP'], MX=list(ns['MX']), MY=list(ns['MY']))
    ns['K13_DCUR'] = 0.0
    Grid = ns['Grid']
    c0 = Grid._c0

    def _c0(self):
        parts = c0(self)
        d = ns['K13_DCUR']
        if d: parts['release'] = parts['release'] + self.prm.gusd(d * self.Ap) / self.R
        return parts

    def _lim(self):
        return self.prm.bun if self.prm.asc != 'M' else min(self.prm.bun, int(max(ns['MX'])))
    Grid._c0 = _c0; Grid._lim = _lim
    return ns


def g11_set(ns):
    """The K12 values (G11 rows) in the form of a gas set."""
    ns['set_gas']('new')
    o = ns['K13_ORIG']
    return dict(F=dict(ns['G10B_F']), M=dict(ns['G10B_M']), FLF=dict(ns['FL_F']), FLM=dict(ns['FL_M']),
                WRAP=o['WRAP'], MX=list(o['MX']), MY=list(o['MY']), d_prf=0.0, d_cur=0.0)


def apply(ns, gs):
    ns['set_gas']('new')
    o = ns['K13_ORIG']
    ns['WRAP'], ns['MX'], ns['MY'] = o['WRAP'], list(o['MX']), list(o['MY'])
    ns['K13_DCUR'] = 0.0
    if gs is not None:
        ns['G10B_F'] = {s: float(gs['F'][s]) for s in (0, 1)}; ns['G10B_M'] = {s: float(gs['M'][s]) for s in (0, 1)}
        ns['FL_F'] = {s: float(gs['FLF'][s]) for s in (0, 1)}; ns['FL_M'] = {s: float(gs['FLM'][s]) for s in (0, 1)}
        ns['WRAP'] = gs['WRAP']
        if gs.get('MX') is not None: ns['MX'], ns['MY'] = list(gs['MX']), list(gs['MY'])
        if gs['d_prf']:
            ns['CPG'] = {k: (g + gs['d_prf'], w) for k, (g, w) in ns['CPG'].items()}
            ns['SP0_UP'] = ns['SP0_UP'] + gs['d_prf']
        ns['K13_DCUR'] = float(gs['d_cur'])
    ns['_G'].clear()


def run(ns, gs, asc, N, up, V=1.0):
    apply(ns, gs)
    f = ns['UPm'] if up else ns['LOm']
    prm = f('N', bun=N, asc=asc, peer='P1')
    res = {}
    for p in PER:
        g = ns['G']('T01t:' + p, V, prm); o = g.opt(W0)
        gb = ns['G']('BR:' + p, V, prm); ob = gb.opt(W0)
        tot = {s_['a']: float(o['tot'][j]) for j, s_ in enumerate(g.S)}
        tot['BlockRun'] = float(ob['tot'][0])
        res[p] = dict(med=float(o['med']), agg=float(o['agg']), tot=tot, n10=int(sum(tot[a] <= 0.10 for a in ALL7)))
    return res


# ------------------------------------------------------------------ measured gas (registration sec. 3.4)
COLS = ['variant', 'event', 'P', 'm', 'sig', 'slot', 'run', 'tx_gas', 'eip7623_floor', 'l1_fee_node_wei']


def read_gas(path):
    rows = list(csv.DictReader(open(path, encoding='ascii'), delimiter='\t'))
    assert rows and list(rows[0].keys()) == COLS, 'columns'
    cell = {}
    for r in rows:
        key = (r['variant'], r['event'], r['P'], r['m'], r['sig'], r['slot'])
        cell.setdefault(key, []).append((int(r['tx_gas']), int(r['eip7623_floor'])))
    med = {k: (statistics.median(x[0] for x in v), statistics.median(x[1] for x in v), len(v),
               max(x[0] for x in v) - min(x[0] for x in v)) for k, v in cell.items()}
    return med


def slot_of(v): return 'reused' if v == 'c1r' else 'fresh'


def get(med, v, ev, P='-', m='-', sig='-', slot=None, col=0):
    key = (v, ev, str(P), str(m), str(sig), slot if slot is not None else (slot_of(v) if ev.startswith('anchor') else '-'))
    return med[key][col] if key in med else None


def measured_set(med, v):
    sf = lambda m, s, c=0: get(med, v, 'anchor_self', 1, m, s, col=c)
    M = {s: (sf(32, s) - sf(8, s)) / 24 for s in (0, 1)}; F = {s: sf(8, s) - 8 * M[s] for s in (0, 1)}
    FLM = {s: (sf(32, s, 1) - sf(8, s, 1)) / 24 for s in (0, 1)}; FLF = {s: sf(8, s, 1) - 8 * FLM[s] for s in (0, 1)}
    one = sf(1, 1)
    bun = {P: get(med, v, 'anchor_bundle', P, 1, 1) for P in (1, 4, 16, 64)}
    if all(x is not None for x in bun.values()):
        WRAP = bun[1] - one; MX = [1, 4, 16, 64]; MY = [0.0] + [bun[P] / P - one for P in (4, 16, 64)]
    else:                                                    # no bundle path in the measured contract (sec. 3.3)
        WRAP = None; MX = None; MY = None
    def d(ev):
        a, b = get(med, v, ev), get(med, 'base', ev)
        return None if a is None or b is None else a - b
    return dict(F=F, M=M, FLF=FLF, FLM=FLM, WRAP=WRAP, MX=MX, MY=MY,
                d_prf=d('prove') or 0.0, d_cur=d('release_one') or 0.0, one=one, lin1=F[1] + M[1])


def transfer_set(g11, ms_v, ms_b):
    """Main form (sec. 5.2): the K12 (G11) cells plus the measured difference variant - base (scenario S only)."""
    return dict(F={s: g11['F'][s] + ms_v['F'][s] - ms_b['F'][s] for s in (0, 1)},
                M={s: g11['M'][s] + ms_v['M'][s] - ms_b['M'][s] for s in (0, 1)},
                FLF={s: g11['FLF'][s] + ms_v['FLF'][s] - ms_b['FLF'][s] for s in (0, 1)},
                FLM={s: g11['FLM'][s] + ms_v['FLM'][s] - ms_b['FLM'][s] for s in (0, 1)},
                WRAP=g11['WRAP'] + ((ms_v['WRAP'] - ms_b['WRAP']) if ms_v['WRAP'] is not None and ms_b['WRAP'] is not None else 0.0), MX=None, MY=None, d_prf=ms_v['d_prf'], d_cur=ms_v['d_cur'])


def hand_set(g11, v):
    h = dict(g11); h['F'] = {s: g11['F'][s] - HAND_SAVE[v] for s in (0, 1)}; h['MX'] = None; h['MY'] = None
    return h


def absolute_set(g11, ms_v):
    """Auxiliary form (sec. 5.3): the measured cells as they are; the G11 bundle header when no bundle was measured."""
    h = dict(ms_v)
    if h['WRAP'] is None: h['WRAP'] = g11['WRAP']
    return h


def anchor_only(gs):
    h = dict(gs); h['d_prf'] = 0.0; h['d_cur'] = 0.0; return h


# ------------------------------------------------------------------ report
def pc(x): return '%.2f%%' % (100 * x)
def f1(x): return '-' if x is None else '%.1f' % x   # K13_supplementary-registration-1.md item 5: report only, None when no bundle row


def cost_tables(ns, sets, P):
    """sets: list of (label, gas set, asc). Returns {label: {(N, up): res}}."""
    R = {}
    for lab, gs, asc in sets:
        R[lab] = {(N, up): run(ns, gs, asc, N, up) for N in NS for up in (False, True)}
    P('\n### median seller(lower / upper) and 10% within seller count(seven among, lower / upper)\n')
    P('| calculation | N | busy | median | quiet | 10% within count lower(busy, median, quiet) | upper |'); P('|---|---|---|---|---|---|---|')
    for lab, _, _ in sets:
        for N in NS:
            lo, up = R[lab][(N, False)], R[lab][(N, True)]
            P('| %s | %d | %s | %s | %s |' % (lab, N, ' | '.join('%s / %s' % (pc(lo[p]['med']), pc(up[p]['med'])) for p in PER),
                                                  ', '.join(str(lo[p]['n10']) for p in PER), ', '.join(str(up[p]['n10']) for p in PER)))
    P('\n### target seller and set (lower / upper, N = 1 and 64)\n')
    P('| calculation | window | target | N 1 | N 64 |'); P('|---|---|---|---|---|')
    for lab, _, _ in sets:
        for p in PER:
            for t in ['median seller'] + TARGETS + ['T01t pooled']:
                def c(N):
                    lo, up = R[lab][(N, False)][p], R[lab][(N, True)][p]
                    f = (lambda r: r['med']) if t == 'median seller' else (lambda r: r['agg']) if t == 'T01t pooled' else (lambda r: r['tot'][t])
                    return '%s / %s' % (pc(f(lo)), pc(f(up)))
                P('| %s | %s | %s | %s | %s |' % (lab, WN[p], t, c(1), c(64)))
    return R


def verdicts(med, R, L1):
    """Letter verdicts of JK13a to JK13d (registration sec. 6)."""
    J = {}
    b1 = get(med, 'base', 'anchor_self', 1, 1, 1)
    for v, lab, cap in (('c1', 'JK13a', 0.60), ('c1r', 'JK13a-r', 0.50)):
        x = get(med, v, 'anchor_self', 1, 1, 1)
        r = (L1 + x - b1) / L1                               # transfer form: K12 one-sale unit 211,556.4 + measured difference
        J[lab] = dict(value=r, cap=cap, holds=bool(r <= cap), raw_ratio=x / b1, delta=x - b1)
    for v, lab in (('c1', 'JK13b'), ('c1r', 'JK13b-r')):
        cells = {p: R['K13-' + v][(64, False)][p]['med'] for p in PER}
        J[lab] = dict(value=cells, cap=0.20, holds=bool(all(x <= 0.20 for x in cells.values())))
    for v, lab in (('c1', 'JK13c'), ('c1r', 'JK13c-r')):
        a = {p: R['K13-' + v][(64, False)][p]['n10'] for p in PER}; b = {p: R['K13-base'][(64, False)][p]['n10'] for p in PER}
        J[lab] = dict(value=a, base=b, holds=bool(any(a[p] > b[p] for p in PER)))
    for v, lab in (('c1', 'JK13d'), ('c1r', 'JK13d-r')):
        ds = {}
        for ev in ('prove', 'release_one', 'dispute_open', 'double_sign', 'swap_proof'):
            a, b = get(med, v, ev), get(med, 'base', ev)
            ds[ev] = None if a is None or b is None else a - b
        got = [x for x in ds.values() if x is not None]
        J[lab] = dict(value=ds, cap=DELTA_CAP, holds=(None if len(got) < 2 else bool(all(x <= DELTA_CAP for x in got))),
                      note='withheld(measured call two below)' if len(got) < 2 else '')
    return J


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gas'); ap.add_argument('--hand', action='store_true'); ap.add_argument('--out')
    a = ap.parse_args()
    ns = load_model(); g11 = g11_set(ns)
    out = []; P = out.append
    if a.hand:
        P('# K13 prior prediction(hand estimate, for verdicts not used not; k13_cost.py --hand)\n')
        P('F_bundled-anchor_feasibility.md 5.3 estimate this with the wrapper again computed is. anchor fixed gas C1 110,500, C1r 127,600 removed proof and cursor restored gas 0 kept.\n')
        P('k12.py SHA-256 %s\n' % sha(K12PY))
        R = cost_tables(ns, [('K12(G11)', g11, 'S'), ('estimate C1', hand_set(g11, 'c1'), 'S'), ('estimate C1r', hand_set(g11, 'c1r'), 'S')], P)
        path = a.out or os.path.join(HERE, 'k13_hand_output.md')
        open(path, 'w', encoding='utf-8').write('\n'.join(out) + '\n'); print('wrote', path); return R
    med = read_gas(a.gas)
    P('# K13 output (k13_cost.py)\n')
    P('| input | SHA-256 |'); P('|---|---|')
    for p_ in (a.gas, K12PY, os.path.join(HERE, 'K13_preregistration.md')):
        P('| %s | %s |' % (os.path.relpath(p_, HERE), sha(p_)))
    P('\n## 1. measured gas (median, run count, run between max difference)\n')
    P('| variant | event | P | m | sig | slot | tx gas | floor | run count | spread |'); P('|---|---|---|---|---|---|---|---|---|---|')
    for k in sorted(med): P('| %s | %d | %d | %d | %d |' % (' | '.join(k), med[k][0], med[k][1], med[k][2], med[k][3]))
    ms = {v: measured_set(med, v) for v in ('base', 'c1', 'c1r')}
    P('\n## 2. model entering cell\n')
    P('| cell | K12(G11) | base | c1 | c1r |'); P('|---|---|---|---|---|')
    for k, fn in (('F[1]', lambda g: g['F'][1]), ('M[1]', lambda g: g['M'][1]), ('F[0]', lambda g: g['F'][0]), ('M[0]', lambda g: g['M'][0]),
                  ('FL_F[1]', lambda g: g['FLF'][1]), ('WRAP', lambda g: g['WRAP']), ('d_prf', lambda g: g['d_prf']), ('d_cur', lambda g: g['d_cur'])):
        P('| %s | %s |' % (k, ' | '.join(f1(fn(g)) for g in (g11, ms['base'], ms['c1'], ms['c1r']))))
    P('| MY (P = 1, 4, 16, 64; G11 1, 2, 4, 8) | %s |' % ' | '.join('-' if g['MY'] is None else ', '.join('%+.0f' % y for y in g['MY']) for g in (g11, ms['base'], ms['c1'], ms['c1r'])))
    P('| leaf one direct / linear fit F+M | - | %s |' % ' | '.join('%d / %.0f (%+.2f%%)' % (ms[v]['one'], ms[v]['lin1'], 100 * (ms[v]['lin1'] / ms[v]['one'] - 1)) for v in ('base', 'c1', 'c1r')))
    P('\n## 3. G11 with difference (base row / G11 row)\n')
    P('| cell | base | K12(G11) | difference |'); P('|---|---|---|---|')
    for k in ('F', 'M'):
        for s in (1, 0): P('| %s[%d] | %.1f | %.1f | %+.2f%% |' % (k, s, ms['base'][k][s], g11[k][s], 100 * (ms['base'][k][s] / g11[k][s] - 1)))
    if ms['base']['WRAP'] is None: P('| WRAP | - | %.1f | bundle row none |' % g11['WRAP'])
    else: P('| WRAP | %.1f | %.1f | %+.1f gas |' % (ms['base']['WRAP'], g11['WRAP'], ms['base']['WRAP'] - g11['WRAP']))
    T = {v: transfer_set(g11, ms[v], ms['base']) for v in ('base', 'c1', 'c1r')}
    P('\n## 4. main calculation (difference transplant: K12 cell + same fork variant − reference, scenario S, mode N, V 1, P1)\n')
    R = cost_tables(ns, [('K13-base', T['base'], 'S'), ('K13-c1', T['c1'], 'S'), ('K13-c1r', T['c1r'], 'S')], P)
    P('\n## 5. auxiliary calculation (for verdicts not used not)\n')
    P('\n### 5.1 anchor cells only changed(d_prf = d_cur = 0, difference transplant)\n')
    cost_tables(ns, [('c1 anchor only', anchor_only(T['c1']), 'S'), ('c1r anchor only', anchor_only(T['c1r']), 'S')], P)
    P('\n### 5.2 absolute values(measured cell as is)\n')
    cost_tables(ns, [('absolute base', absolute_set(g11, ms['base']), 'S'), ('absolute c1', absolute_set(g11, ms['c1']), 'S'), ('absolute c1r', absolute_set(g11, ms['c1r']), 'S')], P)
    if all(ms[v]['MX'] is not None for v in ms):
        P('\n### 5.3 scenario M(measured bundle curve, absolute values)\n')
        cost_tables(ns, [('M base', ms['base'], 'M'), ('M c1', ms['c1'], 'M'), ('M c1r', ms['c1r'], 'M')], P)
    else:
        P('\n### 5.3 scenario M: bundle row absent not computed not\n')
    J = verdicts(med, R, g11['F'][1] + g11['M'][1])
    P('\n## 6. text verdict\n'); P('| verdict | value | threshold | holds |'); P('|---|---|---|---|')
    for k, d in J.items(): P('| %s | %s | %s | %s |' % (k, d['value'], d.get('cap', d.get('base')), {True: 'holds', False: 'does not hold not', None: 'withheld'}[d['holds']]))
    txt = '\n'.join(out) + '\n'
    path = a.out or os.path.join(HERE, 'k13_output.md')
    open(path, 'w', encoding='utf-8').write(txt)
    cells = {lab: {'%d,%s' % (N, 'up' if up else 'lo'): {p: dict(med=r[p]['med'], agg=r[p]['agg'], n10=r[p]['n10'], tot=r[p]['tot']) for p in PER}
                   for (N, up), r in R[lab].items()} for lab in R}
    json.dump(dict(verdicts=J, cells=cells, sets={v: {k: (x if not isinstance(x, dict) else {str(s): y for s, y in x.items()}) for k, x in g.items()} for v, g in ms.items()}),
              open(os.path.splitext(path)[0].replace('k13_output', 'k13_results') + '.json', 'w'), ensure_ascii=False, indent=1, default=float)
    print('wrote', path)
    return R, J


if __name__ == '__main__':
    main()
