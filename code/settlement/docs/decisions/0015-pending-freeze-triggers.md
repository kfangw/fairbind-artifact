# ADR 0015: Keep a bond account frozen while any initial FAIL is pending

Status: Accepted 2026-09-26. Revises the freeze bookkeeping of ADR 0012 and
the overturn edge of ADR 0013 in `fairbind-v1.md` sections 5.4, 18, 21.1, 21.3
and 22, `lifecycle-v1.md` sections 3 and 10, and `contract-interface-v1.md`
sections 10 to 12. Amended 2026-09-28 by ADR 0021: a confirmed failure while
the account is `CLAIM_OPEN` moves `freezeBlock` to its block (decision 6 no
longer keeps the first freeze block), a pending trigger holds every
unreleased entry of its account, and reinstatement is admitted while the claim
window is open.

## Problem

ADR 0012 freezes a bond account on the first initial `FAIL` and records one
trigger, `freezeNonce`. While the account is already `FROZEN` or `CLAIM_OPEN`,
a later initial `FAIL` on another case of the same account changes nothing:
`_freeze` returns early and the case is not remembered as a trigger.

The overturn path then releases too much. Take two cases `A` and `B` under one
bond account:

1. `A` receives an initial `FAIL`. The account becomes `FROZEN` with trigger
   `A`, and the seller is `SUSPENDED`.
2. `B` receives an initial `FAIL`. The freeze is already in place, so nothing
   is recorded.
3. `A` is overturned on review. Its case ends without a failure, the freeze is
   cleared, and the seller returns to `ACTIVE`.

At this point `B` is still an undecided initial `FAIL`, yet the frozen entries
are back on their release schedule and settlements are admitted again. Nothing
restores the hold until a keeper notices `B` and calls `freezeSellerDeferred`.
In between, new buyers pay a seller whose failure is pending, which is what the
immediate stop of ADR 0013 exists to prevent, and an entry whose release block
passes in that interval can be released to the seller before `B` is decided.
The same gap opens after a claim window: if `B`
is still pending when `forfeitUnclaimed` closes the window of `A`, the account
leaves `CLAIM_OPEN`, and sibling registrations under it can settle again, and
the seller owner can reinstate, while `B` is undecided.

The rule ADR 0012 intended is that an initial `FAIL` stops new settlements
under the account and holds its unreleased entries until that case is decided.
With one trigger slot, that rule holds only for the first trigger.

## Decision

The contract keeps, per bond account, the set of pending initial-`FAIL`
triggers.

1. Pending trigger. A case becomes a pending trigger of its seller's bond
   account when it receives an initial `FAIL` (in `judge`, or through
   `freezeSellerDeferred`), whatever the freeze state of the account at that
   moment. It stops being pending when the case reaches a terminal state:
   final `FAIL`, `UNSERVED`, final `PASS` or `INCONCLUSIVE`, or protocol
   `INCONCLUSIVE`. A case is recorded at most once, even if its initial
   verdict is voided by an evidence timeout and judged again.
2. Settlement admission. `settle` refuses a registration whose bond account has
   a pending trigger, in addition to the existing `FROZEN` and `CLAIM_OPEN`
   checks.
3. Overturn with triggers left. When the case anchoring a `FROZEN` account ends
   without a failure and another trigger is still pending, the account stays
   `FROZEN` and the freeze re-anchors to the earliest remaining pending
   trigger: `freezeNonce` becomes that case, `freezeBlock` is unchanged, the
   seller stays `SUSPENDED`, and the contract emits `FreezeReanchored`.
   `releaseFrozen` follows the same rule.
4. Overturn of the last trigger. When the anchoring case ends without a
   failure and no trigger is left, the freeze is released as before
   (`FrozenReleased`). The seller of that trigger returns to `ACTIVE` if it was
   suspended at or after `freezeBlock`, that is, by this freeze.
5. Reinstatement. `reinstateSeller` additionally requires that the bond
   account has no pending trigger.
6. Confirmed failure during an open claim window. Unchanged: a second final
   failure while the account is `CLAIM_OPEN` extends `claimUntilBlock` to
   `finalBlock + claimWindowBlocks` if that is later, counts once toward
   `failureLimit`, and keeps the window anchored to the first confirmed
   failure. The confirmed case leaves the pending set.

`freezeBlock` does not move on re-anchoring because the account admitted no
settlement since it: the window is defined by ledger state at the first
freeze, and every entry settled before it is still held.

The set is stored as a doubly linked list keyed by case nonce, with the head,
tail and count per bond account, so recording and removing a trigger are
constant-time and no call iterates. The router exposes it as
`getFreezeTriggers(bondId)`.

A registration other than the trigger's own is not suspended by a freeze (its
settlements are refused through the bond check). A registration suspended by
an overturned trigger that is not the last one returns to `ACTIVE` through
`reinstateSeller` once the account is released; the protocol does not track
which registrations each trigger suspended.

## Consequences

- An undecided initial `FAIL` always blocks new settlements under its bond
  account and keeps the unreleased entries held, regardless of the order in
  which several cases are decided or whether a claim window closed meanwhile.
- A keeper no longer needs to call `freezeSellerDeferred` to repair the gap;
  the call remains for a pending case of an account that is not frozen.
- An honest seller with several simultaneous wrong initial `FAIL` verdicts is
  held until the last is decided. The delay is bounded by the appeal horizon of
  the latest of them, which ADR 0012 already bounds per case.
- Storage grows by one list entry per pending case and is cleared when the case
  ends. The seller and bond views are unchanged; the router gains one view and
  one event, and the storage layout gains two mappings appended after the
  existing ones.

## Properties

- P1: unchanged.
- P2: strengthened. A buyer who settles is never admitted into a window that a
  pending failure of the same bond account could later need to cover, and
  entries held for a pending failure are not released before it is decided.
- P3: unchanged in loss terms. An overturn still releases every held entry and
  forfeits nothing; only the release time can move to the decision of the last
  pending trigger.
- P4: unchanged.

## Regression

`contracts/test/FairBindBond.t.sol`:

- two initial `FAIL`s, the first overturned: the account stays `FROZEN`,
  re-anchored to the second with the same `freezeBlock`, the seller stays
  `SUSPENDED`, settlement, release and reinstatement are refused (the old
  behaviour released the freeze and reactivated the seller here);
- both overturned: the account is released, nothing is counted or forfeited,
  the seller is `ACTIVE` and can settle;
- the second confirmed while the claim window of the first is open:
  `claimUntilBlock` is extended, the failure is counted once, and the window
  stays anchored to the first;
- a trigger still pending when the claim window closes: reinstatement and
  sibling settlement are refused until it is decided.

The stateful suite models the pending set independently and checks that the
contract count matches it, that no freeze is released and no seller
reactivated while it is nonempty, and that settlement and reinstatement are
refused exactly when it is nonempty.
