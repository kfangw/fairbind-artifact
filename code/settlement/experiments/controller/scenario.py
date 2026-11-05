"""Scenario loading, validation, sweep expansion and parameter resolution."""
import copy
import hashlib
import itertools
import re
from pathlib import Path

from . import operating_point as opt
from . import profile as prof
from .yamlsubset import load

PROCESSES = ('anvil', 'keeper', 'verifier', 'facilitator', 'seller', 'buyer')
PROCESS_ALIASES = {'chain': 'anvil'}
PROPERTY_CODES = ('P1', 'P2', 'P3', 'P4', 'P5', 'T5', 'T6', 'EXPOSURE')
CORE_METRICS = ('double_settlement_rate', 'post_settlement_unrecovered_rate', 'released_exposure',
                'anchor_gas_per_epoch', 'retention_storage_bytes', 'captured_funds_time_average',
                'false_positive_recovery_amount', 'locked_capital', 'gas_per_settlement', 'gas_per_judgment',
                'gas_per_dispute', 'gas_per_call', 'recovery_time_blocks', 'judgment_delay_distribution')
EXTENDED_METRICS = ('cheater_net_gain', 'sales_lost_while_suspended', 'exposure_vs_bond', 'buyer_recovery_rate',
                    'honest_seller_delay_blocks', 'honest_seller_suspended_fraction', 'frozen_amount',
                    'rejected_settlement_count', 'capital_locked_time_integral', 'realized_detection_rate',
                    'realized_sample_rate')
METRICS_FILE = Path(__file__).resolve().parents[1] / 'metrics.md'
_METRIC_ROW = re.compile(r'^\| `([A-Za-z_][A-Za-z0-9_]*)` \|')


def metric_ids(path=METRICS_FILE):
    """Metric ids defined in experiments/metrics.md (the first column of its tables)."""
    ids = []
    for line in Path(path).read_text().splitlines():
        m = _METRIC_ROW.match(line)
        if m:
            ids.append(m.group(1))
    return ids


SPECIFIC_METRICS = frozenset(metric_ids())

# How the controller injects each fault kind:
#   restart   - the controller kills the process at a trigger event and relaunches it;
#   proxy     - the controller-owned HTTP proxy between buyer and seller drops or delays responses;
#   directive - the controller writes a directive file that only the faulted process reads.
FAULT_KINDS = {
    'process_restart': ('restart',),
    'drop_response': ('proxy',),
    'delay_response': ('proxy',),
    'withhold_response': ('proxy', 'directive'),
    'omit_receipt_from_anchor': ('directive',),
    'withhold_anchor': ('directive',),
    'refuse_redelivery': ('directive',),
    'burst_rate': ('directive',),
    'patient_defection': ('directive',),
    'calculating_cheater': ('directive',),
    'verifier_idle': ('directive',),
    'wrong_verdict': ('directive',),
    'collusion': ('directive',),
    'false_non_delivery_claim': ('directive',),
    'false_wrong_delivery_collusion': ('directive',),
    'verifier_always_inconclusive': ('directive',),
    'natural_inconclusive': ('directive',),
    'keeper_outage': ('directive',),
    'seal_withholding': ('directive',),
    'reentering_cheater': ('directive',),
    'double_refund_attempt': ('directive',),
    'honest_high_rate': ('directive',),
    'hold_period_grid': ('directive',),
}

# Scenario parameters the controller applies to the service profile.
DEADLINE_PARAMS = {name: name for name in prof.DEADLINE_FIELDS}
PROFILE_PARAMS = {'epochBlocks': 'epochBlocks', 'maxAssignments': 'maxAssignments',
                  'D_holding_blocks': 'deferBlocks', 'bucket_capacity_q': 'bucketCapacity',
                  'dispute_deposit': 'disputeDeposit'}
