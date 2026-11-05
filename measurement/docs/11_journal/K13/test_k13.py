#!/usr/bin/env python3
"""Synthetic tests of k13_cost.py (registration K13_preregistration.md sec. 9). No measured K13 gas is read.
T1  identity: with no change, and with the K12 (G11) cells passed as a gas set, the wrapper gives the K12 cells of
    k12_output.md (table 6 rows of the main and measured scenarios, the seven-seller table of sec. 3).
T2  measured path: a synthetic gas table whose base rows are the G11 rows gives K12's main scenario through
    read_gas and measured_set (current-design gas in, K12 out).
T3  storage saving path: c1 rows = base rows - 66,300 on every anchor row give K12's scenario Z (table 6).
T4  hand estimates: the C1 and C1r cells of F_bundled-anchor_feasibility.md 5.3 (pre-registered predictions).
T5  preimage cells: d_cur adds gusd(d_cur x A_p) / R to release only; d_prf raises verify; the transfer form (main)
    gives K12 for base and scenario Z for -66,300; letter verdicts read the rows; missing bundle rows keep K12's header.
Run: python3 -I docs/11_journal/K13/test_k13.py
"""
import sys, os, re, tempfile
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import k13_cost as K
import numpy as np

ns = K.load_model(); g11 = K.g11_set(ns)
OUT = open(os.path.join(HERE, '..', 'K12', 'k12_output.md'), encoding='utf-8').read().split('\n')
pc = K.pc
FAIL = []
def check(name, ok, info=''):
    print('%s %s %s' % ('PASS' if ok else 'FAIL', name, info))
    if not ok: FAIL.append(name)

def t6_rows(sc):
    return {int(l.split('|')[2]): l for l in OUT if l.startswith('| %s | ' % sc)}

def t6_line(sc, N, R):
    lo, up = R[(N, False)], R[(N, True)]
    return '| %s | %d | %s | %s | %s |' % (sc, N, ' | '.join('%s / %s' % (pc(lo[p]['med']), pc(up[p]['med'])) for p in K.PER),
                                          ', '.join(str(lo[p]['n10']) for p in K.PER), ', '.join(str(up[p]['n10']) for p in K.PER))

def table(gs, asc):
    return {(N, up): K.run(ns, gs, asc, N, up) for N in K.NS for up in (False, True)}

# ---------------- T1
for lab, gs in (('none', None), ('g11 set', g11)):
    for sc, asc in (('main', 'S'), ('measured', 'M')):
        R = table(gs, asc); ref = t6_rows(sc)
        bad = [N for N in K.NS if t6_line(sc, N, R) != ref[N]]
        check('T1 %s %s table 6' % (lab, sc), not bad, bad)
R = table(g11, 'S')
sec3 = OUT[OUT.index('## 3. main scenario(anchor S, release a 0.6, concurrent activity P1; bundle gas sketch value) mode N, V 1'):]
sec3 = sec3[:sec3.index('### Table 5. pooled(revenue weighted) and large seller (N = 1 relative to lower change %p)')]
n = 0; bad = []
for l in sec3:
    m = re.match(r'\| (busy|median|quiet) \| (.+?) \| (.+) \|$', l)
    if not m: continue
    p = {v: k for k, v in K.WN.items()}[m.group(1)]; a = m.group(2)
    got = ' | '.join('%s / %s' % (pc(R[(N, False)][p]['tot'][a]), pc(R[(N, True)][p]['tot'][a])) for N in K.NS)
    n += 1
    if got != m.group(3): bad.append((p, a))
check('T1 seven-seller table (%d rows)' % n, n == 21 and not bad, bad)

# ---------------- synthetic gas table
SG = {1: 'all signed', 0: 'none signed'}
def g11row(m, s): return ns['gg'](ns['SELF'] % (m, SG[s])), ns['gf'](ns['SELF'] % (m, SG[s]))
def synth(path, save=0, dprf=0, dcur=0):
    rows = []
    def add(v, ev, P, m, s, slot, g, f):
        for r in (1, 2, 3): rows.append([v, ev, P, m, s, slot, r, g, f, 0])
    for v, sv in (('base', 0), ('c1', save), ('c1r', save)):
        slot = 'reused' if v == 'c1r' else 'fresh'
        for s in (0, 1):
            for m in (8, 32):
                g, f = g11row(m, s); add(v, 'anchor_self', 1, m, s, slot, g - sv, f)
            for m in (1, 2, 4, 16, 64):
                g = int(round(g11['F'][s] + g11['M'][s] * m)); add(v, 'anchor_self', 1, m, s, slot, g - sv, 0)
        one = int(round(g11['F'][1] + g11['M'][1]))
        for P in (1, 4, 16, 64):
            add(v, 'anchor_bundle', P, 1, 1, slot, P * (one - sv) + 3252 if P == 1 else P * (one - sv) + 3252 - (P - 1) * 21000, 0)
        add(v, 'prove', '-', '-', '-', '-', 60000 + (dprf if v != 'base' else 0), 0)
        add(v, 'release_one', '-', '-', '-', '-', 103552 + (dcur if v != 'base' else 0), 0)
        add(v, 'dispute_open', '-', '-', '-', '-', 120000 + (1000 if v != 'base' else 0), 0)
    with open(path, 'w', encoding='ascii') as fh:
        fh.write('\t'.join(K.COLS) + '\n')
        for r in rows: fh.write('\t'.join(str(x) for x in r) + '\n')
    return path

