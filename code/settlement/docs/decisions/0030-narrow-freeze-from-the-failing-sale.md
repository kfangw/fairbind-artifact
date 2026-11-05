# ADR 0030: A confirmed failure freezes from the failing sale

Status: Accepted 2026-10-19. Amends ADR 0012 (freeze of every deferred
entry), ADR 0021 (moving the frozen window in an open claim window) and ADR
0022 (forfeiture of the frozen window) in `contract-interface-v1.md` ("ADR
0030 narrow freeze") and `traceability.md`. Changes the behavior of the
freeze, `releasePurchase`, the frozen-pool `claimRefund`, `forfeitUnclaimed`
and `purchaseState` without changing their signatures; appends two views, one
event and five storage mappings; changes no existing storage slot, purchase
field or encoding.

This record implements design 2 rule D2-6 (a) 1 to 4 and the start of the
freeze of rule D2-6 (b).

## Problem

ADR 0012 freezes every unreleased deferred entry of the bond account at the
first confirmed failure. The rule the sampling bound is proved under freezes
less: a confirmed failure tied to the purchase settled in block c holds only
the unreleased entries settled from c on. Entries settled before c were sold
before the fraudulent sale that the failure detects and keep their release
schedule; the bound on the buyers' exposure counts only sales before the
first detected fraudulent sale and never relies on holding them. Holding them
costs an honest seller every unreleased sale at each wrongful failure.

## Decision

1. **Start of a freeze.** Each confirmed failure has a start c:
   - a failure tied to a purchase (FINAL(FAIL), UNSERVED, omission,
     equivocation, a failed sample receipt) starts at that purchase's
     settlement block;
   - a missed anchor starts at the first block of its epoch (the rule names
     the epoch's first sale; no sale of the seller lies between the two, and
     an entry of another registration of the same account settled there is
     held too);
   - an inconclusive window above its threshold starts at the settlement block
     of the purchase whose case gave the window's first inconclusive verdict
     (`inconclusiveFloor`);
   - an initial FAIL under `freezeOnInitialFail` (test builds only) starts at
     its purchase, and its pending trigger still holds every entry as in ADR
     0015.
2. **Frozen window.** The frozen window of an open freeze is a list of
   ordered, disjoint spans of settlement blocks (`freezeSpans`). The first
   failure of a freeze opens the span [c, failure block]. A later failure,
   whatever the seller's status (active, suspended, exiting, reinstated):
   - in `FROZEN` lowers the start of the window to c when c is earlier;
   - in `CLAIM_OPEN` moves `freezeBlock` to its block as in ADR 0021 and adds
     [c, failure block]: the new span absorbs every span it meets, so a c
     inside or before the window lowers its start, and a c after the last
     span (a failure tied to an entry settled after a reinstatement) adds a
     separate span. An entry settled after a reinstatement and before that c
     is outside the window.
   `freezeBlock` stays the end of the last span. An entry is frozen exactly
   when its settlement block lies in a span (or a pending trigger holds it).
3. **Claims.** `claimRefund` (frozen pool) accepts only entries in a span; it
   reverts `ReceiptOutOfWindow` for an entry settled before the window's start,
   between spans, or after the window.
4. **Forfeiture.** `forfeitUnclaimed` records the window's spans as closed
   windows (`forfeitWindows`). When the window is one span and the deferred
   balance holds no entry settled before it (`deferredFloor`, the first
   settlement after the deferred balance was last empty, is at or after the
   span's start, and no earlier window waits to be swept), it forfeits the
   unencumbered deferred balance outside the entries settled after a
   reinstatement as one sum, as before. Otherwise the window closes
   *itemized*: nothing is taken at once, each unclaimed entry of its spans is
   reported `FORFEITED` and leaves the deferred balance into `lockedForfeit`
   when `releasePurchase` next touches it. Earlier entries keep their schedule
   in both cases. The contract cannot sum the entries of a range of
   settlement blocks without iterating them; the itemized close avoids that.
5. **Reporting.** `getFrozenPool().poolBalance` is unchanged in definition and
   is an upper bound of the claimable pool when the account holds unreleased
   entries settled before the window.

## Consequences

- An honest seller's wrongful failure no longer holds its earlier sales.
- The buyers of sales before the failing sale are no longer refunded from the
  frozen pool; the exposure bound does not use them.
- `settle` reads `deferredBalance` before adding to it and writes
  `deferredFloor` when the balance was empty (one warm slot write on the
  first settlement of an account or after it was drained).
- A bond account with an itemized window cannot finish its exit until every
  entry of the window has been swept by `releasePurchase`.
- The stateful suite's frozen-window model (`LifecycleHandler._frozen`, the
  observer's conservation of the frozen pool) still encodes ADR 0012 and has
  to follow this record.

## Tests

`NarrowFreeze.t.sol`: the narrow window on the delivery path, a missed
anchor and an inconclusive window, each against a mutation build that
freezes from block zero (`NarrowFreezeMutants.sol`); a later failure that
lowers the start of a suspended account; a failure after a reinstatement
that adds a span; the one-sum and itemized forfeitures.
