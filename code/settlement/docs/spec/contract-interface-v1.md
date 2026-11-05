# FairBind Contract Interface Version 1

Status: Release candidate for implementation

This document defines the logical Solidity interface. Implementations may pack
storage or split the code into libraries, but they MUST preserve every argument,
check, event field, error condition, and view result described here.

## 1. Deployment boundary

The constructor fixes the EIP-3009 payment and bond token, governance timelock,
emergency guardian, penalty treasury, verifier reward pool, and EIP-712 name
and version:

```solidity
constructor(
    address deploymentToken,
    address governanceTimelock,
    address emergencyGuardian,
    address penaltyTreasury,
    address verifierRewardPool
);
```

The verifier reward pool never changes. It MUST be nonzero and differ from
the token. Since ADR 0022 it receives nothing: forfeited pools and seller
deductions stay locked in the contract. The argument and the module check are
kept so that the deployment interface does not change.

Every address MUST be nonzero and pairwise distinct except that the governance
timelock may also be the penalty treasury. The token and penalty treasury never
change. Governance and the guardian may change only through the two-step
procedures in `governance-v1.md`. The EIP-712 name is `FairBind` and its version
is `1`.

FairBind version 1 supports one token per deployment. Every profile inherits
that immutable token and MUST NOT select another. A deployment for another token
uses another contract address, which changes every FairBind identifier and
signature domain.

The contract is not upgradeable. A protocol revision uses a new deployment.

## 2. Constants and enums

```solidity
uint32 constant PPM = 1_000_000;
uint32 constant RESPONSE_CHUNK_BYTES = 16_384;

enum ServiceClass { NONE, DATA_API, OPEN_WEIGHTS_INFERENCE }
enum SellerStatus { NONE, ACTIVE, SUSPENDED, SANCTIONED, EXITING, EXITED }
enum BondStatus { NONE, ACTIVE, EXITING, EXITED }
enum FreezeState { NONE, FROZEN, CLAIM_OPEN, CLAIM_CLOSED }
enum VerifierStatus { NONE, ACTIVE, REMOVED, EXITING, EXITED }
enum FinancialState {
    NONE, DEFERRED, HELD, FROZEN_CLAIMABLE, REFUNDABLE, REFUNDED, RELEASABLE, RELEASED, FORFEITED
}
enum EpochState { NONE, ANCHORED, SEALED, EPOCH_FAILED }
enum CaseTrigger { NONE, SAMPLE, NON_DELIVERY, WRONG_DELIVERY, OMISSION, EQUIVOCATION }
enum CaseState {
    NONE,
    SERVE_WAIT,
    SERVE_CONFIRM,
    PUBLISHING,
    ASSIGNING,
    JUDGING,
    INITIAL_VERDICT,
    PARTY_REVIEW,
    AUTO_REVIEW,
    TIEBREAK,
    DELIVERED,
    UNSERVED,
    INCONCLUSIVE,
    FINAL,
    WAITING_ASSIGNMENT
}
enum ReviewPath { NONE, PARTY, AUTO }
enum Verdict { NONE, PASS, FAIL, INCONCLUSIVE }
enum RequesterRole { NONE, BUYER, VERIFIER, KEEPER }
enum JudgmentStage { NONE, INITIAL, PARTY, AUTO, TIEBREAK }
enum EpochFailureReason { NONE, ANCHOR_TIMEOUT, SEAL_TIMEOUT, RANDOMNESS_UNAVAILABLE, VERIFIER_SET_UNAVAILABLE }
enum RefundSource { NONE, FINAL_FAIL, UNSERVED, EPOCH_FAILED, OMISSION, EQUIVOCATION, FROZEN_POOL }
enum DepositType { NONE, DISPUTE, APPEAL }
enum ActorType { NONE, SELLER, VERIFIER }
enum SlashReason { NONE, SELLER_FAILURE, VERIFIER_LATE, VERIFIER_WRONG, FORFEIT_UNCLAIMED }
enum ProofBoundary { INTERIOR, LOWER, UPPER }
```

Enum numeric values are part of the ABI and MUST retain this order. The
revision that introduced bond accounts inserted `SUSPENDED` after `ACTIVE` and
`FROZEN_CLAIMABLE` after `HELD`, shifting later values; no deployment used the
earlier order. `WAITING_ASSIGNMENT` (14) is appended by ADR 0028. Since
ADR 0029 an epoch fails after a valid anchor only with
`VERIFIER_SET_UNAVAILABLE`; `SEAL_TIMEOUT` and `RANDOMNESS_UNAVAILABLE` keep
their values and are no longer emitted. `Verdict` values are the codes verifiers sign: `1` PASS, `2`
FAIL, `3` INCONCLUSIVE; `0` marks an assignment without a verdict.
`FROZEN_CLAIMABLE` is reported by `purchaseState` and never stored.
`JudgmentStage` values enter signed verdicts. `attempt` is zero based within a
stage. `ProofBoundary` intentionally starts at zero because every proof names a
boundary mode.

## 3. Configuration types

```solidity
struct DeadlineConfig {
    uint32 anchorBlocks;
    uint32 sealBlocks;
    uint32 openBlocks;
    uint32 responseBlocks;
    uint32 claimBlocks;
    uint32 serveBlocks;
    uint32 judgeBlocks;
    uint32 evidenceBlocks;
    uint32 appealBlocks;
}

struct ServiceProfileInput {
    uint16 classId;
    bytes32 predicateId;
    bytes32 canonId;
    uint64 epochOrigin;
    uint32 epochBlocks;
    uint32 samplePpm;
    uint32 effectivePpm;
    uint32 recheckPpm;
    uint32 bucketCapacity;
    uint32 refillPpmPerBlock;
    uint32 maxRatePpmPerBlock;
    uint32 enforcementBlocks;
    uint32 deferBlocks;
    uint32 retentionBlocks;
    uint32 marginBlocks;
    uint32 maxRequestBytes;
    uint32 maxResponseBytes;
    uint32 maxEvidenceBytes;
    uint96 maxPublicationCost;
    uint96 maxReviewCost;
    uint96 maxPurchaseValue;
    uint96 maxBadGain;
    uint96 sellerPenalty;
    uint96 minVerifierBond;
    uint96 verifierBondCap;
    uint96 verifierLatePenalty;
    uint96 verifierWrongPenalty;
    uint96 disputeDeposit;
    uint96 appealDeposit;
    uint32 verifierExposurePpm;
    uint16 maxAssignments;
    uint16 minVerifiers;
    uint16 strikeLimit;
    uint32 deadlineConfigId;
    uint32 beaconDelayBlocks;
    uint32 beaconSlackL1Blocks;
    uint32 claimWindowBlocks;
    uint32 failureLimit;
    uint32 failureWindowBlocks;
    uint32 maxInconclusivePpm;
    uint32 inconclusiveWindowBlocks;
    uint32 forfeitVerifierPpm;
    bool freezeOnInitialFail;
    uint32 minJudgedCount;
    bytes32 parameterHash;
}
```

The eight fields after `deadlineConfigId` were added with bond accounts, and
`freezeOnInitialFail` and `minJudgedCount` with ADR 0020; their admission
rules are in `profile-v1.md` section 2. `freezeOnInitialFail` selects whether
an initial `FAIL` freezes and suspends (only the admission-override test build
admits `true`); `minJudgedCount` is the number of sampled judged cases a
window needs before the inconclusive threshold can freeze. The
bucket-capacity percentile is committed only through `parameterHash`.

One bucket token equals `PPM` internal units. A settlement consumes one bucket
token. `bucketCapacity` is an integer settlement count, while refill and maximum
rate use parts per million of one settlement per block. Version 1 bounds each
purchase with `maxPurchaseValue` rather than scaling bucket cost by value.

`parameterHash` commits the complete normative `parameters` object. The
`predicateId` identifies the separately versioned predicate codec. Epoch
publication bytes are committed by `publicationHash`. Calibration notes remain
non-normative and are bound to experiments by the recorded repository revision.
The `deadlineConfigId` must name a configuration byte-for-byte equal to the
profile document's nested deadline object. `marginBlocks`,
`maxPublicationCost`, and `maxReviewCost` are included in `parameterHash` and in
the profile admission checks.

## 4. Transaction types

```solidity
struct TransferAuthorization {
    address from;
    address to;
    uint256 value;
    uint256 validAfter;
    uint256 validBefore;
    bytes32 nonce;
}

struct CanonicalRequest {
    bytes method;
    bytes path;
    bytes query;
    bytes headerBlock;
    bytes body;
}

struct FairBindReceipt {
    uint8 version;
    uint256 chainId;
    address contractAddress;
    uint32 sellerId;
    uint32 profileId;
    bytes32 nonce;
    bytes32 requestHash;
    bytes32 responseHash;
    bytes32 claimsHash;
    bytes32 predicateCommitment;
    uint24 epoch;
    uint64 issuedAt;
}

struct ReceiptProof {
    uint32 index;
    uint32 count;
    bytes32[] siblings;
}

struct ReceiptEntry { // FairBindMerkle.ReceiptEntry, ADR 0026
    bytes32 nonce;
    bytes32 receiptLeaf;
}

struct SignedVerdict {
    uint8 version;
    bytes32 nonce;
    uint8 stage;
    uint8 attempt;
    uint32 verifierId;
    uint8 verdict;
    bytes32 evidenceHash;
}
```

