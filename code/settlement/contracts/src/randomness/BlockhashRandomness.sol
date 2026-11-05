// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IRandomness } from "./IRandomness.sol";

/// The sampling path of the first prototype behind IRandomness: the hash of
/// the block A + 1 + delay, served by the chain for 256 blocks only.
contract BlockhashRandomness is IRandomness {
    uint32 public immutable override delayBlocks;

    constructor(uint32 delay) {
        delayBlocks = delay;
    }

    function valueOf(uint64 round) external view override returns (bool ready, bytes32 value) {
        uint256 randomBlock = uint256(round) + 1 + delayBlocks;
        if (block.number <= randomBlock) return (false, bytes32(0));
        value = blockhash(randomBlock);
        ready = value != bytes32(0);
    }
}
