// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { Impl1bBase } from "./Design2Impl1b.t.sol";

interface ClockBlockVm {
    function getBlockNumber() external view returns (uint256);
}

/// Shared driving of the ADR 0029 release-clock tests: an epoch of eight
/// purchases settled at block 10, sealed at BEACON_BLOCK + 1, with verifiers
/// that have no room at the epoch's checkpoint, so that every sample case
/// opened on it waits (ADR 0028).
abstract contract ReleaseClockBase is Impl1bBase {
    ClockBlockVm internal constant cv = ClockBlockVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant SETTLED = 10;
    uint256 internal constant DEFER = 40_000;
    uint8 internal constant WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);
    bytes32 internal constant REDRAW_HASH = keccak256("redraw hash");

    bytes32[] internal sampled;
    bytes32[] internal plain;

    /// The current block through the cheatcode: under via_ir a test function
    /// may read a stale block.number after a roll.
    function _now() internal view returns (uint256) {
        return cv.getBlockNumber();
    }

    function _bond() internal view returns (uint32) {
        return fairbind.getSeller(sellerId).bondId;
    }

    /// Half of all purchases sampled, no automatic recheck, verifier exposure
    /// 10%: a bond of 10 USDC leaves 0.9 USDC of room, below one case.
    function _clockProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _sampledProfile(20);
        p.samplePpm = 500_000;
        p.verifierExposurePpm = 100_000;
    }

    function _epoch() internal {
        _deploy(_clockProfile());
        hv.roll(SETTLED);
        bytes32[] memory ns = new bytes32[](8);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        for (uint256 i; i < ns.length; i++) {
            (bool eligible,) = fairbind.isSampled(ns[i]);
            if (eligible) sampled.push(ns[i]);
            else plain.push(ns[i]);
        }
        require(sampled.length >= 2 && plain.length >= 2, "fixture: two sampled and two unsampled purchases");
    }

    /// Tops up every verifier by 10 USDC (room for one case), writes a
    /// checkpoint one block later and returns its redraw block.
    function _newerCheckpoint() internal returns (uint256 randomBlock) {
        for (uint32 id = 1; id <= 14; id++) fairbind.topUpVerifierBond(id, 10_000_000);
        hv.roll(_now() + 1);
        fairbind.checkpointVerifierTree(PROFILE);
        randomBlock = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
    }

    function _clock() internal view returns (uint32 waiting, uint32 pauses, uint64 total) {
        return fairbind.getReleaseClock(_bond());
    }

    /// Releases `n` exactly at block `at`: the call reverts one block earlier.
    function _releaseExactlyAt(bytes32 n, uint256 at) internal {
        hv.roll(at - 1);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(n);
        hv.roll(at);
        uint256 before = token.balanceOf(SELLER_OWNER);
        fairbind.releasePurchase(n);
        require(token.balanceOf(SELLER_OWNER) == before + G, "released to the seller");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.RELEASED), "released");
    }
}

