// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { D2CheckBase } from "./review/D2ContractCheck.t.sol";

interface SnapshotVm {
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// Shared driving of the ADR 0025 tests on the base profile with every
/// purchase sampled and no automatic recheck.
abstract contract Impl1bBase is D2CheckBase {
    SnapshotVm internal constant sv = SnapshotVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant BEACON = keccak256("beacon");
    uint256 internal constant VERIFIER_WEIGHT = 10_000_000;
    uint256 internal constant VERIFIERS = 14;

    function _sampledProfile(uint32 bucketCapacity) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.bucketCapacity = bucketCapacity;
    }

    /// Round-r candidate of the checkpoint table for a case: the verifier the
    /// ticket of (randomness, nonce, stage, attempt, round) falls on, with the
    /// fourteen equal weights of ReproBase._deploy.
    function _candidate(bytes32 randomness, bytes32 n, uint8 stage, uint8 attempt, uint32 round)
        internal
        pure
        returns (uint32)
    {
        uint256 ticket = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), randomness, n, stage, attempt, round)))
            % (VERIFIERS * VERIFIER_WEIGHT);
        return uint32(ticket / VERIFIER_WEIGHT) + 1;
    }

    function _firstCandidate(bytes32 n) internal pure returns (uint32) {
        return _candidate(BEACON, n, uint8(FairBindCore.JudgmentStage.INITIAL), 0, 0);
    }

    /// Room the effective-bond rule leaves the verifier now for one more case
    /// of the given value (profile-v1 section 5), as the old assignment rule
    /// read it at case opening.
    function _roomNow(uint32 id, uint256 value) internal view returns (bool) {
        FairBindCore.VerifierView memory v = fairbind.getVerifier(id);
        FairBindCore.VerifierCapital memory c = fairbind.getVerifierCapital(id);
        FairBindCore.ServiceProfileInput memory p = fairbind.getServiceProfile(PROFILE).parameters;
        uint256 reserve = p.verifierLatePenalty > p.verifierWrongPenalty ? p.verifierLatePenalty : p.verifierWrongPenalty;
        uint256 all = c.reservedPenalties + reserve;
        if (v.bond < all) return false;
        uint256 cap = v.lockedLiability == 0 ? p.verifierBondCap : (c.conservativeCap < p.verifierBondCap ? c.conservativeCap : p.verifierBondCap);
        uint32 fraction = v.lockedLiability == 0 || p.verifierExposurePpm < c.conservativeFraction ? p.verifierExposurePpm : c.conservativeFraction;
        uint256 bond = v.bond - all < cap ? v.bond - all : cap;
        return v.lockedLiability + value + p.maxReviewCost <= bond * fraction / 1_000_000;
    }
}

