// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Inv } from "./InvariantBase.sol";
import { LifecycleHandler } from "./LifecycleHandler.sol";
import { LifecycleSetup } from "./LifecycleInvariants.t.sol";

/// Drives the handler with pseudo-random sequences of the invariant depth and
/// checks that every deadline branch the invariants rely on is reachable:
/// each side of the anchor, seal, serve, judge, appeal, evidence and claim
/// windows, and the freeze, sanction, overturn and forfeiture paths.
contract LifecycleCoverageTest is LifecycleSetup {
    address internal constant CONSOLE = 0x000000000000000000636F6e736F6c652e6c6f67;
    uint256 internal constant SEQUENCES = 96;
    uint256 internal constant DEPTH = 96;
    uint256 internal constant ACTIONS = 49;

    uint256[256] internal total;

    function _log(string memory label, uint256 value) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,uint256)", label, value));
        ok;
    }

    function _step(uint256 r) internal {
        uint256 a = r % ACTIONS;
        uint256 s = r >> 8;
        uint8 m = uint8(r >> 200);
        LifecycleHandler h = handler;
        if (a == 0 || a == 1 || a == 2) h.settle(s, s >> 3, s >> 9);
        else if (a == 3) h.advance(s);
        else if (a == 4) h.anchorEpoch(s, m);
        else if (a == 5) h.sealEpoch(s, m);
        else if (a == 6) h.openSample(s, m % 4 == 0);
        else if (a == 7) h.disputeWrongDelivery(s, m);
        else if (a == 8) h.disputeNonDelivery(s, m);
        else if (a == 9) h.assignVerifier(s);
        else if (a == 10) h.judge(s, uint8(s >> 5), m);
        else if (a == 11) h.timeoutJudge(s, m);
        else if (a == 12) h.appeal(s, m);
        else if (a == 13) h.finalizeCase(s, m);
        else if (a == 14) h.sealReview(s, m);
        else if (a == 15) h.openAutoRecheck(s, m);
        else if (a == 16) h.requestEvidence(s, m % 2 == 0, m >> 1);
        else if (a == 17) h.discloseEvidence(s, m);
        else if (a == 18) h.timeoutEvidence(s, m);
        else if (a == 19) h.requestServe(s);
        else if (a == 20) h.served(s, m);
        else if (a == 21) h.confirmServe(s, m);
        else if (a == 22) h.publish(s);
        else if (a == 23) h.timeoutServe(s, m);
        else if (a == 24) h.buyerRecovery(s, m);
        else if (a == 25) h.claimEpochFailure(s);
        else if (a == 26) h.claimRefund(s);
        else if (a == 27) h.claimFrozen(s, m);
        else if (a == 28) h.forfeitUnclaimed(s, m);
        else if (a == 29) h.releasePurchase(s, m);
        else if (a == 30) h.freezeSellerDeferred(s);
        else if (a == 31) h.releaseFrozen(s);
        else if (a == 32) h.reinstateSeller(s);
        else if (a == 33) h.topUpBond(s, s >> 7);
        else if (a == 34) h.registerSeller(s);
        else if (a < 42) h.keeper(s, m);
        else if (a == 44) h.timeoutSampleReceipt(s, m);
        // Mode bit 1 of reenter first produces a failure when no claim window
        // is open; the sequences leave it clear so that they reach the same
        // branches as before it.
        else if (a == 45) h.reenter(s, m & 0xfd);
        else if (a == 46) h.setBondTerms(s, m);
        else if (a == 47) h.submitSampleReceipt(s, m);
        else if (a == 48) h.stalledSellerAppeal(s, m);
        else h.keeperRun(s, m);
    }

    function test_deadlineBranchesAreReachable() public {
        string[59] memory names = [
            "", "anchor", "anchor late", "timeoutAnchor", "timeoutAnchor early", "seal", "seal after its deadline",
            "timeoutSeal refused on a full checkpoint", "seal refused without its value", "seal early", "judge", "judge late", "timeoutJudge",
            "timeoutJudge early", "appeal", "appeal late", "finalizeCase", "finalizeCase early", "served",
            "served late", "timeoutServe", "timeoutServe early", "frozen claim", "frozen claim late",
            "forfeitUnclaimed", "forfeitUnclaimed early", "review seal", "review seal expired",
            "automatic recheck", "evidence timeout", "evidence disclosed", "release", "release refused frozen",
            "reinstate", "keeper serve", "buyer recovery", "publish", "rate limit", "epoch failure claim",
            "refund", "dispute late", "freezeSellerDeferred", "releaseFrozen", "foreign receipt refused",
            "settle", "dispute", "openSample", "requestServe", "escalate", "register", "top-up",
            "buyer recovery timeout", "claim outside window", "settle during an open claim window",
            "review seal reopened", "sample receipt timeout", "sample case after a delivered dispute",
            "bond terms changed", "sample receipt submitted"
        ];
        Inv.vm.pauseGasMetering();
        for (uint256 q; q < SEQUENCES; q++) {
            _setUp(Inv.BUILD_REAL);
            uint256 r = uint256(keccak256(abi.encode("coverage", q)));
            for (uint256 d; d < DEPTH; d++) {
                r = uint256(keccak256(abi.encode(r)));
                _step(r);
            }
            for (uint8 b = 1; b < 59; b++) total[b] += obs.hits(b);
            for (uint8 b = 200; b < 205; b++) total[b] += obs.hits(b);
            for (uint8 c; c < Inv.CATEGORIES; c++) {
                if (obs.violations(c) != 0) _log(string.concat("violation ", obs.firstViolation(c)), c);
            }
        }
        for (uint8 b = 1; b < 59; b++) _log(names[b], total[b]);
        _log("inconclusive threshold freeze", total[200]);
        _log("sanction", total[201]);
        _log("overturn", total[202]);
        _log("frozen window moved by a failure in an open claim window", total[203]);
        _log("stalled seller appeal upheld the initial FAIL", total[204]);
        // Both sides of every window, and the freeze, claim, forfeiture,
        // overturn, sanction and reinstatement paths. Publication, escalation,
        // freezeSellerDeferred and releaseFrozen are reported only: the last is
        // reachable only when a trigger ends outside the paths that unfreeze.
        // The overturn of a FROZEN account exists only under freezeOnInitialFail:
        // without it a confirmed failure opens the claim window at once and an
        // overturned initial FAIL never froze anything (ADR 0020).
        // Re-entry during an open claim window, the window moved by the next
        // confirmed failure, and a reopened review seal (ADR 0021) are required too.
        // A submitted sample receipt and a stalled seller appeal that upholds
        // the initial FAIL (ADR 0024, ADR 0025) are required as well.
        uint8[44] memory required = [
            1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
            26, 27, 28, 29, 30, 31, 32, 33, 34, 37, 39, 53, 54, 58, 200, 201, 202, 203, 204
        ];
        bool freezeOnInitialFail = Inv.freezeOnInitialFail();
        // Under design 2 terms every purchase at the cap is sampled and the
        // sequences reach an overturn of a FROZEN account too rarely to
        // require it; changing bond terms is required instead (ADR 0025).
        bool tiered = Inv.tiered();
        if (tiered) require(total[57] != 0, "branch never reached: bond terms changed");
        for (uint256 i; i < required.length; i++) {
            uint8 b = required[i];
            if (b == 202 && !freezeOnInitialFail) {
                require(total[b] == 0, "overturn of a FROZEN account without freezeOnInitialFail");
                continue;
            }
            if (b == 202 && tiered) continue;
            // Without a sanction limit (B = b, ADR 0027) no account is ever
            // sanctioned, and reaching the branch would be a violation.
            if (b == 201 && Inv.sanctionLimit() == 0 && tiered) {
                require(total[b] == 0, "sanction without a sanction limit");
                continue;
            }
            require(total[b] != 0, string.concat("branch never reached: ", b < 59 ? names[b] : Inv.toString(b)));
        }
    }
}

