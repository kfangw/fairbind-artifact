# Specification Traceability

This table maps the frozen research design to normative specification sections and future implementation tests. Source section labels refer to the Korean FairBind protocol specification, revision 6, dated 2026-09-04.

| Research source | Requirement | Repository specification | Required verification |
| --- | --- | --- | --- |
| Section 2.0 | Immutable profiles and bonded registration | FairBind Sections 5.1 through 5.3 | Registry unit tests and immutable-profile invariant |
| Sections 2.1 through 2.3 | Request normalization, `keyId`, and derived nonce | FairBind Sections 6 through 8 | Cross-language test vectors and idempotency property tests |
| Section 2.4 | Atomic settlement checks, token bucket, and deferred funds | FairBind Sections 9, 18, and 19 | Contract unit, fuzz, and invariant tests |
| Section 2.5 | Seller-signed response receipt | FairBind Section 10 | EIP-712 vectors and body-hash boundary tests |
| Sections 2.6 and 2.7 | Epoch anchor and ledger-nonce sampling | FairBind Sections 11 and 12 | Omission, equivocation, and sampling tests |
| Sections 2.7 and 2.9 | Bond-weighted verifier assignment and judgment | FairBind Sections 13 and 15; Sortition Sections 1 through 5 | Snapshot, exclusion, liability, interval, and timeout tests |
| Sections 2.5 and 2.9 | Service-class commitments and reproducible verdict evidence | Predicate Interface Sections 1 through 6 | Commitment vectors, schema validation, replay, and three-verdict tests |
| Section 2.8 | Off-chain redelivery with on-chain publication fallback | FairBind Section 14 | Missing delivery and chunked publication tests |
| Section 2.10 | Buyer disputes | FairBind Section 16 | Claim deadline and deposit accounting tests |
| Section 2.11 | Exclusive appeal or automatic recheck | FairBind Section 17 | State-machine invariant and three-verifier tests |
| Section 2.12 | Public timeout transitions | FairBind Section 20 | Bounded-liveness state exploration |
| Sections 3 and 4 | State and invariants | FairBind Sections 5, 9, 11 through 20 | Storage layout review and invariant suite |
| Section 5 | Gas measurement | Implementation plan, milestone M5 | Gas snapshots by call and transaction path |

## Property obligations

| Property | Specification dependencies | Required evidence |
| --- | --- | --- |
| P1, payment at most once | Identifier derivation, token nonce use, atomic settlement | Collision argument, contract invariants, retry and restart fault tests |
| P2, delivery or refund | Deferred funds, buyer-initiated redelivery, publication fallback, public timeouts | State-machine argument, insufficient-delivery tests, bounded-block trace |
| P3, honest seller protection | Predicate false rejection rate, independent assignment, appeal path | Probability bound, calibrated predicate results, adversarial verifier simulation |
| P4, verifier accountability | Deadlines, evidence hash, reassignment, appeal, automatic recheck | Deterministic timeout tests and measured content-verdict outcomes |

The exposure theorem also depends on measured effective detection probability, settlement rate, enforcement delay, and per-purchase illicit gain. The deployment profile must record the values used to set the token bucket and reserved seller penalty.

## Accepted-decision review

| Decision | P1 | P2 | P3 | P4 |
| --- | --- | --- | --- | --- |
| ADR 0004, exact encodings and bounded profiles | Exact typed identifiers remove cross-language ambiguity. | Exact body boundaries and response limits keep publication finite. | Purchase and verifier-exposure caps make the stated loss bound checkable. | Typed verdicts, evidence hashes, and assignment domains prevent cross-case reuse. |
| ADR 0005, non-upgradeable governance | A deployment cannot rewrite identifier or token rules. | Pause cannot block delivery, refund, release, or timeout calls. | An administrator cannot change a live case or fund destination. | An administrator cannot replace assignments, verdicts, evidence, or deadlines. |
| ADR 0011, bond-keyed rate cap | Unchanged: settlement still consumes one identifier pair per purchase; only the bucket owner moves to the bond account. | Unchanged delivery paths; `settle` additionally requires an active, unfrozen bond account. | Splitting a service across registrations under one bond gains no rate; the exposure bound is per unit of capital. | Unchanged. |
| ADR 0012, freeze on first final failure | Unchanged. | Strengthened: after a final failure every buyer of an unreleased entry of the bond account can recover its amount with its receipt, not only the judged buyer; a freeze always ends by overturn or forfeiture. | An overturned initial `FAIL` costs an honest seller at most release delay: an overturn releases exactly the frozen entries. A wrongful confirmed failure costs it the claims on the frozen pool plus one share of the penalty (ADR 0018), at the per-judged-case probability `u` of `profile-v1.md` section 4. | Unchanged; forfeiture funds the verifier reward pool but changes no verdict rule. |
| ADR 0013, suspension and inconclusive counting | Unchanged. | Unchanged fund rules; a sampled case no longer ends releasable when every verifier times out before the seller served. | The irreversible slash needs `failureLimit` final failures in a window; a protocol `INCONCLUSIVE` never counts against the seller. | No wrong-verdict penalty for any `FINAL(INCONCLUSIVE)`, above or below the threshold. |
| ADR 0017, inconclusive rate counts sampled cases only | Unchanged. | Unchanged fund routing; a disputed `FINAL(INCONCLUSIVE)` ends without seller failure at any rate. | Strengthened: neither a seller padding the judged count with self-disputes nor a buyer choosing which responses to dispute can move the inconclusive rate. | Unchanged. |
| ADR 0016, settle pulls with `receiveWithAuthorization` | Strengthened: a FairBind authorization moves funds only in the `settle` that records its purchase, so no payment exists without a purchase record. | Strengthened: funds can no longer be stranded in the contract outside every delivery and refund path. | Unchanged. | Unchanged. |
| ADR 0015, freeze held while any initial FAIL is pending | Unchanged. | Strengthened: no settlement enters and no held entry is released under a bond account while any of its initial `FAIL` verdicts is undecided, whatever the order of decisions (under `freezeOnInitialFail`, ADR 0020). | Unchanged loss: an overturn still releases every held entry and forfeits nothing; the release waits for the last pending trigger. | Unchanged. |
| ADR 0018, per-failure bond deduction | Unchanged. | Unchanged: the bond is not a refund source; refunds and claims still come from the deferred ledger. | The bound gains a monetary term: a wrongful confirmed failure costs `sellerPenalty / failureLimit` plus the frozen-pool claims, at probability `u` per judged case; the deductions of one window never exceed `sellerPenalty`. | Unchanged. |
| ADR 0019, tiebreak on party review and recheck of an initial INCONCLUSIVE | Unchanged. | Unchanged in outcome; a disagreeing party review adds one review stage inside `caseHorizon`, and `judgmentDelayBlocks` budgets it. | Strengthened: a wrongful confirmed failure needs two erring verifiers on every path a buyer can trigger, and `failureLimit` is bounded per settlement over `failureWindowBlocks + caseHorizon` with every `PASS` appealed. | Strengthened: an incorrect party-review verdict is not final and is penalized when the tiebreak overrules it; an initial `INCONCLUSIVE` is rechecked like a `PASS`. |
| ADR 0020, freeze timing as a profile parameter and minimum judged count | Unchanged. | Unchanged for admissible profiles: every purchase settled since the fraud began is still held at the confirmed failure, so the frozen window covers the same purchases under either timing; below `caseHorizon` the override build requires the early freeze. | Strengthened: under a production profile an honest seller is stopped only by a confirmed failure (probability `u`, not `u1`), and the inconclusive freeze rests on at least `minJudgedCount` sampled judgments. | Unchanged. |
| ADR 0021, failure threshold scaled with the bond, re-entry during the claim window, reopened review seal | Unchanged: no identifier, signature or encoding changes. | Preserved with re-entry: a confirmed failure during an open claim window moves `freezeBlock` to its block, so every purchase settled since the fraud began, including those settled after a reinstatement, is frozen and claimable once; the forfeiture takes only the frozen window; an overturned initial `FAIL` neither unfreezes the confirmed window nor makes a later entry claimable; an exiting seller cannot leave while its pool is open. Strengthened on reviews: one missed seal no longer ends a case. | Strengthened: the per-window sanction probability no longer grows with the bond (`n * failureLimit` at scale `n`); a wrongly failed seller re-enters after a top-up instead of after the claim window; the stated bound counts every path to a wrongful confirmed failure (`u = 3 w1^2`, erratum to ADR 0019). | Strengthened: an appealing seller cannot escape a correct `FAIL` through one missed review seal. |
| ADR 0022, highest recent window scale, owner-only top-up, locked forfeiture | Unchanged: no identifier, signature, encoding or profile field changes. | Unchanged: the exposure bound and the frozen-pool claims use neither the threshold nor the forfeiture destination; the seller still receives nothing of a forfeiture. | Strengthened: a window that opens within `retentionBlocks` of a deduction, or receives a top-up, has the threshold of the highest scale whose settlements it can fail, so the per-window bound holds without an operating condition; nobody but the owner can change the scale. | Unchanged: every confirmed failure still deducts its share; no party receives the deductions or forfeitures, so no verifier or treasury gains from a failure. |
| ADR 0023, verifier-count margin | Unchanged: no identifier, signature or encoding changes; only the evaluation profiles' `parameterHash` moves with `minVerifiers`. | Strengthened: a sampled case that reaches its last assignment ends as a protocol `INCONCLUSIVE`, releasing the purchase to the seller, with probability at most `10^-3` instead of 0.35 at the evaluation values with equal weights. | Unchanged: assignments stay independent weighted draws that exclude earlier participants. | Strengthened: fewer cases end without a verdict for lack of an eligible verifier. |
| ADR 0024, value-proportional sampling and four case rules | Unchanged: no identifier or encoding changes; a purchase under a profile with terms records its sampling rate at settlement. | Strengthened: a sampled purchase whose non-delivery dispute ended as delivered is judged before release; a sample case whose receipt is not on chain in time ends `UNSERVED` and refundable instead of releasable; the case horizon now bounds every enumerated case path. Not met: an anchored epoch past its seal deadline is still refunded before its randomness exists. | Mixed: under a profile with terms an honest seller is sampled up to every purchase at the cap, so `k_S` assumes all settlements sampled; a stalled seller appeal now confirms a wrongful initial `FAIL` (the term `u_106` of the design 2 analysis, unmeasured). | Strengthened: a seller cannot buy a party `PASS` and let the tiebreak lapse; a stalled seller appeal charges no reviewer a wrong-verdict penalty. |
| ADR 0025, checkpoint-time eligibility, fixed review reseal, committed terms | Unchanged: no identifier changes; one new commitment, `termsHash`, of profile terms that ADR 0024 added. | Strengthened: a late sample verdict ends the case `UNSERVED` in the same call instead of racing `finalizeCase`; the keeper calls `timeoutSampleReceipt`; terms can no longer break a confirmed failure of an account opened without them. | Mixed: a full honest verifier is now assigned and may time out (late penalty, next candidate) instead of being skipped; P3 for sellers is unchanged. | Strengthened: the first assignment of a case follows the checkpoint table whatever cases the seller opens after the checkpoint, and a reopened review seal draws the same verifier; locked liability may exceed a verifier's current limit, and a penalty takes at most the remaining bond. |
| ADR 0026, the anchor carries the receipt list | Unchanged: no identifier or tree encoding changes; `anchor` takes the `(nonce, receiptLeaf)` pairs in strictly ascending nonce order in place of the root, `proveOmission` takes a nonce and two list entries, and `proveMisanchoredReceipt` is new. | Strengthened: omission of any real purchase is provable by anyone from the public list; a substituted receipt at the buyer's own nonce is provable only by that buyer (needs its signed receipt). Not met: an epoch above 11,742 entries (30,000,000 gas) or 6,562 entries (16,777,216 gas) cannot be anchored in one transaction. | Unchanged: an honest seller already published the list; it now pays its call data gas, and its sorted list admits no omission or misanchored-receipt proof. | Unchanged. |
| ADR 0027, sanction limit apart from the unit bond | Unchanged identifiers; `SalesTier` gains `sanctionLimit`, so `termsHash` and the design 2 `parameterHash` values move. | Unchanged for `sanctionLimit = failureLimit` (the k * b configuration); with `failureLimit = 1, sanctionLimit = 0` (B = b, decision 131) a failure deducts b and suspends, and a deposit of b reopens the account without a terminal sanction. | Strengthened under B = b: an honest seller needs one b and is never sanctioned for good. | Unchanged. |
| ADR 0028, an exhausted first assignment waits for the next checkpoint | Unchanged: no identifier or encoding changes; `CaseState` gains `WAITING_ASSIGNMENT` at the end. | Mixed: a sampled purchase whose first search is exhausted is held until a redraw judges it instead of becoming releasable after a keeper publication; a profile whose verifiers stay full holds such purchases without a bound (assumption A4). | Mixed: an honest seller's sampled purchase may wait for a verifier with room, and the receipt deadline still runs while it waits. | Strengthened: a full checkpoint no longer turns a drawn sample into an unjudged `INCONCLUSIVE`, and the redraw value is fixed after the checkpoint it uses, which later checkpoints cannot replace. |
| ADR 0029, an anchored epoch waits for its value; a waiting case stops the release clock | Unchanged: no identifier, purchase field or encoding changes; two views, two events and two appended mappings. | Strengthened: an anchored epoch is no longer refunded before its value, so a seller cannot void the epochs whose sample it dislikes, and an entry of an account with a waiting case is not released before `deferBlocks` unpaused blocks, so a long wait cannot release later sales before the freeze. Mixed: if no keeper delivers the value while the chain serves the block hash, the epoch's purchases stay held for good (design 2 open question U9). | Mixed: an honest seller's releases, recent-cap expiry and bond exit wait while any of its cases waits, including waits caused by other sellers' or third parties' load; nothing is counted against it. | Unchanged. |