`chainId` and `contractAddress` are wire fields used to reject a receipt before
EIP-712 recovery. They are domain values and do not appear in the receipt
primary type.

## 5. Administrative calls

```solidity
function createDeadlineConfig(uint32 deadlineConfigId, DeadlineConfig calldata config)
    external;

function createServiceProfile(uint32 profileId, ServiceProfileInput calldata input)
    external;

function setServiceProfileActive(uint32 profileId, bool active) external;
function pauseNewSettlements(bool paused) external;
function nominateGovernance(address nominee, uint64 acceptAfter) external;
function acceptGovernance() external;
function nominateGuardian(address nominee) external;
function acceptGuardian() external;
```

The governance timelock alone may create deadline configurations, create
profiles, or activate a profile. A created object is immutable. Deactivation
affects new registrations and settlements only. The emergency guardian may set
`paused` to true, as may governance. Only governance may set it back to false.
While paused, `setServiceProfileActive(profileId, true)` reverts; deactivation
remains available.

`acceptAfter` is a Unix timestamp no earlier than the current timestamp plus the
current timelock's minimum delay. Only the nominee may accept after that time.
Guardian nomination is itself a delayed timelock transaction; only the nominee
may accept it.

An object ID MUST be nonzero and unused. The caller supplies it so manifests and
multi-environment deployments can retain the same profile IDs without depending
on creation order. Creation never overwrites an object. `configHash` in
`DeadlineConfigCreated` is Keccak-256 over `abi.encode` of the nine `uint32`
fields in their struct order.

## 6. Seller and verifier calls

```solidity
function registerBond(uint32 profileId, uint128 amount) external returns (uint32 bondId);
function topUpBond(uint32 bondId, uint128 amount) external;
function requestBondExit(uint32 bondId) external;
function finalizeBondExit(uint32 bondId) external;

function registerSeller(
    uint32 bondId,
    uint32 profileId,
    address signingKey,
    bytes32 claimsHash
) external returns (uint32 sellerId);

function requestSellerExit(uint32 sellerId) external;
function finalizeSellerExit(uint32 sellerId) external;
function reinstateSeller(uint32 sellerId) external;

function registerVerifier(
    uint256 classBitmap,
    address signingKey,
    uint128 bondAmount
) external returns (uint32 verifierId);

function topUpVerifierBond(uint32 verifierId, uint128 amount) external;
function setVerifierClasses(uint32 verifierId, uint256 classBitmap) external;
function requestVerifierExit(uint32 verifierId) external;
function finalizeVerifierExit(uint32 verifierId) external;
function checkpointVerifierTree(uint32 profileId) external returns (uint64 version);
```

Bond registration and top-up calls transfer the deployment token into the
contract; `registerBond` requires `amount >= sellerPenalty`. `registerSeller`
transfers nothing: only the bond owner may register a seller under a bond, the
bond's profile must equal `profileId`, and the bond must be `ACTIVE`, not
sanctioned, not frozen, and hold at least `sellerPenalty`. A seller exit returns
no funds; `finalizeBondExit` returns the bond balance after every registration
under it has exited, nothing is deferred, no freeze is pending, and
`retentionBlocks` have passed since `requestBondExit`. `finalizeSellerExit`
reverts with `ExitNotReady` while the seller's bond account is `FROZEN` or
`CLAIM_OPEN` or has a pending initial-`FAIL` trigger: an exiting seller is
frozen and deducted like any other and cannot leave before its frozen pool is
closed (ADR 0021). `reinstateSeller` returns a `SUSPENDED` seller to `ACTIVE`
when its bond account is not sanctioned, is not `FROZEN`, has no pending
initial-`FAIL` trigger (ADR 0015), and its balance is at least
`sellerPenalty`; after the per-failure deduction of ADR 0018 that last
condition needs a top-up. The claim window may still be open (ADR 0021): the
account is then marked reopened, and `settle` admits settlements under it
from the block after `freezeBlock`, outside the frozen window, until the next
confirmed failure moves `freezeBlock` over them.
The caller of a registration becomes its owner. Only the owner may top up a
bond (ADR 0022), change verifier classes, or request and finalize its exit. An
owner cannot reduce bond, change a signing key, or change a seller profile in
place. `setVerifierClasses` may add or remove future eligibility but cannot
release liability from a historical checkpoint. `checkpointVerifierTree` is
public and records the current eligible set for one profile only when its
`setHash` has changed. Its ordering and ticket mapping follow `sortition-v1.md`.

## 7. Settlement and epoch calls

```solidity
function settle(
    uint32 sellerId,
    uint32 profileId,
    bytes32 claimsHash,
    bytes16 idempotencyKey,
    bytes32 requestHash,
    TransferAuthorization calldata authorization,
    bytes calldata paymentSignature
) external returns (bytes32 nonce, bytes32 keyId);

function anchor(
    uint32 sellerId,
    uint24 epoch,
    ReceiptEntry[] calldata entries,
    uint32 count,
    bytes32 publicationHash
) external;

function timeoutAnchor(uint32 sellerId, uint24 epoch) external;
function seal(uint32 sellerId, uint24 epoch) external;
function timeoutSeal(uint32 sellerId, uint24 epoch) external;
function openSample(bytes32 nonce) external;
function assignVerifier(bytes32 nonce) external;
```

`settle` performs every check and effect in `fairbind-v1.md` atomically. It
pulls the payment with the token's EIP-3009 `receiveWithAuthorization`; the
struct keeps the name `TransferAuthorization` and its ABI is unchanged. A used
identifier always reverts. Reconciliation uses views and never re-enters
`settle` in a read-only mode. `settle` reverts with `BondNotActive` while the
bond account is `FROZEN`, has a pending initial-`FAIL` trigger, or is
`CLAIM_OPEN` without a reinstatement during the window (or in the block of
`freezeBlock`).

Only the seller owner may call `anchor`. The other epoch progress calls are
public. `entries` is the list of `(nonce, receiptLeaf)` pairs of the epoch
tree (`merkle-v1.md` section 2), 64 bytes of call data per entry; `anchor`
requires its length to equal `count` (`CountMismatch`) and its nonces to
increase strictly (`EntriesNotAscending`), computes the root from it and
stores that root, so no anchor exists without its entry list (ADR 0026). The
list is not stored; it stays in the transaction's call data, and `Anchored`
carries the root and count. The list must fit in one transaction: at the
measured gas, at most 11,742 entries under a 30,000,000 gas transaction limit
and 6,562 under 16,777,216 (ADR 0026, limit 4); a seller above that cannot
anchor in this version.
`publicationHash` is Keccak-256 over the profile-defined publication
manifest bytes. `seal` selects the latest verifier checkpoint whose checkpoint
block is no later than the epoch's anchor deadline, then stores its version and
effective weight with the epoch randomness.

## 8. Serve and publication calls

```solidity
function requestServe(bytes32 nonce) external;
function served(bytes32 nonce, bytes32 bundleHash) external;
function acceptServe(bytes32 nonce) external;
function escalate(bytes32 nonce) external;
function finalizeServed(bytes32 nonce) external;

function publish(
    bytes32 nonce,
    bytes16 idempotencyKey,
    CanonicalRequest calldata request,
    bytes calldata responseBody,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature
) external;

function beginPublication(
    bytes32 nonce,
    bytes16 idempotencyKey,
    CanonicalRequest calldata request,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature,
    uint32 totalBytes,
    uint16 chunkCount
) external;

function publishChunk(bytes32 nonce, uint16 index, bytes calldata chunk) external;
function finalizePublication(bytes32 nonce) external;
function timeoutServe(bytes32 nonce) external;
```

For a buyer, `dispute(NON_DELIVERY)` opens the serve procedure and collects the
dispute deposit atomically. The standalone `requestServe` call is available only
to the verifier assigned to the active stage and attempt. The contract preserves
that assignment while delivery is recovered.

Only the seller owner may call `served`, `publish`, `beginPublication`, or
`publishChunk`. The active requester alone may call `acceptServe` or `escalate`.
Anyone may call
`finalizeServed` after the requester challenge deadline when no escalation
exists. `publish` is the single-call form;
the begin, chunk, and finalize calls are the bounded multi-call form. The
contract recomputes `requestHash` from the normalized `CanonicalRequest` fields
and enforces `maxRequestBytes` over their combined byte length. The requester
retrieves those calldata bytes when it needs the request for predicate replay.
For multi-call publication, the contract stores one hash per fixed 16,384-byte
response chunk and recomputes the positional root in `cryptography-v1.md`.
`totalBytes`, chunk lengths, count, order, uniqueness, and the signed
`responseHash` must all agree before finalization.

