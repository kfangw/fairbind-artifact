# ADR 0029: An anchored epoch waits for its value, and a waiting case stops the release clock

Status: Accepted 2026-10-14. Amends ADR 0024 (the randomness rule it left
unmet), ADR 0022 and ADR 0024 (the recent scale high and the recent cap and
sanction limit) and ADR 0028 (limit 1) in `lifecycle-v1.md` sections 1, 2, 8
and "ADR 0029 epoch and release-clock rules", `fairbind-v1.md` (section 21.2,
invariants 26, 27, 38, 39 and the ADR 0024 and ADR 0029 notes),
`contract-interface-v1.md` and `traceability.md`. Changes the behavior of
`seal`, `timeoutSeal`, `releasePurchase` and `finalizeBondExit` without
changing their signatures; appends two views, two events and two storage
mappings; changes no existing storage slot, purchase field or encoding.

The research decisions this record implements are decision 114 of the project
record: design 2 rule D2-16, no release before the epoch's value arrives, and
the checkpoint-shortage exit D2-16 (f) (paper rule (i)); and decision 145
(2026-10-14) with judgment 146: design 2 rule D2-21, a waiting case stops its
account's release clock, with the recent cap measured over the same unpaused
blocks, D2-21 (d) (paper rule (vii)).

## Problem

1. **Epoch value.** An anchored epoch whose `seal` did not happen by
   `sealDeadline` could be ended by anyone with `timeoutSeal`, and a `seal`
   that found no block hash ended the epoch too; both made every purchase of
   the epoch refundable through `claimEpochFailure` without a seller
   failure. The seller knows the sample of an epoch once its value exists.
   If it can keep that value off chain past the deadline, it voids exactly
   the epochs that drew a fraudulent sale and keeps the others: detection
   never comes. `traceability.md` recorded this as unmet in ADR 0024.
2. **Release clock.** ADR 0028 lets a sampled case wait for a verifier with
   room for as long as the verifiers stay full. Its own purchase stays held,
   but the confirmed failure it may lead to comes later, and every other
   entry of the account keeps its release block `settledBlock +
   deferBlocks`. A seller that keeps the verifiers full (with its own
   always-sampled purchases, for example) delays the failure of a detected
   fraudulent sale past the release of the sales it made after it. The hold
   covers such waits only up to the waiting margin `D_w` (ADR 0028, limit 1).
   The recent cap `V*` and the recent scale high also expire by wall blocks,
   so a failure that arrives after a long wait may deduct at a lower cap.

## Decision

1. **`seal` delivers the value late.** `seal` is valid after `randomBlock`
   while the chain serves `blockhash(randomBlock)` (256 blocks), also after
   `sealDeadline`. A zero hash reverts `InvalidRandomnessWindow` and changes
   nothing: the epoch stays `ANCHORED`, none of its entries is released
   (`releasePurchase` already requires `SEALED`), none is refundable, and
   nothing is counted. A late value takes the normal path: sampling,
   `openSample` and release follow as before. `sealDeadline` keeps its role
   as the keeper's obligation block and in `sampleOpenUntil`.
2. **`timeoutSeal` is the checkpoint-shortage exit.** It keeps its
   signature. For an `ANCHORED` epoch, after the anchor deadline (when no
   later checkpoint can still be written at or before it), it reads the
   epoch's checkpoint, the latest written at or before the anchor deadline
   (the one `seal` uses). If there is none or it holds fewer than
   `minVerifiers` verifiers, the epoch becomes `EPOCH_FAILED` with reason
   `VERIFIER_SET_UNAVAILABLE`, before or after the value exists; `seal`
   could never succeed on it. `claimEpochFailure` refunds its purchases
   without a seller failure, freeze or deduction (the path for an anchored
   epoch, `_sellerFailure` with `anchoredBlock != 0`, is unchanged).
   Otherwise `timeoutSeal` reverts `InvalidTransition`, or
   `DeadlineNotReached` through the anchor deadline. The checkpoint is fixed
   before the value exists, so the seller cannot route an epoch to this exit
   after seeing its sample.