SPECIAL_PARAMS = ('cap_enabled', 'P_S_reserve', 'bond_fraction_of_g_over_p', 'bond_level_realized_atomic',
                  'declared_maxBadGain', 'L_judgment_delay_blocks',
                  'refill_rate_lambda_r',
                  'auto_recheck_prob_pi_v', 'arm', 'exact_hold', 'cell', 'judgment_path',
                  'freeze_on_initial_fail', 'finite_attack_cheat_sales', 'finite_attack_after')
# Categorical string values a parameter may take without being an unresolved symbol.
CATEGORICAL = frozenset({'uniform_random', 'false_fail', 'false_pass', 'buyer_complains_when_verdict_known',
                         'bucket_max', 'bucket_max_x10', 'normal', 'worst', 'after_each_deduction_to_scale',
                         'none', 'cheater', 'honest', 'serve_honestly', 'stop_selling', 'request_exit'})
JUDGMENT_PATHS = ('normal', 'worst')
FINITE_ATTACK_AFTER = ('serve_honestly', 'stop_selling', 'request_exit')
SUPPORTED_ARMS = ('fairbind',)
REQUIRED = ('id', 'name', 'property_under_test', 'preconditions', 'injected_fault', 'parameters', 'n_seeds',
            'observed_metrics', 'expected_outcome', 'ground_truth_source', 'pass_criteria', 'notes')
# Optional: `cells` replaces the full sweep product by named partial grids (I6), and `analysis`
# records the judgment rules the analysis applies to them (falsification conditions, Holm
# families, pruning). The controller validates both and applies neither verdict.
OPTIONAL = ('cells', 'analysis')
CELL_FIELDS = ('set', 'sweep', 'repetitions', 'min_repetitions', 'rate_class', 'profile', 'role', 'note')
RATE_CLASSES = ('low', 'high')
# A cell runs only under its `profile` (the data API profile when it names none).
DEFAULT_CELL_PROFILE = 'data-api-fast-v1'
CELL_ROLES = ('cheater', 'honest', 'positive_control')
_HANGUL = re.compile('[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]')


class ScenarioError(ValueError):
    pass


def load_scenario(path):
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode('ascii')
    except UnicodeDecodeError as exc:
        raise ScenarioError(f'{path.name}: scenario files must be ASCII') from exc
    doc = load(text)
    errors = validate(doc, path.stem)
    if errors:
        raise ScenarioError(f'{path.name}: ' + '; '.join(errors))
    doc['_sha256'] = hashlib.sha256(raw).hexdigest()
    doc['_path'] = str(path)
    return doc


def load_all(directory):
    paths = sorted(Path(directory).glob('*.yaml'))
    if not paths:
        raise ScenarioError(f'no scenario files in {directory}')
    return [load_scenario(p) for p in paths]


def fault_processes(sc):
    procs = sc['injected_fault']['process']
    procs = procs if isinstance(procs, list) else [procs]
    return [PROCESS_ALIASES.get(p, p) for p in procs]


