// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSampling } from "../../src/modules/FairBindSampling.sol";
import { FairBindRecovery } from "../../src/modules/FairBindRecovery.sol";

// Waiting-release mutation build (ADR 0028): a sampled case whose initial
// search is exhausted still waits, but its purchase is not held: the sampling
// module marks it releasable and the recovery module releases it while the
// case waits. The stateful suite must catch the release. It exists only in
// tests.

contract WaitReleaseSampling is FairBindSampling {
    constructor(address a, address b, address c, address d, address e) FairBindSampling(a, b, c, d, e) { }
    function _waitHolds() internal pure override returns (bool) { return false; }
}
contract WaitReleaseRecovery is FairBindRecovery {
    constructor(address a, address b, address c, address d, address e) FairBindRecovery(a, b, c, d, e) { }
    function _waitHolds() internal pure override returns (bool) { return false; }
}
