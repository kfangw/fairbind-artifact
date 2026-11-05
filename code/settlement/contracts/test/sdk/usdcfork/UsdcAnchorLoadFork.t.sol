// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { AnchorLoadTest } from "../AnchorLoad.t.sol";
import { UsdcFork } from "./UsdcFork.sol";

/// AnchorLoad.t.sol unchanged (gas series and loads), on USDC.
contract UsdcAnchorLoadForkTest is AnchorLoadTest, UsdcFork {
    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
        _useUsdc();
    }
}
