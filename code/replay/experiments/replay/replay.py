#!/usr/bin/env python3
"""Settlement replay: runs a recorded settlement list through the seller-side admission rules
under the conditions of conditions.json and writes one run envelope and per-condition results.

    replay.py check-input --settlements CSV --period replay_period|prior_period [--reference-dir DIR]
    replay.py [run] --settlements CSV --operating-point experiments/operating-point.json --qx 137
              --conditions all|1,2,... --out DIR [--timing-only] [--fold first|second|none]

`--timing-only` runs the full computation and writes only row counts, wall time and peak memory.
See README.md for the columns, the named options and the on-chain cross-check.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import resource
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'experiments'))

import numpy as np  # noqa: E402

import design2  # noqa: E402
import engine  # noqa: E402
import injection as inj  # noqa: E402
import inputs  # noqa: E402
import release8  # noqa: E402
import release10  # noqa: E402
from bucket import profile_admits_capacity  # noqa: E402
from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402
from controller.scenario import run_seed  # noqa: E402

FORMAT_VERSION = 1
# Named interpretation options this code implements (README.md, "Options").
OPTIONS = {
    'window_denominator': 'W344: rates (nF / nR scales, rbar_acc, H formula, formula value) divide by the list span rate_blocks (619,111 for the replay period), not the 14-day window_blocks (604,800)',
    'local_blocks': 'E0: local block = ledger block - first block of the list + epochOrigin; the bond is registered at that block with a full bucket',
    'case_opening': 'O-prompt: a sampled case opens in the first block after its beacon block',
    'judged_block': 'J-open: a sampled case counts in a judgment window at its opening block',
    'judgment_windows': 'W1: fixed windows of inconclusiveWindowBlocks from the first block; complete windows with at least one accepted settlement',
    'release': 'R-prompt: an entry is released at settled + deferBlocks',
    'failures_after_end': 'X-drop: injected failures confirmed after the last block are dropped',
    'suspension': 'S-model: suspended from a confirmed failure f to f + 1 + reentry delay (injection.seller_loss)',
    'refund_block': 'P-confirm: a claimed frozen entry is refunded at its confirmed failure block',
    'group_sums': 'G-sum: group H, rates and injection values are sums over the group per reading or draw',
    'fold_split': 'F-half: first fold is blocks [first, first + window_blocks/2), second the rest; each starts with a full bucket',
    'c2_window': 'C2-settle: R20-C2 counts each drawn failure (before X-drop) in the failure window of its case\'s settlement block and compares with s * w * accepted settlements of that window',
    'c1_bound': 'C1-tau: R20-C1 bound s * rbar_acc * w * (1 + reentry delay): the manuscript bound s * r * w * tau_re with tau the S-model suspension length of one failure (from f to f + 1 + reentry delay)',
    'replay_profile': 'P-replay: the replay profile and operating point (conditions.json replay_profile) override failureLimit and the data-API enforcementBlocks of the shared evaluation profile',
}
# Named interpretation options of the design-2 switches (recorded in the envelope of a design-2 run).
D2_OPTIONS = {
    'vmax_name': 'V1: the amount cap is v_max (the first edition called it tau); --tau is still accepted',
    'sales_cap': 'V2: --sales-cap S fixes the cap of every address on the grid {10, 30, 100, 300, 1000, 3245 * n}; auto-zero-reject '
                 'fits the least cap that rejects nothing in the replayed window, prior14 fits it on the 14 days before the window '
                 '(no fitting record: 10), cross fits each half of the window on the other half; none (registration R11, with '
                 '--release fixed10 only) admits every settlement without a bucket, as rule edition 10 candidate v0.6 has no '
                 'count limit, and auto-zero-reject is then the labelled legacy variant',
    'sales_cap_none_bond': 'V2n: under --sales-cap none the bond columns (k_address, deduction_b, bond_B) are those of the main '
                           'cap 3245 of the grid; they do not enter the release path',
    'preset': 'R11-main: --preset r11-main stands for --release fixed10 --r10-accept-over-cap --sales-cap none '
              '--r10-dispute-from anchor --freeze-scope detected-onward --r10-save-sales (switches given explicitly win)',
    'small_bucket': 'V3: q_S = max(1, round(S * 137 / 3245)) half up, r_S = floor((S - q_S) * 10^6 / Lambda) ppm per block, '
                    'Lambda = failure window + hold period',
    'unit_bond': 'V4: b = ceil((40/27) * v_max / p0), B = k(S) * b with k from the table of design2.json (edition 1: B = floor((40/27) * k * v_max / p0), one k)',
    'window_alignment': 'V5: fixed failure and judgment windows on multiples of their length in ledger blocks (edition 1: from the first block of the list)',
    'confirmed_failures': 'V6: only FINAL(FAIL) draws are confirmed failures; the model has no FINAL(INCONCLUSIVE) above the threshold, '
                          'so none is counted or deducted (D2-6 (b)), and a sampled purchase that ended delivered is one sample like any other (94a)',
    'confirm_delay': 'V8: an injected failure is confirmed at its case opening + the judgment and appeal horizon (default); --confirm-delay settlement confirms it at the settlement of the sampled entry + the longest measured path',
    'chain_time': 'V7: durations are kept in seconds and converted to blocks with the chain block time, rounded up; refill rates per block scale with the block time',
}
# The cursor release of rule edition 8 (--release cursor8); recorded in the envelope of such a run only.
R8_OPTIONS = {
    'release': 'R8-cursor: a sale is paid when the release cursor of its address passes its epoch (D2-39): the epoch is '
               'sealed (block of its case opening on the prompt path), every sampled case of the epoch is final '
               '(opening + case length), every buyer window is closed (settled + buyer window; unsigned accounts also '
               'W_e = sample value block + w_b) and every earlier epoch is passed; a condition met in block x holds '
               'from x + 1, the cursor moves keeper-delay blocks after the last one',
    'hold_cap': 'R8-cap: a settlement is rejected (the bucket is not consumed) while N_h = ceil(q_S + r_S H_N) accepted '
                'settlements of the address are not yet paid (D2-42); the replay has no refunds',
    'freeze_r8': 'R8-freeze: a confirmed failure freezes the sales settled from its sampled sale up to the failure '
                 '(narrow scope, D2-6 (a) 2); under the cursor none of them is paid before the failure',
}
R8_ROW_COLUMNS = ['hold_cap_N_h', 'hold_cap_rejected_count', 'hold_cap_rejected_value', 'hold_released_count',
                  'hold_open_count', 'hold_open_value', 'hold_mean', 'hold_value_mean', 'hold_p50', 'hold_p90',
                  'hold_p99', 'hold_max', 'hold_histogram', 'revenue_per_hold']
# The release of the rule edition 10 candidate v0.3 (--release fixed10, registration R10); in such a run only.
R10_OPTIONS = {
    'release': 'R10-fixed: a sale not accepted by its buyer is paid when the release cursor of its address passes its '
               'epoch (v0.3 R6): the sample value is on chain (M_e = A_e + tau_V + 1 + T_V, the value lands at M_e) and '
               'the epoch is anchored (A_e = last block + d_A), every sampled sale is final (an honest proof lands at '
               'the deadline M_e + T_p unless --r10-proof-delay; a missing proof fails in the release call), every '
               'purchase not accepted is past settled + T_c (unsigned ones also W_e = M_e + w_b), every earlier epoch '
               'is passed; a condition met in block x holds from x + 1, the cursor moves keeper-delay blocks later',
    'acceptance': 'R10-accept: a signed sale is accepted (a = 1) by a fixed hash of address and row with share a; it is '
                  'paid in the anchor transaction at A_e and stays in the sample; unsigned sales (share u, also a '
                  'fixed hash) are never accepted',
    'admission': 'R10-admission: no held-settlement cap (v0.3 section 4); bucket admission as edition 7 unless --sales-cap none '
                 '(R11: every settlement admitted, no count limit; v0.6 R2 (a))',
    'seller_epoch': 'R11-seller-epoch: --r10-seller-epoch-k k groups k consecutive profile epochs into one seller epoch '
                    '(v0.6 R1 (a), R6 (a)); the cursor passes the seller epoch when conditions (0) to (3) hold for each of '
                    'its profile epochs and pays every sale not accepted at that block; an accepted sale is paid at the anchor '
                    'deadline of its own profile epoch; k = 1 is the R10 path',
    'dispute_from': 'R11-dispute: --r10-dispute-from anchor starts every dispute window at the anchor deadline (A_e + T_c, v0.6 '
                    'R5 (c)); settlement (default, R10) counts T_c from the settlement of the purchase',
    'held_average': 'R11-held: H_cont_average is the continuous time average of the held money over every block of the window '
                    '[first block, last block], H_cont_average_from_hold over [first block + hold, last block] (the span of the '
                    'hourly readings), both with the exact numerator H_cont_sum_blocks; a sale not released by the last block '
                    'is held to it; has_revenue marks an address with accepted value > 0',
    'sales_file': 'R11-sales: --r10-save-sales writes sales.npz per condition (address_index, block, value, release, epoch, '
                  'row, sampled, accepted, signed of every accepted sale, by address in the order of sales_addresses.json)',
    'over_cap': 'R10-over-cap: with --r10-accept-over-cap a sale above V is accepted and sampled with probability 1 '
                '(tiers 0 and 1, v0.3 R2 (a)); otherwise it is rejected by the value cap as in R8',
}
R10_ROW_COLUMNS = ['hold_released_count', 'hold_open_count', 'hold_open_value', 'hold_mean', 'hold_value_mean',
                   'hold_p50', 'hold_p90', 'hold_p99', 'hold_max', 'hold_histogram', 'revenue_per_hold',
                   'buyer_accepted_count', 'buyer_accepted_value', 'unsigned_count', 'unsigned_value',
                   'sampled_accepted_count', 'over_cap_accepted_count', 'over_cap_accepted_value',
                   'admission', 'H_cont_sum_blocks', 'H_cont_average', 'H_cont_average_from_hold', 'has_revenue']
R10_SWITCHES = ('r10_anchor_delay', 'r10_vrf_response', 'r10_vrf_slack', 'r10_proof_window', 'r10_dispute_window',
                'r10_bind_window', 'r10_proof_delay', 'r10_keeper_delay', 'r10_accept_ppm', 'r10_unsigned_ppm',
                'r10_seller_epoch_k', 'r10_dispute_from')
SALES_FIELDS = ('block', 'value', 'release', 'epoch', 'row', 'sampled', 'accepted', 'signed')
# Under the cursor no frozen sale is paid before its failure, which is the narrow scope with an unbounded hold.
R8_FREEZE_HOLD = 2 ** 62
TABLE1_GROUPS = ('rank1', 'rank2', 'ranks3_44', 'B', 'C_p90', 'C_p75', 'C_p50', 'three', 'A', 'replayed')


def git_state():
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        return dict(revision=None, dirty=True)
    return dict(revision=head, dirty=dirty)


def peak_memory_mib():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def dump(obj):
    return json.dumps(obj, sort_keys=True, indent=1, default=_json_default) + '\n'


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Fraction):
        return str(o)
    raise TypeError(type(o))


def write_csv(path, rows, columns):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(columns)
    for r in rows:
        w.writerow([_cell(r.get(c)) for c in columns])
    Path(path).write_text(buf.getvalue(), encoding='ascii')


def _cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (list, tuple, np.ndarray)):
        # Numbers inside a list cell stay JSON numbers (rules.py reads them with json.loads).
        return json.dumps([_json_num(x) for x in v])
    return _cell_num(v)


def _json_num(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


def _cell_num(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return repr(float(v))
    return v


# ---------------------------------------------------------------- setup

def rate_blocks(cond):
    """Denominator of every rate (option W344, design 9.5)."""
    return cond.get('rate_blocks', cond['window_blocks'])


def default_operating_point(cond):
    spec = cond.get('replay_profile')
    return str(ROOT / spec['operating_point']) if spec else str(ROOT / 'experiments' / 'operating-point.json')


def check_expected_scales(cond, top400, profiles, rules=('nF', 'nR')):
    """The scales other than 1 that the design fixes before the run (design 9.5); returns the
    differences (empty when they agree). A design-2 run checks only the rules it does not replace
    (nR); its nF scales come from the envelope rule and are not the registered design-1 values."""
    spec = cond.get('expected_scales')
    if not spec:
        return []
    name = spec['profile']
    if name not in profiles:
        return []
    p = profiles[name]['parameters']
    errors = []
    for rule in rules:
        got = {a: n for a, n in scales(top400, rule, p, rate_blocks(cond)).items() if n != 1}
        want = {inputs.normalize(a): n for a, n in spec[rule].items()}
        if got != want:
            errors.append(f'{rule} scales {got} differ from the registered {want}')
    return errors


def profile_overrides(profile_file):
    """The replay profile's base file and per-profile overrides, as recorded in the profile file."""
    doc = json.loads(Path(profile_file).read_text(encoding='utf-8'))
    out = dict(derived_from=doc.get('derivedFrom'),
               overrides={pr['name']: pr.get('replayOverrides', {}) for pr in doc['profiles']},
               parameter_hash={pr['name']: pr['parameterHash'] for pr in doc['profiles']})
    base = doc.get('derivedFrom')
    if base:
        path = ROOT / base['file']
        out['base_current_sha256'] = inputs.sha256_file(path) if path.exists() else None
        out['base_unchanged'] = out['base_current_sha256'] == base['sha256']
    return out