## 9. Dispute, judgment, and review calls

```solidity
function dispute(
    bytes32 nonce,
    uint8 kind,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature
) external;

function judge(
    SignedVerdict calldata verdict,
    bytes calldata verdictSignature,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature,
    ReceiptProof calldata proof
) external;

function requestEvidence(bytes32 nonce, uint8 stage, uint8 attempt) external;
function discloseEvidence(bytes32 nonce, uint8 stage, uint8 attempt, bytes calldata evidence) external;
function timeoutEvidence(bytes32 nonce, uint8 stage, uint8 attempt) external;
function timeoutJudge(bytes32 nonce) external;

function appeal(bytes32 nonce) external;
function sealReviewRandomness(bytes32 nonce) external;
function openAutoRecheck(bytes32 nonce) external;
function finalizeCase(bytes32 nonce) external;
```

The contract transfers the fixed dispute or appeal deposit from the caller.
`NON_DELIVERY` requires `receiptSignature.length == 0` and every receipt field to
be zero. `WRONG_DELIVERY` requires a valid seller receipt. The signed verdict
permits submission by a relayer. `assignVerifier` is public and is valid only
when the case is in `ASSIGNING` and its epoch randomness has been sealed.

Only the recorded buyer may call `dispute`. Any account may relay a `judge`
whose signature recovers the active verifier key. Until the initial appeal
deadline, only the buyer or seller owner may request that initial verifier's
evidence. Any account may disclose matching bytes or call a timeout. Only the
buyer may appeal `PASS`; only the seller owner may appeal `FAIL`; nobody may
appeal `INCONCLUSIVE`. Review sealing, automatic recheck, and case finalization
are public. `openAutoRecheck` and `finalizeCase` apply the recheck gate to an
unappealed initial `PASS` or `INCONCLUSIVE` after its candidate block; a
`FAIL` is finalized after its appeal window (ADR 0019). A party-review or
recheck verdict that differs from the initial verdict moves the case to
`TIEBREAK`; one that agrees, and every tiebreak verdict, is final.
`sealReviewRandomness`, `openAutoRecheck` and `finalizeCase` reopen a review
seal whose window has passed or whose block hash is unavailable once per
stage: the call succeeds, keeps `randomBlock`, stores its hash when the chain
still serves it, sets the reopened window's end (`getReviewResealDue`) and
emits `ReviewResealed`; a call after the reopened window, or a reopening after
the hash is gone, ends the case as a progress failure (ADR 0021, ADR 0025). `timeoutJudge` and `timeoutEvidence` keep their
selectors and behaviour; the reference router serves them from the sampling
module.

`discloseEvidence` requires `keccak256(evidence) == evidenceHash` and enforces
`maxEvidenceBytes`. The bytes remain in transaction calldata. A profile may also
publish them in content-addressed storage, but that copy does not replace the
calldata disclosure when a party requests evidence.

Deposit and penalty destinations follow `lifecycle-v1.md`; no call accepts a
destination address. The immutable penalty treasury receives verifier
penalties for which the lifecycle does not name a harmed party. Seller
deductions and forfeitures are locked in the contract (ADR 0022).

`topUpBond` reverts with `Unauthorized` unless the caller is the bond account
owner (ADR 0022). A top-up that raises the scale factor while the account's
failure window is open (`failureCount != 0` and `block.number <=
failureWindowStart + failureWindowBlocks`) raises `getFailureWindowScale` to
the new scale factor.

## 10. Proof and financial calls

```solidity
function proveOmission(
    bytes32 nonce,
    ReceiptEntry calldata left,
    ReceiptProof calldata leftProof,
    ReceiptEntry calldata right,
    ReceiptProof calldata rightProof,
    uint8 boundary
) external;

function proveMisanchoredReceipt(
    FairBindReceipt calldata receipt,
    bytes calldata signature,
    bytes32 anchoredLeaf,
    ReceiptProof calldata proof
) external;

function proveEquivocation(
    FairBindReceipt calldata first,
    bytes calldata firstSignature,
    FairBindReceipt calldata second,
    bytes calldata secondSignature
) external;

function claimEpochFailure(bytes32 nonce) external;
function claimRefund(bytes32 nonce) external;
function releasePurchase(bytes32 nonce) external;

function freezeSellerDeferred(bytes32 triggerNonce) external;
function releaseFrozen(uint32 bondId) external;
function claimRefund(
    bytes32 nonce,
    FairBindReceipt calldata receipt,
    bytes calldata receiptSignature,
    ReceiptProof calldata proof
) external;
function forfeitUnclaimed(uint32 bondId) external;
```

`releasePurchase` reverts with `FrozenEntry` for an entry in a frozen window,
with `NotSampled` for a sampled purchase whose case was never opened, and marks
a forfeited entry `FORFEITED` while paying only the deposits of its finished
case. The receipt overload of `claimRefund` pays the recorded buyer the entry's
own amount while the bond account is `CLAIM_OPEN` and `block.number <=
claimUntilBlock`, for an entry settled no later than the freeze block that is
`DEFERRED` or `RELEASABLE`; the receipt must be valid for the purchase record,
and an inclusion proof against the anchor root is required when the epoch was
anchored. `forfeitUnclaimed` requires `CLAIM_OPEN` and `block.number >
claimUntilBlock` (as extended by later confirmed failures) and forfeits only
the frozen window: entries settled after the freeze block during a reopened
window keep their schedule (ADR 0021). `releasePurchase` also reverts with
`FrozenEntry` for any entry of a bond account with a pending initial-`FAIL`
trigger. `releaseFrozen` requires `FROZEN` and a trigger case that
ended without a failure; when another initial-`FAIL` trigger of the account is
pending it re-anchors the freeze to the earliest one and emits
`FreezeReanchored` instead of releasing it. `freezeSellerDeferred` requires a
profile with `freezeOnInitialFail` and reverts with `InvalidTransition`
otherwise (ADR 0020). The freeze entry points take a `bondId` because the
freeze is kept per bond account; `freezeSellerDeferred` keeps its name.

`boundary` is `0` for an interior proof, `1` for a lower-bound proof, and `2` for
an upper-bound proof. Unused boundary entry and proof arguments are empty.
`proveOmission` takes the nonce of a settled purchase and the bounding listed
entries as `(nonce, receiptLeaf)` pairs with inclusion proofs against the
epoch's anchor; it needs no receipt or signature, so omission of any real
purchase is provable by anyone from the public list (`merkle-v1.md` section 4).
`proveMisanchoredReceipt` takes a seller-signed receipt, the anchored leaf at
its nonce and that entry's inclusion proof, and confirms the seller failure as
equivocation when the two leaves differ; a substituted receipt at the buyer's
own nonce is provable only by that buyer, because the proof needs its signed
receipt. Both proofs revert with `InvalidProof` before the epoch is anchored
or after the purchase's `retainUntil`.
Omission, misanchored-receipt and equivocation proofs are public. Only the recorded buyer receives a
refund. Anyone may trigger an epoch-failure claim, refund, or release, but the
destination cannot be supplied by the caller.

## 11. View types and required views

The following logical view structs are part of the interface. An implementation
may pack the corresponding storage, but it MUST return the same values and
widths.

