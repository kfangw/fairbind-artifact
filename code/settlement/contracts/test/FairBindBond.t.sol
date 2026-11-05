// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

interface LogVm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

/// Bond accounts, the bond-level freeze with receipt claims and forfeiture,
/// suspension and the failure limit, inconclusive counting, the keeper serve
/// fallback, release guards, and the beacon delay.
contract FairBindBondTest is ReproBase {
    uint256 internal constant G = 10_000;
    LogVm internal constant LOGS = LogVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    /// forfeitUnclaimed reports its split once, with both recipients' amounts,
    /// through UnclaimedForfeited, and emits no Slashed event.
    function _checkForfeitLogs(uint32 bondId, uint256 total, uint256 toPool, uint256 toReserve) internal {
        LogVm.Log[] memory logs = LOGS.getRecordedLogs();
        bytes32 forfeited = keccak256("UnclaimedForfeited(uint32,bytes32,uint256,uint256,uint256)");
        bytes32 slashed = keccak256("Slashed(uint8,uint32,bytes32,address,uint256,uint8)");
        uint256 seen;
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].emitter != address(fairbind)) continue;
            require(logs[i].topics[0] != slashed, "forfeiture emits no Slashed");
            if (logs[i].topics[0] != forfeited) continue;
            seen++;
            require(uint256(logs[i].topics[1]) == bondId, "forfeiture bond");
            (uint256 t, uint256 p, uint256 r) = abi.decode(logs[i].data, (uint256, uint256, uint256));
            require(t == total && p == toPool && r == toReserve, "forfeiture amounts");
        }
        require(seen == 1, "one UnclaimedForfeited");
    }

    function _addSeller(uint32 bondId) internal returns (uint32 id) {
        hv.prank(SELLER_OWNER);
        id = fairbind.registerSeller(bondId, PROFILE, hv.addr(SELLER_KEY), CLAIMS);
    }

    function _newBond(uint256 amount) internal returns (uint32 bondId) {
        token.mint(SELLER_OWNER, amount);
        hv.prank(SELLER_OWNER);
        bondId = fairbind.registerBond(PROFILE, uint128(amount));
    }

    function _purchaseFor(uint32 seller) internal returns (bytes32 n) {
        uint32 saved = sellerId;
        sellerId = seller;
        n = _purchase(G);
        sellerId = saved;
    }

    function _bondOf(uint32 seller) internal view returns (FairBindCore.BondView memory) {
        return fairbind.getBond(fairbind.getSeller(seller).bondId);
    }

    function _emptyProof() internal pure returns (FairBindCore.ReceiptProof memory p) {
        p = FairBindCore.ReceiptProof(0, 0, new bytes32[](0));
    }

    function _claim(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.claimRefund(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _emptyProof());
    }

    /// Buyer non-delivery dispute that ends UNSERVED: a final seller failure.
    function _unserved(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        if (block.number <= p.responseDue) hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        fairbind.timeoutServe(n);
    }

    function _sampledProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _baseProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
    }

    /// One purchase in epoch 0, anchored with its receipt tree and sealed.
    function _sealedPurchase() internal returns (bytes32 n) {
        hv.roll(10);
        n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
    }

    // ------------------------------------------------------------ bond bucket

    function test_bucketSharedAcrossRegistrationsOfOneBond() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        uint32 second = _addSeller(bondId);
        uint32 third = _addSeller(bondId);
        uint32[3] memory ids = [sellerId, second, third];
        hv.roll(10);
        for (uint256 i; i < 20; i++) _purchaseFor(ids[i % 3]);
        require(fairbind.getBond(bondId).registrations == 3, "three registrations");
        // Twenty settlements empty the unit bucket whichever registration settles.
        for (uint256 i; i < 3; i++) {
            uint32 saved = sellerId;
            sellerId = ids[i];
            SettleArgs memory a = _settleArgs(G);
            hv.expectRevert(FairBindCore.RateLimitExceeded.selector);
            _settle(a);
            sellerId = saved;
        }
        // A new registration inherits the empty bucket.
        uint32 fourth = _addSeller(bondId);
        sellerId = fourth;
        SettleArgs memory b = _settleArgs(G);
        hv.expectRevert(FairBindCore.RateLimitExceeded.selector);
        _settle(b);
        // A separate bond has its own bucket.
        uint32 otherBond = _newBond(10_000_000);
        uint32 other = _addSeller(otherBond);
        _purchaseFor(other);
        require(fairbind.getBond(otherBond).bucketBalancePpm == 19 * PPM, "separate bucket");
    }

    function test_scaleFactorFollowsBalanceAndNeverRisesWithoutTransfer() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(10);
        for (uint256 i; i < 20; i++) _purchase(G);
        require(fairbind.getBond(bondId).scaleFactor == 1, "unit scale");
        // Top-up by one and a half penalties: floor gives scale 2; the level is not raised.
        token.mint(SELLER_OWNER, 15_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bondId, 15_000_000);
        FairBindCore.BondView memory b = fairbind.getBond(bondId);
        require(b.scaleFactor == 2 && b.bucketBalancePpm == 0, "scale 2, level unchanged");
        // Refill doubles with the scale: 20 blocks at 0.05 per block times 2 = 2 settlements.
        hv.roll(30);
        _purchase(G);
        _purchase(G);
        SettleArgs memory a = _settleArgs(G);
        hv.expectRevert(FairBindCore.RateLimitExceeded.selector);
        _settle(a);
    }

    // ------------------------------------------------------------------ freeze

    function test_failureFreezesEveryRegistrationOfTheBondOnly() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        uint32 b = _addSeller(bondId);
        uint32 otherBond = _newBond(10_000_000);
        uint32 c = _addSeller(otherBond);
        hv.roll(10);
        bytes32[3] memory a = [_purchase(G), _purchase(G), _purchase(G)];
        bytes32[3] memory bs = [_purchaseFor(b), _purchaseFor(b), _purchaseFor(b)];
        bytes32 cn = _purchaseFor(c);
        uint256 held = token.balanceOf(address(fairbind));

        _unserved(a[0]);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window open");
        require(bond.failureCount == 1 && bond.balance == 10_000_000 - 3_333_333, "counted, one share deducted");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(fairbind.getSeller(b).status == uint8(FairBindCore.SellerStatus.ACTIVE), "sibling active");
        require(fairbind.getBond(otherBond).freezeState == 0, "other bond untouched");
        require(fairbind.purchaseState(bs[2]) == uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE), "sibling entry claimable");
        require(fairbind.purchaseState(cn) == uint8(FairBindCore.FinancialState.DEFERRED), "other bond entry deferred");

        // The sibling registration cannot settle while its bond is frozen.
        uint32 saved = sellerId;
        sellerId = b;
        SettleArgs memory s = _settleArgs(G);
        hv.expectRevert(FairBindCore.BondNotActive.selector);
        _settle(s);
        sellerId = saved;
        // Nothing frozen is releasable, even after deferBlocks.
        hv.roll(10 + 40_001);
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(bs[0]);

        // Receipt claims: two sibling buyers claim; a second claim is refused.
        uint256 buyerBefore = token.balanceOf(buyer);
        _claim(bs[0]);
        _claim(bs[1]);
        require(token.balanceOf(buyer) == buyerBefore + 2 * G, "claims paid");
        hv.expectRevert(FairBindCore.AlreadyClaimed.selector);
        this.claimExternal(bs[0]);
        // A receipt for an entry of another bond is outside any open window.
        hv.expectRevert(FairBindCore.ClaimWindowNotOpen.selector);
        this.claimExternal(cn);
        // A receipt that does not match the purchase record is refused.
        FairBindCore.FairBindReceipt memory wrong = _receipt(bs[2]);
        wrong.sellerId = c;
        bytes memory wrongSig = _sig(SELLER_KEY, fairbind.receiptDigest(wrong));
        hv.expectRevert(FairBindCore.InvalidReceipt.selector);
        fairbind.claimRefund(bs[2], wrong, wrongSig, _emptyProof());
        // The judged buyer takes its own refund and deposit.
        fairbind.claimRefund(a[0]);

        // Reinstatement needs the deducted share back first, even while the
        // claim window is open (ADR 0021).
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.forfeitUnclaimed(bondId);

        hv.roll(uint256(bond.claimUntilBlock) + 1);
        hv.expectRevert(FairBindCore.ClaimWindowNotOpen.selector);
        this.claimExternal(bs[2]);
        uint256 poolBefore = token.balanceOf(REWARD_POOL);
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 custodyBefore = token.balanceOf(address(fairbind));
        LOGS.recordLogs();
        fairbind.forfeitUnclaimed(bondId);
        _checkForfeitLogs(bondId, 3 * G, 0, 0);
        // Unclaimed: a[1], a[2], bs[2]. Old rule (ADR 0013): split one to one
        // between the verifier reward pool and the treasury. Now locked in the
        // contract (ADR 0022): no token leaves it.
        require(token.balanceOf(REWARD_POOL) == poolBefore, "nothing to the verifier pool");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
        require(fairbind.getLockedForfeit() - lockedBefore == 3 * G, "remainder locked");
        require(token.balanceOf(address(fairbind)) == custodyBefore, "tokens stay in the contract");
        require(fairbind.purchaseState(a[1]) == uint8(FairBindCore.FinancialState.FORFEITED), "forfeited");
        // A forfeited entry never reaches the seller.
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(a[1]);
        require(token.balanceOf(SELLER_OWNER) == ownerBefore, "forfeited entry not paid");
        require(fairbind.getPurchase(a[1]).financialState == uint8(FairBindCore.FinancialState.FORFEITED), "marked");
        // Conservation over the frozen bond: claims + own refund + forfeiture = six purchases.
        // Only the three claims and the own refund leave the contract; the
        // forfeiture and the deducted share (ADR 0018) stay locked (ADR 0022).
        require(held - token.balanceOf(address(fairbind)) == 3 * G, "frozen pool conserved");
        require(fairbind.getLockedForfeit() == 3 * G + 3_333_333, "forfeiture and share locked");
        require(fairbind.getBond(bondId).deferredBalance == 0, "bond ledger empty");

        // Reinstatement needs the deducted share topped back up.
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
        token.mint(SELLER_OWNER, 3_333_333);
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bondId, 3_333_333);
        hv.prank(SELLER_OWNER);
        fairbind.reinstateSeller(sellerId);
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "reinstated");
    }

    function claimExternal(bytes32 n) external {
        _claim(n);
    }

    function test_overturnReleasesExactlyTheFrozenEntries() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        uint32 sibling = _addSeller(bondId);
        hv.roll(5);
        bytes32 other = _purchaseFor(sibling);
        bytes32 n = _sealedPurchase();
        fairbind.openSample(n);
        _judge(n, 2);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.FROZEN) && bond.freezeNonce == n, "initial FAIL freezes");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "stopped at once");
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releaseFrozen(bondId);
        // Seller appeals; the review overturns the failure.
        token.mint(SELLER_OWNER, 5_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("review"));
        fairbind.sealReviewRandomness(n);
        _judge(n, 1);
        // The disagreeing party review goes to the tiebreak, which also passes (ADR 0019).
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.TIEBREAK), "tiebreak");
        require(fairbind.getBond(bondId).freezeState == uint8(FairBindCore.FreezeState.FROZEN), "still held until the tiebreak");
        rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("tiebreak"));
        fairbind.sealReviewRandomness(n);
        _judge(n, 1);
        bond = fairbind.getBond(bondId);
        require(bond.freezeState == 0 && bond.failureCount == 0 && bond.inconclusiveCount == 0, "overturn leaves nothing");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "unconditional reinstatement");
        require(bond.balance == 10_000_000 && bond.forfeitedTotal == 0, "nothing slashed or forfeited");
        require(fairbind.purchaseState(other) == uint8(FairBindCore.FinancialState.DEFERRED), "sibling back on schedule");
    }

    function test_entryWithOpenCaseAtClaimDeadlineIsForfeitedWhenItsCaseEnds() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = _purchase(G);
        bytes16 key1;
        (ns[1], key1) = _publishablePurchase();
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 2, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        fairbind.openSample(ns[0]);
        fairbind.openSample(ns[1]);
        _judge(ns[0], 2);
        hv.roll(uint256(fairbind.getReview(ns[0]).appealUntil) + 1);
        fairbind.finalizeCase(ns[0]);
        fairbind.claimRefund(ns[0]);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window open");
        // The second entry's own case is still open when the window closes.
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        fairbind.forfeitUnclaimed(bondId);
        require(fairbind.getLockedForfeit() == lockedBefore, "open case excluded from the bulk forfeiture");
        require(fairbind.getBond(bondId).encumbered == G, "still held by its case");
        // Its case ends without a refund right (keeper publication, protocol
        // INCONCLUSIVE): the entry is forfeited, not released.
        _timeoutAllAssignments(ns[1]);
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        _publishResponse(ns[1], key1);
        require(fairbind.getCase(ns[1]).state == uint8(FairBindCore.CaseState.INCONCLUSIVE), "case ended");
        require(fairbind.getPurchase(ns[1]).financialState == uint8(FairBindCore.FinancialState.FORFEITED), "forfeited");
        require(fairbind.getLockedForfeit() - lockedBefore == G, "late entry locked");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore, "never to the seller");
        require(fairbind.getBond(bondId).deferredBalance == 0, "bond ledger empty");
    }

    // ------------------------------------------ pending triggers (ADR 0015)

    /// Two sampled purchases of epoch 0, both judged FAIL in the initial stage,
    /// the second five blocks after the first.
    function _twoInitialFails() internal returns (bytes32 a, bytes32 b) {
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = _purchase(G);
        ns[1] = _purchase(G);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 2, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        (a, b) = (ns[0], ns[1]);
        fairbind.openSample(a);
        fairbind.openSample(b);
        _judge(a, 2);
        hv.roll(block.number + 5);
        _judge(b, 2);
    }

    function _appeal(bytes32 n) internal {
        token.mint(SELLER_OWNER, 5_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
    }

    /// Party review of an appealed FAIL returns PASS, and so does the tiebreak
    /// that the disagreement leads to (ADR 0019).
    function _overturn(bytes32 n) internal {
        for (uint256 stage; stage < 2; stage++) {
            uint64 rb = fairbind.getCase(n).randomBlock;
            if (block.number <= rb) hv.roll(uint256(rb) + 1);
            hv.setBlockhash(rb, keccak256(abi.encode("review", n, stage)));
            fairbind.sealReviewRandomness(n);
            _judge(n, 1);
        }
    }

    function _siblingSettle(uint32 sibling) internal {
        uint32 saved = sellerId;
        sellerId = sibling;
        SettleArgs memory s = _settleArgs(G);
        hv.expectRevert(FairBindCore.BondNotActive.selector);
        _settle(s);
        sellerId = saved;
    }

    /// Old behaviour: the overturn of the first trigger released the freeze
    /// and reactivated the seller while the second initial FAIL was pending.
    function test_overturnOfOneTriggerKeepsTheFreezeWhileAnotherIsPending() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 a, bytes32 b) = _twoInitialFails();
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.FROZEN) && bond.freezeNonce == a, "first FAIL anchors");
        uint64 frozenAt = bond.freezeBlock;
        FairBindCore.TriggerQueue memory q = fairbind.getFreezeTriggers(bondId);
        require(q.count == 2 && q.head == a && q.tail == b, "both initial FAILs pending");
        _appeal(a);
        _appeal(b);
        _overturn(a);
        require(fairbind.getCase(a).finalVerdict == uint8(FairBindCore.Verdict.PASS), "first overturned");
        require(fairbind.getCase(b).state == uint8(FairBindCore.CaseState.PARTY_REVIEW), "second still pending");
        bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.FROZEN), "still frozen");
        require(bond.freezeNonce == b && bond.freezeBlock == frozenAt, "re-anchored to the pending trigger, same window");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "still suspended");
        q = fairbind.getFreezeTriggers(bondId);
        require(q.count == 1 && q.head == b && q.tail == b, "one trigger left");
        // No settlement enters and no entry is released while the second is pending.
        SettleArgs memory s = _settleArgs(G);
        hv.expectRevert(FairBindCore.SellerIsSuspended.selector);
        _settle(s);
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(a);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releaseFrozen(bondId);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
    }

    function test_overturnOfBothTriggersReleasesAndReactivates() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 a, bytes32 b) = _twoInitialFails();
        _appeal(a);
        _appeal(b);
        _overturn(a);
        _overturn(b);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == 0, "released");
        require(bond.failureCount == 0 && bond.forfeitedTotal == 0 && bond.balance == 10_000_000, "nothing counted or taken");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "active again");
        require(fairbind.getFreezeTriggers(bondId).count == 0, "no trigger left");
        require(fairbind.getPurchase(a).financialState == uint8(FairBindCore.FinancialState.RELEASABLE), "back on schedule");
        _purchase(G);
    }

    /// The second confirmed failure extends the open window and, since ADR
    /// 0021, moves freezeBlock to its own block (the old rule kept the first
    /// freeze block, which left purchases settled after a reinstatement
    /// outside the window).
    function test_secondConfirmedFailureExtendsTheOpenClaimWindow() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 a, bytes32 b) = _twoInitialFails();
        hv.roll(uint256(fairbind.getReview(a).appealUntil) + 1);
        fairbind.finalizeCase(a);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN) && bond.freezeNonce == a, "claim window open");
        require(bond.failureCount == 1, "first counted");
        uint64 firstUntil = bond.claimUntilBlock;
        require(fairbind.getFreezeTriggers(bondId).head == b, "second still pending");
        hv.roll(uint256(fairbind.getReview(b).appealUntil) + 1);
        fairbind.finalizeCase(b);
        bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN) && bond.freezeNonce == a, "same trigger");
        require(bond.claimUntilBlock == block.number + 40_000 && bond.claimUntilBlock > firstUntil, "claim window extended");
        require(bond.freezeBlock == block.number, "window boundary moved to the second confirmed failure");
        require(bond.failureCount == 2, "second counted once");
        require(fairbind.getFreezeTriggers(bondId).count == 0, "no trigger left");
    }

    /// A trigger still pending when the claim window closes keeps the bond
    /// closed to new settlements and the seller suspended.
    function test_pendingTriggerOutlivesTheClaimWindow() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        uint32 sibling = _addSeller(bondId);
        (bytes32 a, bytes32 b) = _twoInitialFails();
        hv.roll(uint256(fairbind.getReview(a).appealUntil) + 1);
        fairbind.finalizeCase(a);
        hv.roll(uint256(fairbind.getBond(bondId).claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bondId);
        require(fairbind.getBond(bondId).freezeState == uint8(FairBindCore.FreezeState.CLAIM_CLOSED), "closed");
        require(fairbind.getCase(b).state == uint8(FairBindCore.CaseState.INITIAL_VERDICT), "second not finalized");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
        _siblingSettle(sibling);
        // The second failure becomes final and opens a new window.
        fairbind.finalizeCase(b);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN) && bond.freezeNonce == b, "new window");
        // The first failure is older than failureWindowBlocks by now, so the count restarts.
        require(bond.failureCount == 1 && fairbind.getFreezeTriggers(bondId).count == 0, "counted, none pending");
    }

    // ---------------------------------------------------------- failure limit

    function test_failureLimitSanctionsOnceAtTheLimit() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(10);
        bytes32[4] memory ns = [_purchase(G), _purchase(G), _purchase(G), _purchase(G)];
        _unserved(ns[0]);
        _unserved(ns[1]);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.failureCount == 2 && !bond.sanctioned && bond.balance == 10_000_000 - 2 * 3_333_333, "one short: two shares, no sanction");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        uint256 treasuryBefore = fairbind.getLockedForfeit();
        _unserved(ns[2]);
        bond = fairbind.getBond(bondId);
        require(bond.failureCount == 3 && bond.sanctioned && bond.balance == 0 && bond.scaleFactor == 0, "remainder at limit");
        require(fairbind.getLockedForfeit() - treasuryBefore == 10_000_000 - 2 * 3_333_333, "remainder locked");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SANCTIONED), "sanctioned");
        _unserved(ns[3]);
        require(fairbind.getLockedForfeit() - treasuryBefore == 10_000_000 - 2 * 3_333_333, "nothing after the sanction");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.reinstateSeller(sellerId);
    }

    function test_failuresAgeOutOfTheWindow() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(10);
        bytes32 first = _purchase(G);
        _unserved(first);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bondId);
        token.mint(SELLER_OWNER, 3_333_333);
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bondId, 3_333_333);
        hv.prank(SELLER_OWNER);
        fairbind.reinstateSeller(sellerId);
        // The bucket was clipped to zero while the account was below one penalty; it refills
        // at the profile rate (0.05 per block) once the top-up restores the scale factor.
        hv.roll(uint256(bond.claimUntilBlock) + 1 + 20);
        // The second failure lands after failureWindowBlocks: the count restarts.
        bytes32 second = _purchase(G);
        _unserved(second);
        bond = fairbind.getBond(bondId);
        require(bond.failureCount == 1 && !bond.sanctioned, "aged out");
        require(bond.freezeBlock > bond.forfeitedThrough, "new window after the closed one");
    }

    // ------------------------------------------------------------ inconclusive

    function test_inconclusiveAboveThresholdFreezesWithoutCountingOrPenalty() public {
        FairBindCore.ServiceProfileInput memory p = _sampledProfile();
        p.maxInconclusivePpm = 500_000;
        _deploy(p);
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        bytes32 n = _sealedPurchase();
        fairbind.openSample(n);
        uint32 verifier = fairbind.getCase(n).assignedVerifierId;
        _judge(n, 3);
        _finalizeInitial(n);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(fairbind.getCase(n).finalVerdict == uint8(FairBindCore.Verdict.INCONCLUSIVE), "final inconclusive");
        require(bond.inconclusiveCount == 1 && bond.judgedCount == 1, "counted as inconclusive");
        require(bond.failureCount == 0 && !bond.sanctioned && bond.balance == 10_000_000, "never a failure");
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "frozen above threshold");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(fairbind.getVerifier(verifier).bond == 10_000_000, "no verifier penalty");
    }

    function test_inconclusiveBelowThresholdChangesNoState() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        bytes32 n = _sealedPurchase();
        fairbind.openSample(n);
        _judge(n, 3);
        _finalizeInitial(n);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.inconclusiveCount == 1 && bond.freezeState == 0, "below threshold");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "active");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASABLE), "releasable");
    }

    /// Two purchases in epoch 0, anchored in one receipt tree and sealed.
    function _sealedPurchasePair() internal returns (bytes32 a, bytes32 b) {
        hv.roll(10);
        a = _purchase(G);
        b = _purchase(G);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = a;
        ns[1] = b;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 2, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
    }

    /// Opens a WRONG_DELIVERY dispute on n, judges it and finalizes it.
    function _disputeToFinal(bytes32 n, uint8 result) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        if (fairbind.getCase(n).state == uint8(FairBindCore.CaseState.ASSIGNING)) fairbind.assignVerifier(n);
        _judge(n, result);
        _finalizeInitial(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.FINAL), "dispute final");
        require(fairbind.getCase(n).finalVerdict == result, "dispute verdict");
    }

    function _sampleToFinal(bytes32 n, uint8 result) internal {
        fairbind.openSample(n);
        _judge(n, result);
        _finalizeInitial(n);
        require(fairbind.getCase(n).finalVerdict == result, "sample verdict");
    }

    /// Ends the appeal window of an initial verdict. An initial PASS or
    /// INCONCLUSIVE also passes its recheck decision block (recheckPpm is
    /// zero here).
    function _finalizeInitial(bytes32 n) internal {
        hv.roll(uint256(fairbind.getReview(n).appealUntil) + 1);
        uint64 randomBlock = fairbind.getCase(n).randomBlock;
        if (block.number <= randomBlock) hv.roll(uint256(randomBlock) + 1);
        hv.setBlockhash(randomBlock, keccak256("recheck decision"));
        fairbind.finalizeCase(n);
    }

    /// ADR 0017: a party dispute ending FINAL(PASS) does not enter the judged
    /// count; a sampled FINAL(PASS) does. The old rule counted both, so a
    /// seller could dilute its inconclusive ratio with disputes on its own
    /// purchases.
    function test_disputedPassDoesNotEnterTheJudgedCount() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 disputed, bytes32 sampled) = _sealedPurchasePair();
        _disputeToFinal(disputed, 1);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.judgedCount == 0 && bond.inconclusiveCount == 0, "dispute not counted");
        require(bond.inconclusiveWindowStart == 0, "no window started by a dispute");
        _sampleToFinal(sampled, 1);
        bond = fairbind.getBond(bondId);
        require(bond.judgedCount == 1 && bond.inconclusiveCount == 0, "sample counted");
        require(bond.inconclusiveWindowStart == block.number, "window started by the sample");
    }

    /// ADR 0017: a disputed FINAL(INCONCLUSIVE) changes no counter and never
    /// reaches the above-threshold freeze; a sampled one under the same profile
    /// still does.
    function test_disputedInconclusiveNeitherCountsNorFreezes() public {
        FairBindCore.ServiceProfileInput memory p = _sampledProfile();
        p.maxInconclusivePpm = 1;
        _deploy(p);
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 disputed, bytes32 sampled) = _sealedPurchasePair();
        _disputeToFinal(disputed, 3);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(bond.judgedCount == 0 && bond.inconclusiveCount == 0, "dispute not counted");
        require(bond.freezeState == 0, "dispute inconclusive does not freeze");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "seller active");
        _sampleToFinal(sampled, 3);
        bond = fairbind.getBond(bondId);
        require(bond.judgedCount == 1 && bond.inconclusiveCount == 1, "sample counted");
        require(bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "sampled inconclusive freezes");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
    }

    // ------------------------------------------------ idle verifier, keeper path

    function _timeoutAllAssignments(bytes32 n) internal {
        for (uint256 i; i < 3; i++) {
            hv.roll(uint256(fairbind.getCase(n).judgeDue) + 1);
            fairbind.timeoutJudge(n);
        }
    }

    function _keeperRequest() internal pure returns (FairBindCore.CanonicalRequest memory r) {
        r.method = bytes("GET");
        r.path = bytes("/v1/quote");
        r.query = bytes("symbol=ETH-USD");
        r.headerBlock = bytes("accept:application/json\n");
        r.body = "";
    }

    /// A purchase whose request hash commits a real canonical request, so that
    /// the seller can publish its response on chain.
    function _publishablePurchase() internal returns (bytes32 n, bytes16 key) {
        SettleArgs memory a = _settleArgs(G);
        a.req = fairbind.canonicalRequestHash(_keeperRequest(), fairbind.getServiceProfile(PROFILE).parameters.canonId);
        a.nonce = fairbind.deriveNonce(sellerId, PROFILE, CLAIMS, buyer, a.key, a.req);
        a.auth = FairBindCore.TransferAuthorization(buyer, address(fairbind), G, 0, 100, a.nonce);
        a.sig = _sig(BUYER_KEY, token.receiveAuthorizationDigest(buyer, address(fairbind), G, 0, 100, a.nonce));
        _settle(a);
        n = a.nonce;
        key = a.key;
    }

    /// The seller publishes the response committed by the receipt of n.
    function _publishResponse(bytes32 n, bytes16 key) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(SELLER_OWNER);
        fairbind.publish(n, key, _keeperRequest(), bytes("response"), r, rs);
    }

    /// A publishable sampled purchase, anchored and sealed in epoch 0.
    function _sealedPublishablePurchase() internal returns (bytes32 n, bytes16 key) {
        hv.roll(10);
        (n, key) = _publishablePurchase();
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
    }

    /// ADR 0014: the keeper fallback requires on-chain publication directly,
    /// with the serve deadline; a publication timeout is UNSERVED.
    function test_idleVerifiersLeadToKeeperPublicationAndUnserved() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        bytes32 n = _sealedPurchase();
        fairbind.openSample(n);
        _timeoutAllAssignments(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.PUBLISHING), "keeper publication, not inconclusive");
        require(c.requesterRole == uint8(FairBindCore.RequesterRole.KEEPER), "keeper role");
        require(c.publishDue == block.number + 300 && c.serveDue == c.publishDue, "serve deadline");
        hv.roll(uint256(c.publishDue));
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutServe(n);
        hv.roll(uint256(c.publishDue) + 1);
        fairbind.timeoutServe(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.UNSERVED), "unserved");
        require(fairbind.getBond(bondId).failureCount == 1, "seller failure");
    }

    /// Before ADR 0014 the seller could answer a keeper serve request with any
    /// nonzero bundle hash and let the case end protocol INCONCLUSIVE. Now there
    /// is no off-chain step to answer: served, escalate and finalizeServed revert.
    function test_keeperServeRejectsUnverifiedBundleHash() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        bytes32 n = _sealedPurchase();
        fairbind.openSample(n);
        _timeoutAllAssignments(n);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.served(n, keccak256("bundle"));
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.PUBLISHING) && c.bundleHash == bytes32(0), "no bundle");
        hv.prank(c.requester);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.escalate(n);
        hv.roll(uint256(c.publishDue) + 1);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.finalizeServed(n);
        fairbind.timeoutServe(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.UNSERVED), "unserved");
        require(fairbind.getBond(bondId).failureCount == 1, "seller failure");
    }

    function test_keeperPublicationEndsProtocolInconclusiveWithoutCounters() public {
        _deploy(_sampledProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        (bytes32 n, bytes16 key) = _sealedPublishablePurchase();
        fairbind.openSample(n);
        _timeoutAllAssignments(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.PUBLISHING), "keeper publication");
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        // A response that does not match the signed receipt is not a publication.
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidPublication.selector);
        fairbind.publish(n, key, _keeperRequest(), bytes("other response"), r, rs);
        _publishResponse(n, key);
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.INCONCLUSIVE), "protocol inconclusive");
        require(bond.failureCount == 0 && bond.judgedCount == 0 && bond.inconclusiveCount == 0, "no counter");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "seller unchanged");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASABLE), "releasable");
    }

    // ------------------------------------------------------ receipts and release

    function test_emptyCommitmentIsOnlyAcceptedAsFail() public {
        _deploy(_baseProfile());
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        hv.roll(10);
        bytes32 n = _purchase(G);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        r.predicateCommitment = bytes32(0);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        fairbind.assignVerifier(n);
        FairBindCore.SignedVerdict memory v = _verdict(n, 1);
        bytes memory vs = _sig(1000 + v.verifierId, fairbind.verdictDigest(v));
        hv.expectRevert(FairBindCore.InvalidReceipt.selector);
        fairbind.judge(v, vs, r, rs, _emptyProof());
        v = _verdict(n, 2);
        vs = _sig(1000 + v.verifierId, fairbind.verdictDigest(v));
        fairbind.judge(v, vs, r, rs, _emptyProof());
        require(fairbind.getBond(bondId).freezeState == uint8(FairBindCore.FreezeState.FROZEN), "FAIL freezes");
    }

    function test_unopenedSampleIsNeverReleased() public {
        _deploy(_sampledProfile());
        bytes32 n = _sealedPurchase();
        hv.roll(10 + 40_001);
        hv.expectRevert(FairBindCore.NotSampled.selector);
        fairbind.releasePurchase(n);
        // Opening stays possible after the sample-opening window.
        fairbind.openSample(n);
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.HELD), "held");
    }

    // ------------------------------------------------------------------ beacon

    function test_beaconBlockFollowsTheDeadlineByTheDelay() public {
        _deploy(_baseProfile());
        hv.roll(10);
        _purchase(G);
        hv.roll(700);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        FairBindCore.AnchorView memory a = fairbind.getAnchor(sellerId, 0);
        require(a.randomBlock == TEST_EPOCH0_BEACON_BLOCK, "anchorDeadline + 1 + beaconDelayBlocks");
        require(a.sealDeadline == a.randomBlock + 200, "seal window after the beacon");
        hv.roll(a.randomBlock);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.seal(sellerId, 0);
        hv.roll(uint256(a.randomBlock) + 1);
        hv.setBlockhash(701, keccak256("block after deadline"));
        hv.setBlockhash(a.randomBlock, keccak256("delayed beacon"));
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).randomness == keccak256("delayed beacon"), "delayed beacon read");
    }

    // --------------------------------------------------------------- admission

    function test_admissionChecksJudgmentDelayAndNewFields() public {
        // Admission rules are those of the production build, which admits only the production profile.
        _deploy(_productionProfile());
        uint256 delay = fairbind.judgmentDelayBlocks(PROFILE);
        // openHorizon = max(O_s, O_d, min(O_s, O_d) + 3 * 300) with O_s = 2 * 300 + 100 +
        // beaconDelay + 200 + 200 = 1,868 and O_d = 60 + 1800 = 1,860; the delivered-dispute
        // opening 2,760 dominates. Then every stage with all its assignments and serve
        // procedures, two lapsed review seals and the stalled-appeal block (ADR 0024).
        require(
            delay == (60 + 1800 + 3 * 300) + 9 * (2 * 600 + 3 * 300) + 3 * (600 + 300) + 600 + 6 + 2 * (2 * 200 + 3) + 1,
            "judgment delay formula"
        );
        require(delay == 25_773, "judgment delay value");
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.parameterHash = keccak256("admission");
        p.enforcementBlocks = uint32(delay - 1);
        p.maxRatePpmPerBlock = 1_000_000;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(10, p);
        p.enforcementBlocks = uint32(delay);
        fairbind.createServiceProfile(10, p);
        p = _productionProfile();
        p.claimWindowBlocks = p.retentionBlocks - 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(11, p);
        p = _productionProfile();
        p.beaconSlackL1Blocks = 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(12, p);
        p = _productionProfile();
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS - 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(15, p);
        p.beaconDelayBlocks = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(15, p);
        p = _productionProfile();
        p.failureLimit = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(13, p);
        p = _productionProfile();
        p.maxInconclusivePpm = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(14, p);
    }
}
