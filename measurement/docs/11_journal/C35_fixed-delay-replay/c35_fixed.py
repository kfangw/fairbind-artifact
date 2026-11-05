#!/usr/bin/env python3
"""C35 (calc-rules.md): locked money and holding time of the fourth rule of Section 5 (keep R5's freeze and deduction,
pay each sale a fixed delay D after its settlement) on the R12 cost replay, against FairBind's release cursor.

Reads the R12 runs (sales.npz of every k) and the R12 per-address file, reproduces FairBind's held numerators and
L_FB, cross-checks the fixed-delay held balance against the R12 window lists, and writes per-window sums.

    python3 -I c35_fixed.py --raw $RAW --replayer $REPLAYER --out results
"""
import argparse, csv, hashlib, json, sys, time
from fractions import Fraction
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
J = HERE.parent                               # docs/11_journal
R12 = J / 'R12' / 'results'
U6 = 10 ** 6


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def held_series(b, rl, v, F, N):
    """held(t) for t in [F, F + N): sum of v over sales with b <= t < rl."""
    d = np.zeros(N + 1, dtype=np.int64)
    np.add.at(d, b - F, v)
    end = np.minimum(rl - F, N)
    np.add.at(d, end, -v)
    return np.cumsum(d[:N])


class Run:
    def __init__(self, cdir):
        z = np.load(cdir / 'sales.npz')
        self.b = z['block'].astype(np.int64)
        self.v = z['value'].astype(np.int64)
        self.rl = z['release'].astype(np.int64)
        idx = z['address_index'].astype(np.int64)
        addrs = json.loads((cdir / 'sales_addresses.json').read_text())
        order = np.argsort(idx, kind='stable')
        bounds = np.searchsorted(idx[order], np.arange(len(addrs) + 1))
        self.sel = {a: order[bounds[i]:bounds[i + 1]] for i, a in enumerate(addrs)}

    def of(self, a):
        s = self.sel.get(a, np.zeros(0, dtype=np.int64))
        return self.b[s], self.v[s], self.rl[s]