def validate(doc, stem):
    if not isinstance(doc, dict):
        return ['top level must be a mapping']
    errors = [f'missing field {k}' for k in REQUIRED if k not in doc]
    extra = sorted(set(doc) - set(REQUIRED) - set(OPTIONAL))
    if extra:
        errors.append(f'unknown fields {extra}')
    if errors:
        return errors
    if doc['id'] != stem:
        errors.append(f'id {doc["id"]} does not match file name')
    for key in ('name', 'expected_outcome', 'ground_truth_source', 'pass_criteria', 'notes'):
        if not isinstance(doc[key], str) or not doc[key].strip():
            errors.append(f'{key} must be a non-empty string')
    props = doc['property_under_test']
    if not isinstance(props, list) or not props or any(p not in PROPERTY_CODES for p in props):
        errors.append(f'property_under_test must list codes from {PROPERTY_CODES}')
    if not isinstance(doc['preconditions'], list) or not all(isinstance(p, str) for p in doc['preconditions']):
        errors.append('preconditions must be a list of strings')
    fault = doc['injected_fault']
    if not isinstance(fault, dict):
        errors.append('injected_fault must be a mapping')
    else:
        unknown = sorted(set(fault) - {'process', 'kind', 'action', 'timing', 'target', 'trigger'})
        if unknown:
            errors.append(f'unknown injected_fault fields {unknown}')
        procs = fault.get('process')
        procs = procs if isinstance(procs, list) else [procs]
        if not procs or any(PROCESS_ALIASES.get(p, p) not in PROCESSES for p in procs):
            errors.append(f'injected_fault.process must name processes from {PROCESSES}')
        kind = fault.get('kind')
        if kind not in FAULT_KINDS:
            errors.append(f'unknown fault kind {kind!r}')
        elif kind == 'process_restart' and (len(procs) != 1 or not isinstance(fault.get('trigger'), str)):
            errors.append('process_restart needs one process and a trigger')
        for key in ('action', 'timing'):
            if not isinstance(fault.get(key), str):
                errors.append(f'injected_fault.{key} must be a string')
    params = doc['parameters']
    if not isinstance(params, dict) or not params:
        errors.append('parameters must be a non-empty mapping')
    else:
        for name, spec in params.items():
            if not isinstance(spec, dict) or 'default' not in spec:
                errors.append(f'parameter {name} needs a default')
                continue
            if set(spec) - {'default', 'sweep', 'unit'}:
                errors.append(f'parameter {name} has unknown fields')
            if 'sweep' in spec and (not isinstance(spec['sweep'], list) or not spec['sweep']
                                    or len(set(map(repr, spec['sweep']))) != len(spec['sweep'])):
                errors.append(f'parameter {name} sweep must be a non-empty list without duplicates')
        if isinstance(fault, dict) and fault.get('kind') == 'process_restart':
            trig = fault.get('trigger')
            if trig in params and 'sweep' not in params[trig]:
                errors.append(f'trigger parameter {trig} needs a sweep')
        if isinstance(fault, dict) and fault.get('kind') == 'delay_response' and 'response_delay_blocks' not in params:
            errors.append('delay_response needs response_delay_blocks')
    if isinstance(params, dict) and params:
        cell_names = set()
        if 'cells' in doc:
            errors.extend(_validate_cells(doc['cells'], params, cell_names))
        if 'analysis' in doc:
            errors.extend(_validate_analysis(doc['analysis'], cells(doc), cell_names))
    n = doc['n_seeds']
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        errors.append('n_seeds must be a positive integer')
    metrics = doc['observed_metrics']
    if not isinstance(metrics, dict):
        errors.append('observed_metrics must be a mapping')
    else:
        if tuple(metrics.get('core') or ()) != CORE_METRICS:
            errors.append(f'observed_metrics.core must list the {len(CORE_METRICS)} core metrics in order')
        if tuple(metrics.get('extended') or ()) != EXTENDED_METRICS:
            errors.append(f'observed_metrics.extended must list the {len(EXTENDED_METRICS)} extended metrics in order')
        specific = metrics.get('scenario_specific', [])
        if not isinstance(specific, list) or any(m not in SPECIFIC_METRICS for m in specific):
            errors.append('observed_metrics.scenario_specific names a metric not defined in experiments/metrics.md')
        elif set(specific) & set(CORE_METRICS + EXTENDED_METRICS):
            errors.append('observed_metrics.scenario_specific repeats a core or extended metric')
        if set(metrics) - {'core', 'extended', 'scenario_specific'}:
            errors.append('observed_metrics has unknown fields')
    for text in _strings(doc):
        if _HANGUL.search(text):
            errors.append('scenario text must be English')
            break
    return errors


def _positive_int(v):
    return isinstance(v, int) and not isinstance(v, bool) and v >= 1


def cells(sc):
    """The scenario's cells in file order, each with its name under 'name'."""
    return [dict(spec, name=name) for name, spec in (sc.get('cells') or {}).items()]


