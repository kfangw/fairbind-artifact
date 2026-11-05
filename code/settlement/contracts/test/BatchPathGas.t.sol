// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";

/// Call-frame gas of the batched paths (ADR 0032 to ADR 0035): settle under
/// batch terms, the batch's close and first assignment, a move at
/// assignment after a verifier's own exit request, a case end that starts
/// the next queued case, the proportional appeal deposit, the seller-proof
/// path with the compensation pool, the review values and late-value pauses
/// (ADR 0036), and the redraw of a waiting case into a queue. Run with
/// --isolate. Every number is logged; nothing is asserted about gas.
contract BatchPathGasTest is BatchBase {
    bytes internal constant ENVELOPE = bytes("evidence envelope");

    function _g(string memory label, uint256 gas) internal view {
        _log(label, gas);
    }

    function _settleTwice(string memory tag) internal returns (bytes32 a, bytes32 b) {
        hv.roll(10);
        SettleArgs memory x = _settleArgs(G);
        uint256 g = gasleft();
        _settle(x);
        _g(string.concat(tag, " settle (first of the account) gas"), g - gasleft());
        hv.roll(11);
        SettleArgs memory y = _settleArgs(G);
        g = gasleft();
        _settle(y);
        _g(string.concat(tag, " settle (second) gas"), g - gasleft());
        a = x.nonce;
        b = y.nonce;
    }

    /// The same deployment without batch terms: the reference for the two below.
    function test_gas_settleWithoutBatchTerms() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.batched = false;
        _deployBatched(_batchProfile(), t, _equalBonds());
        _settleTwice("no batch terms:");
    }

    function test_gas_settleUnderBatchTerms() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        _settleTwice("batched, fixed deposit:");
    }

    function test_gas_settleWithTheProportionalDeposit() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.depositPpm = 1_000_000_000;
        _deployBatched(_batchProfile(), t, _equalBonds());
        _settleTwice("batched, proportional deposit:");
    }

    /// n sample cases of one account, opened and assigned in batch 0.
    function _batchOfN(uint256 n, uint128[] memory bonds, uint96 slotValue) internal returns (bytes32[] memory ns) {
        ns = _batchOfNWith(n, bonds, slotValue, false);
    }

    /// With `exitFirst`, verifier 1 asks to exit after the request and a
    /// block before the value is stored, so its round-0 cases move.
    function _batchOfNWith(uint256 n, uint128[] memory bonds, uint96 slotValue, bool exitFirst)
        internal
        returns (bytes32[] memory ns)
    {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = slotValue;
        _deployBatched(_batchProfile(), t, bonds);
        hv.roll(10);
        ns = new bytes32[](n);
        for (uint256 i; i < n; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        hv.prank(KEEPER);
        uint256 g = gasleft();
        fairbind.openSample(ns[0]);
        _g("openSample (joins its batch) gas", g - gasleft());
        _submitReceipt(ns[0]);
        for (uint256 i = 1; i < n; i++) {
            _openSample(ns[i]);
        }
        hv.roll(1113);
        hv.prank(KEEPER);
        g = gasleft();
        fb.requestAssignValue(PROFILE, 0);
        _g("requestAssignValue gas", g - gasleft());
        if (exitFirst) {
            fairbind.requestVerifierExit(1);
            hv.roll(1114);
        }
        _fulfill(_assignId(0));
    }

    function _assignLogged(string memory label) internal {
        hv.prank(KEEPER);
        uint256 g = gasleft();
        fb.assignBatch(PROFILE, 0);
        _g(label, g - gasleft());
    }

    function test_gas_assignBatchOf1() public {
        _batchOfN(1, _equalBonds(), 10_000);
        _assignLogged("assignBatch, 1 case gas");
    }

    function test_gas_assignBatchOf4() public {
        _batchOfN(4, _equalBonds(), 10_000);
        _assignLogged("assignBatch, 4 cases gas");
    }

    function test_gas_assignBatchOf8() public {
        _batchOfN(8, _equalBonds(), 10_000);
        _assignLogged("assignBatch, 8 cases gas");
    }

    /// Eight cases, verifier 1 heavy with one slot: most cases queue.
    function test_gas_assignBatchOf8IntoQueues() public {
        _batchOfN(8, _heavyFirstBonds(), 30_000_000);
        _assignLogged("assignBatch, 8 cases, most queued gas");
        (BatchStore.Slots memory s,) = fb.getSlots(1);
        require(s.active == 1 && s.queued != 0, "one judging, a queue");
        (,,,,, bytes32[] memory list) = fb.getBatch(PROFILE, 0);
        bytes32 started;
        for (uint256 i; i < list.length; i++) {
            if (fairbind.getCase(list[i]).assignedVerifierId == 1) started = list[i];
        }
        _judgeBatched(started, uint8(FairBindCore.Verdict.PASS));
        FairBindCore.CaseView memory c = fairbind.getCase(started);
        hv.roll(uint256(c.randomBlock) + 1);
        hv.setBlockhash(c.randomBlock, keccak256("gate"));
        uint256 g = gasleft();
        fairbind.finalizeCase(started);
        _g("finalizeCase (PASS) that starts the next queued case gas", g - gasleft());
    }

    /// The same eight cases after verifier 1 asked to exit between A_0 and
    /// the batch value: the cases whose round-0 ticket names it move.
    function test_gas_assignBatchOf8WithMoves() public {
        bytes32[] memory ns = _batchOfNWith(8, _heavyFirstBonds(), 30_000_000, true);
        _assignLogged("assignBatch, 8 cases, moves after an exit request gas");
        uint256 moved;
        for (uint256 i; i < 8; i++) {
            if (fb.getBatchEntry(ns[i]).round != 0) moved++;
        }
        require(moved != 0, "cases moved");
        _log("cases moved past verifier 1", moved);
    }

    // ----------------------------------------------------------- appeal

    function _passedFor(BatchStore.Terms memory t) internal returns (bytes32 n) {
        _deployBatched(_batchProfile(), t, _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        _assignBatch(0);
        _judgeBatched(ns[0], uint8(FairBindCore.Verdict.PASS));
        hv.roll(_now() + 1);
        n = ns[0];
    }

    function test_gas_appealWithLimit() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.depositPpm = 1_000_000_000;
        bytes32 n = _passedFor(t);
        hv.prank(buyer);
        uint256 g = gasleft();
        fb.appealWithLimit(n, 20_000_000);
        _g("appealWithLimit (proportional deposit) gas", g - gasleft());
    }

    function test_gas_fixedAppeal() public {
        bytes32 n = _passedFor(_defaultTerms());
        hv.prank(buyer);
        uint256 g = gasleft();
        fairbind.appeal(n);
        _g("appeal (fixed deposit, batched profile) gas", g - gasleft());
    }

    // ------------------------------------------------- proofs and pool

    function _judgeProofLogged(bytes32 n, uint8 verdict, string memory label) internal {
        uint32 u = fb.getProof(n).verifier;
        bytes memory sig = _sig(1000 + u, fb.proofVerdictDigest(n, verdict));
        uint256 g = gasleft();
        fb.judgeProof(n, verdict, sig);
        _g(label, g - gasleft());
    }

    /// Two frozen entries proven and audited (p_a = 1): one fails, one
    /// passes; the pool is distributed and claimed.
    function test_gas_proofPathAndCompensation() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.auditPpm = 1_000_000;
        FairBindCore.ServiceProfileInput memory p = _batchProfile();
        p.effectivePpm = 400_000;
        _deployBatched(p, t, _equalBonds());
        hv.roll(10);
        bytes32 d = _purchase(G);
        bytes32 j = _purchase(G);
        bytes32 k = _purchase(G);
        _unserved(d);
        bytes32[] memory ns = new bytes32[](3);
        ns[0] = d;
        ns[1] = j;
        ns[2] = k;
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(j);
        _openSample(k);
        _assignBatch(0);
        _judgeBatched(j, uint8(FairBindCore.Verdict.PASS));
        _judgeBatched(k, uint8(FairBindCore.Verdict.PASS));
        FairBindCore.CaseView memory c = fairbind.getCase(j);
        hv.roll(uint256(c.randomBlock) + 1);
        hv.setBlockhash(c.randomBlock, keccak256("gate"));
        fairbind.finalizeCase(j);
        fairbind.finalizeCase(k);
        _buildTree(ns);
        bytes32[2] memory both = [j, k];
        for (uint256 i; i < 2; i++) {
            FairBindCore.FairBindReceipt memory r = _receipt(both[i]);
            bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
            FairBindCore.ReceiptProof memory pf = _proof(both[i]);
            hv.prank(SELLER_OWNER);
            uint256 g = gasleft();
            fb.submitProof(both[i], r, sig, pf, ENVELOPE);
            if (i == 0) _g("submitProof (opens, audit use registered) gas", g - gasleft());
        }
        uint64 at = fb.getProof(j).auditBlock;
        hv.roll(uint256(at) + 1);
        for (uint256 i; i < 2; i++) {
            hv.prank(KEEPER);
            uint256 g = gasleft();
            fb.requestAuditValue(both[i]);
            if (i == 0) _g("requestAuditValue gas", g - gasleft());
            _fulfill(_auditId(both[i], at));
            hv.prank(KEEPER);
            g = gasleft();
            fb.drawAudit(both[i]);
            if (i == 0) _g("drawAudit (audited, joins its batch) gas", g - gasleft());
        }
        uint24 e = fb.getBatchEntry(fb.proofCaseId(j)).batch;
        if (_now() <= _a(e)) hv.roll(uint256(_a(e)) + 1);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, e);
        hv.roll(_c(e) + 1);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, e);
        _fulfill(_assignId(e));
        hv.prank(KEEPER);
        uint256 g0 = gasleft();
        fb.assignBatch(PROFILE, e);
        _g("assignBatch, 2 proof cases gas", g0 - gasleft());
        _judgeProofLogged(j, uint8(FairBindCore.Verdict.FAIL), "judgeProof FAIL (bond to the pool, one count) gas");
        _judgeProofLogged(k, uint8(FairBindCore.Verdict.PASS), "judgeProof PASS (confirmed, share of the pool) gas");
        uint32 bondId = _bondOfSeller(sellerId);
        hv.prank(KEEPER);
        g0 = gasleft();
        fb.distributeCompensation(bondId);
        _g("distributeCompensation gas", g0 - gasleft());
        g0 = gasleft();
        fb.claimCompensation(k);
        _g("claimCompensation gas", g0 - gasleft());
    }

    // ------------------------------------------- review values (ADR 0036)

    function test_gas_reviewValuePath() public {
        bytes32 n = _passedFor(_defaultTerms());
        hv.prank(buyer);
        uint256 g = gasleft();
        fairbind.appeal(n);
        _g("appeal (fixed deposit, registers the review use) gas", g - gasleft());
        uint256 t = _now();
        hv.roll(t + 1);
        hv.prank(KEEPER);
        g = gasleft();
        fb.requestReviewValue(n);
        _g("requestReviewValue gas", g - gasleft());
        hv.roll(t + 15);
        hv.prank(KEEPER);
        g = gasleft();
        fb.markValueLate(n);
        _g("markValueLate (review value) gas", g - gasleft());
        _fulfill(_reviewId(n));
        hv.prank(KEEPER);
        g = gasleft();
        fb.assignReview(n);
        _g("assignReview (ends the pause, starts) gas", g - gasleft());
    }

    function test_gas_reviewValueExit() public {
        bytes32 n = _passedFor(_defaultTerms());
        hv.prank(buyer);
        fairbind.appeal(n);
        uint256 t = _now();
        hv.roll(t + 1);
        hv.prank(KEEPER);
        fb.requestReviewValue(n);
        hv.roll(t + 32);
        hv.prank(KEEPER);
        uint256 g = gasleft();
        fb.timeoutReviewValue(n);
        _g("timeoutReviewValue (buyer appeal, no count) gas", g - gasleft());
    }

    /// Two sample cases wait for a batch value marked late; the batch is
    /// assigned after the mark.
    function test_gas_lateBatchValue() public {
        _batchOfNWithoutValue(2);
        hv.roll(1140);
        hv.prank(KEEPER);
        uint256 g = gasleft();
        fb.markAssignLate(PROFILE, 0);
        _g("markAssignLate, 2 cases gas", g - gasleft());
        _fulfill(_assignId(0));
        _assignLogged("assignBatch, 2 cases after a late mark gas");
    }

    function test_gas_unmarkedLateBatchValue() public {
        _batchOfNWithoutValue(2);
        hv.roll(1140);
        _fulfill(_assignId(0));
        _assignLogged("assignBatch, 2 cases, late value without a mark gas");
    }

    function _batchOfNWithoutValue(uint256 n) internal {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](n);
        for (uint256 i; i < n; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
    }

    function test_gas_lateSampleValue() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        hv.roll(701);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 0);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 0);
        hv.roll(715);
        hv.prank(KEEPER);
        uint256 g = gasleft();
        fb.markSampleLate(sellerId, 0);
        _g("markSampleLate gas", g - gasleft());
        _fulfill(_sampleId(0));
        hv.roll(721);
        hv.prank(KEEPER);
        g = gasleft();
        fairbind.seal(sellerId, 0);
        _g("seal (ends a late-sample pause) gas", g - gasleft());
    }

    // ------------------------------------------- redraw under batch terms

    /// Three cases wait after every verifier of A_0's checkpoint asked to
    /// exit; their redraws on A_2's checkpoint start or queue.
    function test_gas_redrawIntoAQueue() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        _deployBatched(_batchProfile(), t, _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1100);
        for (uint32 u = 1; u <= 14; u++) fairbind.requestVerifierExit(u);
        for (uint32 i = 15; i <= 28; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), i == 15 ? 100_000_000 : 1_000_000);
        }
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
        _fulfill(_assignId(0));
        _assignLogged("assignBatch, 3 cases, every round left (all wait) gas");
        hv.roll(1301);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 2);
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            uint256 g = gasleft();
            fairbind.registerRedraw(ns[i]);
            if (i == 0) _g("registerRedraw (batched) gas", g - gasleft());
        }
        hv.roll(1302);
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            fairbind.requestRedrawValue(ns[i]);
            _fulfill(keccak256(abi.encode(VRF_AUX, abi.encode(keccak256("FairBind/redraw/v1"), ns[i], uint8(1), uint32(1), uint64(1301)))));
        }
        for (uint256 i; i < 3; i++) {
            hv.prank(KEEPER);
            uint256 g = gasleft();
            fairbind.assignVerifier(ns[i]);
            uint256 used = g - gasleft();
            bool queued = fairbind.getCase(ns[i]).state == uint8(FairBindCore.CaseState.QUEUED);
            _g(queued ? "assignVerifier, batched redraw into a queue gas" : "assignVerifier, batched redraw that starts gas", used);
        }
    }
}
