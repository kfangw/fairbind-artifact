# FairBind Lifecycle and Fund Rules Version 1

Status: Release candidate for implementation

This document fixes the block formulas, state transitions, and fund priority for
FairBind version 1. A deadline is inclusive unless this document states
otherwise. A call is timely when `block.number <= deadline`. Its timeout becomes
eligible when `block.number > deadline`.

## 1. Profile epoch schedule

Each service profile stores `epochOrigin` and `epochBlocks`. Profile activation
requires `block.number >= epochOrigin`. For a settlement at block `b`:

```text
epoch = floor((b - epochOrigin) / epochBlocks)
epochStart(e) = epochOrigin + e * epochBlocks
epochEnd(e) = epochStart(e + 1) - 1
```

The contract rejects an epoch index that does not fit `uint24`.

Receipts for settlement epoch `e` use these fixed blocks:

```text
anchorBase(e)       = epochEnd(e + 1)
anchorDeadline(e)   = anchorBase(e) + anchorBlocks
randomBlock(e)      = anchorDeadline(e) + 1 + beaconDelayBlocks
sealDeadline(e)     = randomBlock(e) + sealBlocks
sampleOpenUntil(e)  = sealDeadline(e) + openBlocks
```

An epoch with zero recorded settlements has no anchor, randomness, or failure
obligation. Its zero-root view is terminal. For a nonempty epoch, `anchor` is
valid from `anchorBase` through `anchorDeadline`. `randomBlock` does not depend
on the anchor transaction, and the anchor deadline always precedes it by
`beaconDelayBlocks + 1` blocks, so the receipt set is fixed before the beacon
block exists. `seal` is valid after `randomBlock` while the EVM still returns
`blockhash(randomBlock)`, that is through `randomBlock + 256`, also after
`sealDeadline` (ADR 0029). `sealDeadline` is the keeper's obligation block for
the value and fixes `sampleOpenUntil`. `sealBlocks` MUST be at most 255 so the
EVM can still return the fixed block hash at the deadline.

`beaconDelayBlocks` is the delay `Delta` of the sampling beacon expressed in
settlement-chain blocks. A deployment that can read the L1 origin of a block
uses `beaconL1Block(e) = l1Origin(anchorDeadline(e)) + Delta` and admits `seal`
only while `l1Origin(block.number)` lies in `[beaconL1Block(e),
beaconL1Block(e) + beaconSlackL1Blocks]`, storing that block's RANDAO value.
The version 1 contract targets a chain without that interface: it realizes the
delay with `blockhash(randomBlock)` and requires `beaconSlackL1Blocks == 0`.

At sealing, the contract stores the latest purchase-profile verifier checkpoint
whose checkpoint block is no later than `anchorDeadline`. A checkpoint made
after that deadline cannot affect the epoch.

A missing or zero `blockhash(randomBlock)` is not an epoch failure: `seal`
reverts and the epoch stays `ANCHORED`, its purchases unreleased, until the
value is delivered (ADR 0029). The contract never accepts caller-provided
randomness.

## 2. Purchase deadlines

Settlement at block `b` fixes:

```text
responseDue  = b + responseBlocks
claimUntil   = responseDue + claimBlocks
releaseBlock = b + deferBlocks
retainUntil  = b + retentionBlocks
```

The seller may return the normal response after `responseDue`, but an honest
buyer may already have opened `NON_DELIVERY`. A buyer may open `NON_DELIVERY`
only when `block.number > responseDue` and through `claimUntil`.
`WRONG_DELIVERY` may open from settlement through `claimUntil` when the buyer
submits a valid receipt.

No-case release requires all of the following:

- the purchase has no open case or refund right;
- `block.number > claimUntil`;
- `block.number > sampleOpenUntil(epoch)`;
- `block.number >= releaseBlock`;
- `block.number - pausedSince(bond account, b) >= releaseBlock`, where
  `pausedSince` counts the blocks from `b` up to the current block in which at
  least one sampled case of the bond account was in `WAITING_ASSIGNMENT`
  (ADR 0029);
- `block.number >= retainUntil`.

