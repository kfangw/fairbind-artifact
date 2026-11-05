// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import { SampledSettlement, SettlementModule, Receipt, Leaf, Profile, IAuthToken } from "./SampledSettlement.sol";

struct CallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface GasVm {
    function lastCallGas() external view returns (CallGas memory);
}

/// Gas of one cursor call at seller-epoch multiples k = 1 to 32, by the
/// number of sales, their spread over the profile epochs of the seller
/// epoch, whether they are sampled, and the number of profiles. Run with
/// --isolate so the cursor call is its own transaction (cold storage);
/// each row is logged as "k np n active sampled gas".
contract KGasTest is SdkBase {
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    GasVm internal constant gvm = GasVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    event log_string(string);

    bytes32[] internal pids;
    uint256 internal e0;

    function _deploy(uint16 k, uint256 np) internal {
        f = _newSettlement();
        m = SettlementModule(address(f));
        vm.roll(f.genesis() + f.EPOCH_BLOCKS() + 5);
        e0 = f.epochOf(block.number);
        delete pids;
        for (uint256 j; j < np; j++) {
            Profile memory p = _profile(address(lazer), 0, 0, 1);
            p.epochMultiple = k;
            p.inputRule = keccak256(abi.encode("gas input rule", j));
            vm.prank(seller);
            pids.push(f.register(p, 2_000_000));
        }
        vm.prank(seller);
        token.approve(address(f), type(uint256).max);
        vm.prank(seller);
        m.depositBond(seller, CAP);
    }

    function _sale(bytes32 pid, uint256 i) internal returns (Leaf memory l, bytes memory mat) {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("psi", pid, i));
        mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pid, i, PRICE);
        r.responseHash = keccak256(abi.encodePacked(TAG, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(pid, r, i);
        l.sigB = _ack(pid, l.rs, false);
    }

    /// `n` signed honest sales on the first profile in profile epoch e,
    /// anchored; sampled: no value (all sampled) and every sale proved;
    /// otherwise a value under which none is sampled.
    function _epochSales(uint256 e, uint256 n, bool sampled) internal {
        uint256 start = f.genesis() + e * f.EPOCH_BLOCKS() + 5;
        if (block.number < start) vm.roll(start);
        bytes32 pid = pids[0];
        Leaf[] memory ls = new Leaf[](n);
        bytes[] memory mats = new bytes[](n);
        for (uint256 i; i < n; i++) (ls[i], mats[i]) = _sale(pid, e * 1000 + i);
        // keep mats aligned with the sorted leaves
        for (uint256 i = 1; i < n; i++) {
            for (uint256 j = i; j > 0 && ls[j - 1].rs.nonce > ls[j].rs.nonce; j--) {
                (ls[j], ls[j - 1]) = (ls[j - 1], ls[j]);
                (mats[j], mats[j - 1]) = (mats[j - 1], mats[j]);
            }
        }
        epoch = e;
        vm.roll(f.lastBlock(e) + f.D_INC() + 1);
        require(f.anchorUnit(_unit(pid, ls)) == 0, "anchor");
        if (sampled) {
            vm.roll(f.valueDeadline(e) + 1);
            for (uint256 i; i < n; i++) f.prove(_opening(pid, ls, i), mats[i]);
        } else {
            uint256 id = _requestSample(pid, e);
            uint256 w = 1;
            for (;; w++) {
                uint256 v = _valueOf(pid, e, id, w);
                bool any;
                for (uint256 i; i < n; i++) if (f.sampledBy(v, ls[i].rs.nonce, PRICE, CAP)) any = true;
                if (!any) break;
            }
            _fulfill(id, w);
        }
    }

    /// One case: n sales spread evenly over the first `active` profile
    /// epochs of the first seller epoch; returns the cursor call's gas.
    function _case(uint16 k, uint256 np, uint256 n, uint256 active, bool sampled) internal returns (uint256 gas) {
        uint256 id = vm.snapshotState();
        _deploy(k, np);
        uint256 lastBusy = e0;
        for (uint256 i; i < active; i++) {
            uint256 c = n / active + (i < n % active ? 1 : 0);
            if (c == 0) continue;
            _epochSales(e0 + i, c, sampled);
            lastBusy = e0 + i;
        }
        uint256 t = f.anchorDeadline(lastBusy) + f.T_C() + 1;
        if (f.lastBlock(e0 + k - 1) + 1 > t) t = f.lastBlock(e0 + k - 1) + 1;
        if (block.number < t) vm.roll(t);
        uint256 paid = m.release(seller);
        gas = gvm.lastCallGas().gasTotalUsed;
        require(paid == n * PRICE, "all paid");
        require(f.accountCursor(seller) == e0 + k, "cursor past E");
        emit log_string(
            string.concat(
                "row k=",
                _s(k),
                " np=",
                _s(np),
                " n=",
                _s(n),
                " active=",
                _s(active),
                " sampled=",
                sampled ? "1" : "0",
                " gas=",
                _s(gas)
            )
        );
        vm.revertToState(id);
    }

    function _s(uint256 v) internal pure returns (string memory) {
        if (v == 0) return "0";
        bytes memory b;
        while (v != 0) {
            b = abi.encodePacked(bytes1(uint8(48 + v % 10)), b);
            v /= 10;
        }
        return string(b);
    }

    function _rows(uint16 k) internal {
        for (uint256 np = 1; np <= 2; np++) {
            _case(k, np, 0, 1, false);
            _case(k, np, 1, 1, false);
            _case(k, np, 8, 1, false);
            _case(k, np, 32, 1, false);
            _case(k, np, 32, 1, true);
            if (k > 1) {
                _case(k, np, k, k, false); // one sale in every profile epoch of E
                _case(k, np, 4 * k, k, false);
            }
        }
    }

    function test_gas_k1() public {
        _rows(1);
    }

    function test_gas_k2() public {
        _rows(2);
    }

    function test_gas_k4() public {
        _rows(4);
    }

    function test_gas_k8() public {
        _rows(8);
    }

    function test_gas_k16() public {
        _rows(16);
    }

    function test_gas_k32() public {
        _rows(32);
    }
}
