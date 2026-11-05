// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// Beacon delay used by every test profile: the admission floor of
// profile-v1 section 2 (128 L1 blocks of twelve seconds on a two-second chain).
uint32 constant TEST_BEACON_DELAY_BLOCKS = 768;

// Beacon block of epoch 0 for the test profiles (epochOrigin 1, epochBlocks
// 300, anchorBlocks 100): the anchor deadline (block 700) plus one plus the
// beacon delay.
uint256 constant TEST_EPOCH0_BEACON_BLOCK = 700 + 1 + TEST_BEACON_DELAY_BLOCKS;
