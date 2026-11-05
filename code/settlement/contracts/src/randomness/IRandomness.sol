// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Source of the per-epoch sampling value (design 2 rules D2-16 and J4).
///
/// A round is identified by the anchor deadline block A of the epoch: every
/// epoch whose anchor window closes at block A shares the round. The value of
/// a round must be fixed only after A, must not depend on who delivers it and
/// must not change once delivered. A pull interface serves a commit-reveal
/// source, the block hash adapter and a VRF adapter whose fulfilment callback
/// stores the value for valueOf to return.
interface IRandomness {
    /// Blocks after A that the source needs at most before valueOf can be
    /// ready. The sampling module sets randomBlock = A + 1 + delayBlocks and
    /// rejects a source whose delay exceeds the profile's beaconDelayBlocks,
    /// so the judgment horizon of an existing profile stays valid.
    function delayBlocks() external view returns (uint32);

    /// The value of the round, or ready = false while it is not available.
    function valueOf(uint64 round) external view returns (bool ready, bytes32 value);
}