```solidity
struct ServiceProfileView {
    uint32 profileId;
    bool active;
    address deploymentToken;
    ServiceProfileInput parameters;
}

struct SellerView {
    uint32 sellerId;
    uint32 profileId;
    address owner;
    address signingKey;
    bytes32 claimsHash;
    uint32 bondId;
    uint64 suspendedAtBlock;
    uint64 exitEligibleBlock;
    uint8 status;
}

struct BondView {
    uint32 bondId;
    uint32 profileId;
    address owner;
    uint256 balance;
    uint256 bucketBalancePpm;
    uint64 bucketUpdatedBlock;
    uint32 scaleFactor;
    uint32 registrations;
    uint32 failureCount;
    uint64 failureWindowStart;
    uint32 inconclusiveCount;
    uint32 judgedCount;
    uint64 inconclusiveWindowStart;
    uint64 exitEligibleBlock;
    uint256 deferredBalance;
    uint256 encumbered;
    bytes32 freezeNonce;
    uint64 freezeBlock;
    uint64 claimUntilBlock;
    uint64 forfeitedThrough;
    uint256 claimedTotal;
    uint256 forfeitedTotal;
    uint8 freezeState;
    uint8 status;
    bool sanctioned;
}

struct FrozenPoolView {
    uint32 bondId;
    uint8 freezeState;
    bytes32 triggerNonce;
    uint64 freezeBlock;
    uint64 claimUntilBlock;
    uint64 forfeitedThrough;
    uint256 poolBalance;
    uint256 encumbered;
    uint256 claimedTotal;
    uint256 forfeitedTotal;
}

struct VerifierView {
    uint32 verifierId;
    address owner;
    address signingKey;
    uint256 classBitmap;
    uint256 bond;
    uint256 lockedLiability;
    uint64 exitEligibleBlock;
    uint16 strikes;
    uint8 status;
}

struct PurchaseView {
    bytes32 nonce;
    bytes32 keyId;
    uint32 sellerId;
    uint32 profileId;
    address buyer;
    uint256 value;
    bytes32 requestHash;
    bytes32 claimsHash;
    uint24 epoch;
    uint64 settledBlock;
    uint64 responseDue;
    uint64 claimUntil;
    uint64 releaseBlock;
    uint64 retainUntil;
    uint8 financialState;
}

struct CaseView {
    bytes32 nonce;
    address requester;
    bytes32 bundleHash;
    bytes32 randomness;
    bytes32 evidenceHash;
    uint64 caseOpenedBlock;
    uint64 serveDue;
    uint64 challengeUntil;
    uint64 publishDue;
    uint64 randomBlock;
    uint64 judgeDue;
    uint64 evidenceDue;
    uint32 assignedVerifierId;
    uint16 publishedChunks;
    uint8 trigger;
    uint8 state;
    uint8 resumeState;
    uint8 reviewPath;
    uint8 requesterRole;
    uint8 stage;
    uint8 attempt;
    uint8 initialVerdict;
    uint8 finalVerdict;
}

struct AnchorView {
    bytes32 root;
    bytes32 randomness;
    bytes32 publicationHash;
    bytes32 verifierSetHash;
    uint256 totalEffectiveWeight;
    uint64 anchoredBlock;
    uint64 randomBlock;
    uint64 sealDeadline;
    uint64 sortitionVersion;
    uint32 profileId;
    uint32 count;
    uint8 state;
}

struct SellerQuote {
    uint32 sellerId;
    uint32 profileId;
    bytes32 claimsHash;
    address deploymentToken;
    uint96 maxPurchaseValue;
    uint256 bucketBalancePpm;
    uint32 remaining;
    uint64 quotedAtBlock;
    uint24 currentEpoch;
    uint8 sellerStatus;
    uint32 bondId;
}
```

`deferredBalance` is the sum of the bond account's entries that are neither
released, refunded, nor forfeited; `encumbered` is the part held by open cases
or owed as individual refunds. The frozen pool is `deferredBalance -
encumbered` while the account is `FROZEN` or `CLAIM_OPEN`, minus the deferred
and encumbered totals of the entries settled after `freezeBlock` during a
reopened claim window (`getClaimReentry`, ADR 0021); `getFrozenPool` reports
that window total and the window's encumbered part. `forfeitedThrough` is the
freeze block of the latest closed claim window.

`bucketBalancePpm` is the bond account's bucket. `remaining` is
`floor(bucketBalancePpm / PPM)` after applying refill through `quotedAtBlock`. It is an advisory whole-settlement count.

```solidity
function deriveKeyId(uint32 sellerId, address buyer, bytes16 idempotencyKey)
    external view returns (bytes32);

function deriveNonce(
    uint32 sellerId,
    uint32 profileId,
    bytes32 claimsHash,
    address buyer,
    bytes16 idempotencyKey,
    bytes32 requestHash
) external view returns (bytes32);

function purchaseByKey(bytes32 keyId) external view returns (bytes32 nonce);
function getDeadlineConfig(uint32 deadlineConfigId) external view returns (DeadlineConfig memory);
function getServiceProfile(uint32 profileId) external view returns (ServiceProfileView memory);
function getSeller(uint32 sellerId) external view returns (SellerView memory);
function getVerifier(uint32 verifierId) external view returns (VerifierView memory);
function getPurchase(bytes32 nonce) external view returns (PurchaseView memory);
function getCase(bytes32 nonce) external view returns (CaseView memory);
function getAnchor(uint32 sellerId, uint24 epoch) external view returns (AnchorView memory);
function isSampled(bytes32 nonce) external view returns (bool eligible, bool known);
function quoteSeller(uint32 sellerId) external view returns (SellerQuote memory);
function getBond(uint32 bondId) external view returns (BondView memory);
function getFrozenPool(uint32 bondId) external view returns (FrozenPoolView memory);
function getFreezeTriggers(uint32 bondId) external view returns (TriggerQueue memory);
function getClaimReentry(uint32 bondId) external view returns (ClaimReentry memory);
function getFailureWindowScale(uint32 bondId) external view returns (uint32);
function getRecentScaleHigh(uint32 bondId) external view returns (ScaleHigh memory);
function getLockedForfeit() external view returns (uint256);
function getReviewReseals(bytes32 nonce) external view returns (uint8);
function purchaseState(bytes32 nonce) external view returns (uint8);
function judgmentDelayBlocks(uint32 profileId) external view returns (uint256);
```

`getFreezeTriggers` returns the pending initial-`FAIL` triggers of a bond
account (ADR 0015) as `TriggerQueue { bytes32 head; bytes32 tail; uint32
count; }`: the earliest and latest pending case nonces in recording order and
their number. `head` and `tail` are zero when `count` is zero.

`getClaimReentry` returns `ClaimReentry { uint256 deferredBalance; uint256
encumbered; bool reopened; }`: whether a reinstatement reopened the account
during its open claim window, and the deferred and encumbered totals of the
entries settled after `freezeBlock` since; all three are zero outside an open
window and reset whenever `freezeBlock` moves. `getFailureWindowScale` returns
the scale, at least one, of the account's current failure window: at opening
the larger of the scale factor before the opening failure's deduction and the
recent scale high when its `dropBlock` is at most `retentionBlocks` old, raised
by a top-up during the window; the window sanctions at that times
`failureLimit` (ADR 0021, ADR 0022). `getRecentScaleHigh` returns `ScaleHigh {
uint32 scale; uint64 dropBlock; }`, the highest scale the account left through
a drop that is still recent and the block of its latest drop.
`getLockedForfeit` returns the total of forfeitures and seller deductions
locked in the contract; no function decreases it.
`getReviewReseals` returns one bit per `JudgmentStage` value whose review seal
was reopened.

`purchaseState` returns the stored financial state, except that it reports
`FROZEN_CLAIMABLE` for a `DEFERRED` or `RELEASABLE` entry of an open claim window
and `FORFEITED` for such an entry of a closed one.

`quoteSeller` returns profile identifiers, claims hash, current bucket estimate,
seller state, current block, and current epoch. It is advisory. `settle` repeats
all state-sensitive checks.

## 12. Events

The first three indexed fields are shown first when possible.