## Conformance artifacts

The release candidate includes these normative machine-readable artifacts:

- byte-level request canonicalization vectors in `canonicalization-v1.json`;
- identifier, EIP-712, authorization, and selection vectors in
  `cryptography-v1.json`;
- sorted Merkle tree, inclusion, and omission vectors in `merkle-v1.json`;
- predicate commitment and evidence vectors in `predicate-v1.json`;
- x402 version 2 decoded messages and exact header bytes under `x402-v2/`;
- wire, evidence, and service-profile JSON Schemas under `schemas/`.

`scripts/check_spec.py` recomputes these hashes, encodings, deadlines, profile
inequalities, echo constraints, and HTTP headers. M1 adds independent Go and
Solidity consumers rather than replacing the language-neutral checker.

## ADR 0006 conformance review

Initial pre-seal disputes use the sealed epoch hash when assignment starts.
P1 identifiers and P2 fund and delivery rules are unchanged. P3 and P4 require
non-predictable initial assignments; using zero after sealing violated that
precondition. The regression covers initial assignment only, not later review
stages or the full probabilistic bounds.

## ADR 0007: Fixed module packaging

All previous runtime methods retain their encodings at the router. P1 depends on
preserved router-domain identifiers, shared storage and a common reentrancy lock.
P2 depends on unchanged custody and refund/release transitions. P3 and P4 are not
strengthened by the split; their liability and conditional-error assumptions remain
unresolved. The module regression suite and ABI/storage comparison are required
packaging evidence. Constructor and module getters are deployment changes, not
changes to purchase semantics.

## ADR 0008: approved liability and recovery repair

- P1: existing identifiers, rollback, ABI and original storage-prefix regression.
- P2: active-case buyer recovery, exact deadlines, publication and single refund.
- P3: separate dispute deposits, unchanged publication proof and payout priority.
- P4: effective-bond admission; preserved judgment during recovery; liability
  cancellation on seller failure without a fabricated verifier-fault finding.

## ADR 0009 review

P1 retains all existing purchase/authorization vectors and rollback tests. P2 extends concurrent delivery and cancellation tests through review and all retained liabilities. P3 requires evidence-edge renewed appeal, timeout replacement and mutually exclusive party/automatic paths. P4 requires signature replay rejection, no-repeat bounded assignment, penalties with simultaneous liabilities, conclusive-only wrong penalties and failure-to-progress INCONCLUSIVE. Conditional proof assumptions remain explicit; regression success does not establish empirical honest share or predicate error bounds.

## ADRs 0011 to 0013: bond accounts, freeze, suspension

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Bond account owns bucket, penalty, counters, freeze | FairBind 5.2, 5.4, 19; Contract Interface 6, 11 | `FairBindBond` (`registerBond`, `topUpBond`, `registerSeller`), `FairBindSettlement.settle`, `FairBindCore._rescale` | `FairBindBond.t.sol`: shared bucket across two and three registrations, inherited bucket, scale factor on top-up and slash |
| Freeze of every unreleased entry of the bond account | FairBind 18, 21.1, 21.3; Lifecycle 3, 9 | `FairBindCore._freeze`, `_frozen`, `FairBindRecovery.releasePurchase` | `FairBindBond.t.sol`: freeze across registrations and not across bonds; `ReproC` C1 |
| Overturn releases exactly the frozen set | FairBind 18, invariant 21 | `FairBindCore._releaseTrigger`, `FairBindBond.releaseFrozen` | `FairBindBond.t.sol`: overturn on party review; `FairBindM4.t.sol` seller appeal |
| Receipt claims, window, double claim | FairBind 18, invariants 19 and 20; Contract Interface 10 | `FairBindBond.claimRefund(nonce, receipt, signature, proof)` | `FairBindBond.t.sol`: claim, double claim, wrong receipt, claim after the window |
| Forfeiture split, never to seller | FairBind 18, invariant 22; Lifecycle 9 | `FairBindBond.forfeitUnclaimed`, `FairBindCore._splitForfeit` | `FairBindBond.t.sol` forfeiture split; `invariant/FreezeConservation.t.sol` |
| Suspension, reinstatement, failure limit | FairBind 18, 21.3, invariant 25 | `FairBindCore._confirmFailure`, `FairBindBond.reinstateSeller` | `FairBindBond.t.sol`: limit reached exactly, one short, ageing out, reinstatement conditions |
| Inconclusive counting and threshold | FairBind 18, invariant 26; Lifecycle 4 | `FairBindCore._recordJudged`, `_protocolInconclusive` | `FairBindBond.t.sol`: above-threshold freeze without count, protocol inconclusive unchanged, idle verifier keeper path |
| Empty predicate commitment is FAIL | FairBind 10 | `FairBindJudgment.judge` | `FairBindBond.t.sol` empty-commitment test |
| Unopened sample never released | FairBind 12, 18, invariant 27 | `FairBindRecovery.releasePurchase`, `FairBindSampling.openSample` | `FairBindBond.t.sol` unopened-sample test |
| Beacon delay and fixed deadline before beacon | FairBind 12; Lifecycle 1; Sortition 3 | `FairBindSampling.anchor`, `seal` | `ReproD` D1; `FairBindBond.t.sol` beacon ordering |
| `beaconDelayBlocks >= 768` (128 L1 blocks) | FairBind 12; Profile 2 | `FairBindCore._validateProfile` (`MIN_BEACON_DELAY_BLOCKS`) | `FairBindBond.t.sol` admission test; `scripts/check_spec.py`; `experiments/controller/profile.py` admissibility |
| `enforcementBlocks >= judgmentDelayBlocks` | Profile 2, 3 | `FairBindCore._validateProfile`, `_judgmentDelay` | `ReproC` C2; `scripts/check_spec.py` |
| Admission override only in a test build | Profile 2 | `FairBindCore._admissionOverride` (overridden only in `contracts/test/AdmissionOverrideRegistry.sol`) | `AdmissionOverride.t.sol`: production rejects, override build accepts, other rules kept |
| Keeper serve request goes straight to publication | ADR 0014; FairBind 21.1; Lifecycle 4 | `FairBindCore._protocolInconclusive`, `_completeDelivery`; `FairBindPublication`; `FairBindDelivery.timeoutServe` | `FairBindBond.t.sol`: keeper case enters `PUBLISHING`, publication ends protocol `INCONCLUSIVE` without counters, timeout ends `UNSERVED`, `served` with an arbitrary hash reverts |
| Freeze held while any initial FAIL is pending | ADR 0015; FairBind 18, 21.3, invariant 28; Lifecycle 3, 10 | `FairBindCore._freezePending`, `_dropTrigger`, `_releaseTrigger`, `_confirmFailure`; `FairBindSettlement.settle`; `FairBindBond.releaseFrozen`, `reinstateSeller`; `FairBind.getFreezeTriggers` | `FairBindBond.t.sol`: first of two triggers overturned keeps the freeze and the suspension, both overturned release and reactivate, second confirmed failure extends the open claim window, a trigger pending past the claim window blocks reinstatement and sibling settlement; `invariant/LifecycleObserver.sol` pending-trigger model |
| Seller redelivery endpoints: claims document hashes to `claimsHash`; serve authorization status codes | FairBind 14; x402 binding 13; Cryptography 6; Predicate interface 1 | Off chain: `services/seller/serve.go` (`handleClaims`, `handleServe`, `checkServeAuth`), `services/seller/seller.go` (claims hash checked at start), `services/verifier/seller.go` (`Redeliver` fetches the claims), `runtime/verifier/gate.go` (`claims_binding`, claims byte bound) | `services/seller/seller_test.go` serve tests: claims body hashes to the purchase's `claimsHash`, malformed header and invalid nonce `400`, stranger and corrupted signature `401`, unknown nonce `404`; `runtime/verifier/gate_test.go` claims mismatch and claims-limit cases; `services/verifier/adapters_test.go` redelivery fetches the claims |
| Pre-freeze rule stays reproducible | ADR 0012 | `FairBindCore._freezeEnabled` (overridden only in `invariant/FreezeDisabled.sol`) | `ReproC` C1 pre-freeze rule; `invariant/FreezeConservation.t.sol` mutation test |

