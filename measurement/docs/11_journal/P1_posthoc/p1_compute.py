#!/usr/bin/env python3
"""P1 post hoc computations (docs/11_journal/P1_posthoc/calc-rules.md). POST HOC: no registered verdicts.

(1) share of sales whose buyer dispute gas cost exceeds the sale value,
(2) history-bond multiple curve m in {1, 2, 4, 8} on the R12 replay windows (m = 2 must equal R12),
(3) full-inspection proof cost and bond capital cost relative to revenue.

    p1_compute.py --lists $RAW/lists --replayer $REPLAYER \
                  --cache /path/to/cache --out results
"""
import argparse
import csv
import gzip
import hashlib
import json
import math
import pickle
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent                                   # docs/11_journal
WINDOWS = ['median', 'busy']
MS = [1, 2, 4, 8]
LAGS = ['own', 'k1']
SETS = ['S1r', 'S1', 'S2']
ETH = Fraction('2401.44')
PRICES = {'0.010': Fraction('0.010'), '0.0161': Fraction('0.0161'), '1': Fraction(1)}
MAIN_P = '0.010'
RATES = {'4%': Fraction(4, 100), '8%': Fraction(8, 100)}
LISTS = {'median': ('median/settlements_base_2026-07-24_2026-08-13.csv',
                    'median/settlements_base_prior_2026-07-10_2026-07-23.csv',
                    '091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a',
                    '5f701f738aae2cbcb935443e1545aa61d470325bcfceff2a2520f06bac2d9486'),
         'busy': ('busy/settlements_base_2026-06-09_2026-06-29.csv',
                  'busy/settlements_base_prior_2026-05-26_2026-06-08.csv',
                  '91412e264212412afcd4ecdd21e7ca7d98ce7ab8522572fdabef756e6fa10133',
                  '617c9a753bdd331b0c5f2e4f83565cf8789f486fe4105ca3bc00551f0e2e4e21')}


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


def usd(gas, l1wei, p_gwei):
    return Fraction(gas) * p_gwei * Fraction(1, 10 ** 9) * ETH + Fraction(l1wei) * Fraction(1, 10 ** 18) * ETH


def constants():
    g10b = read_tsv(J / 'G10_gas/logs_b/g10b_l1fee.tsv.gz')
    p5 = read_tsv(J / 'G11_gas/logs/p5_l1fee.tsv.gz')
    w_open = int(g10b['G10-6 open dispute 1 KB, tx gas']['l1_fee_node_wei'])
    w_dec = int(g10b['G10-6 decryption check, misbehaviour proven 4 KB, tx gas']['l1_fee_node_wei'])
    g_open = int(p5['P5 non-delivery dispute (honest seller), open, depth 5, 1 KB, tx gas']['tx_gas'])
    g_dec = int(p5['P5 non-delivery dispute (misbehaving seller), decryption challenge, refund, 4 KB, tx gas']['tx_gas'])
    g_t1a = int(p5['P5 proof call, tier 1a Pyth Pro one feed, depth 5, tx gas']['tx_gas'])
    g_t0 = int(p5['P5 proof call, tier 0 storage proof (fixture), depth 5, tx gas']['tx_gas'])
    w_rs3 = int(g10b['G10-3 RedStone-shaped, 3 package(s) of 1 point, tx gas']['l1_fee_node_wei'])
    w_sp0 = int(g10b['G10-4 full: header, account and storage proof, tx gas']['l1_fee_node_wei'])
    assert (g_open, g_dec, g_t1a, g_t0) == (166809, 187750, 86824, 604522)
    C = dict(dispute={'D2': (g_open + g_dec, w_open + w_dec), 'D1': (g_open, w_open)},
             proof={'tier1a': (g_t1a, w_rs3), 'tee': (36440, 2157333560), 'tier0': (g_t0 + 5000, w_sp0)})
    # reproduction checks against K11b (k11b_output.md sections 11 and 14)
    chk = {'D2@1': (float(usd(*C['dispute']['D2'], Fraction(1))), 0.851522),
           'D2@0.0161': (float(usd(*C['dispute']['D2'], Fraction('0.0161'))), 0.013778),
           'tier1a@0.010': (float(usd(*C['proof']['tier1a'], Fraction('0.010'))), 0.00209015),
           'tee@0.010': (float(usd(*C['proof']['tee'], Fraction('0.010'))), 0.00088027),
           'tier0@0.010': (float(usd(*C['proof']['tier0'], Fraction('0.010'))), 0.01470496)}
    for k, (got, want) in chk.items():
        nd = 6 if k.startswith('D2') else 8
        assert round(got, nd) == want, (k, got, want)
    C['k11b_reproduction'] = {k: dict(got=g, k11b=w) for k, (g, w) in chk.items()}
    C['w'] = dict(w_open=w_open, w_dec=w_dec, w_rs3=w_rs3, w_sp0=w_sp0)
    return C


