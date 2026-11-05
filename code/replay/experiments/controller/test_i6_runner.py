"""Execution of the hold-period harness runs (runner.execute and the run flags) with stub processes.

Every process is a `python3 -c` one-liner; no chain is started (block_source is a stub).
"""
import contextlib
import io
import hashlib
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller import profile as prof  # noqa: E402
from controller import runner  # noqa: E402
from controller import scenario as scn  # noqa: E402
from controller.__main__ import main  # noqa: E402

SCENARIO = runner.ROOT / 'experiments' / 'scenarios' / 'I6.yaml'
PROFILE = runner.ROOT / 'profiles' / 'local-evaluation-v1.json'
I6_MANIFEST = Path(__file__).with_name('i6-manifest.json')
SEED = runner.PLAN_BASE_SEEDS['I6']
PY = sys.executable

# A long-running service: records its start, and its stop on SIGTERM, in the order log.
SERVICE = ('import os, signal, sys, time; name, log = sys.argv[1], sys.argv[2];'
           'signal.signal(signal.SIGTERM, lambda *a: (open(log, "a").write(name + " stopped\\n"), os._exit(0)));'
           'open(log, "a").write(name + " started\\n"); time.sleep(120)')
# Anvil: a service that also writes its pid so the collector can check that it is alive.
ANVIL = ('import os, signal, sys, time; log, pid = sys.argv[1], sys.argv[2];'
         'open(pid, "w").write(str(os.getpid()));'
         'signal.signal(signal.SIGTERM, lambda *a: (open(log, "a").write("anvil stopped\\n"), os._exit(0)));'
         'open(log, "a").write("anvil started " + " ".join(sys.argv[3:]) + "\\n"); time.sleep(120)')
# The buyer: waits for the services to start, dumps its environment, writes one row and exits.
BUYER = ('import json, os, sys, time; time.sleep(1); out, envf, code = sys.argv[1], sys.argv[2], int(sys.argv[3]);'
         'json.dump(dict(os.environ), open(envf, "w"));'
         'open(out, "w").write(json.dumps(dict(metric="released_exposure", value=0, observation_id="b")) + "\\n");'
         'sys.exit(code)')
# The collector: fails unless anvil is alive; records its arguments and the ground truth.
COLLECTOR = ('import json, os, sys; log, pid, gt, out = sys.argv[1:5]; os.kill(int(open(pid).read()), 0);'
             'open(log, "a").write("collector\\n");'
             'json.dump(dict(argv=sys.argv[1:], truth=json.load(open(gt)), env=dict(os.environ)),'
             ' open(os.path.join(os.path.dirname(out), "collector-seen.json"), "w"))')


def i6_plan(profile_name='data-api-fast-v1', repetitions=1):
    sc = scn.load_scenario(SCENARIO)
    base = prof.load_profile(PROFILE, profile_name)
    return runner.build_plan([sc], base, base_seed=SEED, repetitions=repetitions)


def first(plan, cell):
    return next(e for e in plan if e['cell']['name'] == cell)


def stub_manifest(buyer_exit=0):
    procs = {name: dict(command=[PY, '-c', SERVICE, name, '{run_dir}/order.log']) for name in runner.LAUNCH_ORDER}
    procs['anvil'] = dict(command=[PY, '-c', ANVIL, '{run_dir}/order.log', '{run_dir}/anvil.pid', '--port',
                                   '{rpc_port}'], ready='rpc')
    procs['buyer'] = dict(command=[PY, '-c', BUYER, '{observations}', '{proc_dir}/env.json', str(buyer_exit)])
    deploy = ('import json, os, sys; json.dump(dict(argv=sys.argv[1:], env=dict(os.environ)),'
              ' open(os.path.join(sys.argv[1], "seen.json"), "w"))')
    return dict(formatVersion=1, rpcUrl='http://127.0.0.1:{rpc_port}', processes=procs, stopTimeoutSeconds=5,
                runTimeoutSeconds=30,
                deploy=dict(command=[PY, '-c', deploy, '{proc_dir}', '{base_port}'],
                            env=dict(FAIRBIND_BASE_PORT='{base_port}')),
                collector=dict(command=[PY, '-c', COLLECTOR, '{run_dir}/order.log', '{run_dir}/anvil.pid',
                                        '{ground_truth}', '{observations}', '{rpc_url}']))