Profile validation sets `deferBlocks >= retentionBlocks` and requires the two
values to cover the worst-case opening and case duration stated in
`profile-v1.md`. An open case holds its purchase amount even after these blocks.

## 3. Financial state

Each purchase has one financial state:

| State | Meaning |
| --- | --- |
| `NONE` | No successful settlement exists. |
| `DEFERRED` | The contract holds the complete purchase amount. |
| `HELD` | An open case prevents release of the complete amount. |
| `FROZEN_CLAIMABLE` | The entry is in the frozen window of a bond account whose claim window is open; its buyer may claim with a receipt. Reported by `purchaseState`, never stored. |
| `REFUNDABLE` | A final seller failure gives the buyer a withdrawal right. |
| `REFUNDED` | The buyer received the complete purchase amount. |
| `RELEASABLE` | All release conditions hold. |
| `RELEASED` | The seller received the complete purchase amount. |
| `FORFEITED` | The amount was locked in the contract (`lockedForfeit`, ADR 0022) after the claim window. |

The contract changes `DEFERRED` to `HELD` atomically when it opens a case. It
changes `HELD` to `REFUNDABLE` or `RELEASABLE` only after the case has a terminal
outcome. `REFUNDED`, `RELEASED`, and `FORFEITED` are terminal and mutually
exclusive.

Independently of the financial state, an entry is frozen while its bond
account is `FROZEN` or `CLAIM_OPEN` and the entry settled no later than the
freeze block. A frozen entry keeps its financial state but cannot be released.
An entry is also held from release, whatever its settlement block and the
freeze state, while its bond account has a pending initial `FAIL` (ADR 0021).
A confirmed failure while the account is `CLAIM_OPEN` moves the freeze block
to its own block, so that every unreleased entry up to it, including the
entries settled after a reinstatement during the window, is frozen and
claimable; an initial `FAIL` in that state does not move it (ADR 0021).
Under a profile with `freezeOnInitialFail` a `FROZEN` account stays frozen,
with the same freeze block, until every case of it that received an initial
`FAIL` has reached a terminal state (ADR 0015); while any such case is
pending, the account admits no settlement. Under a profile without it, the
only production setting, an initial `FAIL` freezes nothing and the account
enters `CLAIM_OPEN` at the confirmed failure (ADR 0020).
When the claim window closes, `forfeitUnclaimed` forfeits the frozen entries
without a refund right of their own in one transfer pair; their stored state
stays `DEFERRED` or `RELEASABLE` and `purchaseState` reports `FORFEITED`. A frozen
entry whose own case is still open then is forfeited when that case ends
without a refund right. An entry settled after the freeze block, which a
reopened account admits after a reinstatement during the window, is not in
the frozen window and is never forfeited by it: the contract keeps the
deferred and encumbered totals of such entries apart, and the forfeited amount
and the frozen pool are the account's totals minus them (ADR 0021).

## 4. Case state

Each purchase has at most one content-review path and one purchase-principal
hold. Under ADR 0008, a later buyer NON_DELIVERY claim may have a separate delivery
recovery record and deposit without adding another content-review path or another
principal balance. Legacy isolated buyer recovery retains the case record.
Explicit buyer recovery selectors address only the independent record.
getBuyerRecovery exposes it. Both records must be terminal before seller release.