def resolve(args, cond, ids=None, d2=None):
    """Operating point, profile file, profiles and consistency errors. With a design-2 setting the
    profile is overlaid (design2.Design2.apply_profile) and checked in the design-2 mode."""
    op = opt.load(args.operating_point)
    profile_file = ROOT / op['profile_file']
    profiles, errors = {}, []
    for c in cond['conditions']:
        if ids is not None and c['id'] not in ids:
            continue
        name = c['profile']
        if name not in profiles:
            profiles[name] = prof.load_profile(profile_file, name)
            if d2 is None:
                errors += opt.check(op, profiles[name])
            else:
                if name != d2.config['profile']:
                    raise SystemExit(f'design 2 is defined for profile {d2.config["profile"]}, not {name}')
                profiles[name] = d2.apply_profile(profiles[name])
                op = d2.apply_op(op, name, profiles[name], prof.case_horizon(profiles[name]))
                errors += design2.check(op, profiles[name], d2)
    return op, profile_file, profiles, errors


def scales(top400, rule, p, window):
    out = {}
    for a, count in top400:
        if rule == 'n1':
            out[a] = 1
        elif rule == 'nF':
            out[a] = inj.scale_nF(count, window, Fraction(p['refillPpmPerBlock'], engine.PPM))
        elif rule == 'nR':
            out[a] = inj.scale_nR(count, window, Fraction(p['maxRatePpmPerBlock'], engine.PPM))
        else:
            raise ValueError(f'unknown scale rule {rule}')
    return out


def settings_for(op, profile_name, cond, alpha_upper=None, extra=(), only=None):
    """Injection settings with w = 3 * w1^2, w1 = c(1 - h) + h * alpha. `extra` appends settings given by
    their w alone ({"name": ..., "w": ...}, design 2: the worst-case w of the k table); `only` keeps the
    settings of those names, in the order they are given."""
    base = op['profiles'][profile_name]
    out = []
    specs = list(cond['injection']['settings'])
    if alpha_upper is not None:
        specs.append(dict(cond['injection']['optional_setting'], alpha=alpha_upper))
    for s in specs:
        h = base['h']['value'] if s['h'] == 'operating point' else s['h']
        c = base['c']['value'] if s['c'] == 'operating point' else s['c']
        alpha = base['alpha']['value'] if s['alpha'] in ('operating point', '--alpha-upper') else s['alpha']
        w1 = c * (1 - h) + h * alpha
        out.append(dict(name=s['name'], h=h, c=c, alpha=alpha, w1=w1, w=3 * w1 * w1))
    for s in extra:
        out.append(dict(name=s['name'], h=None, c=None, alpha=None, w1=None, w=s['w']))
    if only is not None:
        by_name = {s['name']: s for s in out}
        unknown = [n for n in only if n not in by_name]
        if unknown:
            raise ValueError(f'unknown injection settings {unknown}; available: {sorted(by_name)}')
        out = [by_name[n] for n in only]
    return out


# ---------------------------------------------------------------- injection per address

def summarise(values):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return dict(mean=None, p2_5=None, p97_5=None)
    return dict(mean=sum(xs) / len(xs), p2_5=xs[int(0.025 * (len(xs) - 1))], p97_5=xs[int(0.975 * (len(xs) - 1))])


