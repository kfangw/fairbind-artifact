// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";
import { MockUniquePriceFeed, MockGasPriceOracle, Mock1271Wallet, MultiCall } from "./ExchangeMocks.sol";
import { IExchangeFairBind } from "./ExchangeInterfaces.sol";
import { FairBindBatch } from "../src/modules/FairBindBatch.sol";
import { FairBindBatchAdmin } from "../src/modules/FairBindBatchAdmin.sol";
import { FairBindProof } from "../src/modules/FairBindProof.sol";
import { FairBindDeposit } from "../src/modules/FairBindDeposit.sol";
import { FairBindExchange } from "../src/modules/FairBindExchange.sol";
import { FairBindPassProof } from "../src/modules/FairBindPassProof.sol";
import { FairBindSelfProof } from "../src/modules/FairBindSelfProof.sol";
// Keeps the mutation artifacts built when a filter selects only some tests.
import { LateMatchExchange } from "./ExchangeMutants.sol";

interface ExchangeVm {
    function warp(uint256 t) external;
    function fee(uint256 basefee) external;
    function txGasPrice(uint256 price) external;
    function etch(address target, bytes calldata code) external;
    function getBlockTimestamp() external view returns (uint256);
    function expectRevert(bytes4 selector) external;
    function expectRevert() external;
    function lastCallGas() external view returns (uint64 gasLimit, uint64 gasTotalUsed, uint64 gasMemoryUsed, int64 gasRefunded, uint64 gasRemaining);
}

