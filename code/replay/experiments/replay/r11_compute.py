#!/usr/bin/env python3
"""Aggregation of the R11 replay (rule edition 10 candidate as written, registration R11 sections 5 to 9).

    python3 -I r11_compute.py --raw <SCRATCH>/raw --lists <SCRATCH>/raw/lists --out <SCRATCH>/summary \
        --code-commit <HEAD> --docs <research repo>/docs --registration <research repo>/docs/11_journal/R11/R11_preregistration.md

Reads the replay outputs (`<raw>/<window><suffix>/base_v<V>_<mode>/condition-01-seed-0/`, with `sales.npz`), the
k sweep (`<raw>/<window>_ksweep/k<k>/`), the two fraud replays (`<raw>/deter/`, `<raw>/deter_r10style/`), the two
settlement lists (sliding-window baselines), and from the research docs the edition-7 stored outputs (address sets),
the E8b per-address outputs (bucket baselines, gate G6) and the R10 overcap aggregates (gate G2 of the R10-equivalent
variant). Writes `<out>/r11_results.json`, `<out>/r11_tables.md`, `<out>/r11_addr_<config>_<window>_v<V>.csv`,
`<out>/r11_k_<window>.csv` and `<out>/r11_sales_sha256.txt`. Numbers are never corrected; a cell whose gate fails is
marked not reportable. Only numpy beyond the standard library.

Held money has three definitions, all per address and in atomic units: the continuous average over
[first block + hold, last block] (`H_cont_average_from_hold`, the main definition of the registration), the continuous
average over the whole window (`H_cont_average`) and the hourly 487-point average of R10 (`H_time_average`). The
deduction is b = V / s with s = 1 (v0.7c R1 (c)). Baselines are computed over the same sale set as the replay, which
includes the sales above V (registration section 5).
"""
import argparse
import csv
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np

WINDOWS = ('median', 'busy')
LISTS = {'median': 'median/settlements_base_2026-07-24_2026-08-13.csv',
         'busy': 'busy/settlements_base_2026-06-09_2026-06-29.csv'}
VS = ('0.1', '0.2', '0.5', '1')
VMAX = {'0.1': 100_000, '0.2': 200_000, '0.5': 500_000, '1': 1_000_000}
B11 = dict(VMAX)                                        # b = V / s, s = 1 (v0.7c R1 (c), tiers 0 and 1)
LF7 = 29_454                                            # L_F of E8b (reference cells)
SCALE_ANCHOR = 77
MARGINS = (Fraction(1), Fraction(3, 2), Fraction(2), Fraction(4))
MARGIN_NAMES = ('1', '3/2', '2', '4')
SETS = ('S1r', 'S1', 'S2', 'S3', 'S1a', 'S2a')
JUDGEMENT_SET = 'S1r'
SUPPLY_RATES = (0.0320, 0.0356)
EPOCH = 300
ANCHOR_DELAY = 120                                      # a_A of v0.7c R3 (a), R8 (e); R10 used 100
HDEFS = {'cont_from_hold': 'H_cont_average_from_hold', 'cont_window': 'H_cont_average', 'hourly': 'H_time_average'}
MAIN_HDEF = 'cont_from_hold'
KS = (1, 2, 3, 6)
UPPER_X = 0.2
BASE = dict(mode='fixed10', anchor_delay=ANCHOR_DELAY, vrf_response=100, vrf_slack=50, proof_window=1800,
            dispute_window=1800, bind_window=300, proof_delay=None, keeper_delay=0, accept_ppm=0, unsigned_ppm=0,
            accept_over_cap=True, seller_epoch_k=1, dispute_from='anchor')
# name -> (directory suffix, sales-cap mode, V list, expected release10 record, admission)
CONFIGS = {
    'main': ('', 'none', VS, BASE, 'unlimited'),
    'a05': ('_a05', 'none', ('0.2',), dict(BASE, accept_ppm=500_000), 'unlimited'),
    'a09': ('_a09', 'none', ('0.2',), dict(BASE, accept_ppm=900_000), 'unlimited'),
    'short': ('_short', 'none', ('0.2',), dict(BASE, proof_window=300, dispute_window=300), 'unlimited'),
    'long': ('_long', 'none', ('0.2',), dict(BASE, proof_window=7_200, dispute_window=7_200), 'unlimited'),
    'u05a09': ('_u05a09', 'none', ('0.2',), dict(BASE, accept_ppm=900_000, unsigned_ppm=500_000), 'unlimited'),
    'legacy': ('_legacy', 'auto-zero-reject', ('0.2',), BASE, 'bucket'),
    'dsettle': ('_dsettle', 'none', ('0.2',), dict(BASE, dispute_from='settlement'), 'unlimited'),
    'r10equiv': ('_r10equiv', 'auto-zero-reject', ('0.2',), dict(BASE, dispute_from='settlement', anchor_delay=100),
                 'bucket'),
}
STORED = {   # edition-7 stored outputs (registration 2.3, the files of R8 and R10): path under docs, sha256
    ('median', '0.1'): ('05_run-evidence/design2/median-period/seed0/base_v0.1_auto-zero-reject',
                        '87441a7c99329c8aa93084182a8c00e02521cfa5f0930dce6ddc7cc7fc5682e4'),
    ('median', '0.2'): ('05_run-evidence/design2/median-period/seed0/base_v0.2_auto-zero-reject',
                        '5c1c8a44ae4ea728553929d6021ce6cf45298e929e895128507228366d6f9543'),
    ('median', '0.5'): ('11_journal/J13a/out/seed0/base_v0.5_auto-zero-reject',
                        '417b5a8fc67b4fea67bf0ec6bd4198940ef49f061e0f3ac6336176c30598e575'),
    ('median', '1'): ('05_run-evidence/design2/median-period/seed0/base_v1_auto-zero-reject',
                      'eeec20355a802b28327db69fe88d4a402c5aa75531add5a1185a780531ef00bc'),
    ('busy', '0.2'): ('11_journal/J9/out/seed0/base_v0.2_auto-zero-reject',
                      'a1f0c21d43459b0716e038f8a8611a43a0ed5bb5ffda1178fc33d22ee101bfe8'),
}
E8B_RESULTS = ('11_journal/E8b/out/e8_results.json', 'a415a6026840145b4c6d2ea72567da3334a8536347174202896b0a37937bcc26')
E8B_DIR = '11_journal/E8b/out'
R10_RESULTS_DIR = '11_journal/R10/results'
SAME_COLUMNS = ('scale', 'attempted_count', 'attempted_value', 'accepted_count', 'accepted_value', 'sample_count',
                'cap_rejected_count', 'rate_rejected_count', 'sales_cap_S', 'deduction_b', 'epochs_with_settlement')
