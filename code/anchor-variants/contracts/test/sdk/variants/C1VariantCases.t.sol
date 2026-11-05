// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBaseC1 } from "./c1/SdkBaseC1.sol";
import { SettlementBaseC1, UnitRec, EpochRec, AnchorPre } from "./SampledSettlementC1.sol";
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

/// C1: records given back in calldata must be the stored ones.
contract C1VariantCasesTest is SdkBaseC1, VariantCaseKit {
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

    /// One signed sale on pidP and one on pidC, both anchored alone.
    function _two() internal returns (Leaf[] memory lp, Leaf[] memory lc, bytes memory matP) {
        Leaf memory a;
        (a, matP) = _signedSale(pidP, 1);
        (Leaf memory c,) = _signedSale(pidC, 2);
        lp = _one(a);
        lc = _one(c);
        _anchor(pidP, lp);
        require(_anchorV(_unit(pidC, lc)) == 0, "pidC stored");
    }

    /// The stored record opens; a record with one field changed does not.
    function test_V1_wrongRecordRejectedInProof() public {
        (Leaf[] memory lp,, bytes memory mat) = _two();
        vm.roll(f.valueDeadline(epoch) + 1);
        Opening memory o = _opening(pidP, lp, 0);
        UnitRec memory r = _recV(pidP, epoch, 1);
        r.root0 = keccak256("other root0");
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.prove(o, mat, r);
        r = _recV(pidP, epoch, 1);
        r.seq += 1;
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.prove(o, mat, r);
        _proveV(o, mat);
        require(f.passed(keccak256(abi.encode(pidP, lp[0].rs.nonce))), "stored record opens");
    }

    /// Another unit's record (other profile, same epoch) does not open the
    /// leaf, even where its root would.
    function test_V2_otherUnitRecordRejected() public {
        (Leaf[] memory lp, Leaf[] memory lc, bytes memory mat) = _two();
        vm.roll(f.valueDeadline(epoch) + 1);
        Opening memory o = _opening(pidP, lp, 0);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.prove(o, mat, _recV(pidC, epoch, 1));
        // a key dispute on pidC's leaf with pidP's record fails too
        Opening memory oc = _opening(pidC, lc, 0);
        uint8 kk = f.K_KEY();
        UnitRec memory rp = _recV(pidP, epoch, 1);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        f.openDispute(oc, kk, "", 0, rp);
        vm.prank(tower); // the opener pays the deposit
        _openDisputeV(oc, kk, "", 0);
        require(f.openDisputes(keccak256(abi.encode(pidC, lc[0].rs.nonce))) == 1, "stored record opens");
    }

    /// Double-signature evidence needs the stored record: a wrong or another
    /// unit's record reverts; with the stored one the evidence holds.
    function test_V3_doubleSignNeedsStoredRecord() public {
        (Leaf memory a,) = _signedSale(pidP, 1);
        (Leaf memory c,) = _signedSale(pidC, 2);
        Leaf[] memory lp = _one(a);
        _anchor(pidP, lp);
        require(_anchorV(_unit(pidC, _one(c))) == 0, "pidC stored");
        UnitHeader memory h = _hdr(_unit(pidP, lp));
        h.root0 = keccak256("another root0");
        bytes memory s = _hsig(h);
        UnitRec memory r = _recV(pidP, epoch, 1);
        r.count = 7; // a record that would let the evidence through by count
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveDoubleSign(h, s, r);
        vm.expectRevert(SettlementBaseC1.Membership.selector);
        m.proveDoubleSign(h, s, _recV(pidC, epoch, 1));
        _proveDoubleSignV(h, s);
        require(m.account(seller).failures == 1, "evidence with the stored record");
    }

    /// One unit that completes its epoch writes the unit slot only (flagged);
    /// an epoch in two units writes an epoch slot, and a later unit needs the
    /// epoch record and its neighbour's record.
    function test_V4_slotsAndAnchorRecords() public {
        (Leaf memory a,) = _signedSale(pidP, 1);
        (Unit memory u1, Unit memory u2) = _twoUnits();
        _anchor(pidP, _one(a));
        uint256 v = f.unitSlot(_k3(pidP, epoch, 1));
        require(v & 1 == 1 && f.epochSlot(_k2(pidP, epoch)) == 0, "alone: unit slot only, flagged");
        require(_anchorV(u1) == 0, "unit 1");
        require(f.unitSlot(_k3(pidC, epoch, 1)) & 1 == 0, "unit 1 not alone");
        require(f.epochSlot(_k2(pidC, epoch)) != 0 && !f.epochComplete(pidC, epoch), "epoch slot, open");
        _wrongRecords(u2);
        require(_anchorV(u2) == 0, "unit 2 with the stored records");
        require(f.epochComplete(pidC, epoch) && f.epochSlot(_k2(pidC, epoch)) & 1 == 1, "complete by the flag");
    }

    /// Two units of one epoch of pidC, one sale each, count 2.
    function _twoUnits() internal returns (Unit memory u1, Unit memory u2) {
        Leaf[] memory ls = new Leaf[](2);
        (ls[0],) = _signedSale(pidC, 2);
        (ls[1],) = _signedSale(pidC, 3);
        _sort(ls);
        u1 = _unit(pidC, _one(ls[0]));
        u1.count = 2;
        u1.sellerSig = _hsig(_hdr(u1));
        u2 = _unit(pidC, _one(ls[1]));
        u2.count = 2;
        u2.unitNo = 2;
        u2.sellerSig = _hsig(_hdr(u2));
    }

    /// A wrong epoch record, then a wrong neighbour record: rejected (15),
    /// not recorded as the seller's rejection.
    function _wrongRecords(Unit memory u2) internal {
        AnchorPre memory pre;
        pre.er = _erecV[_ekV(pidC, epoch)];
        pre.prev = _recV(pidC, epoch, 1);
        pre.er.stored = 0;
        require(f.anchorUnit(u2, pre) == 15, "wrong epoch record");
        pre.er = _erecV[_ekV(pidC, epoch)];
        pre.prev.last = bytes32(0);
        require(f.anchorUnit(u2, pre) == 15, "wrong neighbour record");
    }

    /// A unit numbered 2 after a unit 1 that completed the epoch alone is
    /// rejected as over the count (13), without any record.
    function test_V5_unitAfterAloneRejected() public {
        (Leaf memory a,) = _signedSale(pidP, 1);
        Leaf[] memory lp = _one(a);
        _anchor(pidP, lp);
        Unit memory u2 = _unit(pidP, lp);
        u2.unitNo = 2;
        u2.sellerSig = _hsig(_hdr(u2));
        require(_anchorV(u2) == 13, "over the count");
    }
}