def run(entry, out, manifest=None, **kw):
    return runner.execute(entry, manifest or stub_manifest(), out, block_source=lambda: 0, **kw)


def free_port_base():
    """A port base whose proxy port (P + 80) is free."""
    for _ in range(50):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            base = s.getsockname()[1] - 80
        if not 1024 <= base <= 65535 - 100:
            continue
        with socket.socket() as s:
            try:
                s.bind(('127.0.0.1', base + 80))
            except OSError:
                continue
        return base
    raise RuntimeError('no free port')


class Execution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = i6_plan()

    def setUp(self):
        self.out = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.out, ignore_errors=True))

    def test_collector_runs_while_anvil_is_alive_and_anvil_stops_last(self):
        entry = first(self.plan, 'M1-low-admissible')
        env = run(entry, self.out)
        self.assertEqual(env['status'], 'completed', env['error'])
        self.assertEqual(env['ended_by'], 'workload_exit')
        order = Path(self.out, 'runs', entry['run_id'], 'order.log').read_text().splitlines()
        self.assertEqual(order[-2:], ['collector', 'anvil stopped'])
        stops = order[order.index('collector') - 4:order.index('collector')]
        self.assertEqual(stops, ['seller stopped', 'facilitator stopped', 'verifier stopped', 'keeper stopped'])
        self.assertEqual(env['processes']['collector']['exit_code'], 0)

    def test_ports_follow_the_port_base(self):
        entry = first(self.plan, 'M1-low-admissible')
        env = run(entry, self.out, port_base=20000)
        self.assertEqual(env['status'], 'completed', env['error'])
        run_dir = Path(self.out, 'runs', entry['run_id'])
        self.assertIn('anvil started --port 20000', (run_dir / 'order.log').read_text())
        deploy = json.loads((run_dir / 'proc' / 'deploy' / 'seen.json').read_text())
        self.assertEqual(deploy['argv'][1], '20010')
        self.assertEqual(deploy['env']['FAIRBIND_BASE_PORT'], '20010')
        self.assertEqual(deploy['env']['FAIRBIND_RPC_URL'], 'http://127.0.0.1:20000')
        self.assertEqual(env['execution']['ports'], dict(rpc_port=20000, base_port=20010, seller_port=20011,
                                                         proxy_port=20080))
        self.assertEqual(env['execution']['rpc_url'], 'http://127.0.0.1:20000')
        seen = json.loads((run_dir / 'observations' / 'collector-seen.json').read_text())
        self.assertEqual(seen['argv'][-1], 'http://127.0.0.1:20000')
        with self.assertRaises(ValueError):
            runner.ports(80)

    def test_proxy_listens_on_the_proxy_port(self):
        entry = first(self.plan, 'M1-low-admissible')
        base = free_port_base()
        manifest = stub_manifest()
        manifest['proxy'] = dict(listen='127.0.0.1:{proxy_port}', upstream='http://127.0.0.1:{seller_port}')
        self.assertEqual(runner.validate_manifest(manifest), [])
        env = run(entry, self.out, manifest, port_base=base)
        self.assertEqual(env['status'], 'completed', env['error'])
        buyer_env = json.loads(Path(self.out, 'runs', entry['run_id'], 'proc', 'buyer', 'env.json').read_text())
        self.assertEqual(buyer_env['FAIRBIND_SELLER_URL'], f'http://127.0.0.1:{base + 80}')

    def test_ground_truth_reaches_the_collector_only(self):
        entry = first(self.plan, 'M1-low-admissible')
        env = run(entry, self.out)
        self.assertEqual(env['status'], 'completed', env['error'])
        run_dir = Path(self.out, 'runs', entry['run_id'])
        truth_path = env['ground_truth']['path']
        seen = json.loads((run_dir / 'observations' / 'collector-seen.json').read_text())
        self.assertEqual(seen['argv'][2], truth_path)
        self.assertEqual(seen['truth']['bad_sales_rule'], 'all_cheater_episode_sales')
        self.assertEqual(seen['env']['FAIRBIND_RUN_DIR'], str(run_dir))
        for dump in (run_dir / 'proc' / 'buyer' / 'env.json', run_dir / 'proc' / 'deploy' / 'seen.json'):
            self.assertNotIn(truth_path, dump.read_text())
            self.assertNotIn('ground-truth', dump.read_text())
        # The manifest cannot hand the path to any other command or env value.
        for where in ('keeper', 'buyer'):
            manifest = stub_manifest()
            manifest['processes'][where]['command'].append('{ground_truth}')
            errors = runner.validate_manifest(manifest)
            self.assertEqual(errors, [f'processes.{where}: unknown placeholder {{ground_truth}} (collector only)'])
        manifest = stub_manifest()
        manifest['deploy']['env']['GT'] = '{ground_truth}'
        self.assertEqual(len(runner.validate_manifest(manifest)), 1)
        # Even past validation, no other process has the placeholder.
        manifest = stub_manifest()
        manifest['processes']['seller']['command'].append('{ground_truth}')
        env = run(first(self.plan, 'H'), self.out, manifest)
        self.assertEqual(env['status'], 'failed')
        self.assertIn("KeyError('ground_truth')", env['error'])

    def test_every_process_gets_the_run_dir_and_the_anvil_name(self):
        entry = first(self.plan, 'M1-low-admissible')
        with mock.patch.dict(os.environ, FAIRBIND_ANVIL='/opt/anvil-1.5.1'):
            env = run(entry, self.out)
        self.assertEqual(env['status'], 'completed', env['error'])
        run_dir = Path(self.out, 'runs', entry['run_id'])
        buyer_env = json.loads((run_dir / 'proc' / 'buyer' / 'env.json').read_text())
        deploy_env = json.loads((run_dir / 'proc' / 'deploy' / 'seen.json').read_text())['env']
        for e in (buyer_env, deploy_env):
            self.assertEqual(e['FAIRBIND_RUN_DIR'], str(run_dir))
            self.assertEqual(e['FAIRBIND_ANVIL'], '/opt/anvil-1.5.1')

    def test_allow_dirty_reaches_the_deploy_step_only(self):
        entry = first(self.plan, 'M1-low-admissible')
        with mock.patch.dict(os.environ, {'FAIRBIND_ALLOW_DIRTY': ''}):
            env = run(entry, self.out, allow_dirty=True)
        self.assertEqual(env['status'], 'completed', env['error'])
        run_dir = Path(self.out, 'runs', entry['run_id'])
        deploy_env = json.loads((run_dir / 'proc' / 'deploy' / 'seen.json').read_text())['env']
        buyer_env = json.loads((run_dir / 'proc' / 'buyer' / 'env.json').read_text())
        self.assertEqual((deploy_env['FAIRBIND_ALLOW_DIRTY'], buyer_env['FAIRBIND_ALLOW_DIRTY']), ('1', ''))

    def test_environment_references_expand_or_fail(self):
        entry = first(self.plan, 'M1-low-admissible')
        manifest = stub_manifest()
        manifest['processes']['anvil']['command'][0] = '$FAKE_PYTHON_FOR_TEST'
        manifest['deploy']['env']['FAIRBIND_ANVIL'] = '$FAKE_PYTHON_FOR_TEST'
        self.assertEqual(runner.manifest_env(manifest), ['FAKE_PYTHON_FOR_TEST'])
        with mock.patch.dict(os.environ, {'FAKE_PYTHON_FOR_TEST': ''}):
            self.assertEqual(runner.missing_env(manifest), ['FAKE_PYTHON_FOR_TEST'])
            env = run(entry, self.out, manifest)
            self.assertEqual(env['status'], 'failed')
            self.assertIn('$FAKE_PYTHON_FOR_TEST, which is not set', env['error'])
        with mock.patch.dict(os.environ, FAKE_PYTHON_FOR_TEST=PY):
            env = run(first(self.plan, 'H'), self.out, manifest)
        self.assertEqual(env['status'], 'completed', env['error'])
        self.assertEqual(env['processes']['anvil']['command'][0], PY)
        # Arguments that only contain a $ are left alone (shell snippets).
        for arg in ('exec "$0" "$@"', '$HOME/x', '$lower'):
            self.assertEqual(runner._expand(arg, {}), arg)

    def test_envelope_profile_and_ground_truth_fields(self):
        for cell, rule, m in (('M1-low-admissible', 'all_cheater_episode_sales', None), ('F-switch', 'first_m', 1),
                              ('H', 'none', None)):
            entry = first(self.plan, cell)
            env = run(entry, self.out)
            self.assertEqual(env['status'], 'completed', env['error'])
            self.assertEqual(env['operating_point_k'], entry['operating_point_k'])
            self.assertEqual(env['operating_point_k']['value'], entry['operating_point']['k']['value'])
            self.assertEqual(env['harness'], entry['harness'])
            self.assertIsNotNone(env['harness'])
            self.assertEqual(env['base_seed'], SEED)
            self.assertEqual(env['cell']['name'], cell)
            profile = json.loads(Path(self.out, 'runs', entry['run_id'], 'shared', 'profile.json').read_text())
            self.assertEqual(profile['harness'], entry['harness'])
            truth = json.loads(Path(env['ground_truth']['path']).read_text())
            self.assertEqual((truth['bad_sales_rule'], truth['bad_sales_m']), (rule, m), cell)
            events = [e['event'] for e in truth['events']]
            self.assertLess(events.index('workload_finished'), events.index('collector_started'))

    def test_timeout_and_process_failure_are_recorded(self):
        entry = first(self.plan, 'M1-low-admissible')
        manifest = stub_manifest()
        manifest['runTimeoutSeconds'] = 1
        manifest['processes']['buyer']['command'] = [PY, '-c', 'import time; time.sleep(120)']
        env = run(entry, self.out, manifest)
        self.assertEqual((env['status'], env['ended_by']), ('timeout', 'wall_clock_limit'))
        self.assertIn('wall-clock limit of 1 s', env['error'])
        self.assertNotIn('collector', env['processes'])
        self.assertFalse(env['reportable'])
        order = Path(self.out, 'runs', entry['run_id'], 'order.log').read_text().splitlines()
        self.assertEqual(order[-1], 'anvil stopped')
        manifest = stub_manifest()
        manifest['processes']['buyer']['command'] = [PY, '-c', 'import time; time.sleep(120)']
        manifest['processes']['keeper']['command'] = [PY, '-c', 'import sys, time; time.sleep(0.5); sys.exit(3)']
        entry = first(self.plan, 'H')
        env = run(entry, self.out, manifest)
        self.assertEqual((env['status'], env['ended_by']), ('failed', 'process_exit'))
        self.assertEqual(env['error'], 'keeper exited with 3 before the workload finished')
        env = run(first(self.plan, 'F-switch'), self.out, stub_manifest(buyer_exit=2))
        self.assertEqual((env['status'], env['ended_by'], env['error']), ('failed', 'workload_exit', 'buyer exited with 2'))

    def test_keep_logs(self):
        entries = [first(self.plan, c) for c in ('M1-low-admissible', 'H', 'F-switch', 'F-stop')]

        def logs(entry):
            return sorted(p.parent.name for p in Path(self.out, 'runs', entry['run_id'], 'proc').glob('*/output.log'))
        env = run(entries[0], self.out, keep_logs='none')
        self.assertEqual((env['status'], env['execution']['logs_kept']), ('completed', False))
        self.assertEqual(logs(entries[0]), [])
        self.assertTrue(env['metrics']['released_exposure']['observed'])
        env = run(entries[1], self.out, keep_logs='failed')
        self.assertEqual((env['status'], logs(entries[1])), ('completed', []))
        env = run(entries[2], self.out, stub_manifest(buyer_exit=1), keep_logs='failed')
        self.assertEqual(env['status'], 'failed')
        self.assertIn('buyer', logs(entries[2]))
        run(entries[3], self.out, keep_logs='all')
        self.assertEqual(logs(entries[3]), ['anvil', 'buyer', 'collector', 'deploy', 'facilitator', 'keeper',
                                            'seller', 'verifier'])
        with self.assertRaises(ValueError):
            run(first(self.plan, 'F-exit'), self.out, keep_logs='some')

    def test_existing_output(self):
        entry = first(self.plan, 'M1-low-admissible')
        run(entry, self.out)
        with self.assertRaises(FileExistsError):
            run(entry, self.out, resume=True)
        partial = first(self.plan, 'H')
        stale = Path(self.out, 'runs', partial['run_id'], 'proc', 'keeper', 'stale.txt')
        stale.parent.mkdir(parents=True)
        stale.write_text('x')
        with self.assertRaises(FileExistsError):
            run(partial, self.out)
        env = run(partial, self.out, resume=True)
        self.assertEqual(env['status'], 'completed', env['error'])
        self.assertFalse(stale.exists())

    def test_smoke_envelope_is_not_reportable(self):
        entry = runner.apply_smoke([first(self.plan, 'M1-low-admissible')], dict(episodes=1))[0]
        with mock.patch.object(runner, 'source_state', lambda: dict(revision='r', dirty=False, upstreams={})):
            env = run(entry, self.out)
        self.assertEqual(env['status'], 'completed', env['error'])
        self.assertEqual((env['smoke'], env['reportable']), (dict(episodes=1), False))
        self.assertTrue(env['run_id'].endswith('-smoke'))

    def test_decision_rules_file(self):
        # An I6 run is reportable only with the decision-rules file, whose name and SHA-256 it records.
        entry = first(self.plan, 'M1-low-admissible')
        rules = Path(self.out, 'rules.md')
        rules.write_text('rules\n')
        clean = mock.patch.object(runner, 'source_state', lambda: dict(revision='r', dirty=False, upstreams={}))
        with clean:
            env = run(entry, Path(self.out, 'without'))
        self.assertEqual((env['status'], env['decision_rules'], env['reportable']), ('completed', None, False))
        with clean:
            env = run(entry, Path(self.out, 'with'), rules=runner.rules_record(rules))
        self.assertEqual(env['decision_rules'], dict(file='rules.md', sha256=hashlib.sha256(b'rules\n').hexdigest()))
        self.assertTrue(env['reportable'])
        self.assertEqual(env['l_actual_min_blocks'], 29680)

