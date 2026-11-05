# ADR 0006: Bind Initial Assignment to Sealed Epoch Randomness

Status: Accepted conformance fix
Date: 2026-09-08

## Problem

A wrong-delivery dispute opened before sealing copied a zero randomness value.
Later assignVerifier read the sealed checkpoint but still derived its tickets
from that zero case value. The epoch was sealed, but its randomness did not
influence the initial assignment.

## Decision

After requiring a sealed epoch, initial assignment copies its immutable epoch
randomness into the case. Later review stages retain their separate randomness.
Identifiers, snapshot selection, fund priority, and deadline rules do not change.
This corrects the implementation to the existing fixed-future-randomness rule.

## Verification

The pre-seal wrong-delivery regression fails before the fix and passes only
when the case uses the sealed epoch hash. Existing sampled assignments must
continue to use the same epoch value. Review-stage behavior is still planned.
