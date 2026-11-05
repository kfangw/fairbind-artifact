"""Analysis of hold-period harness (I6) runs against the decision rules of experiments/scenarios/I6.yaml.

    python3 experiments/i6_analysis.py --runs DIR --scenario experiments/scenarios/I6.yaml --out OUT
        [--resamples 10000] [--bootstrap-seed 20260928] [--allow-dirty] [options]

Inputs. DIR is searched recursively for the controller's output layout: every result envelope
`<output>/results/<run_id>.json` (kind `fairbind-scenario-run`, scenario I6) with its observations
document `<output>/runs/<run_id>/observations/collector.json` (the full collector document; when it
is absent the rows of `collector.jsonl` are read instead and the rules that need per-sale rows report
the fields as missing) and, when present, the ledger dump `<output>/runs/<run_id>/ledger.json` (read
only for the sealed epochs of the pooled detection counts).

Run selection. Smoke runs (a `smoke` marker or a `-smoke` run id) and runs with `reportable: false`
are dropped and counted; runs that ended with an error or a timeout are counted per cell and never
enter a statistic. A reportable run is outside the premise, and left out of every decision rule
except I6-F11a and I6-F11b, when an applicable `fault_observed` item is not ok, when
`injection_draw_mismatch_count` is positive, when its largest keeper delay sum exceeds the keeper
margin in a cell whose injected delay is within the margin (M4-worst uses the path slack instead),
or when it is listed in the manual exclusion file (a harness defect explained by logs).

Every threshold is computed from the values the run recorded (the deployed profile in the
observations document and the operating point in the envelope): g, v, the bond B, k, T_hold,
T_case, marginBlocks, p, s, h, alpha, beta, c, q, r_fill, r_max, T_min, T_catch. The constants the
decision rules state as numbers are printed beside the computed values in `threshold_checks`, and a
difference is flagged, never silently used.

Outputs, in OUT: `i6_results.json` (deterministic, sorted keys, no absolute paths), `i6_tables.md`
(numbers only) and one CSV per table (`table_<name>.csv`).
"""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
from controller import scenario as scn  # noqa: E402

FORMAT = 'fairbind-i6-analysis/v1'
RUN_ID = re.compile(r'^I6-p(\d+)-r(\d+)(-smoke)?$')
TRIGGER_SAMPLE = 1
TERMINAL_CASE_STATES = ('FINAL', 'UNSERVED', 'INCONCLUSIVE', 'DELIVERED')
# The admissible cell whose keeper delay is set from the measured path (T_hold - L_actual) instead of
# the keeper margin: the keeper-margin exclusion does not apply to its runs.
PATH_SLACK_CELLS = ('M4-worst',)
POSITIVE_CONTROL_THRESHOLD = 27  # "L > 0 in fewer than 27 of 30 runs": passed, cause under investigation
FAMILY_ALPHA = 0.05
F8_REJECT_P = 0.001
F8_WINDOW_BOUND = 1e-6

# Constants the decision rules state as numbers, per profile, for comparison with the values computed
# from the runs. `tol` is the absolute tolerance of a match (the stated number's rounding).
REGISTERED = {
    'data-api-fast-v1': {
        'k_default': dict(value=23, tol=0),
        'bond_k_g_ceil_inv_p': dict(value=5_750_000, tol=0),
        'g_over_p': dict(value=250_000, tol=0),
        'p_L': dict(value=0.0405, tol=5e-5),
        'three_w1_sq': dict(value=0.004728, tol=5e-7),
        'T_case': dict(value=58_994, tol=0),
        'marginBlocks': dict(value=500, tol=0),
        'T_case_minus_margin': dict(value=58_494, tol=0),
        'T_hold': dict(value=60_000, tol=0),
        'keeper_margin': dict(value=1_006, tol=0),
        'L_actual': dict(value=29_680, tol=0),
        'p_star': dict(value=0.0582, tol=5e-5),
    },
    'open-weights-standard-v1': {
        'k_default': dict(value=37, tol=0),
        'bond_k_g_ceil_inv_p': dict(value=185_000_000, tol=0),
        'g_over_p': dict(value=5_000_000, tol=0),
        'T_case': dict(value=130_526, tol=0),
        'marginBlocks': dict(value=1_000, tol=0),
        'T_case_minus_margin': dict(value=129_526, tol=0),
        'T_hold': dict(value=132_000, tol=0),
        'keeper_margin': dict(value=1_474, tol=0),
        'L_actual': dict(value=91_180, tol=0),
    },
}
REGISTERED_FAMILY_SIZES = {
    ('I6-F1', 1, 'low'): 16, ('I6-F1', 1, 'high'): 28, ('I6-F1', 2, 'low'): 16, ('I6-F1', 2, 'high'): 28,
    ('I6-F4', 1, 'low'): 8, ('I6-F4', 1, 'high'): 11, ('I6-F4', 2, 'low'): 8, ('I6-F4', 2, 'high'): 11,
    ('I6-F5', 1, 'low'): 16, ('I6-F5', 1, 'high'): 28, ('I6-F5', 2, 'low'): 16, ('I6-F5', 2, 'high'): 28,
    ('I6-F10', None, None): 40, ('I6-F12a', 1, None): 9, ('I6-F9', None, None): 3, ('I6-F6', None, None): 3,
}
# F grid: the predicted fraction of undetected episodes (1 - p*)^m and the predicted mean of Y_F in g.
REGISTERED_F_PREDICTIONS = {1: dict(undetected=0.94, mean_g=-0.5), 5: dict(undetected=0.74, mean_g=-2.7),
                            25: dict(undetected=0.23, mean_g=-13.8)}
# V grid: the stated predictions (8/N)^R and the R they use (none stated for 12).
REGISTERED_V_PREDICTIONS = {9: dict(R=9, value=0.346), 12: dict(R=None, value=None),
                            20: dict(R=14, value=2.7e-6), 40: dict(R=14, value=1.6e-10)}
REGISTERED_F8 = dict(windows_planned=150, reject_p=F8_REJECT_P, window_bound=F8_WINDOW_BOUND)

KINDS = {
    'I6-F1': 'expectation_test', 'I6-F2': 'expectation_test (auxiliary)', 'I6-F3': 'expectation_test',
    'I6-F4': 'expectation_test', 'I6-F5': 'expectation_test', 'I6-F6': 'expectation_test (lower bound)',
    'I6-F8': 'rare_event_test', 'I6-F9': 'expectation_test (exact binomial)',
    'I6-F10': 'expectation_test (exact binomial, lower bound)', 'I6-F11a': 'implementation_invariant',
    'I6-F11b': 'implementation_invariant', 'I6-F12a': 'expectation_test', 'I6-F12b': 'implementation_invariant',
    'I6-PC': 'positive_control', 'I6-V': 'descriptive',
}

# The observation fields each decision rule reads (see the module README section and the coverage notes).
REQUIRED = {
    'I6-F1': ('metrics.episode_exposure', 'metrics.episode_end_mode', 'run.g', 'op.p_ceiling', 'run.keeper_margin'),
    'I6-F2': ('metrics.episode_exposure', 'run.g', 'detection_counts'),
    'I6-F3': ('metrics.episode_exposure', 'run.g', 'op.p_ceiling', 'op.bucket_capacity', 'op.refill_per_block',
              'env.judgment_delay_blocks', 'run.t_hold', 'params.scale_factor'),
    'I6-F4': ('metrics.episode_net_gain', 'run.seller_penalty', 'run.failure_limit', 'run.g', 'op.p_ceiling'),
    'I6-F5': ('metrics.episode_net_gain', 'run.seller_penalty', 'run.failure_limit', 'run.g', 'op.p_ceiling'),
    'I6-F6': ('metrics.episode_exposure', 'metrics.achieved_settlement_rate', 'op.L_min_blocks', 'run.t_hold',
              'doc.sales'),
    'I6-F8': ('metrics.honest_windows',),
    'I6-F9': ('doc.sales', 'op.h', 'op.alpha', 'op.c'),
    'I6-F10': ('detection_counts', 'op.pi', 'op.h', 'op.beta'),
    'I6-F11a': ('metrics.case_path_minus_keeper', 'run.t_case', 'run.margin_blocks'),
    'I6-F11b': ('metrics.case_path_minus_keeper', 'metrics.post_detection_leak', 'run.t_case', 'run.keeper_margin'),
    'I6-F12a': ('metrics.y_f', 'metrics.episode_end_mode', 'run.seller_penalty', 'run.failure_limit'),
    'I6-F12b': ('metrics.bond_exit_finalized_block', 'metrics.bond_exit_deferred_balance',
                'metrics.bond_exit_open_sampled_cases'),
    'I6-PC': ('metrics.post_detection_leak',),
    'I6-V': ('doc.sales', 'metrics.assignment_failure'),
    'cap_off_check': ('metrics.rejected_settlement_count',),
}


class InputError(Exception):
    """An input is missing or malformed."""


# ---------------------------------------------------------------------------------------------
# Statistics (standard library only)


def _log_binom_pmf(i, n, p):
    return math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * math.log(p) + (n - i) * math.log1p(-p)


def _log_sum(terms):
    if not terms:
        return -math.inf
    top = max(terms)
    if top == -math.inf:
        return -math.inf
    return top + math.log(math.fsum(math.exp(t - top) for t in terms))


def binom_sf(x, n, p):
    """P(X >= x) for X ~ Binomial(n, p)."""
    if x <= 0:
        return 1.0
    if x > n:
        return 0.0
    if p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    return min(1.0, math.exp(_log_sum([_log_binom_pmf(i, n, p) for i in range(x, n + 1)])))


def binom_cdf(x, n, p):
    """P(X <= x) for X ~ Binomial(n, p)."""
    if x < 0:
        return 0.0
    if x >= n:
        return 1.0
    if p <= 0:
        return 1.0
    if p >= 1:
        return 0.0
    return min(1.0, math.exp(_log_sum([_log_binom_pmf(i, n, p) for i in range(0, x + 1)])))


def _bisect(f, target, increasing):
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        v = f(mid)
        if (v < target) == increasing:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return (lo + hi) / 2


def clopper_pearson(x, n, level=0.95, sides=2):
    """Exact interval [lo, hi] for a binomial proportion. sides=2: the two-sided interval at `level`;
    sides=1: the one-sided bounds at `level` (lo is the lower bound of [lo, 1], hi of [0, hi])."""
    if not (isinstance(x, int) and isinstance(n, int)) or n <= 0 or not 0 <= x <= n:
        raise ValueError('clopper_pearson needs counts 0 <= x <= n with n > 0')
    tail = (1 - level) / 2 if sides == 2 else 1 - level
    lo = 0.0 if x == 0 else _bisect(lambda q: binom_sf(x, n, q), tail, increasing=True)
    hi = 1.0 if x == n else _bisect(lambda q: binom_cdf(x, n, q), tail, increasing=False)
    return [lo, hi]


def seed_of(base, key):
    return int.from_bytes(hashlib.sha256(f'{base}:{key}'.encode()).digest()[:8], 'big')


def quantile(sorted_values, q):
    """Linear interpolation between order statistics (as experiments/analysis.py)."""
    x = (len(sorted_values) - 1) * q
    i = int(x)
    f = x - i
    return sorted_values[i] * (1 - f) + sorted_values[min(i + 1, len(sorted_values) - 1)] * f


def bootstrap_means(values, resamples, seed):
    """Sorted means of `resamples` resamples of the run values (runs are the unit)."""
    rng = random.Random(seed)
    n = len(values)
    return sorted(math.fsum(rng.choices(values, k=n)) / n for _ in range(resamples))


def mean_summary(values, resamples, seed, threshold=None, direction='upper'):
    """Mean, bootstrap percentile interval and one-sided bootstrap p value against `threshold`.

    direction 'upper': the statement E[Y] <= t; p = share of resampled means <= t (H0: E[Y] <= t).
    direction 'lower': the statement E[Y] >= t; p = share of resampled means >= t (H0: E[Y] >= t)."""
    if not values:
        return dict(n=0, mean=None, interval_95=None, one_sided_95=None, max=None, min=None, p=None)
    boot = bootstrap_means(values, resamples, seed)
    out = dict(n=len(values), mean=math.fsum(values) / len(values), max=max(values), min=min(values),
               interval_95=[quantile(boot, 0.025), quantile(boot, 0.975)],
               one_sided_95=[quantile(boot, 0.05), quantile(boot, 0.95)], p=None)
    if threshold is not None:
        if direction == 'upper':
            out['p'] = sum(1 for b in boot if b <= threshold) / len(boot)
        else:
            out['p'] = sum(1 for b in boot if b >= threshold) / len(boot)
    return out


