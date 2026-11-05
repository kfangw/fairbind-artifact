# ADR 0012: Freeze all deferred funds on the first final failure

Status: Accepted 2026-09-22, together with ADR 0011 and ADR 0013. Replaces the
version 1 refund source rule in `lifecycle-v1.md` section 9 and
`fairbind-v1.md` section 18. Text amended 2026-09-26: the freeze
lands at the initial `FAIL` and the claim window opens at the final `FAIL`; see
the first amendment at the end. Amended 2026-09-28 by ADR 0018, ADR 0019 and
ADR 0020: the freeze lands at the initial `FAIL` only under the profile flag
`freezeOnInitialFail`, otherwise at the confirmed failure; a confirmed failure
deducts a share of the bond; `L` budgets the tiebreak; see the second
amendment. Amended 2026-09-29 by ADR 0022: the forfeited remainder (item 6) is locked in the contract instead of split between the verifier reward pool and the reserve.

The freeze is keyed to the bond account of ADR 0011, not to a single seller
registration: one confirmed failure under a bond account freezes the deferred
entries of every registration that names that bond account. This keeps the
freeze in the same unit as the exposure condition and as the failure counter of
ADR 0013.

## Problem

Version 1 refunds a failed transaction from its own deferred amount, and
explicitly forbids using another purchase's deferred funds
(`lifecycle-v1.md` section 9, `fairbind-v1.md` section 18). A buyer is therefore
made whole only if its own purchase was the one sampled and judged. Every other
buyer of the same seller in the same window, who bought the same defective
service, is paid in full to the seller because no case was ever opened on its
purchase.

The sampling rate is the whole point: only a small fraction of purchases are
judged. Under policy A the recovery that the protocol actually delivers is
therefore proportional to the sampling rate, not to the harm. The bond has to
close that gap on its own, which is why the required bond carries the full
`Lambda * L` term even when the contract is already holding the money.

The measured exchange curve makes the alternative concrete. With `B(D)` the
required bond at deferral `D`, `B(D) + K(D)` is constant for `D <= L`, where
`K(D)` is the capital the honest seller has locked. Moving from bond to holding
does not reduce the total capital the system requires; it moves it. At `D = L`
the bond term collapses to `g/p` and becomes independent of the settlement rate.
What is missing in version 1 is that the money already being held is not
reachable by the buyers it should protect.

## Decision

On the first final failure under a bond account, freeze the entire deferred
ledger of that bond account, and let the affected buyers claim against the
frozen pool.

1. Trigger. A final `FAIL` content verdict, an `UNSERVED` case outcome, or an
   epoch failure for a seller registration freezes every deferred entry of that
   registration's bond account that has not already been released — across all
   registrations naming that bond account, not only the entry belonging to the
   failed purchase.
2. Hold only. Freezing transfers nothing. It blocks `releasePurchase` and blocks
   the release half of `finalizeCase` for every frozen entry. It does not create
   a refund right.
3. Appeal window. The freeze is held until the failing case's appeal window
   closes, following the existing `appealUntil` rule in `lifecycle-v1.md`
   section 6. Nothing may be paid out or forfeited before that block.
4. Overturn. If review overturns the failure, `releaseFrozen` clears the freeze
   and every entry returns to its ordinary release schedule. The honest seller
   loses time, not money.
5. Stands. If the failure stands, the frozen window opens for claims. A buyer
   whose purchase settled inside the frozen window presents its seller-signed
   receipt and, for a sampled epoch, its inclusion proof, and receives its own
   purchase amount from the frozen pool through `claimRefund`. The claim window
   is the profile parameter `claimWindowBlocks`, set equal to `retentionBlocks`:
   the period for which a buyer is required to hold its receipt is the period in
   which it may claim. The name is kept distinct from the existing
   `claimBlocks`, which is the buyer's dispute-opening period.
6. Remainder. When the claim window closes, the unclaimed remainder is forfeited
   and split by a profile-fixed ratio between a verifier reward pool and a
   protocol reserve, the default being one to one (`forfeitVerifierPpm` at half
   of PPM). It is never returned to the seller and never paid to a buyer who did
   not claim.

