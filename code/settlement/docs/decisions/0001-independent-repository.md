# ADR 0001: Independent FairBind Repository

Status: Accepted
Date: 2026-09-04

## Context

The existing stablecoin gateway implements an x402 payment rail and end-to-end flow demo. The existing agent payment arena implements evaluation and statistical analysis. FairBind adds a contract-held deferred balance, seller and verifier registries, epoch anchors, ledger-nonce sampling, redelivery, disputes, review, refunds, and penalties.

Putting these states in the gateway would change the gateway from a reference flow into the FairBind protocol. Putting them in the arena would mix the system under test with the instrument that scores it.

## Decision

FairBind uses an independent repository at `kfangw/fairbind`. The repository owns the normative specification, contracts, protocol library, role processes, adapters, predicates, deployment, and paper artifact.

The gateway and arena remain external projects pinned by revision.

## Consequences

The repository can version FairBind independently and can expose compatibility adapters without changing either upstream project's purpose. Integrated experiments must coordinate three revisions, so every result records `UPSTREAMS.lock.json` with the FairBind revision.