HIST_EDGES = [0, 1000, 2000, 2600, 3000, 4000, 5000, 5600, 7000, 9000, 12000, 15000, 20000, 25000, 31073]
FRAUD = {'main': ('deter', dict(BASE), 'none'),
         'r10style': ('deter_r10style', dict(BASE, anchor_delay=100, accept_over_cap=False, dispute_from='settlement'),
                      'auto-zero-reject')}


def lf11(cfg, k=1):
    """L_F^11: the longest path from a sale to its confirmed failure, with k profile epochs per seller epoch."""
    return EPOCH - 1 + cfg['anchor_delay'] + cfg['vrf_response'] + 1 + cfg['vrf_slack'] + cfg['proof_window'] + 1 \
        + EPOCH * (k - 1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def num(x, default=0.0):
    return default if x in ('', None) else float(x)


def inum(x):
    return int(num(x))


def q(xs, p):
    xs = [x for x in xs if x is not None]
    return float(np.percentile(xs, p)) if xs else None


def is_true(x):
    return str(x).lower() in ('true', '1')


# ---------------------------------------------------------------- gates

def gate_registration(reg):
    """G0 (the file part): the registration's SHA-256 equals the first word of the .sha256 file beside it."""
    reg = Path(reg)
    stated_file = reg.with_suffix('.sha256')
    if not reg.exists() or not stated_file.exists():
        raise SystemExit(f'G0: registration {reg} or its .sha256 is missing')
    got, stated = sha256(reg), stated_file.read_text(encoding='utf-8').split()[0]
    if got != stated:
        raise SystemExit(f'G0: registration hash {got} differs from {stated_file.name}: {stated}')
    return got


def load_condition(run_dir, expect, code_commit, admission, n_addresses, preset='r11-main'):
    """Reads one replay run (`run_dir/run.json`, `run_dir/condition-01-seed-0/`) and applies G3 and the G4 ledger
    check. Returns (run, problems); run is None without output."""
    run_dir = Path(run_dir)
    cdir = run_dir / 'condition-01-seed-0'
    if not (cdir / 'addresses_observed.csv').exists():
        return None, ['no replay output']
    env = json.loads((run_dir / 'run.json').read_text())
    meta = json.loads((cdir / 'condition.json').read_text())
    rows = {r['address']: r for r in read_csv(cdir / 'addresses_observed.csv')}
    problems = []
    if not env.get('reportable'):
        problems.append('run.json reportable false: ' + '; '.join(env.get('not_reportable_reasons', [])))
    if env['code']['revision'] != code_commit or env['code']['dirty']:
        problems.append(f"code {env['code']['revision']} dirty={env['code']['dirty']} (registered {code_commit})")
    if meta.get('release10') != expect:
        problems.append(f"release10 {meta.get('release10')} differs from the registered record (G3)")
    if env['parameters'].get('freeze_scope') != 'detected-onward':
        problems.append('freeze scope is not detected-onward (G3)')
    if meta.get('admission') != [admission]:
        problems.append(f"admission {meta.get('admission')} is not [{admission}] (G3)")
    if admission == 'unlimited' and preset is not None and meta.get('preset') != preset:
        problems.append(f"preset {meta.get('preset')} is not {preset} (G3)")
    if any(num(r.get('H_ledger_list_max_abs_diff')) != 0 for r in rows.values()):
        problems.append('the two H paths differ (G4)')
    if n_addresses is not None and len(rows) != n_addresses:
        problems.append(f'{len(rows)} addresses, expected {n_addresses}')
    if meta.get('sales_file') != 'sales.npz' or not (cdir / 'sales.npz').exists():
        problems.append('sales.npz missing (G4 cannot recompute the continuous average)')
    return dict(env=env, meta=meta, rows=rows, cdir=cdir, cfg=expect,
                first=env['inputs']['settlements']['first_block'], last=env['inputs']['settlements']['last_block']), \
        problems


def load_run(raw, w, cname, v, code_commit, n_addresses):
    suffix, mode, _, expect, admission = CONFIGS[cname]
    return load_condition(Path(raw) / f'{w}{suffix}' / f'base_v{v}_{mode}', expect, code_commit, admission,
                          n_addresses, preset='r11-main' if admission == 'unlimited' else None)


def load_sales(run):
    z = np.load(run['cdir'] / 'sales.npz')
    sales = {k: z[k] for k in z.files}
    addrs = json.loads((run['cdir'] / 'sales_addresses.json').read_text())
    return sales, addrs


def cont_numerators(sales, n_addr, first, last):
    """Per address index: sum over the sales of value times the blocks of [first, last] in which the sale is held
    (a sale not paid by the last block is held to it). Exact int64 accumulation."""
    b, v, rl = sales['block'].astype(np.int64), sales['value'].astype(np.int64), sales['release'].astype(np.int64)
    held = np.maximum(np.minimum(rl, last + 1) - np.maximum(b, first), 0)
    out = np.zeros(n_addr, dtype=np.int64)
    np.add.at(out, sales['address_index'].astype(np.int64), v * held)
    return out


def gate_cont_average(run, sales, addrs):
    """G4: the numerator of the continuous average recomputed from sales.npz equals H_cont_sum_blocks per address."""
    if addrs != list(run['rows']):
        return dict(ok=False, reason='sales_addresses.json order differs from addresses_observed.csv')
    nums = cont_numerators(sales, len(addrs), run['first'], run['last'])
    bad = [a for i, a in enumerate(addrs) if int(nums[i]) != int(run['rows'][a]['H_cont_sum_blocks'])]
    return dict(ok=not bad, mismatches=len(bad), first=bad[:5])


def gate_main_admission(run):
    """G2 (main setting): admission unlimited, every attempted sale admitted, no rate or value-cap rejection."""
    bad = []
    for a, r in run['rows'].items():
        if r.get('admission') != 'unlimited' or r['accepted_count'] != r['attempted_count'] \
                or inum(r['rate_rejected_count']) != 0 or inum(r['cap_rejected_count']) != 0:
            bad.append(a)
    return dict(ok=not bad, mismatches=len(bad), first=bad[:5])


def gate_same_rows(rows_a, rows_b, columns, float_columns=()):
    """Per-address equality of the given columns between two address tables (strings exactly, floats to 1e-9)."""
    diff = []
    for a, r in rows_a.items():
        s = rows_b.get(a)
        if s is None:
            diff.append((a, 'missing'))
            continue
        for c in columns:
            if r.get(c) != s.get(c):
                diff.append((a, c, r.get(c), s.get(c)))
        for c in float_columns:
            x, y = num(r.get(c)), num(s.get(c))
            if not math.isclose(x, y, rel_tol=1e-9, abs_tol=1e-9):
                diff.append((a, c, r.get(c), s.get(c)))
    return dict(ok=not diff and len(rows_a) == len(rows_b), n_differences=len(diff), differences=diff[:20])


def gate_sampled_flags(sales_main, sales_other):
    """G2: a sale admitted in both runs has the same draw (the draw is per list row, R-ENC-S)."""
    rm, ro = sales_main['row'], sales_other['row']
    order = np.argsort(rm, kind='stable')
    pos = np.searchsorted(rm[order], ro)
    pos = np.minimum(pos, len(rm) - 1) if len(rm) else pos
    found = len(rm) > 0 and (rm[order][pos] == ro)
    if not len(rm) or not np.all(found):
        return dict(ok=False, reason='a sale of the other run is not in the main run', missing=int((~found).sum())
                    if len(rm) else len(ro))
    same = sales_main['sampled'][order][pos] == sales_other['sampled']
    return dict(ok=bool(same.all()), common=int(len(ro)), mismatches=int((~same).sum()))


def gate_e8b_att(run, e8addr):
    """G6: the in-cap accepted value (accepted value minus the over-cap accepted value) equals E8b's att_v."""
    bad = []
    for a, r in run['rows'].items():
        incap = inum(r['accepted_value']) - inum(r.get('over_cap_accepted_value'))
        if a not in e8addr or incap != int(e8addr[a]['att_v']):
            bad.append(a)
    return dict(ok=not bad, mismatches=len(bad), first=bad[:5])


def monotone(values):
    """True when every consecutive pair is non-decreasing (None breaks the chain)."""
    xs = list(values)
    return all(xs[i] is not None and xs[i + 1] is not None and xs[i + 1] >= xs[i] for i in range(len(xs) - 1))


# ---------------------------------------------------------------- lists and baselines

def load_list(path, addresses):
    """Per address: (blocks, values) of every row of the list (list order = block order)."""
    per = {a: ([], []) for a in addresses}
    with open(path, newline='') as f:
        rd = csv.reader(f)
        head = next(rd)
        ib, ia, iv = head.index('block_number'), head.index('recipient'), head.index('value_atomic')
        for row in rd:
            a = row[ia].lower()
            if a in per:
                per[a][0].append(int(row[ib]))
                per[a][1].append(int(row[iv]))
    return {a: (np.array(b, dtype=np.int64), np.array(v, dtype=np.int64)) for a, (b, v) in per.items()}


def slide_max(blocks, values, lf):
    """Largest value sum and largest count of a window (t - lf, t], t a sale block, same-block sales included."""
    if len(blocks) == 0:
        return 0, 0
    pre = np.r_[0, np.cumsum(values)]
    hi = np.searchsorted(blocks, blocks, side='right')
    lo = np.searchsorted(blocks, blocks - lf, side='right')
    return int((pre[hi] - pre[lo]).max()), int((hi - lo).max())


def e8b_addr(docs, w, v):
    return {r['address']: r for r in read_csv(Path(docs) / E8B_DIR / f'e8_addr_{w}_v{v}_lf{LF7}.csv')}


def e8b_rows(docs, w, v):
    out = {}
    for r in read_csv(Path(docs) / E8B_DIR / f'e8_rows_{w}_v{v}_lf{LF7}.csv'):
        if r['baseline'] == 'B':
            out[(r['address'], r['m'])] = r
    return out


def baselines(run, lists_w, e8addr, v, lf):
    """Per address: C^M, C^W, C^Wn at L_F^11 over the replay's sale set (sales above V included when the run admits
    them), C^B(m) from the E8b 14-day bucket fit at L_F^11, and the reference C^M, C^W of E8b (L_F 29,454)."""
    vmax, b = VMAX[v], B11[v]
    over = run['cfg']['accept_over_cap']
    rate_blocks = run['meta']['rate_blocks']
    out = {}
    for a, r in run['rows'].items():
        blocks, values = lists_w[a]
        keep = np.ones(len(values), bool) if over else values <= vmax
        Wv, Wn = slide_max(blocks[keep], values[keep], lf)
        acc_v = inum(r['accepted_value'])
        e = e8addr[a]
        rec = dict(CM=b + Fraction(acc_v * lf, rate_blocks), CW=b + Wv, CWn=b + Wn * vmax, W_v=Wv, W_n=Wn,
                   CM_lf7=b + Fraction(int(e['att_v']) * LF7, rate_blocks), CW_lf7=b + int(e['W_v']))
        qq, rr, nn = int(e['q']), int(e['r']), int(e['n'])
        for m, mn in zip(MARGINS, MARGIN_NAMES):
            cap = math.floor(m * qq * nn * 10 ** 6)
            rate = math.floor(m * rr * nn)
            rec[f'CB|{mn}'] = b + (-(-(cap + rate * lf) // 10 ** 6)) * vmax
        out[a] = rec
    return out


def make_sets(rows_main, stored):
    """Address sets (registration 3): S1 by the stored edition-7 scale, S3 without the stored largest revenue,
    S1a and S2a by the run's attempts, S1r by the run's revenue."""
    scale = {a: inum(stored[a]['scale']) if stored[a]['scale'] != '' else 1 for a in rows_main}
    accv7 = {a: inum(stored[a]['accepted_value']) for a in rows_main}
    att = {a: inum(r['attempted_count']) for a, r in rows_main.items()}
    rev = {a for a, r in rows_main.items() if is_true(r.get('has_revenue')) or inum(r['accepted_value']) > 0}
    s1 = {a for a in rows_main if scale[a] <= SCALE_ANCHOR}
    s2 = set(rows_main)
    s3 = s1 - {max(s1, key=lambda a: accv7[a])} if s1 else set()
    return {'S1r': s1 & rev, 'S1': s1, 'S2': s2, 'S3': s3, 'S1a': {a for a in s1 if att[a] > 0},
            'S2a': {a for a in s2 if att[a] > 0}}


def lock_money(run, sets, v, base, rej, hcol):
    """Section 6.1 for one held-money column: per set P_FB, held, L_FB, the ratios, the B(m) cells, references."""
    b = B11[v]
    H = {a: num(r[hcol]) for a, r in run['rows'].items()}
    out = {}
    for sname in SETS:
        S = sets[sname]
        n = len(S)
        P = n * b / 1e6
        held = sum(H[a] for a in S) / 1e6
        L = P + held
        CM = float(sum(base[a]['CM'] for a in S)) / 1e6
        CW = sum(base[a]['CW'] for a in S) / 1e6
        CWn = sum(base[a]['CWn'] for a in S) / 1e6
        CM7 = float(sum(base[a]['CM_lf7'] for a in S)) / 1e6
        CW7 = sum(base[a]['CW_lf7'] for a in S) / 1e6
        rec = dict(n=n, P_FB=P, held=held, L_FB=L, sumC_M=CM, sumC_W=CW, sumC_Wn=CWn,
                   rhoL_M=L / CM if CM else None, rhoL_W=L / CW if CW else None, rhoL_Wn=L / CWn if CWn else None,
                   rhoP_M=P / CM if CM else None, rhoP_W=P / CW if CW else None,
                   ref_lf29454=dict(sumC_M=CM7, sumC_W=CW7, rhoL_M=L / CM7 if CM7 else None,
                                    rhoL_W=L / CW7 if CW7 else None),
                   n_addr_L_gt_M=sum(1 for a in S if b + H[a] > base[a]['CM']),
                   n_addr_L_gt_W=sum(1 for a in S if b + H[a] > base[a]['CW']))
        cells = {}
        for mn in MARGIN_NAMES:
            sumC = sum(base[a][f'CB|{mn}'] for a in S) / 1e6
            rv = sum(int(rej[(a, mn)]['rej_v']) for a in S if (a, mn) in rej)
            av = sum(int(rej[(a, mn)]['att_v']) for a in S if (a, mn) in rej)
            cells[f'B|{mn}'] = dict(sumC=sumC, rhoL_same_upper=L / sumC if sumC else None,
                                    rej_share_v_incap=rv / av if av else None,
                                    n_addr_L_gt_C=sum(1 for a in S if b + H[a] > base[a][f'CB|{mn}']))
        rec['cells'] = cells
        out[sname] = rec
    return out


# ---------------------------------------------------------------- hold lengths, acceptance, thresholds, cost

def hold_distribution(run, S):
    rows = [run['rows'][a] for a in S if inum(run['rows'][a]['accepted_count']) > 0]
    hist = np.zeros(len(HIST_EDGES), dtype=np.int64)
    n_rel = 0
    w_sum = v_sum = c_sum = 0.0
    open_n = open_v = 0
    for r in rows:
        if r.get('hold_histogram'):
            h = np.array(json.loads(r['hold_histogram']), dtype=np.int64)
            hist[:len(h)] += h[:len(hist)]
        k = inum(r['hold_released_count'])
        n_rel += k
        if r['hold_mean'] != '':
            c_sum += num(r['hold_mean']) * k
        rel_v = inum(r['accepted_value']) - inum(r['hold_open_value'])
        if r['hold_value_mean'] != '':
            w_sum += num(r['hold_value_mean']) * rel_v
            v_sum += rel_v
        open_n += inum(r['hold_open_count'])
        open_v += inum(r['hold_open_value'])
    per = lambda c: [num(r[c]) for r in rows if r[c] != '']  # noqa: E731
    tot = hist.sum()
    return dict(sellers=len(rows), released=n_rel, open_count=open_n, open_value=open_v / 1e6,
                mean_blocks=c_sum / n_rel if n_rel else None, value_mean_blocks=w_sum / v_sum if v_sum else None,
                histogram_edges=HIST_EDGES, histogram=hist.tolist(),
                share_lt_2000=float(hist[:2].sum() / tot) if tot else None,
                share_lt_2600=float(hist[:3].sum() / tot) if tot else None,
                seller_p50_median=q(per('hold_p50'), 50), seller_p90_median=q(per('hold_p90'), 50),
                seller_p90_q90=q(per('hold_p90'), 90), seller_max_max=max(per('hold_max')) if per('hold_max') else None,
                seller_value_mean_median=q(per('hold_value_mean'), 50),
                seller_value_mean_q90=q(per('hold_value_mean'), 90))


def buyer_counts(run, S):
    rows = [run['rows'][a] for a in S]
    g = lambda c: sum(inum(r.get(c, '')) for r in rows)  # noqa: E731
    acc_n = g('accepted_count')
    return dict(accepted=acc_n, accepted_value=g('accepted_value') / 1e6, buyer_accepted=g('buyer_accepted_count'),
                buyer_accepted_value=g('buyer_accepted_value') / 1e6,
                buyer_accepted_share=g('buyer_accepted_count') / acc_n if acc_n else None,
                unsigned=g('unsigned_count'), sampled=g('sample_count'), sampled_accepted=g('sampled_accepted_count'),
                over_cap_accepted=g('over_cap_accepted_count'), over_cap_accepted_value=g('over_cap_accepted_value') / 1e6,
                incap_accepted_value=(g('accepted_value') - g('over_cap_accepted_value')) / 1e6)


def thresholds(run, v):
    """Section 6.8: sellers whose revenue over one hold is at least b, and whose largest held sum is at least b."""
    b = B11[v]
    rev = [r for r in run['rows'].values() if inum(r['accepted_value']) > 0]
    if not rev:
        return {}
    tot = sum(inum(r['accepted_value']) for r in rev)
    big = max(rev, key=lambda r: inum(r['accepted_value']))
    out = {}
    for name, pick in (('mean', lambda r: num(r['revenue_per_hold']) >= b), ('largest', lambda r: num(r['H_max']) >= b)):
        sel = [r for r in rev if pick(r)]
        sv = sum(inum(r['accepted_value']) for r in sel)
        ex = sv - (inum(big['accepted_value']) if big in sel else 0)
        rest = tot - inum(big['accepted_value'])
        out[name] = dict(count=len(sel), of=len(rev), share_sellers=len(sel) / len(rev), revenue_share=sv / tot,
                         revenue_share_without_largest=ex / rest if rest else None)
    return out


def capital_cost(hold_blocks):
    return [r * hold_blocks * 2 / (365 * 86_400) for r in SUPPLY_RATES]


# ---------------------------------------------------------------- fraud replay

def fraud(raw):
    """Both fraud replays: summary.json with its release record checked against the expected one."""
    out = {}
    for name, (sub, expect, cap) in FRAUD.items():
        d = Path(raw) / sub
        s = d / 'summary.json'
        if not s.exists():
            out[name] = dict(problems=['no fraud replay output'])
            continue
        summary = json.loads(s.read_text())
        problems = []
        got = dict(summary.get('release10') or {})
        want = {k: v for k, v in expect.items() if k != 'mode'}
        if got != want:
            problems.append(f'release10 {got} differs from the expected {want} (G5)')
        ex = d / 'exact_expectation.json'
        if ex.exists():
            sales_cap = json.loads(ex.read_text()).get('sales_cap')
            if sales_cap != cap:
                problems.append(f'sales cap {sales_cap} is not {cap} (G5)')
        if summary.get('R') != 500:
            problems.append(f"R = {summary.get('R')} is not the registered 500 (G5)")
        out[name] = dict(summary=summary, problems=problems)
    return out


# ---------------------------------------------------------------- k sweep (6.5)

def k_table(raw, w, code_commit, n_addresses, sets, lists_w, e8addr, rej, main_run):
    """Per k: the held money and the hold lengths over S1r and S1, the ratios to k = 1, the monotonicity check (G4),
    the equality of k = 1 with the main V 0.2 run."""
    out = dict(k=list(KS), per_k={}, problems=[])
    base_dir = Path(raw) / f'{w}_ksweep'
    sw = base_dir / 'k_sweep.json'
    out['k_sweep_json'] = sw.exists()
    runs = {}
    for k in KS:
        expect = dict(BASE, seller_epoch_k=k)
        run, prob = load_condition(base_dir / f'k{k}', expect, code_commit, 'unlimited', n_addresses)
        if run is None or prob:
            out['per_k'][str(k)] = dict(problems=prob)
            continue
        sales, addrs = load_sales(run)
        g4 = gate_cont_average(run, sales, addrs)
        if not g4['ok']:
            out['per_k'][str(k)] = dict(problems=['continuous average numerator differs from sales.npz (G4)'])
            continue
        runs[k] = run
        rec = dict(L_F11=lf11(BASE, k), sales_sha256=sha256(run['cdir'] / 'sales.npz'))
        for lag_name, lf in (('lag_k', lf11(BASE, k)), ('lag_k1', lf11(BASE, 1))):
            base = baselines(run, lists_w, e8addr, '0.2', lf)
            rec[lag_name] = {}
            for hname, hcol in HDEFS.items():
                lock = lock_money(run, sets, '0.2', base, rej, hcol)
                rec[lag_name][hname] = {s: {kk: lock[s][kk] for kk in ('n', 'held', 'L_FB', 'sumC_M', 'sumC_W',
                                                                       'rhoL_M', 'rhoL_W')}
                                        for s in ('S1r', 'S1')}
        rec['hold'] = {s: hold_distribution(run, sets[s]) for s in ('S1r', 'S1')}
        out['per_k'][str(k)] = rec
    if 1 in runs and main_run is not None:
        same = gate_same_rows(runs[1]['rows'], main_run['rows'], ('accepted_count', 'accepted_value', 'sample_count',
                                                                   'H_cont_sum_blocks'), ('H_time_average',))
        out['k1_equals_main'] = same
        if not same['ok']:
            out['problems'].append('k = 1 run differs from the main V 0.2 run')
    ks = [k for k in KS if k in runs]
    out['reported_k'] = ks
    mono = {}
    for hname in HDEFS:
        for s in ('S1r', 'S1'):
            mono[f'{hname}|{s}'] = monotone(out['per_k'][str(k)]['lag_k'][hname][s]['held'] for k in ks)
    per_addr = all(all(int(runs[ks[i + 1]]['rows'][a]['H_cont_sum_blocks']) >= int(runs[ks[i]]['rows'][a]['H_cont_sum_blocks'])
                       for a in runs[ks[i]]['rows']) for i in range(len(ks) - 1)) if len(ks) > 1 else True
    mono['per_address_H_cont_sum_blocks'] = per_addr
    out['monotone'] = mono
    if not all(mono.values()):
        out['problems'].append('held money is not non-decreasing in k (G4)')
    if 1 in runs:
        for k in ks:
            for s in ('S1r', 'S1'):
                h1 = out['per_k']['1']['lag_k'][MAIN_HDEF][s]['held']
                hk = out['per_k'][str(k)]['lag_k'][MAIN_HDEF][s]['held']
                out['per_k'][str(k)].setdefault('ratio_to_k1', {})[s] = hk / h1 if h1 else None
    return out


# ---------------------------------------------------------------- verdicts (section 8)

def verdicts(R):
    """JA11, JD11, JM11 on S1r, V 0.2, the main held-money definition; JX11 on the main fraud replay. JM11 needs
    the independent check on the same side of 1, so the replay side is reported and the final verdict left open."""
    v = {}
    win = [w for w in WINDOWS if R['main'][w].get('reportable_0.2')]
    lk = {w: R['main'][w]['V']['0.2']['lock'][MAIN_HDEF][JUDGEMENT_SET] for w in win}
    v['windows'] = win
    v['judgement_set'] = JUDGEMENT_SET
    v['held_money_definition'] = HDEFS[MAIN_HDEF]
    v['JA11'] = dict(cells={f'{w}|{m}': lk[w]['cells'][f'B|{m}']['rhoL_same_upper'] for w in win for m in MARGIN_NAMES})
    v['JA11']['holds'] = bool(win) and all(x is not None and x < 1 for x in v['JA11']['cells'].values())
    v['JD11'] = dict(rhoL_W={w: lk[w]['rhoL_W'] for w in win}, rhoP_W={w: lk[w]['rhoP_W'] for w in win})
    v['JD11']['holds'] = bool(win) and all(x is not None and x < 1 for x in v['JD11']['rhoL_W'].values())
    v['JM11'] = dict(rhoL_M={w: lk[w]['rhoL_M'] for w in win},
                     rhoL_M_S1={w: R['main'][w]['V']['0.2']['lock'][MAIN_HDEF]['S1']['rhoL_M'] for w in win},
                     rhoL_M_other_definitions={h: {w: R['main'][w]['V']['0.2']['lock'][h][JUDGEMENT_SET]['rhoL_M']
                                                  for w in win} for h in HDEFS if h != MAIN_HDEF})
    v['JM11']['holds_replay'] = bool(win) and all(x is not None and x < 1 for x in v['JM11']['rhoL_M'].values())
    v['JM11']['holds'] = None
    v['JM11']['final'] = 'open until r11_check.py reports the same side of 1 (registration 8.2, 11)'
    fr = R.get('fraud', {}).get('main', {})
    s = fr.get('summary', {}).get('r10') if not fr.get('problems') else None
    if s:
        v['JX11'] = dict(above_3se=s['above_3se'], max_mean=s['max_mean'], max_exact=s.get('max_exact'),
                         holds=s['above_3se'] == 0 and s.get('max_exact') is not None and s['max_exact'] <= UPPER_X)
    else:
        v['JX11'] = dict(holds=None, reason=fr.get('problems') or ['no fraud replay output'])
    fv = R.get('fraud', {}).get('r10style', {})
    sv = fv.get('summary', {}).get('r10') if not fv.get('problems') else None
    v['JX11']['r10style_variant'] = dict(above_3se=sv['above_3se'], max_mean=sv['max_mean'],
                                         max_exact=sv.get('max_exact')) if sv else None
    count = total = 0
    for w in WINDOWS:
        for x in VS:
            lock = R['main'][w]['V'].get(x, {}).get('lock')
            if not lock:
                continue
            for hname in HDEFS:
                for sname in SETS:
                    rec = lock[hname][sname]
                    vals = [c['rhoL_same_upper'] for c in rec['cells'].values()] + [rec['rhoL_M'], rec['rhoL_W']]
                    total += len(vals)
                    count += sum(1 for y in vals if y is not None and y >= 1)
    v['cells_rho_ge_1'] = dict(count=count, total=total)
    return v


# ---------------------------------------------------------------- tables

def fmt(x, d=4):
    return 'NA' if x is None else f'{x:.{d}f}'


def tables(R):
    L = ['# R11 result tables (written by r11_compute.py)', '',
         f'Judgement set {JUDGEMENT_SET}; main held-money definition `{HDEFS[MAIN_HDEF]}`; b = V / s, s = 1.', '']
    for w in WINDOWS:
        W = R['main'][w]
        L.append(f'## main, {w}')
        if not W.get('reportable_0.2'):
            L.append(f'- V 0.2 not reportable: {"; ".join(W.get("problems_0.2", []))}')
        for v in VS:
            x = W['V'].get(v, {})
            if not x.get('lock'):
                L.append(f'- V {v}: not reportable ({"; ".join(x.get("problems", []))})')
                continue
            L.append(f'### V {v} (b = {B11[v] / 1e6:.6f} USDC, L_F^11 = {x["L_F11"]})')
            for hname, hcol in HDEFS.items():
                L.append(f'#### held money `{hcol}`' + (' (main)' if hname == MAIN_HDEF else ' (reference)'))
                L.append('| set | n | P_FB | held | L_FB | sum C^M | rho_L^M | sum C^W | rho_L^W | rho_L^Wn | rho_P^M | '
                         'rho_P^W | ref rho_L^M (29,454) | ref rho_L^W (29,454) |')
                L.append('|---|---|---|---|---|---|---|---|---|---|---|---|---|---|')
                for s in SETS:
                    k = x['lock'][hname][s]
                    L.append(f"| {s} | {k['n']} | {k['P_FB']:.2f} | {k['held']:.2f} | {k['L_FB']:.2f} | {k['sumC_M']:.2f} | "
                             f"{fmt(k['rhoL_M'])} | {k['sumC_W']:.2f} | {fmt(k['rhoL_W'])} | {fmt(k['rhoL_Wn'])} | "
                             f"{fmt(k['rhoP_M'])} | {fmt(k['rhoP_W'])} | {fmt(k['ref_lf29454']['rhoL_M'])} | "
                             f"{fmt(k['ref_lf29454']['rhoL_W'])} |")
                L.append('')
            L.append(f'| B(m) | sum C^B ({JUDGEMENT_SET}) | rho_L upper | in-cap rejected share | n(b+H>C) |')
            L.append('|---|---|---|---|---|')
            for key, c in x['lock'][MAIN_HDEF][JUDGEMENT_SET]['cells'].items():
                L.append(f"| {key} | {c['sumC']:.2f} | {fmt(c['rhoL_same_upper'])} | {fmt(c['rej_share_v_incap'])} | "
                         f"{c['n_addr_L_gt_C']} |")
            hd = x['hold'][JUDGEMENT_SET]
            L.append('')
            L.append(f"Hold lengths {JUDGEMENT_SET}: value-weighted mean {fmt(hd['value_mean_blocks'], 0)} blocks, count mean "
                     f"{fmt(hd['mean_blocks'], 0)}, median seller p50 {hd['seller_p50_median']}, median seller p90 "
                     f"{hd['seller_p90_median']}, max {hd['seller_max_max']}, share below 2,000 {fmt(hd['share_lt_2000'])}, "
                     f"below 2,600 {fmt(hd['share_lt_2600'])}, open at the end {hd['open_count']} sales")
            L.append(f"Thresholds: {json.dumps(x['thresholds'])}")
            L.append('')
    L.append('## acceptance and sensitivities (V 0.2)')
    L.append(f'| config | window | reportable | {JUDGEMENT_SET} held (main) | L_FB | rho_L^M | rho_L^W | S1 rho_L^M | '
             'value-weighted hold | buyer-accepted share |')
    L.append('|---|---|---|---|---|---|---|---|---|---|')
    for cname in CONFIGS:
        for w in WINDOWS:
            x = R['main'][w]['V'].get('0.2', {}) if cname == 'main' else R['configs'].get(cname, {}).get(w, {})
            if not x.get('lock'):
                L.append(f'| {cname} | {w} | no | | | | | | | |')
                continue
            k, k1 = x['lock'][MAIN_HDEF][JUDGEMENT_SET], x['lock'][MAIN_HDEF]['S1']
            L.append(f"| {cname} | {w} | yes | {k['held']:.2f} | {k['L_FB']:.2f} | {fmt(k['rhoL_M'])} | {fmt(k['rhoL_W'])} | "
                     f"{fmt(k1['rhoL_M'])} | {fmt(x['hold'][JUDGEMENT_SET]['value_mean_blocks'], 0)} | "
                     f"{fmt(x['buyer'][JUDGEMENT_SET]['buyer_accepted_share'])} |")
    L.append('')
    L.append('## seller epoch multiple k (V 0.2)')
    L.append(f'| window | k | L_F^11(k) | {JUDGEMENT_SET} held (main) | ratio to k = 1 | rho_L^M (lag k) | rho_L^M (lag k = 1) | '
             'rho_L^W (lag k) | value-weighted hold | median seller p90 | max hold |')
    L.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for w in WINDOWS:
        K = R.get('k', {}).get(w)
        if not K or 'per_k' not in K:
            L.append(f'- {w}: not reportable ({"; ".join((K or {}).get("problems", []))})')
            continue
        for k in KS:
            rec = K['per_k'].get(str(k), {})
            if 'problems' in rec:
                L.append(f'| {w} | {k} | not reportable: {"; ".join(rec["problems"])} | | | | | | | | |')
                continue
            a, a1 = rec['lag_k'][MAIN_HDEF][JUDGEMENT_SET], rec['lag_k1'][MAIN_HDEF][JUDGEMENT_SET]
            hd = rec['hold'][JUDGEMENT_SET]
            L.append(f"| {w} | {k} | {rec['L_F11']} | {a['held']:.2f} | {fmt(rec.get('ratio_to_k1', {}).get(JUDGEMENT_SET))} | "
                     f"{fmt(a['rhoL_M'])} | {fmt(a1['rhoL_M'])} | {fmt(a['rhoL_W'])} | {fmt(hd['value_mean_blocks'], 0)} | "
                     f"{hd['seller_p90_median']} | {hd['seller_max_max']} |")
        L.append(f'- {w}: monotone {json.dumps(K["monotone"])}; problems {K["problems"]}')
    L.append('')
    L.append('## verdicts')
    L.append('```')
    L.append(json.dumps(R['verdicts'], indent=1, ensure_ascii=False))
    L.append('```')
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- one configuration

def evaluate(run, sets, lists_w, e8addr, rej, v, out, cname, w):
    lf = lf11(run['cfg'])
    base = baselines(run, lists_w, e8addr, v, lf)
    X = dict(L_F11=lf, lock={h: lock_money(run, sets, v, base, rej, col) for h, col in HDEFS.items()},
             hold={s: hold_distribution(run, sets[s]) for s in ('S1r', 'S1', 'S2')},
             buyer={s: buyer_counts(run, sets[s]) for s in ('S1r', 'S1', 'S2')}, thresholds=thresholds(run, v),
             sales_sha256=sha256(run['cdir'] / 'sales.npz'))
    for s in ('S1r', 'S1', 'S2'):
        vm = X['hold'][s]['value_mean_blocks']
        X['hold'][s]['capital_cost'] = capital_cost(vm) if vm else None
    (out / f'r11_addr_{cname}_{w}_v{v}.csv').write_bytes((run['cdir'] / 'addresses_observed.csv').read_bytes())
    return X


def stored_rows(docs, w, v):
    spec = STORED.get((w, v))
    if spec is None:
        return None, 'no stored edition-7 output registered'
    path = Path(docs) / spec[0] / 'condition-01-seed-0' / 'addresses_observed.csv'
    if not path.exists():
        return None, f'stored output missing: {path}'
    if sha256(path) != spec[1]:
        return None, 'stored output hash differs'
    return {r['address']: r for r in read_csv(path)}, None


def r10_aggregate(docs, w):
    """R10 overcap per-address aggregate of V 0.2, checked against R10's SHA256SUMS.txt."""
    d = Path(docs) / R10_RESULTS_DIR
    name = f'r10_addr_overcap_{w}_v0.2.csv'
    sums = d / 'SHA256SUMS.txt'
    if not (d / name).exists() or not sums.exists():
        return None, 'R10 overcap aggregate missing'
    want = {line.split()[1].lstrip('*'): line.split()[0] for line in sums.read_text().splitlines() if line.strip()}
    if want.get(name) != sha256(d / name):
        return None, 'R10 overcap aggregate hash differs from SHA256SUMS.txt'
    return {r['address']: r for r in read_csv(d / name)}, None


def gates_of_run(run, e8addr, main_sales=None):
    """G2, G4 and G6 of one run; returns (gates, problems)."""
    g = {}
    prob = []
    sales, addrs = load_sales(run)
    g['G4_cont_average'] = gate_cont_average(run, sales, addrs)
    if not g['G4_cont_average']['ok']:
        prob.append('continuous average numerator differs from sales.npz (G4)')
    g['G6_e8b_att'] = gate_e8b_att(run, e8addr)
    if not g['G6_e8b_att']['ok']:
        prob.append('in-cap accepted value differs from E8b att_v (G6)')
    if run['cfg'] is not None and run['meta'].get('admission') == ['unlimited']:
        g['G2_admission'] = gate_main_admission(run)
        if not g['G2_admission']['ok']:
            prob.append('admission is not unlimited for every address (G2)')
    if main_sales is not None:
        g['G2_sampled_flags'] = gate_sampled_flags(main_sales, sales)
        if not g['G2_sampled_flags']['ok']:
            prob.append('sample draws differ from the main run on common sales (G2)')
    return g, prob, sales


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--raw', required=True)
    ap.add_argument('--lists', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--code-commit', required=True)
    ap.add_argument('--docs', required=True, help='the research repository docs/ (stored outputs, E8b, R10 aggregates)')
    ap.add_argument('--registration', required=True, help='the sealed R11_preregistration.md (its .sha256 beside it)')
    ap.add_argument('--addresses', type=int, default=415, help='expected address count per window (default 415)')
    a = ap.parse_args(argv)
    docs = Path(a.docs)
    R = dict(registration_sha256=gate_registration(a.registration), code_commit=a.code_commit, b_atomic=B11,
             anchor_delay=ANCHOR_DELAY, held_money_definitions=HDEFS, main_definition=MAIN_HDEF,
             judgement_set=JUDGEMENT_SET)
    if sha256(docs / E8B_RESULTS[0]) != E8B_RESULTS[1]:
        raise SystemExit('E8b results hash differs from the registered one (G6)')
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sales_hashes = []
    R['main'], R['configs'], R['k'] = {}, {c: {} for c in CONFIGS if c != 'main'}, {}
    for w in WINDOWS:
        W = R['main'][w] = dict(V={}, L_F11=lf11(BASE))
        run02, p02 = load_run(a.raw, w, 'main', '0.2', a.code_commit, a.addresses)
        stored, sp = stored_rows(docs, w, '0.2')
        if run02 is None or stored is None or set(stored) != set(run02['rows']):
            W['reportable_0.2'] = False
            W['problems_0.2'] = p02 + ([sp] if sp else []) + \
                (['stored addresses differ from the run'] if run02 and stored and set(stored) != set(run02['rows']) else [])
            for c in R['configs']:
                R['configs'][c][w] = dict(problems=['no main V 0.2 output or stored output: the sets cannot be defined'])
            R['k'][w] = dict(problems=['no main V 0.2 output or stored output'])
            continue
        sets = make_sets(run02['rows'], stored)
        W['set_sizes'] = {k: len(s) for k, s in sets.items()}
        lists_w = load_list(Path(a.lists) / LISTS[w], set(run02['rows']))
        main_sales = None
        for v in VS:
            run, prob = load_run(a.raw, w, 'main', v, a.code_commit, a.addresses)
            X = W['V'][v] = {}
            if run is None:
                X['problems'] = prob
                if v == '0.2':
                    W['reportable_0.2'] = False
                    W['problems_0.2'] = prob
                continue
            e8addr = e8b_addr(docs, w, v)
            gates, gprob, sales = gates_of_run(run, e8addr)
            X.update(gates)
            prob = prob + gprob
            if v == '0.2':
                main_sales = sales
                W['reportable_0.2'] = not prob
                W['problems_0.2'] = prob
            if prob:
                X['problems'] = prob
                continue
            X.update(evaluate(run, sets, lists_w, e8addr, e8b_rows(docs, w, v), v, out, 'main', w))
            sales_hashes.append((f'main/{w}/v{v}', X['sales_sha256']))
        e8addr02, rej02 = e8b_addr(docs, w, '0.2'), e8b_rows(docs, w, '0.2')
        other = {}
        for cname in R['configs']:
            run, prob = load_run(a.raw, w, cname, '0.2', a.code_commit, a.addresses)
            X = R['configs'][cname][w] = {}
            if run is None:
                X['problems'] = prob
                continue
            gates, gprob, _ = gates_of_run(run, e8addr02, main_sales if W.get('reportable_0.2') else None)
            X.update(gates)
            prob = prob + gprob
            other[cname] = run
            if cname == 'r10equiv':
                agg, ap_ = r10_aggregate(docs, w)
                if agg is None:
                    X['G2_r10_overcap'] = dict(ok=False, reason=ap_)
                else:
                    X['G2_r10_overcap'] = gate_same_rows(run['rows'], agg, SAME_COLUMNS, ('H_time_average',))
                if not X['G2_r10_overcap']['ok']:
                    prob = prob + ['R10-equivalent variant differs from the R10 overcap aggregate (G2)']
            if prob:
                X['problems'] = prob
                continue
            X.update(evaluate(run, sets, lists_w, e8addr02, rej02, '0.2', out, cname, w))
            sales_hashes.append((f'{cname}/{w}/v0.2', X['sales_sha256']))
        if 'legacy' in other and 'r10equiv' in other:
            same = gate_same_rows(other['legacy']['rows'], other['r10equiv']['rows'], SAME_COLUMNS)
            R['configs']['legacy'][w]['G2_same_admission_as_r10equiv'] = same
            if not same['ok']:
                R['configs']['legacy'][w].setdefault('problems', []).append(
                    'legacy-bucket admission differs from the R10-equivalent variant (G2)')
                R['configs']['legacy'][w].pop('lock', None)
        R['k'][w] = k_table(a.raw, w, a.code_commit, a.addresses, sets, lists_w, e8addr02, rej02,
                            run02 if W.get('reportable_0.2') else None)
        for k, rec in R['k'][w]['per_k'].items():
            if 'sales_sha256' in rec:
                sales_hashes.append((f'ksweep/{w}/k{k}', rec['sales_sha256']))
        with open(out / f'r11_k_{w}.csv', 'w', newline='') as f:
            wr = csv.writer(f, lineterminator='\n')
            wr.writerow(['k', 'set', 'L_F11', 'definition', 'held', 'L_FB', 'sumC_M', 'sumC_W', 'rhoL_M', 'rhoL_W',
                         'rhoL_M_lag_k1', 'value_mean_blocks', 'seller_p90_median', 'seller_max_max'])
            for k, rec in R['k'][w]['per_k'].items():
                if 'problems' in rec:
                    continue
                for s in ('S1r', 'S1'):
                    for h in HDEFS:
                        x, x1 = rec['lag_k'][h][s], rec['lag_k1'][h][s]
                        hd = rec['hold'][s]
                        wr.writerow([k, s, rec['L_F11'], HDEFS[h], x['held'], x['L_FB'], x['sumC_M'], x['sumC_W'],
                                     x['rhoL_M'], x['rhoL_W'], x1['rhoL_M'], hd['value_mean_blocks'],
                                     hd['seller_p90_median'], hd['seller_max_max']])
    R['fraud'] = fraud(a.raw)
    R['verdicts'] = verdicts(R)
    (out / 'r11_sales_sha256.txt').write_text(''.join(f'{h}  {n}\n' for n, h in sales_hashes))
    (out / 'r11_results.json').write_text(json.dumps(R, indent=1, ensure_ascii=False, default=float))
    (out / 'r11_tables.md').write_text(tables(R))
    print(json.dumps(R['verdicts'], indent=1, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