The frozen window is the set of deferred entries of the bond account not yet
released at the freeze block. It is defined by ledger state, not by a time range
the seller could influence.

### Bond requirement

With the freeze in place the required bond becomes

```text
B >= g * (1/p + Lambda * max(0, L - D))
```

where `D` is `deferBlocks` and `L` is the enforcement delay below. When
`D >= L`, nothing that a detected seller sold has been released by the time the
freeze lands, the second term is zero, and the bond requirement is `g/p`,
independent of the settlement rate. The rate cap of ADR 0011 is then a
defence-in-depth component rather than a load-bearing one, and it becomes
mandatory only for a profile operated with `D < L`.

### Definition of L in blocks

`L` is the worst-case number of blocks from a bad settlement to the block at
which the seller's failure is final and new settlements stop. From the formulas
already in `lifecycle-v1.md` sections 1, 2, 6 and 7, and reusing `openHorizon`
from `profile-v1.md` section 3:

```text
openHorizon      = max(2 * epochBlocks + anchorBlocks + sealBlocks + openBlocks,
                       responseBlocks + claimBlocks) + Delta
judgmentHorizon  = maxAssignments * (judgeBlocks + 1) + evidenceBlocks
appealHorizon    = appealBlocks + 1 + maxAssignments * (judgeBlocks + 1)
sanctionBlocks   = 1

L = openHorizon + judgmentHorizon + appealHorizon + sanctionBlocks
```

`openHorizon` covers the epoch boundary, the anchor grace, the fixed randomness
block, the seal window and the sample-opening window, and takes the maximum
with the buyer dispute path, which may open as late as `claimUntil`. `Delta` is
the delayed-reveal offset of the randomness decision: the sampling beacon is the
RANDAO value of the L1 block `Delta` blocks after the L1 block that carries the
anchor deadline, so `Delta` L1 blocks (about twelve seconds each) are added
before the sample can be opened. `beaconSlackL1Blocks`, the caller's allowance
around that L1 block, defaults to zero and adds nothing to `L`.
`judgmentHorizon` covers bounded reassignment within the initial stage and one
evidence-disclosure window. `appealHorizon` covers the window in which an
initial `FAIL` becomes final plus one party review, which is the only review
path reachable from `FAIL`. `sanctionBlocks` covers the single public call that
records the sanction. `L` is strictly smaller than the `caseHorizon` of
`profile-v1.md` section 3, which also budgets the automatic-recheck path and the
independent buyer recovery procedures; `caseHorizon` continues to govern
`deferBlocks` and `retentionBlocks`, so `deferBlocks >= caseHorizon >= L` holds
by construction for every admissible profile. Profile admission must check
`enforcementBlocks >= L`, which the current `enforcementBlocks > 0` rule does
not.

### Cost to an honest seller

The cost of a wrong failure verdict against an honest seller under this decision
is delay to release, not loss. The frozen ledger returns in full on an overturn;
no principal moves during the freeze. The magnitude of the delay is bounded by
the appeal window plus, in the worst case, the claim window. The magnitude of
the capital affected is the seller's own locked capital `K(L) = Lambda * v * L`,
which the measured curve puts at roughly 2.5 USDC at the ninety-ninth percentile
of window-average rates and roughly 126 USDC at the maximum peak-hour rate.
This is the honest-seller cost that the design notes should state, and it should be
stated as a delay distribution, not as a loss probability.

The freeze does not by itself reduce the total capital the system ties up. The
curve shows `B(D) + K(D)` constant for `D <= L`. What it changes is who can
reach the held money when a failure is confirmed, and therefore what the bond
has to cover on its own.

## State machine, interface, invariants

State additions:

- A `FROZEN` sub-state on the bond account's deferred ledger, with
  `frozenAtBlock` and `freezeCaseNonce`. A frozen entry is otherwise unchanged
  and retains its financial state.
