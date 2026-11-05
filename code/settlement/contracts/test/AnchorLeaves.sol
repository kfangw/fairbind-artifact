// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import { FairBindMerkle } from "../src/FairBindMerkle.sol";

/// Off-chain side of the anchor rule (ADR 0026): builds the (nonce,
/// receiptLeaf) list an anchor carries and the merkle-v1 root the contract
/// must compute from it, without calling the contract.
library AnchorLeaves {
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/epoch-leaf/v1");
    bytes32 internal constant NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");

    function entryHash(bytes32 nonce, bytes32 receiptLeaf) internal pure returns (bytes32) {
        return keccak256(abi.encode(LEAF_DOMAIN, nonce, receiptLeaf));
    }

    /// Level zero of the tree: the entry hash of each pair, in list order.
    function hashes(FairBindMerkle.ReceiptEntry[] memory list) internal pure returns (bytes32[] memory out) {
        out = new bytes32[](list.length);
        for (uint256 i; i < list.length; i++) out[i] = entryHash(list[i].nonce, list[i].receiptLeaf);
    }

    /// merkle-v1 root over an ordered level zero; an odd last node pairs with itself.
    function rootOf(bytes32[] memory entries) internal pure returns (bytes32) {
        uint256 n = entries.length;
        if (n == 0) return bytes32(0);
        bytes32[] memory level = new bytes32[](n);
        for (uint256 i; i < n; i++) level[i] = entries[i];
        while (n > 1) {
            uint256 w = (n + 1) / 2;
            bytes32[] memory up = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < n ? level[2 * i + 1] : left;
                up[i] = keccak256(abi.encode(NODE_DOMAIN, left, right));
            }
            level = up;
            n = w;
        }
        return level[0];
    }

    /// merkle-v1 root of an anchor list of pairs.
    function rootOf(FairBindMerkle.ReceiptEntry[] memory list) internal pure returns (bytes32) {
        return rootOf(hashes(list));
    }

    /// A one-entry list holding the pair (nonce, receiptLeaf).
    function pair(bytes32 nonce, bytes32 receiptLeaf)
        internal
        pure
        returns (FairBindMerkle.ReceiptEntry[] memory list)
    {
        list = new FairBindMerkle.ReceiptEntry[](1);
        list[0] = FairBindMerkle.ReceiptEntry(nonce, receiptLeaf);
    }

    /// A list of `count` filler pairs derived from `seed`, for tests that
    /// anchor an epoch without needing inclusion proofs. The nonces ascend
    /// from a point derived from the seed, so they are no purchase's nonce in
    /// practice; the first leaf is `seed`.
    function filled(bytes32 seed, uint256 count)
        internal
        pure
        returns (FairBindMerkle.ReceiptEntry[] memory list)
    {
        list = new FairBindMerkle.ReceiptEntry[](count);
        uint256 base = uint256(keccak256(abi.encode("fairbind/test-filler-nonce", seed))) >> 8;
        for (uint256 i; i < count; i++) {
            bytes32 leaf = i == 0 ? seed : keccak256(abi.encode("fairbind/test-filler-entry", seed, i));
            list[i] = FairBindMerkle.ReceiptEntry(bytes32(base + i), leaf);
        }
    }

    /// A one-entry filler list (`filled(seed, 1)`).
    function one(bytes32 seed) internal pure returns (FairBindMerkle.ReceiptEntry[] memory) {
        return filled(seed, 1);
    }
}
