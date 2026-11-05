# ADR 0028: An exhausted first assignment waits for the next checkpoint

Status: Accepted 2026-10-13. Amends ADR 0014 (keeper serve fallback) and
ADR 0025 (checkpoint-time eligibility) in `lifecycle-v1.md` section 4,
`sortition-v1.md` sections 4 and 5, `fairbind-v1.md` (case transitions and
invariant 27), `contract-interface-v1.md` and `traceability.md`. Appends one
`CaseState` value, one storage mapping, one event and one router read; changes
no existing ABI entry, storage slot or encoding.

The research decisions this record implements are decision 137 of the project
record (2026-10-13, variant 2): design 2 rule D2-20, a sampled case whose
first assignment is exhausted waits instead of ending; and decision 139
(2026-10-13): the redraw draws from a value fixed only after the newer
checkpoint is written (rule D2-20 (b), interface J4 (c)), not from the epoch
value.

## Problem

The assignment search draws `minVerifiers` tickets from the checkpoint of the
case's epoch and skips a verifier that already took part in the case or whose
checkpoint liability room is below the case liability (ADR 0025). When every
ticket is skipped, `_assignVerifier` ends in `_protocolInconclusive`. For the
initial stage of a sampled case that is the keeper serve request of ADR 0014:
the seller publishes the sampled response on chain and the case ends as a
protocol `INCONCLUSIVE`, after which the purchase is releasable.

The search fails for want of an eligible verifier, not because the seller did
anything. A seller that keeps the checkpoint verifiers full, or that simply
sells while they are full, turns every sampled purchase of such an epoch into
a releasable `INCONCLUSIVE`: the sample is drawn, but it is never judged, and
the detection probability falls below its floor without any trace.

A redraw cannot reuse the epoch value. The epoch value is public once the
epoch is sealed, and anyone may write the next checkpoint, so whoever writes
it could compute, for each candidate table, which verifier a redraw from the
epoch value (with a retry counter mixed in) would draw, and choose the table.

## Decision

1. `CaseState` gains `WAITING_ASSIGNMENT` (value 14, appended). When the
   search of the initial stage of a sampled case (`trigger = SAMPLE`,
   `stage = INITIAL`, any attempt) is exhausted, the case enters
   `WAITING_ASSIGNMENT` instead of `_protocolInconclusive`. The purchase stays
   `HELD`. `getAssignmentWait(nonce)` records the checkpoint version of the
   search and its block (`searchBlock`). The case has no deadline
   (`judgeDue = 0`); `attempt` does not move; nothing is penalized or
   counted. The contract emits `AssignmentWaiting(nonce, attempt,
   checkpointVersion)`.
2. Anyone may call `assignVerifier(nonce)` on a waiting case. It redraws on
   the **first checkpoint written in a block after `searchBlock`**, version
   `v = _checkpointAt(profile, searchBlock) + 1`; without such a version it
   reverts `InvalidTransition`. A checkpoint call that reproduces the latest
   table creates no version (ADR 0025), so a second call on the same table
   reverts too.
3. **Redraw value.** The value is `blockhash(r)` with
   `r = checkpointBlock(v) + 1 + beaconDelayBlocks`, the epoch rule of
   `sortition-v1.md` section 3 applied to the redraw's checkpoint. Before
   block `r + 1` the call reverts `DeadlineNotReached`. The tickets are those
   of `sortition-v1.md` section 4 with this value in place of the epoch value:
   `keccak256(abi.encode(ASSIGN_DOMAIN, value, nonce, stage, attempt, round))`.
   The preimage is unchanged; `value` already differs from redraw to redraw.
4. **Why the checkpoint writer cannot steer it.** The writer of version `v`
   fixes the table and its rooms in block `checkpointBlock(v)`. The value is
   the hash of a block at least `beaconDelayBlocks + 1` blocks later, so it
   does not exist when the table is fixed; under J4 (a) for block hashes, the
   same assumption the epoch value rests on, nobody who writes or shapes the
   table knows it. After the value exists, nothing anyone writes changes the
   draw: the redraw always uses version `v`, the first one after the search,
   whatever later versions exist, and the caller supplies no input. Writing
   more checkpoints therefore gives no second draw. The only remaining choice
   is not to call: if nobody redraws while the chain still serves
   `blockhash(r)` (256 blocks), the next call counts version `v` as searched
   (point 5) and the case waits for the next checkpoint; that needs every
   keeper to stay silent for 256 blocks (A2).
