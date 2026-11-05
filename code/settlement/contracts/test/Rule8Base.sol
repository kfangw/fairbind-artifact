// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { Rule8Store } from "../src/modules/Rule8Store.sol";
import { ExchangeBase } from "./ExchangeBase.sol";
// Keeps the module artifact built when a filter selects only some tests.
import { FairBindRule8 } from "../src/modules/FairBindRule8.sol";
import { FairBindRule8Release } from "../src/modules/FairBindRule8Release.sol";

/// The calls of the rule edition 8 module through the router.
interface IRule8 {
    function setRule8Terms(uint32 profileId, Rule8Store.Input calldata x) external;
    function rule8TermsHash(uint32 profileId, Rule8Store.Input calldata x) external view returns (bytes32);
    function sealProfile(uint32 profileId, uint24 epoch) external;
    function timeoutSealProfile(uint32 profileId, uint24 epoch) external;
    function closeProfileEpochs(uint32 profileId, uint24 steps) external;
    function getRule8Terms(uint32 profileId) external view returns (Rule8Store.Terms memory);
    function getProfileEpoch(uint32 profileId, uint24 epoch)
        external
        view
        returns (Rule8Store.ProfileEpoch memory, uint32);
    function getClosedBelow(uint32 profileId) external view returns (uint24);
    function rule8MinWindow(uint32 profileId) external view returns (uint256);
    function anchorSigned(
        Rule8Store.AnchorContent calldata c,
        FairBindMerkle.ReceiptEntry[] calldata entries,
        bytes calldata sellerSig
    ) external;
    function proveAnchorEquivocation(
        Rule8Store.AnchorContent calldata a,
        bytes calldata sigA,
        Rule8Store.AnchorContent calldata b,
        bytes calldata sigB
    ) external;
    function anchorDigest(Rule8Store.AnchorContent calldata c) external view returns (bytes32);
    function fundPool(uint32 profileId, uint256 amount) external;
    function payOwedFees(uint32 profileId, uint256 max) external;
    function getFeePool(uint32 profileId) external view returns (uint256 pool, uint256 owedCount, uint256 owedHead);
    function anchorBulk(
        Rule8Store.AnchorContent calldata c,
        Rule8Store.BulkEntry[] calldata entries,
        bytes calldata sellerSig
    ) external;
    function proveBinding(
        bytes32 nonce,
        Rule8Store.BulkEntry calldata en,
        bytes32 rE,
        bytes32 rB,
        uint32 position,
        bytes32[] calldata lambdaPath,
        bytes32[] calldata betaPath
    ) external;
    function releaseUnit(uint32 sellerId, uint24 epoch, uint32 unit, Rule8Store.UnitItem[] calldata items) external;
    function passEpoch(uint32 sellerId) external;
    function releaseSeparate(bytes32 nonce) external;
    function getHeld(uint32 sellerId) external view returns (uint32 held, uint64 episodeFloor);
    function noteCaseEnded(bytes32 nonce) external;
    function getOpenOtherCases(uint32 profileId, uint24 epoch) external view returns (uint32);
    function getSellerEpoch(uint32 sellerId, uint24 epoch)
        external
        view
        returns (Rule8Store.SellerEpoch memory se, uint24 cursor, bytes32 acc0);
}

