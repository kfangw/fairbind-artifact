// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindRecovery } from "../../src/modules/FairBindRecovery.sol";

// Release-clock mutation build (ADR 0029): waiting cases still hold their
// own purchases, and the account still records its pauses, but the recovery
// module counts every block toward an entry's release, as before ADR 0029.
// The stateful suite must catch a release of an entry of an account whose
// case waited. It exists only in tests.

contract PauseIgnoredRecovery is FairBindRecovery {
    constructor(address a, address b, address c, address d, address e) FairBindRecovery(a, b, c, d, e) { }
    function _pauseHolds() internal pure override returns (bool) { return false; }
}
