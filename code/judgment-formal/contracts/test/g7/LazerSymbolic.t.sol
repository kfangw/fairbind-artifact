// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SymTest } from "./Svm.sol";
import { P5Ctx } from "../g10/p5/P5Ref.sol";
import { P5LazerVerifier } from "../g10/p5/P5Verifiers.sol";

/// Symbolic checks of the tier 1a signed-feed verification contract.
/// keccak256 and ecrecover are uninterpreted functions (keccak256 injective).
/// The material is fully symbolic except, in the fixed-layout checks, the
/// two-byte payload length field, which is set to the layout's length.
contract LazerSymbolicTest is SymTest {
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    uint256 internal constant HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;
    uint32 internal constant FEED = 1;
    address internal constant SIGNER = address(0x5167);
    uint8 internal constant CHANNEL = 3;
    uint256 internal constant PERIOD_US = 200_000;

    P5LazerVerifier internal v;

    function setUp() public {
        v = new P5LazerVerifier(SIGNER, FEED);
    }

    function _ctx() internal view returns (P5Ctx memory c) {
        c.nonce = svm.createBytes32("nonce");
        c.amount = uint64(svm.createUint(64, "amount"));
        c.validAfter = uint64(svm.createUint(64, "validAfter"));
        c.requestHash = svm.createBytes32("requestHash");
        c.responseHash = svm.createBytes32("responseHash");
        c.claimsHash = svm.createBytes32("claimsHash");
        c.materialCommit = svm.createBytes32("materialCommit");
        c.anchoredHash = svm.createBytes32("anchoredHash");
    }

    /// material = psi (32) || magic (4) || r (32) || s (32) || v (1) || len (2) || payload (len) || tail
    function _material(uint256 len, uint256 tail) internal view returns (bytes memory m) {
        m = svm.createBytes(32 + 71 + len + tail, "material");
        m[32 + 69] = bytes1(uint8(len >> 8));
        m[32 + 70] = bytes1(uint8(len));
    }

    function _call(P5Ctx memory c, bytes memory m) internal view returns (bool) {
        try v.verify(c, m) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    function _word(bytes memory b, uint256 off) internal pure returns (bytes32 w) {
        assembly {
            w := mload(add(add(b, 0x20), off))
        }
    }

    function _slice(bytes memory b, uint256 off, uint256 n) internal pure returns (bytes memory out) {
        out = new bytes(n);
        for (uint256 i; i < n; i++) out[i] = b[off + i];
    }

    function _be(bytes memory b, uint256 off, uint256 n) internal pure returns (uint256 x) {
        for (uint256 i; i < n; i++) x = (x << 8) | uint8(b[off + i]);
    }

    /// V1, V2, V3, V4 for one layout: what a pass implies.
    function _passImplies(uint256 len, uint256 tail) internal view {
        P5Ctx memory c = _ctx();
        bytes memory m = _material(len, tail);
        if (!_call(c, m)) return;
        bytes32 psi = _word(m, 0);
        bytes memory payload = _slice(m, 32 + 71, len);
        bytes32 r = _word(m, 32 + 4);
        bytes32 s = _word(m, 32 + 36);
        uint8 rv = uint8(m[32 + 68]);
        // V1: the signature over keccak256(payload) recovers to the fixed signer
        assert(uint256(s) <= HALF_N);
        assert(rv == 0 || rv == 1);
        assert(ecrecover(keccak256(payload), rv + 27, r, s) == SIGNER);
        // V2: magic, feed, property and the response fields come from the signed payload
        assert(_be(m, 32, 4) == 706910618);
        assert(_be(payload, 0, 4) == 2479346549);
        assert(_be(payload, 14, 4) == FEED);
        assert(uint8(payload[19]) == 0);
        uint64 ts = uint64(_be(payload, 4, 8));
        int64 price = int64(uint64(_be(payload, 20, 8)));
        assert(c.responseHash == keccak256(abi.encodePacked(TAG, psi, abi.encode(FEED, price, ts))));
        // V3: the update is on the fixed-rate channel and its timestamp is
        // the channel's first grid time at or after validAfter
        assert(uint8(payload[12]) == CHANNEL);
        // (PERIOD_US divides 1e6: the first grid time is validAfter * 1e6)
        assert(uint256(ts) == uint256(c.validAfter) * 1e6);
        // V4: the material commitment
        assert(keccak256(m) == c.materialCommit);
    }

    function check_V1to4_len28() public view {
        _passImplies(28, 0);
    }

    function check_V1to4_len28_tail5() public view {
        _passImplies(28, 5);
    }

    function check_V1to4_len41() public view {
        _passImplies(41, 0);
    }

    function check_V1to4_len64_tail32() public view {
        _passImplies(64, 32);
    }

    /// V1 to V4 for every value of the length field, with the material
    /// length fixed at 32 + 71 + 40: lengths 0..40 run the layout with the
    /// rest as tail (one check per length); a larger length field must be
    /// rejected (check_lengthBeyondMaterialRejected).
    function check_V1to4_total40_len00() public view {
        _passImplies(0, 40);
    }

    function check_V1to4_total40_len01() public view {
        _passImplies(1, 39);
    }

    function check_V1to4_total40_len02() public view {
        _passImplies(2, 38);
    }

    function check_V1to4_total40_len03() public view {
        _passImplies(3, 37);
    }

    function check_V1to4_total40_len04() public view {
        _passImplies(4, 36);
    }

    function check_V1to4_total40_len05() public view {
        _passImplies(5, 35);
    }

    function check_V1to4_total40_len06() public view {
        _passImplies(6, 34);
    }

    function check_V1to4_total40_len07() public view {
        _passImplies(7, 33);
    }

    function check_V1to4_total40_len08() public view {
        _passImplies(8, 32);
    }

    function check_V1to4_total40_len09() public view {
        _passImplies(9, 31);
    }

    function check_V1to4_total40_len10() public view {
        _passImplies(10, 30);
    }

    function check_V1to4_total40_len11() public view {
        _passImplies(11, 29);
    }

    function check_V1to4_total40_len12() public view {
        _passImplies(12, 28);
    }

    function check_V1to4_total40_len13() public view {
        _passImplies(13, 27);
    }

    function check_V1to4_total40_len14() public view {
        _passImplies(14, 26);
    }

    function check_V1to4_total40_len15() public view {
        _passImplies(15, 25);
    }

    function check_V1to4_total40_len16() public view {
        _passImplies(16, 24);
    }

    function check_V1to4_total40_len17() public view {
        _passImplies(17, 23);
    }

    function check_V1to4_total40_len18() public view {
        _passImplies(18, 22);
    }

    function check_V1to4_total40_len19() public view {
        _passImplies(19, 21);
    }

    function check_V1to4_total40_len20() public view {
        _passImplies(20, 20);
    }

    function check_V1to4_total40_len21() public view {
        _passImplies(21, 19);
    }

    function check_V1to4_total40_len22() public view {
        _passImplies(22, 18);
    }

    function check_V1to4_total40_len23() public view {
        _passImplies(23, 17);
    }

    function check_V1to4_total40_len24() public view {
        _passImplies(24, 16);
    }

    function check_V1to4_total40_len25() public view {
        _passImplies(25, 15);
    }

    function check_V1to4_total40_len26() public view {
        _passImplies(26, 14);
    }

    function check_V1to4_total40_len27() public view {
        _passImplies(27, 13);
    }

    function check_V1to4_total40_len28() public view {
        _passImplies(28, 12);
    }

    function check_V1to4_total40_len29() public view {
        _passImplies(29, 11);
    }

    function check_V1to4_total40_len30() public view {
        _passImplies(30, 10);
    }

    function check_V1to4_total40_len31() public view {
        _passImplies(31, 9);
    }

    function check_V1to4_total40_len32() public view {
        _passImplies(32, 8);
    }

    function check_V1to4_total40_len33() public view {
        _passImplies(33, 7);
    }

    function check_V1to4_total40_len34() public view {
        _passImplies(34, 6);
    }

    function check_V1to4_total40_len35() public view {
        _passImplies(35, 5);
    }

    function check_V1to4_total40_len36() public view {
        _passImplies(36, 4);
    }

    function check_V1to4_total40_len37() public view {
        _passImplies(37, 3);
    }

    function check_V1to4_total40_len38() public view {
        _passImplies(38, 2);
    }

    function check_V1to4_total40_len39() public view {
        _passImplies(39, 1);
    }

    function check_V1to4_total40_len40() public view {
        _passImplies(40, 0);
    }

    function check_lengthBeyondMaterialRejected() public view {
        P5Ctx memory c = _ctx();
        bytes memory m = svm.createBytes(32 + 71 + 40, "material");
        hvm.assume(_be(m, 32 + 69, 2) > 40);
        assert(!_call(c, m));
    }

    /// Vacuity: a pass is reachable (this check is expected to FAIL with a
    /// counterexample that is a passing input).
    function check_vacuity_passReachable() public view {
        P5Ctx memory c = _ctx();
        bytes memory m = _material(28, 0);
        assert(!_call(c, m));
    }

    /// V3 stated as rejection: a timestamp outside [validAfter, validAfter +
    /// one period) never passes.
    function check_V3_outsideWindowRejected() public view {
        P5Ctx memory c = _ctx();
        bytes memory m = _material(28, 0);
        uint256 ts = _be(m, 32 + 71 + 4, 8);
        hvm.assume(ts < uint256(c.validAfter) * 1e6 || ts >= uint256(c.validAfter) * 1e6 + PERIOD_US);
        assert(!_call(c, m));
    }

    /// V6: the result does not depend on the block, the time or the caller.
    function check_V6_deterministic() public {
        P5Ctx memory c = _ctx();
        bytes memory m = _material(28, 0);
        bool a = _call(c, m);
        hvm.roll(svm.createUint(64, "block2"));
        hvm.warp(svm.createUint(64, "time2"));
        hvm.prank(svm.createAddress("caller2"));
        bool b = _callExt(c, m);
        assert(a == b);
    }

    function _callExt(P5Ctx memory c, bytes memory m) internal view returns (bool) {
        try v.verify(c, m) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    /// V5: does a pass imply that the update is the signer's first one at or
    /// after validAfter? Two signed updates (ts1 < ts2), the first at or
    /// after validAfter, on any channel; the leaf claims the later one. The
    /// check asserts that the later one is rejected.
    function check_V5_firstUpdateOnly() public view {
        P5Ctx memory c = _ctx();
        bytes memory m1 = _material(28, 0);
        bytes memory m2 = _material(28, 0);
        bytes memory p1 = _slice(m1, 32 + 71, 28);
        uint256 ts1 = _be(p1, 4, 8);
        uint256 ts2 = _be(m2, 32 + 71 + 4, 8);
        // update 1 is a valid signed update of the feed, earlier and in the window
        hvm.assume(ecrecover(keccak256(p1), uint8(m1[32 + 68]) + 27, _word(m1, 36), _word(m1, 68)) == SIGNER);
        hvm.assume(ts1 >= uint256(c.validAfter) * 1e6 && ts1 < ts2);
        assert(!_call(c, m2));
    }

    /// V5, the tie of rule 1-1 (b): two different signed payloads with the
    /// same timestamp on the channel. The rule puts the one with the smaller
    /// digest first; the contract sees one update and cannot order them, so
    /// this check is expected to FAIL (a counterexample). The unique-input
    /// feed condition of the rule (at most one signed update per grid time on
    /// the channel) is what excludes it; it is a condition on the feed, not
    /// on the contract.
    function check_V5_tieOrderNotDecided() public view {
        P5Ctx memory c = _ctx();
        bytes memory m1 = _material(28, 0);
        bytes memory m2 = _material(28, 0);
        bytes memory p1 = _slice(m1, 32 + 71, 28);
        bytes memory p2 = _slice(m2, 32 + 71, 28);
        hvm.assume(ecrecover(keccak256(p1), uint8(m1[32 + 68]) + 27, _word(m1, 36), _word(m1, 68)) == SIGNER);
        hvm.assume(_be(p1, 4, 8) == _be(p2, 4, 8) && uint8(p1[12]) == uint8(p2[12]));
        hvm.assume(uint256(keccak256(p1)) < uint256(keccak256(p2)));
        assert(!_call(c, m2));
    }
}
