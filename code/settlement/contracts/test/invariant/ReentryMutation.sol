// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindJudgment } from "../../src/modules/FairBindJudgment.sol";
import { FairBindReview } from "../../src/modules/FairBindReview.sol";
import { FairBindDelivery } from "../../src/modules/FairBindDelivery.sol";
import { FairBindSampling } from "../../src/modules/FairBindSampling.sol";

// Re-entry mutation build (ADR 0021): the modules that confirm seller
// failures keep the early return of _freeze for an account whose claim window
// is open, as before ADR 0021. A seller reinstated during its claim window
// then keeps selling, and a second confirmed failure leaves every purchase
// settled since the reinstatement outside the frozen window, so they are
// released to the failing seller. The stateful suite must catch the leak. It
// exists only in tests.

contract FreezeKeptJudgment is FairBindJudgment {
    constructor(address a, address b, address c, address d, address e) FairBindJudgment(a, b, c, d, e) { }
    function _moveFreezeInClaimWindow() internal pure override returns (bool) { return false; }
}
contract FreezeKeptReview is FairBindReview {
    constructor(address a, address b, address c, address d, address e) FairBindReview(a, b, c, d, e) { }
    function _moveFreezeInClaimWindow() internal pure override returns (bool) { return false; }
}
contract FreezeKeptDelivery is FairBindDelivery {
    constructor(address a, address b, address c, address d, address e) FairBindDelivery(a, b, c, d, e) { }
    function _moveFreezeInClaimWindow() internal pure override returns (bool) { return false; }
}
contract FreezeKeptSampling is FairBindSampling {
    constructor(address a, address b, address c, address d, address e) FairBindSampling(a, b, c, d, e) { }
    function _moveFreezeInClaimWindow() internal pure override returns (bool) { return false; }
}