| Current state | Call or condition | Next state | Effect |
| --- | --- | --- | --- |
| `NONE` | `openSample` | `ASSIGNING` | Hold funds and start sampled review. |
| `NONE` | `dispute(NON_DELIVERY)` | `SERVE_WAIT` | Hold funds, collect the dispute deposit, and request delivery. |
| `NONE` | `dispute(WRONG_DELIVERY)` | `ASSIGNING` | Hold funds and start content review. |
| `ASSIGNING` | sealed epoch randomness and `assignVerifier` | `JUDGING` | Lock verifier liability and set a deadline. |
| `SERVE_WAIT` | `served` | `SERVE_CONFIRM` | Record the seller's bundle commitment. |
| `SERVE_WAIT` | `timeoutServe` | `UNSERVED` | Record seller failure. |
| `SERVE_CONFIRM` | buyer `acceptServe` or public `finalizeServed` | `DELIVERED` | End a buyer delivery claim. |
| `SERVE_CONFIRM` | verifier `acceptServe` or public `finalizeServed` | preserved `resumeState` | Resume the preserved assignment with a fresh judgment deadline. |
| `SERVE_CONFIRM` | `escalate` | `PUBLISHING` | Require on-chain response publication. |
| `PUBLISHING` | valid `publish` or `finalizePublication` for a buyer | `DELIVERED` | Make the committed response available and end the delivery claim. |
| `PUBLISHING` | valid `publish` or `finalizePublication` for a verifier | preserved `resumeState` | Make the response available and resume judgment. |
| `PUBLISHING` | `timeoutServe` after no valid final publication | `UNSERVED` | Record seller failure. |
| `DELIVERED` | buyer timely converts to wrong delivery | `ASSIGNING` | Start content review without a second deposit. |
| `ASSIGNING` | search exhausted, initial stage of a sampled case | `WAITING_ASSIGNMENT` | Keep the purchase held; record the checkpoint version and block of the search; no deadline; `attempt` unchanged (ADR 0028). |
| `ASSIGNING` | search exhausted otherwise | `INCONCLUSIVE` | End without seller failure. |
| `WAITING_ASSIGNMENT` | `assignVerifier` with no checkpoint written after the search, or before the redraw block has passed | unchanged | Reverts (`InvalidTransition`, `DeadlineNotReached`). |
| `WAITING_ASSIGNMENT` | `assignVerifier` after the redraw block of the first checkpoint written after the search, an eligible verifier found | `JUDGING` | Lock verifier liability on that checkpoint's room and start the judgment deadline in this block (ADR 0028). |
| `WAITING_ASSIGNMENT` | `assignVerifier`, search exhausted again, redraw hash no longer served, or fewer than `minVerifiers` in that checkpoint | `WAITING_ASSIGNMENT` | Record that checkpoint as searched in this block (ADR 0028). |
| `WAITING_ASSIGNMENT` | `timeoutSampleReceipt` after the receipt deadline | `UNSERVED` | Record seller failure (ADR 0024). |
| `JUDGING` | `judge` | `INITIAL_VERDICT` | Record the first content verdict. |
| `JUDGING` | `timeoutJudge`, attempts remain | `ASSIGNING` | Penalize and replace the verifier. |
| `JUDGING` | final attempt times out, sampled case, nothing served | `PUBLISHING` (keeper) | Require the seller to publish the sampled response on chain (ADR 0014). |
| `JUDGING` | final attempt times out otherwise | `INCONCLUSIVE` | End without seller failure. |
| `PUBLISHING` (keeper) | valid `publish` or `finalizePublication` | `INCONCLUSIVE` | End without seller failure. |
| `PUBLISHING` (keeper) | `timeoutServe` after `publishDue` | `UNSERVED` | Record seller failure. |
| `PUBLISHING` (keeper) | `served`, `acceptServe`, `finalizeServed`, or `escalate` | unchanged | Reverts: a keeper case has no off-chain delivery step. |
| `INITIAL_VERDICT` | timely `appeal` | `PARTY_REVIEW` | Fix later randomness and exclude prior verifier. |
| `INITIAL_VERDICT(PASS or INCONCLUSIVE)` | appeal ends, recheck selected | `AUTO_REVIEW` | Assign a second verifier. |
| `INITIAL_VERDICT` | appeal ends, no recheck | `FINAL` | Use the initial verdict. |
| `PARTY_REVIEW` | second verdict agrees | `FINAL` | Use the shared verdict. |
| `PARTY_REVIEW` | second verdict differs | `TIEBREAK` | Fix later randomness for a third verifier. |
| `PARTY_REVIEW` | `timeoutJudge`, attempts remain | `PARTY_REVIEW` | Penalize and replace the second verifier. |
| `AUTO_REVIEW` | second verdict agrees | `FINAL` | Use the shared verdict. |
| `AUTO_REVIEW` | second verdict differs | `TIEBREAK` | Fix later randomness for a third verifier. |
| `AUTO_REVIEW` | `timeoutJudge`, attempts remain | `AUTO_REVIEW` | Penalize and replace the second verifier. |
| `TIEBREAK` | third verdict | `FINAL` | Use the third verdict. |
| `TIEBREAK` | `timeoutJudge`, attempts remain | `TIEBREAK` | Penalize and replace the third verifier. |
| any review stage | final assignment times out | `INCONCLUSIVE` | End without seller failure. |
| `INITIAL_VERDICT`, `PARTY_REVIEW`, `TIEBREAK` waiting for review randomness | seal window passed or block hash unavailable, first time in the stage, hash still served or recorded | unchanged | Reopen the seal with the same `randomBlock` and its stored hash until `block.number + 1 + sealBlocks`, mark the stage, emit `ReviewResealed` (ADR 0021, ADR 0025). |
| `INITIAL_VERDICT`, `PARTY_REVIEW`, `TIEBREAK` waiting for review randomness | the reopened window passed, or the hash was gone at the reopening | `INCONCLUSIVE` | End without seller failure; return the appeal deposit (a seller-appealed review upholds the initial `FAIL`, ADR 0024). |

