// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "./ReleaseBase.sol";

struct RelCallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface RelGasVm {
    function lastCallGas() external view returns (RelCallGas memory);
}

/// Gas of the release calls by the number of sales m they process, for one
/// profile of k = 1 (one profile epoch per seller epoch). Run with
/// --isolate so every call is its own transaction (cold storage). Each row
/// is logged as "row series=<s> m=<m> gas=<g>":
///   check        releaseUnit, m unsampled sales
///   check_proven releaseUnit, m sampled sales, each with a pass (closed cases)
///   check_fail   releaseUnit, m sampled sales without a pass (m failures)
///   passpay      release() after every unit is marked: pass and pay m (m <= N_REL)
///   inline       release() alone: check, pass and pay m (m <= N_REL)
///   inline_proven release() alone over m proven sampled sales
///   pass         release() of a seller epoch of 256 + m sales: pass only
///   payunit      releasePay of one payment unit of m sales
contract ReleaseGasTest is ReleaseBase {
    RelGasVm internal constant gvm = RelGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant TX_CAP = 1 << 24;

    event log_string(string);

    function _row(string memory series, uint256 n) internal returns (uint256 gas) {
        gas = gvm.lastCallGas().gasTotalUsed;
        require(gas < TX_CAP, "above the transaction gas cap");
        emit log_string(string.concat("row series=", series, " m=", _s(n), " gas=", _s(gas)));
    }

    /// n sales on one profile in e0; mode 0: none sampled, 1: all sampled
    /// and proved, 2: all sampled, none proved. Ends after every deadline.
    function _setup(uint256 n, uint8 mode) internal {
        _deploy(1, 1, 100);
        token.mint(buyer, 1e12);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, n, mode == 1 ? PRICE : DUST, 4, mode == 1);
        _anchorAll(pid, e0, ss);
        if (mode == 0) {
            _valueOnlyFull(pid, e0, ss);
        } else {
            vm.roll(f.valueDeadline(e0) + 1); // no value by M_e: every sale sampled
            if (mode == 1) for (uint256 i; i < n; i++) _prove1(pid, e0, ss, i);
        }
        _ripe(e0);
    }

    function _small(uint256 n, uint8 mode) internal {
        uint256 outer = vm.snapshotState();
        _setup(n, mode);
        uint256 id = vm.snapshotState();
        if (mode != 2) {
            m.release(seller);
            _row(mode == 0 ? "inline" : "inline_proven", n);
            vm.revertToState(id);
        }
        m.releaseUnit(seller);
        _row(mode == 0 ? "check" : (mode == 1 ? "check_proven" : "check_fail"), n);
        if (mode == 0) {
            m.release(seller);
            _row("passpay", n);
        }
        vm.revertToState(outer);
    }

    function test_gas_check_and_inline() public {
        uint256[6] memory ms = [uint256(1), 8, 32, 64, 128, 256];
        for (uint256 i; i < ms.length; i++) _small(ms[i], 0);
    }

    function test_gas_proven() public {
        uint256[4] memory ms = [uint256(1), 8, 32, 64];
        for (uint256 i; i < ms.length; i++) _small(ms[i], 1);
    }

    function test_gas_failing() public {
        uint256[4] memory ms = [uint256(1), 32, 128, 256];
        for (uint256 i; i < ms.length; i++) _small(ms[i], 2);
    }

    function test_gas_payment_units() public {
        uint256[3] memory ms = [uint256(1), 64, 256];
        for (uint256 i; i < ms.length; i++) {
            uint256 outer = vm.snapshotState();
            _setup(256 + ms[i], 0);
            m.releaseUnit(seller);
            m.releaseUnit(seller);
            m.release(seller);
            _row("pass", ms[i]);
            m.releasePay(seller, e0);
            if (i == 0) _row("payunit", 256);
            m.releasePay(seller, e0);
            _row("payunit", ms[i]);
            vm.revertToState(outer);
        }
    }
}
