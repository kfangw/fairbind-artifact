// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { P5Ctx, IP5Verifier } from "./P5Ref.sol";
import { RLPReader } from "../vendor/optimism/rlp/RLPReader.sol";
import { SecureMerkleTrie } from "../vendor/optimism/trie/SecureMerkleTrie.sol";

/// Tier 1a verification contract: a Pyth Pro (Lazer) shaped signed update of
/// one feed on one fixed-rate channel, the signer and feed fixed as
/// immutables (no storage). Material = psi (32 bytes) || update. The
/// response is abi.encode(feed, price, timestamp) and must hash to the
/// leaf's h_r = H(tag || psi || r).
///
/// Canonical input (rule 1-1 (b)): the first update with timestamp >=
/// validAfter. The contract binds the update to the fixed-rate channel and
/// requires its timestamp to be the first grid time of that channel at or
/// after validAfter, ceil(validAfter * 1e6 / PERIOD_US) * PERIOD_US. On a
/// channel that publishes one update per grid time (the unique-input feed
/// condition) that update is the first one after validAfter; a missing grid
/// update leaves the honest seller without a proof (w), never a pass.
/// PERIOD_US divides 1e6, so that time is validAfter * 1e6 itself and the
/// contract compares with it directly. The rule's
/// window ends at timestamp <= time(A_e) * 1e6 - delta_sig; the settlement
/// needs block.timestamp > validAfter (EIP-3009) and the anchor comes after
/// the settlement, so time(A_e) >= validAfter + 1 and the update lies in the
/// rule's window whenever the profile's delta_sig is at most 1 s. The
/// contract does not read time(A_e); a profile with a larger delta_sig is
/// outside what it decides.
///
/// ecrecover is called with a constant gas argument, so the runtime code has
/// no GAS opcode (rule R1 (b)(1)); with less gas left the precompile call
/// fails and the update is rejected.
contract P5LazerVerifier is IP5Verifier {
    uint32 internal constant LAZER_EVM_MAGIC = 706910618;
    uint32 internal constant LAZER_PAYLOAD_MAGIC = 2479346549;
    uint8 internal constant CHANNEL = 3; // fixed_rate@200ms
    uint256 internal constant PERIOD_US = 200_000; // documents the channel; divides 1e6
    uint256 internal constant ECRECOVER_GAS = 3000;
    uint256 internal constant HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    address public immutable signer;
    uint32 public immutable feedId;

    constructor(address signer_, uint32 feedId_) {
        signer = signer_;
        feedId = feedId_;
    }

    function verify(P5Ctx calldata c, bytes calldata material) external view returns (bool) {
        if (keccak256(material) != c.materialCommit) return false;
        bytes32 psi = bytes32(material[0:32]);
        bytes calldata update = material[32:];
        if (update.length < 71 || uint32(bytes4(update[0:4])) != LAZER_EVM_MAGIC) return false;
        uint256 len = uint16(bytes2(update[69:71]));
        if (update.length < 71 + len) return false;
        bytes calldata payload = update[71:71 + len];
        address s = _recover(keccak256(payload), bytes32(update[4:36]), bytes32(update[36:68]), uint8(update[68]) + 27);
        if (s == address(0) || s != signer) return false;
        if (uint32(bytes4(payload[0:4])) != LAZER_PAYLOAD_MAGIC) return false;
        uint64 ts = uint64(bytes8(payload[4:12]));
        if (uint8(payload[12]) != CHANNEL) return false;
        // the first grid time at or after validAfter (PERIOD_US divides 1e6)
        if (uint256(ts) != uint256(c.validAfter) * 1e6) return false;
        if (uint8(payload[13]) < 1 || uint32(bytes4(payload[14:18])) != feedId) return false;
        if (uint8(payload[18]) < 1 || uint8(payload[19]) != 0) return false;
        int64 price = int64(uint64(bytes8(payload[20:28])));
        bytes memory r = abi.encode(feedId, price, ts);
        return keccak256(abi.encodePacked(TAG, psi, r)) == c.responseHash;
    }

    function _recover(bytes32 digest, bytes32 r, bytes32 s, uint8 v) internal view returns (address a) {
        if (uint256(s) > HALF_N || (v != 27 && v != 28)) return address(0);
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, digest)
            mstore(add(p, 0x20), v)
            mstore(add(p, 0x40), r)
            mstore(add(p, 0x60), s)
            mstore(0, 0)
            let ok := staticcall(ECRECOVER_GAS, 1, p, 0x80, 0, 0x20)
            if and(ok, eq(returndatasize(), 0x20)) { a := mload(0) }
        }
    }
}