def main():
    ap = argparse.ArgumentParser()
    for k in ('raw', 'replayer', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    t0 = time.time()
    log = lambda s: print(f'[{time.time() - t0:7.1f}s] {s}', flush=True)
    sys.dont_write_bytecode = True
    code = Path(a.replayer) / 'experiments' / 'replay'
    sys.path.insert(0, str(code))
    import r12_compute as R   # noqa: E402
    REG = R.REGISTERED
    a0 = REG['avg_offset_blocks']
    b_at = REG['b_atomic']
    raw = Path(a.raw)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    r12res = json.load(open(R12 / 'r12_results.json'))['windows']
    reg_sha = {}
    for line in open(R12 / 'r12_sales_sha256.txt'):
        if line.strip():
            h, name = line.split()
            reg_sha[name] = h
    RES = dict(windows={}, inputs={'r12_compute.py': sha256(code / 'r12_compute.py')})
    for w in REG['windows']:
        problems = []
        rr = r12res[w]
        F, Z, n_avg = rr['first_block'], rr['last_block'], rr['n_avg']
        N = Z - F + 1
        r12a = {r['address']: r for r in csv.DictReader(open(R12 / f'r12_addr_{w}.csv'))}
        addrs = [x for x, r in r12a.items() if r['in_S1r'] == '1']
        n = len(addrs)
        kstar = {x: int(r12a[x]['k_star']) for x in addrs}
        ks = sorted(set(kstar.values()) | {1})
        runs = {}
        for k in ks:
            cdir = raw / f'{w}_r12cost' / f'k{k}' / 'condition-01-seed-0'
            h = sha256(cdir / 'sales.npz')
            RES['inputs'][f'{w}/k{k}/sales.npz'] = h
            if reg_sha.get(f'r12cost/{w}/k{k}') != h:
                problems.append(f'k{k} sales.npz hash differs from r12_sales_sha256.txt')
            runs[k] = Run(cdir)
        log(f'{w}: runs loaded (k {ks})')
        lp = Path(raw) / 'lists' / REG['lists'][w]['file']
        if sha256(lp) != REG['lists'][w]['sha256']:
            problems.append('window list hash differs from the R12 registration')
        lists_w, meta = R.read_list(lp, addrs)
        log(f'{w}: list read')
        rules = ['D_df', 'D_own', 'FB_kstar', 'FB_k1']
        tot = {r: np.zeros(N - a0, dtype=np.int64) for r in rules}
        sumT = {r: 0 for r in rules}
        sum_max = {r: 0 for r in rules}
        holdw = {r: 0 for r in rules}       # sum v * (release - b), untruncated
        rev_all = 0
        rows = []
        bad = dict(hnum=0, list=0, sales=0)
        for x in addrs:
            ks_ = kstar[x]
            L_own = int(r12a[x]['L_own'])
            if L_own != 300 * ks_ + 1951 or int(r12a[x]['L_k1']) != 2251:
                problems.append(f'{x}: L_own or L_k1 differs from 300k + 1,951')
            b1, v1, rl1 = runs[1].of(x)
            bk, vk, rlk = runs[ks_].of(x)
            if not (np.array_equal(b1, bk) and np.array_equal(v1, vk)):
                bad['sales'] += 1
            lb, lv, _ = lists_w[x]
            o1, ol = np.lexsort((v1, b1)), np.lexsort((lv, lb))
            if not (np.array_equal(b1[o1], lb[ol]) and np.array_equal(v1[o1], lv[ol])):
                bad['list'] += 1
            spec = dict(D_df=(b1, b1 + 2251, v1), D_own=(b1, b1 + L_own, v1),
                        FB_kstar=(bk, rlk, vk), FB_k1=(b1, rl1, v1))
            row = dict(address=x, k_star=ks_, L_own=L_own, revenue=int(v1.sum()) / U6)
            rev_all += int(v1.sum())
            cs = np.cumsum(_per_block(lb, lv, F, N))          # R12 Window.per_block on the window list
            for r, (bb, rl, vv) in spec.items():
                hs = held_series(bb, rl, vv, F, N)[a0:]
                s, m = int(hs.sum()), int(hs.max()) if len(hs) else 0
                tot[r] += hs
                sumT[r] += s
                sum_max[r] += m
                holdw[r] += int((vv * (rl - bb)).sum())
                row[f'held_avg_{r}'] = s / n_avg / U6
                row[f'held_max_{r}'] = m / U6
                if r == 'FB_kstar' and s != int(r12a[x][f'Hnum_k{ks_}']):
                    bad['hnum'] += 1
                if r == 'FB_k1' and s != int(r12a[x]['Hnum_k1']):
                    bad['hnum'] += 1
                if r in ('D_df', 'D_own'):
                    D = 2251 if r == 'D_df' else L_own
                    E = cs.copy(); E[D:] -= cs[:-D]                 # Rev(t - D, t], as R12 Window.in_lag
                    E = E[a0:]
                    if not np.array_equal(E, hs):
                        bad['list'] += 1
            rows.append(row)
        for k_, v_ in bad.items():
            if v_:
                problems.append(f'{v_} per-seller mismatches ({k_})')
        P = Fraction(n * b_at, U6)
        rec = dict(n=n, n_avg=n_avg, revenue=rev_all / U6, k_star_counts={str(k): sum(1 for x in addrs if kstar[x] == k)
                                                                          for k in ks},
                   max_hold_FB_kstar=dict(min=min(300 * kstar[x] + 1951 for x in addrs),
                                          max=max(300 * kstar[x] + 1951 for x in addrs)),
                   rules={})
        for r in rules:
            rec['rules'][r] = dict(
                locked_time=float(P + Fraction(sumT[r], n_avg * U6)),
                held_time=float(Fraction(sumT[r], n_avg * U6)),
                locked_worst_per_seller=float(P + Fraction(sum_max[r], U6)),
                locked_worst_simultaneous=float(P + Fraction(int(tot[r].max()), U6)),
                mean_hold_blocks=holdw[r] / rev_all if rev_all else None)
        L = rr['lag']
        if abs(rec['rules']['FB_kstar']['locked_time'] - L['own']['S1r']['L_FB']) > 1e-9:
            problems.append('FairBind locked money at k* differs from R12 L_FB')
        if abs(rec['rules']['FB_k1']['locked_time'] - rr['k']['1']['S1r']['L_FB']) > 1e-9:
            problems.append('FairBind locked money at k = 1 differs from R12 k curve')
        cmp = {}
        for col, r, lag in (('own', 'D_own', 'own'), ('df', 'D_df', 'k1')):
            q = rec['rules'][r]
            fb, fb1 = rec['rules']['FB_kstar'], rec['rules']['FB_k1']
            cmp[col] = dict(
                fourth_locked_time=q['locked_time'], FB_locked_time=fb['locked_time'], FB_k1_locked_time=fb1['locked_time'],
                ratio_fourth_over_FB=q['locked_time'] / fb['locked_time'],
                ratio_fourth_over_FB_k1=q['locked_time'] / fb1['locked_time'],
                ratio_FB_over_fourth=fb['locked_time'] / q['locked_time'],
                oracle=L[lag]['S1r']['sumC_M'], history=L[lag]['S1r']['sumB_H'],
                ratio_fourth_over_oracle=q['locked_time'] / L[lag]['S1r']['sumC_M'],
                ratio_fourth_over_history=q['locked_time'] / L[lag]['S1r']['sumB_H'],
                fourth_worst_per_seller=q['locked_worst_per_seller'], FB_worst_per_seller=fb['locked_worst_per_seller'],
                fourth_worst_simultaneous=q['locked_worst_simultaneous'],
                FB_worst_simultaneous=fb['locked_worst_simultaneous'],
                sellers_fourth_less=sum(1 for rw in rows if rw[f'held_avg_{r}'] < rw['held_avg_FB_kstar']),
                sellers_fourth_more=sum(1 for rw in rows if rw[f'held_avg_{r}'] > rw['held_avg_FB_kstar']),
                sellers_equal=sum(1 for rw in rows if rw[f'held_avg_{r}'] == rw['held_avg_FB_kstar']))
        rec['compare'] = cmp
        rec['problems'] = problems
        RES['windows'][w] = rec
        log(f'{w}: done, problems {problems}')
        with open(out / f'c35_sellers_{w}.csv', 'w', newline='') as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            wr.writeheader(); wr.writerows(rows)
        del runs
    RES['pass'] = all(not RES['windows'][w]['problems'] for w in RES['windows'])
    RES['env'] = dict(numpy=np.__version__, python=sys.version.split()[0])
    (out / 'c35_fixed.json').write_text(json.dumps(RES, indent=1, ensure_ascii=False) + '\n')
    log(f'pass {RES["pass"]}')


def _per_block(blocks, values, F, N):
    arr = np.zeros(N, dtype=np.int64)
    if len(blocks):
        np.add.at(arr, blocks - F, values)
    return arr


if __name__ == '__main__':
    main()
