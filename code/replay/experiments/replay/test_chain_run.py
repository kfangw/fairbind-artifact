"""A design-2 run on a list built by chain_inputs: base58 addresses, a 0.4 s slot, the chain switches."""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import d2_report  # noqa: E402
import test_replay as tr  # noqa: E402
from d2_testlib import ChainListFixture  # noqa: E402


class ChainRun(ChainListFixture, unittest.TestCase):
    def test_the_run_goes_through_with_the_chain_time(self):
        out, env = self.run_replay('sol', '--vmax', '0.2', '--sales-cap', 'auto-zero-reject')
        self.assertEqual(env['operating_point_errors'], [])
        d2 = env['design2']
        self.assertEqual((d2['chain']['name'], d2['chain']['block_seconds'], d2['hold_blocks']), ('solana', '0.4', 155_365))
        self.assertEqual(d2['chain']['address_case'], 'keep')
        meta = json.loads((out / 'condition-01-seed-0' / 'condition.json').read_text())
        self.assertEqual(meta['hold_blocks'], 155_365)
        self.assertEqual(meta['failure_window_alignment'], 'absolute')
        self.assertTrue(all(int(e) % 155_365 == 0 for e in meta['failure_window_edges']))
        self.assertEqual(meta['failure_windows_complete'], len(meta['failure_window_edges']) - 1)
        rows = d2_report.read_csv(out / 'condition-01-seed-0' / 'addresses_observed.csv')
        names = {r['address'] for r in rows}
        self.assertIn(self.addresses[0], names)
        self.assertIn(self.addresses[1], names)                       # the two that differ in case only
        self.assertEqual(sum(int(r['rate_rejected_count']) for r in rows), 0)
        self.assertEqual(env['parameters']['profile_overrides']['overrides'] is not None, True)

    def test_polygon_style_chain_flag_and_block_time_override(self):
        out, env = self.run_replay('sol_bt', '--vmax', '0.1', '--sales-cap', '300', '--block-time', '0.3')
        self.assertEqual(env['design2']['hold_blocks'], 207_154)
        self.assertEqual(env['design2']['chain']['block_seconds'], '0.3')
        rows = d2_report.read_csv(out / 'condition-01-seed-0' / 'addresses_observed.csv')
        self.assertEqual({r['sales_cap_S'] for r in rows}, {'300'})
        self.assertEqual({r['k_address'] for r in rows}, {'19'})

    def test_the_chain_flags_need_design_two(self):
        with self.assertRaises(SystemExit):
            tr.run_cli(['--settlements', str(self.list_csv), '--conditions-file', str(self.out / 'conditions_solana.json'),
                        '--reference-dir', str(self.out / 'ref'), '--qx', '137', '--out', str(self.root / 'x'),
                        '--chain', 'solana'])


if __name__ == '__main__':
    unittest.main()
