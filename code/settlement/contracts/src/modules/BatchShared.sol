// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";

/// Code shared by the extension modules (ADR 0032 to ADR 0035).
abstract contract BatchShared is FairBindCore {
    address private immutable moduleSelf = address(this);

    bytes32 internal constant PERMUTATION_DOMAIN = keccak256("fairbind/batch-permutation/v1");
    bytes32 internal constant PROOF_CASE_DOMAIN = keccak256("fairbind/proof-case/v1");
    /// Use of an AUX value: the first assignment of a case opened after its batch closed.
    bytes32 internal constant LATE_USE = keccak256("FairBind/late/v1");
    /// Use of an AUX value: the audit draw of a seller proof.
    bytes32 internal constant AUDIT_USE = keccak256("FairBind/audit/v1");
    /// Use of an AUX value: the assignment of a review stage (ADR 0036).
    bytes32 internal constant REVIEW_USE = keccak256("FairBind/review/v1");

    uint8 internal constant KIND_PURCHASE = 1;
    uint8 internal constant KIND_PROOF = 2;

    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }

    modifier onlyHook() {
        if (address(this) == moduleSelf || entered != HOOK_CONTEXT) revert Unauthorized();
        _;
    }

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function _vrf() internal view returns (IVrfRandomness) {
        return IVrfRandomness(SamplingStore.layout().randomness.source);
    }

    /// C_e: the block a batch closes, the opening deadline of its sample cases.
    function _batchClose(ServiceProfileInput storage profile, uint24 epoch) internal view returns (uint256) {
        DeadlineConfig storage d = deadlineConfigs[profile.deadlineConfigId];
        return uint256(_anchorDeadline(profile, epoch)) + 1 + _valueDelay(profile) + d.sealBlocks + d.openBlocks;
    }

    /// The batch whose blocks hold block t: the first epoch with C_e >= t.
    function _batchOf(ServiceProfileInput storage profile, uint256 t) internal view returns (uint24) {
        uint256 c0 = _batchClose(profile, 0);
        if (t <= c0) return 0;
        return uint24((t - c0 + profile.epochBlocks - 1) / profile.epochBlocks);
    }

    /// The checkpoint of block A_e, which a batched epoch must have.
    function _batchVersion(uint32 profileId, uint24 epoch) internal view returns (uint64 version) {
        uint64 a = _anchorDeadline(profiles[profileId].parameters, epoch);
        version = _checkpointAt(profileId, a);
        if (version == 0 || verifierCheckpoints[profileId][version].checkpointBlock != a) revert ServiceClassUnavailable();
    }

    function _assignId(uint32 profileId, uint24 epoch) internal pure returns (bytes32) {
        return keccak256(abi.encode(VRF_ASSIGN, abi.encode(profileId, epoch)));
    }

    function _lateInput(bytes32 nonce, uint64 t) internal pure returns (bytes memory) {
        return abi.encode(LATE_USE, nonce, uint8(JudgmentStage.INITIAL), uint32(0), t);
    }

    function _auditInput(bytes32 nonce, uint64 t) internal pure returns (bytes memory) {
        return abi.encode(AUDIT_USE, nonce, uint8(0), uint32(1), t);
    }

    /// Input of the AUX request of a review stage whose use was registered
    /// in block t: the use, its identifier (nonce, stage) and t.
    function _reviewInput(bytes32 nonce, uint8 stage, uint64 t) internal pure returns (bytes memory) {
        return abi.encode(REVIEW_USE, nonce, stage, uint32(0), t);
    }

    function _proofCase(bytes32 nonce) internal pure returns (bytes32) {
        return keccak256(abi.encode(PROOF_CASE_DOMAIN, nonce));
    }

    /// The eligibility state of verifier `id` at the end of block x: the
    /// first record that ends after x, or the current state. A mutation build
    /// of the tests overrides it.
    function _stateAt(uint32 id, uint256 x) internal view virtual returns (uint96 bond, uint8 status, uint64 classes) {
        BatchStore.VState[] storage h = BatchStore.layout().history[id];
        uint256 lo;
        uint256 hi = h.length;
        while (lo < hi) {
            uint256 mid = (lo + hi) / 2;
            if (h[mid].endBlock <= x) lo = mid + 1;
            else hi = mid;
        }
        if (lo < h.length) {
            BatchStore.VState storage s = h[lo];
            return (s.bond, s.status, s.classes);
        }
        VerifierView storage v = verifiers[id];
        return (uint96(v.bond), v.status, uint64(v.classBitmap));
    }

    /// Slots of verifier u: the largest k with k * (V + reviewCost) <=
    /// exposure * (bond - k * reserve), V the slot value of the batch terms,
    /// and the bond capped at verifierBondCap, under the slot profile.
    function _slotCount(uint32 u) internal view returns (uint256) {
        BatchStore.Layout storage l = BatchStore.layout();
        ServiceProfileInput storage p = profiles[l.slotProfile].parameters;
        uint256 bond = verifiers[u].bond;
        if (bond > p.verifierBondCap) bond = p.verifierBondCap;
        uint256 reserve = p.verifierLatePenalty > p.verifierWrongPenalty ? p.verifierLatePenalty : p.verifierWrongPenalty;
        uint256 gamma = p.verifierExposurePpm;
        return gamma * bond / (PPM * (uint256(l.terms[l.slotProfile].slotValue) + p.maxReviewCost) + gamma * reserve);
    }

    /// An anchored epoch is past M without a SAMPLE value seal would take (a
    /// side-gain profile asks again instead).
    function _deadlinePassed(uint32 sellerId, uint24 epoch) internal view returns (bool) {
        AnchorView storage a = anchors[sellerId][epoch];
        IVrfRandomness vrf = _vrfAt(a.anchoredBlock);
        if (address(vrf) == address(0) || BatchStore.layout().terms[a.profileId].sideGainPpm != 0) return false;
        uint64 deadline = _anchorDeadline(profiles[a.profileId].parameters, epoch);
        return block.number > _sampleDeadline(vrf, deadline) && _sampleValue(vrf, a.profileId, deadline) == bytes32(0);
    }

    function _waitsForBatch(bytes32 caseId) internal view returns (bool) {
        BatchStore.Entry storage en = BatchStore.layout().entries[caseId];
        if (en.kind == KIND_PROOF) return BatchStore.layout().proofs[en.ref].state == BatchStore.P_BATCHED;
        return cases[caseId].state == uint8(CaseState.BATCHED);
    }

    // ------------------------------------------------ value waits (ADR 0036)

    /// Whether the exit of an unanswered ASSIGN or AUX request first asked
    /// for in block `requested` is open: from the block after requested +
    /// D_V + T_V. A mutation build of the tests overrides it.
    function _exitOpen(IVrfRandomness vrf, uint64 requested) internal view virtual returns (bool) {
        return block.number > uint256(requested) + vrf.responseBlocks() + vrf.deadlineSlackBlocks();
    }

    /// First paused block of a value still missing after its bound `due`: the
    /// block after it. A mutation build of the tests overrides it.
    function _lateStart(uint256 due) internal view virtual returns (uint256) {
        return due + 1;
    }

    function _bondOf(bytes32 nonce) internal view returns (uint32) {
        return sellers[purchases[nonce].sellerId].viewData.bondId;
    }

    /// The account starts one more pause of its release clock that counts
    /// from block `from`, which may lie before this block: pauses that began
    /// at or after `from` are merged into it, and a pause that ended at or
    /// after `from` is reopened (ADR 0029, ADR 0036).
    function _pauseFrom(uint32 bondId, uint256 from) internal {
        if (from > block.number) from = block.number;
        ReleaseClock storage clock = releaseClocks[bondId];
        clock.waitingCases++;
        mapping(uint256 => Pause) storage log = pauseLog[bondId];
        uint32 n = clock.pauses;
        while (n != 0 && log[n - 1].start >= from) {
            delete log[n - 1];
            n--;
        }
        uint64 before;
        if (n != 0) {
            Pause storage last = log[n - 1];
            if (last.end == 0 || last.end >= from) {
                last.end = 0;
                clock.pauses = n;
                emit ReleaseClockPaused(bondId, last.pausedBefore + uint64(block.number) - last.start);
                return;
            }
            before = last.pausedBefore + last.end - last.start;
        }
        log[n] = Pause(uint64(from), 0, before);
        clock.pauses = n + 1;
        emit ReleaseClockPaused(bondId, before);
    }

    /// One pause of the account ends in this block (as `_clockWaitEnds`).
    function _pauseEnd(uint32 bondId) internal {
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

    /// The value a waiting case needs is there in block `delivered` (or the
    /// wait ends by its exit, delivered = this block). A pause the keeper
    /// marked ends here. Without a mark, a sample case whose value came after
    /// its bound `due` records the blocks from `due` + 1 to this block now.
    function _valueArrived(BatchStore.Entry storage en, uint256 due, uint256 delivered) internal {
        if (en.paused) {
            en.paused = false;
            _clockWaitEnds(en.ref);
            return;
        }
        if (delivered <= due || en.kind != KIND_PURCHASE || cases[en.ref].trigger != uint8(CaseTrigger.SAMPLE)) return;
        uint32 bondId = _bondOf(en.ref);
        _pauseFrom(bondId, _lateStart(due));
        _pauseEnd(bondId);
    }

    /// A sample case whose assignment value never came ends without a
    /// verdict, as the redraw exit of ADR 0031.
    function _valueExit(bytes32 nonce) internal {
        PurchaseView storage purchase = purchases[nonce];
        _sampleEnded(nonce);
        cases[nonce].state = uint8(CaseState.INCONCLUSIVE);
        _setFinancialState(nonce, FinancialState.DEFERRED);
        _releaseTrigger(nonce);
        _confirmFailure(purchase.sellerId, nonce, false, purchase.settledBlock);
    }

    /// The case waits for the AUX value of its review stage: the stage's use
    /// is registered and no verifier holds or queues the stage.
    function _reviewWaitingUse(bytes32 nonce) internal view returns (BatchStore.ReviewUse storage u) {
        u = BatchStore.layout().reviewUses[nonce];
        CaseView storage c = cases[nonce];
        uint8 st = c.state;
        if (u.registered == 0 || u.stage != c.stage || c.assignedVerifierId != 0
            || (st != uint8(CaseState.PARTY_REVIEW) && st != uint8(CaseState.AUTO_REVIEW) && st != uint8(CaseState.TIEBREAK))) {
            revert NotRegistered();
        }
    }

    function _reviewUseId(bytes32 nonce, BatchStore.ReviewUse storage u) internal view returns (bytes32) {
        return keccak256(abi.encode(VRF_AUX, _reviewInput(nonce, u.stage, u.registered)));
    }

    /// A hook operation this module does not implement.
    function _unknownHook() internal pure {
        revert InvalidTransition();
    }
}
