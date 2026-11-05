# ADR 0021: Scale the failure threshold with the bond; allow re-entry during the claim window; reopen a failed review seal once

Status: Accepted 2026-09-28. Amends ADR 0013 (decision 1, items 2 and 4),
ADR 0015 (decision 6 and the one-slot `_freeze`), ADR 0018 (decision 2) and
ADR 0019 (decision 3, erratum below) in `fairbind-v1.md` sections 17, 18,
21.3 and 22, `lifecycle-v1.md` sections 3, 7, 9 and 10, `profile-v1.md`
sections 3 and 4 and `contract-interface-v1.md` sections 6, 9, 10, 11 and 12.
Changes no encoding of a signed or hashed message. Moves both evaluation
`parameterHash` values (new limits and hold periods), appends three mappings
to the storage layout, and adds three views and one event to the router ABI;
the pre-deployment baselines under `test-vectors/deployment/` are re-cut from
the build, as ADR 0015 did. Amended 2026-09-29 by ADR 0022: the window scale is read before the opening deduction, raised to the highest scale the account left within `retentionBlocks`, and raised by a top-up during the window; only the owner tops up.

## Problem 1: the failure threshold ignores the bond's scale

`failureLimit` is derived in `profile-v1.md` section 4 for a bond account at
scale factor one: `S` bounds the settlements that can be confirmed failed in
one failure window, and `k` is the least count with `C(S, k) q^k <= 10^-6`.
The counter is per bond account, but an account holding `n * sellerPenalty`
has scale factor `n`, a bucket `n` times as large, and settles up to `n S`
purchases per window. At the same `k` its honest owner is sanctioned in a
window with probability `P[Bin(nS, q) >= k]`: 1.3e-2 at `n = 3` and 0.83 at
`n = 7` for the data API profile (`S = 5,970`, `k = 16`), 4.0e-2 at `n = 3`
for open weights, against the `10^-6` target. A large honest seller is
punished for posting a large bond.

## Decision 1: `k(n) = n * failureLimit`

When a fixed failure window opens (the branch of `_confirmFailure` that resets
`failureCount` and sets `failureWindowStart`), the contract records the
account's scale factor, at least one, in `failureWindowScale[bondId]`. The
window sanctions when `failureCount >= failureWindowScale * failureLimit`.
Each counted failure still deducts `sellerPenalty / failureLimit`; the
failure that reaches the threshold deducts the remainder, so that the window's
deductions sum to `failureWindowScale * sellerPenalty`, each bounded by the
balance. The scale is fixed for the window: deductions lower the live scale
factor, and a top-up raises it, but neither moves the threshold of a window
already open.

At `n = 1` nothing changes. A window opened at scale `n` covers at most `n S`
settlements, and by the Chernoff bound `P[Bin(nS, q) >= nk] <= exp(-n S
D(k/S || q)) = (exp(-S D(k/S || q)))^n`, with `D` the binary relative
entropy; `k/S > q`, so the bound shrinks geometrically in `n`. At the
evaluation values `exp(-S D)` is `4.6e-07` and `6.3e-09`, below the target
already at `n = 1`, and the union bound `C(nS, nk) q^{nk}` is `2.6e-17` and
`1.3e-18` at `n = 3`. The penalty per confirmed failure is unchanged, so a
cheating seller pays the same share per failure whatever its scale.

The alternative was to refuse any scale above one (`n_max = 1`) and let a
large seller split into several accounts. It was not needed: the check fits
every module (module sizes below). A seller that prefers per-account
isolation can still split.

## Problem 2: re-entry waits for the whole claim window

ADR 0013 lets a suspended seller return only after its claim window closes,
`retentionBlocks` (60,000 blocks, about 33 hours, at the data API profile).
ADR 0018 made every confirmed failure cost a share of the bond, so the long
stop is no longer the price of a failure; it is only lost business, and for an
honest seller wrongly failed at probability `u` it is the larger part of the
cost. The claim window exists so that buyers can claim the frozen pool; it
does not need the seller to stay out.

