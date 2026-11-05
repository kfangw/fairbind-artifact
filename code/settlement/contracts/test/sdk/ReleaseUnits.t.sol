// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { ReleaseBase } from "./ReleaseBase.sol";
import { SettlementBase, SampledSettlement, Profile, Auth, Account } from "./SampledSettlement.sol";

interface EmitVm {
    function expectEmit(bool t1, bool t2, bool t3, bool data, address emitter) external;
}

/// Release units of the reference settlement contract: unit boundaries
/// (N_REL settlement records of one profile in one profile epoch), their
/// order over the profile epochs and profiles of a seller epoch, the
/// cursor passing only after every unit is marked, payment after the pass
/// (in this call for at most N_REL settlements, else by payment units),
/// failures inside a unit and the freezes they cause in other units, and
/// the smallest sale amount v_min at settlement.
contract ReleaseUnitsTest is ReleaseBase {
    EmitVm internal constant evm = EmitVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    event ReleaseUnitMarked(
        address indexed account, uint256 indexed epoch, uint256 unit, bytes32 pid, uint256 profileEpoch, uint256 from, uint256 to
    );
    event ReleasePaid(address indexed account, uint256 indexed epoch, uint256 unit, uint256 paid);

    address internal stranger = address(0x5157);

    function _expectUnit(uint256 first, uint256 u, bytes32 pid, uint256 e, uint256 lo, uint256 hi) internal {
        evm.expectEmit(true, true, false, true, address(f));
        emit ReleaseUnitMarked(seller, first, u, pid, e, lo, hi);
    }

    function _units() internal view returns (uint256 marked, uint256 total, uint256 sales) {
        (marked, total, sales,) = m.releaseState(seller, e0);
    }

    function _payNext() internal view returns (uint256 next) {
        (,,, next) = m.releaseState(seller, e0);
    }

    /// n sales of DUST on the first profile in e0, anchored, with
    /// a value under which none is sampled, at the block after every
    /// deadline of e0.
    function _plain(uint256 n) internal returns (bytes32 pid) {
        _deploy(1, 1, 100);
        pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, n, DUST, 4, false);
        _anchorAll(pid, e0, ss);
        _valueOnlyFull(pid, e0, ss);
        _ripe(e0);
    }

    // ------------------------------------------------------- boundaries

    /// 600 records: units [0, 256), [256, 512), [512, 600) in order; the
    /// cursor waits for all three; unit calls pay nothing; payment after the
    /// pass in three payment units.
    function test_unit_boundaries_and_payment_units() public {
        bytes32 pid = _plain(600);
        (uint256 mk, uint256 tot, uint256 sales) = _units();
        require(mk == 0 && tot == 3 && sales == 600, "three units");
        vm.expectRevert(SettlementBase.State.selector);
        m.release(seller); // more than N_REL settlements: units first
        uint256 s0 = token.balanceOf(seller);
        uint256[4] memory b = [uint256(0), 256, 512, 600];
        for (uint256 u; u < 3; u++) {
            _expectUnit(e0, u, pid, e0, b[u], b[u + 1]);
            require(m.releaseUnit(seller) == u, "unit number");
            require(token.balanceOf(seller) == s0, "a unit pays nothing");
            require(f.accountCursor(seller) == e0, "cursor stays");
            if (u < 2) {
                vm.expectRevert(SettlementBase.State.selector);
                m.release(seller);
            }
        }
        vm.expectRevert(SettlementBase.State.selector);
        m.releaseUnit(seller); // no fourth unit
        vm.expectRevert(SettlementBase.State.selector);
        m.releasePay(seller, e0); // not passed yet
        require(m.release(seller) == 0, "the pass pays nothing here");
        require(f.accountCursor(seller) == e0 + 1, "cursor past E");
        (uint256 mk2,,,) = m.releaseState(seller, e0);
        require(mk2 == 0, "marks reset");
        require(_payNext() == 0, "payment unit 0 next");
        bytes32[] memory ns = f.epochNonces(pid, e0);
        require(f.sale(pid, ns[0]).status == f.ST_HELD(), "held until its payment unit");
        for (uint256 u; u < 3; u++) {
            uint256 want = (b[u + 1] - b[u]) * DUST;
            evm.expectEmit(true, true, false, true, address(f));
            emit ReleasePaid(seller, e0, u, want);
            require(m.releasePay(seller, e0) == want, "unit paid");
            require(token.balanceOf(seller) == s0 + b[u + 1] * DUST, "paid so far");
            require(f.sale(pid, ns[b[u + 1] - 1]).status == f.ST_PAID(), "last of unit paid");
            if (u < 2) require(f.sale(pid, ns[b[u + 1]]).status == f.ST_HELD(), "next unit still held");
        }
        require(_payNext() == type(uint256).max, "payment done");
        vm.expectRevert(SettlementBase.State.selector);
        m.releasePay(seller, e0);
    }

    /// Exactly N_REL settlements fit one transaction: release() checks,
    /// passes and pays in one call.
    function test_n_rel_inline() public {
        _plain(256);
        (, uint256 tot,) = _units();
        require(tot == 1, "one unit");
        uint256 s0 = token.balanceOf(seller);
        require(m.release(seller) == 256 * DUST, "all paid in the cursor call");
        require(token.balanceOf(seller) == s0 + 256 * DUST, "balance");
        require(_payNext() == type(uint256).max, "no payment units");
    }

    /// N_REL + 1 settlements: two units, the second of one record.
    function test_n_rel_plus_one() public {
        bytes32 pid = _plain(257);
        (, uint256 tot,) = _units();
        require(tot == 2, "two units");
        vm.expectRevert(SettlementBase.State.selector);
        m.release(seller);
        _expectUnit(e0, 0, pid, e0, 0, 256);
        m.releaseUnit(seller);
        _expectUnit(e0, 1, pid, e0, 256, 257);
        m.releaseUnit(seller);
        require(m.release(seller) == 0, "pass");
        require(m.releasePay(seller, e0) == 256 * DUST, "unit 0");
        require(m.releasePay(seller, e0) == DUST, "unit 1 of one sale");
    }

    /// A seller epoch of at most N_REL settlements whose units were partly
    /// marked: release() marks the rest and pays in the same call.
    function test_inline_after_partial_units() public {
        _deploy(1, 2, 100);
        _at(e0, 5);
        Sold[] memory a = _sell(pids[0], 0, 100, DUST, 4, false);
        Sold[] memory c = _sell(pids[1], 1000, 50, DUST, 4, false);
        _anchorAll(pids[0], e0, a);
        _anchorAll(pids[1], e0, c);
        _valueOnlyFull(pids[0], e0, a);
        _valueOnlyFull(pids[1], e0, c);
        _ripe(e0);
        (, uint256 tot,) = _units();
        require(tot == 2, "a unit per profile");
        _expectUnit(e0, 0, pids[0], e0, 0, 100);
        m.releaseUnit(seller);
        require(m.release(seller) == 150 * DUST, "rest marked and all paid");
    }

    /// No settlement in the seller epoch: no unit, the cursor passes at once
    /// after E's last block.
    function test_empty_seller_epoch() public {
        _deploy(1, 1, 100);
        vm.roll(f.lastBlock(e0) + 1);
        (, uint256 tot,) = _units();
        require(tot == 0, "no unit");
        vm.expectRevert(SettlementBase.State.selector);
        m.releaseUnit(seller);
        require(m.release(seller) == 0 && f.accountCursor(seller) == e0 + 1, "passed");
    }

    // ------------------------------------------------------------ order

    /// k = 2, two profiles: units run over the profile epochs of E, then the
    /// profiles in registration order, then the records in settlement order.
    function test_unit_order_k2_two_profiles() public {
        _deploy(2, 2, 100);
        bytes32 a = pids[0];
        bytes32 c = pids[1];
        _at(e0, 5);
        Sold[] memory a0 = _sell(a, 0, 260, DUST, 4, false);
        Sold[] memory c0 = _sell(c, 1000, 3, DUST, 0, false);
        _anchorAll(a, e0, a0);
        _anchorAll(c, e0, c0);
        Sold[] memory c1 = _sell(c, 2000, 5, DUST, 0, false); // in e0 + 1
        require(f.epochOf(block.number) == e0 + 1, "second profile epoch");
        _valueOnlyFull(a, e0, a0);
        _valueOnlyFull(c, e0, c0);
        _anchorAll(c, e0 + 1, c1);
        _valueOnlyFull(c, e0 + 1, c1);
        _ripe(e0 + 1);
        (, uint256 tot, uint256 sales) = _units();
        require(tot == 4 && sales == 268, "four units");
        _expectUnit(e0, 0, a, e0, 0, 256);
        m.releaseUnit(seller);
        _expectUnit(e0, 1, a, e0, 256, 260);
        m.releaseUnit(seller);
        _expectUnit(e0, 2, c, e0, 0, 3);
        m.releaseUnit(seller);
        _expectUnit(e0, 3, c, e0 + 1, 0, 5);
        m.releaseUnit(seller);
        require(m.release(seller) == 0 && f.accountCursor(seller) == e0 + 2, "pass");
        require(m.releasePay(seller, e0) == 256 * DUST, "pay 0");
        require(m.releasePay(seller, e0) == 4 * DUST, "pay 1");
        require(m.releasePay(seller, e0) == 3 * DUST, "pay 2");
        require(m.releasePay(seller, e0) == 5 * DUST, "pay 3");
    }

    /// A unit waits for E's last block and for W_e, A_e + T_c and M_e + T_p
    /// of its profile epoch.
    function test_unit_timing() public {
        _deploy(1, 1, 100);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, 300, DUST, 4, false);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.releaseUnit(seller); // E not over
        _anchorAll(pid, e0, ss);
        _valueOnlyFull(pid, e0, ss);
        uint256 t = f.valueDeadline(e0) + f.T_P();
        uint256 c = f.anchorDeadline(e0) + f.T_C();
        if (c > t) t = c;
        vm.roll(t);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.releaseUnit(seller);
        vm.roll(t + 1);
        m.releaseUnit(seller);
    }

    // ------------------------------------------------- failures, freezes

    /// A failing sampled sale in the middle of unit 1's range: unit 0 records
    /// nothing, unit 1 the failure and its freeze from the sale's block, unit
    /// 2 nothing. After the pass, sales settled before that block are paid;
    /// the sale and every later one are frozen, also in unit 2, whose frozen
    /// sale can be claimed before its payment unit runs.
    function test_failure_mid_unit() public {
        _deploy(1, 1, 100);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Sold[] memory ss = _sell(pid, 0, 300, DUST, 4, false);
        vm.roll(block.number + 1);
        Sold[] memory t = new Sold[](1);
        t[0] = _sell1(pid, 300, CAP, false); // always sampled, never proved
        uint256 sf = f.sale(pid, t[0].rs.nonce).settledBlock;
        vm.roll(block.number + 1);
        ss = _concat(_concat(ss, t), _sell(pid, 301, 299, DUST, 4, false));
        bytes32[] memory ns = f.epochNonces(pid, e0);
        require(ns[300] == t[0].rs.nonce, "settlement order");
        _anchorAll(pid, e0, ss);
        _valueOnlyFull(pid, e0, ss);
        _ripe(e0);
        m.releaseUnit(seller);
        Account memory acc = m.account(seller);
        require(!acc.suspended && acc.failures == 0, "unit 0: no failure");
        m.releaseUnit(seller);
        acc = m.account(seller);
        require(acc.suspended && acc.failures == 1, "unit 1: the failure");
        require(m.freezes(seller)[0].from == sf, "freeze from the sale's block");
        require(f.sale(pid, ns[300]).status == f.ST_FROZEN(), "failing sale frozen");
        m.releaseUnit(seller);
        require(m.account(seller).failures == 1, "unit 2: no failure");
        uint256 s0 = token.balanceOf(seller);
        m.release(seller);
        uint256 b0 = token.balanceOf(buyer);
        vm.prank(stranger);
        m.claimFrozen(pid, ns[550]); // frozen once the freeze is recorded
        require(token.balanceOf(buyer) == b0 + DUST, "claimed to the payer");
        require(m.releasePay(seller, e0) == 256 * DUST, "unit 0 all paid");
        require(m.releasePay(seller, e0) == 44 * DUST, "unit 1: the 44 before the failing sale");
        require(m.releasePay(seller, e0) == 0, "unit 2 nothing");
        require(token.balanceOf(seller) == s0 + 300 * DUST, "seller got the 300 before s_f");
        for (uint256 i; i < 600; i++) {
            uint8 st = f.sale(pid, ns[i]).status;
            if (i < 300) require(st == f.ST_PAID(), "before s_f paid");
            else if (i == 550) require(st == f.ST_REFUNDED(), "claimed");
            else require(st == f.ST_FROZEN(), "from s_f frozen");
        }
    }

    /// A failure recorded by a later unit freezes sales of an earlier,
    /// already marked unit: failures and freezes of all units precede every
    /// payment of the seller epoch.
    function test_later_unit_failure_freezes_earlier_unit() public {
        _deploy(1, 2, 100);
        bytes32 a = pids[0];
        bytes32 c = pids[1];
        _at(e0, 5);
        Sold[] memory t = new Sold[](1);
        t[0] = _sell1(c, 0, CAP, false); // second profile, settled first, failing
        vm.roll(block.number + 1);
        Sold[] memory ss = _sell(a, 1000, 260, DUST, 4, false);
        _anchorAll(a, e0, ss);
        _anchorAll(c, e0, t);
        _valueOnlyFull(a, e0, ss);
        _valueOnlyFull(c, e0, t);
        _ripe(e0);
        m.releaseUnit(seller);
        m.releaseUnit(seller);
        require(m.account(seller).failures == 0, "first profile's units: no failure");
        m.releaseUnit(seller);
        require(m.account(seller).failures == 1, "third unit: the failure");
        uint256 s0 = token.balanceOf(seller);
        m.release(seller);
        require(m.releasePay(seller, e0) == 0, "unit 0 frozen");
        require(m.releasePay(seller, e0) == 0, "unit 1 frozen");
        require(m.releasePay(seller, e0) == 0, "unit 2: the failing sale");
        require(token.balanceOf(seller) == s0, "nothing paid");
        bytes32[] memory ns = f.epochNonces(a, e0);
        for (uint256 i; i < ns.length; i++) require(f.sale(a, ns[i]).status == f.ST_FROZEN(), "frozen");
    }

    /// A missed anchor is recorded once, by the first unit of its profile
    /// epoch; every sale of the epoch is frozen and none is paid.
    function test_missed_anchor_in_units() public {
        _deploy(1, 1, 100);
        bytes32 pid = pids[0];
        _at(e0, 5);
        _sell(pid, 0, 300, DUST, 4, false);
        _ripe(e0);
        m.releaseUnit(seller);
        require(f.missedAt(keccak256(abi.encode(pid, bytes32(e0)))) == block.number, "missed anchor recorded");
        require(m.account(seller).failures == 1, "one failure");
        m.releaseUnit(seller);
        require(m.account(seller).failures == 1, "not again");
        m.release(seller);
        require(m.releasePay(seller, e0) == 0 && m.releasePay(seller, e0) == 0, "nothing paid");
        bytes32[] memory ns = f.epochNonces(pid, e0);
        for (uint256 i; i < ns.length; i++) require(f.sale(pid, ns[i]).status == f.ST_FROZEN(), "frozen");
    }

    // ----------------------------------------------------------- v_min

    function test_vmin_register_bounds() public {
        Profile memory p = _profile(address(lazer), 0, 0, 1);
        p.inputRule = keccak256("vmin bounds");
        p.minAmount = 0;
        vm.prank(seller);
        vm.expectRevert(SettlementBase.BadProfile.selector);
        f.register(p, 2_000_000);
        p.minAmount = CAP + 1;
        vm.prank(seller);
        vm.expectRevert(SettlementBase.BadProfile.selector);
        f.register(p, 2_000_000);
        p.minAmount = CAP; // every sale at the cap
        vm.prank(seller);
        bytes32 pid = f.register(p, 2_000_000);
        require(f.profile(pid).minAmount == CAP, "stored");
    }

    function test_vmin_settle() public {
        _deploy(1, 1, 500);
        bytes32 pid = pids[0];
        _at(e0, 5);
        Auth memory a = _auth(pid, 499, keccak256("below v_min"));
        bytes memory sig = _authSig(a);
        vm.expectRevert(SettlementBase.BelowMin.selector);
        f.settle(a, sig, bytes32(0), bytes32(0), bytes32(0));
        require(f.sale(pid, a.nonce).payer == address(0), "no record");
        require(token.balanceOf(f.vaultOf(pid)) == 0, "no transfer");
        _sell1(pid, 1, 500, false); // at v_min
        _sell1(pid, 2, uint64(CAP), false); // at the cap
        a = _auth(pid, CAP + 1, keccak256("above cap"));
        sig = _authSig(a);
        vm.expectRevert(SettlementBase.OverCap.selector);
        f.settle(a, sig, bytes32(0), bytes32(0), bytes32(0));
        require(f.epochNonces(pid, e0).length == 2, "two settled");
    }
}
