import importlib.util
import json
import unittest
from pathlib import Path

from encoding import (OPEN_WEIGHTS_DOMAIN, canonical, keccak256, object_hash, open_weights_commitment,
                      parse_canonical, parse_hex32)

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / 'test-vectors' / 'predicate-v1.json').read_text())

class KeccakTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(keccak256(b'').hex(), 'c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470')

    def test_matches_spec_checker_outside_single_byte_padding(self):
        # scripts/check_spec.py and protocol.Keccak256 mis-pad inputs of length
        # 135 mod 136; those lengths are covered by the known-answer test below.
        spec = importlib.util.spec_from_file_location('check_spec', ROOT / 'scripts' / 'check_spec.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        for n in list(range(0, 300, 7)) + [134, 136, 137, 272]:
            if n % 136 == 135:
                continue
            data = bytes((i * 31 + n) & 0xff for i in range(n))
            self.assertEqual(keccak256(data), checker.keccak256(data), n)

    def test_single_byte_padding_block(self):
        # Length 135 mod 136 pads with the single byte 0x81. Expected values are
        # from an independent Keccak-256 implementation (pycryptodome 3.x).
        expected = {135: 'd442e2e5a608e8e4142d9adcf549171bf969ed2e6788d8bbc6ec9874e38b25f0',
                    271: '8241b344b9639361d682c97c608d067cc949c94b60d4c8a4c1ece57c457e98b1'}
        for n, digest in expected.items():
            self.assertEqual(keccak256(bytes((i * 31 + n) & 0xff for i in range(n))).hex(), digest)

class VectorTests(unittest.TestCase):
    def test_open_weights_domain(self):
        domain = VECTORS['domains']['openWeightsCommitment']
        self.assertEqual(keccak256(domain['text'].encode()), parse_hex32(domain['hash']))
        self.assertEqual(OPEN_WEIGHTS_DOMAIN, parse_hex32(domain['hash']))

    def test_open_weights_commitment_layout(self):
        v = VECTORS['openWeightsCommitment']
        words = [parse_hex32(v[k]) for k in ('toplocCommitment', 'modelHash', 'configHash')]
        self.assertEqual(OPEN_WEIGHTS_DOMAIN + b''.join(words), bytes.fromhex(v['encoded'][2:]))
        self.assertEqual(open_weights_commitment(*words), parse_hex32(v['predicateCommitment']))

    def test_canonical_object_hashes(self):
        self.assertEqual(object_hash(VECTORS['claims']['value']), parse_hex32(VECTORS['claims']['claimsHash']))
        self.assertEqual(object_hash(VECTORS['evidence']['value']), parse_hex32(VECTORS['evidence']['canonicalHash']))

class FixtureTests(unittest.TestCase):
    def test_binding_fixture_is_consistent(self):
        # testdata/binding-v1.json is also checked by binding_test.go.
        fx = json.loads((Path(__file__).parent / 'testdata' / 'binding-v1.json').read_text())
        p = {k: parse_hex32(v) for k, v in fx['preimage'].items()}
        self.assertEqual(canonical(parse_canonical(fx['config'].encode())), fx['config'].encode())
        self.assertEqual(keccak256(fx['config'].encode()), p['configHash'])
        self.assertEqual(keccak256(fx['trace'].encode()), p['toplocCommitment'])
        self.assertEqual(object_hash(fx['weightManifest']), p['modelHash'])
        self.assertEqual(open_weights_commitment(p['toplocCommitment'], p['modelHash'], p['configHash']),
                         parse_hex32(fx['predicateCommitment']))

class CanonicalTests(unittest.TestCase):
    def test_sorted_compact(self):
        self.assertEqual(canonical({'b': [1, True], 'a': {'d': 'x', 'c': 0}}), b'{"a":{"c":0,"d":"x"},"b":[1,true]}')

    def test_rejects_unsupported_values(self):
        for value in [1.5, -1, 2**53, 'café', 'a\nb', {1: 'x'}, b'x']:
            with self.assertRaises(ValueError):
                canonical({'v': value})

    def test_parse_requires_exact_bytes(self):
        self.assertEqual(parse_canonical(b'{"a":1}'), {'a': 1})
        for raw in [b'{"a": 1}', b'{"a":1,"a":1}', b'{"b":1,"a":2}', b'{"a":1.0}', b'{"a":"\\u0041"}']:
            with self.assertRaises(ValueError):
                parse_canonical(raw)

if __name__ == '__main__':
    unittest.main()
