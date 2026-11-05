// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { G10Base, G10Sig } from "./G10Base.sol";
import { FairBindMerkle } from "../../src/FairBindMerkle.sol";

/// A gas sketch of the rule 10 v0.3 anchor (R3) and of releasing one sale
/// with a lazy deadline check over the epoch's earlier sampled cases (R6 (a)
/// (2)). It is not the FairBind implementation: settlement records are
/// written in setUp, payment is an internal balance credit (no token
/// transfer), and the sample value, dispute windows and freeze are reduced
/// to the slots a release reads or writes.
///
/// Anchor: the entry count equals the epoch's settled count, nonces ascend,
/// each entry's amount and profile match the settlement record (one cold
/// slot per nonce), each buyer signature (if any) is checked against the
/// payer (beta), an accepted sale (a = 1) is paid in the same transaction,
/// the merkle-v1 root over (nonce, H(leaf, signature hash)) is computed, each
/// snapshot key was registered before the epoch's first settlement block,
/// the seller signs (epoch, count, root, snapshot hash), and the anchor
/// stores the root, the snapshot hash, the previous block hash and the beta
/// bitmap.
contract Rule10Sketch {
    struct Sale {
        address payer; // 20 bytes
        uint64 amount; // 8
        uint32 epoch; // 4  (slot 0 full)
        uint64 settleBlock;
        uint64 validAfter;
        uint8 status; // 0 held, 1 paid, 2 frozen, 3 refunded
        bool sampled;
    }

    struct Leaf {
        bytes32 nonce;
        uint64 amount;
        bytes32 requestHash;
        bytes32 responseHash;
        bytes32 ctHash;
        bytes32 keyHash;
        bytes32 claimsHash;
        bytes32 materialCommit;
    }

    struct BuyerSig {
        bytes sig; // empty when the sale carries none
        bool accepted;
    }

    struct Anchor {
        bytes32 root;
        bytes32 snapshotHash;
        bytes32 prevBlockHash;
        uint64 anchoredAt;
        uint32 count;
    }

    struct Case {
        uint64 deadline;
        uint8 state; // 0 open, 1 passed, 2 failed
    }

    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bool accepted)"
    );
    bytes32 internal constant ANCHOR_TYPEHASH =
        keccak256("Anchor(uint32 epoch,uint32 count,bytes32 root,bytes32 snapshotHash)");
    bytes32 public immutable DOMAIN_SEPARATOR;
    bytes32 public constant PROFILE = keccak256("profile");
    bytes32 public constant CODEHASH = keccak256("verifier code");
    uint64 internal constant DISPUTE_WINDOW = 300;
    uint64 internal constant BUYER_WINDOW = 400;

    address public sellerKey;
    mapping(bytes32 => Sale) public sales;
    mapping(uint32 => uint32) public settledCount;
    mapping(uint32 => uint64) public firstSettleBlock;
    mapping(address => uint64) public keyRegisteredAt;
    mapping(uint32 => Anchor) public anchors;
    mapping(uint32 => mapping(uint256 => uint256)) public betaBits;
    mapping(uint32 => bytes32) public sampleValue;
    mapping(uint32 => uint64) public sampleBlock;
    mapping(uint32 => bytes32[]) public sampledCases;
    mapping(bytes32 => Case) public cases;
    uint256 public sellerBalance;
    uint256 public bond;
    uint64 public frozenFrom;
    bool public suspended;
    uint256 public fees;

    constructor(address seller) {
        sellerKey = seller;
        bond = 1e12;
        // Steady state: the seller balance and the fee pool already hold
        // value, so a credit is a nonzero-to-nonzero write.
        sellerBalance = 1;
        fees = 1;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"),
                keccak256("FairBind"),
                keccak256("10"),
                block.chainid,
                address(this)
            )
        );
    }

    // ----------------------------------------------------------- set-up only

    function registerKey(address k, uint64 at) external {
        keyRegisteredAt[k] = at;
    }

    function settleFixture(bytes32 nonce, address payer, uint64 amount, uint32 epoch, uint64 validAfter) external {
        sales[nonce] = Sale(payer, amount, epoch, uint64(block.number), validAfter, 0, false);
        if (settledCount[epoch] == 0) firstSettleBlock[epoch] = uint64(block.number);
        settledCount[epoch]++;
    }

    function sampleFixture(uint32 epoch, bytes32 value, bytes32[] calldata sampled, uint64 deadline, uint8 state) external {
        sampleValue[epoch] = value;
        sampleBlock[epoch] = uint64(block.number);
        for (uint256 i; i < sampled.length; i++) {
            sales[sampled[i]].sampled = true;
            cases[sampled[i]] = Case(deadline, state);
            sampledCases[epoch].push(sampled[i]);
        }
    }

    // ---------------------------------------------------------------- anchor

    function _ackDigest(Leaf calldata l, bool accepted) internal view returns (bytes32) {
        return G10Sig.typed(
            DOMAIN_SEPARATOR,
            keccak256(
                abi.encode(
                    ACK_TYPEHASH, l.nonce, uint256(l.amount), l.requestHash, l.responseHash, l.ctHash, PROFILE, CODEHASH, accepted
                )
            )
        );
    }

    function anchor(
        uint32 epoch,
        Leaf[] calldata leaves,
        BuyerSig[] calldata sigs,
        address[] calldata snapshot,
        bytes calldata sellerSig
    ) external {
        uint256 n = leaves.length;
        require(anchors[epoch].anchoredAt == 0, "anchored");
        require(n == settledCount[epoch] && sigs.length == n, "count");
        bytes32[] memory level = new bytes32[](n);
        uint256 bits;
        uint256 paid;
        bytes32 prev;
        for (uint256 i; i < n; i++) {
            Leaf calldata l = leaves[i];
            require(i == 0 || l.nonce > prev, "order");
            prev = l.nonce;
            Sale storage s = sales[l.nonce];
            address payer = s.payer;
            require(payer != address(0) && s.epoch == epoch && s.amount == l.amount, "settlement");
            bytes32 sigHash;
            if (sigs[i].sig.length != 0) {
                sigHash = keccak256(sigs[i].sig);
                if (G10Sig.recover(_ackDigest(l, sigs[i].accepted), sigs[i].sig) == payer) {
                    bits |= 1 << (2 * (i & 127));
                    if (sigs[i].accepted) {
                        bits |= 2 << (2 * (i & 127));
                        s.status = 1;
                        paid += l.amount;
                    }
                }
            }
            level[i] = FairBindMerkle.entryHash(l.nonce, keccak256(abi.encode(keccak256(abi.encode(l)), sigHash)));
            if ((i & 127) == 127 || i == n - 1) {
                betaBits[epoch][i >> 7] = bits;
                bits = 0;
            }
        }
        bytes32 root = _root(level);
        uint64 first = firstSettleBlock[epoch];
        for (uint256 j; j < snapshot.length; j++) {
            uint64 at = keyRegisteredAt[snapshot[j]];
            require(at != 0 && at < first, "snapshot key");
        }
        bytes32 snapshotHash = keccak256(abi.encode(snapshot));
        bytes32 d = G10Sig.typed(DOMAIN_SEPARATOR, keccak256(abi.encode(ANCHOR_TYPEHASH, epoch, uint32(n), root, snapshotHash)));
        require(G10Sig.recover(d, sellerSig) == sellerKey, "seller signature");
        anchors[epoch] = Anchor(root, snapshotHash, blockhash(block.number - 1), uint64(block.number), uint32(n));
        if (paid != 0) sellerBalance += paid;
    }

    function _root(bytes32[] memory level) internal pure returns (bytes32) {
        uint256 w = level.length;
        while (w > 1) {
            uint256 next = (w + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 a = level[2 * i];
                bytes32 b = 2 * i + 1 < w ? level[2 * i + 1] : a;
                level[i] = FairBindMerkle.nodeHash(a, b);
            }
            w = next;
        }
        return level[0];
    }

    // --------------------------------------------------------------- release

    /// Releases one held sale of `epoch`. Every sampled case of the epoch is
    /// read; a case whose deadline has passed is failed here (the lazy
    /// deadline check), which freezes later sales, slashes and suspends.
    /// Returns whether the sale was paid.
    function release(uint32 epoch, bytes32 nonce) external returns (bool) {
        Sale storage s = sales[nonce];
        require(s.epoch == epoch && s.status == 0, "not held");
        Anchor storage a = anchors[epoch];
        require(a.anchoredAt != 0 && sampleValue[epoch] != 0, "not anchored or no sample");
        uint64 sb = sampleBlock[epoch];
        bytes32[] storage cs = sampledCases[epoch];
        uint256 k = cs.length;
        bool failedNow;
        uint64 failFrom = type(uint64).max;
        for (uint256 i; i < k; i++) {
            bytes32 cn = cs[i];
            Case storage c = cases[cn];
            uint8 st = c.state;
            if (st == 0) {
                require(block.number > c.deadline, "case open");
                c.state = 2;
                failedNow = true;
                uint64 sf = sales[cn].settleBlock;
                if (sf < failFrom) failFrom = sf;
            }
        }
        if (failedNow) {
            uint64 f = frozenFrom;
            if (f == 0 || failFrom < f) frozenFrom = failFrom;
            if (!suspended) suspended = true;
            uint256 b = bond;
            bond = 0;
            fees += b; // locked; the recipient is open (rule 10 v0.3, decision 6)
        }
        uint64 ff = frozenFrom;
        if (ff != 0 && s.settleBlock >= ff) {
            s.status = 2;
            return false;
        }
        // Windows: the dispute window from the sample, and W_e for beta = 0.
        require(block.number > sb + DISPUTE_WINDOW, "dispute window");
        bool beta = _beta(epoch, nonce);
        if (!beta) require(block.number > sb + BUYER_WINDOW, "buyer window");
        s.status = 1;
        uint256 fee = s.amount / 100;
        sellerBalance += s.amount - fee;
        fees += fee;
        return true;
    }

    /// Beta of a sale from the anchor's bitmap (the sketch keeps the entry
    /// index in the low bits of the nonce for this lookup).
    function _beta(uint32 epoch, bytes32 nonce) internal view returns (bool) {
        uint256 i = uint256(nonce) & 0xFFFF;
        return (betaBits[epoch][i >> 7] >> (2 * (i & 127))) & 1 == 1;
    }
}

