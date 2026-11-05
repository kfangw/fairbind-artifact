#!/usr/bin/env python3
"""Sweep of the seller epoch multiple k for the edition-10 release (registration R11, item (e)).

    r11_k_sweep.py --k 1,2,3,6 --out OUT -- <replay.py arguments, without --out and --r10-seller-epoch-k>

Each k is one `replay.py` run written to OUT/k<k>/ with `--r10-seller-epoch-k k` added to the given arguments (which
must select `--release fixed10`, for example through `--preset r11-main`). A k whose `run.json` exists is finished
and skipped, so the call can be repeated. The driver changes no rule or number: it reads `addresses_observed.csv` of
each finished run and writes OUT/k_sweep.json and OUT/k_sweep.csv with, per k and per address set (every address,
and the addresses with revenue), the number of addresses, the accepted value, the sums of H_time_average,
H_cont_average and H_cont_average_from_hold, the value-weighted mean hold over the released sales, the median
hold_p90 over the addresses with a released sale, the largest hold_max and the value still held at the end.
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

SUMS = ('accepted_value', 'H_time_average', 'H_cont_average', 'H_cont_average_from_hold', 'hold_open_value')


def _num(v):
    if v is None or v == '':
        return None
    return float(v)


def summarise_rows(rows):
    """One summary of a list of address rows (dicts from addresses_observed.csv)."""
    out = dict(addresses=len(rows))
    for c in SUMS:
        out['sum_' + c] = sum((_num(r.get(c)) or 0.0) for r in rows)
    w = v = 0.0
    p90, hmax = [], []
    for r in rows:
        hvm = _num(r.get('hold_value_mean'))
        released_value = (_num(r.get('accepted_value')) or 0.0) - (_num(r.get('hold_open_value')) or 0.0)
        if hvm is not None and released_value > 0:
            w += hvm * released_value
            v += released_value
        if r.get('hold_p90') not in (None, ''):
            p90.append(float(r['hold_p90']))
        if r.get('hold_max') not in (None, ''):
            hmax.append(float(r['hold_max']))
    out['hold_value_mean_weighted'] = (w / v) if v > 0 else None
    out['hold_p90_median'] = statistics.median(p90) if p90 else None
    out['hold_max_max'] = max(hmax) if hmax else None
    return out


def summarise_run(run_dir):
    """{condition dir: {'all': summary, 'with_revenue': summary}} of one replay run."""
    out = {}
    for cdir in sorted(Path(run_dir).glob('condition-*')):
        path = cdir / 'addresses_observed.csv'
        if not path.exists():
            continue
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f))
        with_rev = [r for r in rows if str(r.get('has_revenue', '')).lower() in ('true', '1')]
        out[cdir.name] = dict(all=summarise_rows(rows), with_revenue=summarise_rows(with_rev))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    extra = []
    if '--' in argv:
        i = argv.index('--')
        argv, extra = argv[:i], argv[i + 1:]
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--k', default='1,2,3,6', help='comma list of seller epoch multiples')
    p.add_argument('--out', required=True)
    a = p.parse_args(argv)
    if '--out' in extra or '--r10-seller-epoch-k' in extra:
        raise SystemExit('give --out to the sweep and leave --r10-seller-epoch-k to it')
    ks = [int(x) for x in a.k.split(',') if x]
    if not ks or any(k < 1 for k in ks):
        raise SystemExit('--k needs integers >= 1')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    import replay
    results = {}
    for k in ks:
        run_dir = out / f'k{k}'
        if not (run_dir / 'run.json').exists():
            code = replay.main(extra + ['--out', str(run_dir), '--r10-seller-epoch-k', str(k)])
            if code:
                raise SystemExit(f'k = {k}: replay failed with status {code}')
        env = json.loads((run_dir / 'run.json').read_text())
        results[str(k)] = dict(directory=run_dir.name, reportable=env.get('reportable'),
                               release10=env['parameters'].get('release10'), conditions=summarise_run(run_dir))
    (out / 'k_sweep.json').write_text(json.dumps(dict(k=ks, replay_args=extra, results=results), indent=1) + '\n')
    with open(out / 'k_sweep.csv', 'w', newline='') as f:
        w = csv.writer(f, lineterminator='\n')
        cols = ['k', 'condition', 'set', 'addresses'] + ['sum_' + c for c in SUMS] + \
               ['hold_value_mean_weighted', 'hold_p90_median', 'hold_max_max']
        w.writerow(cols)
        for k in ks:
            for cname, sets in results[str(k)]['conditions'].items():
                for sname, s in sets.items():
                    w.writerow([k, cname, sname] + [s.get(c) for c in cols[3:]])
    print(f'{out}: k = {ks}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
