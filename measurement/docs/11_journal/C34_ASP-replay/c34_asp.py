#!/usr/bin/env python3
"""C34 (calc-rules.md): ASP's rolling reserve (and settlement delay, exposure cap) on the bond replay of R12, against
FairBind's matched payout from W3.

Reads the registered R12 sale lists with r12_compute (c13a832, unchanged), reproduces the R12 history bond and
unbonded rate cap per seller, then computes for every grid cell the rolling reserve's uncovered revenue at the
lag's end (worst moment and time average over T), its locked money and the sales its exposure cap refuses.

    python3 -I c34_asp.py --replayer $REPLAYER --lists $RAW/lists --out results
"""
import argparse, csv, hashlib, json, sys, time
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent                               # docs/11_journal
W3 = J / 'C32' / 'W3_replay' / 'results'
R12 = J / 'R12' / 'results'
BPD = 43_200                                  # blocks per day (2-second blocks)
DF = 2_251                                    # Delta_f in blocks (L_k1)
U6 = 10 ** 6
E_MAX = 250_000 * U6                          # ASP Appendix E.3 example, atomic USDC
PER_CHARGE_CAP = 5_000 * U6
DAILY_CAP = 100_000 * U6
H_SET = {'df': DF, '1d': BPD, '7d': 7 * BPD, '30d': 30 * BPD}
CELLS = [dict(name='ASP-E', mode='escrow', rho=5, H='30d', D=7 * BPD)] + \
        [dict(name=f'I_r{r}_{h}', mode='instant', rho=r, H=h, D=0) for r in (5, 10, 20) for h in H_SET]


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def window_sum(cs, idx, back):
    """Rev(t - back, t] for t in idx, with cs[-1] taken as 0 before the first block."""
    lo = idx - back
    prev = np.where(lo >= 0, cs[np.maximum(lo, 0)], 0)
    return cs[idx] - prev


def admit_cap(blocks, values, rho, H, D, cap):
    """ASP exposure cap applied sale by sale in list order: refuse a sale when, with it, the seller's
    R - reserve - delayed = (1 - rho) Rev(t - H, t] - (1 - rho) Rev(t - D, t] (rho in percent, x100 units)
    exceeds the cap. Only called when the unconstrained maximum exceeds the cap."""
    from collections import deque
    keep = np.zeros(len(blocks), dtype=bool)
    qH, qD = deque(), deque()
    sH = sD = 0
    for j, (b, v) in enumerate(zip(blocks.tolist(), values.tolist())):
        while qH and qH[0][0] <= b - H:
            sH -= qH.popleft()[1]
        while D and qD and qD[0][0] <= b - D:
            sD -= qD.popleft()[1]
        unc = (100 - rho) * (sH + v) - ((100 - rho) * (sD + v) if D else 0)
        if unc <= 100 * cap:
            keep[j] = True
            qH.append((b, v)); sH += v
            if D:
                qD.append((b, v)); sD += v
    return keep