/// Deployment and driving helpers for receipt-signature and proof profiles
/// (ADR 0037). Every purchase of the base profile is sampled. Epoch 0 runs
/// from block 1 to 300, its anchor window is [600, 700] (A_0 = 700), its
/// value block 1469 and its seal deadline 1669. Block timestamps start at
/// T0 and do not move with the block number unless a test warps.
abstract contract ExchangeBase is ModuleSwapBase {
    ExchangeVm internal constant xv = ExchangeVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant GUARDIAN_KEY = 0x6A2D;
    uint256 internal constant T0 = 1_800_000_000;
    address internal constant ORACLE = 0x420000000000000000000000000000000000000F;
    bytes32 internal constant FEED = keccak256("BTC/USD");
    bytes32 internal constant TAG = keccak256("fairbind/response/v1");
    uint256 internal constant BASEFEE = 10_000_000;
    uint256 internal constant L1_UNIT = 10_000_000;
    int64 internal constant PRICE = 8_575_490_000_000;
    bytes internal constant RESPONSE = bytes("85754.90");

    IExchangeFairBind internal fx;
    MockUniquePriceFeed internal feed;
    MockGasPriceOracle internal oracle;
    uint8 internal mode = ExchangeStore.MODE_PROOF;
    uint16 internal padLen = 64;
    string internal exchangeArtifact = "FairBindExchange.sol:FairBindExchange";
    string internal passArtifact = "FairBindPassProof.sol:FairBindPassProof";
    string internal selfArtifact = "FairBindSelfProof.sol:FairBindSelfProof";
    string internal batchAdminArtifact = "FairBindBatchAdmin.sol:FairBindBatchAdmin";
    /// The eighth and ninth extension modules (rule edition 8) when set.
    string internal rule8Artifact;
    string internal rule8ReleaseArtifact = "FairBindRule8Release.sol:FairBindRule8Release";
    /// Deployment switches of the activation tests: no oracle code, an
    /// oracle without the bound (before Fjord), and the setting that
    /// requires exchange terms for activation.
    bool internal noOracle;
    bool internal oracleBoundOff;
    bool internal termsRequired;
    /// Whether the deployment activates its profile.
    bool internal skipActivation;
    string[10] internal moduleNames;

    struct Bundle {
        bytes32 ek;
        bytes ct;
        bytes32 ctHash;
        bytes32 ekHash;
        bytes32 rHash;
        bytes32 leaf;
    }

    mapping(bytes32 => bytes32) internal leafOf;
    mapping(bytes32 => Bundle) internal bundleOf;
    bytes32[] internal xs;
    bytes32[][] internal xLevels;
    mapping(bytes32 => uint32) internal xIndex;

    // ------------------------------------------------------------ terms

    function _exchangeProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
    }

    function _input(uint8 m) internal view returns (ExchangeStore.Input memory x) {
        // Input judgment: PROOF, or VOTE with receipt signatures unless the
        // stored mode asked for is NONE.
        x.mode = m == ExchangeStore.MODE_PROOF ? ExchangeStore.INPUT_PROOF : ExchangeStore.INPUT_VOTE;
        x.receiptSigOff = m == ExchangeStore.MODE_NONE;
        x.priceCap = 4_000_000_000;
        x.gFixTx = 21_000;
        x.gFixCall = 12_000;
        x.bEnv = 100;
        x.gasPriceCap = 1;
        x.l1PriceCap = 1;
        x.pubGas = 2_000_000;
        x.pubBytes = 70_000;
        x.keyGas = 400_000;
        x.keyBytes = 1_200;
        x.keyCap = 401_200;
        x.blockGasShare = 1_000_000;
        x.bundleBlocks = 20;
        x.keyBlocks = 20;
        x.disputeSlack = 10;
        x.postSlack = 30;
        x.confirmBlocks = 10;
        x.g1271 = 50_000;
        x.padLength = padLen;
        x.sigLimit = 256;
        if (m == ExchangeStore.MODE_PROOF) {
            x.proofBlocks = 300;
            x.refWindow = 120;
            x.freshWindow = 30;
            x.settleSlack = 30;
            x.maxSkew = 10;
            x.verifier = address(feed);
            x.feedId = FEED;
            x.maxUpdateBytes = 512;
            x.tolerancePpm = 1_000;
        }
        x.tag = TAG;
        // F_max and the binding proof slack: F_max = 30,008 lies in check 8's
        // [L_F + marginBlocks - 1, T_hold - 1] = [26,272, 39,999] (L_F the
        // judgment delay 25,773 of the profile check under these deadlines,
        // no batch terms; T_hold = T_keep = 40,000, check 6), and check 7:
        // 2 * 300 + 100 + 1 + beacon delay 768 = 1,469 blocks from the epoch
        // start to the value block, plus the slack.
        x.bindWindow = 30_008;
        x.bindSlack = 100;
    }

    // ------------------------------------------------------- deployment

    /// Deploys the production modules (or `moduleNames` when set), the seven
    /// extension modules, one profile with the given exchange terms, fourteen
    /// verifiers and one seller; puts the L1 fee oracle at its predeploy
    /// address before activation, warps to T0 and sets the base fee.
    function _deployExchange(FairBindCore.ServiceProfileInput memory p, ExchangeStore.Input memory x, bool setTerms)
        internal
    {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        bytes memory args = abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        string[10] memory names = _productionModules();
        for (uint256 i; i < 10; i++) {
            if (bytes(moduleNames[i]).length != 0) names[i] = moduleNames[i];
        }
        address[10] memory modules;
        for (uint256 i; i < 10; i++) modules[i] = swapArtifacts.deployCode(names[i], args);
        fairbind = FairBind(
            swapArtifacts.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL, modules)
            )
        );
        fx = IExchangeFairBind(address(fairbind));
        address[] memory exts = new address[](bytes(rule8Artifact).length != 0 ? 9 : 7);
        exts[0] = swapArtifacts.deployCode("FairBindBatch.sol:FairBindBatch", args);
        exts[1] = swapArtifacts.deployCode(batchAdminArtifact, args);
        exts[2] = swapArtifacts.deployCode("FairBindProof.sol:FairBindProof", args);
        exts[3] = swapArtifacts.deployCode("FairBindDeposit.sol:FairBindDeposit", args);
        exts[4] = swapArtifacts.deployCode(exchangeArtifact, args);
        exts[5] = swapArtifacts.deployCode(passArtifact, args);
        exts[6] = swapArtifacts.deployCode(selfArtifact, args);
        if (exts.length == 9) {
            exts[7] = swapArtifacts.deployCode(rule8Artifact, args);
            exts[8] = swapArtifacts.deployCode(rule8ReleaseArtifact, args);
        }
        fx.setExtensions(exts);
        // The L1 fee oracle sits at its predeploy before activation, which
        // checks its bound (unless a test leaves it out).
        if (!noOracle) {
            MockGasPriceOracle o = new MockGasPriceOracle();
            xv.etch(ORACLE, address(o).code);
            oracle = MockGasPriceOracle(ORACLE);
            oracle.set(L1_UNIT, 20_000_000_000);
            oracle.setBoundOff(oracleBoundOff);
        }
        if (termsRequired) fx.requireExchangeTerms();
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        _beforeProfile();
        fairbind.createServiceProfile(PROFILE, p);
        token.mint(address(this), 10_000_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), 10_000_000);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        if (setTerms) _setTerms(x);
        _afterProfile();
        if (skipActivation) return;
        fairbind.setServiceProfileActive(PROFILE, true);
        token.mint(SELLER_OWNER, 1_000_000_000_000);
        hv.startPrank(SELLER_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        sellerId = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(p.sellerPenalty));
        hv.stopPrank();
        buyer = hv.addr(BUYER_KEY);
        token.mint(buyer, 1_000_000_000_000);
        hv.prank(buyer);
        token.approve(address(fairbind), type(uint256).max);
        xv.warp(T0);
        xv.fee(BASEFEE);
        // A transaction pays at least the base fee (an isolated call
        // otherwise runs with a zero base fee).
        xv.txGasPrice(BASEFEE);
    }

    /// Runs after the router is deployed and before the profile is created
    /// (a test sets its randomness source here). Nothing by default.
    function _beforeProfile() internal virtual { }

    /// Runs after the profile and its exchange terms exist and before it is
    /// activated (a rule 8 test sets its terms here). Nothing by default.
    function _afterProfile() internal virtual { }

    function _setTerms(ExchangeStore.Input memory x) internal {
        x.termsHash = fx.exchangeTermsHash(PROFILE, x);
        fx.setExchangeTerms(PROFILE, x);
    }

    /// The default deployment of mode `mode` with its default terms.
    function _deployDefault() internal {
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(_exchangeProfile(), _input(mode), true);
    }

    function _deployWith(FairBindCore.ServiceProfileInput memory p) internal {
        feed = new MockUniquePriceFeed(hv.addr(GUARDIAN_KEY));
        _deployExchange(p, _input(mode), true);
    }

    function _ts() internal view returns (uint256) {
        return xv.getBlockTimestamp();
    }

    // -------------------------------------------------------- purchases

    /// A purchase whose EIP-3009 validAfter is `age` seconds before now.
    function _buy(uint256 value, uint256 age) internal returns (bytes32 n) {
        bytes16 key = bytes16(nextKey++);
        bytes32 req = keccak256(abi.encode(key));
        n = fairbind.deriveNonce(sellerId, PROFILE, CLAIMS, buyer, key, req);
        uint256 after_ = _ts() - age;
        uint256 before_ = _ts() + 1000;
        FairBindCore.TransferAuthorization memory auth =
            FairBindCore.TransferAuthorization(buyer, address(fairbind), value, after_, before_, n);
        bytes memory sig = _sig(BUYER_KEY, token.receiveAuthorizationDigest(buyer, address(fairbind), value, after_, before_, n));
        fairbind.settle(sellerId, PROFILE, CLAIMS, key, req, auth, sig);
    }

    function _buy() internal returns (bytes32) {
        return _buy(10_000, 5);
    }

    // ---------------------------------------------------------- bundles

    function _pad(bytes memory r) internal view returns (bytes memory out) {
        out = new bytes(padLen);
        for (uint256 i; i < r.length; i++) out[i] = r[i];
        out[r.length] = 0x80;
    }

    function _keystream(bytes32 ek, bytes32 n, bytes memory pt) internal pure returns (bytes memory ct) {
        ct = new bytes(pt.length);
        for (uint256 i; i < pt.length; i++) {
            bytes32 block_ = keccak256(abi.encode(ek, n, i / 32));
            ct[i] = pt[i] ^ block_[i % 32];
        }
    }

    /// The bundle of purchase n for response r, with key ek and plaintext
    /// psi || padded (padded = pad(r) unless given).
    function _bundleWith(bytes32 n, bytes32 ek, bytes memory padded, bytes32 commitment) internal view returns (Bundle memory b) {
        bytes memory pt = abi.encodePacked(keccak256(abi.encode("psi", n)), padded);
        b.ek = ek;
        b.ct = _keystream(ek, n, pt);
        b.ctHash = keccak256(b.ct);
        b.ekHash = keccak256(abi.encode(ek));
        b.rHash = keccak256(abi.encodePacked(TAG, pt));
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        b.leaf = fairbind.receiptDigest(
            FairBindCore.FairBindReceipt(1, p.sellerId, p.profileId, n, p.requestHash, b.rHash, CLAIMS, commitment, p.epoch, 1)
        );
    }

    function _commitmentOf(bytes32 n) internal view returns (bytes32) {
        return mode == ExchangeStore.MODE_PROOF ? fx.proofCommitment(n) : keccak256("commitment");
    }

    function _bundle(bytes32 n) internal returns (Bundle memory b) {
        b = _bundleWith(n, keccak256(abi.encode("ek", n)), _pad(RESPONSE), _commitmentOf(n));
        leafOf[n] = b.leaf;
        bundleOf[n] = b;
    }

    function _post(bytes32 n, Bundle memory b, uint256 buyerKey) internal view returns (ExchangeStore.Post memory q) {
        q = ExchangeStore.Post(n, b.ctHash, b.ekHash, b.rHash, b.leaf, "");
        q.buyerSig = _sigView(buyerKey, fx.receiptSignatureDigest(n, b.ctHash, b.ekHash, b.rHash, b.leaf));
    }

    /// Posts the receipt signature of n (seller signs the posting).
    function _postSigned(bytes32 n) internal {
        Bundle memory b = bundleOf[n].leaf == 0 ? _bundle(n) : bundleOf[n];
        ExchangeStore.Post memory q = _post(n, b, BUYER_KEY);
        fx.postReceipt(q, _sig(SELLER_KEY, fx.postDigest(q)));
    }

    function _sigView(uint256 key, bytes32 digest) internal view returns (bytes memory) {
        (uint8 v, bytes32 r, bytes32 s) = ExchangeSignVm(address(xv)).sign(key, digest);
        return abi.encodePacked(r, s, v);
    }

    // ---------------------------------------------------- anchor and tree

    /// Builds the ordered tree over ns with leafOf (a filler leaf for a nonce without one).
    function _xTree(bytes32[] memory ns) internal {
        uint256 n = ns.length;
        bytes32[] memory s = new bytes32[](n);
        for (uint256 i; i < n; i++) s[i] = ns[i];
        for (uint256 i = 1; i < n; i++) {
            bytes32 x = s[i];
            uint256 j = i;
            while (j > 0 && uint256(s[j - 1]) > uint256(x)) {
                s[j] = s[j - 1];
                j--;
            }
            s[j] = x;
        }
        delete xs;
        delete xLevels;
        bytes32[] memory level = new bytes32[](n);
        for (uint256 i; i < n; i++) {
            xs.push(s[i]);
            xIndex[s[i]] = uint32(i);
            bytes32 leaf = leafOf[s[i]] == 0 ? keccak256(abi.encode("filler", s[i])) : leafOf[s[i]];
            level[i] = keccak256(abi.encode(LEAF_DOMAIN, s[i], leaf));
        }
        xLevels.push(level);
        while (level.length > 1) {
            uint256 w = (level.length + 1) / 2;
            bytes32[] memory up = new bytes32[](w);
            for (uint256 i; i < w; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < level.length ? level[2 * i + 1] : left;
                up[i] = keccak256(abi.encode(NODE_DOMAIN, left, right));
            }
            xLevels.push(up);
            level = up;
        }
    }

    function _xEntries() internal view returns (FairBindMerkle.ReceiptEntry[] memory list) {
        list = new FairBindMerkle.ReceiptEntry[](xs.length);
        for (uint256 i; i < xs.length; i++) {
            bytes32 leaf = leafOf[xs[i]] == 0 ? keccak256(abi.encode("filler", xs[i])) : leafOf[xs[i]];
            list[i] = FairBindMerkle.ReceiptEntry(xs[i], leaf);
        }
    }

    function _xPath(bytes32 n) internal view returns (uint32 index, bytes32[] memory siblings) {
        index = xIndex[n];
        uint256 height = xLevels.length - 1;
        siblings = new bytes32[](height);
        uint256 cursor = index;
        for (uint256 h; h < height; h++) {
            bytes32[] storage lvl = xLevels[h];
            uint256 other = cursor ^ 1;
            siblings[h] = other < lvl.length ? lvl[other] : lvl[cursor];
            cursor >>= 1;
        }
    }

    /// Anchors epoch e of the seller with purchases ns (rolls to the window).
    function _anchorX(uint24 e, bytes32[] memory ns) internal {
        _xTree(ns);
        uint256 base = 300 * (uint256(e) + 2);
        if (_now() < base) hv.roll(base);
        FairBindMerkle.ReceiptEntry[] memory list = _xEntries();
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, e, list, uint32(ns.length), keccak256("publication"));
    }

    function _matchOf(bytes32 n) internal view returns (ExchangeStore.Match memory m) {
        Bundle storage b = bundleOf[n];
        (uint32 index, bytes32[] memory siblings) = _xPath(n);
        m = ExchangeStore.Match(n, b.ctHash, b.ekHash, b.rHash, b.leaf, 0, index, siblings);
    }

    function _matchAll(bytes32[] memory ns) internal {
        ExchangeStore.Match[] memory ms = new ExchangeStore.Match[](ns.length);
        for (uint256 i; i < ns.length; i++) ms[i] = _matchOf(ns[i]);
        fx.matchAnchor(ms);
    }

    function _one(bytes32 n) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](1);
        ns[0] = n;
    }

    function _two(bytes32 a, bytes32 b) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](2);
        ns[0] = a;
        ns[1] = b;
    }

    /// Seals epoch e on the block hash path (every purchase is sampled under
    /// the base profile).
    function _sealX(uint24 e) internal {
        uint64 rb = fairbind.getAnchor(sellerId, e).randomBlock;
        if (_now() <= rb) hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("beacon", e)));
        fairbind.seal(sellerId, e);
    }

    /// Posts, anchors, matches and seals epoch 0 with purchases ns (all posted).
    function _bindAndSeal(bytes32[] memory ns) internal {
        for (uint256 i; i < ns.length; i++) _postSigned(ns[i]);
        _anchorX(0, ns);
        _matchAll(ns);
        _sealX(0);
    }

    // ------------------------------------------------------------ proofs

    function _update(uint64 publishTime, uint64 prev, int64 price) internal view returns (bytes memory) {
        bytes32 d = feed.updateDigest(FEED, price, 1_000, -8, publishTime, prev);
        return abi.encode(FEED, price, uint64(1_000), int32(-8), publishTime, prev, _sigView(GUARDIAN_KEY, d));
    }

    /// The canonical update of n: published 2 s after its reference time.
    function _canonical(bytes32 n) internal view returns (bytes memory) {
        (, ExchangeStore.Record memory r,) = fx.getExchangeRecord(n);
        return _update(r.refTime + 2, r.refTime - 1, PRICE);
    }

    function _passProof(bytes32 n) internal view returns (ExchangeStore.PassProof memory q) {
        Bundle storage b = bundleOf[n];
        q = ExchangeStore.PassProof(b.ek, b.ct, 1, _canonical(n), "", "");
    }

    function _prove(bytes32 n, uint8 flags) internal {
        ExchangeStore.PassProof memory q = _passProof(n);
        fx.prove(n, flags, q);
    }

    function proveExternal(bytes32 n, uint8 flags, ExchangeStore.PassProof memory q) external {
        fx.prove(n, flags, q);
    }

    function _state(bytes32 n) internal view returns (uint8) {
        return fairbind.getCase(n).state;
    }

    function _fs(bytes32 n) internal view returns (uint8) {
        return fairbind.getPurchase(n).financialState;
    }

    function _record(bytes32 n) internal view returns (ExchangeStore.Record memory r) {
        (, r,) = fx.getExchangeRecord(n);
    }

    function _bound(bytes32 n) internal view returns (bool) {
        (bytes32 h,,) = fx.getExchangeRecord(n);
        return uint256(h) & 1 == 1;
    }
}

interface ExchangeSignVm {
    function sign(uint256 key, bytes32 digest) external view returns (uint8, bytes32, bytes32);
}
