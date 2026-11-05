#!/usr/bin/env python3
"""Independent recheck of P1 (POST HOC) for three sellers per window, by another method than p1_compute.py:
pure-Python integers and Fractions, the list csv read directly (daily revenue keyed by the row's own UTC date string,
not by the block clock), a block-by-block loop with a two-pointer lag sum, and FairBind held money recomputed from
the replay sales.npz release blocks. Written and run by the same agent that wrote p1_compute.py.

    p1_check.py --lists LISTS --raw RAW --out results/p1_check.json
"""
import argparse
import csv
import datetime
import gzip
import json
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent
ETH = Fraction('2401.44')
FILES = {'median': ('median/settlements_base_2026-07-24_2026-08-13.csv',
                    'median/settlements_base_prior_2026-07-10_2026-07-23.csv'),
         'busy': ('busy/settlements_base_2026-06-09_2026-06-29.csv',
                  'busy/settlements_base_prior_2026-05-26_2026-06-08.csv')}
A0 = 31073


def gas_usd(gas, wei, p):
    return Fraction(gas) * p / 10 ** 9 * ETH + Fraction(wei) / 10 ** 18 * ETH


def l1(label):
    with gzip.open(J / 'G10_gas/logs_b/g10b_l1fee.tsv.gz', 'rt') as f:
        f.readline()
        for r in csv.DictReader(f, delimiter='\t'):
            if r['label'] == label:
                return int(r['l1_fee_node_wei'])


def pick(rows):
    s1r = [r for r in rows if r['in_S1r'] == '1']
    big = max(s1r, key=lambda r: int(r['revenue']))
    revs = sorted(int(r['revenue']) for r in s1r)
    med = revs[(len(revs) - 1) // 2]
    mid = min(s1r, key=lambda r: (abs(int(r['revenue']) - med), r['address']))
    newc = [r for r in s1r if int(r['C_prior']) == 0]
    new = max(newc, key=lambda r: int(r['revenue']))
    return [big['address'], mid['address'], new['address']]


def read(path, want):
    out = {a: [] for a in want}
    first = None
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            b = int(r['block_number'])
            if first is None:
                first = (b, r['block_time_utc'])
            last = b
            a = r['recipient'].lower()
            if a in out:
                out[a].append((b, int(r['value_atomic']), r['block_time_utc'][:10]))
    return out, first, last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lists', required=True)
    ap.add_argument('--raw', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    cD2 = gas_usd(166809 + 187750, l1('G10-6 open dispute 1 KB, tx gas') +
                  l1('G10-6 decryption check, misbehaviour proven 4 KB, tx gas'), Fraction('0.010'))
    cP = gas_usd(86824, l1('G10-3 RedStone-shaped, 3 package(s) of 1 point, tx gas'), Fraction('0.010'))
    res = dict(note='POST HOC recheck, same agent as p1_compute.py', c_D2_usd=float(cD2), c_P_usd=float(cP), windows={})
    for w, (lf, pf) in FILES.items():
        rows = list(csv.DictReader(open(J / f'R12/results/r12_addr_{w}.csv')))
        byaddr = {r['address']: r for r in rows}
        picks = pick(rows)
        win, (F, t0s), Z = read(Path(a.lists) / lf, picks)
        pri, _, _ = read(Path(a.lists) / pf, picks)
        d0 = datetime.date.fromisoformat(t0s[:10])
        t0 = int(datetime.datetime.strptime(t0s, '%Y-%m-%d %H:%M:%S').replace(tzinfo=datetime.timezone.utc).timestamp())
        z = np.load(Path(a.raw) / f'{w}_r12cost/k1/condition-01-seed-0/sales.npz')
        res['windows'][w] = {}
        T_lo, n_avg = F + A0, Z - (F + A0) + 1
        nblocks = Z - F + 1
        for addr in picks:
            r = byaddr[addr]
            sales = win[addr]
            rev = sum(v for _, v, _ in sales)
            # daily revenue by the row's date string, prior included
            daily = {}
            for _, v, ds in sales + pri[addr]:
                d = (datetime.date.fromisoformat(ds) - d0).days
                daily[d] = daily.get(d, 0) + v
            ndays = (t0 + 2 * (Z - F)) // 86400 - t0 // 86400 + 1
            C = [max([daily.get(x, 0) for x in range(d - 14, d)]) for d in range(ndays)]
            per_block = {}
            for b, v, _ in sales:
                per_block[b] = per_block.get(b, 0) + v
            kst = int(r['k_star'])
            lags = {'own': 2251 + 300 * (kst - 1), 'k1': 2251}
            assert lags['own'] == int(r['L_own'])
            cell = {}
            for lag, L in lags.items():
                # E(t) over the averaging blocks by a running sum; X_m = max(0, max_t E - m C L / 43200)
                E = sum(v for b, v in per_block.items() if T_lo - 1 - L < b <= T_lo - 1)
                worst = {m: Fraction(0) for m in (1, 2, 4, 8)}
                bsum = {m: 0 for m in (1, 2, 4, 8)}
                for t in range(T_lo, Z + 1):
                    E += per_block.get(t, 0) - per_block.get(t - L, 0)
                    c = C[(t0 + 2 * (t - F)) // 86400 - t0 // 86400]
                    for m in worst:
                        u = 43200 * E - m * c * L
                        if u > 0 and u > worst[m]:
                            worst[m] = u
                        bsum[m] += m * c * L
                for m in worst:
                    cell[f'X_H_m{m}_{lag}'] = float(Fraction(worst[m], 43200 * 10 ** 6))
                    cell[f'avgB_H_m{m}_{lag}'] = float(Fraction(bsum[m], 43200 * n_avg * 10 ** 6))
            # (1)
            below = [v for _, v, _ in sales if Fraction(v, 10 ** 6) < cD2]
            # (3) full inspection and FairBind locked money from sales.npz of k*
            zk = np.load(Path(a.raw) / f'{w}_r12cost/k{kst}/condition-01-seed-0/sales.npz')
            addrs = json.loads((Path(a.raw) / f'{w}_r12cost/k{kst}/condition-01-seed-0/sales_addresses.json').read_text())
            i = addrs.index(addr)
            sel = zk['address_index'] == i
            H = 0
            for s, v, R_ in zip(zk['block'][sel].tolist(), zk['value'][sel].tolist(), zk['release'][sel].tolist()):
                H += v * max(0, min(R_, Z + 1) - max(s, T_lo))
            lock_fb = Fraction(1) + Fraction(H, n_avg * 10 ** 6)
            years = Fraction(nblocks * 2, 86400 * 365)
            rv = Fraction(rev, 10 ** 6)
            cell.update(revenue=float(rv), n_sales=len(sales), k_star=kst,
                        D2_count_share=len(below) / len(sales), D2_value_share=float(Fraction(sum(below), rev)),
                        full_tier1a_ratio=float(cP * len(sales) / rv),
                        fairbind_locked=float(lock_fb),
                        cap_fb_4=float(Fraction(4, 100) * lock_fb * years / rv),
                        cap_fb_8=float(Fraction(8, 100) * lock_fb * years / rv),
                        cap_hist_m2_own_8=float(Fraction(8, 100) * Fraction(cell['avgB_H_m2_own']) * years / rv))
            res['windows'][w][addr] = cell
            print(w, addr, json.dumps(cell), flush=True)
    Path(a.out).write_text(json.dumps(res, indent=1) + '\n')


if __name__ == '__main__':
    main()
