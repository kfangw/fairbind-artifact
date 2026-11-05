// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import {FairBindM4Base} from "./FairBindM4Base.sol";
import {FairBindCore} from "../src/FairBindCore.sol";
contract FairBindM4Test is FairBindM4Base {
    function testEvidenceAtLastAppealBlockRenewsFullWindow() public {
        bytes32 n=_open();_judge(n,1);
        uint64 old=fairbind.getReview(n).appealUntil;vm.roll(old);
        fairbind.requestEvidence(n,1,0);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.finalizeCase(n);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);vm.prank(BUYER);fairbind.appeal(n);
        uint64 due=fairbind.getCase(n).evidenceDue;vm.roll(due);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);fairbind.timeoutEvidence(n,1,0);
        fairbind.discloseEvidence(n,1,0,EVIDENCE);
        require(fairbind.getReview(n).appealUntil==due+600,"full renewed window");
        require(fairbind.getCase(n).randomBlock==due+601,"new future block");
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.requestEvidence(n,1,0);
        vm.roll(due+600);vm.prank(BUYER);fairbind.appeal(n);
        require(fairbind.getCase(n).reviewPath==1,"timely buyer appeal");
    }
    function testEvidenceTimeoutVoidsAndReplacesWithoutReplay() public {
        bytes32 n=_open();uint32 first=fairbind.getCase(n).assignedVerifierId;_judge(n,1);
        fairbind.requestEvidence(n,1,0);vm.roll(fairbind.getCase(n).evidenceDue+1);
        fairbind.timeoutEvidence(n,1,0);
        FairBindCore.CaseView memory c=fairbind.getCase(n);
        require(c.attempt==1 && c.assignedVerifierId!=first && c.initialVerdict==0,"replacement");
        require(fairbind.getVerifier(first).bond==9_500_000,"late penalty");
        require(fairbind.getVerifierCapital(first).reservedPenalties==0,"old reserve released");
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.discloseEvidence(n,1,0,EVIDENCE);
        _judge(n,2);
        vm.roll(fairbind.getReview(n).appealUntil+1);fairbind.finalizeCase(n);
        _assertReleased(n);
    }
    function testJudgeDeadlineSignatureAndAttemptBindings() public {
        bytes32 n=_open();FairBindCore.SignedVerdict memory v=_verdict(n,1);
        FairBindCore.FairBindReceipt memory r=_receipt(n);
        bytes memory rs=_sig(SELLER_KEY,fairbind.receiptDigest(r));
        bytes memory bad=_sig(99999,fairbind.verdictDigest(v));
        vm.expectRevert(FairBindCore.InvalidSignature.selector);
        fairbind.judge(v,bad,r,rs,FairBindCore.ReceiptProof(0,1,new bytes32[](0)));
        v.attempt=1;bytes memory vs=_sig(1000+v.verifierId,fairbind.verdictDigest(v));
        vm.expectRevert(FairBindCore.InvalidConfiguration.selector);
        fairbind.judge(v,vs,r,rs,FairBindCore.ReceiptProof(0,1,new bytes32[](0)));
        vm.roll(fairbind.getCase(n).judgeDue);_judge(n,1);
        _expectJudgeRevert(n,1,FairBindCore.InvalidTransition.selector);
    }
    function testLateVerdictCannotRaceTimeout() public {
        bytes32 n=_open();vm.roll(fairbind.getCase(n).judgeDue+1);
        _expectJudgeRevert(n,1,FairBindCore.DeadlinePassed.selector);
        fairbind.timeoutJudge(n);require(fairbind.getCase(n).attempt==1,"replacement");
    }
    function testPartyAppealIsExclusiveAndSuccessfulBuyerGetsWrongPenalty() public {
        bytes32 n=_open();uint32 first=fairbind.getCase(n).assignedVerifierId;_judge(n,1);
        vm.prank(BUYER);fairbind.appeal(n);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.openAutoRecheck(n);
        _sealReview(n);
        require(fairbind.getCase(n).assignedVerifierId!=first,"no repeat");
        uint256 before=token.balanceOf(BUYER);_judge(n,2);
        // A disagreeing party review goes to the tiebreak; the third verdict is final (ADR 0019).
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.TIEBREAK),"tiebreak");
        _sealReview(n);_judge(n,2);
        require(token.balanceOf(BUYER)==before+6_000_000,"appeal deposit and wrong penalty");
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.FINAL),"final");
        fairbind.claimRefund(n);_assertReleased(n);
        require(fairbind.getVerifier(first).bond==9_000_000,"wrong penalty");
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.finalizeCase(n);
    }
    function testUnsuccessfulAppealDepositGoesToSeller() public {
        bytes32 n=_open();_judge(n,1);vm.prank(BUYER);fairbind.appeal(n);_sealReview(n);
        uint256 before=token.balanceOf(address(this));_judge(n,1);
        require(token.balanceOf(address(this))==before+5_000_000,"opposing party");_assertReleased(n);
        require(fairbind.getCase(n).reviewPath==1,"party path");
    }
    function testAutomaticDisagreementUsesThirdDistinctVerifier() public {
        bytes32 n=_open();uint32 first=fairbind.getCase(n).assignedVerifierId;_judge(n,1);
        _sealReview(n);fairbind.openAutoRecheck(n);
        uint32 second=fairbind.getCase(n).assignedVerifierId;require(second!=first,"second distinct");
        _judge(n,2);require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.TIEBREAK),"tie");
        _sealReview(n);uint32 third=fairbind.getCase(n).assignedVerifierId;
        require(third!=first && third!=second,"third distinct");
        _judge(n,1);_assertReleased(n);
        require(token.balanceOf(TREASURY)==1_000_000,"only wrong second penalized");
        require(fairbind.getCase(n).finalVerdict==1 && fairbind.getCase(n).reviewPath==2,"auto final");
    }
    function testAutoInconclusiveThirdNeverSlashesContent() public {
        bytes32 n=_open();_judge(n,1);_sealReview(n);fairbind.openAutoRecheck(n);_judge(n,2);_sealReview(n);_judge(n,3);
        require(token.balanceOf(TREASURY)==0,"no wrong penalty on inconclusive");_assertReleased(n);
    }
    // ADR 0021: the first missing review hash reopens the seal once; the
    // second ends the case INCONCLUSIVE and returns the appeal deposit (the
    // old rule ended it on the first).
    function testMissingReviewHashEndsInconclusiveAndReturnsAppealDeposit() public {
        bytes32 n=_open();_judge(n,1);vm.prank(BUYER);fairbind.appeal(n);
        uint256 before=token.balanceOf(BUYER);
        uint64 b=fairbind.getCase(n).randomBlock;vm.roll(b+1);vm.setBlockhash(b,bytes32(0));
        fairbind.sealReviewRandomness(n);
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.PARTY_REVIEW),"reopened once");
        require(token.balanceOf(BUYER)==before,"deposit held while reopened");
        b=fairbind.getCase(n).randomBlock;vm.roll(b+1);vm.setBlockhash(b,bytes32(0));
        fairbind.sealReviewRandomness(n);
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.INCONCLUSIVE),"inconclusive");
        require(token.balanceOf(BUYER)==before+5_000_000,"appeal returned");_assertReleased(n);
    }
    // ADR 0021: an expired candidate block reopens the gate once; a second
    // expiry ends INCONCLUSIVE, never a default PASS.
    function testExpiredAutoCandidateCannotSkipSelectedReview() public {
        bytes32 n=_open();_judge(n,1);vm.roll(fairbind.getCase(n).randomBlock+201);fairbind.finalizeCase(n);
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.INITIAL_VERDICT),"gate reopened once");
        // The reopened gate keeps its candidate block (ADR 0025) and ends after its window.
        vm.roll(fairbind.getReviewResealDue(n)+1);fairbind.finalizeCase(n);
        require(fairbind.getCase(n).finalVerdict==3,"no default pass on expiry");_assertReleased(n);
    }
    function testServeOnlyOnceAndOnlyWhileJudgmentTimely() public {
        bytes32 n=_open();fairbind.requestServe(n);fairbind.served(n,keccak256("bundle"));fairbind.acceptServe(n);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.requestServe(n);
        _judge(n,1);vm.prank(BUYER);fairbind.appeal(n);_sealReview(n);
        vm.roll(fairbind.getCase(n).judgeDue+1);
        vm.expectRevert(FairBindCore.DeadlinePassed.selector);fairbind.requestServe(n);
    }
    function testReviewServeResumesSameStage() public {
        bytes32 n=_open();_judge(n,1);vm.prank(BUYER);fairbind.appeal(n);_sealReview(n);
        uint32 id=fairbind.getCase(n).assignedVerifierId;
        fairbind.requestServe(n);fairbind.served(n,keccak256("bundle"));fairbind.acceptServe(n);
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.PARTY_REVIEW),"resume party");
        require(fairbind.getCase(n).assignedVerifierId==id,"same verifier");_judge(n,1);_assertReleased(n);
    }
    function testBuyerTimeoutDuringReviewReleasesAllCapitalAndDeposits() public {
        bytes32 n=_open();_judge(n,1);vm.prank(BUYER);fairbind.appeal(n);_sealReview(n);_buyerClaim(n);
        uint256 before=token.balanceOf(BUYER);vm.roll(fairbind.getBuyerRecovery(n).serveDue+1);fairbind.timeoutBuyerServe(n);
        fairbind.claimRefund(n);_assertReleased(n);
        require(token.balanceOf(BUYER)==before+15_010_000,"principal and three deposits");
        _expectJudgeRevert(n,1,FairBindCore.InvalidTransition.selector);
    }
    function testContentPassDoesNotReleaseOpenBuyerRecovery() public {
        bytes32 n=_open();_judge(n,1);vm.prank(BUYER);fairbind.appeal(n);_sealReview(n);_buyerClaim(n);_judge(n,1);
        require(fairbind.getPurchase(n).financialState==uint8(FairBindCore.FinancialState.HELD),"buyer still holds");
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.releasePurchase(n);
        vm.roll(fairbind.getBuyerRecovery(n).serveDue+1);fairbind.timeoutBuyerServe(n);fairbind.claimRefund(n);_assertReleased(n);
    }
    function testOldRetentionProfileRejected() public {
        FairBindCore.ServiceProfileInput memory p=_profile();p.retentionBlocks=22_000;p.deferBlocks=22_000;p.claimWindowBlocks=22_000;
        vm.expectRevert(FairBindCore.InvalidProfile.selector);fairbind.createServiceProfile(4,p);
    }
    function testInitialInconclusiveWaitsForEvidenceThenReturnsDisputeDeposit() public {
        bytes32 n=_open();_judge(n,3);fairbind.requestEvidence(n,1,0);fairbind.discloseEvidence(n,1,0,EVIDENCE);
        // An unappealed INCONCLUSIVE passes the recheck gate (always selected here) and the recheck agrees.
        vm.roll(fairbind.getReview(n).appealUntil+1);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);fairbind.finalizeCase(n);
        _sealReview(n);fairbind.openAutoRecheck(n);_judge(n,3);_assertReleased(n);
        vm.roll(fairbind.getPurchase(n).releaseBlock);uint256 before=token.balanceOf(BUYER);fairbind.releasePurchase(n);
        require(token.balanceOf(BUYER)==before+5_000_000,"dispute deposit returned");
    }
    function testSellerAppealReversesFailAndReceivesWrongPenalty() public {
        bytes32 n=_open();uint32 initial=fairbind.getCase(n).assignedVerifierId;_judge(n,2);
        fairbind.appeal(n);_sealReview(n);uint256 before=token.balanceOf(address(this));_judge(n,1);
        _sealReview(n);_judge(n,1);
        require(token.balanceOf(address(this))==before+6_000_000,"successful seller appeal accounting");
        require(fairbind.getVerifier(initial).bond==9_000_000,"initial wrong penalty");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).balance==20_000_000,"seller must not be sanctioned");
        require(fairbind.getSeller(sellerId).status==uint8(FairBindCore.SellerStatus.ACTIVE),"overturn reinstates");
        require(fairbind.getCase(n).finalVerdict==1,"reversed final");_assertReleased(n);
    }
    function testSampleJudgeRequiresValidAnchoredReceiptProof() public {
        bytes32 n=_purchase();vm.roll(600);
        fairbind.anchor(sellerId,0,_pairEntry(n,fairbind.receiptDigest(_receipt(n))),1,keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK+1);vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK,keccak256("epoch randomness"));fairbind.seal(sellerId,0);fairbind.openSample(n);
        FairBindCore.SignedVerdict memory v=_verdict(n,1);FairBindCore.FairBindReceipt memory r=_receipt(n);
        bytes memory vs=_sig(1000+v.verifierId,fairbind.verdictDigest(v));bytes memory rs=_sig(SELLER_KEY,fairbind.receiptDigest(r));
        vm.expectRevert(FairBindCore.InvalidProof.selector);
        fairbind.judge(v,vs,r,rs,FairBindCore.ReceiptProof(0,2,new bytes32[](0)));
        fairbind.judge(v,vs,r,rs,FairBindCore.ReceiptProof(0,1,new bytes32[](0)));
        require(fairbind.getCase(n).initialVerdict==1,"valid sample proof");
    }
    function testUnselectedAutomaticReviewFinalizesInitialPass() public {
        FairBindCore.ServiceProfileInput memory p=_profile();p.recheckPpm=0;
        fairbind.createServiceProfile(4,p);fairbind.checkpointVerifierTree(4);fairbind.setServiceProfileActive(4,true);
        sellerId=registerSellerWithBond(fairbind, 4,vm.addr(SELLER_KEY),CLAIMS,20_000_000);activeProfile=4;
        bytes32 n=_open();_judge(n,1);_sealReview(n);fairbind.openAutoRecheck(n);
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.FINAL),"unselected final");
        require(fairbind.getAssignments(n).length==1,"unselected assigned verifier");_assertReleased(n);
    }
    function testEvidenceAuthenticationAndSizeGuards() public {
        bytes32 n=_open();_judge(n,1);
        vm.expectRevert(FairBindCore.Unauthorized.selector);vm.prank(address(123));fairbind.requestEvidence(n,1,0);
        fairbind.requestEvidence(n,1,0);
        vm.expectRevert(FairBindCore.InvalidConfiguration.selector);fairbind.discloseEvidence(n,1,0,bytes("wrong evidence"));
        bytes memory oversized=new bytes(131_073);
        vm.expectRevert(FairBindCore.EvidenceTooLarge.selector);fairbind.discloseEvidence(n,1,0,oversized);
        fairbind.discloseEvidence(n,1,0,EVIDENCE);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);fairbind.discloseEvidence(n,1,0,EVIDENCE);
    }
}