3. **Release clock per bond account.** `releaseClocks[bondId]` holds
   `waitingCases` and the number of pauses; `pauseLog[bondId][i]` holds one
   pause `[start, end)` (`end` zero while open) and `pausedBefore`, the
   paused blocks of the account before `start`. A case that enters
   `WAITING_ASSIGNMENT` from another state (`_waitForCheckpoint`) increments
   `waitingCases`; the first one opens a pause in that block
   (`ReleaseClockPaused`). A case that leaves the wait, by a redraw that
   assigns (`_redraw`) or by ending (`_sellerFailure`, the only path that
   ends a waiting case), decrements it; the last one closes the pause in
   that block (`ReleaseClockResumed`). A redraw that finds nothing leaves
   the case waiting and does not count it again; a redraw whose search is
   exhausted again leaves and re-enters in one block, which reopens the same
   pause. A pause that begins and ends in one block is dropped, so pauses
   never touch or overlap and overlapping waits count once.
4. **Unpaused blocks.** `pausedSince(bondId, s)` is the number of blocks `u`
   with `s <= u < block.number` that lie in a pause: the paused total minus
   the paused blocks before `s`, found by binary search over the pauses
   (two slot reads when no pause touches `[s, now)`). A block counts as
   paused from the block a wait begins up to, not including, the block it
   ends: the case's later path then runs exactly as the path of a case
   assigned at the block it began to wait.
