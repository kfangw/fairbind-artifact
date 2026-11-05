"""Plan and execute scenario runs against a six-process deployment."""
import datetime
import hashlib
import ipaddress
import json
import os
import re
import shutil
import signal
import string
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import baselines as bl
from . import faults
from . import operating_point as opt
from . import profile as prof
from . import scenario as scn
from . import finiteattack
from . import worstpath

ROOT = Path(__file__).resolve().parents[2]
LAUNCH_ORDER = ('anvil', 'keeper', 'verifier', 'facilitator', 'seller', 'buyer')
# Placeholders of manifest commands and env values. The port placeholders come from the port base P
# (--port-base): rpc_port P, base_port P + 10 (the service listeners), seller_port P + 11 (the seller
# listener the deploy step assigns) and proxy_port P + 80; rpcUrl and the proxy use only these.
PORT_PLACEHOLDERS = {'rpc_port', 'base_port', 'seller_port', 'proxy_port'}
PLACEHOLDERS = {'proc_dir', 'directive', 'profile', 'seed', 'rpc_url', 'observations', 'seller_url', 'repo', 'events',
                'run_dir'} | PORT_PLACEHOLDERS
# The ground truth path is given to the collector only.
COLLECTOR_PLACEHOLDERS = {'ground_truth'}
DEFAULT_PORT_BASE = 8545
KEEP_LOGS = ('none', 'failed', 'all')
# A command argument or env value that is exactly $NAME (upper case) takes that environment variable;
# any other $ is passed on unchanged.
ENV_REFERENCE = re.compile(r'\$([A-Z_][A-Z0-9_]*)')


# What a run seed changes. The harness is otherwise deterministic: the same workload on the same
# chain produces the same nonces and block hashes, and so the same sample draws. The seed changes
# exactly these three inputs: the nonce of every purchase and the block hashes that become epoch
# randomness (and therefore which purchases are sampled), and the verifier's per-assignment behavior
# draw of the judgment injection. The buyer driver reads this block from its directive; nothing else
# (fault timing, verdict timing, rates) depends on the seed.
INJECTION_DRAW = 'sha256(fairbind/seed/verifier || seed || nonce || stage || attempt || purpose)'
SEED_EFFECTS = {
    'buyer_idempotency_key': 'k of purchase i = first 16 bytes of SHA-256("fairbind/seed/k" || seed || i)',
    'intra_block_order': ('the buyer submits the settlements of one block in the order of a permutation drawn '
                          'from SHA-256("fairbind/seed/order" || seed || block number)'),
    'verifier_behavior_draw': ('on every assignment the verifier draws whether it acts honestly and whether it '
                               'errs from SHA-256("fairbind/seed/verifier" || seed || nonce || stage || attempt '
                               '|| purpose)'),
}

# The hold-period harness (I6): fault kinds whose plan gives every process the harness blocks below
# (judgment_injection, seller_policy, workload, clock) and a `harness` deploy block.
HARNESS_KINDS = ('hold_period_grid',)
# The base seed the experiment plan fixes for a scenario; a plan with another base seed says so.
PLAN_BASE_SEEDS = {'I6': 20260928}
# Services that write a progress file after every completed pass (directive.WriteProgress); the
# clock stops only when each has caught up with the head.
PROGRESS_ROLES = ('keeper', 'verifier', 'seller')
# The clock stops one block before every deadline and at it.
CLOCK_STOP_OFFSETS = (-1, 0)
INJECTION_APPLIES_TO = 'every assignment'
# Workload end rules by cell role: two episodes per cheater run (first and second episode), five
# complete failure windows per honest run, and the first 30 sampled worst-path cases per
# availability run.
EPISODES_PER_RUN = 2
HONEST_WINDOWS_PER_RUN = 5
WORST_PATH_CASES_PER_RUN = 30


def load_run_list(name, path=None):
    """Return {scenario id: [arm, ...]} for a named run of experiments/scenarios/run-list.json."""
    path = Path(path or ROOT / 'experiments' / 'scenarios' / 'run-list.json')
    doc = json.loads(path.read_text())
    if doc.get('kind') != 'fairbind-run-list' or name not in doc.get('runs', {}):
        raise ValueError(f'{path}: no run named {name}')
    return {e['scenario']: list(e['arms']) for e in doc['runs'][name]['entries']}


def build_plan(scenarios, base_profile, overrides=None, base_seed=0, repetitions=None, op=None, arms_by_scenario=None):
    """Plan every point of every scenario. Each point runs n_seeds times (the scenario's
    n_seeds unless `repetitions` overrides it for all scenarios). `arms_by_scenario` (from a run
    list) runs a scenario once per named arm; without it each scenario runs its own arm."""
    op = op if op is not None else opt.load()
    errors = opt.check(op, base_profile)
    if errors:
        raise opt.OperatingPointError('operating point does not match the profile: ' + '; '.join(errors))
    k = operating_point_k(op, base_profile['name'])
    op_summary = dict(opt.summary(op, base_profile['name']), k=k)
    arms = bl.load_all()
    metric_defs = dict(path='experiments/metrics.md',
                       sha256=hashlib.sha256(scn.METRICS_FILE.read_bytes()).hexdigest())
    plan = []
    known_arms = set(arms) | {'fairbind'}
    for sc in scenarios:
        own_arm = str(sc['parameters'].get('arm', {}).get('default', 'fairbind'))
        for arm in (arms_by_scenario or {}).get(sc['id'], [own_arm]):
            if arm not in known_arms:
                raise ValueError(f"run list names unknown arm {arm} for {sc['id']}")
            plan.extend(_plan_scenario(sc, arm, own_arm, base_profile, overrides, base_seed, repetitions, op,
                                       op_summary, metric_defs, arms))
    return plan