def inject_address(seller, arr, *, seed, settings, draws, p, scale, k, reentries, claims, start, end,
                   fw_edges, rate_blocks, accum, groups_of, share=None, bond=None, confirm_from_settlement=None,
                   freeze_scope='full', freeze_hold=None):
    """Runs every draw for one address and returns its summary rows; adds each draw to the
    group accumulators. `share` (the deduction of one confirmed failure) and `bond` (the unit bond B
    with B / k = share) default to the profile's sellerPenalty and sellerPenalty // k; design 2 passes the
    values of the address's sales cap. `confirm_from_settlement` (design 2, sensitivity of the confirmation
    delay) confirms a failure that many blocks after the settlement of the sampled entry instead of
    `confirm_delay(p)` blocks after the case opening. `freeze_scope` ('full', default; 'detected-onward')
    is passed to engine.evaluate_failures. `freeze_hold` (the cursor release: R8_FREEZE_HOLD) replaces the hold
    with which a frozen sale is told from a paid one."""
    hold = p['deferBlocks']
    loss_hold = hold if freeze_hold is None else freeze_hold
    delay = confirm_delay(p)
    if share is None:
        share = int(p['sellerPenalty']) // k
    if bond is None:
        bond = int(p['sellerPenalty'])
    s = p['samplePpm'] / engine.PPM
    replay_blocks = end - start + 1
    blocks, values, cases = arr['blocks'], arr['values'], arr['cases']
    s_prob = arr.get('s_prob')      # design 2: sampling probability of each accepted settlement
    if s_prob is not None:
        s = float(s_prob.mean()) if len(s_prob) else 0.0   # s_bar of the accepted settlements
    case_settled = arr.get('case_settled')
    if confirm_from_settlement is not None:
        cases, delay = case_settled, confirm_from_settlement
    if freeze_scope not in engine.FREEZE_SCOPES:
        raise ValueError(f'unknown freeze scope {freeze_scope}')
    if freeze_scope != 'full' and (confirm_from_settlement is not None or case_settled is None
                                   or (len(cases) > 1 and bool((np.diff(cases) < 0).any()))):
        # f and the settlement blocks of the sampled sales are aligned only for sorted case openings.
        raise ValueError(f"freeze scope {freeze_scope} needs case-opening confirmation (not --confirm-delay settlement)")
    fw_settled = engine.bin_uniform(blocks, fw_edges)
    fw_samples = engine.bin_uniform(case_settled, fw_edges) if case_settled is not None else None
    fw_revenue_all = engine.bin_uniform(blocks, fw_edges, values)
    rows = []
    for st in settings:
        per = {(t, ph): [] for t in reentries for ph in claims}
        baseline = None
        by_settlement = []
        for d in range(draws):
            # The failures of a draw are shared by every reentry delay and claim probability.
            rng = engine.draw_rng(seed, st['name'], seller, d) if len(cases) else None
            f, f_settled = engine.draw_failures_detail(cases, case_settled, st['w'], delay, end, rng)
            # R20-C2 (design 9.6): every drawn failure in the failure window of its case's settlement.
            by_settlement.append(engine.bin_uniform(f_settled, fw_edges))
            if len(f) == 0:
                if baseline is None:
                    r0 = engine.no_failure_result(blocks, values, fw_edges)
                    baseline = {(t, ph): r0 for t in reentries for ph in claims}
                res = baseline
            else:
                res = {}
                for t in reentries:
                    out = engine.evaluate_failures(blocks, values, f, hold=loss_hold, reentry=t, claim_probs=claims,
                                                   share=share, rng=rng, start=start, end=end, fw_edges=fw_edges,
                                                   claim_window=p['claimWindowBlocks'],
                                                   fw_revenue_all=fw_revenue_all, scope=freeze_scope,
                                                   f_settled=f_settled)
                    for ph, r in zip(claims, out):
                        res[(t, ph)] = r
            for key, r in res.items():
                per[key].append(r)
        for (t, ph), rs in per.items():
            for g in groups_of:
                accum.add_draws((st['name'], t, ph, g), rs, len(fw_edges) - 1, scale * k)
            n_acc = [r['revenue'] for r in rs]
            ratio = [(r['principal'] + r['penalty']) / r['revenue'] if r['revenue'] else None for r in rs]
            # Formula value on the replay's accepted settlements over the whole window.
            revenue_mean = sum(n_acc) / len(n_acc)
            rate = len(blocks) / rate_blocks
            vbar = int(values.sum()) / len(blocks) if len(blocks) else None
            formula = inj.formula_value(s, st['w'], rate, hold, bond, k, vbar) if vbar else None
            lr = summarise(ratio)
            nfw = len(fw_edges) - 1
            row = dict(address=seller, setting=st['name'], h=st['h'], c=st['c'], alpha=st['alpha'], w=st['w'], k=k,
                       scale=scale, reentry_delay_blocks=t, claim_probability=ph, draws=len(rs),
                       onchain_crosscheck='not run')
            for name, vals in (('freeze_fraction', [r['suspended_blocks'] / replay_blocks for r in rs]),
                               ('claim_open_fraction', [r['claim_open_blocks'] / replay_blocks for r in rs]),
                               ('failures', [r['failures'] for r in rs]),
                               ('principal_loss', [r['principal'] for r in rs]),
                               ('penalty_loss', [r['penalty'] for r in rs]),
                               ('refunded', [r['refunded'] for r in rs]),
                               ('forfeited', [r['forfeited'] for r in rs]),
                               ('revenue', n_acc),
                               ('lost_sales', [r['lost_sales'] for r in rs]),
                               ('refund_time_median', [r['refund_time_median'] for r in rs])):
                sm = summarise(vals)
                row.update({f'{name}_mean': sm['mean'], f'{name}_p2_5': sm['p2_5'], f'{name}_p97_5': sm['p97_5']})
            ff = np.array([r['suspended_blocks'] / replay_blocks for r in rs], dtype=float)
            row['freeze_fraction_sd'] = float(ff.std(ddof=1)) if len(rs) > 1 else 0.0
            row['rate_acc_per_block'] = rate
            if s_prob is not None:
                row['s_rate_per_block'] = float(s_prob.sum()) / rate_blocks
                row['s_bar'] = s
            row['sample_count'] = int(len(cases))
            row.update({'loss_over_revenue_mean': lr['mean'], 'loss_over_revenue_p2_5': lr['p2_5'],
                        'loss_over_revenue_p97_5': lr['p97_5']})
            maxes = [r['refund_time_max'] for r in rs if r['refund_time_max'] is not None]
            row['refund_time_max'] = max(maxes) if maxes else None
            row['formula_value'] = formula
            row['ratio_to_formula'] = lr['mean'] / formula if (formula and lr['mean'] is not None) else None
            row['principal_over_revenue_max'] = max(((r['principal'] / r['revenue']) if r['revenue'] else 0.0)
                                                    for r in rs)
            row['failure_windows'] = nfw
            if nfw:
                fwf = np.array([r['fw_failures'] for r in rs], dtype=float)
                fwl = np.array([r['fw_loss'] for r in rs], dtype=float)
                fwr = np.array([r['fw_revenue'] for r in rs], dtype=float)
                row['window_failures_mean'] = fwf.mean(axis=0)
                row['window_failures_p2_5'] = np.sort(fwf, axis=0)[int(0.025 * (len(rs) - 1))]
                row['window_failures_p97_5'] = np.sort(fwf, axis=0)[int(0.975 * (len(rs) - 1))]
                row['window_failures_sd'] = fwf.std(axis=0, ddof=1) if len(rs) > 1 else np.zeros(nfw)
                row['window_failures_expected'] = (s * st['w'] * fw_settled if s_prob is None
                                                   else st['w'] * engine.bin_uniform(blocks, fw_edges, s_prob))
                fbs = np.array(by_settlement, dtype=float)
                row['window_failures_by_settlement_mean'] = fbs.mean(axis=0)
                row['window_failures_by_settlement_sd'] = fbs.std(axis=0, ddof=1) if len(rs) > 1 else np.zeros(nfw)
                if fw_samples is not None:
                    row['window_samples_by_settlement'] = fw_samples
                row['window_loss_mean'] = fwl.mean(axis=0)
                row['window_revenue_mean'] = fwr.mean(axis=0)
                row['window_loss_over_revenue_mean'] = np.where(fwr.mean(axis=0) > 0,
                                                                fwl.mean(axis=0) / np.maximum(fwr.mean(axis=0), 1), 0)
                row['kn_reach_fraction_mean'] = float((fwf >= scale * k).mean())
            rows.append(row)
    return rows


def confirm_delay(p):
    """judgmentHorizon + appealHorizon + 1 (profile-v1 section 3)."""
    d = p['deadlineConfig']
    m = p['maxAssignments']
    judgment = m * (d['judgeBlocks'] + 1) + d['evidenceBlocks']
    appeal = d['appealBlocks'] + 2 * (1 + m * (d['judgeBlocks'] + 1))
    return judgment + appeal + 1


class GroupAccumulator:
    """Per-draw sums over the addresses of a group."""

    FIELDS = ('failures', 'principal', 'penalty', 'refunded', 'forfeited', 'revenue', 'lost_sales',
              'suspended_blocks', 'claim_open_blocks')

    def __init__(self):
        self.data = {}

    def add_draws(self, key, rs, nfw, kn):
        """Adds one address's results, one per draw, to the group sums of every draw."""
        draws = len(rs)
        e = self.data.get(key)
        if e is None:
            e = self.data[key] = {f: np.zeros(draws) for f in self.FIELDS}
            e['weighted_suspended'] = np.zeros(draws)
            e['weight'] = np.zeros(draws)
            e['fw_failures'] = np.zeros((draws, nfw))
            e['fw_loss'] = np.zeros((draws, nfw))
            e['fw_revenue'] = np.zeros((draws, nfw))
            e['kn_windows'] = np.zeros(draws)
            e['windows'] = np.zeros(draws)
        cols = {f: np.fromiter((r[f] for r in rs), dtype=float, count=draws) for f in self.FIELDS}
        for f in self.FIELDS:
            e[f] += cols[f]
        e['weighted_suspended'] += cols['suspended_blocks'] * cols['revenue']
        e['weight'] += cols['revenue']
        if nfw:
            fwf = np.array([r['fw_failures'] for r in rs], dtype=float)
            e['fw_failures'] += fwf
            e['fw_loss'] += np.array([r['fw_loss'] for r in rs], dtype=float)
            e['fw_revenue'] += np.array([r['fw_revenue'] for r in rs], dtype=float)
            e['kn_windows'] += (fwf >= kn).sum(axis=1)
            e['windows'] += nfw


def group_injection_rows(accum, replay_blocks):
    rows = []
    for (setting, t, ph, g), e in sorted(accum.data.items()):
        loss = e['principal'] + e['penalty']
        ratio = np.where(e['revenue'] > 0, loss / np.maximum(e['revenue'], 1), 0.0)
        row = dict(group=g, setting=setting, reentry_delay_blocks=t, claim_probability=ph)
        for name, vals in (('failures', e['failures']), ('principal_loss', e['principal']),
                           ('penalty_loss', e['penalty']), ('refunded', e['refunded']),
                           ('forfeited', e['forfeited']), ('revenue', e['revenue']),
                           ('lost_sales', e['lost_sales']), ('loss_over_revenue', ratio),
                           ('freeze_fraction', np.where(e['weight'] > 0, e['weighted_suspended']
                                                        / np.maximum(e['weight'], 1) / replay_blocks, 0.0))):
            sm = summarise(vals.tolist())
            row.update({f'{name}_mean': sm['mean'], f'{name}_p2_5': sm['p2_5'], f'{name}_p97_5': sm['p97_5']})
        if e['fw_failures'].shape[1]:
            row['window_failures_mean'] = e['fw_failures'].mean(axis=0)
            row['window_loss_mean'] = e['fw_loss'].mean(axis=0)
            row['window_revenue_mean'] = e['fw_revenue'].mean(axis=0)
            row['kn_reach_fraction_mean'] = float((e['kn_windows'] / np.maximum(e['windows'], 1)).mean())
        row['seller_fraud'] = 'not applicable (no dishonest seller)'
        row['onchain_crosscheck'] = 'not run'
        rows.append(row)
    return rows


# ---------------------------------------------------------------- observed groups

