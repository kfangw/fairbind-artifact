// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Rule8Store } from "./Rule8Store.sol";
import { FairBindCore } from "../FairBindCore.sol";
import { BatchStore } from "./BatchStore.sol";

contract FairBindReview is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 8;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool) {}

    function appeal(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage c = cases[nonce];
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.reviewPath != 0 || _evidencePending(nonce))
            revert InvalidTransition();
        if (block.number > reviews[nonce].appealUntil) revert DeadlinePassed();
        PurchaseView storage p = purchases[nonce];
        if (!((c.initialVerdict == uint8(Verdict.PASS) && msg.sender == p.buyer)
            || (c.initialVerdict == uint8(Verdict.FAIL) && msg.sender == sellers[p.sellerId].viewData.owner))) revert Unauthorized();
        // A buyer's appeal under a proportional deposit names its limit (ADR 0033).
        if (msg.sender == p.buyer && c.initialVerdict == uint8(Verdict.PASS)
            && BatchStore.layout().terms[p.profileId].depositPpm != 0) revert InvalidTransition();
        ReviewData storage r = reviews[nonce];
        r.appellant = msg.sender;
        r.deposit = profiles[p.profileId].parameters.appealDeposit;
        _transferFrom(msg.sender, r.deposit);
        c.reviewPath = 1;
        _startReview(nonce, uint8(JudgmentStage.PARTY), uint8(CaseState.PARTY_REVIEW), uint64(block.number + 1));
        emit ReviewSelected(nonce, true, false, c.randomBlock);
    }

    function sealReviewRandomness(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_GATE) {
        CaseView storage c = cases[nonce];
        if (_evidencePending(nonce)) revert InvalidTransition();
        if (c.state == uint8(CaseState.INITIAL_VERDICT) && c.initialVerdict != uint8(Verdict.FAIL) && c.reviewPath == 0) {
            _sealReview(nonce);
            return;
        }
        // A batched review stage draws from its AUX value instead (ADR 0036).
        if (c.assignedVerifierId != 0 || (c.state != uint8(CaseState.PARTY_REVIEW)
            && c.state != uint8(CaseState.TIEBREAK)) || _batched(purchases[nonce].profileId)) revert InvalidTransition();
        if (_sealReview(nonce)) _assignVerifier(nonce);
    }

    function openAutoRecheck(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_GATE) {
        _openAutoReview(nonce);
    }

    function finalizeCase(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_FINALIZE) {
        CaseView storage c = cases[nonce];
        if (c.state == uint8(CaseState.INITIAL_VERDICT)) {
            if (_evidencePending(nonce)) revert InvalidTransition();
            if (block.number <= reviews[nonce].appealUntil) revert DeadlineNotReached();
            // An unappealed PASS or INCONCLUSIVE passes the recheck gate; a FAIL is final.
            if (c.initialVerdict != uint8(Verdict.FAIL)) _openAutoReview(nonce);
            else _finishReview(nonce, c.initialVerdict, false);
        } else if (c.assignedVerifierId == 0 && (c.state == uint8(CaseState.PARTY_REVIEW)
            || c.state == uint8(CaseState.TIEBREAK)) && !_batched(purchases[nonce].profileId)) {
            uint256 due = reviewReseals[nonce] & (uint8(1) << c.stage) == 0
                ? uint256(c.randomBlock) + deadlineConfigs[profiles[purchases[nonce].profileId].parameters.deadlineConfigId].sealBlocks
                : reviewResealDue[nonce];
            if (block.number <= due) revert DeadlineNotReached();
            // Past the seal window: reopen the seal once with the same
            // randomBlock, then end as a progress failure (ADR 0021, ADR 0025).
            _sealReview(nonce);
        } else revert InvalidTransition();
    }

    function requestEvidence(bytes32 nonce, uint8 stage, uint8 attempt) external onlyDelegateCall {
        CaseView storage c = cases[nonce];
        PurchaseView storage p = purchases[nonce];
        if (msg.sender != p.buyer && msg.sender != sellers[p.sellerId].viewData.owner) revert Unauthorized();
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.stage != stage || c.attempt != attempt)
            revert InvalidTransition();
        if (block.number > reviews[nonce].appealUntil) revert DeadlinePassed();
        AssignmentData storage a = _activeAssignment(nonce);
        if (a.evidenceRequested) revert InvalidTransition();
        a.evidenceRequested = true;
        c.evidenceDue = uint64(block.number + deadlineConfigs[profiles[p.profileId].parameters.deadlineConfigId].evidenceBlocks);
        emit EvidenceRequested(nonce, stage, attempt, c.evidenceDue);
    }

    function discloseEvidence(bytes32 nonce, uint8 stage, uint8 attempt, bytes calldata evidence)
        external onlyDelegateCall
    {
        CaseView storage c = cases[nonce];
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.stage != stage || c.attempt != attempt
            || !_evidencePending(nonce)) revert InvalidTransition();
        if (block.number > c.evidenceDue) revert DeadlinePassed();
        if (evidence.length > profiles[purchases[nonce].profileId].parameters.maxEvidenceBytes) revert EvidenceTooLarge();
        AssignmentData storage a = _activeAssignment(nonce);
        if (keccak256(evidence) != a.evidenceHash) revert InvalidConfiguration();
        a.evidenceDisclosed = true;
        c.evidenceDue = 0;
        _renewAppealWindow(nonce);
        emit EvidenceDisclosed(nonce, stage, attempt, a.evidenceHash);
    }

    function _renewAppealWindow(bytes32 nonce) private {
        CaseView storage c = cases[nonce];
        reviews[nonce].appealUntil = uint64(block.number
            + deadlineConfigs[profiles[purchases[nonce].profileId].parameters.deadlineConfigId].appealBlocks);
        c.randomBlock = reviews[nonce].appealUntil + 1;
        c.randomness = 0; // Epoch randomness must not masquerade as a future review hash.
    }
}
