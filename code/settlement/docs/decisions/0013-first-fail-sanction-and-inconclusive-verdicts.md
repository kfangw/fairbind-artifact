# ADR 0013: First-failure sanction and inconclusive verdicts

Status: Accepted 2026-09-22, together with ADR 0011 and ADR 0012. Revises
`fairbind-v1.md` sections 18 and 21.3 and `lifecycle-v1.md` section 8, and adds
a rule the specification currently lacks. Depends on ADR 0012 and cannot be
adopted separately from it. Amended 2026-09-28: ADR 0018 deducts a share of
the bond on every confirmed failure, ADR 0019 rebases `failureLimit`, and ADR
0020 moves the suspension to the confirmed failure unless the profile freezes
at the initial `FAIL` and gates the inconclusive threshold on a minimum judged
count; see the amendment at the end. Amended again 2026-09-28 by ADR 0021:
reinstatement (item 2) is admitted while the claim window is open, and the
terminal sanction (item 4) comes at `n * failureLimit` failures for a window
opened at scale factor `n`.

## Problem 1: one failure ends the business

Version 1 moves a seller from `ACTIVE` to `SANCTIONED` on the first effective
failure claim and charges the reserved seller penalty once
(`fairbind-v1.md` section 21.3, `lifecycle-v1.md` section 8). A `SANCTIONED`
seller cannot accept new settlements, and version 1 gives no way back.

The probability that a compliant seller is wrongly failed on a judged case is
bounded by `(1 - h) + h * alpha`, where `h` is the conditional honest verifier
share and `alpha` the predicate false rejection rate. At the values in play:

| `h` | `alpha` | bound |
| --- | --- | --- |
| 0.9 | 0.01 | 0.109 |
| 0.9 | 0.05 | 0.145 |
| 1.0 | 0.01 | 0.010 |
| 1.0 | 0.05 | 0.050 |

The intended first adopter is a single marketplace or facilitator operator who
is also the verifier, so `h = 1` is the initial operating point and the bound is
`alpha` alone, between 1 and 5 percent. That is far better than 14.5 percent,
and still not survivable, because the bound is per judged case and judged cases
accumulate. A seller judged `n` times is permanently stopped with probability
`1 - (1 - u)^n` for `u = (1 - h) + h * alpha`. At `u = 0.01` that reaches even
odds after about 69 judged cases. With a raw sampling rate of 0.1, a seller at
the top-one-percent boundary of measured peak-hour rates over all 4,400
addresses, 98 settlements per hour, produces roughly ten judged cases per hour
and crosses even odds inside a week. Sellers further up the same distribution —
the peak-hour maximum is 4,201 per hour — cross it in an hour. The sellers this fails first are the ones carrying 92.5 percent of the
settlements. Terminal sanction on a single failure is not deployable at any
`alpha` we can plausibly measure.

## Decision 1: reversible stop now, cumulative threshold for the terminal one

Split what the first failure does from what repeated failure does.

1. First confirmed final failure. The seller enters `SUSPENDED`. New settlements
   stop immediately, and ADR 0012's freeze lands on the whole deferred ledger of
   that seller's bond account. No seller penalty is slashed.
2. Reinstatement. When the claim window of ADR 0012 closes and the bond account
   has been topped back to at least `sellerPenalty`, `reinstateSeller` returns
   the seller to `ACTIVE`. The failure is recorded against the bond account.
3. Overturn. If review overturns the failure, the suspension is lifted with the
   freeze, the failure is not recorded, and no reinstatement conditions apply.
4. Terminal sanction. `SANCTIONED` and the one-time `sellerPenalty` slash apply
   when the count of confirmed final failures recorded against one bond account
   reaches the profile's `failureLimit` within `failureWindowBlocks`.
5. `failureLimit` is chosen from the binomial tail of `u` so that an honest
   seller's annual probability of terminal sanction stays under a profile
   target, using the profile's own `alpha` and `h` and the seller's judged-case
   rate. The profile records the values used. The default is three, and the
   counting window `failureWindowBlocks` is the receipt retention period
   `retentionBlocks`.

The immediate stop is kept, and is kept immediate, because it is what bounds
exposure between detection and enforcement; a deferred stop would let a failing
seller keep selling into a pool that is already frozen, which harms new buyers
without helping anyone. What moves to a threshold is only the irreversible part:
the slash and the permanent end of the business.

