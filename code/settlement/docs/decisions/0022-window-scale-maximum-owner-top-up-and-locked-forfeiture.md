# ADR 0022: Open a failure window at the highest recent scale; only the owner tops up; lock forfeitures and deductions in the contract

Status: Accepted 2026-09-29. Amends ADR 0021 (decision 1), ADR 0018
(decision 1, the destination of a deduction) and ADR 0012 (item 6, the
destination of a forfeited remainder) in `fairbind-v1.md` sections 5.4, 18,
21.3 and 22, `lifecycle-v1.md` sections 2, 9 and 10, `profile-v1.md` sections
2 and 4, `contract-interface-v1.md` sections 1, 6, 11 and 12 and
`governance-v1.md` section 2. Changes no encoding of a signed or hashed
message and no profile field: `forfeitVerifierPpm` stays in the profile
encoding with no effect, so no `parameterHash` moves. Appends two storage
entries (`recentScaleHigh`, `lockedForfeit`) and adds two router views
(`getRecentScaleHigh`, `getLockedForfeit`); no ABI entry of the recorded
router is removed or changed.

## Problem 1: when the window scale is read, and which scale

ADR 0021 records `failureWindowScale` when a fixed failure window opens and
sanctions at `failureWindowScale * failureLimit`. The specification put "deduct
and recompute the scale" and "record the scale when the window opens" in one
paragraph without an order. The contract reads the scale before the opening
failure's deduction (a regression test now pins this); read after it, an
account holding exactly `2 * sellerPenalty` would open its window at scale one
the moment its first share is deducted.

A second gap remains with the order fixed. The threshold is sized for the
settlements that can be confirmed failed in the window: those in `[w -
caseHorizon, w + W]` for a window opening at `w`. A deduction lowers the scale
factor at once, so an account that settled at scale `n` until block `d` and
opens a new window at `w` with `w - d <= caseHorizon` opens at the lower
scale, while up to `n` times the unit volume of its settlements can still be
confirmed failed in that window. At the data API evaluation values an account
at scale two whose window reopens at scale one faces `P[Bin(2S, q) >= k]`
instead of `P[Bin(S, q) >= k]`, about 270 times the target of `10^-6`. A
top-up during an open window raises the settlement volume the same way while
the threshold stays where it opened.

## Problem 2: anyone can top up any account

`topUpBond` had no caller check. A third party could raise an account's scale
factor, and with it the rate the account admits, without the owner's consent.
Under decision 1 below a top-up during an open window also raises its
threshold, so the call must be the owner's.

## Problem 3: the destination of a forfeiture creates an interest

ADR 0012 splits a forfeited remainder between an immutable verifier reward
pool and the treasury (`forfeitVerifierPpm`), and ADR 0018 sends every
per-failure deduction to the treasury. Neither destination is used by any
bound: the exposure bound, the deterrence argument and the honest-seller bound
need only that the money does not return to the seller. The destinations do
create an interest in failures. The reward pool and the treasury are fixed
addresses chosen by the deployer, so the collective interest of the verifiers
is the interest of one party; a deployment in which the operator is the only
verifier (`h = 1`) is the one with the largest conflict; and an
`INCONCLUSIVE` above the threshold opens a claim window, and with it a
forfeiture, without any penalty. The earlier decision to keep the split and
record the conflict as a limitation is reversed.

## Decision 1: the window scale is the highest recent scale

When a fixed failure window opens (the branch of `_confirmFailure` that resets
`failureCount`), its scale is

```text
n_bar = max(1, scaleFactor before this failure's deduction,
            recentScaleHigh.scale if block.number <= recentScaleHigh.dropBlock + retentionBlocks)
```

and a `topUpBond` that raises the scale factor while the window is open
(`failureCount != 0` and `block.number <= failureWindowStart +
failureWindowBlocks`) raises `failureWindowScale` to the new scale factor. The
window sanctions at `n_bar * failureLimit` and its deductions sum to `n_bar *
sellerPenalty`, each bounded by the balance, with `n_bar` the value at the
failure being counted.

`recentScaleHigh[bondId]` is two fields, `scale` and `dropBlock`, updated in
`_rescale` whenever the scale factor falls from `old`: if `old` exceeds the
recorded scale or the record is older than `retentionBlocks`, `scale = old`;
in every case `dropBlock = block.number`. `retentionBlocks` is the case
horizon plus the keeper margin (`profile-v1.md` section 3). The pair is an
upper bound on every scale the account held within `retentionBlocks` before
any later block: a level `m` held until a drop at `d` is recorded at `d` or
covered by a higher live record, and every later drop only raises the record
or restamps it, so the record stays at least `m` until `d + retentionBlocks`.
It is exact when drops are more than `retentionBlocks` apart or monotone; a
sequence of drops each within `retentionBlocks` of the previous keeps the
highest level alive, which can only raise a threshold. The scale factor falls
only through a deduction (`_rescale` after `_confirmFailure`); `finalizeBondExit`
zeroes an exited account without a record, and such an account admits no
settlement.

Why the maximum does not weaken the other bounds. The exposure bound (ADR
0012, ADR 0021) does not use the threshold. The deterrence bound uses only
that every confirmed failure deducts `sellerPenalty / failureLimit` and that a
seller re-enters only at `balance >= sellerPenalty`; both are unchanged. A
higher threshold delays only the terminal sanction. To raise the threshold to
`n_bar` the account must at some point have held `n_bar * sellerPenalty`,
which only deductions reduce. A long-lived record can keep a threshold above
what the current balance covers; this only delays the terminal sanction, and
every failure still deducts `sellerPenalty / failureLimit`. A seller that
wants to escape the sanction can already open a new account. A third party can no longer move the threshold (decision 2).

