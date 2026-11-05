#!/usr/bin/env python3
"""Design-2 report columns (design2_rules section 5) of one condition and seed of a replay run, for
design 1 and design 2 runs alike, from the result files only.

    d2_report.py RUN_DIR [RUN_DIR ...] [--condition 1] [--seed 0] [--group A] [--csv out.csv]
    d2_report.py --columns RUN_DIR [...] [--json out.json] [--csv out.csv] [--addresses out.csv] [--markdown]

The first form is the compact comparison of design 1 and design 2 runs. `--columns` writes the columns of
section 5.2 of the second edition of the rules (`columns()`), one row per run, for the groups
all replayed addresses / A / the rest.

Per group: share of the attempted settlements and of the list that is accepted (count and value),
cap rejections and rate-limit rejections (design 1 does not enforce the cap: zero), inspections
(drawn and expected), bond sum, held proceeds (hourly mean and maximum of the group sum), and for
the main injection setting without reentry delay and with every claim the loss over revenue of the
group (mean and 95% interval over the draws) and the revenue-weighted formula value of its addresses.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from fractions import Fraction
from pathlib import Path

USDC = 1_000_000


def read_csv(path):
    with open(path, newline='', encoding='ascii') as f:
        return list(csv.DictReader(f))


def f(x):
    return None if x in ('', None) else float(x)


def members(rows, group):
    return [r for r in rows if group in json.loads(r['groups'])]


def condition_dir(run_dir, condition, seed):
    return Path(run_dir) / f'condition-{condition:02d}-seed-{seed}'


def report(run_dir, condition=1, seed=0, group='A', setting='main', reentry=0, claim=1.0):
    run_dir = Path(run_dir)
    d = condition_dir(run_dir, condition, seed)
    env = json.loads((run_dir / 'run.json').read_text())
    meta = json.loads((d / 'condition.json').read_text())
    obs = read_csv(d / 'addresses_observed.csv')
    gobs = {r['group']: r for r in read_csv(d / 'groups_observed.csv')}
    ginj = read_csv(d / 'groups_injection.csv')
    ainj = read_csv(d / 'addresses_injection.csv')
    list_rows = env['inputs']['settlements']['rows']
    rep = gobs['replayed']
    list_value = sum(int(r['attempted_value']) for r in obs) / float(rep['share_value'])   # total value of the list
    design2 = 'design2' in meta
    out = dict(run=run_dir.name, condition=condition, seed=seed, design=2 if design2 else 1,
               scale_rule=meta['scale_rule'], tau_usdc=meta['design2']['tau_usdc'] if design2 else None,
               hold_blocks=meta['hold_blocks'], k=meta['k'], unit_bond_usdc=meta['sellerPenalty'] / USDC)
    for g in ('replayed', group):
        rs = members(obs, g) if g != 'replayed' else obs
        att = sum(int(r['attempted_count']) for r in rs)
        attv = sum(int(r['attempted_value']) for r in rs)
        acc = sum(int(r['accepted_count']) for r in rs)
        accv = sum(int(r['accepted_value']) for r in rs)
        cap = sum(int(r.get('cap_rejected_count') or 0) for r in rs)
        capv = sum(int(r.get('cap_rejected_value') or 0) for r in rs)
        rate = sum(int(r['rejected_count']) for r in rs)
        exp_s = (sum(float(r['expected_samples']) for r in rs) if design2 else None)
        gr = gobs[g]
        inj = [r for r in ginj if r['group'] == g and r['setting'] == setting
               and int(r['reentry_delay_blocks']) == reentry and float(r['claim_probability']) == claim]
        wa = [r for r in ainj if r['setting'] == setting and int(r['reentry_delay_blocks']) == reentry
              and float(r['claim_probability']) == claim and r['address'] in {x['address'] for x in rs}]
        w_rev = sum(f(r['revenue_mean']) for r in wa if r['formula_value'])
        formula = (sum(f(r['formula_value']) * f(r['revenue_mean']) for r in wa if r['formula_value']) / w_rev
                   if w_rev else None)
        out[g] = dict(
            addresses=len(rs), attempted_count=att, attempted_value_usdc=attv / USDC,
            accepted_count=acc, accepted_value_usdc=accv / USDC,
            accepted_share_of_attempted_count=acc / att if att else None,
            accepted_share_of_attempted_value=accv / attv if attv else None,
            accepted_share_of_list_count=acc / list_rows, accepted_share_of_list_value=accv / list_value,
            cap_rejected_count=cap, cap_rejected_value_usdc=capv / USDC, rate_rejected_count=rate,
            rate_rejection_rate=rate / att if att else None,
            inspections_drawn=sum(int(r['sample_count']) for r in rs),
            inspections_expected=exp_s if design2 else None,
            bond_sum_usdc=sum(int(r['nB']) for r in rs) / USDC,
            H_mean_usdc=f(gr['H_time_average']) / USDC, H_max_usdc=f(gr['H_max']) / USDC,
            loss_over_revenue_mean=f(inj[0]['loss_over_revenue_mean']) if inj else None,
            loss_over_revenue_p2_5=f(inj[0]['loss_over_revenue_p2_5']) if inj else None,
            loss_over_revenue_p97_5=f(inj[0]['loss_over_revenue_p97_5']) if inj else None,
            formula_value_revenue_weighted=formula)
    return out


# ---------------------------------------------------------------- section 5.2 columns (second edition)

W_REPORT = ('0.0003', '0.004728', '0.011', '0.015')
INJECTION_SETTINGS = ('main', 'w_0.015')


def quartiles(values):
    xs = sorted(values)
    if not xs:
        return dict(n=0, min=None, q1=None, median=None, q3=None, max=None)
    if len(xs) == 1:
        return dict(n=1, min=xs[0], q1=xs[0], median=xs[0], q3=xs[0], max=xs[0])
    q = statistics.quantiles(xs, n=4, method='inclusive')
    return dict(n=len(xs), min=xs[0], q1=q[0], median=q[1], q3=q[2], max=xs[-1])


def formula_terms(r, hold, rate_blocks, w, deduction):
    """The two terms of the loss formula of one address for failure probability w (section 5.2, column 7):
    1 - exp(-w * rbar * sbar * T_hold) and sbar * w * b / vbar, as shares of the address's revenue."""
    acc = int(r['accepted_count'])
    if acc == 0 or r.get('mean_value') in ('', None) or r.get('s_bar') in ('', None):
        return None
    rbar = acc / rate_blocks
    s = float(r['s_bar'])
    vbar = float(r['mean_value'])
    return 1 - math.exp(-w * rbar * s * hold), s * w * deduction / vbar


