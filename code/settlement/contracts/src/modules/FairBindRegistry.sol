// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";
import { FairBindDesign2 } from "../FairBindDesign2.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { Rule8Store } from "./Rule8Store.sol";

interface IExtensionModule {
    function deploymentToken() external view returns (address);
    function penaltyTreasury() external view returns (address);
    function verifierRewardPool() external view returns (address);
    function MODULE_KIND() external view returns (uint8);
    function selectors() external pure returns (bytes4[] memory);
    function hookOps() external pure returns (uint256);
}

contract FairBindRegistry is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 1;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    event RandomnessSourceSet(address indexed source, uint64 since);

    /// Sets the randomness source of the per-epoch sampling value (journal J2).
    /// Governance only, once. It applies to epochs anchored from the next block
    /// on; an epoch anchored earlier keeps the block hash path, so no anchored
    /// epoch changes its source. Until it is set the block hash path of the
    /// prototype runs unchanged. A source that answers responseBlocks() is
    /// request based (IVrfRandomness, ADR 0031).
    function setRandomness(address source) external onlyDelegateCall {
        if (msg.sender != governance) revert Unauthorized();
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        if (cfg.source != address(0)) revert InvalidTransition();
        if (source.code.length == 0) revert InvalidConfiguration();
        (bool ok, bytes memory ret) = source.staticcall(abi.encodeCall(IVrfRandomness.responseBlocks, ()));
        cfg.source = source;
        cfg.since = uint64(block.number + 1);
        cfg.vrf = ok && ret.length == 32;
        emit RandomnessSourceSet(source, cfg.since);
    }

    event ExtensionsSet(address[] modules);

    /// Installs the extension modules of the router (ADR 0032). Governance
    /// only, once. Module i must report kind 11 + i and the deployment's
    /// token, treasury and reward pool. The router runs each selector a module
    /// declares in that module, and each hook operation in the module whose
    /// bitmask names it; no selector or operation may be declared twice.
    function setExtensions(address[] calldata list) external onlyDelegateCall {
        if (msg.sender != governance) revert Unauthorized();
        BatchStore.Layout storage l = BatchStore.layout();
        if (l.exts.length != 0 || list.length == 0) revert InvalidTransition();
        for (uint256 i; i < list.length; i++) {
            if (list[i].code.length == 0) revert InvalidConfiguration();
            IExtensionModule m = IExtensionModule(list[i]);
            if (m.deploymentToken() != deploymentToken || m.penaltyTreasury() != penaltyTreasury
                || m.verifierRewardPool() != verifierRewardPool || m.MODULE_KIND() != 11 + i) revert InvalidConfiguration();
            l.exts.push(list[i]);
            bytes4[] memory sels = m.selectors();
            for (uint256 j; j < sels.length; j++) {
                if (l.route[sels[j]] != address(0)) revert InvalidConfiguration();
                l.route[sels[j]] = list[i];
            }
            uint256 ops = m.hookOps();
            for (uint256 op; op < 256; op++) {
                if ((ops >> op) & 1 == 0) continue;
                if (l.hookExt[op] != address(0)) revert InvalidConfiguration();
                l.hookExt[op] = list[i];
            }
        }
        emit ExtensionsSet(list);
    }

    function createDeadlineConfig(uint32 id, DeadlineConfig calldata config)
        external
        onlyDelegateCall
        onlyGovernance
    {
        if (id == 0) revert InvalidConfiguration();
        if (deadlineConfigExists[id]) revert ObjectAlreadyExists();
        if (
            config.anchorBlocks == 0 || config.sealBlocks == 0 || config.sealBlocks > 255
                || config.openBlocks == 0 || config.responseBlocks == 0 || config.claimBlocks == 0
                || config.serveBlocks == 0 || config.judgeBlocks == 0 || config.evidenceBlocks == 0
                || config.appealBlocks == 0
        ) revert InvalidConfiguration();
        deadlineConfigs[id] = config;
        deadlineConfigExists[id] = true;
        emit DeadlineConfigCreated(id, keccak256(abi.encode(config)));
    }

    function createServiceProfile(uint32 id, ServiceProfileInput calldata input)
        external
        onlyDelegateCall
        onlyGovernance
    {
        if (id == 0) revert InvalidProfile();
        if (profiles[id].profileId != 0) revert ObjectAlreadyExists();
        _validateProfile(input);
        profiles[id] = ServiceProfileView(id, false, deploymentToken, input);
        emit ServiceProfileCreated(
            id, input.classId, input.predicateId, input.canonId, input.parameterHash
        );
    }

    /// Fixes the design 2 terms of a profile that has never been active, once
    /// (ADR 0024, ADR 0025): the detection floor p0, the value caps a seller
    /// may choose, and the sales tiers. termsHash is their commitment, the
    /// value the profile document carries inside the parameters that
    /// parameterHash commits; the call reverts unless the terms reproduce it.
    /// The profile samples every purchase at the cap (samplePpm = PPM), its
    /// effectivePpm is p0, its maxPurchaseValue is the largest cap and is
    /// at least maxBadGain, and its bucket and failure limit are those of the
    /// last (base) tier, whose sellerPenalty / failureLimit covers b of the
    /// largest cap. Each tier admits at most salesLimit settlements in any
    /// interval of failureWindowBlocks plus the case horizon. Both windows
    /// equal retentionBlocks (rule D2-9).
    function setProfileTerms(
        uint32 profileId,
        bytes32 termsHash,
        uint32 detectFloorPpm,
        uint96[] calldata valueCaps,
        SalesTier[] calldata tiers
    ) external onlyDelegateCall onlyGovernance {
        ServiceProfileView storage profile = profiles[profileId];
        if (profile.profileId == 0) revert UnknownProfile();
        ProfileTerms storage pt = profileTerms[profileId];
        // A profile that was ever active may hold accounts opened without terms.
        if (profile.active || profileActivated[profileId] || pt.tiers.length != 0) revert InvalidTransition();
        if (termsHash != _termsHash(detectFloorPpm, valueCaps, tiers)) revert InvalidProfile();
        ServiceProfileInput storage p = profile.parameters;
        uint256 caps = valueCaps.length;
        uint256 count = tiers.length;
        if (
            detectFloorPpm == 0 || detectFloorPpm != p.effectivePpm || p.samplePpm != PPM || caps == 0
                || count == 0 || count > 32 || valueCaps[caps - 1] != p.maxPurchaseValue
                || p.maxBadGain > p.maxPurchaseValue || p.failureWindowBlocks != p.retentionBlocks
                || p.inconclusiveWindowBlocks != p.retentionBlocks
        ) revert InvalidProfile();
        SalesTier calldata base = tiers[count - 1];
        if (
            base.bucketCapacity != p.bucketCapacity || base.refillPpmPerBlock != p.refillPpmPerBlock
                || base.failureLimit != p.failureLimit
                || p.sellerPenalty / p.failureLimit < FairBindDesign2.deduction(p.maxPurchaseValue, detectFloorPpm)
        ) revert InvalidProfile();
        uint256 previous;
        for (uint256 i; i < caps; i++) {
            if (valueCaps[i] <= previous) revert InvalidProfile();
            previous = valueCaps[i];
        }
        uint256 span = uint256(p.failureWindowBlocks) + p.marginBlocks
            + _judgmentDelay(p.epochBlocks, p.beaconDelayBlocks, p.maxAssignments, deadlineConfigs[p.deadlineConfigId]);
        previous = 0;
        for (uint256 i; i < count; i++) {
            SalesTier calldata t = tiers[i];
            if (
                t.salesLimit <= previous || t.bucketCapacity == 0 || t.failureLimit == 0
                    || t.refillPpmPerBlock > p.maxRatePpmPerBlock
                    || uint256(t.bucketCapacity) * PPM + uint256(t.refillPpmPerBlock) * span > uint256(t.salesLimit) * PPM
            ) revert InvalidProfile();
            previous = t.salesLimit;
            pt.tiers.push(t);
        }
        pt.detectFloorPpm = detectFloorPpm;
        pt.valueCaps = valueCaps;
        pt.termsHash = termsHash;
        emit ProfileTermsSet(profileId, termsHash, detectFloorPpm, valueCaps, tiers);
    }

    function setServiceProfileActive(uint32 id, bool active)
        external
        onlyDelegateCall
        onlyGovernance
    {
        ServiceProfileView storage profile = profiles[id];
        if (profile.profileId == 0) revert UnknownProfile();
        if (active && newSettlementsPaused) revert Paused();
        if (active) {
            _exchangeActivation(id);
            if (BatchStore.layout().terms[id].batched && !_batchHorizonHolds(profile.parameters, id)) {
                revert InvalidProfile();
            }
        }
        profile.active = active;
        if (active) profileActivated[id] = true;
        emit ServiceProfileActivationChanged(id, active);
    }

    /// Activation of a profile with exchange terms needs the L1 fee bound
    /// of its measured costs to answer (rule D2-13, D2-33 (e') 1) and
    /// admission check (7) to hold under the randomness source in force;
    /// once the deployment requires exchange terms, a profile without them
    /// does not activate (rule 8.2 row 23).
    function _exchangeActivation(uint32 id) private view {
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        ExchangeStore.Terms storage t = x.terms[id];
        if (t.termsHash == 0) {
            if (x.termsRequired) revert InvalidProfile();
            return;
        }
        (bool ok,) = _l1Bound(t.bEnv);
        ServiceProfileInput storage p = profiles[id].parameters;
        if (!ok || !_bindOpenFits(p, t) || !_bindWindowInRange(p, t, _caseLength(id, p, t.mode))) {
            revert InvalidProfile();
        }
    }

    /// The longest path L_F from a settlement to the end of a sample case that
    /// stops the account, in unpaused blocks with no keeper delay (rule D2-8
    /// (a), the path enumeration 2.6). O_s = 2 * epochBlocks + anchorBlocks + D +
    /// sealBlocks + openBlocks, D the value delay (D_S of the request-based
    /// source in force, else beaconDelayBlocks). A proof profile: O_s + T_p +
    /// 1. A batched vote profile: max(O_s + assignDelay, min(O_s, O_d) +
    /// 3 * serveBlocks + eps + D) + core_0 + 2 * D + (2 * sealBlocks + 3),
    /// with O_d = responseBlocks + claimBlocks, eps = 1 under receipt
    /// signatures (a sample case still opens after the refund of a lapsed
    /// disclosure) and core_0 the stages of the case without review seals.
    /// Any other profile: the profile check's judgment delay.
    function _caseLength(uint32 id, ServiceProfileInput storage p, uint8 mode) internal view returns (uint256) {
        DeadlineConfig storage d = deadlineConfigs[p.deadlineConfigId];
        BatchStore.Terms storage b = BatchStore.layout().terms[id];
        if (mode != ExchangeStore.MODE_PROOF && !b.batched) {
            return _judgmentDelay(p.epochBlocks, p.beaconDelayBlocks, p.maxAssignments, d);
        }
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        uint256 ds = cfg.vrf ? uint256(IVrfRandomness(cfg.source).delayBlocks()) : p.beaconDelayBlocks;
        uint256 os = 2 * uint256(p.epochBlocks) + d.anchorBlocks + ds + d.sealBlocks + d.openBlocks;
        if (mode == ExchangeStore.MODE_PROOF) return os + ExchangeStore.layout().terms[id].proofBlocks + 1;
        uint256 od = uint256(d.responseBlocks) + d.claimBlocks;
        uint256 start = (os < od ? os : od) + 3 * uint256(d.serveBlocks) + ds
            + (mode == ExchangeStore.MODE_VOTE_SIG ? 1 : 0);
        if (os + b.assignDelay > start) start = os + b.assignDelay;
        uint256 m = p.maxAssignments;
        return start + 3 * m * (2 * uint256(d.judgeBlocks) + 3 * uint256(d.serveBlocks))
            + m * (uint256(d.appealBlocks) + d.evidenceBlocks) + d.appealBlocks + 3 * (m - 1)
            + 2 * ds + 2 * uint256(d.sealBlocks) + 3;
    }

    /// A batched profile holds its entries for at least L_F + marginBlocks
    /// (rule D2-8 (a)); the profile check counted the judgment delay without
    /// the batch value waits. The per-call keeper delay keeperSlack of the
    /// n_kappa = 6 * maxAssignments + 4 keeper transitions of its longest
    /// path sums to at most marginBlocks - 1, and keeperSlack <= sealBlocks
    /// - 2 while sealBlocks <= 255, the block hash window of the review seal
    /// (rule D2-13 (c), the path enumeration). A mutation build of the tests
    /// overrides it.
    function _batchHorizonHolds(ServiceProfileInput storage p, uint32 id) internal view virtual returns (bool) {
        uint256 slack = BatchStore.layout().terms[id].keeperSlack;
        return p.retentionBlocks >= _caseLength(id, p, ExchangeStore.layout().terms[id].mode) + p.marginBlocks
            && (6 * uint256(p.maxAssignments) + 4) * slack + 1 <= p.marginBlocks
            && (deadlineConfigs[p.deadlineConfigId].sealBlocks > 255
                || slack + 2 <= deadlineConfigs[p.deadlineConfigId].sealBlocks);
    }

    /// F_max is the J3 bound of the stop, L_F + kappa_Sigma with kappa_Sigma
    /// <= marginBlocks - 1, and stays below the hold T_hold = retentionBlocks
    /// (rule D2-13 (c) 6, the path enumeration 4). A mutation build of the tests
    /// overrides it.
    function _bindWindowInRange(ServiceProfileInput storage p, ExchangeStore.Terms storage t, uint256 caseLength)
        internal
        view
        virtual
        returns (bool)
    {
        return uint256(t.bindWindow) + 1 >= caseLength + p.marginBlocks && t.bindWindow < p.retentionBlocks;
    }

    /// Admission check (7) of rule D2-13 (c): the raw blocks from the first
    /// block of an epoch through the last block in which a binding proof of
    /// its sales may still wait for the sampling value, plus the slack of the
    /// proof transaction, fit in F_max, so that the window the proof is taken
    /// in (rule D2-19 (h)) is never empty. The anchor deadline is A = epoch
    /// start + 2 * epochBlocks - 1 + anchorBlocks. Under a request-based
    /// source the wait ends at M = A + D_S + T_V; otherwise at the value block
    /// A + 1 + delay, bounded by beaconDelayBlocks. A mutation build of the
    /// tests overrides it.
    function _bindOpenFits(ServiceProfileInput storage p, ExchangeStore.Terms storage t)
        internal
        view
        virtual
        returns (bool)
    {
        uint256 blocks = 2 * uint256(p.epochBlocks) + deadlineConfigs[p.deadlineConfigId].anchorBlocks;
        SamplingStore.RandomnessConfig storage cfg = SamplingStore.layout().randomness;
        if (cfg.vrf) {
            IVrfRandomness v = IVrfRandomness(cfg.source);
            blocks += uint256(v.delayBlocks()) + v.deadlineSlackBlocks();
        } else {
            blocks += 1 + uint256(p.beaconDelayBlocks);
        }
        return blocks + t.bindSlack <= t.bindWindow;
    }

    function pauseNewSettlements(bool paused) external onlyDelegateCall {
        if (paused) {
            if (msg.sender != governance && msg.sender != guardian) revert Unauthorized();
        } else if (msg.sender != governance) {
            revert Unauthorized();
        }
        newSettlementsPaused = paused;
        emit NewSettlementsPaused(paused, msg.sender);
    }

    function nominateGovernance(address nominee, uint64 acceptAfter)
        external
        onlyDelegateCall
        onlyGovernance
    {
        if (nominee == address(0) || nominee == deploymentToken || nominee == guardian) {
            revert ZeroAddress();
        }
        if (acceptAfter < block.timestamp) revert InvalidConfiguration();
        governanceNominee = nominee;
        governanceAcceptAfter = acceptAfter;
        emit GovernanceNominated(governance, nominee, acceptAfter);
    }

    function acceptGovernance() external onlyDelegateCall {
        if (msg.sender != governanceNominee || block.timestamp < governanceAcceptAfter) {
            revert Unauthorized();
        }
        address previous = governance;
        governance = msg.sender;
        governanceNominee = address(0);
        governanceAcceptAfter = 0;
        emit GovernanceChanged(previous, msg.sender);
    }

    function nominateGuardian(address nominee) external onlyDelegateCall onlyGovernance {
        if (
            nominee == address(0) || nominee == deploymentToken || nominee == governance
                || nominee == penaltyTreasury
        ) revert ZeroAddress();
        guardianNominee = nominee;
        emit GuardianNominated(guardian, nominee);
    }

    function acceptGuardian() external onlyDelegateCall {
        if (msg.sender != guardianNominee) revert Unauthorized();
        address previous = guardian;
        guardian = msg.sender;
        guardianNominee = address(0);
        emit GuardianChanged(previous, msg.sender);
    }

    function registerVerifier(uint256 classBitmap, address signingKey, uint128 bondAmount)
        external
        onlyDelegateCall
        nonReentrant
        returns (uint32 verifierId)
    {
        if (newSettlementsPaused) revert Paused();
        if (classBitmap == 0 || signingKey == address(0)) revert InvalidConfiguration();
        if (bondAmount == 0) revert InsufficientVerifierBond();
        verifierId = nextVerifierId++;
        // A verifier registered while batched profiles exist had no state before.
        _noteVerifier(verifierId);
        verifiers[verifierId] = VerifierView(
            verifierId,
            msg.sender,
            signingKey,
            classBitmap,
            bondAmount,
            0,
            0,
            0,
            uint8(VerifierStatus.ACTIVE)
        );
        _transferFrom(msg.sender, bondAmount);
        emit VerifierRegistered(verifierId, msg.sender, signingKey, classBitmap, bondAmount);
    }

    function topUpVerifierBond(uint32 verifierId, uint128 amount)
        external
        onlyDelegateCall
        nonReentrant
    {
        VerifierView storage verifier = verifiers[verifierId];
        if (
            verifier.status == uint8(VerifierStatus.NONE)
                || verifier.status == uint8(VerifierStatus.EXITED)
        ) revert VerifierInactive();
        _noteVerifier(verifierId);
        verifier.bond += amount;
        _transferFrom(msg.sender, amount);
        emit VerifierBondChanged(verifierId, verifier.bond);
        // A larger bond may open a slot (ADR 0032).
        if (BatchStore.layout().historyOn) _hook(HOOK_START_HEADS, verifierId);
    }

    function setVerifierClasses(uint32 verifierId, uint256 classBitmap) external onlyDelegateCall {
        VerifierView storage verifier = verifiers[verifierId];
        if (msg.sender != verifier.owner) revert Unauthorized();
        if (verifier.status != uint8(VerifierStatus.ACTIVE) || classBitmap == 0) {
            revert VerifierInactive();
        }
        _noteVerifier(verifierId);
        verifier.classBitmap = classBitmap;
        emit VerifierClassesChanged(verifierId, classBitmap);
    }

    function requestVerifierExit(uint32 verifierId) external onlyDelegateCall {
        VerifierView storage verifier = verifiers[verifierId];
        if (msg.sender != verifier.owner) revert Unauthorized();
        if (verifier.status != uint8(VerifierStatus.ACTIVE)) revert VerifierInactive();
        _noteVerifier(verifierId);
        verifier.status = uint8(VerifierStatus.EXITING);
        // Cases whose candidate is fixed after this block leave the verifier (ADR 0032).
        BatchStore.Layout storage l = BatchStore.layout();
        if (l.historyOn && l.slots[verifierId].departed == 0) l.slots[verifierId].departed = uint64(block.number);
        uint64 earliest = uint64(block.number + 1);
        if (verifier.exitEligibleBlock < earliest) verifier.exitEligibleBlock = earliest;
        // Rule 8 ties the exit to the state of the profile epochs (rule D2-35 (d) 2).
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (r8.profileList.length != 0) r8.exitRequested[verifierId] = uint64(block.number);
        emit VerifierExitRequested(verifierId, verifier.exitEligibleBlock);
    }

    function finalizeVerifierExit(uint32 verifierId) external onlyDelegateCall nonReentrant {
        VerifierView storage verifier = verifiers[verifierId];
        if (msg.sender != verifier.owner) revert Unauthorized();
        if (
            (verifier.status != uint8(VerifierStatus.EXITING) && verifier.status != uint8(VerifierStatus.REMOVED))
                || block.number < verifier.exitEligibleBlock || verifier.lockedLiability != 0 || verifierCapital[verifierId].reservedPenalties != 0
                || BatchStore.layout().slots[verifierId].queued != 0
        ) revert ExitNotReady();
        // Rule 8 holds the exit by the state of the profile epochs (rule D2-35 (d) 2).
        if (Rule8Store.layout().profileList.length != 0) _hook(HOOK_R8_EXIT, verifierId);
        _noteVerifier(verifierId);
        uint256 amount = verifier.bond;
        verifier.bond = 0;
        verifier.status = uint8(VerifierStatus.EXITED);
        _transfer(verifier.owner, amount);
        emit VerifierExited(verifierId, verifier.owner, amount);
    }

    function checkpointVerifierTree(uint32 profileId)
        external
        onlyDelegateCall
        returns (uint64 version)
    {
        // Rule 8: the checkpoint of a profile epoch is a required call; its
        // fee is paid once per epoch (rule D2-38 (a)).
        if (_r8On(profileId)) _r8FeeOnce(profileId, Rule8Store.FEE_CHECKPOINT, _epoch(profiles[profileId].parameters));
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        if (profiles[profileId].profileId == 0) revert UnknownProfile();
        // A batched profile takes only checkpoints of fixed blocks (ADR 0032).
        if (_batched(profileId)) revert InvalidTransition();

        uint256 count;
        for (uint32 id = 1; id < nextVerifierId; id++) {
            if (_checkpointEligible(verifiers[id], profile)) count++;
        }
        uint32[] memory ids = new uint32[](count);
        uint96[] memory weights = new uint96[](count);
        // Each verifier's liability room at this block: assignment under this
        // checkpoint reads eligibility from it (decision 126, ADR 0025).
        uint96[] memory room = new uint96[](count);
        uint256 total;
        uint256 cursor;
        for (uint32 id = 1; id < nextVerifierId; id++) {
            VerifierView storage verifier = verifiers[id];
            if (!_checkpointEligible(verifier, profile)) continue;
            uint96 weight = uint96(
                verifier.bond < profile.verifierBondCap ? verifier.bond : profile.verifierBondCap
            );
            ids[cursor] = id;
            weights[cursor] = weight;
            room[cursor] = _liabilityRoom(id, profile);
            total += weight;
            cursor++;
        }

        uint64 latest = latestCheckpointVersion[profileId];
        if (latest != 0 && _sameCheckpoint(verifierCheckpoints[profileId][latest], ids, weights)
            && _sameRoom(checkpointHeadroom[profileId][latest], room)) {
            return latest;
        }
        version = latest + 1;
        bytes32 setHash =
            keccak256(abi.encode(VERIFIER_SET_DOMAIN, profileId, version, ids, weights));
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[profileId][version];
        checkpoint.version = version;
        checkpoint.checkpointBlock = uint64(block.number);
        checkpoint.verifierIds = ids;
        checkpoint.weights = weights;
        checkpoint.totalEffectiveWeight = total;
        checkpoint.setHash = setHash;
        checkpointHeadroom[profileId][version] = room;
        latestCheckpointVersion[profileId] = version;
        emit VerifierTreeCheckpointed(profileId, version, setHash, total);
        emit VerifierHeadroomCheckpointed(profileId, version, room);
    }

    function _sameRoom(uint96[] storage stored, uint96[] memory room) private view returns (bool) {
        if (stored.length != room.length) return false;
        for (uint256 i; i < room.length; i++) {
            if (stored[i] != room[i]) return false;
        }
        return true;
    }
}
