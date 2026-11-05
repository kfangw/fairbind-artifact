// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

library FairBindMerkle {
    bytes32 internal constant LEAF_DOMAIN = keccak256("fairbind/epoch-leaf/v1");
    bytes32 internal constant NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");

    function entryHash(bytes32 nonce, bytes32 receiptLeaf) internal pure returns (bytes32) {
        return keccak256(abi.encode(LEAF_DOMAIN, nonce, receiptLeaf));
    }

    function nodeHash(bytes32 left, bytes32 right) internal pure returns (bytes32) {
        return keccak256(abi.encode(NODE_DOMAIN, left, right));
    }

    /// One level-zero entry of an epoch tree, as an anchor carries it (ADR 0026).
    struct ReceiptEntry {
        bytes32 nonce;
        bytes32 receiptLeaf;
    }

    /// True when the nonces of `entries` increase strictly, so the list is
    /// sorted and holds no nonce twice.
    function strictlyAscending(ReceiptEntry[] calldata entries) internal pure returns (bool ok) {
        ok = true;
        uint256 n = entries.length;
        assembly ("memory-safe") {
            let p := entries.offset
            let prev := calldataload(p)
            for { let i := 1 } lt(i, n) { i := add(i, 1) } {
                let cur := calldataload(add(p, shl(6, i)))
                if iszero(gt(cur, prev)) {
                    ok := 0
                    break
                }
                prev := cur
            }
        }
    }

    /// Root of the merkle-v1 tree whose level zero is entryHash(nonce,
    /// receiptLeaf) of each entry in the given order: adjacent nodes pair left
    /// to right and an odd last node pairs with itself. A single entry's hash
    /// is the root; no entries give the zero root. Every hash is taken in
    /// scratch memory past the free memory pointer, so no level allocates per
    /// node.
    function computeRoot(ReceiptEntry[] calldata entries) internal pure returns (bytes32 result) {
        uint256 width = entries.length;
        if (width == 0) return bytes32(0);
        if (width == 1) return entryHash(entries[0].nonce, entries[0].receiptLeaf);
        bytes32 leafDomain = LEAF_DOMAIN;
        bytes32 nodeDomain = NODE_DOMAIN;
        uint256 next = (width + 1) >> 1;
        bytes32[] memory level = new bytes32[](next);
        assembly ("memory-safe") {
            // scratch holds abi.encode(domain, a, b); it is not allocated.
            let scratch := mload(0x40)
            let src := entries.offset
            let dst := add(level, 0x20)
            // Level one from the (nonce, receiptLeaf) pairs in the call data.
            for { let i := 0 } lt(i, next) { i := add(i, 1) } {
                let pair := add(src, shl(7, i))
                mstore(scratch, leafDomain)
                calldatacopy(add(scratch, 0x20), pair, 0x40)
                let left := keccak256(scratch, 0x60)
                let right := left
                if lt(add(shl(1, i), 1), width) {
                    calldatacopy(add(scratch, 0x20), add(pair, 0x40), 0x40)
                    right := keccak256(scratch, 0x60)
                }
                mstore(scratch, nodeDomain)
                mstore(add(scratch, 0x20), left)
                mstore(add(scratch, 0x40), right)
                mstore(add(dst, shl(5, i)), keccak256(scratch, 0x60))
            }
            width := next
            mstore(scratch, nodeDomain)
            // Higher levels in place: slot i is written after slots 2i and 2i + 1 are read.
            for { } gt(width, 1) { } {
                next := shr(1, add(width, 1))
                for { let i := 0 } lt(i, next) { i := add(i, 1) } {
                    let pair := add(dst, shl(6, i))
                    let left := mload(pair)
                    let right := left
                    if lt(add(shl(1, i), 1), width) { right := mload(add(pair, 0x20)) }
                    mstore(add(scratch, 0x20), left)
                    mstore(add(scratch, 0x40), right)
                    mstore(add(dst, shl(5, i)), keccak256(scratch, 0x60))
                }
                width := next
            }
            result := mload(dst)
        }
    }

    function verify(
        bytes32 root,
        bytes32 nonce,
        bytes32 receiptLeaf,
        uint32 index,
        uint32 count,
        bytes32[] memory siblings
    ) internal pure returns (bool) {
        if (count == 0 || index >= count) return false;
        bytes32 hash = entryHash(nonce, receiptLeaf);
        uint256 cursor = index;
        uint256 width = count;
        for (uint256 i; i < siblings.length; i++) {
            if (width <= 1) return false;
            if (cursor & 1 == 0) {
                if (cursor + 1 >= width && siblings[i] != hash) return false;
                hash = nodeHash(hash, siblings[i]);
            } else {
                hash = nodeHash(siblings[i], hash);
            }
            cursor >>= 1;
            width = (width + 1) >> 1;
        }
        return width == 1 && hash == root;
    }
}