`UNSERVED`, `DELIVERED`, `INCONCLUSIVE`, and `FINAL` are terminal case states.
`FINAL(FAIL)` and `UNSERVED` make the purchase refundable. `FINAL(PASS)`,
`FINAL(INCONCLUSIVE)`, `INCONCLUSIVE`, and `DELIVERED` make it releasable after
its financial timing conditions hold, unless its entry is frozen or forfeited.
The standalone `INCONCLUSIVE` state is a
progress failure before a final content verdict; `FINAL(INCONCLUSIVE)` is a
completed review whose deciding verifier could not establish either result.

The two have different consequences. A protocol `INCONCLUSIVE` changes no
counter and no seller state. Every final content verdict (`FINAL(PASS)`,
`FINAL(FAIL)`, `FINAL(INCONCLUSIVE)`) of a sampled case (trigger `SAMPLE`)
increments the bond account's judged count within `inconclusiveWindowBlocks`,
and a sampled `FINAL(INCONCLUSIVE)` also increments its inconclusive count.
When `judgedCount >= minJudgedCount` and `inconclusiveCount * PPM >
maxInconclusivePpm * judgedCount`, counting the case itself, the sampled
`FINAL(INCONCLUSIVE)` freezes the bond account, suspends the seller, and opens
the claim window, but is not counted toward `failureLimit`, deducts nothing
from the bond, and makes no verifier wrong. Below the threshold, or with fewer
than `minJudgedCount` judged cases in the window (ADR 0020), it ends without
seller failure. A final content verdict of a
party dispute (`NON_DELIVERY` followed by `WRONG_DELIVERY`, or
`WRONG_DELIVERY`) changes neither count and starts no counting window; a
disputed `FINAL(INCONCLUSIVE)` ends without seller failure at any rate, and a
disputed `FINAL(FAIL)` is a seller failure like a sampled one (ADR 0017).

A sampled case keeps the seller's obligation to produce the sampled response
even if no verifier completes the initial stage. When the final initial
assignment times out and the seller has not served in this case, the case
enters `PUBLISHING` with requester role
`KEEPER` (the caller of the transition) and `publishDue = block.number +
serveBlocks`. A keeper cannot check an off-chain bundle, so the request skips
the `SERVE_WAIT` and `SERVE_CONFIRM` steps and requires on-chain publication
(ADR 0014). A valid publication ends the case as protocol `INCONCLUSIVE`; a
publication timeout ends it `UNSERVED`.

`stage` and `attempt` are stored independently from `CaseState`. A buyer
non-delivery case has no resume stage. When an assigned verifier requests serve
from `JUDGING`, `PARTY_REVIEW`, `AUTO_REVIEW`, or `TIEBREAK`, the contract
preserves the active case state, stage, attempt, verifier, and liability. It
stores that case state as `resumeState` while the case passes through the serve
states. Successful delivery restores it; seller failure ends the whole case as
`UNSERVED`.

