// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { G10Sig } from "../g10/G10Base.sol";
import { P5Ctx, IP5Verifier } from "../g10/p5/P5Ref.sol";

/// EIP-3009 token surface used here (USDC FiatTokenV2_2 on Base, or a mock).
interface IAuthToken {
    function transferWithAuthorization(
        address from,
        address to,
        uint256 value,
        uint256 validAfter,
        uint256 validBefore,
        bytes32 nonce,
        bytes memory signature
    ) external;
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// Chainlink VRF v2.5 coordinator surface used here (VRFCoordinatorV2_5 on
/// Base, or VRFCoordinatorV2_5Mock in the tests).
struct VrfWordsRequest {
    bytes32 keyHash;
    uint256 subId;
    uint16 requestConfirmations;
    uint32 callbackGasLimit;
    uint32 numWords;
    bytes extraArgs;
}

interface IVrfCoordinator {
    function requestRandomWords(VrfWordsRequest calldata req) external returns (uint256 requestId);
    function createSubscription() external returns (uint256 subId);
    function addConsumer(uint256 subId, address consumer) external;
}

/// The settlement contract owns its VRF subscription: it creates it at
/// deployment and has no call that cancels it, moves its ownership or adds
/// and removes consumers, so no subscription owner can withdraw or reissue
/// a request. Anyone funds it on the coordinator.
function vrfSubscribe(address coordinator) returns (uint256) {
    return IVrfCoordinator(coordinator).createSubscription();
}

/// Per-profile receiving address. Deployed with CREATE2 (salt = profile id),
/// so the payment's `to` determines the profile. Pays only on the
/// settlement contract's instruction.
contract ReceivingVault {
    address private immutable owner;
    IAuthToken private immutable token;

    constructor(IAuthToken token_) {
        owner = msg.sender;
        token = token_;
    }

    function pay(address to, uint256 amount) external {
        require(msg.sender == owner, "owner");
        require(token.transfer(to, amount), "transfer");
    }
}

/// Registered profile. Every field is part of the profile id
/// (keccak256(abi.encode(profile))); the verifier gas cap is stored apart.
struct Profile {
    address account; // seller account and payout address
    address receiptKey; // key that signs seller receipts
    address unitKey; // key that signs anchor units
    address verifier; // verification contract
    bytes32 codeHash; // its code hash
    uint8 tier; // 0: same-chain data, 1: signed external data
    uint8 flags; // F_BLOCKHASH | F_CT
    uint64 cap; // amount cap V
    uint64 minAmount; // smallest sale amount v_min (0 < v_min <= V)
    uint32 responseDeadline; // r_dl in blocks after the settlement block, 0 = none
    uint64 deposit; // dispute deposit d_nd (token units)
    uint64 maxFeePerGas; // disclosed price cap p_max (wei per gas)
    uint16 epochMultiple; // k: consecutive profile epochs per seller epoch, 1 to K_MAX
    bytes32 inputRule; // canonical input rule identifier (claims are computed under it)
}

/// Seller receipt fields carried in a leaf.
struct Receipt {
    bytes32 nonce;
    uint64 amount;
    bytes32 requestHash;
    bytes32 responseHash;
    bytes32 ctHash;
    bytes32 keyHash;
    bytes32 claimsHash;
    bytes32 materialCommit;
}

struct Leaf {
    Receipt rs;
    uint8 unanswered;
    bool accept;
    bytes sigB;
}

struct Unit {
    bytes32 pid;
    uint32 epoch;
    uint32 count;
    uint32 unitNo;
    bytes32 first;
    bytes32 last;
    bytes32 root;
    bytes32 root0;
    address[] snapshot;
    Leaf[] leaves;
    bytes sellerSig;
}

/// A leaf opened against a stored unit.
struct Opening {
    bytes32 pid;
    uint32 epoch;
    uint32 unitNo;
    uint256 index;
    Receipt rs;
    uint8 unanswered;
    bytes32 sigHash;
    bool beta;
    bool accept;
    bytes32[] path;
}

struct Auth {
    address from;
    address to;
    uint256 value;
    uint256 validAfter;
    uint256 validBefore;
    bytes32 nonce;
}

/// Header of an anchor unit as the seller signed it (evidence of a double
/// signature carries the header and the signature, not the leaves).
struct UnitHeader {
    bytes32 pid;
    uint32 epoch;
    uint32 count;
    uint32 unitNo;
    bytes32 first;
    bytes32 last;
    bytes32 root;
    bytes32 root0;
    bytes32 snapshotHash;
}

/// Seller account: bond, locked deductions, cap high-water mark, episode and
/// suspension. The bond is held by the settlement contract itself, apart
/// from the held payments in the receiving vaults.
struct Account {
    uint128 bond; // balance b available for deductions
    uint128 locked; // deductions taken: locked here, paid to no one
    uint64 capHigh; // V*_p, the largest cap of the account's profiles
    uint32 episode; // starts at 1 with the first bond, +1 at each re-entry
    uint32 failures; // confirmed failures recorded
    bool suspended; // a confirmed failure stops new settlements
    uint32 settlements; // settlements of the account so far (ordinal of the last)
    uint16 k; // seller-epoch multiple, one per account (that of its profiles)
}

/// One freeze: sales of the account settled from block `from` (s_f) up to
/// the failure (settlement ordinal at most `to`) that were still unpaid and
/// unaccepted are frozen; claims run until at + T_CLAIM.
struct Freeze {
    uint64 from; // s_f
    uint64 to; // the account's settlement count at the confirmed failure
    uint64 at; // same block, start of the claim period
}

/// Storage, constants, events and the helpers shared by the settlement
/// contract and its module. Both inherit this layout; the module runs only
/// through the settlement contract's delegatecall, so it reads and writes
/// the same storage.
abstract contract SettlementBase {
    // ------------------------------------------------------------ constants
    uint256 public constant EPOCH_BLOCKS = 300;
    uint256 public constant A_A = 120; // anchor deadline after the epoch's last block
    uint256 public constant D_INC = 30; // binding wait and completion window
    uint256 internal constant M_A = 30; // deadline margin m_a
    uint256 public constant TAU_V = 10;
    uint256 public constant T_V = 100;
    uint256 public constant W_B = 50;
    uint256 public constant T_RS = 40; // receipt deadline after the settlement block
    uint256 public constant T_C = 600; // dispute window after A_e
    uint256 public constant T_P = 300; // proof window after M_e
    uint256 public constant T_D = 100; // seller answer window
    uint256 public constant T_X = 100; // decryption challenge window
    uint256 public constant T_CLAIM = 600; // claim period of a frozen sale
    uint256 public constant N_UNIT = 256; // leaves per anchor unit
    uint256 public constant C_ND = 1_000_000; // upper bound of a profile's deposit
    uint256 public constant P_FLOOR = 1 gwei; // floor of the disclosed price cap
    uint256 public constant K_MAX = 32; // largest seller-epoch multiple accepted
    // settlement records per release unit: a unit's check (or payment) of at
    // most N_REL sales stays below the 2^24 gas cap of one transaction
    // (EIP-7825), whatever the number of sales in the seller epoch
    uint256 internal constant N_REL = 256;
    // VRF request: confirmations the provider waits for, callback gas, the
    // VRF v2.5 extra-args tag (payment in native ETH), value domain tag
    uint16 public constant VRF_CONFIRMATIONS = 3;
    uint32 public constant VRF_CALLBACK_GAS = 100_000;
    bytes4 internal constant EXTRA_ARGS_V1_TAG = bytes4(keccak256("VRF ExtraArgsV1"));
    bytes32 public constant VRF_TAG = keccak256("settlement/sample-input/v1");

    uint8 public constant F_BLOCKHASH = 1;
    uint8 public constant F_CT = 2;

    uint8 public constant ST_HELD = 0;
    uint8 public constant ST_REFUNDED = 1;
    uint8 public constant ST_PAID = 2;
    uint8 public constant ST_ACCEPT_PAID = 3;
    uint8 public constant ST_FROZEN = 4;

    uint8 internal constant SF_MARKED = 1; // unanswered mark in the anchor
    uint8 internal constant SF_ACCEPTED = 2; // valid buyer signature with a = 1
    uint8 internal constant SF_FAILED = 4; // sample failure recorded
    uint8 internal constant SF_SWAPPED = 8; // swap proof recorded

    uint8 public constant K_NONDELIVERY = 1;
    uint8 public constant K_KEY = 2;

    uint8 public constant D_OPEN = 1;
    uint8 public constant D_ANSWERED = 2;
    uint8 public constant D_CLOSED = 3;

    uint8 internal constant FAIL_SAMPLE = 1;
    uint8 internal constant FAIL_ANCHOR_MISSED = 2;
    uint8 internal constant FAIL_DOUBLE_SIGN = 3;
    uint8 internal constant FAIL_SWAP = 4;

    bytes32 public constant RS_TYPEHASH = keccak256(
        "SellerReceipt(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 keyHash,bytes32 profileId,bytes32 codeHash,bytes32 claimsHash,bytes32 materialCommit)"
    );
    bytes32 public constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bytes32 receiptHash,bool accepted)"
    );
    bytes32 public constant UNIT_TYPEHASH = keccak256(
        "AnchorUnit(bytes32 profileId,uint32 epoch,uint32 count,uint32 unitNo,bytes32 firstNonce,bytes32 lastNonce,bytes32 root,bytes32 root0,bytes32 snapshotHash)"
    );
    bytes32 internal constant MANDATE_TYPEHASH = keccak256("DisputeMandate(bytes32 profileId,bytes32 nonce,address delegate,uint8 kinds)");
    bytes32 public constant LEAF0_TAG = keccak256("p5/leaf0/v1");
    bytes32 public constant NODE_TAG = keccak256("settlement/epoch-node/v1");
    bytes32 internal constant NONCE_TAG = keccak256("settlement/bound-nonce/v1");
    bytes32 public constant TAG = keccak256("p5/response/v1");
    uint256 internal constant ERC1271_GAS = 50_000;

    IAuthToken public immutable token;
    address public immutable coordinator; // VRF v2.5 coordinator
    bytes32 public immutable vrfKeyHash; // the provider's key (gas lane)
    uint256 public immutable vrfSubId; // subscription owned by the settlement contract
    uint256 public immutable genesis;
    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public immutable vaultInitHash;

    // -------------------------------------------------------------- storage
    mapping(bytes32 => Profile) internal _profiles;
    mapping(bytes32 => uint32) public verifierGas;
    mapping(bytes32 => address) public vaultOf;
    mapping(address => bytes32) public profileOfVault;

    mapping(address => Account) internal _accounts;
    mapping(address => bytes32[]) internal _accountProfiles;
    mapping(address => uint256) public accountCursor;
    mapping(address => Freeze[]) internal _freezes;

    struct Sale {
        address payer;
        uint64 amount;
        uint32 settledBlock;
        uint32 epoch;
        uint64 validAfter;
        uint8 status;
        bool bindingCompleted;
        uint8 flags;
        uint32 episode;
        uint32 ordinal; // the account's settlement number of this sale
        uint32 index; // its place among the profile epoch's settlement records
        bytes32 binding;
    }

    mapping(bytes32 => Sale) internal _sales; // (pid, nonce)
    mapping(bytes32 => bytes32[]) internal _epochNonces; // (pid, epoch)

    mapping(bytes32 => bytes32) public unitRoot; // (pid, epoch, unit)
    mapping(bytes32 => bytes32) public unitRoot0;
    mapping(bytes32 => bytes32) public unitFirst;
    mapping(bytes32 => bytes32) public unitLast;
    mapping(bytes32 => uint256) public unitStoredAt;
    mapping(bytes32 => uint256) internal _unitSeq; // processing order of the stored unit
    mapping(bytes32 => uint256) internal _rejectSeq; // (pid, epoch, unit, root0, count) => first order
    uint256 internal _seq;
    mapping(bytes32 => uint256) public epochStoredLeaves; // (pid, epoch)
    mapping(bytes32 => uint256) public epochUnits;
    mapping(bytes32 => uint256) public epochMaxUnit;
    mapping(bytes32 => uint256) public epochCount;
    mapping(bytes32 => uint256) public epochCompleteAt;
    mapping(bytes32 => bytes32) public epochHash;
    mapping(bytes32 => uint256) public missedAt; // (pid, epoch) => block of the missed-anchor record
    mapping(bytes32 => bool) public doubleSigned; // (pid, epoch)

    mapping(bytes32 => uint256) public sampleValue; // (pid, epoch)
    mapping(bytes32 => bool) public passed; // (pid, nonce)

    struct LeafInfo {
        bool known;
        bool beta;
        bytes32 hRS;
        bytes32 requestHash;
        bytes32 responseHash;
        bytes32 ctHash;
        bytes32 keyHash;
    }

    mapping(bytes32 => LeafInfo) internal _leafInfo; // (pid, nonce)

    /// One dispute slot: per purchase, per kind, one payer-side slot and one
    /// third-party slot.
    struct Dispute {
        address opener;
        bool authorized; // payer-side slot
        uint8 state;
        bool bad;
        uint64 deadline;
        uint64 deposit;
        uint64 answerBlock; // block at which an answer became this dispute's answer
    }

    /// Seller answers per purchase; they stay on chain and answer later
    /// disputes: ct and k answer both kinds, k alone the key dispute, the
    /// buyer signature the non-delivery dispute.
    struct Answers {
        bytes32 key;
        uint64 ctkBlock; // ct and k posted (0 = none)
        uint64 kBlock; // k alone posted (0 = none)
        uint64 ackBlock; // buyer signature shown (0 = none)
    }

    mapping(bytes32 => Dispute) internal _disputes; // (pid, nonce, kind, side)
    mapping(bytes32 => Answers) internal _answers; // (pid, nonce)
    uint256 internal _lock = 1;
    mapping(bytes32 => uint256) public openDisputes; // (pid, nonce) => disputes not closed

    /// One VRF request per profile epoch.
    struct VrfReq {
        bytes32 pid;
        uint32 epoch;
        uint64 deadline; // M_e: a later fulfillment gives no value
    }

    mapping(uint256 => VrfReq) internal _vrfRequests; // request id
    mapping(bytes32 => bytes32) public sampleInput; // (pid, epoch) => request input, nonzero once requested

    /// Release units marked of the account's seller epoch at the cursor
    /// (one slot per account; reset when the cursor passes).
    mapping(address => uint256) internal releaseUnitsMarked;
    /// (account, first profile epoch of a passed seller epoch) => 1 + the
    /// payment units done, while its payment runs in units; 0 otherwise.
    mapping(bytes32 => uint256) internal _payNext;
    /// (pid, epoch) => the account's number of freezes when the epoch's
    /// anchor was completed: the freeze state that completion effects use.
    mapping(bytes32 => uint256) internal _complFreezes;
    /// (pid, epoch) => settlement records whose completion transfers the
    /// sequential pull has gone through.
    mapping(bytes32 => uint256) internal _pullNext;

    modifier nonReentrant() {
        if (_lock != 1) revert State();
        _lock = 2;
        _;
        _lock = 1;
    }

    // --------------------------------------------------------------- events
    event ProfileRegistered(bytes32 indexed pid, address indexed vault, Profile profile, uint32 verifierGas);
    event Settled(bytes32 indexed pid, address indexed payer, bytes32 indexed nonce, uint256 amount, uint256 epoch, bytes32 binding);
    event BindingCompleted(bytes32 indexed pid, bytes32 indexed nonce, bytes32 binding);
    event UnitStored(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, bytes32 root, uint32 leaves);
    event UnitRejected(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, uint8 reason);
    event EpochAnchored(bytes32 indexed pid, uint32 indexed epoch, uint32 count);
    event AcceptPaid(bytes32 indexed pid, uint32 indexed epoch, uint256 paid);
    event SampleRequested(bytes32 indexed pid, uint256 indexed epoch, uint256 requestId, bytes32 input);
    event SampleValue(bytes32 indexed pid, uint256 indexed epoch, uint256 value);
    event ProofPassed(bytes32 indexed pid, bytes32 indexed nonce);
    event SwapProven(bytes32 indexed pid, bytes32 indexed nonce);
    event Refunded(bytes32 indexed pid, bytes32 indexed nonce, address payer, uint256 amount);
    event Released(address indexed account, uint256 indexed epoch, uint256 paid);
    event ReleaseUnitMarked(
        address indexed account, uint256 indexed epoch, uint256 unit, bytes32 pid, uint256 profileEpoch, uint256 from, uint256 to
    );
    event ReleasePaid(address indexed account, uint256 indexed epoch, uint256 unit, uint256 paid);
    event PaidAfterDispute(bytes32 indexed pid, bytes32 indexed nonce, uint256 amount);
    event DisputeOpened(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, address opener, bool authorized);
    event Delivered(bytes32 indexed pid, bytes32 indexed nonce, bytes ct, bytes32 key);
    event KeyRevealed(bytes32 indexed pid, bytes32 indexed nonce, bytes32 key);
    event AckShown(bytes32 indexed pid, bytes32 indexed nonce);
    event DecryptionChallenged(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, address by, bool mismatch);
    event DisputeClosed(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, bool refunded, address depositTo);
    event BondDeposited(address indexed account, address from, uint256 amount, uint256 bond);
    event ConfirmedFailure(
        address indexed account, bytes32 indexed pid, bytes32 ref, uint8 kind, uint256 frozenFrom, uint256 deducted
    );
    event AnchorMissed(bytes32 indexed pid, uint256 indexed epoch);
    event DoubleSignProven(bytes32 indexed pid, uint256 indexed epoch, uint32 unitNo);
    event Claimed(bytes32 indexed pid, bytes32 indexed nonce, address payer, uint256 amount, address by);
    event Reentered(address indexed account, uint32 episode, uint256 bond);

    error Unknown();
    error Timing();
    error Unauthorized();
    error Membership();
    error State();
    error Binding();
    error OverCap();
    error BelowMin();
    error Duplicate();
    error Late();
    error NotSampled();
    error VerifierFailed();
    error BadProfile();
    error Bond();

    constructor(
        IAuthToken token_,
        address coordinator_,
        bytes32 keyHash_,
        uint256 subId_,
        uint256 genesis_,
        address self_,
        bytes32 vaultInitHash_
    ) {
        token = token_;
        coordinator = coordinator_;
        vrfKeyHash = keyHash_;
        vrfSubId = subId_;
        genesis = genesis_;
        vaultInitHash = vaultInitHash_;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("Settlement"),
                keccak256("10"),
                block.chainid,
                self_
            )
        );
    }

    // -------------------------------------------------------------- helpers
    function _epochOf(uint256 b) internal view returns (uint256) {
        return (b - genesis) / EPOCH_BLOCKS;
    }

    function _lastBlock(uint256 epoch) internal view returns (uint256) {
        return genesis + (epoch + 1) * EPOCH_BLOCKS - 1;
    }

    function _anchorDeadline(uint256 epoch) internal view returns (uint256) {
        return _lastBlock(epoch) + A_A;
    }

    function _valueDeadline(uint256 epoch) internal view returns (uint256) {
        return _anchorDeadline(epoch) + TAU_V + 1 + T_V;
    }

    function _signDeadlineEnd(uint256 epoch) internal view returns (uint256) {
        return _valueDeadline(epoch) + W_B; // W_e
    }

    function _k2(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, b));
    }

    function _k3(bytes32 a, bytes32 b, uint256 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, b, c));
    }

    function _slot(bytes32 pid, bytes32 nonce, uint8 kind, bool payerSide_) internal pure returns (bytes32) {
        return keccak256(abi.encode(pid, nonce, kind, payerSide_));
    }

    function _node(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return keccak256(abi.encode(NODE_TAG, a, b));
    }

    function _rsHash(bytes32 pid, bytes32 codeHash, Receipt calldata r) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(
                RS_TYPEHASH,
                r.nonce,
                uint256(r.amount),
                r.requestHash,
                r.responseHash,
                r.ctHash,
                r.keyHash,
                pid,
                codeHash,
                r.claimsHash,
                r.materialCommit
            )
        );
    }

    function _leaf0Of(bytes32 nonce, bytes32 hRS, uint8 u) internal pure returns (bytes32) {
        return keccak256(abi.encode(LEAF0_TAG, nonce, hRS, u));
    }

    function _leafOf(bytes32 l0, bytes32 sigHash, bool beta, bool a) internal pure returns (bytes32) {
        return keccak256(abi.encode(l0, sigHash, beta, a));
    }

    function _rootOf(bytes32 leaf, uint256 index, bytes32[] calldata path) internal pure returns (bytes32 h) {
        h = leaf;
        for (uint256 i; i < path.length; i++) {
            h = (index & 1) == 0 ? _node(h, path[i]) : _node(path[i], h);
            index >>= 1;
        }
    }

    /// U_n < v / V as h * V < v * 2^256.
    function _sampledBy(uint256 value, bytes32 nonce, uint64 v, uint64 cap) internal pure returns (bool) {
        if (value == 0 || v >= cap) return true;
        uint256 h = uint256(keccak256(abi.encode(value, nonce)));
        uint256 hi;
        assembly ("memory-safe") {
            let lo := mul(h, cap)
            let mm := mulmod(h, cap, not(0))
            hi := sub(sub(mm, lo), lt(mm, lo))
        }
        return hi < v;
    }

    function _epochComplete(bytes32 pid, uint256 epoch) internal view returns (bool) {
        return epochCompleteAt[_k2(pid, bytes32(epoch))] != 0;
    }

    function _open(Opening calldata o) internal view returns (bytes32 hRS) {
        hRS = o.unanswered == 0 ? _rsHash(o.pid, _profiles[o.pid].codeHash, o.rs) : bytes32(0);
        bytes32 l = _leafOf(_leaf0Of(o.rs.nonce, hRS, o.unanswered), o.sigHash, o.beta, o.accept);
        bytes32 uk = _k3(o.pid, bytes32(uint256(o.epoch)), o.unitNo);
        if (unitStoredAt[uk] == 0 || _rootOf(l, o.index, o.path) != unitRoot[uk]) revert Membership();
        if (!_epochComplete(o.pid, o.epoch)) revert Timing();
    }

    /// Refund of a held or frozen sale to its payer (once; a refund is final).
    function _refund(bytes32 pid, bytes32 nonce) internal returns (bool) {
        Sale storage s = _sales[_k2(pid, nonce)];
        uint8 st = _eff(pid, s);
        if (st != ST_HELD && st != ST_FROZEN) return false;
        s.status = ST_REFUNDED;
        ReceivingVault(vaultOf[pid]).pay(s.payer, s.amount);
        emit Refunded(pid, nonce, s.payer, s.amount);
        return true;
    }

    /// Start of the claim period of the latest freeze covering a sale of the
    /// account, or 0 if no freeze covers it.
    function _frozenAt(address acct, Sale storage s) internal view returns (uint256) {
        return _frozenUpTo(acct, s, _freezes[acct].length);
    }

    /// The same over the account's first n freezes only.
    function _frozenUpTo(address acct, Sale storage s, uint256 n) internal view returns (uint256 at) {
        // freezes are pushed in block order with nondecreasing `to` and
        // `at`: scanning from the latest, the first that covers the sale has
        // the largest `at`, and none before the first with to < ordinal does
        Freeze[] storage fs = _freezes[acct];
        uint256 settled = s.settledBlock;
        uint256 ord = s.ordinal;
        for (uint256 i = n; i != 0;) {
            Freeze storage z = fs[--i];
            if (z.to < ord) break;
            if (z.from <= settled) return z.at;
        }
    }

    /// Status of a sale with its anchor's completion effect (T2) applied:
    /// once the anchor of its profile epoch is complete, a marked sale held
    /// or frozen is refunded, and an accepted sale held and covered by no
    /// freeze recorded before the completion is paid to the seller. The
    /// completing transaction fixes these effects; the tokens move by the
    /// pull calls (pullCompletion, pullSale), which write this status.
    function _eff(bytes32 pid, Sale storage s) internal view returns (uint8 st) {
        st = s.status;
        if ((st != ST_HELD && st != ST_FROZEN) || s.flags & (SF_MARKED | SF_ACCEPTED) == 0) return st;
        bytes32 ek = _k2(pid, bytes32(uint256(s.epoch)));
        if (epochCompleteAt[ek] == 0) return st;
        if (s.flags & SF_MARKED != 0) return ST_REFUNDED;
        if (st == ST_HELD && _frozenUpTo(_profiles[pid].account, s, _complFreezes[ek]) == 0) return ST_ACCEPT_PAID;
    }

    /// A held sale is frozen once a freeze covers its settlement block; the
    /// cursor and claims then write the frozen status.
    function _frozen(address acct, Sale storage s) internal view returns (bool) {
        if (s.status == ST_FROZEN) return true;
        return s.status == ST_HELD && _frozenAt(acct, s) != 0;
    }

    /// A confirmed failure of the account: the deduction min(b(V*_p), bond)
    /// is locked and paid to no one, the account is suspended, and every
    /// sale of the account settled from s_f up to this block that is still
    /// unpaid and unaccepted is frozen.
    function _fail(address acct, uint256 sf, uint8 kind, bytes32 pid, bytes32 ref) internal {
        Account storage a = _accounts[acct];
        uint128 x = a.capHigh < a.bond ? a.capHigh : a.bond;
        a.bond -= x;
        a.locked += x;
        a.suspended = true;
        a.failures += 1;
        _freezes[acct].push(Freeze(uint64(sf), a.settlements, uint64(block.number)));
        emit ConfirmedFailure(acct, pid, ref, kind, sf, x);
    }

    /// Pays a sale whose disputes have ended once the cursor has passed its
    /// epoch and it is not frozen (the later of the two).
    function _payAfterDispute(bytes32 pid, bytes32 nonce) internal {
        bytes32 sk = _k2(pid, nonce);
        Sale storage s = _sales[sk];
        address acct = _profiles[pid].account;
        if (_eff(pid, s) != ST_HELD || openDisputes[sk] != 0 || accountCursor[acct] <= s.epoch || _frozen(acct, s)) return;
        s.status = ST_PAID;
        ReceivingVault(vaultOf[pid]).pay(acct, s.amount);
        emit PaidAfterDispute(pid, nonce, s.amount);
    }

    function _ackDigest(
        bytes32 pid,
        bytes32 codeHash,
        bytes32 nonce,
        uint64 amount,
        bytes32 requestHash,
        bytes32 responseHash,
        bytes32 ctHash,
        bytes32 hRS,
        bool accept
    ) internal view returns (bytes32) {
        return G10Sig.typed(
            DOMAIN_SEPARATOR,
            keccak256(
                abi.encode(
                    ACK_TYPEHASH, nonce, uint256(amount), requestHash, responseHash, ctHash, pid, codeHash, hRS, accept
                )
            )
        );
    }

    /// Applies the purchase's stored seller answers to a slot that has none
    /// yet. Returns true when the slot was settled by them.
    function _applyAnswers(bytes32 pid, bytes32 nonce, uint8 kind, Dispute storage d) internal returns (bool) {
        Answers storage a = _answers[_k2(pid, nonce)];
        if (kind == K_NONDELIVERY) {
            if (a.ackBlock != 0) {
                _settleAck(pid, nonce, d);
                return true;
            }
            if (a.ctkBlock != 0 && _counts(pid, nonce, d, a.ctkBlock)) {
                d.state = D_ANSWERED;
                d.answerBlock = uint64(block.number);
                d.deadline = uint64(block.number + T_X);
                return true;
            }
        } else if (a.ctkBlock != 0 || a.kBlock != 0) {
            d.state = D_ANSWERED;
            d.answerBlock = uint64(block.number);
            d.deadline = uint64(block.number + T_X);
            return true;
        }
        return false;
    }

    /// Whether ct and k posted at block `at` count as delivery for slot d:
    /// on the payer side of a profile with a response deadline (an
    /// extension), an answer after block settled + r_dl does not (it is
    /// kept; the dispute ends undelivered after T_d).
    function _counts(bytes32 pid, bytes32 nonce, Dispute storage d, uint256 at) internal view returns (bool) {
        if (!d.authorized) return true;
        uint32 rdl = _profiles[pid].responseDeadline;
        return rdl == 0 || at <= uint256(_sales[_k2(pid, nonce)].settledBlock) + rdl;
    }

    function _openSlot(bytes32 pid, bytes32 nonce, uint8 kind, bool side) internal view returns (bool) {
        Dispute storage d = _disputes[_slot(pid, nonce, kind, side)];
        return d.state == D_OPEN && block.number <= d.deadline;
    }

    function _settleAck(bytes32 pid, bytes32 nonce, Dispute storage d) internal {
        d.state = D_CLOSED;
        openDisputes[_k2(pid, nonce)] -= 1;
        address acct = _profiles[pid].account;
        if (d.deposit != 0) if (!token.transfer(acct, d.deposit)) revert State();
        emit DisputeClosed(pid, nonce, K_NONDELIVERY, false, acct);
        _payAfterDispute(pid, nonce);
    }

    function _boundNonce(bytes32 pid, bytes32 requestHash, bytes32 claimsHash, bytes32 salt) internal view returns (bytes32) {
        return keccak256(
            abi.encode(NONCE_TAG, block.chainid, address(this), pid, keccak256(abi.encode(requestHash, claimsHash)), salt)
        );
    }

    function _unitDigest(UnitHeader memory h) internal view returns (bytes32) {
        return G10Sig.typed(
            DOMAIN_SEPARATOR,
            keccak256(
                abi.encode(
                    UNIT_TYPEHASH, h.pid, h.epoch, h.count, h.unitNo, h.first, h.last, h.root, h.root0, h.snapshotHash
                )
            )
        );
    }
}

