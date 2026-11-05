// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import { SdkBase } from "./SdkBase.sol";
import { SettlementBase, Receipt, Leaf, Opening, Account, Profile } from "./SampledSettlement.sol";

struct IndCallGas {
    uint64 gasLimit;
    uint64 gasTotalUsed;
    uint64 gasMemoryUsed;
    int64 gasRefunded;
    uint64 gasRemaining;
}

interface IndVm {
    function lastCallGas() external view returns (IndCallGas memory);
}

/// Independent checks of seller epochs of k > 1 profile epochs, written
/// from the rule text (R1, R6, R7) without the implementation's own cases.
/// Each test registers fresh seller accounts with one plaintext tier 1a
/// profile; the base set-up's account (k = 1, four profiles) is not used.
contract KIndependentTest is SdkBase {
    IndVm internal constant ivm = IndVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 internal constant RTAG = keccak256("p5/response/v1");

    struct Acct {
        uint256 key;
        address addr;
        bytes32 pid;
        uint16 k;
    }

    /// One scenario: sales per profile epoch (counts), their amounts in
    /// settlement order, and which of them get no proof.
    struct Plan {
        uint256 nE;
        uint256[] counts;
        uint64[] amounts;
        bool[] noProof;
    }

    mapping(bytes32 => bytes) internal matOf; // nonce => proof material
    mapping(bytes32 => bool) internal skipProof; // nonce => leave unproved
    uint256 internal acctSeq;

    // ------------------------------------------------------------ helpers

    function _use(Acct memory a) internal {
        seller = a.addr;
        sellerKey = a.key;
    }

    function _profileK(uint16 k, bytes32 tag) internal view returns (Profile memory p) {
        p = _profile(address(lazer), 0, 0, 1);
        p.epochMultiple = k;
        p.inputRule = keccak256(abi.encode("independent", tag));
    }

    /// A new seller account with one profile of multiple k and a bond of
    /// `bondCaps` times the cap.
    function _newAcct(uint16 k, uint256 bondCaps) internal returns (Acct memory a) {
        a.key = uint256(keccak256(abi.encode("independent seller", ++acctSeq)));
        a.addr = vm.addr(a.key);
        a.k = k;
        _use(a);
        Profile memory p = _profileK(k, bytes32(acctSeq));
        vm.prank(a.addr);
        a.pid = f.register(p, 2_000_000);
        uint256 bond = bondCaps * CAP;
        token.mint(a.addr, bond);
        vm.prank(a.addr);
        token.approve(address(f), type(uint256).max);
        vm.prank(a.addr);
        m.depositBond(a.addr, bond);
    }

    /// A sale of `amount` the tier 1a verifier accepts; signed by the buyer
    /// (beta = 1) unless `unsigned`.
    function _sale(Acct memory a, uint256 i, uint64 amount, bool unsigned) internal returns (Leaf memory l) {
        _use(a);
        uint64 ts = VALID_AFTER * 1e6;
        bytes32 psi = keccak256(abi.encode("ind psi", a.pid, i));
        bytes memory mat = abi.encodePacked(psi, _lazerUpdate(ts, 7, FEED, feedKey));
        Receipt memory r = _rs(a.pid, i, amount);
        r.responseHash = keccak256(abi.encodePacked(RTAG, psi, abi.encode(FEED, int64(7), ts)));
        r.materialCommit = keccak256(mat);
        l.rs = _buy(a.pid, r, i);
        if (!unsigned) l.sigB = _ack(a.pid, l.rs, false);
        matOf[l.rs.nonce] = mat;
    }

    function _anchorAt(Acct memory a, uint256 e, Leaf[] memory ls) internal {
        _use(a);
        epoch = e;
        Leaf[] memory c = new Leaf[](ls.length); // _anchor sorts its argument; keep settlement order here
        for (uint256 i; i < ls.length; i++) c[i] = ls[i];
        _anchor(a.pid, c);
    }

    /// Proves every leaf of `ls` (profile epoch e) not marked to skip. With
    /// no sample value posted, every sale is sampled once M_e is past.
    function _proveAll(Acct memory a, uint256 e, Leaf[] memory ls) internal {
        _use(a);
        epoch = e;
        Leaf[] memory c = new Leaf[](ls.length); // openings index the anchored (nonce-sorted) order
        for (uint256 i; i < ls.length; i++) c[i] = ls[i];
        _sort(c);
        for (uint256 i; i < c.length; i++) {
            if (skipProof[c[i].rs.nonce]) continue;
            f.prove(_opening(a.pid, c, i), matOf[c[i].rs.nonce]);
        }
    }

    function _firstBlock(uint256 e) internal view returns (uint256) {
        return f.lastBlock(e) + 1 - f.EPOCH_BLOCKS();
    }

    function _rollTo(uint256 b) internal {
        if (block.number < b) vm.roll(b);
    }

    /// Runs a plan for each account from the accounts' (common) cursor:
    /// sales of profile epoch i settled one block apart (all accounts in
    /// the same block), every busy profile epoch anchored at last(e) +
    /// D_INC + 1, no sample value (all sampled), proofs inside (M_e, M_e +
    /// T_p]. Returns the leaves per account and profile epoch.
    function _run(Acct[] memory as_, Plan memory pl) internal returns (Leaf[][][] memory L, uint256 first) {
        first = f.accountCursor(as_[0].addr);
        L = new Leaf[][][](as_.length);
        for (uint256 a; a < as_.length; a++) {
            L[a] = new Leaf[][](pl.nE);
            for (uint256 i; i < pl.nE; i++) L[a][i] = new Leaf[](pl.counts[i]);
        }
        uint256 idx;
        for (uint256 i; i <= pl.nE; i++) {
            if (i > 0) {
                _rollTo(f.lastBlock(first + i - 1) + f.D_INC() + 1);
                for (uint256 a; a < as_.length; a++) {
                    if (L[a][i - 1].length != 0) _anchorAt(as_[a], first + i - 1, L[a][i - 1]);
                }
            }
            if (i >= 2) {
                for (uint256 a; a < as_.length; a++) _proveAll(as_[a], first + i - 2, L[a][i - 2]);
            }
            if (i < pl.nE) {
                _rollTo(_firstBlock(first + i));
                for (uint256 j; j < pl.counts[i]; j++) {
                    for (uint256 a; a < as_.length; a++) {
                        Leaf memory l = _sale(as_[a], idx, pl.amounts[idx], false);
                        skipProof[l.rs.nonce] = pl.noProof[idx];
                        L[a][i][j] = l;
                    }
                    idx++;
                    vm.roll(block.number + 1);
                }
                require(f.epochOf(block.number - 1) == first + i, "plan: sales left their profile epoch");
            }
        }
        _rollTo(f.valueDeadline(first + pl.nE - 1) + 1);
        for (uint256 a; a < as_.length; a++) _proveAll(as_[a], first + pl.nE - 1, L[a][pl.nE - 1]);
    }

    /// The first block at which the rule lets the cursor pass seller epoch
    /// E = {first, ..., first + k - 1}: after E's last block, and for every
    /// profile epoch e of E with sales, after W_e, A_e + T_c and M_e + T_p
    /// (R6 (a)(0) to (3), each strict).
    function _passBlock(uint256 first, uint256 k, uint256[] memory counts) internal view returns (uint256 d) {
        d = f.lastBlock(first + k - 1);
        for (uint256 i; i < k; i++) {
            if (counts.length <= i || counts[i] == 0) continue;
            uint256 e = first + i;
            uint256 le = f.lastBlock(e);
            uint256 ae = le + f.A_A(); // A_e
            uint256 me = ae + f.TAU_V() + 1 + f.T_V(); // M_e
            uint256 we = me + f.W_B(); // W_e
            if (we > d) d = we;
            if (ae + f.T_C() > d) d = ae + f.T_C();
            if (me + f.T_P() > d) d = me + f.T_P();
        }
        d += 1;
    }

    function _plan(uint256[] memory counts, uint64 amount) internal pure returns (Plan memory pl) {
        pl.nE = counts.length;
        pl.counts = counts;
        uint256 n;
        for (uint256 i; i < counts.length; i++) n += counts[i];
        pl.amounts = new uint64[](n);
        pl.noProof = new bool[](n);
        for (uint256 i; i < n; i++) pl.amounts[i] = amount;
    }

    function _one(Acct memory a) internal pure returns (Acct[] memory as_) {
        as_ = new Acct[](1);
        as_[0] = a;
    }

    function _status(Acct memory a, bytes32 nonce) internal view returns (uint8) {
        return f.sale(a.pid, nonce).status;
    }

    function _counts3(uint256 a, uint256 b, uint256 c) internal pure returns (uint256[] memory x) {
        x = new uint256[](3);
        (x[0], x[1], x[2]) = (a, b, c);
    }

    function _countsK(uint256 k, uint256 at, uint256 n) internal pure returns (uint256[] memory x) {
        x = new uint256[](k);
        if (at < k) x[at] = n;
    }

    function _all(uint256 k, uint256 n) internal pure returns (uint256[] memory x) {
        x = new uint256[](k);
        for (uint256 i; i < k; i++) x[i] = n;
    }

    // ---------------------------------------------------- 1. payment time

    /// No payment before the pass block; at the block before it the cursor
    /// reverts and pays nothing; at the pass block it pays every sale of E.
    function _timing(uint16 k, uint256[] memory counts) internal {
        Acct memory a = _newAcct(k, 1);
        Plan memory pl = _plan(counts, PRICE);
        (Leaf[][][] memory L, uint256 first) = _run(_one(a), pl);
        uint256 d = _passBlock(first, k, counts);
        uint256 total = PRICE * pl.amounts.length;
        uint256 s0 = token.balanceOf(a.addr);
        // E's last block, and every block from there up to d - 1, reverts
        uint256 le = f.lastBlock(first + k - 1);
        if (block.number <= le) {
            vm.roll(le);
            vm.expectRevert(SettlementBase.Timing.selector);
            m.release(a.addr);
        }
        vm.roll(d - 1);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(a.addr);
        require(token.balanceOf(a.addr) == s0, "paid before the pass block");
        for (uint256 i; i < k; i++) {
            for (uint256 j; j < L[0][i].length; j++) {
                require(_status(a, L[0][i][j].rs.nonce) == f.ST_HELD(), "held before the pass block");
            }
        }
        vm.roll(d);
        require(m.release(a.addr) == total, "pays all of E at the pass block");
        require(token.balanceOf(a.addr) == s0 + total, "seller balance");
        require(f.accountCursor(a.addr) == first + k, "cursor moved k");
        for (uint256 i; i < k; i++) {
            for (uint256 j; j < L[0][i].length; j++) {
                require(_status(a, L[0][i][j].rs.nonce) == f.ST_PAID(), "paid");
            }
        }
    }

    function test_timing_k2_lastEpochOnly() public {
        _timing(2, _countsK(2, 1, 2));
    }

    function test_timing_k3_lastEpochOnly() public {
        _timing(3, _countsK(3, 2, 2));
    }

    function test_timing_k4_lastEpochOnly() public {
        _timing(4, _countsK(4, 3, 2));
    }

    function test_timing_k2_firstEpochOnly() public {
        _timing(2, _countsK(2, 0, 2)); // A_e + T_c of e1 binds (after last(E))
    }

    function test_timing_k3_firstEpochOnly() public {
        _timing(3, _countsK(3, 0, 2)); // A_e + T_c of e1 = last(e1) + 720 > last(E) = last(e1) + 600
    }

    function test_timing_k4_firstEpochOnly() public {
        _timing(4, _countsK(4, 0, 2)); // last(E) = last(e1) + 900 binds
        // the pass block is then last(E) + 1
    }

    function test_timing_k2_everyEpoch() public {
        _timing(2, _all(2, 1));
    }

    function test_timing_k3_everyEpoch() public {
        _timing(3, _all(3, 1));
    }

    function test_timing_k4_everyEpoch() public {
        _timing(4, _all(4, 1));
    }

    function test_timing_k4_middleEpoch() public {
        _timing(4, _countsK(4, 1, 1)); // last(e2) + 720 > last(E) = last(e2) + 600
    }

    /// Which deadline binds: with k = 4 and sales only in e1 the pass block
    /// is last(E) + 1 exactly; with sales in e_k it is A_{e_k} + T_c + 1.
    function test_timing_bindingDeadline() public {
        uint256 first = f.epochOf(block.number);
        require(_passBlock(first, 4, _countsK(4, 0, 1)) == f.lastBlock(first + 3) + 1, "last(E) binds");
        require(
            _passBlock(first, 4, _countsK(4, 3, 1)) == f.anchorDeadline(first + 3) + f.T_C() + 1, "A_e + T_c binds"
        );
    }

    // --------------------------------------------- 2. failure inside E

    /// k = 3. e1: s0, s1; e2: s2, s3 (s3 unproved), s4; e3: s5. Rule R7 (b):
    /// freeze from s_f = settlement block of s3, of the unpaid sales; s0 to
    /// s2 were settled before s_f and are paid when the cursor passes E
    /// (R6 (c)); s3, s4, s5 are frozen; one deduction min(b(V*_p), bond).
    function _failPlan() internal pure returns (Plan memory pl) {
        pl = _plan(_counts3(2, 3, 1), PRICE);
        pl.noProof[3] = true;
    }

    function _checkFailure(Acct memory a, Leaf[][][] memory L, uint256 lockedBefore, uint128 bondBefore) internal view {
        bytes32[6] memory n = [
            L[0][0][0].rs.nonce,
            L[0][0][1].rs.nonce,
            L[0][1][0].rs.nonce,
            L[0][1][1].rs.nonce,
            L[0][1][2].rs.nonce,
            L[0][2][0].rs.nonce
        ];
        for (uint256 i; i < 3; i++) require(_status(a, n[i]) == f.ST_PAID(), "settled before s_f: paid");
        for (uint256 i = 3; i < 6; i++) require(_status(a, n[i]) == f.ST_FROZEN(), "from s_f: frozen");
        Account memory ac = m.account(a.addr);
        require(ac.failures == 1, "one confirmed failure");
        require(ac.locked == lockedBefore + CAP, "one deduction of b(V*_p) = V");
        require(ac.bond == bondBefore - CAP, "bond less one deduction");
        require(ac.suspended, "suspended");
        require(token.balanceOf(f.vaultOf(a.pid)) == 3 * PRICE, "frozen amounts stay in the vault");
    }

    function test_failureInSecondEpochInsideCursor() public {
        Acct memory a = _newAcct(3, 3);
        Plan memory pl = _failPlan();
        (Leaf[][][] memory L, uint256 first) = _run(_one(a), pl);
        uint256 s0 = token.balanceOf(a.addr);
        vm.roll(_passBlock(first, 3, pl.counts));
        require(m.release(a.addr) == 3 * PRICE, "pays s0 to s2 only");
        require(token.balanceOf(a.addr) == s0 + 3 * PRICE, "seller balance");
        require(f.accountCursor(a.addr) == first + 3, "cursor passed E");
        _checkFailure(a, L, 0, uint128(3 * CAP));
        require(m.freezes(a.addr).length == 1, "one freeze");
        require(m.freezes(a.addr)[0].from == f.sale(a.pid, L[0][1][1].rs.nonce).settledBlock, "s_f");
    }

    function test_failureInSecondEpochDeclaredBeforeCursor() public {
        Acct memory a = _newAcct(3, 3);
        Plan memory pl = _failPlan();
        (Leaf[][][] memory L, uint256 first) = _run(_one(a), pl);
        _rollTo(f.valueDeadline(first + 1) + f.T_P() + 1);
        m.declareSampleFailure(a.pid, L[0][1][1].rs.nonce);
        uint256 s0 = token.balanceOf(a.addr);
        // the declaration pays nothing and the cursor still waits for E
        require(token.balanceOf(a.addr) == s0, "no payment at the declaration");
        vm.roll(_passBlock(first, 3, pl.counts) - 1);
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(a.addr);
        vm.roll(_passBlock(first, 3, pl.counts));
        require(m.release(a.addr) == 3 * PRICE, "pays s0 to s2 only");
        _checkFailure(a, L, 0, uint128(3 * CAP));
    }

    /// Same with the unproved sale in the last profile epoch (e3): every
    /// earlier sale of E is paid, the failed one alone is frozen.
    function test_failureInLastEpoch() public {
        Acct memory a = _newAcct(3, 3);
        Plan memory pl = _plan(_counts3(1, 1, 2), PRICE);
        pl.noProof[3] = true;
        (Leaf[][][] memory L, uint256 first) = _run(_one(a), pl);
        vm.roll(_passBlock(first, 3, pl.counts));
        require(m.release(a.addr) == 3 * PRICE, "pays the three before s_f");
        require(_status(a, L[0][2][1].rs.nonce) == f.ST_FROZEN(), "failed sale frozen");
        require(m.account(a.addr).locked == CAP && m.account(a.addr).failures == 1, "one deduction");
    }

    /// Two failures in E (e2 and e3): one deduction per confirmed failure
    /// (R7 (c)), the freeze from the earlier s_f.
    function test_twoFailuresTwoDeductions() public {
        Acct memory a = _newAcct(3, 3);
        Plan memory pl = _failPlan();
        pl.noProof[5] = true;
        (Leaf[][][] memory L, uint256 first) = _run(_one(a), pl);
        vm.roll(_passBlock(first, 3, pl.counts));
        require(m.release(a.addr) == 3 * PRICE, "pays s0 to s2 only");
        Account memory ac = m.account(a.addr);
        require(ac.failures == 2 && ac.locked == 2 * CAP && ac.bond == CAP, "two deductions");
        require(_status(a, L[0][2][0].rs.nonce) == f.ST_FROZEN(), "frozen");
    }

    /// The same-block reading of R7 (b): a sale settled in s_f's block
    /// before the failed sale is frozen too ("settled from s_f").
    function test_failureFreezesSameBlockEarlierSale() public {
        Acct memory a = _newAcct(2, 2);
        uint256 first = f.accountCursor(a.addr);
        Leaf[] memory e1 = new Leaf[](1);
        e1[0] = _sale(a, 0, PRICE, false);
        vm.roll(_firstBlock(first + 1) + 5);
        Leaf[] memory e2 = new Leaf[](2);
        e2[0] = _sale(a, 1, PRICE, false); // same block as the failed sale, earlier
        e2[1] = _sale(a, 2, PRICE, false); // unproved
        skipProof[e2[1].rs.nonce] = true;
        _anchorAt(a, first, e1);
        vm.roll(f.valueDeadline(first) + 1);
        _proveAll(a, first, e1);
        _anchorAt(a, first + 1, e2);
        vm.roll(f.valueDeadline(first + 1) + 1);
        _proveAll(a, first + 1, e2);
        uint256[] memory c = new uint256[](2);
        (c[0], c[1]) = (1, 2);
        vm.roll(_passBlock(first, 2, c));
        require(m.release(a.addr) == PRICE, "only e1 paid");
        require(_status(a, e2[0].rs.nonce) == f.ST_FROZEN(), "same block, earlier: frozen");
    }

    /// Re-entry inside E (k = 4): the failure of e1 is declared during e3;
    /// after re-entry a sale in e4 is settled. It was settled after the
    /// failure, so the freeze does not cover it and the cursor pays it.
    function test_reentryInsideSellerEpoch() public {
        Acct memory a = _newAcct(4, 3);
        uint256 first = f.accountCursor(a.addr);
        Leaf[] memory e1 = new Leaf[](1);
        e1[0] = _sale(a, 0, PRICE, false);
        skipProof[e1[0].rs.nonce] = true;
        _anchorAt(a, first, e1);
        vm.roll(f.valueDeadline(first) + f.T_P() + 1);
        require(f.epochOf(block.number) == first + 2, "inside e3");
        m.declareSampleFailure(a.pid, e1[0].rs.nonce);
        vm.prank(a.addr);
        m.reenter(0);
        vm.roll(_firstBlock(first + 3) + 1);
        Leaf[] memory e4 = new Leaf[](1);
        e4[0] = _sale(a, 1, PRICE, false);
        _anchorAt(a, first + 3, e4);
        vm.roll(f.valueDeadline(first + 3) + 1);
        _proveAll(a, first + 3, e4);
        uint256[] memory c = new uint256[](4);
        (c[0], c[3]) = (1, 1);
        vm.roll(_passBlock(first, 4, c));
        require(m.release(a.addr) == PRICE, "the sale after re-entry is paid");
        require(_status(a, e1[0].rs.nonce) == f.ST_FROZEN(), "failed sale frozen");
        require(_status(a, e4[0].rs.nonce) == f.ST_PAID(), "paid");
        require(m.account(a.addr).failures == 1 && m.account(a.addr).locked == CAP, "one deduction");
    }

    // -------------------------------------------- 3. amount conservation

    struct Tally {
        uint256 total;
        uint256 paid;
        uint256 frozen;
        uint256 held;
    }

    function _tally(Acct memory a, Leaf[][] memory L) internal view returns (Tally memory t) {
        for (uint256 i; i < L.length; i++) {
            for (uint256 j; j < L[i].length; j++) {
                bytes32 n = L[i][j].rs.nonce;
                uint8 st = _status(a, n);
                uint256 v = f.sale(a.pid, n).amount;
                t.total += v;
                if (st == f.ST_PAID()) t.paid += v;
                else if (st == f.ST_FROZEN()) t.frozen += v;
                else if (st == f.ST_HELD()) t.held += v;
                else revert("unexpected status");
            }
        }
    }

    /// The same random sale sequence for an account with k = 1 and one
    /// with k = K (2 to 4), K profile epochs. With prob. 1/2 one sale has no
    /// proof. Paid + frozen + held = received for both, the seller's gain is
    /// the paid sum, the vault keeps the rest; the paid sums agree, and
    /// equal the sum of the sales settled before the failed one (all of
    /// them without a failure).
    /// forge-config: sdk.fuzz.runs = 256
    function testFuzz_conservationAndKInvariance(uint256 seed) public {
        uint16 kk = uint16(2 + seed % 3);
        Acct[] memory as_ = new Acct[](2);
        as_[0] = _newAcct(1, 3);
        as_[1] = _newAcct(kk, 3);
        Plan memory pl;
        pl.nE = kk;
        pl.counts = new uint256[](kk);
        uint256 n;
        for (uint256 i; i < kk; i++) {
            pl.counts[i] = uint256(keccak256(abi.encode(seed, "count", i))) % 4;
            n += pl.counts[i];
        }
        pl.amounts = new uint64[](n);
        pl.noProof = new bool[](n);
        for (uint256 i; i < n; i++) {
            pl.amounts[i] = uint64(1 + uint256(keccak256(abi.encode(seed, "amount", i))) % CAP);
        }
        uint256 failIdx = type(uint256).max;
        if (n != 0 && (seed >> 128) & 1 == 1) {
            failIdx = uint256(keccak256(abi.encode(seed, "fail"))) % n;
            pl.noProof[failIdx] = true;
        }
        uint256[2] memory gain;
        gain[0] = token.balanceOf(as_[0].addr);
        gain[1] = token.balanceOf(as_[1].addr);
        (Leaf[][][] memory L, uint256 first) = _run(as_, pl);
        uint256 d = _passBlock(first, kk, pl.counts);
        vm.roll(d);
        uint256 paid1;
        for (uint256 i; i < kk; i++) paid1 += m.release(as_[0].addr);
        uint256 paidK = m.release(as_[1].addr);
        require(f.accountCursor(as_[0].addr) == first + kk && f.accountCursor(as_[1].addr) == first + kk, "cursors");
        uint256 expect;
        for (uint256 i; i < n && i < failIdx; i++) expect += pl.amounts[i];
        for (uint256 a; a < 2; a++) {
            Tally memory t = _tally(as_[a], L[a]);
            require(t.paid + t.frozen + t.held == t.total, "conservation");
            require(token.balanceOf(as_[a].addr) - gain[a] == t.paid, "seller gain is the paid sum");
            require(token.balanceOf(f.vaultOf(as_[a].pid)) == t.frozen + t.held, "vault keeps the rest");
            require(t.held == 0, "nothing left held");
            require(t.paid == expect, "paid = sales before s_f");
            if (failIdx == type(uint256).max) require(t.frozen == 0 && t.paid == t.total, "all paid");
            else require(m.account(as_[a].addr).failures == 1 && m.account(as_[a].addr).locked == CAP, "one deduction");
        }
        require(paid1 == paidK, "k = 1 and k = K pay the same");
    }

    // ----------------------------------------- 4. bounds and rejections

    function _tryRegister(uint16 k, bytes32 tag) internal returns (bool ok) {
        Profile memory p = _profileK(k, tag);
        vm.prank(seller);
        try f.register(p, 2_000_000) {
            ok = true;
        } catch (bytes memory err) {
            require(bytes4(err) == SettlementBase.BadProfile.selector, "reverts with BadProfile");
        }
    }

    function test_bounds_k0_k33_rejected_k32_accepted() public {
        Acct memory a;
        a.key = uint256(keccak256("bounds seller"));
        a.addr = vm.addr(a.key);
        _use(a);
        require(!_tryRegister(0, "k0"), "k = 0 rejected");
        require(!_tryRegister(33, "k33"), "k = 33 rejected");
        require(!_tryRegister(type(uint16).max, "kmax"), "k = 65535 rejected");
        require(m.accountProfiles(a.addr).length == 0, "nothing registered");
        require(_tryRegister(32, "k32"), "k = 32 accepted");
        require(m.account(a.addr).k == 32, "account k");
        // same account, another k
        require(!_tryRegister(1, "k1"), "same account k = 1 rejected");
        require(!_tryRegister(31, "k31"), "same account k = 31 rejected");
        require(_tryRegister(32, "k32b"), "same account same k accepted");
        require(m.accountProfiles(a.addr).length == 2, "two profiles");
    }

    function test_bounds_k_inProfileId() public view {
        Profile memory p = _profileK(2, "id");
        Profile memory q = _profileK(3, "id");
        require(f.profileId(p) != f.profileId(q), "k is in the profile id");
    }

    function test_bounds_baseAccountRejectsOtherK() public {
        // the set-up's account has k = 1
        require(!_tryRegister(2, "base k2"), "k = 2 on the k = 1 account rejected");
    }

    /// k = 32 works end to end: a sale in the last profile epoch is paid at
    /// its pass block and the cursor moves 32.
    function test_bounds_k32_runs() public {
        _timing(32, _countsK(32, 31, 1));
    }

    // ------------------------------------------------ 5. cursor movement

    function test_cursor_emptySellerEpochs() public {
        for (uint16 k = 1; k <= 5; k++) {
            uint256 snap = vm.snapshotState();
            Acct memory a = _newAcct(k, 1);
            uint256 first = f.accountCursor(a.addr);
            uint256 le = f.lastBlock(first + k - 1);
            if (k > 1) {
                vm.roll(f.lastBlock(first)); // end of the first profile epoch only
                vm.expectRevert(SettlementBase.Timing.selector);
                m.release(a.addr);
                vm.roll(f.lastBlock(first) + 1);
                vm.expectRevert(SettlementBase.Timing.selector);
                m.release(a.addr);
            }
            vm.roll(le);
            vm.expectRevert(SettlementBase.Timing.selector);
            m.release(a.addr);
            vm.roll(le + 1);
            require(m.release(a.addr) == 0, "empty E pays nothing");
            require(f.accountCursor(a.addr) == first + k, "moved exactly k");
            // the next E is not over yet
            vm.expectRevert(SettlementBase.Timing.selector);
            m.release(a.addr);
            vm.roll(f.lastBlock(first + 2 * k - 1) + 1);
            require(m.release(a.addr) == 0, "second empty E");
            require(f.accountCursor(a.addr) == first + 2 * k, "moved 2k");
            vm.revertToState(snap);
        }
    }

    /// k = 3: one call over a busy E moves the cursor 3; a sale settled at
    /// the first block after E belongs to the next E and is not paid; a
    /// sale at E's last block is.
    function test_cursor_boundarySales() public {
        Acct memory a = _newAcct(3, 1);
        uint256 first = f.accountCursor(a.addr);
        uint256 le = f.lastBlock(first + 2);
        vm.roll(le);
        Leaf[] memory last = new Leaf[](1);
        last[0] = _sale(a, 0, PRICE, false);
        vm.roll(le + 1);
        Leaf[] memory next = new Leaf[](1);
        next[0] = _sale(a, 1, PRICE, false);
        require(f.sale(a.pid, last[0].rs.nonce).epoch == first + 2, "in E");
        require(f.sale(a.pid, next[0].rs.nonce).epoch == first + 3, "in the next E");
        _anchorAt(a, first + 2, last);
        vm.roll(f.valueDeadline(first + 2) + 1);
        _proveAll(a, first + 2, last);
        _anchorAt(a, first + 3, next);
        vm.roll(f.valueDeadline(first + 3) + 1);
        _proveAll(a, first + 3, next);
        uint256[] memory c = _countsK(3, 2, 1);
        vm.roll(_passBlock(first, 3, c));
        require(m.release(a.addr) == PRICE, "pays the sale at E's last block only");
        require(f.accountCursor(a.addr) == first + 3, "moved 3");
        require(_status(a, next[0].rs.nonce) == f.ST_HELD(), "next E held");
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(a.addr); // next E not over (its last block is ahead)
        c = _countsK(3, 0, 1);
        vm.roll(_passBlock(first + 3, 3, c));
        require(m.release(a.addr) == PRICE, "next E");
        require(f.accountCursor(a.addr) == first + 6, "moved 6");
    }

    /// A dispute ending after its own profile epoch's deadlines but before
    /// the cursor passes E (k = 2, a sale in e2 holds E) is not paid then;
    /// the cursor pays it (R6 (c): the later of the two).
    function test_cursor_disputeEndsBeforeCursorPassesE() public {
        Acct memory a = _newAcct(2, 1);
        uint256 first = f.accountCursor(a.addr);
        Leaf[] memory e1 = new Leaf[](1);
        e1[0] = _sale(a, 0, PRICE, true); // unsigned: non-delivery dispute possible
        _anchorAt(a, first, e1);
        Leaf[] memory e2 = new Leaf[](1);
        e2[0] = _sale(a, 1, PRICE, false);
        vm.roll(f.valueDeadline(first) + 1);
        _proveAll(a, first, e1);
        _anchorAt(a, first + 1, e2);
        vm.roll(f.valueDeadline(first + 1) + 1);
        _proveAll(a, first + 1, e2);
        // open at the last block of e1's dispute window, answer one block later
        vm.roll(f.anchorDeadline(first) + f.T_C());
        epoch = first;
        Opening memory o = _opening(a.pid, e1, 0);
        uint8 kind = f.K_NONDELIVERY();
        vm.prank(buyer); // the next call must be openDispute itself
        f.openDispute(o, kind, "", 0);
        uint256[] memory c1 = _countsK(2, 0, 1);
        vm.roll(_passBlock(first, 2, c1)); // every deadline of e1 past, not those of e2
        uint256 s0 = token.balanceOf(a.addr);
        m.answerWithAck(a.pid, e1[0].rs.nonce, false, _ack(a.pid, e1[0].rs, false));
        require(_status(a, e1[0].rs.nonce) == f.ST_HELD(), "dispute over, cursor not past E: held");
        require(token.balanceOf(a.addr) == s0 + DEPOSIT, "only the deposit moved");
        vm.expectRevert(SettlementBase.Timing.selector);
        m.release(a.addr);
        uint256[] memory c = _all(2, 1);
        vm.roll(_passBlock(first, 2, c));
        require(m.release(a.addr) == 2 * PRICE, "cursor pays both");
    }

    /// A dispute still open when the cursor passes E (k = 2) is paid when
    /// it ends, not before.
    function test_cursor_disputeOpenAcrossCursor() public {
        Acct memory a = _newAcct(2, 1);
        uint256 first = f.accountCursor(a.addr);
        Leaf[] memory e1 = new Leaf[](1);
        e1[0] = _sale(a, 0, PRICE, true);
        _anchorAt(a, first, e1);
        vm.roll(f.valueDeadline(first) + 1);
        _proveAll(a, first, e1);
        uint256[] memory c = _countsK(2, 0, 1);
        uint256 d = _passBlock(first, 2, c);
        vm.roll(d - f.T_D() + 10);
        Opening memory o = _opening(a.pid, e1, 0);
        uint8 kind = f.K_NONDELIVERY();
        vm.prank(buyer); // the next call must be openDispute itself
        f.openDispute(o, kind, "", 0);
        vm.roll(d);
        require(m.release(a.addr) == 0, "open dispute not paid by the cursor");
        require(f.accountCursor(a.addr) == first + 2, "cursor passed E");
        uint256 s0 = token.balanceOf(a.addr);
        m.answerWithAck(a.pid, e1[0].rs.nonce, false, _ack(a.pid, e1[0].rs, false));
        require(_status(a, e1[0].rs.nonce) == f.ST_PAID(), "paid when the dispute ends");
        require(token.balanceOf(a.addr) == s0 + PRICE + DEPOSIT, "price and deposit");
    }

    // --------------------------------------------------------- gas: scan

    /// Cursor call over an empty seller epoch, one profile, no sales. Run
    /// with --isolate so the call is its own transaction (cold storage);
    /// without it the figures are of a warm call.
    function _emptyGas(uint16 k) internal returns (uint256 isolated, uint256 warm) {
        Acct memory a = _newAcct(k, 1);
        uint256 first = f.accountCursor(a.addr);
        vm.roll(f.lastBlock(first + k - 1) + 1);
        uint256 snap = vm.snapshotState();
        m.release(a.addr);
        isolated = ivm.lastCallGas().gasTotalUsed;
        vm.revertToState(snap);
        uint256 g0 = gasleft();
        m.release(a.addr);
        warm = g0 - gasleft();
    }

    function test_gas_emptyScan() public {
        uint16[3] memory ks = [uint16(1), 8, 32];
        uint256[3] memory iso;
        uint256[3] memory inl;
        for (uint256 i; i < 3; i++) {
            uint256 snap = vm.snapshotState();
            (iso[i], inl[i]) = _emptyGas(ks[i]);
            vm.revertToState(snap);
        }
        emit log_named_uint("k=1  isolated", iso[0]);
        emit log_named_uint("k=8  isolated", iso[1]);
        emit log_named_uint("k=32 isolated", iso[2]);
        emit log_named_uint("k=1  inline", inl[0]);
        emit log_named_uint("k=8  inline", inl[1]);
        emit log_named_uint("k=32 inline", inl[2]);
        emit log_named_uint("slope 1..8 isolated", (iso[1] - iso[0]) / 7);
        emit log_named_uint("slope 1..32 isolated", (iso[2] - iso[0]) / 31);
        emit log_named_uint("slope 1..8 inline", (inl[1] - inl[0]) / 7);
        emit log_named_uint("slope 1..32 inline", (inl[2] - inl[0]) / 31);
    }

    event log_named_uint(string key, uint256 val);
}
