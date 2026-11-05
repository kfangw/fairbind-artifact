// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "./ReleaseBase.sol";
import { SettlementBase, UnitHeader } from "./SampledSettlement.sol";

/// Anchor completion with owed effects (T2): the transaction whose stored
/// units fill the count fixes, as of itself, each sale's completion effect
/// (a marked sale refunded to its payer, an accepted sale not frozen at that
/// point paid to the seller) and moves the tokens of the first N_REL
/// settlement records; the rest move by pull calls (pullCompletion in
/// settlement order, pullSale for one sale), by anyone, at any time, never
/// changing who is owed what. The cursor neither waits for the pulls nor
/// pays owed sales.
contract AnchorCompletionTest is ReleaseBase {
    address internal stranger = address(0x5157);

    function _pending(bytes32 pid, bytes32 nonce) internal view returns (bool p) {
        (p,) = m.pullPending(pid, nonce);
    }

    /// n sales of DUST on profile j in e0 of the given leaf kind.
    function _sales(uint256 j, uint256 base, uint256 n, uint8 kind) internal returns (Sold[] memory ss) {
        ss = _sell(pids[j], base, n, DUST, 4, false);
        _kind(pids[j], ss, kind);
    }

    // ------------------------------------------------------- boundaries

    /// N_REL marked sales: every refund moves in the completing transaction.
    function test_marked_n_rel_all_in_completion() public {
        _deploy(1, 1, DUST);
        _at(e0, 5);
        Sold[] memory ss = _sales(0, 0, 256, K_MARKED);
        uint256 b0 = token.balanceOf(buyer);
        _anchorAll(pids[0], e0, ss);
        require(token.balanceOf(buyer) == b0 + 256 * DUST, "all refunded at completion");
        bytes32[] memory ns = f.epochNonces(pids[0], e0);
        for (uint256 i; i < ns.length; i++) {
            require(f.sale(pids[0], ns[i]).status == f.ST_REFUNDED() && !_pending(pids[0], ns[i]), "refunded, nothing owed");
        }
        vm.expectRevert(SettlementBase.State.selector);
        m.pullCompletion(pids[0], e0);
    }

    /// N_REL + 1 marked sales: the last in settlement order is refunded (owed)
    /// from the completion and its tokens move by a pull of anyone, once.
    function test_marked_n_rel_plus_one_owed_then_pulled() public {
        _deploy(1, 1, DUST);
        _at(e0, 5);
        Sold[] memory ss = _sales(0, 0, 257, K_MARKED);
        uint256 b0 = token.balanceOf(buyer);
        _anchorAll(pids[0], e0, ss);
        require(token.balanceOf(buyer) == b0 + 256 * DUST, "first N_REL moved");
        bytes32[] memory ns = f.epochNonces(pids[0], e0);
        bytes32 last = ns[256];
        require(f.sale(pids[0], last).status == f.ST_REFUNDED(), "owed refund is a refund");
        require(_pending(pids[0], last), "its transfer waits for a pull");
        require(_pending(pids[0], ns[255]) == false, "the 256th moved");
        require(m.claimDeadline(pids[0], last) == 0, "not claimable");
        vm.prank(stranger);
        m.pullSale(pids[0], last);
        require(token.balanceOf(buyer) == b0 + 257 * DUST, "pulled to the payer");
        require(!_pending(pids[0], last), "done");
        vm.expectRevert(SettlementBase.State.selector);
        m.pullSale(pids[0], last);
        require(m.pullCompletion(pids[0], e0) == 257, "sequential pull goes over it");
        require(token.balanceOf(buyer) == b0 + 257 * DUST, "no second transfer");
        vm.expectRevert(SettlementBase.State.selector);
        m.pullCompletion(pids[0], e0);
    }

    /// Accepted sales above N_REL: the seller is owed every acceptance
    /// payment from the completion; the cursor does not pay them again and
    /// does not wait for the pull; the pull pays the rest.
    function test_accepted_owed_cursor_independent() public {
        _deploy(1, 1, DUST);
        _at(e0, 5);
        Sold[] memory ss = _sales(0, 0, 300, K_ACCEPTED);
        uint256 s0 = token.balanceOf(seller);
        _anchorAll(pids[0], e0, ss);
        require(token.balanceOf(seller) == s0 + 256 * DUST, "first N_REL paid at completion");
        bytes32[] memory ns = f.epochNonces(pids[0], e0);
        require(f.sale(pids[0], ns[299]).status == f.ST_ACCEPT_PAID() && _pending(pids[0], ns[299]), "owed");
        // the cursor's path runs while 44 acceptance payments are still owed
        _valueOnlyFull(pids[0], e0, ss);
        _ripe(e0);
        m.releaseUnit(seller);
        m.releaseUnit(seller);
        m.release(seller);
        require(m.releasePay(seller, e0) == 0 && m.releasePay(seller, e0) == 0, "the cursor pays no accepted sale");
        require(token.balanceOf(seller) == s0 + 256 * DUST, "still owed");
        require(m.pullCompletion(pids[0], e0) == 300, "pull");
        require(token.balanceOf(seller) == s0 + 300 * DUST, "all accepted sales paid once");
        for (uint256 i; i < ns.length; i++) require(f.sale(pids[0], ns[i]).status == f.ST_ACCEPT_PAID(), "accept paid");
    }

    // --------------------------------------------------------- freezes

    /// Evidence of a double-signed anchor of the second profile's epoch: a
    /// freeze from that profile's first sale, settled before the first
    /// profile's sales.
    function _doubleSign(bytes32 pid, Sold[] memory one) internal {
        bytes32 ch = f.profile(pid).codeHash;
        (bytes32 l, bytes32 l0) = _leafHash(pid, ch, one[0]);
        UnitHeader memory h = UnitHeader(
            pid, uint32(e0), 1, 1, one[0].rs.nonce, one[0].rs.nonce, l, keccak256(abi.encode("another root0", l0)), keccak256(abi.encode(new address[](0)))
        );
        bytes memory sig = _sig(
            sellerKey,
            _typed(
                f.DOMAIN_SEPARATOR(),
                keccak256(abi.encode(f.UNIT_TYPEHASH(), h.pid, h.epoch, h.count, h.unitNo, h.first, h.last, h.root, h.root0, h.snapshotHash))
            )
        );
        vm.prank(stranger);
        m.proveDoubleSign(h, sig);
    }

    /// 300 sales on profile 0 (even settlement index accepted, odd marked),
    /// one plain sale on profile 1 settled before them, anchored first.
    function _mixed() internal returns (Sold[] memory a, Sold[] memory c) {
        _deploy(1, 2, DUST);
        _at(e0, 5);
        c = _sales(1, 9000, 1, K_PLAIN);
        vm.roll(block.number + 1);
        a = _sell(pids[0], 0, 300, DUST, 4, false);
        for (uint256 i; i < a.length; i++) {
            a[i].kind = i % 2 == 0 ? K_ACCEPTED : K_MARKED;
            if (i % 2 == 0) a[i].sigB = _ack(pids[0], a[i].rs, true);
        }
        _anchorAll(pids[1], e0, c);
    }

    /// A freeze recorded in the same block just before the completing unit:
    /// the accepted sales are frozen at completion (not paid, claimable); the
    /// marked sales are still refunded (T2 refunds frozen marked sales).
    function test_freeze_just_before_completion() public {
        (Sold[] memory a, Sold[] memory c) = _mixed();
        uint256 s0 = token.balanceOf(seller);
        uint256 b0 = token.balanceOf(buyer);
        _doubleSign(pids[1], c);
        require(m.account(seller).failures == 1, "failure recorded");
        _anchorAll(pids[0], e0, a); // same block: the freeze precedes the completion
        require(token.balanceOf(seller) == s0, "no acceptance payment");
        bytes32[] memory ns = f.epochNonces(pids[0], e0);
        require(f.sale(pids[0], ns[0]).status == f.ST_HELD() && !_pending(pids[0], ns[0]), "accepted sale frozen, nothing owed");
        require(m.claimDeadline(pids[0], ns[0]) != 0, "claimable");
        require(f.sale(pids[0], ns[1]).status == f.ST_REFUNDED(), "marked refunded");
        require(_pending(pids[0], ns[299]), "last marked sale owed");
        require(m.pullCompletion(pids[0], e0) == 300, "pull the rest");
        require(token.balanceOf(buyer) == b0 + 150 * DUST, "150 marked refunds");
        vm.prank(stranger);
        m.claimFrozen(pids[0], ns[298]);
        require(token.balanceOf(buyer) == b0 + 151 * DUST, "a frozen accepted sale claimed");
        require(token.balanceOf(seller) == s0, "seller got nothing");
    }

    /// The same freeze in the same block just after the completing unit: the
    /// acceptance payments are owed from the completion and stay owed; the
    /// pull pays them although a freeze now covers the sales.
    function test_freeze_just_after_completion() public {
        (Sold[] memory a, Sold[] memory c) = _mixed();
        uint256 s0 = token.balanceOf(seller);
        uint256 b0 = token.balanceOf(buyer);
        _anchorAll(pids[0], e0, a);
        _doubleSign(pids[1], c); // same block, after the completion
        bytes32[] memory ns = f.epochNonces(pids[0], e0);
        require(token.balanceOf(seller) == s0 + 128 * DUST, "accepted among the first N_REL paid");
        require(f.sale(pids[0], ns[298]).status == f.ST_ACCEPT_PAID() && _pending(pids[0], ns[298]), "owed despite the freeze");
        require(m.claimDeadline(pids[0], ns[298]) == 0, "not claimable");
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(pids[0], ns[298]);
        require(m.pullCompletion(pids[0], e0) == 300, "pull");
        require(token.balanceOf(seller) == s0 + 150 * DUST, "all 150 acceptance payments");
        require(token.balanceOf(buyer) == b0 + 150 * DUST, "all 150 refunds");
    }

    // ---------------------------------------------------- missed anchor

    /// Units stored but the count never filled by A_e: nothing is owed and
    /// nothing can be pulled; the missed anchor freezes every sale and the
    /// marked sales are claimed like any frozen sale.
    function test_missed_anchor_nothing_owed() public {
        _deploy(1, 1, DUST);
        _at(e0, 5);
        Sold[] memory ss = _sales(0, 0, 300, K_MARKED);
        _qsort(ss, 0, int256(ss.length) - 1);
        vm.roll(f.lastBlock(e0) + f.D_INC() + 1);
        require(f.anchorUnit(_unitOf(pids[0], e0, ss, 0, 256, 1, f.profile(pids[0]).codeHash)) == 0, "unit 1 stored");
        require(!f.epochComplete(pids[0], e0), "incomplete");
        bytes32 n0 = ss[0].rs.nonce;
        require(f.sale(pids[0], n0).status == f.ST_HELD() && !_pending(pids[0], n0), "no completion effect");
        vm.expectRevert(SettlementBase.State.selector);
        m.pullSale(pids[0], n0);
        vm.expectRevert(SettlementBase.State.selector);
        m.pullCompletion(pids[0], e0);
        vm.roll(f.anchorDeadline(e0) + 1);
        m.declareAnchorMissed(pids[0], e0);
        uint256 b0 = token.balanceOf(buyer);
        vm.prank(stranger);
        m.claimFrozen(pids[0], n0);
        require(token.balanceOf(buyer) == b0 + DUST, "claimed as a frozen sale");
        require(f.sale(pids[0], n0).status == f.ST_REFUNDED(), "refunded");
    }
}
