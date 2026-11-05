"""The shared operating point (experiments/operating-point.json) and the symbols it defines.

Scenarios and baseline configs never carry their own copies of g, v, p, L and
the rates; they name them. This module loads the file, checks the derived
entries against the profile arithmetic, and evaluates the names:

    block expressions   L, L_min, delta_F, caseHorizon, hold_period, keeper_margin, and the
                        hold-period grid names T_min (= L_min), T_stop (= delta_F),
                        T_catch (= L), T_case (= caseHorizon), T_hold (= hold_period),
                        with + - * / ( ), e.g. 'L_min/2', '(T_stop+T_catch)/2', '2*L';
                        the result is floored; L_actual and L_actual_min, the largest and
                        smallest measured length of the worst judgment path (L_actual_blocks
                        value and min), are symbols only once they are recorded
    value expressions   g, v, p, pi, g_over_p, failureLimit, e.g. 'g/(2*p)', 'v/2'
    rates               'rate:<name>' from rates.named, in settlements per block
    references          'op:<expression>' in baseline configs, same grammar
"""
import ast
import copy
import hashlib
import json
import math
import operator
from pathlib import Path

from . import profile as prof

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PATH = ROOT / 'experiments' / 'operating-point.json'

BLOCK_SYMBOLS = ('L', 'L_min', 'delta_F', 'caseHorizon', 'hold_period', 'keeper_margin',
                 'T_min', 'T_stop', 'T_catch', 'T_case', 'T_hold')
# The hold-period grid of I6 names the same delays by what they bound: T_min the delay no
# seller can shorten, T_stop the freeze at the initial FAIL, T_catch the confirmed failure,
# T_case the case horizon, T_hold the deployed hold period.
GRID_ALIASES = {'T_min': 'L_min', 'T_stop': 'delta_F', 'T_catch': 'L', 'T_case': 'caseHorizon',
                'T_hold': 'hold_period'}
VALUE_SYMBOLS = ('g', 'v', 'p', 'pi', 'h', 'beta', 'alpha', 'c', 'g_over_p', 'failureLimit',
                 'lambda_max', 'refill', 'L_hours', 'delta_F_hours', 'L_hours_data_api', 'L_hours_open_weights')
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


class OperatingPointError(ValueError):
    pass


def min_detection_delay(profile):
    """L_min: epochBlocks + anchorBlocks + beaconDelayBlocks (a sale in the last block of an
    epoch is not sampled before the anchor deadline of the next epoch plus the beacon delay)."""
    p = profile['parameters']
    return p['epochBlocks'] + p['deadlineConfig']['anchorBlocks'] + p['beaconDelayBlocks']


def freeze_delay(profile):
    """delta_F: worst-case blocks from a bad settlement to the freeze at its initial FAIL."""
    p = profile['parameters']
    d = p['deadlineConfig']
    return prof.open_horizon(profile) + p['maxAssignments'] * (d['judgeBlocks'] + 1) + d['evidenceBlocks']


def load(path=DEFAULT_PATH):
    path = Path(path)
    raw = path.read_bytes()
    doc = json.loads(raw.decode('ascii'))
    if doc.get('kind') != 'fairbind-operating-point' or doc.get('formatVersion') != 1:
        raise OperatingPointError(f'{path}: not an operating point file')
    doc['_sha256'] = hashlib.sha256(raw).hexdigest()
    doc['_path'] = str(path)
    return doc


def _entry(op, profile_name, key):
    try:
        return op['profiles'][profile_name][key]['value']
    except KeyError as exc:
        raise OperatingPointError(f'operating point has no {key} for {profile_name}') from exc


CHECK_MODES = ('design-1', 'design-2')


