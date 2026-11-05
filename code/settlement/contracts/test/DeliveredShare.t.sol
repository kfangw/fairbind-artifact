// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { ExchangeStore } from "../src/modules/ExchangeStore.sol";
import { ExchangeBase } from "./ExchangeBase.sol";

/// The seller's share of a delivered non-delivery dispute under measured
/// costs (ADR 0037, rule D2-24 (d')): min(maxPublicationCost, the measured
/// cost of the seller's calls); the rest is locked for a vote profile
/// without receipt signatures and goes back to the buyer under them. A
/// receipt-signature vote profile ends a lapsed non-delivery dispute with
/// the refund alone; the purchase's sample case stays (rule D2-33 (f)).
contract DeliveredShareTest is ExchangeBase {
    uint256 internal constant D0 = 5_000_000;

    function _startVote(uint8 m, uint32 samplePpm) internal {
        mode = m;
        FairBindCore.ServiceProfileInput memory p = _exchangeProfile();
        p.samplePpm = samplePpm;
        _deployWith(p);
        hv.roll(10);
    }

    function _request() internal pure returns (FairBindCore.CanonicalRequest memory r) {
        r.method = bytes("GET");
        r.path = bytes("/v1/quote");
        r.query = bytes("symbol=BTC-USD");
        r.headerBlock = bytes("accept:application/json\n");
        r.body = "";
    }

    /// A purchase with a canonical request, so that the seller can publish.
    function _buyRequest(bytes16 key) internal returns (bytes32 n) {
        bytes32 req = fairbind.canonicalRequestHash(_request(), keccak256("fairbind/http-canon/v1"));
        n = fairbind.deriveNonce(sellerId, PROFILE, CLAIMS, buyer, key, req);
        uint256 a = _ts() - 5;
        FairBindCore.TransferAuthorization memory auth =
            FairBindCore.TransferAuthorization(buyer, address(fairbind), 10_000, a, a + 1000, n);
        bytes memory sig = _sig(BUYER_KEY, token.receiveAuthorizationDigest(buyer, address(fairbind), 10_000, a, a + 1000, n));
        fairbind.settle(sellerId, PROFILE, CLAIMS, key, req, auth, sig);
    }

    function _disputeND(bytes32 n) internal {
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        if (_now() <= p.responseDue) hv.roll(uint256(p.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
    }

    /// Anchors epoch 0 with the given leaves (leafOf, or the standard
    /// receipt) and seals it with a beacon that samples none of them.
    function _sealUnsampled(bytes32[] memory ns) internal {
        _anchorX(0, ns);
        uint64 rb = fairbind.getAnchor(sellerId, 0).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, _unsampledBeacon(0, ns));
        fairbind.seal(sellerId, 0);
    }

    function _cost(bytes32 n) internal view returns (uint256) {
        (,, ExchangeStore.Ladder memory l) = fx.getExchangeRecord(n);
        return l.cost;
    }

    // --------------------------------------- vote without receipt signatures

    function test_deliveredShareIsTheMeasuredCostAndTheRestIsLocked() public {
        (uint256 share, uint256 locked, uint256 cost) = _servedShare("");
        require(cost != 0 && share == cost, "the measured cost");
        require(locked == D0 - share, "the rest is locked");
    }

    function test_deliveredShareOfTheWholeCapIsCaught() public {
        (uint256 share,,) = _servedShare("ExchangeMutants.sol:LadderCapExchange");
        require(share == D0, "mutation caught");
    }

    function _servedShare(string memory ex) internal returns (uint256 share, uint256 locked, uint256 cost) {
        if (bytes(ex).length != 0) exchangeArtifact = ex;
        _startVote(ExchangeStore.MODE_NONE, 40_000);
        bytes32 n = _buy();
        _disputeND(n);
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        hv.prank(buyer);
        fairbind.acceptServe(n);
        require(_state(n) == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
        cost = _cost(n);
        _sealUnsampled(_one(n));
        hv.roll(40_011);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        uint256 l0 = fairbind.getLockedForfeit();
        fairbind.releasePurchase(n);
        share = token.balanceOf(SELLER_OWNER) - s0 - 10_000;
        locked = fairbind.getLockedForfeit() - l0;
    }

    /// The publication ladder: each stage once; the share sums its measured
    /// calls; a second start of the publication reverts.
    function test_publicationLadderSumsItsCalls() public {
        _startVote(ExchangeStore.MODE_NONE, 40_000);
        bytes16 key = bytes16(uint128(900));
        bytes32 n = _buyRequest(key);
        _disputeND(n);
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        uint256 c1 = _cost(n);
        hv.prank(buyer);
        fairbind.escalate(n);
        bytes memory body = new bytes(16_400);
        for (uint256 i; i < body.length; i++) body[i] = bytes1(uint8(i));
        bytes memory first = new bytes(16_384);
        bytes memory second = new bytes(16);
        for (uint256 i; i < 16_384; i++) first[i] = body[i];
        for (uint256 i; i < 16; i++) second[i] = body[16_384 + i];
        bytes32 root = keccak256(abi.encode(keccak256("fairbind/response-node/v1"), keccak256(first), keccak256(second)));
        FairBindCore.PurchaseView memory p = fairbind.getPurchase(n);
        FairBindCore.FairBindReceipt memory r =
            FairBindCore.FairBindReceipt(1, sellerId, PROFILE, n, p.requestHash, root, CLAIMS, keccak256("c"), p.epoch, 1);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(SELLER_OWNER);
        fairbind.beginPublication(n, key, _request(), r, rs, 16_400, 2);
        uint256 c2 = _cost(n);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidPublication.selector);
        fairbind.beginPublication(n, key, _request(), r, rs, 16_400, 2);
        hv.prank(SELLER_OWNER);
        fairbind.publishChunk(n, 0, first);
        hv.prank(SELLER_OWNER);
        fairbind.publishChunk(n, 1, second);
        uint256 c3 = _cost(n);
        hv.prank(SELLER_OWNER);
        fairbind.finalizePublication(n);
        uint256 c4 = _cost(n);
        require(c1 != 0 && c2 > c1 && c3 > c2 && c4 > c3, "every stage adds its cost");
        require(_state(n) == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
        _sealUnsampled(_one(n));
        hv.roll(40_011);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(n);
        uint256 share = c4 < 5_000_000 ? c4 : 5_000_000;
        require(token.balanceOf(SELLER_OWNER) - s0 == 10_000 + share, "min(cap, sum)");
    }

    function test_profileWithoutCostTermsKeepsTheWholeDeposit() public {
        mode = ExchangeStore.MODE_NONE;
        _deployExchange(_productionProfile(), _input(0), false);
        hv.roll(10);
        bytes32 n = _buy();
        _disputeND(n);
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        hv.prank(buyer);
        fairbind.acceptServe(n);
        require(_cost(n) == 0, "nothing measured");
        _sealUnsampled(_one(n));
        hv.roll(40_011);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(n);
        require(token.balanceOf(SELLER_OWNER) - s0 == 10_000 + D0, "d0 to the seller as before");
    }

    // ---------------------------------------- vote with receipt signatures

    function test_keyDisclosureEndsTheDisputeAndTheRestGoesBack() public {
        _startVote(ExchangeStore.MODE_VOTE_SIG, 40_000);
        bytes32 n = _buy();
        _postSigned(n);
        _disputeND(n);
        Bundle memory b = bundleOf[n];
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InvalidProof.selector);
        fx.discloseKey(n, false, keccak256("wrong"), b.ct, b.leaf);
        hv.prank(SELLER_OWNER);
        fx.discloseKey(n, false, b.ek, b.ct, b.leaf);
        require(_state(n) == uint8(FairBindCore.CaseState.DELIVERED), "delivered");
        uint256 cost = _cost(n);
        require(cost != 0, "measured");
        hv.roll(600);
        _matchAllAfter(n);
        uint256 s0 = token.balanceOf(SELLER_OWNER);
        uint256 b0 = token.balanceOf(buyer);
        hv.roll(40_011);
        fairbind.releasePurchase(n);
        require(token.balanceOf(SELLER_OWNER) - s0 == 10_000 + cost, "the measured cost");
        require(token.balanceOf(buyer) - b0 == D0 - cost, "the rest back to the buyer");
    }

    function _matchAllAfter(bytes32 n) internal {
        _anchorX(0, _one(n));
        _matchAll(_one(n));
        uint64 rb = fairbind.getAnchor(sellerId, 0).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, _unsampledBeacon(0, _one(n)));
        fairbind.seal(sellerId, 0);
    }

    function test_lapsedDisputeRefundsAndTheSampleCaseStays() public {
        _startVote(ExchangeStore.MODE_VOTE_SIG, 1_000_000);
        bytes32 n = _buy();
        _postSigned(n);
        _disputeND(n);
        hv.roll(uint256(fairbind.getCase(n).serveDue) + 1);
        fairbind.timeoutServe(n);
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refund due");
        require(_bond().failureCount == 0, "no failure");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "active");
        uint256 b0 = token.balanceOf(buyer);
        fairbind.claimRefund(n);
        require(token.balanceOf(buyer) - b0 == 10_000 + D0, "price and deposit");
        _anchorX(0, _one(n));
        _matchAll(_one(n));
        _sealX(0);
        fairbind.openSample(n);
        require(fairbind.getCase(n).trigger == uint8(FairBindCore.CaseTrigger.SAMPLE), "the sample case opens");
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDED), "the refund stays");
        hv.roll(_now() + 301);
        fairbind.timeoutSampleReceipt(n);
        require(_bond().failureCount == 1, "a confirmed failure");
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDED), "no second refund");
    }

    function test_unboundPurchaseOpensNoSampleCase() public {
        _startVote(ExchangeStore.MODE_VOTE_SIG, 1_000_000);
        bytes32 n = _buy();
        _anchorX(0, _one(n));
        _sealX(0);
        hv.expectRevert(FairBindCore.NotBound.selector);
        fairbind.openSample(n);
        fx.refundUnbound(n);
        require(_fs(n) == uint8(FairBindCore.FinancialState.REFUNDABLE), "refunded");
    }
}
