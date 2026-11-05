// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import {FairBindCore} from "../src/FairBindCore.sol";
import {FairBindM4Base} from "./FairBindM4Base.sol";

// Read-only authoring snapshot, not an executed test report.
// Base sha256: e84c0d6812dd118e93cd292182994e99e47761b833549b1e27986dbdc214d87a
// Core sha256: bdeb7a211bdca2ddbbcca7fe8ab565632db2ebe5d82a47f5ccb732e8027d365d
contract FairBindM4CapitalTest is FairBindM4Base {
    uint256 private constant LIABILITY = 1_010_000;
    uint256 private constant RESERVE = 1_000_000;

    // Select a deterministic fixture nonce whose first ticket chooses target.
    // This models the Base checkpoint (fourteen equal 10m weights) and its fixed
    // epoch hash. It is not evidence of unpredictable or unbiased deployment randomness.
    function _purchaseFor(uint32 target) internal returns(bytes32 n) {
        for(uint256 i; i<4096; i++) {
            bytes16 key=bytes16(nextKey);
            bytes32 req=keccak256(abi.encode(key));
            n=fairbind.deriveNonce(sellerId,activeProfile,CLAIMS,BUYER,key,req);
            uint256 ticket=uint256(keccak256(abi.encode(
                keccak256("fairbind/verifier/v1"),keccak256("epoch randomness"),n,
                uint8(FairBindCore.JudgmentStage.INITIAL),uint8(0),uint32(0)
            )))%140_000_000;
            if(uint32(ticket/10_000_000)+1==target)return _purchase();
            nextKey++;
        }
        revert("fixture nonce search exhausted");
    }

    function _threeConcurrent() internal returns(bytes32 a,bytes32 b,bytes32 c) {
        a=_purchaseFor(1); b=_purchaseFor(1); c=_purchaseFor(1);
        _anchor(a); _quality(a); _quality(b); _quality(c);
        require(fairbind.getCase(a).assignedVerifierId==1,"first fixture target");
        require(fairbind.getCase(b).assignedVerifierId==1,"second fixture target");
        require(fairbind.getCase(c).assignedVerifierId==1,"third fixture target");
    }

    function _capitalSafe() internal view {
        for(uint32 id=1;id<=14;id++) {
            FairBindCore.VerifierView memory v=fairbind.getVerifier(id);
            FairBindCore.VerifierCapital memory c=fairbind.getVerifierCapital(id);
            require(v.bond>=c.reservedPenalties,"reserves exceed funded bond");
            if(v.lockedLiability==0) {
                require(c.reservedPenalties==0,"reserve without outstanding assignment");
                continue;
            }
            uint256 effective=v.bond-c.reservedPenalties;
            if(effective>c.conservativeCap)effective=c.conservativeCap;
            require(v.lockedLiability<=effective*c.conservativeFraction/1_000_000,
                "post-penalty liability bound violated");
        }
    }

    function _late(bytes32 n) internal {
        uint256 due=uint256(fairbind.getCase(n).judgeDue)+1;
        if(block.number<due)vm.roll(due);
        fairbind.timeoutJudge(n);
    }

    /// Old rule (ADR 0009): a fourth 1.01m liability exceeded 0.5*(10m-4m)
    /// and was skipped when the case opened. Decision 126 (ADR 0025): the
    /// verifier had 4.5m of room at the checkpoint, so the fourth case of the
    /// epoch still goes to it; its locked liability now exceeds the current
    /// bound, while reserves stay funded.
    function testFourthAssignmentFollowsTheCheckpointRoomNotTheCurrentBound() public {
        bytes32 a=_purchaseFor(1);bytes32 b=_purchaseFor(1);
        bytes32 c=_purchaseFor(1);bytes32 d=_purchaseFor(1);
        _anchor(a);_quality(a);_quality(b);_quality(c);
        require(fairbind.getVerifier(1).lockedLiability==3*LIABILITY,"liability accumulation");
        require(fairbind.getVerifierCapital(1).reservedPenalties==3*RESERVE,"reserve accumulation");
        require(fairbind.getCheckpointHeadroom(3,1)[0]==4_500_000,"room at the checkpoint");
        _quality(d);
        require(fairbind.getCase(d).assignedVerifierId==1,"fourth assignment follows the checkpoint room");
        require(fairbind.getVerifier(1).lockedLiability==4*LIABILITY,"fourth liability locked");
        require(fairbind.getVerifierCapital(1).reservedPenalties==4*RESERVE,"fourth reserve locked");
        FairBindCore.VerifierView memory v=fairbind.getVerifier(1);
        require(v.bond>=fairbind.getVerifierCapital(1).reservedPenalties,"reserves funded");
        require(v.lockedLiability>(v.bond-4*RESERVE)/2,"above the current bound");
    }

    function testLateReleasePreservesOtherCasesCapital() public {
        (bytes32 a,bytes32 b,bytes32 c)=_threeConcurrent();
        _late(a);
        FairBindCore.VerifierView memory v=fairbind.getVerifier(1);
        require(v.bond==9_500_000,"late penalty funding");
        require(v.lockedLiability==2*LIABILITY,"other case liability released");
        require(fairbind.getVerifierCapital(1).reservedPenalties==2*RESERVE,"other case reserve released");
        require(!fairbind.getAssignments(b)[0].released,"second assignment released");
        require(!fairbind.getAssignments(c)[0].released,"third assignment released");
        require(fairbind.getAssignments(a)[0].released,"late assignment retained");
        _capitalSafe();
    }

    function testRepeatedTimeoutCannotChargePreviousAssignmentTwice() public {
        bytes32 n=_open();uint32 first=fairbind.getCase(n).assignedVerifierId;
        _late(n);
        require(fairbind.getAssignments(n).length==2,"replacement missing");
        bytes32 beforeHash=keccak256(abi.encode(fairbind.getVerifier(first),
            fairbind.getVerifierCapital(first),fairbind.getAssignments(n)));
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutJudge(n);
        require(beforeHash==keccak256(abi.encode(fairbind.getVerifier(first),
            fairbind.getVerifierCapital(first),fairbind.getAssignments(n))),"repeated timeout changed capital");
        require(fairbind.getVerifier(first).strikes==1,"duplicate strike");
        _capitalSafe();
    }

    function testAssignmentExhaustionReleasesAllAndNeverReusesParticipant() public {
        bytes32 n=_open();
        for(uint256 i;i<3;i++)_late(n);
        FairBindCore.AssignmentData[] memory list=fairbind.getAssignments(n);
        require(list.length==3,"unexpected assignment attempts");
        for(uint256 i;i<list.length;i++)for(uint256 j=i+1;j<list.length;j++)
            require(list[i].verifierId!=list[j].verifierId,"participant reused");
        require(fairbind.getCase(n).finalVerdict==3,"exhaustion not inconclusive");
        require(fairbind.getCase(n).state==uint8(FairBindCore.CaseState.INCONCLUSIVE),"exhaustion state");
        _assertReleased(n);_capitalSafe();
    }

    function testReviewExhaustionReleasesRetainedInitialAssignmentWithoutWrongPenalty() public {
        bytes32 n=_open();uint32 initial=fairbind.getCase(n).assignedVerifierId;
        _judge(n,1);_sealReview(n);fairbind.openAutoRecheck(n);
        require(!fairbind.getAssignments(n)[0].released,"initial released before review final");
        require(fairbind.getVerifierCapital(initial).reservedPenalties==RESERVE,"initial reserve not retained");
        for(uint256 i;i<3;i++)_late(n);
        require(fairbind.getAssignments(n).length==4,"review attempts missing");
        require(fairbind.getCase(n).finalVerdict==3,"review exhaustion verdict");
        require(fairbind.getVerifier(initial).bond==10_000_000,"inconclusive content penalty");
        require(fairbind.getVerifier(initial).strikes==0,"inconclusive content strike");
        _assertReleased(n);_capitalSafe();
    }

    /// Old rule (ADR 0009): a verifier holding a case under a profile with a
    /// 3m cap was skipped for a case of a looser profile while the
    /// conservative cap applied. Decision 126 (ADR 0025): the looser
    /// profile's checkpoint gave it room before either case opened, so it is
    /// assigned; the conservative cap is kept for its later admissions.
    function testConservativeEnvelopePersistsButTheCheckpointRoomDecides() public {
        uint32 highSeller=sellerId;
        FairBindCore.ServiceProfileInput memory p=_profile();p.verifierBondCap=3_000_000;
        fairbind.createServiceProfile(4,p);fairbind.checkpointVerifierTree(4);fairbind.setServiceProfileActive(4,true);
        uint32 lowSeller=registerSellerWithBond(fairbind, 4,vm.addr(SELLER_KEY),CLAIMS,20_000_000);
        sellerId=lowSeller;activeProfile=4;bytes32 low=_purchase();
        uint256 ticket=uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"),keccak256("epoch randomness"),low,uint8(1),uint8(0),uint32(0))))%42_000_000;
        uint32 target=uint32(ticket/3_000_000)+1;
        sellerId=highSeller;activeProfile=3;bytes32 high=_purchaseFor(target);
        vm.roll(600);
        fairbind.anchor(lowSeller,0,_oneEntry(fairbind.receiptDigest(_receipt(low))),1,keccak256("low"));
        fairbind.anchor(highSeller,0,_oneEntry(fairbind.receiptDigest(_receipt(high))),1,keccak256("high"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK+1);vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK,keccak256("epoch randomness"));
        fairbind.seal(lowSeller,0);fairbind.seal(highSeller,0);
        _quality(low);require(fairbind.getCase(low).assignedVerifierId==target,"low fixture");
        _quality(high);
        require(fairbind.getCase(high).assignedVerifierId==target,"the checkpoint room decides");
        require(fairbind.getVerifierCapital(target).conservativeCap==3_000_000,"active cap kept");
        require(fairbind.getVerifier(target).bond>=fairbind.getVerifierCapital(target).reservedPenalties,"reserves funded");
    }

    function testWrongPenaltyPreservesSimultaneousOtherCaseReservations() public {
        (bytes32 a,bytes32 b,bytes32 c)=_threeConcurrent();
        _judge(a,1);vm.prank(BUYER);fairbind.appeal(a);_sealReview(a);_judge(a,2);_sealReview(a);_judge(a,2);
        require(fairbind.getVerifier(1).bond==9_000_000,"wrong penalty funding");
        require(fairbind.getVerifier(1).lockedLiability==2*LIABILITY,"other liabilities changed");
        require(fairbind.getVerifierCapital(1).reservedPenalties==2*RESERVE,"other reservations changed");
        require(!fairbind.getAssignments(b)[0].released && !fairbind.getAssignments(c)[0].released,"other histories closed");
        _capitalSafe();
    }

    function _removedExit(bool requestExitFirst) internal {
        (bytes32 a,bytes32 b,bytes32 c)=_threeConcurrent();
        if(requestExitFirst)fairbind.requestVerifierExit(1);
        _late(a);_late(b);_late(c);
        FairBindCore.VerifierView memory removed=fairbind.getVerifier(1);
        require(removed.strikes==3,"strike limit not reached");
        require(removed.status==uint8(FairBindCore.VerifierStatus.REMOVED),"strike removal missing");
        require(removed.bond==8_500_000,"remaining bond incorrect");
        require(removed.lockedLiability==0,"removed liability not cleared");
        require(fairbind.getVerifierCapital(1).reservedPenalties==0,"removed reserve not cleared");
        require(removed.exitEligibleBlock>block.number,"fixture lacks withdrawal delay");
        vm.expectRevert(FairBindCore.ExitNotReady.selector);fairbind.finalizeVerifierExit(1);
        vm.roll(removed.exitEligibleBlock);
        uint256 beforeBalance=token.balanceOf(address(this));
        fairbind.finalizeVerifierExit(1);
        require(token.balanceOf(address(this))==beforeBalance+8_500_000,"remaining bond not returned");
        require(fairbind.getVerifier(1).status==uint8(FairBindCore.VerifierStatus.EXITED),"exit status");
        require(fairbind.getVerifier(1).bond==0,"withdrawn bond retained");
        vm.expectRevert(FairBindCore.ExitNotReady.selector);fairbind.finalizeVerifierExit(1);
        require(token.balanceOf(address(this))==beforeBalance+8_500_000,"second withdrawal paid");
        _capitalSafe();
    }

    function testWithdrawalAfterRetentionStillRejectsOutstandingCapital() public {
        bytes32 n=_open();uint32 id=fairbind.getCase(n).assignedVerifierId;
        fairbind.requestVerifierExit(id);
        vm.roll(fairbind.getVerifier(id).exitEligibleBlock);
        uint256 balance=token.balanceOf(address(this));
        vm.expectRevert(FairBindCore.ExitNotReady.selector);fairbind.finalizeVerifierExit(id);
        require(token.balanceOf(address(this))==balance,"locked withdrawal paid");
        require(fairbind.getVerifier(id).lockedLiability==LIABILITY,"withdrawal cleared liability");
        require(fairbind.getVerifierCapital(id).reservedPenalties==RESERVE,"withdrawal cleared reserve");
        _capitalSafe();
    }

    function testStrikeRemovedVerifierWithdrawsOnlyRemainingBondAfterRetention() public {
        _removedExit(false);
    }

    function testExitRequestDoesNotBypassStrikeRemovalAndRemainingBondWithdrawal() public {
        _removedExit(true);
    }
}
