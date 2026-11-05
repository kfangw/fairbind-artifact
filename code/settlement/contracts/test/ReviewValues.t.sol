// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";

/// ADR 0036: review stages of a batched case draw from the AUX value of the
/// transaction that opened them (appeal, recheck selection, the verdict that
/// leads to the tiebreak), and their unanswered values exit as the rule
/// sets; AUX and sampling values that come late pause the account's release
/// clock from the block after their bound.
contract ReviewValuesTest is BatchBase {
    uint8 internal constant PARTY = uint8(FairBindCore.JudgmentStage.PARTY);
    uint8 internal constant AUTO = uint8(FairBindCore.JudgmentStage.AUTO);
    uint8 internal constant TIEBREAK = uint8(FairBindCore.JudgmentStage.TIEBREAK);
    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);

    /// One sample case of epoch 0 assigned in batch 0 and judged once.
    function _judgedOnce(uint8 verdict, uint32 recheckPpm) internal returns (bytes32 n, uint32 first, uint64 version) {
        FairBindCore.ServiceProfileInput memory p = _batchProfile();
        p.recheckPpm = recheckPpm;
        _deployBatched(p, _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        n = ns[0];
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        _assignBatch(0);
        (,, version,,,) = fb.getBatch(PROFILE, 0);
        first = fairbind.getCase(n).assignedVerifierId;
        require(first != 0, "started");
        _judgeBatched(n, verdict);
        hv.roll(_now() + 1);
    }

    function _taken(uint32 a) internal pure returns (uint32[] memory t) {
        t = new uint32[](1);
        t[0] = a;
    }

    function _taken(uint32 a, uint32 b) internal pure returns (uint32[] memory t) {
        t = new uint32[](2);
        t[0] = a;
        t[1] = b;
    }

    function _taken(uint32 a, uint32 b, uint32 c) internal pure returns (uint32[] memory t) {
        t = new uint32[](3);
        t[0] = a;
        t[1] = b;
        t[2] = c;
    }

    // --------------------------------------------- review stage values

    /// The buyer's appeal registers the party review's use in its block; the
    /// value is asked for from the next block; the block-hash seal and the
    /// reseal exit are closed. The candidate is the first round of the AUX
    /// value that skips the initial verifier; a judgment timeout moves to the
    /// next attempt on the same value. The disagreeing verdict registers the
    /// tiebreak's use, whose own value picks the third verifier.
    function test_appealAndTiebreakDrawFromTheirAuxValues() public {
        (bytes32 n, uint32 first, uint64 version) = _judgedOnce(PASS, 0);
        hv.prank(buyer);
        fairbind.appeal(n);
        uint64 t = uint64(_now());
        BatchStore.ReviewUse memory u = fb.getReviewUse(n);
        require(u.stage == PARTY && u.registered == t, "the appeal registers the use");
        require(_state(n) == uint8(FairBindCore.CaseState.PARTY_REVIEW) && fairbind.getCase(n).assignedVerifierId == 0, "waits");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fb.requestReviewValue(n);
        hv.roll(uint256(t) + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.assignReview(n);
        hv.roll(uint256(t) + 3);
        hv.setBlockhash(uint256(t) + 1, keccak256("hash"));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.sealReviewRandomness(n);
        hv.roll(uint256(t) + 1000);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.finalizeCase(n);
        bytes32 value = _fulfill(_reviewId(n));
        uint64 delivered = uint64(_now());
        hv.prank(KEEPER);
        fb.assignReview(n);
        uint32 second = _firstFree(version, value, n, PARTY, 0, _taken(first));
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.assignedVerifierId == second && c.state == uint8(FairBindCore.CaseState.PARTY_REVIEW), "AUX candidate");
        require(c.randomness == value && c.randomBlock == delivered, "value and its block");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.NotRegistered.selector);
        fb.assignReview(n);
        // Judgment timeout: the next attempt draws from the same value.
        hv.roll(uint256(c.judgeDue) + 1);
        hv.prank(KEEPER);
        fairbind.timeoutJudge(n);
        uint32 third = _firstFree(version, value, n, PARTY, 1, _taken(first, second));
        c = fairbind.getCase(n);
        require(c.attempt == 1 && c.assignedVerifierId == third, "next attempt, same value");
        _judgeBatched(n, FAIL);
        u = fb.getReviewUse(n);
        require(u.stage == TIEBREAK && u.registered == _now(), "the verdict registers the tiebreak's use");
        require(_state(n) == uint8(FairBindCore.CaseState.TIEBREAK) && fairbind.getCase(n).assignedVerifierId == 0, "tiebreak waits");
        bytes32 value2 = _reviewValueOf(n);
        uint32 fourth = _firstFree(version, value2, n, TIEBREAK, 0, _taken(first, second, third));
        require(fairbind.getCase(n).assignedVerifierId == fourth, "tiebreak candidate from its own value");
        _judgeBatched(n, PASS);
        require(_state(n) == uint8(FairBindCore.CaseState.FINAL), "ended");
    }

    /// The recheck selection registers the automatic review's use; the case
    /// waits in AUTO_REVIEW until its value places it.
    function test_autoRecheckDrawsFromTheValueOfItsSelection() public {
        (bytes32 n, uint32 first, uint64 version) = _judgedOnce(PASS, 1_000_000);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        hv.roll(uint256(c.randomBlock) + 1);
        hv.setBlockhash(c.randomBlock, keccak256("gate"));
        fairbind.finalizeCase(n);
        BatchStore.ReviewUse memory u = fb.getReviewUse(n);
        require(u.stage == AUTO && u.registered == _now(), "the selection registers the use");
        c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.AUTO_REVIEW) && c.assignedVerifierId == 0, "waits");
        bytes32 value = _reviewValueOf(n);
        require(fairbind.getCase(n).assignedVerifierId == _firstFree(version, value, n, AUTO, 0, _taken(first)), "AUX candidate");
    }

    // ----------------------------------------------------------- exits

    function timeoutReviewExternal(bytes32 n) external {
        fb.timeoutReviewValue(n);
    }

    /// The seller appeals an initial FAIL and the review value never comes:
    /// from the block after the first request + D_V + T_V the exit upholds
    /// the FAIL, a confirmed and counted failure. A build that ends it
    /// without a count is caught.
    function _sellerAppealExitUpholdsTheFail(string memory artifact) internal returns (bool) {
        depositArtifact = artifact;
        (bytes32 n,,) = _judgedOnce(FAIL, 0);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        uint256 t = _now();
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        hv.roll(t + 31);
        (bool early,) = address(this).call(abi.encodeCall(this.timeoutReviewExternal, (n)));
        if (early) return false;
        hv.roll(t + 32);
        (bool ok,) = address(this).call(abi.encodeCall(this.timeoutReviewExternal, (n)));
        if (!ok) return false;
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        FairBindCore.BondView memory b = fairbind.getBond(_bondOfSeller(sellerId));
        return c.state == uint8(FairBindCore.CaseState.FINAL) && c.finalVerdict == FAIL && b.failureCount == 1;
    }

    function test_unansweredReviewOfASellerAppealUpholdsTheFail() public {
        require(_sellerAppealExitUpholdsTheFail(depositArtifact), "first FAIL confirmed");
    }

    function test_sellerAppealExitWithoutCountIsCaught() public {
        require(!_sellerAppealExitUpholdsTheFail("BatchMutants.sol:SellerAppealExitDeposit"), "mutation caught");
    }

    /// The buyer appeals a PASS and the review value never comes: the case
    /// ends without a verdict and without a count, its verifier is released,
    /// the deposit goes back, the account is suspended and frozen with its
    /// claim window open, and the buyer claims the purchase.
    function test_unansweredReviewOfABuyerAppealEndsWithoutCount() public {
        (bytes32 n, uint32 first,) = _judgedOnce(PASS, 0);
        uint256 buyer0 = token.balanceOf(buyer);
        hv.prank(buyer);
        fairbind.appeal(n);
        uint256 t = _now();
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        hv.roll(t + 32);
        hv.prank(KEEPER);
        fb.timeoutReviewValue(n);
        require(_state(n) == uint8(FairBindCore.CaseState.INCONCLUSIVE), "no verdict");
        uint32 bondId = _bondOfSeller(sellerId);
        FairBindCore.BondView memory b = fairbind.getBond(bondId);
        require(b.failureCount == 0 && b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "no count, claim window");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(token.balanceOf(buyer) == buyer0, "deposit back");
        (BatchStore.Slots memory s,) = fb.getSlots(first);
        require(fairbind.getVerifier(first).lockedLiability == 0 && s.active == 0, "verifier released");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.NotRegistered.selector);
        fb.timeoutReviewValue(n);
        _buildTree(_one(n));
        _claimWith(n, _proof(n));
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDED), "claimed");
    }

    function _one(bytes32 n) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](1);
        ns[0] = n;
    }

    // ------------------------------------------------ late value pauses

    /// A sample case opened at 1200, after C_0, waits for its AUX value
    /// (registration block 1200, D_S = 11). Marked late at 1215, the account
    /// counts as paused from 1212; the value used at 1220 ends the pause. A
    /// build that pauses from the call is caught.
    function _lateAuxPausesFrom1212(string memory artifact) internal returns (bool) {
        batchArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(1200);
        _openSample(ns[0]);
        hv.roll(1201);
        hv.prank(KEEPER);
        fb.requestLateValue(ns[0]);
        hv.roll(1211);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.markValueLate(ns[0]);
        hv.roll(1215);
        hv.prank(KEEPER);
        fb.markValueLate(ns[0]);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.markValueLate(ns[0]);
        uint32 bondId = _bondOfSeller(sellerId);
        if (fairbind.pausedSince(bondId, 1200) != 3) return false;
        hv.roll(1220);
        _fulfill(_lateId(ns[0], 1200));
        hv.prank(KEEPER);
        fb.assignLate(ns[0]);
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.JUDGING), "started");
        hv.roll(1230);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        return waiting == 0 && fairbind.pausedSince(bondId, 1200) == 1220 - 1212;
    }

    function test_lateAuxValuePausesFromItsBound() public {
        require(_lateAuxPausesFrom1212(batchArtifact), "paused from t + D_S + 1");
    }

    function test_lateAuxPauseFromTheCallIsCaught() public {
        require(!_lateAuxPausesFrom1212("BatchMutants.sol:LateStartNowBatch"), "mutation caught");
    }

    /// Without a mark, a late value stored at 1230 and used at 1235 still
    /// pauses the account from 1212 to the use.
    function test_unmarkedLateAuxValuePausesAtItsUse() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(1200);
        _openSample(ns[0]);
        hv.roll(1201);
        hv.prank(KEEPER);
        fb.requestLateValue(ns[0]);
        hv.roll(1230);
        _fulfill(_lateId(ns[0], 1200));
        hv.roll(1235);
        hv.prank(KEEPER);
        fb.assignLate(ns[0]);
        hv.roll(1240);
        require(fairbind.pausedSince(_bondOfSeller(sellerId), 1200) == 1235 - 1212, "paused from 1212 to the use");
    }

    /// The review value of a buyer's appeal registered at t is late past
    /// t + D_S: marked at t + 15, the account pauses from t + 12 until the
    /// value places the review at t + 20.
    function test_lateReviewValuePausesFromItsBound() public {
        (bytes32 n,,) = _judgedOnce(PASS, 0);
        hv.prank(buyer);
        fairbind.appeal(n);
        uint256 t = _now();
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        hv.roll(t + 11);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.markValueLate(n);
        hv.roll(t + 15);
        hv.prank(KEEPER);
        fb.markValueLate(n);
        uint32 bondId = _bondOfSeller(sellerId);
        require(fairbind.pausedSince(bondId, uint64(t)) == 3, "paused from t + 12");
        hv.roll(t + 20);
        _fulfill(_reviewId(n));
        hv.prank(KEEPER);
        fb.assignReview(n);
        require(fairbind.getCase(n).assignedVerifierId != 0, "started");
        hv.roll(t + 30);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == 0 && fairbind.pausedSince(bondId, uint64(t)) == 8, "pause ended at the use");
    }

    /// Epoch 0 (A = 700, D_S = 11, M = 731) has no sampling value past 711:
    /// marked at 715, the account pauses from 712; the seal at 721 ends it.
    /// A build that pauses from the call is caught.
    function _lateSamplePausesFrom712(string memory artifact) internal returns (bool) {
        proofArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        hv.roll(701);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 0);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 0);
        hv.roll(711);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.markSampleLate(sellerId, 0);
        hv.roll(715);
        hv.prank(KEEPER);
        fb.markSampleLate(sellerId, 0);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.markSampleLate(sellerId, 0);
        uint32 bondId = _bondOfSeller(sellerId);
        if (fairbind.pausedSince(bondId, 700) != 3) return false;
        hv.roll(720);
        _fulfill(_sampleId(0));
        hv.roll(721);
        hv.prank(KEEPER);
        fairbind.seal(sellerId, 0);
        hv.roll(730);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        return waiting == 0 && fairbind.pausedSince(bondId, 700) == 721 - 712;
    }

    function test_lateSampleValuePausesUntilTheSeal() public {
        require(_lateSamplePausesFrom712(proofArtifact), "paused from A + D_S + 1 to the seal");
    }

    function test_lateSamplePauseFromTheCallIsCaught() public {
        require(!_lateSamplePausesFrom712("BatchMutants.sol:LateStartNowProof"), "mutation caught");
    }

    /// Epoch 1 (A = 1000, M = 1031) never gets its value: marked at 1020,
    /// the account pauses from 1012 until the call past M that notes the
    /// deadline. Another seller's epoch can no longer be marked past M, and a
    /// value the seal would take refuses the mark.
    function test_lateSampleValuePausesUntilItsDeadlineIsNoted() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        _addSellerB();
        hv.roll(310);
        bytes32[] memory a = new bytes32[](1);
        a[0] = _purchase(G);
        bytes32[] memory b = new bytes32[](1);
        b[0] = _purchaseOf(sellerB, G);
        _anchorOf(1, sellerId, SELLER_OWNER, a);
        _anchorOf(1, sellerB, SELLER_B_OWNER, b);
        hv.roll(1001);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 1);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 1);
        hv.roll(1020);
        hv.prank(KEEPER);
        fb.markSampleLate(sellerId, 1);
        hv.roll(1031);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.noteSampleDeadline(sellerId, 1);
        hv.roll(1035);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlinePassed.selector);
        fb.markSampleLate(sellerB, 1);
        hv.prank(KEEPER);
        fb.noteSampleDeadline(sellerId, 1);
        hv.roll(1040);
        uint32 bondId = _bondOfSeller(sellerId);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == 0 && fairbind.pausedSince(bondId, 1000) == 1035 - 1012, "paused from 1012 to the noted deadline");
    }
}
