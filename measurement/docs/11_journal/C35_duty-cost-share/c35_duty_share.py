#!/usr/bin/env python3
"""C35 (calc-rules.md): share of sales whose value is at least the buyer's duty cost (one dispute's gas), by count and
by value, per window, for the replayed sales (R12 set S1r) and the six data sellers. POST HOC: no registered verdict.

    python3 -I c35_duty_share.py --lists $RAW/lists --out results
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent                                            # docs/11_journal
ETH = Fraction('2401.44')
PRICES = {'0.010': Fraction('0.010'), '0.0161': Fraction('0.0161'), '1': Fraction(1)}
MAIN = ('D2', '0.010')
CELLS = [('D2', '0.010'), ('D1', '0.010'), ('D2', '0.0161'), ('D2', '1')]
LISTS = {'median': ('median/settlements_base_2026-07-24_2026-08-13.csv',
                    '091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a'),
         'busy': ('busy/settlements_base_2026-06-09_2026-06-29.csv',
                  '91412e264212412afcd4ecdd21e7ca7d98ce7ab8522572fdabef756e6fa10133')}
# P1 results.md section 1 (c_D > v share): n sales, count share %, value share %
P1 = {'median': dict(n=1153924, cells={('D2', '0.010'): (83.69, 2.05), ('D1', '0.010'): (77.52, 1.67),
                                       ('D2', '0.0161'): (90.51, 2.79), ('D2', '1'): (97.40, 10.35)}),
      'busy': dict(n=762322, cells={('D2', '0.010'): (80.17, 5.79), ('D1', '0.010'): (75.00, 4.89),
                                    ('D2', '0.0161'): (89.13, 8.65), ('D2', '1'): (98.48, 31.04)})}
ADDR = {'StableEnrich': '0x325bdf6f7efab24a2210c48c1b64cab2eae1d430', 'OneSource': '0x52e29e0d2aa49bfbfc548c0a9f2196f4aa51f3ea',
        'CoinMarketCap': '0x3c5f3a6ce224bb89d72f5eb4232ecc27f67b3eea', 'StableApify': '0x23d931f95831cee50b5f5edf4d0e88270f6c8411',
        'Exa': '0x6d6e695b09861467c7d462f5aaf31cf3540b9192', 'CoinStats': '0x0750a9e669c37fe1a1847e4b8f9e16f07c16162f'}
SIX = list(ADDR)
PART = {'StableEnrich': 500000, 'Exa': 1000, 'CoinStats': 10000}      # T01t tier-0/1 part: value_atomic <= this
PAPER_REV = {'busy': 1536.73, 'median': 1218.43, 'quiet': 778.09}
EDGES = [-1, 1000, 10000, 100000, 200000, 500000, 1000000, 5000000, 10 ** 30]   # target_sellers bins (lo, hi]
VALCSV = J / 'F/data-review/target_sellers_values.csv'


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def read_tsv(path):
    d = {}
    with gzip.open(path, 'rt') as fh:
        fh.readline()
        for r in csv.DictReader(fh, delimiter='\t'):
            d[r['label']] = r
    return d


def usd(gas, l1wei, p):
    return Fraction(gas) * p * Fraction(1, 10 ** 9) * ETH + Fraction(l1wei) * Fraction(1, 10 ** 18) * ETH


def costs():
    g10b = read_tsv(J / 'G10_gas/logs_b/g10b_l1fee.tsv.gz')
    p5 = read_tsv(J / 'G11_gas/logs/p5_l1fee.tsv.gz')
    w_open = int(g10b['G10-6 open dispute 1 KB, tx gas']['l1_fee_node_wei'])
    w_dec = int(g10b['G10-6 decryption check, misbehaviour proven 4 KB, tx gas']['l1_fee_node_wei'])
    g_open = int(p5['P5 non-delivery dispute (honest seller), open, depth 5, 1 KB, tx gas']['tx_gas'])
    g_dec = int(p5['P5 non-delivery dispute (misbehaving seller), decryption challenge, refund, 4 KB, tx gas']['tx_gas'])
    assert (g_open, g_dec) == (166809, 187750)
    gw = {'D2': (g_open + g_dec, w_open + w_dec), 'D1': (g_open, w_open)}
    c = {(d, p): usd(*gw[d], PRICES[p]) for d, p in CELLS}
    assert round(float(c[('D2', '1')]), 6) == 0.851522 and round(float(c[('D2', '0.0161')]), 6) == 0.013778
    return c, dict(g_open=g_open, g_dec=g_dec, w_open=w_open, w_dec=w_dec)


def read_list(path, addrs):
    per = {a: [] for a in addrs}
    with open(path, newline='') as f:
        rd = csv.reader(f)
        head = next(rd)
        ia, iv = head.index('recipient'), head.index('value_atomic')
        for row in rd:
            a = row[ia].lower()
            if a in per:
                per[a].append(int(row[iv]))
    return {a: np.asarray(v, dtype=np.int64) for a, v in per.items()}


def at_least(vals, c_usd):
    """sales with value_atomic / 1e6 >= c_usd: value_atomic >= ceil(c_usd * 1e6)."""
    thr = math.ceil(c_usd * 10 ** 6)
    m = vals >= thr
    return int(m.sum()), int(vals[m].sum()), int(vals.size), int(vals.sum())


def pct(a, b):
    return 100.0 * a / b if b else None


def q3(xs):
    xs = np.asarray([x for x in xs if x is not None], dtype=float)
    if not xs.size:
        return None
    a, b, c = np.quantile(xs, [0.25, 0.5, 0.75])
    return dict(n=int(xs.size), q1=float(a), median=float(b), q3=float(c))


def bins_quiet():
    out = {}
    for r in csv.DictReader(open(VALCSV, encoding='ascii')):
        if r['source'] != 's1c' or r['window'] != 'quiet' or r['seller'] not in ADDR:
            continue
        hi = 10 ** 30 if r['upper_usdc'] == 'inf' else round(float(r['upper_usdc']) * 10 ** 6)
        out.setdefault(r['seller'], []).append((EDGES[EDGES.index(hi) - 1], hi, int(r['sales']),
                                                 round(float(r['usdc']) * 10 ** 6)))
    return out


def bins_s1b(w):
    out = {}
    for r in csv.DictReader(open(VALCSV, encoding='ascii')):
        if r['source'] == 's1b' and r['window'] == w and r['seller'] in ADDR:
            out.setdefault(r['seller'], {})[r['upper_usdc']] = (int(r['sales']), round(float(r['usdc']) * 10 ** 6))
    return out


def bin_bounds(lo, hi, n, S, thr):
    """bin (lo, hi] atomic, n sales, sum S; count and value of sales >= thr (atomic), as [min, max]."""
    if thr <= lo + 1:
        return (n, n), (S, S)
    if thr > hi:
        return (0, 0), (0, 0)
    # others in (lo, thr - 1], high ones in [thr, hi]
    m_min = max(0, math.ceil((S - n * (thr - 1)) / (hi - thr + 1)))
    m_max = min(n, (S - n * (lo + 1)) // (thr - lo - 1)) if thr - lo - 1 > 0 else n
    m_max = max(m_max, m_min)
    v_min = max(m_min * thr, S - (n - m_min) * (thr - 1))
    v_max = min(m_max * hi, S - (n - m_max) * (lo + 1))
    return (m_min, m_max), (v_min, v_max)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--lists', required=True)
    ap.add_argument('--out', default='results')
    a = ap.parse_args()
    OUT = Path(a.out)
    OUT = OUT if OUT.is_absolute() else HERE / OUT
    OUT.mkdir(parents=True, exist_ok=True)
    C, gasinfo = costs()
    RES = dict(meta=dict(note='POST HOC, no registered verdict; rules calc-rules.md',
                         script_sha256=sha256(__file__), costs_usd={f'{d}@{p}': float(v) for (d, p), v in C.items()},
                         thresholds_atomic={f'{d}@{p}': math.ceil(v * 10 ** 6) for (d, p), v in C.items()},
                         gas=gasinfo, inputs={}), checks={}, all={}, six={}, six_full={})
    pooled = {s: [] for s in SIX}                      # busy + median per-sale values for the quiet imputation
    for w, (fn, want) in LISTS.items():
        path = Path(a.lists) / fn
        got = sha256(path)
        RES['meta']['inputs'][w] = dict(file=fn, sha256=got)
        assert got == want, f'{w} list hash'
        rows = {r['address']: r for r in csv.DictReader(open(J / f'R12/results/r12_addr_{w}.csv'))}
        s1r = [x for x in rows if rows[x]['in_S1r'] == '1']
        addrs = set(s1r) | set(ADDR.values())
        per = read_list(path, addrs)
        allv = np.concatenate([per[x] for x in s1r])
        # ---- reproduction of P1 section 1 (c_D > v)
        chk = dict(n=int(allv.size), n_P1=P1[w]['n'], cells={})
        ok = allv.size == P1[w]['n']
        RES['all'][w] = dict(n_sellers=len(s1r), n_sales=int(allv.size), revenue_usdc=int(allv.sum()) / 1e6, cells={})
        seller_rows = []
        for cell in CELLS:
            k, kv, n, tot = at_least(allv, C[cell])
            below_c, below_v = 100 - pct(k, n), 100 - pct(kv, tot)
            p1c, p1v = P1[w]['cells'][cell]
            good = round(below_c, 2) == p1c and round(below_v, 2) == p1v
            ok &= good
            chk['cells'][f'{cell[0]}@{cell[1]}'] = dict(below_count=below_c, below_value=below_v, P1=(p1c, p1v), match=good)
            shc, shv = [], []
            for x in s1r:
                kk, kkv, nn, tt = at_least(per[x], C[cell])
                shc.append(pct(kk, nn)); shv.append(pct(kkv, tt))
            all_ge = sum(1 for x in s1r if per[x].size and at_least(per[x], C[cell])[0] == per[x].size)
            none_ge = sum(1 for x in s1r if per[x].size and at_least(per[x], C[cell])[0] == 0)
            RES['all'][w]['cells'][f'{cell[0]}@{cell[1]}'] = dict(
                c_usd=float(C[cell]), n_ge=k, value_ge_usdc=kv / 1e6, count_share=pct(k, n), value_share=pct(kv, tot),
                seller_count_share=q3(shc), seller_value_share=q3(shv), sellers_all_ge=all_ge, sellers_none_ge=none_ge)
        chk['pass'] = bool(ok)
        RES['checks'][f'P1_{w}'] = chk
        for x in s1r:
            r = dict(address=x, n_sales=int(per[x].size), revenue_usdc=int(per[x].sum()) / 1e6)
            for cell in CELLS:
                kk, kkv, nn, tt = at_least(per[x], C[cell])
                r[f'n_ge_{cell[0]}_{cell[1]}'] = kk
                r[f'value_ge_{cell[0]}_{cell[1]}'] = kkv / 1e6
            seller_rows.append(r)
        with open(OUT / f'c35_sellers_{w}.csv', 'w', newline='') as fh:
            wr = csv.DictWriter(fh, fieldnames=list(seller_rows[0]))
            wr.writeheader(); wr.writerows(seller_rows)
        # ---- six data sellers
        ref = bins_s1b(w)
        RES['six'][w], RES['six_full'][w] = {}, {}
        sixchk = {}
        for full, dest in ((False, RES['six'][w]), (True, RES['six_full'][w])):
            agg = []
            for s in SIX:
                v = per[ADDR[s]]
                if not full and s in PART:
                    v = v[v <= PART[s]]
                if not full:
                    pooled[s].append(v)
                agg.append(v)
                dest[s] = dict(n_sales=int(v.size), revenue_usdc=int(v.sum()) / 1e6, cells={})
                if full:                                   # check the full address against the s1b bins
                    rb = ref.get(s, {})
                    sixchk[s] = (int(v.size), int(v.sum())) == (sum(b[0] for b in rb.values()),
                                                                sum(b[1] for b in rb.values()))
            agg = np.concatenate(agg)
            dest['six'] = dict(n_sales=int(agg.size), revenue_usdc=int(agg.sum()) / 1e6, cells={})
            for s in SIX + ['six']:
                v = agg if s == 'six' else (per[ADDR[s]] if (full or s not in PART) else per[ADDR[s]][per[ADDR[s]] <= PART[s]])
                for cell in CELLS:
                    k, kv, n, tot = at_least(v, C[cell])
                    dest[s]['cells'][f'{cell[0]}@{cell[1]}'] = dict(n_ge=k, value_ge_usdc=kv / 1e6,
                                                                    count_share=pct(k, n), value_share=pct(kv, tot))
        rev_ok = round(RES['six'][w]['six']['revenue_usdc'], 2) == PAPER_REV[w]
        RES['checks'][f'six_{w}'] = dict(s1b_bins_match=sixchk, revenue=RES['six'][w]['six']['revenue_usdc'],
                                         paper=PAPER_REV[w], revenue_match=rev_ok,
                                         pass_=bool(rev_ok and all(sixchk.values())))
    # ---- quiet window: s1c bins, bounds and reference imputation
    qb = bins_quiet()
    Q = {}
    rev = 0
    for s in SIX:
        bl = [b for b in qb.get(s, []) if (s not in PART or b[1] <= PART[s])]
        rev += sum(b[3] for b in bl)
        Q[s] = bl
    RES['checks']['six_quiet'] = dict(revenue=rev / 1e6, paper=PAPER_REV['quiet'],
                                      revenue_match=round(rev / 1e6, 2) == PAPER_REV['quiet'])
    pooled = {s: (np.concatenate(pooled[s]) if pooled[s] else np.zeros(0, dtype=np.int64)) for s in SIX}
    RES['six']['quiet'] = {}
    tot_all = dict(n=0, S=0)
    agg_cells = {}
    for s in SIX:
        n_s = sum(b[2] for b in Q[s]); S_s = sum(b[3] for b in Q[s])
        tot_all['n'] += n_s; tot_all['S'] += S_s
        RES['six']['quiet'][s] = dict(n_sales=n_s, revenue_usdc=S_s / 1e6, cells={})
        for cell in CELLS:
            thr = math.ceil(C[cell] * 10 ** 6)
            cm = [0, 0]; vm = [0, 0]; ci = 0.0; vi = 0.0; exact = True
            for lo, hi, n, S in Q[s]:
                (a1, a2), (b1, b2) = bin_bounds(lo, hi, n, S, thr)
                cm[0] += a1; cm[1] += a2; vm[0] += b1; vm[1] += b2
                if a1 != a2:
                    exact = False
                    pv = pooled[s][(pooled[s] > lo) & (pooled[s] <= hi)]
                    if pv.size:
                        fc = float((pv >= thr).mean()); fv = float(pv[pv >= thr].sum() / pv.sum())
                    else:
                        fc = fv = float('nan')
                    ci += min(max(fc * n, a1), a2) if fc == fc else float('nan')
                    vi += min(max(fv * S, b1), b2) if fv == fv else float('nan')
                else:
                    ci += a1; vi += b1
            d = dict(exact=exact, count_share=[pct(cm[0], n_s), pct(cm[1], n_s)],
                     value_share=[pct(vm[0], S_s), pct(vm[1], S_s)],
                     count_share_imputed=pct(ci, n_s), value_share_imputed=pct(vi, S_s))
            RES['six']['quiet'][s]['cells'][f'{cell[0]}@{cell[1]}'] = d
            g = agg_cells.setdefault(cell, dict(c=[0, 0], v=[0, 0], ci=0.0, vi=0.0, exact=True))
            g['c'][0] += cm[0]; g['c'][1] += cm[1]; g['v'][0] += vm[0]; g['v'][1] += vm[1]
            g['ci'] += ci; g['vi'] += vi; g['exact'] &= exact
    RES['six']['quiet']['six'] = dict(n_sales=tot_all['n'], revenue_usdc=tot_all['S'] / 1e6, cells={
        f'{c[0]}@{c[1]}': dict(exact=g['exact'], count_share=[pct(g['c'][0], tot_all['n']), pct(g['c'][1], tot_all['n'])],
                               value_share=[pct(g['v'][0], tot_all['S']), pct(g['v'][1], tot_all['S'])],
                               count_share_imputed=pct(g['ci'], tot_all['n']), value_share_imputed=pct(g['vi'], tot_all['S']))
        for c, g in agg_cells.items()})
    with open(OUT / 'c35_results.json', 'w') as fh:
        json.dump(RES, fh, indent=1, ensure_ascii=False, default=str)
    print(json.dumps(RES['checks'], indent=1, ensure_ascii=False, default=str))


if __name__ == '__main__':
    main()
