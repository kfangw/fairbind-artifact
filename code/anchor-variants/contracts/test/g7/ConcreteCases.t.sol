// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "../sdk/SdkBase.sol";
import { P5Ctx } from "../g10/p5/P5Ref.sol";
import { SyntheticHistoryFixture as F } from "./SyntheticHistoryFixture.sol";

/// Concrete cases of the three counterexamples of G7 v1 (V5, W3, W5) and of
/// the reviewer points (GAS opcode, empty slot) on the fixed verification
/// contracts. Each test passes when the fixed behaviour holds; on the
/// contracts of c5325ca the V5, W3 and W5 tests fail.
contract ConcreteCasesTest is SdkBase {
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    bytes32 internal constant PSI = keccak256("g7 case psi");

    function _ok1a(bytes memory m, P5Ctx memory c) internal view returns (bool) {
        try lazer.verify(c, m) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    function _ok0(bytes memory m, P5Ctx memory c) internal view returns (bool) {
        try stor.verify(c, m) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    function _ctx1a(bytes memory m, uint64 ts, int64 price) internal pure returns (P5Ctx memory c) {
        c.validAfter = VALID_AFTER;
        c.responseHash = keccak256(abi.encodePacked(TAG, PSI, abi.encode(FEED, price, ts)));
        c.materialCommit = keccak256(m);
    }

    function _case1a(uint64 ts, int64 price) internal returns (bool) {
        bytes memory m = abi.encodePacked(PSI, _lazerUpdate(ts, price, FEED, feedKey));
        return _ok1a(m, _ctx1a(m, ts, price));
    }

    /// V5: the signer's update at validAfter (the first grid time of the
    /// channel) passes; later updates in the old 60 s window do not.
    function test_V5_onlyFirstUpdatePasses() public {
        uint64 t0 = VALID_AFTER * 1e6;
        require(_case1a(t0, 189_000_000_000), "first update passes");
        require(!_case1a(t0 + 30e6, 191_500_000_000), "update 30 s later rejected");
        require(!_case1a(t0 + 200_000, 191_500_000_000), "next grid update rejected");
        require(!_case1a(t0 + 1, 191_500_000_000), "off-grid update rejected");
        require(!_case1a(t0 + 60e6, 191_500_000_000), "old window edge rejected");
        require(!_case1a(t0 - 200_000, 189_000_000_000), "update before validAfter rejected");
    }

    /// V5, the channel byte: an update of the feed on another channel is
    /// rejected.
    function test_V5_otherChannelRejected() public {
        uint64 t = VALID_AFTER * 1e6;
        int64 p = 189_000_000_000;
        bytes memory payload = abi.encodePacked(uint32(2479346549), t, uint8(1), uint8(1), FEED, uint8(1), uint8(0), p);
        (uint8 vv, bytes32 r, bytes32 s) = vm.sign(feedKey, keccak256(payload));
        bytes memory m =
            abi.encodePacked(PSI, abi.encodePacked(uint32(706910618), r, s, uint8(vv - 27), uint16(payload.length), payload));
        require(!_ok1a(m, _ctx1a(m, t, p)), "channel 1 update rejected");
    }

    /// GAS (R1 (b)(1)): over call gas from 2,000 to 40,000 the honest update
    /// passes exactly above one threshold (a pass never needs less gas than
    /// a rejection), and the runtime code has no GAS opcode (scan_opcodes.py).
    function test_GAS_passMonotoneInCallGas() public {
        uint64 t0 = VALID_AFTER * 1e6;
        bytes memory m = abi.encodePacked(PSI, _lazerUpdate(t0, 7, FEED, feedKey));
        P5Ctx memory c = _ctx1a(m, t0, 7);
        bool seen;
        for (uint256 g = 2_000; g <= 40_000; g += 250) {
            bool ok;
            try lazer.verify{ gas: g }(c, m) returns (bool r) {
                ok = r;
            } catch { }
            require(!seen || ok, "a pass at lower gas, a rejection at higher gas");
            seen = seen || ok;
        }
        require(seen, "passes with enough gas");
    }

    function _m0(bytes[] memory sp, uint256 ref, bytes memory rh, bytes memory nh) internal pure returns (bytes memory) {
        return abi.encode(F.header(), F.accountProof(), sp, ref, PSI, rh, nh);
    }

    function _ctx0(bytes memory m, uint256 ref, bytes32 h, uint64 va) internal pure returns (P5Ctx memory c) {
        c.validAfter = va;
        c.anchoredHash = F.BLOCK_HASH;
        c.materialCommit = keccak256(m);
        c.responseHash = keccak256(abi.encodePacked(TAG, PSI, abi.encode(ref, h)));
    }

    function _ts(uint256 b) internal pure returns (uint64) {
        return uint64(F.T0 + 2 * b);
    }

    /// W3: the next block's hash starts with a zero byte (the trie keeps 31
    /// bytes). The honest response passes and the left-shifted value does not.
    function test_W3_leadingZeroHash() public view {
        require(uint8(F.Z_NEXT_HASH[0]) == 0, "fixture hash has a leading zero byte");
        bytes memory m = _m0(F.zStorageProof(), F.Z_REF, F.zRefHeader(), F.zNextHeader());
        uint64 va = _ts(F.Z_REF);
        require(_ok0(m, _ctx0(m, F.Z_REF, F.Z_REF_HASH, va)), "honest response passes");
        require(!_ok0(m, _ctx0(m, F.Z_REF, F.Z_NEXT_HASH << 8, va)), "shifted value rejected");
    }

    /// W5: block N_REF passes exactly for the validAfter values whose last
    /// block with timestamp <= validAfter it is.
    function test_W5_canonicalOnly() public view {
        bytes memory m = _m0(F.nStorageProof(), F.N_REF, F.nRefHeader(), F.nNextHeader());
        uint64 a = _ts(F.N_REF);
        uint64 b = _ts(F.N_REF + 1);
        require(_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, a)), "ts(ref)");
        require(_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, b - 1)), "ts(next) - 1");
        require(!_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, a - 1)), "before ts(ref)");
        require(!_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, b)), "ts(next)");
        require(!_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, 0)), "0");
        require(!_ok0(m, _ctx0(m, F.N_REF, F.N_REF_HASH, type(uint64).max)), "max");
    }

    /// W5, the last block before the anchored one: the next header is the
    /// anchored header itself.
    function test_W5_lastBlockBeforeAnchor() public view {
        bytes memory m = _m0(new bytes[](0), F.L_REF, F.lRefHeader(), F.lNextHeader());
        require(_ok0(m, _ctx0(m, F.L_REF, F.L_REF_HASH, _ts(F.L_REF))), "L passes");
    }

    /// Empty slot (reviewer point (c)): a proof for a slot absent from the
    /// ring is rejected (the trie library reverts).
    function test_Wempty_absentSlotRejected() public view {
        bytes memory m = _m0(F.eStorageProof(), F.E_NEXT - 1, F.nRefHeader(), F.nNextHeader());
        require(!_ok0(m, _ctx0(m, F.E_NEXT - 1, bytes32(0), _ts(F.E_NEXT - 1))), "absent slot rejected");
    }

    /// W3 for other slots (fuzz, not a proof): with case N's proofs and
    /// headers, any other reference block in the window is rejected.
    function testFuzz_W3_otherRefInWindowRejected(uint256 ref, bytes32 h, uint64 va) public view {
        ref = F.BLOCK_NUMBER - 8191 - 1 + (ref % 8191);
        if (ref == F.N_REF) return;
        bytes memory m = _m0(F.nStorageProof(), ref, F.nRefHeader(), F.nNextHeader());
        require(!_ok0(m, _ctx0(m, ref, h, va)), "other slot rejected");
        require(!_ok0(m, _ctx0(m, ref, F.N_REF_HASH, va)), "other slot with the proven value rejected");
    }
}
