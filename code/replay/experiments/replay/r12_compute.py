#!/usr/bin/env python3
"""Aggregation of the R12 replay (registration R12_preregistration.md in the research repository): FairBind in the cost
setting (V 1, seller epoch multiple k in {1, 2, 4, 8, 16, 32}, a per-seller k) against deployable bonds.

    r12_compute.py check-registration --registration REG
    r12_compute.py print-flags --registration REG --kind cost|bridge
    r12_compute.py selfcheck --registration REG --work DIR
    r12_compute.py compute --registration REG --raw RAW --lists LISTS --docs DOCS --out OUT --code-commit HEAD

Every number the registration fixes is in one fenced block of the registration (info string `json r12-registered`).
The block and the constant REGISTERED below must be equal key by key (`check-registration`); every command starts with
that check, and `print-flags` hands the replay flags of the block to run_r12.sh, so the replay, the expectations of
the gates and the registration share one source. Records are compared whole (`compare_record`): no key of an
expected record or of a written record is skipped (the R11 aggregation skipped `mode` on one side, JX11).

Comparators (registration sections 5 and 6), per address i over the replayed sale set (all settled sales of i,
sales above V included), with the judgement lag L_i:
  history bond   B^H_i(t) = h * C_i(d(t)) * L_i / 43,200, C_i(d) the largest daily revenue of i over the 14 UTC days
                 before day d (the prior window counts); 0 without history
  rate-cap bond  B^R_i = rho_i * L_i / 43,200, rho_i = h * C_i(prior) declared at the window start, rho_0 (the median
                 declared rate of the addresses with a prior history) without one; variant u admits every sale, variant
                 r rejects a sale that would lift the admitted revenue of (t - L_i, t] above B^R_i
  ceiling        C^M_i = b + R_i * L_i / rate_blocks (R11), R_i the window revenue
Exposure E_i(t) = revenue of i settled in (t - L_i, t]; uncovered U_i(t) = max(0, E_i(t) - B_i(t)); per-seller worst
X_i = max_t U_i(t) over the averaging blocks [first + 31,073, last]; time averages over the same blocks. FairBind's
exposure is the bound of theorem 1, V / s = V per seller (s = 1); the replay also counts V times the time-averaged
number of sellers with a held sale. Only numpy beyond the standard library; integer arithmetic where the registration
asks for exact values.
"""
import argparse
import csv
import hashlib
import json
import math
import sys
from collections import deque
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FENCE = '```json r12-registered'

# The registered block, copied into the registration (section 15) and checked against it before anything runs.
REGISTERED = {
    "registration": "R12",
    "windows": ["median", "busy"],
    "lists": {
        "median": {"file": "median/settlements_base_2026-07-24_2026-08-13.csv",
                   "sha256": "091476280d744b7cd932c06beabf35d3d96d382ecb0d69bfb0383200a709052a"},
        "busy": {"file": "busy/settlements_base_2026-06-09_2026-06-29.csv",
                 "sha256": "91412e264212412afcd4ecdd21e7ca7d98ce7ab8522572fdabef756e6fa10133"}},
    "prior_lists": {
        "median": {"file": "median/settlements_base_prior_2026-07-10_2026-07-23.csv",
                   "sha256": "5f701f738aae2cbcb935443e1545aa61d470325bcfceff2a2520f06bac2d9486",
                   "rows": 5648702, "first_date": "2026-07-10", "last_date": "2026-07-23"},
        "busy": {"file": "busy/settlements_base_prior_2026-05-26_2026-06-08.csv",
                 "sha256": "617c9a753bdd331b0c5f2e4f83565cf8789f486fe4105ca3bc00551f0e2e4e21",
                 "rows": 1178201, "first_date": "2026-05-26", "last_date": "2026-06-08"}},
    "addresses": 415,
    "inputs": {
        "raw_dirs": {"median": {"window": "S1b_median-window", "prior": "S1b_prior14_median-window"},
                     "busy": {"window": "S1b_busy-window", "prior": "S1c_busy-window-prior14"}},
        "manifests": {"S1b_median-window": "1f48d314055fa8bf0e92cb8e118975287d55f4ab7ac0a917e0e1104922e84923",
                      "S1b_busy-window": "90371183d2bfcad691db4ab7d886754010f876eda4e794f72ca0ff55bc72d7e1",
                      "S1b_prior14_median-window": "de6d3c313f1937db69474573ea5a3afa1c127600d4b684ae3af39d73c5262941",
                      "S1c_busy-window-prior14": "e5d68f67636a831cbfc161403a25201b5e9b4b74cee509c261a4af73f7d17f4d"},
        "conditions": {"median": {"path": "05_run-evidence/design2/median-period/in/conditions_base_median.json",
                                  "sha256": "5e58da679e9dcf8d04ab0f750d955cde95156a66900b910e614f42840ac56e8c"},
                       "busy": {"path": "11_journal/J9/in/conditions_base_busy.json",
                                "sha256": "b55539d65c52addd93a79e994c041ad4370a626f506423f91d4017d5a3481936"}},
        "reference_dir": "11_journal/J9/in/ref",
        "reference": {"sellers_dune_top400.csv": "3f255ef8174bf502cbc1f7d14e6ec84a011f6d5e8599779b11cd04e5c9bcae91",
                      "sellers_dune_all4400.csv": "bb7ee6f57f87b990b665fb65739b1bae32c14cc98b5852b079dd625d9d53b124"},
        "d2_config": {"path": "11_journal/J13a/in/design2_vmax05.json",
                      "sha256": "76cf20c6423a108c555b80b70c8d1ddcf05c336bd14eeb5ef5631d8132a77caf"}},
    "environment": {"numpy": "2.5.4", "scipy": "1.18.1"},
    "V_atomic": 1000000,
    "b_atomic": 1000000,
    "ks": [1, 2, 4, 8, 16, 32],
    "epoch_blocks": 300,
    "seconds_per_block": 2,
    "blocks_per_day": 43200,
    "avg_offset_blocks": 31073,
    "history_days": 14,
    "history_margin": 2,
    "release10": {
        "cost": {"mode": "fixed10", "anchor_delay": 120, "vrf_response": 10, "vrf_slack": 20, "proof_window": 1800,
                 "dispute_window": 1800, "bind_window": 1800, "proof_delay": None, "keeper_delay": 0,
                 "accept_ppm": 0, "unsigned_ppm": 0, "accept_over_cap": True, "seller_epoch_k": "k",
                 "dispute_from": "anchor"},
        "bridge": {"mode": "fixed10", "anchor_delay": 120, "vrf_response": 100, "vrf_slack": 50,
                   "proof_window": 1800, "dispute_window": 1800, "bind_window": 300, "proof_delay": None,
                   "keeper_delay": 0, "accept_ppm": 0, "unsigned_ppm": 0, "accept_over_cap": True,
                   "seller_epoch_k": 1, "dispute_from": "anchor"}},
    "replay_flags": {
        "common": ["--qx", "137", "--conditions", "1", "--repetitions", "1", "--design", "2", "--vmax", "1",
                   "--sales-cap", "none", "--chain", "base", "--draws", "1", "--k-w", "0.015",
                   "--preset", "r11-main", "--r10-anchor-delay", "120"],
        "cost": ["--r10-vrf-response", "10", "--r10-vrf-slack", "20", "--r10-bind-window", "1800"],
        "bridge": []},
    "run_dirs": {"cost": "{window}_r12cost/k{k}", "bridge": "{window}_r12bridge/k1"},
    "bridge_expect": {
        "median": {"addresses_observed_sha256": "0e20b271c23961fb84cc1ab7efcfea8144f51369368306d299b8aff20cc28b7f",
                   "sales_npz_sha256": "15510c7920b219a4014c682c35701fc1c5abe4eccde95af2b3344ef2f892a9c5"},
        "busy": {"addresses_observed_sha256": "e0ce0c192195de70400e7e379c047913cc9b96ebc3ee6a1b8c5681ad37935988",
                 "sales_npz_sha256": "116d0352a75c746c5617c34c5b5436eee048bc61d6fbcda15b35843e78bc0dfe"},
        "r11_file": "11_journal/R11/results/r11_addr_main_{window}_v1.csv"},
    "run_record": {"meta/design2/vmax_atomic": 1000000, "meta/design2/k_w": "0.015", "env/design": "design-2",
                   "env/parameters/draws": 1, "env/parameters/qX": 137, "meta/condition": 1, "meta/block_seconds": "2"},
    "k_choice": {"release_gas": 114624, "release_l1_wei": "945606403.8667", "gas_price_gwei": "0.010",
                 "eth_usd": "2401.44", "capital_rate": "0.10", "seconds_per_year": 31536000},
    "reserve": {"usd_per_open_purchase": "0.851522", "usd_per_open_purchase_low": "0.013778",
                "k11_open_blocks": 2250},
    "sets": ["S1r", "S1", "S2"],
    "judgement_set": "S1r",
    "lags": {"own": "k_star", "k1": 1},
    "verdict_suffix": {"own": "", "k1": "d"},
    "S1r_counts": {"median": 289, "busy": 178},
    "thresholds": {"JL12_ratio_max": "1.2"},
    "verdict_paths": ["verdicts/JL12/holds", "verdicts/JEH12/holds", "verdicts/JER12/holds",
                      "verdicts/JL12d/holds", "verdicts/JEH12d/holds", "verdicts/JER12d/holds"],
    "outputs": ["r12_results.json", "r12_tables.md", "r12_addr_median.csv", "r12_addr_busy.csv",
                "r12_k_median.csv", "r12_k_busy.csv", "r12_sales_sha256.txt"],
}