/// Tier 0 verification contract. The anchor stores the hash of the block
/// before it (the settlement contract passes it in the context); material =
/// abi.encode(header, accountProof, storageProof, refBlock, psi, refHeader,
/// nextHeader), where header is the anchored block's header. The hash of
/// block refBlock + 1 is read from the EIP-2935 history contract by a
/// storage proof under header (or is the anchored hash itself when refBlock
/// + 1 is that block); nextHeader must hash to it and refHeader to its parent
/// hash. The reference block must be canonical (rule 0-1 (a)): the last
/// block whose timestamp is at most validAfter, checked as
/// timestamp(refHeader) <= validAfter < timestamp(nextHeader). The response
/// is abi.encode(refBlock, refHash). The trie keeps a slot value without
/// leading zero bytes; it is read right-aligned, and a value longer than 32
/// bytes or empty is rejected. A slot absent from the trie makes the trie
/// library revert (rejection).
contract P5StorageVerifier is IP5Verifier {
    address internal constant HISTORY = 0x0000F90827F1C53a10cb7A02335B175320002935;
    uint256 internal constant WINDOW = 8191;
    bytes32 internal constant TAG = keccak256("p5/response/v1");

    function verify(P5Ctx calldata c, bytes calldata material) external pure returns (bool) {
        if (keccak256(material) != c.materialCommit) return false;
        (
            bytes memory header,
            bytes[] memory ap,
            bytes[] memory sp,
            uint256 refBlock,
            bytes32 psi,
            bytes memory refHeader,
            bytes memory nextHeader
        ) = abi.decode(material, (bytes, bytes[], bytes[], uint256, bytes32, bytes, bytes));
        if (keccak256(header) != c.anchoredHash) return false;
        RLPReader.RLPItem[] memory f = RLPReader.readList(header);
        uint256 num = _uint(RLPReader.readBytes(f[8]));
        // block refBlock + 1 lies in [num - WINDOW, num]
        if (refBlock >= num || refBlock + 1 + WINDOW < num) return false;
        bytes32 nextHash = refBlock + 1 == num ? c.anchoredHash : _historyHash(f, ap, sp, refBlock + 1);
        if (nextHash == bytes32(0) || keccak256(nextHeader) != nextHash) return false;
        RLPReader.RLPItem[] memory fn = RLPReader.readList(nextHeader);
        if (_uint(RLPReader.readBytes(fn[8])) != refBlock + 1) return false;
        bytes32 refHash = bytes32(RLPReader.readBytes(fn[0]));
        if (keccak256(refHeader) != refHash) return false;
        RLPReader.RLPItem[] memory fr = RLPReader.readList(refHeader);
        if (_uint(RLPReader.readBytes(fr[8])) != refBlock) return false;
        if (_uint(RLPReader.readBytes(fr[11])) > c.validAfter) return false;
        if (_uint(RLPReader.readBytes(fn[11])) <= c.validAfter) return false;
        bytes memory r = abi.encode(refBlock, refHash);
        return keccak256(abi.encodePacked(TAG, psi, r)) == c.responseHash;
    }

    /// The block hash the history contract keeps for block `b` in the state
    /// under the header's state root, right-aligned; zero when the value is
    /// empty or longer than 32 bytes.
    function _historyHash(RLPReader.RLPItem[] memory f, bytes[] memory ap, bytes[] memory sp, uint256 b)
        internal
        pure
        returns (bytes32)
    {
        bytes32 stateRoot = bytes32(RLPReader.readBytes(f[3]));
        bytes memory acct = SecureMerkleTrie.get(abi.encodePacked(HISTORY), ap, stateRoot);
        RLPReader.RLPItem[] memory af = RLPReader.readList(acct);
        bytes32 storageRoot = bytes32(RLPReader.readBytes(af[2]));
        bytes memory v = SecureMerkleTrie.get(abi.encodePacked(bytes32(b % WINDOW)), sp, storageRoot);
        (bool ok, bytes32 w) = P5Slot.word(RLPReader.readBytes(v));
        return ok ? w : bytes32(0);
    }

    function _uint(bytes memory b) internal pure returns (uint256 x) {
        for (uint256 i; i < b.length; i++) x = (x << 8) | uint8(b[i]);
    }
}

/// A storage slot value as the trie keeps it (big-endian, leading zero bytes
/// dropped) read back as the 256-bit word, right-aligned. Empty or longer
/// than 32 bytes: not a word.
library P5Slot {
    function word(bytes memory raw) internal pure returns (bool ok, bytes32 w) {
        if (raw.length == 0 || raw.length > 32) return (false, bytes32(0));
        uint256 x;
        for (uint256 i; i < raw.length; i++) x = (x << 8) | uint8(raw[i]);
        return (true, bytes32(x));
    }
}