P1 is unchanged by all three decisions. P2 gains the frozen-pool claim path and
the keeper serve fallback for sampled cases. P3 changes from "one wrong final
failure ends the business" to "one wrong failure costs a bounded, reversible
delay; the slash needs `failureLimit` failures". P4 is unchanged: no verdict,
assignment, or penalty rule depends on the freeze.

## ADR 0014: keeper serve goes straight to publication

P1 is unchanged: no identifier, signature, or encoding changes. P2 is
strengthened on the keeper path: the committed response either becomes public
and verified against the seller-signed receipt on chain, or the purchase
becomes refundable through `UNSERVED`, within `serveBlocks`; a seller can no
longer end the case with an unchecked bundle hash. P3 is unchanged for honest
sellers, who can publish the response they signed. P4 is unchanged: no verdict,
assignment, or verifier penalty depends on this path. The regression tests
distinguish the old behaviour (`served` with any hash accepted, case ends
protocol `INCONCLUSIVE`) from the new one (`served` reverts; only publication
or `UNSERVED` ends the case).

## ADR 0015: pending freeze triggers

P1 is unchanged. P2 is strengthened: the freeze of a bond account and the
refusal of new settlements hold until every case of the account that received
an initial `FAIL` has ended, so the overturn of one trigger no longer reopens
the account while another failure is undecided. P3 keeps its loss statement;
only the release time can move to the decision of the last pending trigger,
which the appeal horizon bounds. P4 is unchanged. The regression tests
distinguish the old behaviour (the first overturn released the freeze and
reactivated the seller) from the new one (the freeze re-anchors to the pending
trigger and the seller stays suspended).

## ADR 0016: settle pulls with receiveWithAuthorization

| Requirement | Specification | Implementation | Verification |
| --- | --- | --- | --- |
| Token call is `receiveWithAuthorization`, caller is the payee | FairBind 4, 9, invariant 29; Contract Interface 7 | `FairBindCore._receiveWithAuthorization`, `IFairBindToken`; `FairBindSettlement.settle` | `FairBindM1.t.sol` `testStrandedAuthorizationCannotBeSpentOutsideSettle` |
| Buyer signs `ReceiveWithAuthorization` | Cryptography 2; x402 binding 1, 5 | `services/internal/x402/eip712.go` (`ReceiveDigest`), `services/buyer`, `services/facilitator`, `services/internal/x402/chain/fake.go`, `testworld` | `test-vectors/cryptography-v1.json` `paymentAuthorization`; `scripts/check_spec.py`; `services/internal/x402/x402_test.go` (receive recovers, transfer does not) |
| Old transfer-typed wire refused and shown strandable | ADR 0016 | `contracts/test/MockEIP3009Token.sol` (both functions, `msg.sender == to` on receive) | `FairBindM1.t.sol` `testTransferTypedAuthorizationIsStrandableAndRejectedBySettle`; `ReproA` A1 keeps the stock transfer to the seller wallet |

P1 is strengthened: before, an authorization could move the buyer's funds
into the contract without a purchase record; now every token movement under a
FairBind authorization is the effect of one recorded `settle`. P2 is
strengthened because stranded funds had no delivery or refund path. P3 and P4
are unchanged. The regression tests distinguish the old behaviour (a
transfer-typed authorization is executable by any holder and leaves no record)
from the new one (a direct token call with the FairBind authorization reverts
and the authorization remains usable by `settle`).

## ADR 0017: inconclusive rate counts sampled cases only

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Judged and inconclusive counts take only sampled cases | FairBind 18, invariant 30; Lifecycle 4 | `FairBindCore._recordJudged` (returns unless the case trigger is `SAMPLE`) | `FairBindBond.t.sol` `test_disputedPassDoesNotEnterTheJudgedCount`, `test_disputedInconclusiveNeitherCountsNorFreezes`; `invariant/LifecycleObserver.sol` counter model replays sampled cases only |

P1 and P4 are unchanged. P2 keeps every fund rule; only the set of cases that
can reach the above-threshold freeze narrows to sampled ones. P3 is
strengthened: the rate that can suspend an honest seller is measured on
randomly selected purchases, so no party can steer it. The regression tests
distinguish the old behaviour (a disputed `FINAL(PASS)` incremented
`judgedCount`; a disputed `FINAL(INCONCLUSIVE)` counted and could freeze) from
the new one (neither changes a counter or freezes).

## ADR 0021: scaled failure threshold, re-entry during the claim window, reopened review seal

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Failure window threshold `n * failureLimit` at the scale it opened | FairBind 18, 21.3, invariants 11 and 25; Lifecycle 9; Profile 4; Contract Interface 11, 12 | `FairBindCore._confirmFailure` (`failureWindowScale`); `FairBind.getFailureWindowScale` | `FairBindReentry.t.sol` `test_scaleOneWindowKeepsTheProfileLimit`, `test_scaleThreeWindowSanctionsAtThreeTimesTheLimit`; `invariant/LifecycleObserver.sol` window-scale model |
| Reinstatement during an open claim window; later settlements outside the window | FairBind 18, 21.3; Lifecycle 3, 10; Contract Interface 6, 7, 11 | `FairBindBond.reinstateSeller`; `FairBindSettlement.settle`; `FairBindCore._setFinancialState` (`claimReentries`); `FairBindBond.forfeitUnclaimed`, `claimRefund`; `FairBind.getFrozenPool`, `getClaimReentry` | `FairBindReentry.t.sol` `test_reinstatementDuringTheClaimWindowReopensTheAccount`; `invariant/LifecycleObserver.sol` late-entry totals and window-only pool |
| A confirmed failure during the window moves `freezeBlock` | FairBind 18, 21.3, invariants 34 and 35; Lifecycle 3 | `FairBindCore._freeze` (`_moveFreezeInClaimWindow`) | `FairBindReentry.t.sol` `test_secondFailureAfterReentryMovesTheFrozenWindow`, `test_confirmedInitialFailAfterReentryMovesTheWindow`; `FairBindBond.t.sol` `test_secondConfirmedFailureExtendsTheOpenClaimWindow`; `invariant/ReentryMutation.sol` mutation rejected by `run.sh` |
| A pending initial `FAIL` holds every entry; its overturn leaves the confirmed window | FairBind 18, invariant 28; Lifecycle 3 | `FairBindCore._frozen`, `_freezePending` | `FairBindReentry.t.sol` `test_overturnedInitialFailAfterReentryLeavesTheConfirmedWindow` |
| Review seal reopens once per stage | FairBind 17, invariant 36; Lifecycle 4, 7; Profile 3; Contract Interface 9, 12 | `FairBindCore._sealReview` (`reviewReseals`); `FairBindReview.finalizeCase`; `FairBind.getReviewReseals` | `FairBindReentry.t.sol` review-seal tests; `FairBindM4.t.sol` `testMissingReviewHashEndsInconclusiveAndReturnsAppealDeposit`, `testExpiredAutoCandidateCannotSkipSelectedReview`; `invariant/LifecycleHandler.sol` reseal checks |
| Exit waits for the frozen pool | FairBind 18, 21.3, invariant 37; Contract Interface 6 | `FairBindBond.finalizeSellerExit` | `FairBindReentry.t.sol` exit tests under both freeze timings |
| Corrected `u`, horizons and limits | Profile 3, 4 | `FairBindCore._validateProfile` (seal term) | `scripts/check_spec.py` (`wrongful_final_fail_model`, `retention`); `experiments/controller/profile.py` `case_horizon` |

