"""Bucket arithmetic pinned against hand-computed values from FairBindCore._refilledBucket,
_consumeBucket and FairBindBond.registerBond (and the contract tests that exercise them)."""
import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bucket import Bucket, PPM, profile_admits_capacity  # noqa: E402
import engine  # noqa: E402
from controller import profile as prof  # noqa: E402

PROFILE_FILE = Path(__file__).resolve().parents[2] / 'profiles' / 'local-evaluation-v1.json'
REFILL = 50_000  # refillPpmPerBlock of both evaluation profiles


class ContractValues(unittest.TestCase):
    def test_twenty_first_same_block_settlement_rejects(self):
        # FairBindM1.t.sol testTwentyFirstSameBlockSettlementRejects: capacity 20, scale 1.
        b = Bucket(20, REFILL, 1, 10)
        self.assertEqual([b.consume(10) for _ in range(21)], [True] * 20 + [False])
        self.assertEqual(b.balance_ppm, 0)

    def test_refill_is_block_based_and_integer(self):
        b = Bucket(20, REFILL, 1, 0)
        for _ in range(20):
            self.assertTrue(b.consume(0))
        # 19 blocks refill 950,000 ppm: below one settlement.
        self.assertEqual(b.level(19), 950_000)
        self.assertFalse(b.consume(19))
        # A reverted settle leaves the state as it was: the level keeps accruing from block 0.
        self.assertEqual((b.balance_ppm, b.updated_block), (0, 0))
        self.assertTrue(b.consume(20))
        self.assertEqual((b.balance_ppm, b.updated_block), (0, 20))
        # Half a settlement after 10 blocks, one after 20.
        self.assertEqual(b.level(30), 500_000)
        self.assertTrue(b.consume(40))

    def test_scale_multiplies_capacity_and_refill(self):
        # FairBindBond.t.sol test_scaleFactorFollowsBalance...: 20 blocks at 0.05 per block times 2 = 2.
        b = Bucket(20, REFILL, 2, 10)
        self.assertEqual(b.cap_ppm, 40 * PPM)
        b.balance_ppm = 0  # the level the top-up left in that test
        self.assertTrue(b.consume(30))
        self.assertTrue(b.consume(30))
        self.assertFalse(b.consume(30))

    def test_refill_is_capped(self):
        # FairBindM1.t.sol: after 400 idle blocks quoteSeller().remaining is back at 20.
        b = Bucket(20, REFILL, 1, 0)
        for _ in range(5):
            b.consume(0)
        self.assertEqual(b.level(400) // PPM, 20)
        self.assertEqual(b.level(10_000), 20 * PPM)

    def test_new_bond_starts_full_at_its_scale(self):
        b = Bucket(137, REFILL, 7, 1000)
        self.assertEqual(b.level(1000), 137 * 7 * PPM)
        self.assertEqual(sum(b.consume(1000) for _ in range(137 * 7 + 1)), 959)

    def test_admit_matches_bucket(self):
        rng = random.Random(3)
        for capacity, scale in ((20, 1), (137, 2), (3, 5)):
            blocks = np.array(sorted(rng.randrange(0, 5000) for _ in range(3000)), dtype=np.int64)
            fast = engine.admit(blocks, capacity, REFILL, scale, 0)
            b = Bucket(capacity, REFILL, scale, 0)
            slow = [b.consume(int(x)) for x in blocks]
            self.assertEqual(fast.tolist(), slow)


class ProfileAdmission(unittest.TestCase):
    """FairBindCore._validateProfile: bucketCapacity * PPM + refill * E <= maxRate * E."""

    def test_capacity_bound_of_each_profile(self):
        data = prof.load_profile(PROFILE_FILE, 'data-api-fast-v1')['parameters']
        open_w = prof.load_profile(PROFILE_FILE, 'open-weights-standard-v1')['parameters']
        # Data API: (60,000 - 50,000) * 10,000 / 1e6 = 100.
        self.assertTrue(profile_admits_capacity(data, 20))
        self.assertTrue(profile_admits_capacity(data, 100))
        self.assertFalse(profile_admits_capacity(data, 101))
        self.assertFalse(profile_admits_capacity(data, 137))
        # Open weights: 10,000 * 42,000 / 1e6 = 420.
        self.assertTrue(profile_admits_capacity(open_w, 137))
        self.assertFalse(profile_admits_capacity(open_w, 421))


if __name__ == '__main__':
    unittest.main()