/// Decision 126: a verifier's eligibility is its state at the checkpoint block
/// of the epoch, not at case opening (ADR 0025).
contract CheckpointEligibilityTest is Impl1bBase {
    /// The targeted-decoy attack of the lemma A review (2-1): once the epoch
    /// value is known, the seller opens first the honest sample cases whose
    /// first candidate is the verifier its fraudulent sale would draw, until
    /// that verifier has no room left. The fraudulent case still goes to that
    /// verifier, the first candidate of the checkpoint table; under the rule of
    /// 573647b it went to the next round's candidate.
    function test_targetedDecoysDoNotMoveTheFirstAssignment() public {
        _deploy(_sampledProfile(200));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](160);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        bytes32 fraud = ns[0];
        uint32 target = _firstCandidate(fraud);
        uint32 next = _candidate(BEACON, fraud, uint8(FairBindCore.JudgmentStage.INITIAL), 0, 1);
        require(next != target, "fixture: a different second candidate");
        uint256 decoys;
        for (uint256 i = 1; i < ns.length && _roomNow(target, G); i++) {
            if (_firstCandidate(ns[i]) != target) continue;
            fairbind.openSample(ns[i]);
            require(fairbind.getCase(ns[i]).assignedVerifierId == target, "decoy on the target");
            decoys++;
        }
        require(!_roomNow(target, G), "fixture: the target is full now");
        _log("decoys opened on the target", decoys);
        fairbind.openSample(fraud);
        require(fairbind.getCase(fraud).assignedVerifierId == target, "first assignment follows the checkpoint table");
        require(fairbind.getVerifier(target).lockedLiability == (decoys + 1) * (G + 1_000_000), "liability over the current limit");
    }

    /// The full verifier assigned on checkpoint room that does not answer is
    /// replaced by the next candidate through the existing judgment timeout,
    /// inside maxAssignments.
    function test_aFullVerifierThatDoesNotAnswerIsReplacedByTheNextCandidate() public {
        _deploy(_sampledProfile(200));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](160);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        bytes32 fraud = ns[0];
        uint32 target = _firstCandidate(fraud);
        for (uint256 i = 1; i < ns.length && _roomNow(target, G); i++) {
            if (_firstCandidate(ns[i]) == target) fairbind.openSample(ns[i]);
        }
        fairbind.openSample(fraud);
        uint256 bond = fairbind.getVerifier(target).bond;
        hv.roll(uint256(fairbind.getCase(fraud).judgeDue) + 1);
        fairbind.timeoutJudge(fraud);
        FairBindCore.CaseView memory c = fairbind.getCase(fraud);
        require(c.attempt == 1 && c.assignedVerifierId != target && c.assignedVerifierId != 0, "next candidate");
        require(fairbind.getVerifier(target).bond == bond - 500_000, "late penalty");
    }

    /// Room is read from the checkpoint snapshot: a verifier whose room at the
    /// checkpoint block is below the case liability is skipped although it is
    /// empty when the case opens.
    function test_roomIsTheCheckpointSnapshot() public {
        _deploy(_sampledProfile(200));
        uint64 version = 1;
        uint96[] memory room = fairbind.getCheckpointHeadroom(PROFILE, version);
        require(room.length == VERIFIERS, "one entry per verifier");
        // bond 10, reserve 1, fraction 0.5: (10 - 1) * 0.5 = 4.5 USDC.
        for (uint256 i; i < room.length; i++) require(room[i] == 4_500_000, "room at the checkpoint");
    }

    /// The residual path ADR 0025 records: liability the seller locks before
    /// the checkpoint block is part of the snapshot. A verifier full at the
    /// checkpoint is skipped for every case of the epochs that use it.
    function test_liabilityLockedBeforeTheCheckpointIsPartOfTheSnapshot() public {
        _deploy(_sampledProfile(200));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](160);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        uint32 target = _firstCandidate(ns[0]);
        for (uint256 i = 1; i < ns.length && _roomNow(target, G); i++) {
            if (_firstCandidate(ns[i]) == target) fairbind.openSample(ns[i]);
        }
        uint64 version = fairbind.checkpointVerifierTree(PROFILE);
        require(version == 2, "new version for new room");
        uint96[] memory room = fairbind.getCheckpointHeadroom(PROFILE, version);
        require(room[target - 1] < G + 1_000_000, "full at the new checkpoint");
    }

    /// The epoch takes the latest checkpoint at or before its anchor deadline,
    /// found by binary search over the versions.
    function test_sealTakesTheLatestCheckpointBeforeTheAnchorDeadline() public {
        _deploy(_sampledProfile(200));
        hv.roll(10);
        bytes32 n = _purchase(G);
        // Versions 2 to 6, one per changed room, all before the deadline (700).
        for (uint256 i; i < 5; i++) {
            hv.roll(20 + i);
            fairbind.topUpVerifierBond(uint32(1 + i), 1_000_000);
            require(fairbind.checkpointVerifierTree(PROFILE) == 2 + i, "version");
        }
        // Versions 7 and 8 after the deadline.
        hv.roll(701);
        fairbind.topUpVerifierBond(7, 1_000_000);
        fairbind.checkpointVerifierTree(PROFILE);
        fairbind.topUpVerifierBond(8, 1_000_000);
        require(fairbind.checkpointVerifierTree(PROFILE) == 8, "two late versions");
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, BEACON);
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).sortitionVersion == 6, "latest at or before the deadline");
    }
}

