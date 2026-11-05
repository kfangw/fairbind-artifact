# ADR 0018: Deduct a share of the bond on every confirmed failure

Status: Accepted 2026-09-28. Amends decision 1 of ADR 0013 (items 1, 2 and
4) and item 4 of ADR 0012 in `fairbind-v1.md` sections 18, 21.3 and 22,
`lifecycle-v1.md` sections 8 and 9, `profile-v1.md` section 4 and
`contract-interface-v1.md` section 12. Amended 2026-09-28 by ADR 0021: a
failure window that opens at scale factor `n` sanctions at `n *
failureLimit` and charges `n * sellerPenalty`; decision 2 reads with that
threshold. Amended 2026-09-29 by ADR 0022: a deduction stays locked in the contract instead of going to the penalty treasury.

## Problem

ADR 0013 charges the reserved seller penalty once, when the confirmed
failures of a bond account within `failureWindowBlocks` reach `failureLimit`.
Before that count is reached a confirmed failure costs the seller a suspension,
the claim window on its frozen pool and the time to reinstate, but nothing from
the bond. ADR 0013 wrote this as "the honest seller loses time, not money".

Two things are wrong with that. First, the sentence is false for the honest
seller as well: a wrongful final `FAIL` opens the claim window on the frozen
pool, and every buyer that claims takes its purchase amount from money the
seller earned; what is not claimed is forfeited. Second, for a cheating seller
the bond is idle until the limit. With the limits of ADR 0019 (13 and 20 in the
evaluation profiles) a seller that spreads its failures over several windows
never reaches the limit and never pays from the bond; each episode costs it
only the frozen pool of that episode, and the reinstatement condition
`balance >= sellerPenalty` is met without a top-up because nothing was taken.
The one-time slash is then a threshold the seller can stay under, not a price
it pays per failure.

## Decision

Every counted confirmed failure deducts a share of the seller penalty from the
bond account, and the failure that reaches `failureLimit` deducts the
remainder, so that the deductions of one failure window sum to exactly
`sellerPenalty`.

1. Share. `penaltyPerFailure = sellerPenalty / failureLimit` (integer
   division). On every counted confirmed failure — a `FINAL(FAIL)`, an
   `UNSERVED` outcome, a proven omission or equivocation, or the first
   refund of an epoch that failed for a missed anchor — the contract deducts
   `min(penaltyPerFailure, balance)` from the bond balance, transfers it to the
   penalty treasury, recomputes the scale factor, and emits `Slashed` with
   `actorType` 1 and `reason` 4.
2. Limit. When the count reaches `failureLimit` inside a window, the failure
   deducts `min(sellerPenalty - (failureLimit - 1) * penaltyPerFailure,
   balance)` instead, emits `Slashed` with `reason` 1, sanctions the seller and
   marks the account, as before. After the sanction no further deduction is
   made.
3. Uncounted. A `FINAL(INCONCLUSIVE)` above the inconclusive threshold freezes
   and suspends but deducts nothing, as it counts nothing. A later refund of an
   epoch already counted deducts nothing.
4. Reinstatement. `reinstateSeller` keeps requiring `balance >= sellerPenalty`,
   so a seller that was deducted has to top the share back up before it sells
   again. The scale factor of an account below one penalty is zero, so the
   account admits no settlement until then even under another registration.
5. Overturn. Nothing changes: an initial `FAIL` that is overturned was never
   confirmed and deducts nothing.

The window arithmetic is on the existing counter: a count that restarts after
`failureWindowBlocks` restarts the shares as well, so a bond account that is
never topped up can lose more than one penalty across several windows, one
share per confirmed failure, bounded by its balance.

## Consequences

- A cheating seller pays `sellerPenalty / failureLimit` per confirmed failure
  from the first one, and the whole penalty over any window with
  `failureLimit` failures. Staying under the limit no longer keeps the bond
  intact.
- An honest seller wrongly failed loses the share plus whatever its buyers
  claim from the frozen pool. The cost of a wrongful confirmed failure is
  therefore money, bounded by `sellerPenalty / failureLimit` plus the frozen
  pool of that window, and the probability of one is the per-judged-case `u`
  of `profile-v1.md` section 4. Neither ADR 0012 nor ADR 0013 may describe the
  cost as delay only; both are amended.
- The bond requirement of ADR 0012 is unchanged: `sellerPenalty` is still the
  amount reserved and still charged in full over a window at the limit.
- ADR 0011's exposure bound is unchanged; the deduction lowers the scale factor
  at once, which can only reduce the settlements the account admits.

## Properties

- P1: unchanged.
- P2: unchanged. Refunds and claims are paid from the deferred ledger as
  before; the bond is not a refund source.
- P3: the stated bound now carries a monetary term. The probability of a
  wrongful confirmed failure per judged case is unchanged; its cost is one
  share of the penalty plus the claims on the frozen pool, instead of a delay.
- P4: unchanged.

## Interface

`Slashed(1, sellerId, trigger, penaltyTreasury, share, 4)` is emitted on each
counted confirmed failure below the limit; the terminal failure keeps
`reason` 1 and `SellerSanctioned`, whose `penalty` argument now carries the
remainder charged by that failure rather than the whole penalty. Invariant 25
of `fairbind-v1.md` becomes: the deductions of one failure window sum to at
most `sellerPenalty`, the remainder is charged exactly once and only at
`failureLimit`, and no deduction follows the sanction.

## Regression

`contracts/test/FairBindFailureCosts.t.sol`:

- three confirmed failures under a `failureLimit` of three: the bond loses one
  share after the first, two after the second, and the remainder at the third,
  with the treasury receiving exactly one penalty and `Slashed` reporting
  reason 4 twice and reason 1 once (the old rule left the balance untouched
  until the third);
- a count that restarts without a top-up: later shares are clipped to the
  remaining balance and no sanction follows;
- an above-threshold `FINAL(INCONCLUSIVE)` deducts nothing, and the refunds
  of an epoch that failed for a missed anchor deduct once;
- reinstatement after one failure is refused until the share is topped up.

`contracts/test/invariant/LifecycleObserver.sol` replays the shares per
counted failure and compares the bond balance after every action.
