// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import { FairBindMerkle } from "./FairBindMerkle.sol";
import { IRandomness } from "./randomness/IRandomness.sol";
import { IVrfRandomness } from "./randomness/IVrfRandomness.sol";
import { SamplingStore } from "./modules/SamplingStore.sol";
import { BatchStore } from "./modules/BatchStore.sol";
import { ExchangeStore } from "./modules/ExchangeStore.sol";
import { Rule8Store } from "./modules/Rule8Store.sol";
import { FairBindDesign2 } from "./FairBindDesign2.sol";

interface IFairBindToken {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function receiveWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external;
}

abstract contract FairBindCore {
    uint32 public constant PPM = 1_000_000;
    uint32 public constant RESPONSE_CHUNK_BYTES = 16_384;
    bytes32 public constant KEY_DOMAIN = keccak256("fairbind/key/v1");
    bytes32 public constant PURCHASE_DOMAIN = keccak256("fairbind/v1");
    bytes32 public constant EPOCH_NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");
    bytes32 public constant SAMPLE_DOMAIN = keccak256("fairbind/sample/v1");
    bytes32 public constant ASSIGN_DOMAIN = keccak256("fairbind/verifier/v1");
    bytes32 public constant VERIFIER_SET_DOMAIN = keccak256("fairbind/verifier-set/v1");
    bytes32 public constant HTTP_CANON_DOMAIN = keccak256("fairbind/http-canon/v1");
    bytes32 public constant RESPONSE_NODE_DOMAIN = keccak256("fairbind/response-node/v1");
    bytes32 internal constant PROFILE_TERMS_DOMAIN = keccak256("fairbind/profile-terms/v1");
    bytes32 public constant RECEIPT_TYPEHASH = keccak256(
        "FairBindReceipt(uint8 version,uint32 sellerId,uint32 profileId,bytes32 nonce,bytes32 requestHash,bytes32 responseHash,bytes32 claimsHash,bytes32 predicateCommitment,uint24 epoch,uint64 issuedAt)"
    );
    bytes32 public constant EIP712_DOMAIN_TYPEHASH = keccak256(
        "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
    );
    /// Admission floor for beaconDelayBlocks: 128 L1 blocks of twelve seconds
    /// on a two-second settlement chain (profile-v1 section 2).
    uint32 internal constant MIN_BEACON_DELAY_BLOCKS = 768;
    // Verifiers beyond the 3 * maxAssignments that one case can use (profile-v1 section 2):
    // with exactly minVerifiers equal-weight verifiers, the last assignment of a case that
    // used all 3 * maxAssignments fails with probability at most 4e-4 for every admissible
    // maxAssignments (ADR 0023).
    uint256 internal constant VERIFIER_COUNT_MARGIN = 5;
    uint256 internal constant SECP256K1_HALF_N =
        0x7fffffffffffffffffffffffffffffff5d576e7357a4501ddfe92f46681b20a0;

    enum SellerStatus {
        NONE,
        ACTIVE,
        SUSPENDED,
        SANCTIONED,
        EXITING,
        EXITED
    }
    enum VerifierStatus {
        NONE,
        ACTIVE,
        REMOVED,
        EXITING,
        EXITED
    }
    // FROZEN_CLAIMABLE is reported by purchaseState for an entry of a bond account
    // whose claim window is open; it is never stored. FORFEITED is stored when an
    // entry is forfeited individually and reported by purchaseState otherwise.
    enum FinancialState {
        NONE,
        DEFERRED,
        HELD,
        FROZEN_CLAIMABLE,
        REFUNDABLE,
        REFUNDED,
        RELEASABLE,
        RELEASED,
        FORFEITED
    }
    enum BondStatus {
        NONE,
        ACTIVE,
        EXITING,
        EXITED
    }
    enum FreezeState {
        NONE,
        FROZEN,
        CLAIM_OPEN,
        CLAIM_CLOSED
    }
    /// Verdict codes signed by verifiers and stored in cases. NONE marks an
    /// assignment without a verdict.
    enum Verdict {
        NONE,
        PASS,
        FAIL,
        INCONCLUSIVE
    }
    enum EpochState {
        NONE,
        ANCHORED,
        SEALED,
        EPOCH_FAILED
    }
    enum CaseTrigger {
        NONE,
        SAMPLE,
        NON_DELIVERY,
        WRONG_DELIVERY,
        OMISSION,
        EQUIVOCATION
    }
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
        // Appended by ADR 0028: a sampled case whose initial search found no
        // eligible verifier waits for the next checkpoint.
        WAITING_ASSIGNMENT,
        // Appended by ADR 0032: a case of a batched profile waits in its
        // candidate's queue for a slot, or for the value of its batch.
        QUEUED,
        BATCHED,
        // Appended by ADR 0037: a sample case of a proof profile waits for
        // its PASS proof until judgeDue.
        PROOF_WAIT
    }
    enum JudgmentStage {
        NONE,
        INITIAL,
        PARTY,
        AUTO,
        TIEBREAK
    }
    enum EpochFailureReason {
        NONE,
        ANCHOR_TIMEOUT,
        SEAL_TIMEOUT,
        RANDOMNESS_UNAVAILABLE,
        VERIFIER_SET_UNAVAILABLE
    }
    enum RequesterRole {
        NONE,
        BUYER,
        VERIFIER,
        KEEPER
    }
    enum RefundSource {
        NONE,
        FINAL_FAIL,
        UNSERVED,
        EPOCH_FAILED,
        OMISSION,
        EQUIVOCATION,
        FROZEN_POOL,
        // Appended by ADR 0037: a dispute that ends the purchase with a
        // refund and no confirmed failure, and a purchase whose receipt
        // signature was not bound by its anchor deadline.
        DISPUTE_REFUND,
        UNBOUND
    }
    enum ProofBoundary {
        INTERIOR,
        LOWER,
        UPPER
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
    struct AssignmentData {
        uint32 verifierId;
        uint8 stage;
        uint8 attempt;
        uint8 verdict;
        bool released;
        bool serveUsed;
        bool evidenceRequested;
        bool evidenceDisclosed;
        bytes32 evidenceHash;
        uint256 liability;
        uint256 penaltyReserve;
    }
    struct ReviewData {
        uint64 appealUntil;
        uint8 autoVerdict;
        address appellant;
        uint256 deposit;
    }
    struct VerifierCapital {
        uint256 reservedPenalties;
        uint256 conservativeCap;
        uint32 conservativeFraction;
    }
    bytes32 internal constant VERDICT_TYPEHASH = keccak256("FairBindVerdict(uint8 version,bytes32 nonce,uint8 stage,uint8 attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)");
    bytes32 internal constant RECHECK_DOMAIN = keccak256("fairbind/recheck/v1");

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

    struct TransferAuthorization {
        address from;
        address to;
        uint256 value;
        uint256 validAfter;
        uint256 validBefore;
        bytes32 nonce;
    }

    /// One settlement of a settlement batch: the inputs of `settle`.
    struct SettleItem {
        uint32 sellerId;
        uint32 profileId;
        bytes32 claimsHash;
        bytes16 idempotencyKey;
        bytes32 requestHash;
        TransferAuthorization authorization;
        bytes paymentSignature;
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

    /// Bond account: holds the seller bond, the shared token bucket, the failure
    /// counters and the freeze of the deferred ledger of every registration
    /// that names it. Bucket parameters are the profile unit values multiplied
    /// by scaleFactor = floor(balance / sellerPenalty).
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

    struct SellerData {
        SellerView viewData;
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

    struct VerifierCheckpoint {
        uint64 version;
        uint64 checkpointBlock;
        uint32[] verifierIds;
        uint96[] weights;
        uint256 totalEffectiveWeight;
        bytes32 setHash;
    }

    struct Publication {
        bytes32 responseHash;
        uint32 totalBytes;
        uint32 bytesWritten;
        uint16 chunkCount;
        bytes32[] chunkHashes;
    }

    address public immutable deploymentToken;
    address public immutable penaltyTreasury;
    /// Kept for the constructor and the router's module check. Since ADR 0022
    /// it receives nothing: forfeited remainders stay locked in the contract.
    address public immutable verifierRewardPool;
    address public governance;
    address public guardian;
    address public governanceNominee;
    address public guardianNominee;
    uint64 public governanceAcceptAfter;
    bool public newSettlementsPaused;

    uint32 internal nextSellerId = 1;
    uint32 internal nextVerifierId = 1;
    uint256 internal entered = 1;

    mapping(uint32 => DeadlineConfig) internal deadlineConfigs;
    mapping(uint32 => bool) internal deadlineConfigExists;
    mapping(uint32 => ServiceProfileView) internal profiles;
    mapping(uint32 => SellerData) internal sellers;
    mapping(uint32 => VerifierView) internal verifiers;
    mapping(bytes32 => PurchaseView) internal purchases;
    mapping(bytes32 => bytes32) internal purchaseForKey;
    mapping(bytes32 => bool) internal usedNonce;
    mapping(uint32 => mapping(uint24 => uint32)) public epochPurchaseCount;
    mapping(uint32 => mapping(uint24 => AnchorView)) internal anchors;
    mapping(uint32 => uint64) internal latestCheckpointVersion;
    mapping(uint32 => mapping(uint64 => VerifierCheckpoint)) internal verifierCheckpoints;
    mapping(bytes32 => CaseView) internal cases;
    mapping(bytes32 => mapping(uint32 => bool)) internal caseParticipation;
    mapping(bytes32 => uint256) internal assignmentLiability;
    mapping(bytes32 => Publication) internal publications;
    mapping(bytes32 => uint256) internal disputeDeposits;
    mapping(bytes32 => uint8) internal refundSources;
    mapping(uint32 => mapping(uint24 => uint64)) internal epochRetainUntil;

    // Independent recovery for a buyer whose purchase already has another case.
    mapping(bytes32 => CaseView) internal buyerRecoveries;
    mapping(bytes32 => Publication) internal buyerPublications;
    mapping(bytes32 => uint256) internal buyerRecoveryDeposits;

    mapping(bytes32 => AssignmentData[]) internal assignmentHistory;
    mapping(bytes32 => ReviewData) internal reviews;
    mapping(uint32 => VerifierCapital) internal verifierCapital;

    mapping(uint32 => BondView) internal bonds;
    uint32 internal nextBondId = 1;
    mapping(uint32 => mapping(uint24 => bool)) internal epochFailureCounted;

    /// Pending initial-FAIL triggers of a bond account (ADR 0015): cases whose
    /// initial verdict is FAIL and that have not ended, in recording order. A
    /// freeze is released only when none is left, and a FROZEN freeze whose
    /// trigger ends without a failure re-anchors to the head.
    struct TriggerQueue {
        bytes32 head;
        bytes32 tail;
        uint32 count;
    }

    struct TriggerLink {
        bytes32 prev;
        bytes32 next;
        bool pending;
    }

    mapping(uint32 => TriggerQueue) internal freezeTriggers;
    mapping(bytes32 => TriggerLink) internal triggerLinks;

    /// Re-entry during an open claim window (ADR 0021). reopened is set when a
    /// seller of the account is reinstated while the window is open; the two
    /// totals are the deferred and encumbered value of the entries settled
    /// after freezeBlock, which are outside the frozen window. All three are
    /// cleared whenever freezeBlock moves and when the window closes.
    struct ClaimReentry {
        uint256 deferredBalance;
        uint256 encumbered;
        bool reopened;
    }

    mapping(uint32 => ClaimReentry) internal claimReentries;
    /// Scale factor of the bond account (at least one) when its current fixed
    /// failure window opened; the window's failure threshold is this times
    /// failureLimit (ADR 0021).
    mapping(uint32 => uint32) internal failureWindowScale;
    /// Review stages of a case whose seal was reopened once, one bit per
    /// JudgmentStage value (ADR 0021).
    mapping(bytes32 => uint8) internal reviewReseals;

    /// Highest scale factor a bond account left through a drop that is still
    /// recent, and the block of its latest drop (ADR 0022). A drop keeps the
    /// higher of the level it left and a recorded level whose last drop is at
    /// most retentionBlocks (at least the case horizon, ADR 0024) old, and
    /// restamps the block, so the pair bounds from above every scale factor
    /// the account held within retentionBlocks before any later block.
    struct ScaleHigh {
        uint32 scale;
        uint64 dropBlock;
    }

    mapping(uint32 => ScaleHigh) internal recentScaleHigh;
    /// Forfeited frozen-pool remainders and per-failure bond deductions stay in
    /// the contract (ADR 0022). Nothing withdraws them.
    uint256 internal lockedForfeit;

    /// Value-proportional sampling with seller-chosen terms (ADR 0024). A
    /// profile with sales tiers admits bond accounts that choose a value cap
    /// from valueCaps and one tier. One failure deducts
    /// b = ceil(40 * cap * PPM / (27 * detectFloorPpm)) and the unit bond of a
    /// tier is failureLimit * b (the prefunded failures). sanctionLimit is
    /// the number of failures per unit of scale in one failure window at
    /// which the account is sanctioned for good; zero sets no such limit, so
    /// a failure only deducts and suspends and a top-up reopens the account
    /// (ADR 0027). Tiers are ordered by salesLimit; the last is the base
    /// tier, whose bucket and failure limit equal the profile's and which
    /// alone scales with the balance.
    struct SalesTier {
        uint32 salesLimit;
        uint32 bucketCapacity;
        uint32 refillPpmPerBlock;
        uint32 failureLimit;
        uint32 sanctionLimit;
    }

    struct ProfileTerms {
        uint32 detectFloorPpm;
        uint96[] valueCaps;
        SalesTier[] tiers;
        bytes32 termsHash;
    }

    /// Terms a bond account chose (sampleScaleValue is its value cap vmax,
    /// the name of design 2 rule D2-2), and the highest cap and sanction limit it
    /// left within retentionBlocks (peakCap until peakUntil, peakLimit until
    /// peakLimitUntil). Deductions and the balance a settlement needs use the
    /// higher of the current and the recent cap. windowLimit is the sanction
    /// limit per unit of scale of the current failure window: the highest
    /// limit held from retentionBlocks before the window opened through the
    /// window.
    struct BondTerms {
        uint96 sampleScaleValue;
        uint8 tier;
        uint96 peakCap;
        uint64 peakUntil;
        uint32 peakLimit;
        uint64 peakLimitUntil;
        uint32 windowLimit;
    }

    mapping(uint32 => ProfileTerms) internal profileTerms;
    mapping(uint32 => BondTerms) internal bondTerms;
    /// Sampling rate fixed at settlement from the value and the account's cap
    /// in that block; zero for a purchase under a profile without tiers.
    mapping(bytes32 => uint32) internal settledSamplePpm;
    /// Last block for the receipt and inclusion proof of a sample case; zero
    /// once they are on chain or when no case asks for them.
    mapping(bytes32 => uint64) internal sampleReceiptDue;

    /// Liability room of each verifier of a checkpoint at its checkpoint
    /// block, in the order of its verifierIds (ADR 0025). Every assignment of
    /// an epoch sealed on the checkpoint reads the verifier's eligibility from
    /// here, not from its state when the case opens.
    mapping(uint32 => mapping(uint64 => uint96[])) internal checkpointHeadroom;
    /// Last block of the reopened seal window of the current review stage
    /// (ADR 0025); the review randomBlock stays where it was.
    mapping(bytes32 => uint64) internal reviewResealDue;
    /// Set once a profile has been active; its design 2 terms are fixed only
    /// before (ADR 0025).
    mapping(uint32 => bool) internal profileActivated;

    /// A sampled case whose initial assignment search was exhausted (ADR 0028):
    /// the checkpoint version of its last search, the block of that search,
    /// the number of redraws so far and the value of the last redraw. Zero for
    /// a case that never waited. Once set, every later assignment of the case
    /// reads checkpointVersion instead of the epoch's checkpoint, and every
    /// later initial attempt draws from randomness instead of the epoch value.
    struct AssignmentWait {
        uint64 checkpointVersion;
        uint64 searchBlock;
        uint32 redraws;
        bytes32 randomness;
    }
    mapping(bytes32 => AssignmentWait) internal assignmentWaits;

    /// Release clock of a bond account (design 2 rule D2-21, ADR 0029). A
    /// block in which at least one sampled case of the account waits in
    /// WAITING_ASSIGNMENT is paused. waitingCases counts the waiting cases of
    /// the account and pauses the intervals recorded in pauseLog. An entry
    /// settled in block s is released only after deferBlocks unpaused blocks
    /// since s; the recent value cap (V*), the recent sanction limit, the
    /// recent scale high and the bond exit lock count unpaused blocks too.
    struct ReleaseClock {
        uint32 waitingCases;
        uint32 pauses;
    }
    /// One pause of an account: the blocks [start, end), with end zero while
    /// a case still waits, and pausedBefore the paused blocks of the account
    /// before start. Pauses are kept in block order and never overlap.
    struct Pause {
        uint64 start;
        uint64 end;
        uint64 pausedBefore;
    }
    mapping(uint32 => ReleaseClock) internal releaseClocks;
    mapping(uint32 => mapping(uint256 => Pause)) internal pauseLog;

    /// Narrow freeze (design 2 rule D2-6, ADR 0030). A confirmed failure tied
    /// to the purchase settled in block c holds only the unreleased entries
    /// settled from c through the failure block; entries settled before c
    /// keep their release schedule. The frozen window of an open freeze is the
    /// union of these spans in settlement blocks, ordered and disjoint. A
    /// later failure lowers the start of the span it falls in, merges the
    /// spans it reaches, or adds a span after a reinstatement.
    struct FreezeSpan {
        uint64 from;
        uint64 through;
    }
    mapping(uint32 => FreezeSpan[]) internal freezeSpans;
    /// The spans of every closed claim window, in closing order. `itemized`
    /// marks a window whose unclaimed entries were not forfeited as one sum
    /// at its close: each leaves the deferred balance when it is next touched
    /// (releasePurchase forfeits it).
    struct ForfeitWindow {
        uint64 from;
        uint64 through;
        bool itemized;
    }
    mapping(uint32 => ForfeitWindow[]) internal forfeitWindows;
    /// A block at or before the settlement block of every entry the account's
    /// deferred balance holds: the block of its registration, or of the first
    /// settlement after the deferred balance was last empty.
    mapping(uint32 => uint64) internal deferredFloor;
    /// Set when a window closes itemized; cleared when the deferred balance is
    /// next empty, so no unswept entry of an itemized window remains.
    mapping(uint32 => bool) internal itemizedPending;
    /// Settlement block of the purchase whose case gave the first inconclusive
    /// final verdict of the account's current inconclusive window: the start
    /// of the freeze when the window goes above its threshold (rule D2-6 (b)).
    mapping(uint32 => uint64) internal inconclusiveFloor;

    event ProfileTermsSet(uint32 indexed profileId, bytes32 termsHash, uint32 detectFloorPpm, uint96[] valueCaps, SalesTier[] tiers);
    event BondTermsSet(uint32 indexed bondId, uint96 sampleScaleValue, uint8 tier, uint256 unitBond);
    event SampleReceiptRecorded(bytes32 indexed nonce);
    event VerifierHeadroomCheckpointed(uint32 indexed profileId, uint64 indexed version, uint96[] headroom);
    event AssignmentWaiting(bytes32 indexed nonce, uint8 attempt, uint64 checkpointVersion);
    /// The first waiting case of the account stopped its release clock; the
    /// account had pausedBefore paused blocks before this block (ADR 0029).
    event ReleaseClockPaused(uint32 indexed bondId, uint64 pausedBefore);
    /// The last waiting case of the account left the wait; the account has
    /// pausedTotal paused blocks (ADR 0029).
    event ReleaseClockResumed(uint32 indexed bondId, uint64 pausedTotal);
    /// The frozen window of the account now holds the entries settled in
    /// [from, through] (ADR 0030); one event per span added or changed.
    event FreezeSpanSet(uint32 indexed bondId, uint256 index, uint64 from, uint64 through);

    event VerdictSubmitted(bytes32 indexed nonce, uint8 stage, uint32 indexed verifierId, uint8 verdict, bytes32 evidenceHash);
    event EvidenceRequested(bytes32 indexed nonce, uint8 stage, uint8 attempt, uint64 evidenceDue);
    event EvidenceDisclosed(bytes32 indexed nonce, uint8 stage, uint8 attempt, bytes32 evidenceHash);
    event ReviewSelected(bytes32 indexed nonce, bool partyAppeal, bool autoSelected, uint64 randomBlock);
    event ReviewResealed(bytes32 indexed nonce, uint8 stage, uint64 randomBlock);
    event CaseFinalized(bytes32 indexed nonce, uint8 finalVerdict, uint8 financialState);
    event DepositResolved(bytes32 indexed nonce, uint8 indexed depositType, address indexed recipient, uint256 amount);
    error EvidenceTooLarge();

    event BuyerRecoveryOpened(bytes32 indexed nonce, uint64 serveDue);
    event BuyerRecoveryClosed(bytes32 indexed nonce, uint8 state);
    event DeadlineConfigCreated(uint32 indexed deadlineConfigId, bytes32 configHash);
    event ServiceProfileCreated(
        uint32 indexed profileId,
        uint16 indexed classId,
        bytes32 predicateId,
        bytes32 canonId,
        bytes32 parameterHash
    );
    event ServiceProfileActivationChanged(uint32 indexed profileId, bool active);
    event NewSettlementsPaused(bool paused, address indexed actor);
    event GovernanceNominated(
        address indexed currentGovernance, address indexed nominee, uint64 acceptAfter
    );
    event GovernanceChanged(address indexed previousGovernance, address indexed newGovernance);
    event GuardianNominated(address indexed currentGuardian, address indexed nominee);
    event GuardianChanged(address indexed previousGuardian, address indexed newGuardian);
    event SellerRegistered(
        uint32 indexed sellerId,
        uint32 indexed bondId,
        uint32 indexed profileId,
        address owner,
        address signingKey,
        bytes32 claimsHash
    );
    event BondRegistered(uint32 indexed bondId, uint32 indexed profileId, address indexed owner, uint256 balance, uint32 scaleFactor);
    event BondScaled(uint32 indexed bondId, uint32 oldScaleFactor, uint32 newScaleFactor, uint256 balance);
    event BondExitRequested(uint32 indexed bondId, uint64 eligibleBlock);
    event BondExited(uint32 indexed bondId, address indexed owner, uint256 amount);
    event SellerDeferredFrozen(uint32 indexed bondId, uint32 indexed sellerId, bytes32 indexed triggerNonce, uint256 frozenTotal, uint64 frozenAtBlock);
    event FrozenReleased(uint32 indexed bondId, bytes32 indexed triggerNonce, uint256 releasedTotal);
    event FreezeReanchored(uint32 indexed bondId, bytes32 indexed releasedNonce, bytes32 indexed triggerNonce);
    event ClaimWindowOpened(uint32 indexed bondId, bytes32 indexed triggerNonce, uint64 claimUntilBlock, uint256 poolBalance);
    event FrozenClaimPaid(uint32 indexed bondId, uint32 indexed sellerId, bytes32 indexed nonce, address buyer, uint256 value);
    event UnclaimedForfeited(uint32 indexed bondId, bytes32 indexed nonce, uint256 total, uint256 toVerifierPool, uint256 toReserve);
    event SellerSuspended(uint32 indexed sellerId, uint32 indexed bondId, bytes32 indexed triggerNonce);
    event SellerReinstated(uint32 indexed sellerId, uint32 indexed bondId, uint64 atBlock);
    event SellerSanctioned(uint32 indexed sellerId, uint32 indexed bondId, uint32 failureCount, uint256 penalty);
    event InconclusiveRecorded(uint32 indexed sellerId, uint32 indexed bondId, bytes32 indexed nonce, uint32 inconclusiveCount, uint32 judgedCount, bool aboveThreshold);
    event SellerExitRequested(uint32 indexed sellerId, uint64 eligibleBlock);
    event SellerExited(uint32 indexed sellerId, address indexed owner, uint256 amount);
    event VerifierRegistered(
        uint32 indexed verifierId,
        address indexed owner,
        address signingKey,
        uint256 classBitmap,
        uint256 bond
    );
    event VerifierBondChanged(uint32 indexed verifierId, uint256 bond);
    event VerifierClassesChanged(uint32 indexed verifierId, uint256 classBitmap);
    event VerifierExitRequested(uint32 indexed verifierId, uint64 eligibleBlock);
    event VerifierExited(uint32 indexed verifierId, address indexed owner, uint256 amount);
    /// A settlement batch left item `index` out; `reason` is the selector of
    /// its revert (zero when it carried none, such as running out of gas).
    event SettlementSkipped(uint256 indexed index, bytes32 indexed nonce, bytes4 reason);

    event Settled(
        bytes32 indexed nonce,
        bytes32 indexed keyId,
        uint32 indexed sellerId,
        uint32 bondId,
        uint32 profileId,
        address buyer,
        uint256 value,
        uint24 epoch,
        bytes32 requestHash,
        bytes32 claimsHash
    );
    event VerifierTreeCheckpointed(
        uint32 indexed profileId,
        uint64 indexed version,
        bytes32 setHash,
        uint256 totalEffectiveWeight
    );
    event Anchored(
        uint32 indexed sellerId,
        uint24 indexed epoch,
        bytes32 root,
        uint32 profileId,
        uint32 count,
        uint64 randomBlock,
        bytes32 publicationHash
    );
    event EpochSealed(
        uint32 indexed sellerId,
        uint24 indexed epoch,
        bytes32 randomness,
        bytes32 verifierSetHash,
        uint64 sortitionVersion,
        uint256 totalEffectiveWeight
    );
    event EpochFailed(uint32 indexed sellerId, uint24 indexed epoch, uint8 reason);
    event CaseOpened(bytes32 indexed nonce, uint8 trigger, address requester, uint256 heldValue);
    event VerifierAssigned(
        bytes32 indexed nonce,
        uint8 stage,
        uint8 attempt,
        uint32 indexed verifierId,
        uint64 deadline
    );
    event ServeRequested(
        bytes32 indexed nonce, address indexed requester, uint64 caseOpenedBlock, uint64 deadline
    );
    event Served(bytes32 indexed nonce, bytes32 bundleHash, uint64 challengeUntil);
    event ServeAccepted(bytes32 indexed nonce, address indexed requester);
    event ServeEscalated(bytes32 indexed nonce, uint64 publishDue);
    event PublicationStarted(
        bytes32 indexed nonce, bytes32 responseHash, uint16 chunkCount, uint32 totalBytes
    );
    event PublicationChunk(bytes32 indexed nonce, uint16 indexed index, uint32 bytesWritten);
    event ResponsePublished(
        bytes32 indexed nonce, bytes32 responseHash, uint16 chunkCount, uint32 totalBytes
    );
    event Refunded(bytes32 indexed nonce, address indexed buyer, uint256 value, uint8 source);
    event Released(bytes32 indexed nonce, uint32 indexed sellerId, uint256 value);
    event Slashed(
        uint8 indexed actorType,
        uint32 indexed actorId,
        bytes32 indexed nonce,
        address recipient,
        uint256 amount,
        uint8 reason
    );

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
    error SellerInactive();
    error VerifierInactive();
    error InsufficientSellerBond();
    error InsufficientVerifierBond();
    error ExitNotReady();
    error KeyAlreadyUsed();
    error BatchGasShort();
    error NonceAlreadyUsed();
    error ProfileMismatch();
    error ClaimsMismatch();
    error NonceMismatch();
    error AuthorizationMismatch();
    error AuthorizationExpired();
    error ValueTooLarge();
    error HeldSettlementCap();
    error RateLimitExceeded();
    error ServiceClassUnavailable();
    error LiabilityExceeded();
    error AnchorTooEarly();
    error AnchorWindowClosed();
    error CountMismatch();
    error EntriesNotAscending();
    error InvalidRandomnessWindow();
    error NotSampled();
    error AssignmentExhausted();
    error DeadlineNotReached();
    error DeadlinePassed();
    error InvalidTransition();
    error ClaimWindowClosed();
    error ResponseTooLarge();
    error InvalidReceipt();
    error InvalidSignature();
    error InvalidProof();
    error InvalidPublication();
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
    error NotBound();
    error NonCanonical();

    modifier onlyGovernance() {
        if (msg.sender != governance) revert Unauthorized();
        _;
    }

    modifier nonReentrant() {
        if (entered != 1) revert InvalidConfiguration();
        entered = 2;
        _;
        entered = 1;
    }

    constructor(
        address token,
        address governanceTimelock,
        address emergencyGuardian,
        address treasury,
        address rewardPool
    ) {
        if (
            token == address(0) || governanceTimelock == address(0)
                || emergencyGuardian == address(0) || treasury == address(0)
                || rewardPool == address(0)
        ) revert ZeroAddress();
        if (
            token == governanceTimelock || token == emergencyGuardian || token == treasury
                || governanceTimelock == emergencyGuardian || emergencyGuardian == treasury
                || rewardPool == token
        ) revert InvalidConfiguration();
        verifierRewardPool = rewardPool;
        deploymentToken = token;
        governance = governanceTimelock;
        guardian = emergencyGuardian;
        penaltyTreasury = treasury;
    }

    function _deriveKeyId(uint32 sellerId, address buyer, bytes16 key) internal view returns (bytes32) {
        return keccak256(abi.encode(KEY_DOMAIN, block.chainid, address(this), sellerId, buyer, key));
    }

    function _deriveNonce(
        uint32 sellerId,
        uint32 profileId,
        bytes32 claimsHash,
        address buyer,
        bytes16 key,
        bytes32 requestHash
    ) internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                PURCHASE_DOMAIN,
                block.chainid,
                address(this),
                sellerId,
                profileId,
                claimsHash,
                buyer,
                key,
                requestHash
            )
        );
    }

    function _validateProfile(ServiceProfileInput calldata p) internal view {
        if (!deadlineConfigExists[p.deadlineConfigId]) revert UnknownDeadlineConfig();
        if (p.classId == 0 || p.classId > 2) revert UnsupportedServiceClass();
        if (p.predicateId == bytes32(0) || p.canonId == bytes32(0) || p.parameterHash == bytes32(0))
        {
            revert InvalidProfile();
        }
        if (
            p.epochBlocks == 0 || p.samplePpm == 0 || p.samplePpm > PPM || p.effectivePpm == 0
                || p.effectivePpm > p.samplePpm || p.recheckPpm > PPM
        ) revert InvalidProfile();
        if (
            p.bucketCapacity == 0 || p.refillPpmPerBlock > p.maxRatePpmPerBlock
                || p.enforcementBlocks == 0
        ) revert InvalidProfile();
        if (
            uint256(p.bucketCapacity) * PPM + uint256(p.refillPpmPerBlock) * p.enforcementBlocks
                > uint256(p.maxRatePpmPerBlock) * p.enforcementBlocks
        ) revert InvalidProfile();
        // A test build may skip the three hold-period checks for a D sweep; see _admissionOverride.
        bool strict = !_admissionOverride();
        if (
            (strict && p.deferBlocks < p.retentionBlocks) || p.maxRequestBytes == 0 || p.maxResponseBytes == 0
                || p.maxEvidenceBytes == 0
        ) revert InvalidProfile();
        if (
            p.maxPurchaseValue == 0 || p.sellerPenalty == 0 || p.minVerifierBond == 0
                || p.verifierBondCap < p.minVerifierBond
        ) revert InvalidProfile();
        if (
            p.disputeDeposit < p.maxPublicationCost || p.appealDeposit < p.maxReviewCost
                || p.verifierWrongPenalty < p.maxReviewCost
        ) revert InvalidProfile();
        if (
            p.verifierExposurePpm == 0 || p.verifierExposurePpm > PPM || p.maxAssignments == 0
                || p.maxAssignments > 3 || uint256(p.minVerifiers) < 3 * uint256(p.maxAssignments) + VERIFIER_COUNT_MARGIN
                || p.strikeLimit == 0
        ) revert InvalidProfile();
        DeadlineConfig storage d = deadlineConfigs[p.deadlineConfigId];
        uint256 delay = _judgmentDelay(p.epochBlocks, p.beaconDelayBlocks, p.maxAssignments, d);
        uint256 horizon = delay + p.marginBlocks;
        // Bond requirement per unit of sellerPenalty: g * (1/p + maxRate * max(0, L - D)).
        uint256 exposed = delay > p.deferBlocks ? delay - p.deferBlocks : 0;
        uint256 penaltyFloor = uint256(p.maxBadGain) * ((PPM + uint256(p.effectivePpm) - 1) / p.effectivePpm
            + (uint256(p.maxRatePpmPerBlock) * exposed + PPM - 1) / PPM);
        if ((strict && p.retentionBlocks < horizon) || p.maxBadGain == 0 || p.maxPublicationCost == 0
            || p.maxReviewCost == 0 || p.verifierLatePenalty == 0 || p.verifierWrongPenalty == 0
            || p.sellerPenalty < penaltyFloor || uint256(d.responseBlocks) > uint256(p.epochBlocks) + d.anchorBlocks
            || (uint256(p.maxResponseBytes) + RESPONSE_CHUNK_BYTES - 1) / RESPONSE_CHUNK_BYTES + 2 > d.serveBlocks)
            revert InvalidProfile();
        if ((strict && p.enforcementBlocks < delay) || horizon < delay || p.claimWindowBlocks != p.retentionBlocks
            || p.beaconSlackL1Blocks != 0 || p.beaconDelayBlocks < _beaconFloor() || p.failureLimit == 0 || p.failureWindowBlocks == 0
            || p.maxInconclusivePpm == 0 || p.maxInconclusivePpm > PPM || p.inconclusiveWindowBlocks == 0
            || p.forfeitVerifierPpm > PPM || p.minJudgedCount == 0) revert InvalidProfile();
        // A production build freezes only at the confirmed failure. The override
        // build may freeze at the initial FAIL, and must when the hold period is
        // below the case horizon, where the confirmed failure can come too late.
        if (strict ? p.freezeOnInitialFail : (p.retentionBlocks < horizon && !p.freezeOnInitialFail)) {
            revert InvalidProfile();
        }
        if (block.number < p.epochOrigin) revert InvalidProfile();
    }

    /// Longest path from a settlement to the end of its case, and to a freeze
    /// (ADR 0024): the latest case opening, including a sample case opened on
    /// a purchase whose non-delivery dispute ended as delivered, then every
    /// stage with all its assignments, serve procedures, evidence windows and
    /// two lapsed review seals, plus the block in which a seller-appealed
    /// review that cannot progress upholds the initial FAIL. The case horizon
    /// is this plus marginBlocks.
    function _judgmentDelay(uint32 epochBlocks, uint32 beaconDelay, uint16 maxAssignments, DeadlineConfig storage d)
        internal
        view
        returns (uint256 delay)
    {
        uint256 sampled = 2 * uint256(epochBlocks) + d.anchorBlocks + beaconDelay + d.sealBlocks + d.openBlocks;
        uint256 claimed = uint256(d.responseBlocks) + d.claimBlocks;
        uint256 serve = d.serveBlocks;
        uint256 opening = (sampled < claimed ? sampled : claimed) + 3 * serve;
        if (sampled > opening) opening = sampled;
        if (claimed > opening) opening = claimed;
        uint256 m = maxAssignments;
        delay = opening + 3 * m * (2 * uint256(d.judgeBlocks) + 3 * serve)
            + m * (uint256(d.appealBlocks) + d.evidenceBlocks) + d.appealBlocks + 3 * (m - 1)
            + 2 * (2 * uint256(d.sealBlocks) + 3) + 1;
    }

    function _profileAvailable(uint32 profileId) internal view returns (bool) {
        uint64 version = latestCheckpointVersion[profileId];
        return version != 0
            && verifierCheckpoints[profileId][version].verifierIds.length
                >= profiles[profileId].parameters.minVerifiers;
    }

    function _zeroReceipt(FairBindReceipt calldata receipt) internal pure returns (bool) {
        return receipt.version == 0 && receipt.sellerId == 0 && receipt.profileId == 0
            && receipt.nonce == bytes32(0) && receipt.requestHash == bytes32(0)
            && receipt.responseHash == bytes32(0) && receipt.claimsHash == bytes32(0)
            && receipt.predicateCommitment == bytes32(0) && receipt.epoch == 0
            && receipt.issuedAt == 0;
    }

    function _collectDisputeDeposit(bytes32 nonce, uint256 amount) internal {
        if (disputeDeposits[nonce] != 0) revert InvalidTransition();
        disputeDeposits[nonce] = amount;
        _transferFrom(msg.sender, amount);
    }

    function _publicationAccess(bytes32 nonce) internal view {
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state != uint8(CaseState.PUBLISHING)) revert InvalidTransition();
        if (block.number > caseRecord.publishDue) revert DeadlinePassed();
        if (msg.sender != sellers[purchases[nonce].sellerId].viewData.owner) revert Unauthorized();
    }

    function _validatePublishedRequest(
        PurchaseView storage purchase,
        bytes32 purchaseNonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        uint32 maxRequestBytes
    ) internal view {
        uint256 size = request.method.length + request.path.length + request.query.length
            + request.headerBlock.length + request.body.length;
        if (size > maxRequestBytes) revert ResponseTooLarge();
        bytes32 computed =
            _canonicalRequestHash(request, profiles[purchase.profileId].parameters.canonId);
        if (computed != purchase.requestHash) revert InvalidPublication();
        bytes32 nonce = _deriveNonce(
            purchase.sellerId,
            purchase.profileId,
            sellers[purchase.sellerId].viewData.claimsHash,
            purchase.buyer,
            idempotencyKey,
            computed
        );
        if (nonce != _nonceOf(purchase, purchaseNonce)) revert NonceMismatch();
    }

    function _canonicalRequestHash(CanonicalRequest calldata request, bytes32 canonId)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(
            abi.encodePacked(
                canonId,
                keccak256(request.method),
                keccak256(request.path),
                keccak256(request.query),
                keccak256(request.headerBlock),
                keccak256(request.body)
            )
        );
    }

    function _validateReceipt(
        PurchaseView storage purchase,
        bytes32 nonce,
        FairBindReceipt calldata receipt,
        bytes calldata signature
    ) internal view returns (bytes32 digest) {
        if (
            receipt.version != 1 || receipt.sellerId != purchase.sellerId
                || receipt.profileId != purchase.profileId || receipt.nonce != _nonceOf(purchase, nonce)
                || receipt.requestHash != purchase.requestHash
                || receipt.claimsHash != sellers[purchase.sellerId].viewData.claimsHash || receipt.epoch != purchase.epoch
        ) revert InvalidReceipt();
        digest = _receiptDigest(receipt);
        address signer = _recover(digest, signature);
        if (signer != sellers[purchase.sellerId].viewData.signingKey) revert InvalidSignature();
    }

    function _validateBoundaryReceipt(
        PurchaseView storage omittedPurchase,
        FairBindReceipt calldata receipt,
        bytes calldata signature
    ) internal view returns (bytes32 digest) {
        PurchaseView storage boundaryPurchase = purchases[receipt.nonce];
        if (
            boundaryPurchase.sellerId != omittedPurchase.sellerId
                || boundaryPurchase.profileId != omittedPurchase.profileId
                || boundaryPurchase.epoch != omittedPurchase.epoch
        ) revert InvalidProof();
        return _validateReceipt(boundaryPurchase, receipt.nonce, receipt, signature);
    }

    function _receiptProofValid(
        AnchorView storage anchorRecord,
        FairBindReceipt calldata receipt,
        bytes32 receiptLeaf,
        ReceiptProof calldata proof
    ) internal view returns (bool) {
        if (proof.count != anchorRecord.count) return false;
        return FairBindMerkle.verify(
            anchorRecord.root, receipt.nonce, receiptLeaf, proof.index, proof.count, proof.siblings
        );
    }

    function _receiptDigest(FairBindReceipt calldata receipt) internal view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                RECEIPT_TYPEHASH,
                receipt.version,
                receipt.sellerId,
                receipt.profileId,
                receipt.nonce,
                receipt.requestHash,
                receipt.responseHash,
                receipt.claimsHash,
                receipt.predicateCommitment,
                receipt.epoch,
                receipt.issuedAt
            )
        );
        bytes32 domainSeparator = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256("FairBind"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
        return keccak256(abi.encodePacked(hex"1901", domainSeparator, structHash));
    }

    function _recover(bytes32 digest, bytes calldata signature) internal pure returns (address) {
        if (signature.length != 65) revert InvalidSignature();
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        if (uint256(s) == 0 || uint256(s) > SECP256K1_HALF_N || (v != 27 && v != 28)) {
            revert InvalidSignature();
        }
        address signer = ecrecover(digest, v, r, s);
        if (signer == address(0)) revert InvalidSignature();
        return signer;
    }

    function _chunkCount(uint256 totalBytes) internal pure returns (uint16) {
        uint256 count =
            totalBytes == 0 ? 1 : (totalBytes + RESPONSE_CHUNK_BYTES - 1) / RESPONSE_CHUNK_BYTES;
        if (count > type(uint16).max) revert ResponseTooLarge();
        return uint16(count);
    }

    function _responseHash(bytes calldata body) internal pure returns (bytes32) {
        uint256 count = _chunkCount(body.length);
        bytes32[] memory hashes = new bytes32[](count);
        for (uint256 i; i < count; i++) {
            uint256 start = i * RESPONSE_CHUNK_BYTES;
            uint256 end = start + RESPONSE_CHUNK_BYTES;
            if (end > body.length) end = body.length;
            hashes[i] = keccak256(body[start:end]);
        }
        return _responseRootMemory(hashes);
    }

    function _responseRoot(bytes32[] storage stored) internal view returns (bytes32) {
        bytes32[] memory hashes = new bytes32[](stored.length);
        for (uint256 i; i < stored.length; i++) {
            if (stored[i] == bytes32(0)) revert InvalidPublication();
            hashes[i] = stored[i];
        }
        return _responseRootMemory(hashes);
    }

    function _responseRootMemory(bytes32[] memory hashes) internal pure returns (bytes32) {
        uint256 width = hashes.length;
        while (width > 1) {
            uint256 nextWidth = (width + 1) / 2;
            for (uint256 i; i < nextWidth; i++) {
                bytes32 left = hashes[2 * i];
                bytes32 right = 2 * i + 1 < width ? hashes[2 * i + 1] : left;
                hashes[i] = keccak256(abi.encode(RESPONSE_NODE_DOMAIN, left, right));
            }
            width = nextWidth;
        }
        return hashes[0];
    }

    function _finishPublication(
        bytes32 nonce,
        bytes32 responseHash,
        uint16 chunks,
        uint32 totalBytes
    ) internal {
        emit ResponsePublished(nonce, responseHash, chunks, totalBytes);
        _completeDelivery(nonce);
    }

    function _completeDelivery(bytes32 nonce) internal {
        CaseView storage caseRecord = cases[nonce];
        emit ServeAccepted(nonce, caseRecord.requester);
        if (caseRecord.requesterRole == uint8(RequesterRole.BUYER)) {
            caseRecord.state = uint8(CaseState.DELIVERED);
            if (_costOn(purchases[nonce].profileId)) ExchangeStore.layout().ladders[nonce].delivered = true;
            if (!_buyerRecoveryOpen(nonce) && !_refundDue(nonce)) _setFinancialState(nonce, FinancialState.RELEASABLE);
            return;
        }
        if (caseRecord.requesterRole == uint8(RequesterRole.KEEPER)) {
            // The seller published the sampled response on chain after every assigned
            // verifier timed out: a protocol progress failure that counts against nobody.
            _finishProtocolInconclusive(nonce);
            return;
        }
        if (caseRecord.requesterRole != uint8(RequesterRole.VERIFIER)) revert InvalidTransition();
        caseRecord.state = caseRecord.resumeState;
        caseRecord.resumeState = uint8(CaseState.NONE);
        caseRecord.judgeDue = uint64(
            block.number
                + deadlineConfigs[profiles[purchases[nonce].profileId].parameters
                    .deadlineConfigId].judgeBlocks
        );
    }

    function _sellerFailure(bytes32 nonce, RefundSource source) internal {
        _sellerFailureBody(nonce, source);
        uint32 profileId = purchases[nonce].profileId;
        if (_batched(profileId)) _hook(HOOK_FAILURE + uint256(source), uint256(nonce));
        else if (_exchangeMode(profileId) == ExchangeStore.MODE_PROOF) _hook(HOOK_PASS_FAILURE, uint256(nonce));
    }

    function _sellerFailureBody(bytes32 nonce, RefundSource source) private {
        PurchaseView storage purchase = purchases[nonce];
        // A purchase a dispute refunded while its sample case stays (ADR
        // 0037) takes the failure without a second refund.
        bool early = _refundedEarly(nonce);
        if (
            !early && (purchase.financialState == uint8(FinancialState.REFUNDED)
                || purchase.financialState == uint8(FinancialState.RELEASED)
                || purchase.financialState == uint8(FinancialState.REFUNDABLE)
                || _forfeitedEntry(purchase))
        ) revert AlreadyFinalized();
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.nonce == bytes32(0)) {
            caseRecord.nonce = nonce;
            caseRecord.caseOpenedBlock = uint64(block.number);
        }
        caseRecord.trigger = source == RefundSource.OMISSION
            ? uint8(CaseTrigger.OMISSION)
            : source == RefundSource.EQUIVOCATION
                ? uint8(CaseTrigger.EQUIVOCATION)
                : caseRecord.trigger;
        // A case waiting in a queue or for its batch leaves it (ADR 0032).
        if (caseRecord.state == uint8(CaseState.QUEUED) || caseRecord.state == uint8(CaseState.BATCHED)) {
            _hook(HOOK_CASE_LEAVES, uint256(nonce));
        }
        _sampleEnded(nonce);
        _releaseAllAssignments(nonce);
        _resolveAppealDeposit(nonce, 3);
        if (_buyerRecoveryOpen(nonce)) {
            buyerRecoveries[nonce].state = uint8(CaseState.UNSERVED);
            emit BuyerRecoveryClosed(nonce, uint8(CaseState.UNSERVED));
        }
        // A waiting case that ends here leaves the wait (ADR 0029).
        if (caseRecord.state == uint8(CaseState.WAITING_ASSIGNMENT)) _clockWaitEnds(nonce);
        caseRecord.state = uint8(CaseState.UNSERVED);
        if (!early) {
            _setFinancialState(nonce, FinancialState.REFUNDABLE);
            refundSources[nonce] = uint8(source);
        }
        if (source == RefundSource.EPOCH_FAILED) {
            // Only a missed anchor is the seller's failure, and it counts once per epoch.
            AnchorView storage record = anchors[purchase.sellerId][purchase.epoch];
            if (record.anchoredBlock != 0) {
                // Not the seller's failure: a pending trigger on this case ends without one.
                _releaseTrigger(nonce);
                return;
            }
            bool first = !epochFailureCounted[purchase.sellerId][purchase.epoch];
            epochFailureCounted[purchase.sellerId][purchase.epoch] = true;
            _confirmFailure(purchase.sellerId, nonce, first, _epochStart(profiles[purchase.profileId].parameters, purchase.epoch));
            return;
        }
        _confirmFailure(purchase.sellerId, nonce, true, purchase.settledBlock);
    }

    /// First block of an epoch. A missed anchor is tied to no single purchase:
    /// its freeze starts here (rule D2-6 (a) 1 puts it at the epoch's first
    /// sale; no sale of the seller lies between the two, ADR 0030).
    function _epochStart(ServiceProfileInput storage profile, uint24 epoch) internal view returns (uint64) {
        return uint64(uint256(profile.epochOrigin) + uint256(epoch) * profile.epochBlocks);
    }

    /// Test builds override this to reproduce the pre-freeze refund rule.
    function _freezeEnabled() internal pure virtual returns (bool) {
        return true;
    }

    /// False in every production build. A test build returns true so that a
    /// deferral sweep can admit a profile whose hold period is below the case
    /// horizon (the longest case path plus marginBlocks, ADR 0024): it skips
    /// only retentionBlocks >= caseHorizon (and with it deferBlocks >=
    /// caseHorizon), deferBlocks >= retentionBlocks and enforcementBlocks >=
    /// judgmentDelayBlocks.
    function _admissionOverride() internal pure virtual returns (bool) {
        return false;
    }

    /// Whether a purchase exists. settle does not write the nonce field of the
    /// purchase record, because it equals the mapping key (journal J3b); a record
    /// exists exactly when settledBlock, which settle always sets, is not zero.
    function _purchaseExists(PurchaseView storage purchase) internal view returns (bool) {
        return purchase.settledBlock != 0;
    }

    /// The nonce field as it read before J3b: the key when the purchase exists, zero otherwise.
    function _nonceOf(PurchaseView storage purchase, bytes32 key) internal view returns (bytes32) {
        return purchase.settledBlock != 0 ? key : bytes32(0);
    }

    function _bondOf(PurchaseView storage purchase) internal view returns (BondView storage) {
        return bonds[sellers[purchase.sellerId].viewData.bondId];
    }

    /// True while the entry belongs to the frozen window of its bond account,
    /// or while an initial FAIL of the account is pending: a pending trigger
    /// holds every unreleased entry until it is decided, including entries
    /// settled after a reinstatement during an open claim window (ADR 0021).
    /// The frozen window is the union of the account's freeze spans (ADR 0030).
    function _frozen(PurchaseView storage purchase) internal view returns (bool) {
        if (_r8Paid(purchase)) return false;
        uint32 bondId = sellers[purchase.sellerId].viewData.bondId;
        BondView storage b = bonds[bondId];
        if (freezeTriggers[bondId].count != 0) return true;
        if (b.freezeState != uint8(FreezeState.FROZEN) && b.freezeState != uint8(FreezeState.CLAIM_OPEN)) return false;
        return _inFreezeSpans(bondId, purchase.settledBlock);
    }

    /// Whether settlement block s lies in a span of the account's open freeze.
    function _inFreezeSpans(uint32 bondId, uint256 s) internal view returns (bool) {
        FreezeSpan[] storage spans = freezeSpans[bondId];
        uint256 n = spans.length;
        for (uint256 i; i < n; i++) {
            FreezeSpan storage span = spans[i];
            if (s < span.from) return false;
            if (s <= span.through) return true;
        }
        return false;
    }

    /// The first closed window whose span holds settlement block s, if any,
    /// and whether that window closed itemized (ADR 0030).
    function _forfeitWindowOf(uint32 bondId, uint256 s) internal view returns (bool found, bool itemized) {
        if (s > bonds[bondId].forfeitedThrough) return (false, false);
        ForfeitWindow[] storage windows = forfeitWindows[bondId];
        uint256 n = windows.length;
        for (uint256 i; i < n; i++) {
            ForfeitWindow storage w = windows[i];
            if (s >= w.from && s <= w.through) return (true, w.itemized);
        }
        return (false, false);
    }

    /// True when the entry's principal left, or is due to leave, with the
    /// forfeiture of a closed window.
    function _forfeitedEntry(PurchaseView storage purchase) internal view returns (bool) {
        uint8 s = purchase.financialState;
        if (s == uint8(FinancialState.FORFEITED)) return true;
        if (s != uint8(FinancialState.DEFERRED) && s != uint8(FinancialState.RELEASABLE)) return false;
        if (_r8Paid(purchase)) return false;
        (bool found,) = _forfeitWindowOf(sellers[purchase.sellerId].viewData.bondId, purchase.settledBlock);
        return found;
    }

    /// Single writer of purchase financial state. Keeps the bond account's
    /// deferred and encumbered totals, and forfeits an entry of a closed frozen
    /// window whose own case ends without a refund right. A refund leaves the
    /// bond's bucket as it is (rule D2-7). A mutation build of the tests
    /// overrides it.
    function _setFinancialState(bytes32 nonce, FinancialState next) internal virtual {
        PurchaseView storage purchase = purchases[nonce];
        uint32 bondId = sellers[purchase.sellerId].viewData.bondId;
        BondView storage b = bonds[bondId];
        // An entry settled after the boundary of an open claim window is outside
        // the frozen window; its totals are kept apart as well (ADR 0021).
        ClaimReentry storage late = claimReentries[bondId];
        bool outside = b.freezeState == uint8(FreezeState.CLAIM_OPEN) && purchase.settledBlock > b.freezeBlock;
        uint8 old = purchase.financialState;
        uint256 value = purchase.value;
        if (old == uint8(FinancialState.HELD) || old == uint8(FinancialState.REFUNDABLE)) {
            b.encumbered -= value;
            if (outside) late.encumbered -= value;
        }
        if (next == FinancialState.RELEASABLE) {
            (bool forfeited,) = _forfeitWindowOf(bondId, purchase.settledBlock);
            if (forfeited) next = FinancialState.FORFEITED;
        }
        if (next == FinancialState.HELD || next == FinancialState.REFUNDABLE) {
            b.encumbered += value;
            if (outside) late.encumbered += value;
        }
        if (next >= FinancialState.REFUNDABLE && next != FinancialState.RELEASABLE) _r8Leaving(nonce, purchase.profileId);
        purchase.financialState = uint8(next);
        if (next == FinancialState.REFUNDED || next == FinancialState.RELEASED || next == FinancialState.FORFEITED) {
            b.deferredBalance -= value;
            if (outside) late.deferredBalance -= value;
            if (b.deferredBalance == 0) _deferredEmptied(bondId);
        }
        if (next == FinancialState.FORFEITED) {
            _payDeposits(nonce);
            _lockForfeit(bondId, nonce, value);
        }
    }

    /// The deferred balance of the account is empty: no entry of an itemized
    /// window is left (ADR 0030). The next settlement raises deferredFloor.
    function _deferredEmptied(uint32 bondId) internal {
        if (itemizedPending[bondId]) itemizedPending[bondId] = false;
    }

    /// Pays the dispute and buyer-recovery deposits of an entry that ends
    /// without a refund right, following the release rule.
    function _payDeposits(bytes32 nonce) internal {
        PurchaseView storage purchase = purchases[nonce];
        uint256 deposit = disputeDeposits[nonce];
        uint256 buyerDeposit = buyerRecoveryDeposits[nonce];
        if (deposit == 0 && buyerDeposit == 0) return;
        // A non-delivery dispute that ended as delivered under measured costs
        // pays the seller its measured cost at most (ADR 0037).
        ExchangeStore.Ladder storage lad = ExchangeStore.layout().ladders[nonce];
        if (lad.delivered || lad.recoveryDelivered) {
            _hook(HOOK_LADDER_PAY, uint256(nonce));
            return;
        }
        disputeDeposits[nonce] = 0;
        buyerRecoveryDeposits[nonce] = 0;
        uint8 caseState = cases[nonce].state;
        bool inconclusive = caseState == uint8(CaseState.INCONCLUSIVE)
            || (caseState == uint8(CaseState.FINAL) && cases[nonce].finalVerdict == uint8(Verdict.INCONCLUSIVE));
        if (inconclusive && deposit != 0) {
            _transfer(purchase.buyer, deposit);
            deposit = 0;
        }
        if (deposit + buyerDeposit != 0) _transfer(sellers[purchase.sellerId].viewData.owner, deposit + buyerDeposit);
    }

    /// Locks a forfeited remainder in the contract (ADR 0022). The event keeps
    /// its ABI; both destination amounts are zero.
    function _lockForfeit(uint32 bondId, bytes32 nonce, uint256 amount) internal {
        bonds[bondId].forfeitedTotal += amount;
        lockedForfeit += amount;
        emit UnclaimedForfeited(bondId, nonce, amount, 0, 0);
    }

    function _suspend(uint32 sellerId, bytes32 trigger) internal {
        SellerView storage seller = sellers[sellerId].viewData;
        if (seller.status != uint8(SellerStatus.ACTIVE)) return;
        seller.status = uint8(SellerStatus.SUSPENDED);
        seller.suspendedAtBlock = uint64(block.number);
        // Rule 8: the suspension ends the episode (rule D2-42 (a), (g)).
        _r8Hook(seller.profileId, HOOK_R8_SUSPEND, sellerId);
        emit SellerSuspended(sellerId, seller.bondId, trigger);
    }

    /// True in every production build. The re-entry mutation build of the
    /// stateful suite returns false to restore the early return of _freeze for
    /// an account whose claim window is open (ADR 0021).
    function _moveFreezeInClaimWindow() internal pure virtual returns (bool) {
        return true;
    }

    /// True in every production build: the purchase of a case waiting for an
    /// assignment stays held and cannot be released (ADR 0028). The mutation
    /// build of the stateful suite returns false.
    function _waitHolds() internal pure virtual returns (bool) {
        return true;
    }

    /// True in every production build: blocks in which a case of the account
    /// waits do not count toward its release clock (ADR 0029). The mutation
    /// build of the stateful suite returns false, which counts every block.
    function _pauseHolds() internal pure virtual returns (bool) {
        return true;
    }

    /// Stops new settlements of the seller and holds every unreleased deferred
    /// entry of its bond account. Transfers nothing. A confirmed failure while
    /// the claim window is open moves freezeBlock to this block, so that the
    /// entries settled after a reinstatement join the frozen window and the
    /// account admits nothing until the next reinstatement (ADR 0021); an
    /// initial FAIL leaves the window alone and holds through its pending
    /// trigger instead.
    ///
    /// `from` is the settlement block c of the purchase the failure is tied
    /// to (ADR 0030): the freeze holds the entries settled from c through this
    /// block, whatever the seller's status. A failure of an account already
    /// frozen lowers the start of its window to c when c is earlier; one in an
    /// open claim window also moves the end to this block, joining the spans
    /// that c reaches, or adds a span [c, this block] when c lies after the
    /// window's last span (a failure tied to an entry settled after a
    /// reinstatement).
    function _freeze(uint32 sellerId, bytes32 trigger, bool confirmed, uint64 from) internal {
        _suspend(sellerId, trigger);
        if (!_freezeEnabled()) return;
        uint32 bondId = sellers[sellerId].viewData.bondId;
        BondView storage b = bonds[bondId];
        from = _freezeStart(from);
        if (b.freezeState == uint8(FreezeState.FROZEN)) {
            // No entry of the account settles while it is frozen.
            if (from <= b.freezeBlock) _addFreezeSpan(bondId, from, b.freezeBlock);
            return;
        }
        if (b.freezeState == uint8(FreezeState.CLAIM_OPEN)) {
            if (!confirmed || !_moveFreezeInClaimWindow()) return;
            delete claimReentries[bondId];
        } else {
            b.freezeState = uint8(FreezeState.FROZEN);
            b.freezeNonce = trigger;
            delete freezeSpans[bondId];
        }
        b.freezeBlock = uint64(block.number);
        _addFreezeSpan(bondId, from, uint64(block.number));
        emit SellerDeferredFrozen(bondId, sellerId, trigger, b.deferredBalance, uint64(block.number));
    }

    /// The start of the freeze of a failure tied to settlement block c. Every
    /// production build returns c (ADR 0030); a mutation build returns zero,
    /// the freeze of every unreleased entry that ADR 0012 used.
    function _freezeStart(uint64 c) internal pure virtual returns (uint64) {
        return c;
    }

    /// Adds [from, through] to the spans of the account's open freeze. The
    /// spans stay ordered and disjoint: the new span absorbs every span it
    /// meets, and the end of the last span never moves back.
    function _addFreezeSpan(uint32 bondId, uint64 from, uint64 through) internal {
        FreezeSpan[] storage spans = freezeSpans[bondId];
        uint256 n = spans.length;
        // Spans that end before `from` stay; the rest from index k on merge.
        uint256 k = n;
        while (k != 0 && spans[k - 1].through >= from) k--;
        if (k == n) {
            spans.push(FreezeSpan(from, through));
            emit FreezeSpanSet(bondId, n, from, through);
            return;
        }
        FreezeSpan storage merged = spans[k];
        if (merged.from < from) from = merged.from;
        uint64 last = spans[n - 1].through;
        if (last > through) through = last;
        merged.from = from;
        merged.through = through;
        for (uint256 i = n - 1; i > k; i--) spans.pop();
        emit FreezeSpanSet(bondId, k, from, through);
    }

    /// Freezes on an initial FAIL and records the case as a pending trigger
    /// of the bond account, once per case (ADR 0015).
    function _freezePending(uint32 sellerId, bytes32 nonce) internal {
        _freeze(sellerId, nonce, false, purchases[nonce].settledBlock);
        if (!_freezeEnabled() || triggerLinks[nonce].pending) return;
        TriggerQueue storage q = freezeTriggers[sellers[sellerId].viewData.bondId];
        triggerLinks[nonce] = TriggerLink(q.tail, 0, true);
        if (q.tail != 0) triggerLinks[q.tail].next = nonce;
        else q.head = nonce;
        q.tail = nonce;
        q.count++;
    }

    /// Removes an ended case from the pending triggers of its bond account and
    /// returns the earliest trigger still pending, or zero.
    function _dropTrigger(uint32 bondId, bytes32 nonce) internal returns (bytes32) {
        TriggerQueue storage q = freezeTriggers[bondId];
        TriggerLink memory link = triggerLinks[nonce];
        if (link.pending) {
            if (link.prev != 0) triggerLinks[link.prev].next = link.next;
            else q.head = link.next;
            if (link.next != 0) triggerLinks[link.next].prev = link.prev;
            else q.tail = link.prev;
            delete triggerLinks[nonce];
            q.count--;
        }
        return q.head;
    }

    /// Records a final seller failure: freezes if needed, opens the claim
    /// window, counts the failure toward the terminal sanction and deducts its
    /// share of the seller penalty from the bond (ADR 0018). A window that
    /// opens at scale factor n sanctions at n * failureLimit failures, and its
    /// shares sum to n * sellerPenalty there (ADR 0021). Under a profile with
    /// tiers the threshold is n * sanctionLimit, none when it is zero, and
    /// every failure deducts b (ADR 0024, ADR 0027).
    function _confirmFailure(uint32 sellerId, bytes32 trigger, bool count, uint64 from) internal {
        _freeze(sellerId, trigger, true, from);
        uint32 bondId = sellers[sellerId].viewData.bondId;
        _dropTrigger(bondId, trigger);
        BondView storage b = bonds[bondId];
        ServiceProfileInput storage profile = profiles[b.profileId].parameters;
        uint64 claimUntil = uint64(block.number + profile.claimWindowBlocks);
        if (b.freezeState == uint8(FreezeState.FROZEN)) {
            b.freezeState = uint8(FreezeState.CLAIM_OPEN);
            b.freezeNonce = trigger;
            b.claimUntilBlock = claimUntil;
            emit ClaimWindowOpened(bondId, trigger, claimUntil, b.deferredBalance - b.encumbered);
        } else if (b.freezeState == uint8(FreezeState.CLAIM_OPEN) && b.claimUntilBlock < claimUntil) {
            b.claimUntilBlock = claimUntil;
        }
        if (!count) return;
        if (b.failureCount == 0 || block.number > uint256(b.failureWindowStart) + profile.failureWindowBlocks) {
            b.failureCount = 0;
            b.failureWindowStart = uint64(block.number);
            // The scale is read before this failure's deduction, and raised to
            // any level the account left within retentionBlocks (ADR 0022).
            uint32 open = b.scaleFactor;
            ScaleHigh storage high = recentScaleHigh[bondId];
            // retentionBlocks are counted in unpaused blocks (ADR 0029).
            if (high.scale > open && _unpausedWithin(bondId, high.dropBlock, profile.retentionBlocks)) {
                open = high.scale;
            }
            failureWindowScale[bondId] = open > 1 ? open : 1;
            // Under a profile with tiers the window's sanction limit per unit
            // of scale is the highest one held within retentionBlocks
            // (ADR 0024, ADR 0027).
            uint32 windowLimit = _recentSanctionLimit(b);
            if (windowLimit != 0) bondTerms[bondId].windowLimit = windowLimit;
        }
        b.failureCount++;
        if (b.sanctioned) return;
        uint256 scale = failureWindowScale[bondId];
        (uint256 penalty,,, uint256 unitLimit, bool tiered) = _unitTerms(b, profile);
        uint256 limit = scale * (tiered ? bondTerms[bondId].windowLimit : unitLimit);
        // Under a profile with tiers the unit bond is exactly unitLimit * b,
        // so every failure deducts b of the highest recent cap.
        uint256 share = penalty / unitLimit;
        bool last = b.failureCount >= limit;
        // The last failure of a window takes the remainder so that the window total is scale * sellerPenalty.
        if (last && !tiered) share = scale * penalty - (limit - 1) * share;
        if (share > b.balance) share = b.balance;
        b.balance -= share;
        _rescale(b, profile);
        // The deduction stays in the contract (ADR 0022).
        lockedForfeit += share;
        emit Slashed(1, sellerId, trigger, address(this), share, last ? 1 : 4);
        if (!last) return;
        b.sanctioned = true;
        SellerView storage seller = sellers[sellerId].viewData;
        if (seller.status == uint8(SellerStatus.ACTIVE) || seller.status == uint8(SellerStatus.SUSPENDED)) {
            seller.status = uint8(SellerStatus.SANCTIONED);
        }
        emit SellerSanctioned(sellerId, bondId, b.failureCount, share);
    }

    /// Clears a freeze whose trigger ended without a failure. Entries return to
    /// their release schedule and nothing is forfeited or counted.
    function _unfreeze(uint32 bondId) internal {
        BondView storage b = bonds[bondId];
        b.freezeState = uint8(b.forfeitedThrough != 0 ? FreezeState.CLAIM_CLOSED : FreezeState.NONE);
        delete freezeSpans[bondId];
        bytes32 trigger = b.freezeNonce;
        emit FrozenReleased(bondId, trigger, b.deferredBalance);
        SellerView storage seller = sellers[purchases[trigger].sellerId].viewData;
        if (seller.status == uint8(SellerStatus.SUSPENDED) && seller.suspendedAtBlock >= b.freezeBlock) {
            seller.status = uint8(SellerStatus.ACTIVE);
            emit SellerReinstated(seller.sellerId, bondId, uint64(block.number));
        }
    }

    /// A case ended without a failure. If it anchored a FROZEN freeze, the
    /// freeze moves to the earliest trigger still pending, or is released when
    /// none is left (ADR 0015).
    function _releaseTrigger(bytes32 nonce) internal {
        uint32 bondId = sellers[purchases[nonce].sellerId].viewData.bondId;
        bytes32 head = _dropTrigger(bondId, nonce);
        BondView storage b = bonds[bondId];
        if (b.freezeState != uint8(FreezeState.FROZEN) || b.freezeNonce != nonce) return;
        if (head == 0) {
            _unfreeze(bondId);
        } else {
            b.freezeNonce = head;
            emit FreezeReanchored(bondId, nonce, head);
        }
    }

    /// Counts a final content verdict of a sampled case. Above the inconclusive
    /// threshold, once the window holds minJudgedCount judged cases, a
    /// FINAL(INCONCLUSIVE) freezes and suspends, but is never counted as a
    /// failure. Party disputes change no counter (ADR 0017).
    function _recordJudged(bytes32 nonce, uint8 result) internal {
        if (cases[nonce].trigger != uint8(CaseTrigger.SAMPLE)) return;
        PurchaseView storage purchase = purchases[nonce];
        uint32 bondId = sellers[purchase.sellerId].viewData.bondId;
        BondView storage b = bonds[bondId];
        ServiceProfileInput storage profile = profiles[b.profileId].parameters;
        if (b.judgedCount == 0 || block.number > uint256(b.inconclusiveWindowStart) + profile.inconclusiveWindowBlocks) {
            b.judgedCount = 0;
            b.inconclusiveCount = 0;
            b.inconclusiveWindowStart = uint64(block.number);
        }
        b.judgedCount++;
        if (result != uint8(Verdict.INCONCLUSIVE)) return;
        // The freeze of the window starts at the sale of its first inconclusive case (ADR 0030).
        if (b.inconclusiveCount == 0) inconclusiveFloor[bondId] = purchase.settledBlock;
        b.inconclusiveCount++;
        bool above = b.judgedCount >= profile.minJudgedCount
            && uint256(b.inconclusiveCount) * PPM > uint256(profile.maxInconclusivePpm) * b.judgedCount;
        emit InconclusiveRecorded(purchase.sellerId, bondId, nonce, b.inconclusiveCount, b.judgedCount, above);
        if (above) _confirmFailure(purchase.sellerId, nonce, false, inconclusiveFloor[bondId]);
    }

    /// Recomputes the bucket scale after the bond balance changed. The bucket is
    /// brought current first; a lower scale clips the level at once.
    function _rescale(BondView storage b, ServiceProfileInput storage profile) internal {
        b.bucketBalancePpm = _refilledBucket(b, profile);
        b.bucketUpdatedBlock = uint64(block.number);
        uint32 old = b.scaleFactor;
        (uint256 penalty, uint256 capacity,,, bool tiered) = _unitTerms(b, profile);
        uint256 factor = b.balance / penalty;
        // Only the base tier scales with the balance (ADR 0024).
        if (tiered && factor > 1 && bondTerms[b.bondId].tier + 1 < profileTerms[b.profileId].tiers.length) factor = 1;
        if (factor > type(uint32).max) factor = type(uint32).max;
        b.scaleFactor = uint32(factor);
        uint256 cap = capacity * factor * PPM;
        if (b.bucketBalancePpm > cap) b.bucketBalancePpm = cap;
        if (factor < old) {
            ScaleHigh storage high = recentScaleHigh[b.bondId];
            if (old > high.scale || !_unpausedWithin(b.bondId, high.dropBlock, profile.retentionBlocks)) high.scale = old;
            high.dropBlock = uint64(block.number);
        }
        if (old != factor) emit BondScaled(b.bondId, old, uint32(factor), b.balance);
    }

    function _checkpointEligible(VerifierView storage verifier, ServiceProfileInput storage profile)
        internal
        view
        returns (bool)
    {
        return verifier.status == uint8(VerifierStatus.ACTIVE) && verifier.owner != address(0)
            && verifier.signingKey != address(0) && verifier.bond >= profile.minVerifierBond
            && (verifier.classBitmap & (uint256(1) << profile.classId)) != 0;
    }

    function _sameCheckpoint(
        VerifierCheckpoint storage checkpoint,
        uint32[] memory ids,
        uint96[] memory weights
    ) internal view returns (bool) {
        if (checkpoint.verifierIds.length != ids.length) return false;
        for (uint256 i; i < ids.length; i++) {
            if (checkpoint.verifierIds[i] != ids[i] || checkpoint.weights[i] != weights[i]) {
                return false;
            }
        }
        return true;
    }

    function _checkpointAt(uint32 profileId, uint64 maximumBlock)
        internal
        view
        returns (uint64 version)
    {
        // Checkpoint blocks never decrease with the version: search for the
        // latest version at or before maximumBlock (ADR 0025).
        uint64 high = latestCheckpointVersion[profileId];
        while (version < high) {
            uint64 mid = high - (high - version) / 2;
            if (verifierCheckpoints[profileId][mid].checkpointBlock <= maximumBlock) version = mid;
            else high = mid - 1;
        }
    }

    /// Liability a verifier can still take at this block under the profile's
    /// effective-bond rule (profile-v1 section 5), or zero when its bond does
    /// not cover one more penalty reservation. A checkpoint stores it for each
    /// of its verifiers (ADR 0025).
    function _liabilityRoom(uint32 verifierId, ServiceProfileInput storage profile) internal view returns (uint96) {
        VerifierView storage verifier = verifiers[verifierId];
        VerifierCapital storage capital = verifierCapital[verifierId];
        uint256 reserve = profile.verifierLatePenalty > profile.verifierWrongPenalty
            ? profile.verifierLatePenalty : profile.verifierWrongPenalty;
        uint256 allReserved = capital.reservedPenalties + reserve;
        if (verifier.bond < allReserved) return 0;
        uint256 cap = verifier.lockedLiability == 0 ? profile.verifierBondCap
            : _effectiveBond(capital.conservativeCap, profile.verifierBondCap);
        uint32 fraction = verifier.lockedLiability == 0 || profile.verifierExposurePpm < capital.conservativeFraction
            ? profile.verifierExposurePpm : capital.conservativeFraction;
        uint256 limit = _effectiveBond(verifier.bond - allReserved, cap) * fraction / PPM;
        if (limit <= verifier.lockedLiability) return 0;
        uint256 room = limit - verifier.lockedLiability;
        return room > type(uint96).max ? type(uint96).max : uint96(room);
    }

    function _anchorBase(ServiceProfileInput storage profile, uint24 epoch)
        internal
        view
        returns (uint256)
    {
        return uint256(profile.epochOrigin) + (uint256(epoch) + 2) * profile.epochBlocks - 1;
    }

    function _sampleStatus(PurchaseView storage purchase, bytes32 nonce)
        internal
        view
        returns (bool eligible, bool known)
    {
        AnchorView storage record = anchors[purchase.sellerId][purchase.epoch];
        if (record.state != uint8(EpochState.SEALED)) return (false, false);
        // A purchase under a profile with tiers carries its own rate, fixed at
        // settlement, and is drawn against the rounded-up threshold (ADR 0024).
        nonce = _nonceOf(purchase, nonce);
        uint32 ppm = settledSamplePpm[nonce];
        bool proportional = ppm != 0;
        if (!proportional) ppm = profiles[purchase.profileId].parameters.samplePpm;
        if (ppm == PPM) return (true, true);
        uint256 value = uint256(
            keccak256(
                abi.encode(
                    SAMPLE_DOMAIN,
                    record.randomness,
                    purchase.sellerId,
                    purchase.epoch,
                    nonce
                )
            )
        );
        return (value < (proportional ? FairBindDesign2.threshold(ppm) : _probabilityThreshold(ppm)), true);
    }

    /// Unit bond, bucket capacity and refill per unit of scale, and failure
    /// limit per unit of scale of a bond account: the profile's values, or
    /// those of the account's tier under a profile with tiers (ADR 0024).
    function _unitTerms(BondView storage b, ServiceProfileInput storage profile)
        internal
        view
        returns (uint256 penalty, uint256 capacity, uint256 rate, uint256 limit, bool tiered)
    {
        ProfileTerms storage pt = profileTerms[b.profileId];
        if (pt.tiers.length == 0) {
            return (profile.sellerPenalty, profile.bucketCapacity, profile.refillPpmPerBlock, profile.failureLimit, false);
        }
        BondTerms storage t = bondTerms[b.bondId];
        SalesTier storage tier = pt.tiers[t.tier];
        limit = tier.failureLimit;
        penalty = limit * FairBindDesign2.deduction(_recentCap(b.bondId, t), pt.detectFloorPpm);
        return (penalty, tier.bucketCapacity, tier.refillPpmPerBlock, limit, true);
    }

    /// Commitment to the design 2 terms of a profile (ADR 0025):
    /// keccak256(abi.encode(PROFILE_TERMS_DOMAIN, detectFloorPpm, valueCaps, tiers)).
    function _termsHash(uint32 detectFloorPpm, uint96[] calldata valueCaps, SalesTier[] calldata tiers)
        internal
        pure
        returns (bytes32)
    {
        return keccak256(abi.encode(PROFILE_TERMS_DOMAIN, detectFloorPpm, valueCaps, tiers));
    }

    /// V*: the highest value cap the account held within retentionBlocks,
    /// counted in unpaused blocks (ADR 0029).
    function _recentCap(uint32 bondId, BondTerms storage t) internal view returns (uint256) {
        return t.peakCap > t.sampleScaleValue && _heldUntil(bondId, t.peakUntil) ? t.peakCap : t.sampleScaleValue;
    }

    /// True while a hold of retentionBlocks that ends at `until` still runs:
    /// it began at until - retentionBlocks, and blocks in which a case of the
    /// account waited since then do not count (ADR 0029). Without such a
    /// block this is block.number <= until.
    function _heldUntil(uint32 bondId, uint256 until) internal view returns (bool) {
        if (block.number <= until) return true;
        return _unpausedWithin(
            bondId, until - profiles[bonds[bondId].profileId].parameters.retentionBlocks,
            profiles[bonds[bondId].profileId].parameters.retentionBlocks
        );
    }

    /// Sanction limit of a tier; a tier without one (sanctionLimit zero)
    /// counts as the largest, which no failure count reaches (ADR 0027).
    function _tierSanctionLimit(SalesTier storage tier) internal view returns (uint32) {
        return tier.sanctionLimit == 0 ? type(uint32).max : tier.sanctionLimit;
    }

    /// The highest tier sanction limit the account held within retentionBlocks,
    /// counted in unpaused blocks (ADR 0029).
    function _recentSanctionLimit(BondView storage b) internal view returns (uint32) {
        ProfileTerms storage pt = profileTerms[b.profileId];
        if (pt.tiers.length == 0) return 0;
        BondTerms storage t = bondTerms[b.bondId];
        uint32 limit = _tierSanctionLimit(pt.tiers[t.tier]);
        return t.peakLimit > limit && _heldUntil(b.bondId, t.peakLimitUntil) ? t.peakLimit : limit;
    }

    function _probabilityThreshold(uint32 ppm) internal pure returns (uint256) {
        if (ppm == 0) return 0;
        if (ppm == PPM) return type(uint256).max;
        uint256 quotient = type(uint256).max / PPM;
        uint256 remainder = type(uint256).max % PPM;
        return quotient * ppm + ((remainder + 1) * ppm) / PPM;
    }

    function _effectiveBond(uint256 bond, uint256 cap) internal pure returns (uint256) {
        return bond < cap ? bond : cap;
    }

    function _buyerRecoveryOpen(bytes32 nonce) internal view returns (bool) {
        uint8 state = buyerRecoveries[nonce].state;
        return state == uint8(CaseState.SERVE_WAIT) || state == uint8(CaseState.SERVE_CONFIRM)
            || state == uint8(CaseState.PUBLISHING);
    }

    function _buyerPublicationAccess(bytes32 nonce) internal view {
        CaseView storage recovery = buyerRecoveries[nonce];
        if (recovery.state != uint8(CaseState.PUBLISHING)) revert InvalidTransition();
        if (block.number > recovery.publishDue) revert DeadlinePassed();
        if (msg.sender != sellers[purchases[nonce].sellerId].viewData.owner) revert Unauthorized();
    }

    function _completeBuyerDelivery(bytes32 nonce) internal {
        buyerRecoveries[nonce].state = uint8(CaseState.DELIVERED);
        if (_costOn(purchases[nonce].profileId)) ExchangeStore.layout().ladders[nonce].recoveryDelivered = true;
        emit ServeAccepted(nonce, purchases[nonce].buyer);
        emit BuyerRecoveryClosed(nonce, uint8(CaseState.DELIVERED));
        uint8 state = cases[nonce].state;
        if (state == uint8(CaseState.NONE) || state == uint8(CaseState.DELIVERED)
            || state == uint8(CaseState.INCONCLUSIVE) || state == uint8(CaseState.FINAL)) {
            if (!_buyerRecoveryOpen(nonce) && !_refundDue(nonce)) _setFinancialState(nonce, FinancialState.RELEASABLE);
        }
    }

    function _finishBuyerPublication(bytes32 nonce, bytes32 responseHash, uint16 chunks, uint32 totalBytes) internal {
        emit ResponsePublished(nonce, responseHash, chunks, totalBytes);
        _completeBuyerDelivery(nonce);
    }

    function _assignVerifier(bytes32 nonce) internal {
        CaseView storage caseRecord = cases[nonce];
        PurchaseView storage purchase = purchases[nonce];
        // A batched profile places the case in a verifier queue (ADR 0032).
        if (_batched(purchase.profileId)) {
            _hook(HOOK_ENQUEUE, uint256(nonce));
            return;
        }
        AnchorView storage anchorRecord = anchors[purchase.sellerId][purchase.epoch];
        if (anchorRecord.state != uint8(EpochState.SEALED)) revert InvalidRandomnessWindow();
        // A case that waited searches the checkpoint of its last search, and
        // its initial attempts draw from the value of its last redraw (ADR 0028).
        AssignmentWait storage wait = assignmentWaits[nonce];
        uint64 version = wait.checkpointVersion;
        bool waited = version != 0;
        if (!waited) version = anchorRecord.sortitionVersion;
        // Pre-seal wrong-delivery cases start with no randomness. Bind their initial
        // assignment to the same immutable epoch value used by sampled cases.
        if (caseRecord.stage == uint8(JudgmentStage.INITIAL)) {
            caseRecord.randomness = waited ? wait.randomness : anchorRecord.randomness;
        }
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[purchase.profileId][version];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        uint256 liability = purchase.value + profile.maxReviewCost;

        uint96[] storage room = checkpointHeadroom[purchase.profileId][version];

        for (uint32 round; round < profile.minVerifiers; round++) {
            uint256 ticket = uint256(
                keccak256(
                    abi.encode(
                        ASSIGN_DOMAIN,
                        caseRecord.randomness,
                        nonce,
                        caseRecord.stage,
                        caseRecord.attempt,
                        round
                    )
                )
            ) % checkpoint.totalEffectiveWeight;
            (uint32 verifierId, uint256 index) = _ticketVerifier(checkpoint, ticket);
            if (caseParticipation[nonce][verifierId]) continue;
            // Eligibility is the verifier's state at the checkpoint block of
            // the epoch (decision 126, ADR 0025): status and bond through the
            // checkpoint itself, liability room through its snapshot. Cases
            // opened after that block, in any order, change neither, so the
            // first assignment follows the checkpoint table. A verifier that
            // is full now is still assigned; if it does not answer, the late
            // assignment is replaced by the next candidate as before.
            if (index >= room.length || liability > room[index]) continue;
            VerifierView storage verifier = verifiers[verifierId];
            VerifierCapital storage capital = verifierCapital[verifierId];
            uint256 reserve = profile.verifierLatePenalty > profile.verifierWrongPenalty
                ? profile.verifierLatePenalty : profile.verifierWrongPenalty;
            uint256 allReserved = capital.reservedPenalties + reserve;
            uint256 cap = verifier.lockedLiability == 0 ? profile.verifierBondCap
                : _effectiveBond(capital.conservativeCap, profile.verifierBondCap);
            uint32 fraction = verifier.lockedLiability == 0 || profile.verifierExposurePpm < capital.conservativeFraction
                ? profile.verifierExposurePpm : capital.conservativeFraction;
            capital.reservedPenalties = allReserved;
            capital.conservativeCap = cap;
            capital.conservativeFraction = fraction;
            assignmentHistory[nonce].push(AssignmentData(verifierId, caseRecord.stage, caseRecord.attempt,
                0, false, false, false, false, bytes32(0), liability, reserve));
            verifier.lockedLiability += liability;
            assignmentLiability[nonce] = liability;
            caseParticipation[nonce][verifierId] = true;
            caseRecord.assignedVerifierId = verifierId;
            caseRecord.judgeDue =
                uint64(block.number + deadlineConfigs[profile.deadlineConfigId].judgeBlocks);
            caseRecord.state = caseRecord.stage == uint8(JudgmentStage.INITIAL) ? uint8(CaseState.JUDGING)
                : caseRecord.stage == uint8(JudgmentStage.PARTY) ? uint8(CaseState.PARTY_REVIEW)
                : caseRecord.stage == uint8(JudgmentStage.AUTO) ? uint8(CaseState.AUTO_REVIEW)
                : uint8(CaseState.TIEBREAK);
            emit VerifierAssigned(
                nonce, caseRecord.stage, caseRecord.attempt, verifierId, caseRecord.judgeDue
            );
            return;
        }

        // The initial search of a sampled case lost no judgment: the case
        // waits, its purchase held, for a checkpoint written after this
        // search and a redraw value fixed after that checkpoint (ADR 0028).
        if (caseRecord.stage == uint8(JudgmentStage.INITIAL) && caseRecord.trigger == uint8(CaseTrigger.SAMPLE)) {
            _waitForCheckpoint(nonce, version);
            return;
        }
        _protocolInconclusive(nonce);
    }

    /// Records an exhausted search of the initial stage of a sampled case on
    /// checkpoint `version` and leaves the case waiting without a deadline.
    /// `attempt` does not move (ADR 0028).
    function _waitForCheckpoint(bytes32 nonce, uint64 version) internal {
        CaseView storage c = cases[nonce];
        AssignmentWait storage wait = assignmentWaits[nonce];
        wait.checkpointVersion = version;
        wait.searchBlock = uint64(block.number);
        // A redraw that finds nothing leaves the case waiting; only a case that
        // enters the wait stops the account's release clock (ADR 0029).
        if (c.state != uint8(CaseState.WAITING_ASSIGNMENT)) _clockWaitStarts(nonce);
        c.state = uint8(CaseState.WAITING_ASSIGNMENT);
        c.judgeDue = 0;
        if (!_waitHolds()) _setFinancialState(nonce, FinancialState.RELEASABLE);
        emit AssignmentWaiting(nonce, c.attempt, version);
    }

    /// A case of the account enters WAITING_ASSIGNMENT. The first one stops
    /// the account's release clock from this block on (ADR 0029). A pause
    /// that ended in this block is reopened, so pauses never touch.
    function _clockWaitStarts(bytes32 nonce) internal {
        uint32 bondId = sellers[purchases[nonce].sellerId].viewData.bondId;
        ReleaseClock storage clock = releaseClocks[bondId];
        if (clock.waitingCases++ != 0) return;
        uint32 n = clock.pauses;
        uint64 before;
        if (n != 0) {
            Pause storage last = pauseLog[bondId][n - 1];
            if (last.end == block.number) {
                last.end = 0;
                emit ReleaseClockPaused(bondId, last.pausedBefore + uint64(block.number) - last.start);
                return;
            }
            before = last.pausedBefore + last.end - last.start;
        }
        pauseLog[bondId][n] = Pause(uint64(block.number), 0, before);
        clock.pauses = n + 1;
        emit ReleaseClockPaused(bondId, before);
    }

    /// A waiting case of the account leaves WAITING_ASSIGNMENT, assigned by a
    /// redraw or ended. The last one restarts the release clock in this block,
    /// which counts again (ADR 0029). A pause that began in this block paused
    /// nothing and is dropped.
    function _clockWaitEnds(bytes32 nonce) internal {
        uint32 bondId = sellers[purchases[nonce].sellerId].viewData.bondId;
        ReleaseClock storage clock = releaseClocks[bondId];
        if (--clock.waitingCases != 0) return;
        uint32 n = clock.pauses;
        Pause storage last = pauseLog[bondId][n - 1];
        uint64 total = last.pausedBefore;
        if (last.start == block.number) {
            delete pauseLog[bondId][n - 1];
            clock.pauses = n - 1;
        } else {
            last.end = uint64(block.number);
            total += last.end - last.start;
        }
        emit ReleaseClockResumed(bondId, total);
    }

    /// Paused blocks of the account before block t, for t at most this block:
    /// the number of blocks u < t in which a case of the account waited.
    function _pausedBefore(uint32 bondId, uint256 t) internal view returns (uint256) {
        mapping(uint256 => Pause) storage log = pauseLog[bondId];
        uint256 lo;
        uint256 hi = releaseClocks[bondId].pauses;
        // lo becomes the number of pauses that started before t.
        while (lo < hi) {
            uint256 mid = (lo + hi) / 2;
            if (log[mid].start < t) lo = mid + 1;
            else hi = mid;
        }
        if (lo == 0) return 0;
        Pause storage p = log[lo - 1];
        uint256 end = p.end == 0 || p.end > t ? t : p.end;
        return p.pausedBefore + end - p.start;
    }

    /// Paused blocks of the account from block `from` through the block
    /// before this one: P(now) - P(from) in rule D2-21. An entry settled in
    /// block s has the effective age block.number - s - _pausedSince(s).
    /// Without a pause since `from` this reads two slots at most.
    function _pausedSince(uint32 bondId, uint256 from) internal view returns (uint256) {
        if (!_pauseHolds()) return 0;
        uint256 n = releaseClocks[bondId].pauses;
        if (n == 0 || from >= block.number) return 0;
        Pause storage last = pauseLog[bondId][n - 1];
        uint256 end = last.end == 0 ? block.number : last.end;
        if (end <= from) return 0;
        if (last.start < from) return end - from;
        return last.pausedBefore + end - last.start - _pausedBefore(bondId, from);
    }

    /// True while at most `span` unpaused blocks have passed since `start`,
    /// that is block.number - _pausedSince(start) <= start + span (ADR 0029).
    function _unpausedWithin(uint32 bondId, uint256 start, uint256 span) internal view returns (bool) {
        if (block.number <= start + span) return true;
        return block.number - _pausedSince(bondId, start) <= start + span;
    }

    /// A sampled case whose initial judgment cannot complete falls back to a
    /// keeper serve request before it may end as a protocol INCONCLUSIVE: the
    /// seller must still produce the sampled response, or the case is UNSERVED.
    /// Nobody checks an off-chain bundle on this path, so the request goes
    /// straight to on-chain publication with the serve deadline (ADR 0014).
    function _protocolInconclusive(bytes32 nonce) internal {
        CaseView storage c = cases[nonce];
        if (c.stage != uint8(JudgmentStage.INITIAL) || c.trigger != uint8(CaseTrigger.SAMPLE)
            || c.bundleHash != bytes32(0) || c.requesterRole == uint8(RequesterRole.KEEPER)) {
            _finishReview(nonce, uint8(Verdict.INCONCLUSIVE), true);
            return;
        }
        c.requester = msg.sender;
        c.requesterRole = uint8(RequesterRole.KEEPER);
        c.state = uint8(CaseState.PUBLISHING);
        c.serveDue = uint64(block.number
            + deadlineConfigs[profiles[purchases[nonce].profileId].parameters.deadlineConfigId].serveBlocks);
        c.publishDue = c.serveDue;
        emit ServeRequested(nonce, msg.sender, c.caseOpenedBlock, c.serveDue);
        emit ServeEscalated(nonce, c.publishDue);
    }

    function _finishProtocolInconclusive(bytes32 nonce) internal {
        CaseView storage c = cases[nonce];
        _sampleEnded(nonce);
        c.finalVerdict = uint8(Verdict.INCONCLUSIVE);
        c.state = uint8(CaseState.INCONCLUSIVE);
        if (!_refundDue(nonce)) {
            _setFinancialState(nonce, _buyerRecoveryOpen(nonce) ? FinancialState.HELD : FinancialState.RELEASABLE);
        }
        _releaseTrigger(nonce);
        emit CaseFinalized(nonce, uint8(Verdict.INCONCLUSIVE), purchases[nonce].financialState);
    }

    function _ticketVerifier(VerifierCheckpoint storage checkpoint, uint256 ticket)
        internal
        view
        returns (uint32, uint256)
    {
        uint256 cumulative;
        for (uint256 i; i < checkpoint.verifierIds.length; i++) {
            cumulative += checkpoint.weights[i];
            if (ticket < cumulative) return (checkpoint.verifierIds[i], i);
        }
        revert AssignmentExhausted();
    }

    /// The source in force for an epoch anchored in block `atBlock`, or zero.
    function _sourceAt(uint256 atBlock) internal view returns (IRandomness) {
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        return atBlock >= cfg.since && cfg.source != address(0) ? IRandomness(cfg.source) : IRandomness(address(0));
    }

    /// Request kinds of a request-based source (design 2 rule D2-23, ADR 0031).
    uint8 internal constant VRF_SAMPLE = 1;
    uint8 internal constant VRF_ASSIGN = 2;
    uint8 internal constant VRF_AUX = 3;
    /// Use of an AUX value: the redraw of a waiting case.
    bytes32 internal constant REDRAW_USE = keccak256("FairBind/redraw/v1");

    error RequestTooEarly();
    error NotRegistered();

    /// The request-based source in force for an epoch anchored in block
    /// `atBlock`, or zero when the source in force is not request based.
    function _vrfAt(uint256 atBlock) internal view returns (IVrfRandomness) {
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        return cfg.vrf && atBlock >= cfg.since ? IVrfRandomness(cfg.source) : IVrfRandomness(address(0));
    }

    /// Input of the SAMPLE request of profile `profileId` for anchor deadline A.
    function _sampleInput(uint32 profileId, uint64 anchorDeadline) internal pure returns (bytes memory) {
        return abi.encode(profileId, anchorDeadline);
    }

    /// Last block M = A + D_S + T_V in which the SAMPLE value of anchor
    /// deadline A is taken (rule D2-23 (d)); D_S is the source's delay.
    function _sampleDeadline(IVrfRandomness source, uint64 anchorDeadline) internal view returns (uint64) {
        return uint64(uint256(anchorDeadline) + source.delayBlocks() + source.deadlineSlackBlocks());
    }

    /// The SAMPLE value of an epoch of profile `profileId` with anchor
    /// deadline A, or zero while there is none that the contract accepts: a
    /// value stored after M is never taken (rule D2-23 (d)).
    function _sampleValue(IVrfRandomness source, uint32 profileId, uint64 anchorDeadline) internal view returns (bytes32) {
        bytes32 id = keccak256(abi.encode(VRF_SAMPLE, _sampleInput(profileId, anchorDeadline)));
        (bool ready, bytes32 value) = source.valueOf(id);
        if (!ready) return bytes32(0);
        (, uint64 delivered,) = source.requestTimes(id);
        return _sampleTaken(delivered, _sampleDeadline(source, anchorDeadline)) ? value : bytes32(0);
    }

    /// Whether a SAMPLE value stored in block `delivered` is taken under the
    /// deadline M. Every production build: delivered <= M. A mutation build
    /// of the tests takes every value.
    function _sampleTaken(uint64 delivered, uint64 deadline) internal pure virtual returns (bool) {
        return delivered <= deadline;
    }

    /// Input of the AUX request for redraw `redraw` of a waiting case whose
    /// use was registered in block t (rule D2-23 (a)): the use, its
    /// identifier (nonce, stage, redraw) and t.
    function _redrawInput(bytes32 nonce, uint32 redraw, uint64 registeredBlock) internal pure returns (bytes memory) {
        return abi.encode(REDRAW_USE, nonce, uint8(JudgmentStage.INITIAL), redraw, registeredBlock);
    }

    /// Blocks between the anchor deadline and the value: the profile's beacon
    /// delay, or the delay of the source in force, which may not exceed it so
    /// that the judgment horizon of the profile stays valid.
    function _valueDelay(ServiceProfileInput storage profile) internal view returns (uint256 delay) {
        delay = profile.beaconDelayBlocks;
        IRandomness source = _sourceAt(block.number);
        if (address(source) != address(0)) {
            uint256 sourceDelay = source.delayBlocks();
            if (sourceDelay > delay) revert InvalidConfiguration();
            delay = sourceDelay;
        }
    }

    /// The anchor deadline A of an epoch, from the profile alone.
    function _anchorDeadline(ServiceProfileInput storage profile, uint24 epoch) internal view returns (uint64) {
        return uint64(_anchorBase(profile, epoch) + deadlineConfigs[profile.deadlineConfigId].anchorBlocks);
    }

    /// Records an anchor whose list is complete: the one-transaction anchor, or
    /// the last unit of a split anchor.
    function _finishAnchor(
        uint32 sellerId,
        uint24 epoch,
        AnchorView storage record,
        ServiceProfileInput storage profile,
        uint256 deadline,
        bytes32 root,
        bytes32 publicationHash,
        uint32 count
    ) internal {
        record.root = root;
        record.publicationHash = publicationHash;
        record.anchoredBlock = uint64(block.number);
        // The value block is fixed by the anchor deadline alone and lies the
        // value delay (beaconDelayBlocks, or the shorter delay of the
        // randomness source in force) after the first block past that deadline.
        record.randomBlock = uint64(deadline + 1 + _valueDelay(profile));
        record.sealDeadline =
            uint64(record.randomBlock + deadlineConfigs[profile.deadlineConfigId].sealBlocks);
        record.profileId = sellers[sellerId].viewData.profileId;
        record.count = count;
        record.state = uint8(EpochState.ANCHORED);
        emit Anchored(sellerId, epoch, root, record.profileId, count, record.randomBlock, publicationHash);
    }

    function _consumeBucket(BondView storage b, ServiceProfileInput storage profile)
        internal
    {
        uint256 bucket = _refilledBucket(b, profile);
        if (bucket < PPM) revert RateLimitExceeded();
        b.bucketBalancePpm = bucket - PPM;
        b.bucketUpdatedBlock = uint64(block.number);
    }

    /// Bond bucket: unit capacity and refill of the profile times scaleFactor.
    function _refilledBucket(BondView storage b, ServiceProfileInput storage profile)
        internal
        view
        returns (uint256)
    {
        (, uint256 capacity, uint256 rate,,) = _unitTerms(b, profile);
        uint256 cap = capacity * b.scaleFactor * PPM;
        uint256 refill = uint256(block.number - b.bucketUpdatedBlock) * rate * b.scaleFactor;
        uint256 balance = b.bucketBalancePpm + refill;
        return balance > cap ? cap : balance;
    }

    function _epoch(ServiceProfileInput storage profile) internal view returns (uint24) {
        uint256 value = (block.number - profile.epochOrigin) / profile.epochBlocks;
        if (value > type(uint24).max) revert InvalidConfiguration();
        return uint24(value);
    }

    /// Pulls the payment with EIP-3009 receiveWithAuthorization. The token
    /// requires msg.sender == to, and `to` is this contract, so the buyer's
    /// authorization can be spent only through settle (ADR 0016).
    function _receiveWithAuthorization(
        TransferAuthorization calldata authorization,
        bytes calldata signature
    ) internal {
        if (signature.length != 65) {
            revert AuthorizationMismatch();
        }
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 32))
            v := byte(0, calldataload(add(signature.offset, 64)))
        }
        (bool ok, bytes memory result) = deploymentToken.call(
            abi.encodeCall(
                IFairBindToken.receiveWithAuthorization,
                (
                    authorization.from,
                    authorization.to,
                    authorization.value,
                    authorization.validAfter,
                    authorization.validBefore,
                    authorization.nonce,
                    v,
                    r,
                    s
                )
            )
        );
        if (!ok || (result.length != 0 && !abi.decode(result, (bool)))) revert TransferFailed();
    }

    function _transferFrom(address from, uint256 value) internal {
        (bool ok, bytes memory result) = deploymentToken.call(
            abi.encodeCall(IFairBindToken.transferFrom, (from, address(this), value))
        );
        if (!ok || (result.length != 0 && !abi.decode(result, (bool)))) revert TransferFailed();
    }

    function _transfer(address to, uint256 value) internal {
        (bool ok, bytes memory result) =
            deploymentToken.call(abi.encodeCall(IFairBindToken.transfer, (to, value)));
        if (!ok || (result.length != 0 && !abi.decode(result, (bool)))) revert TransferFailed();
    }
    function _verdictDigest(SignedVerdict calldata v) internal view returns (bytes32) {
        bytes32 h = keccak256(abi.encode(VERDICT_TYPEHASH, v.version, v.nonce, v.stage,
            v.attempt, v.verifierId, v.verdict, v.evidenceHash));
        bytes32 domain = keccak256(abi.encode(EIP712_DOMAIN_TYPEHASH,
            keccak256("FairBind"), keccak256("1"), block.chainid, address(this)));
        return keccak256(abi.encodePacked(hex"1901", domain, h));
    }

    function _activeAssignment(bytes32 nonce) internal view returns (AssignmentData storage a) {
        AssignmentData[] storage list = assignmentHistory[nonce];
        if (list.length == 0) revert InvalidTransition();
        a = list[list.length - 1];
        if (a.released || a.verifierId != cases[nonce].assignedVerifierId
            || a.stage != cases[nonce].stage || a.attempt != cases[nonce].attempt) revert InvalidTransition();
    }

    function _judgmentActive(bytes32 nonce) internal view returns (bool) {
        CaseView storage c = cases[nonce];
        return c.assignedVerifierId != 0 && (c.state == uint8(CaseState.JUDGING)
            || c.state == uint8(CaseState.PARTY_REVIEW) || c.state == uint8(CaseState.AUTO_REVIEW)
            || c.state == uint8(CaseState.TIEBREAK));
    }

    function _releaseAssignment(bytes32 nonce, AssignmentData storage a, uint256 penalty, address recipient) internal {
        if (a.released) return;
        if (penalty > a.penaltyReserve) revert InvalidConfiguration();
        VerifierView storage v = verifiers[a.verifierId];
        // An assignment taken on checkpoint room may exceed the current bond
        // (ADR 0025): the penalty takes at most what is left.
        if (penalty > v.bond) penalty = v.bond;
        VerifierCapital storage capital = verifierCapital[a.verifierId];
        a.released = true;
        v.lockedLiability -= a.liability;
        capital.reservedPenalties -= a.penaltyReserve;
        if (v.lockedLiability == 0) {
            capital.conservativeCap = 0;
            capital.conservativeFraction = 0;
        }
        if (penalty != 0) {
            _noteVerifier(a.verifierId);
            v.bond -= penalty;
            if (v.strikes < type(uint16).max) v.strikes++;
            if (v.strikes >= profiles[purchases[nonce].profileId].parameters.strikeLimit
                && (v.status == uint8(VerifierStatus.ACTIVE) || v.status == uint8(VerifierStatus.EXITING))) v.status = uint8(VerifierStatus.REMOVED);
            _transfer(recipient, penalty);
            emit Slashed(2, a.verifierId, nonce, recipient, penalty, a.verdict == 0 ? 2 : 3);
        }
        // The assignment held a slot of the verifier (ADR 0032).
        if (BatchStore.layout().entries[nonce].kind != 0) _hook(HOOK_SLOT_FREED, a.verifierId);
    }

    function _releaseAllAssignments(bytes32 nonce) internal {
        AssignmentData[] storage list = assignmentHistory[nonce];
        for (uint256 i; i < list.length; i++) _releaseAssignment(nonce, list[i], 0, penaltyTreasury);
        assignmentLiability[nonce] = 0;
        cases[nonce].assignedVerifierId = 0;
    }

    function _resolveAppealDeposit(bytes32 nonce, uint8 result) internal virtual {
        ReviewData storage r = reviews[nonce];
        uint256 amount = r.deposit;
        if (amount == 0) return;
        r.deposit = 0;
        PurchaseView storage p = purchases[nonce];
        address seller = sellers[p.sellerId].viewData.owner;
        address recipient = result == uint8(Verdict.INCONCLUSIVE) || result != cases[nonce].initialVerdict
            ? r.appellant : r.appellant == p.buyer ? seller : p.buyer;
        // A proportional deposit above the fixed one goes to the seller only
        // up to the fixed one when the appeal fails; the rest stays locked
        // (ADR 0033).
        uint256 excess = BatchStore.layout().depositExcess[nonce];
        if (excess != 0) {
            BatchStore.layout().depositExcess[nonce] = 0;
            if (recipient == seller) {
                amount -= excess;
                lockedForfeit += excess;
                emit DepositResolved(nonce, 4, address(this), excess);
            }
        }
        _transfer(recipient, amount);
        emit DepositResolved(nonce, 2, recipient, amount);
    }

    function _finishReview(bytes32 nonce, uint8 result, bool progressFailure) internal {
        CaseView storage c = cases[nonce];
        ServiceProfileInput storage p = profiles[purchases[nonce].profileId].parameters;
        AssignmentData[] storage list = assignmentHistory[nonce];
        // A review the seller appealed against an initial FAIL, including the
        // tiebreak it leads to, upholds that FAIL when it cannot progress. No
        // review verdict is penalized and the appeal deposit goes to the buyer
        // (ADR 0024).
        bool upheld = progressFailure && c.reviewPath == 1 && c.initialVerdict == uint8(Verdict.FAIL);
        if (upheld) result = uint8(Verdict.FAIL);
        // A wrong-verdict penalty goes to the appellant only when it won the
        // review; after a tiebreak that confirms the initial verdict, and on the
        // automatic path, it goes to the treasury.
        address recipient = c.reviewPath == 1 && result != c.initialVerdict && result != uint8(Verdict.INCONCLUSIVE)
            ? reviews[nonce].appellant : penaltyTreasury;
        for (uint256 i; i < list.length; i++) {
            AssignmentData storage a = list[i];
            uint256 penalty;
            if (!upheld && result != uint8(Verdict.INCONCLUSIVE) && a.verdict != uint8(Verdict.NONE)
                && a.verdict != uint8(Verdict.INCONCLUSIVE) && a.verdict != result) penalty = p.verifierWrongPenalty;
            _releaseAssignment(nonce, a, penalty, recipient);
        }
        assignmentLiability[nonce] = 0;
        c.assignedVerifierId = 0;
        _resolveAppealDeposit(nonce, result);
        _sampleEnded(nonce);
        c.finalVerdict = result;
        c.state = uint8(progressFailure ? CaseState.INCONCLUSIVE : CaseState.FINAL);
        if (result == uint8(Verdict.FAIL)) {
            _sellerFailure(nonce, RefundSource.FINAL_FAIL);
            c.state = uint8(CaseState.FINAL);
        } else {
            if (!_refundDue(nonce)) {
                _setFinancialState(nonce, _buyerRecoveryOpen(nonce) ? FinancialState.HELD : FinancialState.RELEASABLE);
            }
            _releaseTrigger(nonce);
        }
        if (!progressFailure) _recordJudged(nonce, result);
        emit CaseFinalized(nonce, result, purchases[nonce].financialState);
    }

    function _replaceLateAssignment(bytes32 nonce) internal {
        CaseView storage c = cases[nonce];
        AssignmentData storage a = _activeAssignment(nonce);
        ServiceProfileInput storage p = profiles[purchases[nonce].profileId].parameters;
        a.verdict = 0; // A void verdict has only a late penalty, never a content penalty.
        _releaseAssignment(nonce, a, p.verifierLatePenalty, penaltyTreasury);
        assignmentLiability[nonce] = 0;
        c.assignedVerifierId = 0;
        c.evidenceHash = 0;
        c.evidenceDue = 0;
        if (c.stage == uint8(JudgmentStage.INITIAL)) {
            c.initialVerdict = 0;
            reviews[nonce].appealUntil = 0;
            c.randomBlock = 0;
        }
        if (uint256(c.attempt) + 1 >= p.maxAssignments) {
            _protocolInconclusive(nonce);
            return;
        }
        c.attempt++;
        c.state = uint8(CaseState.ASSIGNING);
        _assignVerifier(nonce);
    }

    function _evidencePending(bytes32 nonce) internal view returns (bool) {
        if (cases[nonce].state != uint8(CaseState.INITIAL_VERDICT)) return false;
        AssignmentData storage a = _activeAssignment(nonce);
        return a.evidenceRequested && !a.evidenceDisclosed;
    }

    function _startReview(bytes32 nonce, uint8 stage, uint8 state, uint64 randomBlock) internal {
        CaseView storage c = cases[nonce];
        c.stage = stage;
        c.attempt = 0;
        c.state = state;
        c.randomBlock = randomBlock;
        c.randomness = 0;
        c.judgeDue = 0;
        c.evidenceDue = 0;
        c.assignedVerifierId = 0;
        assignmentLiability[nonce] = 0;
        // A batched review stage draws from the AUX value of this block's use.
        if (_batched(purchases[nonce].profileId)) _hook(HOOK_REVIEW_USE, uint256(nonce));
    }

    /// Fixes the review randomness of the current stage: the hash of its
    /// randomBlock, which never moves (rule D2-16 (e), ADR 0025). Any call in
    /// (randomBlock, randomBlock + sealBlocks] seals. The first call after that
    /// window reopens the seal once until one block plus sealBlocks later and
    /// records the hash if the chain still serves it; a call in the reopened
    /// window seals with that same value. The stage ends as a progress failure
    /// when the reopened window passes, or at once when the hash is gone before
    /// anyone recorded it (ADR 0021, ADR 0024).
    function _sealReview(bytes32 nonce) internal returns (bool) {
        CaseView storage c = cases[nonce];
        uint256 random = c.randomBlock;
        if (block.number <= random) revert DeadlineNotReached();
        // blockhash serves the last 256 blocks only.
        if (c.randomness == 0 && block.number <= random + 256) c.randomness = blockhash(random);
        uint8 bit = uint8(1) << c.stage;
        uint8 resealed = reviewReseals[nonce];
        uint256 due = resealed & bit == 0
            ? random + deadlineConfigs[profiles[purchases[nonce].profileId].parameters.deadlineConfigId].sealBlocks
            : reviewResealDue[nonce];
        if (block.number <= due && c.randomness != 0) return true;
        if (resealed & bit == 0 && (c.randomness != 0 || block.number <= random + 256)) {
            reviewReseals[nonce] = resealed | bit;
            reviewResealDue[nonce] = uint64(block.number + 1 + (due - random));
            emit ReviewResealed(nonce, c.stage, c.randomBlock);
        } else {
            _finishReview(nonce, uint8(Verdict.INCONCLUSIVE), true);
        }
        return false;
    }

    /// Automatic recheck of an unappealed initial PASS or INCONCLUSIVE with
    /// probability recheckPpm (ADR 0019); otherwise the initial verdict is final.
    function _openAutoReview(bytes32 nonce) internal {
        CaseView storage c = cases[nonce];
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.initialVerdict == uint8(Verdict.FAIL)
            || c.reviewPath != 0 || _evidencePending(nonce)) revert InvalidTransition();
        if (!_sealReview(nonce)) return;
        ServiceProfileInput storage p = profiles[purchases[nonce].profileId].parameters;
        uint256 value = uint256(keccak256(abi.encode(RECHECK_DOMAIN, c.randomness, nonce)));
        bool selected = p.recheckPpm == PPM || (p.recheckPpm != 0 && value < _probabilityThreshold(p.recheckPpm));
        if (!selected) {
            _finishReview(nonce, c.initialVerdict, false);
            return;
        }
        c.reviewPath = 2;
        c.stage = uint8(JudgmentStage.AUTO);
        c.attempt = 0;
        c.assignedVerifierId = 0;
        c.state = uint8(CaseState.ASSIGNING);
        emit ReviewSelected(nonce, false, true, c.randomBlock);
        // A batched recheck waits for the AUX value of this selection.
        if (_batched(purchases[nonce].profileId)) {
            c.state = uint8(CaseState.AUTO_REVIEW);
            _hook(HOOK_REVIEW_USE, uint256(nonce));
            return;
        }
        _assignVerifier(nonce);
    }

    /// Admission floor of beaconDelayBlocks: the delay of a request-based
    /// source when one is set (its D_S), the block-hash floor otherwise.
    function _beaconFloor() internal view returns (uint256) {
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        return cfg.vrf ? IRandomness(cfg.source).delayBlocks() : MIN_BEACON_DELAY_BLOCKS;
    }

    /// Whether a profile assigns its cases in batches (ADR 0032).
    function _batched(uint32 profileId) internal view returns (bool) {
        return BatchStore.layout().terms[profileId].batched;
    }

    /// Value of `entered` while a module runs a call into an extension module.
    uint256 internal constant HOOK_CONTEXT = 3;
    /// Calls the modules make into the extension modules (ADR 0032): one
    /// selector, an operation and one argument.
    bytes4 internal constant HOOK_SELECTOR = bytes4(keccak256("hook(uint256,uint256)"));
    uint256 internal constant HOOK_ENQUEUE = 1;
    uint256 internal constant HOOK_SLOT_FREED = 2;
    uint256 internal constant HOOK_CASE_LEAVES = 3;
    uint256 internal constant HOOK_START_HEADS = 4;
    uint256 internal constant HOOK_NOTE = 5;
    uint256 internal constant HOOK_SAMPLE_ENDED = 6;
    uint256 internal constant HOOK_JOIN_PROOF = 7;
    uint256 internal constant HOOK_PLACE_PROOF = 8;
    uint256 internal constant HOOK_PROGRESS = 9;
    uint256 internal constant HOOK_REVIEW_USE = 10;
    uint256 internal constant HOOK_SAMPLE_RESUME = 11;
    uint256 internal constant HOOK_FAILURE = 16;
    uint256 internal constant HOOK_PROOF_EXIT = 24;
    uint256 internal constant HOOK_PASS_FAILURE = 25;
    uint256 internal constant HOOK_LADDER_PAY = 26;
    /// Rule edition 8: the fee of a required call, the copy of a profile seal
    /// (plain, for seal, for a checkpoint shortage), a purchase that left the
    /// held state, a WRONG_DELIVERY dispute, and the verifier exit check.
    uint256 internal constant HOOK_R8_FEE = 27;
    uint256 internal constant HOOK_R8_MAT = 28;
    uint256 internal constant HOOK_R8_SEAL = 29;
    uint256 internal constant HOOK_R8_SEAL_FAIL = 30;
    uint256 internal constant HOOK_R8_LEFT = 31;
    uint256 internal constant HOOK_R8_WRONG = 32;
    uint256 internal constant HOOK_R8_EXIT = 33;
    uint256 internal constant HOOK_R8_SUSPEND = 34;
    uint256 internal constant HOOK_R8_FEE_ONCE = 35;

    /// Runs hook `op` with `arg` in the extension module that implements it.
    /// The call runs in the hook context, so that a hook reached through the
    /// router itself reverts.
    function _hook(uint256 op, uint256 arg) internal {
        address ext = BatchStore.layout().hookExt[op];
        if (ext == address(0)) revert InvalidConfiguration();
        uint256 previous = entered;
        entered = HOOK_CONTEXT;
        bytes4 sel = HOOK_SELECTOR;
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, sel)
            mstore(add(p, 4), op)
            mstore(add(p, 36), arg)
            if iszero(delegatecall(gas(), ext, p, 68, 0, 0)) {
                returndatacopy(p, 0, returndatasize())
                revert(p, returndatasize())
            }
        }
        entered = previous;
    }

    /// Keeps the verifier's eligibility state before a change in this block
    /// once batched profiles exist (ADR 0032): a checkpoint written later for
    /// an earlier block reads it.
    function _noteVerifier(uint32 id) internal {
        if (BatchStore.layout().historyOn) _hook(HOOK_NOTE, id);
    }

    /// A sample case of a batched profile ended: it no longer blocks seller
    /// proofs of its account, and its sale no longer holds side-gain deposit
    /// (ADR 0034, ADR 0035).
    function _sampleEnded(bytes32 nonce) internal {
        if (BatchStore.layout().entries[nonce].counted) _hook(HOOK_SAMPLE_ENDED, uint256(nonce));
    }

    /// The high mark of the account's held total at the end of block x, for x
    /// at most the current block when no settlement of the account came after
    /// x (ADR 0033). Windows are fixed intervals of deferBlocks.
    function _heldHigh(BatchStore.HeldMark storage m, uint256 x, uint256 windowBlocks) internal view returns (uint256) {
        uint256 k = x / windowBlocks;
        if (k == m.window) return m.cur > m.prev ? m.cur : m.prev;
        if (k == uint256(m.window) + 1) return m.cur;
        return m.last;
    }

    /// The value of the repeated SAMPLE request of a side-gain profile, asked
    /// for after M with input (profileId, A, 1) and no deadline (ADR 0035).
    function _repeatedSampleValue(IVrfRandomness source, uint32 profileId, uint64 anchorDeadline)
        internal
        view
        returns (bytes32)
    {
        (bool ready, bytes32 value) =
            source.valueOf(keccak256(abi.encode(VRF_SAMPLE, abi.encode(profileId, anchorDeadline, uint32(1)))));
        return ready ? value : bytes32(0);
    }

    /// The seller's epoch has its sampling decided or no sampling at all: it
    /// no longer blocks seller proofs of the account (ADR 0034).
    function _epochResolved(uint32 sellerId, uint24 epoch) internal {
        BatchStore.Layout storage l = BatchStore.layout();
        // A late sampling value no longer pauses the account (rule D2-21 (a)(iv)).
        if (l.samplePaused[sellerId][epoch]) _hook(HOOK_SAMPLE_RESUME, (uint256(sellerId) << 24) | epoch);
        if (!l.epochCounted[sellerId][epoch] || l.epochResolved[sellerId][epoch]) return;
        l.epochResolved[sellerId][epoch] = true;
        l.proofAccounts[sellers[sellerId].viewData.bondId].unsealedEpochs--;
    }

    /// Side-gain deposit of one open sale: ceil(eta * V / p0) at the
    /// account's recent value cap V (ADR 0035).
    function _sideGainUnit(uint32 bondId, uint32 profileId) internal view returns (uint256) {
        ProfileTerms storage pt = profileTerms[profileId];
        bool tiered = pt.tiers.length != 0;
        uint256 cap = tiered ? _recentCap(bondId, bondTerms[bondId]) : profiles[profileId].parameters.maxPurchaseValue;
        uint256 p0 = tiered ? pt.detectFloorPpm : profiles[profileId].parameters.effectivePpm;
        return (uint256(BatchStore.layout().terms[profileId].sideGainPpm) * cap + p0 - 1) / p0;
    }

    // ------------------------------------------- receipt signatures (ADR 0037)

    /// The receipt-signature mode of a profile: none, PROOF or VOTE_SIG.
    function _exchangeMode(uint32 profileId) internal view returns (uint8) {
        return ExchangeStore.layout().terms[profileId].mode;
    }

    // ------------------------------------------------ rule edition 8 (v0.3)

    /// Pays the caller of a required call of a rule 8 profile the fee of its
    /// kind from the profile fee pool (rule D2-38 (a)), after the call's
    /// body: a call that moves no state reverts in its body and is not paid.
    /// The fee depends on the kind only, not on the case's result (rule
    /// D2-38 (c)). Nothing for an edition 7 profile.
    modifier r8Fee(bytes32 nonce, uint8 kind) {
        _;
        _r8Fee(purchases[nonce].profileId, kind);
    }

    function _r8Fee(uint32 profileId, uint8 kind) internal {
        _r8Hook(profileId, HOOK_R8_FEE, (uint256(profileId) << 8) | kind);
    }

    /// Runs rule 8 hook `op` with `arg` when the profile runs rule 8, and
    /// says whether it does. One function for every rule 8 call of the
    /// modules, so that the call is not repeated in their code.
    function _r8Hook(uint32 profileId, uint256 op, uint256 arg) internal returns (bool on) {
        on = _r8On(profileId);
        if (on) _hook(op, arg);
    }

    /// The fee of a profile-level call of kind `kind`, paid once per
    /// profile and `at` (an epoch or an anchor deadline).
    function _r8FeeOnce(uint32 profileId, uint8 kind, uint64 at) internal {
        _r8Hook(profileId, HOOK_R8_FEE_ONCE, (uint256(kind) << 128) | (uint256(profileId) << 64) | at);
    }

    /// Whether a profile runs rule edition 8: its terms were set once before
    /// activation. Every other profile keeps edition 7.
    function _r8On(uint32 profileId) internal view returns (bool) {
        return _r8Possible() && Rule8Store.layout().terms[profileId].on;
    }

    /// True in every module that may handle a rule 8 profile. A module of
    /// batched profiles only returns false (setRule8Terms refuses a batched
    /// profile), which drops the rule 8 code from it.
    function _r8Possible() internal pure virtual returns (bool) {
        return true;
    }

    /// A purchase of a rule 8 profile is about to leave the held state (to
    /// REFUNDABLE, REFUNDED, RELEASED or FORFEITED): the rule 8 module counts
    /// it out of the held count when it was held (rule D2-42 (g)). It reads
    /// the old state, so it runs before the state is written.
    function _r8Leaving(bytes32 nonce, uint32 profileId) internal {
        _r8Hook(profileId, HOOK_R8_LEFT, uint256(nonce));
    }

    /// Selector of the rule 8 module's view of whether a purchase was paid.
    bytes4 internal constant R8_PAID_SELECTOR = bytes4(keccak256("r8Paid(bytes32)"));

    /// Whether a purchase of a rule 8 profile was paid to the seller by the
    /// batch payment of its seller epoch (rule D2-39 (c)): such a purchase
    /// is no longer the seller's held proceeds, so it is not frozen, claimed
    /// or forfeited. The rule 8 module answers through a static call to the
    /// router, which keeps this check out of every module's code.
    function _r8Paid(PurchaseView storage purchase) internal view returns (bool) {
        if (!_r8On(purchase.profileId)) return false;
        (bool ok, bytes memory ret) =
            address(this).staticcall(abi.encodeWithSelector(R8_PAID_SELECTOR, purchaseForKey[purchase.keyId]));
        if (!ok || ret.length != 32) revert InvalidConfiguration();
        return abi.decode(ret, (bool));
    }

    /// Whether a profile measures the seller's cost of the calls it pays for.
    function _costOn(uint32 profileId) internal view returns (bool) {
        return ExchangeStore.layout().terms[profileId].costOn;
    }

    /// Whether the purchase's receipt signature matched its anchor leaf.
    function _bound(bytes32 nonce) internal view returns (bool) {
        return uint256(ExchangeStore.layout().bundles[nonce]) & 1 == 1;
    }

    /// Whether a dispute refunded the purchase while its sample case stays.
    function _refundedEarly(bytes32 nonce) internal view returns (bool) {
        uint8 fs = purchases[nonce].financialState;
        return (fs == uint8(FinancialState.REFUNDABLE) || fs == uint8(FinancialState.REFUNDED))
            && ExchangeStore.layout().records[nonce].early;
    }

    /// The purchase already carries its refund: the end of its case changes
    /// no financial state.
    function _refundDue(bytes32 nonce) internal view returns (bool) {
        uint8 fs = purchases[nonce].financialState;
        return fs == uint8(FinancialState.REFUNDABLE) || fs == uint8(FinancialState.REFUNDED);
    }

    /// OP Stack predeploy whose getL1FeeUpperBound bounds the L1 data fee of
    /// a transaction from its unsigned size.
    address internal constant GAS_PRICE_ORACLE = 0x420000000000000000000000000000000000000F;

    /// The measured cost of this call (rule D2-33 (e') 1, ADR 0037), in token
    /// units: pi * ((g + gFix) * basefee + UB(|xhat| + bEnv)) / 1e18, rounded
    /// down, UB the oracle's getL1FeeUpperBound. g is the gas used since
    /// `gasStart` less `excluded`; gFix is gFixCall plus, for the first such
    /// call of the transaction, gFixTx. bEnv bounds the bytes of the unsigned
    /// envelope outside the call data (the oracle adds the signature).
    /// Priority fees never count.
    function _measuredCost(ExchangeStore.Terms storage t, uint256 gasStart, uint256 excluded, bytes memory xhat)
        internal
        returns (uint256)
    {
        bool first = _firstCostOfTx();
        uint256 l1 = _l1Share(xhat, t.bEnv, first);
        uint256 gas = gasStart - gasleft() - excluded + t.gFixCall + (first ? t.gFixTx : 0);
        return (gas * block.basefee + l1) * t.priceCap / 1e18;
    }

    /// Whether no call of this transaction counted the fixed share yet; marks
    /// it counted (EIP-1153). A mutation build of the tests overrides it.
    function _firstCostOfTx() internal virtual returns (bool first) {
        bytes32 slot = ExchangeStore.COST_MARK;
        assembly ("memory-safe") {
            first := iszero(tload(slot))
            tstore(slot, 1)
        }
    }

    /// The L1 share of a measured call: UB(|xhat| + env) for the first call
    /// of the transaction, UB(|xhat| + env) - UB(env) for a later one, which
    /// leaves the envelope and the size floor to the first. It depends on the
    /// length of xhat only. Zero where the oracle does not answer, which the
    /// activation check leaves to test chains. A mutation build of the tests
    /// overrides it.
    function _l1Share(bytes memory xhat, uint256 env, bool first) internal view virtual returns (uint256 l1) {
        (, l1) = _l1Bound(xhat.length + env);
        if (!first) {
            (, uint256 floor) = _l1Bound(env);
            l1 = l1 > floor ? l1 - floor : 0;
        }
    }

    /// getL1FeeUpperBound(n) of the oracle, and whether it answered.
    function _l1Bound(uint256 n) internal view returns (bool ok, uint256 fee) {
        address oracle = GAS_PRICE_ORACLE;
        if (oracle.code.length == 0) return (false, 0);
        bytes memory ret;
        (ok, ret) = oracle.staticcall(abi.encodeWithSignature("getL1FeeUpperBound(uint256)", n));
        ok = ok && ret.length >= 32;
        if (ok) fee = abi.decode(ret, (uint256));
    }

    /// Whether a seller call of the delivery ladder on `nonce` is measured:
    /// the buyer's non-delivery dispute (or its buyer recovery) under a
    /// profile that measures costs.
    function _ladderOn(bytes32 nonce, bool recovery) internal view returns (bool) {
        if (!_costOn(purchases[nonce].profileId)) return false;
        if (recovery) return true;
        CaseView storage c = cases[nonce];
        return c.requesterRole == uint8(RequesterRole.BUYER) && c.trigger == uint8(CaseTrigger.NON_DELIVERY);
    }

    /// Adds the measured cost of this ladder call to the dispute's sum. The
    /// call data must be the canonical encoding `xhat` of its arguments.
    function _ladderCost(bytes32 nonce, bool recovery, uint256 gasStart, bytes memory xhat) internal {
        if (xhat.length != msg.data.length) revert NonCanonical();
        uint256 c = _measuredCost(ExchangeStore.layout().terms[purchases[nonce].profileId], gasStart, 0, xhat);
        ExchangeStore.Ladder storage lad = ExchangeStore.layout().ladders[nonce];
        if (recovery) lad.recoveryCost += uint96(c);
        else lad.cost += uint96(c);
    }
}
