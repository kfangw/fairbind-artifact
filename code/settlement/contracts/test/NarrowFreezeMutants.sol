// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindDelivery } from "../src/modules/FairBindDelivery.sol";
import { FairBindPublication } from "../src/modules/FairBindPublication.sol";
import { FairBindReview } from "../src/modules/FairBindReview.sol";

// Mutation builds of the narrow freeze (ADR 0030): a failure on the delivery
// path (UNSERVED), a missed anchor or an inconclusive window above its
// threshold freezes from block zero, which holds
// every unreleased entry of the account as ADR 0012 did. Only in tests.

contract WholeFreezeDelivery is FairBindDelivery {
    constructor(address a, address b, address c, address d, address e) FairBindDelivery(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}

contract WholeFreezePublication is FairBindPublication {
    constructor(address a, address b, address c, address d, address e) FairBindPublication(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}

contract WholeFreezeReview is FairBindReview {
    constructor(address a, address b, address c, address d, address e) FairBindReview(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
