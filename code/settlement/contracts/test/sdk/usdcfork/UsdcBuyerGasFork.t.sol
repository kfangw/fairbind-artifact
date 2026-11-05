// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "../ReleaseBase.sol";
import { RelGasVm } from "../ReleaseGas.t.sol";
import { Receipt, Auth } from "../SampledSettlement.sol";
import { UsdcFork } from "./UsdcFork.sol";

/// Buyer-side transactions besides the pulls (those are AnchorLoad's
/// pullsale_<kind> rows), on USDC, with --isolate: the binding completion a
/// buyer sends when the facilitator settled without the binding triple, and
/// for reference the settle transaction itself (sent by the facilitator,
/// not the buyer) with and without the binding, against a bare USDC
/// transferWithAuthorization. Rows: "row series=<s> m=1 gas=<g>".
contract UsdcBuyerGasForkTest is ReleaseBase, UsdcFork {
    RelGasVm internal constant gvm = RelGasVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    event log_string(string);

    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
        _useUsdc();
        _deploy(1, 1, 100);
        _at(e0, 5);
    }

    function _row(string memory series) internal {
        emit log_string(string.concat("row series=", series, " m=1 gas=", _s(gvm.lastCallGas().gasTotalUsed)));
    }

    function _triple(uint256 i) internal view returns (bytes32 rq, bytes32 cl, bytes32 salt, bytes32 nonce) {
        rq = keccak256(abi.encode("buyer req", i));
        cl = keccak256(abi.encode("buyer claims", i));
        salt = keccak256(abi.encode("buyer salt", i));
        nonce = f.boundNonce(pids[0], rq, cl, salt);
    }

    function test_gas_settle_and_binding() public {
        bytes32 pid = pids[0];
        for (uint256 i; i < 2; i++) {
            // settle with the binding triple (the normal path)
            (bytes32 rq, bytes32 cl, bytes32 salt, bytes32 nonce) = _triple(10 + i);
            Auth memory a = _auth(pid, PRICE, nonce);
            f.settle(a, _authSig(a), rq, cl, salt);
            _row("settle_bound");
            // settle without the triple, then the buyer completes the binding
            (rq, cl, salt, nonce) = _triple(20 + i);
            a = _auth(pid, PRICE, nonce);
            f.settle(a, _authSig(a), bytes32(0), bytes32(0), bytes32(0));
            _row("settle_unbound");
            vm.prank(buyer);
            m.completeBinding(pid, nonce, rq, cl, salt);
            _row("completeBinding");
            // a bare USDC transferWithAuthorization to the same vault
            a = _auth(pid, PRICE, keccak256(abi.encode("bare", i)));
            token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, _authSig(a));
            _row("usdc_twa");
        }
    }
}
