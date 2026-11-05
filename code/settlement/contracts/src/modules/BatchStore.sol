// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// Storage of the assignment batches, verifier slots and queues, the
/// proportional appeal deposit, seller proofs with their audit and contest,
/// the compensation pools and the side-gain deposit (ADR 0032 to ADR 0035).
/// It sits at a fixed hashed slot, like SamplingStore, so the core layout and
/// every module stay as they were. Nothing here is used by a profile without
/// batch terms.
library BatchStore {
    /// Terms of a batched profile, fixed once before the profile is active
    /// (ADR 0032). slotValue is the value cap that sizes every verifier's slot
    /// count, assignDelay the bound on the wait for a batch value after the
    /// batch closes, keeperSlack the keeper slack the admission check uses,
    /// depositPpm the proportional appeal deposit (zero keeps the fixed one),
    /// auditPpm the audit probability of a seller proof (zero: no seller
    /// proofs), contestBlocks the contest window (zero: no contest), and
    /// sideGainPpm the side-gain rate of a side-gain profile (zero: none).
    struct Terms {
        bool batched;
        uint32 assignDelay;
        uint32 keeperSlack;
        uint32 depositPpm;
        uint32 auditPpm;
        uint32 contestBlocks;
        uint32 sideGainPpm;
        uint96 slotValue;
        bytes32 termsHash;
    }

    /// Assignment batch of one epoch of a profile (ADR 0032): the sample cases
    /// of the epoch opened by its close and the other cases opened in the
    /// blocks it covers, the batch value and the block the source stored it,
    /// and the checkpoint written for the epoch's anchor deadline.
    struct Batch {
        bytes32 value;
        uint64 valueBlock;
        uint64 checkpointVersion;
        bool assigned;
        bool lateMarked;
        bool exited;
        bytes32[] cases;
    }

    /// One case under batch assignment, keyed by its case id (the purchase
    /// nonce, or the proof case id). key orders the verifier queues: batch,
    /// rank within the account's cases of the batch, the account's place in
    /// the batch permutation, and the first ticket. verifier is the queue it
    /// waits in (zero when it waits in none); round the ticket round that
    /// placed it; fixedBlock the block its candidate was fixed; reserve its
    /// liability reservation while it waits.
    struct Entry {
        uint256 key;
        bytes32 ref;
        bytes32 prev;
        bytes32 next;
        uint24 batch;
        uint32 bondId;
        uint32 rank;
        uint32 verifier;
        uint32 round;
        uint8 kind;
        bool late;
        bool paused;
        bool counted;
        uint64 fixedBlock;
        uint64 lateBlock;
        uint96 reserve;
    }

    /// Slots of a verifier (ADR 0032): cases it judges, cases waiting in its
    /// queue and the reservation they hold, the block from which its own exit
    /// request or withdrawal moves cases fixed after it, and the queue ends.
    struct Slots {
        uint32 active;
        uint32 queued;
        uint64 departed;
        uint96 reserved;
        bytes32 head;
        bytes32 tail;
    }

    /// Verifier state that eligibility reads, kept before each change: the
    /// state the verifier had in every block before endBlock (back to the
    /// previous record).
    struct VState {
        uint64 endBlock;
        uint96 bond;
        uint8 status;
        uint64 classes;
    }

    /// High marks of the account's held total (ADR 0033): the highest value
    /// of the current fixed window and of the one before, the window index,
    /// the value after the latest change, and the high mark at the end of the
    /// block before the first change of block snapBlock.
    struct HeldMark {
        uint96 cur;
        uint96 prev;
        uint32 window;
        uint96 last;
        uint96 snap;
        uint64 snapBlock;
    }

    /// A seller proof on a frozen entry (ADR 0034).
    struct Proof {
        uint8 state;
        bool audited;
        bool contested;
        bool weighted;
        uint8 attempt;
        uint32 verifier;
        uint64 auditBlock;
        uint64 contestUntil;
        uint64 judgeDue;
        uint96 bond;
        uint96 contestDeposit;
        address contester;
        bytes32 evidenceHash;
    }

    /// Per-account seller-proof record: proofs and reservations not yet
    /// decided, the block from which seller proofs are off (zero: on) and the
    /// block of the last switch back on.
    struct ProofAccount {
        uint32 pending;
        uint64 offSince;
        uint64 onSince;
        uint32 openSamples;
        uint32 unsealedEpochs;
    }

    /// Compensation pool of an account (ADR 0034): the undistributed amount,
    /// the value of the entries that share it, and the amount distributed per
    /// unit of value so far (scaled by 1e18).
    struct Pool {
        uint256 balance;
        uint256 weight;
        uint256 index;
    }

    /// Share of one proven entry in its account's pool.
    struct Share {
        uint256 entryIndex;
        uint256 accrued;
    }

    /// Side-gain deposit of an account (ADR 0035) and the number of its sales
    /// whose sampling is undecided or whose sample case is open.
    struct SideGain {
        uint128 deposit;
        uint32 open;
    }

    /// The registered use of a review stage's AUX value: the stage and the
    /// block of the transaction that opened it (the appeal, the recheck
    /// selection or the verdict that led to the tiebreak).
    struct ReviewUse {
        uint8 stage;
        uint64 registered;
    }

    struct Layout {
        address[] exts;
        mapping(bytes4 => address) route;
        mapping(uint256 => address) hookExt;
        bool historyOn;
        uint32 slotProfile;
        mapping(uint32 => Terms) terms;
        mapping(uint32 => mapping(uint24 => Batch)) batches;
        mapping(uint32 => mapping(uint24 => mapping(uint32 => uint32))) batchCount;
        mapping(bytes32 => Entry) entries;
        mapping(uint32 => Slots) slots;
        mapping(uint32 => VState[]) history;
        mapping(uint32 => HeldMark) held;
        mapping(bytes32 => uint96) depositExcess;
        mapping(bytes32 => Proof) proofs;
        mapping(uint32 => ProofAccount) proofAccounts;
        mapping(uint32 => Pool) pools;
        mapping(bytes32 => Share) shares;
        mapping(uint32 => SideGain) sideGain;
        mapping(bytes32 => bool) sideGainOpen;
        mapping(uint32 => mapping(uint24 => uint32)) epochOpenCount;
        mapping(uint32 => mapping(uint24 => bool)) epochResolved;
        mapping(uint32 => mapping(uint24 => bool)) epochCounted;
        mapping(bytes32 => ReviewUse) reviewUses;
        mapping(uint32 => mapping(uint24 => bool)) samplePaused;
    }

    /// States of a seller proof (ADR 0034).
    uint8 internal constant P_RESERVED = 1;
    uint8 internal constant P_OPEN = 2;
    uint8 internal constant P_CONTEST = 3;
    uint8 internal constant P_BATCHED = 4;
    uint8 internal constant P_QUEUED = 5;
    uint8 internal constant P_JUDGING = 6;
    uint8 internal constant P_CONFIRMED = 7;
    uint8 internal constant P_FAILED = 8;
    uint8 internal constant P_INCONCLUSIVE = 9;
    uint8 internal constant P_ENDED = 10;
    uint8 internal constant P_INVALID = 11;

    bytes32 internal constant SLOT = keccak256("fairbind.batch.store.v1");

    function layout() internal pure returns (Layout storage l) {
        bytes32 slot = SLOT;
        assembly ("memory-safe") {
            l.slot := slot
        }
    }
}
