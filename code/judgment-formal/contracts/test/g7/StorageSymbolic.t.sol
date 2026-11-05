// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SymTest } from "./Svm.sol";
import { P5Ctx } from "../g10/p5/P5Ref.sol";
import { P5StorageVerifier, P5Slot } from "../g10/p5/P5Verifiers.sol";
import { RLPReader } from "../g10/vendor/optimism/rlp/RLPReader.sol";
import { SyntheticHistoryFixture as F } from "./SyntheticHistoryFixture.sol";

/// Symbolic checks of the tier 0 storage-proof verification contract.
/// The anchored header, the reference and next headers and the two trie
/// proofs are the synthetic fixture (gen_synthetic_fixture.py); psi and
/// every context field, and in some checks the reference block, are
/// symbolic. keccak256 is an injective uninterpreted function.
contract StorageSymbolicTest is SymTest {
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    uint256 internal constant WINDOW = 8191;

    P5StorageVerifier internal v;

    function setUp() public {
        v = new P5StorageVerifier();
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

    function _call(P5Ctx memory c, bytes memory m) internal view returns (bool) {
        try v.verify(c, m) returns (bool ok) {
            return ok;
        } catch {
            return false;
        }
    }

    function _ts(uint256 b) internal pure returns (uint256) {
        return F.T0 + 2 * b; // the synthetic chain's timestamps
    }

    function _mN(uint256 refBlock, bytes32 psi) internal pure returns (bytes memory) {
        return abi.encode(F.header(), F.accountProof(), F.nStorageProof(), refBlock, psi, F.nRefHeader(), F.nNextHeader());
    }

    /// W1 to W5 with the reference block fixed (case N) and the context and
    /// psi symbolic: what a pass implies.
    function check_W1to5_fixedRef() public view {
        P5Ctx memory c = _ctx();
        bytes32 psi = svm.createBytes32("psi");
        bytes memory m = _mN(F.N_REF, psi);
        if (!_call(c, m)) return;
        assert(c.anchoredHash == keccak256(F.header())); // W1
        assert(c.responseHash == keccak256(abi.encodePacked(TAG, psi, abi.encode(F.N_REF, F.N_REF_HASH)))); // W3, W4
        assert(c.materialCommit == keccak256(m)); // W4
        assert(_ts(F.N_REF) <= c.validAfter && c.validAfter < _ts(F.N_REF + 1)); // W5
    }

    /// W1 to W4 with a symbolic reference block (expected to stop at the
    /// tool's symbolic memory offsets, as in v1).
    function check_W1to4_symbolicRef() public view {
        P5Ctx memory c = _ctx();
        uint256 refBlock = svm.createUint256("refBlock");
        bytes32 psi = svm.createBytes32("psi");
        bytes memory m = _mN(refBlock, psi);
        if (!_call(c, m)) return;
        assert(refBlock == F.N_REF);
        assert(c.responseHash == keccak256(abi.encodePacked(TAG, psi, abi.encode(F.N_REF, F.N_REF_HASH))));
    }

    /// W1 stated as rejection.
    function check_W1_otherAnchoredHashRejected() public view {
        P5Ctx memory c = _ctx();
        hvm.assume(c.anchoredHash != F.BLOCK_HASH);
        bytes memory m = _mN(F.N_REF, svm.createBytes32("psi"));
        c.materialCommit = keccak256(m);
        assert(!_call(c, m));
    }

    /// W2 stated as rejection: block refBlock + 1 outside [num - 8191, num].
    function check_W2_outsideWindowRejected() public view {
        P5Ctx memory c = _ctx();
        c.anchoredHash = F.BLOCK_HASH;
        uint256 refBlock = svm.createUint256("refBlock");
        hvm.assume(refBlock >= F.BLOCK_NUMBER || refBlock + 1 + WINDOW < F.BLOCK_NUMBER);
        bytes memory m = _mN(refBlock, svm.createBytes32("psi"));
        c.materialCommit = keccak256(m);
        assert(!_call(c, m));
    }

    /// W5 stated as rejection: a validAfter for which block N_REF is not the
    /// last block with timestamp <= validAfter is rejected.
    function check_W5_nonCanonicalRejected() public view {
        P5Ctx memory c = _ctx();
        c.anchoredHash = F.BLOCK_HASH;
        hvm.assume(c.validAfter < _ts(F.N_REF) || c.validAfter >= _ts(F.N_REF + 1));
        bytes memory m = _mN(F.N_REF, svm.createBytes32("psi"));
        c.materialCommit = keccak256(m);
        assert(!_call(c, m));
    }

    /// W3, the value width, on the contract's own conversion (P5Slot.word):
    /// for every 256-bit slot value, the trie's encoding (leading zeros
    /// dropped, RLP string) reads back as that value.
    function check_W3_valueWidth() public pure {
        uint256 w = svm.createUint256("slotValue");
        hvm.assume(w != 0); // a zero slot is absent from the trie
        bytes memory enc = _rlpString(_trim(w));
        (bool ok, bytes32 got) = P5Slot.word(RLPReader.readBytes(enc));
        assert(ok && got == bytes32(w));
    }

    /// W3, the leading-zero case through the whole contract (case Z: the
    /// next block's hash starts with a zero byte): a pass implies the true
    /// reference hash.
    function check_W3_leadingZeroPassImpliesTrueHash() public view {
        P5Ctx memory c = _ctx();
        bytes32 psi = svm.createBytes32("psi");
        bytes memory m =
            abi.encode(F.header(), F.accountProof(), F.zStorageProof(), F.Z_REF, psi, F.zRefHeader(), F.zNextHeader());
        if (!_call(c, m)) return;
        assert(c.responseHash == keccak256(abi.encodePacked(TAG, psi, abi.encode(F.Z_REF, F.Z_REF_HASH))));
    }

    /// Empty slot (reviewer point (c)): a storage proof for a slot absent
    /// from the ring is rejected for every context and psi.
    function check_Wempty_absentSlotRejected() public view {
        P5Ctx memory c = _ctx();
        bytes memory m = abi.encode(
            F.header(), F.accountProof(), F.eStorageProof(), F.E_NEXT - 1, svm.createBytes32("psi"), F.nRefHeader(), F.nNextHeader()
        );
        assert(!_call(c, m));
    }

    /// Vacuity: case N passes for some context (expected to FAIL).
    function check_vacuity_fixturePasses() public view {
        P5Ctx memory c = _ctx();
        assert(!_call(c, _mN(F.N_REF, bytes32(0))));
    }

    /// Vacuity of the leading-zero case: case Z passes for some context
    /// (expected to FAIL).
    function check_vacuity_leadingZeroPasses() public view {
        P5Ctx memory c = _ctx();
        bytes memory m =
            abi.encode(F.header(), F.accountProof(), F.zStorageProof(), F.Z_REF, bytes32(0), F.zRefHeader(), F.zNextHeader());
        assert(!_call(c, m));
    }

    function _trim(uint256 w) internal pure returns (bytes memory b) {
        uint256 n = 32;
        while (n > 0 && (w >> (8 * (n - 1))) == 0) n--;
        b = new bytes(n);
        for (uint256 i; i < n; i++) b[i] = bytes1(uint8(w >> (8 * (n - 1 - i))));
    }

    function _rlpString(bytes memory b) internal pure returns (bytes memory) {
        if (b.length == 1 && uint8(b[0]) < 0x80) return b;
        return abi.encodePacked(bytes1(uint8(0x80 + b.length)), b);
    }
}
