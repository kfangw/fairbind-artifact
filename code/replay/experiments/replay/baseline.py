#!/usr/bin/env python3
"""Rate-proportional bond baseline (design 9.9, D9).

A design that judges and deducts like FairBind but does not hold proceeds lets a cheating seller
keep everything it sells until its first detection is confirmed, so its expected gain per
episode is g * (1/p + r * L) and the deduction rule needs, per address a,

    B_vel(a) = k * g * (ceil(1/p) + ceil(r_a * L))

Two steps:

    baseline.py list-only --settlements CSV --reference-dir DIR --out PREFIX
        list-only values, written to PREFIX.json and PREFIX.csv: B_vel(a) under the main
        definition and the variants V-mean, V-path and V-amount, the FairBind-side values
        n_a * B and n_a * k * g * ceil(1/p) (n_a the nF scale; V-amount uses n_a * k * vbar_a *
        ceil(1/p)), group sums (rank 1, rank 2, ranks 3-44, A, B, all replayed) and the median,
        minimum and maximum of B_vel(a) / (n_a * B). Reads only the list and the reference
        aggregates.

    baseline.py compare --baseline PREFIX.json RUN_DIR [--out FILE]
        adds n_a * B + H_max of condition 1 from a finished, reportable replay run (per seed and
        the mean over seeds) beside B_vel(a). This step reads replay results.

Definitions (main / variant):
    r_a  highest clock-hour (UTC) settlement count of a in the list / 1,800 blocks
         (V-mean: settlements of a in the list / rate_blocks)
    L    T_case = caseHorizon (V-path: the longest measured path L_actual)
    g    maxBadGain of the data-API profile (V-amount: vbar_a, the mean settlement value of a)
    p    effectivePpm / PPM; k failureLimit and B sellerPenalty of the replay profile
"""
import argparse
import csv
import io
import json
import statistics
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'experiments'))

import inputs  # noqa: E402
import replay  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402

PROFILE = 'data-api-fast-v1'
HOUR_BLOCKS = 1800
VARIANTS = ('main', 'V-mean', 'V-path', 'V-amount')
GROUPS = ('rank1', 'rank2', 'ranks3_44', 'A', 'B', 'replayed')