One assignment search evaluates rounds `0` through `minVerifiers - 1` against
the sealed epoch checkpoint. If no round names an eligible verifier, the
initial stage of a sampled case waits in `WAITING_ASSIGNMENT` for a newer
checkpoint (ADR 0028, `sortition-v1.md` section 5.1); any other case is
`INCONCLUSIVE`. `maxAssignments` counts verifiers actually assigned and later
timed out within one stage; it does not limit the ticket-search rounds, and
waiting does not count against it.

## 5. Serve deadlines

`requestServe` records:

```text
serveDue = block.number + serveBlocks
```

For a buyer, `dispute(NON_DELIVERY)` performs the serve request atomically. Only
the assigned verifier may call the standalone `requestServe` entry point. That
call pauses the verifier's judgment deadline without releasing its liability.

`served` is timely through `serveDue` and records:

```text
challengeUntil = block.number + serveBlocks
```

The active requester may accept or escalate through `challengeUntil`. After
that block, anyone may call `finalizeServed`. A timely `escalate` records a new
`publishDue = block.number + serveBlocks`. Each `publishChunk` must arrive
through `publishDue`. A chunk does not extend the deadline.

The seller declares `totalBytes`, `chunkCount`, and the receipt's `responseHash`
in `beginPublication`. `chunkCount` MUST equal
`max(1, ceil(totalBytes / 16,384))`. Chunks use zero-based consecutive indices,
each index may appear once, every non-final chunk is 16,384 bytes, and the final
chunk has the exact remaining length. The empty response uses one empty chunk.
The contract stores each chunk hash, not its body bytes, and computes the
positional response root from `cryptography-v1.md` at finalization.
`finalizePublication` succeeds only after the exact declared byte count and all
chunks are present and the root equals the signed receipt. Failure to finish by
`publishDue` becomes `UNSERVED`.

## 6. Judgment and evidence deadlines

Each assignment records:

```text
judgeDue = assignedBlock + judgeBlocks
```

A timely verdict ends that assignment. An initial buyer dispute waits in
`ASSIGNING` until its settlement epoch randomness is sealed. Anyone may then
call `assignVerifier`. Sample opening and timeout reassignment may perform the
same bounded assignment search in their transaction.

`requestEvidence` may be called through
the case appeal deadline. It records `evidenceDue = block.number +
evidenceBlocks`. Failure to disclose evidence by `evidenceDue` voids that
assignment's verdict, applies the late penalty, and returns the same stage to
`ASSIGNING`. The reassignment counter remains bounded by `maxAssignments`.

The initial verdict records `appealUntil = block.number + appealBlocks` and the
automatic-review candidate `randomBlock = appealUntil + 1`. `appeal` is timely
through `appealUntil`; a timely appeal replaces the active review block with the
appeal transaction block plus one.

## 7. Review randomness

A party appeal records `randomBlock = appealTransactionBlock + 1`. An automatic
review uses `randomBlock = appealUntil + 1`. A review verdict, on either path,
that differs from the initial verdict records `randomBlock =
disagreementVerdictBlock + 1` for the tiebreaker (ADR 0019).

`sealReviewRandomness` stores the hash of the recorded block and uses the same
`sealBlocks` bound as epoch sealing. When the seal window has passed or the
block hash is unavailable, the first time in a review stage (the recheck gate,
`PARTY`, `AUTO` or `TIEBREAK`) the seal reopens: the case keeps `randomBlock`,
stores its hash when the chain still serves it, marks the stage as resealed,
records the reopened window's end `block.number + 1 + sealBlocks`
(`getReviewResealDue`), and emits `ReviewResealed` with the unchanged block. A
seal inside the reopened window uses the stored hash, so every assignment
input of the stage stays as it was (ADR 0025, rule D2-16 (e)). When the
reopened window passes, or at the reopening when the hash is already gone, the
stage ends as a progress failure: `INCONCLUSIVE`, which does not turn an
unverifiable content claim into seller failure (ADR 0021), except that a
seller-appealed review against an initial `FAIL` upholds it (ADR 0024).
`finalizeCase` after the seal window of a party review or tiebreak, and the
recheck gate after the seal window of its candidate block, follow the same
rule.

