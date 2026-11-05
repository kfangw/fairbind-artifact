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
    uint32 responseDeadline; // r_dl in blocks after the settlement block, 0 = none
    uint64 deposit; // dispute deposit d_nd (token units)
    uint64 maxFeePerGas; // disclosed price cap p_max (wei per gas)
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

/// Reference settlement contract for the signing client and watchtower
/// end-to-end tests: settlement through EIP-3009 into a per-profile vault
/// with the optional request binding and its completion call, anchor units
/// with buyer signatures checked by ecrecover, refunds of unanswered leaves,
/// sample values (posted by a fixed randomness address standing in for the
/// VRF paths measured elsewhere), proof calls into a verification contract,
/// the swap proof, non-delivery and key disputes that anyone may open (with
/// the payer's mandate signature deciding the deposit), decryption
/// challenges that do not end a dispute early, the response deadline, and
/// the cursor release. Not implemented: freezing and claims beyond the swap
/// proof's refund and suspension, slashing, missed-anchor processing, exits,
/// call fees, bundles and the bypass refund.
contract SampledSettlement {
    // ------------------------------------------------------------ constants
    uint256 public constant EPOCH_BLOCKS = 300;
    uint256 public constant A_A = 120; // anchor deadline after the epoch's last block
    uint256 public constant D_INC = 30; // binding wait and completion window
    uint256 public constant TAU_V = 10;
    uint256 public constant T_V = 100;
    uint256 public constant W_B = 50;
    uint256 public constant T_RS = 40; // receipt deadline after the settlement block
    uint256 public constant T_C = 600; // dispute window after A_e
    uint256 public constant T_P = 300; // proof window after M_e
    uint256 public constant T_D = 100; // seller answer window
    uint256 public constant T_X = 100; // decryption challenge window
    uint256 public constant C_ND = 1_000_000; // upper bound of a profile's deposit
    uint256 public constant P_FLOOR = 1 gwei; // floor of the disclosed price cap

    uint8 public constant F_BLOCKHASH = 1;
    uint8 public constant F_CT = 2;

    uint8 public constant ST_HELD = 0;
    uint8 public constant ST_REFUNDED = 1;
    uint8 public constant ST_PAID = 2;

    uint8 public constant K_NONDELIVERY = 1;
    uint8 public constant K_KEY = 2;

    uint8 public constant D_OPEN = 1;
    uint8 public constant D_ANSWERED = 2;
    uint8 public constant D_CLOSED = 3;

    bytes32 public constant RS_TYPEHASH = keccak256(
        "SellerReceipt(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 keyHash,bytes32 profileId,bytes32 codeHash,bytes32 claimsHash,bytes32 materialCommit)"
    );
    bytes32 public constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bytes32 receiptHash,bool accepted)"
    );
    bytes32 public constant UNIT_TYPEHASH = keccak256(
        "AnchorUnit(bytes32 profileId,uint32 epoch,uint32 count,uint32 unitNo,bytes32 firstNonce,bytes32 lastNonce,bytes32 root,bytes32 root0,bytes32 snapshotHash)"
    );
    bytes32 public constant MANDATE_TYPEHASH = keccak256("DisputeMandate(bytes32 profileId,bytes32 nonce,address delegate,uint8 kinds)");
    bytes32 public constant LEAF0_TAG = keccak256("p5/leaf0/v1");
    bytes32 public constant NODE_TAG = keccak256("settlement/epoch-node/v1");
    bytes32 public constant NONCE_TAG = keccak256("settlement/bound-nonce/v1");
    bytes32 public constant TAG = keccak256("p5/response/v1");

    IAuthToken public immutable token;
    address public immutable randomness;
    uint256 public immutable genesis;
    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public immutable vaultInitHash;

    // -------------------------------------------------------------- storage
    mapping(bytes32 => Profile) internal _profiles;
    mapping(bytes32 => uint32) public verifierGas;
    mapping(bytes32 => address) public vaultOf;
    mapping(address => bytes32) public profileOfVault;
    mapping(bytes32 => bool) public suspended;
    mapping(bytes32 => uint256) public cursor;

    struct Sale {
        address payer;
        uint64 amount;
        uint32 settledBlock;
        uint32 epoch;
        uint64 validAfter;
        uint8 status;
        bool bindingCompleted;
        bytes32 binding;
    }

    mapping(bytes32 => Sale) internal _sales; // (pid, nonce)
    mapping(bytes32 => bytes32[]) internal _epochNonces; // (pid, epoch)

    mapping(bytes32 => bytes32) public unitRoot; // (pid, epoch, unit)
    mapping(bytes32 => bytes32) public unitFirst;
    mapping(bytes32 => bytes32) public unitLast;
    mapping(bytes32 => uint256) public unitStoredAt;
    mapping(bytes32 => uint256) public epochStoredLeaves; // (pid, epoch)
    mapping(bytes32 => uint256) public epochUnits;
    mapping(bytes32 => uint256) public epochMaxUnit;
    mapping(bytes32 => uint256) public epochCompleteAt;
    mapping(bytes32 => bytes32) public epochHash;

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

    struct Dispute {
        address opener;
        bool authorized;
        uint8 state;
        bool bad;
        bool hasAnswer;
        uint64 deadline;
        uint64 deposit;
        uint64 answerBlock;
        bytes32 key;
    }

    mapping(bytes32 => Dispute) internal _disputes; // (pid, nonce, kind)
    mapping(bytes32 => uint256) public openDisputes; // (pid, nonce) => disputes not closed

    // --------------------------------------------------------------- events
    event ProfileRegistered(bytes32 indexed pid, address indexed vault, Profile profile, uint32 verifierGas);
    event Settled(bytes32 indexed pid, address indexed payer, bytes32 indexed nonce, uint256 amount, uint256 epoch, bytes32 binding);
    event BindingCompleted(bytes32 indexed pid, bytes32 indexed nonce, bytes32 binding);
    event UnitStored(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, bytes32 root, uint32 leaves);
    event UnitRejected(bytes32 indexed pid, uint32 indexed epoch, uint32 unitNo, uint8 reason);
    event EpochAnchored(bytes32 indexed pid, uint32 indexed epoch, uint32 count);
    event SampleValue(bytes32 indexed pid, uint256 indexed epoch, uint256 value);
    event ProofPassed(bytes32 indexed pid, bytes32 indexed nonce);
    event SwapProven(bytes32 indexed pid, bytes32 indexed nonce);
    event Refunded(bytes32 indexed pid, bytes32 indexed nonce, address payer, uint256 amount);
    event Released(bytes32 indexed pid, uint256 indexed epoch, uint256 paid);
    event DisputeOpened(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, address opener, bool authorized);
    event Delivered(bytes32 indexed pid, bytes32 indexed nonce, bytes ct, bytes32 key);
    event KeyRevealed(bytes32 indexed pid, bytes32 indexed nonce, bytes32 key);
    event AckShown(bytes32 indexed pid, bytes32 indexed nonce);
    event DecryptionChallenged(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, address by, bool mismatch);
    event DisputeClosed(bytes32 indexed pid, bytes32 indexed nonce, uint8 kind, bool refunded, address depositTo);

    error Unknown();
    error Timing();
    error Unauthorized();
    error Membership();
    error State();
    error Binding();
    error OverCap();
    error Duplicate();
    error Late();
    error NotSampled();
    error VerifierFailed();
    error BadProfile();

    constructor(IAuthToken token_, address randomness_) {
        token = token_;
        randomness = randomness_;
        genesis = block.number;
        vaultInitHash = keccak256(abi.encodePacked(type(ReceivingVault).creationCode, abi.encode(token_)));
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

    // -------------------------------------------------------------- helpers
    function epochOf(uint256 b) public view returns (uint256) {
        return (b - genesis) / EPOCH_BLOCKS;
    }

    function lastBlock(uint256 epoch) public view returns (uint256) {
        return genesis + (epoch + 1) * EPOCH_BLOCKS - 1;
    }

    function anchorDeadline(uint256 epoch) public view returns (uint256) {
        return lastBlock(epoch) + A_A;
    }

    function valueDeadline(uint256 epoch) public view returns (uint256) {
        return anchorDeadline(epoch) + TAU_V + 1 + T_V;
    }

    function signDeadlineEnd(uint256 epoch) public view returns (uint256) {
        return valueDeadline(epoch) + W_B; // W_e
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

    function sale(bytes32 pid, bytes32 nonce) external view returns (Sale memory) {
        return _sales[_k2(pid, nonce)];
    }

    function epochNonces(bytes32 pid, uint256 epoch) external view returns (bytes32[] memory) {
        return _epochNonces[_k2(pid, bytes32(epoch))];
    }

    function leafInfo(bytes32 pid, bytes32 nonce) external view returns (LeafInfo memory) {
        return _leafInfo[_k2(pid, nonce)];
    }

    function dispute(bytes32 pid, bytes32 nonce, uint8 kind) external view returns (Dispute memory) {
        return _disputes[_k3(pid, nonce, kind)];
    }

    function boundNonce(bytes32 pid, bytes32 requestHash, bytes32 claimsHash, bytes32 salt) public view returns (bytes32) {
        return keccak256(
            abi.encode(NONCE_TAG, block.chainid, address(this), pid, keccak256(abi.encode(requestHash, claimsHash)), salt)
        );
    }

    function _k2(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, b));
    }

    function _k3(bytes32 a, bytes32 b, uint256 c) internal pure returns (bytes32) {
        return keccak256(abi.encode(a, b, c));
    }

    function node(bytes32 a, bytes32 b) public pure returns (bytes32) {
        return keccak256(abi.encode(NODE_TAG, a, b));
    }

    function rsHash(bytes32 pid, bytes32 codeHash, Receipt calldata r) public pure returns (bytes32) {
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

    function ackDigest(
        bytes32 pid,
        bytes32 codeHash,
        bytes32 nonce,
        uint64 amount,
        bytes32 requestHash,
        bytes32 responseHash,
        bytes32 ctHash,
        bytes32 hRS,
        bool accept
    ) public view returns (bytes32) {
        return G10Sig.typed(
            DOMAIN_SEPARATOR,
            keccak256(
                abi.encode(
                    ACK_TYPEHASH, nonce, uint256(amount), requestHash, responseHash, ctHash, pid, codeHash, hRS, accept
                )
            )
        );
    }

    /// kinds: bit 0 non-delivery, bit 1 key, bit 2 decryption, bit 3 response.
    function mandateDigest(bytes32 pid, bytes32 nonce, address delegate, uint8 kinds) public view returns (bytes32) {
        return G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(MANDATE_TYPEHASH, pid, nonce, delegate, kinds)));
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
                level[i] = node(a, b);
            }
            w = next;
        }
        return level[0];
    }

    function _rootOf(bytes32 leaf, uint256 index, bytes32[] calldata path) internal pure returns (bytes32 h) {
        h = leaf;
        for (uint256 i; i < path.length; i++) {
            h = (index & 1) == 0 ? node(h, path[i]) : node(path[i], h);
            index >>= 1;
        }
    }

    /// U_n < v / V as h * V < v * 2^256.
    function sampledBy(uint256 value, bytes32 nonce, uint64 v, uint64 cap) public pure returns (bool) {
        if (value == 0 || v >= cap) return true;
        uint256 h = uint256(keccak256(abi.encode(value, nonce)));
        uint256 hi;
        assembly {
            let lo := mul(h, cap)
            let mm := mulmod(h, cap, not(0))
            hi := sub(sub(mm, lo), lt(mm, lo))
        }
        return hi < v;
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

    // --------------------------------------------------------- registration

    /// The seller registers its own profile; the receiving vault is deployed
    /// at the address the profile id determines.
    function register(Profile calldata p, uint32 gv) external returns (bytes32 pid) {
        if (msg.sender != p.account) revert Unauthorized();
        if (p.verifier.codehash != p.codeHash || p.codeHash == bytes32(0)) revert BadProfile();
        if (p.deposit > C_ND || p.cap == 0) revert BadProfile();
        pid = profileId(p);
        if (vaultOf[pid] != address(0)) revert Duplicate();
        address v = address(new ReceivingVault{ salt: pid }(token));
        _profiles[pid] = p;
        verifierGas[pid] = gv;
        vaultOf[pid] = v;
        profileOfVault[v] = pid;
        cursor[pid] = epochOf(block.number);
        emit ProfileRegistered(pid, v, p, gv);
    }

    // --------------------------------------------------------------- settle

    /// Anyone (normally the x402 facilitator) settles an EIP-3009
    /// authorization whose `to` is a profile's vault. With a salt, the nonce
    /// must be the bound nonce and the binding hash is recorded.
    function settle(Auth calldata a, bytes calldata sig, bytes32 requestHash, bytes32 claimsHash, bytes32 salt)
        external
    {
        bytes32 pid = profileOfVault[a.to];
        if (pid == bytes32(0)) revert Unknown();
        if (suspended[pid]) revert State();
        Profile storage p = _profiles[pid];
        if (a.value > p.cap) revert OverCap();
        bytes32 k = _k2(pid, a.nonce);
        if (_sales[k].payer != address(0)) revert Duplicate();
        bytes32 binding;
        if (salt != bytes32(0)) {
            if (a.nonce != boundNonce(pid, requestHash, claimsHash, salt)) revert Binding();
            binding = keccak256(abi.encode(requestHash, claimsHash));
        }
        token.transferWithAuthorization(a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce, sig);
        uint256 epoch = epochOf(block.number);
        _sales[k] = Sale({
            payer: a.from,
            amount: uint64(a.value),
            settledBlock: uint32(block.number),
            epoch: uint32(epoch),
            validAfter: uint64(a.validAfter),
            status: ST_HELD,
            bindingCompleted: false,
            binding: binding
        });
        _epochNonces[_k2(pid, bytes32(epoch))].push(a.nonce);
        emit Settled(pid, a.from, a.nonce, a.value, epoch, binding);
    }

    /// Fills an empty binding hash within D_INC of the settlement block.
    function completeBinding(bytes32 pid, bytes32 nonce, bytes32 requestHash, bytes32 claimsHash, bytes32 salt)
        external
    {
        Sale storage s = _sales[_k2(pid, nonce)];
        if (s.payer == address(0) || s.binding != bytes32(0)) revert State();
        if (block.number > s.settledBlock + D_INC) revert Timing();
        if (nonce != boundNonce(pid, requestHash, claimsHash, salt)) revert Binding();
        s.binding = keccak256(abi.encode(requestHash, claimsHash));
        s.bindingCompleted = true;
        emit BindingCompleted(pid, nonce, s.binding);
    }

    // --------------------------------------------------------------- anchor

    function anchorUnit(Unit calldata x) external returns (uint8 reason) {
        reason = _unit(x);
        if (reason != 0) emit UnitRejected(x.pid, x.epoch, x.unitNo, reason);
    }

    function _unit(Unit calldata x) internal returns (uint8) {
        Profile storage p = _profiles[x.pid];
        if (p.account == address(0)) return 1;
        if (block.number <= lastBlock(x.epoch) || block.number > anchorDeadline(x.epoch)) return 3;
        {
            bytes32 d = G10Sig.typed(
                DOMAIN_SEPARATOR,
                keccak256(
                    abi.encode(
                        UNIT_TYPEHASH,
                        x.pid,
                        x.epoch,
                        x.count,
                        x.unitNo,
                        x.first,
                        x.last,
                        x.root,
                        x.root0,
                        keccak256(abi.encode(x.snapshot))
                    )
                )
            );
            if (G10Sig.recover(d, x.sellerSig) != p.unitKey) return 4;
        }
        bytes32 ek = _k2(x.pid, bytes32(uint256(x.epoch)));
        bytes32 uk = _k3(x.pid, bytes32(uint256(x.epoch)), x.unitNo);
        if (unitStoredAt[uk] != 0) return 5;
        if (_epochNonces[ek].length != x.count || x.unitNo == 0) return 6;
        uint256 n = x.leaves.length;
        if (n == 0 || x.leaves[0].rs.nonce != x.first || x.leaves[n - 1].rs.nonce != x.last) return 7;
        bytes32[] memory lv = new bytes32[](n);
        bytes32[] memory lv0 = new bytes32[](n);
        bytes32 codeHash = p.codeHash;
        for (uint256 i; i < n; i++) {
            uint8 r = _leaf(x, i, codeHash, lv, lv0);
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
        unitRoot[uk] = x.root;
        unitFirst[uk] = x.first;
        unitLast[uk] = x.last;
        unitStoredAt[uk] = block.number;
        emit UnitStored(x.pid, x.epoch, x.unitNo, x.root, uint32(n));
        uint256 stored = epochStoredLeaves[ek] + n;
        uint256 units = epochUnits[ek] + 1;
        uint256 maxU = epochMaxUnit[ek];
        if (x.unitNo > maxU) maxU = x.unitNo;
        epochStoredLeaves[ek] = stored;
        epochUnits[ek] = units;
        epochMaxUnit[ek] = maxU;
        if (stored == x.count && units == maxU) {
            epochCompleteAt[ek] = block.number;
            if (p.flags & F_BLOCKHASH != 0) epochHash[ek] = blockhash(block.number - 1);
            emit EpochAnchored(x.pid, x.epoch, x.count);
        }
        // unanswered marks are refunded at the anchor
        for (uint256 i; i < n; i++) {
            if (x.leaves[i].unanswered != 0) _refund(x.pid, x.leaves[i].rs.nonce);
        }
        return 0;
    }

    function _leaf(Unit calldata x, uint256 i, bytes32 codeHash, bytes32[] memory lv, bytes32[] memory lv0)
        internal
        view
        returns (uint8)
    {
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
            hRS = rsHash(x.pid, codeHash, l.rs);
            if (l.sigB.length != 0) {
                sigHash = keccak256(l.sigB);
                bytes32 d = ackDigest(
                    x.pid, codeHash, nonce, l.rs.amount, l.rs.requestHash, l.rs.responseHash, l.rs.ctHash, hRS, l.accept
                );
                if (G10Sig.recover(d, l.sigB) == s.payer) {
                    beta = true;
                    acc = l.accept;
                }
            }
        }
        bytes32 l0 = leaf0Of(nonce, hRS, l.unanswered);
        lv0[i] = l0;
        lv[i] = leafOf(l0, sigHash, beta, acc);
        return 0;
    }

    function epochComplete(bytes32 pid, uint256 epoch) public view returns (bool) {
        return epochCompleteAt[_k2(pid, bytes32(epoch))] != 0;
    }

    function _open(Opening calldata o) internal view returns (bytes32 hRS) {
        hRS = o.unanswered == 0 ? rsHash(o.pid, _profiles[o.pid].codeHash, o.rs) : bytes32(0);
        bytes32 l = leafOf(leaf0Of(o.rs.nonce, hRS, o.unanswered), o.sigHash, o.beta, o.accept);
        bytes32 uk = _k3(o.pid, bytes32(uint256(o.epoch)), o.unitNo);
        if (unitStoredAt[uk] == 0 || _rootOf(l, o.index, o.path) != unitRoot[uk]) revert Membership();
        if (!epochComplete(o.pid, o.epoch)) revert Timing();
    }

    function _refund(bytes32 pid, bytes32 nonce) internal returns (bool) {
        Sale storage s = _sales[_k2(pid, nonce)];
        if (s.status != ST_HELD) return false;
        s.status = ST_REFUNDED;
        ReceivingVault(vaultOf[pid]).pay(s.payer, s.amount);
        emit Refunded(pid, nonce, s.payer, s.amount);
        return true;
    }

    // ------------------------------------------------------- sample, proof

    /// Stand-in for the VRF value paths: the fixed randomness address posts
    /// one value per profile epoch after A_e and until M_e.
    function postSampleValue(bytes32 pid, uint256 epoch, uint256 value) external {
        if (msg.sender != randomness) revert Unauthorized();
        bytes32 ek = _k2(pid, bytes32(epoch));
        if (block.number <= anchorDeadline(epoch) || block.number > valueDeadline(epoch) || sampleValue[ek] != 0) {
            revert Timing();
        }
        sampleValue[ek] = value;
        emit SampleValue(pid, epoch, value);
    }

    function isSampled(bytes32 pid, bytes32 nonce) public view returns (bool) {
        Sale storage s = _sales[_k2(pid, nonce)];
        uint256 value = sampleValue[_k2(pid, bytes32(uint256(s.epoch)))];
        return sampledBy(value, nonce, s.amount, _profiles[pid].cap);
    }

    /// A sampled sale's proof by anyone until M_e + T_p.
    function prove(Opening calldata o, bytes calldata material) external {
        Profile storage p = _profiles[o.pid];
        _open(o);
        bytes32 sk = _k2(o.pid, o.rs.nonce);
        Sale storage s = _sales[sk];
        if (s.epoch != o.epoch || passed[sk] || o.unanswered != 0) revert State();
        if (block.number > valueDeadline(o.epoch) + T_P) revert Timing();
        uint256 value = sampleValue[_k2(o.pid, bytes32(uint256(o.epoch)))];
        if (value == 0 && block.number <= valueDeadline(o.epoch)) revert Timing();
        if (!sampledBy(value, o.rs.nonce, o.rs.amount, p.cap)) revert NotSampled();
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

    // ------------------------------------------------------------ swap proof

    /// A seller-signed receipt for an anchored unsigned leaf whose receipt
    /// part differs: the sale is refunded and the profile suspended.
    function proveSwap(Opening calldata o, Receipt calldata signedRs, bytes calldata rsSig) external {
        Profile storage p = _profiles[o.pid];
        bytes32 hLeaf = _open(o);
        if (o.unanswered != 0 || o.beta) revert State();
        if (signedRs.nonce != o.rs.nonce) revert State();
        bytes32 hSigned = rsHash(o.pid, p.codeHash, signedRs);
        if (hSigned == hLeaf) revert State();
        if (G10Sig.recover(G10Sig.typed(DOMAIN_SEPARATOR, hSigned), rsSig) != p.receiptKey) revert Unauthorized();
        Sale storage s = _sales[_k2(o.pid, o.rs.nonce)];
        if (s.status != ST_HELD || block.number > signDeadlineEnd(o.epoch)) revert Timing();
        suspended[o.pid] = true;
        _refund(o.pid, o.rs.nonce);
        emit SwapProven(o.pid, o.rs.nonce);
    }

    // ------------------------------------------------------------- disputes

    /// Whether the caller of a dispute call is on the payer's side: the payer
    /// itself, or the delegate named in the payer's mandate sigma_W over
    /// (profile id, nonce, delegate, kinds) with this kind among its kinds.
    /// A contract payer's mandate is checked with ERC-1271 isValidSignature
    /// (a failing call reverts only this dispute transaction).
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
            (bool ok, bytes memory ret) = payer.staticcall(abi.encodeWithSelector(0x1626ba7e, dg, mandate));
            return ok && ret.length == 32 && bytes4(ret) == bytes4(0x1626ba7e);
        }
        return G10Sig.recover(dg, mandate) == payer;
    }

    /// Non-delivery (kind 1, leaf without a valid buyer signature) or key
    /// dispute (kind 2, ciphertext profile, signed leaf), by anyone until
    /// A_e + T_c; the opener pays the deposit. A payer-side opening is not
    /// blocked: it takes over an open third-party dispute of the same kind
    /// (returning the third party's deposit), or reopens a closed one while
    /// the sale is held; a seller answer already on chain stands as the
    /// answer of the new dispute and T_x runs from this block. A second
    /// opening of an open payer-side dispute, and any third-party opening of
    /// a kind already opened, reverts.
    function openDispute(Opening calldata o, uint8 kind, bytes calldata mandate, uint8 kinds) external {
        bytes32 sk = _k2(o.pid, o.rs.nonce);
        Sale storage s = _sales[sk];
        if (s.payer == address(0) || s.epoch != o.epoch || s.status != ST_HELD) revert State();
        if (block.number > anchorDeadline(o.epoch) + T_C) revert Timing();
        Profile storage p = _profiles[o.pid];
        if (kind == K_NONDELIVERY) {
            if (o.beta || o.unanswered != 0) revert State();
        } else if (kind == K_KEY) {
            if (!o.beta || p.flags & F_CT == 0) revert State();
        } else {
            revert State();
        }
        Dispute storage d = _disputes[_k3(o.pid, o.rs.nonce, kind)];
        bool side = payerSide(o.pid, o.rs.nonce, kind, msg.sender, mandate, kinds);
        bool live = d.state == D_OPEN || d.state == D_ANSWERED;
        if (d.state != 0 && (!side || (live && d.authorized))) revert Duplicate();
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
        if (live) {
            // payer-side takeover of a third-party dispute
            if (d.deposit != 0) require(token.transfer(d.opener, d.deposit), "transfer");
        } else {
            openDisputes[sk] += 1;
        }
        d.opener = msg.sender;
        d.authorized = side;
        d.deposit = dep;
        d.bad = d.state == D_ANSWERED && d.bad; // a recorded mismatch stays with the open dispute
        if (d.hasAnswer && _counts(o.pid, o.rs.nonce, kind, d)) {
            d.state = D_ANSWERED;
            d.deadline = uint64(block.number + T_X);
        } else if (!live) {
            d.state = D_OPEN;
            d.bad = false;
            d.deadline = uint64(block.number + T_D);
        } else if (d.state == D_ANSWERED) {
            // the stored answer does not count on the payer side (late)
            d.state = D_OPEN;
            d.bad = false;
            d.deadline = uint64(block.number + T_D);
        }
        emit DisputeOpened(o.pid, o.rs.nonce, kind, msg.sender, side);
    }

    /// Whether a stored seller answer counts as delivery for dispute d: a
    /// non-delivery answer after block settled + r_dl does not count on the
    /// payer side (it is kept, and the dispute ends undelivered after T_d).
    function _counts(bytes32 pid, bytes32 nonce, uint8 kind, Dispute storage d) internal view returns (bool) {
        if (kind != K_NONDELIVERY || !d.authorized) return true;
        uint32 rdl = _profiles[pid].responseDeadline;
        return rdl == 0 || d.answerBlock <= uint256(_sales[_k2(pid, nonce)].settledBlock) + rdl;
    }

    /// The seller's delivery for a non-delivery dispute: ct and k, within
    /// T_d. A late answer on a payer-side dispute of a profile with a
    /// response deadline is kept but is not delivery.
    function answerDeliver(bytes32 pid, bytes32 nonce, bytes calldata ct, bytes32 k) external {
        Dispute storage d = _disputes[_k3(pid, nonce, K_NONDELIVERY)];
        if (d.state != D_OPEN || d.hasAnswer || block.number > d.deadline) revert State();
        LeafInfo storage li = _leafInfo[_k2(pid, nonce)];
        if (keccak256(ct) != li.ctHash || keccak256(abi.encode(k)) != li.keyHash) revert State();
        d.key = k;
        d.hasAnswer = true;
        d.answerBlock = uint64(block.number);
        emit Delivered(pid, nonce, ct, k);
        if (_counts(pid, nonce, K_NONDELIVERY, d)) {
            d.state = D_ANSWERED;
            d.deadline = uint64(block.number + T_X);
        }
    }

    /// The seller's answer to a non-delivery dispute with the buyer's valid
    /// signature for the nonce: the seller wins and takes the deposit.
    function answerWithAck(bytes32 pid, bytes32 nonce, bool accept, bytes calldata sigB) external {
        bytes32 sk = _k2(pid, nonce);
        Dispute storage d = _disputes[_k3(pid, nonce, K_NONDELIVERY)];
        if (d.state != D_OPEN || block.number > d.deadline) revert State();
        LeafInfo storage li = _leafInfo[sk];
        Sale storage s = _sales[sk];
        bytes32 dg = ackDigest(
            pid, _profiles[pid].codeHash, nonce, s.amount, li.requestHash, li.responseHash, li.ctHash, li.hRS, accept
        );
        if (G10Sig.recover(dg, sigB) != s.payer) revert Unauthorized();
        d.state = D_CLOSED;
        openDisputes[sk] -= 1;
        if (d.deposit != 0) require(token.transfer(_profiles[pid].account, d.deposit), "transfer");
        emit AckShown(pid, nonce);
        emit DisputeClosed(pid, nonce, K_NONDELIVERY, false, _profiles[pid].account);
    }

    /// The seller's key for a key dispute, within T_d.
    function answerKey(bytes32 pid, bytes32 nonce, bytes32 k) external {
        Dispute storage d = _disputes[_k3(pid, nonce, K_KEY)];
        if (d.state != D_OPEN || block.number > d.deadline) revert State();
        if (keccak256(abi.encode(k)) != _leafInfo[_k2(pid, nonce)].keyHash) revert State();
        d.key = k;
        d.hasAnswer = true;
        d.answerBlock = uint64(block.number);
        d.state = D_ANSWERED;
        d.deadline = uint64(block.number + T_X);
        emit KeyRevealed(pid, nonce, k);
    }

    /// Decryption challenge by anyone: ct must match h_ct; the key is the
    /// one posted in the dispute, or, for an open key dispute, a key the
    /// caller received that matches h_k. A mismatch with h_r marks the
    /// dispute for a refund at its close; a match changes nothing.
    function challengeDecrypt(bytes32 pid, bytes32 nonce, uint8 kind, bytes calldata ct, bytes32 offchainKey)
        external
        returns (bool mismatch)
    {
        bytes32 sk = _k2(pid, nonce);
        Dispute storage d = _disputes[_k3(pid, nonce, kind)];
        LeafInfo storage li = _leafInfo[sk];
        bytes32 k;
        if (d.state == D_ANSWERED && block.number <= d.deadline) {
            k = d.key;
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

    /// Anyone closes a dispute after its window: unanswered (or answered
    /// late on the payer side) after T_d, or answered after T_x. Refund on
    /// no delivery or a recorded mismatch; on delivery the deposit returns to
    /// a payer-side opener and goes to the seller from a third-party one.
    function closeDispute(bytes32 pid, bytes32 nonce, uint8 kind) external returns (bool refunded) {
        bytes32 sk = _k2(pid, nonce);
        Dispute storage d = _disputes[_k3(pid, nonce, kind)];
        if ((d.state != D_OPEN && d.state != D_ANSWERED) || block.number <= d.deadline) revert State();
        address depositTo;
        if (d.state == D_OPEN || d.bad) {
            refunded = true;
            depositTo = d.opener;
        } else {
            depositTo = d.authorized ? d.opener : _profiles[pid].account;
        }
        d.state = D_CLOSED;
        openDisputes[sk] -= 1;
        if (refunded) _refund(pid, nonce);
        if (d.deposit != 0) require(token.transfer(depositTo, d.deposit), "transfer");
        emit DisputeClosed(pid, nonce, kind, refunded, depositTo);
    }

    // -------------------------------------------------------------- release

    /// Cursor step for one profile epoch: after W_e and A_e + T_c, with the
    /// epoch anchored (or empty), no open dispute, and a passing proof for
    /// every sampled sale still held. Pays the held sales to the seller.
    function release(bytes32 pid) external returns (uint256 paid) {
        uint256 epoch = cursor[pid];
        bytes32 ek = _k2(pid, bytes32(epoch));
        bytes32[] storage ns = _epochNonces[ek];
        if (block.number <= signDeadlineEnd(epoch) || block.number <= anchorDeadline(epoch) + T_C) revert Timing();
        if (ns.length != 0 && epochCompleteAt[ek] == 0) revert State();
        uint256 value = sampleValue[ek];
        uint64 cap = _profiles[pid].cap;
        for (uint256 i; i < ns.length; i++) {
            bytes32 sk = _k2(pid, ns[i]);
            Sale storage s = _sales[sk];
            if (openDisputes[sk] != 0) revert State();
            if (s.status != ST_HELD) continue;
            if (sampledBy(value, ns[i], s.amount, cap) && !passed[sk]) revert NotSampled();
            s.status = ST_PAID;
            paid += s.amount;
        }
        cursor[pid] = epoch + 1;
        if (paid != 0) ReceivingVault(vaultOf[pid]).pay(_profiles[pid].account, paid);
        emit Released(pid, epoch, paid);
    }
}
