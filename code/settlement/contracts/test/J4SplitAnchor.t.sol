// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../src/FairBind.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import { SamplingStore } from "../src/modules/SamplingStore.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";
import { ArtifactVm } from "./DeployFairBind.sol";
import { FoldUnorderedSettlement } from "./J4FoldUnordered.sol";
import { FoldDropsPrefixSettlement } from "./J4FoldDropsPrefix.sol";
import { SingleUnitSplitSettlement } from "./J4SingleUnitSplit.sol";

interface J4Vm {
    function snapshotState() external returns (uint256);
    function revertToState(uint256 id) external returns (bool);
}

/// Cheaper split anchor (journal J4): (a) the units' publication hashes fold
/// into one accumulator instead of one slot per unit; (b) an epoch posted as a
/// single unit takes the one-transaction anchor path. Epoch 0 of the base
/// profile has its anchor window at blocks 600..700.
contract J4SplitAnchorTest is ReproBase {
    J4Vm internal constant jv = J4Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    ArtifactVm internal constant av = ArtifactVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant PUB = keccak256("publication");
    string internal constant REAL = "FairBindSettlement.sol:FairBindSettlement";
    string internal constant UNORDERED = "J4FoldUnordered.sol:FoldUnorderedSettlement";
    string internal constant DROPS_PREFIX = "J4FoldDropsPrefix.sol:FoldDropsPrefixSettlement";
    string internal constant SINGLE_SPLIT = "J4SingleUnitSplit.sol:SingleUnitSplitSettlement";

    // ------------------------------------------------------------- deployment

    /// ArtifactDeploy.deploy with the settlement module taken from `settlement`.
    function _deployRouter(string memory settlement) internal returns (FairBind) {
        bytes memory args = abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        string[10] memory names = [
            "FairBindRegistry.sol:FairBindRegistry",
            settlement,
            "FairBindSampling.sol:FairBindSampling",
            "FairBindDelivery.sol:FairBindDelivery",
            "FairBindPublication.sol:FairBindPublication",
            "FairBindRecovery.sol:FairBindRecovery",
            "FairBindJudgment.sol:FairBindJudgment",
            "FairBindReview.sol:FairBindReview",
            "FairBindBond.sol:FairBindBond",
            "FairBindLens.sol:FairBindLens"
        ];
        address[10] memory modules;
        for (uint256 i; i < 10; i++) modules[i] = av.deployCode(names[i], args);
        return FairBind(
            av.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL, modules)
            )
        );
    }

    /// ReproBase._deploy on the production profile with the given settlement module.
    function _deployWith(string memory settlement) internal {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        p.bucketCapacity = 200;
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        fairbind = _deployRouter(settlement);
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        fairbind.createServiceProfile(PROFILE, p);
        token.mint(address(this), 1_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), 10_000_000);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        fairbind.setServiceProfileActive(PROFILE, true);
        token.mint(SELLER_OWNER, p.sellerPenalty);
        hv.startPrank(SELLER_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        sellerId = registerSellerWithBond(fairbind, PROFILE, hv.addr(SELLER_KEY), CLAIMS, uint128(p.sellerPenalty));
        hv.stopPrank();
        buyer = hv.addr(BUYER_KEY);
        token.mint(buyer, 100_000_000);
        hv.prank(buyer);
        token.approve(address(fairbind), type(uint256).max);
    }

    function _setUpWith(string memory settlement, uint256 purchases)
        internal
        returns (bytes32[] memory ns, bytes32 wholeRoot)
    {
        _deployWith(settlement);
        hv.roll(10);
        ns = new bytes32[](purchases);
        for (uint256 i; i < purchases; i++) ns[i] = _purchase(10_000);
        wholeRoot = _buildTree(ns);
    }

    function _setUp(uint256 purchases) internal returns (bytes32[] memory ns, bytes32 wholeRoot) {
        return _setUpWith(REAL, purchases);
    }

    function _slice(uint256 from, uint256 to) internal view returns (FairBindMerkle.ReceiptEntry[] memory part) {
        FairBindMerkle.ReceiptEntry[] memory all = _treeEntries();
        part = new FairBindMerkle.ReceiptEntry[](to - from);
        for (uint256 i = from; i < to; i++) part[i - from] = all[i];
    }

    function _h(uint256 unit) internal pure returns (bytes32) {
        return keccak256(abi.encode(PUB, unit));
    }

    function _postUnit(uint32 unit, uint8 log2, uint256 from, uint256 to, bytes32 h) internal {
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, unit, log2, _slice(from, to), h);
    }

    function _fold(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(a, b));
    }

    function _anchor() internal view returns (FairBindCore.AnchorView memory) {
        return fairbind.getAnchor(sellerId, 0);
    }

    // ---------------------------------------------------- (a) accumulator

    /// Four units of four: the record's publication hash is the ordered fold of
    /// the four unit hashes, and getAnchorUnits returns [fold of the first three,
    /// last hash], whose packed hash is that publication hash.
    function test_accumulatorFoldsTheUnitsInOrder() public {
        (, bytes32 whole) = _setUp(16);
        hv.roll(650);
        for (uint32 u; u < 4; u++) {
            _postUnit(u, 2, 4 * u, 4 * u + 4, _h(u));
        }
        FairBindCore.AnchorView memory rec = _anchor();
        bytes32 acc2 = _fold(_fold(_h(0), _h(1)), _h(2));
        require(rec.state == uint8(FairBindCore.EpochState.ANCHORED), "anchored by the last unit");
        require(rec.root == whole, "root of the whole list");
        require(rec.publicationHash == _fold(acc2, _h(3)), "ordered fold of the four unit hashes");
        (uint8 log2, bytes32[] memory roots, bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(log2 == 2 && roots.length == 4, "units recorded");
        require(pubs.length == 2 && pubs[0] == acc2 && pubs[1] == _h(3), "accumulator and last hash");
        require(keccak256(abi.encodePacked(pubs)) == rec.publicationHash, "view reproduces the publication hash");
        for (uint256 u; u < 4; u++) require(roots[u] == levels[2][u], "sub-roots kept");
    }

    /// Three units, the last one short: the fold has the same form.
    function test_accumulatorWithAShortLastUnit() public {
        (, bytes32 whole) = _setUp(10);
        hv.roll(650);
        _postUnit(0, 2, 0, 4, _h(0));
        _postUnit(1, 2, 4, 8, _h(1));
        _postUnit(2, 2, 8, 10, _h(2));
        FairBindCore.AnchorView memory rec = _anchor();
        require(rec.root == whole, "root of the whole list");
        require(rec.publicationHash == _fold(_fold(_h(0), _h(1)), _h(2)), "fold of three");
        (, , bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(pubs.length == 2 && keccak256(abi.encodePacked(pubs)) == rec.publicationHash, "view");
    }

    /// While units are open the view shows the running fold only; the epoch is
    /// not anchored and no unit membership holds.
    function test_openUnitsShowTheRunningAccumulator() public {
        _setUp(16);
        hv.roll(650);
        _postUnit(0, 2, 0, 4, _h(0));
        (, , bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(pubs.length == 1 && pubs[0] == _h(0), "after unit 0");
        _postUnit(1, 2, 4, 8, _h(1));
        _postUnit(2, 2, 8, 12, _h(2));
        (, , pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(pubs.length == 1 && pubs[0] == _fold(_fold(_h(0), _h(1)), _h(2)), "after unit 2");
        require(_anchor().state == uint8(FairBindCore.EpochState.NONE), "not anchored");
        require(
            !fairbind.verifyUnitMember(sellerId, 0, 0, sortedNonces[0], sortedLeaves[0], 0, new bytes32[](2)),
            "no member while open"
        );
    }

    /// The nonce continuity between units still holds when the stored nonce
    /// shares its slot with the last hash, and a completed epoch takes no unit.
    function test_continuityAndCompletionWithTheSharedSlot() public {
        _setUp(12);
        hv.roll(650);
        _postUnit(0, 2, 0, 4, _h(0));
        _postUnit(1, 2, 4, 8, _h(1));
        // Unit 2 that starts inside unit 1 (entries 6..9 hold four, but 6 and 7 are posted).
        FairBindMerkle.ReceiptEntry[] memory overlap = _slice(6, 10);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 2, 2, overlap, _h(2));
        // A unit that repeats the last nonce of unit 1.
        FairBindMerkle.ReceiptEntry[] memory repeat = _slice(7, 11);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 2, 2, repeat, _h(2));
        _postUnit(2, 2, 8, 12, _h(2));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 3, 2, _slice(8, 12), _h(3));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 12, PUB);
    }

    /// Incomplete units at the deadline: a missed anchor; the slot that holds the
    /// last nonce is not shown as a hash and no membership holds.
    function test_incompleteUnitsKeepTheNonceOutOfTheView() public {
        _setUp(12);
        hv.roll(650);
        _postUnit(0, 2, 0, 4, _h(0));
        _postUnit(1, 2, 4, 8, _h(1));
        hv.roll(701);
        fairbind.timeoutAnchor(sellerId, 0);
        require(_anchor().state == uint8(FairBindCore.EpochState.EPOCH_FAILED), "missed anchor");
        (, bytes32[] memory roots, bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(roots.length == 2 && pubs.length == 1 && pubs[0] == _fold(_h(0), _h(1)), "running fold only");
        require(
            !fairbind.verifyUnitMember(sellerId, 0, 0, sortedNonces[0], sortedLeaves[0], 0, new bytes32[](2)),
            "no member of a missed anchor"
        );
    }

    /// The machinery after the anchor runs on a four-unit epoch: seal, open,
    /// receipt with a whole-list proof, and membership over (unit, leaf).
    function test_fourUnitsSealOpenAndProve() public {
        (bytes32[] memory ns, ) = _setUp(16);
        hv.roll(650);
        for (uint32 u; u < 4; u++) _postUnit(u, 2, 4 * u, 4 * u + 4, _h(u));
        for (uint256 i; i < ns.length; i++) {
            uint32 idx = treeIndex[ns[i]];
            FairBindCore.ReceiptProof memory whole = _proof(ns[i]);
            bytes32[] memory sib = new bytes32[](2);
            sib[0] = whole.siblings[0];
            sib[1] = whole.siblings[1];
            require(fairbind.verifyUnitMember(sellerId, 0, idx / 4, ns[i], sortedLeaves[idx], idx % 4, sib), "member");
            require(
                !fairbind.verifyUnitMember(sellerId, 0, (idx / 4 + 1) % 4, ns[i], sortedLeaves[idx], idx % 4, sib),
                "other unit"
            );
        }
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        fairbind.openSample(ns[5]);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[5]);
        fairbind.submitSampleReceipt(ns[5], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[5]));
    }

    // ------------------------------------------------ (b) one unit, old path

    /// A single unit is recorded field for field as the one-transaction anchor
    /// of the same list and publication hash, with no unit record.
    function test_singleUnitIsRecordedAsTheOneTransactionAnchor() public {
        (, bytes32 whole) = _setUp(5);
        hv.roll(650);
        uint256 snap = jv.snapshotState();
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 5, PUB);
        FairBindCore.AnchorView memory legacy = _anchor();
        jv.revertToState(snap);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _treeEntries(), PUB);
        FairBindCore.AnchorView memory single = _anchor();
        require(keccak256(abi.encode(single)) == keccak256(abi.encode(legacy)), "same anchor record");
        require(single.root == whole && single.publicationHash == PUB && single.count == 5, "root, hash, count");
        (uint8 log2, bytes32[] memory roots, bytes32[] memory pubs) = fairbind.getAnchorUnits(sellerId, 0);
        require(log2 == 0 && roots.length == 0 && pubs.length == 0, "no unit record");
    }

    /// A unit exactly as large as the epoch is the single-unit case too.
    function test_exactlyFullSingleUnitTakesTheOldPath() public {
        (, bytes32 whole) = _setUp(4);
        hv.roll(650);
        _postUnit(0, 2, 0, 4, PUB);
        require(_anchor().root == whole && _anchor().publicationHash == PUB, "anchored by one unit");
        (, bytes32[] memory roots, ) = fairbind.getAnchorUnits(sellerId, 0);
        require(roots.length == 0, "no unit record");
    }

    /// The checks of the single-unit path: cap, count, order, caller; and no
    /// second anchor of either kind afterwards.
    function test_singleUnitChecks() public {
        _setUp(5);
        hv.roll(650);
        hv.expectRevert(SamplingStore.UnitTooLarge.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 14, _treeEntries(), PUB);
        hv.expectRevert(FairBindCore.CountMismatch.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _slice(0, 4), PUB);
        FairBindMerkle.ReceiptEntry[] memory swapped = _treeEntries();
        (swapped[1], swapped[2]) = (swapped[2], swapped[1]);
        hv.expectRevert(FairBindCore.EntriesNotAscending.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, swapped, PUB);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _treeEntries(), bytes32(0));
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _treeEntries(), PUB);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _treeEntries(), PUB);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchorUnit(sellerId, 0, 0, 13, _treeEntries(), PUB);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 5, PUB);
    }

    /// Membership of a single-unit epoch: unit 0 against the anchor root with
    /// the whole-list proof; another unit or leaf fails. The same holds for an
    /// epoch anchored in one transaction.
    function test_singleUnitMembershipAndCaseFlow() public {
        (bytes32[] memory ns, ) = _setUp(5);
        hv.roll(650);
        uint256 snap = jv.snapshotState();
        for (uint256 k; k < 2; k++) {
            hv.prank(SELLER_OWNER);
            if (k == 0) fairbind.anchorUnit(sellerId, 0, 0, 3, _treeEntries(), PUB);
            else fairbind.anchor(sellerId, 0, _treeEntries(), 5, PUB);
            for (uint256 i; i < ns.length; i++) {
                FairBindCore.ReceiptProof memory pr = _proof(ns[i]);
                bytes32 leaf = sortedLeaves[pr.index];
                require(fairbind.verifyUnitMember(sellerId, 0, 0, ns[i], leaf, pr.index, pr.siblings), "member");
                require(!fairbind.verifyUnitMember(sellerId, 0, 1, ns[i], leaf, pr.index, pr.siblings), "unit 1");
                require(
                    !fairbind.verifyUnitMember(sellerId, 0, 0, ns[i], keccak256("x"), pr.index, pr.siblings), "leaf"
                );
            }
            if (k == 0) {
                hv.roll(BEACON_BLOCK + 1);
                hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
                fairbind.seal(sellerId, 0);
                fairbind.openSample(ns[2]);
                FairBindCore.FairBindReceipt memory r = _receipt(ns[2]);
                fairbind.submitSampleReceipt(ns[2], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[2]));
                jv.revertToState(snap);
            }
        }
    }

    /// An epoch that was never anchored has no unit-0 membership.
    function test_noMembershipWithoutAnAnchor() public {
        _setUp(3);
        require(
            !fairbind.verifyUnitMember(sellerId, 0, 0, sortedNonces[0], sortedLeaves[0], 0, new bytes32[](2)),
            "nothing anchored"
        );
        hv.roll(701);
        fairbind.timeoutAnchor(sellerId, 0);
        require(
            !fairbind.verifyUnitMember(sellerId, 0, 0, sortedNonces[0], sortedLeaves[0], 0, new bytes32[](2)),
            "missed anchor"
        );
    }

    // --------------------------------------------------------- mutations

    /// The publication hash of four units of four with hashes h under `settlement`.
    function _publicationOf(string memory settlement, bytes32[4] memory h) internal returns (bytes32 pub) {
        uint256 snap = jv.snapshotState();
        _setUpWith(settlement, 16);
        hv.roll(650);
        for (uint32 u; u < 4; u++) _postUnit(u, 2, 4 * u, 4 * u + 4, h[u]);
        pub = _anchor().publicationHash;
        jv.revertToState(snap);
    }

    /// The fold property: the ordered fold of every unit hash; swapping two
    /// units or changing the first changes it.
    function _foldHolds(string memory settlement) internal returns (bool) {
        bytes32[4] memory h = [_h(0), _h(1), _h(2), _h(3)];
        bytes32 base = _publicationOf(settlement, h);
        bytes32 swapped = _publicationOf(settlement, [h[0], h[2], h[1], h[3]]);
        bytes32 first = _publicationOf(settlement, [keccak256("other"), h[1], h[2], h[3]]);
        bytes32 spec = _fold(_fold(_fold(h[0], h[1]), h[2]), h[3]);
        return base == spec && swapped != base && first != base;
    }

    function test_foldPropertyHoldsOnTheRealBuild() public {
        require(_foldHolds(REAL), "real fold");
    }

    function test_mutation_unorderedFoldIsCaught() public {
        require(!_foldHolds(UNORDERED), "xor fold must fail the property");
    }

    function test_mutation_foldDroppingEarlierUnitsIsCaught() public {
        require(!_foldHolds(DROPS_PREFIX), "prefix-dropping fold must fail the property");
    }

    /// The single-unit property: no unit record, the anchor's own root and hash.
    function _singleUnitHolds(string memory settlement) internal returns (bool ok) {
        uint256 snap = jv.snapshotState();
        (, bytes32 whole) = _setUpWith(settlement, 3);
        hv.roll(650);
        _postUnit(0, 2, 0, 3, PUB);
        (, bytes32[] memory roots, ) = fairbind.getAnchorUnits(sellerId, 0);
        ok = roots.length == 0 && _anchor().root == whole && _anchor().publicationHash == PUB;
        jv.revertToState(snap);
    }

    function test_singleUnitPropertyHoldsOnTheRealBuild() public {
        require(_singleUnitHolds(REAL), "real single unit");
    }

    function test_mutation_singleUnitStoredAsSplitIsCaught() public {
        require(!_singleUnitHolds(SINGLE_SPLIT), "single unit stored as a split must fail the property");
    }
}
