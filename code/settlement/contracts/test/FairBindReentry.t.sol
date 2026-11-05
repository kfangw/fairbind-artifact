// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

interface ReentryLogVm {
    struct Log {
        bytes32[] topics;
        bytes data;
        address emitter;
    }
    function recordLogs() external;
    function getRecordedLogs() external returns (Log[] memory);
}

/// ADR 0021: the failure threshold scales with the bond account's scale
/// factor; a seller may re-enter while its claim window is open and a later
/// confirmed failure moves the frozen window over what it sold since; a
/// review seal that finds no randomness reopens once; an exiting seller is
/// frozen and deducted like any other and cannot exit while its pool is open.
/// Each test states the behaviour it replaces.
contract FairBindReentryTest is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant PENALTY = 10_000_000;
    uint256 internal constant SHARE = PENALTY / 3;
    ReentryLogVm internal constant LOGS = ReentryLogVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant ACTIVE = uint8(FairBindCore.SellerStatus.ACTIVE);
    uint8 internal constant SUSPENDED = uint8(FairBindCore.SellerStatus.SUSPENDED);
    uint8 internal constant SANCTIONED = uint8(FairBindCore.SellerStatus.SANCTIONED);
    uint8 internal constant EXITING = uint8(FairBindCore.SellerStatus.EXITING);
    uint8 internal constant EXITED = uint8(FairBindCore.SellerStatus.EXITED);
    uint8 internal constant FROZEN = uint8(FairBindCore.FreezeState.FROZEN);
    uint8 internal constant CLAIM_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);
    uint8 internal constant CLAIM_CLOSED = uint8(FairBindCore.FreezeState.CLAIM_CLOSED);
    uint8 internal constant DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);
    uint8 internal constant FROZEN_CLAIMABLE = uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE);
    uint8 internal constant REFUNDED = uint8(FairBindCore.FinancialState.REFUNDED);
    uint8 internal constant RELEASED = uint8(FairBindCore.FinancialState.RELEASED);
    uint8 internal constant FORFEITED = uint8(FairBindCore.FinancialState.FORFEITED);
    uint8 internal constant PARTY_REVIEW = uint8(FairBindCore.CaseState.PARTY_REVIEW);
    uint8 internal constant TIEBREAK = uint8(FairBindCore.CaseState.TIEBREAK);
    uint8 internal constant CASE_INCONCLUSIVE = uint8(FairBindCore.CaseState.INCONCLUSIVE);
    uint8 internal constant INITIAL_VERDICT = uint8(FairBindCore.CaseState.INITIAL_VERDICT);
    uint8 internal constant AUTO_REVIEW = uint8(FairBindCore.CaseState.AUTO_REVIEW);

    // ------------------------------------------------------------- helpers

    function _bondId() internal view returns (uint32) {
        return fairbind.getSeller(sellerId).bondId;
    }

    function _bond() internal view returns (FairBindCore.BondView memory) {
        return fairbind.getBond(_bondId());
    }

    function _status() internal view returns (uint8) {
        return fairbind.getSeller(sellerId).status;
    }

    function _emptyProof() internal pure returns (FairBindCore.ReceiptProof memory) {
        return FairBindCore.ReceiptProof(0, 0, new bytes32[](0));
    }

    function _claimWith(bytes32 n, FairBindCore.ReceiptProof memory proof) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.claimRefund(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), proof);
    }

    function claimExternal(bytes32 n, FairBindCore.ReceiptProof memory proof) external {
        _claimWith(n, proof);
    }

    function _topUp(uint256 amount) internal {
        uint32 bondId = _bondId();
        token.mint(SELLER_OWNER, amount);
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bondId, uint128(amount));
    }

    function _reinstate() internal {
        hv.prank(SELLER_OWNER);
        fairbind.reinstateSeller(sellerId);
    }

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

    /// A beacon block hash under which none of the given purchases is sampled.
    function _unsampledBeacon(uint24 epoch, bytes32[] memory ns) internal view returns (bytes32 h) {
        uint256 ppm = fairbind.getServiceProfile(PROFILE).parameters.samplePpm;
        uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
        for (uint256 salt;; salt++) {
            h = keccak256(abi.encode("beacon", epoch, salt));
            bool any;
            for (uint256 i; i < ns.length; i++) {
                uint256 v = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, ns[i])));
                if (v < threshold) any = true;
            }
            if (!any) return h;
        }
    }

    /// Anchors and seals one epoch over every purchase the seller made in it;
    /// with unsampled set, the beacon leaves every purchase unsampled.
    function _anchorAndSeal(uint24 epoch, bytes32[] memory ns, bool unsampled) internal {
        _buildTree(ns);
        uint256 base = 300 * (uint256(epoch) + 2);
        if (block.number < base) hv.roll(base);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, epoch, _treeEntries(), uint32(ns.length), keccak256("publication"));
        uint64 rb = fairbind.getAnchor(sellerId, epoch).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, unsampled ? _unsampledBeacon(epoch, ns) : keccak256(abi.encode("beacon", epoch)));
        fairbind.seal(sellerId, epoch);
    }

    function _one(bytes32 a) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](1);
        ns[0] = a;
    }

    function _two(bytes32 a, bytes32 b) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](2);
        ns[0] = a;
        ns[1] = b;
    }

    function _appealBySeller(bytes32 n) internal {
        token.mint(SELLER_OWNER, 5_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
    }

    function _sealWith(bytes32 n, bytes32 h) internal {
        uint64 rb = fairbind.getCase(n).randomBlock;
        if (block.number <= rb) hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, h);
        fairbind.sealReviewRandomness(n);
    }

    // ------------------------------------------ failure threshold k(n) = n k

    /// At scale factor one nothing changes: the window's threshold is
    /// failureLimit and its shares sum to one sellerPenalty.
    function test_scaleOneWindowKeepsTheProfileLimit() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[3] memory ns = [_purchase(G), _purchase(G), _purchase(G)];
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        _unserved(ns[0]);
        require(fairbind.getFailureWindowScale(_bondId()) == 1, "window opened at scale one");
        _unserved(ns[1]);
        require(!_bond().sanctioned, "one short of the limit");
        _unserved(ns[2]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.sanctioned && bond.failureCount == 3 && bond.balance == 0, "sanctioned at failureLimit");
        require(fairbind.getLockedForfeit() - lockedBefore == PENALTY, "window total is one penalty");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
        require(_status() == SANCTIONED, "seller sanctioned");
    }

    /// Old rule: a bond at scale factor three was sanctioned at failureLimit
    /// (three) failures although it settles three times as many purchases.
    /// Now its window opens at scale three, sanctions at nine failures, each
    /// failure deducts sellerPenalty / failureLimit, and the ninth takes the
    /// remainder so that the window total is three penalties.
    function test_scaleThreeWindowSanctionsAtThreeTimesTheLimit() public {
        _deploy(_productionProfile());
        _topUp(2 * PENALTY);
        require(_bond().scaleFactor == 3, "scale factor three");
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](9);
        for (uint256 i; i < 9; i++) ns[i] = _purchase(G);
        hv.roll(uint256(fairbind.getPurchase(ns[0]).responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        for (uint256 i; i < 9; i++) {
            hv.prank(buyer);
            fairbind.dispute(ns[i], uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        }
        hv.roll(uint256(fairbind.getCase(ns[0]).serveDue) + 1);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        for (uint256 i; i < 8; i++) {
            fairbind.timeoutServe(ns[i]);
            FairBindCore.BondView memory b = _bond();
            require(b.failureCount == i + 1 && !b.sanctioned, "below n * failureLimit: no sanction");
            require(b.balance == 3 * PENALTY - (i + 1) * SHARE, "one share per failure");
        }
        require(fairbind.getFailureWindowScale(_bondId()) == 3, "window keeps the scale it opened at");
        require(_bond().scaleFactor < 3, "the live scale factor fell with the deductions");
        require(_status() == SUSPENDED, "suspended, not sanctioned, after three failures");
        fairbind.timeoutServe(ns[8]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.failureCount == 9 && bond.sanctioned && bond.balance == 0, "sanctioned at 3 * failureLimit");
        require(fairbind.getLockedForfeit() - lockedBefore == 3 * PENALTY, "window total is three penalties");
        require(token.balanceOf(TREASURY) == treasuryBefore, "nothing to the treasury");
        require(_status() == SANCTIONED, "seller sanctioned");
    }

    // ------------------------------- window scale rule and top-up (ADR 0022)

    /// Opens a non-delivery dispute on every purchase and moves past the serve
    /// deadline; each timeoutServe then confirms one failure.
    function _disputeAll(bytes32[] memory ns) internal {
        hv.roll(uint256(fairbind.getPurchase(ns[0]).responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        for (uint256 i; i < ns.length; i++) {
            hv.prank(buyer);
            fairbind.dispute(ns[i], uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        }
        hv.roll(uint256(fairbind.getCase(ns[ns.length - 1]).serveDue) + 1);
    }

    function _purchases(uint256 count) internal returns (bytes32[] memory ns) {
        ns = new bytes32[](count);
        for (uint256 i; i < count; i++) ns[i] = _purchase(G);
    }

    /// Only the bond account owner may top up. Old rule: anyone could, and a
    /// third party could move the account's scale factor.
    function test_topUpByANonOwnerIsRefused() public {
        _deploy(_productionProfile());
        uint32 bondId = _bondId();
        token.mint(buyer, PENALTY);
        hv.prank(buyer);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fairbind.topUpBond(bondId, uint128(PENALTY));
        require(_bond().balance == PENALTY && _bond().scaleFactor == 1, "balance and scale unchanged");
        _topUp(PENALTY);
        require(_bond().scaleFactor == 2, "the owner tops up");
    }

    /// The window records the scale factor before the opening failure's
    /// deduction, and a failure window that opens within retentionBlocks of a
    /// drop opens at the level the account left. Old rule: the second window
    /// opened at the live scale one and sanctioned at failureLimit although
    /// the account had settled at scale two within the case horizon.
    function test_aRecentDropKeepsTheHigherThreshold() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.failureWindowBlocks = 100;
        _deploy(p);
        _topUp(PENALTY);
        hv.roll(10);
        bytes32[] memory ns = _purchases(4);
        _disputeAll(ns);
        fairbind.timeoutServe(ns[0]);
        require(fairbind.getFailureWindowScale(_bondId()) == 2, "recorded before the deduction");
        require(_bond().scaleFactor == 1, "the deduction lowered the live scale");
        FairBindCore.ScaleHigh memory high = fairbind.getRecentScaleHigh(_bondId());
        require(high.scale == 2 && high.dropBlock == _bond().failureWindowStart, "drop from two recorded");
        hv.roll(uint256(_bond().failureWindowStart) + 101);
        fairbind.timeoutServe(ns[1]);
        require(_bond().failureCount == 1, "a new window opened");
        require(fairbind.getFailureWindowScale(_bondId()) == 2, "opened at the level before the drop");
        fairbind.timeoutServe(ns[2]);
        fairbind.timeoutServe(ns[3]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.failureCount == 3 && !bond.sanctioned, "three failures are below 2 * failureLimit");
        require(bond.balance == 2 * PENALTY - 4 * SHARE, "one share per failure");
    }

    /// A drop older than retentionBlocks (caseHorizon plus the keeper margin)
    /// no longer counts: the window opens at the live scale.
    function test_aDropOlderThanTheHorizonGivesTheLiveScale() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.failureWindowBlocks = 100;
        _deploy(p);
        _topUp(PENALTY);
        hv.roll(10);
        bytes32[] memory ns = _purchases(4);
        _disputeAll(ns);
        fairbind.timeoutServe(ns[0]);
        uint64 dropBlock = fairbind.getRecentScaleHigh(_bondId()).dropBlock;
        hv.roll(uint256(dropBlock) + p.retentionBlocks + 1);
        fairbind.timeoutServe(ns[1]);
        require(fairbind.getFailureWindowScale(_bondId()) == 1, "old drop ignored");
        fairbind.timeoutServe(ns[2]);
        require(!_bond().sanctioned, "one short of failureLimit");
        fairbind.timeoutServe(ns[3]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.failureCount == 3 && bond.sanctioned, "sanctioned at failureLimit");
        require(bond.balance == 2 * PENALTY - SHARE - PENALTY, "the window charged one penalty");
    }

    /// A top-up that raises the scale factor during an open window raises the
    /// window's scale: the threshold becomes 2 * failureLimit and the window
    /// charges two penalties. Old rule: the window kept scale one and
    /// sanctioned at failureLimit.
    function test_topUpDuringTheWindowRaisesTheThreshold() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32[] memory ns = _purchases(6);
        _disputeAll(ns);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        fairbind.timeoutServe(ns[0]);
        require(fairbind.getFailureWindowScale(_bondId()) == 1, "opened at scale one");
        _topUp(2 * PENALTY - _bond().balance);
        require(_bond().scaleFactor == 2, "scale two after the top-up");
        require(fairbind.getFailureWindowScale(_bondId()) == 2, "the open window follows the top-up");
        for (uint256 i = 1; i < 5; i++) {
            fairbind.timeoutServe(ns[i]);
            require(!_bond().sanctioned, "below 2 * failureLimit");
        }
        require(_status() == SUSPENDED, "suspended, not sanctioned, after five failures");
        fairbind.timeoutServe(ns[5]);
        FairBindCore.BondView memory bond = _bond();
        require(bond.failureCount == 6 && bond.sanctioned, "sanctioned at 2 * failureLimit");
        require(fairbind.getLockedForfeit() - lockedBefore == 2 * PENALTY, "the window charged two penalties");
        require(bond.balance == SHARE, "what was above two penalties stays");
    }

    // ----------------------------- worst judgment path (positive control)

    /// Hold period of the positive control: between the prompt initial FAIL
    /// (at the case opening, block 1470) and the initial FAIL of the worst
    /// path (after two assignment timeouts, block 3272), for purchases settled
    /// at block 10.
    uint256 internal constant SHORT_HOLD = 2_400;

    /// A beacon under which the first purchase is sampled and the second is not.
    function _onlyFirstSampled(uint24 epoch, bytes32 a, bytes32 b) internal view returns (bytes32 h) {
        uint256 ppm = fairbind.getServiceProfile(PROFILE).parameters.samplePpm;
        uint256 threshold = type(uint256).max / PPM * ppm + ((type(uint256).max % PPM + 1) * ppm) / PPM;
        for (uint256 salt;; salt++) {
            h = keccak256(abi.encode("worst path beacon", epoch, salt));
            bool sa = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, a))) < threshold;
            bool sb = uint256(keccak256(abi.encode(fairbind.SAMPLE_DOMAIN(), h, sellerId, epoch, b))) < threshold;
            if (sa && !sb) return h;
        }
    }

    /// Two bad sales in epoch 0: the first is sampled and its case opened, the
    /// second is never sampled. The hold period is SHORT_HOLD, below the case
    /// horizon, on the override build, which then freezes at the initial FAIL.
    function _shortHoldPair() internal returns (bytes32 n, bytes32 m) {
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        p.deferBlocks = uint32(SHORT_HOLD);
        p.retentionBlocks = uint32(SHORT_HOLD);
        p.claimWindowBlocks = uint32(SHORT_HOLD);
        // The bond covers the rate term up to the judgment delay of ADR 0024.
        p.sellerPenalty = 15_000_000;
        _deploy(p);
        require(fairbind.getServiceProfile(PROFILE).parameters.freezeOnInitialFail, "early freeze below the horizon");
        hv.roll(10);
        n = _purchase(G);
        m = _purchase(G);
        _buildTree(_two(n, m));
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 2, keccak256("publication"));
        uint64 rb = fairbind.getAnchor(sellerId, 0).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, _onlyFirstSampled(0, n, m));
        fairbind.seal(sellerId, 0);
        fairbind.openSample(n);
        // The worst path keeps the receipt on chain in time (rule D2-17): the
        // initial verdict comes after the receipt deadline, and a verdict
        // that finds the receipt missing ends the case UNSERVED (ADR 0025).
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.submitSampleReceipt(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(n));
    }

    /// caseHorizon of profile-v1 section 3 (ADR 0024) for the deployed profile.
    function _caseHorizon() internal view returns (uint256) {
        FairBindCore.ServiceProfileInput memory p = fairbind.getServiceProfile(PROFILE).parameters;
        FairBindCore.DeadlineConfig memory d = fairbind.getDeadlineConfig(p.deadlineConfigId);
        uint256 a = p.maxAssignments;
        uint256 open = 2 * uint256(p.epochBlocks) + d.anchorBlocks + p.beaconDelayBlocks + d.sealBlocks + d.openBlocks;
        uint256 alt = uint256(d.responseBlocks) + d.claimBlocks;
        uint256 delivered = (open < alt ? open : alt) + 3 * uint256(d.serveBlocks);
        if (alt > open) open = alt;
        if (delivered > open) open = delivered;
        return open + 3 * a * (2 * uint256(d.judgeBlocks) + 3 * uint256(d.serveBlocks))
            + a * (uint256(d.appealBlocks) + d.evidenceBlocks) + d.appealBlocks + 3 * (a - 1)
            + 2 * (2 * uint256(d.sealBlocks) + 3) + 1 + p.marginBlocks;
    }

    /// Every assignment of the current stage but the last times out, and the
    /// chain moves to the judge deadline of the last one.
    function _timeOutAllButLast(bytes32 n) internal {
        uint256 attempts = fairbind.getServiceProfile(PROFILE).parameters.maxAssignments;
        for (uint256 i = 1; i < attempts; i++) {
            hv.roll(uint256(fairbind.getCase(n).judgeDue) + 1);
            fairbind.timeoutJudge(n);
        }
        hv.roll(fairbind.getCase(n).judgeDue);
    }

    /// The seal window of a waiting review stage lapses once; the reopening
    /// records the hash of the unchanged randomBlock and the reopened stage
    /// is sealed at the last block of its new window (ADR 0025).
    function _lapseAndSeal(bytes32 n) internal {
        uint256 sealing = fairbind.getDeadlineConfig(1).sealBlocks;
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + sealing + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("review", n, rb)));
        fairbind.sealReviewRandomness(n);
        require(fairbind.getCase(n).randomBlock == rb && fairbind.getCase(n).assignedVerifierId == 0, "stage reopened");
        require(fairbind.getReviewResealDue(n) == block.number + 1 + sealing, "reopened window");
        hv.roll(fairbind.getReviewResealDue(n));
        fairbind.sealReviewRandomness(n);
        require(fairbind.getCase(n).assignedVerifierId != 0, "reopened stage sealed");
    }

    /// From the initial FAIL at its deadline to the tiebreak's confirming
    /// FAIL: the seller requests evidence at the appeal deadline, the evidence
    /// is disclosed at its deadline, the seller appeals at the renewed
    /// deadline, every review seal lapses once, all assignments but the last
    /// time out in the party review, the party review overturns, and every
    /// verdict lands at its judge deadline.
    function _worstPathAfterInitialFail(bytes32 n) internal {
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        hv.roll(fairbind.getReview(n).appealUntil);
        hv.prank(SELLER_OWNER);
        fairbind.requestEvidence(n, c.stage, c.attempt);
        hv.roll(fairbind.getCase(n).evidenceDue);
        fairbind.discloseEvidence(n, c.stage, c.attempt, EVIDENCE);
        hv.roll(fairbind.getReview(n).appealUntil);
        token.mint(SELLER_OWNER, 5_000_000);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        _lapseAndSeal(n);
        _timeOutAllButLast(n);
        _judge(n, PASS);
        require(fairbind.getCase(n).state == TIEBREAK, "the overturn goes to the tiebreak");
        _lapseAndSeal(n);
        // Seven of the test verifiers are now used; the tiebreak verifier
        // answers at its deadline without timeouts, as in the recorded run.
        hv.roll(fairbind.getCase(n).judgeDue);
        _judge(n, FAIL);
    }

    /// Positive control of the I6 worst path. With a hold period below the
    /// case horizon, the worst path's initial FAIL (after two assignment
    /// timeouts, at the judge deadline) comes after the release block of a bad
    /// sale settled beside the detected one, which reaches the seller: a leak
    /// that the prompt path (next test) does not have. The rest of the worst
    /// path (evidence, appeal, both review seals reopened, tiebreak) runs to
    /// the confirmed failure and stays within caseHorizon.
    function test_worstPathOutlastsAShortHoldAndLeaks() public {
        (bytes32 n, bytes32 m) = _shortHoldPair();
        uint256 settled = fairbind.getPurchase(n).settledBlock;
        _timeOutAllButLast(n);
        require(block.number > settled + SHORT_HOLD, "the worst initial FAIL comes after the release block");
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(m);
        require(token.balanceOf(SELLER_OWNER) - ownerBefore == G, "the later bad sale reached the seller");
        _judge(n, FAIL);
        require(_bond().freezeState == FROZEN, "frozen at the initial FAIL, too late for the other sale");
        _worstPathAfterInitialFail(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.finalVerdict == FAIL && _bond().failureCount == 1, "confirmed failure");
        require(_bond().freezeState == CLAIM_OPEN, "claim window at the confirmed failure");
        require(fairbind.purchaseState(m) == RELEASED, "released before the failure: the leak");
        uint8 both = uint8((1 << uint8(FairBindCore.JudgmentStage.PARTY)) | (1 << uint8(FairBindCore.JudgmentStage.TIEBREAK)));
        require(fairbind.getReviewReseals(n) == both, "both review seals reopened");
        uint256 elapsed = block.number - settled;
        require(elapsed <= _caseHorizon(), "the worst path stays within caseHorizon");
        _log("worst path blocks from settlement to confirmed failure", elapsed);
        _log("caseHorizon", _caseHorizon());
        _log("judgmentDelayBlocks", fairbind.judgmentDelayBlocks(PROFILE));
    }

    /// Control: on the prompt path the initial FAIL lands at the case opening,
    /// before the release block, so the other bad sale is held and then frozen
    /// and claimable at the confirmed failure, not released.
    function test_promptPathHoldsTheOtherSale() public {
        (bytes32 n, bytes32 m) = _shortHoldPair();
        uint256 settled = fairbind.getPurchase(n).settledBlock;
        _judge(n, FAIL);
        require(block.number < settled + SHORT_HOLD, "initial FAIL within the hold");
        hv.roll(settled + SHORT_HOLD + 1);
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(m);
        fairbind.finalizeCase(n);
        require(fairbind.purchaseState(m) == FROZEN_CLAIMABLE, "frozen and claimable, not released");
    }

    // ------------------------------------------ re-entry during CLAIM_OPEN

    /// Old rule: reinstatement waited for the closed claim window, and the
    /// account admitted no settlement while it was open. Now the seller tops
    /// up the deducted share and re-enters at once; what it sells is outside
    /// the frozen window, is neither claimable nor forfeited, and is released
    /// on the normal schedule.
    function test_reinstatementDuringTheClaimWindowReopensTheAccount() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32 w = _purchase(G);
        bytes32 d = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && _status() == SUSPENDED, "claim window open");
        uint64 frozenAt = bond.freezeBlock;
        // Below one penalty after the deduction: a top-up is needed first.
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
        fairbind.reinstateSeller(sellerId);
        _topUp(SHARE);
        _reinstate();
        require(_status() == ACTIVE && fairbind.getClaimReentry(_bondId()).reopened, "reinstated into the open window");
        hv.roll(block.number + 20);
        bytes32 x = _purchase(G);
        require(fairbind.getPurchase(x).settledBlock > frozenAt, "settled after the frozen window");
        require(fairbind.purchaseState(x) == DEFERRED, "outside the frozen window");
        require(fairbind.getClaimReentry(_bondId()).deferredBalance == G, "tracked apart");
        require(fairbind.getFrozenPool(_bondId()).poolBalance == G, "the pool is the frozen window only");
        hv.expectRevert(FairBindCore.ReceiptOutOfWindow.selector);
        this.claimExternal(x, _emptyProof());
        _claimWith(w, _emptyProof());
        require(fairbind.getPurchase(w).financialState == REFUNDED, "window entry claimed");

        // Anchor and seal epoch 1 (x alone) so that x can be released later.
        _anchorAndSeal(fairbind.getPurchase(x).epoch, _one(x), true);
        hv.roll(uint256(_bond().claimUntilBlock) + 1);
        uint256 forfeitedBefore = _bond().forfeitedTotal;
        fairbind.forfeitUnclaimed(_bondId());
        bond = _bond();
        require(bond.freezeState == CLAIM_CLOSED && bond.forfeitedTotal == forfeitedBefore, "nothing of x forfeited");
        require(bond.deferredBalance == G && fairbind.purchaseState(x) == DEFERRED, "x still deferred");
        require(!fairbind.getClaimReentry(_bondId()).reopened, "re-entry state cleared with the window");
        hv.roll(uint256(fairbind.getPurchase(x).releaseBlock));
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(x);
        require(fairbind.getPurchase(x).financialState == RELEASED, "released on schedule");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore + G, "principal to the seller");
    }

    /// Old rule: _freeze returned early while the claim window was open, so
    /// a second confirmed failure left every purchase settled after the
    /// reinstatement outside the frozen window and releasable to the failing
    /// seller. Now the second confirmed failure moves freezeBlock to its
    /// block: those purchases are frozen and claimable once, the account
    /// admits nothing until the next reinstatement, and forfeiture waits for
    /// the extended window.
    function test_secondFailureAfterReentryMovesTheFrozenWindow() public {
        _deploy(_productionProfile());
        hv.roll(10);
        bytes32 w = _purchase(G);
        bytes32 d = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        uint64 firstUntil = _bond().claimUntilBlock;
        _topUp(SHARE);
        _reinstate();
        // The bucket was clipped to zero below one penalty; it refills at 0.05 per block.
        hv.roll(block.number + 60);
        bytes32 x = _purchase(G);
        bytes32 y = _purchase(G);
        _unserved(y);
        fairbind.claimRefund(y);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.failureCount == 2, "second failure counted in the open window");
        require(bond.freezeBlock == block.number, "freezeBlock moved to the second confirmed failure");
        require(bond.claimUntilBlock == block.number + 40_000 && bond.claimUntilBlock > firstUntil, "window extended");
        require(fairbind.purchaseState(x) == FROZEN_CLAIMABLE, "entry settled after the reinstatement is frozen");
        FairBindCore.ClaimReentry memory late = fairbind.getClaimReentry(_bondId());
        require(!late.reopened && late.deferredBalance == 0 && late.encumbered == 0, "re-entry state cleared");
        require(_status() == SUSPENDED, "suspended again");
        SettleArgs memory s = _settleArgs(G);
        hv.expectRevert(FairBindCore.SellerIsSuspended.selector);
        _settle(s);
        // The frozen entry is held, claimed once, and never released.
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(x);
        _claimWith(x, _emptyProof());
        require(fairbind.getPurchase(x).financialState == REFUNDED, "claimed");
        hv.expectRevert(FairBindCore.AlreadyClaimed.selector);
        this.claimExternal(x, _emptyProof());
        // Forfeiture waits for the extended window.
        uint32 bondId = _bondId();
        hv.roll(uint256(firstUntil) + 1);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.forfeitUnclaimed(bondId);
        _claimWith(w, _emptyProof());
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bondId);
        bond = _bond();
        require(bond.freezeState == CLAIM_CLOSED && bond.forfeitedTotal == 0, "nothing left to forfeit");
        require(bond.deferredBalance == 0, "every entry of both windows refunded");
    }

    /// With freezeOnInitialFail (override build), an initial FAIL on a
    /// purchase settled after the reinstatement holds every entry through its
    /// pending trigger but leaves the confirmed window as it was: an overturn
    /// returns the later entries to their schedule and keeps them out of the
    /// claims, while the window of the first failure keeps its entries.
    function test_overturnedInitialFailAfterReentryLeavesTheConfirmedWindow() public {
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 w = _purchase(G);
        bytes32 d = _purchase(G);
        _unserved(d);
        fairbind.claimRefund(d);
        uint64 frozenAt = _bond().freezeBlock;
        _topUp(SHARE);
        _reinstate();
        // The bucket was clipped to zero below one penalty; it refills at 0.05 per block.
        hv.roll(460);
        bytes32 x = _purchase(G);
        bytes32 z = _purchase(G);
        _anchorAndSeal(fairbind.getPurchase(z).epoch, _two(x, z), true);
        FairBindCore.FairBindReceipt memory r = _receipt(z);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(z, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        fairbind.assignVerifier(z);
        _judge(z, FAIL);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.freezeBlock == frozenAt, "initial FAIL leaves the window");
        require(fairbind.getFreezeTriggers(_bondId()).count == 1 && _status() == SUSPENDED, "pending and suspended");
        // The pending trigger holds the later entry; nothing settles.
        hv.expectRevert(FairBindCore.FrozenEntry.selector);
        fairbind.releasePurchase(x);
        hv.expectRevert(FairBindCore.ReceiptOutOfWindow.selector);
        this.claimExternal(x, _proof(x));
        // The seller appeals; the party review and the tiebreak overturn it.
        _appealBySeller(z);
        _sealWith(z, keccak256("party"));
        _judge(z, PASS);
        _sealWith(z, keccak256("tiebreak"));
        _judge(z, PASS);
        require(fairbind.getCase(z).finalVerdict == PASS, "overturned");
        bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.freezeBlock == frozenAt && bond.failureCount == 1,
            "the confirmed window is unchanged and nothing more is counted");
        require(fairbind.getFreezeTriggers(_bondId()).count == 0, "no trigger left");
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(x);
        hv.expectRevert(FairBindCore.ReceiptOutOfWindow.selector);
        this.claimExternal(x, _proof(x));
        _claimWith(w, _emptyProof());
        require(fairbind.getPurchase(w).financialState == REFUNDED, "window entry still claimable");
        _reinstate();
        require(_status() == ACTIVE, "reinstated after the overturn");
    }

    /// The same initial FAIL confirmed: the confirmed failure moves the window
    /// over every entry the pending trigger held.
    function test_confirmedInitialFailAfterReentryMovesTheWindow() public {
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        _purchase(G);
        bytes32 d = _purchase(G);
        _unserved(d);
        uint64 frozenAt = _bond().freezeBlock;
        _topUp(SHARE);
        _reinstate();
        // The bucket was clipped to zero below one penalty; it refills at 0.05 per block.
        hv.roll(460);
        bytes32 x = _purchase(G);
        bytes32 z = _purchase(G);
        _anchorAndSeal(fairbind.getPurchase(z).epoch, _two(x, z), true);
        FairBindCore.FairBindReceipt memory r = _receipt(z);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(z, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        fairbind.assignVerifier(z);
        _judge(z, FAIL);
        hv.roll(uint256(fairbind.getReview(z).appealUntil) + 1);
        fairbind.finalizeCase(z);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeBlock == block.number && bond.freezeBlock > frozenAt, "window moved to the confirmation");
        require(bond.failureCount == 2 && fairbind.getFreezeTriggers(_bondId()).count == 0, "counted, none pending");
        require(fairbind.purchaseState(x) == FROZEN_CLAIMABLE, "later entry claimable");
        _claimWith(x, _proof(x));
        require(fairbind.getPurchase(x).financialState == REFUNDED, "claimed");
    }

    // -------------------------------------------- review seal reopens once

    /// Old rule: a party review whose randomness block hash was unavailable
    /// ended the case as a protocol INCONCLUSIVE at once and returned the
    /// appeal deposit. Since ADR 0021 the first failure reopens the seal and
    /// keeps the deposit; since ADR 0025 the reopened seal keeps randomBlock,
    /// and the hash of that same block assigns the reviewer.
    function test_missingPartyReviewHashReopensTheSealOnce() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        _anchorAndSeal(0, _one(n), false);
        fairbind.openSample(n);
        _judge(n, FAIL);
        _appealBySeller(n);
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        LOGS.recordLogs();
        uint64 rb = fairbind.getCase(n).randomBlock;
        _sealWith(n, bytes32(0));
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == PARTY_REVIEW && c.assignedVerifierId == 0, "still in party review");
        require(c.randomBlock == rb, "reopened on the same randomBlock");
        require(fairbind.getReviewReseals(n) == uint8(1) << uint8(FairBindCore.JudgmentStage.PARTY), "stage marked");
        require(fairbind.getReview(n).deposit == 5_000_000 && token.balanceOf(SELLER_OWNER) == ownerBefore, "deposit held");
        ReentryLogVm.Log[] memory logs = LOGS.getRecordedLogs();
        bytes32 topic = keccak256("ReviewResealed(bytes32,uint8,uint64)");
        uint256 seen;
        for (uint256 i; i < logs.length; i++) if (logs[i].topics[0] == topic) seen++;
        require(seen == 1, "ReviewResealed emitted once");
        _sealWith(n, keccak256("fresh"));
        require(fairbind.getCase(n).assignedVerifierId != 0, "reviewer assigned after the fresh seal");
    }

    /// The second failure in the same stage ends the case; finalizeCase past
    /// the seal window reopens first as well. Before ADR 0024 a seller's
    /// party review ended as a protocol INCONCLUSIVE and returned the appeal
    /// deposit; now the initial FAIL stands and the deposit goes to the buyer.
    function test_secondSealFailureInAStageEndsTheCase() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        _anchorAndSeal(0, _one(n), false);
        fairbind.openSample(n);
        _judge(n, FAIL);
        _appealBySeller(n);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 201);
        fairbind.finalizeCase(n);
        require(fairbind.getCase(n).state == PARTY_REVIEW, "past the seal window: reopened, not ended");
        require(fairbind.getCase(n).randomBlock == rb, "randomBlock kept");
        hv.roll(uint256(fairbind.getReviewResealDue(n)) + 1);
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        uint256 buyerBefore = token.balanceOf(buyer);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.FINAL) && c.finalVerdict == FAIL, "second failure in the stage upholds the initial FAIL");
        require(token.balanceOf(SELLER_OWNER) == ownerBefore, "appeal deposit not returned");
        require(token.balanceOf(buyer) == buyerBefore + 5_000_000, "appeal deposit to the buyer");
    }

    /// Each review stage has its own reopen: after the party review used
    /// its reopen, the tiebreak can still reopen once.
    function test_tiebreakHasItsOwnReopen() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        _anchorAndSeal(0, _one(n), false);
        fairbind.openSample(n);
        _judge(n, FAIL);
        _appealBySeller(n);
        _sealWith(n, bytes32(0));
        _sealWith(n, keccak256("party"));
        _judge(n, PASS);
        require(fairbind.getCase(n).state == TIEBREAK, "disagreement goes to the tiebreak");
        _sealWith(n, bytes32(0));
        require(fairbind.getCase(n).state == TIEBREAK, "tiebreak reopened, not ended");
        uint8 both = (uint8(1) << uint8(FairBindCore.JudgmentStage.PARTY))
            | (uint8(1) << uint8(FairBindCore.JudgmentStage.TIEBREAK));
        require(fairbind.getReviewReseals(n) == both, "both stages marked");
        _sealWith(n, keccak256("tiebreak"));
        require(fairbind.getCase(n).assignedVerifierId != 0, "tiebreak verifier assigned");
    }

    /// Old rule: an unappealed PASS whose recheck candidate block hash was
    /// gone ended as a protocol INCONCLUSIVE. Since ADR 0021 the recheck gate
    /// reopens once; since ADR 0025 the same candidate block decides it.
    function test_expiredRecheckCandidateReopensOnce() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 1_000_000;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        _anchorAndSeal(0, _one(n), false);
        fairbind.openSample(n);
        _judge(n, PASS);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 201);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == INITIAL_VERDICT && c.randomBlock == rb, "gate reopened on the same candidate block");
        hv.roll(block.number + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.finalizeCase(n);
        require(fairbind.getCase(n).state == AUTO_REVIEW, "recheck selected on the fresh candidate block");
    }

    // ------------------------------------------ exit does not skip the freeze

    /// A seller that requests exit right after an initial FAIL is still
    /// frozen, deducted and opens the claim window at the confirmed failure,
    /// and cannot reach EXITED before the frozen pool is closed. The old rule
    /// let it exit once exitEligibleBlock passed, with the claim window open.
    function _exitAfterInitialFail(bool freezeOnInitialFail) internal {
        FairBindCore.ServiceProfileInput memory p = freezeOnInitialFail ? _baseProfile() : _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        bytes32 other = _purchase(G);
        _anchorAndSeal(0, _two(n, other), false);
        fairbind.openSample(n);
        _judge(n, FAIL);
        require(_bond().freezeState == (freezeOnInitialFail ? FROZEN : 0), "freeze timing of the profile");
        uint32 bondId = _bondId();
        hv.prank(SELLER_OWNER);
        fairbind.requestSellerExit(sellerId);
        hv.prank(SELLER_OWNER);
        fairbind.requestBondExit(bondId);
        require(_status() == EXITING, "exiting");
        uint64 eligible = fairbind.getSeller(sellerId).exitEligibleBlock;
        hv.roll(uint256(fairbind.getReview(n).appealUntil) + 1);
        fairbind.finalizeCase(n);
        FairBindCore.BondView memory bond = _bond();
        require(bond.freezeState == CLAIM_OPEN && bond.freezeBlock <= block.number, "frozen, claim window open");
        require(bond.failureCount == 1 && bond.balance == PENALTY - SHARE, "counted and deducted");
        require(fairbind.purchaseState(other) == FROZEN_CLAIMABLE, "the other purchase is in the frozen window");
        require(_status() == EXITING, "still exiting");
        require(bond.claimUntilBlock > eligible, "claim window outlives the exit delay");
        hv.roll(eligible);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ExitNotReady.selector);
        fairbind.finalizeSellerExit(sellerId);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ExitNotReady.selector);
        fairbind.finalizeBondExit(bondId);
        hv.roll(uint256(bond.claimUntilBlock) + 1);
        fairbind.forfeitUnclaimed(bondId);
        hv.prank(SELLER_OWNER);
        fairbind.finalizeSellerExit(sellerId);
        require(_status() == EXITED, "exit after the pool closed");
    }

    function test_exitAfterInitialFailIsFrozenAndDeductedWithoutEarlyFreeze() public {
        _exitAfterInitialFail(false);
    }

    function test_exitAfterInitialFailIsFrozenAndDeductedWithEarlyFreeze() public {
        _exitAfterInitialFail(true);
    }
}