/// Rule D2-16 (e): reopening a lapsed review seal keeps randomBlock and every
/// assignment input (ADR 0025).
contract ReviewResealTest is Impl1bBase {
    bytes32 internal constant REVIEW_HASH = keccak256("review hash");

    function _appealed() internal returns (bytes32 n, uint64 rb) {
        _deploy(_sampledProfile(20));
        hv.roll(10);
        n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, BEACON);
        fairbind.openSample(n);
        _judge(n, uint8(FairBindCore.Verdict.FAIL));
        token.mint(SELLER_OWNER, DEPOSIT);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        rb = fairbind.getCase(n).randomBlock;
    }

    /// Sealing in the first window and sealing in the reopened window after the
    /// first lapsed draw the same review verifier from the same randomBlock.
    function test_reopenedSealDrawsTheSameVerifierFromTheSameRandomBlock() public {
        (bytes32 n, uint64 rb) = _appealed();
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, REVIEW_HASH);
        uint256 snap = sv.snapshotState();
        fairbind.sealReviewRandomness(n);
        uint32 direct = fairbind.getCase(n).assignedVerifierId;
        require(direct != 0, "assigned in the first window");
        sv.revertToState(snap);
        hv.roll(uint256(rb) + 201);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.randomBlock == rb, "randomBlock unchanged");
        require(c.randomness == REVIEW_HASH, "hash recorded at the reopening");
        require(fairbind.getReviewResealDue(n) == uint64(rb) + 201 + 1 + 200, "reopened window");
        // The reopened window still rejects an early finalizeCase.
        hv.roll(uint256(rb) + 402);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.finalizeCase(n);
        fairbind.sealReviewRandomness(n);
        c = fairbind.getCase(n);
        require(c.assignedVerifierId == direct && c.stage == uint8(FairBindCore.JudgmentStage.PARTY) && c.attempt == 0,
            "same inputs, same verifier");
    }

    /// When nobody reads the hash before the chain stops serving it, the
    /// reopened window could never seal: the stage ends at once as a progress
    /// failure, here a seller-appealed review that upholds the initial FAIL.
    function test_aHashGoneBeforeTheReopeningEndsTheStage() public {
        (bytes32 n, uint64 rb) = _appealed();
        hv.roll(uint256(rb) + 257);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.FINAL) && c.finalVerdict == uint8(FairBindCore.Verdict.FAIL),
            "upheld FAIL");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).failureCount == 1, "counted");
    }

    /// After the reopened window passes without a seal the stage ends as before.
    function test_theReopenedWindowEndsTheStageWhenItPasses() public {
        (bytes32 n, uint64 rb) = _appealed();
        hv.roll(uint256(rb) + 201);
        hv.setBlockhash(rb, REVIEW_HASH);
        fairbind.finalizeCase(n);
        hv.roll(uint256(fairbind.getReviewResealDue(n)) + 1);
        fairbind.finalizeCase(n);
        require(fairbind.getCase(n).finalVerdict == uint8(FairBindCore.Verdict.FAIL), "upheld FAIL");
    }
}

