"""Plan and execute scenario runs against a six-process deployment."""
import datetime
import hashlib
import ipaddress
import json
import os
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
from . import scenario as scn
from . import finiteattack
from . import worstpath

ROOT = Path(__file__).resolve().parents[2]
LAUNCH_ORDER = ('anvil', 'keeper', 'verifier', 'facilitator', 'seller', 'buyer')
PLACEHOLDERS = {'proc_dir', 'directive', 'profile', 'seed', 'rpc_url', 'observations', 'seller_url', 'repo', 'events'}


# What a run seed changes. The harness is otherwise deterministic: the same workload on the same
# chain produces the same nonces and block hashes, and so the same sample draws. The seed changes
# exactly these two inputs, which changes the nonce of every purchase and the block hashes that
# become epoch randomness, and therefore which purchases are sampled. The buyer driver reads this
# block from its directive; nothing else (fault timing, verdict timing, rates) depends on the seed.
SEED_EFFECTS = {
    'buyer_idempotency_key': 'k of purchase i = first 16 bytes of SHA-256("fairbind/seed/k" || seed || i)',
    'intra_block_order': ('the buyer submits the settlements of one block in the order of a permutation drawn '
                          'from SHA-256("fairbind/seed/order" || seed || block number)'),
}


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
    op_summary = opt.summary(op, base_profile['name'])
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
            budget = r['parameters'].get('keeper_delay_budget_blocks')
            if isinstance(budget, (int, float)) and not isinstance(budget, bool):
                directives.setdefault('keeper', dict(kind=None, parameters={}))
                directives['keeper'] = dict(directives['keeper'], keeper_delay=worstpath.keeper_delay(budget))
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
                judgment_delay_blocks=r['judgment_delay_blocks'], profile_overrides=r['profile_overrides'],
                fault=dict(kind=fault['kind'], processes=processes, mechanisms=list(mechanisms)),
                controller_actions=actions, directives=directives, metrics=scn.metric_names(sc),
                unresolved=r['unresolved'], inadmissible_profile=r['inadmissible'], blocked_reasons=reasons,
                runnable=not reasons, notes=r['notes'], override_used=r['override_used'],
                override_skipped_checks=r['override_skipped_checks'],
                requested_D_holding_blocks=r['requested_D_holding_blocks'],
                effective_hold_period_blocks=r['effective_hold_period_blocks'],
                operating_point=op_summary, metric_definitions=metric_defs, baseline=baseline,
                cell=None if cell is None else dict(name=cell['name'], rate_class=cell.get('rate_class'),
                                                    role=cell.get('role', 'cheater'),
                                                    repetitions=cell['repetitions'],
                                                    min_repetitions=cell.get('min_repetitions')),
                judgment_path=r['parameters'].get('judgment_path', 'normal'),
                finite_attack=finite,
                worst_path_schedule=(worstpath.schedule(r['profile'])
                                     if r['parameters'].get('judgment_path') == 'worst' else None),
                _profile=r['profile'], _scenario=sc))
    return plan


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


def validate_manifest(m):
    errors = []
    if not isinstance(m, dict) or m.get('formatVersion') != 1:
        return ['formatVersion must be 1']
    allowed = {'formatVersion', 'rpcUrl', 'processes', 'deploy', 'collector', 'proxy', 'stopTimeoutSeconds',
               'runTimeoutSeconds', 'readyTimeoutSeconds'}
    if set(m) - allowed:
        errors.append(f'unknown fields {sorted(set(m) - allowed)}')
    if not _loopback_http(m.get('rpcUrl', '')):
        errors.append('rpcUrl must be literal loopback HTTP')
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
        for arg in spec['command'] + list((spec.get('env') or {}).values()):
            for _, field, _, _ in string.Formatter().parse(arg):
                if field is not None and field not in PLACEHOLDERS:
                    errors.append(f'{name}: unknown placeholder {{{field}}}')
        ready = spec.get('ready')
        if ready is not None and not (ready == 'rpc' or (isinstance(ready, dict) and set(ready) <= {'file', 'seconds'}
                                                             and len(ready) == 1)):
            errors.append(f'{name}.ready must be "rpc", {{"file": path}} or {{"seconds": n}}')
    proxy = m.get('proxy')
    if proxy is not None:
        if not isinstance(proxy, dict) or set(proxy) != {'listen', 'upstream'} or \
                not _loopback_http('http://' + str(proxy.get('listen'))) or not _loopback_http(proxy.get('upstream', '')):
            errors.append('proxy needs loopback listen host:port and loopback http upstream')
    return errors


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


