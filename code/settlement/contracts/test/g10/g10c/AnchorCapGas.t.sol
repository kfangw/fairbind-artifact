// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { Rule10SketchGasTest } from "../Rule10SketchGas.t.sol";

/// G10c-3: large anchors of the G10 anchor sketch, to check the per-sale
/// marginal gas near the EIP-7825 per-transaction cap (2^24 = 16,777,216).
/// Inherits the G10 anchor and release tests, which rerun unchanged as a
/// consistency check against G10b. Run with --isolate.
contract AnchorCapGasTest is Rule10SketchGasTest {
    // One test function per large size, so that the test contract's own
    // memory (the anchor arguments it builds) starts empty each time.
    function test_gas_anchorMid() public {
        uint256[3] memory ns = [uint256(64), 128, 256];
        for (uint256 i; i < ns.length; i++) {
            _measureAnchor(ns[i], 1, 1);
            _measureAnchor(ns[i], 0, 1);
        }
    }

    function test_gas_anchorSigned512() public { _measureAnchor(512, 1, 1); }
    function test_gas_anchorSigned768() public { _measureAnchor(768, 1, 1); }
    function test_gas_anchorSigned900() public { _measureAnchor(900, 1, 1); }
    function test_gas_anchorSigned960() public { _measureAnchor(960, 1, 1); }
    function test_gas_anchorSigned920() public { _measureAnchor(920, 1, 1); }
    function test_gas_anchorSigned925() public { _measureAnchor(925, 1, 1); }
    function test_gas_anchorSigned930() public { _measureAnchor(930, 1, 1); }
    function test_gas_anchorPlain1560() public { _measureAnchor(1560, 0, 1); }
    function test_gas_anchorPlain1565() public { _measureAnchor(1565, 0, 1); }
    function test_gas_anchorPlain512() public { _measureAnchor(512, 0, 1); }
    function test_gas_anchorPlain1024() public { _measureAnchor(1024, 0, 1); }
    function test_gas_anchorPlain1300() public { _measureAnchor(1300, 0, 1); }
    function test_gas_anchorPlain1450() public { _measureAnchor(1450, 0, 1); }
}
