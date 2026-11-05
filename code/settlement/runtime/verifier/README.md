# Authenticated predicate input gate

`Check` authenticates the request, purchase identifiers, seller receipt, response,
commitment preimage, and canonical claims before a service comparison. Its
`READY` result means only that comparison may start. It is never a `PASS` verdict.
An externally modified response, preimage, receipt, or claims object produces
`INCONCLUSIVE`. `FAIL` requires a valid seller signature and commitment opening
that contradict the registered claims.

The caller supplies a trusted `Snapshot` from a finalized ledger and immutable
profile, including the seller signing key, request/response bounds, claims hash,
class, predicate, canonicalization, and manifest hashes. Never decode it from an
untrusted response bundle. This package does not implement ledger retrieval or
finality checks. Likewise, `CanonicalRequest` contains fields already normalized
by the HTTP adapter; it does not normalize raw HTTP. Request limits cover the sum
of all five byte fields, matching the contract publication check.

Claims support only the two fixed version 1 schemas: ASCII keys, bytes32 strings,
and integer version/class values. Exact canonical re-encoding rejects duplicate
keys, unknown fields, whitespace, escaped equivalents, and alternative number
encodings. This is a narrow canonical subset, not a general JCS implementation.
`MaxClaimsBytes` is a trusted worker resource limit in addition to the on-chain
request and response limits.

Receipt verification requires **Foundry cast 1.7.1**, commit
`4072e48705af9d93e3c0f6e29e93b5e9a40caed8`. Every invocation checks this version.
The executable path is trusted deployment configuration. Commands use direct
argument arrays, no shell, no network, and a five-second combined timeout. The
signature must have 65 bytes, nonzero r/s, low s and recovery id 27/28. Acceptance
requires successful process exit and the positive output naming the expected
address. Signing in tests uses public deterministic test key 1 only. Production
keys and signing are outside this package.

Known predicate IDs are the two normative interface IDs and the separately
user-authorized experimental data policy
`0x1a320b649fe0216a2d3ed2e6692f214cc0784cd6ec04bf3ef6cd230418f3ddd7`
(SHA-256 of UTF-8 `fairbind/experimental/data-decimal-median/v1`). Allowing this
identifier does not make its comparison rule the normative data predicate.

Run `go test -count=1 ./runtime/verifier`. Tests require the pinned cast executable;
missing dependencies fail rather than silently skip signature checks. Tests read
existing request, claims and both predicate commitment vectors unchanged.

Not implemented here: source retrieval/authentication, activation trace execution,
service comparisons, evidence serialization/storage, assignment polling, verdict
signing/submission, ledger adapter, deadline scheduling, or a standalone worker.
This is an authentication component, not M4/M5 completion or empirical evidence.