def columns(run_dir, condition=1, seed=0, w_list=W_REPORT, settings=INJECTION_SETTINGS, group='A'):
    """The columns of section 5.2 for one run (a chain, a v_max, a sales cap rule), for the groups
    `replayed` (all replayed addresses), `A` and `rest` (replayed without A). Amounts are USDC; a share of the
    list uses the totals of the whole list. Returns a nested dict."""
    run_dir = Path(run_dir)
    d = condition_dir(run_dir, condition, seed)
    env = json.loads((run_dir / 'run.json').read_text())
    meta = json.loads((d / 'condition.json').read_text())
    d2 = meta.get('design2')
    if d2 is None:
        raise ValueError(f'{run_dir}: not a design-2 run')
    obs = read_csv(d / 'addresses_observed.csv')
    gobs = {r['group']: r for r in read_csv(d / 'groups_observed.csv')}
    ginj = read_csv(d / 'groups_injection.csv')
    ainj = read_csv(d / 'addresses_injection.csv')
    chain = d2.get('chain') or dict(name='base', block_seconds='2')
    bt = Fraction(chain['block_seconds'])
    hold = meta['hold_blocks']
    rate_blocks = meta['rate_blocks']
    replay_blocks = meta['replay_blocks']
    days = float(replay_blocks * bt / 86400)
    hours = days * 24
    members = {'replayed': obs, 'A': [r for r in obs if group in json.loads(r['groups'])]}
    members['rest'] = [r for r in obs if group not in json.loads(r['groups'])]
    list_rows, list_value = meta['list_rows'], meta['list_value']
    b_default = meta['sellerPenalty'] // meta['k']

    def b_of(r):
        return int(r['deduction_b']) if r.get('deduction_b') not in ('', None) else b_default

    out = dict(
        run=run_dir.name, condition=condition, seed=seed,
        chain=chain['name'], block_seconds=str(chain['block_seconds']), block_seconds_source=chain.get('source'),
        rule_edition=d2.get('rule_edition', 1), vmax_usdc=d2.get('vmax_usdc', d2.get('tau_usdc')),
        sales_cap_rule=d2.get('sales_cap') or ('multiplier-' + str(d2.get('multiplier_source'))),
        hold_blocks=hold, hold_hours=float(hold * bt / 3600), failure_window_blocks=d2['failure_window_blocks'],
        window_alignment=d2.get('window_alignment', 'first-block'), failure_windows_complete=meta.get('failure_windows_complete'),
        replay_blocks=replay_blocks, replay_days=days, list_rows=list_rows, list_value_usdc=list_value / USDC,
        k_table=d2.get('k_table'), k_w=d2.get('k_w'), unit_deduction_usdc=d2.get('unit_deduction_atomic', b_default) / USDC,
        addresses_replayed=len(obs), reportable=env['reportable'], code_revision=env['code']['revision'],
        inputs=dict(settlements_sha256=env['inputs']['settlements']['sha256'],
                    prior_sha256=(env.get('design2_prior_input') or {}).get('sha256')))
    # 4, 5: share of the settlements in range (v <= v_max): count first, value after.
    inrange = {}
    for g, rs in members.items():
        att = sum(int(r['attempted_count']) for r in rs)
        attv = sum(int(r['attempted_value']) for r in rs)
        cap = sum(int(r['cap_rejected_count']) for r in rs)
        capv = sum(int(r['cap_rejected_value']) for r in rs)
        inrange[g] = dict(count=1 - cap / att if att else None, value=1 - capv / attv if attv else None,
                          attempted=att, in_range=att - cap)
    inrange['list'] = dict(count=meta['list_cap_pass_rows'] / list_rows, value=meta['list_cap_pass_value'] / list_value,
                           attempted=list_rows, in_range=meta['list_cap_pass_rows'])
    out['in_range_share'] = inrange
    # 1, 2: deposit.
    out['bond_sum_usdc'] = {g: sum(int(r['nB']) for r in rs) / USDC for g, rs in members.items()}
    days_of_revenue, no_revenue = {}, {}
    for g, rs in members.items():
        xs, none = [], 0
        for r in rs:
            rev = int(r['accepted_value'])
            if rev == 0:
                none += 1
                continue
            xs.append(int(r['nB']) / (rev / days))
        days_of_revenue[g], no_revenue[g] = quartiles(xs), none
    out['bond_days_of_revenue'] = days_of_revenue
    out['bond_days_no_revenue_addresses'] = no_revenue
    # 3: caps.
    dist = {}
    for g, rs in members.items():
        c = {}
        for r in rs:
            key = int(r['sales_cap_S']) if r.get('sales_cap_S') not in ('', None) else None
            c[key] = c.get(key, 0) + 1
        dist[g] = {str(k): c[k] for k in sorted(c, key=lambda x: (x is None, x))}
    out['cap_distribution'] = dist
    # 6: held proceeds.
    held = {}
    for g in ('replayed', 'A'):
        gr = gobs[g]
        mean, peak = f(gr['H_time_average']), f(gr['H_max'])
        held[g] = dict(mean_usdc=None if mean is None else mean / USDC, max_usdc=None if peak is None else peak / USDC)
    both = held['replayed']['mean_usdc'], held['A']['mean_usdc']
    held['rest'] = dict(mean_usdc=None if None in both else both[0] - both[1], max_usdc=None)
    per_h = {g: quartiles([f(r['H_time_average']) / USDC for r in rs if r['H_time_average'] not in ('', None)])
             for g, rs in members.items()}
    per_max = {g: quartiles([f(r['H_max']) / USDC for r in rs if r['H_max'] not in ('', None)])
               for g, rs in members.items()}
    out['held_proceeds'] = held
    out['held_proceeds_per_address_mean'] = per_h
    out['held_proceeds_per_address_max'] = per_max
    # 7: loss formula, two terms, as a function of w.
    formula = {}
    for wtxt in w_list:
        w = float(wtxt)
        entry = {}
        for g, rs in members.items():
            rev = t1 = t2 = 0.0
            for r in rs:
                terms = formula_terms(r, hold, rate_blocks, w, b_of(r))
                if terms is None:
                    continue
                value = int(r['accepted_value'])
                rev += value
                t1 += terms[0] * value
                t2 += terms[1] * value
            entry[g] = dict(term1_share=t1 / rev if rev else None, term2_share=t2 / rev if rev else None,
                            total_share=(t1 + t2) / rev if rev else None, term1_usdc=t1 / USDC,
                            term2_usdc=t2 / USDC, total_usdc=(t1 + t2) / USDC, revenue_usdc=rev / USDC)
        formula[wtxt] = entry
    out['loss_formula'] = formula
    # 8: injected loss (ratio of the sums of the draw means; the intervals are those of the group rows).
    injected = {}
    for st in settings:
        rows = [r for r in ainj if r['setting'] == st and int(r['reentry_delay_blocks']) == 0
                and float(r['claim_probability']) == 1.0]
        if not rows:
            continue
        w = f(rows[0]['w'])
        entry = dict(w=w)
        for g, rs in members.items():
            names = {r['address'] for r in rs}
            sel = [r for r in rows if r['address'] in names]
            rev = sum(f(r['revenue_mean']) for r in sel)
            loss = sum(f(r['principal_loss_mean']) + f(r['penalty_loss_mean']) for r in sel)
            entry[g] = dict(ratio_of_means=loss / rev if rev else None, loss_usdc=loss / USDC, revenue_usdc=rev / USDC)
        for g in ('replayed', 'A'):
            gi = [r for r in ginj if r['group'] == g and r['setting'] == st and int(r['reentry_delay_blocks']) == 0
                  and float(r['claim_probability']) == 1.0]
            if gi:
                entry[g].update(group_mean=f(gi[0]['loss_over_revenue_mean']), p2_5=f(gi[0]['loss_over_revenue_p2_5']),
                                p97_5=f(gi[0]['loss_over_revenue_p97_5']))
        injected[st] = entry
    out['injected_loss'] = injected
    # 10, 11: inspections.
    insp = {}
    for g, rs in members.items():
        drawn = sum(int(r['sample_count']) for r in rs)
        exp = sum(float(r['expected_samples']) for r in rs)
        var = sum(float(r['sample_variance']) for r in rs)
        sd = math.sqrt(var)
        insp[g] = dict(drawn=drawn, expected=exp, drawn_per_hour=drawn / hours, expected_per_hour=exp / hours,
                       z=(drawn - exp) / sd if sd else 0.0)
    out['inspections'] = insp
    out['sample_count_check_pass'] = abs(insp['replayed']['z']) <= 4
    # 12: failures in the windows against the threshold n * k.
    main = [r for r in ainj if r['setting'] == settings[0] and int(r['reentry_delay_blocks']) == 0
            and float(r['claim_probability']) == 1.0]
    by_addr = {r['address']: r for r in obs}
    worst, reach, over = None, [], 0
    for r in main:
        o = by_addr[r['address']]
        thr = int(r['scale']) * int(r['k'])
        exp = json.loads(r['window_failures_expected']) if r.get('window_failures_expected') else []
        peak = max(exp) if exp else 0.0
        if peak >= thr:
            over += 1
        if worst is None or peak / thr > worst['expected_over_threshold']:
            worst = dict(address=r['address'], expected_failures=peak, threshold=thr, expected_over_threshold=peak / thr,
                         S=int(o['sales_cap_S']) if o.get('sales_cap_S') else None)
        reach.append(f(r['kn_reach_fraction_mean']) or 0.0)
    out['window_failure_check'] = dict(
        setting=settings[0], windows=meta.get('failure_windows_complete'), addresses_expected_at_threshold=over,
        worst=worst, kn_reach_fraction_mean_over_addresses=sum(reach) / len(reach) if reach else None,
        kn_reach_fraction_max=max(reach) if reach else None, addresses_reaching=sum(1 for x in reach if x > 0))
    # 13: windows below n_min.
    below = {}
    for g, rs in members.items():
        wins = sum(int(r['judgment_windows']) for r in rs)
        wb = sum(int(r['judgment_windows_below']) for r in rs)
        ws = sum(int(r['judgment_window_settlements']) for r in rs)
        wsb = sum(int(r['judgment_window_settlements_below']) for r in rs)
        below[g] = dict(windows=wins, windows_below=wb, share_windows=wb / wins if wins else None,
                        share_settlements=wsb / ws if ws else None)
    out['n_min_windows'] = below
    # 14: rate rejections (the contrast line when the cap was fitted on the 14 days before).
    rej = {}
    for g, rs in members.items():
        att = sum(int(r['attempted_count']) for r in rs)
        cap = sum(int(r['cap_rejected_count']) for r in rs)
        rate = sum(int(r['rate_rejected_count']) for r in rs)
        ratev = sum(int(r['rate_rejected_value']) for r in rs)
        rej[g] = dict(rate_rejected_count=rate, rate_rejected_value_usdc=ratev / USDC,
                      share_of_attempted=rate / att if att else None,
                      share_of_in_range=rate / (att - cap) if att - cap else None)
    out['rate_rejection'] = rej
    return out


