// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../../src/FairBind.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";
import { Inv } from "./InvariantBase.sol";
import { LifecycleHandler } from "./LifecycleHandler.sol";
import { LifecycleObserver } from "./LifecycleObserver.sol";
// Inv.deploy loads these by artifact name; importing them keeps their artifacts
// linked when a filter selects only this file.
import { MockEIP3009Token } from "../MockEIP3009Token.sol";
import { NoFreezeJudgment, NoFreezeReview } from "./FreezeDisabled.sol";
import { FreezeKeptSampling, FreezeKeptDelivery, FreezeKeptJudgment, FreezeKeptReview } from "./ReentryMutation.sol";
import { WaitReleaseSampling, WaitReleaseRecovery } from "./WaitRelease.sol";
import { PauseIgnoredRecovery } from "./PauseIgnored.sol";
import { AdmissionOverrideRegistry } from "../AdmissionOverrideRegistry.sol";

interface SetupToken {
    function mint(address to, uint256 value) external;
    function approve(address spender, uint256 value) external returns (bool);
}

/// Deploys FairBind (or one of the two mutation builds), the profile, fourteen
/// verifiers owned by this contract, and the handler.
abstract contract LifecycleSetup {
    /// Selector set of an invariant target, as forge reads it.
    struct FuzzSelector {
        address addr;
        bytes4[] selectors;
    }

    FairBind internal fb;
    LifecycleHandler internal handler;
    LifecycleObserver internal obs;
    bool internal waitingVariant;
    uint8 internal build;

    function _setUp(uint8 buildKind) internal {
        _setUp(buildKind, false);
    }

    /// `waiting` selects the waiting-assignment variant (ADR 0028): verifiers
    /// open with a bond whose room at the first checkpoint is below one case.
    function _setUp(uint8 buildKind, bool waiting) internal {
        waitingVariant = waiting;
        build = buildKind;
        address token = Inv.vm.deployCode("MockEIP3009Token.sol:MockEIP3009Token", "");
        fb = Inv.deploy(token, address(this), buildKind);
        Inv.vm.roll(10);
        fb.createDeadlineConfig(1, Inv.deadlines());
        fb.createServiceProfile(Inv.PROFILE, Inv.profile());
        if (Inv.tiered()) {
            FairBindCore.SalesTier[] memory t = Inv.tiers(40_500 + fb.judgmentDelayBlocks(Inv.PROFILE));
            fb.setProfileTerms(Inv.PROFILE, Inv.termsHash(t), 40_000, Inv.caps(), t);
        }
        SetupToken(token).mint(address(this), 1_000_000_000);
        SetupToken(token).approve(address(fb), type(uint256).max);
        for (uint256 i = 1; i <= Inv.VERIFIER_COUNT; i++) {
            fb.registerVerifier(uint256(1) << 1, Inv.vm.addr(Inv.VERIFIER_KEY_BASE + i),
                waiting ? Inv.WAIT_VERIFIER_BOND : Inv.VERIFIER_BOND);
        }
        fb.checkpointVerifierTree(Inv.PROFILE);
        fb.setServiceProfileActive(Inv.PROFILE, true);
        handler = new LifecycleHandler(fb, token, address(this), buildKind != Inv.BUILD_NO_FREEZE, waiting);
        obs = handler.obs();
    }

    function targetContracts() public view returns (address[] memory targets) {
        targets = new address[](1);
        targets[0] = address(handler);
    }

    /// The two waiting-assignment actions (ADR 0028) act only in the waiting
    /// variant; elsewhere they are left out so that the other configurations
    /// and the freeze and re-entry mutation runs fuzz the same actions as
    /// before. The two scenario actions run on the production builds and on
    /// the mutation builds they target: failThenRelease on the build without
    /// the bond-level freeze, waitThenRelease on the waiting-release and
    /// release-clock builds. Without them each mutation run found its
    /// violation only with some fuzz seeds (one campaign in eight to one in
    /// four ended without it).
    function excludeSelectors() public view returns (FuzzSelector[] memory excluded) {
        bool failAction = build == Inv.BUILD_REAL || build == Inv.BUILD_NO_FREEZE || build == Inv.BUILD_WIDE_FREEZE;
        bool waitAction = build == Inv.BUILD_REAL || build == Inv.BUILD_WAIT_RELEASE || build == Inv.BUILD_PAUSE_IGNORED
            || build == Inv.BUILD_WIDE_FREEZE;
        bytes4[] memory selectors = new bytes4[](4);
        uint256 k;
        if (!waitingVariant) {
            selectors[k++] = LifecycleHandler.redraw.selector;
            selectors[k++] = LifecycleHandler.refillVerifiers.selector;
        }
        if (!failAction) selectors[k++] = LifecycleHandler.failThenRelease.selector;
        if (!waitAction) selectors[k++] = LifecycleHandler.waitThenRelease.selector;
        if (k == 0) return excluded;
        assembly ("memory-safe") {
            mstore(selectors, k)
        }
        excluded = new FuzzSelector[](1);
        excluded[0] = FuzzSelector(address(handler), selectors);
    }

    function _none(uint8 category) internal view {
        require(obs.violations(category) == 0, obs.firstViolation(category));
    }

    function _holds(bool ok, string memory why) internal pure {
        require(ok, why);
    }
}