def group_observed_rows(per_address, h_series, groups, data, n_points):
    rows = []
    for g in TABLE1_GROUPS:
        members = [a for a in groups[g] if a in per_address]
        if not members:
            continue
        rs = [per_address[a] for a in members]
        att = sum(r['attempted_count'] for r in rs)
        rej = sum(r['rejected_count'] for r in rs)
        acc_value = sum(r['accepted_value'] for r in rs)
        h = np.zeros(n_points)
        for a in members:
            if h_series.get(a) is not None and len(h_series[a]):
                h += h_series[a]
        wins = sum(r['judgment_windows'] for r in rs)
        wins_below = sum(r['judgment_windows_below'] for r in rs)
        ws = sum(r['judgment_window_settlements'] for r in rs)
        ws_below = sum(r['judgment_window_settlements_below'] for r in rs)
        bond = sum(r['nB'] for r in rs)
        hf = sum(r['H_formula'] for r in rs)
        row = dict(group=g, addresses=len(members),
                   share_count=att / data.total_rows, share_value=sum(r['attempted_value'] for r in rs) / data.total_value,
                   rate_acc_per_hour=sum(r['rate_acc_per_hour'] for r in rs),
                   peak_hour_accepted_max=max(r['peak_hour_accepted'] for r in rs),
                   scales=sorted({r['scale'] for r in rs}),
                   H_formula=hf, H_time_average=float(h.mean()) if n_points else None,
                   H_max=float(h.max()) if n_points else None, nB=bond,
                   nB_plus_H_formula=bond + hf,
                   nB_plus_H_time_average=bond + float(h.mean()) if n_points else None,
                   nB_plus_H_max=bond + float(h.max()) if n_points else None,
                   attempted_count=att, rejected_count=rej, rejection_rate=rej / att if att else None,
                   accepted_value=acc_value,
                   sample_count=sum(r['sample_count'] for r in rs),
                   epochs_with_settlement=sum(r['epochs_with_settlement'] for r in rs),
                   epochs_sealed=sum(r['epochs_sealed'] for r in rs),
                   judgment_windows=wins, judgment_windows_below_share=wins_below / wins if wins else None,
                   judgment_window_settlements_below_share=ws_below / ws if ws else None)
        if 'cap_rejected_count' in rs[0]:
            row.update({f: sum(r[f] for r in rs) for f in D2_GROUP_SUMS})
            row['cap_pass_share_count'] = 1 - row['cap_rejected_count'] / att if att else None
            row['cap_pass_share_value'] = (1 - row['cap_rejected_value'] / sum(r['attempted_value'] for r in rs)
                                           if sum(r['attempted_value'] for r in rs) else None)
            row['bond_sum'] = bond
        rows.append(row)
    return rows


D2_ROW_COLUMNS = ['cap_rejected_count', 'cap_rejected_value', 'rate_rejected_count', 'rate_rejected_value',
                  'expected_samples', 'sample_variance', 's_bar', 'scale_segments', 'bond_B', 'deterrence_min',
                  'vmax_atomic', 'sales_cap_S', 'sales_cap_method', 'sales_cap_parts', 'sales_cap_capacity',
                  'sales_cap_refill_ppm', 'k_address', 'deduction_b']
D2_GROUP_SUMS = ['cap_rejected_count', 'cap_rejected_value', 'rate_rejected_count', 'rate_rejected_value',
                 'expected_samples', 'deterrence_min']
D2_GROUP_COLUMNS = D2_GROUP_SUMS + ['cap_pass_share_count', 'cap_pass_share_value', 'bond_sum']
D2_INJ_COLUMNS = ['s_rate_per_block', 's_bar']

OBS_COLUMNS = ['address', 'rank', 'groups', 'scale', 'q', 'bucket_capacity', 'under_assigned', 'attempted_count',
               'attempted_value', 'accepted_count', 'accepted_value', 'rejected_count', 'rejection_rate',
               'rate_acc_per_hour', 'peak_hour_accepted', 'mean_value', 'H_formula', 'H_time_average', 'H_max',
               'H_list_time_average', 'H_ledger_list_max_abs_diff', 'nB', 'nB_plus_H_formula',
               'nB_plus_H_time_average', 'nB_plus_H_max', 'sample_count', 'epochs_with_settlement', 'epochs_sealed',
               'judgment_windows', 'judgment_windows_below', 'judgment_window_settlements',
               'judgment_window_settlements_below']
FOLD_COLUMNS = ['address', 'rank', 'groups', 'scale', 'q', 'bucket_capacity', 'under_assigned', 'attempted_count',
                'attempted_value', 'accepted_count', 'accepted_value', 'rejected_count', 'rejection_rate']
GROUP_OBS_COLUMNS = ['group', 'addresses', 'share_count', 'share_value', 'rate_acc_per_hour', 'peak_hour_accepted_max',
                     'scales', 'H_formula', 'H_time_average', 'H_max', 'nB', 'nB_plus_H_formula',
                     'nB_plus_H_time_average', 'nB_plus_H_max', 'attempted_count', 'rejected_count', 'rejection_rate',
                     'accepted_value', 'sample_count', 'epochs_with_settlement', 'epochs_sealed', 'judgment_windows',
                     'judgment_windows_below_share', 'judgment_window_settlements_below_share']
_INJ_STATS = ['freeze_fraction', 'claim_open_fraction', 'failures', 'principal_loss', 'penalty_loss', 'refunded',
              'forfeited', 'revenue', 'loss_over_revenue', 'lost_sales', 'refund_time_median']
INJ_COLUMNS = (['address', 'setting', 'h', 'c', 'alpha', 'w', 'k', 'scale', 'reentry_delay_blocks',
                'claim_probability', 'draws']
               + [f'{s}_{q}' for s in _INJ_STATS for q in ('mean', 'p2_5', 'p97_5')]
               + ['refund_time_max', 'formula_value', 'ratio_to_formula', 'principal_over_revenue_max',
                  'failure_windows', 'window_failures_mean', 'window_failures_sd', 'window_failures_p2_5',
                  'window_failures_p97_5',
                  'window_failures_expected', 'window_failures_by_settlement_mean',
                  'window_failures_by_settlement_sd', 'window_samples_by_settlement', 'window_loss_mean',
                  'window_revenue_mean', 'window_loss_over_revenue_mean', 'kn_reach_fraction_mean',
                  'freeze_fraction_sd', 'rate_acc_per_block', 'sample_count', 'onchain_crosscheck'])
_GINJ_STATS = ['failures', 'principal_loss', 'penalty_loss', 'refunded', 'forfeited', 'revenue', 'lost_sales',
               'loss_over_revenue', 'freeze_fraction']
GROUP_INJ_COLUMNS = (['group', 'setting', 'reentry_delay_blocks', 'claim_probability']
                     + [f'{s}_{q}' for s in _GINJ_STATS for q in ('mean', 'p2_5', 'p97_5')]
                     + ['window_failures_mean', 'window_loss_mean', 'window_revenue_mean', 'kn_reach_fraction_mean',
                        'seller_fraud', 'onchain_crosscheck'])


# ---------------------------------------------------------------- one condition and seed

