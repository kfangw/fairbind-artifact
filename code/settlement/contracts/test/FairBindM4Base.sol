// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import {FairBindCore} from "../src/FairBindCore.sol";
import {FairBind} from "../src/FairBind.sol";
import {DeployFairBind} from "./DeployFairBind.sol";
import {MockEIP3009Token} from "./MockEIP3009Token.sol";
interface VmM4 {
    function addr(uint256 key) external returns(address);
    function sign(uint256 key, bytes32 digest) external returns(uint8,bytes32,bytes32);
    function prank(address caller) external;
    function roll(uint256 height) external;
    function setBlockhash(uint256 height,bytes32 hash) external;
    function expectRevert(bytes4 selector) external;
}
abstract contract FairBindM4Base is DeployFairBind {
    VmM4 internal constant vm=VmM4(address(uint160(uint256(keccak256("hevm cheat code")))));
    address internal constant BUYER=address(0xB0B);
    address internal constant TREASURY=address(0xCAFE);
    uint256 internal constant SELLER_KEY=55555;
    bytes32 internal constant CLAIMS=keccak256("claims");
    bytes internal constant EVIDENCE=bytes("canonical evidence fixture");
    MockEIP3009Token internal token;
    FairBind internal fairbind;
    uint32 internal sellerId;
    uint32 internal activeProfile=3;
    uint128 internal nextKey=1;
    function setUp() public virtual {
        token=new MockEIP3009Token();
        fairbind=deployFairBind(address(token),address(this),address(0xA11CE),TREASURY);
        fairbind.createDeadlineConfig(1,FairBindCore.DeadlineConfig(100,200,200,60,1800,300,600,300,600));
        fairbind.createServiceProfile(3,_profile());
        token.mint(address(this),1_000_000_000);
        token.approve(address(fairbind),type(uint256).max);
        for(uint32 i=1;i<=14;i++)fairbind.registerVerifier(uint256(1)<<1,vm.addr(1000+i),10_000_000);
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3,true);
        sellerId=registerSellerWithBond(fairbind, 3,vm.addr(SELLER_KEY),CLAIMS,20_000_000);
        token.mint(BUYER,100_000_000);
        vm.prank(BUYER);token.approve(address(fairbind),type(uint256).max);
    }
    function _purchase() internal returns(bytes32 n) {
        bytes16 key=bytes16(nextKey++);bytes32 req=keccak256(abi.encode(key));
        n=fairbind.deriveNonce(sellerId,activeProfile,CLAIMS,BUYER,key,req);
        fairbind.settle(sellerId,activeProfile,CLAIMS,key,req,FairBindCore.TransferAuthorization(BUYER,address(fairbind),10_000,0,100,n),new bytes(65));
    }
    function _receipt(bytes32 n) internal view returns(FairBindCore.FairBindReceipt memory r){
        FairBindCore.PurchaseView memory p=fairbind.getPurchase(n);
        r=FairBindCore.FairBindReceipt(1,p.sellerId,p.profileId,n,p.requestHash,keccak256("response"),CLAIMS,keccak256("commitment"),p.epoch,1);
    }
    function _sig(uint256 key,bytes32 hash) internal returns(bytes memory){
        (uint8 v,bytes32 r,bytes32 s)=vm.sign(key,hash);return abi.encodePacked(r,s,v);
    }
    function _anchor(bytes32 n) internal {
        vm.roll(600);
        uint32 count=fairbind.epochPurchaseCount(sellerId,0);
        fairbind.anchor(sellerId,0,_filledEntries(fairbind.receiptDigest(_receipt(n)),count),count,keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK+1);vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK,keccak256("epoch randomness"));fairbind.seal(sellerId,0);
    }
    function _quality(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory r=_receipt(n);bytes memory signature=_sig(SELLER_KEY,fairbind.receiptDigest(r));
        vm.prank(BUYER);fairbind.dispute(n,uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY),r,signature);
        fairbind.assignVerifier(n);
    }
    function _open() internal returns(bytes32 n){n=_purchase();_anchor(n);_quality(n);}
    function _verdict(bytes32 n,uint8 result) internal view returns(FairBindCore.SignedVerdict memory v){
        FairBindCore.CaseView memory c=fairbind.getCase(n);
        v=FairBindCore.SignedVerdict(1,n,c.stage,c.attempt,c.assignedVerifierId,result,keccak256(EVIDENCE));
    }
    function _judge(bytes32 n,uint8 result) internal {
        FairBindCore.SignedVerdict memory v=_verdict(n,result);
        FairBindCore.FairBindReceipt memory r=_receipt(n);
        fairbind.judge(v,_sig(1000+v.verifierId,fairbind.verdictDigest(v)),r,_sig(SELLER_KEY,fairbind.receiptDigest(r)),FairBindCore.ReceiptProof(0,1,new bytes32[](0)));
    }
    function _expectJudgeRevert(bytes32 n,uint8 result,bytes4 selector) internal {
        FairBindCore.SignedVerdict memory v=_verdict(n,result);
        FairBindCore.FairBindReceipt memory r=_receipt(n);
        bytes memory vs=_sig(1000+v.verifierId,fairbind.verdictDigest(v));
        bytes memory rs=_sig(SELLER_KEY,fairbind.receiptDigest(r));
        vm.expectRevert(selector);
        fairbind.judge(v,vs,r,rs,FairBindCore.ReceiptProof(0,1,new bytes32[](0)));
    }
    function _sealReview(bytes32 n) internal {
        uint64 blockNo=fairbind.getCase(n).randomBlock;
        vm.roll(uint256(blockNo)+1);vm.setBlockhash(blockNo,keccak256(abi.encode(n,blockNo)));
        fairbind.sealReviewRandomness(n);
    }
    function _buyerClaim(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory empty;
        vm.prank(BUYER);fairbind.dispute(n,uint8(FairBindCore.CaseTrigger.NON_DELIVERY),empty,"");
    }
    function _assertReleased(bytes32 n) internal view {
        FairBindCore.AssignmentData[] memory list=fairbind.getAssignments(n);
        for(uint256 i;i<list.length;i++){
            require(list[i].released,"assignment retained");
            require(fairbind.getVerifier(list[i].verifierId).lockedLiability==0,"liability retained");
            require(fairbind.getVerifierCapital(list[i].verifierId).reservedPenalties==0,"reserve retained");
        }
    }
    function _profile() internal pure virtual returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = keccak256("fairbind/http-canon/v1");
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 1_000_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 1_000_000;
        p.bucketCapacity = 20;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 30_000;
        p.deferBlocks = 40_000;
        p.retentionBlocks = 40_000;
        p.marginBlocks = 500;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 10_000;
        p.maxBadGain = 10_000;
        p.sellerPenalty = 10_000_000;
        p.minVerifierBond = 1_000_000;
        p.verifierBondCap = 100_000_000;
        p.verifierLatePenalty = 500_000;
        p.verifierWrongPenalty = 1_000_000;
        p.disputeDeposit = 5_000_000;
        p.appealDeposit = 5_000_000;
        p.verifierExposurePpm = 500_000;
        p.maxAssignments = 3;
        p.minVerifiers = 14;
        p.strikeLimit = 3;
        p.deadlineConfigId = 1;
        p.claimWindowBlocks = p.retentionBlocks;
        p.failureLimit = 3;
        p.failureWindowBlocks = p.retentionBlocks;
        p.maxInconclusivePpm = 1_000_000;
        p.inconclusiveWindowBlocks = p.retentionBlocks;
        p.forfeitVerifierPpm = 500_000;
        p.freezeOnInitialFail = false;
        p.minJudgedCount = 1;
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS;
        p.parameterHash = keccak256("profile");
    }
}
