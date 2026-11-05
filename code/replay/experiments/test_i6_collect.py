"""Tests of experiments/collect_run.py on the run fixtures of testdata/i6_collect (build.py writes them)."""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect_run  # noqa: E402
from controller import runner, scenario  # noqa: E402

FIXTURES = HERE / 'testdata' / 'i6_collect'


def collect(run_dir, **kw):
    inputs = collect_run.load_inputs(run_dir, Path(run_dir) / 'ground-truth.json', **kw)
    return collect_run.collect(inputs)


def item(doc, name):
    return next(i for i in doc['metrics']['fault_observed'] if i['item'] == name)


class Scratch(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def copy(self, name):
        dst = self.tmp / name
        shutil.copytree(FIXTURES / name, dst)
        return dst


class CheaterMetrics(unittest.TestCase):
    """The cheater fixture, worked out by hand (build.py documents the events).

    g = v = 10,000; B = 4,000,000, k = 16, B/k = 250,000. Episode 1 holds n1, n2, n3 (all bad, all
    lost: n1 paid from the pool, n2 refunded, n3 forfeited) and a 250,000 deduction; episode 2 holds
    n4 and n5, both released.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = collect(FIXTURES / 'cheater')
        cls.m = cls.doc['metrics']

    def test_exposure_and_net_gain(self):
        m = self.m
        self.assertEqual(m['released_exposure'], 20000)
        self.assertEqual(m['episode_exposure'], [0, 20000])
        # Episode 1: 3 * (g - v) - 250,000; episode 2: 2 * g.
        self.assertEqual(m['episode_net_gain'], [-250000, 20000])
        self.assertEqual(m['second_episode_exposure'], 20000)
        self.assertEqual(m['second_episode_net_gain'], 20000)
        # Every bad sale adds g (5 * 10,000), the three lost entries cost v, minus the deduction.
        self.assertEqual(m['cheater_net_gain'], 50000 - 30000 - 250000)
        self.assertEqual(m['exposure_vs_bond'], 20000 / 4000000)
        self.assertEqual(m['seller_penalty_charged'], 250000)
        self.assertEqual(m['post_detection_leak'], [0, 0])
        self.assertEqual(m['releases_after_reentry'], 2)
        self.assertEqual(m['y_f'], [])

    def test_episodes_and_detection(self):
        m = self.m
        self.assertEqual(m['episode_end_mode'], ['with_detection', 'open'])
        self.assertEqual(m['episode_end_block'], [2000, None])
        self.assertEqual(m['first_detection_index'], [dict(K=2, censored=False), dict(K=2, censored=True)])
        # Epochs 0 and 17 are sealed; n2 of the five bad sales is detected; n2 and n5 are sampled.
        self.assertEqual(m['realized_detection_rate'], 0.2)
        self.assertEqual(m['realized_sample_rate'], 0.4)
        self.assertEqual(m['final_failure_count'], 1)
        self.assertEqual(m['wrongful_final_fail_count'], 0)
        self.assertEqual(m['suspension_count'], 1)
        self.assertEqual(m['reinstatement_count'], 1)

    def test_case_path_and_keeper_delay(self):
        m = self.m
        # n2 settled at 120 and was confirmed at 2000; finalizeCase due 1900 landed at 2000, the
        # epoch's anchor landed when due, and a call whose transaction left no event is not counted.
        self.assertEqual(m['case_path_blocks'], [1880])
        self.assertEqual(m['keeper_delay_sum_blocks'], [100])
        self.assertEqual(m['case_path_minus_keeper'], [1780])
        self.assertEqual(m['keeper_delay_sum_max_blocks'], 100)
        self.assertEqual(m['worst_path_case_blocks'], [])
        case = self.doc['cases'][0]
        self.assertEqual(case['keeper_calls_unresolved'], 1)
        self.assertEqual(case['case_delay_kappa_sigma'], 100)
        self.assertTrue(item(self.doc, 'kappa_sigma')['ok'])

    def test_buyer_columns(self):
        m = self.m
        self.assertEqual(m['buyer_refund_paid'], [20000, 0])
        self.assertEqual(m['buyer_refund_paid_blocks'], [2100, 1980])
        self.assertEqual(m['buyer_unrecovered_amount'], [10000, 20000])
        self.assertEqual(m['recovery_time_blocks'], [2100, 1980])
        self.assertEqual(m['judgment_delay_distribution'], [1880, 1700])
        self.assertEqual(m['frozen_amount'], [20000])
        self.assertEqual(m['freeze_delay_blocks'], [1880])

    def test_rates_and_profile(self):
        m = self.m
        # Active from 100 to 70,000 except the suspension from 2000 to 5100.
        self.assertEqual(m['achieved_settlement_rate'], 5 / (1900 + 64901))
        self.assertEqual(m['configured_settlement_rate'], 0.05)
        self.assertEqual(m['effective_hold_period_blocks'], 60000)
        self.assertEqual(m['freeze_on_initial_fail'], 0)
        self.assertEqual(m['operating_point_k'], 16)
        run = self.doc['run']
        self.assertEqual((run['t_hold'], run['t_case'], run['deduction']), (60000, 58994, 250000))

    def test_verifiers(self):
        m = self.m
        self.assertEqual(m['verifier_registered_count'], 4)
        self.assertEqual(m['verifier_assignable_count'], 3)
        self.assertEqual(m['verifier_min_bond_ok'], 1)
        self.assertEqual(m['verifier_removed_count'], 1)
        self.assertEqual(m['verifier_removal_rate_per_case'], 0.5)
        self.assertEqual(m['verifier_replacement_count'], 1)
        # Three assignable verifiers, one removed at 3000, replaced at 3001.
        self.assertEqual(m['assignable_min_between_removal_and_replacement'], [2])
        self.assertTrue(item(self.doc, 'replacement_next_block')['ok'])
        self.assertEqual(m['assignment_failure'], [])

    def test_verdict_counts(self):
        self.assertEqual(self.m['verdict_counts_by_truth'], [
            dict(truth='bad', stage='final', PASS=1, FAIL=1, INCONCLUSIVE=0, UNSERVED=0),
            dict(truth='bad', stage='initial', PASS=1, FAIL=1, INCONCLUSIVE=0, UNSERVED=0)])

    def test_fault_observed_passes(self):
        for i in self.m['fault_observed']:
            self.assertTrue(i['ok'], i)
        self.assertFalse(item(self.doc, 'bad_responses')['applicable'])
        self.assertEqual(self.m['injection_draw_mismatch_count'], 0)


class FiniteAttack(unittest.TestCase):
    def test_switch_detected(self):
        doc = collect(FIXTURES / 'finite_switch')
        m = doc['metrics']
        # f2 (a bad sale) is confirmed at 1500, before 130 + T_hold + T_case; nothing was released.
        self.assertEqual(m['episode_end_mode'], ['with_detection'])
        self.assertEqual(m['episode_end_block'], [1500])
        self.assertEqual(m['y_f'], [0 - 250000])
        # Frozen: two bad (g - v = 0) and two honest (-v each), and the deduction.
        self.assertEqual(m['episode_net_gain'], [-20000 - 250000])
        self.assertEqual(m['post_switch_confirmed_failures'], [dict(FAIL=0, UNSERVED=0)])
        self.assertEqual(m['first_detection_index'], [dict(K=2, censored=False)])
        self.assertEqual(doc['episodes'][0]['charged_deduction'], 250000)
        for i in m['fault_observed']:
            self.assertTrue(i['ok'], i)
        self.assertTrue(item(doc, 'bad_responses')['applicable'])
        self.assertTrue(item(doc, 'post_switch_no_confirmed_failure')['applicable'])

    def test_exit_without_detection(self):
        m = collect(FIXTURES / 'finite_exit')['metrics']
        self.assertEqual(m['episode_end_mode'], ['without_detection'])
        self.assertEqual(m['episode_end_block'], [100 + 60000 + 58994])
        self.assertEqual(m['y_f'], [10000])
        self.assertEqual(m['seller_exit_finalized_block'], [60050])
        self.assertEqual(m['seller_exit_deferred_entries'], [1])
        self.assertEqual(m['bond_exit_finalized_block'], [60200])
        self.assertEqual(m['bond_exit_deferred_balance'], [0])
        self.assertEqual(m['bond_exit_open_sampled_cases'], [0])
        self.assertEqual(m['buyer_unrecovered_amount'], [10000])
        self.assertEqual(m['post_switch_confirmed_failures'], [])

    def test_open_episode_before_the_end_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp) / 'run'
            shutil.copytree(FIXTURES / 'finite_exit', run)
            led = json.loads((run / 'ledger.json').read_text())
            led['viewBlock'] = led['toBlock'] = 119093
            (run / 'ledger.json').write_text(json.dumps(led))
            m = collect(run)['metrics']
            self.assertEqual(m['episode_end_mode'], ['open'])
            self.assertEqual(m['y_f'], [None])


class HonestArm(unittest.TestCase):
    def test_windows(self):
        m = collect(FIXTURES / 'honest')['metrics']
        # Start 100 (workload summary) + T_hold; the window from 180,100 is cut off at 185,000.
        self.assertEqual(m['honest_windows'], [
            dict(start=60100, end=120099, wrongful_confirmed_failures=1, sanctioned=0),
            dict(start=120100, end=180099, wrongful_confirmed_failures=0, sanctioned=0)])
        self.assertEqual(m['honest_sanctions_per_window'], 0)
        self.assertEqual(m['wrongful_final_fail_per_sampled_case'], 0.5)
        self.assertEqual(m['wrongful_final_fail_count'], 1)
        self.assertEqual(m['false_positive_recovery_amount'], 10000)
        self.assertEqual(m['honest_top_up_count'], 1)
        self.assertEqual(m['honest_max_window_scale'], 1)
        self.assertEqual(m['honest_seller_delay_blocks'], [60000, 60000])
        self.assertEqual(m['y_f'], [])


class InjectionDraw(unittest.TestCase):
    def test_known_answer_of_the_verifier(self):
        # services/verifier/injected_test.go: seed 20260928, nonce 0x00..0x1f, stage 1, attempt 2.
        nonce = '0x' + bytes(range(32)).hex()
        self.assertEqual(collect_run.injection_draw(20260928, nonce, 1, 2, 'honesty'), 651185476401093 / 2 ** 53)
        self.assertEqual(collect_run.injection_draw(20260928, nonce, 1, 2, 'outcome'), 656817053007810 / 2 ** 53)

    def test_every_field_enters_the_digest(self):
        nonce = '0x' + bytes(range(32)).hex()
        other = '0x' + bytes(range(1, 33)).hex()
        base = collect_run.injection_draw(20260928, nonce, 1, 2, 'honesty')
        for args in ((20260929, nonce, 1, 2, 'honesty'), (20260928, other, 1, 2, 'honesty'),
                     (20260928, nonce, 2, 2, 'honesty'), (20260928, nonce, 1, 3, 'honesty'),
                     (20260928, nonce, 1, 2, 'outcome')):
            self.assertNotEqual(collect_run.injection_draw(*args), base, args)

    def test_rule(self):
        p = dict(h=0.5, alpha=0.2, beta=0.3, c=0.4)
        self.assertEqual(collect_run.injected_verdict(p, 'FAIL', 0.1, 0.29), (True, 'beta', 'PASS'))
        self.assertEqual(collect_run.injected_verdict(p, 'FAIL', 0.1, 0.3), (True, 'beta', 'FAIL'))
        self.assertEqual(collect_run.injected_verdict(p, 'PASS', 0.1, 0.19), (True, 'alpha', 'FAIL'))
        self.assertEqual(collect_run.injected_verdict(p, 'FAIL', 0.5, 0.0), (False, 'none', 'PASS'))
        self.assertEqual(collect_run.injected_verdict(p, 'PASS', 0.9, 0.39), (False, 'c', 'FAIL'))
        off = dict(p, honestErrorOff=True)
        self.assertEqual(collect_run.injected_verdict(off, 'PASS', 0.1, 0.0), (True, 'alpha', 'PASS'))
        self.assertEqual(collect_run.injected_verdict(off, 'PASS', 0.9, 0.0), (False, 'c', 'PASS'))


class Mismatches(Scratch):
    def records(self, run):
        return sorted(run.rglob('injection/*.json'))

    def test_changed_draw_is_flagged(self):
        run = self.copy('finite_switch')
        path = self.records(run)[0]
        rec = json.loads(path.read_text())
        rec['outcomeDraw'] = rec['outcomeDraw'] / 2
        path.write_text(json.dumps(rec))
        doc = collect(run)
        self.assertEqual(doc['metrics']['injection_draw_mismatch_count'], 1)
        self.assertEqual(doc['injection']['draw_mismatches'][0]['field'], 'outcomeDraw')
        self.assertFalse(item(doc, 'injection_log')['ok'])

    def test_changed_verdict_and_seed_are_flagged(self):
        run = self.copy('finite_switch')
        path = self.records(run)[0]
        rec = json.loads(path.read_text())
        rec['verdict'] = 'PASS' if rec['verdict'] == 'FAIL' else 'FAIL'
        rec['seed'] += 1
        path.write_text(json.dumps(rec))
        doc = collect(run)
        fields = sorted(x['field'] for x in doc['injection']['draw_mismatches'])
        self.assertIn('seed', fields)
        self.assertIn('verdict', fields)
        self.assertIn('honestyDraw', fields)
        self.assertEqual(len(doc['injection']['disagreeing_verdicts']), 1)
        self.assertFalse(item(doc, 'injection_log')['ok'])

    def test_missing_record_and_wrong_predicate(self):
        run = self.copy('cheater')
        records = self.records(run)
        records[0].unlink()
        rec = json.loads(records[1].read_text())
        rec['predicateVerdict'] = 'PASS'
        records[1].write_text(json.dumps(rec))
        doc = collect(run)
        self.assertEqual(len(doc['injection']['unrecorded_verdicts']), 1)
        self.assertFalse(item(doc, 'injection_log')['ok'])
        self.assertFalse(item(doc, 'predicate_matches_truth')['ok'])

    def test_cheated_sales_differ_from_ground_truth(self):
        run = self.copy('finite_switch')
        path = next(run.rglob('meta/attack.json'))
        attack = json.loads(path.read_text())
        attack['cheated'] = attack['cheated'][:1]
        path.write_text(json.dumps(attack))
        self.assertFalse(item(collect(run), 'bad_responses')['ok'])

    def test_keeper_delay_off_budget(self):
        run = self.copy('cheater')
        gt = json.loads((run / 'ground-truth.json').read_text())
        gt['parameters']['keeper_delay_budget_blocks'] = 50
        (run / 'ground-truth.json').write_text(json.dumps(gt))
        self.assertFalse(item(collect(run), 'kappa_sigma')['ok'])

    def test_late_replacement(self):
        run = self.copy('cheater')
        led = json.loads((run / 'ledger.json').read_text())
        for e in led['events']:
            if e['event'] == 'VerifierRegistered' and e['args']['verifierId'] == 5:
                e['block'] = 3005
        (run / 'ledger.json').write_text(json.dumps(led))
        doc = collect(run)
        self.assertFalse(item(doc, 'replacement_next_block')['ok'])
        self.assertFalse(doc['verifiers']['replacements'][0]['next_block'])


class WorstPathMissed(Scratch):
    def worst_run(self):
        run = self.copy('cheater')
        gt = json.loads((run / 'ground-truth.json').read_text())
        gt['parameters']['judgment_path'] = 'worst'
        (run / 'ground-truth.json').write_text(json.dumps(gt))
        return run

    def test_missed_row_is_flagged(self):
        run = self.worst_run()
        before = item(collect(run), 'worst_path_structure')
        self.assertNotIn('missed their block', before['reason'])
        with (run / 'proc' / 'keeper' / 'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event='worst_path_missed', action='openSample', key='openSample:0xab',
                                    nonce='0xab', target_block=2200, expected_block=2202, lateness_blocks=2,
                                    sent=True, reason='the head passed the target block')) + '\n')
        after = item(collect(run), 'worst_path_structure')
        self.assertTrue(after['applicable'])
        self.assertFalse(after['ok'])
        self.assertIn('1 worst-path calls missed their block (lateness [2] blocks)', after['reason'])

    def test_late_open_sample_transaction_is_flagged(self):
        run = self.worst_run()
        led = json.loads((run / 'ledger.json').read_text())
        opened = next(e for e in led['events'] if e['event'] == 'CaseOpened')
        with (run / 'proc' / 'keeper' / 'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(event='call_sent', status='sent', action='openSample', key='openSample:x',
                                    tx=opened['tx'], due=opened['block'] - 3, nonce=opened['args']['nonce'])) + '\n')
        after = item(collect(run), 'worst_path_structure')
        self.assertFalse(after['ok'])
        self.assertIn('lateness [3] blocks', after['reason'])


class AssignmentFailure(Scratch):
    def test_stage_without_an_eligible_verifier(self):
        run = self.copy('cheater')
        led = json.loads((run / 'ledger.json').read_text())
        n4 = led['views']['purchases'][3]['nonce']
        led['events'] += [
            dict(block=6100, logIndex=5, tx='0x' + '01' * 32, event='CaseOpened',
                 args=dict(nonce=n4, trigger=1, requester='0x' + '00' * 20, heldValue='10000')),
            dict(block=6100, logIndex=6, tx='0x' + '01' * 32, event='VerifierAssigned',
                 args=dict(nonce=n4, stage=1, attempt=0, verifierId=2, deadline=6400)),
            dict(block=6401, logIndex=0, tx='0x' + '02' * 32, event='Slashed',
                 args=dict(actorType=2, actorId=2, nonce=n4, recipient='0x' + '00' * 20, amount='1', reason=2)),
            dict(block=6401, logIndex=1, tx='0x' + '02' * 32, event='CaseFinalized',
                 args=dict(nonce=n4, finalVerdict=3, financialState=6))]
        led['views']['purchases'][3]['case'].update(stateName='INCONCLUSIVE', finalVerdict=3, trigger=1, stage=1,
                                                    requesterRole=2)
        (run / 'ledger.json').write_text(json.dumps(led))
        m = collect(run)['metrics']
        # The assignable count at the failure block: the fixture's three assignable verifiers.
        self.assertEqual(m['assignment_failure'], [dict(nonce=n4, stage='initial', cause='liability_or_draw', block=6401,
                                                        assignable_count=3)])
        # Only verifier 2, already on the case, in the epoch's checkpoint: participation.
        led['views']['profiles'][0]['checkpoints'][1]['verifierIds'] = [2]
        (run / 'ledger.json').write_text(json.dumps(led))
        doc = collect(run)
        self.assertEqual(doc['metrics']['assignment_failure'][0]['cause'], 'participation')
        self.assertEqual(doc['assignment_failures'][0]['attempt'], 1)


class OptionalInputs(Scratch):
    def test_only_required_inputs(self):
        run = self.copy('cheater')
        for rel in ('proc', 'workload', 'pool'):
            shutil.rmtree(run / rel, ignore_errors=True)
        doc = collect(run)
        m = doc['metrics']
        self.assertEqual(m['released_exposure'], 20000)
        self.assertNotIn('configured_settlement_rate', m)
        self.assertEqual(m['keeper_delay_sum_blocks'], [0])
        # Without the deployment every verifier registered before the first settlement counts, the
        # one at minVerifierBond included.
        self.assertEqual(m['verifier_registered_count'], 4)
        self.assertEqual(m['verifier_min_bond_ok'], 0)
        self.assertFalse(item(doc, 'injection_log')['applicable'])
        self.assertFalse(item(doc, 'kappa_sigma')['ok'])
        for name in ('deployment', 'keeper_events', 'seller_policy', 'workload_summary', 'pool_replacements'):
            self.assertFalse(doc['sources'][name]['present'], name)

    def test_required_inputs(self):
        run = self.copy('cheater')
        (run / 'shared' / 'profile.json').unlink()
        with self.assertRaises(collect_run.InputError):
            collect(run)
        run = self.copy('honest')
        doc = json.loads((run / 'ground-truth.json').read_text())
        doc['bad_sales_rule'] = None
        (run / 'ground-truth.json').write_text(json.dumps(doc))
        with self.assertRaises(collect_run.InputError):
            collect(run)
        self.assertEqual(collect_run.main(['--run-dir', str(run), '--ground-truth', str(run / 'ground-truth.json'),
                                           '--out', str(self.tmp / 'x.jsonl')]), 2)

    def test_optional_files_are_read(self):
        run = self.copy('honest')
        pool = run / 'proc' / 'verifier' / 'pool'
        pool.mkdir(parents=True)
        (pool / 'replacements.jsonl').write_text('')
        doc = collect(run)
        self.assertEqual(doc['workload_summary']['blocks']['start'], 100)
        self.assertEqual(doc['pool_replacements'], dict(lines=0, matches_ledger=True))
        self.assertEqual(doc['sources']['pool_replacements']['path'], 'proc/verifier/pool/replacements.jsonl')

    def test_honest_first_window(self):
        sales = [dict(settled_block=500)]
        self.assertEqual(collect_run.honest_first_window(
            dict(blocks=dict(start=100), honest_windows=dict(first_window_start=777)), sales, 60000), 777)
        self.assertEqual(collect_run.honest_first_window(dict(blocks=dict(start=100)), sales, 60000), 60100)
        self.assertEqual(collect_run.honest_first_window(None, sales, 60000), 60500)
        self.assertIsNone(collect_run.honest_first_window(None, [], 60000))


class LedgerSource(Scratch):
    def test_ledger_override(self):
        run = self.copy('cheater')
        led = self.tmp / 'elsewhere.json'
        (run / 'ledger.json').rename(led)
        with self.assertRaises(collect_run.InputError):
            collect(run)
        self.assertEqual(collect(run, ledger=led)['metrics']['released_exposure'], 20000)

    def test_dump_command(self):
        run = self.copy('cheater')
        saved = self.tmp / 'saved.json'
        (run / 'ledger.json').rename(saved)
        fake = self.tmp / 'fake-dump'
        fake.write_text('#!/usr/bin/env python3\nimport shutil, sys\na = sys.argv\n'
                        f'assert a[a.index("-rpc") + 1] == "http://127.0.0.1:1"\n'
                        f'shutil.copy({str(saved)!r}, a[a.index("-out") + 1])\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        old = os.environ.get('FAIRBIND_LEDGER_DUMP')
        os.environ['FAIRBIND_LEDGER_DUMP'] = str(fake)
        try:
            doc = collect(run, rpc_url='http://127.0.0.1:1')
        finally:
            if old is None:
                del os.environ['FAIRBIND_LEDGER_DUMP']
            else:
                os.environ['FAIRBIND_LEDGER_DUMP'] = old
        self.assertTrue((run / 'ledger.json').exists())
        self.assertEqual(doc['metrics']['released_exposure'], 20000)

    def test_wrong_format(self):
        run = self.copy('cheater')
        led = json.loads((run / 'ledger.json').read_text())
        led['format'] = 'other/v1'
        (run / 'ledger.json').write_text(json.dumps(led))
        with self.assertRaises(collect_run.InputError):
            collect(run)


class Output(Scratch):
    def run_main(self, name, out):
        run = FIXTURES / name
        code = collect_run.main(['--rpc-url', 'http://127.0.0.1:1', '--run-dir', str(run),
                                 '--ground-truth', str(run / 'ground-truth.json'), '--out', str(out)])
        self.assertEqual(code, 0)
        return out.read_bytes(), out.with_suffix('.json').read_bytes()

    def test_deterministic(self):
        for name in ('cheater', 'finite_switch', 'finite_exit', 'honest'):
            first = self.run_main(name, self.tmp / 'a' / f'{name}.jsonl')
            second = self.run_main(name, self.tmp / 'b' / f'{name}.jsonl')
            self.assertEqual(first, second, name)
            doc = json.loads(first[1])
            self.assertEqual(doc['format'], 'fairbind-run-observations/v1')
            self.assertEqual(first[1].decode(), json.dumps(doc, sort_keys=True) + '\n')
            metrics = [json.loads(line)['metric'] for line in first[0].decode().splitlines()]
            self.assertEqual(metrics, sorted(metrics))

    def test_rows_are_accepted_by_the_runner(self):
        out = self.tmp / 'observations'
        for name in ('cheater', 'finite_switch', 'finite_exit', 'honest'):
            shutil.rmtree(out, ignore_errors=True)
            self.run_main(name, out / 'collector.jsonl')
            wanted = sorted(set(scenario.metric_ids()))
            metrics, missing, bad = runner.collect_metrics(out, wanted)
            self.assertEqual(bad, [], name)
            emitted = {json.loads(line)['metric'] for line in (out / 'collector.jsonl').read_text().splitlines()}
            self.assertTrue(emitted <= set(wanted), emitted - set(wanted))
            self.assertTrue(metrics['fault_observed']['observed'])

    def test_every_new_column_is_emitted(self):
        columns = ('y_f', 'episode_end_mode', 'episode_end_block', 'verifier_registered_count',
                   'verifier_min_bond_ok', 'verifier_removed_count', 'verifier_replacement_count',
                   'assignable_min_between_removal_and_replacement', 'assignment_failure',
                   'post_switch_confirmed_failures', 'seller_exit_finalized_block', 'bond_exit_finalized_block',
                   'bond_exit_deferred_balance', 'bond_exit_open_sampled_cases', 'buyer_unrecovered_amount',
                   'honest_windows', 'operating_point_k', 'fault_observed')
        for name in ('cheater', 'finite_switch', 'finite_exit', 'honest'):
            m = collect(FIXTURES / name)['metrics']
            for c in columns:
                self.assertIn(c, m, (name, c))


if __name__ == '__main__':
    unittest.main()


class RunDataGaps(Scratch):
    def test_rejected_settlements_and_detection_eligible(self):
        run = self.copy('cheater')
        doc = collect(run)
        self.assertNotIn('rejected_settlement_count', doc['metrics'])  # no attempt store in the fixture
        # detection_eligible: sealed epoch, sampling window ended by the view block, no or terminal case.
        for r in doc['sales']:
            self.assertIsInstance(r['detection_eligible'], bool)
            if r['detection_eligible']:
                self.assertTrue(r['case_state'] is None or r['case_state'] in collect_run.TERMINAL_CASE_STATES)
        eligible_bad = sum(1 for r in doc['sales'] if r['bad'] and r['detection_eligible'])
        self.assertLessEqual(eligible_bad, sum(1 for r in doc['sales'] if r['bad']))
        attempts = run / 'proc' / 'deploy' / 'services' / 'facilitator' / 'data' / 'attempts'
        attempts.mkdir(parents=True)
        for i, (status, revert) in enumerate([('settled', None), ('rejected', 'RateLimitExceeded'),
                                              ('rejected', 'RateLimitExceeded'), ('rejected', 'SellerIsSuspended')]):
            (attempts / f'0x{i:064x}.json').write_text(json.dumps(dict(version=1, nonce=f'0x{i:064x}', status=status,
                                                                       revert=revert, updatedAt=i)))
        doc = collect(run)
        self.assertEqual(doc['metrics']['rejected_settlement_count'], 2)
        self.assertEqual(doc['metrics']['rejected_settlements_by_revert'], dict(RateLimitExceeded=2, SellerIsSuspended=1))

    def test_wall_clock_fields_are_split_off(self):
        run = self.copy('cheater')
        doc = collect(run)
        self.assertNotIn('wall', doc['workload_summary'] or {})
        self.assertTrue(all('sha256' not in s for s in doc['sources'].values()))
        self.assertIn('sources_sha256', doc['nondeterministic'])
