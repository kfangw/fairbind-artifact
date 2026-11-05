# ADR 0023: Admit a profile only with minVerifiers >= 3 * maxAssignments + 5

Status: Accepted 2026-09-29. Amends ADR 0004 (bounded profiles) in
`profile-v1.md` sections 2, 5 and 7, `fairbind-v1.md` section 13 and
`sortition-v1.md` section 4. Changes one admission inequality and the
`minVerifiers` value of both evaluation profiles, and with it their
`parameterHash` and the x402 vectors that carry it. Changes no encoding, no
ABI entry and no storage slot. Amended 2026-09-30: `N` counts assignable
verifiers, not checkpoint entries, with the least assignable bond of each
evaluation profile, and the statement on protocol `INCONCLUSIVE` counters is
corrected (Assumptions and limits); counting assignable verifiers in the
contract is a follow-up.

## Problem

One case can use up to `3 * maxAssignments` distinct verifiers: `maxAssignments`
attempts in each of the initial stage, the party review (or automatic recheck)
and the tiebreak, each attempt excluding every verifier that already took part
in the case (`caseParticipation`). The admission rule
`minVerifiers >= 3 * maxAssignments` only made the last of those assignments
possible, not likely.

The assignment search (`FairBindCore._assignVerifier`, `sortition-v1.md`
section 4) tries rounds `0` through `minVerifiers - 1`. Each round derives an
independent ticket, maps it to a verifier by checkpoint weight, and skips the
verifier if it already took part. With `N` equal-weight verifiers in the
epoch's checkpoint, `k` of them excluded, and `R = minVerifiers` rounds, the
search finds nobody with probability

```text
P(k, N, R) = (k / N)^R
```

and the case ends as a protocol `INCONCLUSIVE`, which releases the purchase to
the seller and counts against nobody. On a case that reaches its last
assignment, `k = 3 * maxAssignments - 1`. At the former bound with the
evaluation profiles (`maxAssignments = 3`, `minVerifiers = 9`) and exactly nine
registered verifiers, the last assignment fails with probability
`(8/9)^9 = 0.346`, and the case as a whole with probability 0.433. A local run
of the longest judgment path with nine registered verifiers ended this way at
the tiebreak.

## Decision

1. Profile admission requires

   ```text
   minVerifiers >= 3 * maxAssignments + 5
   ```

   (`VERIFIER_COUNT_MARGIN = 5` in `FairBindCore`, checked in
   `_validateProfile`).

2. The margin is the smallest integer `c` such that, for every admissible
   `maxAssignments = m` in `1..3`, a deployment with exactly
   `N = minVerifiers = 3m + c` equal-weight verifiers has

   ```text
   P(3m - 1, 3m + c, 3m + c) <= 10^-3.
   ```

   `experiments/verifier_count.py` computes it exactly with rational
   arithmetic:

   | m | excluded k | smallest N | margin | P_last(N) | P_last(N - 1) |
   | ---: | ---: | ---: | ---: | ---: | ---: |
   | 1 | 2 | 7 | 4 | 1.55e-4 | 1.37e-3 |
   | 2 | 5 | 10 | 4 | 9.77e-4 | 5.04e-3 |
   | 3 | 8 | 14 | 5 | 3.96e-4 | 1.82e-3 |

   `(k/N)^N` decreases in `N` for `N > k`, so every larger count also meets
   the target. One constant, the largest of the three (5), keeps the rule
   independent of `m`; at `m = 1` and `m = 2` it gives 1.5e-5 and 1.7e-4. The
   probability that any of the `3m` assignments of the case fails is 4.6e-4
   at `m = 3`, `N = 14`.

3. For equal-weight verifiers that are all assignable for the case (see
   Assumptions and limits), the bound holds for every admitted deployment,
   not only the minimal one. The seal already requires the epoch's checkpoint
   to hold at least `minVerifiers` entries, settlement and seller registration already require
   the latest checkpoint to hold that many, and every assignment of a case
   draws from its epoch's checkpoint, whose members cannot finish exiting
   before the epoch's retention ends. With `N >= R = minVerifiers`,
   `(k/N)^R <= (k/R)^R`. No new check is needed at case opening.

4. Both evaluation profiles move from `minVerifiers = 9` to 14, and the local
   deployment registers at least the largest `minVerifiers` of its profile
   document.

## Assumptions and limits

- Tickets are modelled as independent uniform draws (keccak256 as a random
  oracle; the modulo bias of `ticket % totalEffectiveWeight` is below
  `2^-160` for any realistic total weight).