ADDR_COLUMNS = ['address', 'in_S1r', 'in_S1', 'revenue', 'C_prior', 'rho2', 'k_star', 'L_kstar'] + \
    [f'NE_k{k}' for k in REGISTERED['ks']] + [f'Ifull_k{k}' for k in REGISTERED['ks']] + \
    [f'Hnum_k{k}' for k in REGISTERED['ks']] + [f'Onum_k{k}' for k in REGISTERED['ks']] + \
    [f'{c}_{lag}' for lag in REGISTERED['lags'] for c in ('L', 'X_H', 'X_Ru', 'X_M', 'Usum_H', 'Usum_Ru', 'Usum_M',
                                                        'Bsum_H', 'rej_value_Rr', 'rej_count_Rr', 'Esum')]
ADDR_CELL = {'X_H': 'X_H', 'X_Ru': 'X_Ru', 'X_M': 'X_M', 'Usum_H': 'Usum_H', 'Usum_Ru': 'Usum_Ru', 'Usum_M': 'Usum_M',
             'Bsum_H': 'Bsum_H', 'rej_value_Rr': 'rej_value', 'rej_count_Rr': 'rej_count', 'Esum': 'Esum'}
K_COLUMNS = ['L_F', 'held', 'L_FB', 'sumC_M_lag_k', 'sumC_M_lag_1', 'ratio_lag_k', 'ratio_lag_1', 'NE',
             'release_cost_usd', 'capital_cost_usd', 'open_purchases_avg', 'reserve_usd']


# ---------------------------------------------------------------- registration and record checks

def registration_block(text):
    """The JSON of the fenced block `json r12-registered` (exactly one such block)."""
    lines = text.splitlines()
    starts = [i for i, ln in enumerate(lines) if ln.strip() == FENCE]
    if len(starts) != 1:
        raise ValueError(f'the registration has {len(starts)} blocks `{FENCE}`, expected 1')
    s = starts[0] + 1
    e = next((i for i in range(s, len(lines)) if lines[i].strip() == '```'), None)
    if e is None:
        raise ValueError('the registered block is not closed')
    return json.loads('\n'.join(lines[s:e]))


def deep_diff(a, b, path=''):
    """Every difference between two JSON values, as strings with the key path. Keys are never skipped."""
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f'{path}/{k}'
            if k not in a:
                out.append(f'{p}: missing on the left')
            elif k not in b:
                out.append(f'{p}: missing on the right')
            else:
                out += deep_diff(a[k], b[k], p)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f'{path}: length {len(a)} != {len(b)}')
        for i, (x, y) in enumerate(zip(a, b)):
            out += deep_diff(x, y, f'{path}[{i}]')
    elif type(a) is not type(b) or a != b:
        out.append(f'{path}: {a!r} != {b!r}')
    return out


def check_registration(reg_path):
    """(registration SHA-256, block); raises SystemExit when the block differs from REGISTERED."""
    raw = Path(reg_path).read_bytes()
    block = registration_block(raw.decode('utf-8'))
    diff = deep_diff(block, REGISTERED)
    if diff:
        raise SystemExit('the registered block differs from the code:\n  ' + '\n  '.join(diff[:40]))
    flags = REGISTERED['replay_flags']['common']
    vmax_flag = Fraction(flags[flags.index('--vmax') + 1]) * 10 ** 6
    if not (vmax_flag == REGISTERED['V_atomic'] == REGISTERED['run_record']['meta/design2/vmax_atomic']
            and REGISTERED['b_atomic'] == REGISTERED['V_atomic']):
        raise SystemExit('the block is not consistent: --vmax, V_atomic, the recorded vmax and b must agree')
    return hashlib.sha256(raw).hexdigest(), block


def compare_record(expected, got):
    """Whole-record comparison: every key of either side counts (no exclusion list anywhere)."""
    if not isinstance(got, dict):
        return dict(ok=False, missing=sorted(expected), extra=[], differing=[], note='record is not an object')
    missing = sorted(k for k in expected if k not in got)
    extra = sorted(k for k in got if k not in expected)
    differing = sorted(k for k in expected if k in got and (type(expected[k]) is not type(got[k])
                                                           or expected[k] != got[k]))
    return dict(ok=not (missing or extra or differing), missing=missing, extra=extra,
                differing=[(k, expected[k], got[k]) for k in differing])


def expected_release10(kind, k):
    rec = dict(REGISTERED['release10'][kind])
    if rec['seller_epoch_k'] == 'k':
        rec['seller_epoch_k'] = k
    return rec


def replay_flags(kind):
    return list(REGISTERED['replay_flags']['common']) + list(REGISTERED['replay_flags'][kind])


def lag_of(rec, k):
    """L_F(k): the longest path from a sale to its confirmed failure with k profile epochs per seller epoch
    (the same expression as R11's lf11)."""
    E = REGISTERED['epoch_blocks']
    return E - 1 + rec['anchor_delay'] + rec['vrf_response'] + 1 + rec['vrf_slack'] + rec['proof_window'] + 1 \
        + E * (k - 1)


def get_path(obj, path):
    for part in path.split('/'):
        if not isinstance(obj, dict) or part not in obj:
            raise KeyError(path)
        obj = obj[part]
    return obj


# ---------------------------------------------------------------- small helpers

def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def exact_sum(a):
    """Exact Python-int sum of a non-negative int64 array (split into 32-bit halves so no partial sum overflows)."""
    a = np.asarray(a, dtype=np.int64)
    if a.size == 0:
        return 0
    if (a < 0).any():
        raise ValueError('exact_sum takes non-negative values')
    hi = a >> 32
    lo = a & 0xFFFFFFFF
    return (int(hi.sum()) << 32) + int(lo.sum())