```solidity
event DeadlineConfigCreated(uint32 indexed deadlineConfigId, bytes32 configHash);
event ServiceProfileCreated(uint32 indexed profileId, uint16 indexed classId,
    bytes32 predicateId, bytes32 canonId, bytes32 parameterHash);
event ServiceProfileActivationChanged(uint32 indexed profileId, bool active);
event NewSettlementsPaused(bool paused, address indexed actor);
event GovernanceNominated(address indexed currentGovernance,
    address indexed nominee, uint64 acceptAfter);
event GovernanceChanged(address indexed previousGovernance,
    address indexed newGovernance);
event GuardianNominated(address indexed currentGuardian, address indexed nominee);
event GuardianChanged(address indexed previousGuardian, address indexed newGuardian);
event SellerRegistered(uint32 indexed sellerId, uint32 indexed bondId,
    uint32 indexed profileId, address owner, address signingKey, bytes32 claimsHash);
event BondRegistered(uint32 indexed bondId, uint32 indexed profileId, address indexed owner,
    uint256 balance, uint32 scaleFactor);
event BondScaled(uint32 indexed bondId, uint32 oldScaleFactor, uint32 newScaleFactor, uint256 balance);
event BondExitRequested(uint32 indexed bondId, uint64 eligibleBlock);
event BondExited(uint32 indexed bondId, address indexed owner, uint256 amount);
event SellerSuspended(uint32 indexed sellerId, uint32 indexed bondId, bytes32 indexed triggerNonce);
event SellerReinstated(uint32 indexed sellerId, uint32 indexed bondId, uint64 atBlock);
event SellerSanctioned(uint32 indexed sellerId, uint32 indexed bondId, uint32 failureCount, uint256 penalty);
event SellerDeferredFrozen(uint32 indexed bondId, uint32 indexed sellerId, bytes32 indexed triggerNonce,
    uint256 frozenTotal, uint64 frozenAtBlock);
event FrozenReleased(uint32 indexed bondId, bytes32 indexed triggerNonce, uint256 releasedTotal);
event FreezeReanchored(uint32 indexed bondId, bytes32 indexed releasedNonce, bytes32 indexed triggerNonce);
event ClaimWindowOpened(uint32 indexed bondId, bytes32 indexed triggerNonce, uint64 claimUntilBlock,
    uint256 poolBalance);
event FrozenClaimPaid(uint32 indexed bondId, uint32 indexed sellerId, bytes32 indexed nonce,
    address buyer, uint256 value);
event UnclaimedForfeited(uint32 indexed bondId, bytes32 indexed nonce, uint256 total,
    uint256 toVerifierPool, uint256 toReserve);
event InconclusiveRecorded(uint32 indexed sellerId, uint32 indexed bondId, bytes32 indexed nonce,
    uint32 inconclusiveCount, uint32 judgedCount, bool aboveThreshold);
event SellerExitRequested(uint32 indexed sellerId, uint64 eligibleBlock);
event SellerExited(uint32 indexed sellerId, address indexed owner, uint256 amount);
event VerifierRegistered(uint32 indexed verifierId, address indexed owner,
    address signingKey, uint256 classBitmap, uint256 bond);
event VerifierBondChanged(uint32 indexed verifierId, uint256 bond);
event VerifierClassesChanged(uint32 indexed verifierId, uint256 classBitmap);
event VerifierExitRequested(uint32 indexed verifierId, uint64 eligibleBlock);
event VerifierExited(uint32 indexed verifierId, address indexed owner, uint256 amount);
event VerifierTreeCheckpointed(uint32 indexed profileId, uint64 indexed version,
    bytes32 setHash, uint256 totalEffectiveWeight);
event Settled(bytes32 indexed nonce, bytes32 indexed keyId, uint32 indexed sellerId,
    uint32 bondId, uint32 profileId, address buyer, uint256 value, uint24 epoch,
    bytes32 requestHash, bytes32 claimsHash);
event Anchored(uint32 indexed sellerId, uint24 indexed epoch, bytes32 root,
    uint32 profileId, uint32 count, uint64 randomBlock, bytes32 publicationHash);
event EpochSealed(uint32 indexed sellerId, uint24 indexed epoch,
    bytes32 randomness, bytes32 verifierSetHash, uint64 sortitionVersion,
    uint256 totalEffectiveWeight);
event EpochFailed(uint32 indexed sellerId, uint24 indexed epoch, uint8 reason);
event ServeRequested(bytes32 indexed nonce, address indexed requester,
    uint64 caseOpenedBlock, uint64 deadline);
event Served(bytes32 indexed nonce, bytes32 bundleHash, uint64 challengeUntil);
event ServeAccepted(bytes32 indexed nonce, address indexed requester);
event ServeEscalated(bytes32 indexed nonce, uint64 publishDue);
event PublicationStarted(bytes32 indexed nonce, bytes32 responseHash,
    uint16 chunkCount, uint32 totalBytes);
event PublicationChunk(bytes32 indexed nonce, uint16 indexed index, uint32 bytesWritten);
event ResponsePublished(bytes32 indexed nonce, bytes32 responseHash,
    uint16 chunkCount, uint32 totalBytes);
event CaseOpened(bytes32 indexed nonce, uint8 trigger, address requester, uint256 heldValue);
event VerifierAssigned(bytes32 indexed nonce, uint8 stage, uint8 attempt,
    uint32 indexed verifierId, uint64 deadline);
event VerdictSubmitted(bytes32 indexed nonce, uint8 stage, uint32 indexed verifierId,
    uint8 verdict, bytes32 evidenceHash);
event EvidenceRequested(bytes32 indexed nonce, uint8 stage, uint8 attempt,
    uint64 evidenceDue);
event EvidenceDisclosed(bytes32 indexed nonce, uint8 stage, uint8 attempt,
    bytes32 evidenceHash);
event ReviewSelected(bytes32 indexed nonce, bool partyAppeal, bool autoSelected,
    uint64 randomBlock);
event ReviewResealed(bytes32 indexed nonce, uint8 stage, uint64 randomBlock);
event CaseFinalized(bytes32 indexed nonce, uint8 finalVerdict, uint8 financialState);
event DepositResolved(bytes32 indexed nonce, uint8 indexed depositType,
    address indexed recipient, uint256 amount);
event Refunded(bytes32 indexed nonce, address indexed buyer, uint256 value, uint8 source);
event Released(bytes32 indexed nonce, uint32 indexed sellerId, uint256 value);
event Slashed(uint8 indexed actorType, uint32 indexed actorId, bytes32 indexed nonce,
    address recipient, uint256 amount, uint8 reason);
```

## 13. Custom errors

Version 1 fixes the following no-argument error selectors. Diagnostic identifiers
and values remain available from call inputs, views, and events.

```solidity
error Unauthorized();
error ZeroAddress();
error InvalidConfiguration();
error Paused();
error UnknownDeadlineConfig();
error UnknownProfile();
error ObjectAlreadyExists();
error InactiveProfile();
error InvalidProfile();
error UnsupportedServiceClass();
error ServiceClassUnavailable();
error SellerInactive();
error VerifierInactive();
error InsufficientSellerBond();
error InsufficientVerifierBond();
error LiabilityExceeded();
error ExitNotReady();
error KeyAlreadyUsed();
error NonceAlreadyUsed();
error ProfileMismatch();
error ClaimsMismatch();
error NonceMismatch();
error AuthorizationMismatch();
error AuthorizationExpired();
error ValueTooLarge();
error RateLimitExceeded();
error AnchorTooEarly();
error AnchorWindowClosed();
error CountMismatch();
error InvalidRandomnessWindow();
error NotSampled();
error ClaimWindowClosed();
error ResponseTooLarge();
error EvidenceTooLarge();
error InvalidReceipt();
error InvalidSignature();
error InvalidProof();
error InvalidPublication();
error IneligibleVerifier();
error AssignmentExhausted();
error DeadlineNotReached();
error DeadlinePassed();
error InvalidTransition();
error AlreadyFinalized();
error TransferFailed();
error BondNotActive();
error BondMismatch();
error SellerIsSuspended();
error FrozenEntry();
error ClaimWindowNotOpen();
error AlreadyClaimed();
error ReceiptOutOfWindow();
error PoolExhausted();
error ReinstateConditionsUnmet();
```

`SellerIsSuspended` rejects a settlement for a `SUSPENDED` seller;
`BondNotActive` rejects a settlement or registration whose bond account is not
`ACTIVE`, is sanctioned, is frozen, or holds less than `sellerPenalty`, and a
settlement whose bond account has a pending initial-`FAIL` trigger.
`UnclaimedForfeited` is emitted once per forfeiture with `nonce` equal to the
trigger for a pool and to the purchase for an entry forfeited when its own case
ends. It carries the total; `toVerifierPool` and `toReserve` are zero, since
the amount stays locked in the contract (ADR 0022). It is the only event a
forfeiture emits: a forfeiture is not a penalty of one actor, so
`forfeitUnclaimed` emits no `Slashed`.

`Slashed` reports a penalty charged to one actor and paid to one recipient:
`actorType` 1 (seller), whose recipient is the contract itself because the
deduction stays locked (ADR 0022), with the seller ID and `reason` 4 (the share
`sellerPenalty / failureLimit` deducted on a confirmed failure below the
limit) or `reason` 1 (the remainder charged when the window's threshold,
`failureWindowScale * failureLimit`, is reached, so that the window charges
`failureWindowScale * sellerPenalty`; ADR 0021), or `actorType` 2 (verifier)
with the verifier ID and `reason` 2 (late) or 3 (wrong verdict).
`SellerSanctioned.penalty` is the remainder charged by the terminal failure
(ADR 0018).

`ReviewResealed` reports the first unavailable randomness of a review stage:
the stage (`JudgmentStage`) and its `randomBlock`, unchanged since ADR 0025
(ADR 0021).
`SellerDeferredFrozen` is also emitted when a confirmed failure moves the
freeze block of an open claim window, with the new `frozenAtBlock`.

An implementation may add errors for internal assertions. It MUST use the
listed error when the corresponding public precondition fails.

## Independent buyer recovery extension (ADR 0008)

When dispute(NON_DELIVERY) finds an existing case it opens getBuyerRecovery(nonce)
instead of replacing that case. The following selectors use the independent
record and retain the argument shapes of the corresponding legacy serve and
publication calls: buyerServed, acceptBuyerServe, finalizeBuyerServed,
escalateBuyerServe, timeoutBuyerServe, publishBuyerResponse,
beginBuyerPublication, publishBuyerChunk, finalizeBuyerPublication.
getBuyerRecovery(bytes32) returns CaseView. These are explicit separate selectors;
they do not change the semantics of a verifier's legacy delivery calls.

## ADR 0009 deployment and inspection

The fixed router constructor receives address[8] modules: the existing six followed by Judgment and Review. getCase retains its original tuple. Supplemental getReview(nonce), getAssignments(nonce), getVerifierCapital(id), and verdictDigest(verdict) expose appended state and the existing EIP-712 verdict format. requestEvidence remains limited to the active initial assignment; while evidence is pending no appeal or finalization is permitted.

Supplemental records use these exact fields in order:

```solidity
struct ReviewData { uint64 appealUntil; uint8 autoVerdict; address appellant; uint256 deposit; }
struct AssignmentData {
    uint32 verifierId; uint8 stage; uint8 attempt; uint8 verdict;
    bool released; bool serveUsed; bool evidenceRequested; bool evidenceDisclosed;
    bytes32 evidenceHash; uint256 liability; uint256 penaltyReserve;
}
struct VerifierCapital { uint256 reservedPenalties; uint256 conservativeCap; uint32 conservativeFraction; }
```
The original CaseView ABI is retained. An assignment history entry persists after
release so receipt/verdict replay and participant exclusions remain auditable.

