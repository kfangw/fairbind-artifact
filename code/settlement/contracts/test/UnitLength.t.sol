// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { ShortUnitSettlement } from "./BatchMutants.sol";

/// The units of a split anchor add up to the epoch count: every unit but the
/// last is full and the last holds the rest. Six purchases in units of four:
/// a last unit of one entry is refused, so no anchor exists whose list is
/// shorter than its count. A settlement module that accepts a short last
/// unit is caught.
contract UnitLengthTest is ModuleSwapBase {
    bytes32 internal constant PUB = keccak256("publication");

    function _slice(uint256 from, uint256 to) internal view returns (FairBindMerkle.ReceiptEntry[] memory part) {
        FairBindMerkle.ReceiptEntry[] memory all = _treeEntries();
        part = new FairBindMerkle.ReceiptEntry[](to - from);
        for (uint256 i = from; i < to; i++) part[i - from] = all[i];
    }

    function postExternal(uint32 unit, uint256 from, uint256 to) external {
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, unit, 2, _slice(from, to), keccak256(abi.encode(PUB, unit)));
    }

    function _shortLastUnitRefused(string memory settlement) internal returns (bool) {
        string[10] memory names = _productionModules();
        if (bytes(settlement).length != 0) names[SETTLEMENT] = settlement;
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deployModules(names, p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](6);
        for (uint256 i; i < 6; i++) ns[i] = _purchase(10_000);
        _buildTree(ns);
        hv.roll(650);
        this.postExternal(0, 0, 4);
        (bool shortPosted,) = address(this).call(abi.encodeCall(this.postExternal, (1, 4, 5)));
        if (shortPosted) return false;
        this.postExternal(1, 4, 6);
        return fairbind.getAnchor(sellerId, 0).count == 6;
    }

    function test_lastUnitMustCompleteTheCount() public {
        require(_shortLastUnitRefused(""), "short last unit refused");
    }

    function test_shortLastUnitIsCaught() public {
        require(!_shortLastUnitRefused("BatchMutants.sol:ShortUnitSettlement"), "mutation caught");
    }
}