/// Review 2-1 and 2-2: design 2 terms are fixed only on a profile that has
/// never been active, against a commitment the profile document carries
/// (ADR 0025).
contract ProfileTermsCommitmentTest is Impl1bBase {
    /// termsHash of the data API and inference documents in
    /// profiles/design2-v1.json (scripts/check_spec.py recomputes both).
    bytes32 internal constant DATA_API_TERMS_HASH = 0xea1312d0d44e952a3d56b0476e3dc95e1ab5f91e7f0cddf7647e0730369faeb8;
    bytes32 internal constant INFERENCE_TERMS_HASH = 0x600c5a36c2341868bbaa26f551cf4ce8a3465d53ea3c824dfbf7e4e961cca2d0;

    function _inferenceTiers() internal pure returns (FairBindCore.SalesTier[] memory t) {
        t = new FairBindCore.SalesTier[](6);
        t[0] = FairBindCore.SalesTier(10, 1, 48, 5, 5);
        t[1] = FairBindCore.SalesTier(30, 1, 156, 7, 7);
        t[2] = FairBindCore.SalesTier(100, 4, 518, 11, 11);
        t[3] = FairBindCore.SalesTier(300, 13, 1_549, 19, 19);
        t[4] = FairBindCore.SalesTier(1_000, 42, 5_173, 38, 38);
        t[5] = FairBindCore.SalesTier(3_245, 137, 16_785, 87, 87);
    }

    function test_termsHashMatchesTheProfileDocuments() public pure {
        require(_termsHash(P0, _caps(), _tiers()) == DATA_API_TERMS_HASH, "data API");
        require(_termsHash(P0, _caps(), _inferenceTiers()) == INFERENCE_TERMS_HASH, "inference");
    }

    /// Both documents of profiles/design2-v1.json pass profile admission and
    /// the terms checks with their committed terms.
    function test_profileDocumentsAreAdmitted() public {
        _deployD2(_profileD2(), false);
        FairBindCore.ServiceProfileInput memory p = _profileD2();
        p.recheckPpm = 200_000;
        fairbind.createServiceProfile(PROFILE + 1, p);
        fairbind.setProfileTerms(PROFILE + 1, DATA_API_TERMS_HASH, P0, _caps(), _tiers());
        fairbind.createDeadlineConfig(2, FairBindCore.DeadlineConfig(100, 200, 200, 1800, 3600, 300, 3600, 1800, 1800));
        p.deadlineConfigId = 2;
        p.epochBlocks = 1800;
        p.refillPpmPerBlock = 16_785;
        p.enforcementBlocks = 92_581;
        p.deferBlocks = 92_581;
        p.retentionBlocks = 92_581;
        p.claimWindowBlocks = 92_581;
        p.failureWindowBlocks = 92_581;
        p.inconclusiveWindowBlocks = 92_581;
        p.maxPublicationCost = 20_000_000;
        p.maxReviewCost = 10_000_000;
        p.minVerifierBond = 50_000_000;
        p.verifierLatePenalty = 5_000_000;
        p.verifierWrongPenalty = 10_000_000;
        p.disputeDeposit = 20_000_000;
        p.appealDeposit = 20_000_000;
        fairbind.createServiceProfile(PROFILE + 2, p);
        require(fairbind.judgmentDelayBlocks(PROFILE + 2) == 92_081, "inference L_F");
        fairbind.setProfileTerms(PROFILE + 2, INFERENCE_TERMS_HASH, P0, _caps(), _inferenceTiers());
    }

    function test_termsMustReproduceTheirCommitment() public {
        _deployD2(_profileD2(), false);
        fairbind.setServiceProfileActive(PROFILE, false);
        // A fresh profile that was never active.
        fairbind.createServiceProfile(PROFILE + 1, _profileD2());
        FairBindCore.SalesTier[] memory t = _tiers();
        bytes32 committed = _termsHash(P0, _caps(), t);
        t[0].failureLimit = 6;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.setProfileTerms(PROFILE + 1, committed, P0, _caps(), t);
        fairbind.setProfileTerms(PROFILE + 1, committed, P0, _caps(), _tiers());
        require(fairbind.getProfileTerms(PROFILE + 1).termsHash == committed, "stored");
    }

    /// Rule D2-9: under terms both windows equal retentionBlocks.
    function test_termsNeedBothWindowsAtTheHoldPeriod() public {
        _deployD2(_profileD2(), false);
        FairBindCore.ServiceProfileInput memory p = _profileD2();
        p.inconclusiveWindowBlocks = 31_072;
        fairbind.createServiceProfile(PROFILE + 1, p);
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE + 1, P0, _caps(), _tiers());
        p = _profileD2();
        p.failureWindowBlocks = 31_074;
        fairbind.createServiceProfile(PROFILE + 2, p);
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE + 2, P0, _caps(), _tiers());
    }
}