P1 is unchanged. P2 holds with re-entry by the exposure argument of ADR 0021:
every purchase settled after a reinstatement is settled after the old freeze
block and before the next confirmed failure, which moves the freeze block over
it before its release block (`D >= L`); without that move (the re-entry
mutation build) the stateful suite finds such a purchase released to the
failing seller. P3 is strengthened for large and for wrongly failed sellers,
and its stated bound is corrected. P4 is strengthened on the review path. The
regression tests distinguish the old behaviour (sanction at `failureLimit`
whatever the scale; reinstatement and settlement refused during the claim
window; the second confirmed failure keeping the first freeze block; a missed
review seal ending the case; exit with the pool open) from the new one.

## ADR 0022: highest recent window scale, owner-only top-up, locked forfeiture

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Window scale read before the opening deduction | FairBind 18, invariant 11; Lifecycle 9; Profile 4; Contract Interface 11 | `FairBindCore._confirmFailure` | `FairBindReentry.t.sol` `test_aRecentDropKeepsTheHigherThreshold` (recorded scale two, live scale one) |
| Window opens at the recent scale high within `retentionBlocks` | FairBind 5.4, 18, invariant 11; Lifecycle 9; Profile 4; Contract Interface 11 | `FairBindCore._rescale` (`recentScaleHigh`), `_confirmFailure`; `FairBind.getRecentScaleHigh` | `FairBindReentry.t.sol` `test_aRecentDropKeepsTheHigherThreshold`, `test_aDropOlderThanTheHorizonGivesTheLiveScale`; `invariant/LifecycleObserver.sol` scale-high model |
| A top-up during an open window raises its scale | FairBind 18; Contract Interface 9, 11 | `FairBindBond.topUpBond` | `FairBindReentry.t.sol` `test_topUpDuringTheWindowRaisesTheThreshold`; `invariant/LifecycleObserver.sol` top-up raise |
| Only the owner tops up | FairBind 5.4, 21.3; Contract Interface 9 | `FairBindBond.topUpBond` | `FairBindReentry.t.sol` `test_topUpByANonOwnerIsRefused` |
| Forfeitures and deductions locked in the contract | FairBind 18, invariant 22; Lifecycle 2, 9; Contract Interface 1, 9, 11, 12; Governance 2 | `FairBindCore._lockForfeit`, `_confirmFailure` (`lockedForfeit`); `FairBind.getLockedForfeit` | `FairBindBond.t.sol`, `FairBindFailureCosts.t.sol`, `FairBindReviewPaths.t.sol`, `repro/ReproC_DeferralPolicyA.t.sol`, `invariant/FreezeConservation.t.sol`; `invariant/LifecycleObserver.sol` locked-total model and custody check; `services/internal/integration/paths_test.go` `TestNonDeliveryUnservedRefundAndForfeit` |

P1 is unchanged. P2 is unchanged: the exposure argument of ADR 0021 uses
neither the threshold nor the destination of a forfeiture. P3 is strengthened:
the honest-seller bound of `profile-v1.md` section 4 now covers a window that
opens after a recent deduction or receives a top-up, and a third party can no
longer move an account's scale. P4 is unchanged: every confirmed failure still
deducts its share and nothing of a forfeiture returns to the seller. The
regression tests distinguish the old behaviour (a window opening at the live
scale after a drop; a top-up leaving the threshold; anyone topping up; the
remainder split to the reward pool and the treasury, the shares sent to the
treasury) from the new one.

## ADR 0023: verifier-count margin

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| `minVerifiers >= 3 * maxAssignments + 5` at profile creation | Profile 2, 5.1; FairBind 13; Sortition 4 | `FairBindCore._validateProfile` (`VERIFIER_COUNT_MARGIN`) | `VerifierCountAdmission.t.sol` `testAdmitsExactlyThreeTimesMaxAssignmentsPlusMargin`, `testRejectsOneBelowTheMargin`, `testRejectsTheFormerBound`; `scripts/check_spec.py`; `experiments/controller/profile.py` |
| Registration, settlement and seal need `minVerifiers` checkpoint entries | FairBind 13; Sortition 1, 3 | `FairBindBond.registerSeller`, `FairBindSettlement.settle` (`_profileAvailable`), `FairBindSampling.seal` | `VerifierCountAdmission.t.sol` `testSellerRegistrationNeedsMinVerifiers`, `testSettlementStopsWhenTheSetFallsBelowMinVerifiers`, `testSealNeedsMinVerifiersInTheEpochCheckpoint`, `testSealAndAssignAtExactlyMinVerifiers` |
| Margin derivation | Profile 5.1 | none | `experiments/verifier_count.py` |

P1 is unchanged. P2 is strengthened: a sampled case that exhausts its
assignment search ends as a protocol `INCONCLUSIVE` and releases the purchase,
and the margin bounds the probability of that at the last of `3 *
maxAssignments` assignments by `10^-3` for equal-weight sets. P3 is unchanged:
the draws and the exclusion rule are the same. P4 is strengthened for the same
reason as P2. The regression test `testRejectsTheFormerBound` distinguishes
the old admission (nine verifiers for three assignments per stage) from the
new one.

## ADR 0024: value-proportional sampling and four case rules

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Longest case path and horizon | Profile 3; Lifecycle (ADR 0024) | `FairBindCore._judgmentDelay`, `_validateProfile`; `FairBind.judgmentDelayBlocks` | `WorstPathLength.t.sol` `test_longestPath_dataApi` (30,573), `test_longestPath_openWeights` (92,081); `scripts/check_spec.py`; `experiments/controller/profile.py` |
| Delivered dispute opens its sample case | FairBind (ADR 0024) 2; Lifecycle (ADR 0024) | `FairBindSampling.openSample`, `FairBindRecovery.releasePurchase`; keeper `planPurchase` | `Design2Rules.t.sol` `test_sampledPurchaseWhoseDisputeEndedDeliveredOpensItsSampleCase`, `test_deliveredDisputeWithOpenBuyerRecoveryStillOpensTheSampleCase`, `test_unsampledDeliveredPurchaseIsReleased` |
| Stalled seller appeal upholds the initial FAIL | FairBind (ADR 0024) 3 | `FairBindCore._finishReview` | `Design2Rules.t.sol` `test_sellerAppealedReviewThatTimesOutUpholdsTheInitialFail`, `test_stalledTiebreakAfterSellerAppealUpholdsTheInitialFail`, `test_sellerAppealedReviewWhoseSealLapsesTwiceUpholdsTheInitialFail`, `test_buyerAppealedReviewThatStallsStaysInconclusive`, `test_stalledAutomaticRecheckStaysInconclusive` |
| Sample receipt on chain in time | FairBind (ADR 0024) 4 | `FairBindSettlement.submitSampleReceipt`, `timeoutSampleReceipt`; `FairBindSampling.openSample`; `FairBindJudgment.judge` | `Design2Rules.t.sol` `test_sampleCaseWithoutItsReceiptOnChainInTimeIsUnserved`, `test_receiptPostedInTimeEndsTheReceiptDeadline`, `test_receiptAfterItsDeadlineIsRefused`, `test_verdictBeforeTheDeadlinePostsTheReceipt`, `test_omittedReceiptDrawnForSamplingEndsUnserved` |
| Value cap, proportional rate, rounded-up threshold | FairBind (ADR 0024) 1; Profile 9; cryptography vector `selection.valueProportional` | `FairBindDesign2`, `FairBindSettlement.settle`, `FairBindCore._sampleStatus` | `Design2Terms.t.sol` `test_integerRulesMatchTheReplayEngine`, `test_settlementAboveTheCapIsRefusedBeforeTheBucket`, `test_samplingRateIsProportionalAndFixedAtSettlement`, `test_purchaseAtTheCapIsAlwaysDrawn`; `scripts/check_spec.py` |
| Profile terms, tiers and unit bond `k * b` | Profile 9 | `FairBindRegistry.setProfileTerms`, `FairBindBond.registerBondWithTerms`, `FairBindCore._unitTerms`, `_rescale`, `_confirmFailure` | `Design2Terms.t.sol` `test_profileTermsAdmitTheRulesTiersAndNoSmallerLimit`, `test_profileTermsAreCheckedAndFixedOnce`, `test_unitBondIsTheFailureLimitTimesTheDeduction`, `test_eachFailureDeductsExactlyB`, `test_smallTierAdmitsAtMostItsLimitInAnyIntervalOfTwiceTheHold`, `test_tierThirtyAdmitsAtMostThirty` |
| Term changes with recent peaks | Profile 9 | `FairBindBond.setBondTerms`, `FairBindCore._recentCap`, `_recentFailureLimit` | `Design2Terms.t.sol` `test_loweringTheCapKeepsTheOldCapForTheHoldPeriod`, `test_raisingTheCapNeedsTheBondFirst`, `test_raisingTheCapAtScaleNRecomputesTheScale`, `test_loweringTheTierKeepsTheHigherLimitForTheNextWindow`, `test_onlyTheOwnerOfAnActiveAccountChangesTerms` |
| Inconclusive above threshold neither counts nor deducts | FairBind 18; ADR 0013, 0017 | `FairBindCore._recordJudged` | `Design2Rules.t.sol` `test_inconclusiveAboveThresholdFreezesWithoutCountOrDeduction` |
| No release of an anchored epoch before its randomness (partly met) | FairBind (ADR 0024) | `FairBindRecovery.releasePurchase` | `Design2Rules.t.sol` `test_D2_16_anchoredEpochReleasesNothingBeforeItsRandomness`; the unmet part was pinned by `test_D2_16_openGap_anchoredEpochPastItsSealDeadlineIsRefunded`, which ADR 0029 replaced with `test_D2_16_anchoredEpochPastItsSealDeadlineIsNotRefunded` |

