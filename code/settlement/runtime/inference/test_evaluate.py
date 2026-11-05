"""Tests for the class-2 predicate pipeline (evaluate.py) on seeded synthetic checkpoints."""
import base64
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import evaluate as E
from encoding import canonical, keccak256, open_weights_commitment, parse_canonical, parse_hex32

REQUIRED = ('torch', 'transformers', 'toploc')
AVAILABLE = all(importlib.util.find_spec(name) for name in REQUIRED)
PROMPT = [1, 17, 300, 42, 901, 5, 77, 1203, 64, 9, 15, 2048]
HERE = Path(__file__).resolve().parent
ZERO = '0x' + '00' * 32


def fake_bundle(status='READY', reason='bindings_authenticated_comparison_required', commitment=None):
    """A bundle for paths that stop before re-execution (no model needed)."""
    trace = b'{"proofs":[]}'
    pre = {'toplocCommitment': '0x' + keccak256(trace).hex(), 'modelHash': '0x' + '22' * 32, 'configHash': '0x' + '33' * 32}
    if commitment is None:
        commitment = '0x' + open_weights_commitment(*(parse_hex32(pre[k]) for k in ('toplocCommitment', 'modelHash', 'configHash'))).hex()
    return {'gate': {'status': status, 'reason': reason}, 'preimage': pre, 'predicateCommitment': commitment,
            'nonce': '0x' + '44' * 32, 'claims': canonical({'version': 1, 'classId': 2, 'predicateId': E.PREDICATE_ID,
                                                             'modelHash': pre['modelHash'], 'configHash': pre['configHash']}),
            'request': E.request_body(PROMPT), 'response': E.response_body([5, 6], trace)}


class GateAndCommitmentTests(unittest.TestCase):
    """These paths never import torch and run in every environment."""

    def test_gate_failed_bundle_is_not_judged(self):
        for status in ('INCONCLUSIVE', None, 'PASS'):
            with self.assertRaises(E.NotJudged):
                E.evaluate(fake_bundle(status=status, reason='receipt_signature'), {})
        with self.assertRaises(E.NotJudged):
            E.evaluate(dict(fake_bundle(), gate=None), {})

    def test_missing_commitment_fails(self):
        v, ev, raw = E.evaluate(fake_bundle(status='FAIL', reason='empty_predicate_commitment', commitment=ZERO), {})
        self.assertEqual((v, ev['reason'], ev['comparison']['verdict']), ('FAIL', 'empty_predicate_commitment', 'FAIL'))
        self.assertEqual(parse_canonical(raw), ev)
        v, ev, _ = E.evaluate(fake_bundle(commitment=ZERO), {})
        self.assertEqual((v, ev['reason']), ('FAIL', 'empty predicate commitment'))

    def test_signed_response_without_trace_fails(self):
        b = fake_bundle()
        b['response'] = canonical({'format': E.RESPONSE_FORMAT, 'version': 1, 'outputIds': [5]})
        self.assertEqual(E.evaluate(b, {})[0], 'FAIL')
        b = fake_bundle()
        b['response'] = E.response_body([5, 6], b'{"proofs":["0x00"]}')
        v, ev, _ = E.evaluate(b, {})
        self.assertEqual((v, ev['reason']), ('FAIL', 'signed trace does not open toplocCommitment'))

    def test_malformed_request_is_inconclusive(self):
        b = fake_bundle()
        b['request'] = b'{"prompt":"text"}'
        self.assertEqual(E.evaluate(b, {})[0], 'INCONCLUSIVE')

    def test_command_line(self):
        b = fake_bundle(status='FAIL', reason='empty_predicate_commitment', commitment=ZERO)
        doc = {'bundle': dict(b, claims=base64.b64encode(b['claims']).decode(), request=base64.b64encode(b['request']).decode(),
                              response=base64.b64encode(b['response']).decode()),
               'profile': {'configs': {}, 'models': {}}}
        run = lambda d: subprocess.run([sys.executable, str(HERE / 'evaluate.py')], input=json.dumps(d).encode(), capture_output=True, check=False)
        out = run(doc)
        r = json.loads(out.stdout)
        self.assertEqual(r['verdict'], 'FAIL')
        self.assertEqual(r['evidenceHash'], '0x' + keccak256(r['evidence'].encode()).hex())
        doc['bundle']['gate'] = {'status': 'INCONCLUSIVE', 'reason': 'response_binding'}
        self.assertEqual(json.loads(run(doc).stdout), {'notJudged': 'response_binding'})
        doc['bundle']['extra'] = 1
        self.assertEqual(run(doc).returncode, 2)


