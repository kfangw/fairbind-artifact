# ADR 0019: Tiebreak on party review and automatic recheck of an initial INCONCLUSIVE

Status: Accepted 2026-09-28. Revises the review paths of `fairbind-v1.md`
section 17 and `lifecycle-v1.md` sections 4, 7 and 9, the
`judgmentDelayBlocks` bound of `profile-v1.md` section 3, the `failureLimit`
derivation of `profile-v1.md` section 4, and the evaluation profiles'
`failureLimit` (13 and 20) and `judgmentDelayBlocks`. Changes no encoding and
no storage layout; the case record already carries the stages. Erratum
2026-09-28 (ADR 0021): the per-judged-case bound of decision 3 missed the
initial `FAIL` overturned by the party review and confirmed by the tiebreak;
the corrected bound is `u = w1^2 (2 + b_a + (1 - b_a) s_re) = 3 w1^2`
(`wrongFinalFailPpm` 4729), and the limits become 16 and 27 with the hold
periods of ADR 0021.

## Problem 1: one further verifier decides a party review

Under `lifecycle-v1.md` section 4 the party-review path ends at the second
verdict, whatever it is. A buyer that appeals every `PASS` therefore needs one
erring reviewer to turn an honest seller's `PASS` into a confirmed `FAIL`, and
a seller that appeals a correct `FAIL` needs one erring reviewer to escape it.
The automatic path is stricter: a recheck that disagrees goes to a third
verifier. The asymmetry is the wrong way round, because the party path is the
one an adversary can trigger at will. The `failureLimit` derivation of
`profile-v1.md` assumed that only the seller appeals and folded the buyer's
appeal in nowhere.

## Problem 2: an initial INCONCLUSIVE is final on one verifier

An unappealed initial `PASS` is automatically rechecked with probability
`recheckPpm`; an initial `INCONCLUSIVE` is not, and nobody may appeal it. A
verifier that cannot or will not evaluate ends the case on its own verdict.
A seller that induces inconclusives (ADR 0013, problem 2) is stopped only by
the rate limit, and an honest seller whose response one verifier could not
judge gets no second look either.

## Decision 1: tiebreak on party review

A party-review verdict that differs from the initial verdict does not end the
case. It fixes new randomness at the review transaction block plus one and
assigns a third verifier, exactly as a disagreeing automatic recheck does; the
tiebreak verdict is final. A party-review verdict equal to the initial verdict
ends the case as before.

- Appeal deposit. Unchanged rule, new reach: the deposit returns to the
  appellant when the final verdict differs from the initial verdict or is
  `INCONCLUSIVE`, and goes to the opposing party when the final verdict
  confirms the initial one. After a tiebreak that confirms the initial verdict
  the appellant loses.
- Wrong-verdict penalty. On the party path an applicable penalty goes to the
  appellant only when the appellant won, that is, when the final verdict is
  `PASS` or `FAIL` and differs from the initial verdict; otherwise it goes to
  the penalty treasury, as on the automatic path. This keeps
  `lifecycle-v1.md` section 9's "successful appellant" exact now that an
  appellant can lose on the party path with a wrong reviewer in between.
- Case horizon. `caseHorizon` of `profile-v1.md` section 3 already budgets
  three judgment stages of `maxAssignments` attempts each, with a serve
  procedure per attempt, and `scripts/check_spec.py` recomputes it as
  `retention` from the same formula; the party path with a tiebreak uses the
  same three stages as the automatic path, so no bound moves.
  `judgmentDelayBlocks` grows by one review stage. It bounds the delay from a
  bad settlement to the block at which the seller's failure is confirmed and
  new settlements stop, and a `FAIL` can now be confirmed in the tiebreak: an
  initial `FAIL` whose party reviewer errs or colludes in the seller's favour,
  or an initial `PASS` flipped on appeal or recheck. `appealHorizon` of
  `profile-v1.md` section 3 becomes `appealBlocks + 2 * (1 + maxAssignments *
  (judgeBlocks + 1))`, and `L` is 9,380 and 41,412 blocks in the evaluation
  profiles (from 7,576 and 30,608). The open-weights profile raises
  `enforcementBlocks` to 42,000 to keep `enforcementBlocks >= L`; the bond
  floor `g (1 / p + Lambda max(0, L - D))` is unchanged at `D >= L`, and `L`
  stays below `caseHorizon`. The contract, `scripts/check_spec.py` and the
  controller compute the same formula.

## Decision 2: automatic recheck of an initial INCONCLUSIVE

An unappealed initial `INCONCLUSIVE` is treated like an unappealed initial
`PASS`: after the appeal window `openAutoRecheck` (or `finalizeCase`, which
performs the same gate) seals the candidate block and selects a recheck with
probability `recheckPpm`. A recheck verdict equal to the initial verdict is
final; a different one goes to the tiebreak, whose verdict is final. Not
selected, the initial `INCONCLUSIVE` is final as today. No party may appeal an
`INCONCLUSIVE`; that stays.

- Counting. A sampled case still counts once toward the judged and
  inconclusive counters, at its final verdict (ADR 0017).
