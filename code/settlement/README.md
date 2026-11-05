# FairBind

FairBind is a post-settlement fair exchange protocol for autonomous agent payments. It binds a payment authorization to an immutable seller profile, advertised claims, a normalized request, and a seller-signed response receipt. It then uses ledger-derived sampling, bonded verification, bounded settlement exposure, redelivery, and per-purchase refunds to handle failures after payment commitment.

This repository is the canonical implementation and artifact repository for FairBind. The protocol is designed as an x402 version 2 extension and uses a FairBind-specific EIP-3009 asset transfer method. The initial implementation supports the x402 `upfront` payment flow.

## Status

Milestones M0 through M3 are implemented at specification version
`1.0.0-rc.1`. The repository contains the normative specification,
machine-readable conformance vectors, evaluation profiles, Go protocol helpers,
the Solidity reference implementation, and Foundry tests for settlement,
anchoring, sampling, redelivery, and refunds. Judgment, review, and the
integrated multi-process artifact remain for M4 and M5. The documentation index
is [`docs/README.md`](docs/README.md), and the normative specification index is
[`docs/spec/README.md`](docs/spec/README.md).

## Repository layout

```text
contracts/     Solidity contracts and contract tests
protocol/      Shared identifiers, messages, receipts, and Merkle logic
services/      Buyer, seller, facilitator, verifier, and keeper processes
adapters/      x402 v2 and reference-gateway integration
predicates/    Service-class predicate implementations
experiments/   Reproducible evaluation runners and analyses
deploy/        Local and public-network deployment material
schemas/       Machine-readable wire schemas
profiles/      Versioned service-profile parameter sets
test-vectors/  Cross-language conformance fixtures
docs/          Indexed specification, architecture, decisions, and implementation plan
```

## Design baseline

FairBind version 1 fixes the following design choices:

- A purchase uses both a derived EIP-3009 nonce and a separate `keyId`.
- The contract samples ledger-recorded nonces, not seller-provided receipt leaves.
- Sampling and verifier assignment use randomness fixed after the seller commits an epoch.
- Each purchase has deferred funds that pay its refund before seller bond is used.
- Seller settlement rate is bounded by a token bucket.
- Verifiers post bonds, face deadlines, and may be replaced or penalized.
- A case follows either a party appeal path or an automatic recheck path, not both.
- Every nonterminal on-chain state has a public timeout transition.

Changes to this baseline require an updated specification, decision record, and review of properties P1 through P4.

## Upstream projects

FairBind uses two existing projects without making either one its implementation home:

- [`stablecoin-x402-gateway`](https://github.com/kfangw/stablecoin-x402-gateway) provides the reference payment rail, EIP-3009 patterns, signed receipt patterns, and fault-recovery examples.
- [`agent-payment-arena`](https://github.com/kfangw/agent-payment-arena) provides evaluation and statistical infrastructure.

Exact upstream revisions are recorded in [`UPSTREAMS.lock.json`](UPSTREAMS.lock.json). The repository does not use Git submodules.

## Local checks

```bash
make check
```

The check validates every JSON artifact, checks normative document completeness
and x402 inline schemas, verifies profile hashes and fixed vectors, runs the Go
tests, and runs the Foundry contract tests.

## License

MIT. See [`LICENSE`](LICENSE) and [`NOTICE`](NOTICE).
