"""The Base-style synthetic list under the second edition of the design-2 rules."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import design2  # noqa: E402
import inputs  # noqa: E402
import replay  # noqa: E402
import test_replay as tr  # noqa: E402


class SecondEditionRun(unittest.TestCase):
    """The Base-style synthetic list under the second edition."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.s = tr.synthetic(d)
        (d / 'prior_dir').mkdir()
        cls.prior_csv = tr.synthetic(d / 'prior_dir', seed=2)['csv']
        cond = json.loads(Path(cls.s['conditions']).read_text())
        cond['inputs']['prior_period']['sha256'] = inputs.sha256_file(cls.prior_csv)
        cls.conditions = d / 'conditions_with_prior.json'
        cls.conditions.write_text(json.dumps(cond, indent=1))
        config = design2.load_config()
        config['vmax_choices_usdc'] = ['0.01'] + config['vmax_choices_usdc']       # the synthetic values are at most 0.05
        cls.config = d / 'design2.json'
        cls.config.write_text(json.dumps(config))
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)

    @classmethod
    def tearDownClass(cls):
        replay.git_state = cls._git
        cls.tmp.cleanup()

    def run_replay(self, name, *extra, draws='3'):
        out = Path(self.tmp.name) / name
        argv = ['--settlements', str(self.s['csv']), '--conditions-file', str(self.conditions), '--reference-dir',
                str(self.s['dir']), '--qx', '137', '--out', str(out), '--draws', draws, '--conditions', '1',
                '--repetitions', '1', '--design', '2', '--d2-config', str(self.config), *extra]
        code, _ = tr.run_cli(argv)
        self.assertEqual(code, 0)
        return out, json.loads((out / 'run.json').read_text())

    def rows(self, out, name='addresses_observed.csv'):
        return list(csv.DictReader(tr._open(out / 'condition-01-seed-0' / name)))

    def test_main_result_rejects_nothing_in_range_and_is_reportable(self):
        out, env = self.run_replay('ed2_main', '--vmax', '0.01', '--sales-cap', 'auto-zero-reject')
        self.assertTrue(env['reportable'], env['not_reportable_reasons'])          # k from the table is not a default breach
        rows = self.rows(out)
        self.assertEqual(sum(int(r['rate_rejected_count']) for r in rows), 0)
        self.assertGreater(sum(int(r['cap_rejected_count']) for r in rows), 0)
        for r in rows:
            self.assertEqual(int(r['deduction_b']), 37_038)             # ceil(37,037.04)
            self.assertEqual(int(r['nB']), int(r['k_address']) * int(r['deduction_b']) * (int(r['sales_cap_S']) // 3245 or 1))
            self.assertIn(r['sales_cap_method'], ('min-zero-insample', 'no-record'))
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual(meta['hold_blocks'], 31_073)
        self.assertEqual(meta['sellerPenalty'], 87 * 37_038)
        self.assertEqual(meta['design2']['threshold_rounding'], 'ceil')
        self.assertEqual(meta['failure_window_alignment'], 'absolute')
        self.assertTrue(all(int(e) % 31_073 == 0 for e in meta['failure_window_edges']))
        self.assertEqual(set(r['setting'] for r in self.rows(out, 'addresses_injection.csv')), {'main', 'w_0.015'})
        self.assertEqual(env['design2']['rule_edition'], 2)
        self.assertIn('sales_cap', env['parameters']['options'])

    def test_prior14_gives_ten_to_addresses_without_a_record(self):
        out, env = self.run_replay('ed2_prior', '--vmax', '0.01', '--sales-cap', 'prior14',
                                   '--prior-settlements', str(self.prior_csv))
        rows = self.rows(out)
        methods = {r['sales_cap_method'] for r in rows}
        self.assertTrue(methods <= {'prior14', 'prior14-no-record'}, methods)
        self.assertTrue(all(r['sales_cap_S'] == '10' for r in rows if r['sales_cap_method'] == 'prior14-no-record'))
        self.assertEqual(env['design2_prior_input']['sha256'], inputs.sha256_file(self.prior_csv))
        with self.assertRaises(SystemExit):
            tr.run_cli(['--settlements', str(self.s['csv']), '--conditions-file', str(self.conditions), '--reference-dir',
                        str(self.s['dir']), '--qx', '137', '--out', str(Path(self.tmp.name) / 'x'), '--draws', '2',
                        '--conditions', '1', '--design', '2', '--d2-config', str(self.config), '--vmax', '0.01',
                        '--sales-cap', 'prior14'])

    def test_the_old_option_name_is_accepted_on_the_command_line(self):
        for name in ('--tau', '--vmax'):
            argv = ['--settlements', 'x', '--reference-dir', 'y', '--qx', '137', '--out', 'z', name, '0.2']
            # the parser is built inside main; check it through the help text and a run that stops at validation
            with self.assertRaises(SystemExit) as ctx:
                replay.main(argv + ['--design', '2', '--d2-edition', '2'])
            self.assertNotEqual(ctx.exception.code, 2)        # not an argument error (2 is argparse's code)

    def test_second_edition_refuses_the_first_edition_hold(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_replay('ed2_hold', '--vmax', '0.1', '--sales-cap', 'auto-zero-reject', '--hold', '30180')
        self.assertIn('hold 30180', str(ctx.exception))

    def test_the_edition_switch_reproduces_the_first_edition_rules(self):
        a, _ = self.run_replay('e1', '--vmax', '0.2', '--d2-edition', '1', '--multiplier-source', 'insample', '--hold', '30180')
        meta = json.loads((a / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual((meta['hold_blocks'], meta['sellerPenalty'], meta['design2']['window_alignment']),
                         (30_180, 20_000_000, 'first-block'))
        # each first-edition rule that the second edition changed has its own switch
        b, _ = self.run_replay('e2_switched', '--vmax', '0.2', '--multiplier-source', 'insample', '--d2-k', '27',
                               '--bond-rule', 'floor-fraction', '--window-align', 'first-block',
                               '--threshold-rounding', 'contract')
        meta_b = json.loads((b / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual((meta_b['hold_blocks'], meta_b['sellerPenalty'], meta_b['design2']['bond_rule'],
                          meta_b['design2']['window_alignment'], meta_b['design2']['threshold_rounding']),
                         (31_073, 20_000_000, 'floor-fraction', 'first-block', 'contract'))
        # with the same hold period and windows the two are the same run
        c, _ = self.run_replay('e1_same_hold', '--vmax', '0.2', '--d2-edition', '1', '--multiplier-source', 'insample',
                               '--hold', '30180', '--failure-window', '30180')
        for f in sorted(p.relative_to(a) for p in a.rglob('*.csv')):
            self.assertEqual((a / f).read_bytes(), (c / f).read_bytes(), f)

    def test_multiplier_source_under_the_second_edition_uses_the_main_cap_times_n(self):
        out, _ = self.run_replay('ed2_mult', '--vmax', '0.2', '--multiplier-source', 'insample')
        for r in self.rows(out):
            self.assertEqual(int(r['sales_cap_S']), 3245 * int(r['scale']))
            self.assertEqual(r['k_address'], '87')
            self.assertEqual(r['sales_cap_method'], 'multiplier')

    def test_d2_k_overrides_the_table(self):
        out, env = self.run_replay('ed2_k', '--vmax', '0.2', '--sales-cap', '100', '--d2-k', '40')
        rows = self.rows(out)
        self.assertEqual({r['k_address'] for r in rows}, {'40'})
        self.assertEqual({int(r['nB']) for r in rows}, {40 * 740_741})
        out, env = self.run_replay('ed2_kw', '--vmax', '0.2', '--sales-cap', '100', '--k-w', '0.004728')
        self.assertEqual({r['k_address'] for r in self.rows(out)}, {'8'})

    def test_injection_settings_switch(self):
        out, _ = self.run_replay('ed2_set', '--vmax', '0.2', '--sales-cap', '300', '--injection-settings', 'main,operator_is_verifier,w_0.015')
        self.assertEqual({r['setting'] for r in self.rows(out, 'addresses_injection.csv')},
                         {'main', 'operator_is_verifier', 'w_0.015'})
        with self.assertRaises(SystemExit):
            self.run_replay('ed2_set2', '--vmax', '0.2', '--sales-cap', '300', '--injection-settings', 'nope')

    def test_confirmation_delay_switch(self):
        a, env_a = self.run_replay('cd_case', '--vmax', '0.01', '--sales-cap', '1000')
        b, env_b = self.run_replay('cd_settle', '--vmax', '0.01', '--sales-cap', '1000', '--confirm-delay', 'settlement')
        meta_a = json.loads((a / 'condition-01-seed-0' / 'condition.json').read_text())
        meta_b = json.loads((b / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual((meta_a['confirm_delay_blocks'], meta_b['confirm_delay_blocks']), (7_512, 30_573))
        self.assertEqual((env_a['design2']['confirm_delay'], env_b['design2']['confirm_delay']), ('case', 'settlement'))
        fa = sum(float(r['failures_mean']) for r in self.rows(a, 'addresses_injection.csv'))
        fb = sum(float(r['failures_mean']) for r in self.rows(b, 'addresses_injection.csv'))
        self.assertLessEqual(fb, fa)
        # the observed columns do not depend on the injection
        self.assertEqual((a / 'condition-01-seed-0' / 'addresses_observed.csv').read_bytes(),
                         (b / 'condition-01-seed-0' / 'addresses_observed.csv').read_bytes())
        with self.assertRaises(SystemExit):
            self.run_replay('cd_ed1', '--vmax', '0.2', '--d2-edition', '1', '--multiplier-source', 'insample',
                            '--confirm-delay', 'settlement')
        with self.assertRaises(SystemExit):
            self.run_replay('cd_bad', '--vmax', '0.01', '--sales-cap', '1000', '--confirm-delay', 'never')

    def test_window_record_in_the_envelope(self):
        a, env = self.run_replay('wr', '--vmax', '0.01', '--sales-cap', '1000')
        meta = json.loads((a / 'condition-01-seed-0' / 'condition.json').read_text())
        w = env['design2_windows']
        self.assertEqual(w['alignment'], 'absolute')
        self.assertEqual(w['failure']['complete_windows'], meta['failure_windows_complete'])
        self.assertEqual(w['failure']['window_blocks'], 31_073)
        self.assertEqual(w['failure']['first_edge'] % 31_073, 0)
        self.assertEqual(w['failure']['last_edge'], meta['failure_window_edges'][-1])
        self.assertEqual(w['failure']['first_edge'], meta['failure_window_edges'][0])
        self.assertEqual(w['judgment']['first_edge'] % 31_073, 0)
        self.assertGreaterEqual(w['judgment']['complete_windows'], w['failure']['complete_windows'])
        self.assertEqual((w['first_block'], w['last_block']), (env['inputs']['settlements']['first_block'],
                                                              env['inputs']['settlements']['last_block']))

    def test_deterministic(self):
        a, _ = self.run_replay('ed2_d1', '--vmax', '1', '--sales-cap', 'auto-zero-reject')
        b, _ = self.run_replay('ed2_d2', '--vmax', '1', '--sales-cap', 'auto-zero-reject')
        for f in sorted(p.relative_to(a) for p in a.rglob('*.csv')):
            self.assertEqual((a / f).read_bytes(), (b / f).read_bytes(), f)


if __name__ == '__main__':
    unittest.main()


if __name__ == '__main__':
    unittest.main()
