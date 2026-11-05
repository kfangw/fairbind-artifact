// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindDesign2 } from "../src/FairBindDesign2.sol";
import { ReproBase } from "./repro/ReproBase.sol";
import { MockEIP3009Token } from "./MockEIP3009Token.sol";

/// Value-proportional sampling with seller-chosen value caps and sales tiers
/// (ADR 0024, design 2 rules D2-1 to D2-5, D2-7, D2-13 and D2-14). The profile
/// is the data API reference case: hold period 31,073 blocks, failure window
/// 31,073 blocks, so every tier admits at most S settlements in any interval
/// of 62,146 blocks. Tier values are those of the rules' table at w = 0.015.
contract Design2TermsTest is ReproBase {
    uint32 internal constant P0 = 400_000;
    uint96 internal constant CAP_SMALL = 100_000;
    uint96 internal constant CAP_MID = 200_000;
    uint96 internal constant CAP_LARGE = 1_000_000;
    uint256 internal constant B_SMALL = 370_371;
    uint256 internal constant B_MID = 740_741;
    uint256 internal constant B_LARGE = 3_703_704;
    uint256 internal constant SPAN = 62_146;
    uint8 internal constant TIER_10 = 0;
    uint8 internal constant TIER_30 = 1;
    uint8 internal constant TIER_100 = 2;
    uint8 internal constant TIER_BASE = 5;

    uint32 internal bondId;

    function _tiers() internal pure returns (FairBindCore.SalesTier[] memory t) {
        t = new FairBindCore.SalesTier[](6);
        t[0] = FairBindCore.SalesTier(10, 1, 144, 5, 5);
        t[1] = FairBindCore.SalesTier(30, 1, 466, 7, 7);
        t[2] = FairBindCore.SalesTier(100, 4, 1_544, 11, 11);
        t[3] = FairBindCore.SalesTier(300, 13, 4_618, 19, 19);
        t[4] = FairBindCore.SalesTier(1_000, 42, 15_415, 38, 38);
        t[5] = FairBindCore.SalesTier(3_245, 137, 50_000, 87, 87);
    }

    function _caps() internal pure returns (uint96[] memory c) {
        c = new uint96[](3);
        c[0] = CAP_SMALL;
        c[1] = CAP_MID;
        c[2] = CAP_LARGE;
    }

    function _profileD2() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.effectivePpm = P0;
        p.recheckPpm = 200_000;
        p.bucketCapacity = 137;
        p.refillPpmPerBlock = 50_000;
        p.maxRatePpmPerBlock = 60_000;
        p.enforcementBlocks = 31_073;
        p.deferBlocks = 31_073;
        p.retentionBlocks = 31_073;
        p.claimWindowBlocks = 31_073;
        p.failureWindowBlocks = 31_073;
        p.inconclusiveWindowBlocks = 31_073;
        p.maxPurchaseValue = CAP_LARGE;
        p.maxBadGain = CAP_LARGE;
        p.failureLimit = 87;
        p.sellerPenalty = uint96(87 * B_LARGE);
        p.verifierBondCap = 1_000_000_000;
    }

    /// Deploys the data API deadlines, the design 2 profile with its terms
    /// (unless `withTerms` is false) and fourteen verifiers, and funds the
    /// seller owner and the buyer.
    function _deployD2(bool withTerms) internal {
        _deployD2With(_profileD2(), withTerms ? _tiers() : new FairBindCore.SalesTier[](0));
    }

    /// The B = b configuration of decision 131 (ADR 0027): the rules' tiers
    /// with one prefunded failure (failureLimit = 1, unit bond b) and no
    /// sanction limit (sanctionLimit = 0).
    function _unitTiers() internal pure returns (FairBindCore.SalesTier[] memory t) {
        t = _tiers();
        for (uint256 i; i < t.length; i++) {
            t[i].failureLimit = 1;
            t[i].sanctionLimit = 0;
        }
    }

    function _profileUnit() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _profileD2();
        p.failureLimit = 1;
        p.sellerPenalty = uint96(B_LARGE);
    }

    /// Deploys with the given profile and tiers; no tiers means no terms.
    function _deployD2With(FairBindCore.ServiceProfileInput memory p, FairBindCore.SalesTier[] memory tiers) internal {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 1800));
        fairbind.createServiceProfile(PROFILE, p);
        require(fairbind.judgmentDelayBlocks(PROFILE) == 30_573, "data API L_F");
        if (tiers.length != 0) _setProfileTerms(PROFILE, P0, _caps(), tiers);
        token.mint(address(this), 1_000_000_000);
        token.approve(address(fairbind), type(uint256).max);
        for (uint32 i = 1; i <= 14; i++) {
            fairbind.registerVerifier(uint256(1) << 1, hv.addr(1000 + i), 50_000_000);
        }
        fairbind.checkpointVerifierTree(PROFILE);
        fairbind.setServiceProfileActive(PROFILE, true);
        token.mint(SELLER_OWNER, 10_000_000_000);
        hv.prank(SELLER_OWNER);
        token.approve(address(fairbind), type(uint256).max);
        buyer = hv.addr(BUYER_KEY);
        token.mint(buyer, 1_000_000_000);
        hv.prank(buyer);
        token.approve(address(fairbind), type(uint256).max);
    }

    function _register(uint256 amount, uint96 cap, uint8 tier) internal {
        hv.startPrank(SELLER_OWNER);
        bondId = fairbind.registerBondWithTerms(PROFILE, uint128(amount), cap, tier);
        sellerId = fairbind.registerSeller(bondId, PROFILE, hv.addr(SELLER_KEY), CLAIMS);
        hv.stopPrank();
    }

    function _setTerms(uint96 cap, uint8 tier) internal {
        hv.prank(SELLER_OWNER);
        fairbind.setBondTerms(bondId, cap, tier);
    }

    function _topUp(uint256 amount) internal {
        hv.prank(SELLER_OWNER);
        fairbind.topUpBond(bondId, uint128(amount));
    }

    function _limit(uint8 tier) internal pure returns (uint256) {
        return _tiers()[tier].failureLimit;
    }

    // ------------------------------------------------------ integer rules

    /// The sampling rate, the threshold and the deduction equal the values of
    /// experiments/replay/design2.py (s_ppm, threshold_ceil) and of rule D2-5.
    function test_integerRulesMatchTheReplayEngine() public pure {
        require(FairBindDesign2.samplePpm(1, CAP_SMALL) == 10, "one unit at 0.1");
        require(FairBindDesign2.samplePpm(1, CAP_MID) == 5, "one unit at 0.2");
        require(FairBindDesign2.samplePpm(1, CAP_LARGE) == 1, "one unit at 1");
        require(FairBindDesign2.samplePpm(33_333, CAP_SMALL) == 333_330, "a third at 0.1");
        require(FairBindDesign2.samplePpm(199_999, CAP_MID) == 999_995, "just below 0.2");
        require(FairBindDesign2.samplePpm(CAP_LARGE, CAP_LARGE) == 1_000_000, "at the cap");
        require(FairBindDesign2.threshold(1) == 0x10c6f7a0b5ed8d36b4c7f34938583621fafc8b0079a2834d26fa3fcc9eaa, "ppm 1");
        require(FairBindDesign2.threshold(5) == 0x53e2d6238da3c21187e7c06e19b90ea9e6eeb702602c9081c2e33eff1951, "ppm 5");
        require(FairBindDesign2.threshold(10) == 0xa7c5ac471b4784230fcf80dc33721d53cddd6e04c059210385c67dfe32a1, "ppm 10");
        require(FairBindDesign2.threshold(333_334) == 0x55556084a515ce9e5e2478854cdb7ae5796bfca85caafbc1acde19fc2a8869c7, "ppm 333334");
        require(FairBindDesign2.threshold(400_000) == 0x6666666666666666666666666666666666666666666666666666666666666667, "ppm 400000");
        require(FairBindDesign2.threshold(999_999) == 0xffffef39085f4a1272c94b380cb6c7a7c9de050374ff865d7cb2d905c0336157, "ppm 999999");
        // test-vectors/cryptography-v1.json selection.valueProportional.
        require(FairBindDesign2.samplePpm(66_666, CAP_MID) == 333_330, "vector rate");
        require(FairBindDesign2.threshold(333_330) == 0x55551d68c692f6e82949a5657fb69984a0e410b630a915379fa97e132b55ef20, "vector threshold");
        require(FairBindDesign2.deduction(CAP_SMALL, P0) == B_SMALL, "b at 0.1");
        require(FairBindDesign2.deduction(CAP_MID, P0) == B_MID, "b at 0.2");
        require(FairBindDesign2.deduction(CAP_LARGE, P0) == B_LARGE, "b at 1");
        // b >= v_max / p0 (rule D2-5 (c)).
        require(B_SMALL * P0 >= uint256(CAP_SMALL) * 1_000_000 && B_LARGE * P0 >= uint256(CAP_LARGE) * 1_000_000, "deterrence");
    }

    // -------------------------------------------------- profile admission

    function _profileOnly() internal returns (FairBindCore.ServiceProfileInput memory p) {
        p = _profileD2();
        token = new MockEIP3009Token();
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 1800));
        fairbind.createServiceProfile(PROFILE, p);
    }

    /// Every tier of the rules' table meets ceil(q + r * 62,146 / PPM) <= S
    /// with equality: one settlement less is refused.
    function test_profileTermsAdmitTheRulesTiersAndNoSmallerLimit() public {
        _profileOnly();
        FairBindCore.SalesTier[] memory t = _tiers();
        for (uint256 i; i < t.length; i++) {
            require((uint256(t[i].bucketCapacity) * 1_000_000 + uint256(t[i].refillPpmPerBlock) * SPAN + 999_999)
                / 1_000_000 == t[i].salesLimit, "ceil(q + r * span) = S");
            FairBindCore.SalesTier[] memory tight = _tiers();
            tight[i].salesLimit -= 1;
            hv.expectRevert(FairBindCore.InvalidProfile.selector);
            _setProfileTerms(PROFILE, P0, _caps(), tight);
        }
        _setProfileTerms(PROFILE, P0, _caps(), t);
    }

    function test_profileTermsAreCheckedAndFixedOnce() public {
        FairBindCore.ServiceProfileInput memory p = _profileOnly();
        p.samplePpm = 500_000;
        fairbind.createServiceProfile(PROFILE + 1, p);
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE + 1, P0, _caps(), _tiers());
        hv.expectRevert(FairBindCore.UnknownProfile.selector);
        _setProfileTerms(PROFILE + 2, P0, _caps(), _tiers());
        // The largest cap is the profile's purchase limit.
        uint96[] memory caps = _caps();
        caps[2] = CAP_LARGE - 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE, P0, caps, _tiers());
        // Caps strictly increase.
        caps = _caps();
        caps[1] = CAP_SMALL;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE, P0, caps, _tiers());
        // The base tier is the profile's bucket and failure limit.
        FairBindCore.SalesTier[] memory t = _tiers();
        t[5].failureLimit = 86;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE, P0, _caps(), t);
        // p0 is the profile's effectivePpm.
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        _setProfileTerms(PROFILE, P0 + 1, _caps(), _tiers());
        hv.prank(address(0xBEEF));
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        _setProfileTerms(PROFILE, P0, _caps(), _tiers());
        _setProfileTerms(PROFILE, P0, _caps(), _tiers());
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        _setProfileTerms(PROFILE, P0, _caps(), _tiers());
        FairBindCore.ProfileTerms memory stored = fairbind.getProfileTerms(PROFILE);
        require(stored.detectFloorPpm == P0 && stored.valueCaps.length == 3 && stored.tiers.length == 6, "stored");
        require(stored.tiers[2].salesLimit == 100 && stored.tiers[2].failureLimit == 11, "tier stored");
    }

    // ----------------------------------------------------- bond and terms

    /// B = k * b for every cap and tier, and floor(B / k) = b.
    function test_unitBondIsTheFailureLimitTimesTheDeduction() public {
        _deployD2(true);
        uint96[3] memory caps = [CAP_SMALL, CAP_MID, CAP_LARGE];
        uint256[3] memory bs = [B_SMALL, B_MID, B_LARGE];
        FairBindCore.SalesTier[] memory t = _tiers();
        hv.startPrank(SELLER_OWNER);
        for (uint256 c; c < 3; c++) {
            for (uint8 i; i < t.length; i++) {
                uint256 unit = uint256(t[i].failureLimit) * bs[c];
                hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
                fairbind.registerBondWithTerms(PROFILE, uint128(unit - 1), caps[c], i);
                uint32 id = fairbind.registerBondWithTerms(PROFILE, uint128(unit), caps[c], i);
                require(fairbind.unitBond(id) == unit, "B = k * b");
                require(fairbind.getBond(id).scaleFactor == 1, "one unit");
                require(fairbind.getBond(id).bucketBalancePpm == uint256(t[i].bucketCapacity) * 1_000_000, "full bucket");
            }
        }
        require(fairbind.unitBond(fairbind.registerBondWithTerms(PROFILE, uint128(87 * B_MID), CAP_MID, TIER_BASE))
            == 64_444_467, "64.44 USDC at 0.2 and S = 3,245");
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        fairbind.registerBond(PROFILE, uint128(87 * B_LARGE));
        hv.expectRevert(FairBindCore.ValueTooLarge.selector);
        fairbind.registerBondWithTerms(PROFILE, uint128(87 * B_LARGE), 300_000, TIER_BASE);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        fairbind.registerBondWithTerms(PROFILE, uint128(87 * B_LARGE), CAP_LARGE, 6);
        hv.stopPrank();
    }

    /// Rule D2-1: a settlement above the account's cap is refused before the
    /// bucket is read, so an empty bucket still reports the cap.
    function test_settlementAboveTheCapIsRefusedBeforeTheBucket() public {
        _deployD2(true);
        _register(5 * B_SMALL, CAP_SMALL, TIER_10);
        hv.roll(10);
        _purchase(CAP_SMALL);
        require(fairbind.quoteSeller(sellerId).remaining == 0, "bucket empty");
        require(fairbind.quoteSeller(sellerId).maxPurchaseValue == CAP_SMALL, "quote reports the cap");
        SettleArgs memory a = _settleArgs(uint256(CAP_SMALL) + 1);
        hv.expectRevert(FairBindCore.ValueTooLarge.selector);
        _settle(a);
        a = _settleArgs(1);
        hv.expectRevert(FairBindCore.RateLimitExceeded.selector);
        _settle(a);
    }

    /// Rules D2-2 and D2-3: each settlement records min(PPM, ceil(v * PPM /
    /// cap)) under the cap in force; at the cap a purchase is always drawn, and
    /// below it the draw compares the ledger sample value with the rounded-up
    /// threshold.
    function test_samplingRateIsProportionalAndFixedAtSettlement() public {
        _deployD2(true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        hv.roll(10);
        bytes32 full = _purchase(CAP_LARGE);
        bytes32 tenth = _purchase(100_000);
        bytes32 unit = _purchase(1);
        _setTerms(CAP_SMALL, TIER_BASE);
        bytes32 afterLowering = _purchase(100_000);
        require(fairbind.getSettledSamplePpm(full) == 1_000_000, "at the cap");
        require(fairbind.getSettledSamplePpm(tenth) == 100_000, "a tenth of the cap");
        require(fairbind.getSettledSamplePpm(unit) == 1, "one unit");
        require(fairbind.getSettledSamplePpm(afterLowering) == 1_000_000, "the cap in force at settlement");
        bytes32[] memory ns = new bytes32[](4);
        ns[0] = full;
        ns[1] = tenth;
        ns[2] = unit;
        ns[3] = afterLowering;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), 4, keccak256("publication"));
        bytes32 beacon = keccak256("design 2 beacon");
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, beacon);
        fairbind.seal(sellerId, 0);
        (bool sampled, bool known) = fairbind.isSampled(full);
        require(sampled && known, "always drawn at the cap");
        (sampled,) = fairbind.isSampled(afterLowering);
        require(sampled, "always drawn at the lowered cap");
        (sampled,) = fairbind.isSampled(tenth);
        require(sampled == (_sampleValue(beacon, tenth) < FairBindDesign2.threshold(100_000)), "ceil threshold, a tenth");
        (sampled,) = fairbind.isSampled(unit);
        require(sampled == (_sampleValue(beacon, unit) < FairBindDesign2.threshold(1)), "ceil threshold, one unit");
    }

    function _sampleValue(bytes32 randomness, bytes32 nonce) internal view returns (uint256) {
        return uint256(keccak256(abi.encode(keccak256("fairbind/sample/v1"), randomness, sellerId, uint24(0), nonce)));
    }

    /// Every purchase at the cap is drawn and opens a sample case.
    function test_purchaseAtTheCapIsAlwaysDrawn() public {
        _deployD2(true);
        _register(87 * B_MID, CAP_MID, TIER_BASE);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](8);
        for (uint256 i; i < ns.length; i++) ns[i] = _purchase(CAP_MID);
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256("any beacon"));
        fairbind.seal(sellerId, 0);
        for (uint256 i; i < ns.length; i++) {
            fairbind.openSample(ns[i]);
            require(fairbind.getCase(ns[i]).trigger == uint8(FairBindCore.CaseTrigger.SAMPLE), "opened");
        }
    }

    /// Rule D2-5: one confirmed failure deducts exactly b, and k failures in
    /// one window deduct exactly B = k * b and sanction.
    function test_eachFailureDeductsExactlyB() public {
        _deployD2(true);
        _register(5 * B_SMALL, CAP_SMALL, TIER_10);
        uint256 locked = fairbind.getLockedForfeit();
        // One purchase in each of five epochs, never anchored.
        uint24[5] memory epochs;
        for (uint256 i; i < 5; i++) {
            if (i > 0) hv.roll(block.number + 6_945);
            else hv.roll(10);
            _purchase(CAP_SMALL);
            epochs[i] = fairbind.quoteSeller(sellerId).currentEpoch;
        }
        hv.roll(block.number + 1_000);
        for (uint256 i; i < 5; i++) {
            fairbind.timeoutAnchor(sellerId, epochs[i]);
            FairBindCore.BondView memory b = fairbind.getBond(bondId);
            require(b.balance == 5 * B_SMALL - (i + 1) * B_SMALL, "b per failure");
            require(b.sanctioned == (i == 4), "sanction at k");
        }
        require(fairbind.getLockedForfeit() - locked == 5 * B_SMALL, "B locked");
    }

    /// Settles one unit whenever the bucket holds one, from a full bucket at
    /// the current block through `span` blocks, and returns the count.
    function _settleGreedily(uint256 rate, uint256 span) internal returns (uint256 count) {
        // The block is tracked in a local: the optimizer may keep block.number
        // across cheat-code rolls inside one call.
        uint256 at = fairbind.quoteSeller(sellerId).quotedAtBlock;
        uint256 end = at + span;
        while (at <= end) {
            _purchase(1);
            count++;
            uint256 level = fairbind.quoteSeller(sellerId).bucketBalancePpm;
            at += (1_000_000 - level + rate - 1) / rate;
            hv.roll(at);
        }
    }

    /// Rule D2-7: a small tier never scales with the balance and its bucket
    /// admits at most S settlements in an interval of twice the hold period;
    /// the base tier scales.
    function test_smallTierAdmitsAtMostItsLimitInAnyIntervalOfTwiceTheHold() public {
        _deployD2(true);
        _register(50 * B_SMALL, CAP_SMALL, TIER_10);
        require(fairbind.getBond(bondId).scaleFactor == 1, "no multiple for a small tier");
        hv.roll(10);
        uint256 count = _settleGreedily(144, SPAN);
        require(count <= 10, "at most S = 10");
        _log("settlements of tier S = 10 in 62,146 blocks", count);
        _topUp(2 * 87 * B_SMALL);
        require(fairbind.getBond(bondId).scaleFactor == 1, "still one unit");
        _setTerms(CAP_SMALL, TIER_BASE);
        require(fairbind.getBond(bondId).scaleFactor == 2, "the base tier scales");
    }

    function test_tierThirtyAdmitsAtMostThirty() public {
        _deployD2(true);
        _register(7 * B_SMALL, CAP_SMALL, TIER_30);
        hv.roll(10);
        uint256 count = _settleGreedily(466, SPAN);
        require(count <= 30, "at most S = 30");
        _log("settlements of tier S = 30 in 62,146 blocks", count);
    }

    // ------------------------------------------------------- rule D2-14

    /// Lowering the cap applies to the next settlement, but the unit bond and
    /// the deduction keep the old cap for the hold period.
    function test_loweringTheCapKeepsTheOldCapForTheHoldPeriod() public {
        _deployD2(true);
        _register(5 * B_LARGE, CAP_LARGE, TIER_10);
        hv.roll(10);
        _setTerms(CAP_SMALL, TIER_10);
        FairBindCore.BondTerms memory t = fairbind.getBondTerms(bondId);
        require(t.sampleScaleValue == CAP_SMALL && t.peakCap == CAP_LARGE && t.peakUntil == 10 + 31_073, "peak kept");
        require(fairbind.unitBond(bondId) == 5 * B_LARGE, "unit bond at the old cap");
        SettleArgs memory a = _settleArgs(CAP_MID);
        hv.expectRevert(FairBindCore.ValueTooLarge.selector);
        _settle(a);
        _purchase(CAP_SMALL);
        uint24 epoch = fairbind.quoteSeller(sellerId).currentEpoch;
        hv.roll(1_000);
        fairbind.timeoutAnchor(sellerId, epoch);
        require(fairbind.getBond(bondId).balance == 4 * B_LARGE, "deducts b of the old cap");
        hv.roll(10 + 31_073 + 1);
        require(fairbind.unitBond(bondId) == 5 * B_SMALL, "the old cap expires");
    }

    /// Raising the cap needs the bond at the new cap first.
    function test_raisingTheCapNeedsTheBondFirst() public {
        _deployD2(true);
        _register(5 * B_SMALL, CAP_SMALL, TIER_10);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
        fairbind.setBondTerms(bondId, CAP_LARGE, TIER_10);
        _topUp(5 * B_LARGE - 5 * B_SMALL - 1);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
        fairbind.setBondTerms(bondId, CAP_LARGE, TIER_10);
        _topUp(1);
        _setTerms(CAP_LARGE, TIER_10);
        require(fairbind.unitBond(bondId) == 5 * B_LARGE, "unit bond at the new cap");
        require(fairbind.quoteSeller(sellerId).maxPurchaseValue == CAP_LARGE, "new cap quoted");
    }

    /// At scale n a higher cap needs one unit bond at the new cap; the scale
    /// is recomputed from the balance and the drop is kept as the recent high.
    function test_raisingTheCapAtScaleNRecomputesTheScale() public {
        _deployD2(true);
        _register(2 * 87 * B_SMALL, CAP_SMALL, TIER_BASE);
        require(fairbind.getBond(bondId).scaleFactor == 2, "scale two");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
        fairbind.setBondTerms(bondId, CAP_LARGE, TIER_BASE);
        _setTerms(CAP_MID, TIER_BASE);
        require(fairbind.getBond(bondId).scaleFactor == 1, "scale recomputed");
        require(fairbind.getRecentScaleHigh(bondId).scale == 2, "drop kept as the recent high");
        _topUp(2 * 87 * B_MID - 2 * 87 * B_SMALL);
        require(fairbind.getBond(bondId).scaleFactor == 2, "scale two at the new cap");
    }

    /// Rule D2-14 (e): after a lower tier, a failure window that opens within
    /// the hold period takes the higher limit; later windows take the new one.
    function test_loweringTheTierKeepsTheHigherLimitForTheNextWindow() public {
        _deployD2(true);
        _register(11 * B_SMALL, CAP_SMALL, TIER_100);
        hv.roll(10);
        _purchase(1);
        uint24 first = fairbind.quoteSeller(sellerId).currentEpoch;
        _setTerms(CAP_SMALL, TIER_10);
        require(fairbind.unitBond(bondId) == 5 * B_SMALL, "unit bond of the new tier");
        FairBindCore.BondTerms memory t = fairbind.getBondTerms(bondId);
        require(t.peakLimit == 11 && t.peakLimitUntil == 10 + 31_073, "peak limit kept");
        hv.roll(1_000);
        fairbind.timeoutAnchor(sellerId, first);
        require(fairbind.getBondTerms(bondId).windowLimit == 11, "window opened at the higher limit");
        require(!fairbind.getBond(bondId).sanctioned, "one of eleven");
    }

    function test_onlyTheOwnerOfAnActiveAccountChangesTerms() public {
        _deployD2(true);
        _register(5 * B_SMALL, CAP_SMALL, TIER_10);
        hv.prank(buyer);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fairbind.setBondTerms(bondId, CAP_SMALL, TIER_30);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.ValueTooLarge.selector);
        fairbind.setBondTerms(bondId, 150_000, TIER_10);
        hv.prank(SELLER_OWNER);
        fairbind.requestBondExit(bondId);
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.BondNotActive.selector);
        fairbind.setBondTerms(bondId, CAP_SMALL, TIER_10);
    }

    // ------------------------------------------- B = b (decision 131, ADR 0027)

    /// With one prefunded failure and no sanction limit, a balance of b
    /// settles; each confirmed failure deducts b and suspends; a deposit of b
    /// and a reinstatement reopen the account; no number of failures in one
    /// window sanctions it.
    function test_unitBondWithoutSanctionLimitDeductsSuspendsAndReopens() public {
        _deployD2With(_profileUnit(), _unitTiers());
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
        fairbind.registerBondWithTerms(PROFILE, uint128(B_SMALL - 1), CAP_SMALL, TIER_100);
        _register(B_SMALL, CAP_SMALL, TIER_100);
        require(fairbind.unitBond(bondId) == B_SMALL, "B = b");
        require(fairbind.getBond(bondId).scaleFactor == 1, "one unit");
        uint256 locked = fairbind.getLockedForfeit();
        hv.roll(10);
        // Twelve failures in one window, more than k = 11 of the rules' table
        // for this tier, each followed by a deposit of b and a reinstatement.
        for (uint256 i; i < 12; i++) {
            _purchase(CAP_SMALL);
            uint24 epoch = fairbind.quoteSeller(sellerId).currentEpoch;
            hv.roll(block.number + 1_000);
            fairbind.timeoutAnchor(sellerId, epoch);
            FairBindCore.BondView memory b = fairbind.getBond(bondId);
            require(b.balance == 0, "b deducted");
            require(!b.sanctioned, "no sanction limit");
            require(b.failureCount == i + 1, "one window");
            require(
                fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended"
            );
            require(fairbind.getLockedForfeit() - locked == (i + 1) * B_SMALL, "b locked per failure");
            // Suspended and empty: no settlement.
            SettleArgs memory a = _settleArgs(CAP_SMALL);
            (bool ok,) = address(this).call(abi.encodeWithSelector(this.trySettle.selector, a));
            require(!ok, "no settlement while suspended");
            hv.prank(SELLER_OWNER);
            hv.expectRevert(FairBindCore.ReinstateConditionsUnmet.selector);
            fairbind.reinstateSeller(sellerId);
            _topUp(B_SMALL);
            hv.prank(SELLER_OWNER);
            fairbind.reinstateSeller(sellerId);
            require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.ACTIVE), "reopened");
            require(fairbind.getBond(bondId).scaleFactor == 1, "one unit again");
            // Settlement reopens after the block of the freeze; the bucket,
            // emptied when the scale fell to zero, refills one unit in 648 blocks.
            hv.roll(block.number + 700);
        }
        // The reopened account settles again.
        _purchase(CAP_SMALL);
    }

    function trySettle(SettleArgs memory a) external {
        _settle(a);
    }

    /// The k * b configuration is the same profile with sanctionLimit = k:
    /// the same deductions, and the k-th failure of a window sanctions.
    function test_sanctionLimitEqualToTheFailureLimitKeepsTheKConfiguration() public {
        _deployD2(true);
        FairBindCore.ProfileTerms memory stored = fairbind.getProfileTerms(PROFILE);
        for (uint256 i; i < stored.tiers.length; i++) {
            require(stored.tiers[i].sanctionLimit == stored.tiers[i].failureLimit, "sanction limit k");
        }
        _register(5 * B_SMALL, CAP_SMALL, TIER_10);
        require(fairbind.unitBond(bondId) == 5 * B_SMALL, "B = k * b");
    }
}