def holm(pvalues, alpha=FAMILY_ALPHA):
    """Holm step-down: {key: (adjusted p, rejected)} for {key: p}; ties are ordered by key."""
    order = sorted(pvalues.items(), key=lambda kv: (kv[1], str(kv[0])))
    m = len(order)
    out, running = {}, 0.0
    for j, (key, p) in enumerate(order):
        running = max(running, min(1.0, (m - j) * p))
        out[key] = (running, running <= alpha)
    return out


def ols_slope(xs, ys):
    n = len(xs)
    if n < 2:
        return None
    mx, my = math.fsum(xs) / n, math.fsum(ys) / n
    sxx = math.fsum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return math.fsum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def slope_summary(points, resamples, seed):
    """Least-squares slope of y on x with a run-bootstrap percentile interval."""
    slope = ols_slope([p[0] for p in points], [p[1] for p in points])
    if slope is None:
        return dict(n=len(points), slope=None, interval_95=None)
    rng = random.Random(seed)
    boot = []
    for _ in range(resamples):
        s = rng.choices(points, k=len(points))
        b = ols_slope([p[0] for p in s], [p[1] for p in s])
        if b is not None:
            boot.append(b)
    boot.sort()
    return dict(n=len(points), slope=slope, interval_95=[quantile(boot, 0.025), quantile(boot, 0.975)] if boot else None,
                resamples_with_slope=len(boot))


def verdict_of(summary, threshold, direction, rejected, certify_bound):
    """The three verdicts: excess_detected (the Holm-corrected one-sided test rejects), certified (the
    interval lies on the statement's side of the threshold) or withheld (the interval holds it)."""
    if summary is None or summary.get('n', 0) == 0 or threshold is None:
        return 'no_data'
    if rejected:
        return 'excess_detected'
    lo, hi = summary[certify_bound]
    if direction == 'upper':
        return 'certified' if hi <= threshold else 'withheld'
    return 'certified' if lo >= threshold else 'withheld'


# ---------------------------------------------------------------------------------------------
# Inputs


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise InputError(f'{path}: {exc}') from exc


def _read_rows(path):
    metrics = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('{'):
            row = json.loads(line)
            metrics[row['metric']] = row['value']
    return dict(format='collector-rows', run={}, metrics=metrics)


def find_envelopes(runs_dir):
    """Every I6 result envelope under runs_dir, in path order."""
    out = []
    for path in sorted(Path(runs_dir).rglob('*.json')):
        if path.parent.name != 'results':
            continue
        try:
            env = json.loads(path.read_text())
        except ValueError:
            continue
        if isinstance(env, dict) and env.get('kind') == 'fairbind-scenario-run' and env.get('scenario') == 'I6':
            out.append((path, env))
    return out


def load_run(env_path, env):
    """The observations document (full, else rows) and the sealed epochs of the seller (from the
    ledger dump) of one envelope."""
    run_dir = env_path.parent.parent / 'runs' / env['run_id']
    obs = run_dir / 'observations'
    doc, source = None, None
    if (obs / 'collector.json').exists():
        doc, source = _read_json(obs / 'collector.json'), 'document'
    elif (obs / 'collector.jsonl').exists():
        doc, source = _read_rows(obs / 'collector.jsonl'), 'rows'
    sealed = None
    ledger = run_dir / 'ledger.json'
    if doc is not None and ledger.exists():
        seller = (doc.get('run') or {}).get('seller_id')
        led = _read_json(ledger)
        sealed = sorted({e['args']['epoch'] for e in led.get('events', [])
                         if e.get('event') == 'EpochSealed' and (seller is None or e['args'].get('sellerId') == seller)})
    return doc, source, sealed


# ---------------------------------------------------------------------------------------------
# Runs


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _frac(v):
    return Fraction(str(v)) if _num(v) is not None else None


class Run:
    def __init__(self, env_path, env, doc, source, sealed, point):
        self.env_path, self.env, self.doc, self.source, self.sealed, self.point = env_path, env, doc, source, sealed, point
        self.run_id = env['run_id']
        self.metrics = (doc or {}).get('metrics') or {}
        self.info = (doc or {}).get('run') or {}
        op = env.get('operating_point') or {}
        self.op_values = op.get('values') or {}
        self.op_key = op.get('sha256') or 'unknown'
        self.profile = op.get('profile')
        self.params = env.get('parameters') or {}
        self.exclusions = []      # premise-outside reasons (every reason)
        self.integrity = []       # the reasons that are not the keeper margin

    # Values the run recorded -----------------------------------------------------------------
    def value(self, spec):
        where, _, name = spec.partition('.')
        if where == 'metrics':
            return self.metrics.get(name)
        if where == 'run':
            return self.info.get(name)
        if where == 'op':
            return self.op_values.get(name)
        if where == 'env':
            return self.env.get(name)
        if where == 'params':
            return self.params.get(name)
        if spec == 'doc.sales':
            return (self.doc or {}).get('sales')
        if spec == 'detection_counts':
            return self.detection_counts()
        raise KeyError(spec)

    def values(self):
        """The quantities the thresholds use, from the deployed profile and the operating point."""
        op, info = self.op_values, self.info
        v = dict(
            g=_num(info.get('g')), v=_num(info.get('v')), B=_num(info.get('seller_penalty')),
            k=_num(info.get('failure_limit')), deduction=_num(info.get('deduction')),
            t_hold=_num(info.get('t_hold')), t_case=_num(info.get('t_case')), margin=_num(info.get('margin_blocks')),
            keeper_margin=_num(info.get('keeper_margin')), p=_num(op.get('p_ceiling')), s=_num(op.get('pi')),
            h=_num(op.get('h')), alpha=_num(op.get('alpha')), beta=_num(op.get('beta')), c=_num(op.get('c')),
            q=_num(op.get('bucket_capacity')), r_fill=_num(op.get('refill_per_block')),
            r_max=_num(op.get('lambda_max_per_block')), t_min=_num(op.get('L_min_blocks')),
            t_catch=_num(self.env.get('judgment_delay_blocks')) if _num(self.env.get('judgment_delay_blocks')) is not None
            else _num(op.get('L_blocks')),
            l_actual=_num(op.get('L_actual_blocks')), op_k=_num(op.get('failureLimit')),
            n=_num(self.params.get('scale_factor')), kappa=_num(self.params.get('keeper_delay_budget_blocks')),
            m=_num(self.params.get('finite_attack_cheat_sales')))
        if v['kappa'] is None:
            v['kappa'] = _num(info.get('kappa'))
        if v['g'] is None:
            v['g'] = _num(self.params.get('bad_sale_gain_atomic'))
        if v['t_hold'] is None:
            v['t_hold'] = _num(self.env.get('effective_hold_period_blocks'))
        if self.params.get('injection') == 'honest_error_off':
            v['alpha_injected'], v['c_injected'] = 0.0, 0.0
        else:
            v['alpha_injected'], v['c_injected'] = v['alpha'], v['c']
        return v

    # Per-run quantities --------------------------------------------------------------------------
    def episode(self, field, e):
        lst = self.metrics.get(field)
        if not isinstance(lst, list) or len(lst) < e:
            return None
        return lst[e - 1]

    def kappa_sigma_max(self):
        m = _num(self.metrics.get('keeper_delay_sum_max_blocks'))
        if m is not None:
            return m
        lst = self.metrics.get('keeper_delay_sum_blocks')
        if isinstance(lst, list):
            return max(lst) if lst else 0
        return None

    def detection_counts(self):
        """(effective detections, eligible bad sales) of realized_detection_rate: bad sales settled in
        sealed epochs whose case is terminal or that have none. Needs the per-sale rows and the sealed
        epochs (ledger dump, or a `detection_eligible` flag per sale row); None when unavailable."""
        sales = (self.doc or {}).get('sales')
        if sales is None:
            return None
        bad = [r for r in sales if r.get('bad')]
        if bad and all('detection_eligible' in r for r in bad):
            eligible = [r for r in bad if r['detection_eligible']]
        elif self.sealed is not None:
            sealed = set(self.sealed)
            eligible = [r for r in bad if r.get('epoch') in sealed
                        and (r.get('case_state') is None or r.get('case_state') in TERMINAL_CASE_STATES)]
        elif not bad:
            eligible = []
        else:
            return None
        return (sum(1 for r in eligible if r.get('effective_detection')), len(eligible))

    def sampled_honest_counts(self):
        """(sampled honest cases ended FINAL FAIL, ended UNSERVED, sampled honest cases in a terminal state)."""
        sales = (self.doc or {}).get('sales')
        if sales is None:
            return None
        rows = [r for r in sales if not r.get('bad') and r.get('case_trigger') == TRIGGER_SAMPLE
                and r.get('case_state') in TERMINAL_CASE_STATES]
        fail = sum(1 for r in rows if r.get('case_state') == 'FINAL' and r.get('final_verdict') == 'FAIL')
        unserved = sum(1 for r in rows if r.get('case_state') == 'UNSERVED')
        return fail, unserved, len(rows)

    def buyer_disputes(self):
        sales = (self.doc or {}).get('sales')
        if sales is None:
            return None
        return sum(1 for r in sales if r.get('case_trigger') not in (None, 0, TRIGGER_SAMPLE))


# ---------------------------------------------------------------------------------------------
# Plan points


def plan_points(sc):
    """The scenario's points in controller order (the index is the run id's pNN)."""
    cells = {c['name']: c for c in scn.cells(sc)}
    out = []
    for index, point in enumerate(scn.sweep_points(sc)):
        cell = cells[point['cell']]
        swept = list((cell.get('sweep') or {}).keys())
        label = point['cell'] + ('[' + ','.join(f'{k}={point[k]}' for k in swept) + ']' if swept else '')
        out.append(dict(index=index, cell=point['cell'], label=label, role=cell.get('role', 'cheater'),
                        rate_class=cell.get('rate_class'), repetitions=cell['repetitions'],
                        min_repetitions=cell.get('min_repetitions'), profile=cell.get('profile', scn.DEFAULT_CELL_PROFILE),
                        judgment_path=point.get('judgment_path', 'normal'),
                        parameters={k: point[k] for k in sorted(point) if k != 'cell'}, swept=swept))
    return out


# ---------------------------------------------------------------------------------------------
# Analysis


class Options:
    def __init__(self, resamples=10000, bootstrap_seed=20260928, certify_bound='interval_95',
                 open_episodes='include', f3_f6_statistic='episode', f2_episodes=(1,), f2_bound='two_sided',
                 f12b_scope='premise', pc_episode='first', p_star=None, honest_w='three_w1_sq',
                 v_rounds=None, ignore_fault_items=(), manual_exclusions=None, second_episode_min_runs=None,
                 f6_rule='holm'):
        self.resamples = resamples
        self.bootstrap_seed = bootstrap_seed
        self.certify_bound = certify_bound
        self.open_episodes = open_episodes
        self.f3_f6_statistic = f3_f6_statistic
        self.f2_episodes = tuple(f2_episodes)
        self.f2_bound = f2_bound
        self.f12b_scope = f12b_scope
        self.pc_episode = pc_episode
        self.p_star = p_star if p_star is not None else {'data-api-fast-v1': REGISTERED['data-api-fast-v1']['p_star']['value']}
        self.honest_w = honest_w
        self.v_rounds = v_rounds if v_rounds is not None else {n: d['R'] for n, d in REGISTERED_V_PREDICTIONS.items()}
        self.ignore_fault_items = tuple(ignore_fault_items)
        self.manual_exclusions = dict(manual_exclusions or {})
        self.second_episode_min_runs = second_episode_min_runs
        self.f6_rule = f6_rule

    def as_dict(self):
        return dict(resamples=self.resamples, bootstrap_seed=self.bootstrap_seed, certify_bound=self.certify_bound,
                    open_episodes=self.open_episodes, f3_f6_statistic=self.f3_f6_statistic,
                    f2_episodes=list(self.f2_episodes), f2_bound=self.f2_bound, f12b_scope=self.f12b_scope,
                    pc_episode=self.pc_episode, p_star=dict(sorted(self.p_star.items())), honest_w=self.honest_w,
                    v_rounds={str(k): v for k, v in sorted(self.v_rounds.items())},
                    ignore_fault_items=sorted(self.ignore_fault_items),
                    manual_exclusions=dict(sorted(self.manual_exclusions.items())),
                    second_episode_min_runs=self.second_episode_min_runs, f6_rule=self.f6_rule)