def _fill(values, args):
    return [a.format_map(values) for a in args]


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


def execute(entry, manifest, output, *, block_source=None, now=faults.now):
    """Run one planned point and write its result envelope. Returns the envelope."""
    output = Path(output).resolve()
    run_dir = output / 'runs' / entry['run_id']
    truth_path = output / 'ground-truth' / f"{entry['run_id']}.json"
    results = output / 'results' / f"{entry['run_id']}.json"
    if run_dir.exists() or results.exists():
        raise FileExistsError(f'{entry["run_id"]} already has output; choose a new directory')
    shared = run_dir / 'shared'
    observations = run_dir / 'observations'
    for d in (shared, observations):
        d.mkdir(parents=True)
    profile_path = shared / 'profile.json'
    # admissionOverride tells the deploy step to use the test build whose registry skips the
    # hold-period admission checks (contracts/test/AdmissionOverrideRegistry.sol).
    profile_path.write_text(json.dumps(dict(formatVersion=1, derivedFromScenario=entry['scenario'],
                                            admissionOverride=bool(entry['override_used']),
                                            profiles=[entry['_profile']]), indent=2))
    sc = entry['_scenario']
    truth = faults.GroundTruth(truth_path, dict(
        run_id=entry['run_id'], scenario=entry['scenario'], injected_fault=sc['injected_fault'],
        parameters=entry['parameters'], expected_outcome=sc['expected_outcome'],
        expected_verdict=faults.expected_verdict(entry['fault']['kind'], entry['parameters'])))
    rpc_url = manifest['rpcUrl']
    block_source = block_source or faults.rpc_block_source(rpc_url)
    seller_url = ''
    proxy = None
    started_at = now()
    status, error = 'completed', None
    procs = {}
    restarts = []
    stop_timeout = float(manifest.get('stopTimeoutSeconds', 10))
    try:
        proxy_action = next((a for a in entry['controller_actions'] if a['action'] == 'proxy'), None)
        if 'proxy' in manifest:
            proxy = faults.ResponseProxy(manifest['proxy']['listen'], manifest['proxy']['upstream'],
                                         mode=proxy_action['mode'] if proxy_action else 'pass',
                                         delay_blocks=(proxy_action or {}).get('delay_blocks', 0),
                                         block_source=block_source, truth=truth).start()
            seller_url = proxy.address
        elif proxy_action:
            raise ValueError('this scenario needs a proxy entry in the manifest')

        def values_for(name):
            proc_dir = run_dir / 'proc' / name
            return dict(proc_dir=str(proc_dir), directive=str(proc_dir / 'directive.json'), profile=str(profile_path),
                        seed=str(entry['seed']), rpc_url=rpc_url, observations=str(observations / f'{name}.jsonl'),
                        seller_url=seller_url, repo=str(ROOT), events=str(proc_dir / 'events.jsonl'))

        def make(name, spec):
            values = values_for(name)
            Path(values['proc_dir']).mkdir(parents=True, exist_ok=True)
            directive = entry['directives'].get(name, dict(kind=None, parameters={}))
            Path(values['directive']).write_text(json.dumps(dict(seed=entry['seed'], **directive), indent=2))
            env = dict(os.environ, FAIRBIND_PROC_DIR=values['proc_dir'], FAIRBIND_DIRECTIVE=values['directive'],
                       FAIRBIND_PROFILE=values['profile'], FAIRBIND_SEED=values['seed'], FAIRBIND_RPC_URL=rpc_url,
                       FAIRBIND_OBSERVATIONS=values['observations'], FAIRBIND_EVENTS=values['events'],
                       FAIRBIND_SELLER_URL=seller_url,
                       FAIRBIND_ADMISSION_OVERRIDE='1' if entry['override_used'] else '0')
            env.update({k: v.format_map(values) for k, v in (spec.get('env') or {}).items()})
            return Process(name, _fill(values, spec['command']), env, values['proc_dir'],
                           Path(values['proc_dir']) / 'output.log'), values

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
                if deploy.proc.wait() != 0:
                    raise RuntimeError('deploy command failed')
                truth.event('deployed')
        for action in entry['controller_actions']:
            if action['action'] == 'kill_restart':
                target = procs[action['process']]
                inj = faults.RestartInjector(values_for(action['process'])['events'], action['trigger'], target.kill,
                                             target.start, action['delay_blocks'], block_source, truth)
                inj.start()
                restarts.append(inj)
        deadline = time.monotonic() + float(manifest.get('runTimeoutSeconds', 3600))
        while procs['buyer'].exit_code() is None or procs['buyer'].proc is None:
            if time.monotonic() > deadline:
                status = 'timeout'
                break
            time.sleep(0.2)
        truth.event('workload_finished', buyer_exit=procs['buyer'].exit_code())
        if status == 'completed' and procs['buyer'].exit_code() != 0:
            status, error = 'failed', f"buyer exited with {procs['buyer'].exit_code()}"
    except Exception as exc:
        status, error = 'failed', repr(exc)
    finally:
        for inj in restarts:
            inj.stop.set()
        for name in reversed(LAUNCH_ORDER):
            if name in procs:
                procs[name].stop(stop_timeout)
        if proxy:
            proxy.close()
    if status == 'completed' and 'collector' in manifest:
        collector, _ = make('collector', manifest['collector'])
        collector.start()
        if collector.proc.wait() != 0:
            status, error = 'failed', 'collector failed'
    finished_at = now()
    truth.write()
    metrics, missing, bad = collect_metrics(observations, entry['metrics'])
    if bad:
        status, error = 'failed', error or f'invalid observation rows: {bad[:3]}'
    src = source_state()
    envelope = dict(
        formatVersion=1, kind='fairbind-scenario-run', run_id=entry['run_id'], scenario=entry['scenario'],
        scenario_sha256=entry['scenario_sha256'], method=str(entry['parameters'].get('arm', 'fairbind')).lower(),
        revision=src['revision'], dirty=src['dirty'], reportable=not src['dirty'] and status == 'completed',
        upstreams=src['upstreams'], parameters=entry['parameters'], profile_overrides=entry['profile_overrides'],
        judgment_delay_blocks=entry['judgment_delay_blocks'], inadmissible_profile=entry['inadmissible_profile'],
        override_used=entry['override_used'], override_skipped_checks=entry['override_skipped_checks'],
        requested_D_holding_blocks=entry['requested_D_holding_blocks'],
        effective_hold_period_blocks=entry['effective_hold_period_blocks'],
        operating_point=entry['operating_point'], metric_definitions=entry['metric_definitions'],
        seed=entry['seed'],
        randomness=dict(seed=entry['seed'], repetition=entry['repetition'], n_seeds=entry['n_seeds'],
                        seed_changes=SEED_EFFECTS, otherwise_deterministic=True),
        detection=detection_summary(entry['_profile'], metrics), created_at=now(), started_at=started_at, finished_at=finished_at, status=status,
        error=error, fault=entry['fault'], controller_actions=entry['controller_actions'],
        restart_errors=[i.error for i in restarts if i.error],
        processes={n: dict(command=p.command, starts=p.starts, exit_code=p.exit_code()) for n, p in procs.items()},
        metrics=metrics, missing_metrics=missing,
        ground_truth=dict(path=str(truth_path), sha256=hashlib.sha256(truth_path.read_bytes()).hexdigest()))
    results.parent.mkdir(parents=True, exist_ok=True)
    results.write_text(json.dumps(envelope, indent=2, sort_keys=True))
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
