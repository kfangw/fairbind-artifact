"""Engine parameters of the design-2 replay: bucket refill of its own, buckets that change during the window,
fixed windows aligned to block 0, and the blocks per hour and seconds per block of a chain."""
import sys
import unittest
from fractions import Fraction
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import design2  # noqa: E402
import engine  # noqa: E402
import test_design2 as td  # noqa: E402
from d2_testlib import trace_arrays  # noqa: E402


class FixedWindows(unittest.TestCase):
    def test_absolute_windows_sit_on_multiples_of_their_length(self):
        edges = design2.window_edges(51_049_201, 51_637_238, 31_073, 'absolute')
        self.assertTrue(all(int(e) % 31_073 == 0 for e in edges))
        self.assertGreaterEqual(int(edges[0]), 51_049_201)
        self.assertLessEqual(int(edges[-1]), 51_637_238 + 1)
        self.assertEqual(int(np.diff(edges).min()), 31_073)
        # the next window would not fit
        self.assertGreater(int(edges[-1]) + 31_073, 51_637_238 + 1)

    def test_first_block_windows_are_the_first_edition_windows(self):
        edges = design2.window_edges(1_000_000, 1_200_000, 30_180, 'first-block')
        self.assertEqual(edges.tolist(), [1_000_000 + 30_180 * i for i in range(7)])
        with self.assertRaises(ValueError):
            design2.window_edges(0, 10, 5, 'rolling')

    def test_edge_cases(self):
        self.assertEqual(len(design2.window_edges(0, 10, 31_073, 'absolute')) - 1, 0)
        self.assertEqual(design2.window_edges(31_073, 62_145, 31_073, 'absolute').tolist(), [31_073, 62_146])
        self.assertEqual(design2.window_edges(31_074, 93_218, 31_073, 'absolute').tolist(), [62_146, 93_219])

    def test_judgment_windows_of_a_replay_follow_the_alignment(self):
        p = td.replay_params()
        p = dict(p, inconclusiveWindowBlocks=1000)
        n = 300
        blocks = np.unique(np.random.default_rng(1).integers(10_000, 15_000, n))
        n = len(blocks)
        arrays = (blocks.astype(np.int64), np.full(n, 10, dtype=np.int64), np.arange(n, dtype=np.int64),
                  np.zeros(n, dtype=np.int64))
        kw = dict(seed=1, p=p, capacity=500, scale=1, origin_ledger=10_000, local_origin=p['epochOrigin'],
                  end_ledger=14_999, block_size={}, window_blocks=5000, first_seconds=0)
        first, _ = engine.replay_address('a', arrays, align='first-block', **kw)
        absolute, _ = engine.replay_address('a', arrays, align='absolute', **kw)
        # 10_000 is a multiple of 1000: the two alignments coincide
        self.assertEqual(first['judgment_windows'], absolute['judgment_windows'])
        kw['origin_ledger'], kw['end_ledger'] = 10_300, 14_999
        shifted_first, _ = engine.replay_address('a', arrays, align='first-block', **kw)
        shifted_abs, _ = engine.replay_address('a', arrays, align='absolute', **kw)
        self.assertEqual(shifted_first['judgment_windows'], 4)          # [10300, 14300) in four windows of 1000
        self.assertEqual(shifted_abs['judgment_windows'], 4)           # [11000, 15000) in four windows of 1000
        self.assertEqual(shifted_first['judgment_window_settlements'] + 0, int(((blocks >= 10_300) & (blocks < 14_300)).sum()))
        self.assertEqual(shifted_abs['judgment_window_settlements'], int(((blocks >= 11_000) & (blocks < 15_000)).sum()))


class EngineParameters(unittest.TestCase):
    def kw(self, **extra):
        p = td.replay_params()
        base = dict(seed=1, p=p, capacity=4, scale=1, origin_ledger=0, local_origin=p['epochOrigin'], end_ledger=70_000,
                    block_size={}, window_blocks=70_000, first_seconds=0, observed=False)
        base.update(extra)
        return base

    def test_a_refill_of_its_own_replaces_the_profile_refill(self):
        blocks = np.arange(0, 20_000, 100, dtype=np.int64)          # 200 settlements, one per 100 blocks (10,000 ppm per block)
        arrays = trace_arrays(blocks)
        default, _ = engine.replay_address('a', arrays, **self.kw(capacity=1))              # profile refill 50,000: all admitted
        slow, _ = engine.replay_address('a', arrays, **self.kw(capacity=1, refill_ppm=1544))
        fast, _ = engine.replay_address('a', arrays, **self.kw(capacity=1, refill_ppm=10_000))
        self.assertEqual(default['accepted_count'], 200)
        self.assertEqual(fast['accepted_count'], 200)
        self.assertLess(slow['accepted_count'], 40)                  # 0.1544 tokens per 100 blocks: about one in seven

    def test_segments_may_carry_their_own_bucket(self):
        arrays = trace_arrays([0] * 3 + [2000] * 12)
        kw = self.kw(capacity=137, block_size={0: 3, 2000: 12}, end_ledger=3000, window_blocks=3000)
        both = engine.replay_address('a', arrays, segments=[(0, 1, 13, 4618), (1000, 1, 4, 1544)], **kw)[0]
        self.assertEqual(both['accepted_count'], 3 + 4)
        two_field = engine.replay_address('a', arrays, segments=[(0, 2), (1000, 1)], **dict(kw, capacity=2))[0]
        self.assertEqual(two_field['accepted_count'], 3 + 2)         # the two-field form still uses the run's bucket: 4 tokens, then 2

    def test_blocks_per_hour_and_seconds_per_block(self):
        p = td.replay_params()
        blocks = np.arange(0, 90_000, 9, dtype=np.int64)
        arrays = trace_arrays(blocks)
        kw = self.kw(p=dict(p, deferBlocks=1000), capacity=5000, refill_ppm=1_000_000, end_ledger=89_999, window_blocks=90_000, observed=True)
        two, _ = engine.replay_address('a', arrays, hour_blocks=1800, block_seconds=2, **kw)
        slot, _ = engine.replay_address('a', arrays, hour_blocks=9000, block_seconds=Fraction(2, 5), **kw)
        self.assertEqual(two['peak_hour_accepted'], 200)             # 1800 blocks of 2 s, one settlement per 9 blocks
        self.assertEqual(slot['peak_hour_accepted'], 1000)           # 9000 blocks of 0.4 s
        self.assertAlmostEqual(two['rate_acc_per_hour'], 10_000 / 90_000 * 1800)
        self.assertAlmostEqual(slot['rate_acc_per_hour'], 10_000 / 90_000 * 9000)
        self.assertEqual(slot['H_formula'], two['H_formula'])


if __name__ == '__main__':
    unittest.main()
