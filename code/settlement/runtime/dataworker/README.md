# Experimental authenticated data comparison

The user approved a separate experimental policy ID. `PolicyID` is the SHA-256
of UTF-8 `fairbind/experimental/data-decimal-median/v1`:
`0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7`.
This reproducible identifier is a new constant, not a change to either normative
predicate ID. No deployed profile is changed or activated by this package.

`Worker.Evaluate` calls the real-signature binding gate before invoking references
or the Python decimal-median comparison. It checks the source-set and tolerance
policy object hashes against the authenticated claims, and the reference time
against the receipt commitment. The source set is an ordered `{sources:[...]}`
object. The exact policy fields are Go's `Policy` JSON tags. All numbers in these
manifests are nonnegative safe integers; selected response values and numeric
thresholds are decimal strings. Manifest keys/strings are a restricted ASCII JCS
subset. Unsupported encodings are rejected rather than silently normalized.

For this first experiment the policy includes a fixed reference_time. Changing
that value changes the policy hash and requires new claims/registration. This is
a fixed-time local comparison, not a production rolling-time service policy.

A trusted operator supplies finalized purchase/profile snapshots and an independent
`ReferenceProvider`. The latter must retrieve/authenticate references and preserve
raw replay objects. Seller-supplied observations must never instantiate that
provider. No network reference adapter or finality adapter is implemented here;
tests use synthetic references and public test-key signatures. Availability errors
produce INCONCLUSIVE. Source names alone do not establish source independence.

The operator also configures the Python executable and comparator path; inputs
cannot choose executable paths. `runtime/predicates/data_experiment.py` checks
its own policy ID, duplicate JSON members, integer types, byte/array limits and
base64 before using the existing exact numeric kernel. Its command-line output
alone is not authenticated. Use `Worker.Evaluate`, not untrusted standalone output,
for a bound comparison. PASS and FAIL here are local comparison results, not
submitted or signed protocol verdicts.

`adapters/httpcanon` normalizes original HTTP fields against normative vectors.
Use its fields to construct `verifier.CanonicalRequest`; compare the actual
framework route using `CheckRoute`. The caller must retain the original request
target and body boundary and explicitly allow only comma-joinable selected headers.

## Predicate pipeline

`Pipeline.Evaluate(ctx, bundle, profile) (Verdict, Evidence, error)` is the
single entry point used by the verifier service:

1. `verifier.Check`. A bundle whose status is neither `READY` nor `FAIL` returns
   `ErrNotJudged` and nothing else runs. A gate `FAIL` (zero
   `predicateCommitment`, or an opened commitment contradicting the claims) is
   `FAIL` without retrieving references.
2. The operator's `Profile.Policy` and `Profile.Sources` are used only if they
   hash to the committed `tolerancePolicyHash` and `sourceSetHash`; otherwise
   the verifier lacks the committed input (`INCONCLUSIVE`). A signed preimage
   whose `referenceTime` differs from the policy's fixed time contradicts the
   seller's own policy (`FAIL`).
3. `ReplaySource.Collect` returns raw objects and unavailable sources.
   `refsource.Provider` implements it. Every raw object is kept verbatim
   (base64 in evidence) with its SHA-256 object ID.
4. `ReplayDecoder.Decode` derives each observation from its raw object
   (`refsource.Decoder`). Objects that fail to decode stay in the evidence and
   are listed as excluded.
5. `Compare` applies the decimal-median rule in exact rational arithmetic. Medians
   are written as exact decimals (`64230.685`).

`INCONCLUSIVE` arises only on the verifier/reference side: committed manifests
unavailable, invalid policy, no reference source, quorum not reached, duplicate
or unregistered sources, disagreeing references. Once the references fix the
medians, a response that is not a JSON object, lacks a selected field or
carries a non-decimal value is `FAIL`, since the seller signed those bytes. The
Python kernel returns `INCONCLUSIVE` for a non-decimal response value; the
cases both define are cross-checked in `TestCompareMatchesPythonKernel`.

`Evidence` (`fairbind/experimental/data-evidence/v1`) holds the policy ID, the
committed hashes, the source set and policy objects, the reference set (raw
replay objects and unavailable sources), its hash, the comparison record
(observations, excluded sources, counted sources, medians, verdict) and its
hash. `Evidence.Encode` returns the canonical bytes (`CanonicalObject`) and
their Keccak-256. `Rederive(evidence, response, decoder)` re-derives the
verdict from those objects and rejects any altered object, hash or verdict.
`testdata/data-evidence-v1.json` is a local regression vector for this layout
(canonical comparison bytes, reference set, comparison and evidence hashes);
it is not a normative protocol vector.

The older `Worker.Evaluate` (Python comparator subprocess) is unchanged.

Still required for a standalone worker: finalized-ledger/source adapters, assigned
case polling, canonical evidence objects and content-addressed storage, verifier
verdict signing/submission, and deadline/recovery scheduling (the last three
are in `services/verifier`). No error-rate calibration or six-process M5
completion is claimed.
