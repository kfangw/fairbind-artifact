# ADR 0017: Count only sampled cases toward the inconclusive rate

Status: Accepted 2026-09-26. Amends decision 2 of ADR 0013 (items 2 and 3) in
`fairbind-v1.md` sections 18 and 22 and `lifecycle-v1.md` section 4.

## Problem

ADR 0013 rate-limits content inconclusives per bond account: every final
content verdict (`FINAL(PASS)`, `FINAL(FAIL)`, `FINAL(INCONCLUSIVE)`) increments
`judgedCount`, a `FINAL(INCONCLUSIVE)` also increments `inconclusiveCount`, and
a `FINAL(INCONCLUSIVE)` with `inconclusiveCount * PPM > maxInconclusivePpm *
judgedCount` freezes the account and suspends the seller.

The denominator counts party disputes as well as sampled cases, and the seller
can create party disputes at will. A seller buys from its own service with an
address it controls, keeps the receipt, and opens `WRONG_DELIVERY` on the
purchase. Its correct response ends `FINAL(PASS)` and increments `judgedCount`.
The cost is gas: the purchase amount is released to the seller after the case,
and the dispute deposit of a `FINAL(PASS)` goes to the seller owner, so both
return to the same operator. With enough padding disputes per window, the
seller keeps its ratio under `maxInconclusivePpm` while it makes every sampled
response unjudgeable, which is the behaviour decision 2 of ADR 0013 exists to
stop.

The denominator is also the wrong population on its own terms. The rate is
meant to estimate the share of the seller's traffic that cannot be judged.
Sampled cases estimate it without bias, because the purchase is selected by
the ledger nonce and fixed randomness. Disputed purchases are selected by a
party, the seller in the attack above or a buyer who suspects a fault, so they
bias the estimate in whichever direction the selecting party wants. A hostile
buyer could, in the same way, dispute responses that are hard to evaluate and
push an honest seller over the threshold with inconclusives it did not induce.

## Decision

1. `judgedCount` and `inconclusiveCount` count only cases opened by
   `openSample` (case trigger `SAMPLE`). A final content verdict of any other
   case changes neither counter and restarts no counting window.
2. The threshold test applies only to a sampled `FINAL(INCONCLUSIVE)`, counting
   the case itself, as before. A `FINAL(INCONCLUSIVE)` of a party dispute is
   never treated as a failure for freezing and suspension: it ends without
   seller failure, as a below-threshold inconclusive does, and its dispute
   deposit returns to the buyer as for every inconclusive.
3. Unchanged: a `FINAL(FAIL)` of a party dispute is a confirmed failure. It
   freezes, suspends, opens the claim window and counts toward `failureLimit`
   exactly as a sampled `FINAL(FAIL)`. A protocol `INCONCLUSIVE` still counts
   nothing. `InconclusiveRecorded` is emitted only for a sampled
   `FINAL(INCONCLUSIVE)`.

## Consequences

- A seller cannot lower its inconclusive ratio by judging its own purchases.
  Self-disputes add nothing to either counter.
- A buyer cannot raise an honest seller's ratio by disputing responses that are
  hard to evaluate. The inconclusive sanction depends only on randomly selected
  purchases.
- The rate is estimated from fewer cases. In a window with few sampled cases
  the first sampled `FINAL(INCONCLUSIVE)` can exceed the threshold on its own,
  as it already could before when no dispute was judged in the window. The
  profile's `inconclusiveWindowBlocks` and `maxInconclusivePpm` should be set
  from the sampled judged-case rate, not from the total judged-case rate; this
  is recorded as a calibration input, not a new admission rule.
- ADR 0013 rejected "treat inconclusive as failure only when the buyer
  disputes" because sampled cases are the majority of judgments. This decision
  keeps that reasoning and draws the consequence in the other direction: the
  rule is enforced on sampled cases, where it is needed and where it cannot be
  steered.
- No storage, ABI or event signature changes. The case record already carries
  its trigger.

## Properties

- P1: unchanged.
- P2: unchanged. Fund routing of every case outcome is unchanged; only which
  cases can reach the above-threshold freeze changes.
- P3: strengthened. An honest seller's inconclusive sanction can no longer be
  driven by the choice of which purchases a buyer disputes.
- P4: unchanged. No wrong-verdict penalty applies to any `FINAL(INCONCLUSIVE)`.

## Regression

`contracts/test/FairBindBond.t.sol`:

- a disputed case ending `FINAL(PASS)` leaves `judgedCount`, `inconclusiveCount`
  and the window start unchanged, and a sampled case ending `FINAL(PASS)` then
  increments `judgedCount` (the old rule incremented it for both);
- a disputed `FINAL(INCONCLUSIVE)` with every profile threshold exceeded leaves
  both counters at zero, does not freeze, and leaves the seller `ACTIVE` (the
  old rule froze and suspended here).

`invariant/LifecycleObserver.sol` replays the counters from sampled cases only
and compares them with the bond view after every action.