- Keeper. `openAutoRecheck` is due for an `INITIAL_VERDICT(INCONCLUSIVE)` one
  block after its candidate block, like a `PASS`; `finalizeCase` at the
  candidate block reverts for it with `DeadlineNotReached`.

## Decision 3: failureLimit from a per-settlement bound

The `failureLimit` basis of `profile-v1.md` section 4 is replaced.

- Per judged case. A wrongful confirmed failure against an honest seller needs
  two independently drawn verifiers to err, `u1 = c (1 - h) + h alpha` each,
  on every path: an initial `FAIL` appealed by the seller and confirmed by the
  party reviewer; an initial `PASS` appealed by an adversarial buyer, flipped
  by the party reviewer and confirmed by the tiebreak; an unappealed `PASS`
  rechecked and flipped, then confirmed by the tiebreak. The tiebreak's own
  error is bounded by one. With the buyer appealing every `PASS` (`b_a = 1`)
  the automatic path is reached only when the buyer does not appeal, so per
  judged case `u = u1^2 (1 + pi_v + b_a (1 - pi_v)) = 2 u1^2`, which is
  `0.003152` at the evaluation values.
- Per settlement. Each settlement is judged with probability
  `pi = samplePpm / PPM`, so it becomes a wrongful confirmed failure with
  probability `q = pi u`. Buyer-opened disputes are not counted in the
  settlement bound; an adversarial buyer that disputes instead of appealing
  gets the same two-verifier bound per dispute.
- Settlements per window. A confirmed failure inside one fixed failure window
  `[w, w + W]` can come from a case opened on a settlement up to `caseHorizon`
  blocks before `w`, so the settlements that can contribute are those in
  `[w - caseHorizon, w + W]`, bounded at scale factor one by
  `S = ceil(bucketCapacity + refillPpmPerBlock (W + caseHorizon) / PPM)`:
  5,900 for the data API profile and 13,077 for open weights.
- Limit. `failureLimit` is the least `k` with `C(S, k) q^k <= 10^-6`: 13 and
  20. `scripts/check_spec.py` recomputes the limit, the union bound
  (`5.047e-07`, `8.127e-07`) and the exact binomial tail (`9.080e-08`,
  `1.644e-08`) in rationals. The basis records `buyerAppealsEveryPass`,
  `tiebreakOnPartyReview`, `settlementBasis`, `caseHorizonBlocks`,
  `wrongFinalFailPpm` (3153, the ceiling of `u` in parts per million) and
  the expected number of wrongful confirmed failures per window (1.860 and
  4.122), each of which now costs the honest seller one share of the penalty
  (ADR 0018).

## Alternatives considered

Keep the party review final and raise the appeal deposit. Rejected: a deposit
prices an appeal, it does not make one reviewer less likely to err, and the
seller's loss on a wrongful confirmed failure is not the deposit.

Recheck every initial `INCONCLUSIVE`. Rejected: it doubles the verifier work
on exactly the cases that are hardest to judge; the rate limit of ADR 0013
already bounds how much a seller gains from inconclusives, and the recheck
probability is the same knob the `PASS` path uses.

Let a party appeal an `INCONCLUSIVE`. Rejected: neither party can show that
the verifier was wrong to abstain, and a seller could use the appeal to buy a
second draw on every hard case.

## Properties

- P1: unchanged.
- P2: unchanged in outcome; a party review that disagrees adds one review
  stage, inside `caseHorizon`.
- P3: strengthened. A wrongful confirmed failure needs two erring verifiers on
  every path a buyer can trigger, and the stated bound is per settlement over
  a window that includes the cases opened before it.
- P4: strengthened. An incorrect party-review verdict is no longer final and
  is penalized when the tiebreak overrules it; an initial `INCONCLUSIVE` is
  subject to the same recheck as a `PASS`.

## Regression

`contracts/test/FairBindReviewPaths.t.sol`:

- an appealed initial `FAIL` reviewed `PASS` goes to `TIEBREAK` with new
  randomness and a third, distinct verifier; a tiebreak `FAIL` confirms the
  failure, sends the appeal deposit to the buyer and the party reviewer's
  penalty to the treasury; a tiebreak `PASS` overturns it, returning the
  deposit and the first verifier's penalty to the seller (the old rule ended
  the case at the party verdict);
- an agreeing party review is still final at the second verdict;
- a buyer's appeal flipped to `FAIL` is not final; an `INCONCLUSIVE` tiebreak
  returns the deposit and penalizes nobody;
- an unappealed initial `INCONCLUSIVE` cannot be finalized at the candidate
  block and is rechecked when selected: agreement is final, disagreement goes
  to the tiebreak (the old rule finalized it at the candidate block);
- not selected, it is final through `sealReviewRandomness` and
  `finalizeCase`; an initial `FAIL` never enters the recheck gate.

`services/keeper` plans `openAutoRecheck` for an initial `INCONCLUSIVE`; the
stateful suite's handler rechecks and finalizes `PASS` and `INCONCLUSIVE`
alike and lets a `PARTY_REVIEW` case enter `TIEBREAK`.
