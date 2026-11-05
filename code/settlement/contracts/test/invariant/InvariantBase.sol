// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS } from "../TestProfileConstants.sol";
import { FairBind } from "../../src/FairBind.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";

/// Cheatcodes used by the stateful invariant suite.
interface InvVm {
    function addr(uint256 key) external returns (address);
    function sign(uint256 key, bytes32 digest) external returns (uint8, bytes32, bytes32);
    function prank(address caller) external;
    function roll(uint256 height) external;
    function setBlockhash(uint256 height, bytes32 hash) external;
    function deployCode(string calldata artifact, bytes calldata args) external returns (address);
    function envOr(string calldata name, bool fallbackValue) external view returns (bool);
    function envOr(string calldata name, uint256 fallbackValue) external view returns (uint256);
    function skip(bool skipTest) external;
    function pauseGasMetering() external;
    function getBlockNumber() external view returns (uint256);
}

/// Shared constants, the profile and deployment of the stateful suite.
/// FairBind and its modules are deployed from their compiled artifacts so that
/// this suite does not embed their creation code. The freeze mutation build
/// replaces the judgment and review modules with the variants of
/// FreezeDisabled.sol, in which the bond-level freeze is switched off; the
/// re-entry mutation build replaces the modules that confirm failures with
/// those of ReentryMutation.sol, which keep the old early return of _freeze
/// during an open claim window (ADR 0021).
library Inv {
    InvVm internal constant vm = InvVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    uint32 internal constant PROFILE = 3;
    uint256 internal constant PPM = 1_000_000;
    address internal constant GUARDIAN = address(0xA11CE);
    address internal constant TREASURY = address(0xCAFE);
    address internal constant REWARD_POOL = address(0xB0B0);
    bytes32 internal constant CLAIMS = keccak256("claims");
    bytes32 internal constant CANON = keccak256("fairbind/http-canon/v1");
    bytes32 internal constant COMMITMENT = keccak256("commitment");
    bytes internal constant EVIDENCE = bytes("canonical evidence fixture");
    bytes internal constant RESPONSE_BODY = bytes("stateful suite response body");
    uint256 internal constant VERIFIER_KEY_BASE = 1000;
    uint256 internal constant VERIFIER_COUNT = 14;
    uint128 internal constant VERIFIER_BOND = 30_000_000;
    // Waiting-assignment variant (ADR 0028): a bond of 2 USDC leaves
    // (2 - 1) * 0.5 = 0.5 USDC of room, below one case (1.01 USDC), so every
    // initial search of the first checkpoint is exhausted; a top-up of 1.1 USDC
    // gives (3.1 - 1) * 0.5 = 1.05 USDC, one case.
    uint128 internal constant WAIT_VERIFIER_BOND = 2_000_000;
    uint128 internal constant WAIT_TOP_UP = 1_100_000;

    // Deadline configuration 1.
    uint32 internal constant ANCHOR_BLOCKS = 100;
    uint32 internal constant SEAL_BLOCKS = 200;
    uint32 internal constant OPEN_BLOCKS = 200;
    uint32 internal constant RESPONSE_BLOCKS = 60;
    uint32 internal constant CLAIM_BLOCKS = 1800;
    uint32 internal constant SERVE_BLOCKS = 300;
    uint32 internal constant JUDGE_BLOCKS = 600;
    uint32 internal constant EVIDENCE_BLOCKS = 300;
    uint32 internal constant APPEAL_BLOCKS = 600;

    // Action kinds the observer distinguishes.
    uint8 internal constant K_OTHER = 0;
    uint8 internal constant K_SETTLE = 1;
    uint8 internal constant K_RELEASE = 2;
    uint8 internal constant K_CLAIM_EPOCH = 3;
    uint8 internal constant K_REINSTATE = 4;
    uint8 internal constant K_FREEZE = 5;
    uint8 internal constant K_TOPUP = 6;
    uint8 internal constant K_TERMS = 7;

    // Builds the suite deploys.
    uint8 internal constant BUILD_REAL = 0;
    uint8 internal constant BUILD_NO_FREEZE = 1;
    uint8 internal constant BUILD_FREEZE_KEPT = 2;
    uint8 internal constant BUILD_WAIT_RELEASE = 3;
    uint8 internal constant BUILD_PAUSE_IGNORED = 4;
    uint8 internal constant BUILD_WIDE_FREEZE = 5;

    // Violation categories; each backs one invariant of the suite.
    uint8 internal constant C_DEADLINE = 0; // a timed call succeeded outside its window
    uint8 internal constant C_LIVENESS = 1; // a call whose preconditions hold reverted
    uint8 internal constant C_RELEASE = 2; // release before the case ended, while frozen, or unopened sample
    uint8 internal constant C_LEAK = 3; // principal settled before a final failure reached the seller
    uint8 internal constant C_LEDGER = 4; // deferred-ledger conservation
    uint8 internal constant C_BUCKET = 5; // shared bond bucket
    uint8 internal constant C_STATUS = 6; // suspension, reinstatement, sanction, freeze ordering
    uint8 internal constant C_FORFEIT = 7; // forfeiture amount and split
    uint8 internal constant C_TERMINAL = 8; // released, refunded, forfeited are exclusive and final
    uint8 internal constant C_CLAIM = 9; // frozen-pool claims
    uint8 internal constant C_COUNTERS = 10; // failure, judged and inconclusive counters, slash once
    uint8 internal constant C_CASE = 11; // case-path safety: sampling, appellant, reassignment
    uint8 internal constant C_APPEAL = 12; // a stalled seller appeal that does not uphold the initial FAIL
    uint8 internal constant C_PAUSE = 13; // release clock of an account differs from its waiting cases (ADR 0029)
    uint8 internal constant CATEGORIES = 14;

    // Design 2 terms of the tiered variant (FAIRBIND_TIERED=1, ADR 0025): two
    // value caps and a base tier at the profile's bucket and failure limit.
    uint96 internal constant CAP_LOW = 5_000;
    uint96 internal constant CAP_HIGH = 10_000;
    uint8 internal constant BASE_TIER = 1;
    /// b(CAP_HIGH) = ceil(40 * 10,000 * PPM / (27 * 40,000)).
    uint256 internal constant DEDUCTION_HIGH = 370_371;

    function deadlines() internal pure returns (FairBindCore.DeadlineConfig memory) {
        return FairBindCore.DeadlineConfig(
            ANCHOR_BLOCKS, SEAL_BLOCKS, OPEN_BLOCKS, RESPONSE_BLOCKS, CLAIM_BLOCKS, SERVE_BLOCKS,
            JUDGE_BLOCKS, EVIDENCE_BLOCKS, APPEAL_BLOCKS
        );
    }

    /// FAIRBIND_FREEZE_ON_INITIAL_FAIL selects the freeze timing of the suite's
    /// profile: 1 (the default) freezes at the initial FAIL on the
    /// admission-override build, 0 freezes at the confirmed failure on the
    /// production build (ADR 0020). run.sh runs both.
    /// FAIRBIND_TIERED=1 gives the suite's profile design 2 terms: every
    /// purchase at the cap is sampled, value caps CAP_LOW and CAP_HIGH, and
    /// accounts open at CAP_HIGH in the base tier, whose unit bond is the
    /// profile's sellerPenalty = failureLimit * b(CAP_HIGH). run.sh runs both.
    function tiered() internal view returns (bool) {
        return vm.envOr("FAIRBIND_TIERED", uint256(0)) != 0;
    }

    /// FAIRBIND_UNIT_BOND=1 with FAIRBIND_TIERED=1 is the B = b configuration
    /// of decision 131 (ADR 0027): every tier prefunds one failure
    /// (failureLimit = 1, unit bond b(CAP_HIGH)) and sets no sanction limit,
    /// so a failure deducts b and suspends and a top-up reopens the account.
    /// Without it the tiers use failureLimit = sanctionLimit (the k * b
    /// configuration). run.sh runs both.
    function unitBondOnly() internal view returns (bool) {
        return tiered() && vm.envOr("FAIRBIND_UNIT_BOND", uint256(0)) != 0;
    }

    /// Sanction limit per unit of scale of the suite's account; zero is none.
    function sanctionLimit() internal view returns (uint32) {
        return unitBondOnly() ? 0 : profile().failureLimit;
    }

    function caps() internal pure returns (uint96[] memory c) {
        c = new uint96[](2);
        c[0] = CAP_LOW;
        c[1] = CAP_HIGH;
    }

    /// A small tier of ten sales and the base tier, both meeting the
    /// admission check q * PPM + r * span <= S * PPM for the profile's span.
    function tiers(uint256 span) internal view returns (FairBindCore.SalesTier[] memory t) {
        t = new FairBindCore.SalesTier[](2);
        bool unit = unitBondOnly();
        t[0] = FairBindCore.SalesTier(10, 1, uint32(9 * PPM / span), 1, unit ? 0 : 1);
        t[1] = FairBindCore.SalesTier(
            uint32((4 * PPM + 50_000 * span + PPM - 1) / PPM), 4, 50_000, unit ? 1 : 2, unit ? 0 : 2
        );
    }

    function termsHash(FairBindCore.SalesTier[] memory t) internal pure returns (bytes32) {
        return keccak256(abi.encode(keccak256("fairbind/profile-terms/v1"), uint32(40_000), caps(), t));
    }

    function freezeOnInitialFail() internal view returns (bool) {
        return vm.envOr("FAIRBIND_FREEZE_ON_INITIAL_FAIL", uint256(1)) != 0;
    }

    /// The reproduction profile with half of all purchases sampled, half of
    /// initial passes and inconclusives rechecked, a small unit bucket so that
    /// the rate limit is reached, a failure limit of two, an inconclusive
    /// threshold that one FINAL(INCONCLUSIVE) can cross, and an uneven
    /// forfeiture split.
    function profile() internal view returns (FairBindCore.ServiceProfileInput memory p) {
        p.classId = 1;
        p.predicateId = keccak256("predicate");
        p.canonId = CANON;
        p.epochOrigin = 1;
        p.epochBlocks = 300;
        p.samplePpm = 500_000;
        p.effectivePpm = 40_000;
        p.recheckPpm = 500_000;
        p.bucketCapacity = 4;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 30_000;
        p.deferBlocks = 40_000;
        p.retentionBlocks = 40_000;
        p.marginBlocks = 500;
        p.maxRequestBytes = 65_536;
        p.maxResponseBytes = 65_536;
        p.maxEvidenceBytes = 131_072;
        p.maxPublicationCost = 5_000_000;
        p.maxReviewCost = 1_000_000;
        p.maxPurchaseValue = 10_000;
        p.maxBadGain = 10_000;
        p.sellerPenalty = 10_000_000;
        p.minVerifierBond = 1_000_000;
        p.verifierBondCap = 100_000_000;
        p.verifierLatePenalty = 500_000;
        p.verifierWrongPenalty = 1_000_000;
        p.disputeDeposit = 5_000_000;
        p.appealDeposit = 5_000_000;
        p.verifierExposurePpm = 500_000;
        p.maxAssignments = 3;
        p.minVerifiers = 14;
        p.strikeLimit = 3;
        p.deadlineConfigId = 1;
        p.claimWindowBlocks = p.retentionBlocks;
        p.failureLimit = unitBondOnly() ? 1 : 2;
        p.failureWindowBlocks = p.retentionBlocks;
        p.maxInconclusivePpm = 500_000;
        p.inconclusiveWindowBlocks = p.retentionBlocks;
        p.forfeitVerifierPpm = 333_333;
        p.freezeOnInitialFail = freezeOnInitialFail();
        p.minJudgedCount = 1;
        p.beaconDelayBlocks = TEST_BEACON_DELAY_BLOCKS;
        p.parameterHash = keccak256("profile");
        if (tiered()) {
            p.samplePpm = uint32(PPM);
            p.sellerPenalty = uint96(p.failureLimit * DEDUCTION_HIGH);
        }
    }

    function deploy(address token, address governance, uint8 build) internal returns (FairBind) {
        bool withoutFreeze = build == BUILD_NO_FREEZE;
        bool kept = build == BUILD_FREEZE_KEPT;
        bool waitRelease = build == BUILD_WAIT_RELEASE;
        bool pauseIgnored = build == BUILD_PAUSE_IGNORED;
        if (build == BUILD_WIDE_FREEZE) return deployWide(token, governance);
        bytes memory args = abi.encode(token, governance, GUARDIAN, TREASURY, REWARD_POOL);
        address[10] memory m;
        m[0] = freezeOnInitialFail()
            ? vm.deployCode("AdmissionOverrideRegistry.sol:AdmissionOverrideRegistry", args)
            : vm.deployCode("FairBindRegistry.sol:FairBindRegistry", args);
        m[1] = vm.deployCode("FairBindSettlement.sol:FairBindSettlement", args);
        m[2] = kept
            ? vm.deployCode("ReentryMutation.sol:FreezeKeptSampling", args)
            : waitRelease ? vm.deployCode("WaitRelease.sol:WaitReleaseSampling", args)
            : vm.deployCode("FairBindSampling.sol:FairBindSampling", args);
        m[3] = kept
            ? vm.deployCode("ReentryMutation.sol:FreezeKeptDelivery", args)
            : vm.deployCode("FairBindDelivery.sol:FairBindDelivery", args);
        m[4] = vm.deployCode("FairBindPublication.sol:FairBindPublication", args);
        m[5] = waitRelease
            ? vm.deployCode("WaitRelease.sol:WaitReleaseRecovery", args)
            : pauseIgnored ? vm.deployCode("PauseIgnored.sol:PauseIgnoredRecovery", args)
            : vm.deployCode("FairBindRecovery.sol:FairBindRecovery", args);
        m[6] = withoutFreeze
            ? vm.deployCode("FreezeDisabled.sol:NoFreezeJudgment", args)
            : kept ? vm.deployCode("ReentryMutation.sol:FreezeKeptJudgment", args)
            : vm.deployCode("FairBindJudgment.sol:FairBindJudgment", args);
        m[7] = withoutFreeze
            ? vm.deployCode("FreezeDisabled.sol:NoFreezeReview", args)
            : kept ? vm.deployCode("ReentryMutation.sol:FreezeKeptReview", args)
            : vm.deployCode("FairBindReview.sol:FairBindReview", args);
        m[8] = vm.deployCode("FairBindBond.sol:FairBindBond", args);
        m[9] = vm.deployCode("FairBindLens.sol:FairBindLens", args);
        return FairBind(
            vm.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(token, governance, GUARDIAN, TREASURY, REWARD_POOL, m)
            )
        );
    }

    /// The wide-freeze mutation build (WideFreeze.sol): every module that can
    /// confirm a failure freezes from block zero (the rule of ADR 0012).
    function deployWide(address token, address governance) internal returns (FairBind) {
        bytes memory args = abi.encode(token, governance, GUARDIAN, TREASURY, REWARD_POOL);
        address[10] memory m;
        m[0] = freezeOnInitialFail()
            ? vm.deployCode("AdmissionOverrideRegistry.sol:AdmissionOverrideRegistry", args)
            : vm.deployCode("FairBindRegistry.sol:FairBindRegistry", args);
        m[1] = vm.deployCode("WideFreeze.sol:WideFreezeSettlement", args);
        m[2] = vm.deployCode("WideFreeze.sol:WideFreezeSampling", args);
        m[3] = vm.deployCode("WideFreeze.sol:WideFreezeDelivery", args);
        m[4] = vm.deployCode("WideFreeze.sol:WideFreezePublication", args);
        m[5] = vm.deployCode("WideFreeze.sol:WideFreezeRecovery", args);
        m[6] = vm.deployCode("WideFreeze.sol:WideFreezeJudgment", args);
        m[7] = vm.deployCode("WideFreeze.sol:WideFreezeReview", args);
        m[8] = vm.deployCode("WideFreeze.sol:WideFreezeBond", args);
        m[9] = vm.deployCode("FairBindLens.sol:FairBindLens", args);
        return FairBind(
            vm.deployCode(
                "FairBind.sol:FairBind",
                abi.encode(token, governance, GUARDIAN, TREASURY, REWARD_POOL, m)
            )
        );
    }

    function toString(uint256 value) internal pure returns (string memory) {
        if (value == 0) return "0";
        uint256 digits;
        for (uint256 v = value; v != 0; v /= 10) digits++;
        bytes memory out = new bytes(digits);
        for (; value != 0; value /= 10) out[--digits] = bytes1(uint8(48 + value % 10));
        return string(out);
    }

    function hex32(bytes32 value) internal pure returns (string memory) {
        bytes memory alphabet = "0123456789abcdef";
        bytes memory out = new bytes(10);
        out[0] = "0";
        out[1] = "x";
        for (uint256 i; i < 4; i++) {
            out[2 + 2 * i] = alphabet[uint8(value[i]) >> 4];
            out[3 + 2 * i] = alphabet[uint8(value[i]) & 15];
        }
        return string(out);
    }

    function selector(bytes memory err) internal pure returns (bytes4 s) {
        if (err.length >= 4) {
            assembly {
                s := mload(add(err, 32))
            }
        }
    }
}
