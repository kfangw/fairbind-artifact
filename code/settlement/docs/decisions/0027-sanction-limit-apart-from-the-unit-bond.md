# ADR 0027: A sanction limit apart from the unit bond

Status: Accepted 2026-10-12. Amends ADR 0024 (sales tiers) and ADR 0025
(committed terms) in `contract-interface-v1.md` ("ADR 0024 entry points and
views"). Adds one field to `SalesTier`, which changes the ABI of
`setProfileTerms`, `getProfileTerms` and `ProfileTermsSet` (not deployed);
changes no storage slot and no other entry.

The research decision this record implements is decision 131 of the project
record (2026-10-12): the bond is `B = b`, one deduction; holding `k * b` is an
optional protection of an honest seller (design 2 rule D2-5 (g)).

## Problem

Under a profile with tiers, `failureLimit` set two things at once: the unit
bond (`failureLimit * b`, the failures a seller prefunds) and the terminal
sanction (a failure window of scale `n` sanctions at `n * failureLimit`
failures). `failureLimit = 1` gives `B = b`, but then the first confirmed
failure is a permanent sanction, while rule D2-6 lets a seller resume after
refilling its balance to `b`.

## Decision

1. `SalesTier` gains `uint32 sanctionLimit`. `failureLimit` keeps its meaning
   for the unit bond and the per-failure deduction (`unit / failureLimit =
   b`). The terminal sanction of a window of scale `n` is reached at
   `n * sanctionLimit` failures. `sanctionLimit = 0` sets no such limit: a
   failure deducts `b`, suspends the seller and opens the claim window, and a
   deposit back to one unit bond followed by `reinstateSeller` reopens it.
2. The recent-limit rule of ADR 0024 (`peakLimit`, `windowLimit`: a window uses
   the highest limit held within `retentionBlocks`) now tracks
   `sanctionLimit`, with zero counted as the largest.
3. `termsHash` encodes the new field, so the design 2 profile documents gain
   `sanctionLimit` per tier and new `termsHash` and `parameterHash` values.
4. Two configurations: `failureLimit = 1, sanctionLimit = 0` is `B = b`
   (decision 131); `failureLimit = sanctionLimit = k` is the `k * b`
   configuration of the evaluation, whose behaviour is unchanged. Profiles
   without tiers keep the single `failureLimit`.

The separation of the scale multiplier from the balance (rule D2-7 (c)) is
not part of this record.

## Consequences

`test_unitBondWithoutSanctionLimitDeductsSuspendsAndReopens` fixes the `B = b`
path: a balance of `b` settles; twelve failures in one window (more than
`k = 11` of the tier) each deduct `b` and suspend, none sanctions, and each
deposit of `b` with a reinstatement reopens settlement.
`test_sanctionLimitEqualToTheFailureLimitKeepsTheKConfiguration` and the
existing tests keep the `k * b` configuration. The stateful suite runs both
configurations (`run.sh`, `FAIRBIND_UNIT_BOND=1` for `B = b`).

## Limits

Without a sanction limit the only stop on a seller that keeps failing is the
deduction of `b` per failure and the suspension until it deposits again; the
deterrence argument of rule D2-5 rests on `b >= v_max / p0` per failure.
