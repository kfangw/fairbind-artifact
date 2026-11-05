// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { FairBindCore } from "../../src/FairBindCore.sol";
import { Impl1bBase } from "../Design2Impl1b.t.sol";

struct OldGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface OldGasVm {
    function lastCallGas() external view returns (OldGas memory);
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
    OldGasVm private constant sc = OldGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));

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

/// G10b: the facilitator settle of the earlier build (the source of the
/// 257,863 figure: ReleaseClockGas.t.sol, "settle (second)", 344,141 minus the
/// x402 median 86,278). Same fixture as ReleaseClockGas (_profileHalf, mock
/// token with signature checks), but the settle transaction alone is measured
/// with vm.lastCallGas under --isolate, while ReleaseClockGas took the
/// gasleft() difference around _purchase(), which under --isolate also counts
/// the deriveNonce and receiveAuthorizationDigest calls (each its own
/// transaction) and the test-side work.
contract OldSettleGasTest is Impl1bBase, SlotCount {
    OldGasVm internal constant og = OldGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function _profileHalf() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _sampledProfile(20);
        p.samplePpm = 500_000;
        p.verifierExposurePpm = 100_000;
    }

    function test_gas_oldSettle() public {
        _deploy(_profileHalf());
        hv.roll(10);
        for (uint256 i; i < 3; i++) {
            uint256 g0 = gasleft();
            SettleArgs memory a = _settleArgs(G);
            uint256 g = gasleft();
            _settle(a);
            g -= gasleft();
            OldGas memory x = og.lastCallGas();
            uint256 whole = g0 - gasleft();
            string memory tag = i == 0 ? "first of the account" : i == 1 ? "second" : "third";
            _log(string.concat("G10b old settle (", tag, "), gasleft difference around _purchase as in ReleaseClockGas"), whole);
            _log(string.concat("G10b old settle (", tag, "), gasleft difference around settle only"), g);
            _log(string.concat("G10b old settle (", tag, "), settle transaction gas used"), x.gasTotalUsed);
        }
        // Storage breakdown of a later settle (the fourth, same state as the second).
        SettleArgs memory b = _settleArgs(G);
        uint256 snap = og.snapshotState();
        og.record();
        _settle(b);
        Slots memory f = _slotsOf(address(fairbind), snap);
        snap = og.snapshotState();
        og.record();
        _settle(b);
        Slots memory k = _slotsOf(address(token), snap);
        _settle(b);
        _logSlots("FairBind", f);
        _logSlots("mock token", k);
    }

    function _logSlots(string memory who, Slots memory r) internal view {
        _log(string.concat("G10b old settle (later), ", who, " storage slots touched"), r.touched);
        _log(string.concat("G10b old settle (later), ", who, " slots written"), r.written);
        _log(string.concat("G10b old settle (later), ", who, " slots created (zero to nonzero)"), r.created);
        _log(string.concat("G10b old settle (later), ", who, " slots changed (nonzero to nonzero)"), r.changed);
        _log(string.concat("G10b old settle (later), ", who, " slots cleared"), r.cleared);
        _log(string.concat("G10b old settle (later), ", who, " slots written back unchanged"), r.same);
    }
}
