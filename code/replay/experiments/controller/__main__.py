"""Scenario controller command line.

    python3 experiments/controller --dry-run
    python3 experiments/controller --manifest local.json --output /tmp/new-run --only F1,S2
    python3 experiments/controller --manifest experiments/controller/i6-manifest.json --run-list hold-period-grid \
        --seed 20260928 --output ./runs/i6 --shard 0/2 --port-base 20000 --skip-existing
"""
import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = 'controller'

from controller import operating_point as opt  # noqa: E402
from controller import profile as prof  # noqa: E402
from controller import runner  # noqa: E402
from controller import scenario as scn  # noqa: E402
from controller.yamlsubset import scalar  # noqa: E402

DEFAULT_SCENARIOS = runner.ROOT / 'experiments' / 'scenarios'
DEFAULT_PROFILE = runner.ROOT / 'profiles' / 'local-evaluation-v1.json'


def parse_sets(items):
    out = {}
    for item in items:
        key, sep, value = item.partition('=')
        if not sep or not key:
            raise SystemExit(f'--set expects name=value, got {item!r}')
        out[key] = scalar(value)
    return out


def select(scenarios, only):
    if not only:
        return scenarios
    wanted = [s.strip() for s in only.split(',') if s.strip()]
    known = {s['id'] for s in scenarios}
    missing = sorted(set(wanted) - known)
    if missing:
        raise SystemExit(f'unknown scenarios: {missing}')
    return [s for s in scenarios if s['id'] in wanted]


def check_sets(scenarios, sets):
    for key in sets:
        specs = [s['parameters'][key] for s in scenarios if key in s['parameters']]
        if not specs:
            raise SystemExit(f'--set {key}: no selected scenario has this parameter')
        if any('sweep' in spec for spec in specs):
            raise SystemExit(f'--set {key}: swept parameters cannot be fixed; select points with --only')