def _ceil_inv(p):
    f = _frac(p)
    return None if not f else math.ceil(1 / f)


def derived(v, p_star=None):
    """Thresholds of one point from the recorded values."""
    d = {}
    g, p, B, k = v.get('g'), v.get('p'), v.get('B'), v.get('k')
    if g is not None and p:
        d['g_over_p'] = float(Fraction(g) / _frac(p))
        d['ceil_inv_p'] = _ceil_inv(p)
    if B is not None and k:
        d['B_over_k'] = B / k
    if 'g_over_p' in d and 'B_over_k' in d:
        d['g_over_p_minus_B_over_k'] = d['g_over_p'] - d['B_over_k']
    if g is not None and k and 'ceil_inv_p' in d:
        d['bond_k_g_ceil_inv_p'] = k * g * d['ceil_inv_p']
        if B is not None:
            d['bond_at_least_k_g_ceil_inv_p'] = B >= d['bond_k_g_ceil_inv_p']
    s, h, beta, alpha, c = v.get('s'), v.get('h'), v.get('beta'), v.get('alpha'), v.get('c')
    if None not in (s, h, beta):
        d['p_L'] = s * (h * (1 - beta)) ** 2
    if None not in (h, alpha, c):
        d['w1'] = h * alpha + (1 - h) * c
        d['three_w1_sq'] = 3 * d['w1'] ** 2
    if v.get('t_case') is not None and v.get('margin') is not None:
        d['T_case_minus_margin'] = v['t_case'] - v['margin']
    if p_star is not None:
        d['p_star'] = p_star
    return d


