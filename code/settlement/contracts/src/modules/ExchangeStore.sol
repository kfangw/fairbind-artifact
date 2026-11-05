// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Storage of the receipt signatures, proof profiles and measured costs
/// (ADR 0037). It sits at a fixed hashed slot, like SamplingStore and
/// BatchStore, so the core layout and every module stay as they were.
/// Nothing here is used by a profile whose terms were never set.
library ExchangeStore {
    /// Profile modes. PROOF judges sample cases and disputes by a PASS proof
    /// the contract checks; VOTE_SIG keeps verifier judgment and adds the
    /// receipt signature of the buyer. Both bind a sale to the signature.
    uint8 internal constant MODE_NONE = 0;
    uint8 internal constant MODE_PROOF = 1;
    uint8 internal constant MODE_VOTE_SIG = 2;
    /// Input judgment values.
    uint8 internal constant INPUT_VOTE = 0;
    uint8 internal constant INPUT_PROOF = 1;

    /// Terms of a profile, fixed once before it is active.
    /// Slot 0 holds what every module reads first: the mode, whether costs
    /// are measured, the price cap pi (smallest token units per 1 ETH), the
    /// per-transaction and per-call gas the measurement does not see
    /// (gFixTx, gFixCall), the bound on the unsigned envelope bytes outside
    /// the call data that the L1 fee bound adds (bEnv, signature excluded)
    /// and the proof deadline T_p.
    struct Terms {
        uint8 mode;
        bool costOn;
        uint96 priceCap;
        uint32 gFixTx;
        uint32 gFixCall;
        uint32 bEnv;
        uint32 proofBlocks;
        uint96 keyCap;
        uint32 bundleBlocks;
        uint32 keyBlocks;
        uint32 refWindow;
        uint32 maxSkew;
        uint32 g1271;
        address verifier;
        uint16 padLength;
        uint16 sigLimit;
        uint32 tolerancePpm;
        bytes32 feedId;
        bytes32 tag;
        bytes32 sourceSetHash;
        bytes32 policyHash;
        uint64 toleranceAbs;
        bytes32 termsHash;
        /// The binding proof window F_max (raw blocks from settlement) and
        /// the slack of a binding proof transaction, which activation
        /// checks against the first block a binding proof is taken (rule
        /// D2-13 (c) 7, D2-19 (h)).
        uint32 bindWindow;
        uint32 bindSlack;
    }

    /// Per purchase: the buyer's validAfter (the reference time of a PASS
    /// proof), the PROOF dispute (kind, state, deadline, deposit), the state
    /// of the seller's proof on a frozen entry, whether a confirmed PASS proof
    /// exists, and whether a dispute refunded the purchase while its sample
    /// case may still open or run (`early`).
    struct Record {
        uint64 refTime;
        uint64 disputeDue;
        uint64 disputeDeposit;
        uint8 disputeKind;
        uint8 disputeState;
        uint8 selfState;
        bool proven;
        bool early;
    }

    /// Measured costs of the seller's calls in a non-delivery dispute that
    /// ended as delivered, for the dispute's case and for a buyer recovery.
    struct Ladder {
        uint96 cost;
        uint96 recoveryCost;
        bool delivered;
        bool recoveryDelivered;
    }

    uint8 internal constant DISPUTE_OPEN = 1;
    uint8 internal constant DISPUTE_PASSED = 2;
    uint8 internal constant DISPUTE_FAILED = 3;

    uint8 internal constant SELF_RESERVED = 1;
    uint8 internal constant SELF_CONFIRMED = 2;
    uint8 internal constant SELF_INVALID = 3;
    uint8 internal constant SELF_RELEASED = 4;

    /// Terms as governance sets them, with the inputs the admission checks
    /// read (rule D2-13): the gas and L1 byte price caps in token units
    /// (gasPriceCap, l1PriceCap), the gas and L1 bytes of the largest
    /// on-chain disclosure of the delivery ladder (pubGas, pubBytes) and of a
    /// PASS proof (keyGas, keyBytes), the block gas a proof may take
    /// (blockGasShare), the slacks of the dispute opening and the posting,
    /// the confirmation depth of a posting for a smart-account payer, the
    /// seller's freshness window and the settlement delay, the largest
    /// update message of the feed (maxUpdateBytes), and the binding proof
    /// window F_max with the slack of a binding proof transaction
    /// (bindWindow, bindSlack; checks 6 and 7).
    struct Input {
        /// Judgment of the profile: 0 VOTE (receipt signatures on unless
        /// receiptSigOff), 1 PROOF. A vote profile takes receipt signatures
        /// by default.
        uint8 mode;
        bool receiptSigOff;
        uint96 priceCap;
        uint32 gFixTx;
        uint32 gFixCall;
        uint32 bEnv;
        uint96 gasPriceCap;
        uint96 l1PriceCap;
        uint32 pubGas;
        uint32 pubBytes;
        uint32 keyGas;
        uint32 keyBytes;
        uint96 keyCap;
        uint32 blockGasShare;
        uint32 bundleBlocks;
        uint32 keyBlocks;
        uint32 disputeSlack;
        uint32 postSlack;
        uint32 confirmBlocks;
        uint32 g1271;
        uint16 padLength;
        uint16 sigLimit;
        uint32 proofBlocks;
        uint32 refWindow;
        uint32 freshWindow;
        uint32 settleSlack;
        uint32 maxSkew;
        address verifier;
        bytes32 feedId;
        uint32 maxUpdateBytes;
        uint32 tolerancePpm;
        uint64 toleranceAbs;
        bytes32 tag;
        uint32 bindWindow;
        uint32 bindSlack;
        bytes32 termsHash;
    }

    /// One receipt-signature posting: the bundle (H(ct), h_ek, h_r, leaf) the
    /// buyer signed and the buyer's signature.
    struct Post {
        bytes32 nonce;
        bytes32 ctHash;
        bytes32 ekHash;
        bytes32 rHash;
        bytes32 leaf;
        bytes buyerSig;
    }

    /// One anchor match: the preimage of the posted h_n without its leaf, the
    /// anchored leaf, and the leaf's merkle-v1 path in the unit that holds the
    /// nonce (unit 0 of an epoch anchored as one unit).
    struct Match {
        bytes32 nonce;
        bytes32 ctHash;
        bytes32 ekHash;
        bytes32 rHash;
        bytes32 leaf;
        uint32 unit;
        uint32 position;
        bytes32[] siblings;
    }

    /// A PASS proof: the key and ciphertext the buyer signed for, the
    /// receipt's issuedAt (the rest of the receipt is the purchase's), the
    /// one update message of the registered feed, and, when the seller had
    /// not posted the receipt signature yet, the buyer's signature and the
    /// seller's posting signature. sellerSig is last so that the call data
    /// ends with it.
    struct PassProof {
        bytes32 ek;
        bytes ct;
        uint64 issuedAt;
        bytes update;
        bytes buyerSig;
        bytes sellerSig;
    }

    struct Layout {
        mapping(uint32 => Terms) terms;
        /// h_n = keccak256(H(ct), h_ek, h_r, leaf) with the lowest bit
        /// cleared; the lowest bit is set once the leaf matched the anchor.
        mapping(bytes32 => bytes32) bundles;
        mapping(bytes32 => Record) records;
        mapping(bytes32 => Ladder) ladders;
        /// Deployment setting: a profile activates only with exchange terms
        /// (rule 8.2 row 23). Set once by governance, never cleared.
        bool termsRequired;
    }

    bytes32 internal constant SLOT = keccak256("fairbind.exchange.store.v1");

    /// Transient slot set by every call that counts a measured cost, posts
    /// signatures or anchors: the fixed share of a transaction is counted
    /// once (EIP-1153).
    bytes32 internal constant COST_MARK = keccak256("fairbind.exchange.cost-mark.v1");

    function layout() internal pure returns (Layout storage l) {
        bytes32 slot = SLOT;
        assembly ("memory-safe") {
            l.slot := slot
        }
    }

    /// Marks this transaction as one whose fixed share was counted.
    function mark() internal {
        bytes32 slot = COST_MARK;
        assembly ("memory-safe") {
            tstore(slot, 1)
        }
    }
}
