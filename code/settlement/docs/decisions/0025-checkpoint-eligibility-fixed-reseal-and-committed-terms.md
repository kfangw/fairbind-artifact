# ADR 0025: Checkpoint-time verifier eligibility, a review reseal that keeps its block, and committed profile terms

Status: Accepted 2026-10-10. Amends ADR 0009 (reserved verifier penalties),
ADR 0021 (reopened review seal) and ADR 0024 (profile terms, sample receipts,
router reads) in `sortition-v1.md` sections 2 to 5, `lifecycle-v1.md`
sections 4 and 7, `fairbind-v1.md` sections 13 and 17, `profile-v1.md`
section 9 and `contract-interface-v1.md`. Appends storage slots, one module
and router entries. Changes the signature of `setProfileTerms` and the
`ProfileTermsSet` event, both added by ADR 0024 and not yet deployed; changes
no other ABI entry, no existing storage slot and no existing encoding.

The research decision this record implements is decision 126 of the project
record (2026-10-10): a verifier's eligibility is judged on its state at the
checkpoint of the epoch, not when the case opens. The other changes close the
second-grade findings 1, 2, 3, 5 and 6 of the IMPL-1 code review and three of
its third-grade findings.

## Problem

1. **Targeted decoys.** The first assignment of a case draws its candidate
   table from the epoch value and the checkpoint, and skipped a candidate that
   had no liability room when the case opened. Once the epoch value is known a
   seller can compute the first candidate of every one of its sample cases. It
   opens first the honest cases whose first candidate is an honest verifier,
   until those verifiers are full, and then opens its fraudulent case, whose
   first candidate is skipped. With fourteen verifiers (nine honest, weight
   0.67) and a limit of 29 cases, 450 to 500 decoys bring the probability that
   the first assignment is honest from 0.67 to between 0.022 and zero, while
   the ineligible weight share stays at 0.66 to 0.67, inside the operating
   condition `rho <= 0.7319` (lemma A, fourth edition, review finding 2-1).
2. **Terms on a profile that was active.** `setProfileTerms` checked only that
   the profile was inactive now. Terms fixed after a deactivation turned an
   account opened with `registerBond` into a tiered account with cap zero: its
   unit bond and deduction were zero and its confirmed failure reverted with a
   division by zero, so a missed anchor could never be recorded.
3. **Terms outside `parameterHash`.** Rule D2-13 (a) commits the caps, `p0`
   and the tiers through `parameterHash`. The terms arrived in a later call
   and nothing tied them to the hash; the repository held no design 2 profile
   document.
4. **Reseal moved the review block.** A review seal whose first window lapsed
   reopened with `randomBlock = block.number + 1`, so the reopened stage drew
   its verifier from a new value. A seller who let the first window lapse when
   an honest reviewer was drawn got a second draw (rule D2-16 (e)).
5. **Late sample verdicts.** A verdict that carried the receipt after the
   receipt deadline was recorded, and the case ended `UNSERVED` only if
   someone called `timeoutSampleReceipt` before `finalizeCase` ended it.
6. **Router size and keeper.** The router had 294 bytes left. The keeper did
   not call `timeoutSampleReceipt` or post sample receipts.

## Decision

1. **Eligibility at the checkpoint (decision 126).** `checkpointVerifierTree`
   stores, beside the verifier set, each verifier's liability room at the
   checkpoint block: `min(bond - reservedPenalties - reserve, cap) * fraction
   / PPM - lockedLiability` under the effective-bond rule of `profile-v1.md`
   section 5, or zero when the bond does not cover one more penalty
   reservation. A call that reproduces both the latest set and the latest room
   returns that version. An assignment under an epoch's checkpoint skips a
   candidate only when it is already in the case or when the case liability
   exceeds its room in the checkpoint. Status, bond and class enter through
   the checkpoint's membership; the verifier's current status, bond and
   liability do not enter. Cases opened after the checkpoint block, in any
   order, therefore change no eligibility, and the first assignment of every
   case follows the checkpoint table.

   A verifier that is full now may be assigned. If it does not answer, the
   existing judgment timeout replaces it with the next candidate and charges
   the late penalty, within `maxAssignments`; the longest case path does not
   change. Liability and penalty reservations are still locked per
   assignment, so a verifier's locked liability may exceed its current limit.
   A penalty takes at most the verifier's remaining bond.

   `_checkpointAt` finds the latest version at or before the cutoff by binary
   search, so the more frequent versions cannot make sealing expensive.

2. **Terms only before first activation.** A profile records that it has
   been active. `setProfileTerms` reverts for such a profile.