/// Run with --isolate. Every number is logged; nothing is asserted about gas.
contract Rule10SketchGasTest is G10Base {
    Rule10Sketch internal r;
    uint256 internal constant SELLER_KEY = 0x5E11;
    uint256 internal constant BUYER_KEY = 0xB0B;
    uint32 internal constant EPOCH = 1;
    bytes32 internal constant ACK_TYPEHASH = keccak256(
        "BuyerAck(bytes32 nonce,uint256 amount,bytes32 requestHash,bytes32 responseHash,bytes32 ctHash,bytes32 profileId,bytes32 codeHash,bool accepted)"
    );
    bytes32 internal constant ANCHOR_TYPEHASH =
        keccak256("Anchor(uint32 epoch,uint32 count,bytes32 root,bytes32 snapshotHash)");

    function setUp() public {
        hv.roll(100);
        r = new Rule10Sketch(hv.addr(SELLER_KEY));
        for (uint256 i; i < 4; i++) r.registerKey(hv.addr(0x7EE0 + i), 50);
        hv.roll(200);
    }

    /// Nonce i: a hash with the entry index in its low 16 bits, so nonces
    /// ascend with i.
    function _nonce(uint256 i) internal pure returns (bytes32) {
        return bytes32((uint256(keccak256("n")) >> 32 << 32) | (i << 16) | i);
    }

    function _leaf(uint256 i) internal pure returns (Rule10Sketch.Leaf memory l) {
        l.nonce = _nonce(i);
        l.amount = uint64(10_000 + i);
        l.requestHash = keccak256(abi.encode("req", i));
        l.responseHash = keccak256(abi.encode("resp", i));
        l.ctHash = keccak256(abi.encode("ct", i));
        l.keyHash = keccak256(abi.encode("k", i));
        l.claimsHash = keccak256("claims");
        l.materialCommit = keccak256(abi.encode("material", i));
    }

    function _settle(uint256 n) internal {
        for (uint256 i; i < n; i++) r.settleFixture(_nonce(i), hv.addr(BUYER_KEY), uint64(10_000 + i), EPOCH, 1_800_000_000);
    }

    /// mode 0: no buyer signatures; 1: every sale signed with a = 0;
    /// 2: every sale signed, one in four accepted.
    function _anchorArgs(uint256 n, uint256 mode, uint256 snap)
        internal
        returns (Rule10Sketch.Leaf[] memory ls, Rule10Sketch.BuyerSig[] memory ss, address[] memory sn, bytes memory sellerSig)
    {
        ls = new Rule10Sketch.Leaf[](n);
        ss = new Rule10Sketch.BuyerSig[](n);
        bytes32[] memory level = new bytes32[](n);
        bytes32 dom = r.DOMAIN_SEPARATOR();
        for (uint256 i; i < n; i++) {
            ls[i] = _leaf(i);
            bytes32 sigHash;
            if (mode != 0) {
                bool acc = mode == 2 && i % 4 == 0;
                Rule10Sketch.Leaf memory l = ls[i];
                bytes32 d = G10Sig.typed(
                    dom,
                    keccak256(
                        abi.encode(ACK_TYPEHASH, l.nonce, uint256(l.amount), l.requestHash, l.responseHash, l.ctHash, r.PROFILE(), r.CODEHASH(), acc)
                    )
                );
                ss[i] = Rule10Sketch.BuyerSig(_sig(BUYER_KEY, d), acc);
                sigHash = keccak256(ss[i].sig);
            }
            level[i] = FairBindMerkle.entryHash(ls[i].nonce, keccak256(abi.encode(keccak256(abi.encode(ls[i])), sigHash)));
        }
        bytes32 root = _rootOf(level);
        sn = new address[](snap);
        for (uint256 j; j < snap; j++) sn[j] = hv.addr(0x7EE0 + j);
        bytes32 ad = G10Sig.typed(dom, keccak256(abi.encode(ANCHOR_TYPEHASH, EPOCH, uint32(n), root, keccak256(abi.encode(sn)))));
        sellerSig = _sig(SELLER_KEY, ad);
    }

    function _rootOf(bytes32[] memory level) internal pure returns (bytes32) {
        uint256 w = level.length;
        while (w > 1) {
            uint256 next = (w + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 a = level[2 * i];
                bytes32 b = 2 * i + 1 < w ? level[2 * i + 1] : a;
                level[i] = FairBindMerkle.nodeHash(a, b);
            }
            w = next;
        }
        return level[0];
    }

    function _measureAnchor(uint256 n, uint256 mode, uint256 snap) internal {
        uint256 id = hv.snapshotState();
        _settle(n);
        hv.roll(300);
        (Rule10Sketch.Leaf[] memory ls, Rule10Sketch.BuyerSig[] memory ss, address[] memory sn, bytes memory sellerSig) =
            _anchorArgs(n, mode, snap);
        uint256 g = gasleft();
        r.anchor(EPOCH, ls, ss, sn, sellerSig);
        g -= gasleft();
        _rec(address(r), abi.encodeCall(r.anchor, (EPOCH, ls, ss, sn, sellerSig)));
        string memory tag = string.concat(
            "G10-5 anchor n=", _u(n), mode == 0 ? " no buyer sigs" : mode == 1 ? " all signed a=0" : " all signed, 1/4 accepted", " snapshot=", _u(snap)
        );
        _log(string.concat(tag, ", tx gas"), g);
        _log(string.concat(tag, ", calldata gas"), _cdGas(abi.encodeCall(r.anchor, (EPOCH, ls, ss, sn, sellerSig))));
        hv.revertToState(id);
    }

    function test_gas_anchor() public {
        uint256[3] memory ns = [uint256(1), 8, 32];
        for (uint256 a; a < 3; a++) {
            for (uint256 mode; mode < 3; mode++) _measureAnchor(ns[a], mode, 1);
            _measureAnchor(ns[a], 1, 4);
        }
    }

    /// Release one sale (entry 7 of 8, signed, unsampled) after k earlier
    /// sampled cases of its epoch: closed (passed) or open past their
    /// deadline (failed lazily in this call).
    function _measureRelease(uint256 k, uint8 caseState) internal {
        uint256 id = hv.snapshotState();
        _settle(8);
        hv.roll(300);
        (Rule10Sketch.Leaf[] memory ls, Rule10Sketch.BuyerSig[] memory ss, address[] memory sn, bytes memory sellerSig) =
            _anchorArgs(8, 1, 1);
        r.anchor(EPOCH, ls, ss, sn, sellerSig);
        bytes32[] memory sampled = new bytes32[](k);
        for (uint256 i; i < k; i++) sampled[i] = _nonce(i);
        hv.roll(400);
        r.sampleFixture(EPOCH, keccak256("sample"), sampled, 500, caseState);
        hv.roll(1000);
        uint256 g = gasleft();
        bool paid = r.release(EPOCH, _nonce(7));
        g -= gasleft();
        _rec(address(r), abi.encodeCall(r.release, (EPOCH, _nonce(7))));
        require(paid == (caseState == 1 || k == 0), "release outcome");
        _log(
            string.concat("G10-5 release one sale, k=", _u(k), caseState == 1 ? " closed cases" : " expired cases (lazy failure, sale frozen)", ", tx gas"),
            g
        );
        hv.revertToState(id);
    }

    function test_gas_release() public {
        uint256[3] memory ks = [uint256(0), 1, 4];
        for (uint256 i; i < 3; i++) _measureRelease(ks[i], 1);
        _measureRelease(1, 0);
        _measureRelease(4, 0);
    }
}
