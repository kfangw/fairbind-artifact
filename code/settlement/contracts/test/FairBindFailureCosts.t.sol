// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

interface CostLogVm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

/// The per-failure bond deduction (ADR 0018), the freeze timing profile flag
/// and the minimum judged count before the inconclusive threshold (ADR 0020).
/// Each test states the behaviour it replaces.
contract FairBindFailureCostsTest is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant PENALTY = 10_000_000;
    uint256 internal constant SHARE = PENALTY / 3;
    CostLogVm internal constant LOGS = CostLogVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant INCONCLUSIVE = uint8(FairBindCore.Verdict.INCONCLUSIVE);
    uint8 internal constant ACTIVE = uint8(FairBindCore.SellerStatus.ACTIVE);
    uint8 internal constant SUSPENDED = uint8(FairBindCore.SellerStatus.SUSPENDED);
    uint8 internal constant SANCTIONED = uint8(FairBindCore.SellerStatus.SANCTIONED);
    uint8 internal constant NONE = uint8(FairBindCore.FreezeState.NONE);
    uint8 internal constant FROZEN = uint8(FairBindCore.FreezeState.FROZEN);
    uint8 internal constant CLAIM_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);

    /// Buyer non-delivery dispute that ends UNSERVED: a confirmed seller failure.
    function _unserved(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        if (block.number <= p.responseDue) hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        fairbind.timeoutServe(n);
    }

    /// Every purchase sampled, no automatic recheck.
    function _sampledProfile(bool freezeOnInitialFail) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = freezeOnInitialFail ? _baseProfile() : _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
    }

    /// Anchors and seals epoch 0 over the given purchases.
    function _sealEpoch(bytes32[] memory ns) internal {
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("beacon"));
        fairbind.seal(sellerId, 0);
    }

    /// Finalizes an unappealed initial verdict after its appeal window, with
    /// the recheck candidate block hash available.
    function _finalizeAfterAppeal(bytes32 n) internal {
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("candidate", n)));
        fairbind.finalizeCase(n);
    }

    function _bond() internal view returns (FairBindCore.BondView memory) {
        return fairbind.getBond(fairbind.getSeller(sellerId).bondId);
    }

    function _status() internal view returns (uint8) {
        return fairbind.getSeller(sellerId).status;
    }

    /// Sum of Slashed amounts against the seller with the given reason since recordLogs.
    function _slashed(uint8 reason) internal returns (uint256 total, uint256 count) {
        CostLogVm.Log[] memory logs = LOGS.getRecordedLogs();
        bytes32 slashed = keccak256("Slashed(uint8,uint32,bytes32,address,uint256,uint8)");
        for (uint256 i; i < logs.length; i++) {
            if (logs[i].emitter != address(fairbind) || logs[i].topics[0] != slashed) continue;
            if (uint256(logs[i].topics[1]) != 1) continue;
            (, uint256 amount, uint256 r) = abi.decode(logs[i].data, (address, uint256, uint256));
            if (r != reason) continue;
            total += amount;
            count++;
        }
    }

    // ------------------------------------------------- per-failure deduction

    /// Old rule: nothing left the bond before failureLimit. Now each counted
    /// failure deducts sellerPenalty / failureLimit and the failure that
    /// reaches the limit deducts the remainder, so the window sums to
    /// sellerPenalty.
    function test_eachConfirmedFailureDeductsItsShareAndTheLimitTakesTheRemainder() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[3] memory ns = [_purchase(G), _purchase(G), _purchase(G)];
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        LOGS.recordLogs();
        _unserved(ns[0]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.balance == PENALTY - SHARE && bond.failureCount == 1 && !bond.sanctioned, "first share deducted");
        require(bond.scaleFactor == 0, "rescaled below one penalty");
        require(fairbind.getLockedForfeit() - lockedBefore == SHARE, "share locked in the contract");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
        (uint256 amount, uint256 count) = _slashed(4);
        require(amount == SHARE && count == 1, "one per-failure Slashed with reason 4");
        require(_status() == SUSPENDED, "suspended, not sanctioned");

        _unserved(ns[1]);
        require(_bond().balance == PENALTY - 2 * SHARE, "second share deducted");
        LOGS.recordLogs();
        _unserved(ns[2]);
        bond = _bond();
        require(bond.balance == 0 && bond.sanctioned && bond.failureCount == 3, "remainder at the limit");
        require(fairbind.getLockedForfeit() - lockedBefore == PENALTY, "window total is one penalty");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
        (amount, count) = _slashed(1);
        require(amount == PENALTY - 2 * SHARE && count == 1, "terminal Slashed carries the remainder");
        require(_status() == SANCTIONED, "sanctioned at the limit");
    }

    /// Old rule: nothing was deducted, so the reinstatement condition
    /// balance >= sellerPenalty held without a top-up. Now the deducted share
    /// has to be topped up first.
    function test_reinstatementNeedsTheDeductedShareToppedUp() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32 n = _purchase(G);
        _unserved(n);
        FairBindCore.BondView memory bond = _bond();
        require(bond.balance == PENALTY - SHARE && _status() == SUSPENDED, "one share deducted");
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bond.bondId);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
        token.mint(SELLER_OWNER, SHARE);
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bond.bondId, uint128(SHARE));
        hv.prank(SELLER_OWNER);
        fairbind.reinstateSeller(sellerId);
        require(_status() == ACTIVE && _bond().balance == PENALTY, "reinstated at one penalty");
    }

    /// The deduction never exceeds the balance: after the failure count
    /// restarts without a top-up, later shares are clipped to what is left.
    function test_deductionIsBoundedByTheBondBalance() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.failureWindowBlocks = 100;
        _deploy(p);
        hv.roll(10);
        bytes32[4] memory ns = [_purchase(G), _purchase(G), _purchase(G), _purchase(G)];
        _unserved(ns[0]);
        // Read the window start from the contract: via-IR folds block.number within a function.
        hv.roll(uint256(_bond().failureWindowStart) + 101);
        _unserved(ns[1]);
        require(_bond().failureCount == 1 && _bond().balance == PENALTY - 2 * SHARE, "count restarted, share deducted");
        hv.roll(uint256(_bond().failureWindowStart) + 101);
        _unserved(ns[2]);
        require(_bond().balance == PENALTY - 3 * SHARE, "one unit left");
        hv.roll(uint256(_bond().failureWindowStart) + 101);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        _unserved(ns[3]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.balance == 0 && !bond.sanctioned && bond.failureCount == 1, "clipped to the balance, no sanction");
        require(fairbind.getLockedForfeit() - lockedBefore == PENALTY - 3 * SHARE, "only the remaining unit moved");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
    }

    /// A sampled FINAL(INCONCLUSIVE) above the threshold freezes and suspends
    /// but deducts nothing, and an epoch failure deducts once per epoch.
    function test_uncountedFailuresDeductNothingAndAnEpochFailureDeductsOnce() public {
        FairBindCore.ServiceProfileInput memory p = _sampledProfile(false);
        p.maxInconclusivePpm = 500_000;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _sealEpoch(ns);
        fairbind.openSample(ns[0]);
        _judge(ns[0], INCONCLUSIVE);
        _finalizeAfterAppeal(ns[0]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && _status() == SUSPENDED, "threshold inconclusive freezes");
        require(bond.balance == PENALTY && bond.failureCount == 0, "nothing deducted or counted");

        // Epoch 1: two purchases, no anchor. The timeout counts and deducts
        // once; the refunds of both purchases add nothing.
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bond.bondId);
        hv.prank(SELLER_OWNER);
        fairbind.reinstateSeller(sellerId);
        uint256 start = 1 + 300 * ((block.number - 1) / 300 + 1);
        hv.roll(start);
        bytes32 a = _purchase(G);
        bytes32 b = _purchase(G);
        uint24 epoch = fairbind.getPurchase(a).epoch;
        hv.roll(start + 600 + 100 + 1);
        fairbind.timeoutAnchor(sellerId, epoch);
        bond = _bond();
        require(bond.balance == PENALTY - SHARE && bond.failureCount == 1, "epoch failure deducts one share");
        fairbind.claimEpochFailure(a);
        fairbind.claimEpochFailure(b);
        bond = _bond();
        require(bond.balance == PENALTY - SHARE && bond.failureCount == 1, "refunds of the same epoch add nothing");
    }

    // ------------------------------------------------------- freeze timing

    /// freezeOnInitialFail = false: an initial FAIL neither freezes nor
    /// suspends; the confirmed failure freezes, suspends and opens the claim
    /// window, and the frozen window includes purchases settled between the
    /// initial and the final FAIL.
    function test_withoutFreezeOnInitialFailTheConfirmedFailureFreezes() public {
        _deploy(_sampledProfile(false));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _sealEpoch(ns);
        fairbind.openSample(ns[0]);
        _judge(ns[0], FAIL);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == NONE && _status() == ACTIVE, "initial FAIL neither freezes nor suspends");
        require(fairbind.getFreezeTriggers(bond.bondId).count == 0, "no pending trigger");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.freezeSellerDeferred(ns[0]);
        // The seller keeps selling between the initial and the final FAIL.
        bytes32 later = _purchase(G);
        hv.roll(uint256(fairbind.getReview(ns[0]).appealUntil) + 1);
        fairbind.finalizeCase(ns[0]);
        bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.freezeNonce == ns[0], "final FAIL freezes and opens claims");
        require(bond.freezeBlock == block.number, "frozen at the confirmed failure");
        require(bond.claimUntilBlock == block.number + 40_000, "claim window from the final FAIL");
        require(_status() == SUSPENDED, "suspended at the confirmed failure");
        require(fairbind.purchaseState(later) == uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE),
            "purchase settled between the two verdicts is in the frozen window");
        FairBindCore.FairBindReceipt memory r = _receipt(later);
        fairbind.claimRefund(later, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)),
            FairBindCore.ReceiptProof(0, 0, new bytes32[](0)));
        require(fairbind.getPurchase(later).financialState == uint8(FairBindCore.FinancialState.REFUNDED), "claimed");
    }

    /// freezeOnInitialFail = false: an overturned initial FAIL changes nothing
    /// on the bond account, before or after the review.
    function test_withoutFreezeOnInitialFailAnOverturnTouchesNothing() public {
        _deploy(_sampledProfile(false));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _sealEpoch(ns);
        fairbind.openSample(ns[0]);
        _judge(ns[0], FAIL);
        token.mint(SELLER_OWNER, 5_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(ns[0]);
        uint64 rb = fairbind.getCase(ns[0]).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("review"));
        fairbind.sealReviewRandomness(ns[0]);
        _judge(ns[0], PASS);
        rb = fairbind.getCase(ns[0]).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("tiebreak"));
        fairbind.sealReviewRandomness(ns[0]);
        _judge(ns[0], PASS);
        FairBindCore.BondView memory bond = _bond();
        require(fairbind.getCase(ns[0]).finalVerdict == PASS, "overturned");
        require(bond.freezeState == NONE && bond.failureCount == 0 && bond.balance == PENALTY, "bond untouched");
        require(_status() == ACTIVE, "never suspended");
    }

    /// freezeOnInitialFail = true (the comparison profile on the override
    /// build): the initial FAIL still freezes, suspends and records a pending
    /// trigger, as before.
    function test_withFreezeOnInitialFailTheInitialFailFreezes() public {
        _deploy(_sampledProfile(true));
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _sealEpoch(ns);
        fairbind.openSample(ns[0]);
        _judge(ns[0], FAIL);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == FROZEN && bond.freezeNonce == ns[0], "initial FAIL freezes");
        require(_status() == SUSPENDED, "suspended at once");
        require(fairbind.getFreezeTriggers(bond.bondId).count == 1, "pending trigger recorded");
        hv.roll(uint256(fairbind.getReview(ns[0]).appealUntil) + 1);
        fairbind.finalizeCase(ns[0]);
        bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.freezeBlock < block.number, "window anchored at the initial FAIL");
    }

    /// Profile admission: the production build admits only
    /// freezeOnInitialFail = false; the override build admits either and
    /// requires true when the hold period is below the case horizon; both
    /// require minJudgedCount >= 1.
    function test_admissionOfTheFreezeFlagAndMinimumJudgedCount() public {
        hv.roll(10);
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(PROFILE, p);
        p = _productionProfile();
        p.minJudgedCount = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(PROFILE, p);
        fairbind.createServiceProfile(PROFILE, _productionProfile());
        require(fairbind.getServiceProfile(PROFILE).parameters.minJudgedCount == 1, "admitted");

        FairBind overridden = deployFairBindWithAdmissionOverride(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        overridden.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
        overridden.createServiceProfile(PROFILE, _baseProfile());
        overridden.createServiceProfile(PROFILE + 1, _productionProfile());
        p = _productionProfile();
        p.deferBlocks = 3_000;
        p.retentionBlocks = 3_000;
        p.claimWindowBlocks = 3_000;
        // The bond covers the rate term up to the judgment delay of ADR 0024.
        p.sellerPenalty = 20_000_000;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE + 2, p);
        p.freezeOnInitialFail = true;
        overridden.createServiceProfile(PROFILE + 2, p);
        p.minJudgedCount = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE + 3, p);
    }

    // ------------------------------------------------ minimum judged count

    /// Old rule: the first sampled FINAL(INCONCLUSIVE) of a window exceeded
    /// any threshold on its own and froze the account. With minJudgedCount the
    /// threshold applies only once the window holds that many judged cases.
    function test_firstInconclusiveOfAWindowNoLongerFreezes() public {
        FairBindCore.ServiceProfileInput memory p = _sampledProfile(false);
        p.maxInconclusivePpm = 500_000;
        p.minJudgedCount = 2;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = _purchase(G);
        ns[1] = _purchase(G);
        ns[2] = _purchase(G);
        _sealEpoch(ns);
        for (uint256 i; i < 3; i++) fairbind.openSample(ns[i]);
        // All three verdicts land inside their judge deadlines; the cases end in order.
        _judge(ns[0], INCONCLUSIVE);
        _judge(ns[1], PASS);
        _judge(ns[2], INCONCLUSIVE);
        _finalizeAfterAppeal(ns[0]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.inconclusiveCount == 1 && bond.judgedCount == 1, "counted");
        require(bond.freezeState == NONE && _status() == ACTIVE, "below the minimum judged count: no freeze");
        // The second judged case is a PASS: the rate is exactly at the threshold, still no freeze.
        _finalizeAfterAppeal(ns[1]);
        require(_bond().freezeState == NONE, "at the threshold: no freeze");
        // The third is inconclusive: two of three above one half, with the minimum met.
        _finalizeAfterAppeal(ns[2]);
        bond = _bond();
        require(bond.inconclusiveCount == 2 && bond.judgedCount == 3, "all counted");
        require(bond.freezeState == CLAIM_OPEN && _status() == SUSPENDED, "threshold applies once the minimum is met");
        require(bond.balance == PENALTY && bond.failureCount == 0, "still no deduction and no failure");
    }
}