P1 is unchanged. P2 is strengthened on three paths (delivered disputes,
missing sample receipts, the case horizon) and remains unmet on one (an
anchored epoch refunded before its randomness). P3 changes in two directions:
the deduction no longer depends on the sales limit, but a stalled seller
appeal now confirms a wrongful initial `FAIL`, and the failure limit of a
profile with terms assumes every settlement sampled. P4 is strengthened. The
regression tests above state the old behaviour each one replaces.


## ADR 0025: checkpoint-time eligibility, fixed review reseal, committed terms

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Eligibility from the epoch's checkpoint (decision 126) | Sortition 2, 3, 4, 5; FairBind (ADR 0025) 1 | `FairBindRegistry.checkpointVerifierTree` (`checkpointHeadroom`), `FairBindCore._liabilityRoom`, `_assignVerifier`, `_checkpointAt`, `_releaseAssignment` | `Design2Impl1b.t.sol` `test_targetedDecoysDoNotMoveTheFirstAssignment`, `test_aFullVerifierThatDoesNotAnswerIsReplacedByTheNextCandidate`, `test_roomIsTheCheckpointSnapshot`, `test_sealTakesTheLatestCheckpointBeforeTheAnchorDeadline`; the residual path is pinned by `test_liabilityLockedBeforeTheCheckpointIsPartOfTheSnapshot`; invariant `invariant_verifierLiability` (checkpoint room) |
| Reopened review seal keeps its block | Lifecycle 4, 7; FairBind (ADR 0025) 2 | `FairBindCore._sealReview` (`reviewResealDue`), `FairBindReview.finalizeCase` | `Design2Impl1b.t.sol` `test_reopenedSealDrawsTheSameVerifierFromTheSameRandomBlock`, `test_aHashGoneBeforeTheReopeningEndsTheStage`, `test_theReopenedWindowEndsTheStageWhenItPasses`; `D2ContractCheck.t.sol` `test_rv_reopenedReviewSealKeepsRandomBlock`; `FairBindReentry.t.sol` reseal tests; `WorstPathLength.t.sol` (30,573 / 92,081 unchanged); `experiments/case_paths.py` |
| Terms only on a profile never active, against `termsHash` | Profile 9.1 | `FairBindRegistry.setProfileTerms`, `setServiceProfileActive` (`profileActivated`), `FairBindCore._termsHash` | `D2ContractCheck.t.sol` `test_rv_termsOnAPreviouslyActiveProfileAreRefused`; `Design2Impl1b.t.sol` `test_termsMustReproduceTheirCommitment`, `test_termsHashMatchesTheProfileDocuments`, `test_profileDocumentsAreAdmitted`, `test_termsNeedBothWindowsAtTheHoldPeriod`; `scripts/check_spec.py` (`profiles/design2-v1.json`) |
| Late sample verdict ends `UNSERVED` | FairBind (ADR 0025) 4; Lifecycle (ADR 0025) | `FairBindJudgment.judge` | `D2ContractCheck.t.sol` `test_rv_verdictAfterTheReceiptDeadlineEndsUnserved` |
| Stalled seller appeal never ends `INCONCLUSIVE` | FairBind (ADR 0024) 3 | `FairBindCore._finishReview` | invariant `invariant_stalledSellerAppealUpholdsTheFail`, driven by the handler action `stalledSellerAppeal` (hit counter "stalled seller appeal upheld the initial FAIL"); the build with D2-15 switched off fails it |
| Read functions in the lens module | Contract Interface (ADR 0025) | `FairBind._read`, `fallback`; `FairBindLens` | every test that reads state; `FairBindM1.t.sol` `testModulesRejectDirectMutation`, `testUnknownSelectorRejected`; `scripts/check_modules.py` (router ABI preserved) |
| Keeper receipt calls | Lifecycle (ADR 0025) | `services/keeper` `planReceipt`, `SubmitSampleReceiptData`, `DirReceiptList` | `keeper_test.go` `TestSampleReceiptSubmittedThenTimedOut`, `TestSampleReceiptTimeoutWithoutList`, `TestDirReceiptListReadsPublishedReceipts`; `directive_test.go` `TestWorstPathReceiptCallsNeedTheList`, `TestWorstPathReviewSealLapsesOnce` |

P1 is unchanged. P2 is strengthened on two paths (late sample verdicts, terms
on an account opened without them). P3 for sellers is unchanged; an honest
verifier may now be assigned while full and pay a late penalty if it cannot
answer. P4 is strengthened: the seller can no longer move the first
assignment by ordering cases after the checkpoint or by letting a review seal
lapse. Liability locked before a checkpoint block still enters that
checkpoint (ADR 0025, limit 1).

## ADR 0026: the anchor carries the receipt list

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| No anchor without its `(nonce, receiptLeaf)` list; nonces strictly ascend; the root is computed on chain | FairBind 11; Merkle 2, 3, 6; Contract Interface 7 | `FairBindSampling.anchor`, `FairBindMerkle.strictlyAscending`, `FairBindMerkle.computeRoot` | `AnchorEntryList.t.sol` `test_anchorStoresTheRootOfItsEntryList`, `test_contractAcceptsInclusionProofAgainstComputedRoot`, `test_anchorRevertsWhenListLengthDiffersFromCount`, `test_anchorRevertsUnlessNoncesStrictlyAscend`; `AnchorReviewCheck.t.sol` `test_computeRootEmptyAndSingle`, `test_computeRootDifferentialAgainstVerify`; Go `TestEntriesRootMatchesTreeRoot` |
| The contract and the services compute the same root | Merkle 2 | `FairBindMerkle.computeRoot`, `x402.EntriesRoot` | `AnchorEntryList.t.sol` `test_computeRootSharedVectors`; Go `TestEntriesRootSharedVectors` |
| Omission of any real purchase is provable by anyone from the public list | Merkle 4; Contract Interface 10 | `FairBindRecovery.proveOmission` | `AnchorEntryList.t.sol` `test_omittedReceiptIsProvenFromThePublishedList`, `test_honestListAdmitsNoOmissionProof`, `test_singleEntryListBoundsOmissionOnBothSides`; `AnchorReviewCheck.t.sol` `test_fillerBetweenRealEntriesAdmitsOmissionProof`, `test_allFillerListAdmitsOmissionProofForEveryPurchase`, `test_descendingOrderDoesNotAnchorAndSortedListAdmitsInteriorProof`; `FairBindM3.t.sol` `testOmissionProofAtListBoundaryRefundsOmittedPurchase` |
| A substituted receipt at the buyer's own nonce is provable only by that buyer (needs its signed receipt) | Merkle 4, 5; Contract Interface 10 | `FairBindRecovery.proveMisanchoredReceipt` | `AnchorEntryList.t.sol` `test_tamperedEntryBreaksTheTrueInclusionProof`, `test_misanchoredReceiptIsProvenByItsBuyer` |
| Anchor gas by list length and the largest list per transaction | Contract Interface 7; ADR 0026 limit 4 | `FairBindSampling.anchor` | `AnchorEntryList.t.sol` `test_anchorGasByListLength` (frame gas within 5% of the table), `test_anchorEntryLimitPerTransaction` |

P1, P3 and P4 are unchanged. P2 is strengthened: assumption A-LEAF (the
seller publishes its receipt list) is now a contract rule. Omission of any
real purchase is provable by anyone from the public list; a substituted
receipt at the buyer's own nonce is provable only by that buyer (needs its
signed receipt). An epoch larger than one transaction can carry (11,742
entries at 30,000,000 gas, 6,562 at 16,777,216) cannot be anchored and fails
by `timeoutAnchor`; chunked anchoring is left to the next version.

## ADR 0028: an exhausted first assignment waits for the next checkpoint

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| An exhausted initial search of a sampled case waits, purchase held, attempt unchanged | Lifecycle 4, ADR 0028 case rules; Sortition 4 | `FairBindCore._assignVerifier`, `_waitForCheckpoint` | `AssignmentWait.t.sol` `test_exhaustedFirstAssignmentWaitsAndHoldsThePurchase`, `test_waitingDoesNotConsumeMaxAssignments`; `FairBindM2.t.sol` `testLiabilityRespectsEffectiveBondCap` (old keeper path replaced) |
| Redraw only on a checkpoint written after the search, from the hash of its block plus `beaconDelayBlocks + 1` | Sortition 5.1; Contract Interface (ADR 0028) | `FairBindSampling.assignVerifier`, `_redraw` | `AssignmentWait.t.sol` `test_redrawBeforeANewerCheckpointReverts`, `test_redrawAfterANewerCheckpointAssignsAndStartsTheJudgeDeadline`, `test_redrawValueIsFixedOnlyAfterTheNewerCheckpoint`, `test_aRedrawHashNoLongerServedWaitsForTheNextCheckpoint` |
| Review stages and buyer disputes keep the old exhaustion rule | Lifecycle 4; ADR 0024 | `FairBindCore._protocolInconclusive`, `_finishReview` | `AssignmentWait.t.sol` `test_disputeExhaustionStillEndsInconclusive`, `test_reviewExhaustionAfterARedrawUpholdsTheInitialFail`; `FairBindM4Capital.t.sol` exhaustion tests |
| No release of a waiting purchase; a freeze covers it as an encumbered entry | FairBind 27; Lifecycle (ADR 0028) | `FairBindRecovery.releasePurchase`, `FairBindBond.claimRefund` | `AssignmentWait.t.sol` `test_aFailureWhileWaitingFreezesAndTheWaitingPurchaseIsClaimableOnceJudged`; invariant `invariant_noReleaseBeforeCaseEndOrWhileFrozen` in `WaitingAssignmentInvariantTest` under every `run.sh` configuration; `WaitingCoverageTest`; the mutation build `WaitRelease.sol` fails it (`run.sh` step 5) |

P1 is unchanged. P2 changes in two directions: a drawn sample is no longer
released unjudged when no verifier has room, but its purchase may stay held
for as long as the verifiers stay full. P3 for an honest seller gains a wait
and no penalty. P4 is strengthened: the redraw draws from a value that did not
exist when its checkpoint was written. The waiting delay is assumption A4 of
the design 2 rules, not a contract bound (ADR 0028, limit 1).