/// Deployment of a receipt-signature vote profile under rule edition 8: the
/// production modules, the seven extension modules of ExchangeBase and the
/// two rule 8 modules as the eighth and ninth. Epoch e runs over blocks [1 + 300e, 300 + 300e],
/// its anchor deadline A_e is 700 + 300e and its value block 1469 + 300e.
abstract contract Rule8Base is ExchangeBase {
    IRule8 internal r8;
    /// Whether the deployment sets rule 8 terms (false: the edition 7 profile
    /// with the module installed).
    bool internal r8Off;

    function _r8Input() internal view virtual returns (Rule8Store.Input memory x) {
        x.unitLog2 = 1;
        x.heldWindow = 40_000;
        x.winBlocks = 31_073;
        x.buyerWindow = 1_800;
        x.callFees = new uint96[](Rule8Store.FEE_KINDS);
    }

    function _afterProfile() internal override {
        r8 = IRule8(address(fairbind));
        if (r8Off) return;
        Rule8Store.Input memory x = _r8Input();
        x.termsHash = r8.rule8TermsHash(PROFILE, x);
        r8.setRule8Terms(PROFILE, x);
    }

    /// Deploys exchange mode `m` with sampling rate `ppm` (every purchase is
    /// sampled at 1,000,000).
    function _deployR8Profile(uint8 m, FairBindCore.ServiceProfileInput memory p) internal {
        rule8Artifact = "FairBindRule8.sol:FairBindRule8";
        mode = m;
        _deployWith(p);
        hv.roll(10);
    }

    function buyExternal() external {
        _buy();
    }

    function _deployR8Mode(uint8 m, uint32 ppm) internal {
        rule8Artifact = "FairBindRule8.sol:FairBindRule8";
        mode = m;
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.samplePpm = ppm;
        p.effectivePpm = ppm;
        _deployWith(p);
        hv.roll(10);
    }

    /// The release unit items of ns in the given (settlement) order.
    function _items(bytes32[] memory ns) internal view returns (Rule8Store.UnitItem[] memory list) {
        list = new Rule8Store.UnitItem[](ns.length);
        for (uint256 i; i < ns.length; i++) {
            FairBindCore.PurchaseView memory p = fairbind.getPurchase(ns[i]);
            list[i] = Rule8Store.UnitItem(ns[i], p.buyer, p.value, fairbind.getServiceProfile(PROFILE).parameters.maxPurchaseValue);
        }
    }

    /// A beacon under which exactly the purchases of ns with their bit set in
    /// `mask` are sampled (the profile's flat rate).
    function _beaconSelecting(uint24 epoch, bytes32[] memory ns, uint256 mask) internal view returns (bytes32 h) {
        uint256 ppm = fairbind.getServiceProfile(PROFILE).parameters.samplePpm;
        uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
        for (uint256 salt;; salt++) {
            h = keccak256(abi.encode("beacon", epoch, salt));
            bool ok = true;
            for (uint256 i; i < ns.length && ok; i++) {
                uint256 v = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, ns[i])));
                ok = (v < threshold) == ((mask >> i) & 1 == 1);
            }
            if (ok) return h;
        }
    }

    /// Seals profile epoch e with the given beacon.
    function _sealProfileWith(uint24 e, bytes32 beacon) internal {
        uint256 rb = _valueBlockOf(e);
        if (_now() <= rb) hv.roll(rb + 1);
        hv.setBlockhash(rb, beacon);
        r8.sealProfile(PROFILE, e);
    }

    function releaseUnitExternal(uint24 e, uint32 unit, Rule8Store.UnitItem[] memory items) external {
        r8.releaseUnit(sellerId, e, unit, items);
    }

    function passExternal() external {
        r8.passEpoch(sellerId);
    }

    function releaseSeparateExternal(bytes32 n) external {
        r8.releaseSeparate(n);
    }

    bytes32 internal constant BIND_DOMAIN = keccak256("fairbind/rule8-bind/v1");

    /// The bulk anchor of epoch e: entries of ns sorted by nonce, with the
    /// signature of `keyOf[n]` (zero: none), the three roots, R^b_e, and the
    /// lambda and beta paths of every nonce.
    struct BulkAnchor {
        Rule8Store.BulkEntry[] entries;
        Rule8Store.AnchorContent content;
        bytes32 rB;
    }

    mapping(bytes32 => uint256) internal keyOf;
    mapping(bytes32 => bytes32[]) internal lambdaPathOf;
    mapping(bytes32 => bytes32[]) internal betaPathOf;
    mapping(bytes32 => uint32) internal positionOf;

    function _bulkEntry(bytes32 n) internal returns (Rule8Store.BulkEntry memory en) {
        Bundle memory b = bundleOf[n].leaf == 0 ? _bundle(n) : bundleOf[n];
        en = Rule8Store.BulkEntry(n, b.ctHash, b.ekHash, b.rHash, b.leaf, "");
        if (keyOf[n] != 0) {
            en.sig = _sigView(keyOf[n], fx.receiptSignatureDigest(n, b.ctHash, b.ekHash, b.rHash, b.leaf));
        }
    }

    function _h(Rule8Store.BulkEntry memory en) internal pure returns (bytes32) {
        return bytes32(uint256(keccak256(abi.encode(en.ctHash, en.ekHash, en.rHash, en.leaf))) & ~uint256(1));
    }

    function _rootOver(bytes32[] memory ns, bytes32[] memory leaves) internal returns (bytes32) {
        for (uint256 i; i < ns.length; i++) leafOf[ns[i]] = leaves[i];
        _xTree(ns);
        return xLevels[xLevels.length - 1][0];
    }

    /// Builds the bulk anchor of ns; bound[n] says whether n's signature holds.
    function _bulkAnchor(uint24 e, bytes32[] memory ns, bool[] memory bound) internal returns (BulkAnchor memory a) {
        uint256 n = ns.length;
        a.entries = new Rule8Store.BulkEntry[](n);
        bytes32[] memory l0 = new bytes32[](n);
        bytes32[] memory le = new bytes32[](n);
        bytes32[] memory lb = new bytes32[](n);
        bytes32[] memory l = new bytes32[](n);
        for (uint256 i; i < n; i++) {
            Rule8Store.BulkEntry memory en = _bulkEntry(ns[i]);
            bytes32 s = en.sig.length == 0 ? bytes32(0) : keccak256(en.sig);
            l[i] = en.leaf;
            l0[i] = keccak256(abi.encode(en.leaf, _h(en)));
            le[i] = keccak256(abi.encode(en.leaf, _h(en), s));
        }
        bytes32 root0 = _rootOver(ns, l0);
        bytes32 rE = _rootOver(ns, le);
        for (uint256 i; i < n; i++) {
            (uint32 idx, bytes32[] memory path) = _xPath(ns[i]);
            positionOf[ns[i]] = idx;
            lambdaPathOf[ns[i]] = path;
            lb[i] = keccak256(abi.encode(BIND_DOMAIN, uint256(idx), bound[i]));
        }
        a.rB = _rootOver(ns, lb);
        for (uint256 i; i < n; i++) {
            (, bytes32[] memory path) = _xPath(ns[i]);
            betaPathOf[ns[i]] = path;
        }
        _rootOver(ns, l);
        for (uint256 i; i < n; i++) a.entries[xIndex[ns[i]]] = _bulkEntry(ns[i]);
        a.content = Rule8Store.AnchorContent(
            sellerId, PROFILE, e, uint32(n), rE, root0, keccak256("publication"), 1, keccak256(abi.encode(rE, root0))
        );
    }

    function _proveBinding(bytes32 n, BulkAnchor memory a) internal {
        r8.proveBinding(n, _bulkEntry(n), a.content.root, a.rB, positionOf[n], lambdaPathOf[n], betaPathOf[n]);
    }

    function proveBindingExternal(bytes32 n, Rule8Store.BulkEntry memory en, bytes32 rE, bytes32 rB) external {
        r8.proveBinding(n, en, rE, rB, positionOf[n], lambdaPathOf[n], betaPathOf[n]);
    }

    function _deployR8() internal {
        rule8Artifact = "FairBindRule8.sol:FairBindRule8";
        mode = ExchangeStore.MODE_VOTE_SIG;
        _deployDefault();
        hv.roll(10);
    }

    function _anchorDeadlineOf(uint24 e) internal pure returns (uint256) {
        return 700 + 300 * uint256(e);
    }

    function _valueBlockOf(uint24 e) internal pure returns (uint256) {
        return 1469 + 300 * uint256(e);
    }

    /// Seals profile epoch e on the block hash path.
    function _sealProfile(uint24 e) internal {
        uint256 rb = _valueBlockOf(e);
        if (_now() <= rb) hv.roll(rb + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("beacon", e)));
        r8.sealProfile(PROFILE, e);
    }

    /// Posts and anchors epoch 0 with ns and matches the anchor (edition 7
    /// posting path; revision 6 adds the bulk check).
    function _postAnchorMatch(uint24 e, bytes32[] memory ns) internal {
        for (uint256 i; i < ns.length; i++) _postSigned(ns[i]);
        _anchorX(e, ns);
        _matchAll(ns);
    }

    /// The anchor content of epoch e over the tree of the last _xTree call.
    function _content(uint24 e, uint32 count) internal view returns (Rule8Store.AnchorContent memory c) {
        bytes32 root = xLevels[xLevels.length - 1][0];
        c = Rule8Store.AnchorContent(
            sellerId, PROFILE, e, count, root, root, keccak256("publication"), 1, keccak256(abi.encode(root, root))
        );
    }

    function _signContent(Rule8Store.AnchorContent memory c) internal returns (bytes memory) {
        return _sig(SELLER_KEY, r8.anchorDigest(c));
    }

    /// Anchors epoch e with ns through the signed path, submitted by `by`.
    function _anchorSignedBy(uint24 e, bytes32[] memory ns, address by) internal {
        _xTree(ns);
        uint256 base = 300 * (uint256(e) + 2);
        if (_now() < base) hv.roll(base);
        Rule8Store.AnchorContent memory c = _content(e, uint32(ns.length));
        bytes memory sig = _signContent(c);
        FairBindMerkle.ReceiptEntry[] memory list = _xEntries();
        hv.prank(by);
        r8.anchorSigned(c, list, sig);
    }

    function anchorSignedExternal(Rule8Store.AnchorContent memory c, FairBindMerkle.ReceiptEntry[] memory list, bytes memory sig)
        external
    {
        r8.anchorSigned(c, list, sig);
    }

    function equivocationExternal(
        Rule8Store.AnchorContent memory a,
        bytes memory sa,
        Rule8Store.AnchorContent memory b,
        bytes memory sb
    ) external {
        r8.proveAnchorEquivocation(a, sa, b, sb);
    }

    function sealExternal(uint24 e) external {
        fairbind.seal(sellerId, e);
    }

    function sealProfileExternal(uint24 e) external {
        r8.sealProfile(PROFILE, e);
    }

    function timeoutSealProfileExternal(uint24 e) external {
        r8.timeoutSealProfile(PROFILE, e);
    }

    function closeExternal(uint24 steps) external {
        r8.closeProfileEpochs(PROFILE, steps);
    }

    function finalizeVerifierExitExternal(uint32 id) external {
        fairbind.finalizeVerifierExit(id);
    }

    function setTermsExternal(Rule8Store.Input memory x) external {
        r8.setRule8Terms(PROFILE, x);
    }
}
