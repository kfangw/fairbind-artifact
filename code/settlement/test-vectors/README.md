# FairBind Version 1 Test Vectors

The JSON files in this directory are normative inputs and expected outputs. Hex
strings use lowercase characters unless an address example tests checksum
handling. Hashes include the `0x` prefix. Decimal values that may exceed the safe
JSON integer range use strings.

The vectors were generated with Foundry `cast` version 1.7.1 and then checked by
recomputing their intermediate values. Private keys are public fixtures. Never
use them outside tests.

| File | Coverage |
| --- | --- |
| [`canonicalization-v1.json`](canonicalization-v1.json) | HTTP normalization, component hashes, final `requestHash`, and rejection cases |
| [`cryptography-v1.json`](cryptography-v1.json) | Domain hashes, purchase identifiers, EIP-712 digests and signatures, and random selection hashes |
| [`merkle-v1.json`](merkle-v1.json) | Ordered tree construction, odd-node duplication, inclusion paths, and omission adjacency |
| [`predicate-v1.json`](predicate-v1.json) | Service-class commitment encodings and canonical evidence hashing |
| [`sortition-v1.json`](sortition-v1.json) | Profile checkpoint ABI encoding and cumulative ticket boundaries |
| [`x402-v2/`](x402-v2/) | Decoded x402 messages and their exact base64 HTTP header encodings |

An implementation must compare decoded bytes and numeric values, not JSON object
member order, except for the HTTP header fixtures whose compact serialization is
part of the fixture.
