"""Execution-binding tests on seeded synthetic checkpoints (see model.py)."""
import importlib.util
import os
import shutil
import tempfile
import unittest

REQUIRED = ('torch', 'transformers', 'toploc')
AVAILABLE = all(importlib.util.find_spec(name) for name in REQUIRED)
PROMPT = [1, 17, 300, 42, 901, 5, 77, 1203, 64, 9, 15, 2048, 3, 18, 400, 11]

@unittest.skipUnless(AVAILABLE, 'requires the pinned torch, transformers and TOPLOC CPU environment')
class BindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import binding as B
        import model as M
        cls.B, cls.M = B, M
        cls.dir = tempfile.mkdtemp(prefix='fairbind-inference-test-')
        cls.model_a = M.write_synthetic_checkpoint(os.path.join(cls.dir, 'a'), 11)
        cls.model_b = M.write_synthetic_checkpoint(os.path.join(cls.dir, 'b'), 12)
        cls.config = B.config_manifest(max_new_tokens=8)
        cls.honest = B.serve(cls.model_a, cls.config, PROMPT)
        cls.claims = B.claims_object(cls.honest.preimage['modelHash'], cls.honest.preimage['configHash'])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def verify(self, served=None, **override):
        served = served or self.honest
        args = dict(claims=self.claims, preimage=served.preimage, config_bytes=self.honest.config_bytes,
                    trace_bytes=served.trace_bytes, model_dir=self.model_a, prompt_ids=PROMPT,
                    output_ids=served.output_ids, predicate_commitment=served.predicate_commitment)
        args.update(override)
        return self.B.verify(**args)

    def test_synthetic_checkpoint_is_deterministic(self):
        again = self.M.write_synthetic_checkpoint(os.path.join(self.dir, 'a-again'), 11)
        self.assertEqual(self.M.weight_manifest(again), self.M.weight_manifest(self.model_a))
        self.assertNotEqual(self.M.weight_manifest(self.model_b), self.M.weight_manifest(self.model_a))

    def test_activation_shapes(self):
        shapes = [tuple(a.shape) for a in self.honest.activations]
        self.assertEqual(shapes, [(len(PROMPT), 576)] + [(576,)] * 7)
        self.assertEqual(len(self.honest.output_ids), 8)

    def test_receipt_commitment_binds_preimage(self):
        from encoding import keccak256, open_weights_commitment, parse_hex32
        p = self.honest.preimage
        self.assertEqual(parse_hex32(p['toplocCommitment']), keccak256(self.honest.trace_bytes))
        self.assertEqual(parse_hex32(p['configHash']), keccak256(self.honest.config_bytes))
        expected = open_weights_commitment(*(parse_hex32(p[k]) for k in ('toplocCommitment', 'modelHash', 'configHash')))
        self.assertEqual(self.honest.predicate_commitment, '0x' + expected.hex())

    def test_identical_rerun_passes(self):
        from encoding import keccak256
        r = self.verify()
        self.assertEqual(r['verdict'], 'PASS', r['reason'])
        d = r['details']
        self.assertEqual(d['reproducedCommitment'], d['toplocCommitment'])
        self.assertEqual(d['traceHash'], '0x' + keccak256(r['record']).hex())
        self.assertEqual(set(d), {'kind', 'toplocCommitment', 'reproducedCommitment', 'modelHash', 'configHash', 'traceHash'})

    def test_swapped_weights_fail(self):
        swapped = self.B.commit(self.B.load_for(self.model_b, self.config), self.honest.preimage['modelHash'], self.config, PROMPT)
        r = self.verify(swapped)
        self.assertEqual(r['verdict'], 'FAIL', r['reason'])
        self.assertNotEqual(r['details']['reproducedCommitment'], r['details']['toplocCommitment'])

    def int8_run(self):
        model = self.M.load_model(self.model_a, 'float32', 'int8-weight-rounding', 'eager')
        return self.B.commit(model, self.honest.preimage['modelHash'], self.config, PROMPT)

    def test_int8_rounding_fails_under_float32_commitment(self):
        r = self.verify(self.int8_run())
        self.assertEqual(r['verdict'], 'FAIL', r['reason'])

    def test_loose_tolerance_does_not_separate_int8(self):
        # Records a limit: the int8 differences are small in bfloat16 mantissa
        # terms. Only the exact-repeat tolerance separates them on this model.
        config = self.B.config_manifest(max_new_tokens=8, tolerance=(4, '8', '8'))
        honest = self.B.serve(self.model_a, config, PROMPT)
        claims = self.B.claims_object(honest.preimage['modelHash'], honest.preimage['configHash'])
        model = self.M.load_model(self.model_a, 'float32', 'int8-weight-rounding', 'eager')
        int8 = self.B.commit(model, honest.preimage['modelHash'], config, PROMPT)
        swapped = self.B.commit(self.B.load_for(self.model_b, config), honest.preimage['modelHash'], config, PROMPT)
        verdicts = [self.verify(s, claims=claims, config_bytes=honest.config_bytes)['verdict'] for s in (honest, int8, swapped)]
        self.assertEqual(verdicts, ['PASS', 'PASS', 'FAIL'])

    def test_altered_response_tokens_fail(self):
        tokens = list(self.honest.output_ids)
        tokens[3] = (tokens[3] + 1) % 4096
        self.assertEqual(self.verify(output_ids=tokens)['verdict'], 'FAIL')

    def test_missing_trace_is_inconclusive(self):
        r = self.verify(trace_bytes=None)
        self.assertEqual((r['verdict'], r['reason']), ('INCONCLUSIVE', 'commitment preimage missing: no TOPLOC trace'))

    def test_missing_preimage_is_inconclusive(self):
        self.assertEqual(self.verify(preimage=None)['verdict'], 'INCONCLUSIVE')

    def test_trace_not_opening_commitment_is_inconclusive(self):
        raw = bytearray(self.honest.trace_bytes)
        raw[-5] = ord('0') if raw[-5] != ord('0') else ord('1')
        r = self.verify(trace_bytes=bytes(raw))
        self.assertEqual((r['verdict'], r['reason']), ('INCONCLUSIVE', 'trace does not open toplocCommitment'))

    def test_preimage_not_opening_receipt_is_inconclusive(self):
        self.assertEqual(self.verify(predicate_commitment='0x' + '11' * 32)['verdict'], 'INCONCLUSIVE')

    def test_empty_receipt_commitment_fails(self):
        self.assertEqual(self.verify(predicate_commitment='0x' + '00' * 32)['verdict'], 'FAIL')

    def test_disclosed_other_model_contradicts_claims(self):
        other = self.B.serve(self.model_b, self.config, PROMPT)
        r = self.verify(other)
        self.assertEqual((r['verdict'], r['reason']), ('FAIL', 'preimage contradicts authenticated claims'))

    def test_disclosed_quantization_contradicts_claims(self):
        other = self.B.serve(self.model_a, self.B.config_manifest(max_new_tokens=8, quantization='int8-weight-rounding'), PROMPT)
        self.assertEqual(self.verify(other)['verdict'], 'FAIL')

    def test_weights_unavailable_is_inconclusive(self):
        for model_dir in (None, self.model_b):
            self.assertEqual(self.verify(model_dir=model_dir)['reason'], 'committed weights unavailable to verifier')

    def test_configuration_unavailable_or_unsupported_is_inconclusive(self):
        from encoding import canonical
        self.assertEqual(self.verify(config_bytes=None)['verdict'], 'INCONCLUSIVE')
        for config in (self.B.config_manifest(runtime={'torch': '0.0.0', 'transformers': '0', 'toploc': '0'}),
                       self.B.config_manifest(accelerator='cuda:unavailable')):
            served = self.B.Served(self.honest.output_ids, canonical(config), self.honest.trace_bytes,
                                   dict(self.honest.preimage, configHash='0x' + __import__('encoding').keccak256(canonical(config)).hex()),
                                   None, [])
            claims = self.B.claims_object(served.preimage['modelHash'], served.preimage['configHash'])
            r = self.verify(served, claims=claims, config_bytes=served.config_bytes)
            self.assertEqual(r['verdict'], 'INCONCLUSIVE', r['reason'])

if __name__ == '__main__':
    unittest.main()