## Decision 2: re-entry during the claim window

`reinstateSeller` is admitted while the account is `CLAIM_OPEN`, under the
conditions it already had except the closed window: the account is not
`FROZEN`, not sanctioned, has no pending initial-`FAIL` trigger, and holds at
least `sellerPenalty` (after a deduction, a top-up). A reinstatement during the
window marks the account reopened (`claimReentries[bondId].reopened`).

1. Settlement. A reopened `CLAIM_OPEN` account admits settlements from the
   block after `freezeBlock`. They settle after `freezeBlock`, so they are
   outside the frozen window: not claimable, not forfeited, and released on
   their normal schedule. Their deferred and encumbered totals are kept apart
   (`claimReentries`), and `forfeitUnclaimed` forfeits only the frozen
   window: `(deferredBalance - late deferred) - (encumbered - late
   encumbered)`. `getFrozenPool` and the pool check of `claimRefund` use the
   same window total.
2. Confirmed failure during the window. `_freeze` no longer returns early for
   a `CLAIM_OPEN` account when the trigger is a confirmed failure: it moves
   `freezeBlock` to the current block, clears the reopened flag and the late
   totals, and suspends the seller; `_confirmFailure` then extends
   `claimUntilBlock` to `block + claimWindowBlocks` as before. Every
   unreleased entry up to this block, including everything settled since the
   reinstatement, is in the frozen window and claimable once; the account
   admits nothing until the next reinstatement. `forfeitUnclaimed` waits for
   the extended `claimUntilBlock`.
3. Initial `FAIL` during the window (`freezeOnInitialFail` only). The initial
   `FAIL` suspends the seller and records a pending trigger (ADR 0015) but
   does not move `freezeBlock`, because the failure is not yet confirmed. A
   pending trigger holds every unreleased entry of the account from release,
   whatever its settlement block and freeze state, and blocks settlement and
   reinstatement. If the case is overturned, the trigger leaves the queue, the
   later entries return to their schedule, and the confirmed window keeps its
   boundary and its claims: an overturned initial `FAIL` never unfreezes an
   entry of the confirmed failure's window, and never makes a later entry
   claimable. If it is confirmed, decision 2.2 applies.
4. Exit. `finalizeSellerExit` is refused while the seller's bond account is
   `FROZEN` or `CLAIM_OPEN` or has a pending trigger. Neither the freeze nor
   the deduction depends on seller or bond status: an `EXITING` seller is
   frozen, counted and deducted like an active one, and cannot reach `EXITED`
   before its frozen pool is closed.

### Exposure bound

ADR 0012 bounds a cheating seller's exposure by the entries released before
its confirmed failure: with `D >= caseHorizon >= L`, every purchase settled
since the fraud began is still held when the failure is confirmed, so the
freeze reaches all of it. Re-entry must not break this.

After a reinstatement at block `r` during the window of a failure confirmed at
`f`, the seller sells again. Let its next fraud begin with a bad sale settled
at `s >= r > f`. That failure is confirmed at some `f' <= s + L`. Every
purchase settled in `(f, f']` has `releaseBlock >= f + 1 + D > f'` when `D >=
L`, so none has been released at `f'`; the entries of the old window were
never releasable (they are claimed or forfeited). At `f'`, decision 2.2 sets
`freezeBlock = f'`, so every purchase settled since `s`, indeed since `f`, is
in the frozen window. The bound of ADR 0012 therefore holds per confirmed
failure with re-entry exactly as without it. Keeping the old early return of
`_freeze` breaks it: the window stays at `f`, the purchases settled in `(r,
f']` stay outside, and each is released to the seller at `settledBlock + D`,
while the claim window, extended to `f' + claimWindowBlocks`, is still open.
The stateful suite has a mutation build with exactly that early return and
must detect the release (below).

