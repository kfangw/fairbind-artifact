// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../../src/FairBindCore.sol";
import { FairBind } from "../../src/FairBind.sol";
import { ReproBase } from "../repro/ReproBase.sol";
import { MockEIP3009Token } from "../MockEIP3009Token.sol";

/// Shared setup of the review checks of ADR 0024 (design 2 rules, second edition).
abstract contract D2CheckBase is ReproBase {
    uint32 internal constant P0 = 400_000;
    uint96 internal constant CAP_SMALL = 100_000;
    uint96 internal constant CAP_MID = 200_000;
    uint96 internal constant CAP_LARGE = 1_000_000;
    uint256 internal constant B_SMALL = 370_371;
    uint256 internal constant B_LARGE = 3_703_704;
    uint8 internal constant TIER_10 = 0;
    uint8 internal constant TIER_BASE = 5;
    uint256 internal constant G = 10_000;
    uint256 internal constant DEPOSIT = 5_000_000;

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
        p.recheckPpm = 0;
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

    function _deployD2(FairBindCore.ServiceProfileInput memory p, bool withTerms) internal {
        token = new MockEIP3009Token();
        token.setVerifySignatures(true);
        fairbind = deployFairBind(address(token), address(this), address(0xA11CE), TREASURY);
        fairbind.createDeadlineConfig(1, FairBindCore.DeadlineConfig(100, 200, 200, 60, 1800, 300, 600, 300, 1800));
        fairbind.createServiceProfile(PROFILE, p);
        if (withTerms) _setProfileTerms(PROFILE, P0, _caps(), _tiers());
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

    function _anchorAndSeal(bytes32[] memory ns, bytes32 beacon) internal {
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(ns.length), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, beacon);
        fairbind.seal(sellerId, 0);
    }

    function _deliveredDispute(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory none;
        hv.roll(100);
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.NON_DELIVERY), none, "");
        hv.prank(SELLER_OWNER);
        fairbind.served(n, keccak256("bundle"));
        hv.prank(buyer);
        fairbind.acceptServe(n);
    }
}

