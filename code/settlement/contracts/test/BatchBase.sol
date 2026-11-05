// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { ModuleSwapBase } from "./ModuleSwapBase.sol";
import { MockVrfVerifier } from "./MockVrfVerifier.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";
import { FairBindBatch } from "../src/modules/FairBindBatch.sol";
import { FairBindBatchAdmin } from "../src/modules/FairBindBatchAdmin.sol";
import { FairBindProof } from "../src/modules/FairBindProof.sol";
import { FairBindDeposit } from "../src/modules/FairBindDeposit.sol";
import { IBatchedFairBind } from "./BatchInterfaces.sol";

/// Deployment and driving helpers for batched profiles (ADR 0032 to ADR
/// 0035). The source is FairBindVrf with D_V = 10 and T_V = 20 behind the
/// test proof check. Epoch e of the base profile has its anchor window from
/// 300(e + 2), anchor deadline A_e = 300(e + 2) + 100, value block A_e + 12,
/// seal deadline A_e + 212 and batch close C_e = A_e + 412 (C_0 = 1112).
abstract contract BatchBase is ModuleSwapBase {
    uint32 internal constant D_V = 10;
    uint32 internal constant T_V = 20;
    uint256 internal constant VRF_KEY = 0x5EED;
    address internal constant KEEPER = address(0x4EE9E2);
    address internal constant SELLER_B_OWNER = address(0x5E11E8);
    uint8 internal constant VRF_SAMPLE = 1;
    uint8 internal constant VRF_ASSIGN = 2;
    uint8 internal constant VRF_AUX = 3;
    uint256 internal constant G = 10_000;

    IBatchedFairBind internal fb;
    MockVrfVerifier internal vrfVerifier;
    FairBindVrf internal vrf;
    string internal batchArtifact = "FairBindBatch.sol:FairBindBatch";
    string internal adminArtifact = "FairBindBatchAdmin.sol:FairBindBatchAdmin";
    string internal proofArtifact = "FairBindProof.sol:FairBindProof";
    string internal depositArtifact = "FairBindDeposit.sol:FairBindDeposit";
    string internal settlementArtifact = "FairBindSettlement.sol:FairBindSettlement";
    string internal judgmentArtifact = "FairBindJudgment.sol:FairBindJudgment";
    uint32 internal sellerB;
    mapping(bytes32 => bytes32[]) internal treeOf;

    // ---------------------------------------------------------- terms

    function _batchProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
    }

    function _defaultTerms() internal pure returns (BatchStore.Terms memory t) {
        t.batched = true;
        t.assignDelay = 20;
        t.keeperSlack = 10;
        t.slotValue = 10_000;
    }

    function _batchTermsHash(uint32 id, BatchStore.Terms memory t, address source) internal view returns (bytes32) {
        return keccak256(
            abi.encode(
                keccak256("fairbind/batch-terms/v1"), id, t.assignDelay, t.keeperSlack, t.depositPpm, t.auditPpm,
                t.contestBlocks, t.sideGainPpm, t.slotValue, source, keccak256(FairBindVrf(source).publicKey()),
                uint256(FairBindVrf(source).responseBlocks()), uint256(FairBindVrf(source).deadlineSlackBlocks())
            )
        );
    }

    // ------------------------------------------------------ deployment

    function _equalBonds() internal pure returns (uint128[] memory bonds) {
        bonds = new uint128[](14);
        for (uint256 i; i < 14; i++) bonds[i] = 10_000_000;
    }

    /// Verifier 1 with a large bond (weight 100 USDC, the cap), the other
    /// thirteen at the minimum: most tickets name verifier 1.
    function _heavyFirstBonds() internal pure returns (uint128[] memory bonds) {
        bonds = new uint128[](14);
        bonds[0] = 100_000_000;
        for (uint256 i = 1; i < 14; i++) bonds[i] = 1_000_000;
    }

    /// Deploys the production modules (or `names`), the two extension modules,
    /// the request-based source at block 5, one profile with the given batch
    /// terms, verifiers with the given bonds, and one seller.
    function _deployBatchedWith(
        string[10] memory names,
        FairBindCore.ServiceProfileInput memory p,
        BatchStore.Terms memory t,
        uint128[] memory verifierBonds
    ) internal {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        bytes memory args = abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        address[10] memory modules;
        for (uint256 i; i < 10; i++) modules[i] = swapArtifacts.deployCode(names[i], args);
        fairbind = FairBind(
            swapArtifacts.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL, modules)
            )
        );
        fb = IBatchedFairBind(address(fairbind));
        fb.setExtensions(_extensions(args));
        vrfVerifier = new MockVrfVerifier();
        vrf = new FairBindVrf(address(fairbind), vrfVerifier, abi.encode(hv.addr(VRF_KEY)), D_V, T_V);
        hv.roll(5);
        fairbind.setRandomness(address(vrf));
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        fairbind.createServiceProfile(PROFILE, p);
        token.mint(address(this), 10_000_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= verifierBonds.length; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), verifierBonds[i - 1]);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        if (t.batched) {
            t.termsHash = _batchTermsHash(PROFILE, t, address(vrf));
            fb.setBatchTerms(PROFILE, t);
        }
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
    }

    /// The four extension modules in kind order.
    function _extensions(bytes memory args) internal returns (address[] memory exts) {
        exts = new address[](4);
        exts[0] = swapArtifacts.deployCode(batchArtifact, args);
        exts[1] = swapArtifacts.deployCode(adminArtifact, args);
        exts[2] = swapArtifacts.deployCode(proofArtifact, args);
        exts[3] = swapArtifacts.deployCode(depositArtifact, args);
    }

    function _deployBatched(FairBindCore.ServiceProfileInput memory p, BatchStore.Terms memory t, uint128[] memory bonds)
        internal
    {
        string[10] memory names = _productionModules();
        names[1] = settlementArtifact;
        names[6] = judgmentArtifact;
        _deployBatchedWith(names, p, t, bonds);
    }

    /// A second bond account and seller with the same signing key and claims.
    function _addSellerB() internal returns (uint32 id) {
        uint256 penalty = fairbind.getServiceProfile(PROFILE).parameters.sellerPenalty;
        token.mint(SELLER_B_OWNER, 1_000_000_000_000);
        hv.startPrank(SELLER_B_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        id = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(penalty));
        hv.stopPrank();
        sellerB = id;
    }

    /// A purchase of seller `s`.
    function _purchaseOf(uint32 s, uint256 value) internal returns (bytes32 n) {
        uint32 keep = sellerId;
        sellerId = s;
        n = _purchase(value);
        sellerId = keep;
    }

    // --------------------------------------------------- epoch geometry

    function _anchorBase(uint24 e) internal pure returns (uint256) {
        return 300 * (uint256(e) + 2);
    }

    function _a(uint24 e) internal pure returns (uint64) {
        return uint64(300 * (uint256(e) + 2) + 100);
    }

    function _c(uint24 e) internal pure returns (uint256) {
        return uint256(_a(e)) + 412;
    }

    // ---------------------------------------------------------- source

    function _sampleId(uint24 e) internal pure returns (bytes32) {
        return keccak256(abi.encode(VRF_SAMPLE, abi.encode(uint32(PROFILE), _a(e))));
    }

    function _assignId(uint24 e) internal pure returns (bytes32) {
        return keccak256(abi.encode(VRF_ASSIGN, abi.encode(uint32(PROFILE), e)));
    }

    function _lateId(bytes32 n, uint64 t) internal pure returns (bytes32) {
        return keccak256(abi.encode(VRF_AUX, abi.encode(keccak256("FairBind/late/v1"), n, uint8(1), uint32(0), t)));
    }

    function _auditId(bytes32 n, uint64 t) internal pure returns (bytes32) {
        return keccak256(abi.encode(VRF_AUX, abi.encode(keccak256("FairBind/audit/v1"), n, uint8(0), uint32(1), t)));
    }

    function _fulfill(bytes32 id) internal returns (bytes32 output) {
        bytes memory proof = _sig(VRF_KEY, keccak256(vrf.storedAlpha(id)));
        output = keccak256(abi.encode(vrfVerifier.OUTPUT_DOMAIN(), proof));
        hv.prank(KEEPER);
        vrf.fulfill(id, output, proof);
    }

    // ---------------------------------------------------------- driving

    /// Anchors epoch e of seller s with its purchases ns (rolls to the window).
    function _anchorOf(uint24 e, uint32 s, address owner, bytes32[] memory ns) internal {
        _buildTree(ns);
        bytes32 tag = keccak256(abi.encode(s, e));
        delete treeOf[tag];
        for (uint256 i; i < ns.length; i++) treeOf[tag].push(ns[i]);
        if (_now() < _anchorBase(e)) hv.roll(_anchorBase(e));
        hv.prank(owner);
        fairbind.anchor(s, e, _treeEntries(), uint32(ns.length), keccak256("publication"));
    }

    /// The checkpoint of A_e, the SAMPLE value and the seal of epoch e for
    /// the given sellers.
    function _sealOf(uint24 e, uint32[] memory ss) internal returns (bytes32 value) {
        if (_now() <= _a(e)) hv.roll(uint256(_a(e)) + 1);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, e);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, e);
        value = _fulfill(_sampleId(e));
        if (_now() <= uint256(_a(e)) + 12) hv.roll(uint256(_a(e)) + 13);
        for (uint256 i; i < ss.length; i++) {
            hv.prank(KEEPER);
            fairbind.seal(ss[i], e);
        }
    }

    function _sellers1() internal view returns (uint32[] memory ss) {
        ss = new uint32[](1);
        ss[0] = sellerId;
    }

    function _sellers2() internal view returns (uint32[] memory ss) {
        ss = new uint32[](2);
        ss[0] = sellerId;
        ss[1] = sellerB;
    }

    /// Opens the sample case of n and puts its receipt and inclusion proof on
    /// chain, as the seller must within serveBlocks of the opening.
    function _openSample(bytes32 n) internal {
        hv.prank(KEEPER);
        fairbind.openSample(n);
        _submitReceipt(n);
    }

    function _submitReceipt(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        _buildTree(treeOf[keccak256(abi.encode(p.sellerId, p.epoch))]);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory pf = _proof(n);
        fairbind.submitSampleReceipt(n, r, sig, pf);
    }

    /// Opens the sample case of every sampled purchase in ns.
    function _openAll(bytes32[] memory ns) internal {
        for (uint256 i; i < ns.length; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            if (eligible) _openSample(ns[i]);
        }
    }

    /// After C_e: asks for, delivers and assigns the batch value of epoch e.
    function _assignBatch(uint24 e) internal returns (bytes32 value) {
        if (_now() <= _c(e)) hv.roll(_c(e) + 1);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, e);
        value = _fulfill(_assignId(e));
        hv.prank(KEEPER);
        fb.assignBatch(PROFILE, e);
    }

    /// Judges the started case n with the receipt tree of its seller's epoch.
    function _judgeBatched(bytes32 n, uint8 verdict) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        _buildTree(treeOf[keccak256(abi.encode(p.sellerId, p.epoch))]);
        _judge(n, verdict);
    }

    /// The AUX request id of the current review stage of n (ADR 0036).
    function _reviewId(bytes32 n) internal view returns (bytes32) {
        BatchStore.ReviewUse memory u = fb.getReviewUse(n);
        return keccak256(
            abi.encode(VRF_AUX, abi.encode(keccak256("FairBind/review/v1"), n, u.stage, uint32(0), u.registered))
        );
    }

    /// Asks for, delivers and uses the AUX value of the current review stage of n.
    function _reviewValueOf(bytes32 n) internal returns (bytes32 value) {
        uint64 t = fb.getReviewUse(n).registered;
        if (_now() <= t) hv.roll(uint256(t) + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        value = _fulfill(_reviewId(n));
        hv.prank(KEEPER);
        fb.assignReview(n);
    }

    /// The candidate of the first round, from `round` on, whose verifier has
    /// not taken part in the case: a copy of the contract's search when no
    /// verifier left by its own action.
    function _firstFree(uint64 version, bytes32 value, bytes32 caseId, uint8 stage, uint8 attempt, uint32[] memory taken)
        internal
        view
        returns (uint32 u)
    {
        for (uint32 round; round < 14; round++) {
            u = _candidate(version, value, caseId, stage, attempt, round);
            bool used;
            for (uint256 i; i < taken.length; i++) {
                if (taken[i] == u) used = true;
            }
            if (!used) return u;
        }
        return 0;
    }

    function _state(bytes32 n) internal view returns (uint8) {
        return fairbind.getCase(n).state;
    }

    function _bondOfSeller(uint32 s) internal view returns (uint32) {
        return fairbind.getSeller(s).bondId;
    }

    // ---------------------------------------------------- order key copy

    /// The order key of a first-stage case: batch, rank, account
    /// permutation, first ticket (ADR 0032).
    function _keyCopy(uint24 e, uint32 rank, bytes32 value, uint32 bondId, bytes32 caseId, uint8 stage)
        internal
        pure
        returns (uint256)
    {
        uint256 perm = uint64(uint256(keccak256(abi.encode(keccak256("fairbind/batch-permutation/v1"), value, bondId))));
        uint256 t0 = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, caseId, stage, uint8(0), uint32(0))));
        return (uint256(e) << 232) | (uint256(rank) << 200) | (perm << 136) | (t0 >> 120);
    }

    /// The candidate of round `round` of (value, case, stage, attempt) on the
    /// checkpoint `version`.
    function _candidate(uint64 version, bytes32 value, bytes32 caseId, uint8 stage, uint8 attempt, uint32 round)
        internal
        view
        returns (uint32)
    {
        (, uint32[] memory ids, uint96[] memory weights, uint256 total,) = fairbind.getVerifierCheckpoint(PROFILE, version);
        uint256 ticket = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, caseId, stage, attempt, round))) % total;
        uint256 cum;
        for (uint256 i; i < ids.length; i++) {
            cum += weights[i];
            if (ticket < cum) return ids[i];
        }
        return 0;
    }
}