## ADR 0029: an anchored epoch waits for its value; a waiting case stops the release clock

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| No release, refund or failure of an anchored epoch without its value; a late value takes the normal path | FairBind 21.2, invariant 38; Lifecycle 1, 8, ADR 0029 rules | `FairBindSampling.seal`, `timeoutSeal`; `FairBindRecovery.releasePurchase`, `claimEpochFailure` | `EpochValueHold.t.sol` `test_missingValueHoldsTheEpochWithoutFailure`, `test_lateValueTakesTheNormalPath`, `test_noRefundWithEnoughVerifiers`; `Design2Rules.t.sol` `test_D2_16_anchoredEpochPastItsSealDeadlineIsNotRefunded`; `FairBindM2.t.sol` `testUnavailableRandomnessKeepsTheEpochAnchored`, `testSealTimeoutNeedsACheckpointShortage`; the stateful suite's seal action (late seal, seal without its value, timeoutSeal refused) under every `run.sh` configuration |
| Refund without seller failure only on a checkpoint shortage, before or after the value | FairBind 21.2; Lifecycle 8, ADR 0029 rules | `FairBindSampling.timeoutSeal`; `FairBindCore._sellerFailure` | `EpochValueHold.t.sol` `test_checkpointShortageRefundsWithoutFailure`, `test_checkpointShortageAlsoEndsTheEpochAfterItsValue` |
| Release clock of a bond account stops while one of its cases waits; overlapping waits count once | FairBind invariants 27, 39; Lifecycle 2, ADR 0029 rules | `FairBindCore._clockWaitStarts`, `_clockWaitEnds`, `_pausedSince`; `FairBindSampling._redraw`; `FairBindRecovery.releasePurchase` | `ReleaseClock.t.sol` `test_noReleaseWhileACaseOfTheAccountWaits`, `test_releaseResumesAfterTheWaitWithTheUnpausedCount`, `test_overlappingWaitsCountOnce`, `test_pausedSinceSumsOnlyThePausesAfterTheBlock`, `test_aWaitingCaseThatEndsRestartsTheClock`, `test_anExhaustedRedrawKeepsOnePause`; invariants `invariant_releaseClockStopsWhileACaseWaits` and `invariant_noReleaseBeforeCaseEndOrWhileFrozen` in `WaitingAssignmentInvariantTest`; `WaitingCoverageTest` branch 63; the mutation build `PauseIgnored.sol` fails the release invariant (`run.sh` step 6) |
| `V*`, the required balance and the bond exit lock count unpaused blocks | FairBind invariant 39; Profile 9 | `FairBindCore._recentCap`, `_recentSanctionLimit`, `_heldUntil`, `_rescale`, `_confirmFailure`; `FairBindBond.finalizeBondExit` | `ReleaseClock.t.sol` `test_recentCapAndRequiredBalanceCountUnpausedBlocks`, `test_bondExitCountsUnpausedBlocks`; the observer's recent-scale-high model in the stateful suite |

P1 is unchanged. P2 is strengthened on both paths and keeps one liveness
limit: an epoch whose value nobody delivers while the chain serves the block
hash holds its purchases without an exit (ADR 0029, limit 1). P3 for an honest
seller gains delays and no penalty. P4 is unchanged.

## ADR 0030: a confirmed failure freezes from the failing sale

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| A confirmed failure freezes the entries settled from its sale on; earlier entries keep their schedule | Contract interface, ADR 0030 | `FairBindCore._freeze`, `_addFreezeSpan`, `_frozen`, `_sellerFailure`, `_recordJudged`; `FairBindSampling.timeoutAnchor`; `FairBindRecovery.releasePurchase` | `NarrowFreeze.t.sol` `test_failureFreezesFromItsSaleAndEarlierEntriesKeepTheirSchedule`, `test_missedAnchorFreezesFromItsEpoch`, `test_inconclusiveFreezeStartsAtTheFirstInconclusiveSale`, `test_earlierEntryIsNotClaimable`; mutation builds in `NarrowFreezeMutants.sol` caught by `test_mutationFreezingFromZeroIsCaught`, `test_missedAnchorMutationIsCaught`, `test_inconclusiveMutationIsCaught` |
| A later failure lowers the start whatever the status; one after a reinstatement adds a span | Contract interface, ADR 0030 | `FairBindCore._freeze`, `_addFreezeSpan` | `test_laterFailureWithAnEarlierSaleLowersTheStart`, `test_failureAfterReinstatementAddsASpanFromItsSale` |
| Forfeiture takes only window entries, as one sum or itemized | Contract interface, ADR 0030 | `FairBindBond.forfeitUnclaimed`, `claimRefund`; `FairBindCore._forfeitWindowOf`, `_setFinancialState` | `test_windowWithoutEarlierEntriesForfeitsOneSum`, `test_windowWithAnEarlierEntryClosesItemized` |

P1 is unchanged. P2 is unchanged for the buyers of the failing sale and of
later sales; the buyers of earlier sales are paid by the seller's delivery
alone, as for any sale that the exposure bound does not count. P3 is
strengthened: a wrongful failure no longer holds an honest seller's earlier
sales. P4 is unchanged.

## ADR 0031: request-based randomness behind IRandomness

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Request input without block hash, stored at the first request, bound to consumer and chain; requests only after their blocks | Contract interface, ADR 0031 | `FairBindVrf.request`, `_alpha`; `FairBindRecovery.requestSampleValue`, `registerRedraw`, `requestRedrawValue` | `VrfRandomness.t.sol` `test_sampleRequestFollowsTheRequestRule`, `test_alphaCarriesNoBlockHash`, `test_onlyTheConsumerRequests`, `test_redrawUsesTheAuxValueOfItsRegisteredUse`; mutation adapter `BlockHashAlphaVrf` caught by `test_alphaWithABlockHashIsCaught` |
| A value is stored once and only with a proof for the stored input and key | Contract interface, ADR 0031 | `FairBindVrf.fulfill` | `test_wrongProofAndSecondResponseAreRefused` |
| SAMPLE value taken only by A + D_S + T_V; no release without it | Contract interface, ADR 0031; ADR 0029 | `FairBindPublication.seal`; `FairBindCore._sampleValue`, `_sampleTaken` | `test_lateButTimelyValueSealsTheEpoch`, `test_valueAfterTheDeadlineIsRefused`, `test_contractRefusesALateValueAnAdapterStored`, `test_noResponseHoldsTheEpoch`, `test_sealWaitsForTheValue`; mutation module `LateTakingPublication` caught by `test_takingALateValueIsCaught` |
| Redraw with the AUX value of a use registered after its checkpoint; exit without count when unanswered | Contract interface, ADR 0031 | `FairBindSampling._redraw`; `FairBindRecovery.timeoutRedrawValue` | `test_redrawUsesTheAuxValueOfItsRegisteredUse`, `test_redrawWithoutAResponseExitsWithoutCount` |

P1 and P4 are unchanged. P2 keeps the liveness limit of ADR 0029 for an
unanswered SAMPLE request and gains an exit for an unanswered redraw. P3
depends on the provider's key and on its answering only registered requests
instead of on block hashes.


## ADR 0032: assignment batches, verifier slots and queues

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Batch terms admitted only with a request-based source and the bounds on D_V, T_V, T_epoch; beacon floor from the source | Contract interface, ADR 0032 | `FairBindBatchAdmin.setBatchTerms`; `FairBindCore._beaconFloor`, `_validateProfile` | `BatchAssignment.t.sol` `test_batchTermsAdmission`, `test_beaconFloorFollowsTheSource`, `test_extensionsAndSourceRequirements` |
| A batched epoch's checkpoint is the state at its anchor deadline, read from the history whenever written | ADR 0032 | `FairBindBatchAdmin.checkpointAt`, `_stateSet`; `BatchShared._stateAt`; `FairBindBatch._note`; `FairBindPublication.seal`, `timeoutSeal` | `test_checkpointKeepsTheStateOfTheAnchorDeadline`, `test_sealTakesOnlyTheCheckpointOfItsAnchorDeadline`, `test_epochWithoutItsCheckpointEndsOnceALaterOneExists`; mutation `CurrentStateBatch` caught by `test_checkpointOfTheCurrentStateIsCaught` |
| First candidates fixed by the batch value and the case alone | ADR 0032 | `FairBindBatch.assignBatch`, `_place`, `_ticketCase`, `_join` | `test_firstCandidatesIgnoreOpeningOrderAndDecoys`, `test_batchMembershipRanksAndTheLateCase`; mutation `OrderTicketBatch` caught by `test_ticketsFromTheOpeningOrderAreCaught` |
| Queues in key order; one account's decoys delay another account's case by one turn | ADR 0032 | `FairBindBatch._setKey`, `_enqueue` | `test_decoysOfAnotherAccountDelayByOneTurn` |
| Slots, the exception start, starts inside freeing transactions, reservations | ADR 0032 | `FairBindBatch._startHeads`, `_startCase`, `hook`; `BatchShared._slotCount`; `FairBindCore._releaseAssignment` | `test_oneSlotStartsTheHeadAndTheVerdictStartsTheNext`, `test_withoutSlotsOneCaseStartsByTheException`, `test_holdingAJudgmentOrAPenaltyMovesNoQueuedCase` |
| Only a verifier's own exit request or withdrawal moves cases, and only those fixed after it | ADR 0032 | `FairBindBatch._moves`, `transferQueued`, `withdrawVerifierBond`; `FairBindRegistry.requestVerifierExit`, `finalizeVerifierExit` | `test_ownExitMovesOnlyCasesFixedAfterIt`, `test_withdrawalLeavingNoSlotRecordsTheDeparture`; mutations `NoMoveBatch`, `MoveAllBatch` caught by `test_exitThatMovesNothingIsCaught`, `test_exitThatMovesEarlierCasesIsCaught` |
| Queued sample cases and a late batch value pause the release clock; unanswered values exit without a count | ADR 0032, ADR 0029 | `FairBindBatch._enqueue`, `_startHeads`; `FairBindBatchAdmin.markAssignLate`, `timeoutAssignValue`, `timeoutLateValue` | `test_queuedSampleCasesPauseTheReleaseClock`, `test_lateBatchValuePausesAndItsExitEndsWithoutCount`, `test_lateValueExitEndsWithoutCount` |
| Split-anchor units add up to the epoch count | ADR 0026 | `FairBindSettlement.anchorUnit`, `_unitLengthOk` | `UnitLength.t.sol` `test_lastUnitMustCompleteTheCount`; mutation `ShortUnitSettlement` caught by `test_shortLastUnitIsCaught` |

