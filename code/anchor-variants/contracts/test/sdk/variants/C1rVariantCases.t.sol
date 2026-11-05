// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBaseC1R } from "./c1r/SdkBaseC1R.sol";
import { SettlementBaseC1, SampledSettlementC1Core, UnitRec, EpochRec, AnchorPre } from "./SampledSettlementC1.sol";
import { Receipt, Leaf, Unit, Opening, UnitHeader } from "../SampledSettlement.sol";

/// Shared builders of the variant cases.
abstract contract VariantCaseKit {
    bytes32 internal constant TAG_V = keccak256("p5/response/v1");

    function _k3(bytes32 a, uint256 b, uint256 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, bytes32(b), c));
    }

    function _k2(bytes32 a, uint256 b) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, bytes32(b)));
    }
}

/// C1r: slot reuse after the cursor and the evidence deadline.
contract C1rVariantCasesTest is SdkBaseC1R, VariantCaseKit {
    uint256 internal constant FALLBACK = 1 << 255;

    function _signedSale(bytes32 pid, uint256 i) internal returns (Leaf memory l, bytes memory mat) {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("psi", pid, i));
        mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pid, i, PRICE);
        r.responseHash = keccak256(abi.encodePacked(TAG_V, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(pid, r, i);
        l.sigB = _ack(pid, l.rs, false);
    }

    function _one(Leaf memory a) internal pure returns (Leaf[] memory ls) {
        ls = new Leaf[](1);
        ls[0] = a;
    }

    function _hdr(Unit memory u) internal pure returns (UnitHeader memory h) {
        h.pid = u.pid;
        h.epoch = u.epoch;
        h.count = u.count;
        h.unitNo = u.unitNo;
        h.first = u.first;
        h.last = u.last;
        h.root = u.root;
        h.root0 = u.root0;
        h.snapshotHash = keccak256(abi.encode(u.snapshot));
    }

    function _hsig(UnitHeader memory h) internal returns (bytes memory) {
        bytes32 sh = keccak256(abi.encode(f.UNIT_TYPEHASH(), h)); // h is a static struct: its fields in order
        return _sig(sellerKey, _typed(f.DOMAIN_SEPARATOR(), sh));
    }

    /// A sale of pidP in epoch e, anchored alone.
    function _saleIn(uint256 e, uint256 i) internal returns (Leaf[] memory ls, bytes memory mat) {
        uint256 start = f.genesis() + e * f.EPOCH_BLOCKS() + 5;
        if (block.number < start) vm.roll(start);
        Leaf memory a;
        (a, mat) = _signedSale(pidP, i);
        ls = _one(a);
        epoch = e;
        _anchor(pidP, ls);
    }

    /// The sale is not sampled and the cursor passes epoch e.
    function _pass(uint256 e, Leaf[] memory ls) internal {
        vm.roll(f.anchorDeadline(e) + 1);
        uint256 v = 1;
        while (f.sampledBy(v, ls[0].rs.nonce, PRICE, CAP)) v++;
        vm.prank(rnd);
        f.postSampleValue(pidP, e, v);
        vm.roll(f.anchorDeadline(e) + f.T_C() + 1);
        while (f.accountCursor(seller) <= e) m.release(seller);
    }

    function _ring() internal pure returns (uint256) {
        return 4; // k + 3 with k = 1
    }

    /// After the cursor passes e, epoch e + 4 writes e's ring slot again; e's
    /// record no longer opens, e + 4's does; no fallback slot is used.
    function test_R1_slotReusedAfterCursor() public {
        uint256 e = epoch;
        (, Leaf[] memory l1, bytes memory mat1) = _reuseSetup(e);
        _checkReused(e);
        vm.roll(f.valueDeadline(e + _ring()) + 1);
        _proveV(_opening(pidP, l1, 0), mat1);
    }

    /// e's stored record opens neither e's leaf (slot now e + 4's) nor e + 4's.
    function test_R1b_staleRecordRejected() public {
        uint256 e = epoch;
        (Leaf[] memory l0, Leaf[] memory l1, bytes memory mat1) = _reuseSetup(e);
        vm.roll(f.valueDeadline(e + _ring()) + 1);
        epoch = e;
        _expectMembership(_opening(pidP, l0, 0), mat1, e);
        epoch = e + _ring();
        _expectMembership(_opening(pidP, l1, 0), mat1, e);
    }

    /// A sale in e, the cursor past e, then a sale in e + 4, both anchored.
    function _reuseSetup(uint256 e) internal returns (Leaf[] memory l0, Leaf[] memory l1, bytes memory mat1) {
        (l0,) = _saleIn(e, 1);
        require(f.unitSlot(_k3(pidP, e % _ring(), 1)) >> 224 == e, "e in the ring slot");
        _pass(e, l0);
        (l1, mat1) = _saleIn(e + _ring(), 2);
    }

    function _checkReused(uint256 e) internal view {
        require(f.unitSlot(_k3(pidP, e % _ring(), 1)) >> 224 == e + _ring(), "rewritten by e + 4");
        require(f.unitSlot(_k3(pidP, (e + _ring()) | FALLBACK, 1)) == 0, "no fallback");
        require(f.epochComplete(pidP, e + _ring()) && !f.epochComplete(pidP, e), "completion by epoch");
    }

    /// The proof call with e's stored record reverts with Membership.
    function _expectMembership(Opening memory o, bytes memory mat, uint256 e) internal {
        UnitRec memory r = _recV(pidP, e, 1);
        (bool ok, bytes memory ret) = address(f).call(abi.encodeCall(SampledSettlementC1Core.prove, (o, mat, r)));
        require(!ok && bytes4(ret) == SettlementBaseC1.Membership.selector, "membership");
    }

    /// While the cursor has not passed e, epoch e + 4 goes to its fallback
    /// slot and both records keep opening.
    function test_R2_fallbackWhileCursorBehind() public {
        uint256 e = epoch;
        (Leaf[] memory l0, bytes memory mat0) = _saleIn(e, 1);
        (Leaf[] memory l1,) = _saleIn(e + _ring(), 2);
        require(f.accountCursor(seller) <= e, "cursor behind");
        require(f.unitSlot(_k3(pidP, e % _ring(), 1)) >> 224 == e, "ring slot kept");
        require(f.unitSlot(_k3(pidP, (e + _ring()) | FALLBACK, 1)) >> 224 == e + _ring(), "fallback slot");
        require(f.epochComplete(pidP, e) && f.epochComplete(pidP, e + _ring()), "both complete");
        // e's proof window is over by now; its record still opens for a
        // non-delivery-free check: the swap proof window (until the cursor)
        epoch = e;
        Opening memory o0 = _opening(pidP, l0, 0);
        vm.expectRevert(SettlementBaseC1.Timing.selector); // past T_p: the open itself passed
        _proveV(o0, mat0);
        l1;
    }

    /// Double-signature evidence of e is accepted until the cursor passes e,
    /// and not after (even before the slot is written again).
    function test_R3_doubleSignDeadlineIsCursor() public {
        uint256 e = epoch;
        (Leaf[] memory l0,) = _saleIn(e, 1);
        UnitHeader memory h = _hdr(_unit(pidP, l0));
        h.root0 = keccak256("another root0");
        bytes memory s = _hsig(h);
        uint256 id = vm.snapshotState();
        _proveDoubleSignV(h, s);
        require(m.account(seller).failures == 1, "before the cursor");
        vm.revertToState(id);
        _pass(e, l0);
        require(f.unitSlot(_k3(pidP, e % _ring(), 1)) >> 224 == e, "slot not yet rewritten");
        vm.expectRevert(SettlementBaseC1.Timing.selector);
        _proveDoubleSignV(h, s);
    }

    /// A missed anchor of a passed epoch is left to the cursor's record.
    function test_R4_missedAnchorAfterCursor() public {
        uint256 e = epoch;
        (Leaf[] memory l0,) = _saleIn(e, 1);
        _pass(e, l0);
        vm.expectRevert(); // complete (State) in the reference; Timing here once slots may be reused
        m.declareAnchorMissed(pidP, e);
        require(m.account(seller).failures == 0, "no failure");
    }
}