For `PARTY_REVIEW` and `TIEBREAK`, successful sealing immediately runs the
bounded assignment search for that stage. `openAutoRecheck` is valid for an
unappealed initial `PASS` or `INCONCLUSIVE` after the automatic candidate
block and through its seal deadline. It seals the candidate block when needed,
computes selection, assigns a second verifier when selected, and otherwise
finalizes the initial verdict. A standalone `sealReviewRandomness` may cache
the automatic randomness first, but does not extend that deadline.
Assignment-search exhaustion or failure to progress a selected review by the
deadline ends the case as `INCONCLUSIVE`.

The case records `reviewPath` as `PARTY` or `AUTO` before assigning a second
verifier. Once nonzero, it cannot change. On either path a second verdict
equal to the initial verdict is final, a second verdict that differs sends the
case to a third verifier, and the third verdict is final (ADR 0019).

## 8. Epoch failure

An epoch enters `EPOCH_FAILED` when any account calls `timeoutAnchor` after the
anchor deadline of an epoch without an anchor, or `timeoutSeal` after the
anchor deadline of an anchored epoch whose checkpoint holds fewer than
`minVerifiers` verifiers (ADR 0029). An anchored epoch without its value does
not fail. Each purchase recorded for that seller and epoch then becomes
independently refundable. The buyer proves membership from the contract
purchase record and does not need a receipt or Merkle proof.

An epoch that failed because no anchor was submitted is the seller's failure.
`timeoutAnchor` freezes the seller's bond account, suspends the seller, opens
the claim window, and records one failure for that epoch; later refunds from
the same epoch record nothing more. An epoch that failed after a valid anchor,
through the checkpoint shortage, is a protocol progress failure: its purchases become refundable, but no seller state or counter
changes. The counted epoch failure deducts one share of the seller penalty
like any confirmed failure (section 9); the refunds of the same epoch deduct
nothing more.

## 9. Fund priority

Refund accounting follows this order:

1. use the affected purchase's complete deferred amount;
2. use seller bond above the reserved seller penalty only if a contract
   accounting fault or an explicitly enabled profile rule created a shortfall;
