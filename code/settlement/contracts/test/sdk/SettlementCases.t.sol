// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import { SampledSettlement, SettlementBase, SettlementModule, Receipt, Leaf, Opening, Auth, Account } from "./SampledSettlement.sol";
import { MockWallet } from "./MockAuthToken.sol";

/// Settlement, binding, anchor, dispute, swap-proof and release cases of the
/// reference settlement contract (local chain, mock token).
contract SettlementCasesTest is SdkBase {
    bytes32 internal constant TAG = keccak256("p5/response/v1");

    struct Ct {
        bytes32 k;
        bytes ct;
        bytes pt;
    }

    function _ctFor(bytes32 nonce, uint256 i, bool honest) internal pure returns (Ct memory c, bytes32 hR) {
        bytes32 psi = keccak256(abi.encode("psi", i));
        c.k = keccak256(abi.encode("key", i));
        c.pt = _pt(256, psi);
        c.ct = _encrypt(c.k, nonce, c.pt);
        hR = honest ? keccak256(abi.encodePacked(TAG, c.pt)) : keccak256("another response");
    }

    /// One epoch on `pid` with `n` sales; sale i is signed when signed[i].
    /// Each receipt commits to an encrypted response; `honest[i]` decides
    /// whether h_r matches the plaintext of ct.
    function _epoch(bytes32 pid, bool[] memory signed, bool[] memory honest)
        internal
        returns (Leaf[] memory ls, Ct[] memory cs)
    {
        uint256 n = signed.length;
        ls = new Leaf[](n);
        cs = new Ct[](n);
        for (uint256 i; i < n; i++) {
            Receipt memory r = _buy(pid, _rs(pid, i, PRICE), i);
            bytes32 hR;
            (cs[i], hR) = _ctFor(r.nonce, i, honest[i]);
            r.ctHash = keccak256(cs[i].ct);
            r.keyHash = keccak256(abi.encode(cs[i].k));
            r.responseHash = hR;
            ls[i].rs = r;
            if (signed[i]) ls[i].sigB = _ack(pid, r, false);
        }
        // keep cs aligned with ls after sorting
        for (uint256 i = 1; i < n; i++) {
            for (uint256 j = i; j > 0 && ls[j - 1].rs.nonce > ls[j].rs.nonce; j--) {
                (ls[j], ls[j - 1]) = (ls[j - 1], ls[j]);
                (cs[j], cs[j - 1]) = (cs[j - 1], cs[j]);
            }
        }
        _anchor(pid, ls);
    }

    function _one(bool s, bool h) internal pure returns (bool[] memory a, bool[] memory b) {
        a = new bool[](1);
        b = new bool[](1);
        a[0] = s;
        b[0] = h;
    }

    function _openAs(address who, bytes32 pid, Leaf[] memory ls, uint8 kind, bytes memory mandate) internal {
        Opening memory o = _opening(pid, ls, 0);
        vm.prank(who);
        f.openDispute(o, kind, mandate, 3);
    }

    function _status(bytes32 pid, bytes32 nonce) internal view returns (uint8) {
        return f.sale(pid, nonce).status;
    }

    // ------------------------------------------------------ settle, bind

    function test_settleBoundRecordsBinding() public {
        Receipt memory r = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        SampledSettlement.Sale memory s = f.sale(pidP, r.nonce);
        require(s.payer == buyer && s.amount == PRICE, "sale");
        require(s.binding == keccak256(abi.encode(r.requestHash, r.claimsHash)), "binding");
        require(token.balanceOf(f.vaultOf(pidP)) == PRICE, "vault holds");
    }

    function test_settleWrongBoundNonceReverts() public {
        Receipt memory r = _rs(pidP, 0, PRICE);
        bytes32 salt = keccak256("s");
        r.nonce = keccak256("not the bound nonce");
        Auth memory a = _auth(pidP, PRICE, r.nonce);
        bytes memory sig = _authSig(a);
        vm.expectRevert(SettlementBase.Binding.selector);
        f.settle(a, sig, r.requestHash, r.claimsHash, salt);
    }

    function test_settleOverCapReverts() public {
        Auth memory a = _auth(pidP, CAP + 1, keccak256("n"));
        bytes memory sig = _authSig(a);
        vm.expectRevert(SettlementBase.OverCap.selector);
        f.settle(a, sig, 0, 0, 0);
    }

    function test_settleUnknownVaultReverts() public {
        Auth memory a = _auth(pidP, PRICE, keccak256("n"));
        a.to = address(0xBEEF);
        bytes memory sig = _authSig(a);
        vm.expectRevert(SettlementBase.Unknown.selector);
        f.settle(a, sig, 0, 0, 0);
    }

    function test_completeBindingWindow() public {
        Receipt memory r = _rs(pidP, 0, PRICE);
        bytes32 salt = keccak256("s");
        r.nonce = f.boundNonce(pidP, r.requestHash, r.claimsHash, salt);
        Auth memory a = _auth(pidP, PRICE, r.nonce);
        f.settle(a, _authSig(a), 0, 0, 0); // facilitator dropped the triple
        uint256 id = vm.snapshotState();
        vm.roll(block.number + f.D_INC() + 1);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.completeBinding(pidP, r.nonce, r.requestHash, r.claimsHash, salt);
        vm.revertToState(id);
        vm.roll(block.number + f.D_INC());
        vm.expectRevert(SettlementBase.Binding.selector);
        m.completeBinding(pidP, r.nonce, keccak256("other request"), r.claimsHash, salt);
        m.completeBinding(pidP, r.nonce, r.requestHash, r.claimsHash, salt);
        require(f.sale(pidP, r.nonce).binding == keccak256(abi.encode(r.requestHash, r.claimsHash)), "completed");
    }

    function test_anchorRejectsLeafAgainstBinding() public {
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        ls[0].rs.requestHash = keccak256("another request"); // seller writes another request
        _toAnchor();
        require(f.anchorUnit(_unit(pidP, ls)) == 10, "binding reason");
    }

    function test_anchorRejectsBeforeBindingWait() public {
        vm.roll(f.lastBlock(epoch) - 5);
        Leaf[] memory ls = new Leaf[](1);
        Auth memory a = _auth(pidP, PRICE, keccak256("unbound"));
        f.settle(a, _authSig(a), 0, 0, 0);
        ls[0].rs = _rs(pidP, 0, PRICE);
        ls[0].rs.nonce = a.nonce;
        vm.roll(f.lastBlock(epoch) + 1);
        require(f.anchorUnit(_unit(pidP, ls)) == 10, "binding wait");
    }

    function test_unansweredLeafRefundedAtAnchor() public {
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        ls[0].unanswered = 1;
        uint256 b0 = token.balanceOf(buyer);
        _anchor(pidP, ls);
        require(_status(pidP, ls[0].rs.nonce) == f.ST_REFUNDED(), "refunded");
        require(token.balanceOf(buyer) == b0 + PRICE, "buyer paid back");
    }

    function test_anchorBetaFromBuyerSignature() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        Opening memory o = _opening(pidP, ls, 0);
        require(o.beta, "beta");
        // a non-delivery dispute cannot open on a signed leaf
        vm.prank(buyer);
        vm.expectRevert(SettlementBase.State.selector);
        f.openDispute(o, 1, "", 0);
    }

    // ------------------------------------------------------- non-delivery

    function test_nonDeliveryUnansweredRefunds() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        uint256 b0 = token.balanceOf(buyer);
        _openAs(buyer, pidP, ls, 1, "");
        require(token.balanceOf(buyer) == b0 - DEPOSIT, "deposit taken");
        vm.expectRevert(SettlementBase.State.selector);
        m.closeDispute(pidP, ls[0].rs.nonce, 1, 1); // T_d not over
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidP, ls[0].rs.nonce, 1, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "price and deposit back");
    }

    function test_nonDeliveryDeliveredDepositToPayer() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        uint256 b0 = token.balanceOf(buyer);
        _openAs(buyer, pidP, ls, 1, "");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        require(!m.challengeDecrypt(pidP, n, 1, 1, cs[0].ct, 0), "matches");
        vm.expectRevert(SettlementBase.State.selector);
        m.closeDispute(pidP, n, 1, 1); // a matching challenge does not end it early
        vm.roll(block.number + f.T_X() + 1);
        require(!m.closeDispute(pidP, n, 1, 1), "no refund");
        require(token.balanceOf(buyer) == b0, "deposit back to the payer");
        require(_status(pidP, n) == f.ST_HELD(), "sale continues");
    }

    function test_nonDeliveryByStrangerDepositToSeller() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        uint256 t0 = token.balanceOf(tower);
        uint256 s0 = token.balanceOf(seller);
        _openAs(tower, pidP, ls, 1, "");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        m.closeDispute(pidP, n, 1, 0);
        require(token.balanceOf(tower) == t0 - DEPOSIT, "stranger loses deposit");
        require(token.balanceOf(seller) == s0 + DEPOSIT, "seller takes it");
    }

    function test_nonDeliveryWithMandateDepositToOpener() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        bytes memory mandate = _sig(buyerKey, f.mandateDigest(pidP, n, tower, 3));
        uint256 t0 = token.balanceOf(tower);
        _openAs(tower, pidP, ls, 1, mandate);
        require(m.dispute(pidP, n, 1, 1).authorized, "authorized");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        m.closeDispute(pidP, n, 1, 1);
        require(token.balanceOf(tower) == t0, "deposit back to the watchtower");
    }

    function test_wrongMandateNotAuthorized() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        bytes memory mandate = _sig(sellerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 3));
        _openAs(tower, pidP, ls, 1, mandate);
        require(!m.dispute(pidP, ls[0].rs.nonce, 1, 0).authorized, "not authorized");
    }

    function test_duplicateOpenReverts() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        Opening memory o = _opening(pidP, ls, 0);
        _stranger();
        vm.prank(tower);
        f.openDispute(o, 1, "", 0);
        uint256 b0 = token.balanceOf(stranger);
        vm.prank(stranger); // a second third-party opening
        vm.expectRevert(SettlementBase.Duplicate.selector);
        f.openDispute(o, 1, "", 0);
        require(token.balanceOf(stranger) == b0, "no second deposit");
    }

    function test_badCiphertextChallengeRefunds() public {
        (bool[] memory s, bool[] memory h) = _one(false, false);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        uint256 b0 = token.balanceOf(buyer);
        _openAs(buyer, pidP, ls, 1, "");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        vm.prank(tower);
        require(m.challengeDecrypt(pidP, n, 1, 1, cs[0].ct, 0), "mismatch");
        vm.roll(block.number + f.T_X() + 1);
        require(m.closeDispute(pidP, n, 1, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "refund and deposit");
    }

    function test_challengeAfterWindowReverts() public {
        (bool[] memory s, bool[] memory h) = _one(false, false);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        _openAs(buyer, pidP, ls, 1, "");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        vm.expectRevert(SettlementBase.State.selector);
        m.challengeDecrypt(pidP, n, 1, 1, cs[0].ct, 0);
    }

    function test_answerWrongCiphertextReverts() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        _openAs(buyer, pidP, ls, 1, "");
        bytes memory other = abi.encodePacked(cs[0].ct, bytes32(0));
        vm.expectRevert(SettlementBase.State.selector);
        m.answerDeliver(pidP, ls[0].rs.nonce, other, cs[0].k);
    }

    function test_sellerWinsWithBuyerSignature() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        bytes memory ack = _ack(pidP, ls[0].rs, false); // the buyer signed but the seller anchored without it
        uint256 s0 = token.balanceOf(seller);
        _openAs(buyer, pidP, ls, 1, "");
        m.answerWithAck(pidP, n, false, ack);
        require(token.balanceOf(seller) == s0 + DEPOSIT, "deposit to seller");
        require(m.dispute(pidP, n, 1, 1).state == f.D_CLOSED(), "closed");
    }

    function test_responseDeadlineLateAnswerRefunds() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidL, s, h); // r_dl = 20 blocks
        bytes32 n = ls[0].rs.nonce;
        uint256 b0 = token.balanceOf(buyer);
        _openAs(buyer, pidL, ls, 1, "");
        m.answerDeliver(pidL, n, cs[0].ct, cs[0].k); // kept, not delivery on the payer side
        require(m.dispute(pidL, n, 1, 1).state == f.D_OPEN(), "still open");
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidL, n, 1, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "refund and deposit");
    }

    function test_disputeAfterWindowReverts() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        Opening memory o = _opening(pidP, ls, 0);
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        vm.prank(buyer);
        vm.expectRevert(SettlementBase.Timing.selector);
        f.openDispute(o, 1, "", 0);
    }

    // ---------------------------------------------------------------- key

    function test_keyDisputeUnansweredRefunds() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls,) = _epoch(pidC, s, h);
        uint256 b0 = token.balanceOf(buyer);
        _openAs(buyer, pidC, ls, 2, "");
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidC, ls[0].rs.nonce, 2, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "refund and deposit");
    }

    function test_keyDisputeBadKeyChallengeRefunds() public {
        (bool[] memory s, bool[] memory h) = _one(true, false);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        bytes32 n = ls[0].rs.nonce;
        _openAs(buyer, pidC, ls, 2, "");
        m.answerKey(pidC, n, cs[0].k);
        vm.prank(buyer);
        require(m.challengeDecrypt(pidC, n, 2, 1, cs[0].ct, 0), "mismatch");
        vm.roll(block.number + f.T_X() + 1);
        require(m.closeDispute(pidC, n, 2, 1), "refund");
    }

    function test_keyDisputeOffchainKeyChallenge() public {
        (bool[] memory s, bool[] memory h) = _one(true, false);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        bytes32 n = ls[0].rs.nonce;
        _openAs(buyer, pidC, ls, 2, "");
        require(m.challengeDecrypt(pidC, n, 2, 1, cs[0].ct, cs[0].k), "mismatch with the key received");
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidC, n, 2, 1), "refund");
    }

    function test_keyDisputeOnPlainProfileReverts() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(buyer);
        vm.expectRevert(SettlementBase.State.selector);
        f.openDispute(o, 2, "", 0);
    }

    /// Posts a sample value under which none of `ns` is sampled.
    function _postUnsampled(bytes32 pid, bytes32[] memory ns) internal {
        uint256 id = _requestSample(pid, epoch);
        uint256 w = 1;
        for (;; w++) {
            uint256 v = _valueOf(pid, epoch, id, w);
            bool any;
            for (uint256 i; i < ns.length; i++) if (f.sampledBy(v, ns[i], PRICE, CAP)) any = true;
            if (!any) break;
        }
        _fulfill(id, w);
    }

    function _nonces(Leaf[] memory ls) internal pure returns (bytes32[] memory ns) {
        ns = new bytes32[](ls.length);
        for (uint256 i; i < ls.length; i++) ns[i] = ls[i].rs.nonce;
    }

    function _deducted() internal view {
        Account memory ac = m.account(seller);
        require(ac.suspended && ac.bond == 0 && ac.locked == CAP, "deducted and suspended");
    }

    function _noFailure() internal view {
        Account memory ac = m.account(seller);
        require(!ac.suspended && ac.bond == CAP && ac.failures == 0, "no failure");
    }

    function _frozenFailure(bytes32 n) internal view {
        require(m.account(seller).suspended, "suspended");
        require(_status(pidP, n) == f.ST_FROZEN(), "failure in the cursor");
    }

    function test_openDisputeDoesNotHoldCursor() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        _openAs(buyer, pidP, ls, 1, "");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        _postUnsampled(pidP, _nonces(ls));
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        require(m.release(seller) == 0, "open dispute: not paid by the cursor");
        require(f.accountCursor(seller) == epoch + 1, "cursor passed");
        require(_status(pidP, n) == f.ST_HELD(), "held");
        uint256 s0 = token.balanceOf(seller);
        m.closeDispute(pidP, n, 1, 1);
        require(_status(pidP, n) == f.ST_PAID(), "paid after the dispute");
        require(token.balanceOf(seller) == s0 + PRICE, "seller paid");
    }

    // ------------------------------------------------------- swap proof

    function test_swapProofFreezesDeductsAndSuspends() public {
        Receipt memory r = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        bytes32 ch = f.profile(pidP).codeHash;
        bytes memory rsSig = _sig(sellerKey, _typed(f.DOMAIN_SEPARATOR(), _rsHash(pidP, ch, r)));
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = abi.decode(abi.encode(r), (Receipt)); // a copy, not an alias
        ls[0].rs.responseHash = keccak256("swapped response"); // anchored leaf differs, no sigB
        uint256 b0 = token.balanceOf(buyer);
        _anchor(pidP, ls);
        m.proveSwap(_opening(pidP, ls, 0), r, rsSig);
        _deducted();
        require(_status(pidP, r.nonce) == f.ST_FROZEN(), "frozen");
        m.claimFrozen(pidP, r.nonce);
        require(token.balanceOf(buyer) == b0 + PRICE, "refund by claim");
        Auth memory a = _auth(pidP, PRICE, keccak256("after"));
        bytes memory sig = _authSig(a);
        vm.expectRevert(SettlementBase.State.selector);
        f.settle(a, sig, 0, 0, 0);
    }

    function test_swapProofRejectsSameReceipt() public {
        Receipt memory r = _buy(pidP, _rs(pidP, 0, PRICE), 0);
        bytes32 ch = f.profile(pidP).codeHash;
        bytes memory rsSig = _sig(sellerKey, _typed(f.DOMAIN_SEPARATOR(), _rsHash(pidP, ch, r)));
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = r;
        _anchor(pidP, ls);
        Opening memory o = _opening(pidP, ls, 0);
        vm.expectRevert(SettlementBase.State.selector);
        m.proveSwap(o, r, rsSig);
    }

    // ------------------------------------------------------------ release

    function test_releaseAfterProofPaysSeller() public {
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256("psi r");
        bytes memory mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(pidP, 0, PRICE);
        r.responseHash = keccak256(abi.encodePacked(TAG, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        Leaf[] memory ls = new Leaf[](1);
        ls[0].rs = _buy(pidP, r, 0);
        ls[0].sigB = _ack(pidP, ls[0].rs, false);
        _anchor(pidP, ls);
        uint256 id = vm.snapshotState();
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        require(m.release(seller) == 0, "no proof by M_e + T_p: failure, nothing paid");
        _frozenFailure(ls[0].rs.nonce);
        vm.revertToState(id);
        vm.roll(f.valueDeadline(epoch) + 1);
        f.prove(_opening(pidP, ls, 0), mat);
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        uint256 s0 = token.balanceOf(seller);
        require(m.release(seller) == PRICE, "paid");
        require(token.balanceOf(seller) == s0 + PRICE, "seller paid");
        require(f.accountCursor(seller) == epoch + 1, "cursor");
        _noFailure();
    }

    function test_refundedSaleStaysInTheSample() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        _openAs(buyer, pidP, ls, 1, "");
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        m.closeDispute(pidP, ls[0].rs.nonce, 1, 1);
        require(_status(pidP, ls[0].rs.nonce) == f.ST_REFUNDED(), "refunded");
        require(m.release(seller) == 0, "nothing to pay");
        require(m.account(seller).failures == 1, "a refunded sampled sale without a pass is a failure");
    }

    function test_releaseSkipsRefundedUnsampled() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        _openAs(buyer, pidP, ls, 1, "");
        _postUnsampled(pidP, _nonces(ls));
        vm.roll(f.anchorDeadline(epoch) + f.T_C() + 1);
        m.closeDispute(pidP, ls[0].rs.nonce, 1, 1);
        require(m.release(seller) == 0, "nothing to pay");
        require(m.account(seller).failures == 0, "no failure");
    }

    // ------------------------------------------------- payer side

    address internal stranger = address(0x5757);

    function _stranger() internal {
        token.mint(stranger, 10_000_000);
        vm.prank(stranger);
        token.approve(address(f), type(uint256).max);
    }

    function _openWith(address who, bytes32 pid, Leaf[] memory ls, uint8 kind, bytes memory mandate, uint8 kinds) internal {
        Opening memory o = _opening(pid, ls, 0);
        vm.prank(who);
        f.openDispute(o, kind, mandate, kinds);
    }

    function test_mandateForAnotherDelegateIsThirdParty() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        _stranger();
        bytes memory mandate = _sig(buyerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 3));
        _openWith(stranger, pidP, ls, 1, mandate, 3); // reused by another sender
        require(!m.dispute(pidP, ls[0].rs.nonce, 1, 0).authorized, "not payer side");
    }

    function test_mandateWithoutTheKindIsThirdParty() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        bytes memory mandate = _sig(buyerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 2)); // key disputes only
        _openWith(tower, pidP, ls, 1, mandate, 2);
        require(!m.dispute(pidP, ls[0].rs.nonce, 1, 0).authorized, "kind not delegated");
    }

    /// The payer-side slot opens beside an open third-party dispute; neither
    /// takes over the other. One delivery by ct and k answers both; the
    /// payer-side deposit returns, the third-party deposit goes to the seller.
    function test_payerSideSlotBesideThirdParty() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        _stranger();
        uint256 st0 = token.balanceOf(stranger);
        uint256 b0 = token.balanceOf(buyer);
        uint256 s0 = token.balanceOf(seller);
        _openWith(stranger, pidP, ls, 1, "", 0);
        _openWith(buyer, pidP, ls, 1, "", 0);
        require(m.dispute(pidP, n, 1, 0).opener == stranger && m.dispute(pidP, n, 1, 1).opener == buyer, "two slots");
        m.answerDeliver(pidP, n, cs[0].ct, cs[0].k);
        require(m.dispute(pidP, n, 1, 0).state == f.D_ANSWERED() && m.dispute(pidP, n, 1, 1).state == f.D_ANSWERED(), "both answered");
        vm.roll(block.number + f.T_X() + 1);
        m.closeDispute(pidP, n, 1, 0);
        m.closeDispute(pidP, n, 1, 1);
        require(token.balanceOf(stranger) == st0 - DEPOSIT, "third party deposit to seller");
        require(token.balanceOf(seller) == s0 + DEPOSIT, "seller took one deposit");
        require(token.balanceOf(buyer) == b0, "payer deposit back");
    }

    function test_secondPayerSideOpenReverts() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        bytes memory mandate = _sig(buyerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 3));
        _openWith(buyer, pidP, ls, 1, "", 0);
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBase.Duplicate.selector);
        f.openDispute(o, 1, mandate, 3);
    }

    /// Third-party slot after a payer-side dispute: allowed (its own slot);
    /// a second third-party dispute reverts.
    function test_thirdPartySlotIndependent() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        _stranger();
        _openWith(buyer, pidP, ls, 1, "", 0);
        _openWith(stranger, pidP, ls, 1, "", 0);
        require(m.dispute(pidP, ls[0].rs.nonce, 1, 0).opener == stranger, "third-party slot");
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBase.Duplicate.selector);
        f.openDispute(o, 1, "", 0);
    }

    /// A colluding third party opens a key dispute, the seller reveals a key
    /// under which ct does not decrypt to h_r, and nobody challenges in T_x:
    /// that slot ends on the seller's side. The payer-side key dispute opens
    /// in its own slot, the key on chain is its answer, T_x counts from its
    /// opening, and the buyer's challenge with the ciphertext it checked
    /// refunds the sale.
    function test_payerSideKeyDisputeAfterThirdPartyKeyDispute() public {
        (bool[] memory s, bool[] memory h) = _one(true, false);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        bytes32 n = ls[0].rs.nonce;
        _stranger();
        uint256 b0 = token.balanceOf(buyer);
        _openWith(stranger, pidC, ls, 2, "", 0);
        m.answerKey(pidC, n, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        require(!m.closeDispute(pidC, n, 2, 0), "seller side");
        _openWith(buyer, pidC, ls, 2, "", 0);
        SampledSettlement.Dispute memory d = m.dispute(pidC, n, 2, 1);
        require(d.state == f.D_ANSWERED() && d.deadline == block.number + f.T_X(), "stored k answers, T_x from now");
        vm.prank(buyer);
        require(m.challengeDecrypt(pidC, n, 2, 1, cs[0].ct, 0), "mismatch");
        vm.roll(block.number + f.T_X() + 1);
        require(m.closeDispute(pidC, n, 2, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "refund, deposit back");
    }

    function test_closedSlotCannotOpenAgain() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        _stranger();
        _openWith(stranger, pidC, ls, 2, "", 0);
        m.answerKey(pidC, ls[0].rs.nonce, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        m.closeDispute(pidC, ls[0].rs.nonce, 2, 0);
        Opening memory o = _opening(pidC, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBase.Duplicate.selector);
        f.openDispute(o, 2, "", 0);
    }

    function test_lateAnswerCountsOnThirdPartyDispute() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidL, s, h); // r_dl = 20 blocks
        bytes32 n = ls[0].rs.nonce;
        _stranger();
        uint256 s0 = token.balanceOf(seller);
        _openWith(stranger, pidL, ls, 1, "", 0);
        m.answerDeliver(pidL, n, cs[0].ct, cs[0].k);
        require(m.dispute(pidL, n, 1, 0).state == f.D_ANSWERED(), "delivered");
        vm.roll(block.number + f.T_X() + 1);
        require(!m.closeDispute(pidL, n, 1, 0), "no refund from a third party");
        require(token.balanceOf(seller) == s0 + DEPOSIT, "deposit to seller");
    }

    /// A late answer given in a third-party dispute does not count for the
    /// payer side: the payer-side dispute ends undelivered and refunds.
    function test_lateAnswerFromThirdPartyDisputeRefundsPayerSide() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidL, s, h);
        bytes32 n = ls[0].rs.nonce;
        _stranger();
        uint256 b0 = token.balanceOf(buyer);
        _openWith(stranger, pidL, ls, 1, "", 0);
        m.answerDeliver(pidL, n, cs[0].ct, cs[0].k);
        _openWith(buyer, pidL, ls, 1, "", 0);
        require(m.dispute(pidL, n, 1, 1).state == f.D_OPEN(), "late answer is not delivery");
        vm.expectRevert(SettlementBase.Duplicate.selector);
        m.answerDeliver(pidL, n, cs[0].ct, cs[0].k); // nothing more to post
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidL, n, 1, 1), "refund");
        require(token.balanceOf(buyer) == b0 + PRICE, "refund and deposit");
    }

    function test_refundIsFinal() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        _openWith(buyer, pidP, ls, 1, "", 0);
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(pidP, ls[0].rs.nonce, 1, 1), "refund");
        _stranger();
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.State.selector);
        f.openDispute(o, 1, "", 0);
    }

    function test_payerKeyDisputeAnsweredDepositBack() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        bytes32 n = ls[0].rs.nonce;
        uint256 b0 = token.balanceOf(buyer);
        _openWith(buyer, pidC, ls, 2, "", 0);
        m.answerKey(pidC, n, cs[0].k);
        vm.roll(block.number + f.T_X() + 1);
        require(!m.closeDispute(pidC, n, 2, 1), "no refund");
        require(token.balanceOf(buyer) == b0, "payer-side key deposit returned");
    }

    function test_ctAndKeyAnswerLaterKeyDispute() public {
        (bool[] memory s, bool[] memory h) = _one(true, true);
        (Leaf[] memory ls, Ct[] memory cs) = _epoch(pidC, s, h);
        bytes32 n = ls[0].rs.nonce;
        _openWith(buyer, pidC, ls, 2, "", 0);
        m.answerDeliver(pidC, n, cs[0].ct, cs[0].k); // ct and k answer a key dispute
        require(m.dispute(pidC, n, 2, 1).state == f.D_ANSWERED(), "answered by ct and k");
        _stranger();
        _openWith(stranger, pidC, ls, 2, "", 0);
        require(m.dispute(pidC, n, 2, 0).state == f.D_ANSWERED(), "later key dispute answered by the stored ct and k");
    }

    function test_answerKeyNeedsOpenKeyDispute() public {
        // a plaintext-profile sale cannot carry a key dispute; use the
        // ciphertext profile with an unsigned leaf for non-delivery and check
        // that a key posted elsewhere is absent
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidC, s, h);
        _openWith(buyer, pidC, ls, 1, "", 0);
        require(m.dispute(pidC, ls[0].rs.nonce, 1, 1).state == f.D_OPEN(), "no stored answer");
        vm.expectRevert(SettlementBase.State.selector);
        m.answerKey(pidC, ls[0].rs.nonce, bytes32(0)); // no key dispute is open
    }

    function test_ackAnswersLaterNonDeliveryDispute() public {
        (bool[] memory s, bool[] memory h) = _one(false, true);
        (Leaf[] memory ls,) = _epoch(pidP, s, h);
        bytes32 n = ls[0].rs.nonce;
        bytes memory ack = _ack(pidP, ls[0].rs, false);
        _stranger();
        _openWith(stranger, pidP, ls, 1, "", 0);
        m.answerWithAck(pidP, n, false, ack);
        uint256 s0 = token.balanceOf(seller);
        _openWith(buyer, pidP, ls, 1, "", 0);
        require(m.dispute(pidP, n, 1, 1).state == f.D_CLOSED(), "stored signature answers it");
        require(token.balanceOf(seller) == s0 + DEPOSIT, "deposit to seller");
    }

    function _walletSale(MockWallet wal) internal returns (Leaf[] memory ls) {
        token.mint(address(wal), 1_000_000);
        Receipt memory r = _rs(pidP, 0, PRICE);
        bytes32 salt = keccak256("wallet salt");
        r.nonce = f.boundNonce(pidP, r.requestHash, r.claimsHash, salt);
        Auth memory a = Auth(address(wal), f.vaultOf(pidP), PRICE, VALID_AFTER, VALID_AFTER + 3600, r.nonce);
        bytes memory sig = _sig(
            buyerKey,
            _typed(
                token.DOMAIN_SEPARATOR(),
                keccak256(abi.encode(TWA_TYPEHASH, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce))
            )
        );
        f.settle(a, sig, r.requestHash, r.claimsHash, salt);
        ls = new Leaf[](1);
        ls[0].rs = r;
        _anchor(pidP, ls);
    }

    function test_erc1271PayerMandateChecked() public {
        MockWallet wal = new MockWallet(buyer);
        Leaf[] memory ls = _walletSale(wal);
        bytes memory mandate = _sig(buyerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 3));
        _openWith(tower, pidP, ls, 1, mandate, 3);
        require(m.dispute(pidP, ls[0].rs.nonce, 1, 1).authorized, "isValidSignature accepted the mandate");
    }

    function test_erc1271PayerBadMandateReverts() public {
        MockWallet wal = new MockWallet(buyer);
        Leaf[] memory ls = _walletSale(wal);
        bytes memory mandate = _sig(sellerKey, f.mandateDigest(pidP, ls[0].rs.nonce, tower, 3));
        Opening memory o = _opening(pidP, ls, 0);
        vm.prank(tower);
        vm.expectRevert(SettlementBase.Unauthorized.selector);
        f.openDispute(o, 1, mandate, 3);
    }
}
