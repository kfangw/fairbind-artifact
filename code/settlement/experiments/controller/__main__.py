"""Scenario controller command line.

    python3 experiments/controller --dry-run
    python3 experiments/controller --manifest local.json --output /tmp/new-run --only F1,S2
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
                   manifest=a.manifest, plan=runner.public_plan(plan))
        print(json.dumps(doc, indent=2, sort_keys=True) if a.format == 'json' else summary(doc['plan']))
        return 0
    if manifest is None or not a.output:
        raise SystemExit('a run needs --manifest and --output (or use --dry-run)')
    src = runner.source_state()
    if src['dirty'] and not a.allow_dirty:
        raise SystemExit('Clean checkout required (or --allow-dirty for unreportable development runs)')
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
        env = runner.execute(entry, manifest, a.output)
        failed += env['status'] != 'completed'
        print(json.dumps(dict(run_id=entry['run_id'], status=env['status'],
                              missing_metrics=len(env['missing_metrics']))))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
