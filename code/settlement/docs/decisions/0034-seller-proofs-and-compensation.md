# ADR 0034: Seller proofs on frozen entries and the compensation pool

Status: Accepted 2026-10-19. Adds seller proofs for profiles with batch terms
whose `auditPpm` is not zero (`contract-interface-v1.md`, "ADR 0034 seller
proofs"). Amends `forfeitUnclaimed` (it waits while a proof of the account is
undecided) and the confirmed-failure path (it ends or voids a proof on the
purchase).

## Decision

1. **Proof.** In an open claim window the seller may prove a frozen,
   unclaimed entry: the signed receipt, its inclusion in the anchor, a
   non-zero predicate commitment and the evidence envelope (calldata), with a
   proof bond `ceil(v (1 - x1) / x1)`, `x1 = auditPpm * p0`, paid apart from
   the account's bond. The entry is held: it cannot be claimed, and the
   window cannot be forfeited, until the proof ends. One proof per entry.
   `setProofsOff` stops new proofs at once; switched back on, only entries
   settled after that block can be proven.
2. **Order.** A proof opens only when the entry's epoch is sealed and past its
   batch close, the entry's own sample case (if sampled) has ended, no sample
   case of the account is open, and every epoch in which the account sold has
   its sampling decided (sealed, failed, or past its sampling deadline as
   recorded by `noteSampleDeadline`). Otherwise it is reserved;
   `activateProof` opens it later. A reservation whose epoch can no longer
   decide (`voidReservation`), or whose purchase has a confirmed failure,
   ends with its bond returned and does not count as the entry's proof.
3. **Audit and contest.** Opening registers the audit use in that block t;
   `requestAuditValue` asks from t + 1 for the AUX value of input
   `("FairBind/audit/v1", nonce, 0, 1, t)` and `drawAudit` audits with
   probability `auditPpm`. An audited proof's judgment joins the batch of
   that block (ADR 0032). An unaudited proof is open to contest for
   `contestBlocks` with a deposit of the entry's value (`contestProof`), whose
   judgment joins the batch of its block; without a contest it is confirmed
   (`confirmProof`, or at once when contest is off). An unanswered audit
   value ends the proof without a verdict (`timeoutAuditValue`); the proof
   counts.
4. **Judgment.** The assigned verifier signs `FairBindProofVerdict(nonce,
   attempt, verifierId, verdict, evidenceHash)` on the predicate recomputed
   on the envelope (`judgeProof`); a late verifier is replaced
   (`timeoutProofJudge`, `maxAssignments` attempts). PASS confirms the proof:
   the bond returns, a lost contest deposit is locked. FAIL forfeits the bond,
   pays the contester its deposit and `min(bond, deposit)`, and counts one
   failure of the account without a new freeze, deduction or suspension.
   INCONCLUSIVE forfeits the bond and counts nothing. After FAIL or
   INCONCLUSIVE the entry returns to the claim window, which runs at least
   `claimWindowBlocks` from the verdict.
5. **Release.** A proven entry is paid to the seller by `releaseProven` under
   the release rules of `releasePurchase`, its effective age counted in
   unpaused blocks. A later confirmed failure of the purchase voids the
   proof.
6. **Compensation pool.** The forfeited bond, less the contester's share,
   enters the account's own pool. `distributeCompensation` splits the pool
   over the account's proven entries in proportion to value once no proof or
   reservation of the account is undecided; `claimCompensation` pays each
   buyer its accrued share. A voided entry keeps what it accrued and stops
   sharing. With no proven entry the pool waits, and is locked after the
   account's bond exits. Pools are never shared between accounts.

## Consequences

- A seller's own buyers share the pool like any buyer; the pool bounds what
  they can take back, and other accounts' pools and buyers are out of reach.
- The judgment of a proof is one stage with attempts; it has no review or
  tiebreak.
- Under the keeper assumption every sampled sale's case is opened by its
  batch close; a sampled sale left unopened is not visible to the order
  condition.
- The claim window of the account is extended after a failed proof rather
  than the entry's alone.

## Tests

`SellerProof.t.sol`: an audited proof that passes and its release, an
audited proof that fails with its pool split to a proven entry, a winning
contest, a lost contest and the contest window, a proof reserved while a
sample case is open (with a mutation that opens it early), the entry and
seller conditions, a held entry and the forfeiture wait, a voided
reservation, an unanswered audit value, a later failure voiding a proof, the
pool per account (with a mutation sharing one pool) and the split by value.
