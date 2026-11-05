// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Storage of the sampling module's later additions (journal J2; J3 adds the split anchor units; ADR 0031 the redraw uses). It sits
/// at a fixed hashed slot instead of after the last variable of FairBindCore,
/// so the core layout and every other module stay as they were. The router
/// reads it through the same accessor.
library SamplingStore {
    /// A split anchor named a unit size above the cap of one transaction.
    error UnitTooLarge();

    /// The randomness source (IRandomness) the sampling value of epochs
    /// anchored from block `since` on comes from. Set once by governance.
    struct RandomnessConfig {
        address source;
        uint64 since;
        /// The source is request based (IVrfRandomness, ADR 0031): sampling
        /// values come from SAMPLE requests and redraw values from AUX requests.
        bool vrf;
    }

    /// The registered use of an AUX value for the next redraw of a waiting
    /// case (design 2 rules D2-20 (b), D2-23 (a), ADR 0031): the block t of the
    /// registering transaction, the checkpoint the redraw searches (the first
    /// one written after the case's last search, written before t), and the
    /// redraw's ordinal. Zero while no redraw is registered.
    struct RedrawUse {
        uint64 registeredBlock;
        uint64 checkpointVersion;
        uint32 redraw;
    }

    /// Split anchor of one epoch: the units posted so far. Unit u holds the
    /// entries at global positions [u * 2^unitLog2, ...) of the epoch's list;
    /// roots[u] is the merkle-v1 root of the unit alone. An epoch posted as a
    /// single unit takes the one-transaction anchor path and has no record here
    /// (journal J4).
    ///
    /// The publication hashes of the units are folded into one accumulator
    /// (journal J4) instead of one slot per unit: pubAcc = h_0 after unit 0 and
    /// keccak256(pubAcc, h_u) after each later unit except the last. The last
    /// unit does not fold; the epoch's publication hash is
    /// keccak256(pubAcc, h_last). `tail` holds the last nonce posted while units
    /// are open and h_last once the epoch is anchored (the nonce is not needed
    /// after the last unit). Each h_u is also in its AnchorUnitPosted event.
    struct UnitAnchor {
        uint8 unitLog2;
        bytes32 tail;
        bytes32[] roots;
        bytes32 pubAcc;
    }

    struct Layout {
        RandomnessConfig randomness;
        mapping(uint32 => mapping(uint24 => UnitAnchor)) units;
        mapping(bytes32 => RedrawUse) redrawUses;
    }

    bytes32 internal constant SLOT = keccak256("fairbind.sampling.store.v1");

    function layout() internal pure returns (Layout storage l) {
        bytes32 slot = SLOT;
        assembly ("memory-safe") {
            l.slot := slot
        }
    }
}
