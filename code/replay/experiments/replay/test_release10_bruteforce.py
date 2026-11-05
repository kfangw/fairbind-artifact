"""Independent check of the edition-10 release: the brute-force simulator bf10_sim (standard library, written apart
from release10.py) against release10.epoch_release on synthetic sellers, and against the replay.py outputs of
--release fixed10 on the synthetic list (run in a separate process)."""
import csv
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import numpy as np  # noqa: E402

import bf10_sim  # noqa: E402
import design2  # noqa: E402
import release10  # noqa: E402
import test_replay as tr  # noqa: E402

TIMINGS = {
    'main': dict(d_A=100, tau_V=100, T_V=50, T_p=1800, T_c=1800, w_b=300),
    'short': dict(d_A=100, tau_V=100, T_V=50, T_p=300, T_c=300, w_b=300),
    'long': dict(d_A=100, tau_V=100, T_V=50, T_p=7200, T_c=7200, w_b=300),
    'prompt': dict(d_A=100, tau_V=100, T_V=50, T_p=1800, T_c=1800, w_b=300, proof_delay=30),
    'keeper_bind': dict(d_A=60, tau_V=20, T_V=10, T_p=500, T_c=100, w_b=700, keeper=3),
}


def to_timing(t, accept_ppm=0, unsigned_ppm=0):
    return release10.Timing10(anchor_delay=t['d_A'], vrf_response=t['tau_V'], vrf_slack=t['T_V'],
                              proof_window=t['T_p'], dispute_window=t['T_c'], bind_window=t['w_b'],
                              proof_delay=t.get('proof_delay'), keeper_delay=t.get('keeper', 0),
                              accept_ppm=accept_ppm, unsigned_ppm=unsigned_ppm)


def synthetic_seller(seed, n, span, p_sample, p_accept, p_unsigned):
    rng = random.Random(seed)
    sales = []
    for _ in range(n):
        signed = rng.random() >= p_unsigned
        sales.append(dict(block=1000 + rng.randrange(span), value=rng.randrange(1, 5000),
                          sampled=rng.random() < p_sample, signed=signed,
                          accepted=signed and rng.random() < p_accept))
    sales.sort(key=lambda s: s['block'])
    return sales


class FunctionLevel(unittest.TestCase):
    """Release blocks and held money at every block for a handful of synthetic sellers."""

    SELLERS = [
        dict(seed=1, n=40, span=3000, p_sample=0.1, p_accept=0.0, p_unsigned=0.0),
        dict(seed=2, n=200, span=6000, p_sample=0.05, p_accept=0.5, p_unsigned=0.0),
        dict(seed=3, n=120, span=20000, p_sample=0.3, p_accept=0.9, p_unsigned=0.2),
        dict(seed=4, n=15, span=900, p_sample=0.0, p_accept=0.3, p_unsigned=0.5),
        dict(seed=5, n=300, span=4000, p_sample=0.02, p_accept=0.0, p_unsigned=0.3),
        dict(seed=6, n=60, span=12000, p_sample=1.0, p_accept=0.5, p_unsigned=0.0),
    ]

    def test_release_and_held_money(self):
        checked = 0
        for spec in self.SELLERS:
            sales = synthetic_seller(**spec)
            blocks = np.array([s['block'] for s in sales], dtype=np.int64)
            values = np.array([s['value'] for s in sales], dtype=np.int64)
            for name, t in TIMINGS.items():
                p = dict(t, origin=1000, epoch_blocks=300)
                paid, held = bf10_sim.simulate(sales, p)
                rel, _ = release10.epoch_release(
                    blocks, (blocks - 1000) // 300, [s['sampled'] for s in sales], [s['accepted'] for s in sales],
                    [s['signed'] for s in sales], lambda e: 1000 + 300 * e, 300, to_timing(t))
                self.assertEqual(rel.tolist(), paid, (spec['seed'], name))
                # held money at every block of the span, from the release array by a direct sum
                for b in range(min(held), max(held) + 1, 7):
                    direct = int(values[(blocks <= b) & (rel > b)].sum())
                    self.assertEqual(held[b], direct, (spec['seed'], name, b))
                checked += 1
        self.assertEqual(checked, len(self.SELLERS) * len(TIMINGS))


