// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { MockVrfVerifier } from "./MockVrfVerifier.sol";

/// Call-frame gas of the request-based randomness path (ADR 0031) with the
/// test proof verifier (one ecrecover; a VRF verifier costs more). Run with
/// --isolate. Every number is logged; nothing is asserted about gas.
contract VrfPathGasTest is ModuleSwapBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant VRF_KEY = 0x5EED;

    function test_gas_samplePath() public {
        _deployModules(_productionModules(), _productionProfile());
        MockVrfVerifier verifier = new MockVrfVerifier();
        FairBindVrf vrf = new FairBindVrf(address(fairbind), verifier, abi.encode(hv.addr(VRF_KEY)), 10, 20);
        hv.roll(5);
        fairbind.setRandomness(address(vrf));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](8);
        uint256 g = gasleft();
        ns[0] = _purchase(G);
        _log("settle (first of the account) gas", g - gasleft());
        g = gasleft();
        ns[1] = _purchase(G);
        _log("settle (second) gas", g - gasleft());
        for (uint256 i = 2; i < 8; i++) ns[i] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 8, keccak256("publication"));
        hv.roll(701);
        g = gasleft();
        fairbind.requestSampleValue(PROFILE, 0);
        _log("requestSampleValue gas", g - gasleft());
        bytes32 id = keccak256(abi.encode(uint8(1), abi.encode(uint32(PROFILE), uint64(700))));
        bytes memory proof = _sig(VRF_KEY, keccak256(vrf.storedAlpha(id)));
        bytes32 output = keccak256(abi.encode(verifier.OUTPUT_DOMAIN(), proof));
        g = gasleft();
        vrf.fulfill(id, output, proof);
        _log("fulfill (mock proof check) gas", g - gasleft());
        hv.roll(713);
        g = gasleft();
        fairbind.seal(sellerId, 0);
        _log("seal (request-based value) gas", g - gasleft());
    }
}
