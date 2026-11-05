// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface G10Vm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function roll(uint256 height) external;
    function warp(uint256 timestamp) external;
    function setBlockhash(uint256 height, bytes32 hash) external;
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// Gas of the last call, as Foundry reports it (vm.lastCallGas). Under
/// --isolate the measured call runs as its own transaction and gasTotalUsed is
/// that transaction's gas used: the 21,000 base, calldata, execution, the
/// refund, and the EIP-7623 floor when the EVM version has it. G10b checked it
/// against anvil receipts on the fork (equal to the gas unit).
struct G10Gas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface G10bVm {
    function lastCallGas() external view returns (G10Gas memory);
    function writeLine(string calldata path, string calldata data) external;
    function toString(bytes calldata value) external pure returns (string memory);
    function toString(address value) external pure returns (string memory);
}

/// Signature recovery shared by the G10 sketches: 65-byte (r, s, v), v in
/// {27, 28}, low s only (EIP-2). A bad signature recovers the zero address
/// and never reverts.
library G10Sig {
    uint256 internal constant HALF_N = 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0;

    function recover(bytes32 digest, bytes calldata sig) internal pure returns (address signer) {
        if (sig.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        assembly ("memory-safe") {
            r := calldataload(sig.offset)
            s := calldataload(add(sig.offset, 0x20))
            v := byte(0, calldataload(add(sig.offset, 0x40)))
        }
        if (uint256(s) > HALF_N || (v != 27 && v != 28)) return address(0);
        signer = ecrecover(digest, v, r, s);
    }

    function recoverRsv(bytes32 digest, bytes32 r, bytes32 s, uint8 v) internal pure returns (address signer) {
        if (uint256(s) > HALF_N || (v != 27 && v != 28)) return address(0);
        signer = ecrecover(digest, v, r, s);
    }

    function typed(bytes32 domainSeparator, bytes32 structHash) internal pure returns (bytes32 d) {
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, hex"1901")
            mstore(add(p, 0x02), domainSeparator)
            mstore(add(p, 0x22), structHash)
            d := keccak256(p, 0x42)
        }
    }
}

/// Binary Merkle membership over a domain-separated node hash (the merkle-v1
/// node of FairBindMerkle: an odd last node pairs with itself).
library G10Merkle {
    bytes32 internal constant NODE_DOMAIN = keccak256("fairbind/epoch-node/v1");

    function node(bytes32 a, bytes32 b) internal pure returns (bytes32 h) {
        bytes32 dom = NODE_DOMAIN;
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, dom)
            mstore(add(p, 0x20), a)
            mstore(add(p, 0x40), b)
            h := keccak256(p, 0x60)
        }
    }

    /// Root from a leaf, its index and the sibling path (calldata).
    function rootOf(bytes32 leaf, uint256 index, bytes32[] calldata path) internal pure returns (bytes32 h) {
        h = leaf;
        for (uint256 i; i < path.length; i++) {
            h = (index & 1) == 0 ? node(h, path[i]) : node(path[i], h);
            index >>= 1;
        }
    }
}

abstract contract G10Base {
    G10Vm internal constant hv = G10Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant CONSOLE = 0x000000000000000000636F6e736F6c652e6c6f67;

    /// G10b: the call just measured, held until its "tx gas" line is logged.
    bool internal recPending;
    uint256 internal recGas;
    address internal recTo;
    bytes internal recData;
    string internal constant REC_FILE = "g10b-out/receipts.tsv";

    function _console(string memory label, uint256 value) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,uint256)", label, value));
        ok;
    }

    /// Keeps the transaction gas of the call that has just run (call this
    /// right after the measured window, before any other call) with its target
    /// and calldata, so that the signed transaction bytes can be rebuilt for
    /// the L1 data fee.
    function _rec(address to, bytes memory data) internal {
        G10Gas memory x = G10bVm(address(hv)).lastCallGas();
        recPending = true;
        recGas = x.gasTotalUsed;
        recTo = to;
        recData = data;
    }

    function _endsWithTxGas(string memory label) internal pure returns (bool) {
        bytes memory b = bytes(label);
        bytes memory t = bytes("tx gas");
        if (b.length < t.length) return false;
        for (uint256 i; i < t.length; i++) {
            if (b[b.length - t.length + i] != t[i]) return false;
        }
        return true;
    }

    function _log(string memory label, uint256 value) internal {
        _console(label, value);
        if (recPending && _endsWithTxGas(label)) {
            recPending = false;
            _console(string.concat(label, " (transaction gas used, G10b)"), recGas);
            G10bVm vm_ = G10bVm(address(hv));
            string memory row = string.concat(
                label, "\t", _u(value), "\t", _u(recGas), "\t", vm_.toString(recTo), "\t", vm_.toString(recData)
            );
            try vm_.writeLine(REC_FILE, row) { } catch { }
        }
    }

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

    function _sig(uint256 key, bytes32 digest) internal returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = hv.sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    /// Levels of a merkle-v1 tree over `leaves` (level 0 is the leaves).
    function _levels(bytes32[] memory leaves) internal pure returns (bytes32[][] memory lv) {
        uint256 depth;
        for (uint256 w = leaves.length; w > 1; w = (w + 1) >> 1) depth++;
        lv = new bytes32[][](depth + 1);
        lv[0] = leaves;
        for (uint256 d = 1; d <= depth; d++) {
            bytes32[] memory prev = lv[d - 1];
            uint256 w = (prev.length + 1) >> 1;
            bytes32[] memory cur = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 a = prev[2 * i];
                bytes32 b = 2 * i + 1 < prev.length ? prev[2 * i + 1] : a;
                cur[i] = G10Merkle.node(a, b);
            }
            lv[d] = cur;
        }
    }

    function _path(bytes32[][] memory lv, uint256 index) internal pure returns (bytes32[] memory p) {
        p = new bytes32[](lv.length - 1);
        for (uint256 d; d + 1 < lv.length; d++) {
            bytes32[] memory l = lv[d];
            uint256 sib = index ^ 1;
            p[d] = sib < l.length ? l[sib] : l[index];
            index >>= 1;
        }
    }
}

contract G10Probe {
    function take(bytes calldata) external { }
}

/// Calibration: what the gasleft() difference around an isolated call holds
/// (the 21,000 base and calldata gas under --isolate).
contract G10CalibrationTest is G10Base {
    function test_gas_calibration() public {
        G10Probe p = new G10Probe();
        bytes memory small = "";
        bytes memory big = new bytes(1000);
        for (uint256 i; i < 1000; i++) big[i] = 0x11;
        uint256 g = gasleft();
        p.take(small);
        g -= gasleft();
        _rec(address(p), abi.encodeCall(p.take, (small)));
        _log("G10 calibration empty_call", g);
        _log("G10b calibration empty_call, tx gas", g);
        _log("G10 calibration empty_call_cd", _cdGas(abi.encodeCall(G10Probe.take, (small))));
        g = gasleft();
        p.take(big);
        g -= gasleft();
        _rec(address(p), abi.encodeCall(p.take, (big)));
        _log("G10 calibration call_1000B", g);
        _log("G10b calibration call_1000B, tx gas", g);
        _log("G10 calibration call_1000B_cd", _cdGas(abi.encodeCall(G10Probe.take, (big))));
    }
}