/// Each test pins one behaviour of the branch as it is, including the gaps
/// the review reports.
contract D2ContractCheckTest is D2CheckBase {
    // ------------------------------------------------- setProfileTerms gap

    /// Review 2-1, closed by ADR 0025. setProfileTerms used to check only that
    /// the profile was inactive now: terms fixed on a deactivated profile
    /// turned an account opened with registerBond into a tiered account with
    /// cap zero, whose confirmed failure reverted with a division by zero. A
    /// profile that was ever active now refuses terms, and the account's
    /// missed anchor is recorded as usual.
    function test_rv_termsOnAPreviouslyActiveProfileAreRefused() public {
        _deployD2(_profileD2(), false);
        hv.startPrank(SELLER_OWNER);
        bondId = fairbind.registerBond(PROFILE, uint128(87 * B_LARGE));
        sellerId = fairbind.registerSeller(bondId, PROFILE, hv.addr(SELLER_KEY), CLAIMS);
        hv.stopPrank();
        hv.roll(10);
        _purchase(CAP_SMALL);
        uint24 epoch = fairbind.quoteSeller(sellerId).currentEpoch;
        fairbind.setServiceProfileActive(PROFILE, false);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        _setProfileTerms(PROFILE, P0, _caps(), _tiers());
        fairbind.setServiceProfileActive(PROFILE, true);
        require(fairbind.unitBond(bondId) == 87 * B_LARGE, "unit bond of the profile");
        hv.roll(1_000);
        fairbind.timeoutAnchor(sellerId, epoch);
        FairBindCore.BondView memory b = fairbind.getBond(bondId);
        require(b.failureCount == 1 && b.balance == 87 * B_LARGE - B_LARGE, "recorded and deducted");
    }

    // ------------------------------------------------------- D2-14 attacks

    /// Rule review attack A8/A9: sell small purchases under cap 1, lower the
    /// cap to 0.1. The sampling rates stay those of cap 1, the unit bond and
    /// the deduction stay b(1) for retentionBlocks.
    function test_rv_loweringTheCapAfterSmallSalesKeepsTheOldDeduction() public {
        _deployD2(_profileD2(), true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        hv.roll(10);
        bytes32 first = _purchase(10_000);
        for (uint256 i; i < 99; i++) _purchase(10_000);
        uint24 epoch = fairbind.quoteSeller(sellerId).currentEpoch;
        _setTerms(CAP_SMALL, TIER_BASE);
        require(fairbind.getSettledSamplePpm(first) == 10_000, "rate fixed under cap 1");
        require(fairbind.unitBond(bondId) == 87 * B_LARGE, "unit bond at V* = 1");
        hv.roll(1_000);
        fairbind.timeoutAnchor(sellerId, epoch);
        require(fairbind.getBond(bondId).balance == 86 * B_LARGE, "deducts b(1)");
        // A lower tier on top of the lower cap still needs k * b(V*) with V* = 1.
        _setTerms(CAP_SMALL, TIER_10);
        require(fairbind.unitBond(bondId) == 5 * B_LARGE, "k(10) * b(1)");
        hv.roll(10 + 31_073 + 1);
        require(fairbind.unitBond(bondId) == 5 * B_SMALL, "V* expires after the hold period");
    }

    /// Lowering the cap does not lower the balance a frozen account needs to
    /// re-enter while V* holds the old cap.
    function test_rv_loweringTheCapDoesNotDodgeTheReentryBalance() public {
        _deployD2(_profileD2(), true);
        _register(5 * B_LARGE, CAP_LARGE, TIER_10);
        hv.roll(10);
        _purchase(CAP_LARGE);
        uint24 epoch = fairbind.quoteSeller(sellerId).currentEpoch;
        hv.roll(1_000);
        fairbind.timeoutAnchor(sellerId, epoch);
        require(fairbind.getBond(bondId).balance == 4 * B_LARGE, "one b deducted");
        hv.prank(SELLER_OWNER);
        hv.expectRevert(FairBindCore.InsufficientSellerBond.selector);
        fairbind.setBondTerms(bondId, CAP_SMALL, TIER_10);
    }

    /// The new terms apply from the transaction that sets them, so a
    /// settlement later in the same block uses the new cap. Rule D2-14 (b)
    /// and (c) of the third edition say the same (review 3-7 closed in the
    /// rules, not in the contract).
    function test_rv_newCapAppliesInTheSameBlock() public {
        _deployD2(_profileD2(), true);
        _register(87 * B_LARGE, CAP_SMALL, TIER_BASE);
        hv.roll(10);
        _setTerms(CAP_LARGE, TIER_BASE);
        bytes32 n = _purchase(CAP_LARGE);
        require(fairbind.getPurchase(n).settledBlock == 10, "same block");
        require(fairbind.getSettledSamplePpm(n) == 1_000_000, "new cap in the change block");
    }

    // ---------------------------------------------------- D2-6 (b), tiered

    function test_rv_inconclusiveAboveThresholdUnderTiersNeitherCountsNorDeducts() public {
        FairBindCore.ServiceProfileInput memory p = _profileD2();
        p.maxInconclusivePpm = 1;
        p.minJudgedCount = 1;
        _deployD2(p, true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        hv.roll(10);
        bytes32 n = _purchase(CAP_LARGE);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(n);
        _judge(n, uint8(FairBindCore.Verdict.INCONCLUSIVE));
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        uint256 locked = fairbind.getLockedForfeit();
        fairbind.finalizeCase(n);
        FairBindCore.BondView memory b = fairbind.getBond(bondId);
        require(b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "frozen");
        require(b.failureCount == 0 && b.balance == 87 * B_LARGE, "not counted, not deducted");
        require(fairbind.getLockedForfeit() == locked, "nothing locked");
    }

    // ----------------------------------------------- D2-11, D2-17 checks

    function _deliveredAndSealed() internal returns (bytes32 n) {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        n = _purchase(G);
        _deliveredDispute(n);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
    }

    /// A delivered dispute opens its sample case once; neither a second
    /// openSample nor a wrong-delivery dispute can reopen the record.
    function test_rv_deliveredDisputeOpensItsSampleCaseOnce() public {
        bytes32 n = _deliveredAndSealed();
        fairbind.openSample(n);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.openSample(n);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        _judge(n, uint8(FairBindCore.Verdict.PASS));
        uint64 rb = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.finalizeCase(n);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.openSample(n);
    }

    /// A wrong-delivery dispute opened on the delivered record before
    /// openSample takes the record: the sample case never opens and the
    /// purchase is judged as a party dispute instead.
    function test_rv_wrongDeliveryDisputeTakesTheDeliveredRecordFirst() public {
        bytes32 n = _deliveredAndSealed();
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.openSample(n);
        require(fairbind.getCase(n).trigger == uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), "party dispute");
    }

    /// A sample case opened on a delivered dispute that ends UNSERVED refunds
    /// the buyer its payment and its dispute deposit (rule R94: the ladder's
    /// deposit follows the sample case).
    function test_rv_deliveredSampleCaseUnservedRefundsPaymentAndDeposit() public {
        bytes32 n = _deliveredAndSealed();
        fairbind.openSample(n);
        hv.roll(uint256(fairbind.getSampleReceiptDue(n)) + 1);
        fairbind.timeoutSampleReceipt(n);
        uint256 before = token.balanceOf(buyer);
        fairbind.claimRefund(n);
        require(token.balanceOf(buyer) - before == G + DEPOSIT, "payment and deposit");
    }

    /// A valid receipt and proof carried by a verdict after the receipt
    /// deadline (still inside the judgment window) do not clear it: the case
    /// ends UNSERVED in the same call (ADR 0025; before, it waited for
    /// timeoutSampleReceipt and raced finalizeCase).
    function test_rv_verdictAfterTheReceiptDeadlineEndsUnserved() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(n);
        uint64 due = fairbind.getSampleReceiptDue(n);
        hv.roll(uint256(due) + 1);
        require(block.number <= fairbind.getCase(n).judgeDue, "inside the judgment window");
        _judge(n, uint8(FairBindCore.Verdict.PASS));
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.UNSERVED), "unserved");
        require(fairbind.getSampleReceiptDue(n) == 0, "deadline consumed");
        require(fairbind.getBond(fairbind.getSeller(sellerId).bondId).failureCount == 1, "counted");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.timeoutSampleReceipt(n);
    }

    // ------------------------------------------------ review reseal (closed)

    /// Rule review 2-1, closed by ADR 0025: the first lapsed review seal keeps
    /// randomBlock, so the reopened seal draws from the same value.
    function test_rv_reopenedReviewSealKeepsRandomBlock() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32 n = _purchase(G);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(n);
        _judge(n, uint8(FairBindCore.Verdict.FAIL));
        token.mint(SELLER_OWNER, DEPOSIT);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        uint64 before = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(before) + 201);
        fairbind.finalizeCase(n);
        uint64 afterReseal = fairbind.getCase(n).randomBlock;
        require(afterReseal == before, "randomBlock kept");
        require(fairbind.getReviewReseals(n) != 0, "seal reopened");
        _log("review randomBlock before", before);
        _log("review randomBlock after reseal", afterReseal);
    }
}

