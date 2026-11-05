// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBind } from "../src/FairBind.sol";
import { ReproBase } from "./repro/ReproBase.sol";

/// The production router rejects a deferral-sweep profile whose hold period is
/// below the case horizon; the admission override test build accepts it and
/// still enforces every other admission rule.
contract AdmissionOverrideTest is ReproBase {
    uint32 internal constant D = 3_000;

    function _setUpRouter(FairBind router) internal {
        router.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 600));
    }

    /// A D sweep point: every hold-period window lowered to D, below the
    /// judgment delay. It freezes at the initial FAIL, which the override
    /// build requires below the case horizon.
    function _sweepProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _baseProfile();
        p.deferBlocks = D;
        p.retentionBlocks = D;
        p.claimWindowBlocks = D;
        p.failureWindowBlocks = D;
        p.inconclusiveWindowBlocks = D;
        // The bond covers g * (ceil(1/p) + maxRate * (judgmentDelayBlocks - D)) at the
        // judgment delay of ADR 0024 (25,773 blocks for these deadlines).
        p.sellerPenalty = 20_000_000;
        p.parameterHash = keccak256("d sweep");
    }

    function test_productionRejectsAndOverrideAcceptsInadmissibleProfile() public {
        hv.roll(10);
        FairBind production = deployFairBind(address(0x1234), address(this), address(0xA11CE), TREASURY);
        FairBind overridden = deployFairBindWithAdmissionOverride(
            address(0x1234), address(this), address(0xA11CE), TREASURY, REWARD_POOL
        );
        _setUpRouter(production);
        _setUpRouter(overridden);

        // retentionBlocks and deferBlocks below the case horizon.
        FairBindCore.ServiceProfileInput memory p = _sweepProfile();
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        production.createServiceProfile(PROFILE, p);
        overridden.createServiceProfile(PROFILE, p);
        require(overridden.getServiceProfile(PROFILE).parameters.deferBlocks == D, "override admitted D");

        // The production profile itself is admitted by both builds.
        production.createServiceProfile(PROFILE, _productionProfile());
        overridden.createServiceProfile(PROFILE + 3, _productionProfile());

        // deferBlocks below retentionBlocks.
        p = _productionProfile();
        p.deferBlocks = p.retentionBlocks - 1;
        p.parameterHash = keccak256("defer below retention");
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        production.createServiceProfile(PROFILE + 1, p);
        overridden.createServiceProfile(PROFILE + 1, p);

        // enforcementBlocks below the judgment delay.
        uint256 judgment = overridden.judgmentDelayBlocks(PROFILE);
        p = _productionProfile();
        p.enforcementBlocks = uint32(judgment - 1);
        p.parameterHash = keccak256("enforcement below delay");
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        production.createServiceProfile(PROFILE + 2, p);
        overridden.createServiceProfile(PROFILE + 2, p);
    }

    function test_overrideKeepsEveryOtherAdmissionRule() public {
        hv.roll(10);
        FairBind overridden = deployFairBindWithAdmissionOverride(
            address(0x1234), address(this), address(0xA11CE), TREASURY, REWARD_POOL
        );
        _setUpRouter(overridden);
        FairBindCore.ServiceProfileInput memory p = _sweepProfile();
        p.claimWindowBlocks = D - 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
        p = _sweepProfile();
        p.beaconDelayBlocks = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
        p = _sweepProfile();
        p.failureWindowBlocks = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
        p = _sweepProfile();
        p.sellerPenalty = 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
        p = _sweepProfile();
        p.freezeOnInitialFail = false;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
        p = _sweepProfile();
        p.minJudgedCount = 0;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        overridden.createServiceProfile(PROFILE, p);
    }
}