## Decision 2: only the owner tops up

`topUpBond` reverts with `Unauthorized` unless `msg.sender` is the account
owner. Nothing else changes: the account must be `ACTIVE`, and the scale factor
is recomputed.

## Decision 3: forfeitures and deductions stay locked in the contract

`forfeitUnclaimed`, and the forfeiture of an entry whose own case ends without
a refund right after its window closed, add the amount to the bond account's
`forfeitedTotal` and to the contract-wide `lockedForfeit`, and transfer
nothing. Every per-failure deduction subtracts its share from the bond
balance, adds it to `lockedForfeit`, and transfers nothing. No function
withdraws `lockedForfeit`. The tokens are not burnt by a transfer: the
deployment token (USDC) reverts on a transfer to the zero address, and a
dead-address transfer would move the same tokens out of reach with an extra
external call.

`UnclaimedForfeited` keeps its signature and reports `toVerifierPool = 0` and
`toReserve = 0`; `Slashed` for a seller deduction names the contract itself as
recipient. `forfeitVerifierPpm` stays in the profile and in its encoding, is
still range-checked, and has no effect; removing it would change the
`ServiceProfileInput` ABI of `createServiceProfile` and both evaluation
`parameterHash` values for no behavioural gain. The constructor keeps the
`rewardPool` argument and the router still checks it against every module,
since removing it would change every deployment script and the recorded
constructor ABI; the address receives nothing. The treasury keeps receiving
verifier late and wrong-verdict penalties; appeal deposits go to the appellant
or the other party of the case, never to the treasury.

The conservation statement of the contract becomes: the token balance of the
contract is at least the sum of bond balances, deferred balances, verifier
bonds and `lockedForfeit`.

## Consequences

- A window opened within `retentionBlocks` of a deduction keeps the threshold
  of the scale the account left; an honest account at scale two that is
  deducted to scale one is no longer sanctioned at `failureLimit` in the next
  window. The honest-seller bound of `profile-v1.md` section 4 holds for
  every window without an operating condition on top-ups.
- The fixed top-up policy of an honest seller (top up to exactly `n *
  sellerPenalty` after each deduction, never otherwise) keeps the threshold
  at the scale the window opened with.
- Nobody but the owner can change an account's scale.
- No party receives money from a failure it can influence. The verifier reward
  pool of version 1 receives nothing.
- Storage appends `recentScaleHigh` and `lockedForfeit`; the router gains
  `getRecentScaleHigh(uint32)` and `getLockedForfeit()`. Runtime sizes after the
  change: router 21,774; registry 23,290; settlement 13,122; sampling
  22,580; delivery 23,767; publication 19,217; recovery 23,265; judgment
  21,677; review 24,139; bond 20,144 (limit 24,576). The maximum-scale rule
  fits every module, so no operating condition on top-ups is needed.

## Properties

- P1: unchanged.
- P2: unchanged. The exposure bound and the frozen-pool claims do not depend on
  the threshold or on the destination of a forfeiture.
- P3: strengthened. The per-window sanction bound now holds for a window that
  opens after a recent deduction or that receives a top-up; a third party can
  no longer change an account's scale.
- P4: unchanged. Every confirmed failure still deducts its share, and the
  seller still receives nothing of a forfeiture.

## Regression

`contracts/test/FairBindReentry.t.sol`:

- the window scale is recorded before the opening failure's deduction (scale
  two recorded, live scale one after the deduction);
- a drop from scale two followed by a new window within `retentionBlocks` opens
  at scale two, and three failures in that window do not sanction (the old rule
  opened at scale one and sanctioned at the third);
- a drop older than `retentionBlocks` opens at the live scale and sanctions at
  `failureLimit`;
- a top-up from scale one to two during an open window raises the threshold to
  `2 * failureLimit`; the sixth failure sanctions and the window locks two
  penalties (the old rule sanctioned at the third);
- a non-owner `topUpBond` reverts with `Unauthorized` and changes nothing;
- positive control of the worst judgment path used by the I6 grid: with a
  hold period below the case horizon, the worst path (assignment timeouts,
  verdict at the judge deadline, evidence requested at the appeal deadline and
  disclosed at its deadline, appeal at the renewed deadline, both review seals
  reopened once, tiebreak) delays the initial `FAIL` past the release block of
  a bad sale settled beside the detected one, which reaches the seller, while
  the prompt path holds it; the whole path ends within `caseHorizon`.

`contracts/test/FairBindBond.t.sol`, `FairBindFailureCosts.t.sol`, `FairBindM3.t.sol`,
`FairBindReviewPaths.t.sol`, `repro/ReproC_DeferralPolicyA.t.sol` and
`invariant/FreezeConservation.t.sol` assert that the forfeiture and the
deductions stay in the contract and reach neither the reward pool nor the
treasury (the old rule split the remainder one to one and sent every share to
the treasury). The stateful suite models the recent scale high, the top-up
raise and the locked total, requires the reward pool to receive nothing and the
treasury only verifier penalties, and adds `lockedForfeit` to the custody
check. The integration test of the non-delivery path checks the locked total
through `getLockedForfeit`.