## ADR 0024 entry points and views

The router adds these entry points; no existing entry changes.

| Entry point | Module | Rule |
| --- | --- | --- |
| `setProfileTerms(uint32 profileId, bytes32 termsHash, uint32 detectFloorPpm, uint96[] valueCaps, SalesTier[] tiers)` | registry, governance only | once, on a profile never active, against `termsHash` (ADR 0025); `profile-v1.md` sections 9 and 9.1 |
| `registerBondWithTerms(uint32 profileId, uint128 amount, uint96 sampleScaleValue, uint8 tier) returns (uint32)` | bond | the only way to open an account under a profile with terms; `registerBond` reverts `InvalidConfiguration` there |
| `setBondTerms(uint32 bondId, uint96 sampleScaleValue, uint8 tier)` | bond, owner only | design 2 rule D2-14 |
| `submitSampleReceipt(bytes32 nonce, FairBindReceipt receipt, bytes receiptSignature, ReceiptProof proof)` | settlement | anyone, until `sampleReceiptDue` |
| `timeoutSampleReceipt(bytes32 nonce)` | settlement | public progress call after `sampleReceiptDue` |

`SalesTier` is `(uint32 salesLimit, uint32 bucketCapacity, uint32
refillPpmPerBlock, uint32 failureLimit, uint32 sanctionLimit)`: the unit bond
is `failureLimit * b` (prefunded failures) and a failure window of scale `n`
sanctions at `n * sanctionLimit` failures, never when `sanctionLimit` is zero
(ADR 0027). Views: `getProfileTerms(profileId)`,
`getBondTerms(bondId)` (`sampleScaleValue`, `tier`, `peakCap`, `peakUntil`,
`peakLimit`, `peakLimitUntil`, `windowLimit`), `unitBond(bondId)`,
`getSettledSamplePpm(nonce)` and `getSampleReceiptDue(nonce)`. Events:
`ProfileTermsSet`, `BondTermsSet` and `SampleReceiptRecorded`. `quoteSeller`
reports the account's value cap as `maxPurchaseValue` under a profile with
terms.

The read functions that the core contract held (`deriveKeyId`, `deriveNonce`,
`purchaseByKey`, the `get*` views, `isSampled`, `quoteSeller`,
`receiptDigest`, `canonicalRequestHash`, `getBuyerRecovery`) are compiled into
the router only; their ABI is unchanged.

## ADR 0025 entry points, views and the lens module

`setProfileTerms` takes `termsHash` after `profileId` (above) and
`ProfileTerms` gains `termsHash`; `ProfileTermsSet(uint32 indexed profileId,
bytes32 termsHash, uint32 detectFloorPpm, uint96[] valueCaps, SalesTier[]
tiers)` replaces the ADR 0024 event. Both were added by ADR 0024 and are not
deployed.

New views: `getCheckpointHeadroom(uint32 profileId, uint64 version) returns
(uint96[])`, the liability room of each verifier of a checkpoint at its block
in the order of `verifierIds` (`sortition-v1.md` section 2), and
`getReviewResealDue(bytes32 nonce) returns (uint64)`, the last block of the
reopened seal window of the current review stage. New event:
`VerifierHeadroomCheckpointed(uint32 indexed profileId, uint64 indexed version,
uint96[] headroom)`, emitted with `VerifierTreeCheckpointed`.

The read functions run in a tenth module, `FairBindLens` (`MODULE_KIND = 10`,
router getter `lensModule()`, constructor array `address[10]`). The router
keeps every read selector with its ABI; a read forwards its call data to the
router itself by `staticcall`, prefixed with
`bytes4(keccak256("fairbind/lens/v1"))`, and the router's fallback delegates
only such a self-call to the lens. Any other unknown selector reverts.
`canonicalRequestHash`, which is `pure`, stays in the router. The lens rejects
direct calls like every module.

## ADR 0028 waiting cases

`assignVerifier(bytes32 nonce)` keeps its signature. On a case in
`WAITING_ASSIGNMENT` it redraws (`sortition-v1.md` section 5.1, anyone,
`InvalidTransition` without a checkpoint written after the case's last search,
`DeadlineNotReached` before the redraw block has passed); on a case in
`ASSIGNING` it is unchanged; in any other state it reverts
`InvalidTransition`.

New view: `getAssignmentWait(bytes32 nonce) returns (AssignmentWait)` with

```solidity
struct AssignmentWait {
    uint64 checkpointVersion; // version of the case's last search; 0 if it never waited
    uint64 searchBlock;       // block of that search
    uint32 redraws;           // redraw calls that used a checkpoint
    bytes32 randomness;       // value of the last redraw
}
```

New event: `AssignmentWaiting(bytes32 indexed nonce, uint8 attempt, uint64
checkpointVersion)`, emitted each time a case enters or stays in
`WAITING_ASSIGNMENT`. A redraw that assigns emits `VerifierAssigned` as before.
The storage mapping `assignmentWaits` is appended after every existing slot.

## ADR 0029 epoch value and release clock

`seal(uint32 sellerId, uint24 epoch)` and `timeoutSeal(uint32 sellerId,
uint24 epoch)` keep their signatures. `seal` no longer reverts
`DeadlinePassed` after `sealDeadline`; it reverts `InvalidRandomnessWindow`
when `blockhash(randomBlock)` is zero or no longer served, and leaves the
epoch `ANCHORED`. `timeoutSeal` is the checkpoint-shortage exit: it reverts
`DeadlineNotReached` through the anchor deadline and `InvalidTransition` when
the epoch's checkpoint holds at least `minVerifiers` verifiers; otherwise it
sets `EPOCH_FAILED` and emits `EpochFailed(sellerId, epoch,
VERIFIER_SET_UNAVAILABLE)`.

`releasePurchase` reverts `DeadlineNotReached` while `block.number -
pausedSince(bondId, settledBlock) < releaseBlock`. `finalizeBondExit` reverts
`ExitNotReady` while `block.number - pausedSince(bondId, exitEligibleBlock -
retentionBlocks) < exitEligibleBlock`.

New views:

```solidity
// waitingCases: cases of the account in WAITING_ASSIGNMENT; pauses: pause
// intervals recorded; pausedTotal: paused blocks before this block.
function getReleaseClock(uint32 bondId)
    external view returns (uint32 waitingCases, uint32 pauses, uint64 pausedTotal);
// Paused blocks of the account from fromBlock up to this block.
function pausedSince(uint32 bondId, uint64 fromBlock) external view returns (uint64);
```

New events: `ReleaseClockPaused(uint32 indexed bondId, uint64 pausedBefore)`
when the first case of the account starts to wait, and
`ReleaseClockResumed(uint32 indexed bondId, uint64 pausedTotal)` when the last
one stops waiting. The storage mappings `releaseClocks` (one slot per account:
`waitingCases`, `pauses`) and `pauseLog` (one slot per pause: `start`, `end`,
`pausedBefore`) are appended after every existing slot. No purchase field or
slot changes.

## ADR 0030 narrow freeze

A confirmed failure tied to the purchase settled in block c freezes the
entries settled from c through the failure block; earlier entries keep their
schedule. The start c is the purchase's settlement block, the first block of
the epoch for a missed anchor, and the settlement block of the first
inconclusive case of the window for an inconclusive window above its
threshold. The frozen window is the ordered list of disjoint spans
`freezeSpans[bondId]`; a later failure lowers the start (any status) or, in
`CLAIM_OPEN`, adds `[c, block]` merged with every span it meets. `freezeBlock`
is the end of the last span.

`releasePurchase` reverts `FrozenEntry` only for an entry in a span (or of an
account with a pending initial-`FAIL` trigger). The frozen-pool `claimRefund`
reverts `ReceiptOutOfWindow` for an entry outside every span.
`forfeitUnclaimed` moves the spans to `forfeitWindows[bondId]`; it forfeits
one sum as before when the window is one span and `deferredFloor[bondId]` is
at or after its start and no itemized window is pending, and closes
*itemized* otherwise: each unclaimed entry of an itemized window is reported
`FORFEITED` and leaves `deferredBalance` into `lockedForfeit` when
`releasePurchase` touches it. `getFrozenPool().poolBalance` is an upper bound
of the pool while earlier entries are unreleased.

```solidity
struct FreezeSpan { uint64 from; uint64 through; }
struct ForfeitWindow { uint64 from; uint64 through; bool itemized; }
function getFreezeSpans(uint32 bondId) external view returns (FreezeSpan[] memory);
function getForfeitWindows(uint32 bondId) external view returns (ForfeitWindow[] memory);
event FreezeSpanSet(uint32 indexed bondId, uint256 index, uint64 from, uint64 through);
```

The storage mappings `freezeSpans`, `forfeitWindows`, `deferredFloor`,
`itemizedPending` and `inconclusiveFloor` are appended after every existing
slot. No purchase field or slot changes.

## ADR 0031 request-based randomness