This is affordable precisely because of ADR 0012. Admissible profiles satisfy
`deferBlocks >= caseHorizon >= L`, so at the moment of the first confirmed
failure nothing the seller sold in the exposure window has been released. The
freeze reaches all of it. The terminal sanction is therefore no longer carrying
containment work, and delaying it costs no exposure. The suspension, which does
carry containment work, stays immediate.

The honest seller's cost under this decision is a bounded stop plus a bounded
delay to release, both reversible, at probability `u` per judged case. The
unfair terminal outcome now needs `failureLimit` independent wrong verdicts, at
probability roughly `u^failureLimit` for small `u` — at `u = 0.01` and
`failureLimit = 3`, on the order of one in a million per window, which is a
number the design notes can state without qualification.

## Problem 2: inconclusive is currently free

`INCONCLUSIVE` is not failure anywhere in version 1. A terminal `INCONCLUSIVE`
releases the funds (`lifecycle-v1.md` section 4), it applies no seller penalty,
and `fairbind-v1.md` section 10 turns an empty required predicate commitment
into `INCONCLUSIVE` rather than a fault. A seller that can reliably make its
responses unjudgeable — by omitting the configuration disclosure, by choosing
request shapes for which no reference can be evaluated, or by serving at times
when the reference is unavailable — is paid every time and is never failed.
Inducing inconclusive dominates both honest service and outright cheating.

Adding a penalty to `INCONCLUSIVE` is not a fix on its own, because genuine
inconclusive outcomes also occur for reasons the seller does not control:
unavailable randomness, exhausted assignment search, and verifier timeouts all
end a case `INCONCLUSIVE` today, and penalising those would raise the honest
seller's effective `alpha` for reasons that have nothing to do with the seller.

## Decision 2: separate the causes, rate-limit the rest

1. Classify. Only a `FINAL(INCONCLUSIVE)` verdict — a deciding verifier that ran
   the predicate and could not establish either result — is a content
   inconclusive and counts against the seller. The standalone `INCONCLUSIVE`
   case state, reached through unavailable randomness, an exhausted ticket
   search, or the final assignment timeout, is a protocol progress failure and
   counts against nothing. `lifecycle-v1.md` section 4 already distinguishes the
   two states; this decision gives the distinction a consequence.
2. Rate. Each bond account carries a content-inconclusive count and a judged
   case count over `inconclusiveWindowBlocks`. The profile fixes
   `maxInconclusivePpm`.
3. Above threshold. While a seller's content-inconclusive rate exceeds
   `maxInconclusivePpm`, a further `FINAL(INCONCLUSIVE)` is treated as a failure
   for freezing and suspension: it triggers ADR 0012's freeze and the
   `SUSPENDED` transition. It is never treated as a failure for slashing, never
   counts toward `failureLimit`, and never produces a wrong-verdict penalty
   against any verifier. `lifecycle-v1.md` section 9's rule that no wrong-verdict
   penalty applies to an inconclusive final verdict is unchanged.
4. Below threshold. A content inconclusive below the threshold behaves as it
   does today: the case ends without seller failure and the purchase becomes
   releasable.
5. Configuration disclosure. A missing or empty required predicate commitment is
   `FAIL`, not `INCONCLUSIVE`. The seller controls that field, it is committed
   in the signed receipt, and its absence is a checkable protocol violation
   rather than an evaluation that could not be completed. This reverses the last
   sentence of `fairbind-v1.md` section 10.
6. Buyer deposit. A buyer dispute ending in a content inconclusive above the
   threshold returns the dispute deposit to the buyer, as `FAIL` does.

The result is that a seller can neither profit from inconclusive nor be ruined
by it. Driving the rate up costs the seller its ability to sell, through a
reversible suspension, with no slash and no verifier blamed. A seller whose
service is genuinely hard to evaluate stays under the threshold and is unharmed,
and a seller for which the threshold is structurally unreachable belongs on a
different profile or a different predicate.

## Spec sections that change

- `fairbind-v1.md` section 10: empty required commitment becomes `FAIL`.
- `fairbind-v1.md` section 18: the reserved penalty is charged at
  `failureLimit`, not at the first failure.
- `fairbind-v1.md` section 21.3: seller state machine gains `SUSPENDED` and the
  `SUSPENDED -> ACTIVE` reinstatement edge; `ACTIVE -> SANCTIONED` becomes
  `SUSPENDED -> SANCTIONED` on reaching `failureLimit`.