def main():
    ap = argparse.ArgumentParser()
    for k in ('replayer', 'lists', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    t0 = time.time()
    log = lambda s: print(f'[{time.time() - t0:7.1f}s] {s}', flush=True)
    sys.dont_write_bytecode = True
    code = Path(a.replayer) / 'experiments' / 'replay'
    sys.path.insert(0, str(code))
    import r12_compute as R   # noqa: E402
    REG = R.REGISTERED
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    r12res = json.load(open(R12 / 'r12_results.json'))['windows']
    w3 = json.load(open(W3 / 'w3_compare.json'))['windows']
    RES = dict(cells=CELLS, E_max_atomic=E_MAX, windows={}, inputs={'r12_compute.py': sha256(code / 'r12_compute.py')})
    for w in REG['windows']:
        problems = []
        rr = r12res[w]
        r12a = {r['address']: r for r in csv.DictReader(open(R12 / f'r12_addr_{w}.csv'))}
        w3s = {r['address']: r for r in csv.DictReader(open(W3 / f'w3_sellers_{w}.csv'))}
        addrs = [x for x, r in r12a.items() if r['in_S1r'] == '1']
        if sorted(addrs) != sorted(w3s):
            problems.append('S1r differs from the W3 seller file')
        lp = Path(a.lists) / REG['lists'][w]['file']
        pp = Path(a.lists) / REG['prior_lists'][w]['file']
        for p, spec in ((lp, REG['lists'][w]), (pp, REG['prior_lists'][w])):
            h = sha256(p)
            RES['inputs'][p.name] = h
            if h != spec['sha256']:
                problems.append(f'{p.name}: hash differs from the R12 registration')
        log(f'{w}: list hashes checked')
        lists_w, meta = R.read_list(lp, addrs)
        prior, pmeta = R.read_list(pp, addrs)
        log(f'{w}: lists read')
        F, Z = rr['first_block'], rr['last_block']
        if meta['first_block'] != F or meta['last_block'] != Z:
            problems.append('window list first or last block differs from R12')
        P0 = pmeta['first_block']
        if pmeta['last_block'] >= F:
            problems.append('prior list overlaps the window')
        win = R.Window(F, Z, meta['first_time'])
        a0 = win.a0
        n_avg = win.n_avg
        if n_avg != rr['n_avg']:
            problems.append('n_avg differs from R12')
        tidx = np.arange(F - P0 + a0, Z - P0 + 1, dtype=np.int64)          # T in concatenated block index
        trunc = {h: float(np.mean(tidx - H < 0)) for h, H in H_SET.items()}
        rate_blocks = rr['rate_blocks']
        h_margin = REG['history_margin']
        lags = ('own', 'k1')
        sums = {lag: {c['name']: dict(X=0, Usum=0, locked=0) for c in CELLS} for lag in lags}
        cap = {c['name']: dict(max_uncapped_usdc=0.0, rejected_value=0, rejected_count=0) for c in CELLS}
        max_sale = max_day = 0
        rows = []
        repro_bad = 0
        for x in addrs:
            bw, vw, _ = lists_w[x]
            bp, vp, _ = prior[x]
            r2 = r12a[x]
            # reproduce R12 history bond and unbonded rate cap with R12's own functions
            daily = dict(R.daily_sums(bp, vp, pmeta['first_block'], pmeta['first_time'], win.day0))
            for d, v in R.daily_sums(bw, vw, win.first, win.first_time, win.day0).items():
                daily[d] = daily.get(d, 0) + v
            caps, cprior = R.history_caps(daily, win.n_days)
            max_day = max(max_day, max(daily.values(), default=0))
            if cprior != int(r2['C_prior']):
                repro_bad += 1
            # concatenated per-block revenue from the prior list's first block
            arr = np.zeros(Z - P0 + 1, dtype=np.int64)
            if len(bp):
                np.add.at(arr, bp - P0, vp)
            np.add.at(arr, bw - P0, vw)
            cs = np.cumsum(arr)
            vall = np.concatenate([vp, vw])
            ball = np.concatenate([bp, bw])
            max_sale = max(max_sale, int(vall.max()) if len(vall) else 0)
            cs_w = np.cumsum(win.per_block(bw, vw))
            row = dict(address=x, k_star=int(r2['k_star']), revenue=int(r2['revenue']) / U6)
            revH = {h: window_sum(cs, tidx, H) for h, H in H_SET.items()}
            rev7 = window_sum(cs, tidx, 7 * BPD)
            for lag in lags:
                L = int(r2[f'L_{lag}'])
                bnd = R.address_bonds(win, bw, vw, caps, cprior, int(r2['rho2']), L, rate_blocks, REG['b_atomic'],
                                      int(r2['revenue']))
                for k in ('X_H', 'X_Ru', 'Usum_H', 'Usum_Ru'):
                    if int(bnd[k]) != int(r2[f'{k}_{lag}']):
                        repro_bad += 1
                E = window_sum(cs, tidx, L)
                if not np.array_equal(E, win.in_lag(cs_w, L)[a0:]):
                    problems.append(f'{x}: E differs from R12 in_lag at lag {lag}')
                for c in CELLS:
                    rho, H, D = c['rho'], H_SET[c['H']], c['D']
                    cover = rho * revH[c['H']] + ((100 - rho) * (rev7 if D == 7 * BPD else window_sum(cs, tidx, D))
                                                  if D else 0)
                    u = np.maximum(100 * E - cover, 0)
                    Xi, Ui = int(u.max()), int(u.sum())
                    lk = int(cover.sum())
                    sums[lag][c['name']]['X'] += Xi
                    sums[lag][c['name']]['Usum'] += Ui
                    sums[lag][c['name']]['locked'] += lk
                    row[f'X_{c["name"]}_{lag}'] = Xi / 100 / U6
                    row[f'Ubar_{c["name"]}_{lag}'] = Ui / 100 / n_avg / U6
                    if lag == 'own':
                        row[f'locked_{c["name"]}'] = lk / 100 / n_avg / U6
            # exposure cap over every block of the window (history from the prior list)
            widx = np.arange(F - P0, Z - P0 + 1, dtype=np.int64)
            for c in CELLS:
                rho, H, D = c['rho'], H_SET[c['H']], c['D']
                unc = (100 - rho) * window_sum(cs, widx, H) - ((100 - rho) * window_sum(cs, widx, D) if D else 0)
                m = int(unc.max())
                cap[c['name']]['max_uncapped_usdc'] = max(cap[c['name']]['max_uncapped_usdc'], m / 100 / U6)
                if m > 100 * E_MAX:
                    keep = admit_cap(ball, vall, rho, H, D, E_MAX)
                    inw = ball >= F
                    cap[c['name']]['rejected_value'] += int(vall[inw & ~keep].sum())
                    cap[c['name']]['rejected_count'] += int((inw & ~keep).sum())
            row['FB_locked'] = (REG['b_atomic'] + int(r2[f'Hnum_k{r2["k_star"]}']) / n_avg) / U6
            for k in ('WB_EG_own', 'WB_EG_k1', 'B_EG_own', 'B_EG_k1'):
                row[k] = float(w3s[x][k])
            rows.append(row)
        if repro_bad:
            problems.append(f'{repro_bad} per-seller values differ from r12_addr (C_prior, X, Usum)')
        log(f'{w}: computed, problems {problems}')
        W = dict(n=len(addrs), n_avg=n_avg, prior_first_block=P0, F=F, Z=Z, truncated_share_of_T=trunc,
                 max_sale_usdc=max_sale / U6, max_daily_usdc=max_day / U6,
                 per_charge_cap_binds=max_sale > PER_CHARGE_CAP, daily_cap_binds=max_day > DAILY_CAP,
                 exposure_cap={k: dict(v, rejected_value=v['rejected_value'] / U6) for k, v in cap.items()},
                 problems=problems, lag={})
        FBw = w3[w]
        for lag in lags:
            fb = FBw['lag'][lag]
            d = dict(FB_worst_EG=FBw['W_all_EG'], FB_worst_EN=FBw['W_all_EN'], FB_TG_p95=FBw['TG_p95'],
                     FB_time_EG=fb['B_EG'], FB_time_EN=fb['B_EN'], X_H=fb['X_H'], X_Ru=fb['X_Ru'],
                     Ubar_H=fb['Ubar_H'], Ubar_Ru=fb['Ubar_Ru'],
                     FB_locked=rr['lag'][lag]['S1r']['L_FB'], sumB_H=rr['lag'][lag]['S1r']['sumB_H'],
                     sumB_R=rr['lag'][lag]['S1r']['sumB_R'], cells={})
            for c in CELLS:
                s = sums[lag][c['name']]
                X = s['X'] / 100 / U6
                Ub = s['Usum'] / 100 / n_avg / U6
                lk = s['locked'] / 100 / n_avg / U6
                nm = c['name']
                d['cells'][nm] = dict(
                    X=X, Ubar=Ub, locked=lk,
                    ratio_FB_worst=(d['FB_worst_EG'] / X) if X else None,
                    ratio_X_over_FB=X / d['FB_worst_EG'],
                    ratio_FB_time=(d['FB_time_EG'] / Ub) if Ub else None,
                    ratio_FBN_time=(d['FB_time_EN'] / Ub) if Ub else None,
                    ratio_FB_locked=d['FB_locked'] / lk if lk else None,
                    TG_p95_ge_X=bool(d['FB_TG_p95'] >= X),
                    sellers_WB_gt_X=sum(r[f'WB_EG_{lag}'] > r[f'X_{nm}_{lag}'] for r in rows),
                    sellers_B_gt_Ubar=sum(r[f'B_EG_{lag}'] > r[f'Ubar_{nm}_{lag}'] for r in rows),
                    sellers_B_lt_Ubar=sum(r[f'B_EG_{lag}'] < r[f'Ubar_{nm}_{lag}'] for r in rows),
                    sellers_FB_locks_more=sum(r['FB_locked'] > r[f'locked_{nm}'] for r in rows))
            W['lag'][lag] = d
        RES['windows'][w] = W
        with open(out / f'c34_sellers_{w}.csv', 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            wr.writeheader(); wr.writerows(rows)
    RES['pass'] = all(not RES['windows'][w]['problems'] for w in RES['windows'])
    RES['env'] = dict(numpy=np.__version__, python=sys.version.split()[0])
    (out / 'c34_asp.json').write_text(json.dumps(RES, indent=1, ensure_ascii=False,
                                                 default=lambda o: o.item() if hasattr(o, 'item') else str(o)) + '\n')
    log(f'pass {RES["pass"]}')


if __name__ == '__main__':
    main()
