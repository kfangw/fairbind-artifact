// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../../src/FairBindCore.sol";
import { MockEIP3009Token } from "../MockEIP3009Token.sol";
import { ReproBase } from "./ReproBase.sol";

/// Case A: a plain upfront EIP-3009 payment to the seller account versus the
/// same purchase settled through FairBind with the contract as payee.
contract ReproA_UpfrontVsDeferred is ReproBase {
    uint256 internal constant G = 10_000;
    address internal constant FACILITATOR = address(0xFAC);

    /// A1: upfront payment straight to the seller account. Delivery failure is
    /// an off-chain fact represented by a boolean; nothing on chain observes it.
    function test_A1_upfrontPaymentHasNoOnChainRecourse() public {
        MockEIP3009Token t = new MockEIP3009Token();
        t.setVerifySignatures(true);
        address b = hv.addr(BUYER_KEY);
        address sellerAccount = hv.addr(SELLER_KEY);
        t.mint(b, 100_000);
        bytes32 authNonce = keccak256("upfront-1");
        (uint8 v, bytes32 r, bytes32 s) =
            hv.sign(BUYER_KEY, t.authorizationDigest(b, sellerAccount, G, 0, 100, authNonce));

        uint256 buyerBefore = t.balanceOf(b);
        hv.prank(FACILITATOR);
        t.transferWithAuthorization(b, sellerAccount, G, 0, 100, authNonce, v, r, s);
        bool delivered = false;
        bool wrongBytes = true;

        _logStr("A1 upfront transfer to seller account");
        _log("A1 delivered (0/1)", delivered ? 1 : 0);
        _log("A1 wrong bytes (0/1)", wrongBytes ? 1 : 0);
        _log("A1 buyer balance delta (loss)", buyerBefore - t.balanceOf(b));
        _log("A1 seller account balance", t.balanceOf(sellerAccount));
        require(t.balanceOf(b) == buyerBefore - G, "A1 buyer debited");
        require(t.balanceOf(sellerAccount) == G, "A1 seller credited");

        // The seller is an account without code: there is no function to call.
        _log("A1 seller account code size", sellerAccount.code.length);
        require(sellerAccount.code.length == 0, "A1 seller has no code");

        // The token offers no buyer-initiated pull-back: transferFrom needs the
        // seller's allowance, and the authorization cannot be reused.
        hv.prank(b);
        hv.expectRevert(bytes("allowance"));
        t.transferFrom(sellerAccount, b, G);
        hv.expectRevert(bytes("used"));
        t.transferWithAuthorization(b, sellerAccount, G, 0, 100, authNonce, v, r, s);
        _log("A1 buyer balance after recovery attempts", t.balanceOf(b));
        require(t.balanceOf(b) == buyerBefore - G, "A1 no recovery");
        _logStr("A1 OBSERVED: funds moved, no recovery path");
    }

    /// A2: the same purchase through FairBind, seller never responds.
    function test_A2_fairbindDefersAndRefundsNonDelivery() public {
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        _deploy(p);
        uint256 buyerStart = token.balanceOf(buyer);
        uint256 ownerStart = token.balanceOf(SELLER_OWNER);
        uint256 contractStart = token.balanceOf(address(fairbind));

        bytes32 n = _purchase(G);
        FairBindCore.PurchaseView memory pv = fairbind.getPurchase(n);
        _log("A2 seller owner delta at settle", token.balanceOf(SELLER_OWNER) - ownerStart);
        _log("A2 contract delta at settle", token.balanceOf(address(fairbind)) - contractStart);
        _log("A2 financialState (1=DEFERRED)", pv.financialState);
        _log("A2 releaseBlock - settledBlock", pv.releaseBlock - pv.settledBlock);
        require(token.balanceOf(SELLER_OWNER) == ownerStart, "A2 seller not paid");
        require(token.balanceOf(address(fairbind)) == contractStart + G, "A2 contract holds");
        require(pv.financialState == uint8(FairBindCore.FinancialState.DEFERRED), "A2 deferred");
        require(pv.releaseBlock - pv.settledBlock == p.deferBlocks, "A2 release block");

        hv.roll(uint256(pv.responseDue) + 1);
        FairBindCore.FairBindReceipt memory empty;
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), empty, "");
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        hv.roll(uint256(c.serveDue) + 1);
        fairbind.timeoutServe(n);
        c = fairbind.getCase(n);
        _log("A2 case state after timeoutServe (UNSERVED)", c.state);
        _log("A2 financialState (4=REFUNDABLE)", fairbind.getPurchase(n).financialState);
        fairbind.claimRefund(n);
        _log("A2 buyer final minus start (0 = whole)", buyerStart - token.balanceOf(buyer));
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        _log("A2 seller status (2=SUSPENDED)", fairbind.getSeller(sellerId).status);
        _log("A2 bond balance after", fairbind.getBond(bondId).balance);
        require(c.state == uint8(FairBindCore.CaseState.UNSERVED), "A2 unserved");
        require(token.balanceOf(buyer) == buyerStart, "A2 buyer whole");
        // First confirmed failure suspends, freezes and deducts one share of the
        // penalty; the terminal sanction waits for failureLimit (ADR 0018).
        require(fairbind.getBond(bondId).balance == p.sellerPenalty - p.sellerPenalty / p.failureLimit, "A2 one share before failure limit");
        require(fairbind.getBond(bondId).failureCount == 1, "A2 failure recorded");
        require(
            fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED),
            "A2 suspended"
        );
    }

    /// A3: the same purchase through FairBind, seller delivers wrong bytes.
    function test_A3_fairbindRefundsWrongDeliveryAfterFail() public {
        _deploy(_baseProfile());
        uint256 buyerStart = token.balanceOf(buyer);
        bytes32 n = _purchase(G);
        bytes32[] memory one = new bytes32[](1);
        one[0] = n;
        _buildTree(one);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("epoch randomness a3"));
        fairbind.seal(sellerId, 0);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        if (fairbind.getCase(n).state == uint8(FairBindCore.CaseState.ASSIGNING)) {
            fairbind.assignVerifier(n);
        }
        _judge(n, 2);
        hv.roll(uint256(fairbind.getReview(n).appealUntil) + 1);
        fairbind.finalizeCase(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        _log("A3 final verdict (2=FAIL)", c.finalVerdict);
        _log("A3 financialState (3=REFUNDABLE)", fairbind.getPurchase(n).financialState);
        fairbind.claimRefund(n);
        _log("A3 buyer final minus start (0 = whole)", buyerStart - token.balanceOf(buyer));
        require(c.finalVerdict == 2, "A3 fail");
        require(token.balanceOf(buyer) == buyerStart, "A3 buyer whole");
    }

    /// A4: an honest delivery is paid to the seller only once deferBlocks pass.
    function test_A4_honestPaymentReleasedOnlyAtReleaseBlock() public {
        _deploy(_baseProfile());
        uint256 ownerStart = token.balanceOf(SELLER_OWNER);
        bytes32 n = _purchase(G);
        bytes32[] memory one = new bytes32[](1);
        one[0] = n;
        _buildTree(one);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 1, keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("epoch randomness a4"));
        fairbind.seal(sellerId, 0);
        FairBindCore.PurchaseView memory pv = fairbind.getPurchase(n);
        (bool sampled,) = fairbind.isSampled(n);
        _log("A4 sampled (0/1, no case opened either way)", sampled ? 1 : 0);
        hv.roll(uint256(pv.releaseBlock) - 1);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(n);
        _log("A4 seller owner delta at releaseBlock-1", token.balanceOf(SELLER_OWNER) - ownerStart);
        hv.roll(uint256(pv.releaseBlock));
        fairbind.releasePurchase(n);
        _log("A4 seller owner delta at releaseBlock", token.balanceOf(SELLER_OWNER) - ownerStart);
        require(token.balanceOf(SELLER_OWNER) == ownerStart + G, "A4 released");
    }
}
