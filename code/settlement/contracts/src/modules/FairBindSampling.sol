// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Rule8Store } from "./Rule8Store.sol";
import { FairBindCore } from "../FairBindCore.sol";
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";

contract FairBindSampling is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 3;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function anchor(
        uint32 sellerId,
        uint24 epoch,
        FairBindMerkle.ReceiptEntry[] calldata entries,
        uint32 count,
        bytes32 publicationHash
    ) external onlyDelegateCall {
        SellerView storage seller = sellers[sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        if (
            seller.status == uint8(SellerStatus.NONE) || seller.status == uint8(SellerStatus.EXITED)
        ) {
            revert SellerInactive();
        }
        if (publicationHash == bytes32(0)) revert InvalidConfiguration();
        if (count == 0 || count != epochPurchaseCount[sellerId][epoch]) revert CountMismatch();
        // The anchor carries the (nonce, receiptLeaf) list itself (ADR 0026):
        // the root is computed here, so no root exists without its published
        // list. Strictly ascending nonces make adjacent entries bracket every
        // nonce the list does not hold, which is what an omission proof uses.
        if (entries.length != count) revert CountMismatch();
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.NONE)) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[seller.profileId].parameters;
        uint256 base = _anchorBase(profile, epoch);
        uint256 deadline = base + deadlineConfigs[profile.deadlineConfigId].anchorBlocks;
        if (block.number < base) revert AnchorTooEarly();
        if (block.number > deadline) revert AnchorWindowClosed();
        if (!FairBindMerkle.strictlyAscending(entries)) revert EntriesNotAscending();
        bytes32 root = FairBindMerkle.computeRoot(entries);
        if (root == bytes32(0)) revert InvalidConfiguration();
        // An anchor counts the fixed share of a measured cost in its transaction (ADR 0037).
        ExchangeStore.mark();
        _finishAnchor(sellerId, epoch, record, profile, deadline, root, publicationHash, count);
    }

    function openSample(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_OPEN) {
        PurchaseView storage purchase = purchases[nonce];
        CaseView storage caseRecord = cases[nonce];
        uint8 financial = purchase.financialState;
        // A purchase whose non-delivery dispute ended as delivered is opened as
        // well, with or without an open buyer recovery (ADR 0024, rule 94a).
        bool delivered = caseRecord.state == uint8(CaseState.DELIVERED)
            && caseRecord.trigger == uint8(CaseTrigger.NON_DELIVERY)
            && (financial == uint8(FinancialState.RELEASABLE) || financial == uint8(FinancialState.HELD));
        // Receipt signatures (ADR 0037): a proof profile opens its sample
        // cases elsewhere; an unbound purchase is no sale and opens none; a
        // purchase refunded by its non-delivery dispute still opens its
        // sample case, which leaves the refund as it is.
        uint8 mode = _exchangeMode(purchase.profileId);
        bool refunded;
        if (mode != ExchangeStore.MODE_NONE) {
            if (mode == ExchangeStore.MODE_PROOF) revert InvalidTransition();
            if (!_bound(nonce)) revert NotBound();
            refunded = caseRecord.state == uint8(CaseState.UNSERVED)
                && caseRecord.trigger == uint8(CaseTrigger.NON_DELIVERY) && _refundedEarly(nonce);
            delivered = delivered || refunded;
        }
        if (
            !_purchaseExists(purchase) || _forfeitedEntry(purchase)
                || !(delivered || (caseRecord.state == uint8(CaseState.NONE) && financial == uint8(FinancialState.DEFERRED)))
        ) revert InvalidTransition();
        // Rule 8: the seller epoch is sealed by its profile epoch (rule D2-35 (b)).
        _r8Hook(purchase.profileId, HOOK_R8_MAT, (uint256(purchase.sellerId) << 24) | purchase.epoch);
        (bool eligible, bool known) = _sampleStatus(purchase, nonce);
        if (!known || !eligible) revert NotSampled();
        AnchorView storage record = anchors[purchase.sellerId][purchase.epoch];
        // Opening after sampleOpenUntil stays possible: an unopened sampled entry
        // is never released, so a late opening only restores its judgment.
        if (!refunded) _setFinancialState(nonce, FinancialState.HELD);
        if (delivered) {
            // The dispute's serve procedure is cleared, including its bundle, so
            // that the sample case owes its own on-chain response (ADR 0014).
            caseRecord.requester = address(0);
            caseRecord.requesterRole = uint8(RequesterRole.NONE);
            caseRecord.resumeState = uint8(CaseState.NONE);
            caseRecord.bundleHash = bytes32(0);
            caseRecord.serveDue = 0;
            caseRecord.challengeUntil = 0;
            caseRecord.publishDue = 0;
            // The dispute's publication and evidence do not carry over (ADR 0025).
            caseRecord.publishedChunks = 0;
            caseRecord.evidenceHash = bytes32(0);
        }
        // The seller puts the receipt and its inclusion proof on chain within
        // serveBlocks, alongside the first judgment window (ADR 0024).
        sampleReceiptDue[nonce] = uint64(
            block.number + deadlineConfigs[profiles[purchase.profileId].parameters.deadlineConfigId].serveBlocks
        );
        caseRecord.nonce = nonce;
        caseRecord.randomness = record.randomness;
        caseRecord.caseOpenedBlock = uint64(block.number);
        caseRecord.trigger = uint8(CaseTrigger.SAMPLE);
        caseRecord.state = uint8(CaseState.ASSIGNING);
        caseRecord.stage = uint8(JudgmentStage.INITIAL);
        emit CaseOpened(nonce, uint8(CaseTrigger.SAMPLE), address(0), purchase.value);
        _assignVerifier(nonce);
    }

    function assignVerifier(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_ASSIGN) {
        uint8 state = cases[nonce].state;
        if (state == uint8(CaseState.WAITING_ASSIGNMENT)) {
            _redraw(nonce);
            return;
        }
        if (state != uint8(CaseState.ASSIGNING)) revert InvalidTransition();
        _assignVerifier(nonce);
    }

    /// Redraws a waiting case (ADR 0028). The redraw uses the first checkpoint
    /// written in a block after the case's last search, never a later one, so
    /// writing more checkpoints cannot change its draw. Its value is the hash
    /// of the block beaconDelayBlocks + 1 after that checkpoint's block, the
    /// epoch rule of sortition-v1 section 3: the checkpoint is fixed before the
    /// value exists. Eligibility is the room in that checkpoint. When the hash
    /// is no longer served, or the checkpoint holds fewer than minVerifiers,
    /// the checkpoint counts as searched and the case waits for the next one.
    ///
    /// Under a request-based source (ADR 0031) the value is instead that of
    /// the AUX request of the redraw's registered use (rule D2-20 (b)): the
    /// use is registered after the checkpoint is written, its value is asked
    /// for in a later block, and the redraw waits until the value is stored.
    function _redraw(bytes32 nonce) private {
        PurchaseView storage purchase = purchases[nonce];
        AssignmentWait storage wait = assignmentWaits[nonce];
        uint64 version = _checkpointAt(purchase.profileId, wait.searchBlock) + 1;
        if (version > latestCheckpointVersion[purchase.profileId]) revert InvalidTransition();
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[purchase.profileId][version];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        bytes32 value;
        IVrfRandomness vrf = _vrfAt(anchors[purchase.sellerId][purchase.epoch].anchoredBlock);
        if (address(vrf) != address(0)) {
            SamplingStore.RedrawUse storage use = SamplingStore.layout().redrawUses[nonce];
            if (use.redraw != wait.redraws + 1) revert NotRegistered();
            bool ready;
            (ready, value) = vrf.valueOf(keccak256(abi.encode(VRF_AUX, _redrawInput(nonce, use.redraw, use.registeredBlock))));
            if (!ready) revert DeadlineNotReached();
        } else {
            uint256 randomBlock = uint256(checkpoint.checkpointBlock) + 1 + profile.beaconDelayBlocks;
            if (block.number <= randomBlock) revert DeadlineNotReached();
            // blockhash serves the last 256 blocks only.
            value = block.number <= randomBlock + 256 ? blockhash(randomBlock) : bytes32(0);
        }
        wait.redraws++;
        if (value == 0 || checkpoint.verifierIds.length < profile.minVerifiers) {
            _waitForCheckpoint(nonce, version);
            return;
        }
        wait.checkpointVersion = version;
        wait.randomness = value;
        // The case leaves the wait in this block; a search that is exhausted
        // again re-enters it in the same block (ADR 0029).
        _clockWaitEnds(nonce);
        cases[nonce].state = uint8(CaseState.ASSIGNING);
        _assignVerifier(nonce);
    }

    // The two judgment timeouts live here, next to the assignment search they
    // restart, so that the judgment module stays below the size limit.
    function timeoutJudge(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_TIMEOUT) {
        if (!_judgmentActive(nonce)) revert InvalidTransition();
        if (block.number <= cases[nonce].judgeDue) revert DeadlineNotReached();
        _replaceLateAssignment(nonce);
    }

    function timeoutEvidence(bytes32 nonce, uint8 stage, uint8 attempt)
        external
        onlyDelegateCall
        nonReentrant
        r8Fee(nonce, Rule8Store.FEE_TIMEOUT)
    {
        CaseView storage c = cases[nonce];
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.stage != stage || c.attempt != attempt
            || !_evidencePending(nonce)) revert InvalidTransition();
        if (block.number <= c.evidenceDue) revert DeadlineNotReached();
        _replaceLateAssignment(nonce);
    }
}
