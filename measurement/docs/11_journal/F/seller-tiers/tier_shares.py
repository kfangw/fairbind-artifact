#!/usr/bin/env python3
"""Tier shares of sales and value among the classified Base sellers, per window, with and without BlockRun.

Reads the tier assignment `seller_tiers.csv` (one row per seller and endpoint family) and recomputes each row's
sales and value from the per-seller totals and value bins of `../data-review/`, checks them against the columns of
`seller_tiers.csv`, and prints the tier shares as a Markdown table.

    python3 -I tier_shares.py > results/tier_shares.md
"""
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DR = HERE.parent / 'data-review'
WINDOWS = {'busy': ('s1b', 'busy'), 'median': ('s1b', 'median'), 'quiet': ('s1c', 'quiet_s1c')}
TIERS = ['T0', 'T1a', 'T1b', 'T1c', 'T2', 'OUT']
INF = float('inf')
# value range (lo, hi] in USDC of the rows that split one address by value bin, in the order of seller_tiers.csv
SPLIT = {('Exa', 'T1c'): (0, 0.001), ('Exa', 'T2'): (0.001, INF),
         ('CoinStats', 'T1c'): (0, 0.001), ('CoinStats', 'T0'): (0.001, 0.01), ('CoinStats', 'T2'): (0.01, INF),
         ('Bitrefill', 'T2'): (0, 0.01), ('Bitrefill', 'OUT'): (0.01, INF)}


def main():
    rows = list(csv.DictReader(open(HERE / 'seller_tiers.csv', encoding='ascii')))
    summ = {(r['source'], r['window'], r['seller']): r for r in csv.DictReader(open(DR / 'target_sellers_all_summary.csv'))}
    bins = {}
    for r in csv.DictReader(open(DR / 'target_sellers_values.csv')):
        up = INF if r['upper_usdc'] == 'inf' else float(r['upper_usdc'])
        bins.setdefault((r['source'], r['window'], r['seller']), []).append((up, int(r['sales']), float(r['usdc'])))
    bad = 0
    for r in rows:
        split = (r['split_by_value_bucket'] == 'yes')
        assert split == ((r['seller'], r['tier']) in SPLIT), r['seller']
        for w, (src, col) in WINDOWS.items():
            k = (src, w, r['seller'])
            if k not in summ:
                n, v = 0, 0.0
            elif not split:
                n, v = int(summ[k]['sales']), float(summ[k]['usdc'])
            else:
                lo, hi = SPLIT[(r['seller'], r['tier'])]
                sel = [(c, u) for up, c, u in bins.get(k, []) if lo < up <= hi]
                n, v = sum(c for c, _ in sel), sum(u for _, u in sel)
            if n != int(r[col + '_sales']) or abs(v - float(r[col + '_usdc'])) > 5e-5:
                bad += 1
                print('mismatch', r['seller'], r['tier'], w, n, r[col + '_sales'], v, r[col + '_usdc'], file=sys.stderr)
            r[w] = (n, v)
    print('# Tier shares of the classified Base sellers\n')
    print('Rows of `seller_tiers.csv` recomputed from `../data-review/`: %s.\n' % ('all equal' if not bad else '%d mismatches' % bad))
    print('Sellers with sales in at least one window: %d.\n' % len({r['seller'] for r in rows if any(r[w][0] for w in WINDOWS)}))
    for excl in (False, True):
        print('## %s BlockRun\n' % ('Without' if excl else 'With'))
        print('| Tier | ' + ' | '.join('%s sales | %s value' % (w, w) for w in WINDOWS) + ' |')
        print('| --- |' + ' --- | --- |' * len(WINDOWS))
        R = [r for r in rows if not (excl and r['seller'] == 'BlockRun')]
        tot = {w: (sum(r[w][0] for r in R), sum(r[w][1] for r in R)) for w in WINDOWS}
        for t in TIERS:
            cells = []
            for w in WINDOWS:
                n = sum(r[w][0] for r in R if r['tier'] == t); v = sum(r[w][1] for r in R if r['tier'] == t)
                cells += ['%.2f%%' % (100 * n / tot[w][0]), '%.2f%%' % (100 * v / tot[w][1])]
            print('| %s | %s |' % (t, ' | '.join(cells)))
        print('| Total | %s |\n' % ' | '.join('{:,} | {:,.2f}'.format(*tot[w]) for w in WINDOWS))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
