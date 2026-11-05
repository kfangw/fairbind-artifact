// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";

/// Read functions of the shared state. The router keeps their selectors and
/// forwards each call here through a static call to itself, so that it
/// carries none of the encoders (ADR 0025).
contract FairBindLens is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 10;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function deriveKeyId(uint32 sellerId, address buyer, bytes16 key) external view onlyDelegateCall returns (bytes32) {
        return _deriveKeyId(sellerId, buyer, key);
    }

    function deriveNonce(
        uint32 sellerId,
        uint32 profileId,
        bytes32 claimsHash,
        address buyer,
        bytes16 key,
        bytes32 requestHash
    ) external view onlyDelegateCall returns (bytes32) {
        return _deriveNonce(sellerId, profileId, claimsHash, buyer, key, requestHash);
    }

    function purchaseByKey(bytes32 keyId) external view onlyDelegateCall returns (bytes32) {
        return purchaseForKey[keyId];
    }

    function getDeadlineConfig(uint32 id) external view onlyDelegateCall returns (DeadlineConfig memory) {
        if (!deadlineConfigExists[id]) revert UnknownDeadlineConfig();
        return deadlineConfigs[id];
    }

    function getServiceProfile(uint32 id) external view onlyDelegateCall returns (ServiceProfileView memory) {
        if (profiles[id].profileId == 0) revert UnknownProfile();
        return profiles[id];
    }

    function getSeller(uint32 id) external view onlyDelegateCall returns (SellerView memory) {
        return sellers[id].viewData;
    }

    function getVerifier(uint32 id) external view onlyDelegateCall returns (VerifierView memory) {
        return verifiers[id];
    }

    function getPurchase(bytes32 nonce) external view onlyDelegateCall returns (PurchaseView memory) {
        PurchaseView memory p = purchases[nonce];
        // Neither the nonce nor the claims hash is stored per purchase (see settle):
        // the nonce is the key and the claims hash is the account's.
        if (p.settledBlock != 0) {
            p.nonce = nonce;
            p.claimsHash = sellers[p.sellerId].viewData.claimsHash;
        }
        return p;
    }

    function getCase(bytes32 nonce) external view onlyDelegateCall returns (CaseView memory) {
        return cases[nonce];
    }

    function getAnchor(uint32 sellerId, uint24 epoch) external view onlyDelegateCall returns (AnchorView memory) {
        return anchors[sellerId][epoch];
    }

    function getVerifierCheckpoint(uint32 profileId, uint64 version)
        external
        view
        onlyDelegateCall
        returns (
            uint64 checkpointBlock,
            uint32[] memory verifierIds,
            uint96[] memory weights,
            uint256 totalEffectiveWeight,
            bytes32 setHash
        )
    {
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[profileId][version];
        return (
            checkpoint.checkpointBlock,
            checkpoint.verifierIds,
            checkpoint.weights,
            checkpoint.totalEffectiveWeight,
            checkpoint.setHash
        );
    }

    function isSampled(bytes32 nonce) external view onlyDelegateCall returns (bool eligible, bool known) {
        PurchaseView storage purchase = purchases[nonce];
        if (!_purchaseExists(purchase)) return (false, false);
        return _sampleStatus(purchase, nonce);
    }

    function quoteSeller(uint32 sellerId) external view onlyDelegateCall returns (SellerQuote memory quote) {
        SellerView storage seller = sellers[sellerId].viewData;
        ServiceProfileInput storage profile = profiles[seller.profileId].parameters;
        uint256 bucket = _refilledBucket(bonds[seller.bondId], profile);
        quote = SellerQuote(
            sellerId,
            seller.profileId,
            seller.claimsHash,
            deploymentToken,
            profileTerms[seller.profileId].tiers.length == 0 ? profile.maxPurchaseValue : bondTerms[seller.bondId].sampleScaleValue,
            bucket,
            uint32(bucket / PPM),
            uint64(block.number),
            _epoch(profile),
            seller.status,
            seller.bondId
        );
    }

    function receiptDigest(FairBindReceipt calldata receipt) external view onlyDelegateCall returns (bytes32) {
        return _receiptDigest(receipt);
    }

    function getBuyerRecovery(bytes32 nonce) external view onlyDelegateCall returns (CaseView memory) {
        return buyerRecoveries[nonce];
    }

    function getBond(uint32 bondId) external view onlyDelegateCall returns (BondView memory) {
        return bonds[bondId];
    }

    function getFrozenPool(uint32 bondId) external view onlyDelegateCall returns (FrozenPoolView memory pool) {
        BondView storage b = bonds[bondId];
        // The pool is the frozen window only: entries settled after a
        // reinstatement during an open claim window are outside it (ADR 0021).
        // Unreleased entries settled before the window's span (ADR 0030) are
        // counted here too, so the value is an upper bound when there are any.
        ClaimReentry storage late = claimReentries[bondId];
        uint256 pending = b.freezeState == uint8(FreezeState.FROZEN) || b.freezeState == uint8(FreezeState.CLAIM_OPEN)
            ? (b.deferredBalance - late.deferredBalance) - (b.encumbered - late.encumbered) : 0;
        pool = FrozenPoolView(bondId, b.freezeState, b.freezeNonce, b.freezeBlock, b.claimUntilBlock,
            b.forfeitedThrough, pending, b.encumbered - late.encumbered, b.claimedTotal, b.forfeitedTotal);
    }

    /// Spans of the open freeze of a bond account, in settlement blocks (ADR 0030).
    function getFreezeSpans(uint32 bondId) external view onlyDelegateCall returns (FreezeSpan[] memory) {
        return freezeSpans[bondId];
    }

    /// Spans of the closed claim windows of a bond account, and whether each
    /// closed itemized (ADR 0030).
    function getForfeitWindows(uint32 bondId) external view onlyDelegateCall returns (ForfeitWindow[] memory) {
        return forfeitWindows[bondId];
    }

    /// Pending initial-FAIL triggers of a bond account: earliest, latest and count.
    function getFreezeTriggers(uint32 bondId) external view onlyDelegateCall returns (TriggerQueue memory) {
        return freezeTriggers[bondId];
    }

    /// Re-entry state of an open claim window: whether a reinstatement reopened
    /// the account, and the totals of the entries settled after freezeBlock.
    function getClaimReentry(uint32 bondId) external view onlyDelegateCall returns (ClaimReentry memory) {
        return claimReentries[bondId];
    }

    /// Scale factor at which the current failure window of a bond account
    /// opened; its sanction threshold is this times failureLimit, or times the
    /// window's sanction limit under a profile with tiers (ADR 0027).
    function getFailureWindowScale(uint32 bondId) external view onlyDelegateCall returns (uint32) {
        return failureWindowScale[bondId];
    }

    /// Highest scale factor the bond account left through a recent drop and the
    /// block of its latest drop; a failure window opening within retentionBlocks
    /// of that block opens at least at this scale (ADR 0022).
    function getRecentScaleHigh(uint32 bondId) external view onlyDelegateCall returns (ScaleHigh memory) {
        return recentScaleHigh[bondId];
    }

    /// Forfeited remainders and per-failure deductions locked in the contract
    /// (ADR 0022). No function withdraws them.
    function getLockedForfeit() external view onlyDelegateCall returns (uint256) {
        return lockedForfeit;
    }

    /// Review stages of a case whose seal was reopened, one bit per stage.
    function getReviewReseals(bytes32 nonce) external view onlyDelegateCall returns (uint8) {
        return reviewReseals[nonce];
    }

    /// Financial state including the states derived from the bond account:
    /// FROZEN_CLAIMABLE inside an open claim window and FORFEITED after it.
    function purchaseState(bytes32 nonce) external view onlyDelegateCall returns (uint8) {
        PurchaseView storage p = purchases[nonce];
        uint8 s = p.financialState;
        if (!_purchaseExists(p) || (s != uint8(FinancialState.DEFERRED) && s != uint8(FinancialState.RELEASABLE))) return s;
        if (_forfeitedEntry(p)) return uint8(FinancialState.FORFEITED);
        BondView storage b = _bondOf(p);
        if (b.freezeState == uint8(FreezeState.CLAIM_OPEN) && _inFreezeSpans(b.bondId, p.settledBlock)) {
            return uint8(FinancialState.FROZEN_CLAIMABLE);
        }
        return s;
    }

    /// Longest path from a settlement to the end of its case (profile-v1 section 3, ADR 0024).
    function judgmentDelayBlocks(uint32 profileId) external view onlyDelegateCall returns (uint256 delay) {
        ServiceProfileInput storage p = profiles[profileId].parameters;
        delay = _judgmentDelay(p.epochBlocks, p.beaconDelayBlocks, p.maxAssignments, deadlineConfigs[p.deadlineConfigId]);
    }

    /// Design 2 terms of a profile, of a bond account, and the account's unit
    /// bond under them (ADR 0024).
    function getProfileTerms(uint32 profileId) external view onlyDelegateCall returns (ProfileTerms memory) {
        return profileTerms[profileId];
    }

    function getBondTerms(uint32 bondId) external view onlyDelegateCall returns (BondTerms memory) {
        return bondTerms[bondId];
    }

    function unitBond(uint32 bondId) external view onlyDelegateCall returns (uint256 penalty) {
        BondView storage b = bonds[bondId];
        (penalty,,,,) = _unitTerms(b, profiles[b.profileId].parameters);
    }

    /// Sampling rate fixed at settlement under a profile with tiers, and the
    /// receipt deadline of a sample case (zero once met).
    function getSettledSamplePpm(bytes32 nonce) external view onlyDelegateCall returns (uint32) {
        return settledSamplePpm[nonce];
    }

    function getSampleReceiptDue(bytes32 nonce) external view onlyDelegateCall returns (uint64) {
        return sampleReceiptDue[nonce];
    }

    function verdictDigest(SignedVerdict calldata verdict) external view onlyDelegateCall returns (bytes32) {
        return _verdictDigest(verdict);
    }

    function getReview(bytes32 nonce) external view onlyDelegateCall returns (ReviewData memory) {
        return reviews[nonce];
    }

    function getAssignments(bytes32 nonce) external view onlyDelegateCall returns (AssignmentData[] memory) {
        return assignmentHistory[nonce];
    }

    function getVerifierCapital(uint32 id) external view onlyDelegateCall returns (VerifierCapital memory) {
        return verifierCapital[id];
    }

    /// Liability room of each verifier of a checkpoint at its checkpoint
    /// block, in the order of its verifierIds (ADR 0025).
    function getCheckpointHeadroom(uint32 profileId, uint64 version)
        external view onlyDelegateCall returns (uint96[] memory)
    {
        return checkpointHeadroom[profileId][version];
    }

    /// Last block of the reopened seal window of the current review stage,
    /// once the stage's seal has been reopened (ADR 0025).
    function getReviewResealDue(bytes32 nonce) external view onlyDelegateCall returns (uint64) {
        return reviewResealDue[nonce];
    }

    function getAssignmentWait(bytes32 nonce) external view onlyDelegateCall returns (AssignmentWait memory) {
        return assignmentWaits[nonce];
    }

    /// Release clock of a bond account (ADR 0029): the number of its cases
    /// waiting for an assignment, the number of pauses recorded, and the
    /// paused blocks of the account before this block.
    function getReleaseClock(uint32 bondId)
        external view onlyDelegateCall returns (uint32 waitingCases, uint32 pauses, uint64 pausedTotal)
    {
        ReleaseClock storage clock = releaseClocks[bondId];
        return (clock.waitingCases, clock.pauses, uint64(_pausedSince(bondId, 0)));
    }

    /// Paused blocks of the account from block `fromBlock` up to this block;
    /// an entry settled in block s may be released once block.number -
    /// pausedSince(bondId, s) >= releaseBlock (ADR 0029).
    function pausedSince(uint32 bondId, uint64 fromBlock) external view onlyDelegateCall returns (uint64) {
        return uint64(_pausedSince(bondId, fromBlock));
    }
}