/// The waiting-assignment variant (ADR 0028) reaches its branches: a sample
/// case that waits, a redraw that assigns after a newer checkpoint, a redraw
/// refused before a newer checkpoint or its value, a release refused while
/// the case waits, and a release refused only because a case of the account
/// waited since the entry's settlement (ADR 0029).
contract WaitingCoverageTest is LifecycleSetup {
    address internal constant CONSOLE = 0x000000000000000000636F6e736F6c652e6c6f67;
    uint256 internal constant SEQUENCES = 32;
    uint256 internal constant DEPTH = 96;

    uint256[256] internal total;

    function _log(string memory label, uint256 value) internal view {
        (bool ok,) = CONSOLE.staticcall(abi.encodeWithSignature("log(string,uint256)", label, value));
        ok;
    }

    function _step(uint256 r) internal {
        uint256 a = r % 16;
        uint256 s = r >> 8;
        uint8 m = uint8(r >> 200);
        LifecycleHandler h = handler;
        if (a < 3) h.settle(s, s >> 3, s >> 9);
        else if (a == 3) h.advance(s);
        else if (a == 4) h.openSample(s, false);
        else if (a == 5) h.redraw(s, m);
        else if (a == 6) h.refillVerifiers(s);
        else if (a == 7) h.releasePurchase(s, m);
        else if (a == 8) h.disputeWrongDelivery(s, m);
        else if (a == 9) h.timeoutSampleReceipt(s, m);
        else if (a == 10) h.submitSampleReceipt(s, m);
        else if (a == 11) h.judge(s, uint8(s >> 5), m);
        else if (a == 12) h.timeoutJudge(s, m);
        else if (a < 15) h.keeper(s, m);
        else h.keeperRun(s, m);
    }

    function test_waitingBranchesAreReachable() public {
        string[5] memory names = [
            "case waits", "redraw assigns", "redraw refused early", "release refused while waiting",
            "release refused while the account's clock is stopped"
        ];
        Inv.vm.pauseGasMetering();
        for (uint256 q; q < SEQUENCES; q++) {
            _setUp(Inv.BUILD_REAL, true);
            uint256 r = uint256(keccak256(abi.encode("waiting coverage", q)));
            for (uint256 d; d < DEPTH; d++) {
                r = uint256(keccak256(abi.encode(r)));
                _step(r);
            }
            for (uint8 b = 1; b < 64; b++) total[b] += obs.hits(b);
            for (uint8 c; c < Inv.CATEGORIES; c++) {
                if (obs.violations(c) != 0) _log(string.concat("violation ", obs.firstViolation(c)), c);
                require(obs.violations(c) == 0, obs.firstViolation(c));
            }
        }
        for (uint8 b = 59; b < 64; b++) {
            _log(names[b - 59], total[b]);
            require(total[b] != 0, string.concat("branch never reached: ", names[b - 59]));
        }
        _log("judge", total[10]);
        _log("release", total[31]);
    }
}
