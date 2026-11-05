// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";

contract FairBindJudgment is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 7;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool) {}

    function judge(SignedVerdict calldata verdict, bytes calldata verdictSignature,
        FairBindReceipt calldata receipt, bytes calldata receiptSignature, ReceiptProof calldata proof)
        external onlyDelegateCall nonReentrant
    {
        bytes32 nonce = verdict.nonce;
        CaseView storage c = cases[nonce];
        if (!_judgmentActive(nonce)) revert InvalidTransition();
        if (block.number > c.judgeDue) revert DeadlinePassed();
        if (verdict.version != 1 || verdict.stage != c.stage || verdict.attempt != c.attempt
            || verdict.verifierId != c.assignedVerifierId || verdict.verdict == uint8(Verdict.NONE)
            || verdict.verdict > uint8(Verdict.INCONCLUSIVE) || verdict.evidenceHash == 0) revert InvalidConfiguration();
        if (_recover(_verdictDigest(verdict), verdictSignature) != verifiers[c.assignedVerifierId].signingKey)
            revert InvalidSignature();
        PurchaseView storage p = purchases[nonce];
        bytes32 leaf = _validateReceipt(p, nonce, receipt, receiptSignature);
        // A missing predicate commitment is a seller violation, never an evaluation gap.
        if (receipt.predicateCommitment == bytes32(0) && verdict.verdict != uint8(Verdict.FAIL)) revert InvalidReceipt();
        if (c.trigger == uint8(CaseTrigger.SAMPLE)) {
            uint64 due = sampleReceiptDue[nonce];
            // Past the receipt deadline the case is UNSERVED whatever the
            // verdict carries; it ends here rather than wait for
            // timeoutSampleReceipt (rule D2-17 (a), ADR 0025).
            if (due != 0 && block.number > due) {
                sampleReceiptDue[nonce] = 0;
                _sellerFailure(nonce, RefundSource.UNSERVED);
                return;
            }
            if (!_receiptProofValid(anchors[p.sellerId][p.epoch], receipt, leaf, proof)) revert InvalidProof();
            // A verdict carrying the receipt and its proof in time puts them on chain (ADR 0024).
            if (due != 0) {
                sampleReceiptDue[nonce] = 0;
                emit SampleReceiptRecorded(nonce);
            }
        }
        AssignmentData storage a = _activeAssignment(nonce);
        if (a.verdict != 0) revert InvalidTransition();
        a.verdict = verdict.verdict;
        a.evidenceHash = verdict.evidenceHash;
        c.evidenceHash = verdict.evidenceHash;
        emit VerdictSubmitted(nonce, c.stage, c.assignedVerifierId, verdict.verdict, verdict.evidenceHash);
        if (c.stage == uint8(JudgmentStage.INITIAL)) {
            c.initialVerdict = verdict.verdict;
            c.state = uint8(CaseState.INITIAL_VERDICT);
            _renewAppeal(nonce);
            // With freezeOnInitialFail an initial FAIL stops the seller, holds
            // its bond's deferred ledger until the appeal window decides, and
            // stays a pending trigger until the case ends. Otherwise the freeze
            // waits for the confirmed failure (ADR 0020).
            if (verdict.verdict == uint8(Verdict.FAIL) && profiles[p.profileId].parameters.freezeOnInitialFail) {
                _freezePending(p.sellerId, nonce);
            }
        } else if (c.stage == uint8(JudgmentStage.PARTY) || c.stage == uint8(JudgmentStage.AUTO)) {
            // A review that agrees with the initial verdict ends the case; one
            // that disagrees goes to a third verifier, on both paths (ADR 0019).
            if (c.stage == uint8(JudgmentStage.AUTO)) reviews[nonce].autoVerdict = verdict.verdict;
            if (verdict.verdict == c.initialVerdict) _finishReview(nonce, verdict.verdict, false);
            else _startReview(nonce, uint8(JudgmentStage.TIEBREAK), uint8(CaseState.TIEBREAK), uint64(block.number + 1));
        } else if (c.stage == uint8(JudgmentStage.TIEBREAK)) {
            _finishReview(nonce, verdict.verdict, false);
        } else revert InvalidTransition();
    }

    function _renewAppeal(bytes32 nonce) private {
        CaseView storage c = cases[nonce];
        reviews[nonce].appealUntil = uint64(block.number
            + deadlineConfigs[profiles[purchases[nonce].profileId].parameters.deadlineConfigId].appealBlocks);
        c.randomBlock = reviews[nonce].appealUntil + 1;
        c.randomness = 0; // Epoch randomness must not masquerade as a future review hash.
    }
}
