"""Freeze scope of the injection model: 'full' (every unreleased entry) against 'detected-onward' (only the
entries settled at or after the failed sampled sale)."""
import random
import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import engine  # noqa: E402


def run(blocks, values, f, f_settled, scope, hold=100, reentry=0, claims=(1,)):
    return engine.evaluate_failures(np.array(blocks, dtype=np.int64), np.array(values, dtype=np.int64),
                                    np.array(f, dtype=np.int64), hold=hold, reentry=reentry, claim_probs=list(claims),
                                    share=7, rng=np.random.default_rng(1), start=0, end=1000,
                                    fw_edges=np.array([0, 1000]), claim_window=hold, scope=scope,
                                    f_settled=None if f_settled is None else np.array(f_settled, dtype=np.int64))


class TinyCase(unittest.TestCase):
    # Hold 100. Entries (block: value): 10:1, 50:2, 90:4, 120:8, 140:16. One failure confirmed at 150 whose
    # sampled sale settled at 120.
    blocks = [10, 50, 90, 120, 140]
    values = [1, 2, 4, 8, 16]

    def test_full_scope_freezes_every_unreleased_entry(self):
        r = run(self.blocks, self.values, [150], [120], 'full')[0]
        # entries 90, 120, 140 are unreleased at 150 (block + 100 > 150); 10 and 50 are released
        self.assertEqual(r['principal'], 4 + 8 + 16)

    def test_narrow_scope_freezes_from_the_detected_sale(self):
        r = run(self.blocks, self.values, [150], [120], 'detected-onward')[0]
        self.assertEqual(r['principal'], 8 + 16)             # entry 90 is released on its schedule (at 190)
        self.assertEqual(r['penalty'], 7)                     # the deduction is unchanged
        self.assertEqual(r['revenue'], 31)
        self.assertEqual(r['refunded'], 24)                   # the frozen entries are claimed

    def test_narrow_equals_full_when_the_sale_opens_the_hold_window(self):
        full = run(self.blocks, self.values, [150], [51], 'full')[0]
        narrow = run(self.blocks, self.values, [150], [51], 'detected-onward')[0]
        self.assertEqual(narrow['principal'], full['principal'])

    def test_same_block_entry_is_frozen(self):
        r = run([119, 120, 120], [1, 2, 4], [150], [120], 'detected-onward')[0]
        self.assertEqual(r['principal'], 2 + 4)

    def test_second_failure_with_an_earlier_sale_freezes_earlier_entries_once(self):
        # failure 1 at 150 from the sale at 140; failure 2 at 160 from the sale at 90.
        r = run(self.blocks, self.values, [150, 160], [140, 90], 'detected-onward')[0]
        # 140 by failure 1; 90, 120 by failure 2 (settled at or after 90, unreleased at 160); each once
        self.assertEqual(r['principal'], 16 + 4 + 8)
        self.assertEqual(r['penalty'], 14)

    def test_no_failure_and_default(self):
        r = run(self.blocks, self.values, [], [], 'detected-onward')[0]
        self.assertEqual((r['principal'], r['failures']), (0, 0))
        default = engine.evaluate_failures(np.array(self.blocks), np.array(self.values), np.array([150]), hold=100,
                                           reentry=0, claim_probs=[1], share=7, rng=None, start=0, end=1000,
                                           fw_edges=np.array([0, 1000]), claim_window=100)[0]
        self.assertEqual(default['principal'], 28)            # the default scope is 'full'

    def test_unknown_scope_and_missing_sale_are_errors(self):
        with self.assertRaises(ValueError):
            run(self.blocks, self.values, [150], [120], 'half')
        with self.assertRaises(ValueError):
            run(self.blocks, self.values, [150], None, 'detected-onward')


class AgainstBruteForce(unittest.TestCase):
    def test_random_cases(self):
        rng = random.Random(5)
        for trial in range(60):
            n = rng.randrange(1, 250)
            blocks = sorted(rng.randrange(0, 900) for _ in range(n))
            values = [rng.randrange(1, 9) for _ in range(n)]
            hold = rng.choice((30, 120, 400))
            F = rng.randrange(0, 9)
            f = sorted(rng.randrange(0, 1000) for _ in range(F))
            settled = [max(0, fj - rng.randrange(0, 300)) for fj in f]
            want, who = 0, {}
            for idx, b in enumerate(blocks):
                for j, fj in enumerate(f):
                    if settled[j] <= b <= fj and b + hold > fj:
                        who[idx] = j
                        want += values[idx]
                        break
            for reentry in (0,):
                got = run(blocks, values, f, settled, 'detected-onward', hold=hold)[0]
                full = run(blocks, values, f, settled, 'full', hold=hold)[0]
                self.assertEqual(got['principal'], want, trial)
                self.assertLessEqual(got['principal'], full['principal'])
                self.assertEqual(got['penalty'], full['penalty'])


class ChainSearch(unittest.TestCase):
    def test_owner_of_every_entry_against_brute_force(self):
        rng = random.Random(9)
        for trial in range(40):
            n = rng.randrange(1, 300)
            blocks = np.array(sorted(rng.randrange(0, 3000) for _ in range(n)), dtype=np.int64)
            hold = rng.choice((40, 500, 2000))
            F = rng.randrange(1, 60)
            f = np.array(sorted(rng.randrange(0, 3200) for _ in range(F)), dtype=np.int64)
            # sales in no particular order, some equal, some after the failure's neighbours
            settled = np.array([max(0, int(fj) - rng.choice((0, 5, 50, 400, 1500))) for fj in f], dtype=np.int64)
            lost, li = engine.narrow_lost(blocks, f, settled, hold)
            for idx, b in enumerate(blocks.tolist()):
                owner = next((j for j in range(F) if settled[j] <= b <= f[j] and b + hold > f[j]), -1)
                self.assertEqual(int(li[idx]), owner, (trial, idx))
                self.assertEqual(bool(lost[idx]), owner >= 0)


if __name__ == '__main__':
    unittest.main()
