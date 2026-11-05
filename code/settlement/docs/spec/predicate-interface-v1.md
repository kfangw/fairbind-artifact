# FairBind Predicate Interface Version 1

Status: Release candidate for implementation

FairBind predicates decide whether a committed response satisfies an immutable
service profile. They do not judge usefulness, intent, style, or truth outside
the registered claim. A predicate returns `PASS`, `FAIL`, or `INCONCLUSIVE` and
produces reproducible evidence for its result.

## 1. Predicate identifiers

Version 1 reserves two predicate identifiers for the evaluation artifact:

| Service class | Identifier | Value |
| --- | --- | --- |
| data API reference comparison | `DATA_API_REFERENCE_V1` | `0xb1659e2eda6c17f24434be64972e5ce19d44b5b4154752bbe83418276831812f` |
| open-weights TOPLOC comparison | `OPEN_WEIGHTS_TOPLOC_V1` | `0xdc77e562812ea60a876f258021aea1da480f6035092b70aa11ca0f5ae1dae9ad` |

These values are protocol constants, not hashes derived from display names. A
new codec, tolerance rule, evidence layout, or decision procedure receives a
new identifier and profile.

## 2. Common evaluation input

Seller claims conform to
[`../../schemas/fairbind-claims-v1.schema.json`](../../schemas/fairbind-claims-v1.schema.json),
and the seller registration stores:

```text
claimsHash = keccak256(UTF8(JCS(claims)))
```

For data APIs, the receipt preimage's `sourceSetHash` and
`tolerancePolicyHash` MUST equal the claims manifest. For open-weights
inference, `modelHash` and `configHash` MUST equal it. A mismatch is `FAIL`.

Every verifier receives the immutable purchase, response bytes, seller receipt,
predicate-commitment preimage, and profile document. It MUST perform these checks
before applying a service-class rule:

1. recompute `requestHash`, `responseHash`, and the purchase nonce;
2. verify the receipt signature and immutable fields;
3. recompute `predicateCommitment` from the supplied preimage;
4. require the predicate and canonicalization identifiers to equal the profile;
5. require every referenced byte object to stay within the profile limits.

A failed cryptographic binding is `FAIL` only when it proves that the seller
signed a response inconsistent with its own commitment. A receipt whose
signature and immutable fields verify but whose `predicateCommitment` is zero
is `FAIL`: the seller controls and signs that field, so its absence is a
missing disclosure, not an incomplete evaluation. Missing verifier-side input,
unavailable external data, unsupported configuration, or an indeterminate
comparison is `INCONCLUSIVE`. A receipt that does not authenticate is neither
result; the verifier does not judge it.

## 3. Data API commitment

The data API preimage is:

```text
referenceTime       uint64
sourceSetHash       bytes32
tolerancePolicyHash bytes32
```

The receipt field is:

```text
predicateCommitment = keccak256(abi.encode(
  keccak256("fairbind/data-commitment/v1"),
  uint64(referenceTime),
  bytes32(sourceSetHash),
  bytes32(tolerancePolicyHash)
))
```

`sourceSetHash` commits an ordered manifest of independent source identifiers,
request mappings, authentication-free replay material, and response-signature
rules. `tolerancePolicyHash` commits field selection, units, normalization,
maximum time skew, numeric tolerances, and missing-field behavior. Both manifests
use `keccak256(UTF8(JCS(manifest)))`.

The predicate returns `PASS` when enough independently retrieved observations
are valid for the committed reference time and every selected value satisfies
the tolerance policy. It returns `FAIL` when the minimum source quorum is valid
and at least one selected value provably violates the policy. It returns
`INCONCLUSIVE` when the quorum, time alignment, signatures, or comparison cannot
be established.

## 4. Open-weights commitment

The open-weights preimage is:

```text
toplocCommitment bytes32
modelHash        bytes32
configHash       bytes32
```

The receipt field is:

```text
predicateCommitment = keccak256(abi.encode(
  keccak256("fairbind/open-weights-commitment/v1"),
  bytes32(toplocCommitment),
  bytes32(modelHash),
  bytes32(configHash)
))
```

`modelHash` identifies the exact public weight artifact. `configHash` commits a
JCS manifest containing tokenizer, prompt template, precision, quantization,
batch size, decoding parameters, kernel and runtime versions, accelerator class,
and the TOPLOC parameters. The response bundle carries the TOPLOC trace needed
to recompute `toplocCommitment`.

The verifier runs the profile's prefill comparison. It returns `PASS` when the
reproduced activation evidence satisfies the committed tolerance policy. It
returns `FAIL` when the model and configuration are supported and the mismatch
exceeds that policy. It returns `INCONCLUSIVE` when weights or trace data are
unavailable, the configuration is unsupported, or observed nondeterminism falls
outside the profile's calibrated decision region.

The predicate tests the claimed process. It does not assert that the natural
language answer is useful or factually correct.

## 5. Evidence envelope

The evidence object conforms to
[`../../schemas/fairbind-evidence-v1.schema.json`](../../schemas/fairbind-evidence-v1.schema.json).
Its hash is:

```text
evidenceHash = keccak256(UTF8(JCS(evidence)))
```

The envelope binds the predicate, purchase nonce, response, seller commitment,
verdict, implementation revision, observation time, and class-specific result
hashes. Large source responses or activation traces remain content-addressed by
the hashes inside `details`. The disclosed envelope MUST contain enough stable
identifiers to retrieve and reproduce those objects during the profile's
retention period.

The verifier signs `evidenceHash` as part of `FairBindVerdict`. A party that
calls `requestEvidence` requests these exact canonical JSON bytes. Alternative
serialization, semantically equivalent JSON, or an unhashed external report
does not satisfy disclosure.

## 6. Reproducibility and calibration

A predicate implementation is deterministic for fixed retrieved objects and
runtime inputs. The experiment records the implementation hash, object hashes,
elapsed time, compute price, and outcome. Calibration separately measures false
rejection, false acceptance, and latency with confidence intervals. Those
measurements set profile values; they do not change the three-way decision rule
for an existing profile.

No version 1 predicate may call another language model for a subjective final
judgment. Services without a reproducible process or independent reference are
outside the supported classes.

## 7. Vectors

[`../../test-vectors/predicate-v1.json`](../../test-vectors/predicate-v1.json)
fixes a claims hash, both commitment encodings, and one canonical evidence hash.
