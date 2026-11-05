// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Same counting as SlotCount in contracts/test/g10b-old/OldSettleGas.t.sol,
// which keeps its own copy so that it can be dropped into an older build.

interface G10bSlotVm {
    function record() external;
    function accesses(address target) external returns (bytes32[] memory reads, bytes32[] memory writes);
    function load(address target, bytes32 slot) external view returns (bytes32);
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// Storage-slot breakdown of one call: distinct slots read (each a cold
/// access in its own transaction), and the slots written, split into new
/// (zero to nonzero), changed (nonzero to nonzero), cleared and unchanged.
abstract contract SlotCount {
    G10bSlotVm private constant sc = G10bSlotVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    struct Slots {
        uint256 touched;
        uint256 written;
        uint256 created;
        uint256 changed;
        uint256 cleared;
        uint256 same;
    }

    function _distinct(bytes32[] memory a) internal pure returns (bytes32[] memory d) {
        d = new bytes32[](a.length);
        uint256 n;
        for (uint256 i; i < a.length; i++) {
            bool seen;
            for (uint256 j; j < n; j++) {
                if (d[j] == a[i]) {
                    seen = true;
                    break;
                }
            }
            if (!seen) d[n++] = a[i];
        }
        assembly ("memory-safe") {
            mstore(d, n)
        }
    }

    /// Call after the measured call with the snapshot taken (and vm.record()
    /// started) just before it. Reverts to the snapshot; the caller then
    /// repeats the call unmeasured to restore the state.
    function _slotsOf(address target, uint256 snap) internal returns (Slots memory r) {
        (bytes32[] memory reads, bytes32[] memory writes) = sc.accesses(target);
        bytes32[] memory t = _distinct(reads);
        bytes32[] memory w = _distinct(writes);
        r.touched = t.length;
        r.written = w.length;
        bytes32[] memory after_ = new bytes32[](w.length);
        for (uint256 i; i < w.length; i++) after_[i] = sc.load(target, w[i]);
        sc.revertToState(snap);
        for (uint256 i; i < w.length; i++) {
            bytes32 before = sc.load(target, w[i]);
            if (before == after_[i]) r.same++;
            else if (before == 0) r.created++;
            else if (after_[i] == 0) r.cleared++;
            else r.changed++;
        }
    }
}
