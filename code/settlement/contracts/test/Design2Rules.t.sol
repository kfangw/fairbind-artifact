// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

/// Case rules of ADR 0024 that apply to every profile: a seller-appealed
/// review that cannot progress upholds the initial FAIL (D2-15), a sampled
/// purchase whose non-delivery dispute ended as delivered still opens its
/// sample case and is not released before it (D2-11), and a sample case
/// without its receipt and inclusion proof on chain in time ends UNSERVED
/// (D2-17). It also fixes two rules the contract already follows: a
/// FINAL(INCONCLUSIVE) above the threshold freezes without counting or
/// deducting (D2-6 (b)), and an anchored epoch releases nothing before its
/// randomness is on chain (D2-16). Each test states the behaviour it replaces.
contract Design2RulesTest is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant APPEAL_DEPOSIT = 5_000_000;
    uint256 internal constant DISPUTE_DEPOSIT = 5_000_000;
    uint256 internal constant VERIFIER_BOND = 10_000_000;
    uint256 internal constant LATE_PENALTY = 500_000;
    uint256 internal constant SELLER_PENALTY = 10_000_000;

    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant INCONCLUSIVE = uint8(FairBindCore.Verdict.INCONCLUSIVE);
    uint8 internal constant FINAL = uint8(FairBindCore.CaseState.FINAL);
    uint8 internal constant CASE_INCONCLUSIVE = uint8(FairBindCore.CaseState.INCONCLUSIVE);
    uint8 internal constant UNSERVED = uint8(FairBindCore.CaseState.UNSERVED);
    uint8 internal constant DELIVERED = uint8(FairBindCore.CaseState.DELIVERED);
    uint8 internal constant REFUNDABLE = uint8(FairBindCore.FinancialState.REFUNDABLE);
    uint8 internal constant HELD = uint8(FairBindCore.FinancialState.HELD);

    function _profile(uint32 samplePpm, uint32 recheckPpm) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = samplePpm;
        p.recheckPpm = recheckPpm;
    }

    function _bondOfSeller() internal view returns (FairBindCore.BondView memory) {
        return fairbind.getBond(fairbind.getSeller(sellerId).bondId);
    }

    function _anchorAndSeal(bytes32[] memory ns, bytes32 beacon) internal {
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, beacon);
        fairbind.seal(sellerId, 0);
    }

    /// One sampled purchase of epoch 0 with its case opened.
    function _openedSample() internal returns (bytes32 n) {
        hv.roll(10);
        n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(n);
    }

    function _appeal(bytes32 n, address appellant) internal {
        token.mint(appellant, APPEAL_DEPOSIT);
        hv.prank(appellant);
        token.approve(address(fairbind), type(uint256).max);
        hv.prank(appellant);
        fairbind.appeal(n);
    }

    function _sealReview(bytes32 n) internal {
        uint64 rb = fairbind.getCase(n).randomBlock;
        if (block.number <= rb) hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("review", n, rb)));
        fairbind.sealReviewRandomness(n);
    }

    function _timeoutAll(bytes32 n) internal {
        for (uint256 i; i < 3; i++) {
            hv.roll(uint256(fairbind.getCase(n).judgeDue) + 1);
            fairbind.timeoutJudge(n);
        }
    }

    // ------------------------------------------- D2-15: seller-appealed reviews

    /// Old rule: every assignment of the seller's party review timing out ended
    /// the case as a protocol INCONCLUSIVE and returned the appeal deposit to
    /// the seller. Now the initial FAIL stands: the case is FINAL(FAIL), the
    /// failure is counted and deducted, the deposit goes to the buyer, and the
    /// late reviewers pay only their late penalty.
    function test_sellerAppealedReviewThatTimesOutUpholdsTheInitialFail() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        uint32 first = fairbind.getCase(n).assignedVerifierId;
        _judge(n, FAIL);
        _appeal(n, SELLER_OWNER);
        _sealReview(n);
        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        _timeoutAll(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "initial FAIL upheld");
        require(fairbind.getPurchase(n).financialState == REFUNDABLE, "refundable");
        require(_bondOfSeller().failureCount == 1, "counted");
        require(_bondOfSeller().balance == SELLER_PENALTY - SELLER_PENALTY / 3, "deducted");
        require(token.balanceOf(buyer) - buyerBefore == APPEAL_DEPOSIT, "appeal deposit to the buyer");
        require(token.balanceOf(TREASURY) - treasuryBefore == 3 * LATE_PENALTY, "late penalties only");
        require(fairbind.getVerifier(first).bond == VERIFIER_BOND, "initial verifier intact");
    }

    /// Old rule: a tiebreak whose every assignment timed out ended the case
    /// INCONCLUSIVE, so a seller could buy the party reviewer's PASS and let
    /// the tiebreak lapse. Now the initial FAIL stands, and the party
    /// reviewer's PASS is not charged a wrong-verdict penalty.
    function test_stalledTiebreakAfterSellerAppealUpholdsTheInitialFail() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        _judge(n, FAIL);
        _appeal(n, SELLER_OWNER);
        _sealReview(n);
        uint32 partyReviewer = fairbind.getCase(n).assignedVerifierId;
        _judge(n, PASS);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.TIEBREAK), "tiebreak");
        _sealReview(n);
        uint256 buyerBefore = token.balanceOf(buyer);
        _timeoutAll(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "initial FAIL upheld");
        require(_bondOfSeller().failureCount == 1, "counted");
        require(fairbind.getVerifier(partyReviewer).bond == VERIFIER_BOND, "no wrong-verdict penalty");
        require(token.balanceOf(buyer) - buyerBefore == APPEAL_DEPOSIT, "appeal deposit to the buyer");
    }

    /// Old rule: two lapsed seals of the seller's party review ended the case
    /// INCONCLUSIVE. Now they uphold the initial FAIL.
    function test_sellerAppealedReviewWhoseSealLapsesTwiceUpholdsTheInitialFail() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        _judge(n, FAIL);
        _appeal(n, SELLER_OWNER);
        hv.roll(uint256(fairbind.getCase(n).randomBlock) + 201);
        fairbind.finalizeCase(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.PARTY_REVIEW), "reopened once");
        hv.roll(uint256(fairbind.getReviewResealDue(n)) + 1);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "initial FAIL upheld");
        require(_bondOfSeller().failureCount == 1, "counted");
    }

    /// Unchanged: a review the buyer appealed against an initial PASS still
    /// ends INCONCLUSIVE when it cannot progress.
    function test_buyerAppealedReviewThatStallsStaysInconclusive() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        _judge(n, PASS);
        _appeal(n, buyer);
        _sealReview(n);
        _timeoutAll(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == CASE_INCONCLUSIVE && c.finalVerdict == INCONCLUSIVE, "protocol INCONCLUSIVE");
        require(_bondOfSeller().failureCount == 0, "not counted");
    }

    /// Unchanged: an automatic recheck that cannot progress ends INCONCLUSIVE.
    function test_stalledAutomaticRecheckStaysInconclusive() public {
        _deploy(_profile(1_000_000, 1_000_000));
        bytes32 n = _openedSample();
        _judge(n, PASS);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.openAutoRecheck(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.AUTO_REVIEW), "rechecked");
        _timeoutAll(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == CASE_INCONCLUSIVE && c.finalVerdict == INCONCLUSIVE, "protocol INCONCLUSIVE");
        require(_bondOfSeller().failureCount == 0, "not counted");
    }

    // ------------------------------- D2-11: delivered non-delivery disputes

    function _deliveredDispute(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory none;
        hv.roll(100);
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), none, "");
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        hv.prank(buyer);
        fairbind.acceptServe(n);
        require(fairbind.getCase(n).state == DELIVERED, "delivered");
    }

    /// Old rule: openSample required a purchase without a case, so a sampled
    /// purchase whose non-delivery dispute ended as delivered was never judged
    /// and was released to the seller. Now it opens its sample case, the
    /// dispute's serve record is cleared, and it is not released before.
    function test_sampledPurchaseWhoseDisputeEndedDeliveredOpensItsSampleCase() public {
        _deploy(_profile(1_000_000, 0));
        hv.roll(10);
        bytes32 n = _purchase(G);
        _deliveredDispute(n);
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASABLE), "releasable");
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        hv.roll(50_000);
        hv.expectRevert(FairBindCore.NotSampled.selector);
        fairbind.releasePurchase(n);
        fairbind.openSample(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.trigger == uint8(FairBindCore.CaseTrigger.SAMPLE), "sample trigger");
        require(c.state == uint8(FairBindCore.CaseState.JUDGING) && c.assignedVerifierId != 0, "assigned");
        require(c.bundleHash == bytes32(0) && c.requester == address(0), "serve record cleared");
        require(c.requesterRole == uint8(FairBindCore.RequesterRole.NONE), "role cleared");
        require(fairbind.getPurchase(n).financialState == HELD, "held");
        require(fairbind.getSampleReceiptDue(n) == block.number + 300, "receipt deadline");
        _judge(n, PASS);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.finalizeCase(n);
        require(fairbind.getCase(n).state == FINAL, "judged");
        uint256 before = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(n);
        require(token.balanceOf(SELLER_OWNER) - before == G + DISPUTE_DEPOSIT, "released after the case, with the deposit");
    }

    /// Rule 94a: the sample case opens also while a buyer recovery is open.
    function test_deliveredDisputeWithOpenBuyerRecoveryStillOpensTheSampleCase() public {
        _deploy(_profile(1_000_000, 0));
        hv.roll(10);
        bytes32 n = _purchase(G);
        _deliveredDispute(n);
        FairBindCore.FairBindReceipt memory none;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), none, "");
        require(fairbind.getBuyerRecovery(n).state == uint8(FairBindCore.CaseState.SERVE_WAIT), "recovery open");
        require(fairbind.getPurchase(n).financialState == HELD, "held by the recovery");
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(n);
        require(fairbind.getCase(n).trigger == uint8(FairBindCore.CaseTrigger.SAMPLE), "sample case opened");
        require(fairbind.getCase(n).assignedVerifierId != 0, "assigned");
    }

    /// Unchanged: an unsampled purchase whose dispute ended as delivered is released.
    function test_unsampledDeliveredPurchaseIsReleased() public {
        _deploy(_profile(40_000, 0));
        hv.roll(10);
        bytes32 n = _purchase(G);
        _deliveredDispute(n);
        bytes32 beacon;
        for (uint256 i;; i++) {
            beacon = keccak256(abi.encode("unsampled", i));
            if (!_sampledCopy(beacon, sellerId, 0, n, 40_000)) break;
        }
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, beacon);
        hv.expectRevert(FairBindCore.NotSampled.selector);
        fairbind.openSample(n);
        hv.roll(50_000);
        fairbind.releasePurchase(n);
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASED), "released");
    }

    // -------------------------------------------- D2-17: sample receipts

    /// Old rule: a sample case whose receipt the seller never put on chain
    /// could not be judged and fell through to INCONCLUSIVE. Now it ends
    /// UNSERVED once its receipt deadline passes: a confirmed failure.
    function test_sampleCaseWithoutItsReceiptOnChainInTimeIsUnserved() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        uint256 due = fairbind.getSampleReceiptDue(n);
        require(due == block.number + 300, "deadline serveBlocks after the opening");
        hv.roll(due);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutSampleReceipt(n);
        hv.roll(due + 1);
        fairbind.timeoutSampleReceipt(n);
        require(fairbind.getCase(n).state == UNSERVED, "unserved");
        require(fairbind.getPurchase(n).financialState == REFUNDABLE, "refundable");
        require(_bondOfSeller().failureCount == 1, "counted");
        uint256 before = token.balanceOf(buyer);
        fairbind.claimRefund(n);
        require(token.balanceOf(buyer) - before == G, "buyer refunded");
    }

    function test_receiptPostedInTimeEndsTheReceiptDeadline() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        uint256 due = fairbind.getSampleReceiptDue(n);
        hv.roll(due);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.submitSampleReceipt(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(n));
        require(fairbind.getSampleReceiptDue(n) == 0, "recorded");
        hv.roll(due + 1);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSampleReceipt(n);
    }

    function test_receiptAfterItsDeadlineIsRefused() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        hv.roll(uint256(fairbind.getSampleReceiptDue(n)) + 1);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory proof = _proof(n);
        hv.expectRevert(FairBindCore.DeadlinePassed.selector);
        fairbind.submitSampleReceipt(n, r, rs, proof);
    }

    /// A verdict carrying the receipt and its proof before the deadline puts
    /// them on chain.
    function test_verdictBeforeTheDeadlinePostsTheReceipt() public {
        _deploy(_profile(1_000_000, 0));
        bytes32 n = _openedSample();
        _judge(n, PASS);
        require(fairbind.getSampleReceiptDue(n) == 0, "recorded by the verdict");
    }

    /// A receipt the seller left out of the anchored tree has no inclusion
    /// proof; drawn for sampling, its case ends UNSERVED.
    function test_omittedReceiptDrawnForSamplingEndsUnserved() public {
        _deploy(_profile(1_000_000, 0));
        hv.roll(10);
        bytes32 kept = _purchase(G);
        bytes32 omitted = _purchase(G);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = kept;
        ns[1] = keccak256("substitute leaf");
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(omitted);
        FairBindCore.FairBindReceipt memory r = _receipt(omitted);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        FairBindCore.ReceiptProof memory proof = _proof(kept);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.submitSampleReceipt(omitted, r, rs, proof);
        hv.roll(uint256(fairbind.getSampleReceiptDue(omitted)) + 1);
        fairbind.timeoutSampleReceipt(omitted);
        require(fairbind.getCase(omitted).state == UNSERVED, "unserved");
        require(_bondOfSeller().failureCount == 1, "counted");
    }

    // ------------------------------- D2-6 (b): inconclusive above threshold

    /// A FINAL(INCONCLUSIVE) above the inconclusive threshold freezes, suspends
    /// and opens the claim window, but is not counted, deducts nothing and
    /// penalizes no verifier.
    function test_inconclusiveAboveThresholdFreezesWithoutCountOrDeduction() public {
        FairBindCore.ServiceProfileInput memory p = _profile(1_000_000, 0);
        p.maxInconclusivePpm = 1;
        p.minJudgedCount = 1;
        _deploy(p);
        bytes32 n = _openedSample();
        uint32 verifier = fairbind.getCase(n).assignedVerifierId;
        _judge(n, INCONCLUSIVE);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        uint256 locked = fairbind.getLockedForfeit();
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == INCONCLUSIVE, "final inconclusive");
        FairBindCore.BondView memory b = _bondOfSeller();
        require(b.inconclusiveCount == 1 && b.judgedCount == 1, "recorded");
        require(b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "frozen with a claim window");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        require(b.failureCount == 0, "not counted");
        require(b.balance == SELLER_PENALTY && fairbind.getLockedForfeit() == locked, "nothing deducted");
        require(fairbind.getVerifier(verifier).bond == VERIFIER_BOND, "no verifier penalty");
    }

    // ------------------------------------------------------ D2-16 markers

    function test_D2_16_anchoredEpochReleasesNothingBeforeItsRandomness() public {
        _deploy(_profile(40_000, 0));
        hv.roll(10);
        bytes32 n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 100);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
        hv.roll(50_000);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
    }

    /// Closed by ADR 0029 (rule D2-16): an anchored epoch past its seal
    /// deadline without its value is no longer refunded; with a full
    /// checkpoint nothing ends it, and nothing is counted.
    function test_D2_16_anchoredEpochPastItsSealDeadlineIsNotRefunded() public {
        _deploy(_profile(40_000, 0));
        hv.roll(10);
        bytes32 n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 201);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSeal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).state == uint8(FairBindCore.EpochState.ANCHORED), "still anchored");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimEpochFailure(n);
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.DEFERRED), "held");
        require(_bondOfSeller().failureCount == 0, "not the seller's failure");
    }
}