5. **What counts unpaused blocks.** `releasePurchase` requires
   `block.number - pausedSince(bondId, settledBlock) >= releaseBlock` (the
   entry's effective age is at least `deferBlocks`) in addition to every
   other condition. `V*` (`_recentCap`), the recent sanction limit
   (`_recentSanctionLimit`) and the recent scale high (`_rescale`,
   `_confirmFailure`) stay in force while at most `retentionBlocks` unpaused
   blocks have passed since the drop that recorded them; the stored
   `peakUntil`, `peakLimitUntil` and `dropBlock` keep their wall-block
   values and the check adds the paused blocks since the drop. The balance a
   settlement, registration or re-entry requires is the unit bond at that
   `V*`, so it follows. `finalizeBondExit` requires `retentionBlocks`
   unpaused blocks since the exit request. Nothing else changes: the claim
   window, `retainUntil`, the omission-proof deadline, the failure and
   inconclusive windows, and the seller and verifier exit locks keep
   counting wall blocks (rule D2-8 (d)).
6. **Frozen accounts.** A waiting case keeps stopping the clock of its
   account while the account is frozen, and after a reinstatement it delays
   the release of entries settled since (rule D2-21 (i) 2 leaves this open;
   this is the reading that releases nothing earlier).
7. **Test hook.** `_pauseHolds()` is true in production; the mutation build
   `PauseIgnored.sol` overrides it in the recovery module, where release then
   counts every block, as before this record.

## Consequences

- No per-entry storage changes: `settle` writes the same slots as before
  and reads nothing new. An account that never waited pays one extra cold
  slot read in `releasePurchase`; an account with pauses pays a second one,
  and the binary search only when a pause began after the entry's
  settlement but is not the latest one. The first case of an account to wait
  writes the account slot and one pause slot; further waiting cases write
  the account slot only; the last case to leave writes the pause's end.
- Measured gas per transaction (`forge test --isolate`, intrinsic cost
  included, `ReleaseClockGas.t.sol`: fourteen verifiers, eight purchases in
  one epoch, the same file run on 4681e40 and on this record):

  | Call | Before | After | Change |
  | --- | ---: | ---: | ---: |
  | `settle`, first of the account | 464,406 | 465,117 | +711 |
  | `settle`, second | 410,942 | 411,653 | +711 |
  | `anchor`, 8 entries | 149,827 | 150,147 | +320 |
  | `seal` | 213,344 | 213,239 | -105 |
  | `openSample`, first case of the account to wait | 417,100 | 464,704 | +47,604 |
  | `openSample`, second waiting case | 373,159 | 378,943 | +5,784 |
  | `assignVerifier` redraw, another case still waits | 350,091 | 357,689 | +7,598 |
  | `assignVerifier` redraw, last waiting case | 367,677 | 382,482 | +14,805 |
  | `releasePurchase`, one pause since settlement | 123,198 | 129,233 | +6,035 |
  | `releasePurchase`, account never paused | 123,104 | 125,837 | +2,733 |

  `settle` and `anchor` take the same path as before; their difference comes from
  the recompiled modules and router. The paper's numbers stay those of the
  earlier build.
- An honest seller's releases stop while any of its sampled cases waits,
  whoever filled the verifiers. Its recent cap, and with it the unit bond it
  must hold, and its bond exit wait the same blocks. It loses nothing.
- An epoch whose value nobody delivers within 256 blocks of `randomBlock`
  holds its purchases for good (limit 1).
- `EpochFailureReason.SEAL_TIMEOUT` and `RANDOMNESS_UNAVAILABLE` keep their
  values and are no longer emitted.
- Tests: `EpochValueHold.t.sol` (rule D2-16), `ReleaseClock.t.sol` (rule
  D2-21), `ReleaseClockGas.t.sol` (gas only). `FairBindM2.t.sol` and
  `Design2Rules.t.sol` replace the three tests that pinned the old seal
  timeout. The stateful suite checks the clock of every account against an
  independent model after every action and before every block move
  (`invariant_releaseClockStopsWhileACaseWaits`), checks every release
  against the model's unpaused count, models the recent scale high with the
  paused blocks, and drives `seal` and `timeoutSeal` under the new rule
  (late seal, seal without its value, timeoutSeal refused on a full
  checkpoint). `run.sh` step 6 requires the `PauseIgnored.sol` build to
  fail the release invariant in the waiting variant. The keeper keeps
  sealing after `sealDeadline` while the hash is served and calls
  `timeoutSeal` after that (`services/keeper`).

## Limits

1. **A lost value holds the epoch for good.** The value is
   `blockhash(randomBlock)`, which the chain serves for 256 blocks. If no
   keeper calls `seal` by then, `seal` reverts forever and only a checkpoint
   shortage ends the epoch: its purchases stay `DEFERRED` with no release
   and no refund outside a freeze of the account (rule D2-16 (c), open
   question U9). A replacement randomness source must let anyone deliver the
   same value at any later time.
2. **The keeper's shortage call is late.** The keeper reads no checkpoint;
   it calls `timeoutSeal` once the hash is no longer served, about 256 blocks
   after `randomBlock`, and that call reverts on a full checkpoint. A short
   checkpoint is refunded later than the rule allows (from the anchor
   deadline on).
3. **Deduction at the failed sale's cap.** Rule D2-21 (c) deducts
   `b(max(V*, V(s)))` with `V(s)` the cap at the failed sale's settlement.
   The contract deducts `b(V*)` with `V*` over unpaused blocks (D2-21 (d)).
   Under J3 counted in unpaused blocks the failed sale's effective age at the
   failure is below `retentionBlocks`, and any later lowering of the cap is
   younger still, so `V* >= V(s)`; the maximum is not stored separately.
4. **Wall-block windows stay.** The failure and inconclusive windows, and
   with them the window scale and sanction limit of the k protection, count
   wall blocks; a wait longer than the waiting margin lengthens the span of
   settlements one window can fail (rule D2-7 (a), D2-21 (i) 3).
5. **Full freeze.** A confirmed failure still freezes every unreleased entry
   of the account. The narrow freeze of the rules (entries settled at or
   after the sale the failure concerns) is not implemented.
6. **Pause log growth.** Each pause adds one slot to its account for good.
   The binary search reads `log2(pauses)` slots in the worst case.
7. **ADR 0028, limits 2, 5, 7 and 8 stand.** In particular a waiting purchase
   of a frozen account whose wait outlasts the claim window is still
   forfeited if a later redraw ends its case without a `FAIL`.