def summary(plan):
    lines = []
    for e in plan:
        state = 'ready' if e['runnable'] else 'blocked: ' + '; '.join(e['blocked_reasons'])
        faults = ', '.join(f"{a['action']}@{a.get('process', 'proxy')}" for a in e['controller_actions'])
        directives = ', '.join(f"{p}:{d['kind']}" for p, d in e['directives'].items() if d['kind'])
        lines.append(f"{e['run_id']:<12} seed={e['seed']:<20} L={e['judgment_delay_blocks']} "
                     f"overrides={json.dumps(e['profile_overrides'], sort_keys=True)}")
        lines.append(f"{'':12} controller=[{faults}] directives=[{directives}] {state}")
        if e['inadmissible_profile']:
            lines.append(f"{'':12} inadmissible profile: {', '.join(e['inadmissible_profile'])}")
        if e['override_used']:
            lines.append(f"{'':12} override_used: true, requested D={e['requested_D_holding_blocks']}, "
                          f"effective hold period={e['effective_hold_period_blocks']}, "
                          f"skipped checks: {', '.join(e['override_skipped_checks'])}")
    return '\n'.join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--scenarios', default=str(DEFAULT_SCENARIOS))
    p.add_argument('--only', help='comma-separated scenario ids')
    p.add_argument('--run-list', help='named run of experiments/scenarios/run-list.json (for example main): its '
                   'scenarios, each on the arms it names')
    p.add_argument('--profile', default=str(DEFAULT_PROFILE))
    p.add_argument('--profile-name', default='data-api-fast-v1')
    p.add_argument('--operating-point', default=str(opt.DEFAULT_PATH))
    p.add_argument('--set', action='append', default=[], metavar='NAME=VALUE',
                   help='resolve an unswept symbolic parameter')
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--repetitions', type=int, default=None,
                   help='runs per point for every scenario (default: each scenario\'s n_seeds)')
    p.add_argument('--dry-run', action='store_true', help='validate scenarios and print the plan; launch nothing')
    p.add_argument('--format', choices=('json', 'text'), default='json')
    p.add_argument('--manifest')
    p.add_argument('--output')
    p.add_argument('--allow-dirty', action='store_true', help='run from a dirty tree; results are not reportable')
    p.add_argument('--allow-inadmissible-profile', action='store_true')
    p.add_argument('--only-cells', help='comma-separated cell names (scenarios with cells, such as I6)')
    p.add_argument('--only-runs', help='comma-separated run ids (for example I6-p74-r0)')
    p.add_argument('--smoke', action='append', default=[], metavar='KEY=VALUE',
                   help='shorten the selected hold-period runs for an integration test (rate_per_block, episodes, '
                   'honest_windows, worst_path_cases); the run id gets -smoke and the envelope is never reportable')
    p.add_argument('--shard', help='K/N: run only the planned runs whose run id falls in shard K of N (0 <= K < N)')
    p.add_argument('--port-base', type=int, default=runner.DEFAULT_PORT_BASE,
                   help='loopback port base P: {rpc_port} P, {base_port} P+10, {seller_port} P+11, {proxy_port} P+80')
    p.add_argument('--skip-existing', action='store_true',
                   help='skip a run that already has a result envelope and restart one that has only partial output')
    p.add_argument('--keep-logs', choices=runner.KEEP_LOGS, default='all',
                   help='keep the process output logs of no run, of runs that did not complete, or of every run')
    p.add_argument('--rules-file', help='decision-rules file of the run list: each envelope records its name and '
                   'SHA-256 (decision_rules); an I6 run without one is not reportable')
    a = p.parse_args(argv)
    if a.repetitions is not None and a.repetitions < 1:
        raise SystemExit('--repetitions must be positive')
    try:
        scenarios = select(scn.load_all(a.scenarios), a.only)
    except scn.ScenarioError as exc:
        print(f'invalid scenario: {exc}', file=sys.stderr)
        return 2
    arms_by_scenario = None
    if a.run_list:
        try:
            arms_by_scenario = runner.load_run_list(a.run_list)
        except (OSError, ValueError, KeyError) as exc:
            print(f'invalid run list: {exc}', file=sys.stderr)
            return 2
        scenarios = [s for s in scenarios if s['id'] in arms_by_scenario]
    sets = parse_sets(a.set)
    check_sets(scenarios, sets)
    base = prof.load_profile(a.profile, a.profile_name)
    base_violations = prof.admissibility(base)
    try:
        op = opt.load(a.operating_point)
        plan = runner.build_plan(scenarios, base, sets, a.seed, a.repetitions, op, arms_by_scenario)
    except (OSError, ValueError) as exc:
        print(f'invalid operating point: {exc}', file=sys.stderr)
        return 2
    try:
        cells = [c.strip() for c in (a.only_cells or '').split(',') if c.strip()]
        plan = runner.select_cells(plan, cells)
        plan = runner.select_runs(plan, [r.strip() for r in (a.only_runs or '').split(',') if r.strip()])
        plan = runner.apply_smoke(plan, runner.parse_smoke(a.smoke))
        shard = runner.parse_shard(a.shard) if a.shard else None
        if shard:
            plan = runner.shard(plan, *shard)
        runner.ports(a.port_base)
    except ValueError as exc:
        print(f'invalid selection: {exc}', file=sys.stderr)
        return 2
    manifest = None
    if a.manifest:
        try:
            manifest = runner.load_manifest(a.manifest)
        except (OSError, ValueError) as exc:
            print(f'invalid manifest: {exc}', file=sys.stderr)
            return 2
    if a.dry_run:
        doc = dict(scenarios=len(scenarios), runs=len(plan), runnable=sum(e['runnable'] for e in plan),
                   base_profile=a.profile_name, operating_point=opt.summary(op, a.profile_name), base_profile_violations=base_violations,
                   manifest=a.manifest, selection=dict(only_cells=cells or None, only_runs=a.only_runs, shard=a.shard, smoke=a.smoke or None),
                   plan=runner.public_plan(plan))
        print(json.dumps(doc, indent=2, sort_keys=True) if a.format == 'json' else summary(doc['plan']))
        return 0
    if manifest is None or not a.output:
        raise SystemExit('a run needs --manifest and --output (or use --dry-run)')
    missing_env = runner.missing_env(manifest)
    if missing_env:
        raise SystemExit(f'the manifest needs environment variables that are not set: {", ".join(missing_env)}')
    src = runner.source_state()
    if src['dirty'] and not a.allow_dirty:
        raise SystemExit('Clean checkout required (or --allow-dirty for unreportable development runs)')
    try:
        rules = runner.rules_record(a.rules_file)
    except OSError as exc:
        raise SystemExit(f'--rules-file: {exc}')
    failed = 0
    for entry in plan:
        if not entry['runnable']:
            print(json.dumps(dict(run_id=entry['run_id'], status='skipped', reasons=entry['blocked_reasons'])))
            continue
        if (entry['inadmissible_profile'] or entry['override_used']) and not a.allow_inadmissible_profile:
            reasons = []
            if entry['inadmissible_profile']:
                reasons.append('inadmissible profile: ' + ', '.join(entry['inadmissible_profile']))
            if entry['override_used']:
                reasons.append('override_used: true (D below caseHorizon needs the override build, which skips '
                               + ', '.join(entry['override_skipped_checks']) + ')')
            print(json.dumps(dict(run_id=entry['run_id'], status='skipped', reasons=reasons)))
            continue
        if a.skip_existing and runner.result_path(a.output, entry['run_id']).exists():
            print(json.dumps(dict(run_id=entry['run_id'], status='skipped', reasons=['result envelope exists'])))
            continue
        env = runner.execute(entry, manifest, a.output, port_base=a.port_base, keep_logs=a.keep_logs,
                             resume=a.skip_existing, allow_dirty=a.allow_dirty, rules=rules)
        failed += env['status'] != 'completed'
        print(json.dumps(dict(run_id=entry['run_id'], status=env['status'], ended_by=env['ended_by'],
                              error=env['error'], missing_metrics=len(env['missing_metrics']))), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