P1 is unchanged. P2 gains the batch and late-value exits and keeps the
liveness limit of an unanswered SAMPLE request. P3 is strengthened: an
honest seller's sample case is judged by the verifier its batch value names
whatever other cases are opened; decoys and busy verifiers only delay it,
in paused blocks. P4 is unchanged.

## ADR 0033: proportional appeal deposit

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Deposit max(d0, phi H) with H at the end of the previous block, within the buyer's limit | ADR 0033 | `FairBindSettlement._settleBatched`; `FairBindDeposit.appealWithLimit`, `_appealHigh`; `FairBindCore._heldHigh` | `AppealDeposit.t.sol` `test_sameBlockSettlementDoesNotRaiseTheDeposit`, `test_limitAndTheFixedPaths`, `test_markKeepsThePeakAfterTheTotalFalls`; mutation `CurrentHeldProof` caught by `test_depositOfTheCurrentBlockIsCaught` |
| A failed appeal pays d0 and locks the rest; a won appeal returns everything | ADR 0033 | `FairBindCore._resolveAppealDeposit` | `test_failedAppealPaysTheFixedDepositAndLocksTheRest`, `test_wonAppealReturnsTheWholeDeposit` |

P1, P2 and P4 are unchanged. P3 is strengthened for a large account: an
appeal that holds it costs in proportion to what it holds.

## ADR 0034: seller proofs and the compensation pool

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Proof on a frozen unclaimed entry with a separate bond; held entry, waiting forfeiture; one proof per entry | ADR 0034 | `FairBindProof.submitProof`, `_proofBond`; `FairBindBond.forfeitUnclaimed` | `SellerProof.t.sol` `test_proofConditions`, `test_heldEntryAndPendingProofKeepTheWindow`, `test_auditedProofFailsAndItsBondCompensatesTheProvenEntry` |
| A proof opens only after the account's sample cases and epochs are decided | ADR 0034 | `FairBindProof._proofReady`, `activateProof`, `voidReservation`; `FairBindDeposit.noteSampleDeadline`; `FairBindCore._sampleEnded`, `_epochResolved` | `test_proofWaitsForTheAccountsOpenSampleCases`, `test_reservationOfAnEpochWithoutAValueIsVoided`; mutation `EarlyProof` caught by `test_proofOpeningEarlyIsCaught` |
| Audit by the AUX value of the opening block; contest; judgment; exits | ADR 0034 | `FairBindProof.drawAudit`, `contestProof`, `confirmProof`, `judgeProof`, `timeoutProofJudge`, `timeoutAuditValue` | `test_auditedProofPassesAndTheEntryIsReleased`, `test_contestThatWinsPaysTheContester`, `test_lostContestLocksAndUncontestedProofWaitsForItsWindow`, `test_unansweredAuditValueEndsTheProof`, `test_laterFailureVoidsAConfirmedProof` |
| Forfeited bonds compensate the account's proven entries by value; pools per account | ADR 0034 | `FairBindProof.distributeCompensation`, `claimCompensation`, `_poolOf` | `test_poolIsSplitInProportionToValue`, `test_poolStaysWithItsAccount`; mutation `SharedPoolProof` caught by `test_sharedPoolIsCaught` |

P1 is unchanged. P2 changes for proven entries: their buyers are paid from
the pool, not by a claim, and the pool's total is the forfeited bonds. P3 is
strengthened: an honest seller recovers a frozen correct sale. P4 is
unchanged.

## ADR 0035: side-gain deposit

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Settlement needs the epoch's opening count and one more unit of deposit | ADR 0035 | `FairBindSettlement._settleBatched`; `FairBindBatchAdmin.recordEpochOpenCount`; `FairBindCore._sideGainUnit` | `SideGain.t.sol` `test_saleNeedsTheOpeningCountAndTheDeposit` |
| A sample failure locks a unit; decided sales free the deposit | ADR 0035 | `FairBindProof._failure`; `FairBindDeposit.clearSideGain`, `withdrawSideGain` | `test_sampleFailureDeductsAUnitAndDecidedSalesFreeTheDeposit` |
| Repeated SAMPLE request after M for a side-gain profile | ADR 0035 | `FairBindDeposit.rerequestSampleValue`; `FairBindPublication.seal`; `FairBindCore._repeatedSampleValue` | `test_repeatedSampleRequestAfterTheDeadline`, `test_onlyASideGainProfileAsksAgain` |

P1, P2 and P4 are unchanged. P3 costs an honest seller of a side-gain profile
the deposit's capital.

## ADR 0036: review values and late-value pauses

| Requirement | Specification | Contract | Verification |
| --- | --- | --- | --- |
| Review stages of a batched case draw from the AUX value of the transaction that opened them; later attempts reuse it; the block-hash seal is closed | ADR 0036 | `FairBindCore._startReview`, `_openAutoReview`; `FairBindDeposit.hook`, `requestReviewValue`, `assignReview`; `FairBindReview.sealReviewRandomness`, `finalizeCase` | `ReviewValues.t.sol` `test_appealAndTiebreakDrawFromTheirAuxValues`, `test_autoRecheckDrawsFromTheValueOfItsSelection` |
| An unanswered review value upholds a seller-appealed FAIL and ends any other sample review without a count | ADR 0036 | `FairBindDeposit.timeoutReviewValue`, `_upholdsFirstFail`; `BatchShared._valueExit`, `_exitOpen` | `test_unansweredReviewOfASellerAppealUpholdsTheFail`, `test_unansweredReviewOfABuyerAppealEndsWithoutCount`; mutation `SellerAppealExitDeposit` caught by `test_sellerAppealExitWithoutCountIsCaught` |
| Exits open after the first request + D_V + T_V | ADR 0032, ADR 0036 | `BatchShared._exitOpen`; `FairBindBatchAdmin.timeoutAssignValue`, `timeoutLateValue` | `BatchAssignment.t.sol` `test_exitOpensAfterTheResponseBoundAndTheSlack`; mutation `EarlyExitAdmin` caught by `test_exitWithoutTheSlackIsCaught` |
| Queued sample cases pause the clock | ADR 0032 | `FairBindBatch._enqueue`, `_queuePauses` | `test_queuedSampleCasesPauseTheReleaseClock`; mutation `QueueNoPauseBatch` caught by `test_queueThatLeavesTheClockRunningIsCaught` |
| Late batch, AUX and sampling values pause from the block after their bound | ADR 0036, ADR 0029 | `BatchShared._pauseFrom`, `_pauseEnd`, `_valueArrived`, `_lateStart`; `FairBindBatchAdmin.markAssignLate`; `FairBindBatch.markValueLate`; `FairBindProof.markSampleLate`, `hook`; `FairBindCore._epochResolved` | `test_lateBatchValuePausesFromItsBound`, `test_unmarkedLateBatchValuePausesAtAssignment`, `test_lateAuxValuePausesFromItsBound`, `test_unmarkedLateAuxValuePausesAtItsUse`, `test_lateReviewValuePausesFromItsBound`, `test_lateSampleValuePausesUntilTheSeal`, `test_lateSampleValuePausesUntilItsDeadlineIsNoted`; mutations `LateStartNowAdmin`, `LateStartNowBatch`, `LateStartNowProof` caught by `test_lateBatchPauseFromTheCallIsCaught`, `test_lateAuxPauseFromTheCallIsCaught`, `test_lateSamplePauseFromTheCallIsCaught` |
| A waiting case redraws into its candidate's queue, keeping its batch and key | ADR 0028, ADR 0032 | `FairBindSampling._redraw`; `FairBindBatch._draw`, `_place`, `_exhausted` | `BatchWait.t.sol` `test_waitingCaseRedrawsIntoAQueue` |
| A failed appeal locks the deposit above d0; settlement needs one more side-gain unit | ADR 0033, ADR 0035 | `FairBindCore._resolveAppealDeposit`; `FairBindSettlement._sideGainCovered` | mutations `ExcessToSellerJudgment`, `SideGainShortSettlement` caught by `test_excessPaidToTheSellerIsCaught`, `test_depositShortOfTheNewSaleIsCaught` |

P1 and P4 are unchanged. P2 gains the review exits. P3 is strengthened: no
block hash decides who judges a review stage of a batched case, and values
that come late hold the account's releases from their bound.

## ADR 0037: receipt signatures, PASS proofs and measured costs

