// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { G10Sig, G10Merkle } from "../G10Base.sol";
import { EcVrf } from "../g10c/EcVrf.sol";
import { RandomWordsRequest, IVrfCoordinatorV2Plus } from "../g10d/MinimalVrfConsumer.sol";

/// ERC-20 surface of the USDC deployed on Base used here.
interface IUsdcP5 {
    function transfer(address to, uint256 value) external returns (bool);
    function transferFrom(address from, address to, uint256 value) external returns (bool);
    function approve(address spender, uint256 value) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// Interface the settlement contract calls on a seller's verification contract (STATICCALL,
/// gas capped at the account's g_v). Everything the check may depend on is
/// in the arguments; the contract keeps its configuration in immutables.
interface IP5Verifier {
    function verify(P5Ctx calldata c, bytes calldata material) external view returns (bool);
}

/// What the settlement contract hands a verification contract for one sampled sale: the
/// seller receipt fields of the anchored leaf, the settlement's validAfter,
/// and, for profiles that need it, the block hash stored by the anchor.
struct P5Ctx {
    bytes32 nonce;
    uint64 amount;
    uint64 validAfter;
    bytes32 requestHash;
    bytes32 responseHash;
    bytes32 claimsHash;
    bytes32 materialCommit;
    bytes32 anchoredHash;
}

/// Seller receipt fields carried in a leaf (R_S), plus the leaf's flags.
struct P5Rs {
    bytes32 nonce;
    uint64 amount;
    bytes32 requestHash;
    bytes32 responseHash;
    bytes32 ctHash;
    bytes32 keyHash;
    bytes32 claimsHash;
    bytes32 materialCommit;
}

struct P5Leaf {
    P5Rs rs;
    uint8 unanswered; // u_n
    bool accept; // a in the buyer signature
    bytes sigB; // buyer signature, empty when the sale carries none
}

/// One signed anchor unit.
struct P5Unit {
    bytes32 pid;
    uint32 epoch;
    uint32 count;
    uint32 unitNo;
    bytes32 first;
    bytes32 last;
    bytes32 root;
    bytes32 root0;
    address[] snapshot;
    P5Leaf[] leaves;
    bytes sellerSig;
}

/// One settled sale as the release call carries it (rebuilds the accumulator).
struct P5Item {
    bytes32 nonce;
    address payer;
    uint64 v;
    uint64 cap;
    bytes32 bindingHash;
}

struct P5Rel {
    bytes32 pid;
    P5Item[] items;
}

/// A leaf opened by a proof or a dispute: the receipt fields and the rest of
/// the leaf, its unit and its Merkle path.
struct P5Open {
    bytes32 pid;
    uint32 epoch;
    uint32 unitNo;
    uint256 index;
    P5Rs rs;
    uint8 unanswered;
    bytes32 sigHash;
    bool beta;
    bool accept;
    bytes32[] path;
}

/// Minimal reference of the rule's anchor units (direct and bundled), shared
/// and direct sample values (ECVRF and Chainlink VRF v2.5 request), the proof
/// call into a verification contract, the cursor release (direct and
/// bundled), and the non-delivery and key disputes. Settlement records are
/// written by a fixture (settlement gas is measured elsewhere). Freezing,
/// slashing, failure processing and exits are not implemented.
contract P5Ref {
    // ---------------------------------------------------------- constants
    uint256 public constant EPOCH_BLOCKS = 300;
    uint256 public constant A_F = 60; // facilitator anchor deadline offset
    uint256 public constant A_A = 120; // seller anchor deadline offset
    uint256 public constant D_INC = 30;
    uint256 public constant TAU_V = 10;
    uint256 public constant T_V = 100;
    uint256 public constant W_B = 50;
    uint256 public constant T_C = 600;
    uint256 public constant T_P = 300;
    uint256 public constant T_D = 100;
    uint256 public constant T_X = 100;
    uint256 public constant D_ND = 50_000; // dispute deposit, 0.05 USDC

    bytes32 internal constant RS_TYPEHASH = keccak256(
        "SellerReceipt(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 keyHash,bytes32 profileId,bytes32 codeHash,bytes32 claimsHash,bytes32 materialCommit)"
    );
    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bytes32 receiptHash,bool accepted)"
    );
    bytes32 internal constant UNIT_TYPEHASH = keccak256(
        "AnchorUnit(bytes32 profileId,uint32 epoch,uint32 count,uint32 unitNo,bytes32 firstNonce,bytes32 lastNonce,bytes32 root,bytes32 root0,bytes32 snapshotHash)"
    );
    bytes32 internal constant LEAF0_TAG = keccak256("p5/leaf0/v1");
    bytes32 internal constant TAG = keccak256("p5/response/v1");
    bytes4 private constant EXTRA_ARGS_V1_TAG = bytes4(keccak256("VRF ExtraArgsV1"));

    // flags of a profile (slot 1)
    uint256 internal constant F_TIER0 = 1; // anchor stores the previous block hash
    uint256 internal constant F_CT = 2; // ciphertext-delivery profile

    IUsdcP5 public immutable token;
    uint256 public immutable genesis;
    uint256 public immutable pkX;
    uint256 public immutable pkY;
    bytes32 public immutable DOMAIN_SEPARATOR;
    address public immutable coordinator;
    bytes32 public immutable vrfKeyHash;
    uint256 public vrfSubId;

    // ------------------------------------------------------------ storage
    /// pid => account (160) | cap (64) | set id (32)
    mapping(bytes32 => uint256) public prof0;
    /// pid => unit key (160) | g_v (32) | flags (64)
    mapping(bytes32 => uint256) public prof1;
    /// pid => verification contract
    mapping(bytes32 => address) public profVerifier;
    /// pid => verification contract code hash
    mapping(bytes32 => bytes32) public profCodeHash;
    /// key => block at which it was registered (signer snapshots)
    mapping(address => uint256) public keyRegisteredAt;
    /// set id => facilitator
    mapping(uint32 => address) public setFacilitator;

    /// (pid, nonce) => payer (160) | v (64) | settled block (32)
    mapping(bytes32 => uint256) public saleA;
    /// (pid, nonce) => validAfter (64) | cap (64) | epoch (32) | bound (8) | status (8)
    mapping(bytes32 => uint256) public saleB;
    /// (pid, nonce) => binding hash H(request hash, claim hash)
    mapping(bytes32 => bytes32) public saleBinding;
    /// (pid, epoch) => accumulator hash (224) | count (32)
    mapping(bytes32 => uint256) public acc;
    /// (pid, epoch) => first settlement block
    mapping(bytes32 => uint256) public firstSettle;
    /// (set, epoch) => profile epochs with a settlement
    mapping(bytes32 => uint256) public setActive;

    /// (pid, epoch, unit) => root, root0, first nonce, last nonce, leaves (32) | stored block (64)
    mapping(bytes32 => bytes32) public unitRoot;
    mapping(bytes32 => bytes32) public unitRoot0;
    mapping(bytes32 => bytes32) public unitFirst;
    mapping(bytes32 => bytes32) public unitLast;
    mapping(bytes32 => uint256) public unitMeta;
    /// (pid, epoch) => count (32) | stored leaves (32) | stored units (32) | max unit (32) | complete block (64)
    mapping(bytes32 => uint256) public epochRec;
    /// (pid, epoch) => previous block hash at completion (tier-0 profiles)
    mapping(bytes32 => bytes32) public epochHash;
    /// rejection records
    mapping(bytes32 => uint256) public rejected;

    /// (pid or set, epoch) => request block; value
    mapping(bytes32 => uint256) public sampleReq;
    mapping(bytes32 => uint256) public sampleValue;
    /// Chainlink request id => (set, epoch) key
    mapping(uint256 => bytes32) public vrfRequestKey;

    /// (pid, nonce) => passing proof recorded
    mapping(bytes32 => uint256) public passed;
    /// pid => next epoch to release
    mapping(bytes32 => uint256) public cursor;
    uint256 public levyPool;

    /// (pid, nonce) => dispute
    struct Dispute {
        bytes32 ctHash;
        bytes32 keyHash;
        bytes32 responseHash;
        bytes32 key;
        uint256 meta; // deadline (64) | state (8) | kind (8)
    }
    mapping(bytes32 => Dispute) public disputes;

    event UnitStored(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, bytes32 root, bytes32 root0, uint32 leaves);
    event UnitRejected(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, bytes32 root0, uint32 count, uint8 reason);
    event EpochAnchored(bytes32 indexed pid, uint32 indexed epoch, uint32 count);
    event SampleRequested(bytes32 indexed key, uint256 indexed epoch, bytes32 alpha);
    event SampleValue(bytes32 indexed key, uint256 indexed epoch, uint256 value);
    event ProofPassed(bytes32 indexed pid, bytes32 indexed nonce);
    event Released(bytes32 indexed pid, uint256 indexed epoch, uint256 paid, uint256 levy);
    event ReleaseSkipped(bytes32 indexed pid, uint256 indexed epoch);
    event DisputeOpened(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind);
    event DisputeAnswered(bytes32 indexed pid, bytes32 indexed nonce);
    event DisputeClosed(bytes32 indexed pid, bytes32 indexed nonce, bool refunded);

    error Timing();
    error Unauthorized();
    error Membership();
    error NotSampled();
    error VerifierFailed();
    error State();

    constructor(IUsdcP5 token_, uint256 pkX_, uint256 pkY_, address coordinator_, bytes32 keyHash_) {
        token = token_;
        genesis = block.number;
        pkX = pkX_;
        pkY = pkY_;
        coordinator = coordinator_;
        vrfKeyHash = keyHash_;
        levyPool = 1; // steady state: the levy pool already holds value
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("Settlement"),
                keccak256("10"),
                block.chainid,
                address(this)
            )
        );
    }

    // ------------------------------------------------------------ helpers
    function epochOf(uint256 b) public view returns (uint256) {
        return (b - genesis) / EPOCH_BLOCKS;
    }

    function lastBlock(uint256 epoch) public view returns (uint256) {
        return genesis + (epoch + 1) * EPOCH_BLOCKS - 1;
    }

    function anchorDeadline(uint256 epoch) public view returns (uint256) {
        return lastBlock(epoch) + A_A;
    }

    function facilitatorDeadline(uint256 epoch) public view returns (uint256) {
        return lastBlock(epoch) + A_F;
    }

    function valueDeadline(uint256 epoch) public view returns (uint256) {
        return anchorDeadline(epoch) + TAU_V + 1 + T_V;
    }

    function _k2(bytes32 a, uint256 b) internal pure returns (bytes32 h) {
        assembly ("memory-safe") {
            mstore(0x00, a)
            mstore(0x20, b)
            h := keccak256(0x00, 0x40)
        }
    }

    function _k3(bytes32 a, uint256 b, uint256 c) internal pure returns (bytes32 h) {
        assembly ("memory-safe") {
            let p := mload(0x40)
            mstore(p, a)
            mstore(add(p, 0x20), b)
            mstore(add(p, 0x40), c)
            h := keccak256(p, 0x60)
        }
    }

    function rsHash(bytes32 pid, bytes32 codeHash, P5Rs calldata r) public pure returns (bytes32) {
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

    function leaf0Of(bytes32 nonce, bytes32 hRS, uint8 u) public pure returns (bytes32) {
        return keccak256(abi.encode(LEAF0_TAG, nonce, hRS, u));
    }

    function leafOf(bytes32 l0, bytes32 sigHash, bool beta, bool a) public pure returns (bytes32) {
        return keccak256(abi.encode(l0, sigHash, beta, a));
    }

    function _root(bytes32[] memory level) internal pure returns (bytes32) {
        uint256 w = level.length;
        while (w > 1) {
            uint256 next = (w + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 a = level[2 * i];
                bytes32 b = 2 * i + 1 < w ? level[2 * i + 1] : a;
                level[i] = G10Merkle.node(a, b);
            }
            w = next;
        }
        return level[0];
    }

    /// U_n < thr(v, V) as h * V < v * 2^256 (512-bit product).
    function sampledBy(uint256 value, bytes32 pid, bool shared, bytes32 nonce, uint64 v, uint64 cap)
        public
        pure
        returns (bool)
    {
        if (value == 0 || v >= cap) return true;
        uint256 h = shared ? uint256(keccak256(abi.encode(value, pid, nonce))) : uint256(keccak256(abi.encode(value, nonce)));
        uint256 hi;
        assembly {
            let lo := mul(h, cap)
            let mm := mulmod(h, cap, not(0))
            hi := sub(sub(mm, lo), lt(mm, lo))
        }
        return hi < v;
    }

    // ------------------------------------------------------ set-up only
    function registerProfile(
        bytes32 pid,
        address account,
        address unitKey,
        uint64 cap,
        uint32 setId,
        address verifier,
        uint32 gv,
        uint256 flags
    ) external {
        prof0[pid] = uint256(uint160(account)) | (uint256(cap) << 160) | (uint256(setId) << 224);
        prof1[pid] = uint256(uint160(unitKey)) | (uint256(gv) << 160) | (flags << 192);
        profVerifier[pid] = verifier;
        profCodeHash[pid] = verifier.codehash;
        cursor[pid] = epochOf(block.number);
    }

    function registerKey(address k) external {
        keyRegisteredAt[k] = block.number;
    }

    function registerSet(uint32 setId, address facilitator) external {
        setFacilitator[setId] = facilitator;
    }

    function setSubscription(uint256 subId) external {
        vrfSubId = subId;
    }

    function _step(bytes32 prev, bytes32 nonce, address payer, uint64 v, uint64 cap, bytes32 bh)
        internal
        pure
        returns (bytes32 h)
    {
        assembly ("memory-safe") {
            let q := mload(0x40)
            mstore(q, prev)
            mstore(add(q, 0x20), nonce)
            mstore(add(q, 0x40), payer)
            mstore(add(q, 0x60), v)
            mstore(add(q, 0x80), cap)
            mstore(add(q, 0xa0), bh)
            h := keccak256(q, 0xc0)
        }
    }

    /// The state a settlement leaves (record, binding, accumulator, counters).
    function settleFixture(bytes32 pid, bytes32 nonce, address payer, uint64 v, uint64 validAfter, bytes32 bindingHash)
        external
    {
        uint256 p0 = prof0[pid];
        uint64 cap = uint64(p0 >> 160);
        uint256 epoch = epochOf(block.number);
        bytes32 k = _k2(pid, uint256(nonce));
        require(saleA[k] == 0, "nonce");
        saleA[k] = uint256(uint160(payer)) | (uint256(v) << 160) | (uint256(uint32(block.number)) << 224);
        saleB[k] = uint256(validAfter) | (uint256(cap) << 64) | (uint256(uint32(epoch)) << 128)
            | (bindingHash != 0 ? uint256(1) << 160 : 0);
        if (bindingHash != 0) saleBinding[k] = bindingHash;
        bytes32 ek = _k2(pid, epoch);
        uint256 w0 = acc[ek];
        if (uint32(w0) == 0) {
            firstSettle[ek] = block.number;
            uint32 setId = uint32(p0 >> 224);
            if (setId != 0) setActive[_k2(bytes32(uint256(setId)), epoch)] += 1;
        }
        bytes32 h = _step(bytes32(w0 >> 32 << 32), nonce, payer, v, cap, bindingHash);
        acc[ek] = (uint256(h) >> 32 << 32) | (uint32(w0) + 1);
    }

    function valueFixture(bytes32 key, uint256 epoch, uint256 value) external {
        bytes32 ek = _k2(key, epoch);
        sampleReq[ek] = block.number;
        sampleValue[ek] = value;
    }

    /// Stands in for the block hash the anchor stored (tier-0 proof fixture).
    function hashFixture(bytes32 pid, uint256 epoch, bytes32 h) external {
        epochHash[_k2(pid, epoch)] = h;
    }

    function passFixture(bytes32 pid, bytes32[] calldata nonces) external {
        for (uint256 i; i < nonces.length; i++) passed[_k2(pid, uint256(nonces[i]))] = 1;
    }

    // ------------------------------------------------------------- anchor

    struct UnitScratch {
        uint256 p0;
        uint256 p1;
        bytes32 codeHash;
        bytes32 ek;
        uint256 er;
        uint256 n;
    }

    /// Checks and stores one unit; returns 0 when stored, else the reason it
    /// was rejected (the rejection is recorded and nothing else changes).
    function _unit(P5Unit calldata x, uint32 viaSet) internal returns (uint8 reason) {
        UnitScratch memory s;
        s.p0 = prof0[x.pid];
        s.p1 = prof1[x.pid];
        if (s.p0 == 0) return _reject(x, 1);
        if (viaSet != 0) {
            if (uint32(s.p0 >> 224) != viaSet) return _reject(x, 2);
            if (block.number > facilitatorDeadline(x.epoch)) return _reject(x, 3);
        } else if (block.number > anchorDeadline(x.epoch)) {
            return _reject(x, 3);
        }
        // (1) the seller's unit signature, digest from the profile id and this domain
        {
            bytes32 sh = keccak256(abi.encode(x.snapshot));
            bytes32 d = G10Sig.typed(
                DOMAIN_SEPARATOR,
                keccak256(
                    abi.encode(UNIT_TYPEHASH, x.pid, x.epoch, x.count, x.unitNo, x.first, x.last, x.root, x.root0, sh)
                )
            );
            if (G10Sig.recover(d, x.sellerSig) != address(uint160(s.p1))) return _reject(x, 4);
        }
        bytes32 uk = _k3(x.pid, x.epoch, x.unitNo);
        if (unitMeta[uk] != 0) return _reject(x, 5); // number already stored
        s.ek = _k2(x.pid, x.epoch);
        s.er = epochRec[s.ek];
        if (uint32(s.er) != 0 && uint32(s.er) != x.count) return _reject(x, 6);
        if (uint32(acc[s.ek]) != x.count) return _reject(x, 6);
        s.n = x.leaves.length;
        if (s.n == 0 || x.leaves[0].rs.nonce != x.first || x.leaves[s.n - 1].rs.nonce != x.last) return _reject(x, 7);
        s.codeHash = profCodeHash[x.pid];
        // (2) the leaves
        bytes32[] memory lv = new bytes32[](s.n);
        bytes32[] memory lv0 = new bytes32[](s.n);
        for (uint256 i; i < s.n; i++) {
            uint8 r = _leaf(x, i, s, lv, lv0);
            if (r != 0) return _reject(x, r);
        }
        if (_root(lv) != x.root || _root(lv0) != x.root0) return _reject(x, 12);
        // signer snapshot: keys registered before the epoch's first settlement
        {
            uint256 fs = firstSettle[s.ek];
            for (uint256 j; j < x.snapshot.length; j++) {
                uint256 at = keyRegisteredAt[x.snapshot[j]];
                if (at == 0 || at >= fs) return _reject(x, 13);
            }
        }
        // order against stored neighbours
        if (x.unitNo > 1) {
            bytes32 pk = _k3(x.pid, x.epoch, x.unitNo - 1);
            if (unitMeta[pk] != 0 && unitLast[pk] >= x.first) return _reject(x, 14);
        }
        {
            bytes32 nk = _k3(x.pid, x.epoch, x.unitNo + 1);
            if (unitMeta[nk] != 0 && unitFirst[nk] <= x.last) return _reject(x, 14);
        }
        // (3) store the unit and the count
        unitRoot[uk] = x.root;
        unitRoot0[uk] = x.root0;
        unitFirst[uk] = x.first;
        unitLast[uk] = x.last;
        unitMeta[uk] = uint256(uint32(s.n)) | (uint256(uint64(block.number)) << 32);
        emit UnitStored(x.pid, x.epoch, x.unitNo, x.root, x.root0, uint32(s.n));
        uint256 stored = uint32(s.er >> 32) + s.n;
        uint256 units = uint32(s.er >> 64) + 1;
        uint256 maxU = uint32(s.er >> 96);
        if (x.unitNo > maxU) maxU = x.unitNo;
        uint256 done;
        // (4) complete when the stored leaves fill the count with numbers 1..k
        if (stored == x.count && units == maxU) {
            done = block.number;
            if ((s.p1 >> 192) & F_TIER0 != 0) epochHash[s.ek] = blockhash(block.number - 1);
            emit EpochAnchored(x.pid, x.epoch, x.count);
        }
        epochRec[s.ek] =
            uint256(x.count) | (stored << 32) | (units << 64) | (maxU << 96) | (done << 128);
        return 0;
    }

    function _leaf(P5Unit calldata x, uint256 i, UnitScratch memory s, bytes32[] memory lv, bytes32[] memory lv0)
        internal
        view
        returns (uint8)
    {
        P5Leaf calldata l = x.leaves[i];
        bytes32 nonce = l.rs.nonce;
        if (i != 0 && nonce <= x.leaves[i - 1].rs.nonce) return 8;
        bytes32 k = _k2(x.pid, uint256(nonce));
        uint256 a = saleA[k];
        uint256 b = saleB[k];
        if (a == 0 || uint32(b >> 128) != x.epoch) return 9;
        bool bound = (b >> 160) & 1 == 1;
        if (bound) {
            if (saleBinding[k] != keccak256(abi.encode(l.rs.requestHash, l.rs.claimsHash))) return 10;
        } else if (block.number <= uint32(a >> 224) + D_INC) {
            return 10; // binding wait
        }
        bytes32 hRS;
        bytes32 sigHash;
        bool beta;
        bool acc_;
        if (l.unanswered == 0) {
            if (l.rs.amount != uint64(a >> 160)) return 11;
            hRS = rsHash(x.pid, s.codeHash, l.rs);
            if (l.sigB.length != 0) {
                sigHash = keccak256(l.sigB);
                bytes32 d = G10Sig.typed(
                    DOMAIN_SEPARATOR,
                    keccak256(
                        abi.encode(
                            ACK_TYPEHASH,
                            nonce,
                            uint256(l.rs.amount),
                            l.rs.requestHash,
                            l.rs.responseHash,
                            l.rs.ctHash,
                            x.pid,
                            s.codeHash,
                            hRS,
                            l.accept
                        )
                    )
                );
                if (G10Sig.recover(d, l.sigB) == address(uint160(a))) {
                    beta = true;
                    acc_ = l.accept;
                }
            }
        }
        bytes32 l0 = leaf0Of(nonce, hRS, l.unanswered);
        lv0[i] = l0;
        lv[i] = leafOf(l0, sigHash, beta, acc_);
        return 0;
    }

    function _reject(P5Unit calldata x, uint8 reason) internal returns (uint8) {
        rejected[keccak256(abi.encode(x.pid, x.epoch, x.unitNo, x.root0, x.count, reason))] = block.number;
        emit UnitRejected(x.pid, x.epoch, x.unitNo, x.root0, x.count, reason);
        return reason;
    }

    /// One unit of one profile, anyone, until A_e (the seller's own path).
    function anchorUnit(P5Unit calldata x) external returns (uint8) {
        return _unit(x, 0);
    }

    /// The facilitator's bundle of units of its set's profiles, until
    /// A^F_e. A rejected unit is recorded and does not revert the others.
    function anchorBundle(uint32 setId, P5Unit[] calldata units) external returns (uint256 storedUnits) {
        if (msg.sender != setFacilitator[setId]) revert Unauthorized();
        for (uint256 i; i < units.length; i++) {
            if (_unit(units[i], setId) == 0) storedUnits++;
        }
    }

    // ------------------------------------------------------ sample values

    function alphaOf(bytes32 key, uint256 epoch) public view returns (bytes32) {
        return keccak256(abi.encode(block.chainid, address(this), key, epoch));
    }

    /// One SAMPLE request per set and epoch, after the common A_e,
    /// when a profile of the set settled in the epoch.
    function requestSampleSet(uint32 setId, uint256 epoch) external {
        bytes32 key = bytes32(uint256(setId));
        bytes32 ek = _k2(key, epoch);
        if (block.number <= anchorDeadline(epoch) || setActive[ek] == 0 || sampleReq[ek] != 0) revert Timing();
        sampleReq[ek] = block.number;
        emit SampleRequested(key, epoch, alphaOf(key, epoch));
    }

    /// The direct participant's request, after A_e, for an anchored epoch.
    function requestSample(bytes32 pid, uint256 epoch) external {
        bytes32 ek = _k2(pid, epoch);
        if (block.number <= anchorDeadline(epoch) || uint64(epochRec[ek] >> 128) == 0 || sampleReq[ek] != 0) {
            revert Timing();
        }
        if (uint32(prof0[pid] >> 224) != 0) revert Unauthorized();
        sampleReq[ek] = block.number;
        emit SampleRequested(pid, epoch, alphaOf(pid, epoch));
    }

    /// The first valid ECVRF value until M_e (set id or profile id as key).
    function fulfillSample(bytes32 key, uint256 epoch, EcVrf.Proof calldata pr) external {
        bytes32 ek = _k2(key, epoch);
        if (sampleReq[ek] == 0 || sampleValue[ek] != 0 || block.number > valueDeadline(epoch)) revert Timing();
        uint256 beta = EcVrf.verify([pkX, pkY], alphaOf(key, epoch), pr);
        sampleValue[ek] = beta;
        emit SampleValue(key, epoch, beta);
    }

    /// The set request through the Chainlink VRF v2.5 coordinator deployed on
    /// Base (native payment, one word); the callback stores the value.
    function requestSampleSetChainlink(uint32 setId, uint256 epoch) external {
        bytes32 key = bytes32(uint256(setId));
        bytes32 ek = _k2(key, epoch);
        if (block.number <= anchorDeadline(epoch) || setActive[ek] == 0 || sampleReq[ek] != 0) revert Timing();
        sampleReq[ek] = block.number;
        uint256 id = IVrfCoordinatorV2Plus(coordinator).requestRandomWords(
            RandomWordsRequest({
                keyHash: vrfKeyHash,
                subId: vrfSubId,
                requestConfirmations: 0,
                callbackGasLimit: 100_000,
                numWords: 1,
                extraArgs: abi.encodeWithSelector(EXTRA_ARGS_V1_TAG, true)
            })
        );
        vrfRequestKey[id] = ek;
        emit SampleRequested(key, epoch, bytes32(id));
    }

    function rawFulfillRandomWords(uint256 requestId, uint256[] calldata words) external {
        if (msg.sender != coordinator) revert Unauthorized();
        bytes32 ek = vrfRequestKey[requestId];
        if (ek == 0 || sampleValue[ek] != 0) return;
        sampleValue[ek] = words[0];
    }

    // -------------------------------------------------------------- proof

    function _openLeaf(P5Open calldata o, bytes32 codeHash) internal view returns (bytes32 hRS) {
        hRS = rsHash(o.pid, codeHash, o.rs);
        bytes32 l = leafOf(leaf0Of(o.rs.nonce, hRS, o.unanswered), o.sigHash, o.beta, o.accept);
        if (G10Merkle.rootOf(l, o.index, o.path) != unitRoot[_k3(o.pid, o.epoch, o.unitNo)]) revert Membership();
    }

    /// A sampled sale's proof; the verification contract is called by
    /// STATICCALL with the stored g_v after its code hash is checked.
    function prove(P5Open calldata o, bytes calldata material) external {
        uint256 p0 = prof0[o.pid];
        uint256 p1 = prof1[o.pid];
        bytes32 codeHash = profCodeHash[o.pid];
        _openLeaf(o, codeHash);
        bytes32 sk = _k2(o.pid, uint256(o.rs.nonce));
        uint256 b = saleB[sk];
        if (uint32(b >> 128) != o.epoch || passed[sk] != 0) revert State();
        if (block.number > valueDeadline(o.epoch) + T_P) revert Timing();
        uint32 setId = uint32(p0 >> 224);
        uint256 value = sampleValue[_k2(setId != 0 ? bytes32(uint256(setId)) : o.pid, o.epoch)];
        if (value == 0 && block.number <= valueDeadline(o.epoch)) revert Timing();
        if (!sampledBy(value, o.pid, setId != 0, o.rs.nonce, o.rs.amount, uint64(b >> 64))) revert NotSampled();
        address verifier = profVerifier[o.pid];
        if (verifier.codehash != codeHash) revert VerifierFailed();
        P5Ctx memory c = P5Ctx(
            o.rs.nonce,
            o.rs.amount,
            uint64(b),
            o.rs.requestHash,
            o.rs.responseHash,
            o.rs.claimsHash,
            o.rs.materialCommit,
            (p1 >> 192) & F_TIER0 != 0 ? epochHash[_k2(o.pid, o.epoch)] : bytes32(0)
        );
        uint256 gv = uint32(p1 >> 160);
        if (gasleft() < gv + gv / 63 + 5_000) revert VerifierFailed();
        (bool ok, bytes memory ret) =
            verifier.staticcall{ gas: gv }(abi.encodeCall(IP5Verifier.verify, (c, material)));
        if (!ok || ret.length != 32 || abi.decode(ret, (uint256)) != 1) revert VerifierFailed();
        passed[sk] = 1;
        emit ProofPassed(o.pid, o.rs.nonce);
    }

    // ------------------------------------------------------------ release

    /// One account's cursor step; returns false, with nothing changed,
    /// when a condition does not hold.
    function _release(bytes32 pid, P5Item[] calldata items) internal returns (bool) {
        uint256 epoch = cursor[pid];
        bytes32 ek = _k2(pid, epoch);
        uint256 er = epochRec[ek];
        uint256 p0 = prof0[pid];
        uint32 setId = uint32(p0 >> 224);
        uint256 value = sampleValue[_k2(setId != 0 ? bytes32(uint256(setId)) : pid, epoch)];
        uint256 me = valueDeadline(epoch);
        if (uint64(er >> 128) == 0 || (value == 0 && block.number <= me)) return false;
        if (block.number <= me + W_B || block.number <= anchorDeadline(epoch) + T_C) return false;
        uint256 n = items.length;
        bytes32 h;
        uint256 sum;
        for (uint256 i; i < n; i++) {
            P5Item calldata it = items[i];
            h = _step(bytes32(uint256(h) >> 32 << 32), it.nonce, it.payer, it.v, it.cap, it.bindingHash);
            sum += it.v;
            if (sampledBy(value, pid, setId != 0, it.nonce, it.v, it.cap)) {
                if (passed[_k2(pid, uint256(it.nonce))] == 0) return false;
            }
        }
        if (acc[ek] != ((uint256(h) >> 32 << 32) | n) || uint32(er) != n) return false;
        uint256 levy = sum / 100;
        cursor[pid] = epoch + 1;
        levyPool += levy;
        if (!token.transfer(address(uint160(p0)), sum - levy)) return false;
        emit Released(pid, epoch, sum - levy, levy);
        return true;
    }

    function release(bytes32 pid, P5Item[] calldata items) external {
        if (!_release(pid, items)) revert State();
    }

    /// The facilitator's bundle of cursor calls of several accounts;
    /// one account's unmet condition does not revert the others.
    function releaseBundle(uint32 setId, P5Rel[] calldata rs) external returns (uint256 paid) {
        if (msg.sender != setFacilitator[setId]) revert Unauthorized();
        for (uint256 i; i < rs.length; i++) {
            if (uint32(prof0[rs[i].pid] >> 224) != setId) {
                emit ReleaseSkipped(rs[i].pid, cursor[rs[i].pid]);
                continue;
            }
            if (_release(rs[i].pid, rs[i].items)) paid++;
            else emit ReleaseSkipped(rs[i].pid, cursor[rs[i].pid]);
        }
    }

    // ----------------------------------------------------------- disputes

    /// Non-delivery dispute (kind 1, beta = 0) or key dispute (kind
    /// 2, ciphertext profile, beta = 1), by the payer, until A_e + T_c, with
    /// a deposit in USDC.
    function openDispute(P5Open calldata o, uint8 kind) external {
        bytes32 sk = _k2(o.pid, uint256(o.rs.nonce));
        uint256 a = saleA[sk];
        uint256 b = saleB[sk];
        if (address(uint160(a)) != msg.sender) revert Unauthorized();
        if (uint32(b >> 128) != o.epoch || uint8(b >> 168) != 0) revert State();
        if (block.number > anchorDeadline(o.epoch) + T_C) revert Timing();
        if (kind == 1) {
            if (o.beta || o.unanswered != 0) revert State();
        } else {
            if (!o.beta || (prof1[o.pid] >> 192) & F_CT == 0) revert State();
        }
        Dispute storage d = disputes[sk];
        if (d.meta != 0) revert State();
        _openLeaf(o, profCodeHash[o.pid]);
        if (!token.transferFrom(msg.sender, address(this), D_ND)) revert State();
        d.ctHash = o.rs.ctHash;
        d.keyHash = o.rs.keyHash;
        d.responseHash = o.rs.responseHash;
        d.meta = uint256(uint64(block.number + T_D)) | (uint256(1) << 64) | (uint256(kind) << 72);
        emit DisputeOpened(o.pid, o.rs.nonce, kind);
    }

    /// The seller's answer to a non-delivery dispute: ct as calldata and k.
    function answerDeliver(bytes32 pid, bytes32 nonce, bytes calldata ct, bytes32 k) external {
        Dispute storage d = disputes[_k2(pid, uint256(nonce))];
        uint256 m = d.meta;
        if (uint8(m >> 64) != 1 || uint8(m >> 72) != 1 || block.number > uint64(m)) revert State();
        if (keccak256(ct) != d.ctHash || keccak256(abi.encode(k)) != d.keyHash) revert State();
        d.key = k;
        d.meta = uint256(uint64(block.number + T_X)) | (uint256(2) << 64) | (uint256(1) << 72);
        emit DisputeAnswered(pid, nonce);
    }

    /// The seller's answer to a key dispute: k alone.
    function answerKey(bytes32 pid, bytes32 nonce, bytes32 k) external {
        Dispute storage d = disputes[_k2(pid, uint256(nonce))];
        uint256 m = d.meta;
        if (uint8(m >> 64) != 1 || uint8(m >> 72) != 2 || block.number > uint64(m)) revert State();
        if (keccak256(abi.encode(k)) != d.keyHash) revert State();
        d.key = k;
        d.meta = uint256(uint64(block.number + T_X)) | (uint256(2) << 64) | (uint256(2) << 72);
        emit DisputeAnswered(pid, nonce);
    }

    /// Decryption challenge within T_x: the buyer posts ct; the contract
    /// decrypts with the posted key and compares with h_r. A mismatch refunds
    /// the sale and returns the deposit; a match pays the deposit to the seller.
    function challengeDecrypt(bytes32 pid, bytes32 nonce, bytes calldata ct) external returns (bool refunded) {
        bytes32 sk = _k2(pid, uint256(nonce));
        Dispute storage d = disputes[sk];
        uint256 m = d.meta;
        if (uint8(m >> 64) != 2 || block.number > uint64(m)) revert State();
        uint256 a = saleA[sk];
        if (address(uint160(a)) != msg.sender) revert Unauthorized();
        if (keccak256(ct) != d.ctHash) revert State();
        refunded = decryptHash(d.key, nonce, ct) != d.responseHash;
        d.meta = (m & ~(uint256(0xff) << 64)) | (uint256(refunded ? 4 : 3) << 64);
        if (refunded) {
            saleB[sk] = saleB[sk] | (uint256(4) << 168);
            if (!token.transfer(msg.sender, uint64(a >> 160) + D_ND)) revert State();
        } else {
            if (!token.transfer(address(uint160(prof0[pid])), D_ND)) revert State();
        }
        emit DisputeClosed(pid, nonce, refunded);
    }

    /// keccak256(TAG || (ct XOR keystream)), keystream word j = keccak(k, nonce, j).
    function decryptHash(bytes32 k, bytes32 nonce, bytes calldata ct) public pure returns (bytes32 h) {
        require(ct.length % 32 == 0, "length");
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
}