def _validate_cells(cells, params, names):
    errors = []
    if not isinstance(cells, dict) or not cells:
        return ['cells must be a non-empty mapping from cell name to cell']
    for name, cell in cells.items():
        if not isinstance(cell, dict):
            errors.append(f'cell {name} must be a mapping')
            continue
        names.add(name)
        if set(cell) - set(CELL_FIELDS):
            errors.append(f'cell {name} has unknown fields {sorted(set(cell) - set(CELL_FIELDS))}')
        fixed, sweep = cell.get('set') or {}, cell.get('sweep') or {}
        if not isinstance(fixed, dict) or not isinstance(sweep, dict):
            errors.append(f'cell {name}: set and sweep must be mappings')
            continue
        for key in list(fixed) + list(sweep):
            if key not in params:
                errors.append(f'cell {name} names undeclared parameter {key}')
        if set(fixed) & set(sweep):
            errors.append(f'cell {name} both sets and sweeps {sorted(set(fixed) & set(sweep))}')
        for key, values in sweep.items():
            if not isinstance(values, list) or not values or len(set(map(repr, values))) != len(values):
                errors.append(f'cell {name} sweep of {key} must be a non-empty list without duplicates')
        reps = cell.get('repetitions')
        if not _positive_int(reps):
            errors.append(f'cell {name} needs a positive repetitions count')
        low = cell.get('min_repetitions')
        if low is not None and (not _positive_int(low) or (_positive_int(reps) and low > reps)):
            errors.append(f'cell {name}: min_repetitions must be a positive count not above repetitions')
        if cell.get('rate_class') not in RATE_CLASSES:
            errors.append(f'cell {name}: rate_class must be one of {RATE_CLASSES}')
        if cell.get('role', 'cheater') not in CELL_ROLES:
            errors.append(f'cell {name}: role must be one of {CELL_ROLES}')
        path = fixed.get('judgment_path', params.get('judgment_path', {}).get('default', 'normal'))
        if 'judgment_path' in params and path not in JUDGMENT_PATHS:
            errors.append(f'cell {name}: judgment_path must be one of {JUDGMENT_PATHS}')
    return errors


def _validate_analysis(analysis, cells, names):
    errors = []
    if not isinstance(analysis, dict):
        return ['analysis must be a mapping']
    if set(analysis) - {'conditions', 'holm_families', 'pruning', 'honest_top_up_policy'}:
        errors.append('analysis has unknown fields')
    conditions = analysis.get('conditions') or {}
    if not isinstance(conditions, dict) or not conditions:
        errors.append('analysis.conditions must be a non-empty mapping')
        conditions = {}
    for cid, cond in conditions.items():
        if not isinstance(cond, dict) or not isinstance(cond.get('statistic'), str) \
                or not isinstance(cond.get('threshold'), str):
            errors.append(f'condition {cid} needs a statistic and a threshold')
            continue
        for c in list(cond.get('cells', [])) + list(cond.get('descriptive_cells', [])):
            if c not in names:
                errors.append(f'condition {cid} names unknown cell {c}')
    by_name = {c['name']: c for c in cells if isinstance(c, dict) and 'name' in c}
    families = analysis.get('holm_families') or {}
    if not isinstance(families, dict):
        errors.append('analysis.holm_families must be a mapping from family name to family')
        families = {}
    for fname, fam in families.items():
        if not isinstance(fam, dict) or fam.get('condition') not in conditions:
            errors.append(f'Holm family {fname} names no known condition')
            continue
        if fam.get('episode') not in (1, 2, None):
            errors.append(f'Holm family of {fam["condition"]}: episode must be 1 or 2')
        members = fam.get('cells') or []
        if not members:
            errors.append(f'Holm family of {fam["condition"]} is empty')
        for c in members:
            if c not in names:
                errors.append(f'Holm family of {fam["condition"]} names unknown cell {c}')
            elif fam.get('rate_class') and by_name[c].get('rate_class') != fam['rate_class']:
                errors.append(f'Holm family of {fam["condition"]} mixes rate class at cell {c}')
    pruning = analysis.get('pruning')
    if pruning is not None:
        if not isinstance(pruning, dict):
            errors.append('analysis.pruning must be a mapping')
        else:
            order, reduced, floor = pruning.get('order') or [], pruning.get('reduced_repetitions'), \
                pruning.get('min_repetitions')
            for c in order:
                if c not in names:
                    errors.append(f'pruning order names unknown cell {c}')
                elif by_name[c].get('rate_class') != 'low':
                    errors.append(f'pruning order names cell {c} that is not a low-rate cell')
            if not (_positive_int(reduced) and _positive_int(floor) and floor <= reduced):
                errors.append('pruning needs min_repetitions <= reduced_repetitions, both positive')
            if not _positive_int(pruning.get('min_second_episode_runs')):
                errors.append('pruning needs a positive min_second_episode_runs')
            for c in order:
                cell = by_name.get(c)
                if cell and _positive_int(floor) and cell.get('min_repetitions') not in (None, floor):
                    errors.append(f'cell {c}: min_repetitions differs from the pruning floor')
    return errors


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def metric_names(sc):
    m = sc['observed_metrics']
    names = list(m['core']) + list(m['extended'])
    return names + [x for x in m.get('scenario_specific', []) if x not in names]


