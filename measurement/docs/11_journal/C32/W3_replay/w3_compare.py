#!/usr/bin/env python3
"""W3 part 1 (calc-rules.md sec. 1): FairBind's realized fraud payout and the bonds' realized shortfall on the same
replay, the same fraud strategy (s = 1) and the same start sets.

Uses R13/r13_sim.py unchanged (load_window, sellers_of, worst_start, rng_for, Seller.mc). Bond cells come from the
R12 outputs unchanged.

    python3 -I w3_compare.py --raw $RAW --out results
"""
import argparse, csv, hashlib, json, sys
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent.parent                      # docs/11_journal
sys.dont_write_bytecode = True
sys.path.insert(0, str(J / 'R13'))
import r13_sim as R13   # noqa: E402

T_OFF = 31_073
EP = 300
SC = 86_400
U6 = 1e6


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def rel_ok(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(b))


def mapped(st_ep, E, epochs):
    """E of the first candidate at or after each epoch (0 when none)."""
    idx = np.searchsorted(st_ep, epochs, side='left')
    has = idx < len(st_ep)
    return np.where(has, E[np.minimum(idx, len(E) - 1)], 0.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    r12dir = J / 'R12' / 'results'
    r12res = json.load(open(r12dir / 'r12_results.json'))['windows']
    r13res = json.load(open(J / 'R13' / 'results' / 'r13_results.json'))['windows']
    p2c = json.load(open(J / 'P2_posthoc' / 'results' / 'p2_c.json'))
    sales_sha = {}
    for line in open(r12dir / 'r12_sales_sha256.txt'):
        h, k = line.split()
        sales_sha[k] = h
    reg = R13.REGISTERED
    RES = {'checks': {}, 'windows': {}, 'inputs': {}}
    for widx, w in enumerate(reg['windows']):
        problems = []
        npz = Path(a.raw) / f'{w}_r12cost' / 'k1' / 'condition-01-seed-0' / 'sales.npz'
        h = sha256(npz)
        RES['inputs'][f'{w}/sales.npz'] = h
        if h != sales_sha[f'r12cost/{w}/k1']:
            problems.append('sales.npz differs from r12_sales_sha256.txt')
        win, prob = R13.load_window(a.raw, r12dir, w, check_hashes=True)
        problems += prob
        RES['inputs'].update({f'{w}/{k}': v for k, v in win['hashes'].items()})
        sellers = R13.sellers_of(win)
        r12a = {r['address']: r for r in csv.DictReader(open(r12dir / f'r12_addr_{w}.csv'))}
        r13a = {r['address']: r for r in csv.DictReader(open(J / 'R13' / 'results' / f'r13_addr_{w}.csv'))}
        F, Z = win['F'], win['Z']
        n_avg = r12res[w]['n_avg']
        eA = np.arange(-(-T_OFF // EP), (Z - F) // EP + 1)
        totG = np.zeros(reg['replicates'], dtype=np.int64)
        rows = []
        for x in win['S1r']:
            pos, s = sellers[x]
            tG, tN, EG, EN = R13.worst_start(s, reg['horizon'])
            st_ep = s.epochs[s.starts]
            r3 = r13a[x]
            for got, exp, lab in ((EG[tG], float(r3['EG']), 'EG'), (EN[tN], float(r3['EN']), 'EN'),
                                  (EG.max(), float(r3['max_EG_any_start']), 'maxEG')):
                if not rel_ok(got, exp):
                    problems.append(f'{x}: {lab} {got} differs from R13 {exp}')
            j0 = int(s.starts[tG])
            g, _ = s.mc(j0, reg['replicates'], R13.rng_for(reg['seed'], widx, pos, j0), chunk=reg['mc_chunk'])
            totG += g
            r2 = r12a[x]
            row = dict(address=x, k_star=int(r2['k_star']), revenue=s.revenue() / U6,
                       W_all_EG=EG[tG] / U6, W_all_EN=EN[tN] / U6,
                       A_EG=float(mapped(st_ep, EG, eA).mean()) / U6, A_EN=float(mapped(st_ep, EN, eA).mean()) / U6)
            for lag in ('own', 'k1'):
                L = int(r2[f'L_{lag}'])
                eB = np.arange(-(-(T_OFF - L) // EP), (Z - F - L) // EP + 1)
                mG, mN = mapped(st_ep, EG, eB), mapped(st_ep, EN, eB)
                row[f'L_{lag}'] = L
                row[f'B_EG_{lag}'] = float(mG.mean()) / U6
                row[f'B_EN_{lag}'] = float(mN.mean()) / U6
                row[f'WB_EG_{lag}'] = float(mG.max()) / U6
                row[f'WB_EN_{lag}'] = float(mN.max()) / U6
                for c in ('H', 'Ru'):
                    row[f'X_{c}_{lag}'] = int(r2[f'X_{c}_{lag}']) / SC / U6
                    row[f'Ubar_{c}_{lag}'] = int(r2[f'Usum_{c}_{lag}']) / SC / n_avg / U6
            rows.append(row)
        # checks against R13, P2 and R12
        tot13 = np.array([int(r['total_G']) for r in csv.DictReader(open(J / 'R13' / 'results' / f'r13_totals_{w}.csv'))])
        if not np.array_equal(tot13, totG):
            problems.append('realized totals T_G differ from r13_totals')
        S = lambda k: float(sum(r[k] for r in rows))
        if not rel_ok(S('W_all_EG') * U6, r13res[w]['agg']['sum_EG']) or not rel_ok(S('W_all_EN') * U6, r13res[w]['agg']['sum_EN']):
            problems.append('worst-start sums differ from R13')
        if not rel_ok(S('A_EG'), p2c[w]['c1_EG_sum']) or not rel_ok(S('A_EN'), p2c[w]['c1_EN_sum']):
            problems.append('time-uniform (A) sums differ from P2 c1')
        for lag in ('own', 'k1'):
            r12s = r12res[w]['lag'][lag]['S1r']
            for c in ('H', 'Ru'):
                if not rel_ok(S(f'Ubar_{c}_{lag}'), r12s[f'U_avg_{c}']):
                    problems.append(f'Ubar {c} {lag} differs from R12')
                if int(sum(int(r12a[r['address']][f'X_{c}_{lag}']) for r in rows)) != int(r12s[f'X_sum_{c}_scaled']):
                    problems.append(f'X {c} {lag} differs from R12')
        q = lambda p: int(R13.sample_quantile(totG, p))
        Wr = dict(n=len(rows), nV=float(len(rows)), problems=problems,
                  FB_replay_exposure_R12=r12res[w]['lag']['own']['S1r']['FB_replay_exposure'],
                  W_all_EG=S('W_all_EG'), W_all_EN=S('W_all_EN'), A_EG=S('A_EG'), A_EN=S('A_EN'),
                  TG_mean=float(totG.mean()) / U6, TG_median=q(0.5) / U6, TG_p95=q(0.95) / U6, TG_max=int(totG.max()) / U6,
                  epochs_A=len(eA), lag={})
        for lag in ('own', 'k1'):
            d = dict(B_EG=S(f'B_EG_{lag}'), B_EN=S(f'B_EN_{lag}'), WB_EG=S(f'WB_EG_{lag}'), WB_EN=S(f'WB_EN_{lag}'))
            for c in ('H', 'Ru'):
                d[f'X_{c}'] = S(f'X_{c}_{lag}')
                d[f'Ubar_{c}'] = S(f'Ubar_{c}_{lag}')
                d[f'sellers_B_EG_gt_Ubar_{c}'] = sum(r[f'B_EG_{lag}'] > r[f'Ubar_{c}_{lag}'] for r in rows)
                d[f'sellers_B_EG_lt_Ubar_{c}'] = sum(r[f'B_EG_{lag}'] < r[f'Ubar_{c}_{lag}'] for r in rows)
                d[f'sellers_WB_EG_gt_X_{c}'] = sum(r[f'WB_EG_{lag}'] > r[f'X_{c}_{lag}'] for r in rows)
                d[f'sellers_Wall_EG_gt_X_{c}'] = sum(r['W_all_EG'] > r[f'X_{c}_{lag}'] for r in rows)
                d[f'sellers_B_EN_gt_Ubar_{c}'] = sum(r[f'B_EN_{lag}'] > r[f'Ubar_{c}_{lag}'] for r in rows)
                d[f'TG_ge_X_{c}_share'] = float((totG / U6 >= d[f'X_{c}']).mean())
            Wr['lag'][lag] = d
        RES['windows'][w] = Wr
        with open(out / f'w3_sellers_{w}.csv', 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
        print(w, 'problems:', problems, flush=True)
    RES['checks']['pass'] = all(not RES['windows'][w]['problems'] for w in RES['windows'])
    RES['env'] = dict(numpy=np.__version__, python=sys.version.split()[0],
                      r13_sim_sha256=sha256(J / 'R13' / 'r13_sim.py'))
    (out / 'w3_compare.json').write_text(json.dumps(RES, indent=1, ensure_ascii=False, default=lambda o: o.item() if hasattr(o, 'item') else str(o)) + '\n')
    print(json.dumps(RES['checks']))


if __name__ == '__main__':
    main()
