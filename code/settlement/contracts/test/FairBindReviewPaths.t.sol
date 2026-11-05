// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ReproBase } from "./repro/ReproBase.sol";

/// The tiebreak after a disagreeing party review and the automatic recheck
/// of an initial INCONCLUSIVE (ADR 0019). Each test states the behaviour it
/// replaces.
contract FairBindReviewPathsTest is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant WRONG_PENALTY = 1_000_000;
    uint256 internal constant APPEAL_DEPOSIT = 5_000_000;
    uint256 internal constant VERIFIER_BOND = 10_000_000;

    uint8 internal constant PASS = uint8(FairBindCore.Verdict.PASS);
    uint8 internal constant FAIL = uint8(FairBindCore.Verdict.FAIL);
    uint8 internal constant INCONCLUSIVE = uint8(FairBindCore.Verdict.INCONCLUSIVE);
    uint8 internal constant TIEBREAK = uint8(FairBindCore.CaseState.TIEBREAK);
    uint8 internal constant FINAL = uint8(FairBindCore.CaseState.FINAL);
    uint8 internal constant AUTO_REVIEW = uint8(FairBindCore.CaseState.AUTO_REVIEW);

    function _profile(uint32 recheckPpm) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = recheckPpm;
    }

    /// One sampled purchase of epoch 0 with its case opened.
    function _openedSample() internal returns (bytes32 n) {
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
        fairbind.openSample(n);
    }

    function _appeal(bytes32 n, address appellant) internal {
        token.mint(appellant, APPEAL_DEPOSIT);
        hv.prank(appellant);
        token.approve(address(fairbind), type(uint256).max);
        hv.prank(appellant);
        fairbind.appeal(n);
    }

    /// Seals the review randomness of a waiting review stage and assigns its verifier.
    function _sealReview(bytes32 n) internal {
        uint64 rb = fairbind.getCase(n).randomBlock;
        if (block.number <= rb) hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("review", n, rb)));
        fairbind.sealReviewRandomness(n);
    }

    /// Passes the recheck gate after the appeal window.
    function _recheck(bytes32 n) internal {
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256(abi.encode("candidate", n)));
        fairbind.openAutoRecheck(n);
    }

    function _verifier(bytes32 n) internal view returns (uint32) {
        return fairbind.getCase(n).assignedVerifierId;
    }

    // ------------------------------------------------ tiebreak on party review

    /// Old rule: the party-review verdict was final. Now a party review that
    /// differs from the initial verdict goes to a third verifier; here it
    /// confirms the initial FAIL, the appellant loses its deposit and the
    /// party reviewer's wrong-verdict penalty goes to the treasury.
    function test_partyReviewDisagreementGoesToTiebreakWhichConfirmsTheInitialVerdict() public {
        _deploy(_profile(0));
        bytes32 n = _openedSample();
        uint32 first = _verifier(n);
        _judge(n, FAIL);
        _appeal(n, SELLER_OWNER);
        _sealReview(n);
        uint32 second = _verifier(n);
        _judge(n, PASS);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == TIEBREAK && c.stage == uint8(FairBindCore.JudgmentStage.TIEBREAK), "tiebreak, not final");
        require(c.randomBlock == block.number + 1 && c.assignedVerifierId == 0, "fixed later randomness");
        require(c.reviewPath == 1, "still the party path");
        _sealReview(n);
        uint32 third = _verifier(n);
        require(third != first && third != second && second != first, "three distinct verifiers");
        uint256 treasuryBefore = token.balanceOf(TREASURY);
        uint256 lockedBefore = fairbind.getLockedForfeit();
        uint256 buyerBefore = token.balanceOf(buyer);
        _judge(n, FAIL);
        c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "third verdict is final");
        require(fairbind.getVerifier(second).bond == VERIFIER_BOND - WRONG_PENALTY, "party reviewer was wrong");
        require(fairbind.getVerifier(first).bond == VERIFIER_BOND && fairbind.getVerifier(third).bond == VERIFIER_BOND, "others intact");
        // The share of the seller penalty that the confirmed failure deducts
        // (ADR 0018) stays locked in the contract (ADR 0022).
        require(token.balanceOf(TREASURY) - treasuryBefore == WRONG_PENALTY,
            "penalty to the treasury: the appellant lost");
        require(fairbind.getLockedForfeit() - lockedBefore == uint256(10_000_000) / 3, "deducted share locked");
        require(token.balanceOf(buyer) - buyerBefore == APPEAL_DEPOSIT, "appeal deposit to the opposing party");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).failureCount == 1, "confirmed failure counted");
    }

    /// The tiebreak overturns the initial verdict: the appellant wins its
    /// deposit back and the first verifier's penalty.
    function test_tiebreakAfterPartyReviewCanOverturnTheInitialVerdict() public {
        _deploy(_profile(0));
        bytes32 n = _openedSample();
        uint32 first = _verifier(n);
        _judge(n, FAIL);
        _appeal(n, SELLER_OWNER);
        _sealReview(n);
        _judge(n, PASS);
        _sealReview(n);
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        _judge(n, PASS);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == PASS, "overturned by the tiebreak");
        require(fairbind.getVerifier(first).bond == VERIFIER_BOND - WRONG_PENALTY, "first verifier was wrong");
        require(token.balanceOf(SELLER_OWNER) - ownerBefore == APPEAL_DEPOSIT + WRONG_PENALTY,
            "deposit and penalty to the successful appellant");
        FairBindCore.BondView memory bond = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(bond.failureCount == 0 && bond.balance == 10_000_000 && bond.freezeState == 0, "no failure recorded");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASABLE), "releasable");
    }

    /// A party review that agrees with the initial verdict still ends the case
    /// at the second verdict, with the deposit to the opposing party.
    function test_agreeingPartyReviewIsFinal() public {
        _deploy(_profile(0));
        bytes32 n = _openedSample();
        _judge(n, PASS);
        _appeal(n, buyer);
        _sealReview(n);
        uint256 ownerBefore = token.balanceOf(SELLER_OWNER);
        _judge(n, PASS);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == PASS, "agreement is final");
        require(token.balanceOf(SELLER_OWNER) - ownerBefore == APPEAL_DEPOSIT, "deposit to the seller");
    }

    /// A buyer's appeal of a PASS that the party reviewer flips to FAIL is not
    /// final either; the tiebreak decides, and an INCONCLUSIVE tiebreak
    /// returns the deposit and penalizes nobody.
    function test_buyerAppealFlipGoesToTiebreakAndInconclusiveTiebreakPenalizesNobody() public {
        _deploy(_profile(0));
        bytes32 n = _openedSample();
        uint32 first = _verifier(n);
        _judge(n, PASS);
        _appeal(n, buyer);
        _sealReview(n);
        uint32 second = _verifier(n);
        _judge(n, FAIL);
        require(fairbind.getCase(n).state == TIEBREAK, "flip goes to the tiebreak");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "no failure yet");
        _sealReview(n);
        uint256 buyerBefore = token.balanceOf(buyer);
        _judge(n, INCONCLUSIVE);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == INCONCLUSIVE, "inconclusive tiebreak is final");
        require(fairbind.getVerifier(first).bond == VERIFIER_BOND && fairbind.getVerifier(second).bond == VERIFIER_BOND, "no penalty");
        require(token.balanceOf(buyer) - buyerBefore == APPEAL_DEPOSIT, "deposit back to the appellant");
    }

    // ------------------------------------- automatic recheck of INCONCLUSIVE

    /// Old rule: an unappealed initial INCONCLUSIVE became final after the
    /// appeal window. Now it passes the recheck gate: selected here, the
    /// second verifier agrees and the case ends FINAL(INCONCLUSIVE).
    function test_initialInconclusiveIsRecheckedAndAgreementIsFinal() public {
        _deploy(_profile(1_000_000));
        bytes32 n = _openedSample();
        _judge(n, INCONCLUSIVE);
        // No party may appeal an INCONCLUSIVE, and it is not final at the appeal deadline.
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fairbind.appeal(n);
        hv.roll(uint256(fairbind.getReview(n).appealUntil) + 1);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.finalizeCase(n);
        _recheck(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.reviewPath == 2 && c.stage == uint8(FairBindCore.JudgmentStage.AUTO), "automatic path");
        require(c.state == AUTO_REVIEW && c.assignedVerifierId != 0, "second verifier assigned");
        _judge(n, INCONCLUSIVE);
        c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == INCONCLUSIVE, "agreement is final");
        FairBindCore.BondView memory bond = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(bond.judgedCount == 1 && bond.inconclusiveCount == 1, "counted once");
    }

    /// A recheck that disagrees with the initial INCONCLUSIVE goes to the
    /// tiebreak, whose verdict is final and can be a FAIL.
    function test_recheckOfInconclusiveThatDisagreesGoesToTiebreak() public {
        _deploy(_profile(1_000_000));
        bytes32 n = _openedSample();
        _judge(n, INCONCLUSIVE);
        _recheck(n);
        _judge(n, FAIL);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == TIEBREAK, "disagreement goes to the tiebreak");
        _sealReview(n);
        _judge(n, FAIL);
        c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL, "tiebreak FAIL is final");
        FairBindCore.BondView memory bond = fairbind.getBond(fairbind.getSeller(sellerId).bondId);
        require(bond.failureCount == 1 && bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "confirmed failure");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "refundable");
    }

    /// Not selected: the initial INCONCLUSIVE is final, as before, through
    /// finalizeCase, sealReviewRandomness or openAutoRecheck.
    function test_unselectedInconclusiveIsFinal() public {
        _deploy(_profile(0));
        bytes32 n = _openedSample();
        _judge(n, INCONCLUSIVE);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.sealReviewRandomness(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.INITIAL_VERDICT), "sealing alone decides nothing");
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == INCONCLUSIVE && c.reviewPath == 0, "final without review");
    }

    /// An initial FAIL never enters the recheck gate: it is final after the
    /// appeal window when not appealed.
    function test_initialFailIsNotRechecked() public {
        _deploy(_profile(1_000_000));
        bytes32 n = _openedSample();
        _judge(n, FAIL);
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.openAutoRecheck(n);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == FINAL && c.finalVerdict == FAIL && c.reviewPath == 0, "final FAIL");
    }
}
