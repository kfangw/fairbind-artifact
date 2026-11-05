#!/usr/bin/env python3
"""Replay inputs for a chain other than Base: joins the daily settlement files of a collection into one
list, derives the reference aggregates and a conditions file from the list itself.

    chain_inputs.py build --chain polygon --dir DIR_OF_DAILY_FILES [--prior-dir DIR] --out OUT_DIR

The daily files are `settlements_YYYY-MM-DD.csv.gz` (a plain `.csv` also works) with the columns of
conditions.json (`block_number, block_time_utc, tx_hash, tx_index, trace_address, recipient, payer,
value_atomic, facilitator`), one file per UTC date, sorted by block inside a file. An optional
`manifest.jsonl` next to them lists, for each file, its row count, the SHA-256 of the compressed file and
the sum of its values; `build` checks all three.

The output directory gets
    settlements_<chain>_<first date>_<last date>.csv          the joined list
    settlements_<chain>_prior_<first date>_<last date>.csv    the joined prior list (with --prior-dir)
    ref/sellers_<chain>_top.csv, ref/sellers_<chain>_all.csv  settlement counts per recipient of the list
                                                              (the reference aggregates; --reference-dir)
    conditions_<chain>.json                                   conditions.json for this list
    input_report.json                                         hashes, counts, checks, measured block time

The reference aggregates are counted from the replayed list itself (there is no earlier reference for these
chains), so the scale rules that read them are descriptive here; the design-2 sales cap does not read them.
The address groups follow the Base definitions at the size of the chain: A is the top 1% of the receiving
addresses (at least one), B takes every eighth rank after the first A + 3 ranks, C the addresses nearest the
90th, 75th and 50th percentile of the mean rate (five each).
"""
import argparse
import copy
import csv
import gzip
import hashlib
import io
import json
import re
import sys
from collections import Counter
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import inputs  # noqa: E402

FILE_RE = re.compile(r'^settlements_(\d{4}-\d{2}-\d{2})\.csv(\.gz)?$')
TOP_N = 400


def daily_files(directory):
    """The daily files of a directory in date order; refuses a gap between the first and the last date."""
    found = {}
    for path in Path(directory).iterdir():
        m = FILE_RE.match(path.name)
        if m:
            found[m.group(1)] = path
    if not found:
        raise ValueError(f'{directory}: no settlements_YYYY-MM-DD.csv(.gz) files')
    import datetime
    dates = sorted(found)
    d0, d1 = (datetime.date.fromisoformat(dates[0]), datetime.date.fromisoformat(dates[-1]))
    missing = [str(d0 + datetime.timedelta(days=i)) for i in range((d1 - d0).days + 1)
               if str(d0 + datetime.timedelta(days=i)) not in found]
    if missing:
        raise ValueError(f'{directory}: missing dates {missing}')
    return [(d, found[d]) for d in dates]


def read_manifest(directory):
    path = Path(directory) / 'manifest.jsonl'
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            entry = json.loads(line)
            out[entry['file']] = entry
    return out


def open_text(path):
    if str(path).endswith('.gz'):
        return io.TextIOWrapper(gzip.open(path, 'rb'), encoding='ascii', newline='')
    return open(path, newline='', encoding='ascii')


