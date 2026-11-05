#!/usr/bin/env python3
"""W3 part 2 (calc-rules.md sec. 2): the bond replay's daily revenue per seller against the raw daily sale files.

D^R12: r12_compute.read_list and daily_sums (R12 code c13a832, unchanged) on the registered lists, as the R12
       aggregation computes them (prior list on the window's day0).
D^raw: the raw daily files settlements_<date>.csv.gz, summed per lower-case recipient and file date.
Also checks list, manifest and file hashes, re-derives C_prior per address against r12_addr_<window>.csv, and
compares the agg_2026-10-21 day table (diagnostic only).

    python3 -I w3_daily.py --window median --replayer $REPLAYER \
        --lists $RAW/lists --rawdata $RAWDATA --out results
"""
import argparse, csv, gzip, hashlib, json, sys, time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
J = HERE.parent.parent
REPO = J.parent.parent
TOL = 10_000          # 0.01 USDC in atomic units


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for c in iter(lambda: f.read(1 << 20), b''):
            h.update(c)
    return h.hexdigest()


def raw_daily(directory, addrs, log):
    """{(addr, date): value}, per-file checks against the manifest, rows whose block date differs from the file."""
    d = Path(directory)
    man = [json.loads(l) for l in open(d / 'manifest.jsonl') if l.strip()]
    out = defaultdict(int)
    checks = []
    for m in man:
        p = d / m['file']
        ok_hash = sha256(p) == m['sha256_gz']
        rows = vsum = off = 0
        date = m['date']
        with gzip.open(p, 'rt', newline='') as f:
            rd = csv.reader(f)
            head = next(rd)
            ia, iv, it = head.index('recipient'), head.index('value_atomic'), head.index('block_time_utc')
            for row in rd:
                rows += 1
                v = int(row[iv])
                vsum += v
                if row[it][:10] != date:
                    off += 1
                a = row[ia].lower()
                if a in addrs:
                    out[(a, date)] += v
        checks.append(dict(file=m['file'], date=date, sha256_gz_ok=ok_hash, rows=rows, rows_ok=rows == int(m['rows']),
                           value_ok=vsum == int(m['value_sum_atomic']), rows_off_date=off))
        log(f'  {d.name}/{m["file"]}: rows {rows}, hash {ok_hash}')
    return dict(out), checks, sha256(d / 'manifest.jsonl')


def agg_daily(path, addrs):
    out = {}
    with gzip.open(path, 'rt', newline='') as f:
        for r in csv.DictReader(f):
            a = r['recipient'].lower()
            if a in addrs:
                out[(a, r['date'])] = out.get((a, r['date']), 0) + int(r['value_atomic_sum'])
    return out


def compare(A, B, addrs, dates):
    keys = {(a, d) for a in addrs for d in dates}
    stray = sorted(k for k in set(A) | set(B) if k not in keys)
    diffs = []
    for k in sorted(keys):
        x, y = A.get(k, 0), B.get(k, 0)
        if x != y:
            diffs.append((k[0], k[1], x, y))
    over = [t for t in diffs if abs(t[2] - t[3]) > TOL]
    mx = max((abs(t[2] - t[3]) for t in diffs), default=0)
    return dict(cells=len(keys), nonzero_days_A=sum(1 for k in keys if A.get(k, 0)), nonzero_days_B=sum(1 for k in keys if B.get(k, 0)),
                diff_cells=len(diffs), over_tol_cells=len(over), max_abs_diff_usdc=mx / 1e6, first=diffs[:5],
                stray_keys=len(stray), addresses_with_diff=len({t[0] for t in diffs}))


