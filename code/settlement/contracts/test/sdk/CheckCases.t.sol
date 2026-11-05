// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import {
    SettlementBase,
    Profile,
    Receipt,
    Leaf,
    Unit,
    Opening,
    Auth,
    UnitHeader,
    Account
} from "./SampledSettlement.sol";
import { P5Ctx, IP5Verifier } from "../g10/p5/P5Ref.sol";

/// Verification contract for these cases: a proof passes when the material
/// hashes to the receipt's material commitment. An honest seller holds that
/// material; any other material fails.
contract CommitVerifier is IP5Verifier {
    function verify(P5Ctx calldata c, bytes calldata material) external pure returns (bool) {
        return keccak256(material) == c.materialCommit;
    }
}

/// Cases written from the settlement rules (confirmed failures, the narrow
/// freeze, deductions, suspension and re-entry, claims of frozen sales, the
/// cursor, missed and double-signed anchors, open disputes and the cursor,
/// the honest seller), independently of the implementation's own tests.
/// Sampling is steered by amount: a sale of the full cap is always sampled,
/// and the posted value is chosen so that no smaller sale is.
contract CheckCasesTest is SdkBase {
    CommitVerifier internal cv;
    bytes32 internal p1;
    bytes32 internal p2;
    uint256 internal buyer2Key = uint256(keccak256("check case buyer two"));
    address internal buyer2;
    address internal stranger = address(0x57A2);
    uint256 internal counter;
    uint256 internal e0;

    function setUp() public override {
        super.setUp();
        cv = new CommitVerifier();
        p1 = _reg(CAP, 1);
        p2 = _reg(CAP, 2);
        buyer2 = vm.addr(buyer2Key);
        token.mint(buyer2, 100_000_000);
        token.mint(stranger, 100_000_000);
        vm.prank(buyer2);
        token.approve(address(f), type(uint256).max);
        vm.prank(stranger);
        token.approve(address(f), type(uint256).max);
        e0 = epoch;
    }

    // ------------------------------------------------------------ helpers

    function _reg(uint64 cap, uint256 salt) internal returns (bytes32) {
        Profile memory p = _profile(address(cv), 0, 0, 1);
        p.cap = cap;
        p.inputRule = keccak256(abi.encode("check case rule", salt));
        vm.prank(seller);
        return f.register(p, 2_000_000);
    }

    function _mat(Receipt memory r) internal pure returns (bytes memory) {
        return abi.encode("check material", r.requestHash);
    }

    /// A settled sale by the holder of `key` on `pid`.
    function _sell(uint256 key, bytes32 pid, uint64 amount) internal returns (Receipt memory r) {
        uint256 i = ++counter;
        r = _rs(pid, 7000 + i, amount);
        r.materialCommit = keccak256(_mat(r));
        bytes32 salt = keccak256(abi.encode("check case salt", pid, i));
        r.nonce = f.boundNonce(pid, r.requestHash, r.claimsHash, salt);
        Auth memory a = Auth(vm.addr(key), f.vaultOf(pid), amount, VALID_AFTER, VALID_AFTER + 3600, r.nonce);
        bytes memory s = _sig(
            key,
            _typed(
                token.DOMAIN_SEPARATOR(),
                keccak256(abi.encode(TWA_TYPEHASH, a.from, a.to, a.value, a.validAfter, a.validBefore, a.nonce))
            )
        );
        f.settle(a, s, r.requestHash, r.claimsHash, salt);
    }

    function _lf(Receipt memory r) internal pure returns (Leaf memory l) {
        l.rs = r;
    }

    function _lfAccept(bytes32 pid, Receipt memory r) internal returns (Leaf memory l) {
        l.rs = r;
        l.accept = true;
        l.sigB = _ack(pid, r, true);
    }

    function _lfMarked(Receipt memory r) internal pure returns (Leaf memory l) {
        l.rs = r;
        l.unanswered = 1;
    }

    function _one(Leaf memory a) internal pure returns (Leaf[] memory ls) {
        ls = new Leaf[](1);
        ls[0] = a;
    }

    function _two(Leaf memory a, Leaf memory b) internal pure returns (Leaf[] memory ls) {
        ls = new Leaf[](2);
        ls[0] = a;
        ls[1] = b;
    }

    function _rollTo(uint256 b) internal {
        if (block.number < b) vm.roll(b);
    }

    /// Anchors the whole profile epoch in one unit (sorts `ls` in place).
    function _anchorEp(bytes32 pid, Leaf[] memory ls, uint256 ep) internal {
        epoch = ep;
        _sort(ls);
        Unit memory u = _unit(pid, ls);
        _rollTo(f.lastBlock(ep) + f.D_INC() + 1);
        require(block.number <= f.anchorDeadline(ep), "anchor window passed");
        require(f.anchorUnit(u) == 0, "anchor rejected");
        require(f.epochComplete(pid, ep), "complete");
    }

    /// Posts a sample value under which exactly the sales of the full cap
    /// are sampled.
    function _value(bytes32 pid, uint256 ep, Leaf[] memory ls) internal {
        _rollTo(f.anchorDeadline(ep) + 1);
        uint64 cap = f.profile(pid).cap;
        uint256 id = m.requestSample(pid, ep);
        for (uint256 w = 1; w < 5000; w++) {
            uint256 v = _valueOf(pid, ep, id, w);
            bool ok = true;
            for (uint256 j; j < ls.length && ok; j++) {
                if (ls[j].unanswered != 0) continue;
                bool want = ls[j].rs.amount >= cap;
                if (f.sampledBy(v, ls[j].rs.nonce, ls[j].rs.amount, cap) != want) ok = false;
            }
            if (ok) {
                _fulfill(id, w);
                return;
            }
        }
        revert("no value");
    }

    function _openAt(bytes32 pid, Leaf[] memory ls, bytes32 nonce, uint256 ep) internal returns (Opening memory) {
        epoch = ep;
        return _opening(pid, ls, _find(ls, nonce));
    }

    function _prove(bytes32 pid, Leaf[] memory ls, Receipt memory r, uint256 ep) internal {
        f.prove(_openAt(pid, ls, r.nonce, ep), _mat(r));
    }

    function _proofEnd(uint256 ep) internal view returns (uint256) {
        return f.valueDeadline(ep) + f.T_P();
    }

    /// First block at which every window of epoch `ep` has passed.
    function _cursorBlock(uint256 ep) internal view returns (uint256 b) {
        b = f.anchorDeadline(ep) + f.T_C();
        if (_proofEnd(ep) > b) b = _proofEnd(ep);
        if (f.signDeadlineEnd(ep) > b) b = f.signDeadlineEnd(ep);
        b += 1;
    }

    /// Moves the cursor past epoch `ep` (and the epochs before it).
    function _releaseThrough(uint256 ep) internal {
        _rollTo(_cursorBlock(ep));
        while (m.accountCursor(seller) <= ep) m.release(seller);
    }

    function _st(bytes32 pid, Receipt memory r) internal view returns (uint8) {
        return f.sale(pid, r.nonce).status;
    }

    function _frozen(bytes32 pid, Receipt memory r) internal view returns (bool) {
        return m.claimDeadline(pid, r.nonce) != 0;
    }

    function _acct() internal view returns (Account memory) {
        return m.account(seller);
    }

    function _sk(bytes32 pid, bytes32 nonce) internal pure returns (bytes32) {
        return keccak256(abi.encode(pid, nonce));
    }

    function _hdr(Unit memory u) internal pure returns (UnitHeader memory) {
        return UnitHeader(
            u.pid, u.epoch, u.count, u.unitNo, u.first, u.last, u.root, u.root0, keccak256(abi.encode(u.snapshot))
        );
    }

    function _hdrSig(uint256 key, UnitHeader memory h) internal returns (bytes memory) {
        return _sig(
            key,
            _typed(
                f.DOMAIN_SEPARATOR(),
                keccak256(
                    abi.encode(
                        f.UNIT_TYPEHASH(),
                        h.pid,
                        h.epoch,
                        h.count,
                        h.unitNo,
                        h.first,
                        h.last,
                        h.root,
                        h.root0,
                        h.snapshotHash
                    )
                )
            )
        );
    }

    function _holders() internal view returns (address[] memory h) {
        h = new address[](15);
        h[0] = buyer;
        h[1] = buyer2;
        h[2] = seller;
        h[3] = tower;
        h[4] = stranger;
        h[5] = address(vrf);
        h[6] = address(this);
        h[7] = address(f);
        h[8] = f.module();
        h[9] = f.vaultOf(p1);
        h[10] = f.vaultOf(p2);
        h[11] = f.vaultOf(pidP);
        h[12] = f.vaultOf(pidC);
        h[13] = f.vaultOf(pidL);
        h[14] = f.vaultOf(pidT0);
    }

    function _bals(address[] memory h) internal view returns (uint256[] memory b) {
        b = new uint256[](h.length);
        for (uint256 i; i < h.length; i++) b[i] = token.balanceOf(h[i]);
    }

    /// One sampled sale on p1 in e0, anchored, with a value posted and no
    /// proof; returns its leaves.
    function _failingSale(uint256 key) internal returns (Receipt memory r, Leaf[] memory ls) {
        r = _sell(key, p1, CAP);
        ls = _one(_lf(r));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
    }

    // ============== (1) no pass by T_p on a sampled sale is a confirmed failure

    /// R4 (b), R7 (a): at M_e + T_p the case is still open (no failure yet,
    /// a failing submission records nothing); after it, no pass is recorded
    /// and the failure is confirmed.
    function test_P1_noPassByProofDeadlineIsConfirmedFailure() public {
        (Receipt memory r, Leaf[] memory ls) = _failingSale(buyerKey);
        require(f.isSampled(p1, r.nonce), "sampled");
        _rollTo(_proofEnd(e0));
        vm.expectRevert(SettlementBase.Timing.selector);
        m.declareSampleFailure(p1, r.nonce);
        Opening memory o = _openAt(p1, ls, r.nonce, e0);
        vm.expectRevert(SettlementBase.VerifierFailed.selector);
        f.prove(o, bytes("not the material"));
        require(!f.passed(_sk(p1, r.nonce)), "nothing recorded");
        require(_acct().failures == 0, "no failure yet");
        vm.roll(_proofEnd(e0) + 1);
        vm.expectRevert(SettlementBase.Timing.selector);
        f.prove(o, _mat(r)); // no pass after T_p, even with the right material
        m.declareSampleFailure(p1, r.nonce);
        Account memory a = _acct();
        require(a.failures == 1 && a.suspended, "confirmed failure");
        require(_frozen(p1, r), "the failed sale is frozen");
    }

    /// R4 (b): a failing submission changes nothing and anyone may submit
    /// again within T_p; a pass ends the case.
    function test_P1_failedSubmissionThenPassInTime() public {
        (Receipt memory r, Leaf[] memory ls) = _failingSale(buyerKey);
        Opening memory o = _openAt(p1, ls, r.nonce, e0);
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.VerifierFailed.selector);
        f.prove(o, bytes("garbage"));
        _rollTo(_proofEnd(e0)); // the last block still takes a pass
        f.prove(o, _mat(r));
        require(f.passed(_sk(p1, r.nonce)), "pass");
        vm.roll(_proofEnd(e0) + 1);
        vm.expectRevert(SettlementBase.State.selector);
        m.declareSampleFailure(p1, r.nonce);
        _releaseThrough(e0);
        require(_st(p1, r) == f.ST_PAID(), "paid");
        require(_acct().failures == 0 && !_acct().suspended, "no failure");
    }

    /// A sale that was not sampled has no case and no failure.
    function test_P1_unsampledSaleHasNoFailure() public {
        Receipt memory r = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lf(r));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        require(!f.isSampled(p1, r.nonce), "not sampled");
        vm.roll(_proofEnd(e0) + 1);
        vm.expectRevert(SettlementBase.NotSampled.selector);
        m.declareSampleFailure(p1, r.nonce);
        _releaseThrough(e0);
        require(_st(p1, r) == f.ST_PAID() && _acct().failures == 0, "paid, no failure");
    }

    /// R6 (a)(0): with no value by M_e every sale of the epoch is sampled, so
    /// a small sale without a pass is a confirmed failure at the cursor.
    function test_P1_noValueByMeSamplesEverySale() public {
        Receipt memory r = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lf(r));
        _anchorEp(p1, ls, e0);
        vm.roll(f.valueDeadline(e0) + 1);
        require(f.isSampled(p1, r.nonce), "all sampled");
        _releaseThrough(e0);
        require(_acct().failures == 1, "failure at the cursor");
        require(_st(p1, r) == f.ST_FROZEN(), "frozen, not paid");
    }

    /// R5 (a), R7 (a): an accepted sale stays in the sample; its failure is a
    /// confirmed failure (deduction, freeze of later unaccepted sales) and
    /// the accepted sale itself is not refunded.
    function test_P1_acceptedSaleFailureIsConfirmed() public {
        Receipt memory x = _sell(buyerKey, p1, CAP);
        vm.roll(block.number + 1);
        Receipt memory y = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _two(_lfAccept(p1, x), _lf(y));
        uint256 s0 = token.balanceOf(seller);
        _anchorEp(p1, ls, e0);
        require(_st(p1, x) == f.ST_ACCEPT_PAID(), "accept paid at the anchor");
        require(token.balanceOf(seller) == s0 + CAP, "seller paid");
        _value(p1, e0, ls);
        require(f.isSampled(p1, x.nonce), "accepted sale sampled");
        uint256 b0 = token.balanceOf(buyer);
        _releaseThrough(e0);
        Account memory a = _acct();
        require(a.failures == 1 && a.suspended && a.bond == 0 && a.locked == CAP, "confirmed failure");
        require(_st(p1, x) == f.ST_ACCEPT_PAID(), "accepted sale not refunded");
        require(_st(p1, y) == f.ST_FROZEN(), "later unaccepted sale frozen");
        require(token.balanceOf(buyer) == b0, "no refund of the accepted sale");
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, x.nonce);
    }

    /// R4 (b): a sale refunded in a dispute stays in the sample.
    function test_P1_disputeRefundedSaleStaysSampled() public {
        (Receipt memory r, Leaf[] memory ls) = _failingSale(buyerKey);
        Opening memory od = _openAt(p1, ls, r.nonce, e0);
        vm.prank(buyer);
        f.openDispute(od, 1, "", 0);
        vm.roll(block.number + f.T_D() + 1);
        require(m.closeDispute(p1, r.nonce, 1, 1), "refunded");
        require(_st(p1, r) == f.ST_REFUNDED(), "refunded");
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, r.nonce);
        require(_acct().failures == 1 && _acct().locked == CAP, "still a confirmed failure");
    }

    // ===================================================== (2) freeze range

    /// R7 (b), R6 (a)(2): failure of B (profile p2) in the cursor call. A,
    /// settled before s_f, is paid; every later unpaid unaccepted sale of the
    /// account is frozen, on either profile and in the next epoch (a sale
    /// waiting for its case included); an unanswered mark is refunded and an
    /// accepted sale paid at the anchor is outside the freeze.
    function test_P2_freezeFromSfOverTheAccount() public {
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        vm.roll(block.number + 1);
        Receipt memory b = _sell(buyer2Key, p2, CAP);
        vm.roll(block.number + 1);
        Receipt memory c = _sell(buyerKey, p1, PRICE);
        Receipt memory d = _sell(buyerKey, p2, PRICE);
        Receipt memory mk = _sell(buyerKey, p1, PRICE);
        Receipt memory k = _sell(buyerKey, p1, PRICE);
        vm.roll(f.lastBlock(e0) + 1);
        Receipt memory e = _sell(buyerKey, p1, PRICE);
        Leaf[] memory l1 = new Leaf[](4);
        l1[0] = _lf(a);
        l1[1] = _lf(c);
        l1[2] = _lfMarked(mk);
        l1[3] = _lfAccept(p1, k);
        Leaf[] memory l2 = _two(_lf(b), _lf(d));
        uint256 s0 = token.balanceOf(seller);
        _anchorEp(p1, l1, e0);
        _anchorEp(p2, l2, e0);
        require(_st(p1, mk) == f.ST_REFUNDED() && _st(p1, k) == f.ST_ACCEPT_PAID(), "anchor outcomes");
        _value(p1, e0, l1);
        _value(p2, e0, l2);
        Leaf[] memory l3 = _one(_lf(e));
        _anchorEp(p1, l3, e0 + 1);
        _value(p1, e0 + 1, l3);
        _rollTo(_cursorBlock(e0));
        m.release(seller);
        require(_acct().failures == 1, "one failure");
        require(_st(p1, a) == f.ST_PAID(), "before s_f: paid");
        require(_st(p2, b) == f.ST_FROZEN() && _st(p1, c) == f.ST_FROZEN() && _st(p2, d) == f.ST_FROZEN(), "frozen");
        require(_frozen(p1, e), "next epoch's sale frozen");
        require(!_frozen(p1, a) && !_frozen(p1, mk) && !_frozen(p1, k), "outside the freeze");
        require(token.balanceOf(seller) == s0 + a.amount + k.amount, "only A and the accepted sale paid");
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, mk.nonce);
        _releaseThrough(e0 + 1);
        require(_st(p1, e) == f.ST_FROZEN(), "frozen sale not paid by the cursor");
        require(token.balanceOf(seller) == s0 + a.amount + k.amount, "seller gets no frozen payment");
    }

    /// R7 (b): a failure declared before the cursor freezes the later sales;
    /// a sale of an earlier epoch is paid by the cursor afterwards.
    function test_P2_earlierEpochPaidAfterDeclaredFailure() public {
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        Leaf[] memory la = _one(_lf(a));
        vm.roll(f.lastBlock(e0) + 1);
        Receipt memory b = _sell(buyerKey, p1, CAP);
        vm.roll(block.number + 1);
        Receipt memory c = _sell(buyerKey, p1, PRICE);
        _anchorEp(p1, la, e0);
        _value(p1, e0, la);
        Leaf[] memory lb = _two(_lf(b), _lf(c));
        _anchorEp(p1, lb, e0 + 1);
        _value(p1, e0 + 1, lb);
        vm.roll(_proofEnd(e0 + 1) + 1);
        require(m.accountCursor(seller) == e0, "cursor has not passed e0");
        m.declareSampleFailure(p1, b.nonce);
        require(_frozen(p1, c) && _frozen(p1, b) && !_frozen(p1, a), "freeze from s_f");
        _releaseThrough(e0);
        require(_st(p1, a) == f.ST_PAID(), "earlier sale paid");
    }

    // ===================================================== (3) deduction

    /// R7 (c): the deduction min(b(V*_p), balance) is taken from the bond and
    /// goes to no one: no address's token balance rises.
    function test_P3_deductionGoesToNoOne() public {
        (Receipt memory r,) = _failingSale(buyerKey);
        vm.roll(_proofEnd(e0) + 1);
        address[] memory h = _holders();
        uint256[] memory before = _bals(h);
        Account memory a0 = _acct();
        vm.prank(stranger);
        m.declareSampleFailure(p1, r.nonce);
        uint256[] memory afterB = _bals(h);
        for (uint256 i; i < h.length; i++) require(afterB[i] <= before[i], "a balance rose");
        Account memory a1 = _acct();
        require(a0.bond == CAP && a1.bond == 0 && a1.locked == a0.locked + CAP, "deducted min(b, balance)");
    }

    /// R7 (c), R1 (d): each confirmed failure deducts min(b(V*_p), balance),
    /// also while the account is suspended; with nothing left it deducts 0.
    function test_P3_deductionIsMinOfBondAndCap() public {
        vm.prank(seller);
        m.depositBond(seller, CAP / 2); // balance 1.5 b
        Receipt memory b1 = _sell(buyerKey, p1, CAP);
        Receipt memory b2 = _sell(buyerKey, p1, CAP);
        Receipt memory b3 = _sell(buyerKey, p1, CAP);
        Leaf[] memory ls = new Leaf[](3);
        ls[0] = _lf(b1);
        ls[1] = _lf(b2);
        ls[2] = _lf(b3);
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, b1.nonce);
        require(_acct().bond == CAP / 2 && _acct().locked == CAP, "first: b");
        m.declareSampleFailure(p1, b2.nonce);
        require(_acct().bond == 0 && _acct().locked == CAP + CAP / 2, "second: the rest");
        m.declareSampleFailure(p1, b3.nonce);
        require(_acct().bond == 0 && _acct().locked == CAP + CAP / 2 && _acct().failures == 3, "third: 0");
    }

    /// R1 (c): settlement needs a balance of b(V*_p) at the cap high-water
    /// mark, and the deduction is measured at that mark.
    function test_P3_bondAndDeductionAtCapHighWaterMark() public {
        _reg(3 * CAP, 3);
        Receipt memory r0 = _rs(p1, 1, CAP);
        r0.materialCommit = keccak256(_mat(r0));
        bytes32 salt = keccak256("hw salt");
        r0.nonce = f.boundNonce(p1, r0.requestHash, r0.claimsHash, salt);
        Auth memory au = Auth(buyer, f.vaultOf(p1), CAP, VALID_AFTER, VALID_AFTER + 3600, r0.nonce);
        bytes memory sg = _authSig(au);
        vm.expectRevert(SettlementBase.Bond.selector);
        f.settle(au, sg, r0.requestHash, r0.claimsHash, salt);
        vm.prank(seller);
        m.depositBond(seller, 2 * CAP);
        (Receipt memory r,) = _failingSale(buyerKey);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, r.nonce);
        require(_acct().bond == 0 && _acct().locked == 3 * CAP, "deduction at V*_p");
        vm.prank(seller);
        vm.expectRevert(SettlementBase.Bond.selector);
        m.reenter(CAP);
        vm.prank(seller);
        m.reenter(3 * CAP);
        require(!_acct().suspended, "re-entered at b(V*_p)");
    }

    // ============================================ (4) suspension and re-entry

    /// R2 (a), R7 (c): a suspended account takes no new settlement, and a
    /// bond top-up by anyone does not lift the suspension.
    function test_P4_noSettlementWhileSuspended() public {
        (Receipt memory r,) = _failingSale(buyerKey);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, r.nonce);
        Receipt memory q = _rs(p2, 99, PRICE);
        bytes32 salt = keccak256("suspended salt");
        q.nonce = f.boundNonce(p2, q.requestHash, q.claimsHash, salt);
        Auth memory au = _auth(p2, PRICE, q.nonce);
        bytes memory sg = _authSig(au);
        vm.expectRevert(SettlementBase.State.selector);
        f.settle(au, sg, q.requestHash, q.claimsHash, salt);
        vm.prank(stranger);
        m.depositBond(seller, 5 * CAP);
        require(_acct().suspended, "still suspended");
        vm.expectRevert(SettlementBase.State.selector);
        f.settle(au, sg, q.requestHash, q.claimsHash, salt);
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.State.selector);
        m.reenter(0); // re-entry is the account's own call
    }

    /// R7 (d): re-entry only once the balance is back at b(V*_p), with no
    /// waiting (same block as the failure); a new episode starts, frozen
    /// sales stay frozen, and the new sale is not frozen.
    function test_P4_reentryOnlyAfterBalanceRestored() public {
        (Receipt memory r,) = _failingSale(buyerKey);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, r.nonce);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.Bond.selector);
        m.reenter(0);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.Bond.selector);
        m.reenter(CAP - 1);
        Account memory a = _acct();
        require(a.suspended && a.bond == 0 && a.episode == 1, "unchanged after a short re-entry");
        vm.prank(seller);
        m.reenter(CAP);
        a = _acct();
        require(!a.suspended && a.bond == CAP && a.episode == 2, "re-entered");
        Receipt memory n2 = _sell(buyerKey, p2, PRICE);
        require(!_frozen(p2, n2), "new sale not frozen");
        require(_frozen(p1, r), "old sale stays frozen");
        m.claimFrozen(p1, r.nonce);
        vm.prank(seller);
        vm.expectRevert(SettlementBase.State.selector);
        m.reenter(0); // not suspended
    }

    /// R7 (d): a case of the earlier episode failing after re-entry is a
    /// confirmed failure: deduction from the current balance, suspension, and
    /// the freeze from its s_f covers the new episode's unpaid sale.
    function test_P4_oldEpisodeFailureAfterReentry() public {
        Receipt memory b1 = _sell(buyerKey, p1, CAP);
        Receipt memory b2 = _sell(buyerKey, p1, CAP);
        Leaf[] memory ls = _two(_lf(b1), _lf(b2));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, b1.nonce);
        vm.prank(seller);
        m.reenter(CAP);
        Receipt memory n2 = _sell(buyerKey, p2, PRICE);
        require(!_frozen(p2, n2), "not frozen yet");
        vm.roll(block.number + 1);
        m.declareSampleFailure(p1, b2.nonce);
        Account memory a = _acct();
        require(a.suspended && a.failures == 2 && a.bond == 0 && a.locked == 2 * CAP, "current balance deducted");
        require(_frozen(p2, n2), "new episode's unpaid sale frozen");
    }

    // ============================================== (5) claims of frozen sales

    /// R7 (b): anyone may claim; the refund goes to the sale's payer only,
    /// and a second claim fails.
    function test_P5_claimRefundsThePayerOnce() public {
        (Receipt memory r,) = _failingSale(buyer2Key);
        vm.roll(_proofEnd(e0) + 1);
        m.declareSampleFailure(p1, r.nonce);
        address[] memory h = _holders();
        uint256[] memory b0 = _bals(h);
        vm.prank(stranger);
        m.claimFrozen(p1, r.nonce);
        uint256[] memory b1 = _bals(h);
        for (uint256 i; i < h.length; i++) {
            if (h[i] == buyer2) require(b1[i] == b0[i] + CAP, "payer refunded");
            else if (h[i] == f.vaultOf(p1)) require(b1[i] == b0[i] - CAP, "from the vault");
            else require(b1[i] == b0[i], "no one else moves");
        }
        require(_st(p1, r) == f.ST_REFUNDED(), "refunded");
        vm.prank(buyer2);
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, r.nonce);
        vm.prank(buyer);
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, r.nonce);
    }

    /// Only frozen sales are claimed: a held sale with no freeze and a paid
    /// sale are not.
    function test_P5_claimOnlyFrozenSales() public {
        Receipt memory r = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lf(r));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, r.nonce);
        _releaseThrough(e0);
        require(_st(p1, r) == f.ST_PAID(), "paid");
        vm.expectRevert(SettlementBase.State.selector);
        m.claimFrozen(p1, r.nonce);
    }

    /// R7 (b): an unclaimed frozen payment never goes to the seller, before
    /// or after the claim period.
    function test_P5_unclaimedFrozenPaymentNeverReachesSeller() public {
        (Receipt memory r,) = _failingSale(buyerKey);
        uint256 s0 = token.balanceOf(seller);
        _releaseThrough(e0);
        require(_st(p1, r) == f.ST_FROZEN() && _acct().failures == 1, "frozen at the cursor");
        vm.roll(block.number + f.T_CLAIM() + 50);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.claimFrozen(p1, r.nonce);
        _releaseThrough(e0 + 3);
        require(token.balanceOf(seller) == s0, "seller never paid");
        require(token.balanceOf(f.vaultOf(p1)) >= CAP, "payment stays held");
        require(_st(p1, r) == f.ST_FROZEN(), "still frozen");
    }

    // ===================================================== (6) the cursor

    /// R6 (a)(2): the cursor does not pass an epoch while a sampled case is
    /// open (here at M_e + T_p, the last block of the case).
    function test_P6_cursorWaitsForSampleCases() public {
        _failingSale(buyerKey);
        _rollTo(_proofEnd(e0));
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(seller);
        require(m.accountCursor(seller) == e0, "cursor stays");
    }

    /// R6 (a)(4): epochs are passed in order; the next epoch waits for its
    /// own windows.
    function test_P6_cursorInOrder() public {
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        Leaf[] memory la = _one(_lf(a));
        vm.roll(f.lastBlock(e0) + 1);
        Receipt memory b = _sell(buyerKey, p1, PRICE);
        Leaf[] memory lb = _one(_lf(b));
        _anchorEp(p1, la, e0);
        _value(p1, e0, la);
        _anchorEp(p1, lb, e0 + 1);
        _value(p1, e0 + 1, lb);
        _rollTo(_cursorBlock(e0));
        m.release(seller);
        require(_st(p1, a) == f.ST_PAID() && _st(p1, b) == f.ST_HELD(), "e0 only");
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(seller);
        _releaseThrough(e0 + 1);
        require(_st(p1, b) == f.ST_PAID(), "then e0 + 1");
    }

    /// R6 (a), R3 (a) empty profile epoch: an epoch with no settlement is
    /// passed at once after it ends, and it has no missed anchor.
    function test_P6_emptyEpochPassedAtOnce() public {
        vm.roll(f.lastBlock(e0) + 1);
        m.release(seller);
        require(m.accountCursor(seller) == e0 + 1, "passed at once");
        vm.roll(f.anchorDeadline(e0) + 1);
        vm.expectRevert(SettlementBase.State.selector);
        m.declareAnchorMissed(p1, e0);
    }

    /// R6 (a): the settlement count of an epoch is known only when the epoch
    /// ends, so the cursor must not treat an unfinished epoch as empty. A
    /// sale settled in the epoch must still go through the cursor (paid
    /// after an honest anchor and windows) and be open to a swap proof until
    /// the cursor passes it (R5 (b)).
    function test_P6_cursorDoesNotPassUnfinishedEpoch() public {
        require(block.number <= f.lastBlock(e0), "inside e0");
        try m.release(seller) { } catch { }
        Receipt memory r = _sell(buyerKey, p1, PRICE);
        require(m.accountCursor(seller) <= e0, "cursor passed an epoch that has a settlement");
        Leaf[] memory ls = _one(_lf(r));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        _releaseThrough(e0 + 1);
        require(_st(p1, r) == f.ST_PAID(), "sale paid by the cursor");
    }

    // ================================================== (7) missed anchor

    /// R3 (e), R7 (b): after A_e anyone records the missed anchor; the freeze
    /// starts at the profile epoch's first sale; sales before it (an earlier
    /// epoch, another profile's earlier sale) are paid by the cursor.
    function test_P7_missedAnchorFreezesFromFirstSale() public {
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        Leaf[] memory la = _one(_lf(a));
        uint256 e1 = e0 + 1;
        vm.roll(f.lastBlock(e0) + 1);
        Receipt memory c = _sell(buyerKey, p2, PRICE);
        vm.roll(block.number + 1);
        Receipt memory b1 = _sell(buyerKey, p1, PRICE);
        vm.roll(block.number + 1);
        Receipt memory b2 = _sell(buyer2Key, p1, PRICE);
        _anchorEp(p1, la, e0);
        _value(p1, e0, la);
        Leaf[] memory lc = _one(_lf(c));
        _anchorEp(p2, lc, e1);
        _rollTo(f.anchorDeadline(e1));
        vm.expectRevert(SettlementBase.Timing.selector);
        m.declareAnchorMissed(p1, e1);
        vm.roll(f.anchorDeadline(e1) + 1);
        _value(p2, e1, lc);
        vm.prank(stranger);
        m.declareAnchorMissed(p1, e1);
        require(f.missedAt(_sk(p1, bytes32(e1))) != 0, "recorded");
        Account memory ac = _acct();
        require(ac.failures == 1 && ac.suspended && ac.locked == CAP, "confirmed failure");
        require(_frozen(p1, b1) && _frozen(p1, b2), "epoch's sales frozen");
        require(!_frozen(p1, a) && !_frozen(p2, c), "earlier sales not frozen");
        vm.expectRevert(SettlementBase.State.selector);
        m.declareAnchorMissed(p1, e1);
        m.claimFrozen(p1, b2.nonce);
        require(_st(p1, b2) == f.ST_REFUNDED(), "claimed");
        _releaseThrough(e1);
        require(_st(p1, a) == f.ST_PAID() && _st(p2, c) == f.ST_PAID(), "earlier sales paid");
        require(_st(p1, b1) == f.ST_FROZEN(), "frozen");
    }

    /// R3 (a)(e): units that do not complete the epoch by A_e leave the
    /// anchor missed; a unit after A_e is rejected.
    function test_P7_incompleteAnchorIsMissed() public {
        Receipt memory b1 = _sell(buyerKey, p1, PRICE);
        Receipt memory b2 = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _two(_lf(b1), _lf(b2));
        _sort(ls);
        epoch = e0;
        Unit memory u1 = _unit(p1, _one(ls[0]));
        u1.count = 2;
        u1.sellerSig = _hdrSig(sellerKey, _hdr(u1));
        Unit memory u2 = _unit(p1, _one(ls[1]));
        u2.count = 2;
        u2.unitNo = 2;
        u2.sellerSig = _hdrSig(sellerKey, _hdr(u2));
        _rollTo(f.lastBlock(e0) + f.D_INC() + 1);
        require(f.anchorUnit(u1) == 0, "unit 1 stored");
        require(!f.epochComplete(p1, e0), "not complete");
        vm.roll(f.anchorDeadline(e0) + 1);
        require(f.anchorUnit(u2) != 0, "late unit rejected");
        require(!f.epochComplete(p1, e0), "still not complete");
        m.declareAnchorMissed(p1, e0);
        require(_frozen(p1, b1) && _frozen(p1, b2) && _acct().failures == 1, "missed");
    }

    /// R3 (e): the cursor that reaches an epoch with no record first records
    /// the missed anchor.
    function test_P7_cursorRecordsMissedAnchor() public {
        Receipt memory b = _sell(buyerKey, p1, PRICE);
        _releaseThrough(e0);
        require(f.missedAt(_sk(p1, bytes32(e0))) != 0, "recorded by the cursor");
        require(_acct().failures == 1 && _st(p1, b) == f.ST_FROZEN(), "frozen, not paid");
    }

    // ============================================= (8) double-signed anchor

    function _doubleSignSetup() internal returns (Receipt memory a, Receipt memory b1, Receipt memory b2, Unit memory u) {
        a = _sell(buyerKey, p1, PRICE);
        Leaf[] memory la = _one(_lf(a));
        vm.roll(f.lastBlock(e0) + 1);
        b1 = _sell(buyerKey, p1, PRICE);
        vm.roll(block.number + 1);
        b2 = _sell(buyerKey, p1, PRICE);
        _anchorEp(p1, la, e0);
        _value(p1, e0, la);
        Leaf[] memory lb = _two(_lf(b1), _lf(b2));
        _sort(lb);
        epoch = e0 + 1;
        u = _unit(p1, lb);
        _rollTo(f.lastBlock(e0 + 1) + f.D_INC() + 1);
        require(f.anchorUnit(u) == 0, "stored");
    }

    /// R3 (e), R7 (b): a seller signature on the stored unit's number with
    /// another root0 is a confirmed failure; the freeze starts at the epoch's
    /// first sale; the earlier epoch's sale is paid.
    function test_P8_doubleSignedAnchorIsConfirmedFailure() public {
        (Receipt memory a, Receipt memory b1, Receipt memory b2, Unit memory u) = _doubleSignSetup();
        UnitHeader memory h = _hdr(u);
        h.root0 = keccak256("another root0");
        vm.prank(stranger);
        m.proveDoubleSign(h, _hdrSig(sellerKey, h));
        Account memory ac = _acct();
        require(ac.failures == 1 && ac.suspended && ac.locked == CAP, "confirmed failure");
        require(_frozen(p1, b1) && _frozen(p1, b2) && !_frozen(p1, a), "from the epoch's first sale");
        _releaseThrough(e0);
        require(_st(p1, a) == f.ST_PAID(), "earlier epoch paid");
    }

    /// R3 (e) count branch: same number and root0, another count.
    function test_P8_countBranch() public {
        (,,, Unit memory u) = _doubleSignSetup();
        UnitHeader memory h = _hdr(u);
        h.count = 3;
        m.proveDoubleSign(h, _hdrSig(sellerKey, h));
        require(_acct().failures == 1, "confirmed failure");
    }

    /// Not evidence: the stored content itself, a number with no stored
    /// unit, a signature by a key other than the profile's unit key.
    function test_P8_nonEvidence() public {
        (,,, Unit memory u) = _doubleSignSetup();
        UnitHeader memory h = _hdr(u);
        bytes memory same = _hdrSig(sellerKey, h);
        vm.expectRevert();
        m.proveDoubleSign(h, same);
        UnitHeader memory h2 = _hdr(u);
        h2.unitNo = 2;
        h2.root0 = keccak256("x");
        bytes memory s2 = _hdrSig(sellerKey, h2);
        vm.expectRevert();
        m.proveDoubleSign(h2, s2);
        UnitHeader memory h3 = _hdr(u);
        h3.root0 = keccak256("y");
        bytes memory s3 = _hdrSig(buyerKey, h3);
        vm.expectRevert();
        m.proveDoubleSign(h3, s3);
        require(_acct().failures == 0 && !_acct().suspended, "no failure");
    }

    /// R3 (a)(e): a signed unit rejected before its number's unit is stored
    /// is not evidence (same profile, epoch, number, root0 and count); a
    /// signature with the same root0 and another count still is.
    function test_P8_rejectionBeforeStoreExcusesOnlyThatSignature() public {
        Receipt memory b = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lf(b));
        epoch = e0;
        Unit memory bad = _unit(p1, ls);
        bad.count = 2; // wrong count, rejected after the signature check
        bad.sellerSig = _hdrSig(sellerKey, _hdr(bad));
        Unit memory good = _unit(p1, ls);
        _rollTo(f.lastBlock(e0) + f.D_INC() + 1);
        require(f.anchorUnit(bad) != 0, "rejected");
        require(f.anchorUnit(good) == 0, "stored");
        UnitHeader memory hb = _hdr(bad);
        bytes memory sb = _hdrSig(sellerKey, hb);
        vm.expectRevert();
        m.proveDoubleSign(hb, sb);
        require(_acct().failures == 0, "excused");
        UnitHeader memory h3 = _hdr(bad);
        h3.count = 3;
        m.proveDoubleSign(h3, _hdrSig(sellerKey, h3));
        require(_acct().failures == 1, "other count is evidence");
    }

    /// R3 (e): a rejection recorded after the store does not excuse the
    /// signature.
    function test_P8_rejectionAfterStoreDoesNotExcuse() public {
        Receipt memory b = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lf(b));
        epoch = e0;
        Unit memory good = _unit(p1, ls);
        Unit memory other = _unit(p1, ls);
        other.root0 = keccak256("other content");
        other.sellerSig = _hdrSig(sellerKey, _hdr(other));
        _rollTo(f.lastBlock(e0) + f.D_INC() + 1);
        require(f.anchorUnit(good) == 0, "stored");
        require(f.anchorUnit(other) != 0, "rejected after the store");
        UnitHeader memory h = _hdr(other);
        m.proveDoubleSign(h, _hdrSig(sellerKey, h));
        require(_acct().failures == 1, "double signature");
    }

    // ====================================== (9) open disputes and the cursor

    /// R6 (c) (v0.8): an open dispute does not hold the cursor; the cursor
    /// passes and pays the other sales, and the disputed sale is paid when
    /// its dispute ends without a refund.
    function test_P9_openDisputeDoesNotHoldCursor() public {
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        Receipt memory b = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _two(_lf(a), _lf(b));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        vm.roll(f.anchorDeadline(e0) + f.T_C()); // last block of the dispute window
        Opening memory od = _openAt(p1, ls, a.nonce, e0);
        vm.prank(buyer);
        f.openDispute(od, 1, "", 0);
        uint256 s0 = token.balanceOf(seller);
        _rollTo(_cursorBlock(e0));
        require(m.dispute(p1, a.nonce, 1, 1).state == f.D_OPEN(), "still open");
        m.release(seller);
        require(m.accountCursor(seller) == e0 + 1, "cursor passed");
        require(_st(p1, b) == f.ST_PAID() && _st(p1, a) == f.ST_HELD(), "other sale paid, disputed held");
        require(token.balanceOf(seller) == s0 + PRICE, "one payment");
        uint256 v0 = token.balanceOf(f.vaultOf(p1));
        m.answerWithAck(p1, a.nonce, false, _ack(p1, a, false));
        require(_st(p1, a) == f.ST_PAID(), "paid after the dispute");
        require(token.balanceOf(f.vaultOf(p1)) == v0 - PRICE, "its payment left the vault");
    }

    /// R6 (c): a disputed sale that is frozen when its dispute ends is not
    /// paid.
    function test_P9_frozenDisputedSaleNotPaid() public {
        Receipt memory x = _sell(buyerKey, p1, CAP);
        vm.roll(block.number + 1);
        Receipt memory a = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _two(_lf(x), _lf(a));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
        vm.roll(f.anchorDeadline(e0) + f.T_C());
        Opening memory od = _openAt(p1, ls, a.nonce, e0);
        vm.prank(buyer);
        f.openDispute(od, 1, "", 0);
        _rollTo(_cursorBlock(e0));
        m.release(seller);
        require(_acct().failures == 1 && _st(p1, a) == f.ST_FROZEN(), "frozen by the failure");
        uint256 v0 = token.balanceOf(f.vaultOf(p1));
        m.answerWithAck(p1, a.nonce, false, _ack(p1, a, false));
        require(_st(p1, a) == f.ST_FROZEN() && token.balanceOf(f.vaultOf(p1)) == v0, "not paid");
    }

    // ================================================== (10) honest seller

    /// An honest seller that proves every sampled sale within T_p: no
    /// deduction, no freeze, no suspension; every sale is paid.
    function test_P10_honestSellerKeepsBond() public {
        Receipt memory s1 = _sell(buyerKey, p1, CAP);
        Receipt memory s2 = _sell(buyer2Key, p1, PRICE);
        Receipt memory s3 = _sell(buyerKey, p1, PRICE);
        Receipt memory s4 = _sell(buyerKey, p2, CAP);
        Receipt memory s5 = _sell(buyer2Key, p2, PRICE);
        Leaf[] memory l1 = new Leaf[](3);
        l1[0] = _lf(s1);
        l1[1] = _lf(s2);
        l1[2] = _lfAccept(p1, s3);
        Leaf[] memory l2 = _two(_lf(s4), _lf(s5));
        uint256 s0 = token.balanceOf(seller);
        _anchorEp(p1, l1, e0);
        _anchorEp(p2, l2, e0);
        _value(p1, e0, l1);
        _value(p2, e0, l2);
        Opening memory o = _openAt(p1, l1, s1.nonce, e0);
        vm.prank(stranger);
        vm.expectRevert(SettlementBase.VerifierFailed.selector);
        f.prove(o, bytes("a stranger's bad material"));
        vm.roll(_proofEnd(e0) - 5);
        _prove(p1, l1, s1, e0);
        _prove(p2, l2, s4, e0);
        _releaseThrough(e0);
        Account memory a = _acct();
        require(a.bond == CAP && a.locked == 0 && a.failures == 0 && !a.suspended, "bond intact");
        require(m.freezes(seller).length == 0, "no freeze");
        require(token.balanceOf(seller) == s0 + 2 * CAP + 3 * PRICE, "all paid");
        require(
            _st(p1, s1) == f.ST_PAID() && _st(p1, s2) == f.ST_PAID() && _st(p1, s3) == f.ST_ACCEPT_PAID()
                && _st(p2, s4) == f.ST_PAID() && _st(p2, s5) == f.ST_PAID(),
            "statuses"
        );
        _sell(buyerKey, p1, PRICE); // still settles
    }

    // ============================================== swap proof (R5 (b))

    function _swapSetup() internal returns (Receipt memory a, Receipt memory x, Leaf[] memory ls, Receipt memory signed) {
        a = _sell(buyerKey, p1, PRICE);
        vm.roll(block.number + 1);
        x = _sell(buyerKey, p1, PRICE);
        signed = _copy(x);
        Receipt memory swapped = _copy(x);
        swapped.responseHash = keccak256("another response");
        ls = _two(_lf(a), _lf(swapped));
        _anchorEp(p1, ls, e0);
        _value(p1, e0, ls);
    }

    function _copy(Receipt memory r) internal pure returns (Receipt memory) {
        return Receipt(
            r.nonce, r.amount, r.requestHash, r.responseHash, r.ctHash, r.keyHash, r.claimsHash, r.materialCommit
        );
    }

    function _rsSig(bytes32 pid, Receipt memory r) internal returns (bytes memory) {
        return _sig(sellerKey, _typed(f.DOMAIN_SEPARATOR(), _rsHash(pid, f.profile(pid).codeHash, r)));
    }

    /// R5 (b), R7: a seller-signed receipt that differs from the anchored
    /// unsigned leaf is a confirmed failure with s_f at that sale.
    function test_Swap_isConfirmedFailure() public {
        (Receipt memory a, Receipt memory x, Leaf[] memory ls, Receipt memory signed) = _swapSetup();
        Opening memory o = _openAt(p1, ls, x.nonce, e0);
        vm.prank(stranger);
        m.proveSwap(o, signed, _rsSig(p1, signed));
        require(_acct().failures == 1 && _acct().locked == CAP, "confirmed failure");
        require(_frozen(p1, x) && !_frozen(p1, a), "freeze from the swapped sale");
        _releaseThrough(e0);
        require(_st(p1, a) == f.ST_PAID(), "earlier sale paid");
    }

    /// R5 (b): accepted for a refunded sale; refused once the cursor passed
    /// the epoch; refused for an unanswered mark.
    function test_Swap_refundedAcceptedAfterCursorRefused() public {
        (, Receipt memory x, Leaf[] memory ls, Receipt memory signed) = _swapSetup();
        Opening memory o = _openAt(p1, ls, x.nonce, e0);
        bytes memory sg = _rsSig(p1, signed);
        uint256 id = vm.snapshotState();
        vm.prank(buyer);
        f.openDispute(o, 1, "", 0);
        vm.roll(block.number + f.T_D() + 1);
        m.closeDispute(p1, x.nonce, 1, 1);
        require(_st(p1, x) == f.ST_REFUNDED(), "refunded");
        m.proveSwap(o, signed, sg);
        require(_acct().failures == 1, "refunded sale: still a failure");
        vm.revertToState(id);
        _releaseThrough(e0);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.proveSwap(o, signed, sg);
    }

    function test_Swap_notForUnansweredMark() public {
        Receipt memory x = _sell(buyerKey, p1, PRICE);
        Leaf[] memory ls = _one(_lfMarked(x));
        _anchorEp(p1, ls, e0);
        Receipt memory signed = x;
        Opening memory o = _openAt(p1, ls, x.nonce, e0);
        bytes memory sg = _rsSig(p1, signed);
        vm.expectRevert();
        m.proveSwap(o, signed, sg);
        require(_acct().failures == 0, "no failure");
    }
}