class Analysis:
    def __init__(self, sc, options):
        self.sc = sc
        self.o = options
        self.points = plan_points(sc)
        self.analysis = sc.get('analysis') or {}
        self.conditions_cfg = self.analysis.get('conditions') or {}
        self.families_cfg = self.analysis.get('holm_families') or {}
        pruning = self.analysis.get('pruning') or {}
        if self.o.second_episode_min_runs is None:
            self.o.second_episode_min_runs = pruning.get('min_second_episode_runs', 30)
        self.runs = []
        self.dropped = {}
        self.failed = []
        self.no_observations = []
        self.groups = {}
        self.notes = []

    # Loading --------------------------------------------------------------------------------------
    def add(self, env_path, env, loader=load_run):
        rid = env.get('run_id') or ''
        match = RUN_ID.match(rid)
        if env.get('smoke') or (match and match.group(3)) or rid.endswith('-smoke'):
            self.dropped.setdefault('smoke', []).append(rid)
            return
        if not env.get('reportable'):
            reason = 'dirty' if env.get('dirty') else ('status_' + str(env.get('status')) if env.get('status') != 'completed'
                                                      else 'not_reportable')
            if env.get('status') != 'completed' and not env.get('dirty'):
                self.failed.append(dict(run_id=rid, status=env.get('status'), error=env.get('error')))
                point = self.points[int(match.group(1))] if match and int(match.group(1)) < len(self.points) else None
                if point is not None:
                    self.groups.setdefault((point['index'], (env.get('operating_point') or {}).get('sha256') or 'unknown'),
                                           dict(runs=[], failed=[], no_obs=[]))['failed'].append(rid)
                return
            self.dropped.setdefault(reason, []).append(rid)
            return
        if not match or int(match.group(1)) >= len(self.points):
            self.dropped.setdefault('unplaced_run_id', []).append(rid)
            return
        point = self.points[int(match.group(1))]
        if (env.get('cell') or {}).get('name') not in (None, point['cell']):
            self.dropped.setdefault('cell_mismatch', []).append(rid)
            return
        op_key = (env.get('operating_point') or {}).get('sha256') or 'unknown'
        if any(r.run_id == rid and r.op_key == op_key for r in self.runs):
            # The same planned run twice at one operating point (a re-run after the k change keeps the
            # run id and has another operating point).
            self.dropped.setdefault('duplicate_run_id', []).append(rid)
            return
        doc, source, sealed = loader(env_path, env)
        run = Run(env_path, env, doc, source, sealed, point)
        run.repetition = int(match.group(2))
        key = (point['index'], run.op_key)
        grp = self.groups.setdefault(key, dict(runs=[], failed=[], no_obs=[]))
        if doc is None:
            self.no_observations.append(rid)
            grp['no_obs'].append(rid)
            return
        self.classify(run)
        self.runs.append(run)
        grp['runs'].append(run)

    def classify(self, run):
        v = run.values()
        for it in run.metrics.get('fault_observed') or []:
            if not it.get('applicable') or it.get('ok') or it.get('item') in self.o.ignore_fault_items:
                continue
            if it.get('item') == 'post_switch_no_confirmed_failure':
                ps = (run.metrics.get('post_switch_confirmed_failures') or [{}])[0]
                if ps.get('FAIL'):
                    run.integrity.append('post_switch_confirmed_failure:FAIL')
                if ps.get('UNSERVED'):
                    run.integrity.append('post_switch_confirmed_failure:UNSERVED')
                if not ps.get('FAIL') and not ps.get('UNSERVED'):
                    run.integrity.append('fault_observed:post_switch_no_confirmed_failure')
            else:
                run.integrity.append('fault_observed:' + str(it.get('item')))
        if 'fault_observed' not in run.metrics:
            run.integrity.append('fault_observed:missing')
        mismatch = _num(run.metrics.get('injection_draw_mismatch_count'))
        if mismatch:
            run.integrity.append('injection_draw_mismatch')
        if run.run_id in self.o.manual_exclusions:
            run.integrity.append('manual:' + str(self.o.manual_exclusions[run.run_id]))
        run.exclusions = list(run.integrity)
        kmax = run.kappa_sigma_max()
        if (run.point['cell'] not in PATH_SLACK_CELLS and v['keeper_margin'] is not None and kmax is not None
                and not self.cell_outside(run.point, v) and kmax > v['keeper_margin']):
            run.exclusions.append('keeper_margin_exceeded')

    @staticmethod
    def cell_outside(point, v):
        """Why a whole point is outside the premise by design (None when it is not)."""
        if v.get('t_hold') is not None and v.get('t_case') is not None and v['t_hold'] < v['t_case']:
            return ['hold_below_T_case']
        if point['cell'] not in PATH_SLACK_CELLS and v.get('kappa') is not None and v.get('keeper_margin') is not None \
                and v['kappa'] > v['keeper_margin']:
            return ['keeper_delay_above_margin']
        return None

    # Group helpers ---------------------------------------------------------------------------------
    def group_runs(self, point_index, op, scope='premise'):
        grp = self.groups.get((point_index, op))
        if not grp:
            return []
        runs = sorted(grp['runs'], key=lambda r: r.run_id)
        if scope == 'premise':
            return [r for r in runs if not r.exclusions]
        if scope == 'integrity':
            return [r for r in runs if not r.integrity]
        return runs

    def ops_of(self, point_index):
        return sorted({op for (i, op) in self.groups if i == point_index})

    def point_values(self, point_index, op):
        runs = self.group_runs(point_index, op, scope='all')
        if not runs:
            return None, []
        vals = [r.values() for r in runs]
        base = vals[0]
        differ = sorted({k for vv in vals[1:] for k in base if vv.get(k) != base.get(k)})
        return base, differ

    def episode_values(self, runs, field, e):
        out = []
        for r in runs:
            val = r.episode(field, e)
            mode = r.episode('episode_end_mode', e)
            if _num(val) is None:
                continue
            if self.o.open_episodes == 'exclude' and mode == 'open':
                continue
            out.append((r.run_id, val))
        return out

    def rate_bound(self, x, n):
        """The exact bounds that certify a proportion: the two-sided 95% interval, or the one-sided 95%
        bounds with --certify-bound one_sided_95."""
        return clopper_pearson(x, n, 0.95, 1 if self.o.certify_bound == 'one_sided_95' else 2)

    def seed(self, key):
        return seed_of(self.o.bootstrap_seed, key)

    def points_of_cells(self, cells):
        return [p for p in self.points if p['cell'] in set(cells)]

    # Expectation families ------------------------------------------------------------------------
    def run_family(self, name, condition, members, direction, episode=None, rate_class=None):
        """members: [(point, op, values, threshold, extra)]. Holm over the members with data."""
        summaries, pvals = {}, {}
        for point, op, values, threshold, extra in members:
            key = (point['index'], op)
            s = mean_summary(values, self.o.resamples, self.seed(f'{name}:{point["index"]}:{op}'), threshold, direction)
            summaries[key] = (point, op, s, threshold, extra)
            if s['n'] and threshold is not None and s['p'] is not None:
                pvals[key] = s['p']
        adj = holm(pvals)
        rows = []
        for key in sorted(summaries):
            point, op, s, threshold, extra = summaries[key]
            a = adj.get(key)
            row = dict(point=point['index'], label=point['label'], op=op, threshold=threshold, summary=s,
                       p_holm=a[0] if a else None, rejected=bool(a and a[1]),
                       verdict=verdict_of(s, threshold, direction, bool(a and a[1]), self.o.certify_bound))
            row.update(extra or {})
            rows.append(row)
        reg = REGISTERED_FAMILY_SIZES.get((condition, episode, rate_class))
        return dict(name=name, condition=condition, episode=episode, rate_class=rate_class, direction=direction,
                    size=len(pvals), registered_size=reg, size_matches=(reg == len(pvals)) if reg is not None else None,
                    members=rows)

    def yaml_families(self, condition):
        return [(n, f) for n, f in sorted(self.families_cfg.items()) if f.get('condition') == condition]

    def ops_all(self):
        return sorted({op for (_, op) in self.groups})

    def members_per_op(self, points):
        by_op = {}
        for p in points:
            for op in self.ops_of(p['index']):
                by_op.setdefault(op, []).append(p)
        return by_op

    def cond_exposure_like(self, condition, field, threshold_of, direction='upper', point_filter=None):
        fams = []
        for name, f in self.yaml_families(condition):
            pts = self.points_of_cells(f['cells'])
            for op, plist in sorted(self.members_per_op(pts).items()):
                members = []
                ep = f.get('episode', 1)
                for p in plist:
                    base, _ = self.point_values(p['index'], op)
                    if base is None:
                        continue
                    d = derived(base)
                    if point_filter and not point_filter(p, base, d):
                        continue
                    runs = self.group_runs(p['index'], op)
                    vals = self.episode_values(runs, field, ep)
                    extra = dict(runs_included=len(runs), runs_with_value=len(vals))
                    if ep == 2:
                        finished = sum(1 for r in runs if r.episode('episode_end_mode', 2) not in (None, 'open'))
                        extra['finished_second_episodes'] = finished
                        if finished < self.o.second_episode_min_runs:
                            extra['not_judged'] = f'{finished} finished second episodes < {self.o.second_episode_min_runs}'
                            vals = []
                    members.append((p, op, [x for _, x in vals], threshold_of(p, base, d, runs), extra))
                fams.append(self.run_family(f'{name}@{op[:8]}', condition, members, direction, ep, f.get('rate_class')))
        return fams

    # Conditions --------------------------------------------------------------------------------
    def cond_f1(self):
        fams = self.cond_exposure_like('I6-F1', 'episode_exposure', lambda p, b, d, runs: d.get('g_over_p'))
        # M4-worst beside the rule: without the runs that have a case longer than T_hold (5.3).
        sens = []
        for p in self.points_of_cells(PATH_SLACK_CELLS):
            for op in self.ops_of(p['index']):
                base, _ = self.point_values(p['index'], op)
                runs = self.group_runs(p['index'], op)
                over = [r.run_id for r in runs if any(x > (base or {}).get('t_hold', math.inf)
                                                      for x in (r.metrics.get('case_path_blocks') or []))]
                excess = [max(x - base['t_hold'] for x in r.metrics['case_path_blocks']) for r in runs if r.run_id in over]
                for e in (1, 2):
                    vals = [x for rid, x in self.episode_values(runs, 'episode_exposure', e) if rid not in over]
                    d = derived(base) if base else {}
                    s = mean_summary(vals, self.o.resamples, self.seed(f'F1-sens:{p["index"]}:{op}:{e}'),
                                     d.get('g_over_p'), 'upper')
                    sens.append(dict(point=p['index'], label=p['label'], op=op, episode=e, runs_over_T_hold=over,
                                     largest_excess_blocks=max(excess) if excess else None, summary=s,
                                     threshold=d.get('g_over_p')))
        return dict(families=fams, m4_worst_without_runs_over_T_hold=sens)

    def detection_pool(self, runs):
        det = elig = 0
        missing = []
        for r in runs:
            c = r.detection_counts()
            if c is None:
                missing.append(r.run_id)
                continue
            det += c[0]
            elig += c[1]
        return det, elig, missing

    def cond_f2(self):
        fams = []
        for name, f in self.yaml_families('I6-F2'):
            pts = self.points_of_cells(f['cells'])
            for ep in self.o.f2_episodes:
                for op, plist in sorted(self.members_per_op(pts).items()):
                    members = []
                    for p in plist:
                        base, _ = self.point_values(p['index'], op)
                        if base is None:
                            continue
                        runs = self.group_runs(p['index'], op)
                        det, elig, missing = self.detection_pool(runs)
                        lower = None
                        if elig:
                            lower = clopper_pearson(det, elig, 0.95, 2 if self.o.f2_bound == 'two_sided' else 1)[0]
                        threshold = None if lower is None or base.get('g') is None else (base['g'] / lower if lower > 0 else None)
                        vals = self.episode_values(runs, 'episode_exposure', ep)
                        members.append((p, op, [x for _, x in vals], threshold,
                                        dict(detections=det, eligible=elig, p_star_L=lower, runs_without_counts=missing)))
                    fams.append(self.run_family(f'{name}-episode{ep}@{op[:8]}', 'I6-F2', members, 'upper', ep))
        return dict(families=fams)

    def cond_f3(self):
        def thr(p, base, d, runs):
            kh = max([r.kappa_sigma_max() or 0 for r in runs] or [0])
            need = ('g', 'p', 'q', 'r_fill', 't_catch', 't_hold', 'n')
            if any(base.get(x) is None for x in need):
                return None
            ell = max(0, base['t_catch'] + kh - base['t_hold'])
            return base['g'] * (1 / base['p'] + base['n'] * (base['q'] + base['r_fill'] * ell))
        field = 'episode_exposure' if self.o.f3_f6_statistic == 'episode' else None
        fams = self.cond_exposure_like('I6-F3', field or 'episode_exposure', thr) if field else self._run_total('I6-F3', thr, 'upper')
        # point prediction g(1/p + r_max (T_catch + kappa_Sigma - T_hold)+), descriptive
        preds = []
        for p in self.points_of_cells(self.conditions_cfg.get('I6-F3', {}).get('cells', [])):
            for op in self.ops_of(p['index']):
                base, _ = self.point_values(p['index'], op)
                runs = self.group_runs(p['index'], op)
                if base is None or any(base.get(x) is None for x in ('g', 'p', 'r_max', 't_catch', 't_hold')):
                    continue
                kh = max([r.kappa_sigma_max() or 0 for r in runs] or [0])
                preds.append(dict(point=p['index'], label=p['label'], op=op, kappa_hat=kh, point_prediction=base['g'] * (
                    1 / base['p'] + base['r_max'] * max(0, base['t_catch'] + kh - base['t_hold']))))
        return dict(families=fams, point_predictions=preds)

    def _run_total(self, condition, thr, direction, run_filter=None):
        fams = []
        for name, f in self.yaml_families(condition):
            pts = self.points_of_cells(f['cells'])
            for op, plist in sorted(self.members_per_op(pts).items()):
                members = []
                for p in plist:
                    base, _ = self.point_values(p['index'], op)
                    if base is None:
                        continue
                    runs = [r for r in self.group_runs(p['index'], op) if not run_filter or run_filter(r)]
                    vals = [r.metrics['released_exposure'] for r in runs if _num(r.metrics.get('released_exposure')) is not None]
                    members.append((p, op, vals, thr(p, base, derived(base), runs), dict(runs_included=len(runs))))
                fams.append(self.run_family(f'{name}@{op[:8]}', condition, members, direction))
        return fams

    def cond_f4(self):
        return dict(families=self.cond_exposure_like(
            'I6-F4', 'episode_net_gain', lambda p, b, d, runs: 0,
            point_filter=lambda p, b, d: bool(d.get('bond_at_least_k_g_ceil_inv_p'))))

    def cond_f5(self):
        return dict(families=self.cond_exposure_like(
            'I6-F5', 'episode_net_gain', lambda p, b, d, runs: d.get('g_over_p_minus_B_over_k')))

    def cond_f6(self):
        def no_dispute(r):
            n = r.buyer_disputes()
            return n == 0

        def thr(p, base, d, runs):
            rates = [r.metrics['achieved_settlement_rate'] for r in runs
                     if _num(r.metrics.get('achieved_settlement_rate')) is not None]
            if not rates or any(base.get(x) is None for x in ('g', 't_min', 't_hold')):
                return None
            rbar = math.fsum(rates) / len(rates)
            return base['g'] * (rbar * (base['t_min'] - base['t_hold']) - 1)
        fams = []
        for name, f in self.yaml_families('I6-F6'):
            pts = self.points_of_cells(f['cells'])
            for op, plist in sorted(self.members_per_op(pts).items()):
                members = []
                for p in plist:
                    base, _ = self.point_values(p['index'], op)
                    if base is None:
                        continue
                    all_runs = self.group_runs(p['index'], op)
                    runs = [r for r in all_runs if no_dispute(r)]
                    if self.o.f3_f6_statistic == 'episode':
                        vals = [x for _, x in self.episode_values(runs, 'episode_exposure', 1)]
                    else:
                        vals = [r.metrics['released_exposure'] for r in runs if _num(r.metrics.get('released_exposure')) is not None]
                    rates = [r.metrics.get('achieved_settlement_rate') for r in runs]
                    members.append((p, op, vals, thr(p, base, derived(base), runs), dict(
                        runs_included=len(all_runs), runs_without_disputes=len(runs),
                        mean_achieved_rate=(math.fsum(x for x in rates if _num(x) is not None) / sum(1 for x in rates if _num(x) is not None))
                        if any(_num(x) is not None for x in rates) else None)))
                fam = self.run_family(f'{name}@{op[:8]}', 'I6-F6', members, 'lower')
                if self.o.f6_rule == 'upper_bound':
                    # The rule's own wording: falsified when the (unadjusted) 95% upper bound of the mean
                    # exposure is below the bound of the lower-bound statement.
                    for m in fam['members']:
                        s, t = m['summary'], m['threshold']
                        if s['n'] and t is not None:
                            lo, hi = s[self.o.certify_bound]
                            m['rejected'] = hi < t
                            m['verdict'] = 'excess_detected' if hi < t else ('certified' if lo >= t else 'withheld')
                    fam['rule'] = 'upper_bound'
                fams.append(fam)
        # I6-S1: slope of exposure on the achieved rate per run, descriptive.
        slopes = []
        for p in self.points_of_cells(self.conditions_cfg.get('I6-F6', {}).get('cells', [])):
            for op in self.ops_of(p['index']):
                pts2 = [(r.metrics['achieved_settlement_rate'], r.episode('episode_exposure', 1))
                        for r in self.group_runs(p['index'], op)
                        if _num(r.metrics.get('achieved_settlement_rate')) is not None and _num(r.episode('episode_exposure', 1)) is not None]
                slopes.append(dict(point=p['index'], label=p['label'], op=op,
                                   **slope_summary(pts2, self.o.resamples, self.seed(f'S1:{p["index"]}:{op}'))))
        return dict(families=fams, slopes_I6_S1=slopes)

    def honest_points(self):
        return [p for p in self.points if p['role'] == 'honest']

    def cond_f8_f9(self):
        f8, f9 = [], []
        for op in self.ops_all():
            per_scale, windows_all = [], []
            pvals, rows = {}, {}
            for p in self.honest_points():
                if (p['index'], op) not in self.groups:
                    continue
                base, _ = self.point_values(p['index'], op)
                runs = self.group_runs(p['index'], op)
                d = derived(base) if base else {}
                wins = []
                for r in runs:
                    sales = (r.doc or {}).get('sales') or []
                    for w in r.metrics.get('honest_windows') or []:
                        settled = sum(1 for s in sales if w['start'] <= s.get('settled_block', -1) <= w['end']) if sales else None
                        wins.append(dict(run_id=r.run_id, settlements=settled, **w))
                windows_all.extend(wins)
                w_model = d.get('three_w1_sq') if self.o.honest_w == 'three_w1_sq' else None
                model = [x['settlements'] * base['s'] * w_model for x in wins
                         if x['settlements'] is not None and base and base.get('s') is not None and w_model is not None]
                fails = unserved = cases = 0
                missing = []
                for r in runs:
                    c = r.sampled_honest_counts()
                    if c is None:
                        missing.append(r.run_id)
                        continue
                    fails += c[0]
                    unserved += c[1]
                    cases += c[2]
                t = d.get('three_w1_sq')
                if cases and t is not None:
                    pvals[(p['index'], op)] = binom_sf(fails, cases, t)
                hist = {}
                for x in wins:
                    hist[x['wrongful_confirmed_failures']] = hist.get(x['wrongful_confirmed_failures'], 0) + 1
                row = dict(point=p['index'], label=p['label'], op=op, n=base.get('n') if base else None,
                           k=base.get('k') if base else None,
                           k_n=(base['k'] * base['n']) if base and base.get('k') is not None and base.get('n') is not None else None,
                           runs=len(runs), windows=len(wins),
                           wrongful_per_window_mean=(math.fsum(x['wrongful_confirmed_failures'] for x in wins) / len(wins)) if wins else None,
                           wrongful_per_window_max=max((x['wrongful_confirmed_failures'] for x in wins), default=None),
                           wrongful_per_window_histogram={str(k2): hist[k2] for k2 in sorted(hist)},
                           model_mean=(math.fsum(model) / len(model)) if model else None,
                           sanctioned_windows=sum(1 for x in wins if x['sanctioned']),
                           top_ups=sum(r.metrics['honest_top_up_count'] for r in runs if _num(r.metrics.get('honest_top_up_count')) is not None),
                           top_up_runs_missing=[r.run_id for r in runs if _num(r.metrics.get('honest_top_up_count')) is None],
                           max_window_scale=max((r.metrics['honest_max_window_scale'] for r in runs
                                                 if _num(r.metrics.get('honest_max_window_scale')) is not None), default=None),
                           sampled_cases=cases, wrongful_final_fail=fails, unserved=unserved,
                           rate=(fails / cases) if cases else None,
                           interval_95=clopper_pearson(fails, cases) if cases else None, three_w1_sq=t,
                           runs_without_sales_rows=missing)
                rows[(p['index'], op)] = row
                per_scale.append(row)
            adj = holm(pvals)
            for key, row in rows.items():
                fails, cases = row['wrongful_final_fail'], row['sampled_cases']
                a = adj.get(key)
                row['p'] = pvals.get(key)
                row['p_holm'] = a[0] if a else None
                row['rejected'] = bool(a and a[1])
                if row['rate'] is None:
                    row['verdict'] = 'no_data'
                elif row['rejected']:
                    row['verdict'] = 'excess_detected'
                else:
                    row['verdict'] = 'certified' if self.rate_bound(fails, cases)[1] <= row['three_w1_sq'] else 'withheld'
            if per_scale:
                f9.append(dict(op=op, size=len(pvals), registered_size=3, size_matches=len(pvals) == 3,
                               members=sorted(per_scale, key=lambda r: r['point'])))
                W = len(windows_all)
                Z = sum(x['sanctioned'] for x in windows_all)
                p_bound = min(1.0, W * F8_WINDOW_BOUND) if Z >= 1 else None
                f8.append(dict(op=op, W=W, Z=Z, p_bound=p_bound, reject_at=F8_REJECT_P,
                               rejected=bool(p_bound is not None and p_bound <= F8_REJECT_P),
                               verdict='rejected' if p_bound is not None and p_bound <= F8_REJECT_P else (
                                   'not_rejected' if W else 'no_data'),
                               registered_windows_planned=REGISTERED_F8['windows_planned'],
                               evidence=[dict(run_id=x['run_id'], start=x['start'], end=x['end'], sanctioned=x['sanctioned'])
                                         for x in sorted(windows_all, key=lambda x: (x['run_id'], x['start'])) if x['sanctioned']],
                               per_scale=[dict(point=r['point'], label=r['label'], windows=r['windows'],
                                               sanctioned_windows=r['sanctioned_windows']) for r in per_scale]))
        return dict(families=f8), dict(families=f9)

    def cond_f10(self):
        fams, descriptive = [], []
        cfg = self.conditions_cfg.get('I6-F10', {})
        for name, f in self.yaml_families('I6-F10'):
            pts = self.points_of_cells(f['cells'])
            for op, plist in sorted(self.members_per_op(pts).items()):
                pvals, rows = {}, {}
                for p in plist:
                    base, _ = self.point_values(p['index'], op)
                    if base is None:
                        continue
                    d = derived(base)
                    runs = self.group_runs(p['index'], op)
                    det, elig, missing = self.detection_pool(runs)
                    t = d.get('p_L')
                    if elig and t is not None:
                        pvals[(p['index'], op)] = binom_cdf(det, elig, t)
                    rows[(p['index'], op)] = dict(point=p['index'], label=p['label'], op=op, detections=det, eligible=elig,
                                                  rate=det / elig if elig else None,
                                                  interval_95=clopper_pearson(det, elig) if elig else None,
                                                  p_L=t, p=base.get('p'), p_star=self.o.p_star.get(p['profile']),
                                                  runs_included=len(runs), runs_without_counts=missing)
                adj = holm(pvals)
                for key, row in rows.items():
                    det, elig = row['detections'], row['eligible']
                    a = adj.get(key)
                    row['p_value'] = pvals.get(key)
                    row['p_holm'] = a[0] if a else None
                    row['rejected'] = bool(a and a[1])
                    row['verdict'] = ('no_data' if row['rate'] is None or row['p_L'] is None else 'excess_detected' if row['rejected']
                                      else 'certified' if self.rate_bound(det, elig)[0] >= row['p_L'] else 'withheld')
                reg = REGISTERED_FAMILY_SIZES[('I6-F10', None, None)]
                fams.append(dict(name=f'{name}@{op[:8]}', condition='I6-F10', direction='lower', size=len(pvals),
                                 registered_size=reg, size_matches=len(pvals) == reg,
                                 members=[rows[k] for k in sorted(rows)]))
        for p in self.points_of_cells(cfg.get('descriptive_cells', [])):
            for op in self.ops_of(p['index']):
                base, _ = self.point_values(p['index'], op)
                runs = self.group_runs(p['index'], op)
                det, elig, missing = self.detection_pool(runs)
                descriptive.append(dict(point=p['index'], label=p['label'], op=op, detections=det, eligible=elig,
                                        rate=det / elig if elig else None,
                                        interval_95=clopper_pearson(det, elig) if elig else None,
                                        predicted_s=base.get('s') if base else None, runs_without_counts=missing))
        return dict(families=fams, worst_path_descriptive=descriptive)

    def cond_f11(self):
        cells = self.conditions_cfg.get('I6-F11a', {}).get('cells', [])
        ev_a, ev_b, checked = [], [], 0
        missing = []
        for p in self.points_of_cells(cells):
            for op in self.ops_of(p['index']):
                for r in self.group_runs(p['index'], op, scope='all'):
                    v = r.values()
                    cpm = r.metrics.get('case_path_minus_keeper')
                    if not isinstance(cpm, list) or v['t_case'] is None or v['margin'] is None:
                        missing.append(r.run_id)
                        continue
                    checked += 1
                    cases = (r.doc or {}).get('cases') or [dict(case_path_minus_keeper=x) for x in cpm]
                    for c in cases:
                        x = c.get('case_path_minus_keeper')
                        if x is None:
                            continue
                        if x > v['t_case'] - v['margin']:
                            ev_a.append(dict(run_id=r.run_id, point=p['index'], nonce=c.get('nonce'), case_path_minus_keeper=x,
                                             threshold=v['t_case'] - v['margin'], excluded_from_premise=r.exclusions))
                        if x > v['t_case']:
                            ev_b.append(dict(clause='path_over_T_case', run_id=r.run_id, point=p['index'], nonce=c.get('nonce'),
                                             case_path_minus_keeper=x, threshold=v['t_case'], excluded_from_premise=r.exclusions))
                    kmax = r.kappa_sigma_max()
                    leaks = r.metrics.get('post_detection_leak') or []
                    if kmax is not None and v['keeper_margin'] is not None and kmax <= v['keeper_margin'] \
                            and any((_num(x) or 0) > 0 for x in leaks):
                        path_a = any(e['run_id'] == r.run_id for e in ev_a)
                        ev_b.append(dict(clause='leak_within_margin', run_id=r.run_id, point=p['index'], post_detection_leak=leaks,
                                         kappa_sigma_max=kmax, keeper_margin=v['keeper_margin'],
                                         attributed_to=('case_horizon_lemma' if path_a else 'freeze_at_confirmed_failure'),
                                         excluded_from_premise=r.exclusions))
        key = lambda e: (e['run_id'], str(e.get('nonce')), e.get('clause', ''))  # noqa: E731
        return (dict(runs_checked=checked, runs_missing_fields=sorted(missing), verdict='violated' if ev_a else (
                    'not_violated' if checked else 'no_data'), evidence=sorted(ev_a, key=key)),
                dict(runs_checked=checked, runs_missing_fields=sorted(missing), verdict='violated' if ev_b else (
                    'not_violated' if checked else 'no_data'), evidence=sorted(ev_b, key=key)))

    def finite_points(self):
        return [p for p in self.points if p['role'] == 'finite']

    def cond_f12(self):
        fams = []
        f_rows = []
        for name, f in self.yaml_families('I6-F12a'):
            pts = self.points_of_cells(f['cells'])
            for op, plist in sorted(self.members_per_op(pts).items()):
                members = []
                for p in plist:
                    base, _ = self.point_values(p['index'], op)
                    if base is None:
                        continue
                    d = derived(base)
                    runs = self.group_runs(p['index'], op)
                    all_runs = self.group_runs(p['index'], op, scope='all')
                    vals = [(r.run_id, r.episode('y_f', 1)) for r in runs if _num(r.episode('y_f', 1)) is not None]
                    modes = [r.episode('episode_end_mode', 1) for r in runs]
                    m = base.get('m')
                    ps = self.o.p_star.get(p['profile'])
                    bound = pred = und = None
                    if None not in (m, base.get('p')) and 'g_over_p_minus_B_over_k' in d:
                        bound = (1 - (1 - base['p']) ** m) * d['g_over_p_minus_B_over_k']
                    if None not in (m, ps, base.get('g')) and 'B_over_k' in d:
                        und = (1 - ps) ** m
                        pred = m * base['g'] * und - (1 - und) * d['B_over_k']
                    ex = {}
                    for r in all_runs:
                        for reason in r.exclusions:
                            ex[reason] = ex.get(reason, 0) + 1
                    net = [r.episode('episode_net_gain', 1) for r in runs if _num(r.episode('episode_net_gain', 1)) is not None]
                    undetected_yf = [r.episode('y_f', 1) for r in runs if r.episode('episode_end_mode', 1) == 'without_detection'
                                     and _num(r.episode('y_f', 1)) is not None]
                    exposure = [r.episode('episode_exposure', 1) for r in runs if _num(r.episode('episode_exposure', 1)) is not None]
                    refunds = [r.episode('buyer_refund_paid', 1) for r in runs if _num(r.episode('buyer_refund_paid', 1)) is not None]
                    unrec = [r.episode('buyer_unrecovered_amount', 1) for r in runs if _num(r.episode('buyer_unrecovered_amount', 1)) is not None]
                    ps_counts = dict(FAIL=0, UNSERVED=0)
                    for r in all_runs:
                        for x in r.metrics.get('post_switch_confirmed_failures') or []:
                            ps_counts['FAIL'] += x.get('FAIL', 0)
                            ps_counts['UNSERVED'] += x.get('UNSERVED', 0)
                    se = [x for r in all_runs for x in (r.metrics.get('seller_exit_deferred_entries') or [])]
                    be = [x for r in all_runs for x in (r.metrics.get('bond_exit_deferred_balance') or [])]
                    extra = dict(
                        m=m, strategy=p['cell'], runs_included=len(runs), excluded_reasons=dict(sorted(ex.items())),
                        with_detection=modes.count('with_detection'), without_detection=modes.count('without_detection'),
                        open=modes.count('open'), predicted_undetected=und, predicted_mean=pred, upper_bound=bound,
                        net_gain=mean_summary(net, self.o.resamples, self.seed(f'F12-net:{p["index"]}:{op}')),
                        undetected_y_f_mean=(math.fsum(undetected_yf) / len(undetected_yf)) if undetected_yf else None,
                        exposure_mean=(math.fsum(exposure) / len(exposure)) if exposure else None,
                        buyer_refund_paid_sum=sum(refunds), buyer_unrecovered_sum=sum(unrec),
                        post_switch_confirmed_failures=ps_counts if p['cell'] == 'F-switch' else None,
                        seller_exit_deferred_entries_max=max(se) if se else None,
                        bond_exit_deferred_balance_max=max(be) if be else None, g=base.get('g'), k=base.get('k'))
                    members.append((p, op, [x for _, x in vals], 0, extra))
                fam = self.run_family(f'{name}@{op[:8]}', 'I6-F12a', members, 'upper', 1)
                fams.append(fam)
                f_rows.extend(fam['members'])
        # (b): bond exit while a deferred balance or an open sampled case remains.
        ev, checked, missing = [], 0, []
        for p in self.points_of_cells(self.conditions_cfg.get('I6-F12b', {}).get('cells', [])):
            for op in self.ops_of(p['index']):
                scope = 'premise' if self.o.f12b_scope == 'premise' else 'all'
                for r in self.group_runs(p['index'], op, scope=scope):
                    blocks = r.metrics.get('bond_exit_finalized_block')
                    bal = r.metrics.get('bond_exit_deferred_balance')
                    opn = r.metrics.get('bond_exit_open_sampled_cases')
                    if not all(isinstance(x, list) for x in (blocks, bal, opn)):
                        missing.append(r.run_id)
                        continue
                    checked += 1
                    for b, x, o in zip(blocks, bal, opn):
                        if (x or 0) > 0 or (o or 0) > 0:
                            ev.append(dict(run_id=r.run_id, point=p['index'], block=b, deferred_balance=x, open_sampled_cases=o,
                                           excluded_from_premise=r.exclusions))
        f12b = dict(runs_checked=checked, runs_missing_fields=sorted(missing), scope=self.o.f12b_scope,
                    verdict='violated' if ev else ('not_violated' if checked else 'no_data'),
                    evidence=sorted(ev, key=lambda e: (e['run_id'], e['block'])),
                    note='bond funds leave the account only through finalizeBondExit (BondExited); no other withdrawal exists')
        return dict(families=fams), f12b

    def cond_pc(self):
        out = []
        for p in self.points_of_cells(self.conditions_cfg.get('I6-PC', {}).get('cells', [])):
            for op in self.ops_of(p['index']):
                runs = self.group_runs(p['index'], op, scope='integrity')
                leaks = []
                for r in runs:
                    lst = r.metrics.get('post_detection_leak')
                    if not isinstance(lst, list):
                        continue
                    L = (lst[0] if lst else 0) if self.o.pc_episode == 'first' else max(lst or [0])
                    leaks.append((r, L or 0))
                positive = sum(1 for _, L in leaks if L > 0)
                if not leaks:
                    verdict = 'no_data'
                elif positive == 0:
                    verdict = 'failed'
                elif positive < POSITIVE_CONTROL_THRESHOLD:
                    verdict = 'passed_cause_under_investigation'
                else:
                    verdict = 'passed'
                zero = [dict(run_id=r.run_id, case_path_blocks=r.metrics.get('case_path_blocks'),
                             kappa_sigma=r.metrics.get('keeper_delay_sum_blocks')) for r, L in leaks if L == 0]
                out.append(dict(point=p['index'], label=p['label'], op=op, runs=len(leaks), runs_with_leak=positive,
                                leak_max=max((L for _, L in leaks), default=None), verdict=verdict,
                                runs_with_zero_leak=zero if positive < POSITIVE_CONTROL_THRESHOLD else [],
                                runs_excluded=[dict(run_id=r.run_id, reasons=r.integrity)
                                               for r in self.group_runs(p['index'], op, scope='all') if r.integrity]))
        return out

    def cond_v(self):
        out = []
        for p in self.points_of_cells(self.conditions_cfg.get('I6-V', {}).get('descriptive_cells', [])):
            for op in self.ops_of(p['index']):
                for r in self.group_runs(p['index'], op, scope='all'):
                    sales = (r.doc or {}).get('sales')
                    fails = {f['nonce']: f for f in r.metrics.get('assignment_failure') or [] if isinstance(f, dict)}
                    N = r.params.get('assignable_verifiers')
                    if sales is None:
                        out.append(dict(point=p['index'], label=p['label'], op=op, run_id=r.run_id, N=N, cases=None,
                                        note='no per-sale rows'))
                        continue
                    sampled = sorted((s for s in sales if s.get('bad') and s.get('case_trigger') == TRIGGER_SAMPLE),
                                     key=lambda s: (s.get('settled_block'), s.get('index', 0)))[:30]
                    failed = [fails[s['nonce']] for s in sampled if s['nonce'] in fails]
                    stages, causes = {}, {}
                    for f in failed:
                        stages[str(f.get('stage'))] = stages.get(str(f.get('stage')), 0) + 1
                        causes[str(f.get('cause'))] = causes.get(str(f.get('cause')), 0) + 1
                    # Failures inside a replacement gap: fewer assignable verifiers than N at the failure
                    # block when the collector records the count, else the strike_removal cause.
                    gap = sum(1 for f in failed if (f['assignable_count'] < N if isinstance(f.get('assignable_count'), int)
                                                    and N else f.get('cause') == 'strike_removal'))
                    R = self.o.v_rounds.get(N)
                    reg = REGISTERED_V_PREDICTIONS.get(N, {})
                    n_cases = len(sampled)
                    out.append(dict(
                        point=p['index'], label=p['label'], op=op, run_id=r.run_id, N=N, cases=n_cases,
                        terminal_cases=sum(1 for s in sampled if s.get('case_state') in TERMINAL_CASE_STATES),
                        assignment_failures=len(failed), fraction=(len(failed) / n_cases) if n_cases else None,
                        interval_95=clopper_pearson(len(failed), n_cases) if n_cases else None,
                        stages=dict(sorted(stages.items())), causes=dict(sorted(causes.items())),
                        prediction=(8 / N) ** R if N and R else None, prediction_R=R,
                        registered_prediction=reg.get('value'),
                        removed=r.metrics.get('verifier_removed_count'), replacements=r.metrics.get('verifier_replacement_count'),
                        strike_removal_cases=gap,
                        fraction_without_strike_removal=((len(failed) - gap) / (n_cases - gap)) if n_cases - gap > 0 else None,
                        premise_reasons=r.exclusions))
        return out

    # Checks, completeness ------------------------------------------------------------------------
    def threshold_checks(self):
        out = []
        seen = set()
        for (pi, op) in sorted(self.groups):
            p = self.points[pi]
            base, _ = self.point_values(pi, op)
            if base is None:
                continue
            reg = REGISTERED.get(p['profile'])
            if not reg:
                continue
            d = derived(base)
            computed = dict(T_case=base.get('t_case'), marginBlocks=base.get('margin'),
                            T_case_minus_margin=d.get('T_case_minus_margin'), L_actual=base.get('l_actual'),
                            p_L=d.get('p_L'), three_w1_sq=d.get('three_w1_sq') if p['cell'] != 'F-switch' else None,
                            k_default=base.get('k'))
            if p['cell'] in ('M1-high-admissible', 'M1-low-admissible') or p['role'] == 'finite':
                # B = k * g * ceil(1/p) with the recorded k, beside the stated bond at the default k.
                computed['bond_k_g_ceil_inv_p'] = d.get('bond_k_g_ceil_inv_p')
                computed['g_over_p'] = d.get('g_over_p')
            if p['judgment_path'] == 'normal' and p['cell'] not in ('M1-low-comparison', 'M1-high-comparison', 'M3-low',
                                                                   'M3-high', 'P5-short-hold'):
                computed['T_hold'] = base.get('t_hold')
                computed['keeper_margin'] = base.get('keeper_margin')
            for name, value in computed.items():
                if value is None or name not in reg:
                    continue
                key = (p['profile'], op, name, value)
                if key in seen:
                    continue
                seen.add(key)
                r = reg[name]
                out.append(dict(profile=p['profile'], op=op, name=name, registered=r['value'], computed=value,
                                match=abs(value - r['value']) <= r['tol'], first_point=p['label']))
            if p['role'] == 'honest' and base.get('k') is not None and base.get('n') is not None:
                reg_kn = reg['k_default']['value'] * base['n']
                key = (p['profile'], op, 'k_n', base['n'])
                if key not in seen:
                    seen.add(key)
                    out.append(dict(profile=p['profile'], op=op, name=f'k(n) n={base["n"]}', registered=reg_kn,
                                    computed=base['k'] * base['n'], match=reg_kn == base['k'] * base['n'],
                                    first_point=p['label']))
        return sorted(out, key=lambda x: (x['profile'], x['op'], x['name'], str(x['computed'])))

    def value_consistency(self):
        out = []
        for (pi, op) in sorted(self.groups):
            _, differ = self.point_values(pi, op)
            if differ:
                out.append(dict(point=pi, label=self.points[pi]['label'], op=op, differing_values=differ))
            for r in self.group_runs(pi, op, scope='all'):
                v = r.values()
                if v['op_k'] is not None and v['k'] is not None and v['op_k'] != v['k']:
                    out.append(dict(point=pi, label=self.points[pi]['label'], op=op, run_id=r.run_id,
                                    note=f'operating point failureLimit {v["op_k"]} differs from the deployed {v["k"]}'))
        return out

    def completeness(self):
        pts = []
        for p in self.points:
            ops = self.ops_of(p['index'])
            if not ops:
                pts.append(dict(point=p['index'], label=p['label'], profile=p['profile'], op=None, planned=p['repetitions'],
                                min_repetitions=p['min_repetitions'], found=0, completed_with_observations=0, failed=0,
                                no_observations=0, missing_repetitions=list(range(p['repetitions']))))
                continue
            for op in ops:
                grp = self.groups[(p['index'], op)]
                reps = sorted(r.repetition for r in grp['runs'])
                failed_reps = sorted(int(RUN_ID.match(x).group(2)) for x in grp['failed'])
                noobs_reps = sorted(int(RUN_ID.match(x).group(2)) for x in grp['no_obs'])
                have = set(reps) | set(failed_reps) | set(noobs_reps)
                pts.append(dict(point=p['index'], label=p['label'], profile=p['profile'], op=op, planned=p['repetitions'],
                                min_repetitions=p['min_repetitions'], found=len(have),
                                completed_with_observations=len(reps), failed=len(failed_reps),
                                no_observations=len(noobs_reps),
                                below_min_repetitions=bool(p['min_repetitions'] and len(reps) < p['min_repetitions']),
                                missing_repetitions=[i for i in range(p['repetitions']) if i not in have]))
        fields = {}
        for rule, specs in sorted(REQUIRED.items()):
            runs = self.rule_runs(rule)
            per = {}
            for spec in specs:
                absent = sorted(r.run_id for r in runs if r.value(spec) is None)
                if absent:
                    per[spec] = absent
            fields[rule] = dict(runs=len(runs), absent=per)
        second = []
        for p in self.points:
            if p['role'] not in ('cheater',):
                continue
            for op in self.ops_of(p['index']):
                runs = self.group_runs(p['index'], op)
                finished = sum(1 for r in runs if r.episode('episode_end_mode', 2) not in (None, 'open'))
                if runs and finished < self.o.second_episode_min_runs:
                    second.append(dict(point=p['index'], label=p['label'], op=op, finished_second_episodes=finished))
        return dict(points=pts, required_fields=fields, second_episode_not_judged=second,
                    points_without_runs=[x['label'] for x in pts if x['op'] is None])

    def rule_runs(self, rule):
        cfg = self.conditions_cfg.get(rule, {})
        cells = list(cfg.get('cells', [])) + list(cfg.get('descriptive_cells', []))
        if rule == 'cap_off_check':
            cells = [c['name'] for c in scn.cells(self.sc) if (c.get('set') or {}).get('cap_enabled') is False]
        scope = 'all' if rule in ('I6-F11a', 'I6-F11b', 'I6-V') else 'premise'
        out = []
        for p in self.points_of_cells(cells):
            for op in self.ops_of(p['index']):
                out.extend(self.group_runs(p['index'], op, scope=scope))
        return out

    def cap_off_check(self):
        out = []
        for r in sorted(self.rule_runs('cap_off_check'), key=lambda r: r.run_id):
            x = r.metrics.get('rejected_settlement_count')
            out.append(dict(run_id=r.run_id, point=r.point['index'], rejected_settlement_count=x,
                            ok=None if x is None else x == 0))
        return dict(runs=len(out), missing=sum(1 for x in out if x['ok'] is None),
                    violations=[x for x in out if x['ok'] is False])

    # Cell summaries ------------------------------------------------------------------------------
    def cell_rows(self):
        rows = []
        for (pi, op) in sorted(self.groups):
            p = self.points[pi]
            grp = self.groups[(pi, op)]
            base, _ = self.point_values(pi, op)
            all_runs = self.group_runs(pi, op, scope='all')
            runs = self.group_runs(pi, op)
            ex = {r.run_id: r.exclusions for r in all_runs if r.exclusions}
            d = derived(base, self.o.p_star.get(p['profile'])) if base else {}
            row = dict(point=pi, label=p['label'], cell=p['cell'], role=p['role'], rate_class=p['rate_class'], op=op,
                       profile=p['profile'], parameters=p['parameters'],
                       runs=dict(planned=p['repetitions'], min_repetitions=p['min_repetitions'],
                                 completed_with_observations=len(all_runs), failed=len(grp['failed']),
                                 no_observations=len(grp['no_obs']), excluded=dict(sorted(ex.items())), included=len(runs)),
                       values=base, derived=d, premise_by_design=self.cell_outside(p, base or {}))
            if base:
                row['freeze_on_initial_fail'] = sorted({r.metrics.get('freeze_on_initial_fail') for r in all_runs}, key=str)
                row['override_used'] = sorted({bool(r.env.get('override_used')) for r in all_runs})
                rates = [r.metrics.get('achieved_settlement_rate') for r in runs if _num(r.metrics.get('achieved_settlement_rate')) is not None]
                conf = [r.metrics.get('configured_settlement_rate') for r in runs if _num(r.metrics.get('configured_settlement_rate')) is not None]
                row['configured_rate'] = conf[0] if conf else None
                row['achieved_rate_mean'] = math.fsum(rates) / len(rates) if rates else None
                ks = [r.kappa_sigma_max() for r in runs if r.kappa_sigma_max() is not None]
                row['kappa_sigma_max'] = max(ks) if ks else None
                row['runs_kappa_sigma_over_margin'] = sum(1 for r in all_runs if (r.kappa_sigma_max() or 0) > (base.get('keeper_margin') or 0))
                row['cases_kappa_sigma_not_budget'] = sum(1 for r in runs for x in (r.metrics.get('keeper_delay_sum_blocks') or [])
                                                          if (base.get('kappa') or 0) > 0 and x != base.get('kappa'))
                cp = [x for r in runs for x in (r.metrics.get('case_path_blocks') or [])]
                cpm = [x for r in runs for x in (r.metrics.get('case_path_minus_keeper') or [])]
                row['case_path_max'] = max(cp) if cp else None
                row['case_path_minus_keeper_max'] = max(cpm) if cpm else None
                tcm = d.get('T_case_minus_margin')
                row['cases_over_T_case_minus_margin'] = sum(1 for x in cpm if tcm is not None and x > tcm)
                row['cases_over_T_case'] = sum(1 for x in cpm if base.get('t_case') is not None and x > base['t_case'])
                row['cases_over_L_actual'] = (sum(1 for x in cpm if base.get('l_actual') is not None and x > base['l_actual'])
                                              if p['judgment_path'] == 'worst' else None)
                row['cases_over_T_hold'] = sum(1 for x in cp if base.get('t_hold') is not None and x > base['t_hold'])
                eps = {}
                for e in (1, 2):
                    ex_vals = self.episode_values(runs, 'episode_exposure', e)
                    net = self.episode_values(runs, 'episode_net_gain', e)
                    leak = [x for _, x in self.episode_values(runs, 'post_detection_leak', e)]
                    modes = [r.episode('episode_end_mode', e) for r in runs if r.episode('episode_end_mode', e) is not None]
                    refunds = [x for _, x in self.episode_values(runs, 'buyer_refund_paid', e)]
                    unrec = [x for _, x in self.episode_values(runs, 'buyer_unrecovered_amount', e)]
                    eps[str(e)] = dict(
                        exposure=mean_summary([x for _, x in ex_vals], self.o.resamples, self.seed(f'X:{pi}:{op}:{e}')),
                        net_gain=mean_summary([x for _, x in net], self.o.resamples, self.seed(f'N:{pi}:{op}:{e}')),
                        leak_mean=math.fsum(leak) / len(leak) if leak else None, leak_max=max(leak) if leak else None,
                        runs_with_leak=sum(1 for x in leak if x > 0),
                        with_detection=modes.count('with_detection'), without_detection=modes.count('without_detection'),
                        open=modes.count('open'), buyer_refund_paid_sum=sum(refunds) if refunds else None,
                        buyer_unrecovered_sum=sum(unrec) if unrec else None)
                row['episodes'] = eps
                refund_blocks = sorted(x for r in runs for x in (r.metrics.get('buyer_refund_paid_blocks') or []))
                row['buyer_refund_blocks_median'] = quantile(refund_blocks, 0.5) if refund_blocks else None
                row['buyer_refund_blocks_max'] = refund_blocks[-1] if refund_blocks else None
                fd = sorted(x for r in runs for x in (r.metrics.get('freeze_delay_blocks') or []))
                row['freeze_delay_median'] = quantile(fd, 0.5) if fd else None
                row['freeze_delay_max'] = fd[-1] if fd else None
                row['releases_after_reentry'] = sum(r.metrics['releases_after_reentry'] for r in runs
                                                    if _num(r.metrics.get('releases_after_reentry')) is not None)
                det, elig, missing = self.detection_pool(runs)
                row['detection'] = dict(detections=det, eligible=elig, rate=det / elig if elig else None,
                                        interval_95=clopper_pearson(det, elig) if elig else None,
                                        runs_without_counts=missing)
                fdi = [x for r in runs for x in (r.metrics.get('first_detection_index') or []) if isinstance(x, dict)]
                sk = sum(x.get('K', 0) for x in fdi)
                row['auxiliary_detection_estimator'] = (sum(1 for x in fdi if not x.get('censored')) / sk) if sk else None
                row['verifiers'] = dict(
                    registered=sorted({r.metrics.get('verifier_registered_count') for r in all_runs}, key=str),
                    removed=sum(r.metrics.get('verifier_removed_count') or 0 for r in all_runs),
                    replacements=sum(r.metrics.get('verifier_replacement_count') or 0 for r in all_runs),
                    removal_rate_mean=(lambda xs: math.fsum(xs) / len(xs) if xs else None)(
                        [r.metrics['verifier_removal_rate_per_case'] for r in all_runs
                         if _num(r.metrics.get('verifier_removal_rate_per_case')) is not None]),
                    assignable_min=min((x for r in all_runs for x in (r.metrics.get('assignable_min_between_removal_and_replacement') or [])),
                                       default=None),
                    assignment_failures=sum(len(r.metrics.get('assignment_failure') or []) for r in all_runs))
                t = {}
                if 'g_over_p' in d:
                    t['g_over_p'] = d['g_over_p']
                if 'g_over_p_minus_B_over_k' in d:
                    t['g_over_p_minus_B_over_k'] = d['g_over_p_minus_B_over_k']
                row['reference_values'] = t
            rows.append(row)
        return rows

    # Everything ----------------------------------------------------------------------------------
    def result(self):
        conds = {}
        conds['I6-F1'] = self.cond_f1()
        conds['I6-F2'] = self.cond_f2()
        conds['I6-F3'] = self.cond_f3()
        conds['I6-F4'] = self.cond_f4()
        conds['I6-F5'] = self.cond_f5()
        conds['I6-F6'] = self.cond_f6()
        conds['I6-F8'], conds['I6-F9'] = self.cond_f8_f9()
        conds['I6-F10'] = self.cond_f10()
        conds['I6-F11a'], conds['I6-F11b'] = self.cond_f11()
        conds['I6-F12a'], conds['I6-F12b'] = self.cond_f12()
        conds['I6-PC'] = dict(cells=self.cond_pc())
        conds['I6-V'] = dict(cells=self.cond_v())
        for name, c in conds.items():
            c['kind'] = KINDS[name]
            c['verdict'] = c.get('verdict') or overall_verdict(name, c)
        ops = {}
        for r in self.runs:
            o = ops.setdefault(r.op_key, dict(sha256=r.op_key, path=(r.env.get('operating_point') or {}).get('path'),
                                              k_by_profile={}, values_by_profile={}))
            o['k_by_profile'][r.profile] = (r.env.get('operating_point_k') or {}).get('value', r.op_values.get('failureLimit'))
            o['values_by_profile'][r.profile] = r.op_values
        return dict(
            format=FORMAT, options=self.o.as_dict(),
            scenario=dict(sha256=self.sc.get('_sha256'), points=len(self.points)),
            runs=dict(reportable_with_observations=len(self.runs), dropped={k: sorted(v) for k, v in sorted(self.dropped.items())},
                      failed=sorted(self.failed, key=lambda x: x['run_id']), no_observations=sorted(self.no_observations),
                      premise_outside={r.run_id: r.exclusions for r in sorted(self.runs, key=lambda r: r.run_id) if r.exclusions},
                      without_full_document=sorted(r.run_id for r in self.runs if r.source != 'document')),
            operating_points=ops, cells=self.cell_rows(), conditions=conds, threshold_checks=self.threshold_checks(),
            value_consistency=self.value_consistency(), cap_off_check=self.cap_off_check(), completeness=self.completeness(),
            registered_constants=dict(per_profile=REGISTERED, family_sizes={f'{k[0]}|{k[1]}|{k[2]}': v for k, v in REGISTERED_FAMILY_SIZES.items()},
                                      f_grid_predictions={str(k): v for k, v in REGISTERED_F_PREDICTIONS.items()},
                                      v_predictions={str(k): v for k, v in REGISTERED_V_PREDICTIONS.items()}, f8=REGISTERED_F8))