/// Stateful invariants over settlement, sampling, disputes, serve and
/// publication, judgment, appeal and recheck, evidence, the bond-level freeze,
/// frozen-pool claims, forfeiture, release, suspension, reinstatement and the
/// sanction, across two bond accounts of which one carries several seller
/// registrations.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = true
contract LifecycleInvariantTest is LifecycleSetup {
    function setUp() public virtual {
        _setUp(Inv.BUILD_REAL);
    }

    /// Every timed call (anchor, timeoutAnchor, seal, timeoutSeal, dispute,
    /// judge, timeoutJudge, appeal, finalizeCase, sealReviewRandomness,
    /// openAutoRecheck, evidence request, disclosure and timeout, served,
    /// accept, escalate, finalizeServed, publish, timeoutServe, the buyer
    /// recovery calls, frozen claims and forfeitUnclaimed) succeeds only
    /// inside its window: at the deadline block for timely calls, after it for
    /// timeouts.
    function invariant_deadlineWindows() public view {
        _none(Inv.C_DEADLINE);
    }

    /// A timely call whose other preconditions hold does not revert, so every
    /// nonterminal state keeps a bounded path to a terminal state (inv. 12).
    function invariant_timelyCallsSucceed() public view {
        _none(Inv.C_LIVENESS);
    }

    /// No deferred principal is released before its case ended, while its
    /// entry is frozen, before the release conditions, for a sampled entry
    /// whose case was never opened, while its case waits for an assignment,
    /// or before deferBlocks blocks in which no case of its account waited
    /// (inv. 18, 27, ADR 0028, ADR 0029).
    function invariant_noReleaseBeforeCaseEndOrWhileFrozen() public view {
        _none(Inv.C_RELEASE);
    }

    /// The release clock of every bond account stops exactly in the blocks in
    /// which one of its sampled cases waits for an assignment: its waiting
    /// count and paused blocks equal the model, also since each settlement
    /// (design 2 rule D2-21, ADR 0029). The release invariant above checks
    /// that no entry is released before deferBlocks unpaused blocks.
    function invariant_releaseClockStopsWhileACaseWaits() public view {
        _none(Inv.C_PAUSE);
    }

    /// No verifier is assigned twice to one case, an unsampled purchase never
    /// opens a sampled case, no assignment precedes the epoch seal, and an
    /// initial INCONCLUSIVE has no appellant (inv. 6, 4).
    function invariant_noVerifierReparticipation() public view {
        (bool ok, string memory why) = obs.checkParticipation();
        _holds(ok, why);
        _none(Inv.C_CASE);
    }

    /// deferred + refunded + released + forfeited = settled for every bond
    /// account, where deferred includes held, refundable and frozen entries;
    /// released, refunded and forfeited are exclusive and final (inv. 9, 19).
    function invariant_deferredLedgerConservation() public view {
        (bool ok, string memory why) = obs.checkLedger();
        _holds(ok, why);
        _none(Inv.C_TERMINAL);
    }

    /// Every registration of a bond account reads one bucket equal to an
    /// independent model of refill, consumption and rescaling; registrations
    /// never change bond and adding one leaves the level unchanged (inv. 23, 24).
    function invariant_bondBucketAcrossSellers() public view {
        (bool ok, string memory why) = obs.checkBucket();
        _holds(ok, why);
        _none(Inv.C_BUCKET);
    }

    /// Suspension only follows a failure or initial FAIL of the seller itself;
    /// reactivation only by reinstatement or by the overturn of the freeze
    /// that suspended it; SANCTIONED is absorbing and reached only at the
    /// failure limit; the bond is slashed once; failure, judged and
    /// inconclusive counters equal an independent model, so a protocol
    /// INCONCLUSIVE changes none of them (inv. 11, 25, 26).
    function invariant_suspensionReinstatementSanctionOrdering() public view {
        (bool ok, string memory why) = obs.checkCounters();
        _holds(ok, why);
        _none(Inv.C_STATUS);
        _none(Inv.C_COUNTERS);
    }

    /// Every forfeiture and every per-failure deduction stays locked in the
    /// contract, nothing reaches the verifier pool and the treasury receives
    /// only verifier penalties (ADR 0022); a forfeiture equals the entries it
    /// forfeits (the frozen window only, never an entry settled after a
    /// reinstatement), and an overturned freeze forfeits nothing (inv. 21, 22).
    function invariant_forfeitSplit() public view {
        _none(Inv.C_FORFEIT);
    }

    /// Frozen-pool claims pay exactly the entry amount, only for entries of the
    /// frozen window with a valid receipt of the purchase's seller (inv. 19, 20).
    function invariant_frozenPoolClaims() public view {
        _none(Inv.C_CLAIM);
    }

    /// Negative invariant of the freeze: no principal settled at or before a
    /// final seller failure of a bond account is ever released to the seller,
    /// including purchases settled after a reinstatement during an open claim
    /// window and before the next confirmed failure (ADR 0021).
    /// FreezeMutationInvariantTest and ReentryMutationInvariantTest run the
    /// same check on the two mutation builds.
    function invariant_frozenPrincipalNeverReachesFailingSeller() public view {
        _none(Inv.C_LEAK);
    }

    /// A seller-appealed review against an initial FAIL, including the
    /// tiebreak it leads to, that cannot progress (both review seals lapse, the
    /// last assignment times out, or the search is exhausted) upholds the
    /// initial FAIL and never ends as a protocol INCONCLUSIVE (rule D2-15,
    /// ADR 0024).
    function invariant_stalledSellerAppealUpholdsTheFail() public view {
        _none(Inv.C_APPEAL);
    }

    /// Verifier liability and penalty reserves equal the unreleased
    /// assignments, and each assignment fit its verifier's liability room in
    /// the checkpoint of the epoch (inv. 8 as decision 126 changes it, ADR 0025).
    function invariant_verifierLiability() public view {
        (bool ok, string memory why) = obs.checkLiability();
        _holds(ok, why);
    }
}

