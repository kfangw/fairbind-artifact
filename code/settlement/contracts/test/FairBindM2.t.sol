// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import {FairBindCore} from "../src/FairBindCore.sol";
import {DeployFairBind} from "./DeployFairBind.sol";

import { FairBind } from "../src/FairBind.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

interface VmM2 {
    function prank(address caller) external;
    function roll(uint256 blockNumber) external;
    function setBlockhash(uint256 height, bytes32 hash) external;
    function expectRevert(bytes4 selector) external;
}

contract MerkleHarness {
    function verify(
        bytes32 root,
        bytes32 nonce,
        bytes32 leaf,
        uint32 index,
        uint32 count,
        bytes32[] memory siblings
    ) external pure returns (bool) {
        return FairBindMerkle.verify(root, nonce, leaf, index, count, siblings);
    }
}

contract FairBindM2Test is DeployFairBind {
    VmM2 private constant vm = VmM2(address(uint160(uint256(keccak256("hevm cheat code")))));
    MockEIP3009Token private token;
    FairBind private fairbind;
    uint32 private sellerId;
    bytes32 private constant CLAIMS = keccak256("claims");
    address private constant BUYER = address(0xB0B);

    function setUp() public {
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), address(0xCAFE));
        fairbind.createDeadlineConfig(
            1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600)
        );
        fairbind.createServiceProfile(3, _profile());
        token.mint(address(this), 1_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        _registerVerifiers(14);
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3, true);
        sellerId = registerSellerWithBond(fairbind, 3, address(0x515E), CLAIMS, 10_000_000);
        token.mint(BUYER, 100_000);
    }

    function testMerkleVectorAndOddDuplication() public {
        MerkleHarness harness = new MerkleHarness();
        bytes32[] memory siblings = new bytes32[](2);
        siblings[0] = 0x64ce93f4153134d24dbf6c330cfa72e9c632bbabdcbcaec00fd49fb5fe14d6a1;
        siblings[1] = 0x41633787219e7ebc73e866c9453e8e5d15dcc07828db7040acc4d8a3c7917df0;
        bool valid = harness.verify(
            0xb0e5ce6b84df6db5f7e3847d05560064b749bdc676f4ad8ff9338ca0a71bf28a,
            bytes32(uint256(0x30)),
            0x9e19446555a83d5e12578fee5fdc10a13e1d57272f8fd65730f16cd65fb03caf,
            1,
            3,
            siblings
        );
        require(valid, "proof");
    }

    function testCheckpointAnchorSealSampleAndAssign() public {
        uint64 version = fairbind.checkpointVerifierTree(3);
        (,, uint96[] memory weights, uint256 total,) = fairbind.getVerifierCheckpoint(3, version);
        require(weights.length == 14 && total == 140_000_000, "checkpoint");

        bytes32 nonce = _settle(bytes16(uint128(1)));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        (bool sampled, bool known) = fairbind.isSampled(nonce);
        require(sampled && known, "sample");
        fairbind.openSample(nonce);
        FairBindCore.CaseView memory caseRecord = fairbind.getCase(nonce);
        require(caseRecord.state == uint8(FairBindCore.CaseState.JUDGING), "case state");
        require(caseRecord.assignedVerifierId != 0, "assignment");
        require(
            fairbind.getVerifier(caseRecord.assignedVerifierId).lockedLiability == 1_010_000,
            "liability"
        );
    }

    function testMissedAnchorBecomesEpochFailure() public {
        _settle(bytes16(uint128(2)));
        vm.roll(701);
        fairbind.timeoutAnchor(sellerId, 0);
        require(
            fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.EPOCH_FAILED),
            "failed"
        );
    }

    function testSealRejectsInsufficientVerifierSet() public {
        _settle(bytes16(uint128(3)));
        for (uint32 id = 1; id <= 9; id++) {
            fairbind.requestVerifierExit(id);
        }
        fairbind.checkpointVerifierTree(3);
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        vm.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.seal(sellerId, 0);
    }

    function testNontrivialSamplingUsesFixedHashWithoutReceipt() public {
        // A separate profile retains the baseline helpers but samples half the nonce space.
        FairBindCore.ServiceProfileInput memory p = _profile();
        p.samplePpm = 500_000;
        fairbind.createServiceProfile(4, p);
        fairbind.checkpointVerifierTree(4);
        fairbind.setServiceProfileActive(4, true);
        sellerId = registerSellerWithBond(fairbind, 4, address(0x515E), CLAIMS, 10_000_000);
        bytes16 key = bytes16(uint128(42));
        bytes32 req = keccak256("half");
        bytes32 n = fairbind.deriveNonce(sellerId, 4, CLAIMS, BUYER, key, req);
        FairBindCore.TransferAuthorization memory a =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 1, 0, 100, n);
        fairbind.settle(sellerId, 4, CLAIMS, key, req, a, new bytes(65));
        vm.roll(600);
        fairbind.anchor(
            sellerId, 0, _oneEntry(keccak256("arbitrary-root-no-receipt")), 1, keccak256("publication")
        );
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        bytes32 random = keccak256("fixed-randomness");
        vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK, random);
        fairbind.seal(sellerId, 0);
        (bool selected, bool known) = fairbind.isSampled(n);
        uint256 ticket = uint256(
            keccak256(abi.encode(keccak256("fairbind/sample/v1"), random, sellerId, uint24(0), n))
        );
        require(known && selected == (ticket < uint256(1) << 255), "half threshold");
    }

    /// Rule D2-16 (ADR 0029): a missing block hash no longer fails the epoch;
    /// seal reverts and the epoch stays anchored, waiting for its value.
    function testUnavailableRandomnessKeepsTheEpochAnchored() public {
        _settle(bytes16(uint128(30)));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK, bytes32(0));
        vm.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        require(
            fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED),
            "missing hash keeps the epoch anchored"
        );
    }

    /// Rule D2-16 (ADR 0029): timeoutSeal is the checkpoint-shortage exit. It
    /// is not open through the anchor deadline, and after it the epoch's
    /// fourteen-verifier checkpoint keeps it closed, also past sealDeadline,
    /// where a late value still seals the epoch.
    function testSealTimeoutNeedsACheckpointShortage() public {
        _settle(bytes16(uint128(31)));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(700);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutSeal(sellerId, 0);
        // The seal deadline is the beacon block plus sealBlocks (200).
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 201);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSeal(sellerId, 0);
        vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK, keccak256("late value"));
        fairbind.seal(sellerId, 0);
        require(
            fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.SEALED),
            "late value seals"
        );
    }

    function testLiabilityRespectsEffectiveBondCap() public {
        FairBindCore.ServiceProfileInput memory p = _profile();
        p.verifierBondCap = 1_000_000;
        fairbind.createServiceProfile(4, p);
        fairbind.checkpointVerifierTree(4);
        fairbind.setServiceProfileActive(4, true);
        sellerId = registerSellerWithBond(fairbind, 4, address(0x515E), CLAIMS, 10_000_000);
        bytes16 key = bytes16(uint128(43));
        bytes32 req = keccak256("cap");
        bytes32 n = fairbind.deriveNonce(sellerId, 4, CLAIMS, BUYER, key, req);
        FairBindCore.TransferAuthorization memory a =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 1, 0, 100, n);
        fairbind.settle(sellerId, 4, CLAIMS, key, req, a, new bytes(65));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        fairbind.openSample(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        // An exhausted initial search on a sampled case waits for the next
        // checkpoint with its purchase held (ADR 0028); before ADR 0028 it fell
        // back to a keeper request that went straight to publication (ADR 0014).
        require(
            c.state == uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT)
                && c.requesterRole == uint8(FairBindCore.RequesterRole.NONE),
            "effective-bond capacity exhausted"
        );
        require(c.assignedVerifierId == 0, "no over-cap assignment");
        token.mint(BUYER, 5_000_000);
        vm.prank(BUYER);
        token.approve(address(fairbind), type(uint256).max);
        FairBindCore.FairBindReceipt memory empty;
        vm.prank(BUYER);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        vm.roll(50_000);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
        fairbind.timeoutBuyerServe(n);
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "buyer right survives inconclusive");
    }

    // Regression for independently available buyer recovery during judgment.
    function testActiveSampleAllowsIndependentBuyerRecovery() public {
        bytes32 nonce = _settle(bytes16(uint128(92)));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        fairbind.openSample(nonce);
        require(fairbind.getCase(nonce).state == uint8(FairBindCore.CaseState.JUDGING), "active sample");
        FairBindCore.FairBindReceipt memory receipt;
        token.mint(BUYER, 5_000_000);
        vm.prank(BUYER);
        token.approve(address(fairbind), type(uint256).max);
        vm.prank(BUYER);
        fairbind.dispute(nonce, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), receipt, new bytes(0));
        require(fairbind.getBuyerRecovery(nonce).state == uint8(FairBindCore.CaseState.SERVE_WAIT), "buyer recovery");
        require(fairbind.getCase(nonce).state == uint8(FairBindCore.CaseState.JUDGING), "judgment preserved");
    }

    function _registerVerifiers(uint32 count) internal {
        for (uint32 i; i < count; i++) {
            fairbind.registerVerifier(uint256(1) << 1, address(uint160(0x1000 + i)), 10_000_000);
        }
    }

    function _settle(bytes16 key) internal returns (bytes32 nonce) {
        bytes32 requestHash = keccak256(abi.encode(key));
        nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        FairBindCore.TransferAuthorization memory authorization =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 10_000, 0, 100, nonce);
        fairbind.settle(sellerId, 3, CLAIMS, key, requestHash, authorization, new bytes(65));
    }

    function _profile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = keccak256("fairbind/http-canon/v1");
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 1_000_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 200_000;
        p.bucketCapacity = 20;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 30_000;
        p.deferBlocks = 40_000;
        p.retentionBlocks = 40_000;
        p.marginBlocks = 500;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 10_000;
        p.maxBadGain = 10_000;
        p.sellerPenalty = 10_000_000;
        p.minVerifierBond = 1_000_000;
        p.verifierBondCap = 100_000_000;
        p.verifierLatePenalty = 500_000;
        p.verifierWrongPenalty = 1_000_000;
        p.disputeDeposit = 5_000_000;
        p.appealDeposit = 5_000_000;
        p.verifierExposurePpm = 500_000;
        p.maxAssignments = 3;
        p.minVerifiers = 14;
        p.strikeLimit = 3;
        p.deadlineConfigId = 1;
        p.claimWindowBlocks = p.retentionBlocks;
        p.failureLimit = 3;
        p.failureWindowBlocks = p.retentionBlocks;
        p.maxInconclusivePpm = 1_000_000;
        p.inconclusiveWindowBlocks = p.retentionBlocks;
        p.forfeitVerifierPpm = 500_000;
        p.freezeOnInitialFail = false;
        p.minJudgedCount = 1;
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS;
        p.parameterHash = keccak256("profile");
    }
}
