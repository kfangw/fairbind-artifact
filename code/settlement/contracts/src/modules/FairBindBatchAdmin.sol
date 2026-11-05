// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { BatchShared } from "./BatchShared.sol";

interface IVrfPublicKey {
    function publicKey() external view returns (bytes memory);
}

/// Extension module 1 (ADR 0032): batch terms and their admission check,
/// checkpoints of fixed blocks read from the verifiers' state history, the
/// requests of batch and late values, the pause of a late batch value, the
/// exits of unanswered batch and late values, and the progress failure of a
/// case whose draws are used up.
contract FairBindBatchAdmin is BatchShared {
    /// A module of batched profiles: rule 8 does not admit them.
    function _r8Possible() internal pure override returns (bool) {
        return false;
    }

    uint8 public constant MODULE_KIND = 12;

    bytes32 internal constant BATCH_TERMS_DOMAIN = keccak256("fairbind/batch-terms/v1");

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        BatchShared(token, gov, guard, treasury, rewardPool)
    { }


    event BatchTermsSet(uint32 indexed profileId, bytes32 termsHash);
    event EpochOpenCountRecorded(uint32 indexed profileId, uint24 indexed epoch, uint32 count);
    event BatchValueLate(uint32 indexed profileId, uint24 indexed epoch);
    event BatchValueTimedOut(uint32 indexed profileId, uint24 indexed epoch);
    event LateValueTimedOut(bytes32 indexed nonce);

    // ------------------------------------------------------------ terms

    /// Fixes the batch terms of a profile that has never been active, once
    /// (ADR 0032). The source must be request based. Admission: D_S = D_V + 1,
    /// assignDelay >= D_V + 1, T_V >= keeperSlack, epochBlocks >= D_S + T_V,
    /// slotValue at least the profile's largest value cap, the audit rate a
    /// probability. termsHash commits the terms, the source, its public key
    /// and its two bounds.
    function setBatchTerms(uint32 profileId, BatchStore.Terms calldata t) external onlyDelegateCall onlyGovernance {
        ServiceProfileView storage profile = profiles[profileId];
        if (profile.profileId == 0) revert UnknownProfile();
        BatchStore.Layout storage l = BatchStore.layout();
        if (profile.active || profileActivated[profileId] || l.terms[profileId].batched) revert InvalidTransition();
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        if (!cfg.vrf) revert InvalidConfiguration();
        IVrfRandomness vrf = IVrfRandomness(cfg.source);
        uint256 dv = vrf.responseBlocks();
        uint256 tv = vrf.deadlineSlackBlocks();
        uint256 ds = vrf.delayBlocks();
        ServiceProfileInput storage p = profile.parameters;
        if (
            !t.batched || ds != dv + 1 || t.assignDelay < dv + 1 || tv < t.keeperSlack
                || p.epochBlocks < ds + tv || t.slotValue < p.maxPurchaseValue || t.auditPpm > PPM
                || (t.auditPpm == 0 && t.contestBlocks != 0) || _excludedByExchange(profileId, t.sideGainPpm)
        ) revert InvalidProfile();
        bytes32 h = keccak256(
            abi.encode(
                BATCH_TERMS_DOMAIN, profileId, t.assignDelay, t.keeperSlack, t.depositPpm, t.auditPpm,
                t.contestBlocks, t.sideGainPpm, t.slotValue, address(vrf),
                keccak256(IVrfPublicKey(address(vrf)).publicKey()), dv, tv
            )
        );
        if (h != t.termsHash) revert InvalidProfile();
        l.terms[profileId] = t;
        l.historyOn = true;
        if (l.slotProfile == 0) l.slotProfile = profileId;
        emit BatchTermsSet(profileId, h);
    }

    /// Batch terms and exchange terms exclude each other in either order:
    /// a proof profile takes no verifier assignment, a receipt-signature
    /// vote profile no side-gain grade (rules D2-13, D2-28 (c), D2-33 (h)).
    /// A mutation build of the tests overrides it.
    function _excludedByExchange(uint32 profileId, uint256 sideGainPpm) internal view virtual returns (bool) {
        uint8 m = _exchangeMode(profileId);
        return m == ExchangeStore.MODE_PROOF || (m == ExchangeStore.MODE_VOTE_SIG && sideGainPpm != 0);
    }

    // ------------------------------------------------------- checkpoints

    /// Writes the checkpoint of epoch `epoch` of a batched profile: the state
    /// every verifier had at the end of the epoch's anchor deadline A, read
    /// from the state history, whoever writes it and whenever (ADR 0032).
    /// Anyone may call it after A while no checkpoint of a later block exists.
    function checkpointAt(uint32 profileId, uint24 epoch) external onlyDelegateCall returns (uint64 version) {
        if (!_batched(profileId)) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint64 a = _anchorDeadline(profile, epoch);
        if (block.number <= a) revert DeadlineNotReached();
        uint64 latest = latestCheckpointVersion[profileId];
        uint64 latestBlock = verifierCheckpoints[profileId][latest].checkpointBlock;
        if (latest != 0 && latestBlock == a) return latest;
        if (latest != 0 && latestBlock > a) revert InvalidTransition();
        (uint32[] memory ids, uint96[] memory weights, uint256 total) = _stateSet(profile, a);
        version = latest + 1;
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[profileId][version];
        checkpoint.version = version;
        checkpoint.checkpointBlock = a;
        checkpoint.verifierIds = ids;
        checkpoint.weights = weights;
        checkpoint.totalEffectiveWeight = total;
        checkpoint.setHash = keccak256(abi.encode(VERIFIER_SET_DOMAIN, profileId, version, ids, weights));
        latestCheckpointVersion[profileId] = version;
        emit VerifierTreeCheckpointed(profileId, version, checkpoint.setHash, total);
    }

    /// Records, once, the number of verifiers eligible by state at the block
    /// before epoch `epoch` opens, for a side-gain profile; a settlement of
    /// the epoch needs it at minVerifiers at least (ADR 0035).
    function recordEpochOpenCount(uint32 profileId, uint24 epoch) external onlyDelegateCall returns (uint32 count) {
        BatchStore.Layout storage l = BatchStore.layout();
        if (l.terms[profileId].sideGainPpm == 0) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint64 start = _epochStart(profile, epoch);
        if (start == 0 || block.number < start) revert DeadlineNotReached();
        if (l.epochOpenCount[profileId][epoch] != 0) return l.epochOpenCount[profileId][epoch];
        (uint32[] memory ids,,) = _stateSet(profile, start - 1);
        count = uint32(ids.length);
        l.epochOpenCount[profileId][epoch] = count;
        emit EpochOpenCountRecorded(profileId, epoch, count);
    }

    /// Verifiers eligible by state at the end of block x, with their weights.
    function _stateSet(ServiceProfileInput storage profile, uint256 x)
        private
        view
        returns (uint32[] memory ids, uint96[] memory weights, uint256 total)
    {
        uint256 n = nextVerifierId;
        uint32[] memory tmpIds = new uint32[](n);
        uint96[] memory tmpWeights = new uint96[](n);
        uint256 count;
        for (uint32 id = 1; id < n; id++) {
            (uint96 bond, uint8 status, uint64 classes) = _stateAt(id, x);
            VerifierView storage v = verifiers[id];
            if (
                status != uint8(VerifierStatus.ACTIVE) || v.owner == address(0) || v.signingKey == address(0)
                    || bond < profile.minVerifierBond || (classes & (uint64(1) << profile.classId)) == 0
            ) continue;
            uint96 w = bond < profile.verifierBondCap ? bond : uint96(profile.verifierBondCap);
            tmpIds[count] = id;
            tmpWeights[count] = w;
            total += w;
            count++;
        }
        ids = new uint32[](count);
        weights = new uint96[](count);
        for (uint256 i; i < count; i++) {
            ids[i] = tmpIds[i];
            weights[i] = tmpWeights[i];
        }
    }


    /// Keeper call: asks for the batch value of epoch `epoch`, input
    /// (profileId, epoch), from the block after the batch closes. A repeated
    /// call asks again with the same input.
    function requestAssignValue(uint32 profileId, uint24 epoch) external onlyDelegateCall {
        if (!_batched(profileId)) revert InvalidTransition();
        if (block.number <= _batchClose(profiles[profileId].parameters, epoch)) revert RequestTooEarly();
        _vrf().request(VRF_ASSIGN, abi.encode(profileId, epoch), 0);
    }

    /// Keeper call: the batch value is still missing past C_e + assignDelay.
    /// Every sample case of the batch counts as paused from the block after
    /// C_e + assignDelay until the batch is assigned or exits (ADR 0032,
    /// ADR 0036).
    function markAssignLate(uint32 profileId, uint24 epoch) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Terms storage t = l.terms[profileId];
        if (!t.batched) revert InvalidTransition();
        BatchStore.Batch storage b = l.batches[profileId][epoch];
        if (b.assigned || b.exited || b.lateMarked) revert InvalidTransition();
        uint256 due = _batchClose(profiles[profileId].parameters, epoch) + t.assignDelay;
        if (block.number <= due) revert DeadlineNotReached();
        (bool ready,) = _vrf().valueOf(_assignId(profileId, epoch));
        if (ready) revert InvalidTransition();
        b.lateMarked = true;
        uint256 n = b.cases.length;
        for (uint256 i; i < n; i++) {
            bytes32 caseId = b.cases[i];
            BatchStore.Entry storage en = l.entries[caseId];
            if (en.kind != KIND_PURCHASE || en.paused || !_waitsForBatch(caseId)
                || cases[caseId].trigger != uint8(CaseTrigger.SAMPLE)) continue;
            en.paused = true;
            _pauseFrom(_bondOf(caseId), _lateStart(due));
        }
        emit BatchValueLate(profileId, epoch);
    }

    /// The exit of an unanswered batch value: when the value is not stored by
    /// the first request block + D_V + T_V, anyone may end the batch's
    /// waiting cases from the next block. A sample case ends without a
    /// verdict, its account suspended and frozen from the case's sale with
    /// its claim window opened, nothing counted or deducted. A dispute ends
    /// as a progress failure. A seller proof ends without a verdict.
    function timeoutAssignValue(uint32 profileId, uint24 epoch) external onlyDelegateCall nonReentrant {
        if (!_batched(profileId)) revert InvalidTransition();
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Batch storage b = l.batches[profileId][epoch];
        if (b.assigned || b.exited) revert InvalidTransition();
        IVrfRandomness vrf = _vrf();
        (uint64 requested, uint64 delivered,) = vrf.requestTimes(_assignId(profileId, epoch));
        if (requested == 0 || delivered != 0) revert InvalidTransition();
        if (!_exitOpen(vrf, requested)) revert DeadlineNotReached();
        b.exited = true;
        uint256 due = _batchClose(profiles[profileId].parameters, epoch) + l.terms[profileId].assignDelay;
        uint256 n = b.cases.length;
        for (uint256 i; i < n; i++) {
            bytes32 caseId = b.cases[i];
            if (!_waitsForBatch(caseId)) continue;
            BatchStore.Entry storage en = l.entries[caseId];
            _valueArrived(en, due, block.number);
            if (en.kind == KIND_PROOF) {
                _hook(HOOK_PROOF_EXIT, uint256(en.ref));
            } else if (cases[caseId].trigger == uint8(CaseTrigger.SAMPLE)) {
                _valueExit(caseId);
            } else {
                _protocolInconclusive(caseId);
            }
        }
        emit BatchValueTimedOut(profileId, epoch);
    }

    // ------------------------------------------------- late first assignment

    /// Keeper call: asks, from the block after its opening, for the AUX value
    /// of a sample case opened after its batch closed. Input (late use,
    /// nonce, initial stage, 0, opening block).
    function requestLateValue(bytes32 nonce) external onlyDelegateCall {
        BatchStore.Entry storage en = BatchStore.layout().entries[nonce];
        if (!en.late || cases[nonce].state != uint8(CaseState.BATCHED)) revert NotRegistered();
        if (block.number <= en.lateBlock) revert RequestTooEarly();
        _vrf().request(VRF_AUX, _lateInput(nonce, en.lateBlock), 0);
    }

    /// The exit of an unanswered late value, as for the batch value.
    function timeoutLateValue(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Entry storage en = BatchStore.layout().entries[nonce];
        if (!en.late || cases[nonce].state != uint8(CaseState.BATCHED)) revert NotRegistered();
        IVrfRandomness vrf = _vrf();
        (uint64 requested, uint64 delivered,) = vrf.requestTimes(keccak256(abi.encode(VRF_AUX, _lateInput(nonce, en.lateBlock))));
        if (requested == 0 || delivered != 0) revert InvalidTransition();
        if (!_exitOpen(vrf, requested)) revert DeadlineNotReached();
        _valueArrived(en, uint256(en.lateBlock) + vrf.delayBlocks(), block.number);
        _valueExit(nonce);
        emit LateValueTimedOut(nonce);
    }

    /// Hook operation of this module: the progress failure of a case whose
    /// draws are used up.
    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op == HOOK_PROGRESS) _protocolInconclusive(bytes32(arg));
        else _unknownHook();
    }

    function hookOps() external pure returns (uint256) {
        return 1 << HOOK_PROGRESS;
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](8);
        s[0] = this.setBatchTerms.selector;
        s[1] = this.checkpointAt.selector;
        s[2] = this.recordEpochOpenCount.selector;
        s[3] = this.requestAssignValue.selector;
        s[4] = this.markAssignLate.selector;
        s[5] = this.timeoutAssignValue.selector;
        s[6] = this.requestLateValue.selector;
        s[7] = this.timeoutLateValue.selector;
    }
}
