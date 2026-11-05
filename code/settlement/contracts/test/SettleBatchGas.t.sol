// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { SettleBatchBase } from "./SettleBatchBase.sol";

contract GasProbe {
    function take(bytes calldata) external { }
}

/// Gas of the settlement batch against separate settle calls in the same
/// block (rule D2-34 (h)). Run with --isolate: each measured call is a
/// transaction of its own. Cells: n in {1, 2, 4, 8, 16, 32} items, m = 1
/// seller or m = n sellers, a vote account with receipt signatures or a
/// proof account, first settlements of the accounts and a second batch in
/// the next block. Every buyer is distinct. Lines are logged as
/// "SM <account> <round> <n> <m> <field>"; nothing is asserted about gas.
contract SettleBatchGasTest is SettleBatchBase {
    uint256[6] internal sizes = [uint256(1), 2, 4, 8, 16, 32];

    function _u(uint256 v) internal pure returns (string memory s) {
        if (v == 0) return "0";
        while (v != 0) {
            s = string.concat(string(abi.encodePacked(bytes1(uint8(48 + v % 10)))), s);
            v /= 10;
        }
    }

    /// Calldata gas of EIP-2028: 4 per zero byte, 16 per other byte.
    function _cdGas(bytes memory d) internal pure returns (uint256 g) {
        for (uint256 i; i < d.length; i++) g += d[i] == 0 ? 4 : 16;
    }

    function _line(string memory tag, string memory field, uint256 v) internal view {
        _log(string.concat(tag, " ", field), v);
    }

    /// Calibration: whether the gasleft() difference around an isolated call
    /// holds the 21,000 base and the calldata gas.
    function test_gas_calibration() public {
        GasProbe p = new GasProbe();
        bytes memory small = "";
        bytes memory big = new bytes(1000);
        for (uint256 i; i < 1000; i++) big[i] = 0x11;
        uint256 g = gasleft();
        p.take(small);
        g -= gasleft();
        _log("SM calibration empty_call", g);
        _log("SM calibration empty_call_cd", _cdGas(abi.encodeCall(GasProbe.take, (small))));
        g = gasleft();
        p.take(big);
        g -= gasleft();
        _log("SM calibration call_1000B", g);
        _log("SM calibration call_1000B_cd", _cdGas(abi.encodeCall(GasProbe.take, (big))));
    }

    function _items(uint256 n, bool mixed, uint256 buyerFrom) internal returns (FairBindCore.SettleItem[] memory items) {
        items = new FairBindCore.SettleItem[](n);
        for (uint256 i; i < n; i++) items[i] = _item(mixed ? i : 0, buyerFrom + i, VALUE);
    }

    /// One batch and the same items as separate settle calls, from the same state.
    function _measure(string memory tag, FairBindCore.SettleItem[] memory items) internal {
        bytes memory data = _batchCall(items);
        uint256 snap = sw.snapshotState();
        uint256 g = gasleft();
        uint256 settled = sb.settleBatch(items);
        g -= gasleft();
        require(settled == items.length, "every item settles");
        _line(tag, "batch_gas", g);
        _line(tag, "batch_bytes", data.length);
        _line(tag, "batch_cdgas", _cdGas(data));
        sw.revertToState(snap);
        uint256 sum;
        uint256 bytes_;
        uint256 cd;
        for (uint256 i; i < items.length; i++) {
            bytes memory one = _settleCall(items[i]);
            uint256 h = gasleft();
            fairbind.settle(
                items[i].sellerId,
                items[i].profileId,
                items[i].claimsHash,
                items[i].idempotencyKey,
                items[i].requestHash,
                items[i].authorization,
                items[i].paymentSignature
            );
            h -= gasleft();
            if (i == 0) _line(tag, "settle_first_gas", h);
            sum += h;
            bytes_ += one.length;
            cd += _cdGas(one);
        }
        _line(tag, "settle_sum_gas", sum);
        _line(tag, "settle_sum_bytes", bytes_);
        _line(tag, "settle_sum_cdgas", cd);
    }

    function _cells(uint8 m, string memory account, bool mixed) internal {
        _deployBatch(m, 64, 32);
        _fundBuyers(0, 64);
        for (uint256 k; k < 6; k++) {
            uint256 n = sizes[k];
            string memory sellers = _u(mixed ? n : 1);
            uint256 s0 = sw.snapshotState();
            _measure(string.concat("SM ", account, " first ", _u(n), " ", sellers), _items(n, mixed, 0));
            // The separate calls left the state the batch leaves; the second
            // round runs in the next block with new buyers.
            hv.roll(_now() + 1);
            _measure(string.concat("SM ", account, " second ", _u(n), " ", sellers), _items(n, mixed, 32));
            sw.revertToState(s0);
        }
    }

    function test_gas_voteOneSeller() public {
        _cells(ExchangeStore.MODE_VOTE_SIG, "VOTE", false);
    }

    function test_gas_voteMixedSellers() public {
        _cells(ExchangeStore.MODE_VOTE_SIG, "VOTE", true);
    }

    function test_gas_proofOneSeller() public {
        _cells(ExchangeStore.MODE_PROOF, "PROOF", false);
    }

    function test_gas_proofMixedSellers() public {
        _cells(ExchangeStore.MODE_PROOF, "PROOF", true);
    }
}
