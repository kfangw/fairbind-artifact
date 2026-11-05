# ADR 0002: x402 Version 2 Extension Binding

Status: Accepted
Date: 2026-09-04

## Context

The reference gateway currently implements an x402 version 1 wire shape. The current x402 version 2 specification separates core payment types, asset transfer methods, payment flows, and optional extensions.

FairBind keeps the EIP-3009 authorization but changes its recipient and settlement call. The payment names the FairBind contract as recipient, and the facilitator calls the FairBind settlement entry point. FairBind negotiation also needs immutable profile and predicate data that does not belong in the base payment type.

## Decision

The first binding uses:

- x402 version 2;
- scheme `exact`;
- extension key `fairbind`;
- asset transfer method `eip3009-fairbind-v1`;
- payment flow `upfront`.

FairBind profile data uses `extensions.fairbind`. The `extra` object contains the
protocol-reserved `assetTransferMethod` and `paymentFlow` fields and the exact-EVM
`name` and `version` fields required to construct the token's EIP-3009 EIP-712
domain.

## Consequences

Existing x402 version 1 clients cannot use the binding. The reference gateway needs a version 2 adapter and a general settlement backend before it can host a FairBind resource without FairBind-specific code in its core.

Support for the `authorization` flow requires separate conformance tests because it executes the resource before settlement.
