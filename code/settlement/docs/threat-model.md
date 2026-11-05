# Threat Model

## Protected outcomes

FairBind protects four outcomes after a buyer signs an EIP-3009 payment authorization:

- one purchase key causes at most one successful payment;
- a settled honest buyer receives the seller-committed response or a full refund within bounded blocks;
- a compliant seller has a stated probability bound against an incorrect final failure verdict;
- verifier deadline failures and reviewable content errors have explicit economic consequences.

## Adversaries

A malicious seller may omit a response, return a response that conflicts with its registered claims, omit a receipt from an epoch, sign conflicting receipts, delay redelivery, exceed its allowed settlement rate, or stop participating after settlement.

A malicious verifier may miss deadlines, hide evidence, submit an incorrect verdict, coordinate with a seller or buyer, or split its capital across identities. Assignment weight therefore depends on capped effective bond rather than account count.

A malicious or unavailable reference source may return stale or inconsistent
data. Data API predicates require a profile-defined independent-source quorum
and return `INCONCLUSIVE` when that quorum or time alignment cannot be
established. An open-weights verifier may use another model or configuration;
the evidence envelope binds its implementation, weights, configuration, and
reproduced commitment.

A malicious facilitator may alter seller parameters, request hashes, identifiers, or contract arguments. The buyer signature and contract recomputation must reject these changes. A facilitator may also report an uncertain settlement. Buyers and sellers reconcile the transaction hash and contract state before retrying. A facilitator, or anyone who copies the authorization from a reverted `settle`, may try to execute it at the token directly; the authorization is an EIP-3009 `ReceiveWithAuthorization` that only the FairBind contract can execute, so such a call reverts and the funds stay with the buyer (ADR 0016).

A malicious buyer may submit false non-delivery or wrong-delivery claims, and may appeal every `PASS`. Dispute deposits, seller publication, predicate judgment, and final deposit accounting bound this behavior; a review that disagrees with the initial verdict goes to a third verifier, so a buyer needs two erring verifiers to turn an honest seller's `PASS` into a confirmed failure (ADR 0019). Under a production profile a wrongful initial `FAIL` neither freezes nor suspends the seller; only a confirmed failure does, and it then costs the seller the claims on its frozen pool and one share of the penalty (ADRs 0018 and 0020); the seller may re-enter after topping the share up, without waiting for the claim window to close (ADR 0021). Repeated false disputes cost the buyer its dispute deposit whenever the correct verdict stands. FairBind does not protect a buyer whose signing key is compromised.

A cheating seller may re-enter during the claim window of its last failure and cheat again. Its failures keep counting in the same failure window, and its next confirmed failure moves the frozen window over everything it sold since the reinstatement, so re-entry does not let it keep the proceeds of the next episode (ADR 0021). A seller cannot shelter a pending failure by requesting exit: an exiting seller is frozen and deducted and cannot finish its exit while its frozen pool is open. A large honest seller is not punished for a large bond: its failure threshold scales with the bond's scale factor. A window that opens soon after a deduction lowered the scale keeps the threshold of the scale the account left (within `retentionBlocks`), and a top-up during a window raises its threshold, so neither a deduction nor a top-up can leave an honest seller's threshold below its settlement volume (ADR 0022). Only the bond account's owner can top it up, so a third party cannot move its scale, its rate or its threshold.

A keeper may refuse to call a transition or attempt to call at a favorable time. At least one live keeper is assumed. Fixed deadlines and precommitted randomness blocks prevent a keeper from choosing the transition result. A review seal missed once reopens on a new future block instead of ending the case, so a single late or withheld seal cannot hand an appellant a protocol `INCONCLUSIVE` and its deposit; two misses in the same stage still end it (ADR 0021). The hold period exceeds the case horizon by a keeper margin (1,006 and 1,474 blocks in the evaluation profiles) that bounds the total keeper lateness over one case.

The emergency guardian may be malicious, but it can only stop new exposure. It
cannot block an existing obligation. The immutable penalty treasury can dispose
of received verifier penalties but cannot redirect purchase principal, deposits, or bond
withdrawals.

Nobody gains from a seller's failure. Forfeited frozen pools and the per-failure
deductions of seller bonds stay locked in the contract with no withdrawal
function; they reach neither the verifier reward pool nor the treasury (ADR
0022). A deployer that runs every verifier, or a verifier set that shares one
reward address, therefore has no payment to collect by convicting honest
sellers or by driving an account above the inconclusive threshold. The locked
tokens are lost to everyone; they are not burnt by a transfer, which the
deployment token would refuse for the zero address.

## Collusion boundary

The verifier model records a lower bound on honest effective bond after excluding every verifier already used in the case. Security bounds do not apply when adversarial effective bond exceeds that profile assumption.

Seller and facilitator collusion cannot change fields covered by the buyer-derived nonce. Seller and verifier collusion remains possible with the probability represented by effective detection and review parameters. Buyer and verifier collusion may harm an honest seller within the bound stated by P3.

## Out of scope

Version 1 excludes chain consensus compromise, long-range reorganization beyond the deployment finality policy, censorship that defeats the keeper and honest-buyer liveness assumptions, private-key theft, predicate definitions that do not represent the advertised service, verifier confidentiality, and denial of service against off-chain storage.

FairBind also does not provide atomic exchange. It commits funds first and supplies bounded delivery recovery and economic compensation after settlement.
