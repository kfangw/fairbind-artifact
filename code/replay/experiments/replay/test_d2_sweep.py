"""d2_sweep: every v_max under every sales cap rule, resumable."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import d2_sweep  # noqa: E402
import inputs  # noqa: E402
import test_replay as tr  # noqa: E402


class SweepDriver(unittest.TestCase):
    """d2_sweep: every v_max under every rule, resumable, same files as an uninterrupted run."""

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

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def argv(self, out, *extra):
        return ['--settlements', str(self.s['csv']), '--conditions-file', str(self.conditions), '--reference-dir',
                str(self.s['dir']), '--prior-settlements', str(self.prior_csv), '--out', str(out), '--draws', '2', *extra]

    def test_configurations_and_a_stopped_run_continues_to_the_same_files(self):
        one = Path(self.tmp.name) / 'sweep_one'
        two = Path(self.tmp.name) / 'sweep_two'
        sub = ['--vmax', '0.1,1', '--modes', 'auto-zero-reject,prior14']
        self.assertEqual(d2_sweep.main(self.argv(one, *sub)), 0)
        tags = sorted(p.name for p in one.iterdir() if p.is_dir() and not p.name.startswith('.'))
        self.assertEqual(tags, ['base_v0.1_auto-zero-reject', 'base_v0.1_prior14', 'base_v1_auto-zero-reject', 'base_v1_prior14'])
        for t in tags:
            env = json.loads((one / t / 'run.json').read_text())
            self.assertEqual(env['design2']['vmax_usdc'], t.split('_')[1][1:])
            self.assertEqual(env['design2']['sales_cap'], t.split('_')[2])
        # a time limit that is already used up stops before any address, the next call finishes
        self.assertEqual(d2_sweep.main(self.argv(two, '--time-limit', '-1', *sub)), d2_sweep.STOPPED)
        self.assertFalse(any((two / t / 'run.json').exists() for t in tags))
        self.assertEqual(d2_sweep.main(self.argv(two, *sub)), 0)
        for t in tags:
            for f in sorted(p.relative_to(one / t) for p in (one / t).rglob('*.csv')):
                self.assertEqual((one / t / f).read_bytes(), (two / t / f).read_bytes(), (t, f))
        # a finished configuration is skipped
        stamp = (two / tags[0] / 'run.json').stat().st_mtime_ns
        self.assertEqual(d2_sweep.main(self.argv(two, *sub)), 0)
        self.assertEqual((two / tags[0] / 'run.json').stat().st_mtime_ns, stamp)

    def test_prior_mode_is_skipped_without_a_prior_list(self):
        out = Path(self.tmp.name) / 'sweep_noprior'
        argv = ['--settlements', str(self.s['csv']), '--conditions-file', str(self.conditions), '--reference-dir',
                str(self.s['dir']), '--out', str(out), '--draws', '2', '--vmax', '0.2']
        self.assertEqual(d2_sweep.main(argv), 0)
        note = json.loads((out / 'sweep.json').read_text())
        self.assertEqual([s['tag'] for s in note['skipped']], ['base_v0.2_prior14'])
        self.assertTrue((out / 'base_v0.2_auto-zero-reject' / 'run.json').exists())
        self.assertFalse((out / 'base_v0.2_prior14' / 'run.json').exists())


if __name__ == '__main__':
    unittest.main()
