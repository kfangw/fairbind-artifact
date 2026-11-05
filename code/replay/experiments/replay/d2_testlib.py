"""Shared helpers of the second-edition design-2 tests."""
import gzip
import json
import random
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import numpy as np  # noqa: E402

import design2  # noqa: E402
import inputs  # noqa: E402
import replay  # noqa: E402
from controller import operating_point as opt  # noqa: E402

VMAX = {'0.1': 100_000, '0.2': 200_000, '1': 1_000_000}
GRID = [10, 30, 100, 300, 1000, 3245]
K = {'0.015': [5, 7, 11, 19, 38, 87], '0.004728': [4, 5, 8, 11, 20, 39]}


def make2(**kw):
    """A second-edition overlay (v_max 0.2, least cap without rejection) with the given changes."""
    config = design2.load_config()
    op = opt.load(replay.default_operating_point(inputs.load_conditions()))
    args = dict(vmax_usdc='0.2', sales_cap='auto-zero-reject', edition=2)
    args.update(kw)
    return design2.Design2(config, op, **args)


def trace_arrays(blocks, values=None):
    """The four arrays of one address (blocks, values, rows, positions); every value 10 atomic units by default."""
    n = len(blocks)
    v = np.full(n, 10, dtype=np.int64) if values is None else np.asarray(values, dtype=np.int64)
    return (np.asarray(blocks, dtype=np.int64), v, np.arange(n, dtype=np.int64), np.zeros(n, dtype=np.int64))


class ChainListFixture:
    """A mixin for test cases: a four-day list of a base58 chain (0.4 s slots, two recipients that differ only
    in case, 44 recipients in all) built by chain_inputs, and runs of replay.py on it."""

    @classmethod
    def setUpClass(cls):
        import chain_inputs
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        rng = random.Random(21)
        cls.addresses = ['Cv' + 'x' * 10 + 'AA', 'cv' + 'x' * 10 + 'aa', 'Bd2xS189uhhn', 'D2gmY6xa5uft'] + [
            f'Addr{i:03d}' for i in range(40)]
        weights = [30, 12, 8, 5] + [1] * 40          # the first recipient is rank 1
        days = ['2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11']
        directory = cls.root / 'win'
        directory.mkdir()
        block = 90_000
        header = 'block_number,block_time_utc,tx_hash,tx_index,trace_address,recipient,payer,value_atomic,facilitator\n'
        n = 0
        for date in days:
            lines = []
            for _ in range(2500):
                block += rng.choice((0, 0, 1, 2, 3, 400))
                rec = rng.choices(cls.addresses, weights)[0]
                n += 1
                lines.append(f'{block},{date} {rng.randrange(24):02d}:00:00,tx{n:07d},{n % 50},3,{rec},P,'
                             f'{rng.choice((1000, 1000, 10_000, 150_000, 2_000_000))},F\n')
            with gzip.open(directory / f'settlements_{date}.csv.gz', 'wt', newline='') as f:
                f.write(header + ''.join(lines))
        cls.report = chain_inputs.build('solana', directory, cls.root / 'out')
        cls.out = cls.root / 'out'
        cls.list_csv = cls.out / 'settlements_solana_2026-09-08_2026-09-11.csv'
        cls._git = replay.git_state
        replay.git_state = lambda: dict(revision='0' * 40, dirty=False)

    @classmethod
    def tearDownClass(cls):
        replay.git_state = cls._git
        inputs.set_address_case('lower')
        cls.tmp.cleanup()

    def argv(self, out, *extra):
        return ['--settlements', str(self.list_csv), '--conditions-file', str(self.out / 'conditions_solana.json'),
                '--reference-dir', str(self.out / 'ref'), '--qx', '137', '--out', str(out), '--draws', '3',
                '--conditions', '1', '--repetitions', '1', '--design', '2', '--chain', 'solana', *extra]

    def run_replay(self, name, *extra):
        import test_replay as tr
        out = self.root / name
        code, _ = tr.run_cli(self.argv(out, *extra))
        assert code == 0
        return out, json.loads((out / 'run.json').read_text())