def address_table(run_dir, condition=1, seed=0, group='A'):
    """Column 15: for each replayed address the cap S_a, v_max, the way it was chosen and the bond."""
    d = condition_dir(Path(run_dir), condition, seed)
    meta = json.loads((d / 'condition.json').read_text())
    rows = []
    for r in read_csv(d / 'addresses_observed.csv'):
        rows.append(dict(address=r['address'], rank=r['rank'], group_A=group in json.loads(r['groups']),
                         vmax_usdc=int(r['vmax_atomic']) / USDC, sales_cap_S=r['sales_cap_S'],
                         method=r['sales_cap_method'], k=r['k_address'], bond_usdc=int(r['nB']) / USDC,
                         attempted=r['attempted_count'], cap_rejected=r['cap_rejected_count'],
                         rate_rejected=r['rate_rejected_count'], accepted_value_usdc=int(r['accepted_value']) / USDC))
    return rows


def flatten(x, prefix=''):
    """A nested dict as a flat dict with dotted keys (lists stay JSON text)."""
    out = {}
    for k, v in x.items():
        key = f'{prefix}{k}'
        if isinstance(v, dict):
            out.update(flatten(v, key + '.'))
        elif isinstance(v, (list, tuple)):
            out[key] = json.dumps(v)
        else:
            out[key] = v
    return out