def operating_point_k(op, profile_name):
    """k (the failure limit failureLimit) of the operating point, with where it was read. The bond
    B = k * g * ceil(1/p) of a cell is bond_fraction_of_g_over_p: failureLimit resolved from the same
    entry, and opt.check has matched it against the profile's failureLimit."""
    entry = op['profiles'][profile_name]['failureLimit']
    path = opt.summary(op, profile_name)['path']
    return dict(value=entry['value'], source=f"{path} profiles.{profile_name}.failureLimit "
                                            f"({entry.get('status', 'unstated')}): {entry.get('source', '')}")


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def judgment_injection(op, profile_name, mode):
    """Verifier block: on every assignment the verifier acts honestly with probability h; an honest
    verifier fails a bad response with probability 1 - beta and a good one with alpha, a dishonest one
    passes a bad response and fails a good one with c. honest_error_off sets alpha = c = 0."""
    t = opt.symbols(op, profile_name)
    off = mode == 'honest_error_off'
    return dict(h=float(t['h']), alpha=0.0 if off else float(t['alpha']), beta=float(t['beta']),
                c=0.0 if off else float(t['c']), draw=INJECTION_DRAW, applies_to=INJECTION_APPLIES_TO,
                honest_error_off=off)


def seller_policy(role, scale_factor, honest_top_up):
    """Seller block: every role appeals every initial FAIL. A cheater tops its bond account up to
    n * B before it re-enters; an honest seller tops up after each deduction and re-enters at the
    first admitted block; a finite attacker never re-enters and never tops up (reentry and top_up
    both none)."""
    if role == 'finite':
        reentry, top_up = 'none', 'none'
    else:
        reentry = 'top_up_to_scale_then_reinstate'
        top_up = honest_top_up if role == 'honest' else 'before_reentry_to_scale'
    return dict(role=role, appeal_initial_fail=True, scale_factor=scale_factor, reentry=reentry, top_up=top_up)


def workload(role, params, profile, effective_hold):
    """Buyer driver block: the purchase rate, the claim rule and the end rule of the cell role."""
    p = profile['parameters']
    worst = params.get('judgment_path') == 'worst'
    if role == 'finite':
        end = dict(rule='finite_attack', m=params['finite_attack_cheat_sales'], hold_blocks=effective_hold,
                   case_horizon=prof.case_horizon(profile))
    elif role == 'honest':
        end = dict(rule='honest_windows', windows=HONEST_WINDOWS_PER_RUN, window_blocks=p['failureWindowBlocks'],
                   start_offset=effective_hold)
    elif role == 'availability':
        end = dict(rule='worst_path_cases', count=WORST_PATH_CASES_PER_RUN)
    else:
        end = dict(rule='episodes', count=EPISODES_PER_RUN)
    # max_blocks null: no block cap; the wall-clock limit of the run manifest bounds the run.
    return dict(rate_per_block=params.get('Lambda_cheater'), scale_factor=params.get('scale_factor', 1),
                dispute_sampled_sale=False, appeal_initial_pass=role == 'honest',
                claim='after_case_final' if worst else 'when_claimable', end=end, max_blocks=None)


def clock(kappa):
    """Buyer driver block for the chain clock: the progress files it waits on and the stop offsets."""
    return dict(progress=list(PROGRESS_ROLES), stop_offsets=list(CLOCK_STOP_OFFSETS), kappa=int(kappa))