def ceil_fraction(x):
    x = Fraction(x)
    return -(-x.numerator // x.denominator)


def parameters(op, profile):
    p = profile['parameters']
    entry = op['profiles'][PROFILE]
    ppm = op['chain']['ppm']
    return dict(k=int(p['failureLimit']), g=int(p['maxBadGain']), B=int(p['sellerPenalty']),
                p=Fraction(p['effectivePpm'], ppm), inv_p=ceil_fraction(Fraction(ppm, p['effectivePpm'])),
                T_case=int(entry['caseHorizon_blocks']['value']), L_actual=int(entry['L_actual_blocks']['value']),
                decimals=op['chain']['token_decimals'])


def list_stats(path, columns, addresses):
    """Per address: settlement count, value sum and the highest clock-hour count, from the list."""
    wanted = set(addresses)
    out = {a: dict(count=0, value=0, hours={}) for a in addresses}
    for row in inputs.iter_rows(path, columns):
        a = row[5].lower()
        if a not in wanted:
            continue
        s = out[a]
        s['count'] += 1
        s['value'] += int(row[7])
        hour = inputs.utc_seconds(row[1]) // 3600
        s['hours'][hour] = s['hours'].get(hour, 0) + 1
    for s in out.values():
        s['peak_hour'] = max(s['hours'].values()) if s['hours'] else 0
        del s['hours']
    return out


def b_vel(k, g, inv_p, rate, length):
    """k * g * (ceil(1/p) + ceil(r * L)), exact (rate a Fraction per block)."""
    return k * g * (inv_p + ceil_fraction(rate * length))


def address_row(a, st, n, prm, rate_blocks):
    k, g, inv_p, B = prm['k'], prm['g'], prm['inv_p'], prm['B']
    peak_rate = Fraction(st['peak_hour'], HOUR_BLOCKS)
    mean_rate = Fraction(st['count'], rate_blocks)
    vbar = Fraction(st['value'], st['count']) if st['count'] else Fraction(0)
    row = dict(address=a, scale=n, settlements=st['count'], value_atomic=st['value'], peak_hour=st['peak_hour'],
               mean_value_atomic=float(vbar))
    row['B_vel_main'] = b_vel(k, g, inv_p, peak_rate, prm['T_case'])
    row['B_vel_V-mean'] = b_vel(k, g, inv_p, mean_rate, prm['T_case'])
    row['B_vel_V-path'] = b_vel(k, g, inv_p, peak_rate, prm['L_actual'])
    # V-amount: vbar_a in place of g on both sides.
    row['B_vel_V-amount'] = float(k * vbar * (inv_p + ceil_fraction(peak_rate * prm['T_case'])))
    row['fairbind_bond_nB'] = n * B
    row['fairbind_deterrence_min'] = n * k * g * inv_p
    row['fairbind_deterrence_min_V-amount'] = float(n * k * vbar * inv_p)
    for v in VARIANTS:
        row[f'ratio_{v}'] = float(Fraction(row[f'B_vel_{v}']) / (n * B))
    return row


def summary(rows, groups, prm):
    out = {}
    for g in GROUPS:
        members = [r for r in rows if r['address'] in groups[g]]
        e = dict(addresses=len(members))
        for v in VARIANTS:
            e[f'B_vel_{v}_sum'] = sum(r[f'B_vel_{v}'] for r in members)
            ratios = [r[f'ratio_{v}'] for r in members]
            e[f'ratio_{v}'] = dict(median=statistics.median(ratios) if ratios else None,
                                   min=min(ratios) if ratios else None, max=max(ratios) if ratios else None)
        for key in ('fairbind_bond_nB', 'fairbind_deterrence_min', 'fairbind_deterrence_min_V-amount'):
            e[f'{key}_sum'] = sum(r[key] for r in members)
        out[g] = e
    return out


CSV_COLUMNS = (['address', 'rank', 'groups', 'scale', 'settlements', 'value_atomic', 'peak_hour', 'mean_value_atomic']
               + [f'B_vel_{v}' for v in VARIANTS]
               + ['fairbind_bond_nB', 'fairbind_deterrence_min', 'fairbind_deterrence_min_V-amount']
               + [f'ratio_{v}' for v in VARIANTS])


def write_csv(path, rows, columns):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(columns)
    for r in rows:
        w.writerow([json.dumps(r[c]) if isinstance(r.get(c), list) else
                    (repr(r[c]) if isinstance(r.get(c), float) else r.get(c, '')) for c in columns])
    Path(path).write_text(buf.getvalue(), encoding='ascii')


def list_only(settlements, ref_dir, cond, op_path):
    op = opt.load(op_path)
    profile = prof.load_profile(ROOT / op['profile_file'], PROFILE)
    errors = opt.check(op, profile)
    if errors:
        raise SystemExit('operating point and profile disagree: ' + '; '.join(errors))
    prm = parameters(op, profile)
    top400, _alla, groups, _hashes, _c, rank = replay.build_groups(cond, Path(ref_dir))
    seen = set()
    groups['replayed'] = [a for a in groups['all400'] + groups['C'] if not (a in seen or seen.add(a))]
    sets = {g: set(groups[g]) for g in GROUPS}
    rate_blocks = replay.rate_blocks(cond)
    counts = groups['_counts']
    scales = replay.scales([(a, counts[a]) for a in groups['replayed']], 'nF', profile['parameters'], rate_blocks)
    stats = list_stats(settlements, cond['inputs']['columns'], groups['replayed'])
    rows = []
    for a in groups['replayed']:
        r = address_row(a, stats[a], scales[a], prm, rate_blocks)
        r['rank'] = rank.get(a)
        r['groups'] = [g for g in GROUPS if a in sets[g]]
        rows.append(r)
    sha = inputs.sha256_file(settlements)
    doc = dict(kind='fairbind-r20-velocity-baseline', design_section='9.9', step='list-only', code=replay.git_state(),
               settlements=dict(path=str(settlements), sha256=sha,
                                period=next((k for k, v in cond['inputs'].items()
                                             if isinstance(v, dict) and v.get('sha256') == sha), None)),
               conditions_file=dict(path=cond['_path'], sha256=cond['_sha256']),
               operating_point=dict(path=op['_path'], sha256=op['_sha256']), profile=PROFILE,
               parameters=dict(k=prm['k'], g_atomic=prm['g'], p=str(prm['p']), ceil_inv_p=prm['inv_p'],
                               B_atomic=prm['B'], L_main_T_case=prm['T_case'], L_V_path=prm['L_actual'],
                               hour_blocks=HOUR_BLOCKS, rate_blocks=rate_blocks, scale_rule='nF',
                               token_decimals=prm['decimals']),
               units='atomic token units (divide by 10^token_decimals for USDC)',
               groups=summary(rows, sets, prm), addresses=rows)
    return doc


def compare(baseline_path, run_dir):
    """n_a * B + H_max of condition 1 from a finished reportable run, beside B_vel(a)."""
    import rules
    base = json.loads(Path(baseline_path).read_text())
    env = rules.load_run(run_dir)
    condition = 1
    dirs = rules.seed_dirs(run_dir, env, condition)
    if not dirs:
        raise SystemExit(f'{run_dir}: condition {condition} was not run')
    per_seed = []
    for d in dirs:
        rows = {r['address']: r for r in rules.read_csv(d / 'addresses_observed.csv')}
        per_seed.append({a: float(r['nB_plus_H_max']) for a, r in rows.items() if r['nB_plus_H_max'] != ''})
    out_rows = []
    for r in base['addresses']:
        vals = [s[r['address']] for s in per_seed if r['address'] in s]
        mean = sum(vals) / len(vals) if vals else None
        out_rows.append(dict(address=r['address'], groups=r['groups'], scale=r['scale'],
                             B_vel_main=r['B_vel_main'], nB_plus_H_max_per_seed=vals, nB_plus_H_max_mean=mean,
                             ratio_B_vel_main_to_nB_plus_H_max=(r['B_vel_main'] / mean) if mean else None))
    groups = {}
    for g in GROUPS:
        members = [x for x in out_rows if g in x['groups']]
        means = [x['nB_plus_H_max_mean'] for x in members if x['nB_plus_H_max_mean'] is not None]
        groups[g] = dict(addresses=len(members), B_vel_main_sum=sum(x['B_vel_main'] for x in members),
                         nB_plus_H_max_mean_sum=sum(means))
    return dict(kind='fairbind-r20-velocity-baseline', design_section='9.9', step='compare', code=replay.git_state(),
                baseline=dict(path=str(baseline_path), sha256=inputs.sha256_file(baseline_path)),
                run=dict(path=str(run_dir), code=env.get('code'), seeds=[d.name for d in dirs]),
                groups=groups, addresses=out_rows)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ('list-only', 'compare'):
        print('usage: baseline.py list-only ... | compare ...', file=sys.stderr)
        return 2
    command = argv.pop(0)
    ap = argparse.ArgumentParser(prog=f'baseline.py {command}')
    if command == 'list-only':
        ap.add_argument('--settlements', required=True)
        ap.add_argument('--reference-dir', required=True)
        ap.add_argument('--conditions-file', default=str(inputs.CONDITIONS_PATH))
        ap.add_argument('--operating-point', default=None)
        ap.add_argument('--out', required=True, help='output prefix; writes PREFIX.json and PREFIX.csv')
        a = ap.parse_args(argv)
        cond = inputs.load_conditions(a.conditions_file)
        doc = list_only(a.settlements, a.reference_dir, cond, a.operating_point or replay.default_operating_point(cond))
        prefix = Path(a.out)
        Path(str(prefix) + '.json').write_text(json.dumps(doc, indent=1, sort_keys=True) + '\n')
        write_csv(str(prefix) + '.csv', doc['addresses'], CSV_COLUMNS)
        print(f'{prefix}.json, {prefix}.csv: {len(doc["addresses"])} addresses')
        return 0
    ap.add_argument('run_dir')
    ap.add_argument('--baseline', required=True, help='PREFIX.json of the list-only step')
    ap.add_argument('--out')
    a = ap.parse_args(argv)
    import rules
    try:
        doc = compare(a.baseline, a.run_dir)
    except rules.NotReportable as exc:
        print(f'refused: {exc}', file=sys.stderr)
        return 2
    text = json.dumps(doc, indent=1, sort_keys=True) + '\n'
    if a.out:
        Path(a.out).write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
