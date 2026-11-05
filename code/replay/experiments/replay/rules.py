#!/usr/bin/env python3
"""Decision rules and computation checks over the result files of a replay run.

    rules.py RUN_DIR [RUN_DIR ...] [--m1-predictions CSV] [--out rules.json]

Each rule states its inputs, the statistic, the threshold and a verdict. A rule is
evaluated on every seed of its condition; a verdict that differs between seeds is reported
as seed dependent and the rule counts as met (the unfavourable side). Several run
directories (the same run at two failure limits) are evaluated one by one, and R20-D1 is
met when it is met at either.

The script refuses a run whose envelope says `reportable: false`.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import inputs  # noqa: E402

MET, NOT_MET = 'condition met', 'condition not met'


class NotReportable(Exception):
    pass


def load_run(run_dir):
    run_dir = Path(run_dir)
    env = json.loads((run_dir / 'run.json').read_text())
    if env.get('reportable') is not True:
        raise NotReportable(f'{run_dir}: run is not reportable: {env.get("not_reportable_reasons")}')
    return env


def read_csv(path):
    with open(path, newline='', encoding='ascii') as f:
        return list(csv.DictReader(f))


def num(v):
    return None if v in ('', None) else float(v)


def nums(cell):
    """A list cell as floats (list cells written before the number fix held strings)."""
    return [float(x) for x in json.loads(cell)]


def in_group(row, group):
    return group in json.loads(row['groups'])


def seed_dirs(run_dir, env, condition):
    return [Path(run_dir) / r['directory'] for r in env['runs'] if r['condition'] == condition]


def combine(per_seed):
    verdicts = {v['verdict'] for v in per_seed}
    if len(verdicts) == 1:
        return verdicts.pop()
    return 'seed dependent (' + MET + ' in some seeds)'


# ---------------------------------------------------------------- observed rules

def rule_f1(rows, spec):
    a = [r for r in rows if in_group(r, spec['group'])]
    over = [r['address'] for r in a if num(r['H_max']) > spec['ratio'] * num(r['H_formula'])]
    share = len(over) / len(a) if a else None
    return dict(statistic=share, addresses=len(a), over=len(over), threshold=spec['share'],
                verdict=MET if share is not None and share > spec['share'] else NOT_MET)


def rule_f3(rows, spec):
    a = [r for r in rows if in_group(r, spec['group']) and r['under_assigned'] == 'false']
    att = sum(int(r['attempted_count']) for r in a)
    rej = sum(int(r['rejected_count']) for r in a)
    rate = rej / att if att else None
    return dict(statistic=rate, addresses=len(a), attempted=att, rejected=rej, threshold=spec['rate'],
                verdict=MET if rate is not None and rate > spec['rate'] else NOT_MET)


def rule_f4(rows, spec):
    ws = sum(int(r['judgment_window_settlements']) for r in rows)
    below = sum(int(r['judgment_window_settlements_below']) for r in rows)
    share = below / ws if ws else None
    return dict(statistic=share, settlements_in_windows=ws, threshold=spec['weighted_share'],
                verdict=MET if share is not None and share > spec['weighted_share'] else NOT_MET)


def rule_m1(rows, spec, predictions):
    if predictions is None:
        return dict(statistic=None, threshold=spec['share'], verdict='not evaluated: no rejection predictions given')
    a = [r for r in rows if in_group(r, spec['group'])]
    missing = [r['address'] for r in a if r['address'] not in predictions]
    if missing:
        return dict(statistic=None, threshold=spec['share'], verdict=f'not evaluated: {len(missing)} addresses without a prediction')
    far = [r for r in a if abs(num(r['rejection_rate']) - predictions[r['address']]) > spec['difference']]
    share = len(far) / len(a) if a else None
    return dict(statistic=share, addresses=len(a), threshold=spec['share'],
                verdict=MET if share is not None and share > spec['share'] else NOT_MET)


def check_c2_samples(rows, spec, s):
    """R20-C2 third sentence: drawn samples against the expectation. With one rate s the count is
    binomial(accepted, s); under per-row rates (design 2, columns expected_samples and
    sample_variance) it is a Poisson binomial: mean the sum of s(v), variance the sum of s(v)(1 - s(v))."""
    smp = sum(int(r['sample_count']) for r in rows)
    if s is None and rows and rows[0].get('expected_samples') not in (None, ''):
        expected = sum(float(r['expected_samples']) for r in rows)
        sd = math.sqrt(sum(float(r['sample_variance']) for r in rows))
        z = (smp - expected) / sd if sd else 0.0
        return dict(statistic=z, samples=smp, expected=expected, threshold=spec['sample_sd'],
                    distribution='poisson binomial (per-row sampling rates)',
                    verdict='fail: stop the replay' if abs(z) > spec['sample_sd'] else 'pass')
    acc = sum(int(r['accepted_count']) for r in rows)
    sd = math.sqrt(acc * s * (1 - s)) if acc else 0.0
    z = (smp - s * acc) / sd if sd else 0.0
    return dict(statistic=z, samples=smp, expected=s * acc, threshold=spec['sample_sd'],
                verdict='fail: stop the replay' if abs(z) > spec['sample_sd'] else 'pass')


# ---------------------------------------------------------------- injection rules and checks

def rule_d1(inj_rows, spec):
    a = [r for r in inj_rows if in_group_inj(r, spec) and r['setting'] == spec['setting']
         and int(r['reentry_delay_blocks']) == spec['reentry_delay_blocks'] and float(r['claim_probability']) == 1.0]
    ratios = [num(r['ratio_to_formula']) for r in a if num(r['ratio_to_formula']) is not None]
    med = statistics.median(ratios) if ratios else None
    met = med is not None and (med < spec['low'] or med > spec['high'])
    return dict(statistic=med, addresses=len(ratios), threshold=[spec['low'], spec['high']],
                k=sorted({int(r['k']) for r in a}), verdict=MET if met else NOT_MET)


def in_group_inj(row, spec):
    return row['address'] in spec['_members']


def check_c3(inj_rows):
    bad = sorted({r['address'] for r in inj_rows if num(r['principal_over_revenue_max']) > 1.0})
    return dict(statistic=len(bad), addresses=bad, threshold=0,
                verdict='fail: do not use the injection columns' if bad else 'pass')


Z95 = 1.959963984540054


def _outside(mean, sd, n, target, z=Z95):
    half = z * sd / math.sqrt(n) if n > 1 else 0.0
    return abs(mean - target) > half and not (sd == 0 and mean == target)


def check_c2_windows(inj_rows, z=Z95):
    """R20-C2 per address and failure window (design 9.6): the Monte Carlo mean of the injected
    failures assigned to the window of their case's settlement, against s * w * (accepted
    settlements of that window), with the 95% interval of the mean (1.96 standard errors).

    The diagnostic `conditional_on_samples` compares the same mean with w * (sampled cases settled
    in the window), which takes the sampling noise of the replay out of the comparison; it is
    reported beside the verdict and does not change it. Rows without the per-settlement columns
    (an older run) fall back to the confirmation-window counts, and `assignment` says so."""
    flagged, conditional, source = [], [], set()
    for r in inj_rows:
        if r.get('window_failures_by_settlement_mean'):
            mean = nums(r['window_failures_by_settlement_mean'])
            sd = nums(r['window_failures_by_settlement_sd'])
            source.add('settlement window')
        elif r.get('window_failures_mean'):
            mean = nums(r['window_failures_mean'])
            sd = nums(r['window_failures_sd'])
            source.add('confirmation window')
        else:
            continue
        exp = nums(r['window_failures_expected'])
        samples = nums(r['window_samples_by_settlement']) if r.get('window_samples_by_settlement') else None
        w = num(r.get('w'))
        n = int(r['draws'])
        for j, (m, d, e) in enumerate(zip(mean, sd, exp)):
            key = dict(address=r['address'], setting=r['setting'],
                       reentry_delay_blocks=int(r['reentry_delay_blocks']), window=j)
            if _outside(m, d, n, e, z):
                flagged.append(key)
            if samples is not None and w is not None and _outside(m, d, n, w * samples[j], z):
                conditional.append(key)
    return dict(statistic=len(flagged), flagged=flagged[:50], threshold=0, assignment=sorted(source),
                conditional_on_samples=dict(statistic=len(conditional), flagged=conditional[:50]),
                verdict='fail: injection implementation error' if flagged else 'pass')


def c1_bound(s, rate_per_block, w, reentry_delay_blocks):
    """Upper bound on the expected frozen fraction, manuscript v1.5 section 6.4: s * r * w * tau.
    tau is the suspension length of one failure in the injection model (option C1-tau): from the
    confirmed failure f to the re-entry block f + 1 + reentry delay."""
    return s * rate_per_block * w * (1 + reentry_delay_blocks)


def check_c1(inj_rows, s, replay_blocks=None, z=Z95):
    """R20-C1 (design 5.5, 9.7): per address, setting and reentry delay, the Monte Carlo mean of the
    freeze fraction may not exceed the bound by more than the 95% interval of the mean. Rows whose
    bound exceeds 1 are left out (they go to R20-C2). The diagnostic `conditional_on_samples` uses
    the replay's sampled cases, sample_count * w * (1 + delay) / replay blocks, in place of the
    bound; it is reported beside the verdict and does not change it."""
    per_row = s is None and any(r.get('s_rate_per_block') not in (None, '') for r in inj_rows[:1])
    if s is None and not per_row:
        return dict(statistic=None, verdict='not evaluated: no sample rate in condition.json')
    flagged, conditional, excluded, checked = [], [], 0, 0
    seen = set()
    for r in inj_rows:
        if r.get('freeze_fraction_sd') in (None, '') or r.get('rate_acc_per_block') in (None, ''):
            return dict(statistic=None, verdict='not evaluated: the run has no freeze_fraction_sd column')
        key = (r['address'], r['setting'], int(r['reentry_delay_blocks']))
        if key in seen:  # the freeze fraction does not depend on the claim probability
            continue
        seen.add(key)
        tau = int(r['reentry_delay_blocks'])
        w = num(r['w'])
        # Per-row rates (design 2): s * rbar_acc is the expected samples per block, sum of s(v) / blocks.
        bound = c1_bound(1.0 if per_row else s, num(r['s_rate_per_block']) if per_row else num(r['rate_acc_per_block']),
                         w, tau)
        if bound > 1:
            excluded += 1
            continue
        checked += 1
        mean, sd, n = num(r['freeze_fraction_mean']), num(r['freeze_fraction_sd']), int(r['draws'])
        half = z * sd / math.sqrt(n) if n > 1 else 0.0
        item = dict(address=r['address'], setting=r['setting'], reentry_delay_blocks=tau, mean=mean, bound=bound)
        if mean - bound > half:
            flagged.append(item)
        if replay_blocks and r.get('sample_count') not in (None, ''):
            cond_bound = int(r['sample_count']) * w * (1 + tau) / replay_blocks
            if mean - cond_bound > half:
                conditional.append(dict(item, bound=cond_bound))
    return dict(statistic=len(flagged), checked=checked, excluded_bound_above_one=excluded, flagged=flagged[:50],
                threshold=0, bound='s * rbar_acc * w * (1 + reentry delay) (manuscript v1.5 6.4, option C1-tau)',
                conditional_on_samples=dict(statistic=len(conditional), flagged=conditional[:50]),
                verdict='fail: do not use the injection columns' if flagged else 'pass')


# ---------------------------------------------------------------- driver

def _m1(rows, spec, predictions, note):
    if note is not None and note.startswith('not evaluated'):
        return dict(statistic=None, threshold=spec['share'], verdict=note)
    out = rule_m1(rows, spec, predictions)
    if note:
        out['note'] = note
    return out


def evaluate(run_dirs, predictions=None, conditions_path=None, predictions_sha256=None):
    cond = inputs.load_conditions(conditions_path or inputs.CONDITIONS_PATH)
    specs = cond['rules']
    out = dict(runs=[], rules={})
    d1_runs = []
    for run_dir in run_dirs:
        env = load_run(run_dir)
        per = {}
        # The prediction file must be the one whose hash the run envelope recorded (design 9.7).
        registered = ((env.get('inputs') or {}).get('m1_predictions') or {}).get('sha256')
        m1_note = None
        if env.get('design') == 'design-2':
            m1_note = 'not evaluated: the R20-M1 predictions are made for the design-1 scales (nF)'
        elif predictions is not None and registered is not None and predictions_sha256 != registered:
            m1_note = 'not evaluated: the prediction file differs from the one recorded in the run envelope'
        elif predictions is not None and registered is None:
            m1_note = 'the prediction file is not recorded in the run envelope'
        c = specs['R20-F1']['condition']
        dirs = seed_dirs(run_dir, env, c)
        if not dirs:
            raise ValueError(f'{run_dir}: condition {c} was not run')
        members_a = None
        for d in dirs:
            rows = read_csv(d / 'addresses_observed.csv')
            meta = json.loads((d / 'condition.json').read_text())
            members_a = {r['address'] for r in rows if in_group(r, 'A')}
            inj_rows = read_csv(d / 'addresses_injection.csv')
            seed_out = per.setdefault('seeds', [])
            sample_rate = meta.get('sample_rate')
            seed_out.append(dict(
                directory=d.name,
                **{'R20-F1': rule_f1(rows, specs['R20-F1']), 'R20-F3': rule_f3(rows, specs['R20-F3']),
                   'R20-F4': rule_f4(rows, specs['R20-F4']),
                   'R20-M1': _m1(rows, specs['R20-M1'], predictions, m1_note),
                   'R20-C2-samples': check_c2_samples(rows, specs['R20-C2'], sample_rate),
                   'R20-D1': rule_d1(inj_rows, dict(specs['R20-D1'], _members=members_a)),
                   'R20-C2-windows': check_c2_windows(inj_rows), 'R20-C3': check_c3(inj_rows),
                   'R20-C1': check_c1(inj_rows, sample_rate, meta.get('replay_blocks'))}))
        summary = {}
        for name in ('R20-F1', 'R20-F3', 'R20-F4', 'R20-M1', 'R20-D1'):
            summary[name] = combine([x[name] for x in per['seeds']])
        d1_runs.append(summary['R20-D1'])
        out['runs'].append(dict(directory=str(run_dir), k=env['parameters']['k'], k_role=env['parameters']['k_role'],
                                conditions_run=sorted({r['condition'] for r in env['runs']}),
                                conditions_not_run=env.get('conditions_not_run', []),
                                summary=summary, seeds=per['seeds']))
    out['rules']['R20-D1'] = MET if any(v != NOT_MET for v in d1_runs) else NOT_MET
    for name in ('R20-F1', 'R20-F3', 'R20-F4', 'R20-M1'):
        vs = {r['summary'][name] for r in out['runs']}
        out['rules'][name] = vs.pop() if len(vs) == 1 else 'differs between runs: ' + ', '.join(sorted(vs))
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('runs', nargs='+')
    p.add_argument('--m1-predictions', help='CSV with address,predicted_rejection_rate')
    p.add_argument('--conditions-file', default=None)
    p.add_argument('--out')
    a = p.parse_args(argv)
    predictions = sha = None
    if a.m1_predictions:
        predictions = {r['address'].lower(): float(r['predicted_rejection_rate']) for r in read_csv(a.m1_predictions)}
        sha = inputs.sha256_file(a.m1_predictions)
    try:
        result = evaluate(a.runs, predictions, a.conditions_file, sha)
    except NotReportable as exc:
        print(f'refused: {exc}', file=sys.stderr)
        return 2
    text = json.dumps(result, sort_keys=True, indent=1) + '\n'
    if a.out:
        Path(a.out).write_text(text)
    sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