def main():
    ap = argparse.ArgumentParser()
    for k in ('window', 'replayer', 'lists', 'rawdata', 'out'):
        ap.add_argument('--' + k, required=True)
    a = ap.parse_args()
    t0 = time.time()
    log = lambda s: print(f'[{time.time() - t0:7.1f}s] {s}', flush=True)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(a.replayer) / 'experiments' / 'replay'))
    import r12_compute as R   # noqa: E402
    REG = R.REGISTERED
    w = a.window
    res = dict(window=w, r12_compute_sha256=sha256(Path(a.replayer) / 'experiments' / 'replay' / 'r12_compute.py'))
    r12addr = {r['address']: r for r in csv.DictReader(open(J / 'R12' / 'results' / f'r12_addr_{w}.csv'))}
    addrs = list(r12addr)
    S1r = {x for x, r in r12addr.items() if r['in_S1r'] == '1'}
    sa = json.load(open(Path(a.lists).parent / f'{w}_r12cost' / 'k1' / 'condition-01-seed-0' / 'sales_addresses.json'))
    res['addresses'] = len(addrs)
    res['addresses_equal_sales_addresses'] = sorted(addrs) == sorted(sa)
    # lists and the R12 daily sums
    lp = Path(a.lists) / REG['lists'][w]['file']
    pp = Path(a.lists) / REG['prior_lists'][w]['file']
    res['list_sha256'] = {lp.name: sha256(lp), pp.name: sha256(pp)}
    res['list_sha_ok'] = (res['list_sha256'][lp.name] == REG['lists'][w]['sha256'] and
                          res['list_sha256'][pp.name] == REG['prior_lists'][w]['sha256'])
    log(f'list hashes ok: {res["list_sha_ok"]}')
    lists_w, meta = R.read_list(lp, addrs)
    log('window list read')
    prior_rows, pmeta = R.read_list(pp, addrs)
    log('prior list read')
    day0 = meta['first_time'] // 86400
    D12 = {}
    for x in addrs:
        dd = dict(R.daily_sums(prior_rows[x][0], prior_rows[x][1], pmeta['first_block'], pmeta['first_time'], day0))
        for d, v in R.daily_sums(lists_w[x][0], lists_w[x][1], meta['first_block'], meta['first_time'], day0).items():
            dd[d] = dd.get(d, 0) + v
        for d, v in dd.items():
            D12[(x, R.date_of((day0 + d) * 86400))] = v
    # C_prior reproduces the R12 column
    cp_bad = []
    for x in addrs:
        prior = max([D12.get((x, R.date_of((day0 + d) * 86400)), 0) for d in range(-REG['history_days'], 0)])
        if prior != int(r12addr[x]['C_prior']):
            cp_bad.append((x, prior, r12addr[x]['C_prior']))
    res['C_prior_mismatch'] = len(cp_bad)
    res['C_prior_first'] = cp_bad[:5]
    res['list_meta'] = {k: meta[k] for k in ('first_block', 'last_block', 'rows', 'date_mismatches')}
    res['prior_meta'] = {k: pmeta[k] for k in ('first_block', 'last_block', 'rows', 'date_mismatches')}
    # raw daily files
    I = REG['inputs']
    Draw, checks, mh = {}, {}, {}
    for part in ('window', 'prior'):
        dname = I['raw_dirs'][w][part]
        o, c, h = raw_daily(Path(a.rawdata) / dname, set(addrs), log)
        Draw.update(o)
        checks[dname] = c
        mh[dname] = dict(sha256=h, registered=I['manifests'][dname], ok=h == I['manifests'][dname])
    res['manifests'] = mh
    res['files_all_ok'] = all(x['sha256_gz_ok'] and x['rows_ok'] and x['value_ok'] for c in checks.values() for x in c)
    res['rows_off_date'] = sum(x['rows_off_date'] for c in checks.values() for x in c)
    res['file_checks'] = checks
    dates = sorted({x['date'] for c in checks.values() for x in c})
    res['dates'] = [dates[0], dates[-1], len(dates)]
    res['compare_r12_vs_raw'] = compare(D12, Draw, addrs, dates)
    res['compare_r12_vs_raw_S1r'] = compare({k: v for k, v in D12.items() if k[0] in S1r},
                                            {k: v for k, v in Draw.items() if k[0] in S1r}, sorted(S1r), dates)
    res['S1r'] = len(S1r)
    # diagnostic: the agg_2026-10-21 day table
    aggdir = REPO / 'data' / 'processed' / 'agg_2026-10-21'
    Dagg = {}
    for fn in (f'days_{w}.csv.gz', f'days_{w}_prior14.csv.gz'):
        Dagg.update(agg_daily(aggdir / fn, set(addrs)))
        res.setdefault('agg_sha256', {})[fn] = sha256(aggdir / fn)
    res['compare_agg_vs_raw'] = compare(Dagg, Draw, addrs, dates)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / f'w3_daily_{w}.json').write_text(json.dumps(res, indent=1, ensure_ascii=False) + '\n')
    log(json.dumps({k: res[k] for k in ('list_sha_ok', 'C_prior_mismatch', 'files_all_ok', 'rows_off_date')}))
    log(json.dumps(res['compare_r12_vs_raw']))
    log(json.dumps(res['compare_agg_vs_raw']))


if __name__ == '__main__':
    main()
