// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Storage of rule edition 8 (design 2 rule 8, v0.3). It sits at a fixed
/// hashed slot, like SamplingStore, BatchStore and ExchangeStore, so the core
/// layout and every module stay as they were. A profile whose rule 8 terms
/// were never set keeps edition 7 in every respect: nothing here is read for
/// it except the `on` flag.
library Rule8Store {
    /// Profile epoch states (rule D2-35 (a), (c)).
    uint8 internal constant PE_NONE = 0;
    uint8 internal constant PE_SEALED = 1;
    uint8 internal constant PE_FAILED = 2;

    /// Kinds of required calls whose first successful caller is paid a fee
    /// from the profile fee pool (rule D2-38 (a)). The fee of each kind is a
    /// profile term.
    uint8 internal constant FEE_SAMPLE_REQUEST = 1;
    uint8 internal constant FEE_SEAL = 2;
    uint8 internal constant FEE_CHECKPOINT = 3;
    uint8 internal constant FEE_OPEN = 4;
    uint8 internal constant FEE_ASSIGN = 5;
    uint8 internal constant FEE_TIMEOUT = 6;
    uint8 internal constant FEE_FINALIZE = 7;
    uint8 internal constant FEE_ANCHOR_TIMEOUT = 8;
    uint8 internal constant FEE_CURSOR = 9;
    uint8 internal constant FEE_GATE = 10;
    uint8 internal constant FEE_SEAL_TIMEOUT = 11;
    uint8 internal constant FEE_CLOSE = 12;
    uint8 internal constant FEE_KINDS = 13;

    /// Item flags (rule D2-39 (c)): a purchase left out of the batch payment
    /// of its seller epoch waits for a separate release (an open dispute, or
    /// a state the batch does not pay), and a separately released one.
    uint8 internal constant ITEM_SEPARATE = 1;
    uint8 internal constant ITEM_DONE = 2;

    /// Terms of a profile, fixed once before it is active.
    struct Terms {
        bool on;
        /// u_r: a release unit holds 2^unitLog2 settlements in settlement
        /// order (rule D2-39 (n)).
        uint8 unitLog2;
        /// Revision 6: anchors carry the buyers' receipt signatures and the
        /// contract checks them in bulk (rule D2-41).
        bool bulkSig;
        /// H_N, the held window in raw blocks (rule D2-42 (b)).
        uint32 heldWindow;
        /// T_win(m) = L_F(m) + kappa_bar + D_bar_w in raw blocks (rule D2-8 (a')).
        uint32 winBlocks;
        /// w_b: the buyer window after the value block of an unsigned
        /// account (rule D2-39 (b) 3, (l)).
        uint32 buyerWindow;
        /// Fees (rule D2-36 (e), D2-38 (b)): the anchor submitter, the
        /// share of the selected cases, a release unit (c_r0 + c_r1 per
        /// item) and the share of the profile-level calls per seller epoch.
        uint96 cAnchor;
        uint96 cCase;
        uint96 cR0;
        uint96 cR1;
        uint96 cEp;
        bytes32 termsHash;
    }

    /// Terms as governance sets them.
    struct Input {
        uint8 unitLog2;
        bool bulkSig;
        uint32 heldWindow;
        uint32 winBlocks;
        uint32 buyerWindow;
        uint96 cAnchor;
        uint96 cCase;
        uint96 cR0;
        uint96 cR1;
        uint96 cEp;
        uint96[] callFees;
        bytes32 termsHash;
    }

    /// One profile epoch (rule D2-35 (a)): the sampling value and the
    /// checkpoint of block A_e, written once by the profile seal.
    struct ProfileEpoch {
        bytes32 randomness;
        bytes32 setHash;
        uint256 weight;
        uint64 version;
        uint8 state;
    }

    /// One seller epoch under the release cursor (rule D2-39).
    struct SellerEpoch {
        /// Release units done, the selected sales seen by them, and the
        /// release-unit fees they took (for the levy).
        uint32 unitsDone;
        uint32 selected;
        uint32 payCount;
        uint32 separateCount;
        /// Purchases that left the held state (paid, refunded) before the
        /// cursor passed (rule D2-42 (g)).
        uint32 left;
        bool passed;
        bool paid;
        bool itemized;
        uint96 payAmount;
        uint96 relFees;
        /// Revision 2: hash of the seller-signed anchor content.
        bytes32 content;
        /// Revision 6: C_e = H(R_e || R^b_e).
        bytes32 bindRoot;
    }

    /// The anchor content the seller signs (rule D2-36 (a)): the seller
    /// epoch, its count, the root of the anchored list and the root without
    /// signature hashes (root0), the publication hash, and the units K with
    /// the hash U of their roots. A one-transaction anchor has K = 1 and
    /// U = H(root || root0).
    struct AnchorContent {
        uint32 sellerId;
        uint32 profileId;
        uint24 epoch;
        uint32 count;
        bytes32 root;
        bytes32 root0;
        bytes32 publicationHash;
        uint32 units;
        bytes32 unitsHash;
    }

    /// One entry of an anchor with the buyer's receipt signature (rule D2-41
    /// (a)(b)): the nonce, the bundle (H(ct), h_ek, h_r) and the receipt
    /// leaf the buyer signed, and the buyer's signature (empty when the
    /// seller has none).
    struct BulkEntry {
        bytes32 nonce;
        bytes32 ctHash;
        bytes32 ekHash;
        bytes32 rHash;
        bytes32 leaf;
        bytes sig;
    }

    /// One settlement of a release unit as it was accumulated (rule D2-39 (b) 2).
    struct UnitItem {
        bytes32 nonce;
        address payer;
        uint256 value;
        uint256 cap;
    }

    /// A fee owed by the pool while it was short (rule D2-38 (d)).
    struct Owed {
        address to;
        uint96 amount;
    }

    struct Layout {
        mapping(uint32 => Terms) terms;
        mapping(uint32 => mapping(uint8 => uint96)) callFees;
        mapping(uint32 => mapping(uint24 => ProfileEpoch)) profileEpochs;
        /// Per profile epoch: seller epochs with sales the cursor has not
        /// passed (rule D2-35 (d) 1).
        mapping(uint32 => mapping(uint24 => uint32)) openSellerEpochs;
        /// Per profile epoch: open cases outside its sample cases (rule D2-35
        /// (d) 1 (ii)): WRONG_DELIVERY disputes of its purchases, counted at
        /// opening and counted out once their end is noted.
        mapping(uint32 => mapping(uint24 => uint32)) openOtherCases;
        mapping(bytes32 => bool) otherCounted;
        /// Per profile: the lowest profile epoch not closed.
        mapping(uint32 => uint24) closedBelow;
        /// Per seller: the release cursor E_a, the lowest seller epoch not
        /// passed (rule D2-39 (a)).
        mapping(uint32 => uint24) cursor;
        mapping(uint32 => mapping(uint24 => SellerEpoch)) sellerEpochs;
        /// Settlement accumulator per release unit: A_{a,E,k} (rule D2-39 (b) 2).
        mapping(uint32 => mapping(uint24 => mapping(uint256 => bytes32))) unitAcc;
        /// Done units, a bit per unit.
        mapping(uint32 => mapping(uint24 => mapping(uint256 => uint256))) doneBits;
        mapping(bytes32 => uint8) itemFlag;
        /// n_h, the held settlements of the seller's episode (rule D2-42 (a)),
        /// and the block of the last suspension: a purchase settled at or
        /// before it belongs to an earlier episode.
        mapping(uint32 => uint32) held;
        mapping(uint32 => uint64) episodeFloor;
        /// The profile fee pool, the queue of owed fees and the sellers'
        /// unpaid levies (rule D2-38 (b), (d)).
        mapping(uint32 => uint256) pool;
        mapping(uint32 => Owed[]) owed;
        mapping(uint32 => uint256) owedHead;
        mapping(uint32 => uint256) levyDebt;
        /// Verifier exit request blocks (rule D2-35 (d) 2).
        mapping(uint32 => uint64) exitRequested;
        /// Profiles with rule 8 terms, for the verifier exit check.
        uint32[] profileList;
        /// Fees paid once per key (a profile-level call of an epoch).
        mapping(bytes32 => bool) feeOnce;
    }

    bytes32 internal constant SLOT = keccak256("fairbind.rule8.store.v1");

    function layout() internal pure returns (Layout storage l) {
        bytes32 slot = SLOT;
        assembly ("memory-safe") {
            l.slot := slot
        }
    }
}
