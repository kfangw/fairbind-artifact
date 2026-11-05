"""W6 (post hoc, calc-rules.md): block-filling cost of the shortest swap-proof window with Base's EIP-1559
base-fee response and the buyer's fee ceiling p_swap, and the margins of Table tab:margins.

Run: python3 -I w6.py            (prints Markdown tables)
     python3 -I w6.py --check    (checks only)
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
P10 = os.path.join(HERE, '..', '..', 'P10_fit-conditions', 'results', 'p10.json')

# Base header values (extraData 0x01|00000064|00000005|00000000004c4b40, blocks 48,343,249 .. 53,527,249)
L = 400_000_000
E = 5
D = 100
T = L // E
BMIN = 5_000_000          # wei
ETH = 2_401.44            # USD per ETH (manuscript fee basis)
N = 62                    # blocks to fill: T_sw 31 + (M_e - A_e) 31
GWEI = 10 ** 9

B_START = [0.005, 0.0100, 0.0161, 0.05]
P_SWAP = [0.005, 0.0100, 0.0161, 0.1, 1.0]


def wei(g):
    return int(round(g * GWEI))


def usd(w):
    return w / 1e18 * ETH


def nxt(b, m):
    """Next base fee (op-geth CalcBaseFee with Holocene params and Jovian minBaseFee)."""
    if m == T:
        return b
    if m > T:
        return b + max(1, (b * (m - T) // T) // D)
    return max(BMIN, b - (b * (T - m) // T) // D)


def min_gas_above(b, p):
    """Smallest u in [0, L] with nxt(b, u) > p (assumes b > p)."""
    if nxt(b, 0) > p:
        return 0
    lo, hi = 0, L
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if nxt(b, mid) > p:
            hi = mid
        else:
            lo = mid
    return hi


def s0(p):
    return N * L * wei(p)


def s1(b1):
    b, c = wei(b1), 0
    for _ in range(N):
        c += L * b
        b = nxt(b, L)
    return dict(cost=c, b_end=b)


def hold(b, p, blocks):
    """Greedy maintenance over `blocks` window blocks starting at base fee b > p."""
    c = g = 0
    for t in range(blocks):
        u = 0 if t == blocks - 1 else min_gas_above(b, p)
        c += u * b; g += u
        b = nxt(b, u)
    return c, g


def s2(b1, ps):
    b, p, c, k = wei(b1), wei(ps), 0, 0
    while k < N and b <= p:
        c += L * p
        b = nxt(b, L)
        k += 1
    hc, hg = hold(b, p, N - k) if k < N else (0, 0)
    return dict(cost=c + hc, k=k, hold_gas=hg, hold_cost=hc)


def s3(b0, ps):
    b, p, c, j = wei(b0), wei(ps), 0, 0
    while b <= p:
        c += L * b
        b = nxt(b, L)
        j += 1
    hc, hg = hold(b, p, N)
    return dict(cost=c + hc, j=j, pre_cost=c, hold_gas=hg, hold_cost=hc)


def cells():
    M = json.load(open(P10, encoding='utf-8'))['margins']
    out = {}
    for w in ('busy', 'median'):
        rows = [r for r in M if r['win'] == w]
        data = [r for r in rows if r['seller'] != 'BlockRun']
        se = [r for r in rows if r['seller'].startswith('StableEnrich')][0]
        br = [r for r in rows if r['seller'] == 'BlockRun'][0]
        out[w] = [('Every data seller, mean epoch (least margin)', max(r['Re'] for r in data)),
                  ('StableEnrich, largest epoch', se['Rmax']),
                  ('BlockRun, mean epoch', br['Re']),
                  ('BlockRun, largest epoch', br['Rmax'])]
    return out


def check():
    ok = True
    # on-chain pairs: (base fee, gasUsed) -> next base fee
    for b, m, want in [(5_097_522, 119_860_379, 5_122_920), (5_122_920, 96_698_795, 5_133_613)]:
        got = nxt(b, m); ok &= got == want
        print('rule check', b, m, got, want, got == want)
    c0 = usd(s0(0.005)); ok &= abs(c0 - 297.77856) < 1e-6
    print('S0(0.005) USD', round(c0, 5))
    tab5 = {'busy': [417.6, 5.13, 8.51, 1.99], 'median': [571.6, 9.45, 7.04, 0.35]}
    for w, cs in cells().items():
        for (lab, R), want in zip(cs, tab5[w]):
            got = c0 / R
            nd = len(repr(want).split('.')[1])   # match at the table's rounding
            ok &= round(got, nd) == want
            print('tab5', w, lab, round(got, 3), want)
    print('CHECK', 'OK' if ok else 'FAIL')
    return ok


def fmt(x):
    if x >= 100: return '%.0f' % x
    if x >= 10: return '%.1f' % x
    return '%.2f' % x


def report():
    ref = usd(s0(0.005))
    print('## A. S0 and S1 (USD)\n')
    print('| start base fee (gwei) | S0 linear n L p | S1 full fill with base-fee response | S1 / S0 | base fee at block 63 (gwei) |')
    print('|---|---|---|---|---|')
    for b1 in B_START:
        r = s1(b1); c0, c1 = usd(s0(b1)), usd(r['cost'])
        print('| %s | %.2f | %.2f | %.3f | %.4f |' % (b1, c0, c1, c1 / c0, r['b_end'] / GWEI))
    print('\n## B. S2 (in-window outbid, then base fee above p_swap)\n')
    print('| b_1 (gwei) | p_swap (gwei) | k* | hold gas | cost USD | S0(p_swap) USD | / S0(0.005) |')
    print('|---|---|---|---|---|---|---|')
    for b1 in B_START:
        for ps in P_SWAP:
            r = s2(b1, ps)
            print('| %s | %s | %d | %s | %.2f | %.2f | %.3f |' % (b1, ps, r['k'], format(r['hold_gas'], ','), usd(r['cost']), usd(s0(ps)), usd(r['cost']) / ref))
    print('\n## C. S3 (pre-pump before the window, then hold)\n')
    print('| b_0 (gwei) | p_swap (gwei) | j* | pre-pump USD | hold gas | hold USD | cost USD | / S0(0.005) |')
    print('|---|---|---|---|---|---|---|---|')
    for b0 in B_START:
        for ps in P_SWAP:
            r = s3(b0, ps)
            print('| %s | %s | %d | %.2f | %s | %.2f | %.2f | %.3f |' % (b0, ps, r['j'], usd(r['pre_cost']), format(r['hold_gas'], ','), usd(r['hold_cost']), usd(r['cost']), usd(r['cost']) / ref))
    cols = [('S0 0.005', usd(s0(0.005))), ('S1 b=0.005', usd(s1(0.005)['cost']))]
    cols += [('S2 p=%s' % ps, usd(s2(0.005, ps)['cost'])) for ps in P_SWAP]
    cols += [('S3 p=%s' % ps, usd(s3(0.005, ps)['cost'])) for ps in P_SWAP]
    print('\n## D. Table 5 margins C / R_e (start base fee 0.005 gwei)\n')
    print('cost USD: ' + ', '.join('%s %.2f' % c for c in cols) + '\n')
    for w, cs in cells().items():
        print('### %s window\n' % w)
        print('| cell | R_e USD | ' + ' | '.join(c[0] for c in cols) + ' |')
        print('|---|---|' + '---|' * len(cols))
        for lab, R in cs:
            print('| %s | %.4g | ' % (lab, R) + ' | '.join(fmt(c / R) for _, c in cols) + ' |')
        print()


if __name__ == '__main__':
    if '--check' in sys.argv:
        sys.exit(0 if check() else 1)
    check(); print()
    report()