def run_condition(c, rep, *, data, cond, profiles, top400, groups, rank, q_values, op, args, settings_cache,
                  out_dir, observed_only_rejections, k_of, d2=None, plan=None):
    p = profiles[c['profile']]['parameters']
    q = q_values[c['q']]
    seed = run_seed(cond['base_seed'], cond['seed_scope'], c['id'], rep)
    window = rate_blocks(cond)
    segments, rule_name, caps = {}, c['scale_rule'], {}
    if plan is not None and c['scale_rule'] == 'nF':
        # Design 2 replaces the mean-rate rule nF by the envelope rule nE (D2-7) or, in the second
        # edition, by a sales cap from the grid (D2-7 (b)).
        sc = {}
        for a in groups['replayed']:
            res, segments[a] = plan.scale(a, data.per[a], q, p['refillPpmPerBlock'])
            if getattr(plan, 'kind', None) == 'cap':
                caps[a], sc[a] = res, res['scale']
            else:
                sc[a] = res
        rule_name = plan.name
    else:
        sc = scales(top400, c['scale_rule'], p, window)
    replayed = groups['replayed']
    start, end = data.first_block, data.last_block
    local_origin = p['epochOrigin']
    hold = p['deferBlocks']
    k = k_of[c['profile']]
    release = build_release(args)
    per_address, arrays, h_series = {}, {}, {}
    save_sales = isinstance(release, release10.Release10) and bool(getattr(args, 'r10_save_sales', False)) \
        and not observed_only_rejections
    sales_parts = []
    r_fill = Fraction(p['refillPpmPerBlock'], engine.PPM)
    for a in replayed:
        count = dict(top400).get(a)
        # Scale of an address outside the top 400 (group C): the same rule on its reference count.
        if a not in sc:
            ref = groups['_counts'][a]
            sc[a] = scales([(a, ref)], c['scale_rule'], p, window)[a]
        if d2 is not None and a not in caps:
            # A multiplier of the first-edition rules: the bucket is the run's own (q, profile refill) times n.
            caps[a] = dict(d2.multiplier_spec(sc[a]), capacity=q, refill_ppm=p['refillPpmPerBlock'])
        row, arr = engine.replay_address(a, data.per[a], seed=seed, p=p, capacity=q if d2 is None else caps[a]['capacity'],
                                         scale=sc[a],
                                         origin_ledger=start, local_origin=local_origin, end_ledger=end,
                                         block_size=data.block_size, window_blocks=window,
                                         first_seconds=data.first_seconds, observed=not observed_only_rejections,
                                         **({} if d2 is None else dict(cap=d2.vmax, sample_tau=d2.vmax,
                                                                       rounding=d2.rounding,
                                                                       segments=segments.get(a),
                                                                       refill_ppm=caps[a]['refill_ppm'],
                                                                       align=d2.align, hour_blocks=d2.hour_blocks,
                                                                       block_seconds=d2.block_seconds,
                                                                       unlimited=caps[a].get('unlimited', False))),
                                         **({} if release is None else dict(release=release)))
        if save_sales:
            sales_parts.append((len(sales_parts), arr))
        ref_count = count if count is not None else groups['_counts'][a]
        row['rank'] = rank.get(a)
        row['groups'] = sorted(g for g in groups if not g.startswith('_') and a in groups['_sets'][g])
        a_fill = r_fill if d2 is None else Fraction(caps[a]['refill_ppm'], engine.PPM)
        row['under_assigned'] = inj.under_assigned(ref_count, window, sc[a], a_fill)
        row['nB'] = sc[a] * int(p['sellerPenalty']) if d2 is None else caps[a]['bond']
        if d2 is not None:
            cs = caps[a]
            row['bond_B'] = cs['bond_unit']
            row['deterrence_min'] = sc[a] * cs['k'] * d2.vmax * engine.PPM / d2.p0_ppm
            row.update(vmax_atomic=d2.vmax, sales_cap_S=cs['S'], sales_cap_method=cs['method'],
                       sales_cap_parts=cs.get('S_parts'), sales_cap_capacity=cs['capacity'],
                       sales_cap_refill_ppm=cs['refill_ppm'], k_address=cs['k'], deduction_b=cs['b'])
        if not observed_only_rejections:
            for key in ('formula', 'time_average', 'max'):
                v = row[f'H_{key}']
                row[f'nB_plus_H_{key}'] = None if v is None else row['nB'] + v
            h_series[a] = arr['h']
            arrays[a] = arr
        per_address[a] = row
    result = dict(condition=c['id'], repetition=rep, seed=seed, profile=c['profile'], scale_rule=rule_name,
                  q_name=c['q'], q=q, k=k, attempted=sum(r['attempted_count'] for r in per_address.values()))
    if observed_only_rejections:
        rows = [per_address[a] for a in replayed]
        if out_dir:
            write_csv(out_dir / 'addresses_observed.csv', rows, FOLD_COLUMNS)
        return result
    hour_blocks = engine.HOUR_BLOCKS if d2 is None else d2.hour_blocks
    points = list(range(start + hold, end + 1, hour_blocks))
    obs_groups = group_observed_rows(per_address, h_series, groups, data, len(points))
    # Injection.
    fw = p['failureWindowBlocks']
    fw_edges = design2.window_edges(start + hold, end, fw, 'first-block' if d2 is None else d2.align)
    n_fw = len(fw_edges) - 1
    settings = settings_cache[c['profile']]
    accum = GroupAccumulator()
    inj_rows = []
    obs_columns, group_obs_columns, inj_columns = OBS_COLUMNS, GROUP_OBS_COLUMNS, INJ_COLUMNS
    if d2 is not None:
        obs_columns = OBS_COLUMNS + D2_ROW_COLUMNS
        group_obs_columns = GROUP_OBS_COLUMNS + D2_GROUP_COLUMNS
        inj_columns = INJ_COLUMNS + D2_INJ_COLUMNS
    if isinstance(release, release10.Release10):
        obs_columns = obs_columns + R10_ROW_COLUMNS
    elif release is not None:
        obs_columns = obs_columns + R8_ROW_COLUMNS
    groups_of_addr = {a: [g for g in TABLE1_GROUPS if a in groups['_sets'][g]] for a in replayed}
    for a in replayed:
        own = {} if d2 is None else dict(share=caps[a]['b'], bond=caps[a]['bond_unit'],
                                         confirm_from_settlement=d2.l_actual if d2.confirm_delay == 'settlement' else None)
        inj_rows += inject_address(a, arrays[a], seed=seed, settings=settings, draws=args.draws, p=p, scale=sc[a],
                                   k=k if d2 is None else caps[a]['k'],
                                   reentries=cond['injection']['reentry_delay_blocks'],
                                   claims=cond['injection']['claim_probability'], start=start, end=end,
                                   fw_edges=fw_edges, rate_blocks=window, accum=accum,
                                   groups_of=groups_of_addr[a], freeze_scope=getattr(args, 'freeze_scope', 'full'),
                                   **own, **({} if release is None else dict(freeze_hold=R8_FREEZE_HOLD)))
    ginj = group_injection_rows(accum, end - start + 1)
    result['accepted'] = sum(r['accepted_count'] for r in per_address.values())
    result['injection_rows'] = len(inj_rows)
    sales_file = None
    if out_dir and save_sales:
        sales_file = write_sales(out_dir, replayed, sales_parts)
    if out_dir:
        write_csv(out_dir / 'addresses_observed.csv', [per_address[a] for a in replayed], obs_columns)
        write_csv(out_dir / 'groups_observed.csv', obs_groups, group_obs_columns)
        write_csv(out_dir / 'addresses_injection.csv', inj_rows, inj_columns)
        write_csv(out_dir / 'groups_injection.csv', ginj, GROUP_INJ_COLUMNS)
        extra = dict(sample_rate=p['samplePpm'] / engine.PPM)
        if d2 is not None:
            # Per-row sampling probabilities (D2-2): no single rate; rules.py reads the per-row columns.
            extra = dict(sample_rate=None, sample_rule=dict(kind='value-proportional', tau_atomic=d2.tau,
                                                            rounding=d2.rounding, p0_ppm=d2.p0_ppm),
                         design2=d2.describe(), list_rows=data.total_rows, list_value=data.total_value,
                         list_cap_pass_rows=data.cap_rows, list_cap_pass_value=data.cap_value,
                         scales_not_one={a: sc[a] for a in replayed if sc[a] != 1},
                         sales_caps={a: dict(S=caps[a]['S'], method=caps[a]['method']) for a in replayed},
                         failure_window_alignment=d2.align, judgment_window_alignment=d2.align,
                         failure_windows_complete=int(n_fw), block_seconds=design2.decimal_text(d2.block_seconds), chain=d2.chain)
            if isinstance(release, release10.Release10):
                extra['release10'] = release.describe()
                extra['addresses_with_revenue'] = sum(1 for a in replayed if per_address[a].get('has_revenue'))
                extra['admission'] = sorted({per_address[a].get('admission') for a in replayed})
                extra['sales_file'] = sales_file
                if getattr(args, 'preset', None):
                    extra['preset'] = args.preset
            elif release is not None:
                extra['release8'] = release.describe()
        (out_dir / 'condition.json').write_text(dump(dict(
            result, failure_windows=int(n_fw), failure_window_edges=fw_edges.tolist(),
            hour_readings=len(points),
            confirm_delay_blocks=confirm_delay(p) if d2 is None or d2.confirm_delay == 'case' else d2.l_actual,
            hold_blocks=hold,
            settings=settings, share_B_over_k=int(p['sellerPenalty']) // k, sellerPenalty=int(p['sellerPenalty']),
            replay_blocks=end - start + 1, rate_blocks=window, **extra)))
    return result


def write_sales(out_dir, replayed, parts):
    """sales.npz (registration R11): every accepted sale of the condition with its payment block, by address in the
    order of `replayed` (sales_addresses.json), each address's sales by settlement block. Returns the file name."""
    cols = {f: [] for f in SALES_FIELDS}
    idx = []
    for i, arr in parts:
        n = len(arr['blocks'])
        idx.append(np.full(n, i, dtype=np.int32))
        cols['block'].append(arr['blocks']); cols['value'].append(arr['values']); cols['release'].append(arr['release'])
        cols['epoch'].append(arr['epochs']); cols['row'].append(arr['rows']); cols['sampled'].append(arr['sampled'])
        cols['accepted'].append(arr['accepted']); cols['signed'].append(arr['signed'])
    out = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in cols.items()}
    out['address_index'] = np.concatenate(idx) if idx else np.zeros(0, dtype=np.int32)
    np.savez_compressed(out_dir / 'sales.npz', **out)
    (out_dir / 'sales_addresses.json').write_text(json.dumps(list(replayed)) + '\n')
    return 'sales.npz'


# ---------------------------------------------------------------- commands

def build_groups(cond, ref_dir):
    top400 = inputs.load_top400(ref_dir / cond['inputs']['top400']['file_name'])
    alla = inputs.load_all_addresses(ref_dir / cond['inputs']['all_addresses']['file_name'])
    g, hashes, c_detail = inputs.groups(top400, alla, cond)
    rank = {a: i + 1 for i, (a, _) in enumerate(top400)}
    out = dict(g)
    out['rank1'] = g['A'][:1]
    out['rank2'] = g['A'][1:2]
    out['ranks3_44'] = g['A'][2:]
    counts = dict(alla)
    counts.update(dict(top400))
    out['_counts'] = counts
    return top400, alla, out, hashes, c_detail, rank


_CTX = None


def _run_task(task):
    c, rep = task
    x = _CTX
    args, out = x['args'], x['out']
    t0 = time.time()
    cdir = None
    if not args.timing_only:
        cdir = out / (f"condition-{c['id']:02d}-seed-{rep}" if args.fold == 'none'
                      else f"condition-{c['id']:02d}-fold-{args.fold}")
        cdir.mkdir(parents=True, exist_ok=True)
    res = run_condition(c, rep, data=x['data'], cond=x['cond'], profiles=x['profiles'], top400=x['top400'],
                        groups=x['groups'], rank=x['rank'], q_values=x['q_values'], op=x['op'], args=args,
                        settings_cache=x['settings_cache'], out_dir=cdir,
                        observed_only_rejections=args.fold != 'none', k_of=x['k_of'], d2=x['d2'], plan=x['plan'])
    entry = dict(condition=c['id'], repetition=rep, seed=res['seed'], attempted_rows=res['attempted'],
                 wall_seconds=round(time.time() - t0, 3), peak_memory_mib=round(peak_memory_mib(), 1))
    if cdir is not None:
        entry['directory'] = cdir.name
    print(f"condition {c['id']} repetition {rep}: {entry['wall_seconds']} s", file=sys.stderr)
    return entry


D2_FLAGS = ('vmax', 'd2_k', 'hold', 'failure_window', 'multiplier_source', 'multiplier_margin',
            'prior_settlements', 'threshold_rounding', 'floor_rule', 'd2_config', 'd2_edition', 'sales_cap',
            'k_w', 'bond_rule', 'window_align', 'chain', 'block_time', 'injection_settings', 'confirm_delay')