tmp = tempfile.mkdtemp()
# ---------------- T2
med = K.read_gas(synth(os.path.join(tmp, 'g0.tsv')))
ms = K.measured_set(med, 'base')
check('T2 base cells = G11 cells', all(abs(ms[k][s] - g11[k][s]) < 1e-9 for k in ('F', 'M', 'FLF', 'FLM') for s in (0, 1)) and ms['WRAP'] == g11['WRAP'] and ms['d_prf'] == 0 and ms['d_cur'] == 0)
R0 = table(ms, 'S'); ref = t6_rows('main')
check('T2 measured path gives K12 main rows', all(t6_line('main', N, R0) == ref[N] for N in K.NS))
# ---------------- T3
med3 = K.read_gas(synth(os.path.join(tmp, 'g3.tsv'), save=66_300))
for v in ('c1', 'c1r'):
    R3 = table(K.measured_set(med3, v), 'S'); ref = t6_rows('Z')
    check('T3 %s with -66,300 gives K12 scenario Z rows' % v, all(t6_line('Z', N, R3).replace('| Z |', '| Z |') == ref[N] for N in K.NS),
          [t6_line('Z', N, R3) for N in K.NS if t6_line('Z', N, R3) != ref[N]][:1])
# ---------------- T4
F53 = {('c1', 1): ('19.82 / 33.44', '36.99 / 60.47', '56.59 / 94.53'), ('c1', 64): ('13.80 / 16.43', '20.37 / 22.10', '27.52 / 28.79'),
       ('c1r', 1): ('19.15 / 32.77', '35.37 / 58.85', '53.99 / 91.93'), ('c1r', 64): ('13.13 / 15.76', '19.19 / 20.92', '24.92 / 26.19')}
N10 = {('c1', 1): (1, 1, 2), ('c1', 64): (2, 1, 2), ('c1r', 1): (1, 1, 2), ('c1r', 64): (3, 1, 2)}
APF = {'c1': '9.02', 'c1r': '8.42'}
for v in ('c1', 'c1r'):
    Rh = table(K.hand_set(g11, v), 'S')
    for N in (1, 64):
        got = tuple('%.2f / %.2f' % (100 * Rh[(N, False)][p]['med'], 100 * Rh[(N, True)][p]['med']) for p in K.PER)
        check('T4 hand %s N %d median seller' % (v, N), got == F53[(v, N)], got)
        got = tuple(Rh[(N, False)][p]['n10'] for p in K.PER)
        check('T4 hand %s N %d count within 10%%' % (v, N), got == N10[(v, N)], got)
    got = '%.2f' % (100 * Rh[(64, False)]['busy']['tot']['StableApify'])
    check('T4 hand %s N 64 StableApify busy' % v, got == APF[v], got)
# ---------------- T5
med5 = K.read_gas(synth(os.path.join(tmp, 'g5.tsv'), save=0, dprf=4000, dcur=3000))
ms5 = K.measured_set(med5, 'c1')
check('T5 d_prf, d_cur read', ms5['d_prf'] == 4000 and ms5['d_cur'] == 3000)
K.apply(ns, ms); prm = ns['LOm']('N', bun=1, asc='S', peer='P1'); gA = ns['G']('T01t:busy', 1.0, prm)
pa = {k: v.copy() for k, v in gA.c0parts.items()}
K.apply(ns, ms5); gB = ns['G']('T01t:busy', 1.0, ns['LOm']('N', bun=1, asc='S', peer='P1'))
pb = gB.c0parts
add = prm.gusd(3000 * gA.Ap) / gA.R
check('T5 release + gusd(d_cur A_p)/R', np.allclose(pb['release'] - pa['release'], add))
check('T5 verify rises with d_prf', bool(np.all(pb['verify'] > pa['verify'])) and np.allclose(pb['anchor'], pa['anchor']))
mb, mc, mr = (K.measured_set(med3, v) for v in ('base', 'c1', 'c1r'))
Rb = table(K.transfer_set(g11, mb, mb), 'S'); Rc = table(K.transfer_set(g11, mc, mb), 'S'); Rr = table(K.transfer_set(g11, mr, mb), 'S')
check('T5 transfer base = K12 main rows', all(t6_line('main', N, Rb) == t6_rows('main')[N] for N in K.NS))
check('T5 transfer c1 (-66,300) = K12 Z rows', all(t6_line('Z', N, Rc) == t6_rows('Z')[N] for N in K.NS))
L1 = g11['F'][1] + g11['M'][1]
J = K.verdicts(med3, {'K13-base': Rb, 'K13-c1': Rc, 'K13-c1r': Rr}, L1)
check('T5 JK13a value', abs(J['JK13a']['value'] - (L1 - 66300) / L1) < 1e-12 and J['JK13a']['holds'] is False and J['JK13a']['delta'] == -66300, J['JK13a'])
check('T5 JK13c against K12 counts', J['JK13c']['base'] == {'busy': 1, 'median': 1, 'quiet': 2}, J['JK13c'])
# no bundle rows: transfer keeps the K12 header
med6 = {k: v for k, v in med3.items() if k[1] != 'anchor_bundle'}
m6 = K.measured_set(med6, 'c1')
check('T5 missing bundle rows', m6['WRAP'] is None and K.transfer_set(g11, m6, K.measured_set(med6, 'base'))['WRAP'] == g11['WRAP'])
check('T5 JK13d reads dispute delta', J['JK13d']['value']['dispute_open'] == 1000 and J['JK13d']['holds'] is True and J['JK13d']['value']['double_sign'] is None)
print('\n%d failed' % len(FAIL) if FAIL else '\nall passed')
sys.exit(1 if FAIL else 0)