- `CLAIM_OPEN` as a bond-account-level state entered when the triggering failure
  becomes final, with `claimUntilBlock = finalBlock + claimWindowBlocks`, and
  `CLAIM_CLOSED` after forfeiture.
- A purchase in a frozen window that has no case of its own gains a
  `FROZEN_CLAIMABLE` financial state between `CLAIM_OPEN` and its claim or the
  forfeiture, sitting between `DEFERRED` and `REFUNDED`/`RELEASED`.

Interface additions in `fairbind-v1.md` section 21.5 and
`contract-interface-v1.md` section 10:

```solidity
function freezeSellerDeferred(bytes32 triggerNonce) external;
function releaseFrozen(uint32 bondId) external;
function claimRefund(
    bytes32 nonce,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature,
    ReceiptProof calldata proof
) external;
function forfeitUnclaimed(uint32 bondId) external;
function getFrozenPool(uint32 bondId) external view returns (FrozenPoolView memory);
```

The entry point keeps the name `freezeSellerDeferred` used elsewhere in the
specification, but its effect and its bookkeeping are per bond account; the
argument of `releaseFrozen`, `forfeitUnclaimed` and `getFrozenPool` is therefore
a `bondId`.

`freezeSellerDeferred`, `releaseFrozen` and `forfeitUnclaimed` are public
progress calls with no caller-selected result and belong in the list in
`lifecycle-v1.md` section 10. The existing single-argument `claimRefund` remains
for the case whose own purchase failed and for epoch failure, where the contract
record already establishes membership; the new overload serves a buyer whose
purchase was never judged and must therefore present a receipt.

Invariants to add to `fairbind-v1.md` section 22:

- No frozen entry is released, refunded or forfeited before the triggering
  case's appeal window closes.
- The sum of refunds paid from a frozen pool never exceeds the pool balance, and
  each purchase is paid at most once.
- A claim is accepted only for a purchase whose seller, profile and epoch match
  a valid seller-signed receipt, only for a purchase whose seller registration
  names the frozen bond account, and only inside the claim window.
- An overturned failure releases exactly the entries it froze and forfeits
  nothing.
- Forfeited value reaches only the verifier reward pool and the protocol
  reserve, in the profile-fixed ratio.
- A purchase is released, refunded, or forfeited-against, never two of the
  three.

Tests: freeze covering entries across several epochs and across two or three
seller registrations under one bond account, and leaving a registration under a
different bond account untouched; freeze
during an open case on another purchase; overturn releasing the full set;
double-claim rejection; claim with a receipt for the wrong seller, profile,
epoch or chain; claim one block after the window; forfeiture split arithmetic
and rounding; a frozen entry whose own case is still running at the claim
deadline; interaction with the independent buyer recovery record of ADR 0008, in
particular that a recovery deposit is not paid out of the frozen pool;
conservation over the whole pool.

## Alternatives considered

Policy A as it stands. Rejected: recovery scales with the sampling rate rather
than with the harm, and the bond has to carry the full rate term even while the
contract is holding more than enough money to pay the affected buyers.

Refund all frozen entries automatically, without a claim. Rejected: the contract
does not know which settlements were defective, and an automatic refund of a
whole window converts every confirmed failure into a full clawback of that
window's revenue, including purchases that were served correctly. It also
requires the contract to iterate an unbounded ledger in one transaction, which
the bounded-progress requirement of `fairbind-v1.md` invariant 12 forbids. The
claim path puts the per-buyer work on the buyer and keeps every call bounded.

Slash-only, with no freeze. Rejected: it makes recovery depend entirely on bond
size, which is what the rate term was introduced to avoid, and it pays the
seller the revenue of the window in which it was failing.

Freeze a fixed time window rather than the unreleased ledger. Rejected: a
seller could shape the window by timing settlements around the boundary, and the
unreleased ledger is already exactly the set of money the contract still
controls.

## Amendment 2026-09-28: freeze timing, cost, and L

ADR 0020 makes the freeze timing a profile parameter. Read the decision and
the first amendment as follows:

