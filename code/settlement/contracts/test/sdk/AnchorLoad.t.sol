// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "./ReleaseBase.sol";
import { RelGasVm } from "./ReleaseGas.t.sol";

/// Anchor, completion, pull and release transactions of one profile epoch of
/// n sales of v_min (third-party dust settlements), every leaf marked
/// unanswered (the seller's answer to a flood: each is refunded) or every
/// leaf plain (unsigned, answered), for n = 1,024, 2,000 and 5,000; and gas
/// rows for fits. Run with --isolate (each call its own transaction). Every
/// measured transaction must stay below 2^24 gas. Rows:
///   "load kind=<k> n=<n> <call> <i> [leaves=<l>] gas=<g>"
///   "row series=<s> m=<m> gas=<g>"
interface SkipVm {
    function skip(bool skipTest) external;
}

contract AnchorLoadTest is ReleaseBase {
    RelGasVm internal constant gvm = RelGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant TX_CAP = 1 << 24;

    event log_string(string);

    string internal tag; // prefix of the rows of the running case
    uint256 internal unitsTotal;
    uint256 internal maxGas;

    function _gas() internal returns (uint256 g) {
        g = gvm.lastCallGas().gasTotalUsed;
        require(g < TX_CAP, "above the transaction gas cap");
        if (g > maxGas) maxGas = g;
    }

    function _afterAnchorUnit(uint256 u) internal override {
        uint256 g = _gas();
        if (bytes(tag).length != 0) emit log_string(string.concat(tag, " anchorUnit ", _s(u), " gas=", _s(g)));
    }

    function _kname(uint8 k) internal pure returns (string memory) {
        return k == K_MARKED ? "marked" : (k == K_ACCEPTED ? "accepted" : "plain");
    }

    // ------------------------------------------------------------- load

    function _load(uint256 n, uint8 kind) internal {
        tag = string.concat("load kind=", _kname(kind), " n=", _s(n));
        maxGas = 0;
        _deploy(1, 1, DUST);
        token.mint(buyer, 1e12);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, n, DUST, 20, false);
        _kind(pid, ss, kind);
        uint256 b0 = token.balanceOf(buyer);
        uint256 s0 = token.balanceOf(seller);
        _anchorAll(pid, e0, ss);
        uint256 pulls = 1; // the completing transaction ran the first chunk
        while (true) {
            (, uint256 pulled) = m.pullPending(pid, ss[0].rs.nonce);
            if (pulled >= n) break;
            m.pullCompletion(pid, e0);
            emit log_string(string.concat(tag, " pullCompletion ", _s(pulls++), " gas=", _s(_gas())));
        }
        if (kind == K_MARKED) require(token.balanceOf(buyer) == b0 + n * DUST, "every marked sale refunded");
        _valueOnlyFull(pid, e0, ss);
        _ripe(e0);
        (, uint256 tot,,) = m.releaseState(seller, e0);
        for (uint256 u; u < tot; u++) {
            m.releaseUnit(seller);
            emit log_string(string.concat(tag, " releaseUnit ", _s(u), " gas=", _s(_gas())));
        }
        m.release(seller);
        emit log_string(string.concat(tag, " release 0 gas=", _s(_gas())));
        uint256 paid;
        if (n > 256) {
            for (uint256 u; u < tot; u++) {
                paid += m.releasePay(seller, e0);
                emit log_string(string.concat(tag, " releasePay ", _s(u), " gas=", _s(_gas())));
            }
        }
        if (kind == K_MARKED) require(paid == 0 && token.balanceOf(seller) == s0, "no marked sale paid to the seller");
        else require(token.balanceOf(seller) == s0 + n * DUST, "every plain sale paid by the cursor");
        emit log_string(string.concat(tag, " max gas=", _s(maxGas)));
        tag = "";
    }

    function test_load_marked_1024() public {
        _load(1024, K_MARKED);
    }

    function test_load_marked_2000() public {
        _load(2000, K_MARKED);
    }

    /// Needs a raised test gas budget (--gas-limit) to build 5,000 sales;
    /// skipped under the default budget.
    function test_load_marked_5000() public {
        if (gasleft() < 4_000_000_000) return SkipVm(address(vm)).skip(true);
        _load(5000, K_MARKED);
    }

    function test_load_plain_1024() public {
        _load(1024, K_PLAIN);
    }

    function test_load_plain_2000() public {
        _load(2000, K_PLAIN);
    }

    /// Needs a raised test gas budget (--gas-limit) to build 5,000 sales;
    /// skipped under the default budget.
    function test_load_plain_5000() public {
        if (gasleft() < 4_000_000_000) return SkipVm(address(vm)).skip(true);
        _load(5000, K_PLAIN);
    }

    // ------------------------------------------------------- gas series

    function _row(string memory series, uint256 mm, uint256 g) internal {
        emit log_string(string.concat("row series=", series, " m=", _s(mm), " gas=", _s(g)));
    }

    /// c sales of one kind, settled, sorted; anchors unit 1 with the first
    /// `first` sorted leaves and unit 2 with the rest; rows: the non-final
    /// unit 1 ("unit_<kind>", m = first) and the completing unit 2
    /// ("complete_<kind>", m = records whose transfers the completing
    /// transaction runs, min(c, N_REL), for a unit 2 of one leaf).
    function _units(uint256 c, uint256 first, uint8 kind) internal returns (bytes32 pid, Sold[] memory ss) {
        _deploy(1, 1, DUST);
        token.mint(buyer, 1e12);
        pid = pids[0];
        _at(e0, 5);
        ss = _sell(pid, 0, c, DUST, 20, false);
        _kind(pid, ss, kind);
        _qsort(ss, 0, int256(ss.length) - 1);
        vm.roll(f.lastBlock(e0) + f.D_INC() + 1);
        bytes32 ch = f.profile(pid).codeHash;
        require(f.anchorUnit(_unitOf(pid, e0, ss, 0, first, 1, ch)) == 0, "unit 1");
        _row(string.concat("unit_", _kname(kind)), first, _gas());
        require(f.anchorUnit(_unitOf(pid, e0, ss, first, c, 2, ch)) == 0, "unit 2");
        if (c - first == 1) _row(string.concat("complete_", _kname(kind)), c < 256 ? c : 256, _gas());
        require(f.epochComplete(pid, e0), "complete");
    }

    function _series(uint8 kind) internal {
        uint256[4] memory ls = [uint256(1), 32, 128, 255];
        for (uint256 i; i < ls.length; i++) {
            uint256 id = vm.snapshotState();
            _units(ls[i] + 1, ls[i], kind); // non-final unit of ls[i] leaves; completion of ls[i] + 1 records
            vm.revertToState(id);
        }
        uint256[3] memory ms = [uint256(1), 64, 256];
        for (uint256 i; i < ms.length; i++) {
            uint256 id = vm.snapshotState();
            bytes32 pid = _anchored(256 + ms[i], kind);
            m.pullCompletion(pid, e0);
            _row(string.concat("chunk_", _kname(kind)), ms[i], _gas());
            vm.revertToState(id);
        }
        if (kind != K_PLAIN) {
            uint256 id = vm.snapshotState();
            bytes32 pid = _anchored(258, kind);
            bytes32[] memory ns = f.epochNonces(pid, e0);
            m.pullSale(pid, ns[256]);
            _row(string.concat("pullsale_", _kname(kind)), 1, _gas());
            m.pullSale(pid, ns[257]);
            _row(string.concat("pullsale_", _kname(kind)), 1, _gas());
            vm.revertToState(id);
        }
    }

    /// c sales of one kind anchored in units of N_UNIT (complete).
    function _anchored(uint256 c, uint8 kind) internal returns (bytes32 pid) {
        _deploy(1, 1, DUST);
        token.mint(buyer, 1e12);
        pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, c, DUST, 20, false);
        _kind(pid, ss, kind);
        _anchorAll(pid, e0, ss);
    }

    function test_gas_marked() public {
        _series(K_MARKED);
    }

    function test_gas_accepted() public {
        _series(K_ACCEPTED);
    }

    function test_gas_plain() public {
        _series(K_PLAIN);
    }
}
