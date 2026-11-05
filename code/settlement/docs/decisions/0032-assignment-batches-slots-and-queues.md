# ADR 0032: Assignment batches, verifier slots and queues

Status: Accepted 2026-10-19. Amends ADR 0025 (eligibility at the checkpoint)
and ADR 0028 (the waiting case) for profiles with batch terms, and the
deployment boundary of `contract-interface-v1.md` ("ADR 0032 batches, slots
and queues") and `traceability.md`. A profile without batch terms behaves as
before; its calls read one more storage slot. ADR 0036 amends the review
stages (item 3 and the last consequence) and the start of the late-batch
pause (item 7).

## Context

Under ADR 0025 a sampled case is assigned when it is opened, from the epoch's
sampling value, and a verifier whose liability room at the checkpoint does
not cover the case is skipped. A seller who opens cases in a chosen order, or
opens decoy cases of other accounts, changes which verifier the next case
reaches; a coalition that keeps verifiers busy changes it as well. The fix is
to fix every candidate by a value that is drawn after the set of cases is
closed, to keep a busy verifier as the candidate and let the case wait for
it, and to order each verifier's waiting cases so that one account's decoys
delay another account's case by at most one turn.

## Decision

1. **Batch terms.** Governance fixes, once and before a profile is first
   active, `BatchStore.Terms`: `assignDelay` (bound on the wait for the
   batch value after the batch closes), `keeperSlack`, `slotValue` (the value
   that sizes slots), and the optional rates of ADR 0033 to ADR 0035. The
   source must be request based (ADR 0031). Admission: `D_S = D_V + 1`,
   `assignDelay >= D_V + 1`, `T_V >= keeperSlack`, `epochBlocks >= D_S +
   T_V`, `slotValue` at least the profile's largest cap. `termsHash`
   commits the terms, the source address, the hash of its public key and its
   two bounds. With a request-based source set, the admission floor of
   `beaconDelayBlocks` is the source's `D_S` instead of 768.
2. **Fixed-block checkpoints and state history.** Once batch terms exist the
   contract keeps, before every change of a verifier's bond, status or
   classes, the state it had (`BatchStore.history`). `checkpointAt(profile,
   e)` writes, after `A_e`, the checkpoint of block `A_e` from that history,
   whoever writes it and whenever, while no checkpoint of a later block
   exists. The ordinary checkpoint is closed for a batched profile. `seal` of
   a batched epoch takes only the checkpoint of `A_e`; `timeoutSeal` ends the
   epoch as a shortage when that checkpoint holds too few verifiers or can no
   longer be written. Eligibility is the state alone: liability room and
   locked liability no longer exclude a verifier.
3. **Batches.** Batch `e` of a profile holds the sample cases of epoch `e`
   opened by `C_e = sealDeadline + openBlocks` and the other cases opened in
   `(C_{e-1}, C_e]` (a wrong-delivery dispute, a seller proof's judgment).
   `requestAssignValue(profile, e)` asks, after `C_e`, for the ASSIGN value of
   input `(profileId, e)`; `assignBatch(profile, e)` takes it once stored.
   Each case's first candidate is the ticket of round 0 of `(value, case,
   stage, attempt)` on the checkpoint of `A_e`; a later round is used only
   when the verifier already took part in the case or left by its own action
   (item 6). The opening order and every other case leave the candidate
   unchanged. A sample case opened after `C_e` is *late*: its first
   assignment uses the AUX value of input `("FairBind/late/v1", nonce, 1, 0,
   t)` with `t` its opening block (`requestLateValue`, `assignLate`).
4. **Slots and starts.** A verifier's slot count is the largest `k` with
   `k (slotValue + maxReviewCost) <= exposure (bond - k reserve)`, the bond
   capped at `verifierBondCap`, under the first batched profile. A placed
   case waits in its candidate's queue (`CaseState.QUEUED`) with a
   reservation of `min(liability, unreserved bond)`. The head starts while the
   verifier judges fewer cases than its slots, and one starts whenever it
   judges none, whatever its slots or state. Starting happens inside every
   transaction that frees a slot (verdict, timeout, case end), raises the bond
   (`topUpVerifierBond`) or places a case; there is no separate call. A
   started case locks its liability then and its judgment window runs from
   then. A penalty that leaves no slot or makes the verifier ineligible moves
   nothing.
5. **Order.** A queue is ordered by the key `(batch, rank, account place,
   first ticket)`: rank is the case's place among its account's cases of the
   batch by first ticket (late cases take the next ranks in arrival order),
   the account place is `keccak256(domain, batch value, bondId)` truncated to
   64 bits, and the first ticket breaks ties. Later stages of a case keep its
   key.
6. **Own departures.** A verifier's exit request, or a withdrawal
   (`withdrawVerifierBond`) that leaves it no slot, records its departure
   block. A case whose candidate is fixed in a later block (the batch value's
   or the AUX value's storage block, the review value's block) moves to the
   next round instead of entering that verifier's queue; a case fixed earlier
   stays. `transferQueued` performs the same move for a queued case and
   refuses one fixed earlier. A queued case blocks the verifier's exit, and
   its reservation limits withdrawals.
7. **Clock and exits.** A queued sample case pauses its account's release
   clock until it starts (ADR 0029). `markAssignLate` pauses the batch's
   sample cases from the call when the batch value is still missing past
   `C_e + assignDelay`. When the ASSIGN (or late AUX) value is not stored by
   its first request block `+ D_V + T_V`, `timeoutAssignValue`
   (`timeoutLateValue`) ends the waiting cases from the next block: a sample
   case without a verdict, its account suspended and frozen from its sale
   with the claim window open, nothing counted or deducted; a dispute as a
   progress failure; a seller proof without a verdict (ADR 0034).
8. **Packaging.** The router runs each selector it does not declare in the
   extension module that declared it (`setExtensions`, once, governance,
   kinds 11 to 14 in order). Modules call extension code through one hook
   entry point, `hook(op, arg)`, only inside their own calls; the router
   does not route it.

## Consequences

- Who judges a case is fixed by the batch value and the case alone; decoys
  and busy verifiers only delay. Delay is paid in the account's release
  clock.
- A verifier with no slot still judges one case at a time; its other queued
  cases wait for it. Queues grow when demand exceeds slots (not enforced).
- A checkpoint written for an epoch reads the history; verifiers registered
  before batch terms existed have no record before registration, so a
  checkpoint of a block before their registration would count them. Batch
  checkpoints are of anchor deadlines after activation, where this does not
  arise.
- `assignBatch` sorts in memory; its gas grows with the batch size and a
  very large batch would need a split call.
- Review stages draw from the review value as before (block hash of the
  stage's random block), placed through the queues; their AUX values and
  exits are open.

## Tests

`BatchAssignment.t.sol`: admission bounds, the beacon floor, extension
installation and the closed hook, the checkpoint of `A_e` (with a mutation
that reads the current state), seal on that checkpoint and the shortage
exit, batch membership, ranks, keys and the late case, candidates
independent of opening order and decoys (with a mutation drawing from the
list order), the alternation bound, slots and the exception start,
judgments held to their deadline and penalties moving nothing, own exits
moving only later-fixed cases (two mutations), withdrawals, the clock pause,
and the exits of a late batch value and a late value. `UnitLength.t.sol`
checks that split-anchor units add up to the count (with a mutation).