def overall_verdict(name, c):
    """Condition-level verdict: triggered when any member of any family detects an excess."""
    fams = c.get('families')
    if name == 'I6-F8':
        if not fams:
            return 'no_data'
        return 'rejected' if any(f['rejected'] for f in fams) else 'not_rejected'
    if name == 'I6-PC':
        vs = [x['verdict'] for x in c['cells']]
        if not vs:
            return 'no_data'
        return 'failed' if 'failed' in vs else ('passed_cause_under_investigation' if 'passed_cause_under_investigation' in vs
                                                else ('passed' if all(v == 'passed' for v in vs) else 'no_data'))
    if name == 'I6-V':
        return 'descriptive'
    members = [m for f in fams or [] for m in f['members']]
    if not any(m['verdict'] != 'no_data' for m in members):
        return 'no_data'
    if any(m['verdict'] == 'excess_detected' for m in members):
        return 'triggered'
    if all(m['verdict'] in ('certified', 'no_data') for m in members):
        return 'not_triggered (all certified)'
    return 'not_triggered (some withheld)'


# ---------------------------------------------------------------------------------------------
# Tables


def _f(x, g=None):
    if x is None:
        return 'NA'
    if isinstance(x, bool):
        return '1' if x else '0'
    if g:
        x = x / g
    if isinstance(x, int):
        return str(x)
    if isinstance(x, float):
        if x == int(x) and abs(x) < 1e15:
            return str(int(x))
        return f'{x:.6g}'
    return str(x)


