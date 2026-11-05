// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseLoadTest } from "../ReleaseLoad.t.sol";
import { UsdcFork } from "./UsdcFork.sol";

/// ReleaseLoad.t.sol unchanged (2,000 sales), on USDC.
contract UsdcReleaseLoadForkTest is ReleaseLoadTest, UsdcFork {
    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
        _useUsdc();
    }
}
