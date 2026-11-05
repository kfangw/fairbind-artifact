// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { IVrfVerifier } from "../src/randomness/IVrfVerifier.sol";
import { FairBindPublication } from "../src/modules/FairBindPublication.sol";

// Mutation builds of the request-based randomness. They exist only in tests.

/// An adapter that stores a response after the request's deadline.
contract LateAcceptingVrf is FairBindVrf {
    constructor(address c, IVrfVerifier v, bytes memory pk, uint32 d, uint32 t) FairBindVrf(c, v, pk, d, t) { }
    function _late(uint64) internal pure override returns (bool) { return false; }
}

/// An adapter whose VRF input carries the hash of the request's parent block.
contract BlockHashAlphaVrf is FairBindVrf {
    constructor(address c, IVrfVerifier v, bytes memory pk, uint32 d, uint32 t) FairBindVrf(c, v, pk, d, t) { }
    function _alpha(uint8 kind, bytes calldata input) internal view override returns (bytes memory) {
        return abi.encode(DOMAIN, block.chainid, consumer, kind, input, blockhash(block.number - 1));
    }
}

/// A module carrying seal that takes a SAMPLE value stored after the deadline.
contract LateTakingPublication is FairBindPublication {
    constructor(address a, address b, address c, address d, address e) FairBindPublication(a, b, c, d, e) { }
    function _sampleTaken(uint64, uint64) internal pure override returns (bool) { return true; }
}
