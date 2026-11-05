// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "./FairBindCore.sol";
import { FairBindMerkle } from "./FairBindMerkle.sol";
import { SamplingStore } from "./modules/SamplingStore.sol";
import { BatchStore } from "./modules/BatchStore.sol";

interface IModuleConfig {
    function deploymentToken() external view returns (address);
    function penaltyTreasury() external view returns (address);
    function verifierRewardPool() external view returns (address);
    function MODULE_KIND() external view returns (uint8);
}

contract FairBind is FairBindCore {
    address public immutable registryModule;
    address public immutable settlementModule;
    address public immutable samplingModule;
    address public immutable deliveryModule;
    address public immutable publicationModule;
    address public immutable recoveryModule;

    address public immutable judgmentModule;
    address public immutable reviewModule;
    address public immutable bondModule;
    address public immutable lensModule;

    constructor(
        address token,
        address gov,
        address guard,
        address treasury,
        address rewardPool,
        address[10] memory modules
    ) FairBindCore(token, gov, guard, treasury, rewardPool) {
        for (uint8 i; i < 10; i++) {
            if (modules[i].code.length == 0) {
                revert InvalidConfiguration();
            }
            IModuleConfig module = IModuleConfig(modules[i]);
            if (
                module.deploymentToken() != token || module.penaltyTreasury() != treasury
                    || module.verifierRewardPool() != rewardPool || module.MODULE_KIND() != i + 1
            ) revert InvalidConfiguration();
        }
        registryModule = modules[0];
        settlementModule = modules[1];
        samplingModule = modules[2];
        deliveryModule = modules[3];
        publicationModule = modules[4];
        recoveryModule = modules[5];
        judgmentModule = modules[6];
        reviewModule = modules[7];
        bondModule = modules[8];
        lensModule = modules[9];
    }

    // Read functions of the shared state keep their selectors here and run in
    // the lens module: each forwards through a static call to the router
    // itself, which the fallback delegates to the lens (ADR 0025).
    function deriveKeyId(uint32, address, bytes16) external view returns (bytes32) { _read(); }
    function deriveNonce(uint32, uint32, bytes32, address, bytes16, bytes32) external view returns (bytes32) { _read(); }
    function purchaseByKey(bytes32) external view returns (bytes32) { _read(); }
    function getDeadlineConfig(uint32) external view returns (DeadlineConfig memory) { _read(); }
    function getServiceProfile(uint32) external view returns (ServiceProfileView memory) { _read(); }
    function getSeller(uint32) external view returns (SellerView memory) { _read(); }
    function getVerifier(uint32) external view returns (VerifierView memory) { _read(); }
    function getPurchase(bytes32) external view returns (PurchaseView memory) { _read(); }
    /// The randomness source of the per-epoch sampling value and the first block
    /// from which anchored epochs use it (journal J2); zero while the block hash path runs.
    /// The units of a split anchor (journal J3, J4): the unit size 2^unitLog2,
    /// the merkle-v1 root of each posted unit, and the publication accumulator.
    /// While units are open `publicationHashes` is [pubAcc], the fold of the
    /// units posted so far; once the last unit of two or more is in it is
    /// [pubAcc, h_last], and keccak256(abi.encodePacked(publicationHashes)) is
    /// the epoch's publication hash. The per-unit hashes are in the
    /// AnchorUnitPosted events. An epoch posted as one unit, or anchored in one
    /// transaction, has no unit record: all three are empty.
    function getAnchorUnits(uint32 sellerId, uint24 epoch)
        external
        view
        returns (uint8 unitLog2, bytes32[] memory roots, bytes32[] memory publicationHashes)
    {
        SamplingStore.UnitAnchor storage u = SamplingStore.layout().units[sellerId][epoch];
        roots = u.roots;
        unitLog2 = u.unitLog2;
        if (roots.length == 0) return (unitLog2, roots, publicationHashes);
        if (roots.length > 1 && _unitsComplete(u, anchors[sellerId][epoch], roots.length)) {
            publicationHashes = new bytes32[](2);
            publicationHashes[1] = u.tail;
        } else {
            publicationHashes = new bytes32[](1);
        }
        publicationHashes[0] = u.pubAcc;
    }

    /// True when (nonce, receiptLeaf) is the entry at `position` of unit `unit`
    /// of the completed split anchor of the epoch. It costs a proof as deep as
    /// the unit, not as the whole list. An epoch anchored as one unit (or in one
    /// transaction) is its own unit 0, checked against the anchor root (journal J4).
    function verifyUnitMember(
        uint32 sellerId,
        uint24 epoch,
        uint32 unit,
        bytes32 nonce,
        bytes32 receiptLeaf,
        uint32 position,
        bytes32[] calldata siblings
    ) external view returns (bool) {
        SamplingStore.UnitAnchor storage u = SamplingStore.layout().units[sellerId][epoch];
        AnchorView storage record = anchors[sellerId][epoch];
        uint256 n = u.roots.length;
        if (n == 0) {
            if (unit != 0 || record.state == uint8(EpochState.NONE) || record.root == bytes32(0)) return false;
            return FairBindMerkle.verify(record.root, nonce, receiptLeaf, position, record.count, siblings);
        }
        if (unit >= n || !_unitsComplete(u, record, n)) return false;
        uint256 size = uint256(1) << u.unitLog2;
        uint256 left = uint256(record.count) - uint256(unit) * size;
        return FairBindMerkle.verify(u.roots[unit], nonce, receiptLeaf, position, uint32(left < size ? left : size), siblings);
    }

    /// Whether the n posted units of a split epoch make up its anchored list.
    function _unitsComplete(SamplingStore.UnitAnchor storage u, AnchorView storage record, uint256 n)
        private
        view
        returns (bool)
    {
        uint256 size = uint256(1) << u.unitLog2;
        return record.state != uint8(EpochState.NONE) && n == (uint256(record.count) + size - 1) / size;
    }

    function getRandomness() external view returns (address source, uint64 since) {
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        return (cfg.source, cfg.since);
    }

    /// Whether the randomness source is request based (ADR 0031), and the
    /// registered redraw use of a waiting case.
    function getRandomnessKind() external view returns (bool vrf) {
        return SamplingStore.layout().randomness.vrf;
    }

    function getRedrawUse(bytes32 nonce) external view returns (SamplingStore.RedrawUse memory) {
        return SamplingStore.layout().redrawUses[nonce];
    }
    function getCase(bytes32) external view returns (CaseView memory) { _read(); }
    function getAnchor(uint32, uint24) external view returns (AnchorView memory) { _read(); }
    function getVerifierCheckpoint(uint32, uint64) external view returns (uint64, uint32[] memory, uint96[] memory,
        uint256, bytes32) { _read(); }
    function isSampled(bytes32) external view returns (bool, bool) { _read(); }
    function quoteSeller(uint32) external view returns (SellerQuote memory) { _read(); }
    function receiptDigest(FairBindReceipt calldata) external view returns (bytes32) { _read(); }

    function canonicalRequestHash(CanonicalRequest calldata request, bytes32 canonId)
        external
        pure
        returns (bytes32)
    {
        return _canonicalRequestHash(request, canonId);
    }

    function getBuyerRecovery(bytes32) external view returns (CaseView memory) { _read(); }
    function getBond(uint32) external view returns (BondView memory) { _read(); }
    function getFrozenPool(uint32) external view returns (FrozenPoolView memory) { _read(); }
    function getFreezeTriggers(uint32) external view returns (TriggerQueue memory) { _read(); }
    function getFreezeSpans(uint32) external view returns (FreezeSpan[] memory) { _read(); }
    function getForfeitWindows(uint32) external view returns (ForfeitWindow[] memory) { _read(); }
    function getClaimReentry(uint32) external view returns (ClaimReentry memory) { _read(); }
    function getFailureWindowScale(uint32) external view returns (uint32) { _read(); }
    function getRecentScaleHigh(uint32) external view returns (ScaleHigh memory) { _read(); }
    function getLockedForfeit() external view returns (uint256) { _read(); }
    function getReviewReseals(bytes32) external view returns (uint8) { _read(); }
    function purchaseState(bytes32) external view returns (uint8) { _read(); }
    function judgmentDelayBlocks(uint32) external view returns (uint256) { _read(); }
    function getProfileTerms(uint32) external view returns (ProfileTerms memory) { _read(); }
    function getBondTerms(uint32) external view returns (BondTerms memory) { _read(); }
    function unitBond(uint32) external view returns (uint256) { _read(); }
    function getSettledSamplePpm(bytes32) external view returns (uint32) { _read(); }
    function getSampleReceiptDue(bytes32) external view returns (uint64) { _read(); }
    function verdictDigest(SignedVerdict calldata) external view returns (bytes32) { _read(); }
    function getReview(bytes32) external view returns (ReviewData memory) { _read(); }
    function getAssignments(bytes32) external view returns (AssignmentData[] memory) { _read(); }
    function getVerifierCapital(uint32) external view returns (VerifierCapital memory) { _read(); }
    function getCheckpointHeadroom(uint32, uint64) external view returns (uint96[] memory) { _read(); }
    function getReviewResealDue(bytes32) external view returns (uint64) { _read(); }
    function getAssignmentWait(bytes32) external view returns (AssignmentWait memory) { _read(); }
    function getReleaseClock(uint32) external view returns (uint32, uint32, uint64) { _read(); }
    function pausedSince(uint32, uint64) external view returns (uint64) { _read(); }

    function registerBond(uint32 profileId, uint128 amount) external returns (uint32 bondId) { _delegate(bondModule); }
    function topUpBond(uint32 bondId, uint128 amount) external { _delegate(bondModule); }
    function requestBondExit(uint32 bondId) external { _delegate(bondModule); }
    function finalizeBondExit(uint32 bondId) external { _delegate(bondModule); }
    function reinstateSeller(uint32 sellerId) external { _delegate(bondModule); }
    function freezeSellerDeferred(bytes32 triggerNonce) external { _delegate(bondModule); }
    function releaseFrozen(uint32 bondId) external { _delegate(bondModule); }
    function forfeitUnclaimed(uint32 bondId) external { _delegate(bondModule); }
    function claimRefund(bytes32 nonce, FairBindReceipt calldata receipt, bytes calldata receiptSignature,
        ReceiptProof calldata proof) external { _delegate(bondModule); }

    function setProfileTerms(uint32 profileId, bytes32 termsHash, uint32 detectFloorPpm, uint96[] calldata valueCaps,
        SalesTier[] calldata tiers) external { _delegate(registryModule); }
    function registerBondWithTerms(uint32 profileId, uint128 amount, uint96 sampleScaleValue, uint8 tier)
        external returns (uint32 bondId) { _delegate(bondModule); }
    function setBondTerms(uint32 bondId, uint96 sampleScaleValue, uint8 tier) external { _delegate(bondModule); }
    function submitSampleReceipt(bytes32 nonce, FairBindReceipt calldata receipt, bytes calldata receiptSignature,
        ReceiptProof calldata proof) external { _delegate(settlementModule); }
    function timeoutSampleReceipt(bytes32 nonce) external { _delegate(settlementModule); }
    function setRandomness(address source) external { _delegate(registryModule); }
    function anchorUnit(uint32 sellerId, uint24 epoch, uint32 unit, uint8 unitLog2,
        FairBindMerkle.ReceiptEntry[] calldata entries, bytes32 publicationHash) external { _delegate(settlementModule); }

    function judge(SignedVerdict calldata verdict, bytes calldata verdictSignature, FairBindReceipt calldata receipt,
        bytes calldata receiptSignature, ReceiptProof calldata proof) external { _delegate(judgmentModule); }
    function requestEvidence(bytes32 nonce, uint8 stage, uint8 attempt) external { _delegate(reviewModule); }
    function discloseEvidence(bytes32 nonce, uint8 stage, uint8 attempt, bytes calldata evidence) external { _delegate(reviewModule); }
    function timeoutEvidence(bytes32 nonce, uint8 stage, uint8 attempt) external { _delegate(samplingModule); }
    function timeoutJudge(bytes32 nonce) external { _delegate(samplingModule); }
    function appeal(bytes32 nonce) external { _delegate(reviewModule); }
    function sealReviewRandomness(bytes32 nonce) external { _delegate(reviewModule); }
    function openAutoRecheck(bytes32 nonce) external { _delegate(reviewModule); }
    function finalizeCase(bytes32 nonce) external { _delegate(reviewModule); }

    function createDeadlineConfig(uint32 id, DeadlineConfig calldata config) external {
        _delegate(registryModule);
    }

    function createServiceProfile(uint32 id, ServiceProfileInput calldata input) external {
        _delegate(registryModule);
    }

    function setServiceProfileActive(uint32 id, bool active) external {
        _delegate(registryModule);
    }

    function pauseNewSettlements(bool paused) external {
        _delegate(registryModule);
    }

    function nominateGovernance(address nominee, uint64 acceptAfter) external {
        _delegate(registryModule);
    }

    function acceptGovernance() external {
        _delegate(registryModule);
    }

    function nominateGuardian(address nominee) external {
        _delegate(registryModule);
    }

    function acceptGuardian() external {
        _delegate(registryModule);
    }

    function registerSeller(uint32 bondId, uint32 profileId, address signingKey, bytes32 claimsHash)
        external
        returns (uint32 sellerId)
    {
        _delegate(bondModule);
    }

    function requestSellerExit(uint32 sellerId) external {
        _delegate(bondModule);
    }

    function finalizeSellerExit(uint32 sellerId) external {
        _delegate(bondModule);
    }

    function registerVerifier(uint256 classBitmap, address signingKey, uint128 bondAmount)
        external
        returns (uint32 verifierId)
    {
        _delegate(registryModule);
    }

    function topUpVerifierBond(uint32 verifierId, uint128 amount) external {
        _delegate(registryModule);
    }

    function setVerifierClasses(uint32 verifierId, uint256 classBitmap) external {
        _delegate(registryModule);
    }

    function requestVerifierExit(uint32 verifierId) external {
        _delegate(registryModule);
    }

    function finalizeVerifierExit(uint32 verifierId) external {
        _delegate(registryModule);
    }

    function checkpointVerifierTree(uint32 profileId) external returns (uint64 version) {
        _delegate(registryModule);
    }

    /// Installs the extension modules once (ADR 0032).
    function setExtensions(address[] calldata list) external {
        _delegate(registryModule);
    }

    function settle(
        uint32 sellerId,
        uint32 profileId,
        bytes32 claimsHash,
        bytes16 idempotencyKey,
        bytes32 requestHash,
        TransferAuthorization calldata authorization,
        bytes calldata paymentSignature
    ) external returns (bytes32 nonce, bytes32 keyId) {
        _delegate(settlementModule);
    }

    function settleBatch(SettleItem[] calldata items) external returns (uint256 settled) {
        _delegate(settlementModule);
    }

    function anchor(
        uint32 sellerId,
        uint24 epoch,
        FairBindMerkle.ReceiptEntry[] calldata entries,
        uint32 count,
        bytes32 publicationHash
    ) external {
        _delegate(samplingModule);
    }

    function timeoutAnchor(uint32 sellerId, uint24 epoch) external {
        _delegate(publicationModule);
    }

    function seal(uint32 sellerId, uint24 epoch) external {
        _delegate(publicationModule);
    }

    function timeoutSeal(uint32 sellerId, uint24 epoch) external {
        _delegate(publicationModule);
    }

    function openSample(bytes32 nonce) external {
        _delegate(samplingModule);
    }

    function assignVerifier(bytes32 nonce) external {
        _delegate(samplingModule);
    }

    function dispute(
        bytes32 nonce,
        uint8 kind,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external {
        _delegate(deliveryModule);
    }

    function requestServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function served(bytes32 nonce, bytes32 bundleHash) external {
        _delegate(deliveryModule);
    }

    function acceptServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function finalizeServed(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function escalate(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function publish(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        bytes calldata responseBody,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external {
        _delegate(publicationModule);
    }

    function beginPublication(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        uint32 totalBytes,
        uint16 chunkCount
    ) external {
        _delegate(publicationModule);
    }

    function publishChunk(bytes32 nonce, uint16 index, bytes calldata chunk) external {
        _delegate(publicationModule);
    }

    function finalizePublication(bytes32 nonce) external {
        _delegate(publicationModule);
    }

    function timeoutServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function claimEpochFailure(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function claimRefund(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function releasePurchase(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function requestSampleValue(uint32 profileId, uint24 epoch) external {
        _delegate(recoveryModule);
    }

    function registerRedraw(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function requestRedrawValue(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function timeoutRedrawValue(bytes32 nonce) external {
        _delegate(recoveryModule);
    }

    function proveOmission(
        bytes32 nonce,
        FairBindMerkle.ReceiptEntry calldata left,
        ReceiptProof calldata leftProof,
        FairBindMerkle.ReceiptEntry calldata right,
        ReceiptProof calldata rightProof,
        uint8 boundary
    ) external {
        _delegate(bondModule);
    }

    function proveMisanchoredReceipt(
        FairBindReceipt calldata receipt,
        bytes calldata signature,
        bytes32 anchoredLeaf,
        ReceiptProof calldata proof
    ) external {
        _delegate(recoveryModule);
    }

    function proveEquivocation(
        FairBindReceipt calldata first,
        bytes calldata firstSignature,
        FairBindReceipt calldata second,
        bytes calldata secondSignature
    ) external {
        _delegate(recoveryModule);
    }

    function buyerServed(bytes32 nonce, bytes32 bundleHash) external {
        _delegate(deliveryModule);
    }

    function acceptBuyerServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function finalizeBuyerServed(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function escalateBuyerServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function timeoutBuyerServe(bytes32 nonce) external {
        _delegate(deliveryModule);
    }

    function publishBuyerResponse(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        bytes calldata responseBody,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external {
        _delegate(publicationModule);
    }

    function beginBuyerPublication(
        bytes32 nonce,
        bytes16 idempotencyKey,
        CanonicalRequest calldata request,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        uint32 totalBytes,
        uint16 chunkCount
    ) external {
        _delegate(publicationModule);
    }

    function publishBuyerChunk(bytes32 nonce, uint16 index, bytes calldata chunk)
        external
       
    {
        _delegate(publicationModule);
    }

    function finalizeBuyerPublication(bytes32 nonce) external {
        _delegate(publicationModule);
    }

    /// Prefix of a read forwarded by the router to itself.
    bytes4 private constant READ_PREFIX = bytes4(keccak256("fairbind/lens/v1"));

    /// Forwards the call data of a read function to the router itself behind
    /// READ_PREFIX, as a static call, and returns its result.
    function _read() private view {
        bytes4 prefix = READ_PREFIX;
        assembly {
            let size := calldatasize()
            mstore(0, prefix)
            calldatacopy(4, 0, size)
            let ok := staticcall(gas(), address(), 0, add(size, 4), 0, 0)
            returndatacopy(0, 0, returndatasize())
            if iszero(ok) { revert(0, returndatasize()) }
            return(0, returndatasize())
        }
    }

    /// Runs a forwarded read in the lens module when the router's own static
    /// call reaches it. Any other unknown selector runs in the extension
    /// module that declared it (ADR 0032); without one it reverts.
    fallback() external {
        if (msg.sender != address(this) || msg.sig != READ_PREFIX) {
            address ext = BatchStore.layout().route[msg.sig];
            if (ext == address(0)) revert InvalidTransition();
            assembly {
                calldatacopy(0, 0, calldatasize())
                let ok := delegatecall(gas(), ext, 0, calldatasize(), 0, 0)
                returndatacopy(0, 0, returndatasize())
                if iszero(ok) { revert(0, returndatasize()) }
                return(0, returndatasize())
            }
        }
        address lens = lensModule;
        assembly {
            let size := sub(calldatasize(), 4)
            calldatacopy(0, 4, size)
            let ok := delegatecall(gas(), lens, 0, size, 0, 0)
            returndatacopy(0, 0, returndatasize())
            if iszero(ok) { revert(0, returndatasize()) }
            return(0, returndatasize())
        }
    }

    function _delegate(address module) private {
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), module, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            if iszero(ok) { revert(0, returndatasize()) }
            return(0, returndatasize())
        }
    }
}