def join_files(directory, out_path, columns):
    """Writes the joined list and returns its statistics. Each file is checked against the manifest (row
    count, SHA-256 of the compressed file, value sum) and the header against `columns`; the block number must
    not decrease from one row to the next, across file boundaries too."""
    files = daily_files(directory)
    manifest = read_manifest(directory)
    counts, values_by, facilitators = Counter(), Counter(), Counter()
    rows = value_sum = zero_values = max_value = order_violations = 0
    seen, duplicates = set(), 0
    first = last = None
    day_stats, problems = [], []
    prev_block = None
    sha = hashlib.sha256()
    with open(out_path, 'w', newline='', encoding='ascii') as out:
        writer = csv.writer(out, lineterminator='\n')
        writer.writerow(columns)
        for date, path in files:
            n = vsum = 0
            fb = lb = ft = lt = None
            with open_text(path) as fh:
                reader = csv.reader(fh)
                header = next(reader)
                if header != columns:
                    raise ValueError(f'{path}: header {header} is not {columns}')
                for row in reader:
                    block = int(row[0])
                    value = int(row[7])
                    if prev_block is not None and block < prev_block:
                        order_violations += 1
                    prev_block = block
                    ident = (row[2], row[4])
                    if ident in seen:
                        duplicates += 1
                    seen.add(ident)
                    if value == 0:
                        zero_values += 1
                    max_value = max(max_value, value)
                    key = inputs.normalize(row[5])
                    counts[key] += 1
                    values_by[key] += value
                    facilitators[inputs.normalize(row[8])] += 1
                    n += 1
                    vsum += value
                    if fb is None:
                        fb, ft = block, inputs.utc_seconds(row[1])
                        if first is None:
                            first = (block, row[1])
                    lb, lt = block, inputs.utc_seconds(row[1])
                    last = (block, row[1])
                    writer.writerow(row)
            m = manifest.get(path.name)
            if m is not None:
                if int(m['rows']) != n:
                    problems.append(f'{path.name}: {n} rows, manifest {m["rows"]}')
                if int(m['value_sum_atomic']) != vsum:
                    problems.append(f'{path.name}: value sum {vsum}, manifest {m["value_sum_atomic"]}')
                if inputs.sha256_file(path) != m['sha256_gz']:
                    problems.append(f'{path.name}: SHA-256 differs from the manifest')
            elif manifest:
                problems.append(f'{path.name}: not in the manifest')
            rows += n
            value_sum += vsum
            day_stats.append(dict(date=date, rows=n, value_sum_atomic=vsum, first_block=fb, last_block=lb,
                                  seconds_per_block=(None if fb is None or lb == fb else str(Fraction(lt - ft, lb - fb)))))
    with open(out_path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            sha.update(chunk)
    t0, t1 = inputs.utc_seconds(first[1]), inputs.utc_seconds(last[1])
    measured = Fraction(t1 - t0, last[0] - first[0]) if last[0] != first[0] else None
    return dict(path=str(out_path), sha256=sha.hexdigest(), rows=rows, value_sum_atomic=value_sum,
                first_block=first[0], first_time_utc=first[1], last_block=last[0], last_time_utc=last[1],
                first_date=files[0][0], last_date=files[-1][0], files=len(files),
                distinct_recipients=len(counts), distinct_facilitators=len(facilitators),
                max_value_atomic=max_value, zero_value_rows=zero_values, block_order_violations=order_violations,
                duplicate_tx_trace=duplicates, manifest_problems=problems, manifest_checked=bool(manifest),
                seconds_per_block_mean=None if measured is None else str(measured),
                seconds_per_block_mean_float=None if measured is None else float(measured),
                days=day_stats), counts, facilitators


def ranked(counts):
    """Recipients by settlements, descending; equal counts by address."""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def write_reference(counts, ref_dir, chain):
    ref_dir = Path(ref_dir)
    ref_dir.mkdir(parents=True, exist_ok=True)
    order = ranked(counts)
    top = ref_dir / f'sellers_{chain}_top.csv'
    allp = ref_dir / f'sellers_{chain}_all.csv'
    for path, header, rows in ((top, ['seller_id', 'settlements'], order[:TOP_N]),
                               (allp, ['recipient', 'settlements'], order)):
        with open(path, 'w', newline='', encoding='ascii') as f:
            w = csv.writer(f, lineterminator='\n')
            w.writerow(header)
            w.writerows(rows)
    return top, allp, order


def group_spec(n_recipients):
    """The Base group definitions at the size of the chain (see the module docstring)."""
    n_a = max(1, -(-n_recipients // 100))
    n_top = min(TOP_N, n_recipients)
    return n_a, n_top, n_a + 4


def make_conditions(base, chain, list_stats, prior_stats, top_path, all_path, n_recipients, facilitator_hash, measured):
    cond = copy.deepcopy(base)
    n_a, n_top, b_from = group_spec(n_recipients)
    span = list_stats['last_block'] - list_stats['first_block'] + 1
    cond['description'] = (f'Conditions of the {chain} tuning list (built by chain_inputs.py from the list itself): '
                           + base['description'])
    rp = cond['inputs']['replay_period']
    rp.update(file_name=Path(list_stats['path']).name, sha256=list_stats['sha256'], rows=list_stats['rows'],
              first_block=list_stats['first_block'], last_block=list_stats['last_block'],
              start_utc=list_stats['first_time_utc'], end_utc_inclusive=list_stats['last_time_utc'])
    if prior_stats is not None:
        pp = cond['inputs']['prior_period']
        pp.update(file_name=Path(prior_stats['path']).name, sha256=prior_stats['sha256'], rows=prior_stats['rows'],
                  first_block=prior_stats['first_block'], last_block=prior_stats['last_block'],
                  start_utc=prior_stats['first_time_utc'], end_utc_exclusive=list_stats['first_time_utc'])
        pp.pop('qx_window_utc', None)
        pp.pop('qx_window_rows', None)
    else:
        cond['inputs'].pop('prior_period', None)
    cond['inputs']['top400'] = dict(file_name=Path(top_path).name, sha256=inputs.sha256_file(top_path))
    cond['inputs']['all_addresses'] = dict(file_name=Path(all_path).name, sha256=inputs.sha256_file(all_path),
                                           rows=n_recipients)
    cond['inputs']['facilitators'] = dict(count=list_stats['distinct_facilitators'],
                                          sha256_sorted_joined_no_trailing_newline=facilitator_hash)
    cond['inputs']['expected_total'] = list_stats['rows']
    cond['window_blocks'] = span
    cond['window_hours'] = round(span * float(measured) / 3600) if measured else None
    cond['rate_blocks'] = span
    cond['rate_blocks_note'] = ('every rate divides by the list span last_block - first_block + 1 (as for Base); '
                                'window_blocks is the same span, there is no separate 14-day window for this chain')
    cond.pop('expected_scales', None)
    g = cond['groups']
    g['all400'] = dict(ranks=[1, n_top], sha256=None)
    g['A'] = dict(ranks=[1, n_a], sha256=None)
    g['B'] = dict(rank_from=b_from, rank_step=8, rank_to=n_top, sha256=None)
    g['AB'] = dict(sha256=None)
    g['C'] = dict(g['C'], sha256=None)
    cond['run_conditions'] = [1]
    cond['run_conditions_note'] = 'design 2 runs condition 1 (the nE / sales cap rule replaces nF)'
    cond['chain'] = dict(name=chain, seconds_per_block_mean_in_list=measured,
                         note='from the list; the chain value used by a run is design2.json chains.<chain>.block_seconds or --block-time')
    return cond


def build(chain, directory, out_dir, prior_dir=None, base_conditions=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = inputs.load_conditions(base_conditions or inputs.CONDITIONS_PATH)
    columns = base['inputs']['columns']
    design = json.loads((HERE / 'design2.json').read_text(encoding='ascii'))
    if chain not in design['chains']:
        raise ValueError(f'unknown chain {chain}')
    inputs.set_address_case(design['chains'][chain]['address_case'])
    first_date, last_date = daily_files(directory)[0][0], daily_files(directory)[-1][0]
    list_path = out_dir / f'settlements_{chain}_{first_date}_{last_date}.csv'
    stats, counts, facilitators = join_files(directory, list_path, columns)
    prior_stats = None
    if prior_dir is not None:
        pf = daily_files(prior_dir)
        prior_path = out_dir / f'settlements_{chain}_prior_{pf[0][0]}_{pf[-1][0]}.csv'
        prior_stats, _, _ = join_files(prior_dir, prior_path, columns)
    top, allp, order = write_reference(counts, out_dir / 'ref', chain)
    fac_hash = hashlib.sha256('\n'.join(sorted(facilitators)).encode()).hexdigest()
    cond = make_conditions(base, chain, stats, prior_stats, top, allp, len(order), fac_hash,
                           stats['seconds_per_block_mean_float'])
    cond_path = out_dir / f'conditions_{chain}.json'
    cond_path.write_text(json.dumps(cond, indent=1) + '\n', encoding='ascii')
    report = dict(chain=chain, list=stats, prior=prior_stats, conditions=str(cond_path),
                  conditions_sha256=inputs.sha256_file(cond_path), reference_top=str(top), reference_all=str(allp),
                  recipients=len(order), top_recipients=[dict(address=a, settlements=c) for a, c in order[:10]],
                  group_sizes=dict(zip(('A', 'top', 'B_from_rank'), group_spec(len(order)))),
                  checks_pass=not (stats['manifest_problems'] or stats['block_order_violations']
                                   or stats['duplicate_tx_trace'] or (prior_stats and (
                                       prior_stats['manifest_problems'] or prior_stats['block_order_violations']
                                       or prior_stats['duplicate_tx_trace']))))
    (out_dir / 'input_report.json').write_text(json.dumps(report, indent=1, default=str) + '\n', encoding='ascii')
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build')
    b.add_argument('--chain', required=True)
    b.add_argument('--dir', required=True, help='directory of the daily files of the replayed window')
    b.add_argument('--prior-dir', default=None, help='directory of the daily files of the 14 days before it')
    b.add_argument('--out', required=True)
    b.add_argument('--base-conditions', default=None)
    a = p.parse_args(argv)
    report = build(a.chain, a.dir, a.out, a.prior_dir, a.base_conditions)
    summary = {k: report[k] for k in ('chain', 'recipients', 'checks_pass')}
    summary['rows'] = report['list']['rows']
    summary['sha256'] = report['list']['sha256']
    print(json.dumps(summary, indent=1))
    return 0 if report['checks_pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
