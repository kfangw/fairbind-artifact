// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { Impl1bBase } from "./Design2Impl1b.t.sol";

interface ValueBlockVm {
    function getBlockNumber() external view returns (uint256);
}

/// Design 2 rule D2-16 (paper rule (i)), ADR 0029: an anchored epoch whose
/// sampling value has not arrived stays held. It ends in a refund, without a
/// seller failure, only when its verifier checkpoint, fixed at the anchor
/// deadline before the value, holds fewer verifiers than minVerifiers.
/// Otherwise it waits for the value, which anyone may deliver late.
contract EpochValueHoldTest is Impl1bBase {
    ValueBlockVm internal constant vv = ValueBlockVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant ANCHOR_DEADLINE = 700;
    uint256 internal constant SEAL_DEADLINE = BEACON_BLOCK + 200;
    uint8 internal constant ANCHORED = uint8(FairBindCore.EpochState.ANCHORED);
    uint8 internal constant SEALED = uint8(FairBindCore.EpochState.SEALED);
    uint8 internal constant FAILED = uint8(FairBindCore.EpochState.EPOCH_FAILED);
    uint8 internal constant DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);

    function _now() internal view returns (uint256) {
        return vv.getBlockNumber();
    }

    function _halfSampled() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _sampledProfile(20);
        p.samplePpm = 500_000;
    }

    /// Settles `count` purchases at block 10 and anchors epoch 0 at block 600.
    function _anchored(uint256 count) internal returns (bytes32[] memory ns) {
        _deploy(_halfSampled());
        hv.roll(10);
        ns = new bytes32[](count);
        for (uint256 i; i < count; i++) ns[i] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(count), keccak256("publication"));
    }

    function _untouched(bytes32[] memory ns) internal view {
        FairBindCore.BondView memory b = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(b.failureCount == 0 && b.freezeState == 0 && b.balance == 10_000_000, "no failure, freeze or deduction");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "seller active");
        for (uint256 i; i < ns.length; i++) {
            require(fairbind.getPurchase(ns[i]).financialState == DEFERRED, "held");
        }
    }

    /// (1) Without the value nothing is released and nothing fails: seal
    /// reverts and leaves the epoch ANCHORED, the old seal timeout no longer
    /// exists, releasePurchase refuses every entry after every other release
    /// condition, and the seller is neither counted, frozen nor deducted.
    /// A value the chain no longer serves leaves the epoch held for good.
    function test_missingValueHoldsTheEpochWithoutFailure() public {
        bytes32[] memory ns = _anchored(4);
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, bytes32(0));
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).state == ANCHORED, "still anchored");
        hv.roll(SEAL_DEADLINE + 1);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSeal(sellerId, 0);
        // Past releaseBlock, retainUntil, claimUntil and sampleOpenUntil.
        hv.roll(10 + 40_000 + 1_000);
        for (uint256 i; i < ns.length; i++) {
            hv.expectRevert(FairBindCore.InvalidTransition.selector);
            fairbind.releasePurchase(ns[i]);
            hv.expectRevert(FairBindCore.InvalidTransition.selector);
            fairbind.claimEpochFailure(ns[i]);
        }
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSeal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).state == ANCHORED, "held for good");
        _untouched(ns);
    }

    /// (2) A checkpoint at the anchor deadline with fewer than minVerifiers
    /// verifiers ends the epoch, before its value exists: EPOCH_FAILED with
    /// reason VERIFIER_SET_UNAVAILABLE, every purchase refundable and refunded,
    /// and no failure counted, frozen or deducted.
    function test_checkpointShortageRefundsWithoutFailure() public {
        _deploy(_halfSampled());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 3, keccak256("publication"));
        // A verifier leaves; the checkpoint written before the anchor deadline
        // holds thirteen verifiers, one fewer than minVerifiers.
        fairbind.requestVerifierExit(14);
        hv.roll(650);
        require(fairbind.checkpointVerifierTree(PROFILE) == 2, "newer checkpoint");
        (, uint32[] memory ids,,,) = fairbind.getVerifierCheckpoint(PROFILE, 2);
        require(ids.length == 13, "thirteen verifiers");
        hv.roll(ANCHOR_DEADLINE);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutSeal(sellerId, 0);
        hv.roll(ANCHOR_DEADLINE + 1);
        require(_now() < BEACON_BLOCK, "before the value exists");
        uint256 before = token.balanceOf(buyer);
        fairbind.timeoutSeal(sellerId, 0);
        FairBindCore.AnchorView memory a = fairbind.getAnchor(sellerId, 0);
        require(a.state == FAILED, "epoch failed");
        for (uint256 i; i < ns.length; i++) {
            fairbind.claimEpochFailure(ns[i]);
            require(fairbind.getPurchase(ns[i]).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "refundable");
            fairbind.claimRefund(ns[i]);
        }
        require(token.balanceOf(buyer) == before + 3 * G, "buyers refunded");
        FairBindCore.BondView memory b = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(b.failureCount == 0 && b.freezeState == 0 && b.balance == 10_000_000, "no failure, freeze or deduction");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "seller active");
    }

    /// The shortage exit also applies after the value exists, when seal
    /// cannot succeed on the short checkpoint.
    function test_checkpointShortageAlsoEndsTheEpochAfterItsValue() public {
        _deploy(_halfSampled());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        fairbind.requestVerifierExit(3);
        fairbind.checkpointVerifierTree(PROFILE);
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, BEACON);
        hv.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.seal(sellerId, 0);
        fairbind.timeoutSeal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).state == FAILED, "epoch failed");
    }

    /// (3) A value delivered after sealDeadline takes the normal path: the
    /// epoch seals with it, a sampled purchase opens its case, and an
    /// unsampled purchase is released at its usual block.
    function test_lateValueTakesTheNormalPath() public {
        bytes32[] memory ns = _anchored(8);
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, bytes32(0));
        hv.expectRevert(FairBindCore.InvalidRandomnessWindow.selector);
        fairbind.seal(sellerId, 0);
        hv.roll(SEAL_DEADLINE + 40);
        hv.setBlockhash(BEACON_BLOCK, BEACON);
        fairbind.seal(sellerId, 0);
        FairBindCore.AnchorView memory a = fairbind.getAnchor(sellerId, 0);
        require(a.state == SEALED && a.randomness == BEACON, "sealed late with the value");
        require(a.sealDeadline == SEAL_DEADLINE, "the deadline does not move");
        bytes32 s;
        bytes32 u;
        for (uint256 i; i < ns.length; i++) {
            (bool eligible, bool known) = fairbind.isSampled(ns[i]);
            require(known, "known");
            if (eligible && s == 0) s = ns[i];
            if (!eligible && u == 0) u = ns[i];
        }
        require(s != 0 && u != 0, "fixture: a sampled and an unsampled purchase");
        fairbind.openSample(s);
        require(fairbind.getCase(s).state == uint8(FairBindCore.CaseState.JUDGING), "sample case assigned");
        hv.roll(10 + 40_000 - 1);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(u);
        hv.roll(10 + 40_000);
        fairbind.releasePurchase(u);
        require(fairbind.getPurchase(u).financialState == uint8(FairBindCore.FinancialState.RELEASED), "released");
    }

    /// (4) With enough verifiers in the checkpoint there is no refund: before
    /// the value, after sealDeadline and after the value is lost, timeoutSeal
    /// reverts and claimEpochFailure finds no failed epoch.
    function test_noRefundWithEnoughVerifiers() public {
        bytes32[] memory ns = _anchored(2);
        uint256[4] memory at = [ANCHOR_DEADLINE + 1, BEACON_BLOCK + 1, SEAL_DEADLINE + 1, BEACON_BLOCK + 300];
        for (uint256 i; i < at.length; i++) {
            hv.roll(at[i]);
            hv.expectRevert(FairBindCore.InvalidTransition.selector);
            fairbind.timeoutSeal(sellerId, 0);
            hv.expectRevert(FairBindCore.InvalidTransition.selector);
            fairbind.claimEpochFailure(ns[0]);
        }
        require(fairbind.getAnchor(sellerId, 0).state == ANCHORED, "anchored");
        _untouched(ns);
    }
}
