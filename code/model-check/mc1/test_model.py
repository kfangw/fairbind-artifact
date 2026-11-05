"""Regression tests for two model defects found by the self-checks (MC1_results.md 9 (sec.) 6, 11).

    python3 -m unittest test_model
"""
import unittest

from model import default_cfg, initial_states, tx_anchor, tx_open, tx_answer, tx_dch, \
    tx_swap_proof, advance


def fresh(**kw):
    cfg = default_cfg(seller='ADV', prof='C', buyers=('OBL',), **kw)
    s = [x for x in initial_states(cfg) if not x.ps[0].ctgood and not x.ps[0].sampled][0]
    return cfg, s


class T(unittest.TestCase):
    def test_existing_sigma_b_answers_later_nd(self):
        cfg, s = fresh()
        p = s.ps[0]
        p.signed = 0
        p.sb_seller = 0
        s.now = 3
        tx_anchor(s, [0], [False], [False], cfg, [])
        self.assertIsNone(tx_open(s, 0, 'ND', 'T', 'X', None, cfg, []))
        self.assertIsNone(tx_answer(s, 0, 'SIG', cfg, []))
        s.now = 4
        self.assertIsNone(tx_open(s, 0, 'ND', 'P', 'W2', None, cfg, []))
        self.assertEqual(p.slots['ND_P'][5], 'sig')      # ends at once for the seller
        self.assertEqual(p.deps['ND_P'], 'seller')

    def test_deferred_judgement_counts_same_block_challenge(self):
        cfg, s = fresh()
        p = s.ps[0]
        p.signed = 0
        s.now = 4
        tx_anchor(s, [0], [False], [True], cfg, [])
        self.assertIsNone(tx_open(s, 0, 'KEY', 'T', 'X', None, cfg, []))
        self.assertIsNone(tx_answer(s, 0, 'K', cfg, []))   # eff = 4, window ends with block 6
        s.now = 6
        self.assertIsNone(tx_swap_proof(s, 0, cfg, []))     # terminal in block 6
        self.assertNotIn('KEY_T', p.deps)                    # not judged mid-block
        self.assertIsNone(tx_dch(s, 0, 'KEY_T', cfg, []))   # mismatching challenge in block 6
        advance(s, cfg)                                      # block 6 ends
        self.assertEqual(p.deps['KEY_T'], 'X')               # opener gets the deposit back


    def test_sigma_b_wins_a_same_block_tie(self):
        cfg, s = fresh()
        p = s.ps[0]
        p.signed = 0
        p.sb_seller = 0
        s.now = 4
        tx_anchor(s, [0], [False], [False], cfg, [])
        self.assertIsNone(tx_open(s, 0, 'KEY', 'T', 'X', None, cfg, []))
        self.assertIsNone(tx_open(s, 0, 'ND', 'T', 'X', None, cfg, []))
        s.now = 6
        self.assertIsNone(tx_answer(s, 0, 'CTK', cfg, []))   # answers both open disputes
        p.a_sig = 6                                          # a sigma_B in the same block
        from model import answer_for
        self.assertEqual(answer_for(p, 'ND_T', cfg), (6, 'SIG'))
        self.assertEqual(answer_for(p, 'KEY_T', cfg), (6, 'K'))


if __name__ == '__main__':
    unittest.main()