/// Reference settlement contract for the signing client and watchtower
/// end-to-end tests: seller bonds, settlement through EIP-3009 into a
/// per-profile vault (amounts from the profile's smallest sale amount v_min
/// to its cap V) with the optional request binding and its completion
/// call (in SettlementModule), anchor units with buyer signatures checked by ecrecover (acceptance
/// payments and unanswered refunds owed from the transaction that completes
/// the epoch's units, as of that transaction, their tokens moved there for
/// the first N_REL settlement records and by pull calls for the rest;
/// rejection records), sample values from Chainlink VRF v2.5 (one request
/// per profile epoch after A_e, fulfilled by the coordinator until M_e; in
/// SettlementModule), proof calls into a
/// verification contract, non-delivery and key disputes that anyone may open
/// (with the payer's mandate signature deciding the slot), decryption
/// challenges, and the response deadline. Confirmed failures (sample proof
/// missing by T_p, missed anchor, double-signed anchor, swap proof), freezes,
/// deductions, claims, suspension and re-entry, and the cursor with its
/// release units (at most N_REL settlement records each, so that every
/// release transaction stays below the 2^24 gas cap) live in
/// SettlementModule, reached through this contract's fallback. Seller epochs
/// group k consecutive profile epochs (k a profile field, one per account).
/// Not implemented: exits, key-compromise suspension, cap and profile
/// changes (so no seller epoch is cut), call fees and levies, bundles, the
/// bypass refund and the response dispute.
contract SampledSettlement is SettlementBase {
    address public immutable module;

    constructor(IAuthToken token_, address coordinator_, bytes32 keyHash_)
        SettlementBase(
            token_,
            coordinator_,
            keyHash_,
            vrfSubscribe(coordinator_),
            block.number,
            address(this),
            keccak256(abi.encodePacked(type(ReceivingVault).creationCode, abi.encode(token_)))
        )
    {
        // admission checks the protocol constants must pass
        require(
            EPOCH_BLOCKS >= TAU_V + 1 + T_V && A_A < EPOCH_BLOCKS && W_B >= 1 + D_INC && T_RS <= T_C - D_INC
                && T_X >= D_INC && M_A >= D_INC && A_A >= D_INC + M_A
        );
        uint256 sub = vrfSubId;
        IVrfCoordinator(coordinator_).addConsumer(sub, address(this));
        // the module gets the vault init hash, not the vault's creation code
        module = address(
            new SettlementModule(token_, coordinator_, keyHash_, sub, block.number, address(this), vaultInitHash)
        );
    }

    /// Calls the settlement contract does not define run in the module on
    /// this contract's storage.
    fallback() external {
        address m = module;
        assembly {
            calldatacopy(0, 0, calldatasize())
            let ok := delegatecall(gas(), m, 0, calldatasize(), 0, 0)
            returndatacopy(0, 0, returndatasize())
            if iszero(ok) { revert(0, returndatasize()) }
            return(0, returndatasize())
        }
    }

    // ---------------------------------------- views of the shared helpers

    function epochOf(uint256 b) public view returns (uint256) {
        return _epochOf(b);
    }

    function lastBlock(uint256 epoch) public view returns (uint256) {
        return _lastBlock(epoch);
    }

    function anchorDeadline(uint256 epoch) public view returns (uint256) {
        return _anchorDeadline(epoch);
    }

    function valueDeadline(uint256 epoch) public view returns (uint256) {
        return _valueDeadline(epoch);
    }

    function signDeadlineEnd(uint256 epoch) public view returns (uint256) {
        return _signDeadlineEnd(epoch);
    }

    function node(bytes32 a, bytes32 b) public pure returns (bytes32) {
        return _node(a, b);
    }

    function rsHash(bytes32 pid, bytes32 codeHash, Receipt calldata r) public pure returns (bytes32) {
        return _rsHash(pid, codeHash, r);
    }

    function leaf0Of(bytes32 nonce, bytes32 hRS, uint8 u) public pure returns (bytes32) {
        return _leaf0Of(nonce, hRS, u);
    }

    function leafOf(bytes32 l0, bytes32 sigHash, bool beta, bool a) public pure returns (bytes32) {
        return _leafOf(l0, sigHash, beta, a);
    }

    function sampledBy(uint256 value, bytes32 nonce, uint64 v, uint64 cap) public pure returns (bool) {
        return _sampledBy(value, nonce, v, cap);
    }

    function epochComplete(bytes32 pid, uint256 epoch) public view returns (bool) {
        return _epochComplete(pid, epoch);
    }

    function ackDigest(bytes32 pid, bytes32 codeHash, bytes32 nonce, uint64 amount, bytes32 requestHash, bytes32 responseHash, bytes32 ctHash, bytes32 hRS, bool accept) public view returns (bytes32) {
        return _ackDigest(pid, codeHash, nonce, amount, requestHash, responseHash, ctHash, hRS, accept);
    }

    function profileId(Profile memory p) public pure returns (bytes32) {
        return keccak256(abi.encode(p));
    }

    function vaultAddress(bytes32 pid) public view returns (address) {
        return address(uint160(uint256(keccak256(abi.encodePacked(bytes1(0xff), address(this), pid, vaultInitHash)))));
    }

    function profile(bytes32 pid) external view returns (Profile memory) {
        return _profiles[pid];
    }

    /// The sale's record, its status with the completion effect applied.
    function sale(bytes32 pid, bytes32 nonce) external view returns (Sale memory x) {
        Sale storage s = _sales[_k2(pid, nonce)];
        x = s;
        x.status = _eff(pid, s);
    }

    function epochNonces(bytes32 pid, uint256 epoch) external view returns (bytes32[] memory) {
        return _epochNonces[_k2(pid, bytes32(epoch))];
    }

    function boundNonce(bytes32 pid, bytes32 requestHash, bytes32 claimsHash, bytes32 salt) public view returns (bytes32) {
        return _boundNonce(pid, requestHash, claimsHash, salt);
    }

    function _root(bytes32[] memory level) internal pure returns (bytes32) {
        uint256 w = level.length;
        while (w > 1) {
            uint256 next = (w + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 a = level[2 * i];
                bytes32 b = 2 * i + 1 < w ? level[2 * i + 1] : a;
                level[i] = _node(a, b);
            }
            w = next;
        }
        return level[0];
    }

    /// kinds: bit 0 non-delivery, bit 1 key, bit 2 decryption, bit 3 response.
    function mandateDigest(bytes32 pid, bytes32 nonce, address delegate, uint8 kinds) public view returns (bytes32) {
        return G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(MANDATE_TYPEHASH, pid, nonce, delegate, kinds)));
    }

    // --------------------------------------------------------- registration

    /// The seller registers its own profile; the receiving vault is deployed
    /// at the address the profile id determines. The account's cap
    /// high-water mark rises to the profile's cap; settlement needs a bond of
    /// at least that mark (b(V) = V for tiers 0 and 1 with s-hat = 1).
    /// The seller-epoch multiple k (1 to K_MAX) is a profile field; the
    /// account's seller epochs are k consecutive profile epochs from its
    /// first profile's registration epoch, so every profile of an account
    /// must declare the same k.
    function register(Profile calldata p, uint32 gv) external returns (bytes32 pid) {
        if (msg.sender != p.account) revert Unauthorized();
        if (p.verifier.codehash != p.codeHash || p.codeHash == bytes32(0)) revert BadProfile();
        if (p.deposit > C_ND || p.cap == 0 || p.tier > 1) revert BadProfile();
        if (p.minAmount == 0 || p.minAmount > p.cap) revert BadProfile();
        if (p.epochMultiple == 0 || p.epochMultiple > K_MAX) revert BadProfile();
        pid = profileId(p);
        if (vaultOf[pid] != address(0)) revert Duplicate();
        address v = address(new ReceivingVault{ salt: pid }(token));
        _profiles[pid] = p;
        verifierGas[pid] = gv;
        vaultOf[pid] = v;
        profileOfVault[v] = pid;
        bytes32[] storage ps = _accountProfiles[p.account];
        Account storage a = _accounts[p.account];
        if (ps.length == 0) {
            accountCursor[p.account] = _epochOf(block.number);
            a.k = p.epochMultiple;
        } else if (a.k != p.epochMultiple) {
            revert BadProfile();
        }
        ps.push(pid);
        if (p.cap > a.capHigh) a.capHigh = p.cap;
        emit ProfileRegistered(pid, v, p, gv);
    }

    // --------------------------------------------------------------- settle

    /// Anyone (normally the x402 facilitator) settles an EIP-3009
    /// authorization whose `to` is a profile's vault. With a salt, the nonce
    /// must be the bound nonce and the binding hash is recorded. Reverts when
    /// the seller's account is suspended or its bond is below b(V*_p).
    function settle(Auth calldata a, bytes calldata sig, bytes32 requestHash, bytes32 claimsHash, bytes32 salt)
        external
    {
        bytes32 pid = profileOfVault[a.to];
        if (pid == bytes32(0)) revert Unknown();
        Profile storage p = _profiles[pid];
        {
            Account storage acc = _accounts[p.account];
            if (acc.suspended) revert State();
            if (acc.bond < acc.capHigh) revert Bond();
        }
        if (a.value > p.cap) revert OverCap();
        if (a.value < p.minAmount) revert BelowMin();
        bytes32 k = _k2(pid, a.nonce);
        if (_sales[k].payer != address(0)) revert Duplicate();
        bytes32 binding;
        if (salt != bytes32(0)) {
            if (a.nonce != boundNonce(pid, requestHash, claimsHash, salt)) revert Binding();
            binding = keccak256(abi.encode(requestHash, claimsHash));
        }
        token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, sig);
        uint256 epoch = _epochOf(block.number);
        Sale storage sl = _sales[k];
        sl.payer = a.from;
        sl.amount = uint64(a.value);
        sl.settledBlock = uint32(block.number);
        sl.epoch = uint32(epoch);
        sl.validAfter = uint64(a.validAfter);
        {
            Account storage acc = _accounts[p.account];
            sl.episode = acc.episode;
            sl.ordinal = ++acc.settlements;
        }
        sl.binding = binding;
        bytes32[] storage en = _epochNonces[_k2(pid, bytes32(epoch))];
        sl.index = uint32(en.length);
        en.push(a.nonce);
        emit Settled(pid, a.from, a.nonce, a.value, epoch, binding);
    }

    // --------------------------------------------------------------- anchor

    function anchorUnit(Unit calldata x) external returns (uint8 reason) {
        uint256 seq = ++_seq;
        reason = _unit(x, seq);
        if (reason != 0) {
            // a rejection after the seller signature was checked is recorded
            // with its order; a signature recorded before its number's stored
            // unit is not evidence of a double signature
            if (reason >= 5) {
                bytes32 rk = keccak256(abi.encode(x.pid, x.epoch, x.unitNo, x.root0, x.count));
                if (_rejectSeq[rk] == 0) _rejectSeq[rk] = seq;
            }
            emit UnitRejected(x.pid, x.epoch, x.unitNo, reason);
        }
    }

    function _unit(Unit calldata x, uint256 seq) internal returns (uint8) {
        Profile storage p = _profiles[x.pid];
        if (p.account == address(0)) return 1;
        if (block.number <= _lastBlock(x.epoch) || block.number > _anchorDeadline(x.epoch)) return 3;
        if (
            G10Sig.recover(
                _unitDigest(
                    UnitHeader(
                        x.pid, x.epoch, x.count, x.unitNo, x.first, x.last, x.root, x.root0, keccak256(abi.encode(x.snapshot))
                    )
                ),
                x.sellerSig
            ) != p.unitKey
        ) return 4;
        bytes32 ek = _k2(x.pid, bytes32(uint256(x.epoch)));
        bytes32 uk = _k3(x.pid, bytes32(uint256(x.epoch)), x.unitNo);
        if (unitStoredAt[uk] != 0) return 5;
        if (_epochNonces[ek].length != x.count || x.unitNo == 0) return 6;
        uint256 n = x.leaves.length;
        if (n == 0 || x.leaves[0].rs.nonce != x.first || x.leaves[n - 1].rs.nonce != x.last) return 7;
        if (n > N_UNIT || epochStoredLeaves[ek] + n > x.count) return 13;
        bytes32[] memory lv = new bytes32[](n);
        bytes32[] memory lv0 = new bytes32[](n);
        uint8[] memory fl = new uint8[](n);
        bytes32 codeHash = p.codeHash;
        for (uint256 i; i < n; i++) {
            uint8 r = _leaf(x, i, codeHash, lv, lv0, fl);
            if (r != 0) return r;
        }
        if (_root(lv) != x.root || _root(lv0) != x.root0) return 12;
        if (x.unitNo > 1) {
            bytes32 pk = _k3(x.pid, bytes32(uint256(x.epoch)), x.unitNo - 1);
            if (unitStoredAt[pk] != 0 && unitLast[pk] >= x.first) return 14;
        }
        {
            bytes32 nk = _k3(x.pid, bytes32(uint256(x.epoch)), x.unitNo + 1);
            if (unitStoredAt[nk] != 0 && unitFirst[nk] <= x.last) return 14;
        }
        _store(x, uk, seq, fl);
        uint256 stored = epochStoredLeaves[ek] + n;
        uint256 units = epochUnits[ek] + 1;
        uint256 maxU = epochMaxUnit[ek];
        if (x.unitNo > maxU) maxU = x.unitNo;
        epochStoredLeaves[ek] = stored;
        epochUnits[ek] = units;
        epochMaxUnit[ek] = maxU;
        if (epochCount[ek] == 0) epochCount[ek] = x.count;
        if (stored == x.count && units == maxU) _complete(x.pid, x.epoch, ek, p);
        return 0;
    }

    function _store(Unit calldata x, bytes32 uk, uint256 seq, uint8[] memory fl) internal {
        unitRoot[uk] = x.root;
        unitRoot0[uk] = x.root0;
        unitFirst[uk] = x.first;
        unitLast[uk] = x.last;
        unitStoredAt[uk] = block.number;
        _unitSeq[uk] = seq;
        emit UnitStored(x.pid, x.epoch, x.unitNo, x.root, uint32(x.leaves.length));
        for (uint256 i; i < fl.length; i++) {
            if (fl[i] != 0) _sales[_k2(x.pid, x.leaves[i].rs.nonce)].flags |= fl[i];
        }
    }

    /// The epoch's units are complete (T2): the completion effects of its
    /// sales are fixed as of this transaction (the account's freezes so far,
    /// _eff), in O(1); the first N_REL settlement records' transfers (all of
    /// them for an epoch of at most N_REL settlements) run here through the
    /// module's pull, the rest by later pull calls.
    function _complete(bytes32 pid, uint32 epoch, bytes32 ek, Profile storage p) internal {
        epochCompleteAt[ek] = block.number;
        _complFreezes[ek] = _freezes[p.account].length;
        if (p.flags & F_BLOCKHASH != 0) epochHash[ek] = blockhash(block.number - 1);
        emit EpochAnchored(pid, epoch, uint32(epochCount[ek]));
        (bool ok,) = module.delegatecall(abi.encodeCall(SettlementModule.pullCompletion, (pid, uint256(epoch))));
        if (!ok) revert State();
    }

    function _leaf(
        Unit calldata x,
        uint256 i,
        bytes32 codeHash,
        bytes32[] memory lv,
        bytes32[] memory lv0,
        uint8[] memory fl
    ) internal view returns (uint8) {
        Leaf calldata l = x.leaves[i];
        bytes32 nonce = l.rs.nonce;
        if (i != 0 && nonce <= x.leaves[i - 1].rs.nonce) return 8;
        Sale storage s = _sales[_k2(x.pid, nonce)];
        if (s.payer == address(0) || s.epoch != x.epoch) return 9;
        if (s.binding != bytes32(0) && l.unanswered == 0) {
            if (s.binding != keccak256(abi.encode(l.rs.requestHash, l.rs.claimsHash))) return 10;
        }
        if (block.number <= uint256(s.settledBlock) + D_INC) return 10; // binding wait
        bytes32 hRS;
        bytes32 sigHash;
        bool beta;
        bool acc;
        if (l.unanswered == 0) {
            if (l.rs.amount != s.amount) return 11;
            hRS = _rsHash(x.pid, codeHash, l.rs);
            if (l.sigB.length != 0) {
                sigHash = keccak256(l.sigB);
                bytes32 d = _ackDigest(
                    x.pid, codeHash, nonce, l.rs.amount, l.rs.requestHash, l.rs.responseHash, l.rs.ctHash, hRS, l.accept
                );
                if (G10Sig.recover(d, l.sigB) == s.payer) {
                    beta = true;
                    acc = l.accept;
                }
            }
        } else {
            fl[i] = SF_MARKED;
        }
        if (acc) fl[i] = SF_ACCEPTED;
        bytes32 l0 = _leaf0Of(nonce, hRS, l.unanswered);
        lv0[i] = l0;
        lv[i] = _leafOf(l0, sigHash, beta, acc);
        return 0;
    }

    // ------------------------------------------------------- sample, proof

    function isSampled(bytes32 pid, bytes32 nonce) public view returns (bool) {
        Sale storage s = _sales[_k2(pid, nonce)];
        if (s.flags & SF_MARKED != 0) return false;
        uint256 value = sampleValue[_k2(pid, bytes32(uint256(s.epoch)))];
        return _sampledBy(value, nonce, s.amount, _profiles[pid].cap);
    }

    /// A sampled sale's proof by anyone until M_e + T_p.
    function prove(Opening calldata o, bytes calldata material) external {
        Profile storage p = _profiles[o.pid];
        _open(o);
        bytes32 sk = _k2(o.pid, o.rs.nonce);
        Sale storage s = _sales[sk];
        if (s.epoch != o.epoch || passed[sk] || o.unanswered != 0) revert State();
        if (block.number > _valueDeadline(o.epoch) + T_P) revert Timing();
        uint256 value = sampleValue[_k2(o.pid, bytes32(uint256(o.epoch)))];
        if (value == 0 && block.number <= _valueDeadline(o.epoch)) revert Timing();
        if (!_sampledBy(value, o.rs.nonce, o.rs.amount, p.cap)) revert NotSampled();
        if (p.verifier.codehash != p.codeHash) revert VerifierFailed();
        P5Ctx memory c = P5Ctx(
            o.rs.nonce,
            o.rs.amount,
            s.validAfter,
            o.rs.requestHash,
            o.rs.responseHash,
            o.rs.claimsHash,
            o.rs.materialCommit,
            p.flags & F_BLOCKHASH != 0 ? epochHash[_k2(o.pid, bytes32(uint256(o.epoch)))] : bytes32(0)
        );
        uint256 gv = verifierGas[o.pid];
        if (gasleft() < gv + gv / 63 + 5_000) revert VerifierFailed();
        (bool ok, bytes memory ret) =
            p.verifier.staticcall{ gas: gv }(abi.encodeCall(IP5Verifier.verify, (c, material)));
        if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert VerifierFailed();
        passed[sk] = true;
        emit ProofPassed(o.pid, o.rs.nonce);
    }

    // ------------------------------------------------------------- disputes

    /// Whether a dispute call is payer-side: the payer itself, or the
    /// delegate named in the payer's mandate sigma_W over (profile id, nonce,
    /// delegate, kinds) with this kind among its kinds. An EOA payer's
    /// mandate that does not recover to the payer leaves the call
    /// third-party; a contract payer's mandate is checked with ERC-1271
    /// isValidSignature (gas-capped staticcall) and a false or reverting
    /// check reverts the call.
    function payerSide(bytes32 pid, bytes32 nonce, uint8 kind, address caller, bytes calldata mandate, uint8 kinds)
        public
        view
        returns (bool)
    {
        address payer = _sales[_k2(pid, nonce)].payer;
        if (caller == payer) return true;
        if (mandate.length == 0 || kinds & (uint8(1) << (kind - 1)) == 0) return false;
        bytes32 dg = mandateDigest(pid, nonce, caller, kinds);
        if (payer.code.length != 0) {
            (bool ok, bytes memory ret) =
                payer.staticcall{ gas: ERC1271_GAS }(abi.encodeWithSelector(0x1626ba7e, dg, mandate));
            if (!ok || ret.length != 32 || bytes4(ret) != bytes4(0x1626ba7e)) revert Unauthorized();
            return true;
        }
        return G10Sig.recover(dg, mandate) == payer;
    }

    /// Non-delivery (kind 1, leaf without a valid buyer signature) or key
    /// dispute (kind 2, ciphertext profile, signed leaf), by anyone until
    /// A_e + T_c, in the caller's slot (payer-side or third-party), on a
    /// held or frozen sale. The opener pays the deposit. A second dispute in
    /// an occupied slot reverts; the two slots neither block nor take over
    /// each other. A seller answer already on chain becomes the new
    /// dispute's answer and T_x runs from this block.
    function openDispute(Opening calldata o, uint8 kind, bytes calldata mandate, uint8 kinds) external nonReentrant {
        bytes32 sk = _k2(o.pid, o.rs.nonce);
        Sale storage s = _sales[sk];
        uint8 st = _eff(o.pid, s);
        if (s.payer == address(0) || s.epoch != o.epoch || (st != ST_HELD && st != ST_FROZEN)) {
            revert State();
        }
        if (block.number > _anchorDeadline(o.epoch) + T_C) revert Timing();
        Profile storage p = _profiles[o.pid];
        if (kind == K_NONDELIVERY) {
            if (o.beta || o.unanswered != 0) revert State();
        } else if (kind == K_KEY) {
            if (!o.beta || p.flags & F_CT == 0) revert State();
        } else {
            revert State();
        }
        bool side = payerSide(o.pid, o.rs.nonce, kind, msg.sender, mandate, kinds);
        Dispute storage d = _disputes[_slot(o.pid, o.rs.nonce, kind, side)];
        if (d.state != 0) revert Duplicate();
        bytes32 hRS = _open(o);
        LeafInfo storage li = _leafInfo[sk];
        if (!li.known) {
            li.known = true;
            li.beta = o.beta;
            li.hRS = hRS;
            li.requestHash = o.rs.requestHash;
            li.responseHash = o.rs.responseHash;
            li.ctHash = o.rs.ctHash;
            li.keyHash = o.rs.keyHash;
        }
        uint64 dep = p.deposit;
        if (dep != 0 && !token.transferFrom(msg.sender, address(this), dep)) revert State();
        d.opener = msg.sender;
        d.authorized = side;
        d.deposit = dep;
        d.state = D_OPEN;
        d.deadline = uint64(block.number + T_D);
        openDisputes[sk] += 1;
        emit DisputeOpened(o.pid, o.rs.nonce, kind, msg.sender, side);
        _applyAnswers(o.pid, o.rs.nonce, kind, d);
    }


}