class Selection(unittest.TestCase):
    def test_shards_cover_the_plan_exactly_once(self):
        plan = i6_plan(repetitions=None)
        ids = [e['run_id'] for e in plan]
        self.assertEqual(len(ids), len(set(ids)))
        for n in (1, 2, 3, 7):
            parts = [runner.shard(plan, k, n) for k in range(n)]
            got = [e['run_id'] for part in parts for e in part]
            self.assertEqual(sorted(got), sorted(ids), n)
            if n > 1:
                self.assertTrue(all(parts), n)
        # A shard depends on the run id only: it keeps its runs under a cell filter.
        cells = runner.select_cells(plan, ['M1-low-admissible', 'H'])
        self.assertEqual({e['run_id'] for e in runner.shard(cells, 1, 3)},
                         {e['run_id'] for e in runner.shard(plan, 1, 3)} & {e['run_id'] for e in cells})
        for bad in ('3/3', '1', 'a/b', '-1/2', '0/0'):
            with self.assertRaises(ValueError):
                runner.parse_shard(bad)

    def dry(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--dry-run', '--run-list', 'hold-period-grid', '--seed', str(SEED), *args])
        return code, (json.loads(out.getvalue()) if code == 0 else None)

    def test_dry_run_flags(self):
        _, full = self.dry()
        self.assertEqual((full['runs'], full['runnable']), (4254, 4254))
        counts = []
        for k in range(3):
            code, doc = self.dry('--shard', f'{k}/3')
            self.assertEqual(code, 0)
            self.assertEqual(doc['selection']['shard'], f'{k}/3')
            counts.append(doc['runs'])
        self.assertEqual(sum(counts), 4254)
        code, doc = self.dry('--only-cells', 'H,F-switch')
        self.assertEqual({e['cell']['name'] for e in doc['plan']}, {'H', 'F-switch'})
        self.assertEqual(doc['selection']['only_cells'], ['H', 'F-switch'])
        self.assertEqual(self.dry('--only-cells', 'H,nope')[0], 2)
        code, doc = self.dry('--repetitions', '1', '--only-runs', 'I6-p74-r0,I6-p80-r0')
        self.assertEqual([(e['run_id'], e['cell']['name']) for e in doc['plan']],
                         [('I6-p74-r0', 'F-stop'), ('I6-p80-r0', 'V-9')])
        self.assertEqual(self.dry('--only-runs', 'I6-p99-r0')[0], 2)

    def test_smoke_overrides(self):
        _, base = self.dry('--repetitions', '1', '--only-runs', 'I6-p08-r0,I6-p68-r0')
        code, doc = self.dry('--repetitions', '1', '--only-runs', 'I6-p08-r0,I6-p68-r0', '--smoke', 'episodes=1',
                             '--smoke', 'honest_windows=1', '--smoke', 'rate_per_block=0.002')
        self.assertEqual(code, 0)
        cheater, honest = doc['plan']
        self.assertEqual((cheater['run_id'], honest['run_id']), ('I6-p08-r0-smoke', 'I6-p68-r0-smoke'))
        self.assertEqual(cheater['smoke'], dict(rate_per_block=0.002, episodes=1))
        self.assertEqual(honest['smoke'], dict(rate_per_block=0.002, honest_windows=1))
        w = honest['directives']['buyer']['workload']
        self.assertEqual((w['rate_per_block'], w['end']['windows']), (0.002, 1))
        self.assertEqual(cheater['directives']['buyer']['workload']['end'], dict(rule='episodes', count=1))
        # Nothing but the buyer workload and the buyer funding changes.
        for before, after in zip(base['plan'], doc['plan']):
            self.assertEqual(before['directives']['seller'], after['directives']['seller'])
            self.assertEqual({k: v for k, v in before['harness'].items() if k != 'buyerPurchases'},
                             {k: v for k, v in after['harness'].items() if k != 'buyerPurchases'})
        self.assertLess(honest['harness']['buyerPurchases'], base['plan'][1]['harness']['buyerPurchases'])
        self.assertEqual(self.dry('--only-runs', 'I6-p08-r0', '--repetitions', '1', '--smoke', 'honest_windows=1')[0], 2)
        for bad in ('episodes=0', 'nope=1', 'rate_per_block=x', 'episodes'):
            self.assertEqual(self.dry('--only-runs', 'I6-p08-r0', '--repetitions', '1', '--smoke', bad)[0], 2)

        self.assertEqual(self.dry('--shard', '2/2')[0], 2)
        self.assertEqual(self.dry('--port-base', '10')[0], 2)

    def test_i6_manifest(self):
        manifest = runner.load_manifest(I6_MANIFEST)
        self.assertEqual(runner.manifest_env(manifest), ['FAIRBIND_ANVIL_151'])
        anvil = manifest['processes']['anvil']['command']
        # A fixed genesis timestamp and a fixed step per block (FAIRBIND_BLOCK_TIME_STEP of the deploy
        # step): block hashes, and the sampling that uses them, do not depend on the wall clock.
        self.assertEqual(anvil, ['$FAIRBIND_ANVIL_151', '--port', '{rpc_port}', '--chain-id', '31337', '--silent',
                                 '--prune-history', '--slots-in-an-epoch', '0', '--timestamp', '1700000000'])
        self.assertEqual(manifest['deploy']['env']['FAIRBIND_BLOCK_TIME_STEP'], '1')
        # Batch mode: every service sends the transactions of a head into the next block together, and
        # skips the heads a bulk mine passes through.
        for name in ('keeper', 'verifier', 'seller', 'facilitator', 'buyer'):
            self.assertIn('-batch', manifest['processes'][name]['command'], name)
        for name in ('keeper', 'verifier', 'seller'):
            cmd = manifest['processes'][name]['command']
            self.assertEqual(cmd[cmd.index('-hold-file') + 1], '{run_dir}/proc/hold.json', name)
        for name in ('seller', 'facilitator', 'buyer'):
            self.assertIn('-chain-time', manifest['processes'][name]['command'], name)
        # The clock waits on every service's progress at the head: the keeper reads the latest block
        # and the finalized block is the head (verifier discovery).
        self.assertIn('-lockstep', manifest['processes']['keeper']['command'])
        # A late-valid worst-path call (openSample) waits until the peers reported the head.
        keeper = manifest['processes']['keeper']['command']
        self.assertEqual(keeper[keeper.index('-yield-to') + 1],
                         '{run_dir}/proc/verifier/progress.json,{run_dir}/proc/seller/progress.json')
        self.assertIn('{ground_truth}', manifest['collector']['command'])
        self.assertIn('./services/verifier/cmd/fairbind-verifier-pool', manifest['processes']['verifier']['command'])
        self.assertIn('./services/buyer/cmd/fairbind-workload', manifest['processes']['buyer']['command'])
        self.assertEqual(manifest['deploy']['env']['FAIRBIND_BASE_PORT'], '{base_port}')
        with mock.patch.dict(os.environ, {'FAIRBIND_ANVIL_151': ''}), tempfile.TemporaryDirectory() as out, \
                self.assertRaises(SystemExit) as ctx:
            main(['--manifest', str(I6_MANIFEST), '--output', out, '--run-list', 'hold-period-grid',
                  '--only-cells', 'H', '--allow-dirty'])
        self.assertIn('FAIRBIND_ANVIL_151', str(ctx.exception))

    def test_skip_existing_and_only_cells_through_main(self):
        with tempfile.TemporaryDirectory() as out:
            manifest_path = Path(out, 'manifest.json')
            manifest = stub_manifest()
            manifest['processes']['anvil']['ready'] = {'seconds': 0}  # main reads blocks over RPC; no chain here
            manifest_path.write_text(json.dumps(manifest))
            args = ['--manifest', str(manifest_path), '--output', str(Path(out, 'o')), '--run-list',
                    'hold-period-grid', '--seed', str(SEED), '--repetitions', '1', '--only-cells', 'H',
                    '--allow-dirty', '--port-base', '21000', '--keep-logs', 'none']

            def call(*extra):
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    code = main(args + list(extra))
                return code, [json.loads(line) for line in captured.getvalue().splitlines()]
            code, lines = call()
            self.assertEqual(code, 0)
            self.assertEqual([line['status'] for line in lines], ['completed'] * len(lines))
            self.assertGreaterEqual(len(lines), 1)
            env = json.loads(runner.result_path(Path(out, 'o'), lines[0]['run_id']).read_text())
            self.assertEqual((env['execution']['port_base'], env['execution']['keep_logs']), (21000, 'none'))
            with self.assertRaises(FileExistsError):
                call()
            code, lines = call('--skip-existing')
            self.assertEqual(code, 0)
            self.assertEqual({line['status'] for line in lines}, {'skipped'})
            self.assertEqual({r for line in lines for r in line['reasons']}, {'result envelope exists'})


if __name__ == '__main__':
    unittest.main()
