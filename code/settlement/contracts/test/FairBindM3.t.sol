// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;
import { TEST_BEACON_DELAY_BLOCKS, TEST_EPOCH0_BEACON_BLOCK } from "./TestProfileConstants.sol";
import {FairBindCore} from "../src/FairBindCore.sol";
import { FairBindMerkle } from "../src/FairBindMerkle.sol";
import {DeployFairBind} from "./DeployFairBind.sol";

import { FairBind } from "../src/FairBind.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

interface VmM3 {
    function setBlockhash(uint256 height, bytes32 hash) external;
    function roll(uint256 blockNumber) external;
    function prank(address sender) external;
    function startPrank(address sender) external;
    function stopPrank() external;
    function expectRevert(bytes4 selector) external;
    function addr(uint256 privateKey) external returns (address);
    function sign(uint256 privateKey, bytes32 digest)
        external
        returns (uint8 v, bytes32 r, bytes32 s);
}

contract FairBindM3Test is DeployFairBind {
    VmM3 private constant vm = VmM3(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 private constant SELLER_KEY = 0xA11CE55;
    address private constant BUYER = address(0xB0B);
    bytes32 private constant CLAIMS = keccak256("claims");

    MockEIP3009Token private token;
    FairBind private fairbind;
    uint32 private sellerId;

    function setUp() public {
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), address(0xCAFE));
        fairbind.createDeadlineConfig(
            1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600)
        );
        fairbind.createServiceProfile(3, _profile());
        token.mint(address(this), 200_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i; i < 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, address(uint160(0x1000 + i)), 10_000_000);
        }
        fairbind.checkpointVerifierTree(3);
        fairbind.setServiceProfileActive(3, true);
        sellerId = registerSellerWithBond(fairbind, 3, vm.addr(SELLER_KEY), CLAIMS, 20_000_000);
        token.mint(BUYER, 10_000_000);
        vm.prank(BUYER);
        token.approve(address(fairbind), type(uint256).max);
    }

    function testNonDeliveryTimeoutRefundsPrincipalAndDepositAndSuspends() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 nonce = _settle(bytes16(uint128(1)), request);
        uint256 buyerAfterPayment = token.balanceOf(BUYER);
        _openNonDelivery(nonce);
        vm.roll(363);
        fairbind.timeoutServe(nonce);
        require(
            fairbind.getPurchase(nonce).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE),
            "refundable"
        );
        fairbind.claimRefund(nonce);
        require(token.balanceOf(BUYER) == buyerAfterPayment + 10_000, "principal and deposit");
        // The first final failure suspends, freezes and deducts one share of the
        // penalty; the remainder waits for failureLimit (ADR 0018).
        // The share stays locked in the contract and reaches no treasury (ADR 0022).
        require(fairbind.getLockedForfeit() == uint256(10_000_000) / 3, "one share at the first failure");
        require(token.balanceOf(address(0xCAFE)) == 0, "nothing to the treasury");
        require(
            fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED),
            "suspended"
        );
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).failureCount == 1, "failure recorded");
    }

    function testDirectPublicationCompletesDelivery() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes16 key = bytes16(uint128(2));
        bytes32 nonce = _settle(key, request);
        _openAndEscalate(nonce);
        bytes memory response = bytes("hello fairbind");
        FairBindCore.FairBindReceipt memory receipt = _receipt(nonce, keccak256(response));
        fairbind.publish(nonce, key, request, response, receipt, _sign(receipt));
        require(fairbind.getCase(nonce).state == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
        require(
            fairbind.getPurchase(nonce).financialState == uint8(FairBindCore.FinancialState.RELEASABLE),
            "releasable"
        );
    }

    function testChunkPublicationRequiresOrderAndMatchesResponseRoot() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes16 key = bytes16(uint128(3));
        bytes32 nonce = _settle(key, request);
        _openAndEscalate(nonce);
        bytes memory first = new bytes(16_384);
        bytes memory second = new bytes(17);
        for (uint256 i; i < first.length; i++) {
            first[i] = bytes1(uint8(i));
        }
        for (uint256 i; i < second.length; i++) {
            second[i] = bytes1(uint8(200 + i));
        }
        bytes32 root = keccak256(
            abi.encode(keccak256("fairbind/response-node/v1"), keccak256(first), keccak256(second))
        );
        FairBindCore.FairBindReceipt memory receipt = _receipt(nonce, root);
        fairbind.beginPublication(
            nonce, key, request, receipt, _sign(receipt), uint32(first.length + second.length), 2
        );
        vm.expectRevert(FairBindCore.InvalidPublication.selector);
        fairbind.publishChunk(nonce, 1, second);
        fairbind.publishChunk(nonce, 0, first);
        fairbind.publishChunk(nonce, 1, second);
        fairbind.finalizePublication(nonce);
        require(fairbind.getCase(nonce).state == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
    }

    function testEpochFailureRefundsWithoutReceipt() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 nonce = _settle(bytes16(uint128(4)), request);
        uint256 buyerAfterPayment = token.balanceOf(BUYER);
        vm.roll(701);
        fairbind.timeoutAnchor(sellerId, 0);
        fairbind.claimEpochFailure(nonce);
        fairbind.claimRefund(nonce);
        require(token.balanceOf(BUYER) == buyerAfterPayment + 10_000, "epoch refund");
    }

    function testEquivocationMakesPurchaseRefundable() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 nonce = _settle(bytes16(uint128(5)), request);
        FairBindCore.FairBindReceipt memory first = _receipt(nonce, keccak256("first"));
        FairBindCore.FairBindReceipt memory second = _receipt(nonce, keccak256("second"));
        fairbind.proveEquivocation(first, _sign(first), second, _sign(second));
        require(
            fairbind.getPurchase(nonce).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE),
            "equivocation"
        );
    }

    function testNoCasePurchaseReleasesOnlyAfterEpochAndRetention() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 nonce = _settle(bytes16(uint128(6)), request);
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(nonce);
        uint256 sellerBalance = token.balanceOf(address(this));
        vm.roll(fairbind.getPurchase(nonce).releaseBlock);
        fairbind.releasePurchase(nonce);
        require(token.balanceOf(address(this)) == sellerBalance + 10_000, "seller release");
    }

    function testEscalatedPublicationTimeoutRefunds() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 nonce = _settle(bytes16(uint128(7)), request);
        _openAndEscalate(nonce);
        vm.roll(363);
        fairbind.timeoutServe(nonce);
        require(
            fairbind.getPurchase(nonce).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE),
            "publication timeout"
        );
    }

    /// The seller keeps one real entry and pads the count with a filler on
    /// the far side, so the omitted purchase lies outside the real entry:
    /// below the first entry (LOWER) or above the last (UPPER). Anyone proves
    /// the omission from the purchase nonce and the boundary entry.
    function testOmissionProofAtListBoundaryRefundsOmittedPurchase() public {
        FairBindCore.CanonicalRequest memory request = _request();
        bytes32 firstNonce = _settle(bytes16(uint128(8)), request);
        bytes32 secondNonce = _settle(bytes16(uint128(9)), request);
        FairBindCore.FairBindReceipt memory boundaryReceipt = _receipt(secondNonce, keccak256("second"));
        FairBindMerkle.ReceiptEntry memory boundary =
            FairBindMerkle.ReceiptEntry(secondNonce, fairbind.receiptDigest(boundaryReceipt));
        bool lower = firstNonce < secondNonce;
        // The filler sits on the side away from the omitted purchase.
        FairBindMerkle.ReceiptEntry memory filler = FairBindMerkle.ReceiptEntry(
            lower ? bytes32(type(uint256).max) : bytes32(0), keccak256("filler")
        );
        FairBindMerkle.ReceiptEntry[] memory entries = new FairBindMerkle.ReceiptEntry[](2);
        entries[lower ? 0 : 1] = boundary;
        entries[lower ? 1 : 0] = filler;
        vm.roll(600);
        fairbind.anchor(sellerId, 0, entries, 2, keccak256("publication"));
        bytes32[] memory siblings = new bytes32[](1);
        siblings[0] = keccak256(
            abi.encode(keccak256("fairbind/epoch-leaf/v1"), filler.nonce, filler.receiptLeaf)
        );
        FairBindCore.ReceiptProof memory boundaryProof =
            FairBindCore.ReceiptProof(lower ? 0 : 1, 2, siblings);
        FairBindCore.ReceiptProof memory emptyProof;
        FairBindMerkle.ReceiptEntry memory emptyEntry;
        vm.prank(address(0xBEEF)); // anyone
        if (lower) {
            fairbind.proveOmission(
                firstNonce, emptyEntry, emptyProof, boundary, boundaryProof,
                uint8(FairBindCore.ProofBoundary.LOWER)
            );
        } else {
            fairbind.proveOmission(
                firstNonce, boundary, boundaryProof, emptyEntry, emptyProof,
                uint8(FairBindCore.ProofBoundary.UPPER)
            );
        }
        require(
            fairbind.getPurchase(firstNonce).financialState
                == uint8(FairBindCore.FinancialState.REFUNDABLE),
            "omission"
        );
    }

    function testServeTimeoutExactBoundaryAndDoubleRefund() public {
        bytes32 n = _settle(bytes16(uint128(70)), _request());
        _openNonDelivery(n);
        uint256 due = fairbind.getCase(n).serveDue;
        vm.roll(due);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutServe(n);
        vm.roll(due + 1);
        fairbind.timeoutServe(n);
        fairbind.claimRefund(n);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimRefund(n);
    }

    function testTwoRefundsBelowFailureLimitChargeNoPenalty() public {
        token.mint(BUYER, 1_000_000);
        FairBindCore.CanonicalRequest memory req = _request();
        bytes32 first = _settle(bytes16(uint128(71)), req);
        bytes32 second = _settle(bytes16(uint128(72)), req);
        uint256 beforeBalance = token.balanceOf(BUYER);
        _openNonDelivery(first);
        _openNonDelivery(second);
        vm.roll(363);
        fairbind.timeoutServe(first);
        fairbind.timeoutServe(second);
        fairbind.claimRefund(first);
        fairbind.claimRefund(second);
        require(fairbind.getLockedForfeit() == 2 * (uint256(10_000_000) / 3), "two shares below failureLimit");
        require(token.balanceOf(address(0xCAFE)) == 0, "nothing to the treasury");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).failureCount == 2, "two failures");
        require(token.balanceOf(BUYER) == beforeBalance + 20_000, "two principals and deposits");
    }

    function testFinalizeServedBoundary() public {
        bytes32 n = _settle(bytes16(uint128(73)), _request());
        _openNonDelivery(n);
        fairbind.served(n, keccak256("bundle"));
        uint256 end = fairbind.getCase(n).challengeUntil;
        vm.roll(end);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.finalizeServed(n);
        vm.roll(end + 1);
        fairbind.finalizeServed(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
    }

    function testMaximumResponsePublication() public {
        FairBindCore.CanonicalRequest memory req = _request();
        bytes16 key = bytes16(uint128(74));
        bytes32 n = _settle(key, req);
        _openAndEscalate(n);
        bytes memory body = new bytes(65_536);
        bytes32 leaf = keccak256(new bytes(16_384));
        bytes32 pair = keccak256(abi.encode(keccak256("fairbind/response-node/v1"), leaf, leaf));
        bytes32 root = keccak256(abi.encode(keccak256("fairbind/response-node/v1"), pair, pair));
        FairBindCore.FairBindReceipt memory receipt = _receipt(n, root);
        fairbind.publish(n, key, req, body, receipt, _sign(receipt));
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.DELIVERED), "maximum");
    }

    function testOversizedResponseRejects() public {
        FairBindCore.CanonicalRequest memory req = _request();
        bytes16 key = bytes16(uint128(75));
        bytes32 n = _settle(key, req);
        _openAndEscalate(n);
        FairBindCore.FairBindReceipt memory receipt = _receipt(n, keccak256("unused"));
        bytes memory signature = _sign(receipt);
        bytes memory body = new bytes(65_537);
        vm.expectRevert(FairBindCore.ResponseTooLarge.selector);
        fairbind.publish(n, key, req, body, receipt, signature);
    }

    function testPreSealWrongDeliveryUsesSealedRandomness() public {
        FairBindCore.CanonicalRequest memory req = _request();
        bytes32 n = _settle(bytes16(uint128(80)), req);
        FairBindCore.FairBindReceipt memory receipt = _receipt(n, keccak256("wrong"));
        bytes memory signature = _sign(receipt);
        vm.prank(BUYER);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), receipt, signature);
        require(fairbind.getCase(n).randomness == bytes32(0), "not sealed yet");
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        fairbind.seal(sellerId, 0);
        bytes32 random = fairbind.getAnchor(sellerId, 0).randomness;
        require(random != bytes32(0), "sealed hash");
        fairbind.assignVerifier(n);
        require(fairbind.getCase(n).randomness == random, "stale pre-seal randomness");
    }

    function testConcurrentBuyerTimeoutPreservesJudgmentThenRefundsAndUnlocks() public {
        bytes32 n = _settle(bytes16(uint128(91)), _request());
        _sample(n);
        uint32 verifierId = fairbind.getCase(n).assignedVerifierId;
        uint256 liability = fairbind.getVerifier(verifierId).lockedLiability;
        _openConcurrentBuyer(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.JUDGING), "judgment intact");
        require(fairbind.getVerifier(verifierId).lockedLiability == liability, "liability retained");
        uint64 due = fairbind.getBuyerRecovery(n).serveDue;
        vm.roll(due);
        vm.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutBuyerServe(n);
        vm.roll(uint256(due) + 1);
        fairbind.timeoutBuyerServe(n);
        require(fairbind.getVerifier(verifierId).lockedLiability == 0, "liability canceled");
        require(fairbind.getBuyerRecovery(n).state == uint8(FairBindCore.CaseState.UNSERVED), "buyer closed");
        fairbind.claimRefund(n);
        require(token.balanceOf(BUYER) == 10_000_000, "principal and buyer deposit conserved");
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimRefund(n);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutBuyerServe(n);
    }

    function testConcurrentBuyerPublicationKeepsJudgmentAndLiability() public {
        bytes16 key = bytes16(uint128(92));
        FairBindCore.CanonicalRequest memory req = _request();
        bytes32 n = _settle(key, req);
        _sample(n);
        uint32 verifierId = fairbind.getCase(n).assignedVerifierId;
        _openConcurrentBuyer(n);
        fairbind.buyerServed(n, keccak256("bundle"));
        vm.prank(BUYER);
        fairbind.escalateBuyerServe(n);
        bytes memory response = bytes("published to buyer");
        FairBindCore.FairBindReceipt memory rec = _receipt(n, keccak256(response));
        fairbind.publishBuyerResponse(n, key, req, response, rec, _sign(rec));
        require(fairbind.getBuyerRecovery(n).state == uint8(FairBindCore.CaseState.DELIVERED), "buyer delivered");
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.JUDGING), "judgment intact");
        require(fairbind.getVerifier(verifierId).lockedLiability == 1_010_000, "liability intact");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.HELD), "judgment hold");
        vm.roll(50_000);
        vm.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
    }

    function testConcurrentChunkRestartAndOrder() public {
        bytes16 key = bytes16(uint128(93));
        FairBindCore.CanonicalRequest memory req = _request();
        bytes32 n = _settle(key, req);
        _sample(n);
        _openConcurrentBuyer(n);
        fairbind.buyerServed(n, keccak256("bundle"));
        vm.prank(BUYER);
        fairbind.escalateBuyerServe(n);
        bytes memory first = new bytes(16_384);
        bytes memory second = bytes("tail");
        bytes32 root = keccak256(abi.encode(keccak256("fairbind/response-node/v1"), keccak256(first), keccak256(second)));
        FairBindCore.FairBindReceipt memory rec = _receipt(n, root);
        bytes memory sig = _sign(rec);
        fairbind.beginBuyerPublication(n, key, req, rec, sig, 16_388, 2);
        vm.expectRevert(FairBindCore.InvalidPublication.selector);
        fairbind.publishBuyerChunk(n, 1, second);
        fairbind.publishBuyerChunk(n, 0, first);
        fairbind.beginBuyerPublication(n, key, req, rec, sig, 16_388, 2);
        require(fairbind.getBuyerRecovery(n).publishedChunks == 0, "restart counter");
        fairbind.publishBuyerChunk(n, 0, first);
        fairbind.publishBuyerChunk(n, 1, second);
        fairbind.finalizeBuyerPublication(n);
        require(fairbind.getBuyerRecovery(n).state == uint8(FairBindCore.CaseState.DELIVERED), "published");
    }

    function testQualityAndBuyerDepositsBothRefundedOnBuyerTimeout() public {
        bytes32 n = _settle(bytes16(uint128(94)), _request());
        FairBindCore.FairBindReceipt memory rec = _receipt(n, keccak256("wrong"));
        bytes memory sig = _sign(rec);
        vm.prank(BUYER);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), rec, sig);
        token.mint(BUYER, 5_000_000);
        vm.roll(62);
        _openConcurrentBuyer(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.ASSIGNING), "pending judgment retained");
        vm.roll(uint256(fairbind.getBuyerRecovery(n).serveDue) + 1);
        fairbind.timeoutBuyerServe(n);
        fairbind.claimRefund(n);
        require(token.balanceOf(BUYER) == 15_000_000, "both deposits and principal");
    }

    function testVerifierAndBuyerServeRoutesRemainIndependent() public {
        bytes32 n = _settle(bytes16(uint128(95)), _request());
        _sample(n);
        // Registered verifier owners are this test contract.
        fairbind.requestServe(n);
        _openConcurrentBuyer(n);
        fairbind.served(n, keccak256("verifier bundle"));
        fairbind.buyerServed(n, keccak256("buyer bundle"));
        fairbind.acceptServe(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.JUDGING), "verifier resumed");
        require(fairbind.getBuyerRecovery(n).state == uint8(FairBindCore.CaseState.SERVE_CONFIRM), "buyer unaffected");
        vm.prank(BUYER);
        fairbind.acceptBuyerServe(n);
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.JUDGING), "judgment remains");
    }

    function _sample(bytes32 n) internal {
        vm.roll(600);
        fairbind.anchor(sellerId, 0, _oneEntry(keccak256("root")), 1, keccak256("publication"));
        // A deterministic selected sample fixture; no claim about unbiased randomness.
        bytes32 random;
        for (uint256 i = 1; i <= 1024; i++) {
            bytes32 candidate = bytes32(i);
            if (uint256(keccak256(abi.encode(keccak256("fairbind/sample/v1"), candidate,
                sellerId, uint24(0), n))) < type(uint256).max / 10) {
                random = candidate;
                break;
            }
        }
        require(random != bytes32(0), "selected fixture");
        vm.roll(TEST_EPOCH0_BEACON_BLOCK + 1);
        vm.setBlockhash(TEST_EPOCH0_BEACON_BLOCK, random);
        fairbind.seal(sellerId, 0);
        fairbind.openSample(n);
    }

    function _openConcurrentBuyer(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory empty;
        vm.prank(BUYER);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
    }

    function _openNonDelivery(bytes32 nonce) internal {
        vm.roll(62);
        FairBindCore.FairBindReceipt memory empty;
        vm.prank(BUYER);
        fairbind.dispute(nonce, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
    }

    function _openAndEscalate(bytes32 nonce) internal {
        _openNonDelivery(nonce);
        fairbind.served(nonce, keccak256("bundle"));
        vm.prank(BUYER);
        fairbind.escalate(nonce);
    }

    function _settle(bytes16 key, FairBindCore.CanonicalRequest memory request)
        internal
        returns (bytes32 nonce)
    {
        bytes32 requestHash =
            fairbind.canonicalRequestHash(request, keccak256("fairbind/http-canon/v1"));
        nonce = fairbind.deriveNonce(sellerId, 3, CLAIMS, BUYER, key, requestHash);
        FairBindCore.TransferAuthorization memory authorization =
            FairBindCore.TransferAuthorization(BUYER, address(fairbind), 10_000, 0, 100, nonce);
        fairbind.settle(sellerId, 3, CLAIMS, key, requestHash, authorization, new bytes(65));
    }

    function _receipt(bytes32 nonce, bytes32 responseHash)
        internal
        view
        returns (FairBindCore.FairBindReceipt memory receipt)
    {
        FairBindCore.PurchaseView memory purchase = fairbind.getPurchase(nonce);
        receipt = FairBindCore.FairBindReceipt({
            version: 1,
            sellerId: sellerId,
            profileId: 3,
            nonce: nonce,
            requestHash: purchase.requestHash,
            responseHash: responseHash,
            claimsHash: CLAIMS,
            predicateCommitment: keccak256("commitment"),
            epoch: purchase.epoch,
            issuedAt: 1
        });
    }

    function _sign(FairBindCore.FairBindReceipt memory receipt) internal returns (bytes memory) {
        bytes32 digest = fairbind.receiptDigest(receipt);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(SELLER_KEY, digest);
        return abi.encodePacked(r, s, v);
    }

    function _request() internal pure returns (FairBindCore.CanonicalRequest memory request) {
        request.method = bytes("GET");
        request.path = bytes("/v1/quote");
        request.query = bytes("symbol=ETH-USD");
        request.headerBlock = bytes("accept:application/json\n");
        request.body = "";
    }

    function _profile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = keccak256("fairbind/http-canon/v1");
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 100_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 200_000;
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