def _iv(iv, g=None):
    return 'NA' if not iv else f'[{_f(iv[0], g)}, {_f(iv[1], g)}]'


def build_tables(res):
    """{name: (columns, rows)} of the tables; exposure and gain columns are in units of g."""
    T = {}
    cells = res['cells']
    cols = ['point', 'cell', 'op', 'episode', 'T_hold', 'freeze_on_initial_fail', 'path', 'B', 'n', 'g', 'cap',
            'kappa_target', 'kappa_sigma_max', 'rate_configured', 'rate_achieved', 'runs_planned', 'runs_included',
            'runs_excluded', 'runs_failed', 'X_mean_g', 'X_ci95_g', 'X_max_g', 'L_mean_g', 'L_max_g', 'runs_L_pos',
            'case_path_max', 'case_path_minus_kappa_max', 'cases_over_Tcase_minus_margin', 'cases_over_Tcase',
            'g_over_p_g', 'net_mean_g', 'net_ci95_g', 'g_over_p_minus_B_over_k_g', 'detect_rate', 'detect_ci95', 'p_L',
            'p', 'p_star', 'releases_after_reentry', 'freeze_delay_median', 'freeze_delay_max', 'refund_sum',
            'refund_blocks_median', 'refund_blocks_max', 'unrecovered_v', 'episodes_detected', 'episodes_undetected',
            'episodes_open', 'premise']
    rows = []
    for c in cells:
        if c['role'] not in ('cheater', 'positive_control') or not c['values']:
            continue
        v, d, g = c['values'], c['derived'], c['values'].get('g')
        par = c['parameters']
        for e in ('1', '2'):
            ep = c['episodes'][e]
            rows.append([c['point'], c['label'], c['op'][:8], e, v.get('t_hold'), _f(c['freeze_on_initial_fail'][0] if c['freeze_on_initial_fail'] else None),
                         par.get('judgment_path'), v.get('B'), v.get('n'), g, par.get('cap_enabled'), v.get('kappa'),
                         c['kappa_sigma_max'], c['configured_rate'], c['achieved_rate_mean'], c['runs']['planned'],
                         c['runs']['included'], len(c['runs']['excluded']), c['runs']['failed'],
                         _f(ep['exposure']['mean'], g), _iv(ep['exposure']['interval_95'], g), _f(ep['exposure']['max'], g),
                         _f(ep['leak_mean'], g), _f(ep['leak_max'], g), ep['runs_with_leak'], c['case_path_max'],
                         c['case_path_minus_keeper_max'], c['cases_over_T_case_minus_margin'], c['cases_over_T_case'],
                         _f(d.get('g_over_p'), g), _f(ep['net_gain']['mean'], g), _iv(ep['net_gain']['interval_95'], g),
                         _f(d.get('g_over_p_minus_B_over_k'), g), c['detection']['rate'], _iv(c['detection']['interval_95']),
                         d.get('p_L'), v.get('p'), d.get('p_star'), c['releases_after_reentry'], c['freeze_delay_median'],
                         c['freeze_delay_max'], ep['buyer_refund_paid_sum'], c['buyer_refund_blocks_median'],
                         c['buyer_refund_blocks_max'], _f(ep['buyer_unrecovered_sum'], v.get('v')), ep['with_detection'],
                         ep['without_detection'], ep['open'], ';'.join(c['premise_by_design'] or []) or 'within'])
    T['I6-1_cheater_cells'] = (cols, rows)

    f9 = res['conditions']['I6-F9']['families']
    cols = ['op', 'n', 'k_n', 'runs', 'windows', 'wrongful_per_window_mean', 'wrongful_per_window_max', 'model_mean',
            'sanctioned_windows', 'top_ups', 'max_window_scale', 'sampled_cases', 'wrongful_final_fail', 'rate',
            'rate_ci95', 'three_w1_sq', 'p_holm_F9']
    rows = [[f['op'][:8], m['n'], m['k_n'], m['runs'], m['windows'], m['wrongful_per_window_mean'], m['wrongful_per_window_max'],
             m['model_mean'], m['sanctioned_windows'], m['top_ups'], m['max_window_scale'], m['sampled_cases'],
             m['wrongful_final_fail'], m['rate'], _iv(m['interval_95']), m['three_w1_sq'], m['p_holm']]
            for f in f9 for m in f['members']]
    for f in res['conditions']['I6-F8']['families']:
        rows.append([f['op'][:8], 'all', None, None, f['W'], None, None, None, f['Z'], None, None, None, None, None, None,
                     None, f['p_bound']])
    T['I6-2_honest_arm'] = (cols, rows)

    cols = ['condition', 'kind', 'family', 'episode', 'rate_class', 'family_size', 'registered_size', 'rejected_cells',
            'certified', 'withheld', 'no_data', 'excluded_runs', 'verdict']
    rows = []
    excluded = len(res['runs']['premise_outside'])
    for name, c in sorted(res['conditions'].items()):
        fams = c.get('families')
        if fams and name not in ('I6-F8',):
            for f in fams:
                vs = [m['verdict'] for m in f['members']]
                rows.append([name, c['kind'], f.get('name', f.get('op', '')[:8]), f.get('episode'), f.get('rate_class'),
                             f['size'], f.get('registered_size'), vs.count('excess_detected'), vs.count('certified'),
                             vs.count('withheld'), vs.count('no_data'), excluded, c['verdict']])
        elif name == 'I6-F8':
            for f in fams or []:
                rows.append([name, c['kind'], f['op'][:8], None, None, f['W'], REGISTERED_F8['windows_planned'], f['Z'],
                             None, None, None, excluded, f['verdict']])
        else:
            n_ev = len(c.get('evidence') or [])
            rows.append([name, c['kind'], None, None, None, c.get('runs_checked'), None, n_ev, None, None, None,
                         excluded, c['verdict']])
    T['I6-3_conditions'] = (cols, rows)

    cols = ['item', 'point', 'op', 'value_1', 'value_2', 'value_3', 'verdict']
    rows = []
    for x in res['conditions']['I6-PC']['cells']:
        rows.append(['positive_control', x['label'], x['op'][:8], x['runs'], x['runs_with_leak'], x['leak_max'], x['verdict']])
    for x in res['conditions']['I6-F10']['worst_path_descriptive']:
        rows.append(['worst_path_detection_rate', x['label'], x['op'][:8], x['rate'], _iv(x['interval_95']), x['predicted_s'], None])
    for x in res['conditions']['I6-F6']['slopes_I6_S1']:
        rows.append(['I6-S1_slope', x['label'], x['op'][:8], x['slope'], _iv(x['interval_95']), x['n'], None])
    for c in cells:
        if not c['values']:
            continue
        rows.append(['auxiliary_detection_estimator', c['label'], c['op'][:8], c.get('auxiliary_detection_estimator'),
                     c['detection']['rate'], None, None])
        vv = c['verifiers']
        rows.append(['verifiers_registered/removed/replacements', c['label'], c['op'][:8], ';'.join(map(str, vv['registered'])),
                     vv['removed'], vv['replacements'], None])
        rows.append(['removal_rate_mean/assignable_min/assignment_failures', c['label'], c['op'][:8], vv['removal_rate_mean'],
                     vv['assignable_min'], vv['assignment_failures'], None])
        rows.append(['case_path_max/cases_over_L_actual/cases_over_T_hold', c['label'], c['op'][:8], c['case_path_minus_keeper_max'],
                     c['cases_over_L_actual'], c['cases_over_T_hold'], None])
        rows.append(['kappa_cases_not_budget/runs_over_margin', c['label'], c['op'][:8], c['cases_kappa_sigma_not_budget'],
                     c['runs_kappa_sigma_over_margin'], None, None])
    for x in res['threshold_checks']:
        rows.append(['threshold_check:' + x['name'], x['first_point'], x['op'][:8], x['registered'], x['computed'], None,
                     'match' if x['match'] else 'MISMATCH'])
    T['I6-4_harness_checks'] = (cols, rows)

    cols = ['point', 'strategy', 'm', 'op', 'k', 'runs_planned', 'runs_included', 'excluded', 'detected', 'undetected',
            'open', 'undetected_predicted', 'y_f_mean_g', 'y_f_ci95_g', 'net_mean_g', 'net_ci95_g', 'undetected_y_f_mean_g',
            'predicted_mean_g', 'upper_bound_g', 'exposure_mean_g', 'refund_sum', 'unrecovered', 'post_switch_FAIL',
            'post_switch_UNSERVED', 'seller_exit_deferred_entries_max', 'bond_exit_deferred_balance_max', 'p_holm', 'verdict']
    rows = []
    planned = {c['point']: c['runs']['planned'] for c in cells}
    for f in res['conditions']['I6-F12a']['families']:
        for m in f['members']:
            g = m.get('g')
            ps = m.get('post_switch_confirmed_failures') or {}
            ex = ';'.join(f'{k}={v}' for k, v in m['excluded_reasons'].items())
            rows.append([m['point'], m['strategy'], m['m'], m['op'][:8], m['k'], planned.get(m['point']), m['runs_included'], ex,
                         m['with_detection'], m['without_detection'], m['open'], m['predicted_undetected'],
                         _f(m['summary']['mean'], g), _iv(m['summary']['interval_95'], g), _f(m['net_gain']['mean'], g),
                         _iv(m['net_gain']['interval_95'], g), _f(m['undetected_y_f_mean'], g), _f(m['predicted_mean'], g),
                         _f(m['upper_bound'], g), _f(m['exposure_mean'], g), m['buyer_refund_paid_sum'], m['buyer_unrecovered_sum'],
                         ps.get('FAIL'), ps.get('UNSERVED'), m['seller_exit_deferred_entries_max'],
                         m['bond_exit_deferred_balance_max'], m['p_holm'], m['verdict']])
    T['I6-5_finite_attack'] = (cols, rows)

    cols = ['N', 'point', 'op', 'run', 'cases', 'assignment_failures', 'fraction', 'ci95', 'prediction', 'R',
            'registered_prediction', 'stage_initial', 'stage_party', 'stage_auto', 'stage_tiebreak', 'removed', 'replacements',
            'strike_removal_cases', 'fraction_without_strike_removal']
    rows = []
    for x in res['conditions']['I6-V']['cells']:
        st = x.get('stages') or {}
        rows.append([x['N'], x['label'], x['op'][:8], x['run_id'], x['cases'], x.get('assignment_failures'), x.get('fraction'),
                     _iv(x.get('interval_95')), x.get('prediction'), x.get('prediction_R'), x.get('registered_prediction'),
                     st.get('initial'), st.get('party'), st.get('auto'), st.get('tiebreak'), x.get('removed'), x.get('replacements'),
                     x.get('strike_removal_cases'), x.get('fraction_without_strike_removal')])
    T['I6-6_availability'] = (cols, rows)

    cols = ['condition', 'family', 'point', 'op', 'n', 'mean', 'ci95', 'threshold', 'p', 'p_holm', 'verdict']
    rows = []
    for name in ('I6-F1', 'I6-F2', 'I6-F3', 'I6-F4', 'I6-F5', 'I6-F6', 'I6-F12a'):
        for f in res['conditions'][name]['families']:
            for m in f['members']:
                s = m['summary']
                rows.append([name, f['name'], m['label'], m['op'][:8], s['n'], s['mean'], _iv(s['interval_95']), m['threshold'],
                             s['p'], m['p_holm'], m['verdict']])
    for f in res['conditions']['I6-F10']['families']:
        for m in f['members']:
            rows.append(['I6-F10', f['name'], m['label'], m['op'][:8], m['eligible'], m['rate'], _iv(m['interval_95']), m['p_L'],
                         m['p_value'], m['p_holm'], m['verdict']])
    T['I6-3b_members'] = (cols, rows)
    return T


