// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";

// Split-anchor mutation build (journal J4): a single unit is stored as a split
// anchor of one unit (the J3 behaviour) instead of taking the one-transaction
// anchor path. The tests in J4SplitAnchor.t.sol must tell it from the real
// build. It exists only in tests.
contract SingleUnitSplitSettlement is FairBindSettlement {
    constructor(address a, address b, address c, address d, address e) FairBindSettlement(a, b, c, d, e) { }
    function _singleUnitDirect() internal pure override returns (bool) { return false; }
}