Under `freezeOnInitialFail` the argument is the same with the initial `FAIL`
at `i` in place of the hold: the pending trigger holds every entry from `i`
until the case ends, so nothing settled before `i` is released while the case
is open, which is what the early freeze exists for below the case horizon.

## Problem 3: one missed review seal ends a case

A review stage (the recheck gate of an unappealed initial verdict, a party
review, a tiebreak) fixes its randomness at a future block and must be sealed
within `sealBlocks` of it. `_sealReview` ended the case as a protocol
`INCONCLUSIVE` the first time the seal window passed or the block hash was
unavailable, and returned the appeal deposit to the appellant. A cheating
seller that appeals a correct `FAIL` gains the case and its deposit from one
missed keeper call; nothing about the verdicts changed.

## Decision 3: reopen once per stage

The first time a review stage finds its randomness unavailable, `_sealReview`
sets `randomBlock = block.number + 1`, marks the stage in
`reviewReseals[nonce]` (one bit per `JudgmentStage`), emits
`ReviewResealed(nonce, stage, randomBlock)`, and returns without assigning; the
next seal uses the new block with the same `sealBlocks` window. Only a second
failure in the same stage ends the case as a protocol `INCONCLUSIVE`, as
before. `finalizeCase` past the seal window of a party review or tiebreak goes
through the same rule, and so does the recheck gate. Each stage has its own
reopen: a case whose party review reopened can still reopen its tiebreak.

`caseHorizon` of `profile-v1.md` section 3 budgets the follow-up seals as
`2 * 2 * (sealBlocks + 2)` instead of `2 * (sealBlocks + 2)`: two review seals
on the longest path, each of which may reopen once. `judgmentDelayBlocks` is
unchanged: its review terms count the one block to the review randomness and
no seal window, so a prompt keeper never reopens on that path. The new
horizons are 58,994 and 130,526 blocks (from 58,590 and 130,122). The keeper
margin `retentionBlocks - caseHorizon` would fall to 6 and 474 blocks, below
the 410 and 878 of the current profiles, so `deferBlocks = retentionBlocks =
claimWindowBlocks = failureWindowBlocks = inconclusiveWindowBlocks` rise to the
next multiple of 1,000 that restores it: 60,000 and 132,000 (margins 1,006 and
1,474).

## Erratum to ADR 0019, decision 3

The per-judged-case bound `u = u1^2 (1 + pi_v + b_a (1 - pi_v))` missed one
path: an initial `FAIL` appealed by the seller, overturned by the party
reviewer, and confirmed by the tiebreak it leads to. Its probability is `w1 (1
- w1) w1 <= w1^2`. The corrected bound, with `s_re = recheckPpm / PPM`, is

```text
u = w1^2 * (2 + b_a + (1 - b_a) * s_re)
```

which is `3 w1^2 = 0.00472827` at `b_a = 1` (`wrongFinalFailPpm = 4729`), not
`2 w1^2 = 0.003152`. `w1 = c (1 - h) + h alpha` is an upper bound on one
verifier's error only for `c >= alpha` (a non-honest verifier that does not
collude still errs at `alpha`), so the model uses `max(c, alpha)`; this
matters only for the `c = 0` row of the sensitivity table. With the new
horizons and hold periods, `S = 5,970` and `13,147`, and `failureLimit`
becomes 16 and 27 (union bounds `7.611e-07` and `2.381e-07`, exact tails
`5.449e-08` and `6.160e-10`); with the old hold periods it would be 16 and 26.
At `b_a = 0` the limits are 14 and 22.

## Consequences

- An honest seller wrongly failed loses one share and the claims on its
  frozen pool, but can sell again as soon as it tops the share up, instead of
  after `retentionBlocks`.
- A cheating seller that re-enters at once is frozen again, over everything
  it sold since, at its next confirmed failure; its failures keep counting in
  the same failure window, so a seller that re-enters in every claim window
  reaches the sanction threshold faster than one that waits (C1).
- A large bond is no longer a liability for an honest seller: its sanction
  threshold scales with its settlement volume.