def _cell(x):
    return _f(x) if not isinstance(x, str) else x


def tables_markdown(tables):
    out = ['# I6 tables', '']
    for name in sorted(tables):
        cols, rows = tables[name]
        out += [f'## {name}', '', '| ' + ' | '.join(cols) + ' |', '|' + '---|' * len(cols)]
        for r in rows:
            out.append('| ' + ' | '.join(_cell(x) for x in r) + ' |')
        out.append('')
    return '\n'.join(out)


def tables_csv(cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(cols)
    for r in rows:
        w.writerow([_cell(x) for x in r])
    return buf.getvalue()


# ---------------------------------------------------------------------------------------------
# CLI


def _dumps(value):
    return json.dumps(value, sort_keys=True, indent=1, ensure_ascii=True, allow_nan=False, default=str) + '\n'


def analyze(runs_dir, scenario_path, options):
    sc = scn.load_scenario(scenario_path)
    a = Analysis(sc, options)
    for path, env in find_envelopes(runs_dir):
        a.add(path, env)
    return a.result()


def write_outputs(res, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'i6_results.json').write_text(_dumps(res))
    tables = build_tables(res)
    (out / 'i6_tables.md').write_text(tables_markdown(tables))
    for name, (cols, rows) in tables.items():
        (out / f'table_{name}.csv').write_text(tables_csv(cols, rows))


def _source_state():
    try:
        rev = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
    except (OSError, subprocess.CalledProcessError):
        rev, dirty = None, None
    return dict(revision=rev, dirty=dirty)


def _p_star(items):
    out = {}
    for item in items:
        prof_name, sep, val = item.partition('=')
        if not sep:
            raise argparse.ArgumentTypeError(f'--p-star expects PROFILE=VALUE, got {item!r}')
        out[prof_name] = float(val)
    return out


def _v_rounds(text):
    out = {}
    for part in text.split(','):
        n, _, r = part.partition(':')
        out[int(n)] = int(r) if r and r != 'none' else None
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--runs', required=True, help='directory searched for results/<run_id>.json envelopes')
    ap.add_argument('--scenario', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--resamples', type=int, default=10000)
    ap.add_argument('--bootstrap-seed', type=int, default=20260928)
    ap.add_argument('--certify-bound', choices=('interval_95', 'one_sided_95'), default='interval_95',
                    help='bound that certifies a statement: the two-sided 95%% interval (default) or the one-sided 95%% bound')
    ap.add_argument('--open-episodes', choices=('include', 'exclude'), default='include',
                    help='episodes still open at the end of a run: their recorded values enter the statistics (default) or not')
    ap.add_argument('--f3-f6-statistic', choices=('episode', 'run_total'), default='episode',
                    help='I6-F3 and I6-F6: first-episode exposure (default) or released_exposure of the whole run')
    ap.add_argument('--f6-rule', choices=('holm', 'upper_bound'), default='holm',
                    help='I6-F6: Holm-corrected one-sided bootstrap test over the rate levels (default) or the '
                         'unadjusted 95%% upper bound below the bound')
    ap.add_argument('--f2-episodes', default='1', help='episodes judged by I6-F2 (default 1; "1,2" for both)')
    ap.add_argument('--f2-bound', choices=('two_sided', 'one_sided'), default='two_sided',
                    help='p*_L of I6-F2: lower end of the two-sided exact 95%% interval (default) or the one-sided bound')
    ap.add_argument('--f12b-scope', choices=('premise', 'all'), default='premise')
    ap.add_argument('--pc-episode', choices=('first', 'any'), default='first')
    ap.add_argument('--p-star', action='append', default=[], metavar='PROFILE=VALUE')
    ap.add_argument('--v-rounds', default='9:9,12:none,20:14,40:14', help='R of the (8/N)^R prediction per N')
    ap.add_argument('--ignore-fault-item', action='append', default=[], metavar='ITEM')
    ap.add_argument('--manual-exclusions', help='JSON file {run_id: reason} of runs outside the premise by logs')
    ap.add_argument('--allow-dirty', action='store_true', help='record a dirty checkout instead of refusing to run')
    a = ap.parse_args(argv)
    src = _source_state()
    if src['dirty'] and not a.allow_dirty:
        print('i6_analysis: clean checkout required (or --allow-dirty)', file=sys.stderr)
        return 2
    p_star = {'data-api-fast-v1': REGISTERED['data-api-fast-v1']['p_star']['value']}
    p_star.update(_p_star(a.p_star))
    opts = Options(resamples=a.resamples, bootstrap_seed=a.bootstrap_seed, certify_bound=a.certify_bound,
                   open_episodes=a.open_episodes, f3_f6_statistic=a.f3_f6_statistic,
                   f2_episodes=[int(x) for x in a.f2_episodes.split(',')], f2_bound=a.f2_bound, f12b_scope=a.f12b_scope,
                   pc_episode=a.pc_episode, p_star=p_star, f6_rule=a.f6_rule, v_rounds=_v_rounds(a.v_rounds),
                   ignore_fault_items=a.ignore_fault_item,
                   manual_exclusions=_read_json(a.manual_exclusions) if a.manual_exclusions else None)
    try:
        res = analyze(a.runs, a.scenario, opts)
    except (InputError, scn.ScenarioError) as exc:
        print(f'i6_analysis: {exc}', file=sys.stderr)
        return 2
    res['source'] = src
    write_outputs(res, a.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