- Trigger. Under `freezeOnInitialFail = true` the freeze and the suspension
  land at the initial `FAIL`, as the first amendment says; a production build
  admits only `false`, under which an initial `FAIL` changes nothing and the
  confirmed failure freezes, suspends and opens the claim window in one step.
  The outcomes that are final at once (`UNSERVED`, a missed anchor, a
  `FINAL(INCONCLUSIVE)` above the threshold once `minJudgedCount` is met)
  freeze at that moment under either setting.
- Item 4 and "Cost to an honest seller". The sentence "the honest seller
  loses time, not money" is withdrawn. An overturned initial `FAIL` still
  releases the frozen entries and costs nothing (and under `false` never
  froze). A wrongful *confirmed* failure, however, opens the claim window on
  the frozen pool, so every buyer that claims takes its purchase amount from
  the seller's revenue and the rest is forfeited, and it deducts
  `sellerPenalty / failureLimit` from the bond (ADR 0018). The honest seller's
  cost is money, bounded by the frozen pool plus one share, at the per-judged-
  case probability `u` of `profile-v1.md` section 4.
- "Definition of L in blocks". `appealHorizon` becomes `appealBlocks +
  2 * (1 + maxAssignments * (judgeBlocks + 1))`: a party review that disagrees
  with the initial verdict goes to a tiebreak (ADR 0019), and a `FAIL` can be
  confirmed there. `L` remains strictly smaller than `caseHorizon`.
- The argument for the early freeze in the first amendment is retained for
  profiles below `caseHorizon` only, which a production build does not admit.

## Amendment 2026-09-26: the freeze lands at the initial FAIL

This section corrects the text of this record to match the specification and
the contract. It changes no rule that `fairbind-v1.md`, `lifecycle-v1.md` or the
contract implement, and it changes no code.

The title and the decision above say that the freeze happens on the first
*final* failure. What was specified and implemented is a two-step rule:

1. Freeze at the initial `FAIL`. An initial `FAIL` verdict (in `judge`, or
   through `freezeSellerDeferred` for a case holding one) freezes the unreleased
   deferred ledger of the seller's bond account and suspends the seller. The
   outcomes that are final at once, `UNSERVED`, a missed anchor, and a
   `FINAL(INCONCLUSIVE)` above the inconclusive threshold, freeze at that
   moment, which is also their final moment. This is the reading
   `fairbind-v1.md` section 18 ("Freeze. An initial `FAIL` verdict, a final
   `FAIL`, ..."), `lifecycle-v1.md` section 3, and ADR 0015 already use.
2. Claim window at the final `FAIL`. The claim window opens only when the
   failure becomes final (`CLAIM_OPEN`, `claimUntilBlock = finalBlock +
   claimWindowBlocks`), as item 5 and the state-machine section above already
   say. An overturn in between releases the freeze (item 4) or, under ADR 0015,
   re-anchors it to another pending initial `FAIL`.

Read accordingly:

- The title means "freeze all deferred funds on the first failure verdict, and
  open claims on the first final failure".
- Decision item 1 ("Trigger") covers an initial `FAIL` content verdict, not only
  a final one; the other listed outcomes are unchanged.
- Item 3 ("Appeal window") describes why the initial-`FAIL` freeze is a hold
  only: nothing is paid out or forfeited before the appeal window of the
  triggering case closes.
- "Definition of L in blocks" is unchanged. `L` still runs to the block at
  which the failure is final, because the claim window, the failure count and
  the sanction wait for it; the freeze itself lands earlier, at the initial
  verdict inside `judgmentHorizon`, so the stated bound is conservative for the
  freeze.
- The suspension of ADR 0013 decision 1, item 1 lands at the same moment as the
  freeze, the initial `FAIL`; the failure is recorded against the bond account
  only at the final `FAIL`.

The reason for freezing at the initial verdict is the one ADR 0013 gives for
keeping the stop immediate: between an initial `FAIL` and its final outcome a
seller that is failing would otherwise keep selling, and entries whose release
block passes in that interval would be paid to it before the appeal decides.
