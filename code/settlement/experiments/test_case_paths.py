import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import case_paths as cp  # noqa: E402
from controller import profile as prof  # noqa: E402


class CasePaths(unittest.TestCase):
    def result(self, name):
        return cp.analyse(prof.load_profile(cp.PROFILE_FILE, name))

    def test_longest_sampled_path_is_the_measured_one(self):
        for name, measured in cp.MEASURED.items():
            self.assertEqual(self.result(name)['longest_sampled'], measured, name)

    def test_delivered_dispute_opening_is_the_longest(self):
        # Lemma C, third edition, section 4.2: the sample case opened after a delivered
        # non-delivery dispute, with the stalled seller appeal, is the longest path; the
        # dispute-opened path is shorter by the opening difference.
        r = self.result('open-weights-standard-v1')
        self.assertEqual((r['longest'], r['longest_sampled'], r['longest_dispute']), (92081, 92081, 91713))
        self.assertFalse(r['exceeds_measured'])
        r = self.result('data-api-fast-v1')
        self.assertEqual((r['longest'], r['longest_sampled'], r['longest_dispute']), (30573, 30573, 29673))
        self.assertFalse(r['exceeds_measured'])

    def test_terms_account_for_the_horizon(self):
        # Since ADR 0024 the horizon is the longest path plus the margin: the longest path
        # spends every term of judgmentDelayBlocks exactly.
        for name in cp.MEASURED:
            r = self.result(name)
            self.assertEqual(sum(t['longest_path_uses'] for t in r['terms']), r['longest'])
            self.assertEqual(sum(t['budget'] for t in r['terms']) + r['marginBlocks'], r['caseHorizon'])
            self.assertEqual(r['longest'], r['caseHorizon_minus_margin'])
            for t in r['terms']:
                self.assertEqual(t['longest_path_uses'], t['budget'], t['term'])

    def test_without_recheck_the_auto_path_is_gone_but_not_the_length(self):
        p = prof.load_profile(cp.PROFILE_FILE, 'data-api-fast-v1')
        p['parameters']['recheckPpm'] = 0
        self.assertEqual(cp.analyse(p)['longest'], 30573)

    def test_one_assignment_per_stage(self):
        p = prof.load_profile(cp.PROFILE_FILE, 'data-api-fast-v1')
        p['parameters']['maxAssignments'] = 1
        d = p['parameters']['deadlineConfig']
        # delivered-dispute opening + initial (2J + 3S + A + E + A) + two reviews
        # (2 * sealBlocks + 3 + 2J + 3S) + the block of the stalled tiebreak.
        want = (2760 + 2 * d['judgeBlocks'] + 3 * d['serveBlocks'] + 2 * d['appealBlocks'] + d['evidenceBlocks']
                + 2 * (2 * d['sealBlocks'] + 3 + 2 * d['judgeBlocks'] + 3 * d['serveBlocks']) + 1)
        self.assertEqual(cp.analyse(p)['longest'], want)


if __name__ == '__main__':
    unittest.main()
