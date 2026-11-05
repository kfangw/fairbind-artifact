// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Rule8Store } from "./Rule8Store.sol";
import { FairBindCore } from "../FairBindCore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";

contract FairBindDelivery is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 4;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function dispute(
        bytes32 nonce,
        uint8 kind,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature
    ) external onlyDelegateCall nonReentrant {
        PurchaseView storage purchase = purchases[nonce];
        if (!_purchaseExists(purchase) || msg.sender != purchase.buyer) revert Unauthorized();
        if (block.number > purchase.claimUntil) revert ClaimWindowClosed();
        if (purchase.financialState == uint8(FinancialState.REFUNDABLE)
            || purchase.financialState == uint8(FinancialState.REFUNDED)
            || purchase.financialState == uint8(FinancialState.RELEASED)
            || _forfeitedEntry(purchase)) revert AlreadyFinalized();
        CaseView storage caseRecord = cases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        // A proof profile opens its disputes through openProofDispute (ADR 0037).
        if (_exchangeMode(purchase.profileId) == ExchangeStore.MODE_PROOF) revert InvalidTransition();

        if (kind == uint8(CaseTrigger.NON_DELIVERY)) {
            if (block.number <= purchase.responseDue) {
                revert InvalidTransition();
            }
            if (receiptSignature.length != 0 || !_zeroReceipt(receipt)) {
                revert InvalidReceipt();
            }
            if (caseRecord.state != uint8(CaseState.NONE)) {
                _openBuyerRecovery(nonce, profile.disputeDeposit, profile.deadlineConfigId);
                return;
            }
            _collectDisputeDeposit(nonce, profile.disputeDeposit);
            _setFinancialState(nonce, FinancialState.HELD);
            caseRecord.nonce = nonce;
            caseRecord.requester = msg.sender;
            caseRecord.caseOpenedBlock = uint64(block.number);
            caseRecord.serveDue =
                uint64(block.number + deadlineConfigs[profile.deadlineConfigId].serveBlocks);
            caseRecord.trigger = kind;
            caseRecord.state = uint8(CaseState.SERVE_WAIT);
            caseRecord.requesterRole = uint8(RequesterRole.BUYER);
            emit CaseOpened(nonce, kind, msg.sender, purchase.value);
            emit ServeRequested(nonce, msg.sender, caseRecord.caseOpenedBlock, caseRecord.serveDue);
            return;
        }

        if (kind != uint8(CaseTrigger.WRONG_DELIVERY)) revert InvalidTransition();
        _validateReceipt(purchase, nonce, receipt, receiptSignature);
        if (caseRecord.state == uint8(CaseState.NONE)) {
            _collectDisputeDeposit(nonce, profile.disputeDeposit);
            caseRecord.nonce = nonce;
            caseRecord.caseOpenedBlock = uint64(block.number);
        } else if (caseRecord.state != uint8(CaseState.DELIVERED)) {
            revert InvalidTransition();
        }
        _setFinancialState(nonce, FinancialState.HELD);
        caseRecord.requester = msg.sender;
        caseRecord.trigger = kind;
        caseRecord.state = uint8(CaseState.ASSIGNING);
        caseRecord.stage = uint8(JudgmentStage.INITIAL);
        // Rule 8: the case holds its profile epoch open until its end is
        // noted (rule D2-35 (d) 1 (ii)); the seller epoch takes its value
        // from the profile seal.
        _r8Hook(purchase.profileId, HOOK_R8_WRONG, uint256(nonce));
        caseRecord.randomness = anchors[purchase.sellerId][purchase.epoch].randomness;
        emit CaseOpened(nonce, kind, msg.sender, purchase.value);
        // Under batch assignment the case joins the batch of this block (ADR 0032).
        if (_batched(purchase.profileId)) _hook(HOOK_ENQUEUE, uint256(nonce));
    }

    function requestServe(bytes32 nonce) external onlyDelegateCall {
        CaseView storage caseRecord = cases[nonce];
        if (!_judgmentActive(nonce)) revert InvalidTransition();
        if (block.number > caseRecord.judgeDue) revert DeadlinePassed();
        AssignmentData storage assignment = _activeAssignment(nonce);
        if (assignment.serveUsed) revert InvalidTransition();
        assignment.serveUsed = true;
        VerifierView storage verifier = verifiers[caseRecord.assignedVerifierId];
        if (msg.sender != verifier.owner) revert Unauthorized();
        ServiceProfileInput storage profile = profiles[purchases[nonce].profileId].parameters;
        caseRecord.requester = msg.sender;
        caseRecord.requesterRole = uint8(RequesterRole.VERIFIER);
        caseRecord.resumeState = caseRecord.state;
        caseRecord.state = uint8(CaseState.SERVE_WAIT);
        caseRecord.serveDue =
            uint64(block.number + deadlineConfigs[profile.deadlineConfigId].serveBlocks);
        emit ServeRequested(nonce, msg.sender, caseRecord.caseOpenedBlock, caseRecord.serveDue);
    }

    function served(bytes32 nonce, bytes32 bundleHash) external onlyDelegateCall {
        uint256 g0 = gasleft();
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_WAIT)) revert InvalidTransition();
        if (msg.sender != sellers[purchases[nonce].sellerId].viewData.owner) revert Unauthorized();
        if (block.number > caseRecord.serveDue) revert DeadlinePassed();
        if (bundleHash == bytes32(0)) revert InvalidPublication();
        uint32 serveBlocks =
            deadlineConfigs[profiles[purchases[nonce].profileId].parameters
            .deadlineConfigId].serveBlocks;
        caseRecord.bundleHash = bundleHash;
        caseRecord.challengeUntil = uint64(block.number + serveBlocks);
        caseRecord.state = uint8(CaseState.SERVE_CONFIRM);
        emit Served(nonce, bundleHash, caseRecord.challengeUntil);
        if (_ladderOn(nonce, false)) _ladderCost(nonce, false, g0, abi.encodeWithSelector(msg.sig, nonce, bundleHash));
    }

    function acceptServe(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (msg.sender != caseRecord.requester) revert Unauthorized();
        if (block.number > caseRecord.challengeUntil) revert DeadlinePassed();
        _completeDelivery(nonce);
    }

    function finalizeServed(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_FINALIZE) {
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (block.number <= caseRecord.challengeUntil) revert DeadlineNotReached();
        _completeDelivery(nonce);
    }

    function escalate(bytes32 nonce) external onlyDelegateCall {
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (msg.sender != caseRecord.requester) revert Unauthorized();
        if (block.number > caseRecord.challengeUntil) revert DeadlinePassed();
        uint32 serveBlocks =
            deadlineConfigs[profiles[purchases[nonce].profileId].parameters
            .deadlineConfigId].serveBlocks;
        caseRecord.publishDue = uint64(block.number + serveBlocks);
        caseRecord.state = uint8(CaseState.PUBLISHING);
        emit ServeEscalated(nonce, caseRecord.publishDue);
    }

    function timeoutServe(bytes32 nonce) external onlyDelegateCall nonReentrant r8Fee(nonce, Rule8Store.FEE_TIMEOUT) {
        CaseView storage caseRecord = cases[nonce];
        if (caseRecord.state == uint8(CaseState.SERVE_WAIT)) {
            if (block.number <= caseRecord.serveDue) revert DeadlineNotReached();
        } else if (caseRecord.state == uint8(CaseState.PUBLISHING)) {
            if (block.number <= caseRecord.publishDue) revert DeadlineNotReached();
        } else {
            revert InvalidTransition();
        }
        // The buyer's non-delivery dispute of a receipt-signature vote profile
        // ends with the refund alone (rule D2-33 (f), ADR 0037).
        if (caseRecord.requesterRole == uint8(RequesterRole.BUYER) && _refundOnly(nonce)) {
            caseRecord.state = uint8(CaseState.UNSERVED);
            return;
        }
        _sellerFailure(nonce, RefundSource.UNSERVED);
    }
    function _openBuyerRecovery(bytes32 nonce, uint256 deposit, uint32 deadlineId) internal {
        CaseView storage recovery = buyerRecoveries[nonce];
        if (recovery.state != uint8(CaseState.NONE)) revert InvalidTransition();
        buyerRecoveryDeposits[nonce] = deposit;
        _transferFrom(msg.sender, deposit);
        recovery.nonce = nonce;
        recovery.requester = msg.sender;
        recovery.requesterRole = uint8(RequesterRole.BUYER);
        recovery.trigger = uint8(CaseTrigger.NON_DELIVERY);
        recovery.caseOpenedBlock = uint64(block.number);
        recovery.serveDue = uint64(block.number + deadlineConfigs[deadlineId].serveBlocks);
        recovery.state = uint8(CaseState.SERVE_WAIT);
        _setFinancialState(nonce, FinancialState.HELD);
        emit BuyerRecoveryOpened(nonce, recovery.serveDue);
        emit ServeRequested(nonce, msg.sender, recovery.caseOpenedBlock, recovery.serveDue);
    }

    function buyerServed(bytes32 nonce, bytes32 bundleHash) external onlyDelegateCall {
        uint256 g0 = gasleft();
        CaseView storage caseRecord = buyerRecoveries[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_WAIT)) revert InvalidTransition();
        if (msg.sender != sellers[purchases[nonce].sellerId].viewData.owner) revert Unauthorized();
        if (block.number > caseRecord.serveDue) revert DeadlinePassed();
        if (bundleHash == bytes32(0)) revert InvalidPublication();
        uint32 serveBlocks =
            deadlineConfigs[profiles[purchases[nonce].profileId].parameters
            .deadlineConfigId].serveBlocks;
        caseRecord.bundleHash = bundleHash;
        caseRecord.challengeUntil = uint64(block.number + serveBlocks);
        caseRecord.state = uint8(CaseState.SERVE_CONFIRM);
        emit Served(nonce, bundleHash, caseRecord.challengeUntil);
        if (_ladderOn(nonce, true)) _ladderCost(nonce, true, g0, abi.encodeWithSelector(msg.sig, nonce, bundleHash));
    }

    function acceptBuyerServe(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage caseRecord = buyerRecoveries[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (msg.sender != caseRecord.requester) revert Unauthorized();
        if (block.number > caseRecord.challengeUntil) revert DeadlinePassed();
        _completeBuyerDelivery(nonce);
    }

    function finalizeBuyerServed(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage caseRecord = buyerRecoveries[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (block.number <= caseRecord.challengeUntil) revert DeadlineNotReached();
        _completeBuyerDelivery(nonce);
    }

    function escalateBuyerServe(bytes32 nonce) external onlyDelegateCall {
        CaseView storage caseRecord = buyerRecoveries[nonce];
        if (caseRecord.state != uint8(CaseState.SERVE_CONFIRM)) revert InvalidTransition();
        if (msg.sender != caseRecord.requester) revert Unauthorized();
        if (block.number > caseRecord.challengeUntil) revert DeadlinePassed();
        uint32 serveBlocks =
            deadlineConfigs[profiles[purchases[nonce].profileId].parameters
            .deadlineConfigId].serveBlocks;
        caseRecord.publishDue = uint64(block.number + serveBlocks);
        caseRecord.state = uint8(CaseState.PUBLISHING);
        emit ServeEscalated(nonce, caseRecord.publishDue);
    }

    function timeoutBuyerServe(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage caseRecord = buyerRecoveries[nonce];
        if (caseRecord.state == uint8(CaseState.SERVE_WAIT)) {
            if (block.number <= caseRecord.serveDue) revert DeadlineNotReached();
        } else if (caseRecord.state == uint8(CaseState.PUBLISHING)) {
            if (block.number <= caseRecord.publishDue) revert DeadlineNotReached();
        } else {
            revert InvalidTransition();
        }
        if (_refundOnly(nonce)) {
            caseRecord.state = uint8(CaseState.UNSERVED);
            emit BuyerRecoveryClosed(nonce, uint8(CaseState.UNSERVED));
            return;
        }
        _sellerFailure(nonce, RefundSource.UNSERVED);
    }

    /// Under a receipt-signature vote profile a lapsed non-delivery dispute
    /// refunds the purchase once, with its deposits, and counts no failure;
    /// the purchase's sample case may still open and run (rule D2-33 (f) 2 3).
    function _refundOnly(bytes32 nonce) private returns (bool) {
        if (_exchangeMode(purchases[nonce].profileId) != ExchangeStore.MODE_VOTE_SIG) return false;
        PurchaseView storage p = purchases[nonce];
        if (!_refundDue(nonce)) {
            _setFinancialState(nonce, FinancialState.REFUNDABLE);
            refundSources[nonce] = uint8(RefundSource.DISPUTE_REFUND);
            ExchangeStore.layout().records[nonce].early = true;
        } else if (p.financialState == uint8(FinancialState.REFUNDED)) {
            // Refunded already: the deposits go back at once.
            uint256 d = disputeDeposits[nonce] + buyerRecoveryDeposits[nonce];
            disputeDeposits[nonce] = 0;
            buyerRecoveryDeposits[nonce] = 0;
            if (d != 0) _transfer(p.buyer, d);
        }
        return true;
    }

}
