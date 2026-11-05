# Predicate implementation boundary

`data_reference.py` implements a proposed exact-decimal median comparison policy.
A fixed source quorum, source agreement spread, units, reference time/skew, and
absolute-plus-relative tolerances determine a three-way class comparison. Missing
references and unsupported encodings remain INCONCLUSIVE. Repeated source IDs
cannot satisfy a quorum. Decimal strings avoid binary-floating boundary changes.

This is a comparison kernel, not the complete DATA_API_REFERENCE_V1 protocol
predicate. A worker must validate the purchase, request and response commitments,
signed seller receipt, JCS claims and policy hashes, source identities and
retrieval/authenticity rules before calling it. An unverified seller-provided
reference list is not independent evidence. Production tolerances, source quorum,
and error calibration remain unselected; unit fixtures are not market data.

The policy can be committed as a new immutable tolerance manifest after review.
Do not register or reuse a predicate identifier for a changed decision procedure
without updating the specification and vectors. R09 integration and public source
acquisition remain separate from these tests.

## Optional TOPLOC comparison

`toploc_compare.py` validates proof counts and encodings before calling the pinned
native verifier. It rejects null modulus proofs before native arithmetic. Each
prefill/decode block is flattened and verified separately, retaining canonical
batching while using the native index-modulus handling. This does not authenticate
the model, purchase, tensor capture or seller receipt. Fixed zero tolerances are
only an exact-repeat diagnostic; cross-hardware policy calibration is still open.

Create a Python 3.12 environment and install
`experiments/requirements-toploc-cpu.txt` first. Then check out TOPLOC at the revision
in `UPSTREAMS.lock.json` and install that checkout with `pip install --no-build-isolation`.
This order supplies PyTorch to the native build. Run all comparison tests with
`python -m unittest discover -s runtime/predicates -p 'test_*.py' -v`. Without the
optional environment, three native tests are explicitly skipped.

`experiments/toploc_cpu_pilot.py --model-dir PATH --output NEW_DIRECTORY` performs
three local prefill comparisons with the pinned public model. Download only model
config/tokenizer and safetensors files at the locked revision; remote code is not
required. The script requires a clean checkout and records model file hashes,
input IDs, BF16 tensors, proofs, parameters, seed, versions and elapsed times. It
does not estimate false-positive/negative rates or generate paper result tables.