def utc_seconds(s):
    import calendar
    import time
    return calendar.timegm(time.strptime(s, '%Y-%m-%d %H:%M:%S'))


def date_of(sec):
    import time
    return time.strftime('%Y-%m-%d', time.gmtime(sec))


# ---------------------------------------------------------------- lists: sales and daily revenue

def read_list(path, addresses):
    """Per address: blocks, values and list row numbers (data rows from 0, every row counts, registration A1 of R11),
    and the list's first block, first time, last block, row count and the UTC dates that carry a row (any address).
    Also checks the UTC date of every row of the given addresses against the 2-second block clock (gate G1d);
    returns the mismatch count."""
    per = {a: ([], [], []) for a in addresses}
    first = first_t = last = None
    mism = 0
    all_days = set()
    n = -1
    spb = REGISTERED['seconds_per_block']
    with open(path, newline='') as f:
        rd = csv.reader(f)
        head = next(rd)
        ib, it, ia, iv = (head.index('block_number'), head.index('block_time_utc'), head.index('recipient'),
                          head.index('value_atomic'))
        date_cache = {}
        for n, row in enumerate(rd):
            b = int(row[ib])
            if first is None:
                first, first_t = b, utc_seconds(row[it])
            last = b
            all_days.add((first_t + spb * (b - first)) // 86400)
            a = row[ia].lower()
            if a in per:
                per[a][0].append(b)
                per[a][1].append(int(row[iv]))
                per[a][2].append(n)
                day = (first_t + spb * (b - first)) // 86400
                want = date_cache.get(day)
                if want is None:
                    want = date_cache[day] = date_of(day * 86400)
                if row[it][:10] != want:
                    mism += 1
    out = {a: (np.array(b, dtype=np.int64), np.array(v, dtype=np.int64), np.array(r, dtype=np.int64))
           for a, (b, v, r) in per.items()}
    return out, dict(first_block=first, first_time=first_t, last_block=last, date_mismatches=mism, rows=n + 1,
                     dates=sorted(date_of(d * 86400) for d in all_days))


def daily_sums(blocks, values, first_block, first_time, day0):
    """{day index relative to day0: revenue} with the 2-second clock of the list that holds the rows."""
    spb = REGISTERED['seconds_per_block']
    days = (first_time + spb * (blocks - first_block)) // 86400 - day0
    out = {}
    for d, v in zip(days.tolist(), values.tolist()):
        out[d] = out.get(d, 0) + v
    return out


def history_caps(daily, n_days):
    """C(d) for d = 0 .. n_days - 1: the largest daily revenue over days d - 14 .. d - 1 (missing days are 0),
    and C(prior) = the largest over days -14 .. -1."""
    H = REGISTERED['history_days']
    caps = [max([daily.get(x, 0) for x in range(d - H, d)]) for d in range(n_days)]
    prior = max([daily.get(x, 0) for x in range(-H, 0)])
    return caps, prior


def prior_coverage(pmeta, meta, spec=None):
    """Gate G1 for the prior list (day coverage, not block adjacency): its rows fall on exactly the 14 UTC dates
    just before the window's first date with no date missing, its last row is before the window's first row and its
    first row at most 14 days of blocks before it; with `spec` (the registered prior list) also its row count and
    first and last dates. Returns (ok, detail)."""
    import datetime
    H = REGISTERED['history_days']
    d0 = datetime.date.fromisoformat(date_of(meta['first_time']))
    want = [str(d0 - datetime.timedelta(days=H - i)) for i in range(H)]
    detail = dict(dates_ok=pmeta['dates'] == want, before=pmeta['last_block'] < meta['first_block'],
                  span_ok=meta['first_block'] - pmeta['first_block'] <= H * REGISTERED['blocks_per_day'],
                  first_date=pmeta['dates'][0] if pmeta['dates'] else None,
                  last_date=pmeta['dates'][-1] if pmeta['dates'] else None, rows=pmeta['rows'],
                  gap_blocks=meta['first_block'] - pmeta['last_block'] - 1)
    if spec is not None:
        detail['registered_ok'] = (pmeta['rows'] == spec['rows'] and detail['first_date'] == spec['first_date']
                                   and detail['last_date'] == spec['last_date'])
    ok = detail['dates_ok'] and detail['before'] and detail['span_ok'] and detail.get('registered_ok', True)
    return ok, detail


def lower_median(xs):
    """The lower median (the ((n - 1) // 2)-th of the sorted values, from 0): an integer when the values are."""
    xs = sorted(xs)
    return xs[(len(xs) - 1) // 2] if xs else None


# ---------------------------------------------------------------- exposure and bonds (per address)

class Window:
    """Block arrays shared by the addresses of one window: averaging range and UTC day per block."""

    def __init__(self, first_block, last_block, first_time):
        self.first, self.last, self.first_time = first_block, last_block, first_time
        self.N = last_block - first_block + 1
        self.a0 = REGISTERED['avg_offset_blocks']
        if self.N <= self.a0:
            raise ValueError('window shorter than the averaging offset')
        self.n_avg = self.N - self.a0
        spb = REGISTERED['seconds_per_block']
        self.day0 = first_time // 86400
        self.day = ((first_time + spb * np.arange(self.N, dtype=np.int64)) // 86400 - self.day0)
        self.n_days = int(self.day[-1]) + 1

    def per_block(self, blocks, values):
        arr = np.zeros(self.N, dtype=np.int64)
        if len(blocks):
            np.add.at(arr, blocks - self.first, values)
        return arr

    def in_lag(self, cs, L):
        """E(t) for every block index t: revenue settled in (t - L, t]; cs is the cumulative per-block revenue."""
        E = cs.copy()
        if L < self.N:
            E[L:] -= cs[:-L]
        return E


def uncovered(E_scaled, Bn, a0):
    """(exact sum over the averaging blocks, max over them) of max(0, E_scaled - Bn), all in the same scaled unit."""
    u = np.maximum(E_scaled[a0:] - Bn[a0:] if np.ndim(Bn) else E_scaled[a0:] - Bn, 0)
    return exact_sum(u), int(u.max()) if u.size else 0


def admit_rate_cap(blocks, values, L, cap_scaled, scale):
    """Variant r of the rate-cap bond: sales in list order; a sale is admitted when the admitted revenue of
    (s - L, s] (earlier admitted sales of the same block included) plus its value stays at or below the bond, i.e.
    scale * (sum + v) <= cap_scaled. Returns the admitted mask."""
    keep = np.zeros(len(blocks), dtype=bool)
    q = deque()
    tot = 0
    for j, (b, v) in enumerate(zip(blocks.tolist(), values.tolist())):
        while q and q[0][0] <= b - L:
            tot -= q.popleft()[1]
        if scale * (tot + v) <= cap_scaled:
            keep[j] = True
            q.append((b, v))
            tot += v
    return keep


def address_bonds(win, blocks, values, caps, C_prior, rho2, L, rate_blocks, b_atomic, revenue):
    """Comparator cells of one address at lag L. Scales: history and rate cap in atomic x 86,400 (B * 86,400 =
    2 h C L or 2 rho L), the ceiling in atomic x rate_blocks."""
    h = REGISTERED['history_margin']
    S = 2 * REGISTERED['blocks_per_day']                     # 86,400
    cs = np.cumsum(win.per_block(blocks, values))
    E = win.in_lag(cs, L)
    caps_arr = np.asarray(caps, dtype=np.int64)
    Bn_H = 2 * h * caps_arr[win.day] * L                     # B^H * 86,400 per block
    uH = uncovered(E * S, Bn_H, win.a0)
    Bsum_H = exact_sum(Bn_H[win.a0:])
    Bn_R = rho2 * L                                          # B^R * 86,400 (rho2 = 2 rho is an integer)
    uRu = uncovered(E * S, Bn_R, win.a0)
    Bn_M = b_atomic * rate_blocks + revenue * L              # C^M * rate_blocks
    uM = uncovered(E * rate_blocks, Bn_M, win.a0)
    keep = admit_rate_cap(blocks, values, L, Bn_R, S)
    cs_r = np.cumsum(win.per_block(blocks[keep], values[keep]))
    uRr = uncovered(win.in_lag(cs_r, L) * S, Bn_R, win.a0)
    return dict(Usum_H=uH[0], X_H=uH[1], Bsum_H=Bsum_H, Usum_Ru=uRu[0], X_Ru=uRu[1], Usum_M=uM[0], X_M=uM[1],
                Usum_Rr=uRr[0], X_Rr=uRr[1], rej_value=int(values[~keep].sum()), rej_count=int((~keep).sum()),
                Esum=exact_sum(E[win.a0:]), scale_HR=S, scale_M=rate_blocks, Bn_R=Bn_R, Bn_M=Bn_M)


# ---------------------------------------------------------------- FairBind runs

def load_run(run_dir, expect, code_commit, n_addresses):
    """One replay run (`run.json`, `condition-01-seed-0/`) with gate G3 (whole-record comparison) and the G4 ledger
    check. Returns (run, problems)."""
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
    rec = compare_record(expect, meta.get('release10'))
    if not rec['ok']:
        problems.append(f'release10 record differs from the registered one (G3): {rec}')
    rec_env = compare_record(expect, env.get('parameters', {}).get('release10'))
    if not rec_env['ok']:
        problems.append(f'run.json release10 record differs from the registered one (G3): {rec_env}')
    if env['parameters'].get('freeze_scope') != 'detected-onward':
        problems.append('freeze scope is not detected-onward (G3)')
    if meta.get('admission') != ['unlimited']:
        problems.append(f"admission {meta.get('admission')} is not ['unlimited'] (G3)")
    if meta.get('preset') != 'r11-main':
        problems.append(f"preset {meta.get('preset')} is not r11-main (G3)")
    rec_both = dict(meta=meta, env=env)
    for path, want in REGISTERED['run_record'].items():
        try:
            got = get_path(rec_both, path)
        except KeyError:
            problems.append(f'{path} missing from the run record (G3)')
            continue
        if type(got) is not type(want) or got != want:
            problems.append(f'{path} is {got!r}, registered {want!r} (G3)')
    if any(float(r.get('H_ledger_list_max_abs_diff') or 0) != 0 for r in rows.values()):
        problems.append('the two H paths differ (G4)')
    for a, r in rows.items():
        if r.get('admission') != 'unlimited' or r['accepted_count'] != r['attempted_count']:
            problems.append(f'{a}: not every attempted sale admitted (G2)')
            break
    if n_addresses is not None and len(rows) != n_addresses:
        problems.append(f'{len(rows)} addresses, expected {n_addresses}')
    if meta.get('sales_file') != 'sales.npz' or not (cdir / 'sales.npz').exists():
        problems.append('sales.npz missing')
    first = env['inputs']['settlements']['first_block']
    last = env['inputs']['settlements']['last_block']
    return dict(env=env, meta=meta, rows=rows, cdir=cdir, first=first, last=last,
                rate_blocks=meta['rate_blocks']), problems


def run_sales(run):
    z = np.load(run['cdir'] / 'sales.npz')
    sales = {k: z[k] for k in z.files}
    addrs = json.loads((run['cdir'] / 'sales_addresses.json').read_text())
    return sales, addrs


def interval_numerators(starts, ends, weights, idx, n_addr, lo, hi):
    """Per address: sum of weight x |[start, end) intersected with [lo, hi]| (exact int64)."""
    held = np.maximum(np.minimum(ends, hi + 1) - np.maximum(starts, lo), 0)
    out = np.zeros(n_addr, dtype=np.int64)
    np.add.at(out, idx, weights * held)
    return out


def union_length(starts, ends, lo, hi):
    """Length of the union of [start, end) intersected with [lo, hi] (vectorised sweep)."""
    s = np.maximum(np.asarray(starts, dtype=np.int64), lo)
    e = np.minimum(np.asarray(ends, dtype=np.int64), hi + 1)
    ok = e > s
    s, e = s[ok], e[ok]
    if not len(s):
        return 0
    order = np.argsort(s, kind='stable')
    s, e = s[order], e[order]
    reach = np.maximum.accumulate(e)
    new = np.ones(len(s), dtype=bool)
    new[1:] = s[1:] > reach[:-1]
    seg = np.cumsum(new) - 1
    seg_start = s[new]
    seg_end = np.zeros(int(seg[-1]) + 1, dtype=np.int64)
    np.maximum.at(seg_end, seg, e)
    return int((seg_end - seg_start).sum())


def fairbind_cells(run, k):
    """Per address of one run: whole-window held numerator (H_cont_sum_blocks, checked), held numerator over the
    averaging blocks (checked against H_cont_average_from_hold), open-purchase numerator, seller-open blocks, number
    of seller epochs with a sale. Returns (cells, problems)."""
    sales, addrs = run_sales(run)
    problems = []
    if addrs != list(run['rows']):
        return None, ['sales_addresses.json order differs from addresses_observed.csv']
    n = len(addrs)
    first, last = run['first'], run['last']
    a0 = REGISTERED['avg_offset_blocks']
    b = sales['block'].astype(np.int64)
    v = sales['value'].astype(np.int64)
    rl = sales['release'].astype(np.int64)
    idx = sales['address_index'].astype(np.int64)
    if sales['accepted'].astype(bool).any():
        problems.append('a sale is accepted although a = 0')
    E = REGISTERED['epoch_blocks']
    if not np.array_equal(sales['epoch'].astype(np.int64), (b - first) // E):
        problems.append(f'sales.npz epoch is not floor((block - first block) / {E}) (G3: epoch length and origin)')
    full = interval_numerators(b, rl, v, idx, n, first, last)
    hnum = interval_numerators(b, rl, v, idx, n, first + a0, last)
    onum = interval_numerators(b, rl, np.ones_like(v), idx, n, first + a0, last)
    n_avg = last - first - a0 + 1
    sep = ((b - first) // E) // k
    cells = {}
    order = np.argsort(idx, kind='stable')
    bounds = np.searchsorted(idx[order], np.arange(n + 1))
    bad_full = bad_hold = 0
    for i, a in enumerate(addrs):
        r = run['rows'][a]
        if int(full[i]) != int(r['H_cont_sum_blocks']):
            bad_full += 1
        want = float(r['H_cont_average_from_hold'] or 0)
        got = int(hnum[i]) / n_avg
        if not math.isclose(got, want, rel_tol=1e-9, abs_tol=1e-9):
            bad_hold += 1
        sel = order[bounds[i]:bounds[i + 1]]
        cells[a] = dict(Ifull=int(full[i]), Hnum=int(hnum[i]), Onum=int(onum[i]),
                        Sopen=union_length(b[sel], rl[sel], first + a0, last),
                        NE=int(len(np.unique(sep[sel]))), revenue=int(r['accepted_value']))
    if bad_full:
        problems.append(f'H_cont_sum_blocks differs from sales.npz for {bad_full} addresses (G4)')
    if bad_hold:
        problems.append(f'H_cont_average_from_hold differs from sales.npz for {bad_hold} addresses (G4)')
    return cells, problems


def release_cost_exact():
    """c_rel in USD as a Fraction (registration 4.3)."""
    kc = REGISTERED['k_choice']
    gp = Fraction(kc['gas_price_gwei']) * Fraction(1, 10 ** 9)
    eth = Fraction(kc['eth_usd'])
    return kc['release_gas'] * gp * eth + Fraction(kc['release_l1_wei']) * Fraction(1, 10 ** 18) * eth


def capital_per_block_exact():
    """r x (2 s / year) as a Fraction."""
    kc = REGISTERED['k_choice']
    return Fraction(kc['capital_rate']) * REGISTERED['seconds_per_block'] / kc['seconds_per_year']


def release_cost_usd():
    return float(release_cost_exact())


def k_cost(c):
    """c_i(k) = c_rel x NE(k) + r x (2 s / year) x Ifull(k) / 10^6, exact."""
    return release_cost_exact() * c['NE'] + capital_per_block_exact() * Fraction(c['Ifull'], 10 ** 6)


def choose_k(cells_by_k):
    """k* of one address: argmin over k of k_cost, computed in rationals; ties go to the smaller k."""
    best = None
    for k in REGISTERED['ks']:
        cost = k_cost(cells_by_k[k])
        if best is None or cost < best[1]:
            best = (k, cost)
    return best[0]


# ---------------------------------------------------------------- sets

def make_sets(rows_k1, stored):
    """S1r, S1, S2 as in R11 section 3 (S1 by the stored edition-7 scale of V 0.2, S1r by revenue). With stored None
    (synthetic self-check) every address is in S1."""
    rev = {a for a, r in rows_k1.items() if int(r['accepted_value']) > 0}
    if stored is None:
        s1 = set(rows_k1)
    else:
        s1 = {a for a in rows_k1 if (int(stored[a]['scale']) if stored[a]['scale'] != '' else 1) <= 77}
    return {'S1r': s1 & rev, 'S1': s1, 'S2': set(rows_k1)}


# ---------------------------------------------------------------- one window

def window_results(w, runs, lists_w, list_meta, prior_daily, stored, out):
    """All cells of one window. runs: {k: run}; lists_w: per address (blocks, values, rows) of the window list."""
    ks = REGISTERED['ks']
    V, b = REGISTERED['V_atomic'], REGISTERED['b_atomic']
    rec_cost = expected_release10('cost', 1)
    lagk = {k: lag_of(rec_cost, k) for k in ks}
    run1 = runs[1]
    addrs = list(run1['rows'])
    problems = []
    if set(lists_w) != set(addrs):
        problems.append('list addresses differ from the run')
    win = Window(run1['first'], run1['last'], list_meta['first_time'])
    if list_meta['first_block'] != run1['first'] or list_meta['last_block'] != run1['last']:
        problems.append('list first or last block differs from the run')
    rate_blocks = run1['rate_blocks']
    sets = make_sets(run1['rows'], stored)
    # FairBind per k
    cells = {}
    for k in ks:
        c, p = fairbind_cells(runs[k], k)
        if c is None:
            return None, p
        problems += [f'k = {k}: {x}' for x in p]
        cells[k] = c
    # k chain (every pair of a power-of-two list nests): Ifull per address non-decreasing in k
    chain_bad = sum(1 for a in addrs for i in range(len(ks) - 1)
                    if cells[ks[i + 1]][a]['Ifull'] < cells[ks[i]][a]['Ifull'])
    if chain_bad:
        problems.append(f'held money decreases in k for {chain_bad} (address, pair) cells (G4)')
    # revenue equal across k and to the list
    for a in addrs:
        if any(cells[k][a]['revenue'] != cells[1][a]['revenue'] for k in ks) or \
                int(lists_w[a][1].sum()) != cells[1][a]['revenue']:
            problems.append(f'{a}: revenue differs between runs or from the list (G6)')
            break
    kstar = {a: choose_k({k: cells[k][a] for k in ks}) for a in addrs}
    # history and declared rates
    caps, cprior = {}, {}
    for a in addrs:
        blocks, values, _ = lists_w[a]
        daily = dict(prior_daily.get(a, {}))
        for d, x in daily_sums(blocks, values, win.first, win.first_time, win.day0).items():
            daily[d] = daily.get(d, 0) + x
        caps[a], cprior[a] = history_caps(daily, win.n_days)
    h = REGISTERED['history_margin']
    rho2_0 = lower_median([2 * h * cprior[a] for a in addrs if cprior[a] > 0])
    if rho2_0 is None:
        problems.append('no address has a prior history: rho_0 is not defined')
        rho2_0 = 0
    rho2 = {a: (2 * h * cprior[a] if cprior[a] > 0 else rho2_0) for a in addrs}
    # comparators per address, at every registered lag
    def lag_blocks(lag, a):
        spec = REGISTERED['lags'][lag]
        return lagk[kstar[a]] if spec == 'k_star' else lagk[spec]
    per = {}
    for a in addrs:
        blocks, values, _ = lists_w[a]
        rev = cells[1][a]['revenue']
        per[a] = {lag: address_bonds(win, blocks, values, caps[a], cprior[a], rho2[a], lag_blocks(lag, a),
                                     rate_blocks, b, rev) for lag in REGISTERED['lags']}
        if any(per[a][lag]['X_Rr'] != 0 for lag in REGISTERED['lags']):
            problems.append(f'{a}: the rejecting rate cap leaves an uncovered exposure (G5)')
    n_avg = win.n_avg
    unit_hi = Fraction(REGISTERED['reserve']['usd_per_open_purchase'])
    unit_lo = Fraction(REGISTERED['reserve']['usd_per_open_purchase_low'])
    S_ = 2 * REGISTERED['blocks_per_day']
    thr = Fraction(REGISTERED['thresholds']['JL12_ratio_max'])

    def lag_cells(S, lag):
        n = len(S)
        P = Fraction(n * b, 10 ** 6)
        held = Fraction(sum(cells[kstar[a]][a]['Hnum'] for a in S), n_avg * 10 ** 6)   # FairBind at k*, every lag
        LFB = P + held
        CM = sum((Fraction(b * rate_blocks + cells[1][a]['revenue'] * lag_blocks(lag, a), rate_blocks) for a in S),
                 Fraction(0)) / 10 ** 6
        BH = Fraction(sum(per[a][lag]['Bsum_H'] for a in S), S_ * n_avg * 10 ** 6)
        BR = sum((Fraction(rho2[a] * lag_blocks(lag, a), S_) for a in S), Fraction(0)) / 10 ** 6
        XH = sum(per[a][lag]['X_H'] for a in S)
        XRu = sum(per[a][lag]['X_Ru'] for a in S)
        bound_scaled = n * V * S_
        rev_S = sum(cells[1][a]['revenue'] for a in S)
        rej = sum(per[a][lag]['rej_value'] for a in S)
        rec = dict(n=n, P_FB=float(P), held=float(held), L_FB=float(LFB), sumC_M=float(CM),
                   sumC_M_no_b=float(CM - P), sumB_H=float(BH), sumB_R=float(BR),
                   ratio_LFB_CM=float(LFB / CM) if CM else None, ratio_LFB_CM_le_threshold=bool(CM and LFB <= thr * CM),
                   ratio_LFB_BH=float(LFB / BH) if BH else None, ratio_LFB_BR=float(LFB / BR) if BR else None,
                   E_avg=sum(per[a][lag]['Esum'] for a in S) / n_avg / 1e6,
                   U_avg_H=sum(per[a][lag]['Usum_H'] for a in S) / S_ / n_avg / 1e6,
                   U_avg_Ru=sum(per[a][lag]['Usum_Ru'] for a in S) / S_ / n_avg / 1e6,
                   U_avg_M=sum(per[a][lag]['Usum_M'] / rate_blocks for a in S) / n_avg / 1e6,
                   X_sum_H=XH / S_ / 1e6, X_sum_Ru=XRu / S_ / 1e6,
                   X_sum_H_scaled=XH, X_sum_Ru_scaled=XRu, FB_bound_scaled=bound_scaled, scale=S_,
                   X_sum_M=sum(per[a][lag]['X_M'] / rate_blocks for a in S) / 1e6,
                   X_gt_V_H=sum(1 for a in S if per[a][lag]['X_H'] > V * S_),
                   X_gt_V_Ru=sum(1 for a in S if per[a][lag]['X_Ru'] > V * S_),
                   X_gt_V_M=sum(1 for a in S if per[a][lag]['X_M'] > V * rate_blocks),
                   FB_bound=n * V / 1e6,
                   reject_value_Rr=rej / 1e6, reject_count_Rr=sum(per[a][lag]['rej_count'] for a in S),
                   reject_share_Rr=float(Fraction(rej, rev_S)) if rev_S else None,
                   no_prior=sum(1 for a in S if cprior[a] == 0))
        onum = Fraction(sum(cells[kstar[a]][a]['Onum'] for a in S), n_avg)
        rec.update(open_purchases_avg=float(onum), reserve_usd=float(onum * unit_hi),
                   reserve_usd_low=float(onum * unit_lo),
                   FB_open_sellers_avg=sum(cells[kstar[a]][a]['Sopen'] for a in S) / n_avg,
                   reserve_usd_k11=float(Fraction(sum(len(lists_w[a][0]) for a in S), win.N)
                                         * REGISTERED['reserve']['k11_open_blocks'] * unit_hi))
        rec['FB_replay_exposure'] = rec['FB_open_sellers_avg'] * V / 1e6
        return rec

    def reserve_vs_seller(S):
        """Per seller: buyers' reserve (USD, unit 0.851522) against the seller's own locked money b + H_i(k*)
        (USDC, 1 USDC = 1 USD). Reported only."""
        ratios, ge = [], 0
        for a in S:
            res = unit_hi * Fraction(cells[kstar[a]][a]['Onum'], n_avg)
            own = Fraction(b, 10 ** 6) + Fraction(cells[kstar[a]][a]['Hnum'], n_avg * 10 ** 6)
            ratios.append(res / own)
            ge += res >= own
        ratios.sort()
        return dict(n=len(S), sellers_reserve_ge_own=ge,
                    median_ratio=float(ratios[(len(ratios) - 1) // 2]) if ratios else None,
                    max_ratio=float(ratios[-1]) if ratios else None)

    R = dict(first_block=win.first, last_block=win.last, n_blocks=win.N, n_avg=n_avg, n_days=win.n_days,
             rate_blocks=rate_blocks, lags={str(k): lagk[k] for k in ks}, rho2_0=rho2_0,
             set_sizes={s: len(x) for s, x in sets.items()},
             k_star_counts={str(k): sum(1 for a in sets['S1r'] if kstar[a] == k) for k in ks},
             list_date_mismatches=list_meta['date_mismatches'], release_cost_usd=release_cost_usd())
    R['lag'] = {lag: {s: lag_cells(sets[s], lag) for s in REGISTERED['sets']} for lag in REGISTERED['lags']}
    R['reserve_vs_seller'] = {s: reserve_vs_seller(sets[s]) for s in REGISTERED['sets']}
    # k curve: FairBind with one k for every address, ceiling at L_F(k) and L_F(1)
    per_block = float(capital_per_block_exact())
    kcurve = {}
    for k in ks:
        kcurve[str(k)] = {}
        for s in REGISTERED['sets']:
            S = sets[s]
            held = sum(cells[k][a]['Hnum'] for a in S) / n_avg / 1e6
            P = len(S) * b / 1e6
            CMk = float(sum((Fraction(b * rate_blocks + cells[1][a]['revenue'] * lagk[k], rate_blocks) for a in S),
                            Fraction(0))) / 1e6
            CM1 = float(sum((Fraction(b * rate_blocks + cells[1][a]['revenue'] * lagk[1], rate_blocks) for a in S),
                            Fraction(0))) / 1e6
            onum = sum(cells[k][a]['Onum'] for a in S) / n_avg
            kcurve[str(k)][s] = dict(L_F=lagk[k], held=held, L_FB=P + held, sumC_M_lag_k=CMk, sumC_M_lag_1=CM1,
                                     ratio_lag_k=(P + held) / CMk if CMk else None,
                                     ratio_lag_1=(P + held) / CM1 if CM1 else None,
                                     NE=sum(cells[k][a]['NE'] for a in S),
                                     release_cost_usd=release_cost_usd() * sum(cells[k][a]['NE'] for a in S),
                                     capital_cost_usd=per_block * sum(cells[k][a]['Ifull'] for a in S) / 1e6,
                                     open_purchases_avg=onum, reserve_usd=onum * float(unit_hi))
    R['k'] = kcurve
    with open(Path(out) / f'r12_addr_{w}.csv', 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(ADDR_COLUMNS)
        for a in addrs:
            row = [a, int(a in sets['S1r']), int(a in sets['S1']), cells[1][a]['revenue'], cprior[a], rho2[a],
                   kstar[a], lagk[kstar[a]]] + [cells[k][a]['NE'] for k in ks] + \
                [cells[k][a]['Ifull'] for k in ks] + [cells[k][a]['Hnum'] for k in ks] + \
                [cells[k][a]['Onum'] for k in ks]
            for lag in REGISTERED['lags']:
                row += [lag_blocks(lag, a)] + [per[a][lag][ADDR_CELL[c]] for c in ADDR_CELL]
            wr.writerow(row)
    with open(Path(out) / f'r12_k_{w}.csv', 'w', newline='') as f:
        wr = csv.writer(f, lineterminator='\n')
        wr.writerow(['k', 'set'] + K_COLUMNS)
        for k in ks:
            for s in REGISTERED['sets']:
                wr.writerow([k, s] + [kcurve[str(k)][s][c] for c in K_COLUMNS])
    return R, problems


def verdicts(R):
    """Section 8.2 of the registration: judgement set S1r, every reportable window, each rule at every registered lag
    (`lags`, name suffix from `verdict_suffix`). JL12 compares L_FB <= 1.2 x sum C^M in rationals; JEH12 and JER12
    compare sum X > n x V in integers at the scale 86,400."""
    js = REGISTERED['judgement_set']
    thr = float(Fraction(REGISTERED['thresholds']['JL12_ratio_max']))
    ws = [w for w in REGISTERED['windows'] if R['windows'].get(w, {}).get('reportable')]
    names = ('JL12', 'JEH12', 'JER12')
    sfx = REGISTERED['verdict_suffix']
    if not ws:
        return {n + sfx[lag]: dict(holds=None, reason='no reportable window') for n in names for lag in sfx}
    out = {}
    for lag in REGISTERED['lags']:
        def cell(w):
            return R['windows'][w]['lag'][lag][js]
        out['JL12' + sfx[lag]] = dict(holds=all(cell(w)['ratio_LFB_CM_le_threshold'] for w in ws),
                                      values={w: cell(w)['ratio_LFB_CM'] for w in ws}, threshold=thr, lag=lag,
                                      windows=ws)
        out['JEH12' + sfx[lag]] = dict(holds=all(cell(w)['X_sum_H_scaled'] > cell(w)['FB_bound_scaled'] for w in ws),
                                       values={w: [cell(w)['X_sum_H'], cell(w)['FB_bound']] for w in ws}, lag=lag,
                                       windows=ws)
        out['JER12' + sfx[lag]] = dict(holds=all(cell(w)['X_sum_Ru_scaled'] > cell(w)['FB_bound_scaled']
                                                 for w in ws),
                                       values={w: [cell(w)['X_sum_Ru'], cell(w)['FB_bound']] for w in ws}, lag=lag,
                                       windows=ws)
    return out


def tables(R):
    L = ['# R12 tables (registration R12, section 6)', '']
    for w in REGISTERED['windows']:
        W = R['windows'].get(w)
        if not W or not W.get('reportable'):
            L += [f'## {w}: not reportable', '', '; '.join((W or {}).get('problems', [])), '']
            continue
        for lag in REGISTERED['lags']:
            L += [f'## {w}, lag {lag}', '', '| set | n | L_FB | ΣC^M | ΣB^H | ΣB^R | L_FB/ΣC^M | ΣX^H | ΣX^Ru | ΣX^M | '
                  'n V | Ū^H | Ū^Ru | rejected share (r) | reserve USD |', '|' + '---|' * 15]
            for s in REGISTERED['sets']:
                c = W['lag'][lag][s]
                L.append('| ' + ' | '.join([s, str(c['n'])] + [f"{c[x]:.4f}" if c[x] is not None else '-' for x in (
                    'L_FB', 'sumC_M', 'sumB_H', 'sumB_R', 'ratio_LFB_CM', 'X_sum_H', 'X_sum_Ru', 'X_sum_M',
                    'FB_bound', 'U_avg_H', 'U_avg_Ru', 'reject_share_Rr', 'reserve_usd')]) + ' |')
            L.append('')
    L += ['## verdicts', '']
    for n, v in R['verdicts'].items():
        L.append(f"- {n}: {v.get('holds')} {json.dumps(v.get('values'))}")
    return '\n'.join(L) + '\n'


# ---------------------------------------------------------------- commands

def _num_or_none(x):
    try:
        return int(x)
    except ValueError:
        pass
    try:
        return float(x)
    except ValueError:
        return None


def compare_csv_columns(path_a, path_b):
    """Gate G2b fallback (registration 2.3): the same header and rows, integer cells equal exactly, other numeric
    cells within relative 1e-9 (absolute 1e-9 where a value is 0), text cells equal."""
    ra, rb = read_csv(path_a), read_csv(path_b)
    with open(path_a, newline='') as f:
        ha = next(csv.reader(f))
    with open(path_b, newline='') as f:
        hb = next(csv.reader(f))
    if ha != hb or len(ra) != len(rb):
        return dict(ok=False, reason='header or row count differs')
    diff = []
    for i, (x, y) in enumerate(zip(ra, rb)):
        for c in ha:
            u, v = x[c], y[c]
            if u == v:
                continue
            nu, nv = _num_or_none(u), _num_or_none(v)
            if isinstance(nu, int) and isinstance(nv, int):
                diff.append((i, c, u, v))
            elif nu is not None and nv is not None:
                if not math.isclose(float(nu), float(nv), rel_tol=1e-9, abs_tol=1e-9):
                    diff.append((i, c, u, v))
            else:
                diff.append((i, c, u, v))
    return dict(ok=not diff, differences=len(diff), first=diff[:5])


def write_empty_window_files(out, w):
    with open(Path(out) / f'r12_addr_{w}.csv', 'w', newline='') as f:
        csv.writer(f, lineterminator='\n').writerow(ADDR_COLUMNS)
    with open(Path(out) / f'r12_k_{w}.csv', 'w', newline='') as f:
        csv.writer(f, lineterminator='\n').writerow(['k', 'set'] + K_COLUMNS)


def compute(reg, raw, lists, docs, out, code_commit, stored_loader=None, check_hashes=True, bridge_expect=None):
    """The aggregation. `check_hashes`, `bridge_expect` and `stored_loader` None are for the synthetic self-check
    only (registration 9, S1): they turn off the registered input hashes, row counts, dates and S1r counts, take the
    bridge expectation from the caller and put every address in S1."""
    reg_sha, _ = check_registration(reg)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    R = dict(registration=REGISTERED['registration'], registration_sha256=reg_sha, code_commit=code_commit,
             registered=REGISTERED, windows={},
             environment=dict(numpy=np.__version__, python=sys.version.split()[0]))
    R['environment']['numpy_registered'] = np.__version__ == REGISTERED['environment']['numpy']
    sales_lines = []
    for w in REGISTERED['windows']:
        W = R['windows'][w] = dict(problems=[], notes=[])
        runs = {}
        for k in REGISTERED['ks']:
            d = Path(raw) / REGISTERED['run_dirs']['cost'].format(window=w, k=k)
            run, p = load_run(d, expected_release10('cost', k), code_commit, REGISTERED['addresses'])
            W['problems'] += [f'cost k = {k}: {x}' for x in p]
            if run is not None:
                runs[k] = run
                sales_lines.append(f"{sha256(run['cdir'] / 'sales.npz')}  r12cost/{w}/k{k}")
        bd = Path(raw) / REGISTERED['run_dirs']['bridge'].format(window=w)
        brun, bp = load_run(bd, expected_release10('bridge', 1), code_commit, REGISTERED['addresses'])
        W['problems'] += [f'bridge: {x}' for x in bp]
        if brun is not None:
            got = sha256(brun['cdir'] / 'addresses_observed.csv')
            bexp = (bridge_expect or REGISTERED['bridge_expect'])[w]
            snpz = sha256(brun['cdir'] / 'sales.npz')
            sales_lines.append(f'{snpz}  r12bridge/{w}/k1')
            W['bridge'] = dict(addresses_observed_sha256=got, equal=got == bexp['addresses_observed_sha256'],
                               sales_npz_sha256=snpz, sales_npz_equal=snpz == bexp['sales_npz_sha256'])
            if not W['bridge']['equal']:
                r11_file = None if docs is None else \
                    Path(docs) / REGISTERED['bridge_expect']['r11_file'].format(window=w)
                if r11_file is not None and r11_file.exists() and \
                        sha256(r11_file) == REGISTERED['bridge_expect'][w]['addresses_observed_sha256']:
                    cc = compare_csv_columns(brun['cdir'] / 'addresses_observed.csv', r11_file)
                    W['bridge']['column_comparison'] = cc
                    if cc['ok']:
                        W['notes'].append('bridge: bytes differ from R11, columns equal within the registered '
                                          'tolerance (G2b fallback)')
                    else:
                        W['problems'].append('bridge: addresses_observed.csv differs from R11 main V 1 (G2b)')
                else:
                    W['problems'].append('bridge: bytes differ and the R11 file is not available for the column '
                                         'comparison (G2b)')
        if len(runs) != len(REGISTERED['ks']) or brun is None:
            W['reportable'] = False
            write_empty_window_files(out, w)
            continue
        lp = Path(lists) / REGISTERED['lists'][w]['file']
        pp = Path(lists) / REGISTERED['prior_lists'][w]['file']
        if check_hashes:
            if sha256(lp) != REGISTERED['lists'][w]['sha256']:
                W['problems'].append('window list hash differs (G1)')
            if sha256(pp) != REGISTERED['prior_lists'][w]['sha256']:
                W['problems'].append('prior list hash differs (G1)')
        addrs = list(runs[1]['rows'])
        lists_w, meta = read_list(lp, addrs)
        if meta['date_mismatches']:
            W['problems'].append(f"{meta['date_mismatches']} list rows whose date differs from the block clock (G1d)")
        prior_rows, pmeta = read_list(pp, addrs)
        if pmeta['date_mismatches']:
            W['problems'].append(f"{pmeta['date_mismatches']} prior rows whose date differs from the block clock (G1d)")
        prior_ok, cov = prior_coverage(pmeta, meta, REGISTERED['prior_lists'][w] if check_hashes else None)
        W['prior_coverage'] = cov
        if not prior_ok:
            W['problems'].append(f'prior list does not cover the 14 days just before the window: {cov} (G1)')
        day0 = meta['first_time'] // 86400
        prior_daily = {a: daily_sums(prior_rows[a][0], prior_rows[a][1], pmeta['first_block'], pmeta['first_time'],
                                     day0) for a in addrs}
        stored = stored_loader(w) if stored_loader else None
        res, p = window_results(w, runs, lists_w, meta, prior_daily, stored, out)
        W['problems'] += p
        if res is not None:
            W.update(res)
            if check_hashes and W['set_sizes']['S1r'] != REGISTERED['S1r_counts'][w]:
                W['notes'].append(f"S1r has {W['set_sizes']['S1r']} addresses, R11 had "
                                  f"{REGISTERED['S1r_counts'][w]} (G6, reported)")
        else:
            write_empty_window_files(out, w)
        W['reportable'] = res is not None and not W['problems']
    R['verdicts'] = verdicts(R)
    (out / 'r12_results.json').write_text(json.dumps(R, indent=1, default=str) + '\n')
    (out / 'r12_tables.md').write_text(tables(R))
    (out / 'r12_sales_sha256.txt').write_text('\n'.join(sales_lines) + '\n')
    for p in REGISTERED['verdict_paths']:
        get_path(R, p)
    missing = [n for n in REGISTERED['outputs'] if not (out / n).exists()]
    if missing:
        raise SystemExit(f'registered outputs missing: {missing}')
    return R


def check_inputs(rawdata, docs):
    """The registered hashes of the input files outside the lists (registration 2.1, 2.2): manifests, condition files,
    reference aggregates, design configuration. Returns the list of problems."""
    I = REGISTERED['inputs']
    bad = []
    for d, h in I['manifests'].items():
        f = Path(rawdata) / d / 'manifest.jsonl'
        if not f.exists() or sha256(f) != h:
            bad.append(f'manifest {f}')
    for w, c in I['conditions'].items():
        if sha256(Path(docs) / c['path']) != c['sha256']:
            bad.append(f"conditions {c['path']}")
    for n, h in I['reference'].items():
        if sha256(Path(docs) / I['reference_dir'] / n) != h:
            bad.append(f'reference {n}')
    if sha256(Path(docs) / I['d2_config']['path']) != I['d2_config']['sha256']:
        bad.append('design configuration')
    return bad


def stored_loader_from_docs(docs):
    import r11_compute as r11

    def load(w):
        rows, err = r11.stored_rows(docs, w, '0.2')
        if rows is None:
            raise SystemExit(f'stored edition-7 output for {w}: {err}')
        return rows
    return load


def selfcheck(reg, work):
    """Before any real replay: the registered block equals the code, and a synthetic end-to-end run (the real replayer
    with the registered flags on the synthetic list of test_replay, then this aggregation) passes G3 for every k and
    yields every registered output path. Returns a report dict; raises SystemExit on a failure."""
    import tempfile  # noqa: F401
    import test_r12_compute as t
    reg_sha, _ = check_registration(reg)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    R = t.synthetic_end_to_end(work, reg)
    bad = [w for w in REGISTERED['windows'] if not R['windows'][w].get('reportable')]
    if bad:
        raise SystemExit(f"selfcheck: synthetic windows not reportable: "
                         f"{ {w: R['windows'][w]['problems'] for w in bad} }")
    for p in REGISTERED['verdict_paths']:
        get_path(R, p)
    rep = dict(registration_sha256=reg_sha, synthetic_windows=REGISTERED['windows'], verdict_paths_present=True,
               outputs_present=True, g3_records_equal=True, flags_as_registered=True,
               changed_for_synthetic=['input hashes, prior row counts and dates, S1r counts not checked',
                                      'bridge expectation taken from the synthetic bridge run (G2b vacuous)',
                                      'every address in S1 (no stored edition-7 output)',
                                      'address count of the synthetic list'])
    (work / 'selfcheck.json').write_text(json.dumps(rep, indent=1) + '\n')
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check-registration')
    c.add_argument('--registration', required=True)
    c.add_argument('--numpy', default=None, help='the version pinned by run_r12.sh (must equal the block)')
    c.add_argument('--scipy', default=None, help='the version pinned by run_r12.sh (must equal the block)')
    i = sub.add_parser('check-inputs')
    for x in ('--registration', '--rawdata', '--docs'):
        i.add_argument(x, required=True)
    pl = sub.add_parser('print-window')
    pl.add_argument('--registration', required=True)
    pl.add_argument('--window', required=True)
    p = sub.add_parser('print-flags')
    p.add_argument('--registration', required=True)
    p.add_argument('--kind', choices=('cost', 'bridge'), required=True)
    pk = sub.add_parser('print-ks')
    pk.add_argument('--registration', required=True)
    s = sub.add_parser('selfcheck')
    s.add_argument('--registration', required=True)
    s.add_argument('--work', required=True)
    m = sub.add_parser('compute')
    for x in ('--registration', '--raw', '--lists', '--docs', '--out', '--code-commit'):
        m.add_argument(x, required=True)
    a = ap.parse_args(argv)
    sha, _ = check_registration(a.registration)
    if a.cmd == 'check-registration':
        env = REGISTERED['environment']
        for name, pin in (('numpy', a.numpy), ('scipy', a.scipy)):
            if pin is not None and pin != env[name]:
                raise SystemExit(f'{name} pinned {pin} in run_r12.sh, registered {env[name]}')
        if a.numpy is not None and np.__version__ != env['numpy']:
            raise SystemExit(f'numpy {np.__version__} installed, registered {env["numpy"]}')
        if a.scipy is not None:
            import scipy
            if scipy.__version__ != env['scipy']:
                raise SystemExit(f'scipy {scipy.__version__} installed, registered {env["scipy"]}')
        print(sha)
    elif a.cmd == 'check-inputs':
        bad = check_inputs(a.rawdata, a.docs)
        if bad:
            raise SystemExit('input hashes differ (G1): ' + '; '.join(bad))
        print('inputs ok')
    elif a.cmd == 'print-window':
        I, w = REGISTERED['inputs'], a.window
        print('\t'.join([I['raw_dirs'][w]['window'], I['raw_dirs'][w]['prior'], REGISTERED['lists'][w]['file'],
                         REGISTERED['lists'][w]['sha256'], REGISTERED['prior_lists'][w]['file'],
                         REGISTERED['prior_lists'][w]['sha256'], I['conditions'][w]['path'], I['reference_dir'],
                         I['d2_config']['path']]))
    elif a.cmd == 'print-flags':
        print(' '.join(replay_flags(a.kind)))
    elif a.cmd == 'print-ks':
        print(','.join(map(str, REGISTERED['ks'])))
    elif a.cmd == 'selfcheck':
        print(json.dumps(selfcheck(a.registration, a.work)))
    else:
        compute(a.registration, a.raw, a.lists, a.docs, a.out, a.code_commit,
                stored_loader=stored_loader_from_docs(a.docs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