/// Confirmed failures, freezes, deductions, claims, bond, suspension and
/// re-entry, the swap proof and the cursor. Deployed by SampledSettlement and
/// reached only through its delegatecall, so it works on that contract's
/// storage, address and domain.
contract SettlementModule is SettlementBase {
    constructor(
        IAuthToken token_,
        address coordinator_,
        bytes32 keyHash_,
        uint256 subId_,
        uint256 genesis_,
        address self_,
        bytes32 vaultInitHash_
    ) SettlementBase(token_, coordinator_, keyHash_, subId_, genesis_, self_, vaultInitHash_) { }

    // -------------------------------------------------------------- binding

    /// Fills an empty binding hash within D_INC of the settlement block.
    function completeBinding(bytes32 pid, bytes32 nonce, bytes32 requestHash, bytes32 claimsHash, bytes32 salt)
        external
    {
        Sale storage s = _sales[_k2(pid, nonce)];
        if (s.payer == address(0) || s.binding != bytes32(0)) revert State();
        if (block.number > s.settledBlock + D_INC) revert Timing();
        if (nonce != _boundNonce(pid, requestHash, claimsHash, salt)) revert Binding();
        s.binding = keccak256(abi.encode(requestHash, claimsHash));
        s.bindingCompleted = true;
        emit BindingCompleted(pid, nonce, s.binding);
    }

    // ------------------------------------------------------ sample value

    /// Commitment to the profile epoch's anchor: the stored roots of its
    /// units in unit order (fixed once the epoch is complete, before A_e).
    function anchorCommitment(bytes32 pid, uint256 epoch) public view returns (bytes32 h) {
        uint256 n = epochMaxUnit[_k2(pid, bytes32(epoch))];
        for (uint256 u = 1; u <= n; u++) {
            h = keccak256(abi.encode(h, unitRoot[_k3(pid, bytes32(epoch), u)]));
        }
    }

    /// SAMPLE: the profile epoch's one VRF request, by anyone, after A_e
    /// and until M_e, for an epoch whose anchor is complete. The request
    /// input binds the chain, this contract, the profile, the epoch and the
    /// anchor commitment; the contract never sends a second request for the
    /// same profile epoch, so no input repeats and no one can reissue a
    /// request to draw another value. If no value arrives by M_e, every
    /// sale of the epoch (unanswered marks excepted) is sampled.
    function requestSample(bytes32 pid, uint256 epoch) external returns (uint256 id) {
        bytes32 ek = _k2(pid, bytes32(epoch));
        if (block.number <= _anchorDeadline(epoch) || block.number > _valueDeadline(epoch)) revert Timing();
        if (epochCompleteAt[ek] == 0 || sampleInput[ek] != 0) revert State();
        bytes32 input =
            keccak256(abi.encode(VRF_TAG, block.chainid, address(this), pid, epoch, anchorCommitment(pid, epoch)));
        sampleInput[ek] = input; // before the call: one request per profile epoch
        id = IVrfCoordinator(coordinator).requestRandomWords(
            VrfWordsRequest({
                keyHash: vrfKeyHash,
                subId: vrfSubId,
                requestConfirmations: VRF_CONFIRMATIONS,
                callbackGasLimit: VRF_CALLBACK_GAS,
                numWords: 1,
                extraArgs: abi.encodeWithSelector(EXTRA_ARGS_V1_TAG, true)
            })
        );
        _vrfRequests[id] = VrfReq(pid, uint32(epoch), uint64(_valueDeadline(epoch)));
        emit SampleRequested(pid, epoch, id, input);
    }

    /// R_e from the request input, the coordinator's request id and the
    /// VRF word; 0 stands for "no value", so it is mapped to 1.
    function sampleValueOf(bytes32 input, uint256 requestId, uint256 word) public pure returns (uint256 v) {
        v = uint256(keccak256(abi.encode(input, requestId, word)));
        if (v == 0) v = 1;
    }

    /// VRF v2.5 callback, accepted from the coordinator only. The first
    /// word of a known request fulfilled by M_e becomes R_e; an unknown or
    /// late request, or a second fulfillment, leaves the value unchanged.
    function rawFulfillRandomWords(uint256 requestId, uint256[] calldata words) external {
        if (msg.sender != coordinator) revert Unauthorized();
        VrfReq memory r = _vrfRequests[requestId];
        if (r.deadline == 0 || block.number > r.deadline || words.length == 0) return;
        bytes32 ek = _k2(r.pid, bytes32(uint256(r.epoch)));
        if (sampleValue[ek] != 0) return;
        uint256 v = sampleValueOf(sampleInput[ek], requestId, words[0]);
        sampleValue[ek] = v;
        emit SampleValue(r.pid, r.epoch, v);
    }

    function vrfRequest(uint256 requestId) external view returns (VrfReq memory) {
        return _vrfRequests[requestId];
    }

    // ------------------------------------------------- dispute answers

    /// side: 1 payer-side slot, 0 third-party slot.
    function dispute(bytes32 pid, bytes32 nonce, uint8 kind, uint8 side) external view returns (Dispute memory) {
        return _disputes[_slot(pid, nonce, kind, side == 1)];
    }

    function answers(bytes32 pid, bytes32 nonce) external view returns (Answers memory) {
        return _answers[_k2(pid, nonce)];
    }

    function decryptHash(bytes32 k, bytes32 nonce, bytes calldata ct) public pure returns (bytes32 h) {
        if (ct.length % 32 != 0) return bytes32(0);
        bytes32 tag = TAG;
        assembly ("memory-safe") {
            let out := mload(0x40)
            mstore(out, tag)
            let words := shr(5, ct.length)
            let scratch := add(add(out, 0x20), ct.length)
            mstore(scratch, k)
            mstore(add(scratch, 0x20), nonce)
            for { let j := 0 } lt(j, words) { j := add(j, 1) } {
                mstore(add(scratch, 0x40), j)
                let ks := keccak256(scratch, 0x60)
                mstore(add(add(out, 0x20), shl(5, j)), xor(calldataload(add(ct.offset, shl(5, j))), ks))
            }
            h := keccak256(out, add(0x20, ct.length))
        }
    }

    /// The seller's ct and k for the purchase, while a dispute of either
    /// kind is open and unanswered; it answers every open slot of both kinds
    /// (non-delivery slots only where it counts as delivery).
    function answerDeliver(bytes32 pid, bytes32 nonce, bytes calldata ct, bytes32 k) external nonReentrant {
        if (
            !_openSlot(pid, nonce, K_NONDELIVERY, true) && !_openSlot(pid, nonce, K_NONDELIVERY, false)
                && !_openSlot(pid, nonce, K_KEY, true) && !_openSlot(pid, nonce, K_KEY, false)
        ) revert State();
        Answers storage a = _answers[_k2(pid, nonce)];
        if (a.ctkBlock != 0) revert Duplicate();
        LeafInfo storage li = _leafInfo[_k2(pid, nonce)];
        if (keccak256(ct) != li.ctHash || keccak256(abi.encode(k)) != li.keyHash) revert State();
        a.key = k;
        a.ctkBlock = uint64(block.number);
        emit Delivered(pid, nonce, ct, k);
        for (uint256 i; i < 4; i++) {
            uint8 kind = i < 2 ? K_NONDELIVERY : K_KEY;
            Dispute storage d = _disputes[_slot(pid, nonce, kind, i % 2 == 1)];
            if (d.state == D_OPEN) _applyAnswers(pid, nonce, kind, d);
        }
    }

    /// The seller's answer with the buyer's valid signature for the nonce:
    /// open non-delivery slots end on the seller's side and their deposits go
    /// to the seller; the signature stays on chain for later ones.
    function answerWithAck(bytes32 pid, bytes32 nonce, bool accept, bytes calldata sigB) external nonReentrant {
        if (!_openSlot(pid, nonce, K_NONDELIVERY, true) && !_openSlot(pid, nonce, K_NONDELIVERY, false)) revert State();
        bytes32 sk = _k2(pid, nonce);
        LeafInfo storage li = _leafInfo[sk];
        Sale storage s = _sales[sk];
        bytes32 dg = _ackDigest(
            pid, _profiles[pid].codeHash, nonce, s.amount, li.requestHash, li.responseHash, li.ctHash, li.hRS, accept
        );
        if (G10Sig.recover(dg, sigB) != s.payer) revert Unauthorized();
        _answers[sk].ackBlock = uint64(block.number);
        emit AckShown(pid, nonce);
        for (uint256 i; i < 2; i++) {
            Dispute storage d = _disputes[_slot(pid, nonce, K_NONDELIVERY, i == 1)];
            if (d.state == D_OPEN) _settleAck(pid, nonce, d);
        }
    }

    /// The seller's key alone, while a key dispute is open; it answers the
    /// open key slots.
    function answerKey(bytes32 pid, bytes32 nonce, bytes32 k) external nonReentrant {
        if (!_openSlot(pid, nonce, K_KEY, true) && !_openSlot(pid, nonce, K_KEY, false)) revert State();
        Answers storage a = _answers[_k2(pid, nonce)];
        if (a.kBlock != 0 || a.ctkBlock != 0) revert Duplicate();
        if (keccak256(abi.encode(k)) != _leafInfo[_k2(pid, nonce)].keyHash) revert State();
        a.key = k;
        a.kBlock = uint64(block.number);
        emit KeyRevealed(pid, nonce, k);
        for (uint256 i; i < 2; i++) {
            Dispute storage d = _disputes[_slot(pid, nonce, K_KEY, i == 1)];
            if (d.state == D_OPEN) _applyAnswers(pid, nonce, K_KEY, d);
        }
    }

    /// Decryption challenge by anyone on one slot: ct must match h_ct; the
    /// key is the answered one, or, for an open key slot, a key the caller
    /// received that matches h_k. A mismatch with h_r marks the slot for a
    /// refund at its close; a match changes nothing.
    function challengeDecrypt(bytes32 pid, bytes32 nonce, uint8 kind, uint8 side, bytes calldata ct, bytes32 offchainKey)
        external
        nonReentrant
        returns (bool mismatch)
    {
        bytes32 sk = _k2(pid, nonce);
        Dispute storage d = _disputes[_slot(pid, nonce, kind, side == 1)];
        LeafInfo storage li = _leafInfo[sk];
        bytes32 k;
        if (d.state == D_ANSWERED && block.number <= d.deadline) {
            k = _answers[sk].key;
        } else if (kind == K_KEY && d.state == D_OPEN && keccak256(abi.encode(offchainKey)) == li.keyHash) {
            k = offchainKey;
        } else {
            revert State();
        }
        if (keccak256(ct) != li.ctHash) revert State();
        mismatch = decryptHash(k, nonce, ct) != li.responseHash;
        if (mismatch) d.bad = true;
        emit DecryptionChallenged(pid, nonce, kind, msg.sender, mismatch);
    }

    /// Anyone closes a slot after its window: unanswered (or answered late
    /// on the payer side) after T_d, or answered after T_x. No delivery or a
    /// recorded mismatch refunds (once; a refund is final) and returns the
    /// deposit to the opener. Answered without mismatch: a payer-side
    /// opener gets the deposit back (non-delivery delivered by ct and k, or
    /// key dispute answered by k); a third-party deposit goes to the seller.
    /// A sale whose last dispute ends without a refund is paid now if the
    /// cursor has passed its epoch and it is not frozen.
    function closeDispute(bytes32 pid, bytes32 nonce, uint8 kind, uint8 side)
        external
        nonReentrant
        returns (bool refunded)
    {
        bytes32 sk = _k2(pid, nonce);
        Dispute storage d = _disputes[_slot(pid, nonce, kind, side == 1)];
        if ((d.state != D_OPEN && d.state != D_ANSWERED) || block.number <= d.deadline) revert State();
        address depositTo;
        if (d.state == D_OPEN || d.bad) {
            refunded = _refund(pid, nonce);
            depositTo = d.opener;
        } else {
            depositTo = d.authorized ? d.opener : _profiles[pid].account;
        }
        d.state = D_CLOSED;
        openDisputes[sk] -= 1;
        if (d.deposit != 0) if (!token.transfer(depositTo, d.deposit)) revert State();
        emit DisputeClosed(pid, nonce, kind, refunded, depositTo);
        _payAfterDispute(pid, nonce);
    }

    // ------------------------------------------------------------ accounts

    function account(address acct) external view returns (Account memory) {
        return _accounts[acct];
    }

    function accountProfiles(address acct) external view returns (bytes32[] memory) {
        return _accountProfiles[acct];
    }

    function freezes(address acct) external view returns (Freeze[] memory) {
        return _freezes[acct];
    }

    /// b(V*_p) for tiers 0 and 1 with s-hat = 1: the cap high-water mark.
    function bondRequired(address acct) public view returns (uint256) {
        return _accounts[acct].capHigh;
    }

    /// Anyone adds to an account's bond (from the caller's tokens). The
    /// first bond starts the first episode.
    function depositBond(address acct, uint256 amount) external {
        if (_accountProfiles[acct].length == 0) revert Unknown();
        if (!token.transferFrom(msg.sender, address(this), amount)) revert State();
        Account storage a = _accounts[acct];
        a.bond += uint128(amount);
        if (a.episode == 0) a.episode = 1;
        emit BondDeposited(acct, msg.sender, amount, a.bond);
    }

    /// Re-entry of a suspended account at any time once its bond, topped up
    /// by `topUp` from the account, is at least b(V*_p): a new episode
    /// starts. Frozen sales stay frozen.
    function reenter(uint256 topUp) external {
        Account storage a = _accounts[msg.sender];
        if (!a.suspended) revert State();
        if (topUp != 0) {
            if (!token.transferFrom(msg.sender, address(this), topUp)) revert State();
            a.bond += uint128(topUp);
            emit BondDeposited(msg.sender, msg.sender, topUp, a.bond);
        }
        if (a.bond < a.capHigh) revert Bond();
        a.suspended = false;
        a.episode += 1;
        emit Reentered(msg.sender, a.episode, a.bond);
    }

    // ------------------------------------------------------------ failures

    function _sampleFailure(bytes32 pid, bytes32 nonce, Sale storage s) internal {
        s.flags |= SF_FAILED;
        if (_eff(pid, s) == ST_HELD) s.status = ST_FROZEN;
        _fail(_profiles[pid].account, s.settledBlock, FAIL_SAMPLE, pid, nonce);
    }

    /// Failure processing of a sample case that has no pass recorded by
    /// M_e + T_p, by anyone after that block: a confirmed failure with s_f at
    /// the sale's settlement block. A sale refunded in a dispute stays in the
    /// sample; only unanswered marks leave it.
    function declareSampleFailure(bytes32 pid, bytes32 nonce) external {
        bytes32 sk = _k2(pid, nonce);
        Sale storage s = _sales[sk];
        if (s.payer == address(0)) revert Unknown();
        if (block.number <= _valueDeadline(s.epoch) + T_P) revert Timing();
        if (!_epochComplete(pid, s.epoch)) revert State();
        if (s.flags & (SF_MARKED | SF_FAILED) != 0 || passed[sk]) revert State();
        if (!_sampledBy(sampleValue[_k2(pid, bytes32(uint256(s.epoch)))], nonce, s.amount, _profiles[pid].cap)) {
            revert NotSampled();
        }
        _sampleFailure(pid, nonce, s);
    }

    function _anchorMissed(bytes32 pid, uint256 epoch, bytes32 ek) internal {
        missedAt[ek] = block.number;
        emit AnchorMissed(pid, epoch);
        uint256 sf = _sales[_k2(pid, _epochNonces[ek][0])].settledBlock;
        _fail(_profiles[pid].account, sf, FAIL_ANCHOR_MISSED, pid, bytes32(epoch));
    }

    /// Failure processing of a missed anchor, by anyone after A_e: the
    /// profile epoch has settlements and its units were not complete by
    /// A_e. A confirmed failure with s_f at the epoch's first settlement.
    function declareAnchorMissed(bytes32 pid, uint256 epoch) external {
        bytes32 ek = _k2(pid, bytes32(epoch));
        if (_epochNonces[ek].length == 0 || epochCompleteAt[ek] != 0 || missedAt[ek] != 0) revert State();
        if (block.number <= _anchorDeadline(epoch)) revert Timing();
        _anchorMissed(pid, epoch, ek);
    }

    /// Evidence of a double-signed anchor, by anyone: a seller signature on
    /// a unit with the (profile, epoch, unit number) of a stored unit whose
    /// root0 or count differs from it. A signature whose (profile, epoch,
    /// unit number, root0, count) matches a rejection recorded (after its
    /// signature was checked) before that stored unit is not evidence. One
    /// confirmed failure per profile epoch, with s_f at its first
    /// settlement.
    function proveDoubleSign(UnitHeader calldata h, bytes calldata sig) external {
        bytes32 ek = _k2(h.pid, bytes32(uint256(h.epoch)));
        bytes32 uk = _k3(h.pid, bytes32(uint256(h.epoch)), h.unitNo);
        if (unitStoredAt[uk] == 0) revert State();
        if (h.root0 == unitRoot0[uk] && h.count == epochCount[ek]) revert State();
        if (G10Sig.recover(_unitDigest(h), sig) != _profiles[h.pid].unitKey) revert Unauthorized();
        uint256 r = _rejectSeq[keccak256(abi.encode(h.pid, h.epoch, h.unitNo, h.root0, h.count))];
        if (r != 0 && r < _unitSeq[uk]) revert State();
        if (doubleSigned[ek]) revert Duplicate();
        doubleSigned[ek] = true;
        emit DoubleSignProven(h.pid, h.epoch, h.unitNo);
        uint256 sf = _sales[_k2(h.pid, _epochNonces[ek][0])].settledBlock;
        _fail(_profiles[h.pid].account, sf, FAIL_DOUBLE_SIGN, h.pid, bytes32(uint256(h.epoch)));
    }

    /// Swap proof: a seller-signed receipt for an anchored unsigned leaf
    /// whose receipt part differs. Accepted from the epoch's anchor until the
    /// cursor passes the epoch, also for refunded sales and suspended
    /// accounts; once per sale. A confirmed failure with s_f at the sale's
    /// settlement block (the sale itself is frozen and claimed).
    function proveSwap(Opening calldata o, Receipt calldata signedRs, bytes calldata rsSig) external {
        Profile storage p = _profiles[o.pid];
        bytes32 hLeaf = _open(o);
        if (o.unanswered != 0 || o.beta) revert State();
        if (signedRs.nonce != o.rs.nonce) revert State();
        bytes32 hSigned = _rsHash(o.pid, p.codeHash, signedRs);
        if (hSigned == hLeaf) revert State();
        if (G10Sig.recover(G10Sig.typed(DOMAIN_SEPARATOR, hSigned), rsSig) != p.receiptKey) revert Unauthorized();
        Sale storage s = _sales[_k2(o.pid, o.rs.nonce)];
        if (s.flags & SF_SWAPPED != 0) revert Duplicate();
        if (accountCursor[p.account] > o.epoch) revert Timing();
        s.flags |= SF_SWAPPED;
        if (s.status == ST_HELD) s.status = ST_FROZEN;
        emit SwapProven(o.pid, o.rs.nonce);
        _fail(p.account, s.settledBlock, FAIL_SWAP, o.pid, o.rs.nonce);
    }

    // -------------------------------------------------------------- claims

    /// End of the claim period of a frozen sale, or 0 if it is not frozen.
    function claimDeadline(bytes32 pid, bytes32 nonce) public view returns (uint256) {
        Sale storage s = _sales[_k2(pid, nonce)];
        uint8 st = _eff(pid, s);
        if (st != ST_HELD && st != ST_FROZEN) return 0;
        uint256 at = _frozenAt(_profiles[pid].account, s);
        return at == 0 ? 0 : at + T_CLAIM;
    }

    /// Claim of a frozen sale by anyone within T_claim of its freeze; the
    /// refund always goes to the sale's payer. Unclaimed frozen payments
    /// stay in the vault and never go to the seller.
    function claimFrozen(bytes32 pid, bytes32 nonce) external {
        uint256 end = claimDeadline(pid, nonce);
        if (end == 0) revert State();
        if (block.number > end) revert Timing();
        Sale storage s = _sales[_k2(pid, nonce)];
        _refund(pid, nonce);
        emit Claimed(pid, nonce, s.payer, s.amount, msg.sender);
    }

    // --------------------------------------------------- completion pulls

    /// Moves the tokens of completion effects that are fixed but not yet
    /// transferred, for the settlement records [lo, hi) of a complete
    /// profile epoch: refunds of marked sales to their payers, and one
    /// payment to the seller for its accepted sales.
    function _pullRange(bytes32 pid, uint256 epoch, uint256 lo, uint256 hi) internal returns (uint256 paid) {
        bytes32[] storage ns = _epochNonces[_k2(pid, bytes32(epoch))];
        ReceivingVault v = ReceivingVault(vaultOf[pid]);
        for (uint256 i = lo; i < hi; i++) {
            Sale storage s = _sales[_k2(pid, ns[i])];
            uint8 e = _eff(pid, s);
            if (e == s.status) continue;
            s.status = e;
            if (e == ST_REFUNDED) {
                v.pay(s.payer, s.amount);
                emit Refunded(pid, ns[i], s.payer, s.amount);
            } else {
                paid += s.amount;
            }
        }
        if (paid != 0) {
            v.pay(_profiles[pid].account, paid);
            emit AcceptPaid(pid, uint32(epoch), paid);
        }
    }

    /// Completion pull, by anyone, at any time after the anchor's completion
    /// (the completing transaction runs the first): the next N_REL
    /// settlement records of the profile epoch in settlement order. Returns
    /// the records gone through so far.
    function pullCompletion(bytes32 pid, uint256 epoch) external returns (uint256 hi) {
        bytes32 ek = _k2(pid, bytes32(epoch));
        uint256 lo = _pullNext[ek];
        uint256 n = _epochNonces[ek].length;
        if (epochCompleteAt[ek] == 0 || lo >= n) revert State();
        hi = lo + N_REL < n ? lo + N_REL : n;
        _pullNext[ek] = hi;
        _pullRange(pid, epoch, lo, hi);
    }

    /// Pull of one sale's completion transfer, by anyone (the refund goes to
    /// the payer, the acceptance payment to the seller).
    function pullSale(bytes32 pid, bytes32 nonce) external {
        Sale storage s = _sales[_k2(pid, nonce)];
        if (_eff(pid, s) == s.status) revert State();
        _pullRange(pid, s.epoch, s.index, s.index + 1);
    }

    /// Whether the sale has a fixed completion transfer not yet made, and
    /// the records the sequential completion pull has gone through.
    function pullPending(bytes32 pid, bytes32 nonce) external view returns (bool pending, uint256 pulled) {
        Sale storage s = _sales[_k2(pid, nonce)];
        pending = _eff(pid, s) != s.status;
        pulled = _pullNext[_k2(pid, bytes32(uint256(s.epoch)))];
    }

    // -------------------------------------------------------------- cursor

    /// Release units of a seller epoch E (the k profile epochs from `first`):
    /// over the profile epochs of E in order, within each over the account's
    /// profiles in registration order, within each the profile epoch's
    /// settlement records in settlement order, N_REL per unit (the last unit
    /// of a profile epoch may be shorter; a profile epoch without
    /// settlements has none). Returns unit g as the records [lo, hi) of
    /// profile pid in profile epoch e (pid = 0 if E has no unit g), the
    /// number of units of E and its number of settlements.
    function _unitAt(address acct, uint256 first, uint256 g)
        internal
        view
        returns (bytes32 pid, uint256 e, uint256 lo, uint256 hi, uint256 total, uint256 sales)
    {
        bytes32[] storage pids = _accountProfiles[acct];
        uint256 np = pids.length;
        uint256 k = _accounts[acct].k;
        for (uint256 i; i < k; i++) {
            for (uint256 j; j < np; j++) {
                uint256 n = _epochNonces[_k2(pids[j], bytes32(first + i))].length;
                uint256 u = (n + N_REL - 1) / N_REL;
                if (g >= total && g < total + u) {
                    pid = pids[j];
                    e = first + i;
                    lo = (g - total) * N_REL;
                    hi = lo + N_REL < n ? lo + N_REL : n;
                }
                total += u;
                sales += n;
            }
        }
    }

    /// Release state of the account: release units of the seller epoch at
    /// the cursor (marked so far, in all) and its settlements; and the next
    /// payment unit (0-based) of the passed seller epoch from `first`, or
    /// type(uint256).max if its payment does not run in units or is done.
    function releaseState(address acct, uint256 first)
        external
        view
        returns (uint256 marked, uint256 total, uint256 sales, uint256 payNext)
    {
        (,,,, total, sales) = _unitAt(acct, accountCursor[acct], type(uint256).max);
        marked = releaseUnitsMarked[acct];
        unchecked {
            payNext = _payNext[_k2(bytes32(uint256(uint160(acct))), bytes32(first))] - 1;
        }
    }

    /// Cursor conditions C0 to C3 that wait on deadlines, for a profile
    /// epoch with settlements: W_e, A_e + T_c and M_e + T_p have passed.
    function _ripe(uint256 e) internal view {
        if (block.number <= _signDeadlineEnd(e) || block.number <= _anchorDeadline(e) + T_C) revert Timing();
        if (block.number <= _valueDeadline(e) + T_P) revert Timing();
    }

    /// Release unit call, by anyone: checks and marks the next release unit
    /// of the seller epoch E at the account's cursor, in unit order, only
    /// after E's last block and the deadlines of the unit's profile epoch.
    /// A profile epoch whose units were not complete by A_e is recorded as
    /// a missed anchor (if not yet recorded); otherwise every sampled sale of
    /// the unit (unanswered marks excepted, refunded sales included) without
    /// a pass by M_e + T_p is a confirmed failure, with its freeze. The call
    /// pays no sale. The cursor passes E only once every unit of E is marked.
    function releaseUnit(address acct) external returns (uint256 unit) {
        uint256 first = accountCursor[acct];
        if (_accountProfiles[acct].length == 0) revert Unknown();
        if (block.number <= _lastBlock(first + _accounts[acct].k - 1)) revert Timing();
        unit = releaseUnitsMarked[acct];
        (bytes32 pid, uint256 e, uint256 lo, uint256 hi,,) = _unitAt(acct, first, unit);
        if (pid == bytes32(0)) revert State();
        _ripe(e);
        _check(pid, e, lo, hi);
        releaseUnitsMarked[acct] = unit + 1;
        emit ReleaseUnitMarked(acct, first, unit, pid, e, lo, hi);
    }

    /// Cursor step for one seller epoch E of the account: the k profile
    /// epochs from the cursor, over all the account's profiles, only after
    /// E's last block. A profile epoch of E without settlements needs
    /// nothing more; for every other profile epoch e of E the call waits for
    /// W_e and A_e + T_c and M_e + T_p of that e. The cursor passes E only
    /// when every release unit of E is marked (releaseUnit); a seller epoch
    /// of at most N_REL settlements fits one transaction, and this call
    /// first checks and marks its remaining units itself, in unit order.
    /// After all failures and freezes, the cursor moves to the profile epoch
    /// after E, and the held sales of E that are not frozen and have no open
    /// dispute are paid: in this call, one vault payment per profile, when E
    /// has at most N_REL settlements; otherwise afterwards, by releasePay
    /// one unit at a time. Frozen sales are marked frozen; a sale with an
    /// open dispute stays held and is paid when its last dispute ends
    /// without a refund.
    function release(address acct) external returns (uint256 paid) {
        uint256 first = accountCursor[acct];
        bytes32[] storage pids = _accountProfiles[acct];
        uint256 np = pids.length;
        if (np == 0) revert Unknown();
        uint256 k = _accounts[acct].k;
        // the settlement counts of E are fixed only once E is over
        if (block.number <= _lastBlock(first + k - 1)) revert Timing();
        uint256 busy; // bit i: profile epoch first + i has settlements
        uint256 sales;
        for (uint256 i; i < k; i++) {
            uint256 e = first + i;
            uint256 total;
            for (uint256 j; j < np; j++) {
                total += _epochNonces[_k2(pids[j], bytes32(e))].length;
            }
            if (total == 0) continue;
            _ripe(e);
            busy |= 1 << i;
            sales += total;
        }
        if (busy != 0) {
            (,,,, uint256 total,) = _unitAt(acct, first, type(uint256).max);
            for (uint256 g = releaseUnitsMarked[acct]; g < total; g++) {
                if (sales > N_REL) revert State(); // E needs its release units first
                (bytes32 pid, uint256 e, uint256 lo, uint256 hi,,) = _unitAt(acct, first, g);
                _check(pid, e, lo, hi);
            }
            releaseUnitsMarked[acct] = 0;
        }
        accountCursor[acct] = first + k;
        if (sales > N_REL) {
            _payNext[_k2(bytes32(uint256(uint160(acct))), bytes32(first))] = 1;
        } else if (busy != 0) {
            for (uint256 j; j < np; j++) {
                uint256 sum;
                for (uint256 i; i < k; i++) {
                    if (busy & (1 << i) == 0) continue;
                    sum += _pay(acct, pids[j], first + i, 0, type(uint256).max);
                }
                if (sum != 0) {
                    ReceivingVault(vaultOf[pids[j]]).pay(acct, sum);
                    paid += sum;
                }
            }
        }
        emit Released(acct, first, paid);
    }

    /// Payment unit of a passed seller epoch (first profile epoch `first`)
    /// of more than N_REL settlements, by anyone, in unit order: the held
    /// sales of the unit that are not frozen and have no open dispute are
    /// paid in one vault payment; frozen sales are marked frozen.
    function releasePay(address acct, uint256 first) external returns (uint256 paid) {
        bytes32 pk = _k2(bytes32(uint256(uint160(acct))), bytes32(first));
        uint256 next = _payNext[pk];
        if (next == 0) revert State();
        (bytes32 pid, uint256 e, uint256 lo, uint256 hi, uint256 total,) = _unitAt(acct, first, next - 1);
        _payNext[pk] = next == total ? 0 : next + 1;
        paid = _pay(acct, pid, e, lo, hi);
        if (paid != 0) ReceivingVault(vaultOf[pid]).pay(acct, paid);
        emit ReleasePaid(acct, first, next - 1, paid);
    }

    /// Failure processing of the settlement records [lo, hi) of a profile
    /// epoch with settlements.
    function _check(bytes32 pid, uint256 epoch, uint256 lo, uint256 hi) internal {
        bytes32 ek = _k2(pid, bytes32(epoch));
        bytes32[] storage ns = _epochNonces[ek];
        if (epochCompleteAt[ek] == 0) {
            if (missedAt[ek] == 0) _anchorMissed(pid, epoch, ek);
            return;
        }
        uint256 value = sampleValue[ek];
        uint64 cap = _profiles[pid].cap;
        for (uint256 i = lo; i < hi; i++) {
            bytes32 sk = _k2(pid, ns[i]);
            Sale storage s = _sales[sk];
            if (s.flags & (SF_MARKED | SF_FAILED) != 0 || passed[sk]) continue;
            if (_sampledBy(value, ns[i], s.amount, cap)) _sampleFailure(pid, ns[i], s);
        }
    }

    /// Payment of the held sales among the settlement records [lo, hi) of a
    /// profile epoch (hi clipped to its records).
    function _pay(address acct, bytes32 pid, uint256 epoch, uint256 lo, uint256 hi) internal returns (uint256 paid) {
        bytes32[] storage ns = _epochNonces[_k2(pid, bytes32(epoch))];
        if (hi > ns.length) hi = ns.length;
        for (uint256 i = lo; i < hi; i++) {
            bytes32 sk = _k2(pid, ns[i]);
            Sale storage s = _sales[sk];
            if (_eff(pid, s) != ST_HELD) continue;
            if (_frozenAt(acct, s) != 0) {
                s.status = ST_FROZEN;
                continue;
            }
            if (openDisputes[sk] != 0) continue;
            s.status = ST_PAID;
            paid += s.amount;
        }
    }
}
