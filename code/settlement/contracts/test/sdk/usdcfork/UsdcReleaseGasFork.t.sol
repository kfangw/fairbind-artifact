// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "../SdkBase.sol";
import { ReleaseGasTest } from "../ReleaseGas.t.sol";
import { UsdcFork } from "./UsdcFork.sol";

/// ReleaseGas.t.sol unchanged (the same tests and rows), on USDC.
contract UsdcReleaseGasForkTest is ReleaseGasTest, UsdcFork {
    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
        _useUsdc();
    }
}
