// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Rule8Store } from "./Rule8Store.sol";
import { FairBindCore } from "../FairBindCore.sol";
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";

contract FairBindRecovery is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 6;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function claimEpochFailure(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage purchase = purchases[nonce];
        if (!_purchaseExists(purchase)) revert InvalidTransition();
        if (anchors[purchase.sellerId][purchase.epoch].state != uint8(EpochState.EPOCH_FAILED)) {
            revert InvalidTransition();
        }
        _sellerFailure(nonce, RefundSource.EPOCH_FAILED);
    }

    function claimRefund(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage purchase = purchases[nonce];
        if (purchase.financialState != uint8(FinancialState.REFUNDABLE)) {
            revert InvalidTransition();
        }
        uint256 principal = purchase.value;
        uint256 deposit = disputeDeposits[nonce] + buyerRecoveryDeposits[nonce];
        disputeDeposits[nonce] = 0;
        buyerRecoveryDeposits[nonce] = 0;
        _setFinancialState(nonce, FinancialState.REFUNDED);
        _transfer(purchase.buyer, principal + deposit);
        emit Refunded(nonce, purchase.buyer, principal, refundSources[nonce]);
    }

    function releasePurchase(bytes32 nonce) external onlyDelegateCall nonReentrant {
        if (_buyerRecoveryOpen(nonce)) revert InvalidTransition();
        PurchaseView storage purchase = purchases[nonce];
        // Rule 8 pays by the release cursor only (rule D2-39 (h)).
        if (_r8On(purchase.profileId)) revert InvalidTransition();
        if (
            purchase.financialState != uint8(FinancialState.DEFERRED)
                && purchase.financialState != uint8(FinancialState.RELEASABLE)
        ) revert InvalidTransition();
        if (_frozen(purchase)) revert FrozenEntry();
        uint8 caseState = cases[nonce].state;
        if (_forfeitedEntry(purchase)) {
            // The principal left with the forfeiture of the closed window; only
            // deposits of a finished case remain to be paid. An entry of a
            // window closed itemized leaves the deferred balance here and is
            // locked (ADR 0030).
            if (caseState != uint8(CaseState.NONE) && !_caseDone(caseState)) revert InvalidTransition();
            (, bool itemized) = _forfeitWindowOf(sellers[purchase.sellerId].viewData.bondId, purchase.settledBlock);
            if (itemized) {
                _setFinancialState(nonce, FinancialState.FORFEITED);
                return;
            }
            purchase.financialState = uint8(FinancialState.FORFEITED);
            _payDeposits(nonce);
            return;
        }
        // Under receipt signatures only a bound purchase is a sale (ADR 0037).
        if (_exchangeMode(purchase.profileId) != 0 && !_bound(nonce)) revert NotBound();
        AnchorView storage anchorRecord = anchors[purchase.sellerId][purchase.epoch];
        if (anchorRecord.state != uint8(EpochState.SEALED)) revert InvalidTransition();
        DeadlineConfig storage deadlines =
            deadlineConfigs[profiles[purchase.profileId].parameters.deadlineConfigId];
        if (
            block.number <= purchase.claimUntil
                || block.number <= anchorRecord.sealDeadline + deadlines.openBlocks
                || block.number < purchase.releaseBlock || block.number < purchase.retainUntil
        ) revert DeadlineNotReached();
        // The release clock of the account stops while one of its cases waits
        // for an assignment: deferBlocks must pass in unpaused blocks since
        // settlement (design 2 rule D2-21, ADR 0029).
        if (
            block.number - _pausedSince(sellers[purchase.sellerId].viewData.bondId, purchase.settledBlock)
                < purchase.releaseBlock
        ) revert DeadlineNotReached();
        if (caseState == uint8(CaseState.NONE) || (caseState == uint8(CaseState.DELIVERED)
            && cases[nonce].trigger == uint8(CaseTrigger.NON_DELIVERY))) {
            // A sampled entry is paid only after its sample case has been opened
            // and closed, also when a non-delivery dispute ended as delivered.
            (bool eligible,) = _sampleStatus(purchase, nonce);
            if (eligible) revert NotSampled();
        } else if (!_caseDone(caseState)
            && (_waitHolds() || caseState != uint8(CaseState.WAITING_ASSIGNMENT))) revert InvalidTransition();
        _payDeposits(nonce);
        _setFinancialState(nonce, FinancialState.RELEASED);
        _transfer(sellers[purchase.sellerId].viewData.owner, purchase.value);
        emit Released(nonce, purchase.sellerId, purchase.value);
    }

    event RedrawRegistered(bytes32 indexed nonce, uint32 redraw, uint64 checkpointVersion, uint64 registeredBlock);

    /// Keeper call (design 2 rule D2-23 (a), ADR 0031): asks the request-based
    /// source for the SAMPLE value of the epochs of profile `profileId` whose
    /// anchor deadline is that of `epoch`. Anyone may call it, from the block
    /// after the anchor deadline A through the last block M = A + D_S + T_V in
    /// which the value is taken; a repeated call asks again with the same input.
    function requestSampleValue(uint32 profileId, uint24 epoch) external onlyDelegateCall {
        if (profiles[profileId].profileId == 0) revert UnknownProfile();
        IVrfRandomness vrf = _vrfAt(block.number);
        if (address(vrf) == address(0)) revert InvalidTransition();
        (uint64 anchorDeadline, uint64 deadline) = _sampleRequestWindow(vrf, profileId, epoch);
        vrf.request(VRF_SAMPLE, _sampleInput(profileId, anchorDeadline), deadline);
        _r8FeeOnce(profileId, Rule8Store.FEE_SAMPLE_REQUEST, anchorDeadline);
    }

    /// The anchor deadline A and the deadline M of a SAMPLE request in this
    /// block, which must lie in [A + 1, M]. The request reads the profile and
    /// the epoch only: no account and no anchor (rule D2-23 (a)), so an epoch
    /// that no account anchored still gets its value. A mutation build of the
    /// tests overrides it.
    function _sampleRequestWindow(IVrfRandomness vrf, uint32 profileId, uint24 epoch)
        internal
        view
        virtual
        returns (uint64 anchorDeadline, uint64 deadline)
    {
        anchorDeadline = _anchorDeadline(profiles[profileId].parameters, epoch);
        if (block.number <= anchorDeadline) revert RequestTooEarly();
        deadline = _sampleDeadline(vrf, anchorDeadline);
        if (block.number > deadline) revert DeadlinePassed();
    }

    /// Keeper call (design 2 rule D2-20 (b), ADR 0031): registers the use of
    /// an AUX value for the next redraw of a waiting case under a
    /// request-based source. Anyone may call it once the checkpoint the
    /// redraw searches, the first one written after the case's last search,
    /// is on chain; the block of this call is the t of the AUX request.
    function registerRedraw(bytes32 nonce) external onlyDelegateCall {
        if (cases[nonce].state != uint8(CaseState.WAITING_ASSIGNMENT)) revert InvalidTransition();
        PurchaseView storage purchase = purchases[nonce];
        if (address(_vrfAt(anchors[purchase.sellerId][purchase.epoch].anchoredBlock)) == address(0)) {
            revert InvalidTransition();
        }
        AssignmentWait storage wait = assignmentWaits[nonce];
        uint64 version = _checkpointAt(purchase.profileId, wait.searchBlock) + 1;
        if (version > latestCheckpointVersion[purchase.profileId]) revert InvalidTransition();
        SamplingStore.RedrawUse storage use = SamplingStore.layout().redrawUses[nonce];
        uint32 redraw = wait.redraws + 1;
        if (use.redraw == redraw) revert InvalidTransition();
        use.registeredBlock = uint64(block.number);
        use.checkpointVersion = version;
        use.redraw = redraw;
        emit RedrawRegistered(nonce, redraw, version, uint64(block.number));
    }

    /// Keeper call (rule D2-23 (a), ADR 0031): asks for the AUX value of the
    /// registered redraw of a waiting case, in a block after the registration.
    /// A repeated call asks again with the stored input.
    function requestRedrawValue(bytes32 nonce) external onlyDelegateCall {
        SamplingStore.RedrawUse storage use = SamplingStore.layout().redrawUses[nonce];
        if (cases[nonce].state != uint8(CaseState.WAITING_ASSIGNMENT) || use.redraw != assignmentWaits[nonce].redraws + 1) {
            revert NotRegistered();
        }
        if (block.number <= use.registeredBlock) revert RequestTooEarly();
        PurchaseView storage purchase = purchases[nonce];
        _vrfAt(anchors[purchase.sellerId][purchase.epoch].anchoredBlock).request(
            VRF_AUX, _redrawInput(nonce, use.redraw, use.registeredBlock), 0
        );
    }

    event RedrawValueTimedOut(bytes32 indexed nonce, uint32 redraw);

    /// Keeper call, the exit of rule D2-23 (d) (b) for a redraw (ADR 0031):
    /// when the AUX value of a waiting case's registered redraw is not stored
    /// by its first request block + D_V + T_V, anyone may end the case from
    /// the next block. The case ends without a verdict; the seller is
    /// suspended and the account freezes from the case's settlement block and
    /// opens its claim window here, as a confirmed failure would, but the
    /// failure is not counted and nothing is deducted. The purchase is an
    /// unencumbered frozen entry its buyer can claim. A value stored later is
    /// never used: the case no longer waits.
    function timeoutRedrawValue(bytes32 nonce) external onlyDelegateCall nonReentrant {
        CaseView storage c = cases[nonce];
        SamplingStore.RedrawUse storage use = SamplingStore.layout().redrawUses[nonce];
        if (c.state != uint8(CaseState.WAITING_ASSIGNMENT) || use.redraw != assignmentWaits[nonce].redraws + 1) {
            revert NotRegistered();
        }
        PurchaseView storage purchase = purchases[nonce];
        IVrfRandomness vrf = _vrfAt(anchors[purchase.sellerId][purchase.epoch].anchoredBlock);
        bytes32 id = keccak256(abi.encode(VRF_AUX, _redrawInput(nonce, use.redraw, use.registeredBlock)));
        (uint64 requested, uint64 delivered,) = vrf.requestTimes(id);
        if (requested == 0 || delivered != 0) revert InvalidTransition();
        if (block.number <= uint256(requested) + vrf.responseBlocks() + vrf.deadlineSlackBlocks()) {
            revert DeadlineNotReached();
        }
        _clockWaitEnds(nonce);
        _sampleEnded(nonce);
        c.state = uint8(CaseState.INCONCLUSIVE);
        _setFinancialState(nonce, FinancialState.DEFERRED);
        _releaseTrigger(nonce);
        _confirmFailure(purchase.sellerId, nonce, false, purchase.settledBlock);
        emit RedrawValueTimedOut(nonce, use.redraw);
    }

    function _caseDone(uint8 caseState) private pure returns (bool) {
        return caseState == uint8(CaseState.DELIVERED) || caseState == uint8(CaseState.INCONCLUSIVE)
            || caseState == uint8(CaseState.FINAL);
    }

    /// A receipt the seller signed whose nonce the anchored list holds with a
    /// different receipt leaf. The anchor's nonces are unique, so the entry
    /// at that nonce is the one the seller committed for this purchase; a
    /// different leaf is a second commitment at one nonce and is confirmed as
    /// equivocation. Only a holder of the signed receipt (its buyer, or the
    /// seller) can prove it.
    function proveMisanchoredReceipt(
        FairBindReceipt calldata receipt,
        bytes calldata signature,
        bytes32 anchoredLeaf,
        ReceiptProof calldata proof
    ) external onlyDelegateCall nonReentrant {
        if (receipt.nonce == bytes32(0)) revert InvalidProof();
        PurchaseView storage purchase = purchases[receipt.nonce];
        bytes32 leaf = _validateReceipt(purchase, receipt.nonce, receipt, signature);
        AnchorView storage anchorRecord = anchors[purchase.sellerId][purchase.epoch];
        if (!_bindingProofOpen(purchase, anchorRecord)) revert InvalidProof();
        if (
            anchoredLeaf == leaf || proof.count != anchorRecord.count
                || !FairBindMerkle.verify(
                    anchorRecord.root, receipt.nonce, anchoredLeaf, proof.index, proof.count, proof.siblings
                )
        ) revert InvalidProof();
        _sellerFailure(receipt.nonce, RefundSource.EQUIVOCATION);
    }

    /// A binding proof is taken from the anchor on through the purchase's
    /// retainUntil, before the epoch's SAMPLE value as well (rule D2-19 (g));
    /// the proof's timing is the client's condition, not a start the contract
    /// enforces. A mutation build of the tests overrides it.
    function _bindingProofOpen(PurchaseView storage purchase, AnchorView storage anchorRecord)
        internal
        view
        virtual
        returns (bool)
    {
        return anchorRecord.root != bytes32(0) && block.number <= purchase.retainUntil;
    }

    function proveEquivocation(
        FairBindReceipt calldata first,
        bytes calldata firstSignature,
        FairBindReceipt calldata second,
        bytes calldata secondSignature
    ) external onlyDelegateCall nonReentrant {
        if (first.nonce == bytes32(0) || first.nonce != second.nonce) revert InvalidProof();
        PurchaseView storage purchase = purchases[first.nonce];
        bytes32 firstLeaf = _validateReceipt(purchase, first.nonce, first, firstSignature);
        bytes32 secondLeaf = _validateReceipt(purchase, first.nonce, second, secondSignature);
        if (firstLeaf == secondLeaf) revert InvalidProof();
        _sellerFailure(first.nonce, RefundSource.EQUIVOCATION);
    }
}
