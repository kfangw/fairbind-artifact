# ADR 0010: Separate experimental decimal-median predicate

Status: Accepted by the user on 2026-09-08.

The user chose a distinct experimental identifier for the proposed decimal-string,
median and tolerance policy. The identifier is SHA-256 of the UTF-8 string
`fairbind/experimental/data-decimal-median/v1`, with value
`0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7`.
It does not alias DATA_API_REFERENCE_V1 and no existing profile is mutated.

The local implementation uses the existing data commitment ABI, a restricted
canonical manifest codec, and the previously tested exact numeric comparison.
Receipt authentication precedes reference retrieval and comparison. External
byte tampering produces INCONCLUSIVE, not an attributed seller failure. A complete
signed receipt/commitment opening that contradicts registered claims may produce
FAIL. READY from the input gate is not a content verdict.

P1 and P2: no settlement identifiers, custody or recovery transitions change.
P3: only authenticated inputs reach comparison; error-rate calibration is still
required before security claims. P4: local results are not signed/submitted
verdicts, and workers still need assignment/deadline/evidence integration.
No production source independence, empirical detection bound, or rollout is approved
by this local experimental-policy decision.
