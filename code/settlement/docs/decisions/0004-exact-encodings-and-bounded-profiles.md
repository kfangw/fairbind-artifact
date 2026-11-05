# ADR 0004: Exact Encodings and Bounded Profiles

Status: Accepted
Date: 2026-09-04

## Context

The frozen research design defined the fields that bind a purchase but left HTTP
normalization, EIP-712 types, Merkle node encoding, and several profile units for
implementation. Different libraries would otherwise produce valid-looking but
incompatible hashes. An unbounded payment value would also invalidate a profile's
fixed seller penalty.

## Decision

FairBind version 1 uses the byte encodings in `docs/spec/canonicalization-v1.md`,
`docs/spec/cryptography-v1.md`, and `docs/spec/merkle-v1.md`. One contract
deployment supports one EIP-3009 token. Each profile limits purchase value and
uses a parts-per-million token bucket that consumes one unit per settlement.

Receipt leaves equal their EIP-712 digests. Receipt-tree nodes preserve position
and duplicate an unpaired final node. Sampling uses a separate domain-separated
hash over ledger nonces.

## Consequences

Go, Solidity, and Python implementations can share machine-readable vectors.
Services with different tokens or wider price ranges use another deployment or
profile. Supporting value-weighted bucket consumption is an additive future
profile version.

P1 gains exact cross-language identifier inputs. P2 gains explicit body and
response-size boundaries. P3 and P4 keep their existing probability arguments;
the bounded purchase value makes their economic parameters checkable.