A source that answers `responseBlocks()` is request based
(`IVrfRandomness`). Its requests are identified by
`keccak256(abi.encode(kind, input))`, kind SAMPLE = 1, ASSIGN = 2, AUX = 3,
with VRF input `abi.encode("FairBind/vrf/v1", chainid, consumer, kind,
input)`. SAMPLE input is `abi.encode(uint32 profileId, uint64 A)`; the AUX
input of a redraw is `abi.encode(keccak256("FairBind/redraw/v1"), nonce,
uint8(1), uint32 redraw, uint64 t)`.

```solidity
function requestSampleValue(uint32 profileId, uint24 epoch) external;   // A < block <= A + D_S + T_V
function registerRedraw(bytes32 nonce) external;                        // waiting case, checkpoint on chain
function requestRedrawValue(bytes32 nonce) external;                    // block > t
function timeoutRedrawValue(bytes32 nonce) external;                    // block > first request + D_V + T_V
function getRandomnessKind() external view returns (bool vrf);
function getRedrawUse(bytes32 nonce) external view returns (SamplingStore.RedrawUse memory);
event RedrawRegistered(bytes32 indexed nonce, uint32 redraw, uint64 checkpointVersion, uint64 registeredBlock);
event RedrawValueTimedOut(bytes32 indexed nonce, uint32 redraw);
error RequestTooEarly();
error NotRegistered();
```

`seal` of an epoch anchored under a request-based source takes the SAMPLE
value stored by `A + D_S + T_V` and reverts `InvalidRandomnessWindow`
otherwise. `assignVerifier` on a waiting case reverts `NotRegistered` without
a registered use and `DeadlineNotReached` until its AUX value is stored.
The sampling store appends `RandomnessConfig.vrf` in the slot of the source
and the mapping `redrawUses`.
`seal`, `timeoutSeal` and `timeoutAnchor` run in the publication module and
`setRandomness` in the registry module; the router's selectors are unchanged.

## ADR 0032 batches, slots and queues

The router runs every selector it does not declare in the extension module
that declared it in `selectors()`; `setExtensions(address[])` installs the
modules once (governance; module i reports `MODULE_KIND() == 11 + i`, the
deployment's token, treasury and reward pool, and `hookOps()`, the bitmask of
the hook operations it implements). Modules reach extension code only
through `hook(uint256 op, uint256 arg)` inside their own calls; the router
does not route `hook`. Module 11 `FairBindBatch`, 12 `FairBindBatchAdmin`, 13
`FairBindProof`, 14 `FairBindDeposit`. All new state is in `BatchStore` at
slot `keccak256("fairbind.batch.store.v1")`; the core layout is unchanged.

```solidity
struct Terms { bool batched; uint32 assignDelay; uint32 keeperSlack; uint32 depositPpm; uint32 auditPpm;
    uint32 contestBlocks; uint32 sideGainPpm; uint96 slotValue; bytes32 termsHash; }
// termsHash = keccak256(abi.encode(keccak256("fairbind/batch-terms/v1"), profileId, assignDelay,
//     keeperSlack, depositPpm, auditPpm, contestBlocks, sideGainPpm, slotValue, source,
//     keccak256(publicKey), uint256(D_V), uint256(T_V)))
function setExtensions(address[] calldata list) external;                 // governance, once
function setBatchTerms(uint32 profileId, Terms calldata t) external;      // governance, never-active profile
function checkpointAt(uint32 profileId, uint24 epoch) external returns (uint64 version); // block > A_e
function requestAssignValue(uint32 profileId, uint24 epoch) external;     // block > C_e; input (profileId, epoch)
function assignBatch(uint32 profileId, uint24 epoch) external;            // value stored
function markAssignLate(uint32 profileId, uint24 epoch) external;         // block > C_e + assignDelay, no value
function timeoutAssignValue(uint32 profileId, uint24 epoch) external;     // block > first request + D_V + T_V
function requestLateValue(bytes32 nonce) external;                        // block > opening block t
function assignLate(bytes32 nonce) external;
function timeoutLateValue(bytes32 nonce) external;
function transferQueued(bytes32 caseId) external;
function withdrawVerifierBond(uint32 verifierId, uint128 amount) external;
function getBatchTerms(uint32 profileId) external view returns (Terms memory);
function getBatch(uint32 profileId, uint24 epoch) external view returns (bytes32 value, uint64 valueBlock,
    uint64 checkpointVersion, bool assigned, bool exited, bytes32[] memory cases);
function getBatchEntry(bytes32 caseId) external view returns (BatchStore.Entry memory);
function getQueue(uint32 verifierId) external view returns (bytes32[] memory);
function getSlots(uint32 verifierId) external view returns (BatchStore.Slots memory, uint256 slots);
function verifierStateAt(uint32 verifierId, uint64 x) external view returns (uint96 bond, uint8 status, uint64 classes);
function batchClose(uint32 profileId, uint24 epoch) external view returns (uint256);
function batchOf(uint32 profileId, uint64 atBlock) external view returns (uint24);
function proofCaseId(bytes32 nonce) external pure returns (bytes32);
```

`C_e = A_e + 1 + D_S + sealBlocks + openBlocks`. `CaseState` appends
`QUEUED` (15, waiting in a verifier queue) and `BATCHED` (16, waiting for the
batch or late value). For a batched profile `checkpointVerifierTree` reverts
`InvalidTransition`, `seal` reverts `ServiceClassUnavailable` without the
checkpoint of `A_e`, and `timeoutSeal` reverts `DeadlineNotReached` while that
checkpoint can still be written. The ticket of round r is
`keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, caseId, stage,
attempt, r)) mod totalEffectiveWeight`. The queue key is `(batch << 232) |
(rank << 200) | (uint64(keccak256(abi.encode(keccak256("fairbind/batch-permutation/v1"),
batchValue, bondId))) << 136) | (firstTicket >> 120)`. A late case's input is
`abi.encode(keccak256("FairBind/late/v1"), nonce, uint8(1), uint32(0), uint64 t)`.
`finalizeVerifierExit` also needs an empty queue. With a request-based source
set, `createServiceProfile` takes `beaconDelayBlocks >= D_S`.

## ADR 0033 proportional appeal deposit

```solidity
function appealWithLimit(bytes32 nonce, uint256 maxDeposit) external;     // buyer, initial PASS
function appealDepositOf(bytes32 nonce) external view returns (uint256 deposit, uint256 heldHigh);
error DepositAboveLimit();
event AppealDepositSet(bytes32 indexed nonce, uint256 deposit, uint256 heldHigh);
```

The deposit is `max(appealDeposit, ceil(depositPpm * H / 1e6))`, `H` the high
mark of the account's deferred balance at the end of the previous block over
the current and the previous window of `deferBlocks`. `appeal` reverts
`InvalidTransition` for a buyer's appeal of a PASS under a non-zero
`depositPpm`. A failed appeal pays `appealDeposit` to the seller and locks the
rest (`DepositResolved` type 4).

## ADR 0034 seller proofs

```solidity
function setProofsOff(uint32 bondId, bool off) external;
function submitProof(bytes32 nonce, FairBindReceipt calldata receipt, bytes calldata receiptSignature,
    ReceiptProof calldata proof, bytes calldata evidence) external;
function activateProof(bytes32 nonce) external;
function voidReservation(bytes32 nonce) external;
function requestAuditValue(bytes32 nonce) external;                       // block > t
function drawAudit(bytes32 nonce) external;
function timeoutAuditValue(bytes32 nonce) external;
function contestProof(bytes32 nonce) external;                            // deposit: the entry's value
function confirmProof(bytes32 nonce) external;
function judgeProof(bytes32 nonce, uint8 verdict, bytes calldata signature) external;
function timeoutProofJudge(bytes32 nonce) external;
function releaseProven(bytes32 nonce) external;
function distributeCompensation(uint32 bondId) external;
function claimCompensation(bytes32 nonce) external;
function noteSampleDeadline(uint32 sellerId, uint24 epoch) external;
function proofVerdictDigest(bytes32 nonce, uint8 verdict) external view returns (bytes32);
function getProof(bytes32 nonce) external view returns (BatchStore.Proof memory);
function getProofAccount(uint32 bondId) external view returns (BatchStore.ProofAccount memory);
function getPool(uint32 bondId) external view returns (BatchStore.Pool memory);
function proofBondOf(bytes32 nonce) external view returns (uint256);
function proofReady(bytes32 nonce) external view returns (bool);
```

The proof bond is `ceil(v (1e6 - x1) / x1)`, `x1 = auditPpm * p0 / 1e6`. The
audit input is `abi.encode(keccak256("FairBind/audit/v1"), nonce, uint8(0),
uint32(1), uint64 t)`; the audit draws `keccak256(abi.encode(
keccak256("fairbind/audit/v1"), value, nonce)) < threshold(auditPpm)`. The
verdict digest is EIP-712 over `FairBindProofVerdict(bytes32 nonce,uint8
attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)`. A held proof
entry is `HELD`; `forfeitUnclaimed` reverts `DeadlineNotReached` while the
account has an undecided proof or reservation.