def load_window(rc, lists, w, cache):
    """Per address (blocks, values) of the window list, prior daily sums, list meta; cached in `cache`."""
    cp = Path(cache) / f'p1_lists_{w}.pkl'
    if cp.exists():
        return pickle.loads(cp.read_bytes())
    lf, pf, lsha, psha = LISTS[w]
    assert sha256(Path(lists) / lf) == lsha, f'{w} window list hash'
    assert sha256(Path(lists) / pf) == psha, f'{w} prior list hash'
    addrs = [r['address'] for r in csv.DictReader(open(J / f'R12/results/r12_addr_{w}.csv'))]
    per, meta = rc.read_list(Path(lists) / lf, addrs)
    prior, pmeta = rc.read_list(Path(lists) / pf, addrs)
    day0 = meta['first_time'] // 86400
    prior_daily = {a: rc.daily_sums(prior[a][0], prior[a][1], pmeta['first_block'], pmeta['first_time'], day0)
                   for a in addrs}
    obj = dict(per={a: (per[a][0], per[a][1]) for a in addrs}, meta=meta, prior_daily=prior_daily, addrs=addrs)
    Path(cache).mkdir(parents=True, exist_ok=True)
    cp.write_bytes(pickle.dumps(obj))
    return obj


def q3(xs):
    xs = np.asarray(xs, dtype=float)
    if not xs.size:
        return None
    a, b, c = np.quantile(xs, [0.25, 0.5, 0.75])
    return dict(n=int(xs.size), q1=float(a), median=float(b), q3=float(c))


