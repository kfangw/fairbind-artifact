# FairBind Version 1 Specification Set

Status: Release candidate for implementation

The documents in this directory form the FairBind version 1 specification. The
protocol overview states the security-relevant rules. The component documents
define byte encodings, contract calls, deadlines, and transport messages.

## Normative documents

| Document | Scope |
| --- | --- |
| [`fairbind-v1.md`](fairbind-v1.md) | Roles, assumptions, protocol flow, invariants, and security properties |
| [`canonicalization-v1.md`](canonicalization-v1.md) | HTTP request normalization and `requestHash` |
| [`cryptography-v1.md`](cryptography-v1.md) | Domain separation, identifiers, EIP-712 receipts, serve authorizations, and verdicts |
| [`merkle-v1.md`](merkle-v1.md) | Receipt tree construction, inclusion, omission, and equivocation proofs |
| [`contract-interface-v1.md`](contract-interface-v1.md) | Solidity types, calls, events, errors, views, and access rules |
| [`lifecycle-v1.md`](lifecycle-v1.md) | Block formulas, state transitions, timeout behavior, and fund priority |
| [`predicate-interface-v1.md`](predicate-interface-v1.md) | Predicate identifiers, commitment codecs, evidence, and verdict rules |
| [`sortition-v1.md`](sortition-v1.md) | Profile-specific verifier snapshots, weights, ticket mapping, and exit liability |
| [`profile-v1.md`](profile-v1.md) | Profile validation and evaluation profiles |
| [`governance-v1.md`](governance-v1.md) | Non-upgradeability, administrative roles, delay, and emergency controls |
| [`x402-v2-integration.md`](x402-v2-integration.md) | x402 version 2 and HTTP binding |
| [`traceability.md`](traceability.md) | Research requirements, properties, documents, and planned tests |

The machine-readable vectors under [`../../test-vectors/`](../../test-vectors/)
are normative. When prose and a vector disagree, implementations MUST reject the
vector and the repository MUST correct the inconsistency before implementation
continues. No implementation may silently choose one interpretation.

## Conformance terms

An implementation conforms to FairBind version 1 only when it passes every
positive vector, rejects every negative vector, and satisfies the invariants in
`fairbind-v1.md`. Passing the HTTP vectors alone establishes transport
compatibility, not protocol conformance.

Profile values under `profiles/` support local and testnet evaluation. They do
not claim production security until an experiment records the measured inputs
required by `profile-v1.md`.