class EndToEnd(unittest.TestCase):
    """replay.py --release fixed10 on the synthetic list (separate process) against bf10_sim from the csv."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.d = Path(cls.tmp.name)
        cls.s = tr.synthetic(d)
        config = design2.load_config()
        config['vmax_choices_usdc'] = ['0.01'] + config['vmax_choices_usdc']
        (d / 'design2.json').write_text(json.dumps(config))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_cli(self, name, *extra):
        out = self.d / name
        argv = [sys.executable, str(HERE / 'replay.py'), '--settlements', str(self.s['csv']), '--conditions-file',
                str(self.s['conditions']), '--reference-dir', str(self.s['dir']), '--qx', '137', '--out', str(out),
                '--draws', '1', '--conditions', '1', '--repetitions', '1', '--design', '2', '--d2-config',
                str(self.d / 'design2.json'), '--vmax', '0.01', '--sales-cap', 'auto-zero-reject',
                '--release', 'fixed10', '--freeze-scope', 'detected-onward', *extra]
        res = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stderr[-2000:])
        return out / 'condition-01-seed-0'

    def compare(self, name, timing, accept_ppm=0, unsigned_ppm=0, extra=()):
        cdir = self.run_cli(name, *extra)
        meta = json.loads((cdir / 'condition.json').read_text())
        rounding = meta['design2']['threshold_rounding']
        hour_blocks = int(3600 / float(meta['block_seconds']))
        per, (first, last) = bf10_sim.read_list(self.s['csv'], 10_000, meta['seed'], rounding, accept_ppm,
                                                unsigned_ppm, block_col='block_number', value_col='value_atomic')
        with open(cdir / 'addresses_observed.csv', newline='') as fh:
            rows = {r['address']: r for r in csv.DictReader(fh)}
        p = dict(timing, origin=first, epoch_blocks=300)
        n = 0
        for a, r in rows.items():
            sales = per.get(a, [])
            self.assertEqual(int(r['accepted_count']), len(sales), a)      # auto-zero-reject: every in-cap sale
            if not sales:
                continue
            got, _ = bf10_sim.address_stats(sales, p, first, last, meta['hold_blocks'], hour_blocks)
            for c in ('sample_count', 'buyer_accepted_count', 'unsigned_count', 'hold_released_count',
                      'hold_open_count', 'hold_open_value', 'hold_p90', 'hold_max'):
                want = '' if got[c] is None else str(got[c])
                self.assertEqual(r[c], want, (name, a, c))
            for c in ('H_time_average', 'hold_mean', 'hold_value_mean'):
                if got[c] is None:
                    self.assertEqual(r[c], '', (name, a, c))
                else:
                    self.assertAlmostEqual(float(r[c]), got[c], delta=1e-9 * max(1.0, abs(got[c])), msg=(name, a, c))
            n += 1
        self.assertGreater(n, 20)
        return n

    def test_main(self):
        self.compare('main', TIMINGS['main'])

    def test_acceptance_and_unsigned(self):
        self.compare('acc', TIMINGS['main'], 500_000, 300_000,
                     ('--r10-accept-ppm', '500000', '--r10-unsigned-ppm', '300000'))

    def test_short_with_binding_w_e(self):
        t = dict(TIMINGS['short'], T_c=100, w_b=700)
        self.compare('short', t, 900_000, 500_000,
                     ('--r10-proof-window', '300', '--r10-dispute-window', '100', '--r10-bind-window', '700',
                      '--r10-accept-ppm', '900000', '--r10-unsigned-ppm', '500000'))

    def test_long_prompt_keeper(self):
        t = dict(TIMINGS['long'], proof_delay=30, keeper=2)
        self.compare('long', t, extra=('--r10-proof-window', '7200', '--r10-dispute-window', '7200',
                                       '--r10-proof-delay', '30', '--r10-keeper-delay', '2'))


if __name__ == '__main__':
    unittest.main()