/// Accounts walked through the case calls once each, for the gas report
/// (forge test --match-test test_rv_gasProbe... --gas-report).
contract D2GasProbeTest is D2CheckBase {
    function test_rv_gasProbeTiered() public {
        _deployD2(_profileD2(), true);
        _register(87 * B_LARGE, CAP_LARGE, TIER_BASE);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](4);
        for (uint256 i; i < 4; i++) ns[i] = _purchase(CAP_LARGE);
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(ns[0]);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[0]);
        fairbind.submitSampleReceipt(ns[0], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[0]));
        _judge(ns[0], uint8(FairBindCore.Verdict.PASS));
        uint64 rb = fairbind.getCase(ns[0]).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.finalizeCase(ns[0]);
        hv.roll(50_000);
        fairbind.releasePurchase(ns[0]);
        _setTerms(CAP_SMALL, TIER_BASE);
        fairbind.openSample(ns[1]);
        hv.roll(uint256(fairbind.getSampleReceiptDue(ns[1])) + 1);
        fairbind.timeoutSampleReceipt(ns[1]);
    }

    /// The same walk without terms (constant samplePpm = PPM), and the
    /// opening of a sample case on a delivered dispute.
    function test_rv_gasProbeUntiered() public {
        FairBindCore.ServiceProfileInput memory p = _productionProfile();
        p.samplePpm = 1_000_000;
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](4);
        for (uint256 i; i < 4; i++) ns[i] = _purchase(G);
        _deliveredDispute(ns[2]);
        _anchorAndSeal(ns, keccak256("beacon"));
        fairbind.openSample(ns[0]);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[0]);
        fairbind.submitSampleReceipt(ns[0], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[0]));
        _judge(ns[0], uint8(FairBindCore.Verdict.PASS));
        uint64 rb = fairbind.getCase(ns[0]).randomBlock;
        hv.roll(uint256(rb) + 1);
        hv.setBlockhash(rb, keccak256("candidate"));
        fairbind.finalizeCase(ns[0]);
        hv.roll(50_000);
        fairbind.releasePurchase(ns[0]);
        uint256 g = gasleft();
        fairbind.openSample(ns[2]);
        _log("gasleft delta: openSample on a delivered dispute", g - gasleft());
        g = gasleft();
        fairbind.openSample(ns[1]);
        _log("gasleft delta: openSample, no prior case", g - gasleft());
        hv.roll(uint256(fairbind.getSampleReceiptDue(ns[1])) + 1);
        fairbind.timeoutSampleReceipt(ns[1]);
    }
}