5. A redraw whose value is no longer served, or whose checkpoint holds fewer
   than `minVerifiers` verifiers, records `v` as searched at this block
   (`searchBlock = block.number`) and leaves the case waiting. A redraw whose
   search is exhausted again does the same. Otherwise the redraw assigns a
   verifier: the case becomes `JUDGING` and its judgment deadline starts in
   that block (`judgeDue = block.number + judgeBlocks`).
6. Eligibility in a redraw is the room in checkpoint `v` (rule D2-12 (a),
   with the exception of rule D2-20 (b)). Once a case has redrawn, every later
   assignment of the case reads the checkpoint of its last redraw
   (`getAssignmentWait(nonce).checkpointVersion`) instead of the epoch's, and
   every later initial attempt draws from the redraw value
   (`getAssignmentWait(nonce).randomness`) instead of the epoch value. The
   review stages keep their own review values.
7. The number of redraws has no bound and no constant limits the wait.
   `getAssignmentWait(nonce)` returns `(checkpointVersion, searchBlock,
   redraws, randomness)`.
8. Exhaustion everywhere else is unchanged: the review stages (`PARTY`,
   `AUTO`, `TIEBREAK`; a seller-appealed review still upholds the initial
   `FAIL`, ADR 0024), the initial stage of a buyer dispute
   (`WRONG_DELIVERY`), which still ends `INCONCLUSIVE`, and the final initial
   attempt that times out, which still takes the keeper serve path of
   ADR 0014.

## Consequences

- `releasePurchase` refuses a waiting purchase twice: it is `HELD`, which no
  release path accepts, and its case is not ended. A freeze of the bond
  account treats it like every other `HELD` entry: its value stays
  encumbered, so it is neither in the frozen pool nor forfeited, and only its
  own case settles it. If a later redraw ends the case with a `FAIL`, the
  purchase is refundable; if it ends without one inside an open claim window,
  the purchase becomes `RELEASABLE` and is claimable from the pool like any
  other entry of the frozen window.
- The seller's receipt deadline of the sample case (ADR 0024) still runs from
  the case opening: it is the seller's obligation, not a judgment deadline,
  and a missing receipt ends a waiting case `UNSERVED`. The redraw block lies
  at least `beaconDelayBlocks + 1` blocks after a checkpoint, later than
  `serveBlocks` after the opening, so in practice the receipt must be posted
  before any redraw.
- The ordinary assignment path reads one more storage slot (the wait record).
  An exhaustion writes the first word of the wait record (version, block,
  count); a redraw writes both words and runs the usual search. A redraw that
  assigns costs about 260,000 gas in its call frame in
  `test_redrawAfterANewerCheckpointAssignsAndStartsTheJudgeDeadline` (fourteen
  verifiers); `anchor` is unchanged.
- `AssignmentWait` is appended after the last storage variable; every module
  shares the layout (`scripts/check_modules.py`).
- Tests: `AssignmentWait.t.sol` pins each point above, including the redraw's
  dependence on the redraw block hash alone. The stateful suite gains a
  waiting variant (`WaitingAssignmentInvariantTest`, verifiers that open
  without room for one case and a handler action that writes newer
  checkpoints) under every configuration of `run.sh`, a coverage test
  (`WaitingCoverageTest`), and a mutation build in which a waiting case does
  not hold its purchase (`WaitRelease.sol`), which must fail the release
  invariant (`run.sh` step 5). The test build hook is `_waitHolds()`. The
  two new handler actions are excluded from the fuzzed selectors outside the
  waiting variant, so the other configurations and mutation runs fuzz the
  same actions as before.

## Limits