def sweep_points(sc):
    """Cartesian product of swept parameters in file order; others take their default.

    A scenario with `cells` is instead the union of its cells in file order: each cell fixes
    some parameters (`set`), sweeps others (`sweep`), and leaves the rest at their default;
    every point carries its cell name as `cell`.
    """
    params = sc['parameters']
    if 'cells' in sc:
        points = []
        base = {n: s['default'] for n, s in params.items()}
        for cell in cells(sc):
            sweep = cell.get('sweep') or {}
            names = list(sweep)
            for combo in itertools.product(*(sweep[n] for n in names)):
                point = dict(base)
                point.update(cell.get('set') or {})
                point.update(zip(names, combo))
                point['cell'] = cell['name']
                points.append(point)
        return points
    swept = [n for n, s in params.items() if 'sweep' in s]
    base = {n: s['default'] for n, s in params.items()}
    points = []
    for combo in itertools.product(*(params[n]['sweep'] for n in swept)):
        point = dict(base)
        point.update(zip(swept, combo))
        points.append(point)
    return points


def cell_of(sc, point):
    """The cell definition a point belongs to, or None for a plain sweep."""
    name = point.get('cell')
    return next((c for c in cells(sc) if c['name'] == name), None)


def point_repetitions(sc, point):
    """Repetitions of a point: its cell's count when the scenario has cells, else n_seeds."""
    cell = cell_of(sc, point)
    return cell['repetitions'] if cell else sc['n_seeds']


def run_seed(base_seed, scenario_id, point_index, repetition):
    digest = hashlib.sha256(f'{base_seed}:{scenario_id}:{point_index}:{repetition}'.encode()).digest()
    return int.from_bytes(digest[:8], 'big') >> 1


def block_table(op, profile):
    """Symbols for one resolved point: value symbols from the operating point, block symbols
    recomputed from the derived profile (a deadline override moves L and the horizons)."""
    table = opt.symbols(op, profile['name'])
    table.update(L=prof.judgment_delay(profile), delta_F=opt.freeze_delay(profile),
                 L_min=opt.min_detection_delay(profile), caseHorizon=prof.case_horizon(profile))
    table.update({alias: table[name] for alias, name in opt.GRID_ALIASES.items()})
    return table