def check(op, profile, mode='design-1', g_over_p=None, window_lengths=None):
    """Return the mismatches between the operating point and the profile (empty when consistent).

    mode 'design-1' (default) is the check of the shared evaluation profiles: the hold period
    covers the case horizon (a negative keeper margin is an error) and the retention, claim, failure
    and inconclusive windows all equal the hold period.

    mode 'design-2' is the named mode of the reduced design (design2_rules D2-8, D2-9). The hold
    period may be below caseHorizon, so the keeper margin hold - caseHorizon may be negative; it must
    still equal the operating point's entry and the hold period must cover the measured longest path
    L_actual. Only the retention and claim windows are tied to the hold period; the failure and
    inconclusive windows must be one of `window_lengths`. `g_over_p` replaces the expected value of
    g_over_p_atomic, which the design-2 exposure floor changes."""
    if mode not in CHECK_MODES:
        raise OperatingPointError(f'unknown check mode {mode!r}')
    name = profile['name']
    if name not in op['profiles']:
        return [f'profile {name} is not in the operating point']
    p = profile['parameters']
    ppm = op['chain']['ppm']
    expected = {
        'g_atomic': int(p['maxBadGain']),
        'v_atomic': int(p['maxPurchaseValue']),
        'pi': p['samplePpm'] / ppm,
        'p_ceiling': p['effectivePpm'] / ppm,
        'L_blocks': prof.judgment_delay(profile),
        'delta_F_blocks': freeze_delay(profile),
        'L_min_blocks': min_detection_delay(profile),
        'caseHorizon_blocks': prof.case_horizon(profile),
        'hold_period_blocks': max(p['deferBlocks'], p['retentionBlocks']),
        'keeper_margin_blocks': max(p['deferBlocks'], p['retentionBlocks']) - prof.case_horizon(profile),
        'failureLimit': p['failureLimit'],
        'lambda_max_per_block': p['maxRatePpmPerBlock'] / ppm,
        'refill_per_block': p['refillPpmPerBlock'] / ppm,
        'bucket_capacity': p['bucketCapacity'],
        'g_over_p_atomic': (prof.penalty_floor(profile, defer_blocks=prof.judgment_delay(profile))
                            if g_over_p is None else g_over_p),
    }
    errors = []
    hold = max(p['deferBlocks'], p['retentionBlocks'])
    if mode == 'design-1' and hold - prof.case_horizon(profile) < 0:
        errors.append(f'{name}: negative keeper margin (hold period below caseHorizon) outside design-2 mode')
    if mode == 'design-2':
        l_actual = op['profiles'][name].get('L_actual_blocks', {}).get('value')
        if not isinstance(l_actual, int) or hold < l_actual:
            errors.append(f'{name}: hold period {hold} does not cover the measured longest path {l_actual}')
    for key, want in expected.items():
        got = _entry(op, name, key)
        if not math.isclose(got, want, rel_tol=1e-12, abs_tol=0):
            errors.append(f'{name}.{key} is {got}, profile gives {want}')
    tied = ('retentionBlocks', 'claimWindowBlocks', 'failureWindowBlocks', 'inconclusiveWindowBlocks')
    if mode == 'design-2':
        tied = ('retentionBlocks', 'claimWindowBlocks')
        for field in ('failureWindowBlocks', 'inconclusiveWindowBlocks'):
            if p[field] not in (window_lengths or ()):
                errors.append(f'{name}.{field} is not an allowed design-2 window length')
    for field in tied:
        if p[field] != _entry(op, name, 'hold_period_blocks'):
            errors.append(f'{name}.{field} differs from hold_period_blocks')
    bound = op['profiles'][name]['p_ceiling'].get('bound')
    pi, h, beta = (_entry(op, name, k) for k in ('pi', 'h', 'beta'))
    if bound is not None and not math.isclose(bound, round(pi * (h * (1 - beta)) ** 2, 4)):
        errors.append(f'{name}.p_ceiling.bound is not pi * (h * (1 - beta))^2')
    if _entry(op, name, 'p_ceiling') > pi * (h * (1 - beta)) ** 2 + 1e-12:
        errors.append(f'{name}.p_ceiling exceeds pi * (h * (1 - beta))^2')
    return errors


