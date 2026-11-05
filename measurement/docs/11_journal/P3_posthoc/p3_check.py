#!/usr/bin/env python3
"""P3 check by the same agent with other methods (calc-rules.md sec. 4). NOT an independent check.
Seller inputs (R, n, n_s, E1, per-epoch counts) come from k11b.py's data functions; the cost formulas below do not use Grid.
    python3 -I p3_check.py results
"""
import json, math, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; K11 = HERE.parent / 'K11'; OUT = Path(sys.argv[1])
R = json.load(open(OUT / 'p3.json')); SUPP = json.load(open(OUT / 'p3_supp.json'))
src = (K11 / 'k11b.py').read_text(encoding='utf-8')
src = src.replace("HERE = os.path.dirname(os.path.abspath(__file__))", "HERE = %r" % str(K11)).replace("open(HERE + '/k11b_output.md', 'w').write(txt)", "pass")
g = {'__name__': 'k11b_p3c'}; exec(compile(src, 'k11b.py', 'exec'), g)

ETH = 2401.44; GP = 0.010
def gusd(gas, gp=GP, eth=ETH): return gas * gp * 1e-9 * eth
def wusd(wei, eth=ETH): return wei * 1e-18 * eth
F = 105_742 + 8_882; RW_F = g['RW_F']; RW_M = g['RW_M']; W = 0.00173; r = 0.10
GAS = {'RS3': (86_824, 2_132_754_915), 'SP0': (604_522 + 5_000, 28_173_828_378), 'TEE': (36_440, 2_157_333_560)}
DAYS = {'busy': 21, 'median': 21, 'quiet': 15}


def seller(kind, p, name, V=1.0):
    for s in g['t13_sellers'](kind, p, V):
        if s['a'].startswith(name): return s
    raise KeyError(name)


def counts(s):
    return None if s['cnt'] is None else [int(x) for x in s['cnt']]


def extra_units(s, k, cap, E):
    c = counts(s)
    if c is None:                                   # same bound as k11b splits_bound (no per-epoch counts)
        mk = min(k * s['m1'], s['n'])
        return 0 if mk <= cap else min(math.ceil(s['n'] / cap) - 1, E * (math.ceil(mk / cap) - 1))
    grp = {}
    for e, x in enumerate(c):
        if x: grp[e // k] = grp.get(e // k, 0) + x
    return sum(max(math.ceil(m / cap) - 1, 0) for m in grp.values())


def fi_lower(kind, p, name, tier, relm=2_930, relk=2_083):
    s = seller(kind, p, name); n = s['n']; Rv = s['R']; Nep = DAYS[p] * 144; Wb = DAYS[p] * 43_200
    cp = gusd(GAS[tier][0]) + wusd(GAS[tier][1])
    cap = math.floor((2 ** 24 - F) / (relm + relk))
    best = None
    for k in (1, 2, 4, 8, 16, 32):
        E = min(s['E1'], math.ceil(Nep / k)); Ur = extra_units(s, k, cap, E)
        tot = (n * cp + gusd((E + Ur) * F + (relm + relk) * n) + wusd((E + Ur) * RW_F + RW_M * n)) / Rv + W + r * (300 * k + 1_800) / Wb * DAYS[p] / 365
        if best is None or tot < best[0]: best = (tot, k)
    return best


res = {'FI': [], 'na': [], 'sens': [], 'gstar': []}
ok = True
# (a)
for name, kind, tier in (('StableEnrich', 'T01t', 'RS3'), ('OneSource', 'T01t', 'SP0'), ('BlockRun', 'BR', 'TEE')):
    tot, k = fi_lower(kind, 'median', name, tier)
    row = [x for x in R['FI']['median|lo']['rows'] if x['a'].startswith(name)][0]
    same = abs(tot - row['fi']) < 1e-12 and k == row['fi_k']
    ok &= same
    res['FI'].append(dict(seller=name, hand=tot, k_hand=k, p3=row['fi'], k_p3=row['fi_k'], fb=row['fb'], cheaper='FI' if tot < row['fb'] else 'FB', same=same))
# (b): change of the FairBind total between REL_M 2,930 and 16,800 at the same k, by hand
for p, name in (('busy', 'StableEnrich'), ('quiet', 'OneSource')):
    s = seller('T01t', p, name); n, ns, Rv = s['n'], s['ns'], s['R']; q = min(ns / n, 1.0)
    o = R['orig']['T01t|1|%s|lo' % p]['per']; a = R['na']['T01t|1|%s|lo' % p]['per']
    key = [x for x in o if x.startswith(name)][0]; k = o[key][1]; assert a[key][1] == k
    E = min(s['E1'], math.ceil(DAYS[p] * 144 / k))
    U0 = extra_units(s, k, math.floor((2 ** 24 - F) / (2_930 + 2_083 * q)), E)
    U1 = extra_units(s, k, math.floor((2 ** 24 - F) / (16_800 + 2_083 * q)), E)
    d = (gusd((U1 - U0) * F + (16_800 - 2_930) * n) + wusd((U1 - U0) * RW_F)) / Rv
    same = abs((a[key][0] - o[key][0]) - d) < 1e-12
    ok &= same
    res['na'].append(dict(window=p, seller=name, k=k, Ur_2930=U0, Ur_16800=U1, hand_delta=d, p3_delta=a[key][0] - o[key][0], same=same))
# (c): linear price structure on the (b) model, median StableEnrich lower
S = R['sens']; cell = lambda key: [v for kk, v in S[key]['cells']['T01t|1|median|lo']['per'].items() if kk.startswith('StableEnrich')][0]
b0, bp, be, tgt = cell('0.005|2401.44|2'), cell('0.005|2401.44|2.5'), cell('0.005|2742|2'), cell('0.02|2742|2.5')
assert b0[1] == bp[1] == be[1] == tgt[1]
gas_part = (bp[0] - b0[0]) / (0.0125 / 0.010 - 1)
l1_part = (be[0] - b0[0]) / (2742 / 2401.44 - 1) - gas_part
pred = b0[0] + gas_part * ((0.0275 * 2742) / (0.010 * 2401.44) - 1) + l1_part * (2742 / 2401.44 - 1)
same = abs(pred - tgt[0]) < 1e-12
ok &= same
res['sens'].append(dict(gas_share=gas_part, l1_share=l1_part, rest=b0[0] - gas_part - l1_part, predicted=pred, p3=tgt[0], k=tgt[1], same=same))
# break-even consistency: FI-min StableEnrich cheaper iff 31,315 < g*
for p in ('busy', 'median', 'quiet'):
    gs = SUPP['gstar|%s|StableEnrich(Out candidates excluded)' % p]
    rmin = [x for x in R['FI_min']['%s|lo' % p]['rows'] if x['a'].startswith('StableEnrich')][0]
    agree = (31_315 < gs) == (rmin['fi'] < rmin['fb'])
    ok &= agree
    res['gstar'].append(dict(window=p, gstar=gs, fimin_cheaper=rmin['fi'] < rmin['fb'], agree=agree))
res['all_ok'] = bool(ok)
json.dump(res, open(OUT / 'p3_check.json', 'w'), indent=1, ensure_ascii=False)
print(json.dumps(res, indent=1, ensure_ascii=False))