@unittest.skipUnless(AVAILABLE, 'requires the pinned torch, transformers and TOPLOC CPU environment')
class ReexecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import binding as B
        import model as M
        cls.B = B
        cls.dir = tempfile.mkdtemp(prefix='fairbind-evaluate-test-')
        cls.model_dir = M.write_synthetic_checkpoint(os.path.join(cls.dir, 'a'), 11)
        cls.config = B.config_manifest(max_new_tokens=6)
        cls.honest = B.serve(cls.model_dir, cls.config, PROMPT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir)

    def bundle(self, output_ids=None):
        s, p = self.honest, self.honest.preimage
        return {'gate': {'status': 'READY', 'reason': 'bindings_authenticated_comparison_required'},
                'preimage': dict(p), 'predicateCommitment': s.predicate_commitment, 'nonce': '0x' + '44' * 32,
                'claims': canonical(self.B.claims_object(p['modelHash'], p['configHash'])),
                'request': E.request_body(PROMPT), 'response': E.response_body(output_ids or s.output_ids, s.trace_bytes)}

    def profile(self, models=True, configs=True):
        p = self.honest.preimage
        return {'configs': {p['configHash']: self.honest.config_bytes} if configs else {},
                'models': {p['modelHash']: self.model_dir} if models else {}}

    def test_pass(self):
        v, ev, raw = E.evaluate(self.bundle(), self.profile())
        self.assertEqual(v, 'PASS', ev['reason'])
        self.assertEqual(ev['inputHash'], '0x' + keccak256(E.request_body(PROMPT)).hex())
        self.assertEqual(ev['modelHash'], self.honest.preimage['modelHash'])
        self.assertEqual(ev['configHash'], '0x' + keccak256(self.honest.config_bytes).hex())
        self.assertEqual(ev['reproducedCommitment'], ev['toplocCommitment'])
        self.assertEqual(ev['reexecutedOutputHash'], ev['sellerOutputHash'])
        self.assertEqual(ev['comparison']['verdict'], 'PASS')
        self.assertEqual(ev['comparison']['recordHash'], '0x' + keccak256(ev['record'].encode()).hex())
        self.assertEqual(canonical(parse_canonical(raw)), raw)
        # Deterministic evidence for the same inputs.
        self.assertEqual(E.evaluate(self.bundle(), self.profile())[2], raw)

    def test_tampered_output_fails(self):
        tokens = list(self.honest.output_ids)
        tokens[2] = (tokens[2] + 1) % 4096
        v, ev, _ = E.evaluate(self.bundle(tokens), self.profile())
        self.assertEqual(v, 'FAIL', ev['reason'])
        self.assertNotEqual(ev['reexecutedOutputHash'], ev['sellerOutputHash'])
        self.assertNotEqual(ev['reproducedCommitment'], ev['toplocCommitment'])

    def test_model_unavailable_is_inconclusive(self):
        v, ev, _ = E.evaluate(self.bundle(), self.profile(models=False))
        self.assertEqual((v, ev['reason']), ('INCONCLUSIVE', 'committed weights unavailable to verifier'))
        self.assertEqual(ev['reexecutedOutputHash'], ZERO)
        v, ev, _ = E.evaluate(self.bundle(), self.profile(configs=False))
        self.assertEqual((v, ev['reason']), ('INCONCLUSIVE', 'configuration manifest unavailable'))


if __name__ == '__main__':
    unittest.main()