- `fairbind-v1.md` section 21.5: add `reinstateSeller`.
- `fairbind-v1.md` section 22: add invariants that a slash occurs at most once
  per bond account and only at `failureLimit`; that an overturned failure
  leaves no recorded failure and no recorded inconclusive; that a protocol
  progress `INCONCLUSIVE` never changes seller state.
- `lifecycle-v1.md` section 4: the consequence of `FINAL(INCONCLUSIVE)` becomes
  threshold-dependent.
- `lifecycle-v1.md` section 8: the first failure claim suspends rather than
  sanctions and slashes.
- `lifecycle-v1.md` section 9: the buyer dispute deposit follows the
  above-threshold inconclusive to the buyer.
- `profile-v1.md` section 2: add `failureLimit > 0`, `failureWindowBlocks > 0`,
  `0 < maxInconclusivePpm <= PPM`, `inconclusiveWindowBlocks > 0`.
- `profile-v1.md` section 4: record the `alpha`, `h` and judged-case rate used to
  derive `failureLimit`, and the resulting honest-seller terminal-sanction
  probability.
- `predicate-interface-v1.md`: the conditions for the three verdicts must
  distinguish a missing disclosure from an incomplete evaluation.
- `contract-interface-v1.md` sections 2, 3 and 11: `SellerStatus` gains
  `SUSPENDED`, which changes the enum ordering and therefore the ABI;
  `ServiceProfileInput` gains the four new fields inside `parameterHash`; the
  seller view exposes the failure and inconclusive counters.

Tests: reinstatement after a claim window with and without a bond top-up;
failure count reaching `failureLimit` exactly and one short of it; failures
ageing out of `failureWindowBlocks`; an overturned failure leaving no counter
change; a protocol `INCONCLUSIVE` leaving seller state untouched; the
inconclusive rate crossing the threshold on the transition case itself; an
empty commitment producing `FAIL` and reaching the freeze; and a seller
alternating failure and inconclusive to check that neither counter is credited
by the other.

## Amendment 2026-09-28

Read decision 1 and the paragraphs after it with these changes:

- Item 1. "No seller penalty is slashed" is withdrawn. Every counted confirmed
  failure deducts `sellerPenalty / failureLimit` from the bond account, and
  the failure that reaches `failureLimit` deducts the remainder, so one
  window's deductions sum to `sellerPenalty` (ADR 0018). The suspension and
  the freeze land at the confirmed failure under a production profile; only a
  profile with `freezeOnInitialFail`, admitted by the override build, places
  them at the initial `FAIL` (ADR 0020).
- Item 2. Reinstatement still requires the bond back at `sellerPenalty`,
  which after a deduction means a top-up.
- Item 4. The terminal sanction charges the remainder, not the whole
  penalty, and no deduction follows it.
- Item 5. `failureLimit` is derived per settlement over
  `failureWindowBlocks + caseHorizon` with every `PASS` appealed and the
  tiebreak of ADR 0019 in place; the evaluation values are 13 and 20
  (`profile-v1.md` section 4). The default of three is withdrawn.
- "The honest seller's cost under this decision is a bounded stop plus a
  bounded delay to release, both reversible" is withdrawn: a wrongful
  confirmed failure costs the claims on the frozen pool plus one share of the
  penalty (ADR 0012, second amendment). The stop at the initial `FAIL`
  argued for in "The immediate stop is kept" is required only below the case
  horizon; for an admissible profile every purchase settled since the fraud
  began is still held at the confirmed failure (ADR 0020).
- Decision 2, item 3. The above-threshold rule applies only once the window
  holds `minJudgedCount` judged cases (ADR 0020).

## Alternatives considered

Keep immediate terminal sanction on the first failure. Rejected on the numbers
above: at the best plausible operating point it still ends a high-volume honest
seller's business within days.

Move everything to a cumulative threshold, including the stop. Rejected: a
failing seller would keep accepting settlements that are frozen on arrival,
which harms new buyers and adds nothing for anyone else.

Penalise every inconclusive. Rejected: it charges the seller for verifier-set
and randomness failures it does not control and raises the honest seller's
effective rejection rate for structural reasons.

Treat inconclusive as failure only when the buyer disputes. Rejected: sampled
cases are the majority of judgments and the buyer often cannot tell that the
response was unjudgeable, so the rule would be unenforceable exactly where it is
needed.
