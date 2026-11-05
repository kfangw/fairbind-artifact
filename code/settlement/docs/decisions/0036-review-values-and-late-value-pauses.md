# ADR 0036: Review values of batched cases and pauses of late values

Status: Accepted 2026-10-19. Amends ADR 0032 (review stages, the start of
the late-batch pause) and ADR 0029 (paused blocks) for profiles with batch
terms. A profile without batch terms behaves as before; `seal` and the
end of an epoch's sampling read one more storage slot.

## Context

Under ADR 0032 the review stages of a batched case (the party review after
an appeal, the automatic recheck, the tiebreak) still drew their candidates
from the hash of a block after the stage opened. A block producer that is
part of a coalition can withhold or choose that hash; the first assignment
and the redraw already use values of a request-based source that nobody
can choose. The pause of a late batch value also began at the keeper's
call rather than at the block after the bound, and AUX and sampling values
that came late did not pause the account at all.

## Decision

1. **Review uses.** In a batched profile the transaction that opens a review
   stage registers the stage's use in its block t: the appeal
   (`appeal`, `appealWithLimit`), the recheck selection (`finalizeCase`,
   `openAutoRecheck`; the selection itself still reads the review block
   hash) and the verdict that leads to the tiebreak. The stage waits in
   `PARTY_REVIEW`, `AUTO_REVIEW` or `TIEBREAK` with no verifier.
   `requestReviewValue(nonce)` asks, from block t + 1, for the AUX value of
   input `(keccak256("FairBind/review/v1"), nonce, stage, 0, t)`;
   `assignReview(nonce)` takes it once stored, records it as the case's
   randomness and its storage block as the block that fixes the candidate,
   and places the stage through the verifier queues. Later attempts of the
   stage draw from the same value. `sealReviewRandomness` and the reseal
   path of `finalizeCase` are closed for these stages.
2. **Review exits.** When the review value is not stored by its first request
   block + D_V + T_V, `timeoutReviewValue(nonce)` ends the stage from the
   next block. A review the seller asked for against an initial FAIL, and a
   review of a case that is not a sample case, end as a progress failure
   (the FAIL is upheld and counted). Any other review of a sample case ends
   without a verdict: its verifiers are released without penalty, the
   appeal deposit returns to the appellant, and the account is suspended
   and frozen from the case's sale with its claim window open, nothing
   counted or deducted.
3. **Late-value pauses.** A sample case that waits for a value past its
   bound pauses its account's release clock from the block after the bound:
   the batch value after `C_e + assignDelay` (`markAssignLate`), the late
   first assignment's and a review stage's AUX value after `t + D_S`
   (`markValueLate`), and the epoch's sampling value after `A_e + D_S`
   (`markSampleLate`, per seller and epoch). A mark records the pause from
   that block even when the keeper calls later; pauses that began after it
   are merged. The pause ends when the value is used (`assignBatch`,
   `assignLate`, `assignReview`), when the case exits, or for the sampling
   value when the epoch is sealed or fails or, outside a side-gain profile,
   when `noteSampleDeadline` is called after M. A value used without a mark
   after its bound records the pause from the block after the bound to the
   use in that transaction.
4. **Packaging.** Operation 10 registers a review use and runs in
   `FairBindDeposit` with the review calls; `markValueLate` runs in
   `FairBindBatch`; operation 11
   ends a sampling pause and runs in `FairBindProof` with `markSampleLate`,
   for the size limit.

## Consequences

- Who judges a review stage is fixed by its AUX value and the case; no
  block hash enters it.
- A pause ends in the transaction that uses the value, which may be later
  than the block the value was stored: an account counts at most the
  keeper's delay more paused blocks than the bound requires. A mark made
  after a value was stored is refused; a sampling value stored after its
  bound before any mark records no pause.
- Releases made before a mark are not undone; a mark changes only entries
  still held.
- The recheck selection draws from the review block hash as before.

## Tests

`ReviewValues.t.sol`: the appeal and the tiebreak drawing from their AUX
values with the next attempt on the same value, the recheck selection's
value, the closed seal paths, the exit of a seller's appeal (with a mutation
that does not count it) and of a buyer's appeal, and the late-value pauses
of a late first assignment, a review stage and an epoch's sampling value
(with mutations that pause from the call). `BatchAssignment.t.sol`: the
late batch value paused from `C_e + assignDelay + 1` (with a mutation), the
unmarked late batch value, the exit bound (with a mutation without T_V),
and the queue pause (with a mutation). `BatchWait.t.sol`: the redraw of a
waiting case into a queue.