## ADR 0035 side-gain deposit

```solidity
function recordEpochOpenCount(uint32 profileId, uint24 epoch) external returns (uint32 count);
function depositSideGain(uint32 bondId, uint128 amount) external;
function withdrawSideGain(uint32 bondId, uint128 amount) external;        // no open sale
function clearSideGain(bytes32 nonce) external;
function rerequestSampleValue(uint32 profileId, uint24 epoch) external;   // block > M; input (profileId, A, 1)
function getSideGain(uint32 bondId) external view returns (BatchStore.SideGain memory);
```

`settle` of a side-gain profile reverts `ServiceClassUnavailable` below the
epoch's opening count and `InsufficientSellerBond` below `ceil(eta V / p0)
(open + 1)`. `seal` takes the repeated request's value when the first
request's was not stored by `M`.

## ADR 0036 review values and late-value pauses

```solidity
struct ReviewUse { uint8 stage; uint64 registered; }
function requestReviewValue(bytes32 nonce) external;                      // block > registered
function assignReview(bytes32 nonce) external;
function timeoutReviewValue(bytes32 nonce) external;                      // block > first request + D_V + T_V
function markValueLate(bytes32 nonce) external;                           // late or review AUX, block > t + D_S
function markSampleLate(uint32 sellerId, uint24 epoch) external;          // block > A + D_S
function getReviewUse(bytes32 nonce) external view returns (BatchStore.ReviewUse memory);
event ReviewUseRegistered(bytes32 indexed nonce, uint8 stage, uint64 registered);
event ReviewValueTimedOut(bytes32 indexed nonce, uint8 stage);
event ValueWaitPaused(bytes32 indexed nonce, uint64 from);
event SampleWaitPaused(uint32 indexed sellerId, uint24 indexed epoch, uint64 from);
```

A review stage of a batched profile registers its use in the block of the
appeal, the recheck selection or the verdict that leads to the tiebreak; its
input is `abi.encode(keccak256("FairBind/review/v1"), nonce, uint8 stage,
uint32(0), uint64 t)`. For such a stage `sealReviewRandomness` reverts
`InvalidTransition`, and so does `finalizeCase` while the stage has no
verifier. `markAssignLate` pauses from `C_e + assignDelay + 1`. `BatchStore`
appends `reviewUses` and `samplePaused`; hook operation 10 runs in module 14
and 11 in module 13; `markValueLate` is declared by module 11 and
`markSampleLate` by module 13.

## ADR 0037 receipt signatures, PASS proofs and measured costs

```solidity
// ExchangeStore.Input: mode, priceCap, gFixTx, gFixCall, bEnv, gasPriceCap, l1PriceCap, pubGas, pubBytes,
// keyGas, keyBytes, keyCap, blockGasShare, bundleBlocks, keyBlocks, disputeSlack, postSlack, confirmBlocks,
// g1271, padLength, sigLimit, proofBlocks, refWindow, freshWindow, settleSlack, maxSkew, verifier, feedId,
// maxUpdateBytes, tolerancePpm, toleranceAbs, tag, termsHash
struct Post { bytes32 nonce; bytes32 ctHash; bytes32 ekHash; bytes32 rHash; bytes32 leaf; bytes buyerSig; }
struct Match { bytes32 nonce; bytes32 ctHash; bytes32 ekHash; bytes32 rHash; bytes32 leaf; uint32 unit; uint32 position; bytes32[] siblings; }
struct PassProof { bytes32 ek; bytes ct; uint64 issuedAt; bytes update; bytes buyerSig; bytes sellerSig; }
function setExchangeTerms(uint32 profileId, ExchangeStore.Input calldata x) external;      // governance, once, inactive profile
function exchangeTermsHash(uint32 profileId, ExchangeStore.Input calldata x) external pure returns (bytes32);
function requireExchangeTerms() external;                                                  // governance, once: activation needs exchange terms
function postReceipt(Post calldata post, bytes calldata sellerSig) external;               // block <= A_e of the purchase
function postReceipts(Post[] calldata posts, bytes calldata sellerSig) external;           // one seller; failing nonces skipped
function matchAnchor(Match[] calldata matches) external;                                   // block <= A_e
function refundUnbound(bytes32 nonce) external;                                            // block > A_e, not bound
function discloseKey(bytes32 nonce, bool recovery, bytes32 ek, bytes calldata ct, bytes32 leaf) external; // VOTE_SIG ladder
function openProofSample(bytes32 nonce) external;                                          // PROOF, bound and sampled
function openProofDispute(bytes32 nonce, uint8 kind) external;                             // buyer, kind 2 or 3, deposit d0
function prove(bytes32 nonce, uint8 flags, PassProof calldata q) external;                 // flags 0 PASS, 2 FAIL
function proveAbsence(bytes32 nonce, bytes calldata update) external;
function timeoutProof(bytes32 nonce) external;                                             // block > due
function selfProve(bytes32 nonce) external;                                                // seller, proven purchase
function activateSelfProof(bytes32 nonce) external;
function voidSelfProof(bytes32 nonce) external;
function releaseSelfProven(bytes32 nonce) external;                                        // age > retainUntil
function getExchangeTerms(uint32 profileId) external view returns (ExchangeStore.Terms memory);
function getExchangeRecord(bytes32 nonce) external view returns (bytes32 bundle, ExchangeStore.Record memory, ExchangeStore.Ladder memory);
function receiptSignatureDigest(bytes32 nonce, bytes32 ctHash, bytes32 ekHash, bytes32 rHash, bytes32 leaf) external view returns (bytes32);
function postDigest(Post calldata post) external view returns (bytes32);
function postListDigest(uint32 profileId, bytes32 listHash, uint256 count) external view returns (bytes32);
function proofCommitment(bytes32 nonce) external view returns (bytes32);
function selfProofReady(bytes32 nonce) external view returns (bool);
```

The L1 share of a measured cost is `GasPriceOracle(0x42..0F).getL1FeeUpperBound(|xhat| + bEnv)`,
less `getL1FeeUpperBound(bEnv)` for a later measured call of the same
transaction; `bEnv` bounds the unsigned envelope bytes outside the call data,
the signature excluded. `setServiceProfileActive(id, true)` reverts
`InvalidProfile` for a profile with exchange terms when that call does not
answer, and, after `requireExchangeTerms`, for a profile without exchange
terms. `setBatchTerms` reverts `InvalidProfile` under a PROOF profile, and
with `sideGainPpm != 0` under a VOTE_SIG profile. `setExchangeTerms` reverts
`InvalidProfile` unless 0 < `bindWindow` <= `retentionBlocks`; activation
reverts `InvalidProfile` when `bindWindow` is below the value wait plus
`bindSlack`, below L_F + `marginBlocks` - 1 or not below `retentionBlocks`,
and, for a batched profile, when `retentionBlocks` < L_F + `marginBlocks` or
(6 * `maxAssignments` + 4) * `keeperSlack` > `marginBlocks` - 1 or `keeperSlack` > `sealBlocks` - 2 with `sealBlocks` <= 255 (ADR 0037 12).

Signatures use the domain `EIP712Domain(string name,string version,uint256
chainId,address verifyingContract,bytes32 salt)` with name `FairBind`,
version `1` and the profile's parameter hash as salt. The buyer signs
`FairBindReceiptSignature(address seller,bytes32 nonce,bytes32 ctHash,bytes32
ekHash,bytes32 responseHash,bytes32 leaf)` with `seller` the registered
signing key; the seller signs `FairBindReceiptPost(bytes32 nonce,bytes32
ctHash,bytes32 ekHash,bytes32 responseHash,bytes32 leaf)` or
`FairBindReceiptPostList(bytes32 listHash,uint256 count)`, `listHash` the
keccak256 of the concatenated 160-byte items. `ekHash = keccak256(ek)`,
`ctHash = keccak256(ct)`, `|ct| = padLength + 32`; plaintext block i is ct
xor `keccak256(ek, nonce, i)`; `rHash = keccak256(tag || plaintext)`. A PASS
proof's receipt is the purchase's receipt with `responseHash = rHash`,
`predicateCommitment = keccak256(abi.encode(uint64 validAfter,
sourceSetHash, policyHash))` and the given `issuedAt`. `CaseState` appends
`PROOF_WAIT` (17); `RefundSource` appends `DISPUTE_REFUND` (7) and `UNBOUND`
(8). Errors `NotBound`, `NonCanonical` (core), `ProofNotAllowed`,
`ProofNotPass`, `GasBelow1271Bound` (modules 15 to 17). `settle` of a PROOF
profile reverts `AuthorizationExpired` when `validAfter` is more than
`refWindow` seconds old; `dispute` and `openSample` revert for PROOF
profiles; `openSample` and `releasePurchase` revert `NotBound` for an
unbound purchase of a receipt-signature profile. Hooks 25 and 26 run in
modules 17 and 15. The GasPriceOracle is read at
`0x420000000000000000000000000000000000000F` when it has code.