| Requirement | Decision | Implementation | Tests |
|---|---|---|---|
| Exchange terms are fixed once before activation with their admission checks; a vote profile takes receipt signatures by default | ADR 0037 | `FairBindExchange.setExchangeTerms`, `_admit` | `ExchangeAdmission.t.sol` `test_admissionChecks`, `test_termsAreFixedOnceByGovernanceBeforeActivation`, `test_voteTakesReceiptSignaturesByDefault`; mutation `OpenAdmissionExchange` caught by `test_admissionWithoutChecksIsCaught` |
| Only the seller posts a receipt signature, with its registered key, one bundle per nonce; failing nonces of a list are skipped | ADR 0037 | `FairBindExchange.postReceipt`, `postReceipts`, `_postingSignatureOk`, `_slotFree`; `ExchangeShared._signedBy` | `ReceiptExchange.t.sol` `test_postListSkipsOnlyTheFailingNonces`, `test_postingNeedsTheRegisteredSellerKey`, `test_buyerSignatureNamesTheRegisteredSeller`, `test_secondBundleOfANonceIsDropped`, `test_smartAccountSignatureHoldsAfterRevocation`, `test_postingWithoutGasForThe1271CapReverts`; mutations `AnyPosterExchange`, `RepostExchange` caught by `test_postingByAnyoneIsCaught`, `test_secondBundleReplacingTheFirstIsCaught` |
| A sale is a purchase whose posted leaf matched the anchor by A_e; any other is refunded once and never released. A posting, alone or carried by a PASS proof, binds nothing without the separate match; the posting slack of admission check (3) covers both transactions (posting and match) | ADR 0037 | `FairBindExchange.matchAnchor`, `_matchInTime`, `_inUnit`, `refundUnbound`, `_admit`; `FairBindPassProof._postInProof`; `FairBindRecovery.releasePurchase`; `FairBindSampling.openSample` | `test_lateMatchIsRefusedAndThePurchaseRefunded`, `test_unboundPurchaseIsRefundedOnceAndNeverReleased`, `test_matchInTheUnitOfASplitAnchor`, `test_postingInAProofBindsOnlyByAMatch`, `DeliveredShare.t.sol` `test_unboundPurchaseOpensNoSampleCase`; mutation `LateMatchExchange` caught by `test_lateMatchAcceptedIsCaught` |
| No refund returns its unit to the seller's bucket: unbound refund, key-dispute and wrong-delivery refunds of a proof profile, non-delivery refund of a VOTE_SIG profile | ADR 0037, rule D2-7 | `FairBindCore._setFinancialState` (the bucket untouched); `FairBindExchange.refundUnbound`; `FairBindPassProof._disputeFail`; `FairBindDelivery._refundOnly` | `BucketUnit.t.sol` four tests; mutations `UnitBackExchange`, `UnitBackProof`, `UnitBackDelivery` caught by its four `...ReturningTheUnitIsCaught` tests |
| A proof profile's sample case and dispute pass only with a PASS proof the contract checks; absent input or no proof fails | ADR 0037 | `FairBindPassProof.openProofSample`, `openProofDispute`, `prove`, `proveAbsence`, `timeoutProof`; `ExchangeShared._decrypt`, `_unpad`, `_proofLeaf` | `PassProof.t.sol` `test_honestSaleIsBoundProvedAndReleased`, `test_noProofByTheDeadlineIsAConfirmedFailure`, `test_absentInputFailsBeforeTheDeadline`, `test_theProofChecksEveryInput`, `test_honestProofPasses`, `test_plaintextWithoutItsPadMarkIsRefused`; mutations `NoNonceProof`, `NoMarkProof` caught by `test_keyStreamWithoutTheNonceIsCaught`, `test_unpadWithoutTheMarkIsCaught` |
| The reference time is the buyer's validAfter within delta_ref | ADR 0037 | `FairBindSettlement._settleProof`, `_referenceTimeOk` | `test_staleAuthorizationIsRefused`; mutation `StaleRefSettlement` caught by `test_staleAuthorizationAcceptedIsCaught` |
| A dispute without a PASS proof refunds without a failure; the sample case stays | ADR 0037 | `FairBindPassProof._disputeFail`; `FairBindCore._sellerFailureBody`, `_refundedEarly` | `test_withheldKeyRefundsAndTheSampleCaseStays`, `test_disputeOfAProvenPurchasePassesAtOnce`, `test_wrongDeliveryDisputeThatPassesPaysTheDeposit` |
| A key dispute pays the seller min(c_key, measured cost), the fixed share once per transaction, without priority fees; the L1 share is getL1FeeUpperBound(|xhat| + bEnv), less UB(bEnv) for a later call of the transaction, and depends on the length only | ADR 0037 | `FairBindPassProof._disputePass`, `_keyShare`; `FairBindCore._measuredCost`, `_firstCostOfTx`, `_l1Share`, `_l1Bound` | `test_keyDisputePaysTheMeasuredCostAndReturnsTheRest`, `ExchangeCost.t.sol` (with --isolate, `test_keyDisputeL1ShareIsTheBoundOfItsLength`), `L1Bound.t.sol` `test_sameLengthInputsTakeTheSameL1Share`, `test_laterShortCallAddsNothingUnderTheFloor`; mutations `CapShareProof`, `EveryCallFixedProof`, `GetL1FeeProof` (and its probe `GetL1FeeShareProbe`) caught by `test_constantKeyShareIsCaught`, `test_fixedShareOnEveryCallIsCaught`, `test_keyDisputeL1ShareByContentIsCaught`, `test_l1ShareByContentIsCaught` |
| A profile with exchange terms activates only where the L1 fee bound answers; with `requireExchangeTerms` set (evaluation setting deployment) no profile activates without exchange terms | ADR 0037, rule 8.2 row 23 | `FairBindRegistry.setServiceProfileActive`, `_exchangeActivation`; `FairBindExchange.requireExchangeTerms` | `L1Bound.t.sol` `test_activationNeedsTheL1Bound`, `test_activationWithoutTheOracleIsRefused`, `test_voteTermsOffKeepsTheBoundCheck`, `test_requiredTermsRefuseAVoteProfileWithoutThem`, `test_withoutTheSettingAProfileWithoutTermsActivates` |
| A binding proof is taken from the anchor on, also before the epoch's SAMPLE value, through retainUntil (the start of D2-19 (h) withdrawn) | Rule D2-19 (g); ADR 0037 11 | `FairBindRecovery.proveMisanchoredReceipt` | `BindStart.t.sol` `test_bindingProofBeforeTheValueIsTaken`, `test_bindingProofAfterTheRequestIsTaken`, `test_bindingProofHoldsThroughTheWindow`, `test_bindingProofOfAnExitingAccount`; mutation `ValueStartRecovery` caught by `test_bindingProofWaitingForTheValueIsCaught` |
| Checks 6, 7 and 8: 0 < F_max <= T_keep; value wait + slack <= F_max; L_F + margin - 1 <= F_max <= T_hold - 1; a batched hold covers L_F + margin and (6m + 4) * keeperSlack <= margin - 1, keeperSlack <= T_seal - 2 | Rule D2-13 (c) 6, 7, D2-8 (a); the path enumeration; ADR 0037 12 | `FairBindExchange._keepCoversWindow`; `FairBindRegistry._bindOpenFits`, `_caseLength`, `_bindWindowInRange`, `_batchHorizonHolds` | `BindStart.t.sol` `test_keepBelowTheWindowIsRefused`, `test_windowBelowTheValueWaitIsRefused`, `test_windowUnderTheRequestSourceFollowsM`, `test_windowOutsideTheStopRangeIsRefused`, `test_batchedHoldBelowItsCaseLengthIsRefused`, `test_keeperSlackAboveTheMarginIsRefused`, `test_keeperSlackAboveTheSealIsRefused`; mutations `ShortKeepExchange`, `AnyWindowRegistry`, `AnyRangeRegistry`, `ShortBatchHoldRegistry` caught by the five `...AcceptedIsCaught` tests |
| The SAMPLE request does not depend on an anchor | Rule D2-23 (a), 8.2 row 25 | `FairBindRecovery.requestSampleValue` | `BindStart.t.sol` `test_sampleRequestOfAnEpochWithoutAnchors`, `test_sampleValueOfAnEpochWithAMissedAnchor`; mutation `AnchoredSampleRecovery` caught by `test_sampleRequestTiedToAnAnchorIsCaught` |
| Batch terms and exchange terms exclude each other in either order (side-gain grade under VOTE_SIG, any batch terms under PROOF) | ADR 0037 | `FairBindExchange._admit`; `FairBindBatchAdmin.setBatchTerms`, `_excludedByExchange` | `ExchangeAdmission.t.sol` `test_sideGainAfterReceiptTermsIsRefused`, `test_receiptTermsAfterSideGainAreRefused`; mutation `SideGainAfterTermsAdmin` caught by `test_sideGainAfterReceiptTermsAcceptedIsCaught` |
| A delivered non-delivery dispute pays min(maxPublicationCost, measured sum); the rest is locked without receipt signatures and returned with them; a lapsed one of a VOTE_SIG profile only refunds | ADR 0037 | `FairBindCore._payDeposits`, `_ladderOn`, `_ladderCost`; `FairBindExchange._ladderPay`, `_ladderShare`, `discloseKey`; `FairBindDelivery.served`, `timeoutServe`, `_refundOnly`; `FairBindPublication` ladder calls | `DeliveredShare.t.sol` six tests; mutation `LadderCapExchange` caught by `test_deliveredShareOfTheWholeCapIsCaught` |
| The seller's proof on a frozen entry of a proof profile waits for the order condition and pays after T_rcpt; a failure voids it | ADR 0037, ADR 0034 | `FairBindSelfProof.selfProve`, `activateSelfProof`, `voidSelfProof`, `releaseSelfProven`, `_selfReady`, `_bindingWindowOver`, `hook` | `test_selfProofReleasesAfterTheBindingWindow`, `test_selfProofWaitsForTheAccountsOpenCases`, `test_bindingFailureVoidsTheSelfProof`; mutations `EarlyReleaseSelf`, `EarlyReadySelf` caught by `test_releaseAtTheBindingBoundIsCaught`, `test_selfProofConfirmedWhileACaseIsOpenIsCaught` |

P1 to P4: a profile whose exchange terms were never set keeps every rule; the frozen core is unchanged for it. Under receipt signatures a purchase is a sale only once bound, so deferred-fund priority applies to bound sales and unbound purchases are refunded before any release.