/// Every invariant above with verifiers that open without room for one case
/// (ADR 0028): each initial search of a sample case on the first checkpoint
/// is exhausted and the case waits; refillVerifiers tops up verifiers and
/// writes newer checkpoints, and a redraw assigns on the first one after the
/// case's last search. Buyer disputes and review stages keep ending
/// INCONCLUSIVE (or upholding a seller-appealed FAIL) when exhausted.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = true
contract WaitingAssignmentInvariantTest is LifecycleInvariantTest {
    function setUp() public override {
        _setUp(Inv.BUILD_REAL, true);
    }
}

/// The release invariant on the mutation build in which a waiting case does
/// not hold its purchase (WaitRelease.sol). It is expected to FAIL: the
/// fuzzer releases the purchase of a waiting case to the seller. Skipped
/// unless FAIRBIND_WAIT_MUTATION=1; run.sh runs it and requires the failure.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract WaitReleaseMutationInvariantTest is LifecycleSetup {
    function setUp() public {
        if (!Inv.vm.envOr("FAIRBIND_WAIT_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_WAIT_RELEASE, true);
    }

    function invariant_noReleaseBeforeCaseEndOrWhileFrozen() public view {
        _none(Inv.C_RELEASE);
    }
}

/// The release invariant on the mutation build in which release ignores the
/// stopped clock (PauseIgnored.sol), with verifiers that open without room.
/// It is expected to FAIL: the fuzzer releases an entry of an account one of
/// whose cases waited, before deferBlocks unpaused blocks since its
/// settlement. Skipped unless FAIRBIND_PAUSE_MUTATION=1; run.sh runs it and
/// requires the failure.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract PauseIgnoredMutationInvariantTest is LifecycleSetup {
    function setUp() public {
        if (!Inv.vm.envOr("FAIRBIND_PAUSE_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_PAUSE_IGNORED, true);
    }

    function invariant_noReleaseBeforeCaseEndOrWhileFrozen() public view {
        _none(Inv.C_RELEASE);
    }
}

/// The negative invariant on the mutation build without the bond-level freeze
/// (FreezeDisabled.sol). It is expected to FAIL: the fuzzer finds a sequence
/// in which a failing seller receives the principal of an unsampled purchase
/// settled before its failure. Skipped unless FAIRBIND_MUTATION=1 so that the
/// default run stays green; run.sh runs it and requires the failure.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract FreezeMutationInvariantTest is LifecycleSetup {
    function setUp() public {
        if (!Inv.vm.envOr("FAIRBIND_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_NO_FREEZE);
    }

    function invariant_frozenPrincipalNeverReachesFailingSeller() public view {
        _none(Inv.C_LEAK);
    }
}

/// The same negative invariant on the re-entry mutation build
/// (ReentryMutation.sol), in which _freeze keeps its old early return while
/// the claim window is open. It is expected to FAIL: a seller reinstated
/// during its claim window sells, a second confirmed failure leaves those
/// purchases outside the frozen window, and one is released to the failing
/// seller. Skipped unless FAIRBIND_REENTRY_MUTATION=1; run.sh runs it and
/// requires the failure.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract ReentryMutationInvariantTest is LifecycleSetup {
    function setUp() public {
        if (!Inv.vm.envOr("FAIRBIND_REENTRY_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_FREEZE_KEPT);
    }

    function invariant_frozenPrincipalNeverReachesFailingSeller() public view {
        _none(Inv.C_LEAK);
    }
}
