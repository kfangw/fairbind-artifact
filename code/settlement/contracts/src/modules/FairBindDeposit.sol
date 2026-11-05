// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { BatchStore } from "./BatchStore.sol";
import { BatchShared } from "./BatchShared.sol";

/// Extension module 3: the proportional appeal deposit (ADR 0033), the
/// switch of seller proofs and the end of an epoch's sampling deadline
/// (ADR 0034), the side-gain deposit with the repeated sampling request
/// of a side-gain profile (ADR 0035), and the review values of batched
/// cases (ADR 0036).
contract FairBindDeposit is BatchShared {
    /// A module of batched profiles: rule 8 does not admit them.
    function _r8Possible() internal pure override returns (bool) {
        return false;
    }

    uint8 public constant MODULE_KIND = 14;

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        BatchShared(token, gov, guard, treasury, rewardPool)
    { }


    error DepositAboveLimit();

    event AppealDepositSet(bytes32 indexed nonce, uint256 deposit, uint256 heldHigh);
    event ProofsSwitched(uint32 indexed bondId, bool off);
    event SideGainChanged(uint32 indexed bondId, uint256 deposit);
    event ReviewUseRegistered(bytes32 indexed nonce, uint8 stage, uint64 registered);
    event ReviewValueTimedOut(bytes32 indexed nonce, uint8 stage);


    /// A buyer's appeal of an initial PASS under a proportional deposit (ADR
    /// 0033). The deposit is max(d0, ceil(depositPpm * H)), d0 the profile's
    /// appealDeposit and H the high mark of the account's held total at the
    /// end of the block before this one; the call reverts when it exceeds
    /// maxDeposit. A failed appeal pays the seller d0 and locks the rest.
    function appealWithLimit(bytes32 nonce, uint256 maxDeposit) external onlyDelegateCall nonReentrant {
        CaseView storage c = cases[nonce];
        if (c.state != uint8(CaseState.INITIAL_VERDICT) || c.reviewPath != 0 || _evidencePending(nonce)) {
            revert InvalidTransition();
        }
        if (block.number > reviews[nonce].appealUntil) revert DeadlinePassed();
        PurchaseView storage p = purchases[nonce];
        if (msg.sender != p.buyer || c.initialVerdict != uint8(Verdict.PASS)) revert Unauthorized();
        BatchStore.Layout storage l = BatchStore.layout();
        uint256 ppm = l.terms[p.profileId].depositPpm;
        if (ppm == 0) revert InvalidTransition();
        uint256 high = _appealHigh(sellers[p.sellerId].viewData.bondId, p.profileId);
        uint256 d0 = profiles[p.profileId].parameters.appealDeposit;
        uint256 d = (ppm * high + PPM - 1) / PPM;
        if (d < d0) d = d0;
        if (d > maxDeposit) revert DepositAboveLimit();
        ReviewData storage r = reviews[nonce];
        r.appellant = msg.sender;
        r.deposit = d;
        l.depositExcess[nonce] = uint96(d - d0);
        _transferFrom(msg.sender, d);
        c.reviewPath = 1;
        _startReview(nonce, uint8(JudgmentStage.PARTY), uint8(CaseState.PARTY_REVIEW), uint64(block.number + 1));
        emit AppealDepositSet(nonce, d, high);
        emit ReviewSelected(nonce, true, false, c.randomBlock);
    }

    /// High mark at the end of the previous block, as an appeal in this block reads it.
    function _appealHigh(uint32 bondId, uint32 profileId) internal view virtual returns (uint256) {
        BatchStore.HeldMark storage m = BatchStore.layout().held[bondId];
        if (m.snapBlock == block.number) return m.snap;
        return _heldHigh(m, block.number - 1, profiles[profileId].parameters.deferBlocks);
    }

    function appealDepositOf(bytes32 nonce) external view onlyDelegateCall returns (uint256 d, uint256 high) {
        PurchaseView storage p = purchases[nonce];
        high = _appealHigh(sellers[p.sellerId].viewData.bondId, p.profileId);
        d = (uint256(BatchStore.layout().terms[p.profileId].depositPpm) * high + PPM - 1) / PPM;
        uint256 d0 = profiles[p.profileId].parameters.appealDeposit;
        if (d < d0) d = d0;
    }

    // ----------------------------------------------------- seller proofs

    /// The account's seller proofs go off at once for every entry; back on,
    /// they take only entries settled after this block.
    function setProofsOff(uint32 bondId, bool off) external onlyDelegateCall {
        if (msg.sender != bonds[bondId].owner) revert Unauthorized();
        BatchStore.ProofAccount storage acc = BatchStore.layout().proofAccounts[bondId];
        if (off) {
            acc.offSince = uint64(block.number);
        } else {
            acc.offSince = 0;
            acc.onSince = uint64(block.number);
        }
        emit ProofsSwitched(bondId, off);
    }


    function depositSideGain(uint32 bondId, uint128 amount) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (BatchStore.layout().terms[b.profileId].sideGainPpm == 0) revert InvalidTransition();
        BatchStore.SideGain storage g = BatchStore.layout().sideGain[bondId];
        g.deposit += amount;
        _transferFrom(msg.sender, amount);
        emit SideGainChanged(bondId, g.deposit);
    }

    /// The deposit leaves only while no sale of the account is open.
    function withdrawSideGain(uint32 bondId, uint128 amount) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        BatchStore.SideGain storage g = BatchStore.layout().sideGain[bondId];
        if (g.open != 0 || amount > g.deposit) revert InvalidTransition();
        g.deposit -= amount;
        _transfer(b.owner, amount);
        emit SideGainChanged(bondId, g.deposit);
    }

    /// A sale whose sampling is decided without a case to wait for (not
    /// sampled, its epoch failed, or the sale already ended) stops holding
    /// side-gain deposit. A sampled sale stops when its sample case ends.
    function clearSideGain(bytes32 nonce) external onlyDelegateCall {
        BatchStore.Layout storage l = BatchStore.layout();
        if (!l.sideGainOpen[nonce]) revert InvalidTransition();
        PurchaseView storage p = purchases[nonce];
        uint8 fs = p.financialState;
        uint8 es = anchors[p.sellerId][p.epoch].state;
        bool done = fs == uint8(FinancialState.REFUNDED) || fs == uint8(FinancialState.REFUNDABLE)
            || fs == uint8(FinancialState.RELEASED) || _forfeitedEntry(p) || es == uint8(EpochState.EPOCH_FAILED);
        if (!done && es == uint8(EpochState.SEALED)) {
            (bool eligible,) = _sampleStatus(p, nonce);
            done = !eligible;
        }
        if (!done) revert InvalidTransition();
        l.sideGainOpen[nonce] = false;
        l.sideGain[sellers[p.sellerId].viewData.bondId].open--;
    }

    /// Keeper call of a side-gain profile: once M passed without a taken
    /// SAMPLE value, asks again with the input (profileId, A, 1) and no
    /// deadline; seal takes its value.
    function rerequestSampleValue(uint32 profileId, uint24 epoch) external onlyDelegateCall {
        if (BatchStore.layout().terms[profileId].sideGainPpm == 0) revert InvalidTransition();
        IVrfRandomness vrf = _vrf();
        uint64 a = _anchorDeadline(profiles[profileId].parameters, epoch);
        if (block.number <= _sampleDeadline(vrf, a)) revert RequestTooEarly();
        if (_sampleValue(vrf, profileId, a) != bytes32(0)) revert InvalidTransition();
        vrf.request(VRF_SAMPLE, abi.encode(profileId, a, uint32(1)), 0);
    }

    /// Keeper call: an anchored epoch passed its sampling deadline M without
    /// a value it takes. Its sales can no longer be sampled, so the epoch no
    /// longer blocks seller proofs of the account.
    function noteSampleDeadline(uint32 sellerId, uint24 epoch) external onlyDelegateCall {
        AnchorView storage a = anchors[sellerId][epoch];
        if (a.state != uint8(EpochState.ANCHORED) || !_deadlinePassed(sellerId, epoch)) revert InvalidTransition();
        _epochResolved(sellerId, epoch);
    }

    function getSideGain(uint32 bondId) external view onlyDelegateCall returns (BatchStore.SideGain memory) {
        return BatchStore.layout().sideGain[bondId];
    }

    // ------------------------------------------- review values (ADR 0036)

    /// Keeper call: asks, from the block after the stage's use was
    /// registered, for the AUX value of a batched review stage. Input
    /// (review use, nonce, stage, 0, registration block). A repeated call
    /// asks again with the stored input.
    function requestReviewValue(bytes32 nonce) external onlyDelegateCall {
        BatchStore.ReviewUse storage u = _reviewWaitingUse(nonce);
        if (block.number <= u.registered) revert RequestTooEarly();
        _vrf().request(VRF_AUX, _reviewInput(nonce, u.stage, u.registered), 0);
    }

    /// Keeper call: once the stage's AUX value is stored, places the stage in
    /// its candidate's queue. Later attempts of the stage draw from the same
    /// value; the block it was stored in fixes the candidate.
    function assignReview(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.ReviewUse storage u = _reviewWaitingUse(nonce);
        IVrfRandomness vrf = _vrf();
        bytes32 id = _reviewUseId(nonce, u);
        (bool ready, bytes32 value) = vrf.valueOf(id);
        if (!ready) revert DeadlineNotReached();
        (, uint64 delivered,) = vrf.requestTimes(id);
        CaseView storage c = cases[nonce];
        c.randomness = value;
        c.randomBlock = delivered;
        _valueArrived(BatchStore.layout().entries[nonce], uint256(u.registered) + vrf.delayBlocks(), delivered);
        _hook(HOOK_ENQUEUE, uint256(nonce));
    }

    /// The exit of an unanswered review value, from the block after its first
    /// request + D_V + T_V. A review the seller asked for against an initial
    /// FAIL, and the review of a case that is not a sample case, end as a
    /// progress failure, which upholds that FAIL. Any other review of a sample
    /// case ends without a verdict: its verifiers are released, the appeal
    /// deposit goes back, and the account is suspended and frozen from the
    /// case's sale with its claim window open, nothing counted or deducted.
    function timeoutReviewValue(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.ReviewUse storage u = _reviewWaitingUse(nonce);
        IVrfRandomness vrf = _vrf();
        (uint64 requested, uint64 delivered,) = vrf.requestTimes(_reviewUseId(nonce, u));
        if (requested == 0 || delivered != 0) revert InvalidTransition();
        if (!_exitOpen(vrf, requested)) revert DeadlineNotReached();
        _valueArrived(BatchStore.layout().entries[nonce], uint256(u.registered) + vrf.delayBlocks(), block.number);
        CaseView storage c = cases[nonce];
        emit ReviewValueTimedOut(nonce, c.stage);
        if (c.trigger != uint8(CaseTrigger.SAMPLE) || _upholdsFirstFail(c)) {
            _finishReview(nonce, uint8(Verdict.INCONCLUSIVE), true);
            return;
        }
        _releaseAllAssignments(nonce);
        _resolveAppealDeposit(nonce, uint8(Verdict.INCONCLUSIVE));
        _valueExit(nonce);
    }

    /// Whether an unanswered review upholds the initial FAIL: a review the
    /// seller appealed for. A mutation build of the tests overrides it.
    function _upholdsFirstFail(CaseView storage c) internal view virtual returns (bool) {
        return c.reviewPath == 1 && c.initialVerdict == uint8(Verdict.FAIL);
    }

    function getReviewUse(bytes32 nonce) external view onlyDelegateCall returns (BatchStore.ReviewUse memory) {
        return BatchStore.layout().reviewUses[nonce];
    }

    /// Hook operation of this module: register a review stage's use.
    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op != HOOK_REVIEW_USE) _unknownHook();
        bytes32 nonce = bytes32(arg);
        uint8 stage = cases[nonce].stage;
        BatchStore.layout().reviewUses[nonce] = BatchStore.ReviewUse(stage, uint64(block.number));
        emit ReviewUseRegistered(nonce, stage, uint64(block.number));
    }

    function hookOps() external pure returns (uint256) {
        return 1 << HOOK_REVIEW_USE;
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](13);
        s[0] = this.appealWithLimit.selector;
        s[1] = this.appealDepositOf.selector;
        s[2] = this.setProofsOff.selector;
        s[3] = this.depositSideGain.selector;
        s[4] = this.withdrawSideGain.selector;
        s[5] = this.clearSideGain.selector;
        s[6] = this.rerequestSampleValue.selector;
        s[7] = this.noteSampleDeadline.selector;
        s[8] = this.getSideGain.selector;
        s[9] = this.requestReviewValue.selector;
        s[10] = this.assignReview.selector;
        s[11] = this.timeoutReviewValue.selector;
        s[12] = this.getReviewUse.selector;
    }
}