def flat(r, group):
    row = {k: v for k, v in r.items() if k not in ('replayed',) and not isinstance(v, dict)}
    for g in ('replayed', group):
        for k, v in r[g].items():
            row[f'{g}.{k}'] = v
    return row


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('runs', nargs='+')
    p.add_argument('--condition', type=int, default=1)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--group', default='A')
    p.add_argument('--csv')
    p.add_argument('--columns', action='store_true', help='the columns of section 5.2 (second edition), one row per run')
    p.add_argument('--json', help='with --columns: the nested result')
    p.add_argument('--addresses', help='with --columns: column 15 as a CSV (one run only)')
    a = p.parse_args(argv)
    if a.columns:
        results = [columns(r, a.condition, a.seed, group=a.group) for r in a.runs]
        if a.json:
            Path(a.json).write_text(json.dumps(results, indent=1) + '\n')
        if a.addresses:
            rows = address_table(a.runs[0], a.condition, a.seed, a.group)
            with open(a.addresses, 'w', newline='', encoding='ascii') as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator='\n')
                w.writeheader()
                w.writerows(rows)
        flat_rows = [flatten(r) for r in results]
        cols = list(flat_rows[0])
        if a.csv:
            with open(a.csv, 'w', newline='', encoding='ascii') as fh:
                w = csv.writer(fh, lineterminator='\n')
                w.writerow(cols)
                for r in flat_rows:
                    w.writerow([r.get(c) for c in cols])
        json.dump(results, sys.stdout, indent=1)
        sys.stdout.write('\n')
        return 0
    rows = [flat(report(r, a.condition, a.seed, a.group), a.group) for r in a.runs]
    cols = list(rows[0])
    if a.csv:
        with open(a.csv, 'w', newline='', encoding='ascii') as fh:
            w = csv.writer(fh, lineterminator='\n')
            w.writerow(cols)
            for r in rows:
                w.writerow([r.get(c) for c in cols])
    json.dump(rows, sys.stdout, indent=1)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
