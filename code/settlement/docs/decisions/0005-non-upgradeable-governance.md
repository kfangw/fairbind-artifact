# ADR 0005: Non-upgradeable Contract with Delayed Admission Controls

Status: Accepted
Date: 2026-09-04

## Context

An upgradeable contract could change deadlines, fund priority, or case outcomes
after a buyer signs. FairBind still needs to admit profiles and stop new exposure
when an incident occurs.

## Decision

The version 1 contract is not upgradeable. A governance timelock may create and
activate immutable profiles. An emergency guardian may pause new activity but
cannot block any call that completes an existing obligation. Public-network
administration uses a two-of-three multisignature wallet and a delay of at least
two days.

## Consequences

A protocol change requires a new deployment and explicit client selection. P1
through P4 continue under the contract and profile that the purchase nonce
binds. Lost governance keys can stop new activity but cannot stop public timeout,
refund, release, or exit calls.
