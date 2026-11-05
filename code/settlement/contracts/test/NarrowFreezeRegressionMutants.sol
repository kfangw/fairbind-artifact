// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";

// Mutation build of the narrow freeze (ADR 0030) on the settlement module,
// which confirms the failure of a sample case whose receipt is not on chain
// by its deadline (timeoutSampleReceipt): the freeze starts at block zero and
// holds every unreleased entry of the account, the rule of ADR 0012. Only in
// tests.

contract WholeFreezeSettlement is FairBindSettlement {
    constructor(address a, address b, address c, address d, address e) FairBindSettlement(a, b, c, d, e) { }
    function _freezeStart(uint64) internal pure override returns (uint64) { return 0; }
}