/// Design 2 rule D2-21 (paper rule (vii)), ADR 0029: while a sampled case of
/// an account waits for an assignment, the account's release clock stops.
contract ReleaseClockTest is ReleaseClockBase {
    /// (1) An unsampled entry of the account is not released while a case
    /// of the account waits, even long after deferBlocks wall blocks, and
    /// nothing is counted against the seller.
    function test_noReleaseWhileACaseOfTheAccountWaits() public {
        _epoch();
        uint256 waitFrom = _now();
        fairbind.openSample(sampled[0]);
        require(fairbind.getCase(sampled[0]).state == WAITING, "waits");
        (uint32 waiting, uint32 pauses, uint64 total) = _clock();
        require(waiting == 1 && pauses == 1 && total == 0, "clock stopped from this block");
        bytes32 u = plain[0];
        // Every release condition of ADR 0024 holds from block SETTLED + DEFER.
        hv.roll(SETTLED + DEFER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(u);
        hv.roll(SETTLED + 5 * DEFER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.releasePurchase(u);
        require(fairbind.pausedSince(_bond(), uint64(SETTLED)) == _now() - waitFrom, "paused since the wait began");
        // The effective age stays at the blocks before the wait.
        require(_now() - SETTLED - fairbind.pausedSince(_bond(), uint64(SETTLED)) == waitFrom - SETTLED, "age");
        FairBindCore.BondView memory b = fairbind.getBond(_bond());
        require(b.failureCount == 0 && b.freezeState == 0, "no failure, no freeze");
        require(fairbind.getPurchase(u).financialState == uint8(FairBindCore.FinancialState.DEFERRED), "held");
    }

    /// (2) Once the wait ends, release resumes after deferBlocks unpaused
    /// blocks: exactly at SETTLED + DEFER + (end - start) of the pause.
    function test_releaseResumesAfterTheWaitWithTheUnpausedCount() public {
        _epoch();
        uint256 start = _now();
        fairbind.openSample(sampled[0]);
        uint256 rb = _newerCheckpoint();
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        fairbind.assignVerifier(sampled[0]);
        uint256 end = _now();
        require(fairbind.getCase(sampled[0]).state == uint8(FairBindCore.CaseState.JUDGING), "assigned");
        (uint32 waiting, uint32 pauses, uint64 total) = _clock();
        require(waiting == 0 && pauses == 1 && total == end - start, "one pause of end - start blocks");
        _log("paused blocks", end - start);
        _releaseExactlyAt(plain[0], SETTLED + DEFER + (end - start));
        // A pause before the settlement block does not delay a later entry.
        require(fairbind.pausedSince(_bond(), uint64(end)) == 0, "nothing paused since the wait ended");
    }

    /// (3) Two waits that overlap stop the clock once: the pause runs from the
    /// first wait's start to the last wait's end.
    function test_overlappingWaitsCountOnce() public {
        _epoch();
        uint256 start = _now();
        fairbind.openSample(sampled[0]);
        hv.roll(start + 130);
        fairbind.openSample(sampled[1]);
        require(fairbind.getCase(sampled[1]).state == WAITING, "second waits");
        (uint32 waiting, uint32 pauses,) = _clock();
        require(waiting == 2 && pauses == 1, "two waiting cases, one pause");
        uint256 rb = _newerCheckpoint();
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        fairbind.assignVerifier(sampled[0]);
        (waiting, pauses,) = _clock();
        require(waiting == 1 && pauses == 1, "still paused while the second waits");
        hv.roll(rb + 51);
        fairbind.assignVerifier(sampled[1]);
        uint256 end = _now();
        uint64 total;
        (waiting, pauses, total) = _clock();
        require(waiting == 0 && pauses == 1 && total == end - start, "one pause from first start to last end");
        // Counted twice it would be (end - start) + (end - start - 130).
        _releaseExactlyAt(plain[0], SETTLED + DEFER + (end - start));
    }

    /// Pauses that do not touch are kept apart: pausedSince(s) sums only the
    /// paused blocks at or after s, also when s lies inside a pause.
    function test_pausedSinceSumsOnlyThePausesAfterTheBlock() public {
        _epoch();
        uint256 a1 = _now();
        fairbind.openSample(sampled[0]);
        uint256 rb = _newerCheckpoint();
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        fairbind.assignVerifier(sampled[0]);
        uint256 z1 = _now();
        // The epoch's checkpoint has no room, so a second case opened now
        // waits again: a second pause.
        hv.roll(z1 + 200);
        uint256 a2 = _now();
        fairbind.openSample(sampled[1]);
        require(fairbind.getCase(sampled[1]).state == WAITING, "waits on the epoch checkpoint");
        hv.roll(a2 + 300);
        (uint32 waiting, uint32 pauses, uint64 total) = _clock();
        require(waiting == 1 && pauses == 2, "two pauses");
        uint256 p1 = z1 - a1;
        require(total == p1 + 300, "both pauses up to now");
        uint32 b = _bond();
        require(fairbind.pausedSince(b, uint64(SETTLED)) == p1 + 300, "from the settlement");
        require(fairbind.pausedSince(b, uint64(a1)) == p1 + 300, "from the first start");
        require(fairbind.pausedSince(b, uint64(a1 + 7)) == p1 - 7 + 300, "from inside the first pause");
        require(fairbind.pausedSince(b, uint64(z1)) == 300, "from the first end");
        require(fairbind.pausedSince(b, uint64(z1 + 100)) == 300, "between the pauses");
        require(fairbind.pausedSince(b, uint64(a2)) == 300, "from the second start");
        require(fairbind.pausedSince(b, uint64(a2 + 120)) == 180, "from inside the open pause");
        require(fairbind.pausedSince(b, uint64(_now())) == 0, "from this block");
    }

    /// A waiting case that ends UNSERVED (its receipt never posted) leaves
    /// the wait and restarts the clock in that block.
    function test_aWaitingCaseThatEndsRestartsTheClock() public {
        _epoch();
        uint256 start = _now();
        fairbind.openSample(sampled[0]);
        uint256 due = fairbind.getSampleReceiptDue(sampled[0]);
        hv.roll(due + 1);
        fairbind.timeoutSampleReceipt(sampled[0]);
        require(fairbind.getCase(sampled[0]).state == uint8(FairBindCore.CaseState.UNSERVED), "unserved");
        (uint32 waiting, uint32 pauses, uint64 total) = _clock();
        require(waiting == 0 && pauses == 1 && total == due + 1 - start, "clock restarted at the failure");
    }

    /// A redraw that finds nothing leaves the case waiting and does not
    /// count it again; a pause that begins and ends in one block is dropped.
    function test_anExhaustedRedrawKeepsOnePause() public {
        _epoch();
        uint256 start = _now();
        fairbind.openSample(sampled[0]);
        // A newer checkpoint where no verifier has room: one more verifier.
        hv.roll(_now() + 1);
        fairbind.registerVerifier(uint256(1) << 1, hv.addr(1015), 1_000_000);
        require(fairbind.checkpointVerifierTree(PROFILE) == 2, "version 2 has no room");
        uint256 rb = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        fairbind.assignVerifier(sampled[0]);
        require(fairbind.getCase(sampled[0]).state == WAITING, "still waits");
        (uint32 waiting, uint32 pauses, uint64 total) = _clock();
        require(waiting == 1 && pauses == 1 && total == _now() - start, "one open pause");
    }
}

/// D2-21 (d), ADR 0029: the largest cap of the preceding hold (V*), the
/// balance a settlement or re-entry requires, and the bond paid out on exit
/// count the same unpaused blocks.
contract ReleaseClockTermsTest is Impl1bBase {
    ClockBlockVm internal constant cv = ClockBlockVm(address(uint160(uint256(keccak256("hevm cheat code")))));
    uint256 internal constant HOLD = 31_073;
    uint256 internal constant LOWERED = 1_500;

    function _now() internal view returns (uint256) {
        return cv.getBlockNumber();
    }

    /// Design 2 terms with exposure 4%: a verifier bond of 50 USDC leaves
    /// 1.96 USDC of room, below a case of value 1 USDC (liability 2 USDC).
    function _waitingAtCapOne() internal returns (bytes32 w) {
        FairBindCore.ServiceProfileInput memory p = _profileD2();
        p.verifierExposurePpm = 40_000;
        _deployD2(p, true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        hv.roll(10);
        w = _purchase(CAP_LARGE);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = w;
        _anchorAndSeal(ns, BEACON);
        fairbind.openSample(w);
        require(fairbind.getCase(w).state == uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT), "waits");
        // The receipt goes on chain before its deadline, long before a redraw.
        FairBindCore.FairBindReceipt memory r = _receipt(w);
        fairbind.submitSampleReceipt(w, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(w));
        hv.roll(LOWERED);
        _setTerms(CAP_SMALL, TIER_BASE);
    }

    /// Redraws w on a checkpoint where every verifier has room; returns the block.
    function _endWait(bytes32 w) internal returns (uint256) {
        for (uint32 id = 1; id <= 14; id++) fairbind.topUpVerifierBond(id, 2_000_000);
        hv.roll(_now() + 1);
        fairbind.checkpointVerifierTree(PROFILE);
        uint256 rb = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
        hv.roll(rb + 1);
        hv.setBlockhash(rb, keccak256("redraw"));
        fairbind.assignVerifier(w);
        require(fairbind.getCase(w).state == uint8(FairBindCore.CaseState.JUDGING), "assigned");
        return _now();
    }

    /// V* and the required balance stay at cap 1 while the clock is stopped,
    /// past the raw hold, and expire exactly HOLD unpaused blocks after the
    /// cap was lowered; a confirmed failure in between deducts b(1).
    function test_recentCapAndRequiredBalanceCountUnpausedBlocks() public {
        bytes32 w = _waitingAtCapOne();
        require(fairbind.unitBond(bondId) == 87 * B_LARGE, "V* = 1 after lowering");
        // A purchase at the lower cap in an epoch that is never anchored.
        bytes32 late = _purchase(CAP_SMALL);
        uint24 lateEpoch = fairbind.getPurchase(late).epoch;
        hv.roll(LOWERED + HOLD + 1);
        // Without the pause V* would be the lower cap here.
        require(fairbind.unitBond(bondId) == 87 * B_LARGE, "V* still 1 while the case waits");
        uint256 snap = sv.snapshotState();
        fairbind.timeoutAnchor(sellerId, lateEpoch);
        require(fairbind.getBond(bondId).balance == 87 * B_LARGE - B_LARGE, "deducts b(V*) = b(1)");
        sv.revertToState(snap);
        hv.roll(LOWERED + HOLD + 1);
        uint256 end = _endWait(w);
        // The lowering happened inside the pause, so its hold restarts at end.
        hv.roll(end + HOLD);
        require(fairbind.unitBond(bondId) == 87 * B_LARGE, "V* = 1 for HOLD unpaused blocks");
        hv.roll(end + HOLD + 1);
        require(fairbind.unitBond(bondId) == 87 * B_SMALL, "V* expires after HOLD unpaused blocks");
    }

    /// The bond is paid out on exit only after HOLD unpaused blocks since the
    /// exit request.
    function test_bondExitCountsUnpausedBlocks() public {
        bytes32 w = _waitingAtCapOne();
        hv.startPrank(SELLER_OWNER);
        fairbind.requestSellerExit(sellerId);
        fairbind.requestBondExit(bondId);
        hv.stopPrank();
        uint256 eligible = fairbind.getBond(bondId).exitEligibleBlock;
        require(eligible == LOWERED + HOLD, "exit lock of HOLD blocks");
        uint256 end = _endWait(w);
        _postAndPass(w);
        // w itself: HOLD unpaused blocks since block 10, paused from the seal.
        uint256 paused = end - (BEACON_BLOCK + 1);
        hv.roll(10 + HOLD + paused);
        fairbind.releasePurchase(w);
        hv.roll(eligible + 1);
        hv.prank(SELLER_OWNER);
        fairbind.finalizeSellerExit(sellerId);
        uint256 payout = eligible + (end - LOWERED);
        hv.roll(payout - 1);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ExitNotReady.selector);
        fairbind.finalizeBondExit(bondId);
        hv.roll(payout);
        uint256 before = token.balanceOf(SELLER_OWNER);
        hv.prank(SELLER_OWNER);
        fairbind.finalizeBondExit(bondId);
        require(token.balanceOf(SELLER_OWNER) == before + 87 * B_LARGE, "bond paid out");
    }

    function _postAndPass(bytes32 w) internal {
        _judge(w, uint8(FairBindCore.Verdict.PASS));
        uint64 gate = fairbind.getCase(w).randomBlock;
        hv.roll(uint256(gate) + 1);
        hv.setBlockhash(gate, keccak256("gate"));
        fairbind.finalizeCase(w);
        require(fairbind.getCase(w).state == uint8(FairBindCore.CaseState.FINAL), "final");
    }
}
