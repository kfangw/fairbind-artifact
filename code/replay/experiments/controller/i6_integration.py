"""End-to-end integration runs of the hold-period harness (I6) on a local Anvil.

Runs a short list of cells through the controller with the real manifest (i6-manifest.json), each
shortened with --smoke where a planned run would take hours, and checks the collector's output:
every fault_observed item holds or does not apply, the injection log has no draw mismatch, the
workload ended by the expected end rule, and the cell's own checks. It needs FAIRBIND_ANVIL_151,
cast, forge artifacts in out/ and minutes of wall time per run, so it is not part of `make check`:

    python3 experiments/controller/i6_integration.py --output /path/outside/the/repo [--only NAME,...]
        [--parallel 2] [--port-base 22000] [--allow-dirty] [--twice]

It prints one JSON line per run and writes OUTPUT/integration-summary.json with the measured costs
(blocks, purchases, stops, wall seconds) of every run. Exit status 1 when a run or a check fails.

--twice runs every named run a second time with the same seed (OUTPUT/NAME and OUTPUT/NAME.2) and
compares their observations/collector.jsonl byte for byte; a difference is a failed check, reported
with the first differing rows.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name('i6-manifest.json')
SEED = 20260928

# name: planned run (with --repetitions 1), smoke overrides, accepted workload end modes, cell checks.
RUNS = {
    'finite-stop-1': dict(run='I6-p74-r0', smoke=[], end={'horizon', 'detected'}, checks=['finite']),
    'finite-exit-1': dict(run='I6-p77-r0', smoke=[], end={'horizon', 'detected'}, checks=['finite', 'exit']),
    'cheater-m1-high': dict(run='I6-p08-r0', smoke=['episodes=1', 'rate_per_block=0.01'],
                            end={'count_reached', 'sanctioned'}, checks=['detected']),
    'availability-v9': dict(run='I6-p80-r0', smoke=['worst_path_cases=3'], end={'cases_final'},
                            checks=['worst_path', 'replacement']),
    'm4-worst': dict(run='I6-p44-r0', smoke=['episodes=1', 'rate_per_block=0.01'], end={'count_reached', 'sanctioned'},
                     checks=['worst_path']),
    # Few concurrent cases (about three): complete worst paths without exhausting the verifier set.
    'm4-worst-3': dict(run='I6-p44-r0', smoke=['episodes=3', 'rate_per_block=0.001'], end={'count_reached', 'sanctioned'},
                       checks=['worst_path']),
    'honest-h1': dict(run='I6-p68-r0', smoke=['honest_windows=1', 'rate_per_block=0.001'],
                      end={'windows_complete'}, checks=['honest']),
}


def observations(run_dir):
    rows = {}
    for line in (run_dir / 'observations' / 'collector.jsonl').read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r['metric']] = r['value']
    return rows


def check(name, spec, envelope, run_dir):
    """Problems of one finished run (empty when every check holds)."""
    problems = []
    if envelope['status'] != 'completed':
        return [f"status {envelope['status']}: {envelope['error']}"]
    obs = observations(run_dir)
    bad = [i for i in obs.get('fault_observed', []) if i['applicable'] and not i['ok']]
    problems += [f"fault_observed {i['item']}: {i['reason']}" for i in bad]
    if not obs.get('fault_observed'):
        problems.append('no fault_observed row')
    if obs.get('injection_draw_mismatch_count') != 0:
        problems.append(f"injection_draw_mismatch_count {obs.get('injection_draw_mismatch_count')}")
    summary = json.loads((run_dir / 'workload' / 'summary.json').read_text())
    if summary['end']['mode'] not in spec['end']:
        problems.append(f"end mode {summary['end']['mode']}, want one of {sorted(spec['end'])}")
    modes = obs.get('episode_end_mode') or []
    for c in spec['checks']:
        if c == 'finite' and not set(modes) <= {'with_detection', 'without_detection'}:
            problems.append(f'finite episode end modes {modes}')
        if c == 'exit' and obs.get('bond_exit_deferred_balance') not in ([], [0], None):
            problems.append(f"bond exit with deferred balance {obs.get('bond_exit_deferred_balance')}")
        if c == 'detected' and (obs.get('final_failure_count') or 0) < 1:
            problems.append('no confirmed failure in a cheater run')
        if c == 'worst_path' and not obs.get('worst_path_case_blocks'):
            problems.append('no worst-path case')
        if c == 'replacement':
            removed, replaced = obs.get('verifier_removed_count'), obs.get('verifier_replacement_count')
            if removed != replaced:
                problems.append(f'{removed} verifiers removed, {replaced} replaced')
        if c == 'honest' and not obs.get('honest_windows'):
            problems.append('no complete honest window')
    return problems


def costs(envelope, run_dir):
    summary = json.loads((run_dir / 'workload' / 'summary.json').read_text())
    blocks = summary['blocks']['end'] - summary['blocks']['start']
    purchases, stops = summary['purchases']['attempted'], summary['clock']['stops']
    t0 = time.mktime(time.strptime(envelope['started_at'][:19], '%Y-%m-%dT%H:%M:%S'))
    t1 = time.mktime(time.strptime(envelope['finished_at'][:19], '%Y-%m-%dT%H:%M:%S'))
    size = sum(f.stat().st_size for f in run_dir.rglob('*') if f.is_file())
    return dict(blocks=blocks, purchases=purchases, settled=summary['purchases']['settled'], stops=stops,
                settles=summary['clock']['settles'], mine_seconds=round(summary['clock']['mine_seconds'], 1),
                driver_seconds=round(summary['wall']['seconds'], 1), run_seconds=t1 - t0, run_dir_bytes=size)


def run_one(name, spec, args, port_base, results, lock, label=None):
    label = label or name
    out = Path(args.output) / label
    if out.exists():
        shutil.rmtree(out)
    cmd = [sys.executable, str(ROOT / 'experiments' / 'controller'), '--manifest', str(MANIFEST), '--run-list',
           'hold-period-grid', '--seed', str(SEED), '--repetitions', '1', '--only-runs', spec['run'], '--output',
           str(out), '--port-base', str(port_base)]
    for s in spec['smoke']:
        cmd += ['--smoke', s]
    if args.allow_dirty:
        cmd.append('--allow-dirty')
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    run_id = spec['run'] + ('-smoke' if spec['smoke'] else '')
    envelope_path = next(iter(sorted((out / 'results').rglob(f'{run_id}.json'))), None) if (out / 'results').exists() \
        else None
    row = dict(name=label, run_id=run_id, smoke=spec['smoke'])
    if envelope_path is None:
        row.update(status='no envelope', problems=[proc.stderr.strip()[-2000:] or proc.stdout.strip()[-2000:]])
    else:
        envelope = json.loads(envelope_path.read_text())
        run_dir = out / 'runs' / run_id
        row.update(status=envelope['status'], cell=envelope['cell']['name'], problems=check(name, spec, envelope, run_dir))
        if envelope['status'] == 'completed':
            row.update(costs(envelope, run_dir))
    with lock:
        results.append(row)
        print(json.dumps(row), flush=True)


def collector_rows(out, spec):
    run_id = spec['run'] + ('-smoke' if spec['smoke'] else '')
    path = out / 'runs' / run_id / 'observations' / 'collector.jsonl'
    return path.read_bytes() if path.exists() else None


def compare_twice(name, spec, output):
    """Byte comparison of the collector rows of NAME and NAME.2."""
    a, b = collector_rows(Path(output) / name, spec), collector_rows(Path(output) / f'{name}.2', spec)
    row = dict(name=f'{name} (twice)', status='completed', problems=[])
    if a is None or b is None:
        row['problems'].append('collector.jsonl missing in one of the two runs')
        return row
    row['identical'] = a == b
    if a != b:
        la, lb = a.decode().splitlines(), b.decode().splitlines()
        diff = [dict(first=x, second=y) for x, y in zip(la, lb) if x != y]
        if len(la) != len(lb):
            diff.append(dict(first=f'{len(la)} rows', second=f'{len(lb)} rows'))
        row['differing_rows'] = diff[:20]
        row['problems'].append(f'collector.jsonl differs in {len(diff)} rows between two runs with the same seed')
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', required=True, help='directory outside the repository')
    ap.add_argument('--only', help='comma-separated run names: ' + ', '.join(RUNS))
    ap.add_argument('--parallel', type=int, default=2)
    ap.add_argument('--port-base', type=int, default=22000)
    ap.add_argument('--allow-dirty', action='store_true')
    ap.add_argument('--twice', action='store_true', help='run each twice and compare collector.jsonl')
    args = ap.parse_args(argv)
    if not os.environ.get('FAIRBIND_ANVIL_151'):
        raise SystemExit('FAIRBIND_ANVIL_151 is not set')
    out = Path(args.output).resolve()
    try:
        out.relative_to(ROOT)
        raise SystemExit('--output must be outside the repository')
    except ValueError:
        pass
    names = [n.strip() for n in (args.only or ','.join(RUNS)).split(',') if n.strip()]
    unknown = sorted(set(names) - set(RUNS))
    if unknown:
        raise SystemExit(f'unknown runs: {unknown}')
    out.mkdir(parents=True, exist_ok=True)
    results, lock = [], threading.Lock()
    # Each run name keeps its port base, so the second run of --twice uses the same loopback ports
    # (the seller's URL enters its epoch manifests and so the chain).
    ports = {n: args.port_base + 200 * i for i, n in enumerate(names)}

    def phase(queue):
        def worker():
            while True:
                with lock:
                    if not queue:
                        return
                    name, label = queue.pop(0)
                run_one(name, RUNS[name], args, ports[name], results, lock, label)
        threads = [threading.Thread(target=worker) for _ in range(max(1, args.parallel))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    phase([(n, n) for n in names])
    if args.twice:
        phase([(n, f'{n}.2') for n in names])
    if args.twice:
        for n in names:
            row = compare_twice(n, RUNS[n], out)
            results.append(row)
            print(json.dumps(row), flush=True)
    (out / 'integration-summary.json').write_text(json.dumps(results, indent=2))
    failed = [r['name'] for r in results if r['problems'] or r['status'] != 'completed']
    print(json.dumps(dict(runs=len(results), failed=failed)))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
