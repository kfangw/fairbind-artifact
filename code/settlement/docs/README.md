# Documentation

This directory separates normative protocol rules from design context and
project planning. Start with the protocol specification when implementing or
reviewing behavior.

## Normative specification

[`spec/README.md`](spec/README.md) lists the version 1 specification in reading
order. The core protocol is defined in [`spec/fairbind-v1.md`](spec/fairbind-v1.md).
The remaining files define canonicalization, cryptography, Merkle trees,
contract interfaces, lifecycle rules, predicates, sortition, profiles,
governance, x402 integration, and property traceability.

## Design context

- [`architecture.md`](architecture.md) describes the component boundaries and
  trust model.
- [`threat-model.md`](threat-model.md) records the adversaries, protected
  properties, assumptions, and residual risks.
- [`decisions/`](decisions/) contains numbered architecture decision records.

## Project status

[`implementation-plan.md`](implementation-plan.md) tracks milestones and their
acceptance requirements. M0 through M3 have reference implementations. M4
covers judgment and review, and M5 covers the integrated artifact and public
testnet deployment.

Protocol changes must follow the change-control rules in
[`../AGENTS.md`](../AGENTS.md) and the implementation plan.
