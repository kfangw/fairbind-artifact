// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseGasTest } from "../ReleaseGas.t.sol";
import { AnchorLoadTest } from "../AnchorLoad.t.sol";
import { UsdcFork } from "./UsdcFork.sol";

/// Control: the same gas tests with the mock token on the same Base fork
/// , so that the USDC rows differ from these by the token alone.
contract MockReleaseGasForkTest is ReleaseGasTest, UsdcFork {
    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
    }
}

contract MockAnchorLoadForkTest is AnchorLoadTest, UsdcFork {
    function setUp() public override {
        if (!_onFork()) {
            _useUsdc(); // skips
            return;
        }
        super.setUp();
    }
}