def symbols(op, profile_name):
    """Numeric symbol table for one profile."""
    e = lambda key: _entry(op, profile_name, key)  # noqa: E731
    hours = 3600 / op['chain']['block_seconds']
    table = dict(L=e('L_blocks'), L_min=e('L_min_blocks'), delta_F=e('delta_F_blocks'),
                caseHorizon=e('caseHorizon_blocks'), hold_period=e('hold_period_blocks'),
                keeper_margin=e('keeper_margin_blocks'),
                g=e('g_atomic'), v=e('v_atomic'), p=e('p_ceiling'), pi=e('pi'), h=e('h'), beta=e('beta'),
                alpha=e('alpha'), c=e('c'), g_over_p=e('g_over_p_atomic'), failureLimit=e('failureLimit'),
                lambda_max=e('lambda_max_per_block'), refill=e('refill_per_block'),
                L_hours=e('L_blocks') / hours, delta_F_hours=e('delta_F_blocks') / hours,
                **{'L_hours_' + '_'.join(n.split('-')[:2]): op['profiles'][n]['L_blocks']['value'] / hours
                   for n in op['profiles']})
    table.update({alias: table[name] for alias, name in GRID_ALIASES.items()})
    # L_actual: settlement block to confirmed-failure block, minus kappa_Sigma, of the
    # effective-detection cases of the worst judgment path, recorded here before the I6 main run:
    # `value` is the largest (L_actual, used by M4-worst) and `min` the smallest (L_actual_min, used
    # by the positive controls); `min` defaults to `value` when the path length is deterministic.
    # Until the value is recorded (null) the symbols are absent and every expression using them
    # stays unresolved, which blocks the run.
    entry = op['profiles'][profile_name].get('L_actual_blocks', {})
    measured = entry.get('value')
    if isinstance(measured, int) and not isinstance(measured, bool):
        table['L_actual'] = measured
        low = entry.get('min', measured)
        if not isinstance(low, int) or isinstance(low, bool) or low > measured:
            raise OperatingPointError(f'{profile_name}.L_actual_blocks.min must be an integer at most the value')
        table['L_actual_min'] = low
    return table


def rate_per_block(op, name):
    named = op['rates']['named']
    if name not in named:
        raise OperatingPointError(f'unknown rate {name!r}; known: {sorted(named)}')
    return named[name]['per_hour'] * op['chain']['block_seconds'] / 3600


def evaluate(expr, table):
    """Evaluate an arithmetic expression over the symbol table (+ - * / and parentheses only)."""
    if isinstance(expr, bool):
        raise OperatingPointError('boolean is not a number')
    if isinstance(expr, (int, float)):
        return expr
    try:
        tree = ast.parse(str(expr).strip(), mode='eval')
    except SyntaxError as exc:
        raise OperatingPointError(f'cannot parse {expr!r}') from exc

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) \
                and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in table:
                raise OperatingPointError(f'unknown symbol {node.id!r} in {expr!r}')
            return table[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise OperatingPointError(f'unsupported expression {expr!r}')
    return walk(tree)


def is_symbolic(value, table):
    """True when value is a string expression that uses only known symbols."""
    if not isinstance(value, str) or value.startswith('rate:'):
        return False
    try:
        evaluate(value, table)
    except OperatingPointError:
        return False
    return True


def number(expr, table):
    """evaluate(), returning an int when the result is integral."""
    result = evaluate(expr, table)
    return int(round(result)) if abs(result - round(result)) < 1e-6 else result


def blocks(expr, table):
    return int(math.floor(evaluate(expr, table) + 1e-9))


def resolve_reference(value, op, table):
    """Resolve 'op:<expr>' and 'rate:<name>' strings; other values are returned unchanged."""
    if isinstance(value, str) and value.startswith('op:'):
        return number(value[3:], table)
    if isinstance(value, str) and value.startswith('rate:'):
        return rate_per_block(op, value[5:])
    return value


def resolve_tree(doc, op, table):
    """Deep copy of doc with every 'op:' and 'rate:' string resolved."""
    if isinstance(doc, dict):
        return {k: resolve_tree(v, op, table) for k, v in doc.items()}
    if isinstance(doc, list):
        return [resolve_tree(v, op, table) for v in doc]
    return resolve_reference(doc, op, table)


def summary(op, profile_name):
    """What a plan entry and a result envelope record about the operating point."""
    return dict(path=str(Path(op['_path']).relative_to(ROOT)) if str(op['_path']).startswith(str(ROOT))
                else op['_path'], sha256=op['_sha256'], profile=profile_name,
                values=copy.deepcopy({k: v['value'] for k, v in op['profiles'][profile_name].items()}))