def window_counts(d2, p, data):
    """The complete fixed windows of the replayed list: failure windows (from the end of the hold period) and
    judgment windows (from the first block), with the first and last edge (design 2, D2-9)."""
    start, end = data.first_block, data.last_block
    out = {}
    for name, lo, length in (('failure', start + p['deferBlocks'], p['failureWindowBlocks']),
                             ('judgment', start, p['inconclusiveWindowBlocks'])):
        edges = design2.window_edges(lo, end, length, d2.align)
        out[name] = dict(window_blocks=length, complete_windows=len(edges) - 1,
                         first_edge=int(edges[0]) if len(edges) else None,
                         last_edge=int(edges[-1]) if len(edges) else None)
    return dict(alignment=d2.align, first_block=start, last_block=end, **out)


def build_design2(args):
    """The design-2 switches of this run (design2.json holds the choices)."""
    config = design2.load_config(args.d2_config)
    op = opt.load(args.operating_point)
    if args.vmax is None:
        raise SystemExit('--design 2 needs --vmax (one of ' + ', '.join(config['vmax_choices_usdc']) + ')')
    try:
        k, k_table = design2.parse_k(args.d2_k)
        return design2.Design2(
            config, op, vmax_usdc=args.vmax, k=k, k_table=k_table, hold=args.hold, failure_window=args.failure_window,
            source=args.multiplier_source, margin=args.multiplier_margin or config['multiplier']['default_margin'],
            rounding=args.threshold_rounding, floor_rule=args.floor_rule or config['floor_rule']['default'],
            edition=args.d2_edition or 2, bond_rule=args.bond_rule, align=args.window_align,
            sales_cap=args.sales_cap, k_w=args.k_w, chain=args.chain or 'base', block_seconds=args.block_time,
            confirm_delay=args.confirm_delay or 'case')
    except ValueError as exc:
        raise SystemExit(str(exc))


def build_release(args):
    """The cursor release of this run (release8.Release8), or None for the hold of edition 7 (the default)."""
    if getattr(args, 'release', 'hold') == 'hold':
        return None
    if args.release == 'fixed10':
        given = {k[4:]: getattr(args, k) for k in R10_SWITCHES if getattr(args, k, None) is not None}
        return release10.Release10(timing=release10.Timing10(accept_over_cap=bool(args.r10_accept_over_cap), **given))
    timing = release8.CursorTiming(case_length=args.r8_case_length, buyer_window=args.r8_buyer_window,
                                   bind_window=args.r8_bind_window, keeper_delay=args.r8_keeper_delay,
                                   open_offset=args.r8_open_offset)
    return release8.Release8(timing=timing, h_n=args.r8_hold_window)


def check_release_args(args, d2, p):
    """The cursor release needs the second edition of design 2 and the narrow freeze; its case length defaults
    to the confirmation delay of an injected failure (the replay's path model)."""
    mode = getattr(args, 'release', 'hold')
    r8_extra = [n for n in ('r8_case_length', 'r8_bind_window', 'r8_open_offset', 'r8_hold_window')
                if getattr(args, n, None) is not None]
    r10_extra = [n for n in R10_SWITCHES if getattr(args, n, None) is not None] + \
        (['r10_accept_over_cap'] if getattr(args, 'r10_accept_over_cap', False) else [])
    if r10_extra and mode != 'fixed10':
        raise SystemExit('the --r10-* switches need --release fixed10')
    if getattr(args, 'r10_save_sales', False) and mode != 'fixed10':
        raise SystemExit('--r10-save-sales needs --release fixed10')
    if d2 is not None and d2.sales_cap == 'none' and mode != 'fixed10':
        raise SystemExit('--sales-cap none (admission without a bucket, R11) needs --release fixed10')
    if mode == 'hold':
        if r8_extra:
            raise SystemExit('the --r8-* switches need --release cursor8')
        return
    if mode == 'fixed10':
        if r8_extra:
            raise SystemExit('the --r8-* switches need --release cursor8')
        if d2 is None or d2.edition != 2:
            raise SystemExit('--release fixed10 needs --design 2 (second edition)')
        if getattr(args, 'freeze_scope', 'full') != 'detected-onward':
            raise SystemExit('--release fixed10 needs --freeze-scope detected-onward (v0.3 R7 (b))')
        if d2.confirm_delay != 'case':
            raise SystemExit('--release fixed10 needs --confirm-delay case')
        try:
            release10.check_epoch_length(build_release(args).timing, p['epochBlocks'])
        except (ValueError, TypeError) as exc:
            raise SystemExit(f'--release fixed10: {exc}')
        return
    if d2 is None or d2.edition != 2:
        raise SystemExit('--release cursor8 needs --design 2 (second edition)')
    if getattr(args, 'freeze_scope', 'full') != 'detected-onward':
        raise SystemExit('--release cursor8 needs --freeze-scope detected-onward (D2-6 (a) 2)')
    if d2.confirm_delay != 'case':
        raise SystemExit('--release cursor8 needs --confirm-delay case')
    if args.r8_case_length is None:
        args.r8_case_length = confirm_delay(p)


def build_plan(args, cond, d2, data, replayed):
    """The multiplier plan (first edition) or the sales cap plan (second edition). The prior-14-days
    source reads the registered prior list (checked against its hash in conditions.json) for the replayed
    addresses only."""
    prior, prior_input = None, None
    wants_prior = d2.sales_cap == 'prior14' if d2.sales_cap is not None else d2.source == 'prior14'
    if wants_prior:
        if not args.prior_settlements:
            raise SystemExit('the prior14 multiplier source needs --prior-settlements')
        spec = cond['inputs'].get('prior_period')
        if spec is None:
            raise SystemExit('this conditions file registers no prior-period list')
        sha = inputs.sha256_file(args.prior_settlements)
        if sha != spec['sha256']:
            raise SystemExit('--prior-settlements is not the registered prior-period list (hash differs)')
        prior = engine.load(args.prior_settlements, cond['inputs']['columns'], replayed, inputs.iter_rows,
                            inputs.utc_seconds, norm=inputs.normalize)
        prior_input = dict(path=str(args.prior_settlements), sha256=sha, rows=prior.total_rows)
    mid = data.first_block + cond['window_blocks'] // 2
    if d2.sales_cap is not None:
        plan = design2.CapPlan(d2, d2.sales_cap, prior=prior, mid_block=mid, first_block=data.first_block)
    else:
        plan = design2.MultiplierPlan(d2.source, design2.parse_margin(d2.margin), d2.tau, prior=prior,
                                      mid_block=mid, first_block=data.first_block)
    return plan, prior_input