3. **Committed terms.** `setProfileTerms(profileId, termsHash, detectFloorPpm,
   valueCaps, tiers)` requires `termsHash = keccak256(abi.encode(
   keccak256("fairbind/profile-terms/v1"), detectFloorPpm, valueCaps, tiers))`,
   stores it with the terms and emits it in `ProfileTermsSet`. The profile
   document carries the terms and `termsHash` inside `parameters`
   (`designTwoTerms`), so `parameterHash` commits them; an observer compares
   the stored `termsHash` with the document. Under terms, `failureWindowBlocks`
   and `inconclusiveWindowBlocks` must equal `retentionBlocks` (rule D2-9).
   `profiles/design2-v1.json` holds the data API and inference documents, and
   `scripts/check_spec.py` recomputes both hashes and the tier checks.

4. **The reopened seal keeps its block (rule D2-16 (e)).** The first call
   after the seal window reopens the stage once without moving `randomBlock`.
   It records the block hash when the chain still serves it (within 256
   blocks of `randomBlock`) and sets the reopened window to end one block plus
   `sealBlocks` after the reopening, the same length as before. A call in the
   reopened window seals with the recorded value; the assignment inputs (value,
   nonce, stage, attempt, round) are those of the first window. The stage ends
   as a progress failure when the reopened window passes, and at once when the
   hash was gone before anyone recorded it, since no call could then seal it.
   `ReviewResealed` keeps its fields; its block is the unchanged `randomBlock`.

5. **A late sample verdict ends the case.** A verdict on a sample case after
   the receipt deadline, with the receipt still missing, ends the case
   `UNSERVED` in the same call. The outcome no longer depends on whether
   `timeoutSampleReceipt` or `finalizeCase` comes first.

6. **Read functions in a lens module.** The read functions run in a tenth
   module, `FairBindLens` (`MODULE_KIND = 10`). The router keeps their
   selectors and ABI; each forwards its call data to the router itself with a
   static call behind a fixed prefix, and the router's fallback delegates only
   that self-call to the lens. Every other unknown selector still reverts.
   `canonicalRequestHash` stays in the router because it is `pure`.

7. **Keeper.** The keeper calls `timeoutSampleReceipt` in the first block
   after a sample case's receipt deadline, and with a published receipt list
   (`receiptsDir`, one JSON file per purchase) submits the receipt and its
   proof before the deadline. Under the worst-path directive it touches the
   receipt calls only with a list. The directive reads the reopened seal's end
   from `getReviewResealDue`.

8. **Smaller items.** `openSample` on a delivered dispute clears the
   dispute's published chunk count and evidence hash. The bond terms field
   `valueCap` is renamed `sampleScaleValue`, the rules' name (D2-2).

## Consequences

The router shrinks from 24,282 to 10,630 bytes (13,946 bytes left); the lens
takes 17,376. Reads cost one more internal call, a static call to the router
and a delegate call to the lens: about 9,400 to 10,100 more gas per read in the
review probes (`getCase` 20,201 to 29,638).

A checkpoint stores one more packed array and reads each verifier's capital:
`checkpointVerifierTree` with fourteen verifiers rises from 561,958 to 830,864
gas. A new version appears whenever any verifier's room changes, not only when
the set changes. `settle`, `setBondTerms` and `registerBondWithTerms` change
by less than 100 gas and `submitSampleReceipt` by 105; the first assignment in
`openSample` reads the room array instead of the verifier's capital (largest
probe value 500,272 to 489,493).

The stateful suite gains a tiered variant (`FAIRBIND_TIERED=1`), actions for
`setBondTerms`, `submitSampleReceipt` and a stalled seller appeal, and an
invariant that a stalled seller appeal never ends `INCONCLUSIVE`; a build with
rule D2-15 switched off fails it. Its liability invariant now checks
each assignment against the checkpoint room instead of the current exposure
limit.

## Assumptions and limits

1. **Liability locked before the checkpoint.** The room is read at the
   checkpoint block, and a seller can lock liability before that block with
   honest cases of earlier epochs whose values it already knows, or call
   `checkpointVerifierTree` right after doing so. An honest verifier that is
   full at the checkpoint is ineligible for every case of the epochs that use
   it. This closes the reactive attack (decoys chosen after the epoch value)
   but not a standing one (honest verifiers kept full across checkpoint
   blocks). Closing it needs eligibility that ignores liability, or a room the
   seller cannot fill (decision 116 keeps no per-account case limit). The test
   `test_liabilityLockedBeforeTheCheckpointIsPartOfTheSnapshot` pins it.
2. **Exited and removed verifiers.** A verifier in the checkpoint that later
   exits or is removed may still be drawn. Sealing extends the exit lock of
   every verifier in the selected checkpoint, so an exit between the
   checkpoint and the seal is the only case; such a verifier times out and is
   replaced.
3. **Reseal and the block hash.** With block hashes the reopened stage can
   seal only if someone recorded the hash within 256 blocks of `randomBlock`,
   that is in the first window or in the 56 blocks after it (with
   `sealBlocks = 200`). A replacement randomness source (rule D2-16 (a) to
   (d)) is outside this record.
4. **Receipt list.** The keeper's receipt posting depends on the seller's
   published list (A-LEAF). No service publishes signed receipts in the
   directory format yet.
