// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";

/// ADR 0035: a side-gain profile. A settlement needs the epoch's opening
/// count (verifiers eligible by state at the block before the epoch opens)
/// at minVerifiers and a side-gain deposit of one unit per open sale plus
/// one; a sample case's confirmed failure deducts a unit; an epoch past its
/// sampling deadline asks again with a new input. Here eta = 0.1 and p0 =
/// 0.04, so one unit at the cap of 0.01 USDC is 25,000 base units.
contract SideGainTest is BatchBase {
    uint256 internal constant UNIT = 25_000;

    function _sideTerms() internal pure returns (BatchStore.Terms memory t) {
        t = _defaultTerms();
        t.sideGainPpm = 100_000;
    }

    function _deploySide(FairBindCore.ServiceProfileInput memory p) internal {
        _deployBatched(p, _sideTerms(), _equalBonds());
    }

    function settleExternal() external returns (bytes32) {
        return _purchase(G);
    }

    function _settles() internal returns (bool ok) {
        (ok,) = address(this).call(abi.encodeCall(this.settleExternal, ()));
    }

    function _deposit(uint128 amount) internal {
        uint32 bondId = _bondOfSeller(sellerId);
        hv.prank(SELLER_OWNER);
        fb.depositSideGain(bondId, amount);
    }

    /// Epoch 1 opens at block 301: no sale before its opening count is
    /// recorded, none without the deposit, and one more unit per open sale.
    /// A verifier that asked to exit before epoch 2 opened leaves its count
    /// at 13, below minVerifiers, and the epoch takes no sale.
    /// Each sale needs one unit beyond those of the open sales: none without
    /// a deposit, one with one unit, a second one only with two. A build that
    /// asks only for the open sales' units takes the first sale with none.
    function _saleNeedsOneMoreUnit(string memory artifact) internal returns (bool) {
        settlementArtifact = artifact;
        _deploySide(_batchProfile());
        hv.roll(301);
        hv.prank(KEEPER);
        fb.recordEpochOpenCount(PROFILE, 1);
        if (_settles()) return false;
        _deposit(uint128(UNIT));
        if (!_settles() || _settles()) return false;
        _deposit(uint128(UNIT));
        return _settles();
    }

    function test_eachSaleNeedsOneMoreUnit() public {
        require(_saleNeedsOneMoreUnit(settlementArtifact), "one unit more per sale");
    }

    function test_depositShortOfTheNewSaleIsCaught() public {
        require(!_saleNeedsOneMoreUnit("BatchMutants.sol:SideGainShortSettlement"), "mutation caught");
    }

    function test_saleNeedsTheOpeningCountAndTheDeposit() public {
        _deploySide(_batchProfile());
        hv.roll(301);
        hv.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        this.settleExternal();
        hv.prank(KEEPER);
        require(fb.recordEpochOpenCount(PROFILE, 1) == 14, "fourteen at block 300");
        require(!_settles(), "no deposit");
        _deposit(uint128(UNIT));
        require(_settles(), "one unit for one open sale");
        require(!_settles(), "the second sale needs two units");
        _deposit(uint128(UNIT));
        require(_settles(), "two units");
        uint32 bondId = _bondOfSeller(sellerId);
        require(fb.getSideGain(bondId).open == 2, "two open sales");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.withdrawSideGain(bondId, 1);
        hv.roll(550);
        fairbind.requestVerifierExit(3);
        hv.roll(601);
        hv.prank(KEEPER);
        require(fb.recordEpochOpenCount(PROFILE, 2) == 13, "thirteen at block 600");
        _deposit(uint128(UNIT));
        hv.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        this.settleExternal();
    }

    /// A sample case that ends FINAL(FAIL) deducts one unit; its end and an
    /// unsampled sale's clearing free the deposit.
    function test_sampleFailureDeductsAUnitAndDecidedSalesFreeTheDeposit() public {
        FairBindCore.ServiceProfileInput memory p = _batchProfile();
        p.samplePpm = 500_000;
        _deploySide(p);
        hv.roll(301);
        hv.prank(KEEPER);
        fb.recordEpochOpenCount(PROFILE, 1);
        _deposit(uint128(8 * UNIT));
        bytes32[] memory ns = new bytes32[](6);
        for (uint256 i; i < 6; i++) ns[i] = _purchase(G);
        _anchorOf(1, sellerId, SELLER_OWNER, ns);
        _sealOf(1, _sellers1());
        uint32 bondId = _bondOfSeller(sellerId);
        bytes32 sampled;
        bytes32 unsampled;
        for (uint256 i; i < 6; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            if (eligible && sampled == bytes32(0)) sampled = ns[i];
            if (!eligible && unsampled == bytes32(0)) unsampled = ns[i];
        }
        require(sampled != bytes32(0) && unsampled != bytes32(0), "a partial sample");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.clearSideGain(sampled);
        fb.clearSideGain(unsampled);
        require(fb.getSideGain(bondId).open == 5, "one cleared");
        hv.roll(1050);
        _openSample(sampled);
        _assignBatch(1);
        _judgeBatched(sampled, uint8(FairBindCore.Verdict.FAIL));
        hv.roll(uint256(fairbind.getReview(sampled).appealUntil) + 1);
        uint256 deposit0 = fb.getSideGain(bondId).deposit;
        fairbind.finalizeCase(sampled);
        require(deposit0 - fb.getSideGain(bondId).deposit == UNIT, "one unit deducted");
        require(fb.getSideGain(bondId).open == 4, "the case's end frees its sale");
    }

    /// Past M = A + D_S + T_V without a value, a side-gain profile asks again
    /// with input (profile, A, 1) and seals with that value; the first
    /// request's late value is refused. Another profile cannot ask again.
    function test_repeatedSampleRequestAfterTheDeadline() public {
        _deploySide(_batchProfile());
        hv.roll(301);
        hv.prank(KEEPER);
        fb.recordEpochOpenCount(PROFILE, 1);
        _deposit(uint128(UNIT));
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(1, sellerId, SELLER_OWNER, ns);
        hv.roll(1001);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 1);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 1);
        hv.roll(1031);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fb.rerequestSampleValue(PROFILE, 1);
        hv.roll(1032);
        hv.prank(KEEPER);
        fb.rerequestSampleValue(PROFILE, 1);
        bytes32 again = keccak256(abi.encode(VRF_SAMPLE, abi.encode(uint32(PROFILE), _a(1), uint32(1))));
        bytes32 value = _fulfill(again);
        hv.prank(KEEPER);
        fairbind.seal(sellerId, 1);
        require(fairbind.getAnchor(sellerId, 1).randomness == value, "sealed with the repeated request's value");
        (bool late,) = address(this).call(abi.encodeCall(this.fulfillExternal, (_sampleId(1))));
        require(!late, "the first request's value is refused after M");
    }

    function fulfillExternal(bytes32 id) external returns (bytes32) {
        return _fulfill(id);
    }

    function test_onlyASideGainProfileAsksAgain() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(2000);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.rerequestSampleValue(PROFILE, 1);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.recordEpochOpenCount(PROFILE, 1);
    }
}