def resolve(sc, point, base_profile, overrides=None, op=None):
    """Resolve one sweep point against the base profile.

    Returns a dict with the resolved parameters, the derived profile, the
    profile overrides it applied, the directive parameters, unresolved symbols,
    admissibility violations and reasons the point cannot run.
    """
    op = op if op is not None else opt.load()
    overrides = dict(overrides or {})
    values = dict(point)
    values.update({k: v for k, v in overrides.items() if k in values})
    profile = copy.deepcopy(base_profile)
    p = profile['parameters']
    applied, unresolved, blocked, notes = {}, [], [], []
    override_used = False

    def numeric(name):
        v = values[name]
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    for name, field in DEADLINE_PARAMS.items():
        if name in values and values[name] != 'profile_default':
            if not numeric(name):
                unresolved.append(name)
                continue
            p['deadlineConfig'][field] = int(values[name])
            applied[f'deadlineConfig.{field}'] = int(values[name])
    for name in ('epochBlocks', 'maxAssignments', 'bucket_capacity_q', 'dispute_deposit'):
        if name in values and values[name] != 'profile_default':
            if not numeric(name):
                unresolved.append(name)
                continue
            field = PROFILE_PARAMS[name]
            v = int(values[name])
            p[field] = str(v) if isinstance(p[field], str) else v
            applied[field] = p[field]
    if 'refill_rate_lambda_r' in values and values['refill_rate_lambda_r'] != 'profile_default':
        if numeric('refill_rate_lambda_r'):
            p['refillPpmPerBlock'] = prof.ceil_ppm(values['refill_rate_lambda_r'])
            applied['refillPpmPerBlock'] = p['refillPpmPerBlock']
        else:
            unresolved.append('refill_rate_lambda_r')
    if 'auto_recheck_prob_pi_v' in values and values['auto_recheck_prob_pi_v'] != 'profile_default':
        if numeric('auto_recheck_prob_pi_v'):
            p['recheckPpm'] = prof.ceil_ppm(values['auto_recheck_prob_pi_v'])
            applied['recheckPpm'] = p['recheckPpm']
        else:
            unresolved.append('auto_recheck_prob_pi_v')

    L = prof.judgment_delay(profile)
    table = block_table(op, profile)
    for name, v in list(values.items()):
        # Rates and value expressions come from the operating point, never from literals.
        if isinstance(v, str) and v.startswith('rate:'):
            try:
                values[name] = opt.rate_per_block(op, v[5:])
            except opt.OperatingPointError:
                unresolved.append(name)
        elif name != 'D_holding_blocks' and opt.is_symbolic(v, table):
            # A block count is a whole number of blocks: an expression such as keeper_margin/2
            # is rounded down.
            values[name] = opt.blocks(v, table) if name.endswith('_blocks') else opt.number(v, table)
    if 'L_judgment_delay_blocks' in values:
        given = values['L_judgment_delay_blocks']
        if given == 'profile_judgment_delay':
            values['L_judgment_delay_blocks'] = L
        elif numeric('L_judgment_delay_blocks') and int(given) != L:
            notes.append(f'L_judgment_delay_blocks {given} differs from the profile judgment delay {L}; '
                         'the profile value is used')
            values['L_judgment_delay_blocks'] = L
        elif not numeric('L_judgment_delay_blocks'):
            unresolved.append('L_judgment_delay_blocks')
    if 'D_holding_blocks' in values and values['D_holding_blocks'] != 'profile_default':
        try:
            values['D_holding_blocks'] = opt.blocks(values['D_holding_blocks'], table)
        except opt.OperatingPointError:
            unresolved.append('D_holding_blocks')
        else:
            D = values['D_holding_blocks']
            hold = max(p['deferBlocks'], p['retentionBlocks'])
            if D >= prof.case_horizon(profile):
                # Admissible point: no override. At or below the profile hold period the
                # profile runs unchanged; above it the hold fields are raised to D. With
                # exact_hold (the I6 grid) a point between the case horizon and the profile
                # hold period lowers them to D as well, which is still admissible.
                if D > hold or (values.get('exact_hold') is True and D < hold):
                    for field in prof.D_SWEEP_FIELDS:
                        p[field] = D
                        applied[field] = D
                else:
                    notes.append(f'D = {D} is at or above caseHorizon; the admissible profile hold period '
                                 f'{hold} is used without override')
            else:
                # Release needs both releaseBlock (settledBlock + deferBlocks) and retainUntil
                # (settledBlock + retentionBlocks), and the claim window must equal retention, so
                # these three follow D. failureWindowBlocks and inconclusiveWindowBlocks stay at
                # the profile values. The profile then needs the override build.
                for field in prof.D_SWEEP_FIELDS:
                    p[field] = D
                    applied[field] = D
                # Below the case horizon the confirmed failure can come after the release, so
                # the sweep keeps the freeze at the initial FAIL (delta_F); the override build
                # requires the flag there.
                p['freezeOnInitialFail'] = True
                applied['freezeOnInitialFail'] = True
                override_used = True
    # 'D' is the effective hold period of this point; a parameter may be an expression in it
    # (for example the slow cheater rate 1/(10*p*D)).
    table['D'] = max(p['deferBlocks'], p['retentionBlocks'])
    for name, v in list(values.items()):
        if isinstance(v, str) and name != 'D_holding_blocks' and opt.is_symbolic(v, table):
            values[name] = opt.blocks(v, table) if name.endswith('_blocks') else opt.number(v, table)
    # bucket_max is the sustained bucket rate of the account, scale_factor * r_fill (the refill
    # rate of the deployed rate fields, read before any cap transform); bucket_max_x10 is ten
    # times that, used only with the cap off.
    if values.get('Lambda_cheater') in ('bucket_max', 'bucket_max_x10'):
        scale = values.get('scale_factor', 1)
        if isinstance(scale, (int, float)) and not isinstance(scale, bool):
            factor = 10 if values['Lambda_cheater'] == 'bucket_max_x10' else 1
            values['Lambda_cheater'] = factor * scale * p['refillPpmPerBlock'] / prof.PPM
        else:
            unresolved.append('Lambda_cheater')
    # The cap transform comes before the penalty: the floor is computed from the rate fields
    # that are actually deployed, because every build (the override build included) enforces
    # sellerPenalty >= expectedPenaltyFloor.
    if values.get('cap_enabled') is False:
        prof.disable_cap(profile)
        for field in ('enforcementBlocks', 'maxRatePpmPerBlock', 'refillPpmPerBlock', 'bucketCapacity'):
            applied[field] = p[field]
    # The worst-path positive control keeps the production freeze timing below the case horizon
    # (freeze_on_initial_fail: false on the override build), so that a confirmed failure after
    # the hold period shows as a release. An admissible point cannot switch the flag on.
    fof = values.get('freeze_on_initial_fail', 'profile_default')
    if fof is False and override_used:
        p['freezeOnInitialFail'] = False
        applied['freezeOnInitialFail'] = False
    elif fof is True and not override_used:
        blocked.append('freeze_on_initial_fail: true needs the override build (a hold below caseHorizon)')
    elif fof not in (True, False, 'profile_default'):
        unresolved.append('freeze_on_initial_fail')
    if values.get('judgment_path', 'normal') not in JUDGMENT_PATHS:
        unresolved.append('judgment_path')
    # A finite attack (controller/finiteattack.py): m cheated sales, then one of three courses.
    cheat = values.get('finite_attack_cheat_sales')
    if cheat is not None and (isinstance(cheat, bool) or not isinstance(cheat, int) or cheat < 1):
        unresolved.append('finite_attack_cheat_sales')
    if 'finite_attack_after' in values and (cheat is None or values['finite_attack_after'] not in FINITE_ATTACK_AFTER):
        unresolved.append('finite_attack_after')
    if values.get('P_S_reserve') == 'profile_penalty_floor':
        floor = prof.penalty_floor(profile)
        values['P_S_reserve'] = floor
        p['sellerPenalty'] = str(floor)
        applied['sellerPenalty'] = p['sellerPenalty']
    elif 'P_S_reserve' in values:
        if numeric('P_S_reserve'):
            p['sellerPenalty'] = str(int(values['P_S_reserve']))
            applied['sellerPenalty'] = p['sellerPenalty']
        else:
            unresolved.append('P_S_reserve')
    if 'bond_fraction_of_g_over_p' in values:
        if numeric('bond_fraction_of_g_over_p') and numeric('bad_sale_gain_atomic'):
            realized, declared = bond_level(profile, values['bond_fraction_of_g_over_p'],
                                            values['bad_sale_gain_atomic'])
            p['sellerPenalty'], p['maxBadGain'] = str(realized), str(declared)
            applied['sellerPenalty'], applied['maxBadGain'] = p['sellerPenalty'], p['maxBadGain']
            values['bond_level_realized_atomic'] = realized
            values['declared_maxBadGain'] = declared
        else:
            unresolved.append('bond_fraction_of_g_over_p')
    arm = values.get('arm', 'fairbind')
    if str(arm).lower() not in SUPPORTED_ARMS:
        blocked.append(f'arm {arm} runs through a policy adapter that is not in this repository')
    if values.get('bond_regime') not in (None, 'fairbind_penalty'):
        blocked.append(f'bond_regime {values["bond_regime"]} needs a baseline deployment')

    directive = {}
    for name, v in values.items():
        if name in DEADLINE_PARAMS or name in PROFILE_PARAMS or name in SPECIAL_PARAMS:
            continue
        directive[name] = v
        if isinstance(v, str) and v not in _allowed_strings(sc, name):
            unresolved.append(name)
    if 'D_holding_blocks' not in values:
        # A deadline sweep lengthens the case horizon; keep retention and deferral admissible.
        horizon = prof.case_horizon(profile)
        if p['retentionBlocks'] < horizon or p['deferBlocks'] < horizon:
            retention = max(p['retentionBlocks'], horizon)
            p['retentionBlocks'] = p['claimWindowBlocks'] = retention
            p['deferBlocks'] = max(p['deferBlocks'], retention)
            for field in ('retentionBlocks', 'claimWindowBlocks', 'deferBlocks'):
                applied[field] = p[field]
            notes.append(f'retention and deferral raised to the case horizon {horizon}')
        # The same sweep can lengthen the judgment delay past enforcementBlocks; raising the
        # enforcement window only relaxes the rate condition, so keep it admissible as well.
        if p['enforcementBlocks'] < prof.judgment_delay(profile):
            p['enforcementBlocks'] = prof.judgment_delay(profile)
            applied['enforcementBlocks'] = p['enforcementBlocks']
            notes.append(f'enforcementBlocks raised to the judgment delay {p["enforcementBlocks"]}')
    violations = prof.admissibility(profile)
    skipped = list(prof.OVERRIDE_SKIPPED_CHECKS) if override_used else []
    enforced = [v for v in violations if v not in skipped]
    if override_used and enforced:
        blocked.append('violates checks the override build still enforces: ' + ', '.join(enforced))
    requested_D = values.get('D_holding_blocks')
    if not (isinstance(requested_D, (int, float)) and not isinstance(requested_D, bool)):
        requested_D = None
    effective_hold_period = max(p['deferBlocks'], p['retentionBlocks'])
    return dict(parameters=values, parameter_expressions=dict(point), profile=profile, profile_overrides=applied, directive=directive,
                judgment_delay_blocks=L, unresolved=sorted(set(unresolved)), inadmissible=violations,
                blocked=blocked, notes=notes, override_used=override_used, override_skipped_checks=skipped,
                requested_D_holding_blocks=requested_D, effective_hold_period_blocks=effective_hold_period)


def bond_level(profile, fraction, true_gain):
    """Realize a bond of fraction * g/p (g = the seller's true gain per bad sale) as sellerPenalty.

    Every build enforces sellerPenalty >= expectedPenaltyFloor = maxBadGain * (ceil(1/p) + rate
    term) and sellerPenalty > 0, so a bond below g/p is realized by declaring a smaller
    maxBadGain (the field is used only in that floor) while the seller's directive keeps its
    true gain. A bond of 0 becomes the smallest admissible penalty (declared gain 1).
    Returns (sellerPenalty, declared maxBadGain).
    """
    p = profile['parameters']
    unit = prof.penalty_floor(profile) // prof._int(p['maxBadGain'])
    target = int(fraction * true_gain * (-(-prof.PPM // p['effectivePpm'])))
    declared = max(1, target // unit)
    return max(target, declared * unit), declared


def _allowed_strings(sc, name):
    """String values that are categorical choices rather than unresolved symbols."""
    spec = sc['parameters'][name]
    return set(v for v in spec.get('sweep', []) if isinstance(v, str)) | CATEGORICAL