def cmd_run(args):
    t_start = time.time()
    cond = inputs.load_conditions(args.conditions_file)
    ref_dir = Path(args.reference_dir)
    ids = [c['id'] for c in cond['conditions']] if args.conditions == 'all' else [int(x) for x in args.conditions.split(',')]
    unknown = sorted(set(ids) - {c['id'] for c in cond['conditions']})
    if unknown:
        raise SystemExit(f'unknown conditions {unknown}')
    d2 = None
    if args.design == 2:
        d2 = build_design2(args)
        inputs.set_address_case(d2.address_case)
    elif any(getattr(args, name) is not None for name in D2_FLAGS):
        raise SystemExit('the design-2 switches need --design 2')
    else:
        inputs.set_address_case('lower')
    op, profile_file, profiles, op_errors = resolve(args, cond, ids, d2)
    check_release_args(args, d2, profiles[next(c for c in cond['conditions'] if c['id'] in ids)['profile']]['parameters'])
    top400, alla, groups, hashes, c_detail, rank = build_groups(cond, ref_dir)
    scale_errors = check_expected_scales(cond, top400, profiles, ('nF', 'nR') if d2 is None else ('nR',))
    if scale_errors:
        # Design 9.5: the run stops when the implementation does not give the registered scales.
        raise SystemExit('scale check failed: ' + '; '.join(scale_errors))
    reduced = args.addresses == 'reduced'
    replayed = (groups['A'] + groups['B'] + groups['C']) if reduced else (groups['all400'] + groups['C'])
    seen = set()
    groups['replayed'] = [a for a in replayed if not (a in seen or seen.add(a))]
    # The three addresses whose mean rate exceeds n * r_fill under nR (secondary condition).
    chosen = [c for c in cond['conditions'] if c['id'] in ids]
    pd = profiles[chosen[0]['profile']]['parameters']
    nr = scales(top400, 'nR', pd, rate_blocks(cond))
    groups['three'] = [a for a, cnt in top400 if inj.under_assigned(cnt, rate_blocks(cond), nr[a],
                                                                     Fraction(pd['refillPpmPerBlock'], engine.PPM))]
    groups['_sets'] = {g: set(v) for g, v in groups.items() if not g.startswith('_')}
    q_values = {'qX': args.qx}
    q20 = {profiles[c['profile']]['parameters']['bucketCapacity'] for c in chosen}
    if len(q20) != 1:
        raise SystemExit('profiles disagree on the placeholder bucket capacity')
    q_values['q20'] = q20.pop()
    k_of = {name: int(pr['parameters']['failureLimit']) for name, pr in profiles.items()}
    if d2 is not None and d2.edition == 2:
        extra = d2.config['edition2'].get('injection_extra_settings', [])
        only = ([s for s in args.injection_settings.split(',') if s] if args.injection_settings
                else d2.config['edition2'].get('injection_settings'))
    else:
        extra, only = (), ([s for s in args.injection_settings.split(',') if s] if args.injection_settings else None)
    try:
        settings_cache = {name: settings_for(op, name, cond, args.alpha_upper, extra, only) for name in profiles}
    except ValueError as exc:
        raise SystemExit(str(exc))
    # Input list.
    sha = inputs.sha256_file(args.settlements)
    period = next((k for k, v in cond['inputs'].items() if isinstance(v, dict) and v.get('sha256') == sha), None)
    fold_range = None
    first_block = last_block = None
    if args.fold != 'none':
        spec = cond['inputs'][period] if period else None
        if spec is None:
            raise SystemExit('a fold needs a registered settlement list')
        mid = spec['first_block'] + cond['window_blocks'] // 2
        fold_range = (spec['first_block'], mid - 1) if args.fold == 'first' else (mid, spec['last_block'])
    t_load = time.time()
    data = engine.load(args.settlements, cond['inputs']['columns'], groups['replayed'], inputs.iter_rows,
                       inputs.utc_seconds, block_range=fold_range, cap=None if d2 is None else d2.vmax,
                       norm=inputs.normalize)
    plan, prior_input = None, None
    if d2 is not None:
        plan, prior_input = build_plan(args, cond, d2, data, groups['replayed'])
    load_seconds = time.time() - t_load
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    git = git_state()
    reasons = []
    if args.timing_only:
        reasons.append('timing-only pass')
    if git['dirty'] or git['revision'] is None:
        reasons.append('working tree not clean')
    if period != 'replay_period':
        reasons.append('input list is not the registered replay-period list')
    if args.qx != cond['q']['qX']:
        reasons.append(f'qX {args.qx} differs from the fixed value {cond["q"]["qX"]}')
    if op_errors:
        reasons.append('operating point and profile disagree')
    if hashes['C']['registered'] is None:
        reasons.append('group C list hash not fixed')
    for name in ('all400', 'A', 'B', 'AB', 'C'):
        if hashes[name]['registered'] is None:
            continue
        if not hashes[name]['match']:
            reasons.append(f'group {name} hash mismatch')
    k_default = cond.get('k_default', {})
    for name, k in k_of.items():
        if d2 is not None and d2.edition == 2:
            break      # the second edition takes k from the table (D2-5 (e)), not from the pre-certification default
        if args.k_role == 'default' and k_default.get(name) is not None and k_default[name] != k:
            reasons.append(f'{name} failureLimit {k} is not the pre-certification default {k_default[name]}')
    admissible = {}
    for c in chosen:
        pr = profiles[c['profile']]['parameters']
        admissible[f"{c['profile']}:{c['q']}"] = profile_admits_capacity(pr, q_values[c['q']])
    if period == 'replay_period' and args.fold == 'none' \
            and data.last_block - data.first_block + 1 != rate_blocks(cond):
        reasons.append(f'list span {data.last_block - data.first_block + 1} differs from rate_blocks {rate_blocks(cond)}')
    registered_ids = cond.get('run_conditions')
    not_run = [c['id'] for c in cond['conditions'] if c['id'] not in ids]
    if registered_ids is not None and sorted(ids) != sorted(registered_ids) and d2 is None:
        reasons.append(f'conditions run {sorted(ids)} differ from the registered set {sorted(registered_ids)}')
    rp = cond.get('replay_profile')
    overrides = profile_overrides(profile_file)
    if rp is not None:
        if Path(args.operating_point).resolve() != (ROOT / rp['operating_point']).resolve():
            reasons.append('operating point is not the registered replay operating point')
        elif overrides.get('base_unchanged') is False:
            reasons.append('replay profile is out of date with its base profile (run replay_profile.py --write)')
    design = dict(path=args.design_record,
                  sha256=inputs.sha256_file(args.design_record) if args.design_record else None)
    m1 = dict(path=args.m1_predictions,
              sha256=inputs.sha256_file(args.m1_predictions) if args.m1_predictions else None)
    envelope = dict(
        formatVersion=FORMAT_VERSION, kind='fairbind-settlement-replay-run',
        **({} if d2 is None else dict(design='design-2', design2=d2.describe(), design2_prior_input=prior_input,
                                      design2_windows=window_counts(d2, profiles[chosen[0]['profile']]['parameters'], data),
                                      design2_note='design-2 rules are not registered (D2-REG); results on '
                                                   'the tuning-period list are implementation checks, not evaluation')),
        inputs=dict(settlements=dict(path=str(args.settlements), sha256=sha, period=period,
                                     rows=data.total_rows, first_block=data.first_block, last_block=data.last_block,
                                     fold=args.fold, fold_block_range=fold_range),
                    top400=dict(path=str(ref_dir / cond['inputs']['top400']['file_name']),
                                sha256=inputs.sha256_file(ref_dir / cond['inputs']['top400']['file_name'])),
                    all_addresses=dict(path=str(ref_dir / cond['inputs']['all_addresses']['file_name']),
                                       sha256=inputs.sha256_file(ref_dir / cond['inputs']['all_addresses']['file_name'])),
                    conditions_file=dict(path=cond['_path'], sha256=cond['_sha256']),
                    operating_point=dict(path=op['_path'], sha256=op['_sha256']),
                    profile_file=dict(path=str(profile_file), sha256=inputs.sha256_file(profile_file)),
                    design_record=design, m1_predictions=m1),
        # Common rule 3 of the design README names this item `preregistration`; the same object.
        preregistration=dict(design),
        code=dict(git, replayer='experiments/replay/replay.py'),
        parameters=dict(qX=args.qx, q20=q_values['q20'], k=k_of, k_role=args.k_role, draws=args.draws,
                        base_seed=cond['base_seed'], addresses=args.addresses, replayed_addresses=len(groups['replayed']),
                        window_blocks=cond['window_blocks'], rate_blocks=rate_blocks(cond),
                        injection_settings=settings_cache, profile_overrides=overrides,
                        reentry_delay_blocks=cond['injection']['reentry_delay_blocks'],
                        claim_probability=cond['injection']['claim_probability'],
                        profile_capacity_admissible=admissible, options=OPTIONS if d2 is None else dict(OPTIONS, **D2_OPTIONS),
                        **({} if getattr(args, 'freeze_scope', 'full') == 'full' else dict(freeze_scope=args.freeze_scope))),
        groups=dict(hashes=hashes, C=c_detail if not args.timing_only else {k: dict(target_per_block=v['target_per_block'])
                                                                              for k, v in c_detail.items()},
                    three=groups['three']),
        conditions=[dict(c) for c in chosen],
        conditions_not_run=[dict(id=i, reason='not run in this run (design 9.2: conditions 6-10 are reported as not run)'
                                 if registered_ids is not None and i not in registered_ids else 'not selected')
                            for i in not_run],
        operating_point_errors=op_errors,
        started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_start)))
    r8 = build_release(args)
    if isinstance(r8, release10.Release10):
        envelope['parameters']['options'] = dict(envelope['parameters']['options'], **R10_OPTIONS)
        envelope['parameters']['release10'] = r8.describe()
        envelope['parameters']['preset'] = getattr(args, 'preset', None)
        envelope['parameters']['save_sales'] = bool(getattr(args, 'r10_save_sales', False))
    elif r8 is not None:
        envelope['parameters']['options'] = dict(envelope['parameters']['options'], **R8_OPTIONS)
        envelope['parameters']['release8'] = r8.describe()
    seeds_of = (lambda c: c['seeds']) if args.repetitions is None else (lambda c: min(c['seeds'], args.repetitions))
    tasks = [(c, rep) for c in chosen for rep in range(seeds_of(c) if args.fold == 'none' else 1)]
    global _CTX
    _CTX = dict(data=data, cond=cond, profiles=profiles, top400=top400, groups=groups, rank=rank, q_values=q_values,
                op=op, args=args, settings_cache=settings_cache, out=out, k_of=k_of, d2=d2, plan=plan)
    if args.jobs > 1 and len(tasks) > 1:
        import multiprocessing
        with multiprocessing.get_context('fork').Pool(args.jobs) as pool:
            runs = pool.map(_run_task, tasks, chunksize=1)
    else:
        runs = [_run_task(t) for t in tasks]
    envelope.update(runs=runs, load_seconds=round(load_seconds, 3), wall_seconds=round(time.time() - t_start, 3),
                    peak_memory_mib=round(peak_memory_mib(), 1),
                    peak_memory_children_mib=round(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024, 1),
                    jobs=args.jobs, finished_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    reportable=not reasons, not_reportable_reasons=reasons,
                    column_source=({'half': sorted(inj.HALF_REPLAY_COLUMNS)} if args.fold != 'none' else 'full'))
    (out / ('timing.json' if args.timing_only else 'run.json')).write_text(dump(envelope))
    return envelope


def cmd_check_input(args):
    cond = inputs.load_conditions(args.conditions_file)
    ref_dir = Path(args.reference_dir)
    extract_dir = Path(args.extraction_dir) if args.extraction_dir else Path(args.settlements).parent
    kwargs = {}
    if args.period == 'replay_period':
        kwargs['reference_per_address'] = inputs.load_all_addresses(ref_dir / cond['inputs']['all_addresses']['file_name'])
        kwargs['top400'] = inputs.load_top400(ref_dir / cond['inputs']['top400']['file_name'])
    fac = extract_dir / 'facilitators.csv'
    report = inputs.check_input(args.settlements, cond, args.period, facilitators_path=fac if fac.exists() else None,
                                qx=args.period == 'prior_period', **kwargs)
    per_file = extract_dir / 'input_check_per_address.csv'
    if args.period == 'replay_period' and per_file.exists():
        with open(per_file, newline='', encoding='utf-8') as f:
            rows = list(csv.DictReader(f))
        ext = {r['recipient'].lower(): int(r['settlements_extracted']) for r in rows}
        ref = dict(kwargs['reference_per_address'])
        report['per_address']['extraction_report_file_match'] = all(ext.get(a) == ref.get(a) for a in ref) and \
            len(ext) == len(ref)
    text = dump(report)
    if args.out:
        Path(args.out).write_text(text)
    sys.stdout.write(text)
    return 0 if report['pass'] else 1


PRESETS = ('r11-main',)


