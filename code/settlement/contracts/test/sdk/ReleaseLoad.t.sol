// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "./ReleaseBase.sol";
import { SettlementBase } from "./SampledSettlement.sol";
import { RelGasVm } from "./ReleaseGas.t.sol";

/// Load: one seller epoch of 2,000 sales of v_min (third-party dust
/// settlements on an honest seller's profile), more than one call of the
/// earlier contract could release under the 2^24 gas cap. The release runs
/// in 8 release units, the cursor call and 8 payment units, each below the
/// cap. Run with --isolate for transaction gas; rows are logged as
/// "load <call> <index> gas=<g>".
contract ReleaseLoadTest is ReleaseBase {
    RelGasVm internal constant gvm = RelGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant TX_CAP = 1 << 24;
    uint256 internal constant N = 2_000;

    event log_string(string);

    uint256 internal maxGas;

    function _row(string memory call, uint256 i) internal {
        uint256 gas = gvm.lastCallGas().gasTotalUsed;
        require(gas < TX_CAP, "above the transaction gas cap");
        if (gas > maxGas) maxGas = gas;
        emit log_string(string.concat("load ", call, " ", _s(i), " gas=", _s(gas)));
    }

    function _afterAnchorUnit(uint256 u) internal override {
        uint256 gas = gvm.lastCallGas().gasTotalUsed;
        emit log_string(string.concat("load anchorUnit ", _s(u), " gas=", _s(gas)));
    }

    function test_load_2000_sales() public {
        _deploy(1, 1, DUST);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, N, DUST, 8, false);
        require(f.epochNonces(pid, e0).length == N, "settled");
        require(_anchorAll(pid, e0, ss) == 8, "eight anchor units");
        _valueOnlyFull(pid, e0, ss);
        _ripe(e0);
        (uint256 mk, uint256 tot, uint256 sales,) = m.releaseState(seller, e0);
        require(mk == 0 && tot == 8 && sales == N, "eight release units");
        vm.expectRevert(SettlementBase.State.selector);
        m.release(seller); // one call no longer releases a seller epoch above N_REL
        uint256 s0 = token.balanceOf(seller);
        for (uint256 u; u < tot; u++) {
            m.releaseUnit(seller);
            _row("releaseUnit", u);
        }
        require(token.balanceOf(seller) == s0, "units pay nothing");
        m.release(seller);
        _row("release", 0);
        require(f.accountCursor(seller) == e0 + 1, "cursor past E");
        uint256 paid;
        for (uint256 u; u < tot; u++) {
            paid += m.releasePay(seller, e0);
            _row("releasePay", u);
        }
        require(paid == N * DUST && token.balanceOf(seller) == s0 + N * DUST, "all 2,000 paid");
        (,,, uint256 next) = m.releaseState(seller, e0);
        require(next == type(uint256).max, "done");
        emit log_string(string.concat("load transactions=", _s(2 * tot + 1), " max gas=", _s(maxGas)));
    }
}
