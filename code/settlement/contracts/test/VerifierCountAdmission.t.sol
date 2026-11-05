// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { DeployFairBind } from "./DeployFairBind.sol";
import { FairBind } from "../src/FairBind.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

interface VmVerifierCount {
    function roll(uint256 blockNumber) external;
    function expectRevert(bytes4 selector) external;
}

/// Admission of minVerifiers against maxAssignments (profile-v1 section 2, ADR 0023)
/// and the minimum verifier set behind registration, settlement and the epoch seal.
contract VerifierCountAdmissionTest is DeployFairBind {
    VmVerifierCount private constant vm =
        VmVerifierCount(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private constant MARGIN = 5;
    bytes32 private constant CLAIMS = keccak256("claims");
    address private constant BUYER = address(0xB0B);
    MockEIP3009Token private token;
    FairBind private fairbind;

    function setUp() public {
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), address(0xCAFE));
        fairbind.createDeadlineConfig(
            1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600)
        );
        token.mint(address(this), 1_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        token.mint(BUYER, 100_000);
    }

    function testAdmitsExactlyThreeTimesMaxAssignmentsPlusMargin() public {
        for (uint16 m = 1; m <= 3; m++) {
            FairBindCore.ServiceProfileInput memory p = _profile(m, uint16(3 * m + MARGIN));
            fairbind.createServiceProfile(10 + m, p);
            require(fairbind.getServiceProfile(10 + m).parameters.minVerifiers == 3 * m + MARGIN, "admitted");
        }
    }

    function testRejectsOneBelowTheMargin() public {
        for (uint16 m = 1; m <= 3; m++) {
            FairBindCore.ServiceProfileInput memory p = _profile(m, uint16(3 * m + MARGIN - 1));
            vm.expectRevert(FairBindCore.InvalidProfile.selector);
            fairbind.createServiceProfile(20 + m, p);
        }
    }

    /// The former bound minVerifiers >= 3 * maxAssignments admitted nine verifiers
    /// for three assignments per stage; the new bound does not.
    function testRejectsTheFormerBound() public {
        vm.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(3, _profile(3, 9));
        fairbind.createServiceProfile(3, _profile(3, 14));
    }

    function testSellerRegistrationNeedsMinVerifiers() public {
        fairbind.createServiceProfile(3, _profile(3, 14));
        _registerVerifiers(1, 13);
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3, true);
        uint32 bondId = fairbind.registerBond(3, 10_000_000);
        vm.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.registerSeller(bondId, 3, address(0x515E), CLAIMS);
        _registerVerifiers(14, 1);
        fairbind.checkpointVerifierTree(3);
        require(fairbind.registerSeller(bondId, 3, address(0x515E), CLAIMS) != 0, "registered");
    }

    function testSettlementStopsWhenTheSetFallsBelowMinVerifiers() public {
        uint32 sellerId = _activeSeller();
        _settle(sellerId, bytes16(uint128(1)));
        fairbind.requestVerifierExit(14);
        fairbind.checkpointVerifierTree(3);
        bytes16 key = bytes16(uint128(2));
        bytes32 requestHash = keccak256(abi.encode(key));
        bytes32 nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        FairBindCore.TransferAuthorization memory authorization =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 10_000, 0, 100, nonce);
        vm.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.settle(sellerId, 3, CLAIMS, key, requestHash, authorization, new bytes(65));
    }

    /// An epoch whose checkpoint lost one verifier before the anchor deadline cannot
    /// be sealed, so no case of that epoch is assigned from fewer than minVerifiers.
    function testSealNeedsMinVerifiersInTheEpochCheckpoint() public {
        uint32 sellerId = _activeSeller();
        _settle(sellerId, bytes16(uint128(3)));
        fairbind.requestVerifierExit(14);
        fairbind.checkpointVerifierTree(3);
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        vm.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.seal(sellerId, 0);
    }

    function testSealAndAssignAtExactlyMinVerifiers() public {
        uint32 sellerId = _activeSeller();
        bytes32 nonce = _settle(sellerId, bytes16(uint128(4)));
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        fairbind.openSample(nonce);
        require(fairbind.getCase(nonce).assignedVerifierId != 0, "assigned");
    }

    function _activeSeller() internal returns (uint32 sellerId) {
        fairbind.createServiceProfile(3, _profile(3, 14));
        _registerVerifiers(1, 14);
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3, true);
        sellerId = registerSellerWithBond(fairbind, 3, address(0x515E), CLAIMS, 10_000_000);
    }

    function _registerVerifiers(uint32 first, uint32 count) internal {
        for (uint32 i = first; i < first + count; i++) {
            fairbind.registerVerifier(uint256(1) << 1, address(uint160(0x1000 + i)), 10_000_000);
        }
    }

    function _settle(uint32 sellerId, bytes16 key) internal returns (bytes32 nonce) {
        bytes32 requestHash = keccak256(abi.encode(key));
        nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        FairBindCore.TransferAuthorization memory authorization =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 10_000, 0, 100, nonce);
        fairbind.settle(sellerId, 3, CLAIMS, key, requestHash, authorization, new bytes(65));
    }

    function _profile(uint16 maxAssignments, uint16 minVerifiers)
        internal
        pure
        returns (FairBindCore.ServiceProfileInput memory p)
    {
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
        p.maxAssignments = maxAssignments;
        p.minVerifiers = minVerifiers;
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