def window(rc, W, w, C, R12, R13):
    reg = rc.REGISTERED
    S_ = 2 * reg['blocks_per_day']
    V = reg['V_atomic']
    b = reg['b_atomic']
    rows = {r['address']: r for r in csv.DictReader(open(J / f'R12/results/r12_addr_{w}.csv'))}
    addrs = W['addrs']
    sets = {'S1r': [a for a in addrs if rows[a]['in_S1r'] == '1'],
            'S1': [a for a in addrs if rows[a]['in_S1'] == '1'], 'S2': list(addrs)}
    meta = W['meta']
    win = rc.Window(meta['first_block'], meta['last_block'], meta['first_time'])
    rw = R12['windows'][w]
    assert (win.first, win.last, win.n_avg) == (rw['first_block'], rw['last_block'], rw['n_avg'])
    n_avg = win.n_avg
    out = dict(first_block=win.first, last_block=win.last, n_blocks=win.N, n_avg=n_avg,
               days=win.N * 2 / 86400, set_sizes={s: len(x) for s, x in sets.items()})
    seller = {a: dict(revenue=int(rows[a]['revenue']), n_sales=int(len(W['per'][a][0])),
                      k_star=int(rows[a]['k_star'])) for a in addrs}
    for a in addrs:
        assert seller[a]['revenue'] == int(W['per'][a][1].sum())

    # ---------------- (2) history-bond multiple
    caps = {}
    for a in addrs:
        blocks, values = W['per'][a]
        daily = dict(W['prior_daily'].get(a, {}))
        for d, x in rc.daily_sums(blocks, values, win.first, win.first_time, win.day0).items():
            daily[d] = daily.get(d, 0) + x
        caps[a], _ = rc.history_caps(daily, win.n_days)
    cell = {}          # cell[m][lag][a] = (X, Usum, Bsum)
    for m in MS:
        cell[m] = {lag: {} for lag in LAGS}
        for a in addrs:
            blocks, values = W['per'][a]
            cs = np.cumsum(win.per_block(blocks, values))
            ca = np.asarray(caps[a], dtype=np.int64)
            for lag in LAGS:
                L = int(rows[a][f'L_{lag}'])
                E = win.in_lag(cs, L)
                Bn = 2 * m * ca[win.day] * L
                us, ux = rc.uncovered(E * S_, Bn, win.a0)
                cell[m][lag][a] = (ux, us, rc.exact_sum(Bn[win.a0:]))
    # m = 2 check, per address (exact) and per set (rel 1e-12)
    check = dict(per_address_mismatches=0, set_mismatches=[])
    for lag in LAGS:
        for a in addrs:
            X, U, B = cell[2][lag][a]
            if (X, U, B) != (int(rows[a][f'X_H_{lag}']), int(rows[a][f'Usum_H_{lag}']), int(rows[a][f'Bsum_H_{lag}'])):
                check['per_address_mismatches'] += 1
    curve = {}
    for m in MS:
        curve[str(m)] = {}
        for lag in LAGS:
            curve[str(m)][lag] = {}
            for s in SETS:
                S = sets[s]
                XH = sum(cell[m][lag][a][0] for a in S)
                BH = Fraction(sum(cell[m][lag][a][2] for a in S), S_ * n_avg * 10 ** 6)
                LFB = rw['lag'][lag][s]['L_FB']
                rec = dict(n=len(S), X_sum_H=XH / S_ / 1e6, sumB_H=float(BH),
                           U_avg_H=sum(cell[m][lag][a][1] for a in S) / S_ / n_avg / 1e6,
                           X_gt_V_H=sum(1 for a in S if cell[m][lag][a][0] > V * S_),
                           ratio_LFB_BH=float(Fraction(LFB) / BH) if BH else None,
                           rejected_value=0.0)
                curve[str(m)][lag][s] = rec
                if m == 2:
                    r12 = rw['lag'][lag][s]
                    for key in ('X_sum_H', 'sumB_H', 'U_avg_H', 'X_gt_V_H'):
                        g, e = rec[key], r12[key]
                        if not (g == e or abs(g - e) <= 1e-12 * max(abs(e), 1e-300)):
                            check['set_mismatches'].append([lag, s, key, g, e])
    check['ok'] = check['per_address_mismatches'] == 0 and not check['set_mismatches']
    out['history_curve'] = curve
    out['m2_check'] = check
    a13 = R13['windows'][w]['agg']
    out['fairbind_side'] = {lag: dict(nV=rw['lag'][lag]['S1r']['FB_bound'], L_FB=rw['lag'][lag]['S1r']['L_FB'])
                            for lag in LAGS}
    out['fairbind_side']['R13'] = dict(sum_EN=a13['sum_EN'] / 1e6, sum_EG=a13['sum_EG'] / 1e6,
                                       sum_q95_G=a13['sum_q95_G'] / 1e6, sum_q95_N=a13['sum_q95_N'] / 1e6, n=a13['n'])

    # ---------------- (1) dispute cost vs sale value (S1r, whole window)
    S = sets['S1r']
    vals = np.concatenate([W['per'][a][1] for a in S]).astype(np.int64)
    disp = {}
    for dk, (g, wl) in C['dispute'].items():
        disp[dk] = {}
        for pk, p in PRICES.items():
            c = usd(g, wl, p)                                   # USD
            # c > v  <=>  v_atomic < c * 1e6  <=>  v_atomic <= ceil(c * 1e6) - 1 (v_atomic an integer)
            lim = math.ceil(c * 10 ** 6) - 1
            more = vals <= lim
            per_c, per_v = [], []
            for a in S:
                v = W['per'][a][1]
                if len(v) == 0:
                    continue
                mk = v <= lim
                per_c.append(mk.sum() / len(v))
                per_v.append(v[mk].sum() / v.sum() if v.sum() else 0.0)
            disp[dk][pk] = dict(cost_usd=float(c), share_count=float(more.mean()),
                                share_value=float(Fraction(int(vals[more].sum()), int(vals.sum()))),
                                n_sales=int(vals.size), sellers_count_share=q3(per_c), sellers_value_share=q3(per_v),
                                sellers_all_sales_below=int(sum(1 for x in per_c if x == 1.0)))
    out['dispute'] = disp
    qv = np.quantile(vals / 1e6, [0.25, 0.5, 0.75])
    out['sale_value_quantiles_usdc'] = dict(q1=float(qv[0]), median=float(qv[1]), q3=float(qv[2]),
                                            n=int(vals.size), total=float(vals.sum() / 1e6))

    # ---------------- (3) full inspection and capital cost (S1r)
    full = {}
    for ck, (g, wl) in C['proof'].items():
        full[ck] = {}
        for pk, p in PRICES.items():
            c = usd(g, wl, p)
            ratios = [float(c * seller[a]['n_sales'] / Fraction(seller[a]['revenue'], 10 ** 6)) for a in S]
            tot = c * sum(seller[a]['n_sales'] for a in S) / Fraction(sum(seller[a]['revenue'] for a in S), 10 ** 6)
            full[ck][pk] = dict(cost_per_sale_usd=float(c), aggregate_ratio=float(tot), sellers=q3(ratios),
                                sellers_ratio_gt_1=sum(1 for x in ratios if x > 1),
                                share_sellers_ratio_gt_1=sum(1 for x in ratios if x > 1) / len(ratios),
                                total_cost_usd=float(c * sum(seller[a]['n_sales'] for a in S)))
    out['full_inspection'] = full
    Dyears = Fraction(win.N * 2, 86400 * 365)
    bonds = {}                                            # per address average locked USDC over T
    for m in MS:
        for lag in LAGS:
            bonds[f'history_m{m}_{lag}'] = {a: Fraction(cell[m][lag][a][2], S_ * n_avg * 10 ** 6) for a in S}
    for lag in LAGS:
        bonds[f'ratecap_{lag}'] = {a: Fraction(int(rows[a]['rho2']) * int(rows[a][f'L_{lag}']), S_ * 10 ** 6)
                                   for a in S}
    bonds['fairbind_kstar'] = {a: Fraction(b, 10 ** 6) + Fraction(int(rows[a][f"Hnum_k{rows[a]['k_star']}"]),
                                                                    n_avg * 10 ** 6) for a in S}
    # FairBind sum must equal R12 L_FB
    lfb = float(sum(bonds['fairbind_kstar'].values()))
    assert abs(lfb - rw['lag']['own']['S1r']['L_FB']) < 1e-9, (lfb, rw['lag']['own']['S1r']['L_FB'])
    cap = {}
    for bk, bd in bonds.items():
        cap[bk] = dict(sum_locked=float(sum(bd.values())))
        for rk, r in RATES.items():
            costs = {a: r * bd[a] * Dyears for a in S}
            ratios = [float(costs[a] / Fraction(seller[a]['revenue'], 10 ** 6)) for a in S]
            cap[bk][rk] = dict(total_cost_usd=float(sum(costs.values())),
                               aggregate_ratio=float(sum(costs.values()) /
                                                     Fraction(sum(seller[a]['revenue'] for a in S), 10 ** 6)),
                               sellers=q3(ratios))
    out['capital'] = cap
    out['revenue_S1r'] = sum(seller[a]['revenue'] for a in S) / 1e6
    out['n_sales_S1r'] = sum(seller[a]['n_sales'] for a in S)
    # per-seller file
    with open(Path(OUT) / f'p1_sellers_{w}.csv', 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        cD = usd(*C['dispute']['D2'], PRICES[MAIN_P])
        lim = math.ceil(cD * 10 ** 6) - 1
        assert Fraction(lim) < cD * 10 ** 6 <= Fraction(lim + 1)
        cP = usd(*C['proof']['tier1a'], PRICES[MAIN_P])
        head = ['address', 'in_S1r', 'revenue_atomic', 'n_sales', 'C_prior', 'k_star', 'D2_count_share_p010',
                'D2_value_share_p010', 'full_tier1a_ratio_p010'] + \
            [f'X_H_m{m}_{lag}' for m in MS for lag in LAGS] + [f'Bsum_H_m{m}_{lag}' for m in MS for lag in LAGS]
        wr.writerow(head)
        for a in addrs:
            v = W['per'][a][1]
            rev = int(v.sum())
            mk = v <= lim
            wr.writerow([a, rows[a]['in_S1r'], rev, len(v), rows[a]['C_prior'], rows[a]['k_star'],
                         float(mk.mean()) if len(v) else '', float(v[mk].sum() / rev) if rev else '',
                         float(cP * len(v) / Fraction(rev, 10 ** 6)) if rev else ''] +
                        [cell[m][lag][a][0] for m in MS for lag in LAGS] +
                        [cell[m][lag][a][2] for m in MS for lag in LAGS])
    return out


def pct(x, nd=2):
    return '' if x is None else f'{100 * x:.{nd}f}%'


def sig(x):
    return '' if x is None else f'{x:.3g}'


def tables(R):
    L = ['# P1 posthoc calculation Table (post hoc, registration verdict none)', '']
    L += ['## (1) dispute cost > sales amount sales share (S1r, window whole sales)', '',
          '| window | dispute | p (gwei) | c_D (USD) | count share | amount share | per seller count share Q1 / median / Q3 | per seller amount share Q1 / median / Q3 | all sales c_D below seller |',
          '|---|---|---|---|---|---|---|---|---|']
    for w in WINDOWS:
        W = R['windows'][w]
        for dk in ('D2', 'D1'):
            for pk in PRICES:
                d = W['dispute'][dk][pk]
                sc, sv = d['sellers_count_share'], d['sellers_value_share']
                L.append(f"| {w} | {dk} | {pk} | {d['cost_usd']:.6f} | {pct(d['share_count'])} | {pct(d['share_value'])} | "
                         f"{pct(sc['q1'])} / {pct(sc['median'])} / {pct(sc['q3'])} | {pct(sv['q1'])} / {pct(sv['median'])} / {pct(sv['q3'])} | "
                         f"{d['sellers_all_sales_below']} / {sc['n']} |")
    L += ['', 'sales amount percentile(count weighted, USDC): ' + '; '.join(
        f"{w} Q1 {R['windows'][w]['sale_value_quantiles_usdc']['q1']:.4g}, median {R['windows'][w]['sale_value_quantiles_usdc']['median']:.4g}, "
        f"Q3 {R['windows'][w]['sale_value_quantiles_usdc']['q3']:.4g} (sales {R['windows'][w]['sale_value_quantiles_usdc']['n']:,} items)" for w in WINDOWS), '']
    L += ['## (2) history deposit multiple curve (S1r, USDC)', '']
    for w in WINDOWS:
        W = R['windows'][w]
        fs = W['fairbind_side']
        L += [f"### {w} (n = {W['set_sizes']['S1r']}; m = 2 match: {'pass' if W['m2_check']['ok'] else 'failure'})", '',
              '| m | ΣX^H own | X>V own | ΣB̄^H own | L_FB/ΣB̄^H own | ΣX^H k1 | X>V k1 | ΣB̄^H k1 | L_FB/ΣB̄^H k1 | refused revenue |',
              '|---|---|---|---|---|---|---|---|---|---|']
        for m in MS:
            o, k = W['history_curve'][str(m)]['own']['S1r'], W['history_curve'][str(m)]['k1']['S1r']
            L.append(f"| {m} | {o['X_sum_H']:,.2f} | {o['X_gt_V_H']} | {o['sumB_H']:,.2f} | {o['ratio_LFB_BH']:.3f} | "
                     f"{k['X_sum_H']:,.2f} | {k['X_gt_V_H']} | {k['sumB_H']:,.2f} | {k['ratio_LFB_BH']:.3f} | none |")
        L += ['', f"FairBind side(m and independent, R12 and R13 original value): n × V = {fs['own']['nV']:,.2f}, L_FB = {fs['own']['L_FB']:,.2f}, "
                  f"R13 Σ E[N] = {fs['R13']['sum_EN']:,.2f}, Σ E[G] = {fs['R13']['sum_EG']:,.2f}, Σ q95(G) = {fs['R13']['sum_q95_G']:,.2f}", '']
    L += ['## (3a) full inspection cost / revenue (S1r)', '',
          '| window | proof | p (gwei) | c_P (USD) | set ratio | per seller Q1 / median / Q3 | ratio > 1 seller |', '|---|---|---|---|---|---|---|']
    for w in WINDOWS:
        for ck in ('tier1a', 'tee', 'tier0'):
            for pk in PRICES:
                d = R['windows'][w]['full_inspection'][ck][pk]
                s = d['sellers']
                L.append(f"| {w} | {ck} | {pk} | {d['cost_per_sale_usd']:.8f} | {pct(d['aggregate_ratio'])} | "
                         f"{pct(s['q1'])} / {pct(s['median'])} / {pct(s['q3'])} | {d['sellers_ratio_gt_1']} / {s['n']} |")
    L += ['', '## (3b) deposit capital cost / revenue (S1r, r × mean locked money × window period)', '',
          '| window | bundle | Σ mean locked money | r | set ratio | per seller Q1 / median / Q3 |', '|---|---|---|---|---|---|']
    for w in WINDOWS:
        for bk, d in R['windows'][w]['capital'].items():
            for rk in RATES:
                s = d[rk]['sellers']
                L.append(f"| {w} | {bk} | {d['sum_locked']:,.2f} | {rk} | {pct(d[rk]['aggregate_ratio'], 3)} | "
                         f"{pct(s['q1'], 3)} / {pct(s['median'], 3)} / {pct(s['q3'], 3)} |")
    return '\n'.join(L) + '\n'


def main():
    global OUT
    ap = argparse.ArgumentParser()
    ap.add_argument('--lists', required=True)
    ap.add_argument('--replayer', required=True)
    ap.add_argument('--cache', required=True)
    ap.add_argument('--out', default=str(HERE / 'results'))
    a = ap.parse_args()
    OUT = a.out
    Path(OUT).mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(Path(a.replayer) / 'experiments/replay'))
    import r12_compute as rc
    sums = dict(l.split()[::-1] for l in open(J / 'R12/results/SHA256SUMS.txt') if l.strip())
    for n in ('r12_addr_median.csv', 'r12_addr_busy.csv', 'r12_results.json'):
        assert sha256(J / 'R12/results' / n) == sums[n], n
    sums13 = dict(l.split()[::-1] for l in open(J / 'R13/results/SHA256SUMS.txt') if l.strip())
    assert sha256(J / 'R13/results/r13_results.json') == sums13['r13_results.json']
    C = constants()
    R12 = json.load(open(J / 'R12/results/r12_results.json'))
    R13 = json.load(open(J / 'R13/results/r13_results.json'))
    R = dict(note='POST HOC: no registered verdicts (calc-rules.md)', rules_sha256=sha256(HERE / 'calc-rules.md'),
             constants=dict(dispute=C['dispute'], proof=C['proof'], l1=C['w'], eth_usd=str(ETH),
                            prices_gwei=list(PRICES), main_price_gwei=MAIN_P,
                            k11b_reproduction=C['k11b_reproduction']),
             numpy=np.__version__, windows={})
    for w in WINDOWS:
        W = load_window(rc, a.lists, w, a.cache)
        R['windows'][w] = window(rc, W, w, C, R12, R13)
        print(w, 'm2 check', R['windows'][w]['m2_check'], flush=True)
    (Path(OUT) / 'p1_results.json').write_text(json.dumps(R, indent=1, ensure_ascii=False, default=str) + '\n')
    (Path(OUT) / 'p1_tables.md').write_text(tables(R))


if __name__ == '__main__':
    main()