- Weights are equal. Checkpoint weight is `min(bond, verifierBondCap)`, so
  equal bonds at or above the cap give equal weights; the local deployment
  registers every verifier with the same bond. If the `k` excluded verifiers
  hold a weight share `w`, the probability is `w^R`, and with a
  heaviest-to-lightest weight ratio `rho` the share is at most
  `k * rho / (k * rho + N - k)`. At the evaluation ratio
  `verifierBondCap / minVerifierBond = 100` the resulting probability ceiling
  at `m = 3`, `N = 14` is 0.90, so the margin is a statement about equal-weight sets, not about arbitrary ones.
- `N` is the number of assignable verifiers in the epoch's checkpoint, not the
  number of checkpoint entries. A verifier is assignable for a case when
  `_assignVerifier` would accept it: status `ACTIVE` or `EXITING`, bond at
  least `minVerifierBond`, and, with `reserve = max(verifierLatePenalty,
  verifierWrongPenalty)`,

  ```text
  lockedLiability + value + maxReviewCost
    <= min(bond - reservedPenalties - reserve, cap) * fraction / PPM
  ```

  (`profile-v1.md` section 5). For a verifier with no open assignment
  (`lockedLiability = reservedPenalties = 0`, `cap = verifierBondCap`,
  `fraction = verifierExposurePpm`) and a purchase at `maxPurchaseValue`, this
  is

  ```text
  bond >= reserve + (maxPurchaseValue + maxReviewCost) * PPM / verifierExposurePpm
  ```

  and with `c` open assignments of that size it is `c` times the right-hand
  side, up to `verifierBondCap * verifierExposurePpm / PPM` of locked
  liability. The contract does not count assignable verifiers. Profile
  admission checks only `minVerifiers >= 3 * maxAssignments + 5`. Seller
  registration and settlement (`_profileAvailable`) and the seal
  (`FairBindSampling`) count the entries of the checkpoint, and a checkpoint
  entry (`_checkpointEligible`) needs only an `ACTIVE` status, a signing key,
  the class bit and `bond >= minVerifierBond`. A deployment that passes all
  three checks can therefore have fewer than `minVerifiers` assignable
  verifiers, and the bound of decision 3 does not hold for it. If no
  checkpoint entry is assignable, every assignment search fails.
- Evaluation profiles. Both have `reserve = verifierWrongPenalty` and
  `verifierExposurePpm = 500000`.

  | profile | reserve | maxPurchaseValue + maxReviewCost | least assignable bond | minVerifierBond |
  | --- | ---: | ---: | ---: | ---: |
  | `data-api-fast-v1` | 1.00 | 0.01 + 1.00 = 1.01 | 1 + 1.01 / 0.5 = **3.02** | 1 |
  | `open-weights-standard-v1` | 10.0 | 0.1 + 10.0 = 10.1 | 10 + 10.1 / 0.5 = **30.2** | 50 |

  (token units, six decimals; the integer check accepts 3,020,000 and
  30,200,000 base units and refuses one base unit less). A data API verifier
  bonded at 1 or more but below 3.02 enters the checkpoint but is never assigned; an
  inference verifier at `minVerifierBond` is assignable for one case at a
  time. An evaluation deployment registers every verifier of the data API
  class with a bond of at least 3.02, or `3.02 * c` for `c` concurrent
  assignments. `scripts/local_setup.py` registers every verifier with the
  larger of the largest `minVerifierBond` and the smallest `verifierBondCap` of the
  created profiles, 100, which is assignable in both profiles and gives equal
  weights.
- Protocol `INCONCLUSIVE` outcomes enter no counter. `_finishReview` with
  `progressFailure` set and `_finishProtocolInconclusive` do not call
  `_recordJudged`, so `inconclusiveCount`, `judgedCount` and the
  `maxInconclusivePpm` threshold see only content verdicts of sampled cases.
  No on-chain counter records failed assignment searches per seller, per
  bond account or per class; their frequency is bounded only by the
  assumptions above. The target bounds one path in one case.

## Consequences

- A profile with `minVerifiers = 3 * maxAssignments`, admitted before, is
  refused. `contracts/test/VerifierCountAdmission.t.sol` pins the old and new
  boundaries for `m = 1, 2, 3`, and the seal, settlement and registration
  refusals at `minVerifiers - 1` verifiers.
- The evaluation profiles' `parameterHash` values change, and with them the
  x402 fixtures that advertise the data API profile hash.
- The test suites register fourteen verifiers instead of nine.

## Follow-up

- Counting assignable verifiers in the contract: the seal, `_profileAvailable`
  and `_checkpointEligible` would count only verifiers that meet the
  assignment bound above for a purchase at `maxPurchaseValue`, or profile
  admission would require `minVerifierBond >= reserve + (maxPurchaseValue +
  maxReviewCost) * PPM / verifierExposurePpm`. Either is decided against the
  remaining size margin of the affected modules and needs its own regression
  tests. Neither is implemented here.