def apply_preset(args):
    """--preset r11-main (registration R11, main setting): the rule as written in edition 10 candidate v0.6 for tiers 0
    and 1 with s = 1: sales above V admitted and sampled with probability 1, no count limit (no bucket), every dispute
    window from the anchor deadline, the narrow freeze, and the per-sale payment file. A switch given explicitly keeps
    its value."""
    preset = getattr(args, 'preset', None)
    if preset is None:
        return
    if preset == 'r11-main':
        if args.release == 'hold':
            args.release = 'fixed10'
        args.r10_accept_over_cap = True
        if args.sales_cap is None:
            args.sales_cap = 'none'
        if args.r10_dispute_from is None:
            args.r10_dispute_from = 'anchor'
        if args.freeze_scope == 'full':
            args.freeze_scope = 'detected-onward'
        args.r10_save_sales = True


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    command = 'run'
    if argv and argv[0] in ('run', 'check-input'):
        command = argv.pop(0)
    p = argparse.ArgumentParser(prog='replay.py ' + command)
    p.add_argument('--settlements', required=True)
    p.add_argument('--conditions-file', default=str(inputs.CONDITIONS_PATH))
    p.add_argument('--reference-dir', required=True, help='directory with the top-400 and all-address aggregates')
    if command == 'check-input':
        p.add_argument('--period', required=True, choices=('replay_period', 'prior_period'))
        p.add_argument('--extraction-dir', help='directory with facilitators.csv (default: the list directory)')
        p.add_argument('--out')
        return cmd_check_input(p.parse_args(argv))
    p.add_argument('--operating-point', default=None,
                   help='default: the replay operating point named in conditions.json (replay_profile)')
    p.add_argument('--qx', type=int, required=True)
    p.add_argument('--conditions', default='all')
    p.add_argument('--out', required=True)
    p.add_argument('--timing-only', action='store_true')
    p.add_argument('--fold', choices=('first', 'second', 'none'), default='none')
    p.add_argument('--draws', type=int, default=None)
    p.add_argument('--addresses', choices=('full', 'reduced'), default='full')
    p.add_argument('--alpha-upper', type=float, default=None)
    p.add_argument('--k-role', choices=('default', 'certified'), default='default')
    p.add_argument('--design-record', default=None)
    p.add_argument('--m1-predictions', default=None, help='R20-M1 prediction CSV (m1_predictions.py); its hash goes in the envelope')
    p.add_argument('--jobs', type=int, default=1)
    p.add_argument('--repetitions', type=int, default=None,
                   help='run at most this many seeds of each condition (default: the registered number)')
    p.add_argument('--design', type=int, choices=(1, 2), default=1,
                   help='1: the registered rules (default, outputs unchanged); 2: the design-2 switches below')
    p.add_argument('--d2-config', default=None, help='design2.json (default: next to replay.py)')
    p.add_argument('--d2-edition', type=int, choices=(1, 2), default=None,
                   help='design 2: the edition of the rules (default 2; 1 repeats the first-edition switches)')
    p.add_argument('--vmax', '--tau', dest='vmax', default=None,
                   help='design 2: amount cap v_max in USDC (D2-1), one of design2.json vmax_choices_usdc (--tau is the first-edition name)')
    p.add_argument('--d2-k', default=None,
                   help='design 2: failure limit k: one integer for every cap, or S:k,S:k,... (default: the table of design2.json)')
    p.add_argument('--k-w', default=None, help='design 2: which k table (the failure probability w), default 0.015')
    p.add_argument('--hold', type=int, default=None,
                   help='design 2: deferBlocks = retentionBlocks = claimWindowBlocks (D2-8); edition 2: 31,073 blocks of 2 s or the same time on the chain')
    p.add_argument('--failure-window', type=int, default=None,
                   help='design 2: failureWindowBlocks = inconclusiveWindowBlocks (D2-9); edition 2: the hold period')
    p.add_argument('--sales-cap', default=None,
                   help='design 2, edition 2: sales cap S of every address (10, 30, 100, 300, 1000, 3245 * n) or a mode: '
                        'auto-zero-reject (least cap with zero rejection in the window), prior14 (fitted on the 14 days before), cross')
    p.add_argument('--multiplier-source', choices=design2.SOURCES, default=None,
                   help='design 2: record the first-edition multiplier is fitted on (D2-7, undecided U3)')
    p.add_argument('--multiplier-margin', default=None, help='design 2: margin factor m on the fitted multiplier (1, 1.5, 2)')
    p.add_argument('--prior-settlements', default=None, help='design 2, prior14: the 14 days before the window')
    p.add_argument('--threshold-rounding', default=None, help='design 2: contract (floor, today) or ceil (D2-3 as written; edition 2 default)')
    p.add_argument('--floor-rule', default=None, help='design 2: exposure floor rule, product or ratio (U7)')
    p.add_argument('--bond-rule', default=None, help='design 2: integer-b (edition 2) or floor-fraction (edition 1)')
    p.add_argument('--window-align', default=None, help='design 2: absolute (edition 2) or first-block (edition 1)')
    p.add_argument('--chain', default=None, help='design 2: base (default), polygon or solana (block time and address case from design2.json)')
    p.add_argument('--block-time', default=None, help='design 2: seconds per block or slot, replacing the chain default (hold and windows are converted)')
    p.add_argument('--confirm-delay', choices=('case', 'settlement'), default=None,
                   help='design 2: when an injected failure is confirmed: case (the case opening plus the judgment and appeal horizon, default) '
                        'or settlement (the settlement of the sampled entry plus the longest measured path, the sensitivity of D2-8)')
    p.add_argument('--freeze-scope', choices=('full', 'detected-onward'), default='full',
                   help="injection: which held entries a wrongful confirmed failure freezes: full (default; every unreleased entry) "
                        "or detected-onward (only entries settled at or after the failed sampled sale)")
    p.add_argument('--release', choices=release8.MODES + release10.MODES, default='hold',
                   help='hold: a sale is released at settled + deferBlocks (rule edition 7, default); cursor8: by the '
                        'release cursor of rule edition 8 (D2-39), with the --r8-* switches')
    p.add_argument('--r8-case-length', type=int, default=None,
                   help='cursor8: blocks from a case opening to its final state (default: the confirmation delay)')
    p.add_argument('--r8-buyer-window', type=int, default=1860, help='cursor8: buyer window after a settlement (T_response + T_claim)')
    p.add_argument('--r8-bind-window', type=int, default=None,
                   help='cursor8: w_b of an unsigned account (W_e = sample value block + w_b); default none (receipt-signed)')
    p.add_argument('--r8-keeper-delay', type=int, default=0, help='cursor8: blocks from the last condition to the cursor call')
    p.add_argument('--r8-open-offset', type=int, default=None,
                   help='cursor8: case opening this many blocks after the epoch start (default: the prompt path of the replay)')
    p.add_argument('--r8-hold-window', type=int, default=None,
                   help='cursor8: H_N in blocks; a settlement is rejected while ceil(q_S + r_S H_N) settlements are held (D2-42)')
    p.add_argument('--r10-anchor-delay', type=int, default=None, help='fixed10: d_A, A_e = last epoch block + d_A (default 100)')
    p.add_argument('--r10-vrf-response', type=int, default=None, help='fixed10: tau_V (default 100)')
    p.add_argument('--r10-vrf-slack', type=int, default=None, help='fixed10: T_V (default 50)')
    p.add_argument('--r10-proof-window', type=int, default=None, help='fixed10: T_p (default 1800)')
    p.add_argument('--r10-dispute-window', type=int, default=None, help='fixed10: T_c from the settlement (default 1800)')
    p.add_argument('--r10-bind-window', type=int, default=None, help='fixed10: w_b of unsigned sales (default 300)')
    p.add_argument('--r10-proof-delay', type=int, default=None,
                   help='fixed10: an honest proof lands this many blocks after M_e (default: at the deadline T_p)')
    p.add_argument('--r10-keeper-delay', type=int, default=None, help='fixed10: kappa_r (default 0)')
    p.add_argument('--r10-accept-ppm', type=int, default=None, help='fixed10: buyer acceptance share a in ppm (default 0)')
    p.add_argument('--r10-unsigned-ppm', type=int, default=None, help='fixed10: unsigned share u in ppm (default 0)')
    p.add_argument('--r10-accept-over-cap', action='store_true',
                   help='fixed10: accept sales above V and sample them with probability 1 (tiers 0 and 1)')
    p.add_argument('--r10-seller-epoch-k', type=int, default=None,
                   help='fixed10 (R11): profile epochs per seller epoch k (v0.6 R1 (a), R6 (a)); default 1 (the R10 path)')
    p.add_argument('--r10-dispute-from', choices=release10.DISPUTE_FROM, default=None,
                   help='fixed10 (R11): the dispute window T_c runs from the settlement (default, R10) or from the anchor '
                        'deadline A_e (v0.6 R5 (c))')
    p.add_argument('--r10-save-sales', action='store_true',
                   help='fixed10 (R11): write sales.npz per condition with the payment block of every accepted sale')
    p.add_argument('--preset', choices=PRESETS, default=None,
                   help='r11-main: the main setting of registration R11 (fixed10, over-cap acceptance, no bucket, dispute '
                        'windows from the anchor deadline, narrow freeze, sales file); explicit switches win')
    p.add_argument('--injection-settings', default=None, help='comma list of injection settings to run (design 2 edition 2 default: main,w_0.015)')
    args = p.parse_args(argv)
    apply_preset(args)
    cond = inputs.load_conditions(args.conditions_file)
    if args.draws is None:
        args.draws = cond['injection']['draws']
    if args.operating_point is None:
        args.operating_point = default_operating_point(cond)
    env = cmd_run(args)
    if args.timing_only:
        sys.stdout.write(dump(dict(rows=env['inputs']['settlements']['rows'], runs=env['runs'],
                                   wall_seconds=env['wall_seconds'], peak_memory_mib=env['peak_memory_mib'])))
    else:
        sys.stdout.write(f"{args.out}: reportable={env['reportable']}\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