3. charge the reserved seller penalty only through the per-failure rule of
   ADR 0018: every counted confirmed failure of the bond account deducts
   `min(sellerPenalty / failureLimit, balance)`, locked in the contract (ADR
   0022), and
   the failure that brings the count within `failureWindowBlocks` to the
   window's threshold `n * failureLimit` deducts the remainder, `min(n *
   sellerPenalty - (n * failureLimit - 1) * (sellerPenalty / failureLimit),
   balance)`, so that one window's deductions sum to `n * sellerPenalty`;
   `n`, at least one, is the larger of the account's scale factor before the
   opening failure's deduction and its recent scale high within
   `retentionBlocks`, raised by a top-up that raises the scale factor while
   the window is open (ADR 0021, ADR 0022); nothing is deducted after the
   sanction.

Normal deferred funds from another purchase never pay a refund of an
individually refundable purchase or the seller penalty. The one exception is
the frozen pool: after a final failure, the buyer of any frozen entry of the
same bond account without its own refund right may claim that entry's own
amount with a seller-signed receipt during the claim window
(`claimWindowBlocks`, equal to `retentionBlocks`). The remainder after the window
is forfeited and locked in the contract (`lockedForfeit`); no function
withdraws it, and it never returns to the seller (ADR 0022). An
independent buyer-recovery deposit is never paid out of the frozen pool; it
follows the release rule of its purchase. A dispute or appeal deposit pays only bounded case costs and delay
compensation. It does not replace the purchase principal.

A buyer dispute deposit follows the terminal result. It returns to the buyer for
`FAIL`, `UNSERVED`, or `INCONCLUSIVE` (including a `FINAL(INCONCLUSIVE)` above
the inconclusive threshold); it transfers to the seller for `PASS` or
`DELIVERED`. A sampled case has no dispute deposit.

An appeal deposit returns to the appellant when the final verdict differs from
the initial verdict or is `INCONCLUSIVE`. When the final verdict confirms the
initial verdict, including through a tiebreak, the deposit transfers to the
opposing purchase party. An appeal does not change the purchase-principal
accounting.

A wrong-verdict penalty applies only when the final verdict is `PASS` or `FAIL`.
No verifier receives a wrong-verdict penalty when the final verdict is
`INCONCLUSIVE`. An applicable penalty transfers to the appellant on the
party-review path when the final verdict differs from the initial verdict (the
successful appellant), and to the immutable penalty treasury otherwise and on
the automatic path. A verifier late penalty transfers to the same
treasury. The per-failure shares of the seller penalty and forfeited pools
transfer nowhere: they stay locked in the contract (ADR 0022). Version 1 pays no caller reward for public progress transactions;
experiments account for their gas separately.

## 10. Public progress calls

Anyone may call the following functions when their state and block predicates
hold:

```text
seal
openSample
assignVerifier
timeoutAnchor
timeoutSeal
timeoutServe
timeoutJudge
timeoutEvidence
sealReviewRandomness
openAutoRecheck
claimEpochFailure
finalizeCase
claimRefund
releasePurchase
freezeSellerDeferred
releaseFrozen
forfeitUnclaimed
```

`freezeSellerDeferred(triggerNonce)` freezes the bond account of a case holding
an initial `FAIL` that is not yet terminal, under a profile with
`freezeOnInitialFail`, when no freeze is in place;
`releaseFrozen(bondId)` clears a freeze whose trigger case ended without a
failure, or re-anchors it to the earliest remaining pending initial `FAIL`
when one is left; `forfeitUnclaimed(bondId)` closes a claim window after
`claimUntilBlock`, including any extension by a later confirmed failure. The
contract also performs the freeze, the overturn, the move of the freeze block
and the opening and extension of the claim window inline in the transitions
that cause them. `reinstateSeller` is a seller-owner call, not a public
progress call; it is admitted while the claim window is open (ADR 0021).

These functions do not accept a caller-selected result. A failed or premature
call reverts without changing funds, counters, randomness, or assignments.

## 11. ADR 0009 implementation rules

An initial evidence request is allowed once for the active stage/attempt, by the buyer or seller, through appealUntil. It suspends appeal, auto selection and finalization until disclosure or timeout. Matching bounded evidence disclosed through evidenceDue starts a full appealBlocks window from that block and sets randomBlock=appealUntil+1. Timeout after evidenceDue voids the verdict and releases that assignment after its late penalty, then increments the attempt or ends INCONCLUSIVE. Old signed verdicts and evidence requests cannot be replayed against the replacement.

requestServe is allowed once per assigned verifier and only through judgeDue. Assignment history retains liability and penalty reserve for submitted verdicts. Late assignments release their own capital after their penalty; finalization releases all remaining assignments. Only signed PASS/FAIL that differ from a conclusive final verdict receive a wrong-verdict penalty. INCONCLUSIVE never receives a wrong-verdict penalty. Counterparties retain distinct buyer delivery state while review runs. Seller failure outside review returns any unresolved appeal deposit to its appellant and releases all assignments without inventing content faults. Final content FAIL applies seller failure but records FINAL/FAIL. Terminal INCONCLUSIVE does not create a seller failure.

Review waiting states have assignedVerifierId=0 until their fixed future hash is sealed. Assigning a review restores its corresponding PARTY_REVIEW, AUTO_REVIEW or TIEBREAK state. Missing/expired review randomness reopens the seal once per stage and ends INCONCLUSIVE the second time (ADR 0021); exhausted bounded ticket search ends INCONCLUSIVE. An initial FAIL finalizes after its unobstructed appeal window; an initial PASS or INCONCLUSIVE must use the fixed automatic candidate and selection gate (ADR 0019). No caller chooses a deciding outcome or randomness.

A strike-limit removal excludes both ACTIVE and EXITING verifiers from future assignment. A REMOVED verifier may finalize exit directly only after its retention lock, zero liabilities and zero reservations; removal does not confiscate the remaining unslashed bond.

## ADR 0024 case rules

- `openSample` also accepts a case in `DELIVERED` with trigger
  `NON_DELIVERY` whose purchase is `RELEASABLE`, or `HELD` by an open buyer
  recovery; the case becomes a sample case in `ASSIGNING` and the purchase
  `HELD`. `releasePurchase` reverts `NotSampled` for such a purchase while it
  is sampled.
- A sample case sets `sampleReceiptDue = opening block + serveBlocks`.
  `submitSampleReceipt` (anyone, until the deadline) or a verdict carrying the
  receipt and proof by the deadline clears it. `timeoutSampleReceipt`, after
  the deadline, ends a sample case that is not `FINAL`, `INCONCLUSIVE` or
  `UNSERVED` as `UNSERVED` through the seller-failure path.
- In `_finishReview`, a progress failure with `reviewPath = 1` and
  `initialVerdict = FAIL` yields `FINAL(FAIL)` instead of `INCONCLUSIVE`,
  without wrong-verdict penalties and without recording a judged case.
- The case horizon of `profile-v1.md` section 3 is the longest of these paths
  plus `marginBlocks`.

## ADR 0025 case rules

- An assignment reads a candidate's eligibility from the epoch's checkpoint
  (membership and liability room), not from the verifier's state at case
  opening (`sortition-v1.md` sections 2 and 4).
- A reopened review seal keeps `randomBlock`; its window ends
  `getReviewResealDue(nonce)` (section 7).
- `judge` on a sample case after its receipt deadline, with the receipt not on
  chain, ends the case `UNSERVED`, like `timeoutSampleReceipt`.
- The keeper calls `timeoutSampleReceipt` in the first block after the
  deadline and, given the published receipt list, submits the receipt before
  it.

## ADR 0028 case rules

- An exhausted search of the initial stage of a sampled case (any attempt)
  leaves the case in `WAITING_ASSIGNMENT` with its purchase `HELD`. The case
  has no judgment deadline while it waits and no bound on the number of
  redraws; `attempt` does not move.
- `assignVerifier` on a waiting case is a public progress call. It redraws on
  the first checkpoint written in a block after the case's last search, from
  the hash of that checkpoint's block plus `beaconDelayBlocks + 1`
  (`sortition-v1.md` section 5.1). Its first eligible block is the obligation
  block of the keeper (design 2 assumption A2).
- `releasePurchase` refuses a waiting purchase, and `claimRefund` refuses it
  while it waits (it is `HELD`); a freeze of the bond account covers it as an
  encumbered entry until its own case ends.
- The receipt deadline of the sample case keeps running from the case opening
  and a missing receipt ends a waiting case `UNSERVED`.
- Exhaustion of a review stage, of the initial stage of a buyer dispute and
  the timeout of the final initial attempt are unchanged.

## ADR 0029 epoch and release-clock rules

- `seal` delivers the epoch value after `randomBlock` for as long as the
  chain serves `blockhash(randomBlock)`, also after `sealDeadline`. Without
  it the call reverts `InvalidRandomnessWindow` and changes nothing.
- `timeoutSeal(sellerId, epoch)` is valid for an `ANCHORED` epoch after its
  anchor deadline, before or after the value exists, and only when the
  epoch's checkpoint (the latest written at or before the anchor deadline) is
  missing or holds fewer than `minVerifiers` verifiers. It sets
  `EPOCH_FAILED` with reason `VERIFIER_SET_UNAVAILABLE`. Otherwise it reverts
  `InvalidTransition` (`DeadlineNotReached` through the anchor deadline).
- The first sampled case of a bond account that enters `WAITING_ASSIGNMENT`
  stops the account's release clock in that block; the last one to leave it
  (a redraw that assigns, or a case that ends) restarts it in that block.
  A redraw that finds nothing does not count the case again.
- `releasePurchase` requires `block.number - pausedSince(s) >= releaseBlock`
  in addition to every other release condition. The recent value cap and
  sanction limit (ADR 0024), the recent scale high (ADR 0022) and the bond
  exit lock end after `retentionBlocks` unpaused blocks. The claim window,
  `retainUntil`, the omission-proof deadline, the seller exit lock and the
  verifier exit lock keep counting wall blocks.
- A waiting case of a frozen account keeps stopping the clock of every entry
  of the account, including entries settled after a reinstatement.
