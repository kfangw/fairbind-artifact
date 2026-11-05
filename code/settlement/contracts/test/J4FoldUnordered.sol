// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindSettlement } from "../src/modules/FairBindSettlement.sol";

// Split-anchor mutation build (journal J4). Order-insensitive fold (xor): swapping
// two units leaves the publication hash unchanged.
// The tests in J4SplitAnchor.t.sol must tell it from the real fold. It exists only in tests.
contract FoldUnorderedSettlement is FairBindSettlement {
    constructor(address a, address b, address c, address d, address e) FairBindSettlement(a, b, c, d, e) { }
    function _publicationStep(bytes32 acc, bytes32 publicationHash) internal pure override returns (bytes32) {
        return acc ^ publicationHash;
    }
}