1. **Waiting delay is an assumption (U15, variant c).** The rules carry the
   waiting delay as assumption A4: every waiting case is assigned within
   `D_w` blocks, with `kappa_Sigma + D_w <= kappa_bar - 1` (J3). The contract
   enforces no bound and does not stop the release clock of the account while
   one of its cases waits. While a case waits its own purchase stays held, but
   the confirmed failure it may lead to comes later, and other purchases of
   the account settled after it may be released before that failure. In the
   reference case the keeper margin is spent on `kappa_Sigma` and leaves no
   room for `D_w`.
2. **Liveness.** A profile whose verifiers stay full keeps its sampled
   purchases held. Each redraw adds at least `beaconDelayBlocks + 1` blocks
   after a newer checkpoint. A new version exists only when a verifier's
   membership, weight or room changes; with an unchanged table the case waits
   even though a new value might find a verifier. The waiting cases are
   visible on chain (`AssignmentWaiting`).
3. **Retention.** The case horizon no longer bounds a sampled case. The
   seller's obligation to serve the response and the retention of the case
   data last until the case ends. A verifier assigned on a redraw is held by
   its locked liability, not by the epoch's exit lock; a verifier of the
   redraw's checkpoint that exits before the redraw may still be drawn and is
   then replaced by the judgment timeout (ADR 0025, limit 2).
4. **Block hashes.** The redraw value is a block hash, like the epoch value
   and the review values; J4 does not hold for block hashes on a chain whose
   block producer can withhold blocks. Whoever produces block `r` could bias
   the redraw like the epoch value. A replacement randomness source (rule
   D2-16) must serve the redraw value too, bound to the case, the redraw's
   checkpoint version and nothing a caller chooses.
5. **Skipping a value.** A value not used within 256 blocks of `r` is lost and
   the case waits for a later checkpoint (decision point 4). The keeper's
   redraw duty (A2: the first block at which the newer checkpoint and its
   value are on chain) must therefore be met within 256 blocks. The keeper
   does not yet call `assignVerifier` on waiting cases.
6. **Standing full verifiers.** Waiting does not close the decoy attack of
   ADR 0025, limit 1: a seller that keeps honest verifiers full and leaves
   colluding verifiers with room is never exhausted, so its cases never wait.
7. **A redraw that finds nothing skips the checkpoints written in
   between.** The next redraw takes the first checkpoint written after
   `searchBlock` (`_checkpointAt(profile, searchBlock) + 1`,
   `FairBindSampling.sol:201`), and an exhausted redraw, a redraw whose value
   is no longer served, or a checkpoint with fewer than `minVerifiers`
   verifiers sets `searchBlock = block.number` (`_waitForCheckpoint`,
   `FairBindCore.sol:1863`). Every checkpoint written between the redraw's
   checkpoint and that block is therefore never searched. If the only table
   with room was such a skipped version, the case waits until yet another
   checkpoint is written, and with an unchanged table it waits for good. The
   skipped table cannot be steered by the caller, who still supplies no
   input, but the caller's timing decides which versions are skipped, so
   point 4 of the decision is too strong: not calling is not the only choice
   left to the caller. This is a liveness limit, not a randomness limit. The
   code is not changed in this record.
8. **A wait that outlasts the claim window of a frozen account forfeits the
   principal.** A waiting purchase is `HELD`, and `claimRefund` accepts only
   `DEFERRED` and `RELEASABLE` entries (`FairBindBond.sol:288`). When the
   account is frozen and the wait lasts past `claimUntilBlock`,
   `forfeitUnclaimed` closes the window and sets `forfeitedThrough`. If a
   later redraw then ends the case without a `FAIL`, the purchase would be
   `RELEASABLE`, but `_setFinancialState` turns it into `FORFEITED` because
   its `settledBlock` is not above `forfeitedThrough`
   (`FairBindCore.sol:1324`). The principal stays locked in the contract; the
   buyer cannot claim it and the seller does not receive it, even though the
   sample was judged correct. Before this record a judgment deadline ended
   the case inside the window. The first Consequences bullet describes only
   the case that ends inside an open window. The code is not changed in this
   record; closing this needs a research decision (let a waiting purchase be
   claimed from the frozen pool, or block `forfeitUnclaimed` while an entry
   waits). `AssignmentWait.t.sol` has no test of a pass after the window.