- A single missed review seal costs one reopen and at most `sealBlocks + 2`
  blocks; a keeper outage longer than two seal windows in one stage still ends
  the case `INCONCLUSIVE`.
- Evaluation profiles: `failureLimit` 16 and 27; hold periods 60,000 and
  132,000; `caseHorizon` 58,994 and 130,526; both `parameterHash` values
  change, and the x402 vectors carrying the data API hash are updated.
- Contract surface: storage appends `claimReentries`, `failureWindowScale`
  and `reviewReseals`; the router gains `getClaimReentry`,
  `getFailureWindowScale` and `getReviewReseals` and the event
  `ReviewResealed`. `timeoutJudge` and `timeoutEvidence` are served by the
  sampling module instead of the judgment module (same selectors and
  behaviour), which keeps the judgment module below the size limit. Runtime
  sizes after the change: router 21,564; registry 23,290; settlement 13,122;
  sampling 22,470; delivery 24,050; publication 19,519; recovery 22,947;
  judgment 21,681; review 24,128; bond 19,989 (limit 24,576).

## Properties

- P1: unchanged.
- P2: preserved with re-entry. Every purchase settled since a fraud began is
  frozen at its confirmed failure (exposure bound above); buyers of the moved
  window claim once; a frozen entry is paid at most once; the forfeiture never
  takes an entry settled after a reinstatement. Strengthened for reviews: a
  missed seal no longer ends a case whose buyer appealed a `PASS`.
- P3: strengthened. The per-window sanction probability no longer grows with
  the bond; a wrongly failed seller re-enters after a top-up instead of after
  the claim window; the stated bound now counts every path to a wrongful
  confirmed failure (erratum).
- P4: strengthened. A seller cannot escape a correct `FAIL` on appeal through
  one missed review seal.

## Regression

`contracts/test/FairBindReentry.t.sol`:

- scale one: a window opens at scale one and sanctions at `failureLimit`
  (unchanged); scale three: nine failures, one share each, the ninth takes the
  remainder so the window charges three penalties, the window keeps scale
  three while the live scale factor falls (the old rule sanctioned at three);
- re-entry: after a top-up, reinstatement during the open window reopens the
  account; the new purchase is outside the window, not claimable, not
  forfeited, and released on schedule (the old rule refused reinstatement and
  settlement until the window closed);
- a second confirmed failure after re-entry moves `freezeBlock` to its block,
  extends the window, freezes the new purchase, which is claimed once and never
  released, refuses settlement, and makes `forfeitUnclaimed` wait for the
  extended window (the old early return left the purchase outside);
- under `freezeOnInitialFail`, an initial `FAIL` after re-entry holds the new
  purchase through its pending trigger without moving the window; overturned,
  the window and its claims are unchanged and the new purchase is back on
  schedule; confirmed, the window moves over it;
- review seals: a missing party-review hash reopens on the next block and keeps
  the deposit (the old rule ended the case and returned it); a second miss in
  the stage ends it; the tiebreak has its own reopen; an expired recheck
  candidate reopens the gate;
- exit: after an initial `FAIL`, under both freeze timings, an exiting seller
  is frozen, counted and deducted at the confirmed failure, and
  `finalizeSellerExit` and `finalizeBondExit` are refused until the pool closes
  (the old rule let the seller exit with the window open).

`contracts/test/FairBindBond.t.sol` and `FairBindM4.t.sol` are updated where
the old behaviour was asserted (the second confirmed failure keeps the window
boundary; a missing review hash ends the case at once).

The stateful suite models the window scale, the moved window and the late
totals, checks the frozen-pool view and the forfeiture against the frozen
window only, and adds an action that tops up, reinstates during the window,
settles, fails one of the new purchases and releases the others. The mutation
build `contracts/test/invariant/ReentryMutation.sol` keeps the old early
return of `_freeze`; `run.sh` requires its negative invariant (no principal
settled before a confirmed failure reaches the seller) to fail.
