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

    def test_dispute_opening_lengthens_open_weights(self):
        r = self.result('open-weights-standard-v1')
        self.assertEqual((r['longest'], r['longest_dispute']), (91712, 91712))
        self.assertTrue(r['exceeds_measured'])
        r = self.result('data-api-fast-v1')
        self.assertEqual((r['longest'], r['longest_dispute']), (29680, 29672))
        self.assertFalse(r['exceeds_measured'])

    def test_terms_account_for_the_horizon(self):
        for name in cp.MEASURED:
            r = self.result(name)
            model = cp.Model(prof.load_profile(cp.PROFILE_FILE, name))
            self.assertEqual(sum(t['longest_path_uses'] for t in r['terms']), r['longest'])
            self.assertEqual(sum(t['budget'] for t in r['terms']) + r['marginBlocks'], r['caseHorizon'])
            unusable = {t['term']: t['unusable'] for t in r['terms']}
            m, d = model.m, prof._p(prof.load_profile(cp.PROFILE_FILE, name))['deadlineConfig']
            self.assertEqual(unusable['serve'], 2 * 3 * d['serveBlocks'])
            self.assertEqual(unusable['evidence'], 2 * m * d['evidenceBlocks'])
            self.assertEqual(unusable['appeal'], (5 * m - 1) * d['appealBlocks'])
            self.assertEqual(unusable['seal'], 2)
            self.assertEqual(unusable['slack'], 3)
            self.assertEqual((unusable['open'], unusable['judge']), (0, 0))

    def test_without_recheck_the_auto_path_is_gone_but_not_the_length(self):
        p = prof.load_profile(cp.PROFILE_FILE, 'data-api-fast-v1')
        p['parameters']['recheckPpm'] = 0
        self.assertEqual(cp.analyse(p)['longest'], 29680)

    def test_one_assignment_per_stage(self):
        p = prof.load_profile(cp.PROFILE_FILE, 'data-api-fast-v1')
        p['parameters']['maxAssignments'] = 1
        d = p['parameters']['deadlineConfig']
        # open + initial (2J + 3S + A + E + A) + two reviews (2 * sealBlocks + 3 + 2J + 3S).
        want = (1868 + 2 * d['judgeBlocks'] + 3 * d['serveBlocks'] + 2 * d['appealBlocks'] + d['evidenceBlocks']
                + 2 * (2 * d['sealBlocks'] + 3 + 2 * d['judgeBlocks'] + 3 * d['serveBlocks']))
        self.assertEqual(cp.analyse(p)['longest'], want)


if __name__ == '__main__':
    unittest.main()