def _spare_verifiers(profile, role, registered):
    """Spare identities: one per registered verifier, and for an availability run at least the
    removals its 30 worst-path cases can cause (each case strikes 3 * (maxAssignments - 1) + 1
    verifiers: the replaced assignments of the three stages and the overturned party review)."""
    if role != 'availability':
        return registered
    p = profile['parameters']
    strikes = 3 * worstpath.schedule(profile)['max_replaced_assignments'] + 1
    return max(registered, -(-WORST_PATH_CASES_PER_RUN * strikes // p['strikeLimit']))


def expected_purchases(role, params, profile, end):
    """Purchases a run of the cell role may send, with margin, for the buyer's funding: the rate
    times the blocks the end rule spans, doubled. A cheater episode is bounded by ten times the
    expected purchases to detection (P(no detection) = (1 - p)^(10/p) < e^-10) plus a case horizon
    of sales; an availability run by ten times the sales that yield its sampled cases."""
    p = profile['parameters']
    rate = float(params.get('Lambda_cheater') or 0)
    horizon = prof.case_horizon(profile)
    rule = end['rule']
    if rule == 'finite_attack':
        n = end['m'] + rate * (end['hold_blocks'] + end['case_horizon'])
    elif rule == 'honest_windows':
        n = rate * (end['start_offset'] + end['windows'] * end['window_blocks'])
    elif rule == 'worst_path_cases':
        n = 10 * end['count'] * PPM_UNIT / p['samplePpm']
    else:
        n = end['count'] * (10 * PPM_UNIT / p['effectivePpm'] + rate * horizon)
    return int(2 * n) + 100


PPM_UNIT = 1_000_000


def harness_plan(r, role, op, profile_name):
    """The harness blocks of one resolved point of a hold-period scenario: per-process directive
    blocks, the deploy `harness` block and the reasons it cannot run."""
    params, profile = r['parameters'], r['profile']
    reasons = []
    unresolved = set(r['unresolved'])
    blocks = {}
    if 'injection' not in unresolved:
        blocks['verifier'] = dict(judgment_injection=judgment_injection(op, profile_name, params.get('injection', 'on')))
    scale = params.get('scale_factor', 1)
    blocks['seller'] = dict(seller_policy=seller_policy(params.get('seller_role', 'cheater'), scale,
                                                        params.get('honest_top_up_policy',
                                                                   'after_each_deduction_to_scale')))
    buyer = {}
    if not unresolved & {'Lambda_cheater', 'finite_attack_cheat_sales', 'scale_factor'}:
        buyer['workload'] = workload(role, params, profile, r['effective_hold_period_blocks'])
    kappa = params.get('keeper_delay_budget_blocks', 0)
    if _number(kappa):
        buyer['clock'] = clock(kappa)
    blocks['buyer'] = buyer
    harness = None
    assignable = params.get('assignable_verifiers', profile['parameters']['minVerifiers'])
    if 'assignable_verifiers' not in unresolved and isinstance(scale, int) and not isinstance(scale, bool):
        registered = max(assignable, profile['parameters']['minVerifiers'])
        purchases = expected_purchases(role, params, profile, buyer['workload']['end']) if 'workload' in buyer else None
        harness = prof.harness(profile, scale, assignable, _spare_verifiers(profile, role, registered), purchases)
        reasons.extend(prof.harness_violations(profile, harness))
        if role == 'finite' and harness['cheatBody'] is not True:
            reasons.append('a finite-attack cell needs cheatBody in the harness block')
    return blocks, harness, reasons


def _plan_scenario(sc, arm_choice, own_arm, base_profile, overrides, base_seed, repetitions, op, op_summary,
                   metric_defs, arms):
    plan = []
    tag = '' if arm_choice == own_arm else f'-{arm_choice}'
    processes = scn.fault_processes(sc)
    fault = sc['injected_fault']
    mechanisms = scn.FAULT_KINDS[fault['kind']]
    for index, point in enumerate(scn.sweep_points(sc)):
        if tag:
            point = dict(point, arm=arm_choice)
        cell = scn.cell_of(sc, point)
        if cell is not None and cell.get('profile', scn.DEFAULT_CELL_PROFILE) != base_profile['name']:
            continue
        r = scn.resolve(sc, point, base_profile, overrides, op)
        n_seeds = repetitions or scn.point_repetitions(sc, point)
        for rep in range(n_seeds):
            seed = scn.run_seed(base_seed, sc['id'] + tag, index, rep)
            actions = []
            if 'restart' in mechanisms:
                trigger = fault['trigger']
                if trigger in r['parameters']:
                    trigger = r['parameters'][trigger]
                    if trigger == 'uniform_random':
                        choices = sc['parameters'][fault['trigger']]['sweep']
                        trigger = choices[seed % len(choices)]
                delay = next((v for k, v in r['parameters'].items() if k.endswith('restart_delay')), 0)
                actions.append(dict(action='kill_restart', process=processes[0], trigger=trigger,
                                    delay_blocks=delay))
            if 'proxy' in mechanisms:
                mode = 'delay' if fault['kind'] == 'delay_response' else 'drop'
                action = dict(action='proxy', mode=mode)
                if mode == 'delay':
                    action['delay_blocks'] = r['parameters']['response_delay_blocks']
                actions.append(action)
            # Controller-side faults (restart, proxy) are not described to the process; it only
            # receives the sweep values it needs, such as retry counts or local retention.
            hidden = {fault.get('trigger'), 'response_delay_blocks'} if 'directive' not in mechanisms else set()
            given = {k: v for k, v in r['directive'].items() if k not in hidden}
            kind = fault['kind'] if 'directive' in mechanisms else None
            directives = {p: dict(kind=kind, parameters=given) for p in processes}
            # The buyer always receives the seed effects, faulted or not.
            directives.setdefault('buyer', dict(kind=None, parameters={}))
            directives['buyer'] = dict(directives['buyer'], randomness=SEED_EFFECTS)
            # The worst-path directives go to every process that acts on the case (verifier,
            # seller, keeper, buyer), faulted or not.
            if r['parameters'].get('judgment_path') == 'worst':
                for proc, block in worstpath.directives(r['profile']).items():
                    directives.setdefault(proc, dict(kind=None, parameters={}))
                    directives[proc] = dict(directives[proc], worst_path=block)
            # A keeper delay is a per-case budget: the keeper spends all of it on the last keeper
            # call before the confirmed failure of each case and makes every other call promptly.
            # The block goes to the keeper on the worst path and whenever the budget is positive;
            # a normal-path keeper with no budget receives none.
            budget = r['parameters'].get('keeper_delay_budget_blocks')
            path = r['parameters'].get('judgment_path', 'normal')
            if isinstance(budget, (int, float)) and not isinstance(budget, bool) and (path == 'worst' or budget > 0):
                directives.setdefault('keeper', dict(kind=None, parameters={}))
                directives['keeper'] = dict(directives['keeper'],
                                            keeper_delay=dict(worstpath.keeper_delay(budget), path=path))
            # A finite attack goes to the seller only: it cheats on its first m sales, then serves
            # honestly, stops selling, or stops selling and exits.
            cheat = r['parameters'].get('finite_attack_cheat_sales')
            finite = None
            if isinstance(cheat, int) and not isinstance(cheat, bool) and cheat >= 1 \
                    and 'finite_attack_cheat_sales' not in r['unresolved'] \
                    and 'finite_attack_after' not in r['unresolved']:
                finite = finiteattack.directive(cheat, r['parameters'].get('finite_attack_after', 'serve_honestly'))
                directives.setdefault('seller', dict(kind=None, parameters={}))
                directives['seller'] = dict(directives['seller'], finite_attack=finite)
            reasons = list(r['blocked'])
            harness = None
            role = cell.get('role', 'cheater') if cell is not None else 'cheater'
            run_profile, profile_overrides = r['profile'], r['profile_overrides']
            if fault['kind'] in HARNESS_KINDS:
                blocks, harness, harness_reasons = harness_plan(r, role, op, base_profile['name'])
                reasons.extend(harness_reasons)
                run_profile, profile_overrides = harness_predicate(run_profile, profile_overrides)
                for proc, extra in blocks.items():
                    if extra:
                        directives.setdefault(proc, dict(kind=None, parameters={}))
                        directives[proc] = dict(directives[proc], **extra)
            baseline = None
            arm = str(r['parameters'].get('arm', 'fairbind'))
            if r['parameters'].get('bond_regime') == 'full_collateral':
                arm = 'B4'
            if arm.lower() != 'fairbind':
                if arm in arms:
                    baseline = bl.resolve(arms[arm], op, base_profile['name'])
                else:
                    reasons.append(f'arm {arm} has no config in experiments/baselines')
            if r['unresolved']:
                reasons.append('unresolved parameters: ' + ', '.join(r['unresolved']))
            plan.append(dict(
                run_id=f"{sc['id']}{tag}-p{index:02d}-r{rep}", scenario=sc['id'], arm=arm_choice, scenario_sha256=sc['_sha256'],
                point_index=index, repetition=rep, n_seeds=n_seeds, seed=seed, parameters=r['parameters'],
                parameter_expressions=r['parameter_expressions'],
                judgment_delay_blocks=r['judgment_delay_blocks'], profile_overrides=profile_overrides,
                fault=dict(kind=fault['kind'], processes=processes, mechanisms=list(mechanisms)),
                controller_actions=actions, directives=directives, metrics=scn.metric_names(sc),
                unresolved=r['unresolved'], inadmissible_profile=r['inadmissible'], blocked_reasons=reasons,
                runnable=not reasons, notes=r['notes'] + _seed_notes(sc['id'], base_seed), override_used=r['override_used'],
                override_skipped_checks=r['override_skipped_checks'],
                requested_D_holding_blocks=r['requested_D_holding_blocks'],
                effective_hold_period_blocks=r['effective_hold_period_blocks'],
                operating_point=op_summary, metric_definitions=metric_defs, baseline=baseline,
                cell=None if cell is None else dict(name=cell['name'], rate_class=cell.get('rate_class'),
                                                    role=cell.get('role', 'cheater'),
                                                    repetitions=cell['repetitions'],
                                                    min_repetitions=cell.get('min_repetitions')),
                judgment_path=r['parameters'].get('judgment_path', 'normal'),
                finite_attack=finite, harness=harness, operating_point_k=op_summary['k'], base_seed=base_seed,
                worst_path_schedule=(worstpath.schedule(r['profile'])
                                     if r['parameters'].get('judgment_path') == 'worst' else None),
                _profile=run_profile, _scenario=sc))
    return plan


# The decimal-median data predicate the local verifiers judge with their data pipeline over the
# replay fixtures (runtime/verifier ExperimentalDataPredicate, scripts/local_setup.py). The local
# profile's normative DATA_API_REFERENCE_V1 has no pipeline and is judged INCONCLUSIVE, so no bad
# response would ever be detected on the normal path.
EXPERIMENTAL_DATA_PREDICATE = '0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7'
DATA_API_CLASS = 1


def harness_predicate(profile, overrides):
    """The profile and profile overrides of a hold-period harness run: a data API profile is judged
    under the experimental data predicate (recorded as a predicateId override); other profiles are
    returned unchanged."""
    params = profile['parameters']
    if params.get('classId') != DATA_API_CLASS or params.get('predicateId') == EXPERIMENTAL_DATA_PREDICATE:
        return profile, overrides
    return (dict(profile, parameters=dict(params, predicateId=EXPERIMENTAL_DATA_PREDICATE)),
            dict(overrides, predicateId=EXPERIMENTAL_DATA_PREDICATE))


def _seed_notes(scenario_id, base_seed):
    want = PLAN_BASE_SEEDS.get(scenario_id)
    if want is None or want == base_seed:
        return []
    return [f'base seed {base_seed} differs from the experiment plan base seed {want} of {scenario_id} '
            f'(start the controller with --seed {want})']


def envelope_fields(entry):
    """Plan fields the result envelope carries beside the operating point: k with its source, the
    deploy harness block (None outside the hold-period harness) and the smoke overrides (None for a
    planned run)."""
    return dict(operating_point_k=entry['operating_point_k'], harness=entry['harness'], base_seed=entry['base_seed'],
                smoke=entry.get('smoke'))


# Smoke overrides (--smoke KEY=VALUE): shorten a hold-period harness run for an integration test by
# changing the buyer driver's workload block only. A smoke run is never a planned run: its run id
# ends in SMOKE_SUFFIX, its envelope records `smoke` and is never reportable, and the analysis must
# not read it. Keys: rate_per_block (purchases per block), and the count of the end rule:
# episodes, honest_windows, worst_path_cases.
SMOKE_SUFFIX = '-smoke'
SMOKE_KEYS = {'rate_per_block': float, 'episodes': int, 'honest_windows': int, 'worst_path_cases': int}
SMOKE_END_FIELDS = {'episodes': ('episodes', 'count'), 'honest_windows': ('honest_windows', 'windows'),
                    'worst_path_cases': ('worst_path_cases', 'count')}


def parse_smoke(items):
    """{key: value} of --smoke KEY=VALUE items; values must be positive."""
    out = {}
    for item in items:
        key, sep, raw = str(item).partition('=')
        if not sep or key not in SMOKE_KEYS:
            raise ValueError(f'--smoke expects one of {sorted(SMOKE_KEYS)}=VALUE, got {item!r}')
        try:
            value = SMOKE_KEYS[key](raw)
        except ValueError:
            raise ValueError(f'--smoke {key}: {raw!r} is not a {SMOKE_KEYS[key].__name__}') from None
        if not value > 0 or value != value or value == float('inf'):
            raise ValueError(f'--smoke {key} must be positive')
        out[key] = value
    return out


def apply_smoke(plan, smoke):
    """Plan entries with the smoke overrides applied to the buyer workload block. An end-rule count
    applies to the entries with that end rule; an override that applies to no entry is an error."""
    if not smoke:
        return plan
    used = set()
    out = []
    for entry in plan:
        buyer = (entry.get('directives') or {}).get('buyer') or {}
        if 'workload' not in buyer:
            raise ValueError(f"--smoke: {entry['run_id']} has no workload block")
        workload = json.loads(json.dumps(buyer['workload']))
        applied = {}
        if 'rate_per_block' in smoke:
            workload['rate_per_block'] = applied['rate_per_block'] = smoke['rate_per_block']
        for key, (rule, field) in SMOKE_END_FIELDS.items():
            if key in smoke and workload['end']['rule'] == rule:
                workload['end'][field] = applied[key] = smoke[key]
        used |= set(applied)
        e = dict(entry, run_id=entry['run_id'] + SMOKE_SUFFIX, smoke=applied,
                 directives=dict(entry['directives'], buyer=dict(buyer, workload=workload)))
        if entry.get('harness') is not None:
            params = dict(entry['parameters'], Lambda_cheater=workload['rate_per_block'])
            e['harness'] = dict(entry['harness'], buyerPurchases=expected_purchases(
                (entry.get('cell') or {}).get('role'), params, entry['_profile'], workload['end']))
        out.append(e)
    unused = sorted(set(smoke) - used)
    if unused:
        raise ValueError(f'--smoke {", ".join(unused)} applies to no selected run')
    return out


def public_plan(plan):
    return [{k: v for k, v in entry.items() if not k.startswith('_')} for entry in plan]


def _loopback_http(url):
    u = urllib.parse.urlsplit(url)
    try:
        return u.scheme == 'http' and ipaddress.ip_address(u.hostname).is_loopback
    except (TypeError, ValueError):
        return False


def load_manifest(path):
    with open(path, encoding='utf-8') as f:
        m = json.load(f)
    errors = validate_manifest(m)
    if errors:
        raise ValueError(f'{path}: ' + '; '.join(errors))
    return m


def _placeholders(text):
    return {field for _, field, _, _ in string.Formatter().parse(text) if field is not None}


def validate_manifest(m):
    errors = []
    if not isinstance(m, dict) or m.get('formatVersion') != 1:
        return ['formatVersion must be 1']
    allowed = {'formatVersion', 'rpcUrl', 'processes', 'deploy', 'collector', 'proxy', 'stopTimeoutSeconds',
               'runTimeoutSeconds', 'readyTimeoutSeconds'}
    if set(m) - allowed:
        errors.append(f'unknown fields {sorted(set(m) - allowed)}')
    rpc = m.get('rpcUrl', '')
    if not isinstance(rpc, str) or not _loopback_http(rpc):
        errors.append('rpcUrl must be literal loopback HTTP')
    elif _placeholders(rpc) - PORT_PLACEHOLDERS:
        errors.append(f'rpcUrl may use only {sorted(PORT_PLACEHOLDERS)}')
    procs = m.get('processes')
    if not isinstance(procs, dict) or set(procs) != set(LAUNCH_ORDER):
        errors.append(f'processes must define exactly {LAUNCH_ORDER}')
        procs = {}
    commands = [(f'processes.{n}', p) for n, p in procs.items()]
    commands += [(k, m[k]) for k in ('deploy', 'collector') if k in m]
    for name, spec in commands:
        if not isinstance(spec, dict) or not isinstance(spec.get('command'), list) or not spec['command'] \
                or not all(isinstance(a, str) for a in spec['command']):
            errors.append(f'{name}.command must be a non-empty list of strings')
            continue
        if set(spec) - {'command', 'env', 'ready'}:
            errors.append(f'{name} has unknown fields')
        allowed_fields = PLACEHOLDERS | (COLLECTOR_PLACEHOLDERS if name == 'collector' else set())
        for arg in spec['command'] + list((spec.get('env') or {}).values()):
            try:
                fields = _placeholders(arg)
            except ValueError:
                errors.append(f'{name}: malformed placeholder in {arg!r}')
                continue
            for field in sorted(fields - allowed_fields):
                where = ' (collector only)' if field in COLLECTOR_PLACEHOLDERS else ''
                errors.append(f'{name}: unknown placeholder {{{field}}}{where}')
        ready = spec.get('ready')
        if ready is not None and not (ready == 'rpc' or (isinstance(ready, dict) and set(ready) <= {'file', 'seconds'}
                                                             and len(ready) == 1)):
            errors.append(f'{name}.ready must be "rpc", {{"file": path}} or {{"seconds": n}}')
    proxy = m.get('proxy')
    if proxy is not None:
        if not isinstance(proxy, dict) or set(proxy) != {'listen', 'upstream'} or \
                not _loopback_http('http://' + str(proxy.get('listen'))) or not _loopback_http(proxy.get('upstream', '')):
            errors.append('proxy needs loopback listen host:port and loopback http upstream')
        elif (_placeholders(proxy['listen']) | _placeholders(proxy['upstream'])) - PORT_PLACEHOLDERS:
            errors.append(f'proxy may use only {sorted(PORT_PLACEHOLDERS)}')
    return errors


def ports(port_base):
    """Loopback ports of one run from its port base P: Anvil at P, the service listeners from P + 10
    (the deploy step's FAIRBIND_BASE_PORT: facilitator, seller, buyer, second buyer) and the proxy at
    P + 80. Parallel shards take port bases at least 100 apart."""
    p = int(port_base)
    if not 1024 <= p <= 65535 - 100:
        raise ValueError(f'port base {p} must lie in 1024..{65535 - 100}')
    return dict(rpc_port=str(p), base_port=str(p + 10), seller_port=str(p + 11), proxy_port=str(p + 80))


def _env_reference(arg):
    """The environment variable an argument names when it is exactly $NAME, else None."""
    match = ENV_REFERENCE.fullmatch(arg)
    return None if match is None else match.group(1)


def manifest_env(manifest):
    """Environment variables the manifest names as whole arguments ($NAME), in order."""
    specs = list(manifest.get('processes', {}).values()) + [manifest[k] for k in ('deploy', 'collector')
                                                             if k in manifest]
    names = []
    for spec in specs:
        for arg in spec['command'] + list((spec.get('env') or {}).values()):
            name = _env_reference(arg)
            if name and name not in names:
                names.append(name)
    return names


def missing_env(manifest, environ=None):
    environ = os.environ if environ is None else environ
    return [n for n in manifest_env(manifest) if not environ.get(n)]


def _expand(arg, environ):
    name = _env_reference(arg)
    if name is None:
        return arg
    if not environ.get(name):
        raise ValueError(f'the manifest names ${name}, which is not set in the environment')
    return environ[name]


def result_path(output, run_id):
    return Path(output).resolve() / 'results' / f'{run_id}.json'


def select_cells(plan, cells):
    """Plan entries of the named I6 cells; an unknown name is an error."""
    if not cells:
        return plan
    known = {e['cell']['name'] for e in plan if e.get('cell')}
    unknown = sorted(set(cells) - known)
    if unknown:
        raise ValueError(f'unknown cells: {unknown}')
    return [e for e in plan if e.get('cell') and e['cell']['name'] in cells]


def select_runs(plan, run_ids):
    """Plan entries with the named run ids, in plan order; an unknown id is an error."""
    if not run_ids:
        return plan
    known = {e['run_id'] for e in plan}
    unknown = sorted(set(run_ids) - known)
    if unknown:
        raise ValueError(f'unknown run ids: {unknown}')
    return [e for e in plan if e['run_id'] in run_ids]


def parse_shard(text):
    """'K/N' with 0 <= K < N."""
    k, sep, n = str(text).partition('/')
    try:
        k, n = int(k), int(n)
    except ValueError:
        raise ValueError(f'--shard expects K/N, got {text!r}') from None
    if not sep or n < 1 or not 0 <= k < n:
        raise ValueError(f'--shard expects K/N with 0 <= K < N, got {text!r}')
    return k, n


def shard_of(run_id, n):
    """Shard of a run: SHA-256 of its run id modulo n. It depends on the run id only, so a shard
    keeps its runs when the plan is filtered or reordered."""
    return int.from_bytes(hashlib.sha256(run_id.encode()).digest()[:8], 'big') % n


def shard(plan, k, n):
    return [e for e in plan if shard_of(e['run_id'], n) == k]


def bad_sales_rule(entry):
    """Which settled sales of the observed seller are bad, for the collector's ground truth:
    `first_m` for a finite attacker (its first m sales), `none` for an honest seller, and
    `all_cheater_episode_sales` for a cheater (every sale in every episode). None outside the
    hold-period harness and the finite attack."""
    finite = entry.get('finite_attack')
    if finite:
        return dict(rule='first_m', m=finite['cheat_sales'])
    policy = (entry['directives'].get('seller') or {}).get('seller_policy')
    if policy is None:
        return None
    if policy['role'] == 'honest':
        return dict(rule='none', m=None)
    if policy['role'] == 'finite':
        raise ValueError(f"{entry['run_id']}: a finite seller policy without a finite_attack block")
    return dict(rule='all_cheater_episode_sales', m=None)


def source_state():
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    try:
        revision, dirty = git('rev-parse', 'HEAD'), bool(git('status', '--porcelain'))
    except (OSError, subprocess.CalledProcessError):
        revision, dirty = None, True
    lock = json.loads((ROOT / 'UPSTREAMS.lock.json').read_text())
    upstreams = [dict(name=u['name'], revision=u['revision']) for u in lock.get('upstreams', [])]
    return dict(revision=revision, dirty=dirty, upstreams=upstreams)


class Process:
    def __init__(self, name, command, env, cwd, log_path):
        self.name, self.command, self.env, self.cwd, self.log_path = name, command, env, cwd, log_path
        self.proc, self.starts, self.lock = None, 0, threading.Lock()

    def start(self):
        with self.lock:
            log = open(self.log_path, 'ab')
            self.proc = subprocess.Popen(self.command, env=self.env, cwd=self.cwd, stdout=log, stderr=subprocess.STDOUT,
                                         start_new_session=True)
            log.close()
            self.starts += 1

    def kill(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()

    def stop(self, timeout):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()

    def exit_code(self):
        return None if self.proc is None else self.proc.poll()


def _fill(values, args, environ):
    return [_expand(a.format_map(values), environ) for a in args]


def _wait_ready(spec, values, rpc_url, timeout, block_source):
    ready = spec.get('ready')
    deadline = time.monotonic() + timeout
    if ready is None:
        return
    if isinstance(ready, dict) and 'seconds' in ready:
        time.sleep(float(ready['seconds']))
        return
    while time.monotonic() < deadline:
        try:
            if ready == 'rpc':
                block_source()
                return
            if Path(ready['file'].format_map(values)).exists():
                return
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.2)
    raise TimeoutError(f'process not ready: {ready}')


def _remove_logs(run_dir):
    for log in sorted(Path(run_dir, 'proc').glob('*/output.log')):
        log.unlink()


def rules_record(path):
    """The decision-rules file of a run list (--rules-file): its name and SHA-256, or None."""
    if path is None:
        return None
    raw = Path(path).read_bytes()
    return dict(file=Path(path).name, sha256=hashlib.sha256(raw).hexdigest())


def l_actual_min(entry):
    """The smallest measured worst-path length L_actual of the run's profile (operating point
    L_actual_blocks.min, defaulting to its value), or None when the operating point has none."""
    op = entry.get('operating_point') or {}
    try:
        doc = json.loads((ROOT / op['path']).read_text()) if not Path(op['path']).is_absolute() \
            else json.loads(Path(op['path']).read_text())
        rec = doc['profiles'][op['profile']].get('L_actual_blocks') or {}
    except (KeyError, TypeError, OSError, ValueError):
        return None
    low = rec.get('min', rec.get('value'))
    return low if isinstance(low, int) and not isinstance(low, bool) else None


def execute(entry, manifest, output, *, block_source=None, now=faults.now, port_base=DEFAULT_PORT_BASE,
            keep_logs='all', resume=False, allow_dirty=False, rules=None):
    """Run one planned point and write its result envelope. Returns the envelope.

    Order: anvil, deploy, the services, the buyer (the workload); when the buyer exits every process
    but anvil stops, the collector runs against the live chain, and anvil stops last. `resume`
    replaces the output of a run that has no result envelope (an interrupted run); a run with an
    envelope is never overwritten. `rules` is rules_record(--rules-file): the envelope keeps it as
    decision_rules, and an I6 run without it is not reportable. `allow_dirty` (the controller's --allow-dirty) lets the deploy
    step deploy from a dirty tree (FAIRBIND_ALLOW_DIRTY=1); the envelope records the tree as dirty."""
    if keep_logs not in KEEP_LOGS:
        raise ValueError(f'keep_logs must be one of {KEEP_LOGS}')
    output = Path(output).resolve()
    run_dir = output / 'runs' / entry['run_id']
    truth_path = output / 'ground-truth' / f"{entry['run_id']}.json"
    results = result_path(output, entry['run_id'])
    if results.exists():
        raise FileExistsError(f'{entry["run_id"]} already has a result envelope; choose a new directory')
    if run_dir.exists():
        if not resume:
            raise FileExistsError(f'{entry["run_id"]} already has output; choose a new directory')
        shutil.rmtree(run_dir)
    port_values = ports(port_base)
    environ = dict(os.environ)
    shared = run_dir / 'shared'
    observations = run_dir / 'observations'
    for d in (shared, observations):
        d.mkdir(parents=True)
    profile_path = shared / 'profile.json'
    # admissionOverride tells the deploy step to use the test build whose registry skips the
    # hold-period admission checks (contracts/test/AdmissionOverrideRegistry.sol); harness is the
    # deploy block of the hold-period harness (bond scale, verifier counts and bonds, spares).
    profile_doc = dict(formatVersion=1, derivedFromScenario=entry['scenario'],
                       admissionOverride=bool(entry['override_used']), profiles=[entry['_profile']])
    if entry.get('harness') is not None:
        profile_doc['harness'] = entry['harness']
    profile_path.write_text(json.dumps(profile_doc, indent=2))
    sc = entry['_scenario']
    bad = bad_sales_rule(entry)
    truth = faults.GroundTruth(truth_path, dict(
        run_id=entry['run_id'], scenario=entry['scenario'], injected_fault=sc['injected_fault'],
        parameters=entry['parameters'], expected_outcome=sc['expected_outcome'],
        expected_verdict=faults.expected_verdict(entry['fault']['kind'], entry['parameters']),
        cell=(entry.get('cell') or {}).get('name'), bad_sales_rule=bad and bad['rule'],
        bad_sales_m=bad and bad['m']))
    rpc_url = manifest['rpcUrl'].format_map(port_values)
    block_source = block_source or faults.rpc_block_source(rpc_url)
    seller_url = ''
    proxy = None
    started_at = now()
    status, error, ended_by = 'completed', None, 'workload_exit'
    procs = {}
    restarts = []
    stop_timeout = float(manifest.get('stopTimeoutSeconds', 10))

    def values_for(name):
        proc_dir = run_dir / 'proc' / name
        return dict(port_values, proc_dir=str(proc_dir), directive=str(proc_dir / 'directive.json'),
                    profile=str(profile_path), seed=str(entry['seed']), rpc_url=rpc_url,
                    observations=str(observations / f'{name}.jsonl'), seller_url=seller_url, repo=str(ROOT),
                    events=str(proc_dir / 'events.jsonl'), run_dir=str(run_dir))

    def make(name, spec):
        values = values_for(name)
        if name == 'collector':
            values['ground_truth'] = str(truth_path)
        Path(values['proc_dir']).mkdir(parents=True, exist_ok=True)
        directive = entry['directives'].get(name, dict(kind=None, parameters={}))
        Path(values['directive']).write_text(json.dumps(dict(seed=entry['seed'], **directive), indent=2))
        env = dict(environ, FAIRBIND_PROC_DIR=values['proc_dir'], FAIRBIND_DIRECTIVE=values['directive'],
                   FAIRBIND_PROFILE=values['profile'], FAIRBIND_SEED=values['seed'], FAIRBIND_RPC_URL=rpc_url,
                   FAIRBIND_OBSERVATIONS=values['observations'], FAIRBIND_EVENTS=values['events'],
                   FAIRBIND_SELLER_URL=seller_url, FAIRBIND_RUN_DIR=values['run_dir'],
                   FAIRBIND_ADMISSION_OVERRIDE='1' if entry['override_used'] else '0')
        if name == 'deploy' and allow_dirty:
            env['FAIRBIND_ALLOW_DIRTY'] = '1'
        env.update({k: _expand(v.format_map(values), environ) for k, v in (spec.get('env') or {}).items()})
        return Process(name, _fill(values, spec['command'], environ), env, values['proc_dir'],
                       Path(values['proc_dir']) / 'output.log'), values

    try:
        proxy_action = next((a for a in entry['controller_actions'] if a['action'] == 'proxy'), None)
        if 'proxy' in manifest:
            proxy = faults.ResponseProxy(manifest['proxy']['listen'].format_map(port_values),
                                         manifest['proxy']['upstream'].format_map(port_values),
                                         mode=proxy_action['mode'] if proxy_action else 'pass',
                                         delay_blocks=(proxy_action or {}).get('delay_blocks', 0),
                                         block_source=block_source, truth=truth).start()
            seller_url = proxy.address
        elif proxy_action:
            raise ValueError('this scenario needs a proxy entry in the manifest')

        ready_timeout = float(manifest.get('readyTimeoutSeconds', 60))
        for name in LAUNCH_ORDER:
            spec = manifest['processes'][name]
            procs[name], values = make(name, spec)
            procs[name].start()
            truth.event('process_started', process=name)
            _wait_ready(spec, values, rpc_url, ready_timeout, block_source)
            if name == 'anvil' and 'deploy' in manifest:
                deploy, _ = make('deploy', manifest['deploy'])
                deploy.start()
                code = deploy.proc.wait()
                if code != 0:
                    ended_by = 'deploy_failure'
                    raise RuntimeError(f'deploy command exited with {code}')
                truth.event('deployed')
        restarted = set()
        for action in entry['controller_actions']:
            if action['action'] == 'kill_restart':
                target = procs[action['process']]
                inj = faults.RestartInjector(values_for(action['process'])['events'], action['trigger'], target.kill,
                                             target.start, action['delay_blocks'], block_source, truth)
                inj.start()
                restarts.append(inj)
                restarted.add(action['process'])
        limit = float(manifest.get('runTimeoutSeconds', 3600))
        deadline = time.monotonic() + limit
        # The run ends when the buyer exits, when any other process exits (a process the controller
        # restarts is exempt), or at the wall-clock limit.
        while procs['buyer'].exit_code() is None:
            dead = next((n for n in LAUNCH_ORDER[:-1] if n not in restarted and procs[n].exit_code() is not None),
                        None)
            if dead is not None:
                status, ended_by = 'failed', 'process_exit'
                error = f'{dead} exited with {procs[dead].exit_code()} before the workload finished'
                break
            if time.monotonic() > deadline:
                status, ended_by = 'timeout', 'wall_clock_limit'
                error = f'wall-clock limit of {limit:g} s reached before the workload finished'
                break
            time.sleep(0.2)
        truth.event('workload_finished', buyer_exit=procs['buyer'].exit_code(), ended_by=ended_by)
        if status == 'completed' and procs['buyer'].exit_code() != 0:
            status, error = 'failed', f"buyer exited with {procs['buyer'].exit_code()}"
    except Exception as exc:
        status, error = 'failed', repr(exc)
        if ended_by == 'workload_exit':
            ended_by = 'controller_error'
    finally:
        for inj in restarts:
            inj.stop.set()
        # Every process but anvil stops first, so the chain is final and still readable.
        for name in reversed(LAUNCH_ORDER[1:]):
            if name in procs:
                procs[name].stop(stop_timeout)
        if proxy:
            proxy.close()
    collector = None
    try:
        if status == 'completed' and 'collector' in manifest:
            if 'anvil' in procs and procs['anvil'].exit_code() is not None:
                status, error = 'failed', f"anvil exited with {procs['anvil'].exit_code()} before the collector ran"
            else:
                truth.event('collector_started')
                truth.write()
                collector, _ = make('collector', manifest['collector'])
                collector.start()
                code = collector.proc.wait()
                if code != 0:
                    status, error = 'failed', f'collector exited with {code}'
    except Exception as exc:
        status, error = 'failed', f'collector: {exc!r}'
    finally:
        if 'anvil' in procs:
            procs['anvil'].stop(stop_timeout)
    finished_at = now()
    truth.write()
    metrics, missing, bad_rows = collect_metrics(observations, entry['metrics'])
    if bad_rows:
        status, error = 'failed', error or f'invalid observation rows: {bad_rows[:3]}'
    logs_kept = keep_logs == 'all' or (keep_logs == 'failed' and status != 'completed')
    if not logs_kept:
        _remove_logs(run_dir)
    src = source_state()
    processes = {n: dict(command=p.command, starts=p.starts, exit_code=p.exit_code()) for n, p in procs.items()}
    if collector is not None:
        processes['collector'] = dict(command=collector.command, starts=collector.starts,
                                      exit_code=collector.exit_code())
    envelope = dict(
        formatVersion=1, kind='fairbind-scenario-run', run_id=entry['run_id'], scenario=entry['scenario'],
        scenario_sha256=entry['scenario_sha256'], method=str(entry['parameters'].get('arm', 'fairbind')).lower(),
        revision=src['revision'], dirty=src['dirty'],
        reportable=(not src['dirty'] and status == 'completed' and not entry.get('smoke')
                    and (rules is not None or entry['scenario'] != 'I6')),
        decision_rules=rules, l_actual_min_blocks=l_actual_min(entry),
        upstreams=src['upstreams'], parameters=entry['parameters'], profile_overrides=entry['profile_overrides'],
        judgment_delay_blocks=entry['judgment_delay_blocks'], inadmissible_profile=entry['inadmissible_profile'],
        override_used=entry['override_used'], override_skipped_checks=entry['override_skipped_checks'],
        requested_D_holding_blocks=entry['requested_D_holding_blocks'],
        effective_hold_period_blocks=entry['effective_hold_period_blocks'],
        operating_point=entry['operating_point'], metric_definitions=entry['metric_definitions'],
        seed=entry['seed'], cell=entry.get('cell'),
        randomness=dict(seed=entry['seed'], repetition=entry['repetition'], n_seeds=entry['n_seeds'],
                        seed_changes=SEED_EFFECTS, otherwise_deterministic=True),
        detection=detection_summary(entry['_profile'], metrics), created_at=now(), started_at=started_at, finished_at=finished_at, status=status,
        error=error, ended_by=ended_by, fault=entry['fault'], controller_actions=entry['controller_actions'],
        restart_errors=[i.error for i in restarts if i.error],
        execution=dict(port_base=int(port_base), ports={k: int(v) for k, v in port_values.items()},
                       rpc_url=rpc_url, keep_logs=keep_logs, logs_kept=logs_kept),
        processes=processes, metrics=metrics, missing_metrics=missing,
        ground_truth=dict(path=str(truth_path), sha256=hashlib.sha256(truth_path.read_bytes()).hexdigest()),
        **envelope_fields(entry))
    results.parent.mkdir(parents=True, exist_ok=True)
    tmp = results.with_suffix('.tmp')
    tmp.write_text(json.dumps(envelope, indent=2, sort_keys=True))
    tmp.replace(results)
    return envelope


def detection_summary(profile, metrics):
    """Expected detection and sampling probabilities of the run's profile beside the realized rates.

    A realized rate is the mean of its observations, or None when the run reported none.
    """
    p = profile['parameters']

    def realized(name):
        rows = (metrics.get(name) or {}).get('observations') or []
        values = [r['value'] for r in rows if isinstance(r['value'], (int, float))]
        return sum(values) / len(values) if values else None
    return dict(expected_p=p['effectivePpm'] / 1_000_000, expected_pi=p['samplePpm'] / 1_000_000,
                realized_detection_rate=realized('realized_detection_rate'),
                realized_sample_rate=realized('realized_sample_rate'))


def collect_metrics(directory, names):
    """Read observation rows {"metric", "value", "observation_id"?} from *.jsonl.

    A metric without rows is reported as missing, never as zero.
    """
    values = {n: [] for n in names}
    bad = []
    for path in sorted(Path(directory).glob('*.jsonl')):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                v = row['value']
                if row['metric'] not in values:
                    continue
                if isinstance(v, bool) or not isinstance(v, (int, float, list)):
                    raise ValueError('value')
                values[row['metric']].append(dict(value=v, observation_id=row.get('observation_id'),
                                                  source=path.stem))
            except (ValueError, KeyError, TypeError):
                bad.append(f'{path.name}:{number}')
    metrics = {n: dict(observed=bool(v), count=len(v), observations=v) for n, v in values.items()}
    return metrics, [n for n, v in values.items() if not v], bad


def utc_stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
