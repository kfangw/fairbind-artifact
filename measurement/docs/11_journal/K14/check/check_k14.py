"""K14 independent check: k11b Grid not calling without by hand formula n, n_s, FR n_s, cost difference again computes.
input: F/data-review/target_sellers_values.csv (k11b VALCSV), G10b/G11 gas logs two lines.
run: python3 -I check_k14.py   (K14/check in the folder or from anywhere)"""
import csv, gzip, math, os
HERE = os.path.dirname(os.path.abspath(__file__))
J = os.path.abspath(os.path.join(HERE, '..', '..'))          # docs/11_journal
VALCSV = J + '/F/data-review/target_sellers_values.csv'
EDGES = [0.0, 0.001, 0.01, 0.1, 0.2, 0.5, 1.0, 5.0, math.inf]
PER = {'busy': ('s1b', 'busy', 21), 'median': ('s1b', 'median', 21), 'quiet': ('s1c', 'quiet', 15)}
SET = [('StableEnrich', 0.5), ('OneSource', None), ('CoinMarketCap', None), ('StableApify', None), ('Exa', 0.001), ('CoinStats', 0.01)]
V = 1.0

bins = {}
for r in csv.DictReader(open(VALCSV, encoding='ascii')):
    for p, (src, win, _) in PER.items():
        if r['source'] == src and r['window'] == win:
            up = math.inf if r['upper_usdc'] == 'inf' else float(r['upper_usdc'])
            bins.setdefault((p, r['seller']), []).append((up, int(r['sales']), float(r['usdc'])))

def ns_fb_bin(c, u, lo, up, V):                     # hand formula: k11b ns_group 'hi'and same definition
    if c <= 0: return 0.0
    if up <= V: return u / V                        # all sales v <= V: expected sample = Σ v/V
    if lo >= V: return float(c)                     # all sales v > V: increase drawn
    return min(float(c), u / V)

def seller(p, nm, part):
    B = [b for b in bins.get((p, nm), []) if part is None or b[0] <= part + 1e-12]
    B = [b for b in B if b[1] > 0]
    if not B: return None
    n = sum(b[1] for b in B); R = sum(b[2] for b in B)
    nsfb = sum(ns_fb_bin(c, u, EDGES[EDGES.index(up) - 1], up, V) for up, c, u in B)
    vhat = max(b[0] for b in B)
    pr = 1.0 if vhat == math.inf else vhat / (V + vhat)
    return dict(a=nm if part is None else '%s(%g or less)' % (nm, part), n=n, R=R, nsfb=nsfb, vhat=vhat, p=pr, nsfr=n * pr, B=B)

# ---- 1. median window Table
print('## 1. median window, V = 1')
S = [s for s in (seller('median', nm, pt) for nm, pt in SET) if s]
for s in S:
    print('%-22s n=%6d R=%.6f nsFB=%.6f vhat=%g p=%.9f nsFR=%.6f ratio=%.9f' % (s['a'], s['n'], s['R'], s['nsfb'], s['vhat'], s['p'], s['nsfr'], s['nsfr'] / s['nsfb']))
sfb = sum(s['nsfb'] for s in S); sfr = sum(s['nsfr'] for s in S)
print('sum nsFB=%.6f nsFR=%.6f ratio=%.9f' % (sfb, sfr, sfr / sfb))

# ---- 2. StableEnrich cost difference (lower = k11b LOm('N'), gas 'new', V = 1)
gp, eth = 0.005 + (2.0 - 1.0) * 0.005, 2401.44     # BASIS g10b, MULT_MAIN 2.0, TIP_REF 0.005 -> 0.010 gwei
gusd = lambda g: g * gp * 1e-9 * eth
wusd = lambda wei: wei * 1e-18 * eth
T1A_GAS = 86_824                                    # G11 p5_l1fee: 'P5 proof call, tier 1a Pyth Pro one feed, depth 5'
RS3_WEI = 2_132_754_915                             # G10b l1fee: RS3 row l1_fee_node_wei (gas set 'new' keeps old wei)
cP = gusd(T1A_GAS) + wusd(RS3_WEI)
REL_K = 2_083
w, a, b = 0.00173, 0.0, V                           # bV = True
DF = 300 * 1 + 120 + 31 + 1800                      # df1: DF(1) = EPB + DA + SV + TP (k and independent)
Wb = 21 * 43200
se = S[0]; R = se['R']
def terms(ns):
    lam = w * ns * DF / Wb
    return dict(verify=cP * ns / R, release=gusd(REL_K * ns) / R,
                frozen=(1 - a) * (1 - math.exp(-lam)), frozen_lin=(1 - a) * lam, deduct=w * ns * b / R)
tf, tr = terms(se['nsfb']), terms(se['nsfr'])
print('\n## 2. StableEnrich median, lower, V = 1  (cP = %.9f USD, gusd/gas = %.6e)' % (cP, gusd(1)))
tot_fb = tot_fr = 0.0
for k in ('verify', 'release', 'frozen', 'deduct', 'frozen_lin'):
    print('%-10s FB=%.6f%%  FR=%.6f%%  diff=%+.6f%%p' % (k, 100 * tf[k], 100 * tr[k], 100 * (tr[k] - tf[k])))
    if k != 'frozen_lin': tot_fb += tf[k]; tot_fr += tr[k]
print('ns term sum: FB=%.6f%% FR=%.6f%% diff=%+.6f%%p' % (100 * tot_fb, 100 * tot_fr, 100 * (tot_fr - tot_fb)))
# release split correction upper bound: capR = floor((2^24 - REL_F)/(REL_M + REL_K q)); added unit <= ceil(n/capR_FR)
REL_F, REL_M = 105_742 + 8_882, 2_930
cap = lambda q: math.floor((2 ** 24 - REL_F) / (REL_M + REL_K * min(q, 1.0)))
cfb, cfr = cap(se['nsfb'] / se['n']), cap(se['nsfr'] / se['n'])
extra = math.ceil(se['n'] / cfr)
bound = (gusd(REL_F * extra) + wusd(0)) / R
print('capR FB=%d FR=%d; release split difference upper bound(unit %d x REL_F gas, L1 excluded) = %.5f%%p' % (cfb, cfr, extra, 100 * bound))

# ---- 3. JK14c: CoinMarketCap, Exa(0.001 or less), all window
print('\n## 3. price single seller, all window')
for p in PER:
    for nm, pt in (('CoinMarketCap', None), ('Exa', 0.001)):
        s = seller(p, nm, pt)
        if s is None: print(p, nm, 'none'); continue
        print('%-7s %-16s bins=%s mean=%.6f nsFB=%.6f nsFR=%.6f ratio=%.9f' % (p, s['a'], s['B'], s['R'] / s['n'], s['nsfb'], s['nsfr'], s['nsfr'] / s['nsfb']))

# ---- 3b. median window lower V = 1, price single seller n_s term difference (same formula)
print('\n## 3b. median, lower, V = 1: n_s term difference')
for s in S:
    if s['a'] not in ('CoinMarketCap', 'Exa(0.001 or less)', 'CoinStats(0.01 or less)'): continue
    R = s['R']
    def t(ns):
        lam = w * ns * DF / Wb
        return cP * ns / R + gusd(REL_K * ns) / R + (1 - math.exp(-lam)) + w * ns * b / R
    print('%-22s diff=%+.10f (ratio) = %+.8f%%p' % (s['a'], t(s['nsfr']) - t(s['nsfb']), 100 * (t(s['nsfr']) - t(s['nsfb']))))
print('\nStableEnrich ns term difference (ratio, precise) = %.12f' % (tot_fr - tot_fb))
