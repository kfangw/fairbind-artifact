// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { Inv } from "./InvariantBase.sol";
import { LifecycleInvariantTest } from "./LifecycleInvariants.t.sol";
// Inv.deployWide loads these by artifact name.
import {
    WideFreezeSettlement,
    WideFreezeSampling,
    WideFreezeDelivery,
    WideFreezePublication,
    WideFreezeRecovery,
    WideFreezeJudgment,
    WideFreezeReview,
    WideFreezeBond
} from "./WideFreeze.sol";

/// Every invariant of the suite on the wide-freeze mutation build
/// (WideFreeze.sol), whose freeze starts at block zero instead of the
/// settlement block of the failing sale (ADR 0030). It must FAIL: an entry
/// settled before the failing sale is refused at release, claimable or
/// forfeited. Before the suite checked both sides of the window it passed
/// (2026-10-22, 128 runs, both variants). The observer now flags an entry
/// settled before the start c of a confirmed failure that reads frozen
/// without a model window holding it, and the handler reads release refusal,
/// frozen claims and itemized forfeiture from the observer's windows, not the
/// contract's spans. With that, both variants failed invariant_forfeitSplit,
/// invariant_suspensionReinstatementSanctionOrdering ("before the start") and
/// invariant_timelyCallsSucceed (FrozenEntry). run.sh step 7.
/// Skipped unless FAIRBIND_WIDE_FREEZE_MUTATION=1.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract WideFreezeMutationInvariantTest is LifecycleInvariantTest {
    function setUp() public override {
        if (!Inv.vm.envOr("FAIRBIND_WIDE_FREEZE_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_WIDE_FREEZE);
    }
}

/// The same on the waiting-assignment variant (ADR 0028), in which a later
/// sale's case can wait when an earlier sale fails.
/// forge-config: default.invariant.runs = 128
/// forge-config: default.invariant.depth = 64
/// forge-config: default.invariant.fail-on-revert = false
contract WideFreezeWaitingMutationInvariantTest is LifecycleInvariantTest {
    function setUp() public override {
        if (!Inv.vm.envOr("FAIRBIND_WIDE_FREEZE_MUTATION", false)) Inv.vm.skip(true);
        _setUp(Inv.BUILD_WIDE_FREEZE, true);
    }
}
