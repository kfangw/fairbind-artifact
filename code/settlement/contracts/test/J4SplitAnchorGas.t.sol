// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ReproBase } from "./repro/ReproBase.sol";

/// Gas of the anchor transactions of one epoch (journal J4): the one-transaction
/// anchor and the split anchor in 1, 2, 4, 8 and 32 units, for 64 and 8 entries.
/// It uses only interfaces that exist before and after J4, so the same file
/// measures both builds. Run with --isolate, so that each call is one
/// transaction (21,000 base cost included, every slot cold). No gas assertion.
contract J4SplitAnchorGasTest is ReproBase {
    bytes32 internal constant PUB = keccak256("publication");

    function _setUp(uint256 purchases) internal {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.bucketCapacity = 200;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](purchases);
        for (uint256 i; i < purchases; i++) ns[i] = _purchase(10_000);
        _buildTree(ns);
        hv.roll(650);
    }

    function _slice(uint256 from, uint256 to) internal view returns (FairBindMerkle.ReceiptEntry[] memory part) {
        FairBindMerkle.ReceiptEntry[] memory all = _treeEntries();
        part = new FairBindMerkle.ReceiptEntry[](to - from);
        for (uint256 i = from; i < to; i++) part[i - from] = all[i];
    }

    function _oneTransaction(uint256 n) internal {
        _setUp(n);
        FairBindMerkle.ReceiptEntry[] memory all = _treeEntries();
        hv.prank(SELLER_OWNER);
        uint256 g = gasleft();
        fairbind.anchor(sellerId, 0, all, uint32(n), PUB);
        g -= gasleft();
        _log(string.concat("J4 anchor, ", _u(n), " entries, one transaction"), g);
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    function _units(uint256 n, uint8 log2) internal {
        _setUp(n);
        uint256 size = uint256(1) << log2;
        uint256 count = (n + size - 1) / size;
        string memory tag = string.concat("J4 anchorUnit, ", _u(n), " entries in ", _u(count), " unit(s) of ", _u(size));
        uint256 total;
        uint256 first;
        uint256 last;
        uint256 middleSum;
        uint32 unit;
        for (uint256 from; from < n; from += size) {
            uint256 to = from + size < n ? from + size : n;
            FairBindMerkle.ReceiptEntry[] memory part = _slice(from, to);
            bytes32 h = keccak256(abi.encode(PUB, unit));
            hv.prank(SELLER_OWNER);
            uint256 g = gasleft();
            fairbind.anchorUnit(sellerId, 0, unit, log2, part, h);
            g -= gasleft();
            total += g;
            if (unit == 0) first = g;
            if (to == n) last = g;
            else if (unit != 0) middleSum += g;
            if (count <= 8) _log(string.concat(tag, ", unit ", _u(unit)), g);
            unit++;
        }
        _log(string.concat(tag, ", first unit"), first);
        if (count > 2) _log(string.concat(tag, ", middle unit (mean)"), middleSum / (count - 2));
        if (count > 1) _log(string.concat(tag, ", last unit"), last);
        _log(string.concat(tag, ", sum"), total);
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "anchored");
    }

    function test_gas_64_oneTransaction() public { _oneTransaction(64); }
    function test_gas_64_units1() public { _units(64, 6); }
    function test_gas_64_units2() public { _units(64, 5); }
    function test_gas_64_units4() public { _units(64, 4); }
    function test_gas_64_units8() public { _units(64, 3); }
    function test_gas_64_units32() public { _units(64, 1); }
    function test_gas_8_oneTransaction() public { _oneTransaction(8); }
    function test_gas_8_units1() public { _units(8, 3); }
    function test_gas_8_units2() public { _units(8, 2); }
    function test_gas_8_units8() public { _units(8, 0); }

    function _u(uint256 x) internal pure returns (string memory) {
        if (x == 0) return "0";
        uint256 d;
        for (uint256 t = x; t != 0; t /= 10) d++;
        bytes memory b = new bytes(d);
        while (x != 0) {
            b[--d] = bytes1(uint8(48 + (x % 10)));
            x /= 10;
        }
        return string(b);
    }
}
