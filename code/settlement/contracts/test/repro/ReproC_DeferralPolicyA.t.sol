// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../../src/FairBindCore.sol";
import { ReproBase } from "./ReproBase.sol";

/// Case C: the calculating cheater of case B driven through the FairBind
/// settlement path. Every sale is defective. All sampled purchases are opened,
/// judged FAIL, finalized and refunded; every other purchase is then pushed
/// through releasePurchase after deferBlocks, and the buyers of half of them
/// present their receipts to the frozen pool.
///
/// test_C1 runs the current rule (bond-level freeze). test_C1_preFreezeRule
/// runs the same sequence on the mutation build with the freeze switched off
/// and keeps the pre-ADR 0012 expectation: unsampled cheated sales are
/// released to the seller. test_C2 records that the short enforcement window
/// the old admission rule accepted is now rejected.
///
/// Calls used: settle, anchor, seal, isSampled, openSample, judge,
/// finalizeCase, claimRefund, releasePurchase, forfeitUnclaimed.
contract ReproC_DeferralPolicyA is ReproBase {
    uint256 internal constant G = 10_000;
    uint256 internal constant LAMBDA = 5;
    uint256 internal constant DELTA_J = 100;
    uint256 internal constant N = LAMBDA * DELTA_J;

    struct Outcome {
        uint256 sampled;
        uint256 refunded;
        uint256 released;
        uint256 releaseReverts;
        uint256 releasedAmount;
        uint256 claimed;
        uint256 forfeited;
        uint256 penalty;
        uint256 heldAtSettle;
        uint256 ownerDeltaAtSettle;
        int256 sellerNet;
        uint256 buyerUnrecovered;
    }

    function _profileFor(uint32 enforcement) internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _baseProfile();
        p.samplePpm = 200_000;
        p.effectivePpm = 200_000;
        p.recheckPpm = 0;
        p.bucketCapacity = 5;
        p.refillPpmPerBlock = 5_000_000;
        // Smallest maxRate the bucket inequality admits for this enforcement window.
        p.maxRatePpmPerBlock = uint32(
            (uint256(p.bucketCapacity) * PPM + uint256(p.refillPpmPerBlock) * enforcement
                    + enforcement - 1) / enforcement
        );
        p.enforcementBlocks = enforcement;
        // Small review costs so that every sampled case can hold a verifier at once.
        p.maxPublicationCost = 1_000;
        p.maxReviewCost = 1_000;
        p.verifierLatePenalty = 500;
        p.verifierWrongPenalty = 1_000;
        p.maxBadGain = uint96(G);
        // Smallest seller penalty the admission rule accepts: with
        // deferBlocks >= judgment delay the rate term is zero, so g * ceil(1/p).
        p.sellerPenalty = uint96(G * ((PPM + uint256(p.effectivePpm) - 1) / p.effectivePpm));
    }

    function _run(string memory tag) internal returns (Outcome memory o) {
        // Deploy once to learn the judgment delay, then use it as the enforcement window.
        FairBindCore.ServiceProfileInput memory p = _profileFor(30_000);
        _deploy(p);
        uint32 enforcement = uint32(fairbind.judgmentDelayBlocks(PROFILE));
        p = _profileFor(enforcement);
        _deploy(p);
        _logStr(tag);
        _log("  enforcementBlocks (= judgment delay)", enforcement);
        _log("  sellerPenalty (admission floor)", p.sellerPenalty);
        _log("  deferBlocks", p.deferBlocks);

        uint256 ownerStart = token.balanceOf(SELLER_OWNER);
        uint256 buyerStart = token.balanceOf(buyer);
        uint256 contractStart = token.balanceOf(address(fairbind));
        uint256 poolStart = token.balanceOf(REWARD_POOL);
        uint256 lockedStart = fairbind.getLockedForfeit();
        bytes32[] memory ns = new bytes32[](N);
        uint256 k;
        for (uint256 b = 1; b <= DELTA_J; b++) {
            hv.roll(b);
            for (uint256 j; j < LAMBDA; j++) ns[k++] = _purchase(G);
        }
        o.ownerDeltaAtSettle = token.balanceOf(SELLER_OWNER) - ownerStart;
        o.heldAtSettle = token.balanceOf(address(fairbind)) - contractStart;

        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(N), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256(abi.encode("epoch randomness c", enforcement)));
        fairbind.seal(sellerId, 0);

        bool[] memory isS = new bool[](N);
        for (uint256 i; i < N; i++) {
            (bool e,) = fairbind.isSampled(ns[i]);
            isS[i] = e;
            if (e) o.sampled++;
        }
        _log("  sampled |S|", o.sampled);

        hv.roll(800);
        for (uint256 i; i < N; i++) {
            if (!isS[i]) continue;
            fairbind.openSample(ns[i]);
            _judge(ns[i], 2);
        }
        hv.roll(800 + 600 + 1);
        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        uint256 bondBefore = fairbind.getBond(bondId).balance;
        for (uint256 i; i < N; i++) {
            if (isS[i]) fairbind.finalizeCase(ns[i]);
        }
        o.penalty = bondBefore - fairbind.getBond(bondId).balance;
        _log("  seller status (3=SANCTIONED)", fairbind.getSeller(sellerId).status);
        _log("  penalty taken from bond", o.penalty);

        SettleArgs memory late = _settleArgs(G);
        hv.expectRevert(FairBindCore.SellerInactive.selector);
        _settle(late);

        for (uint256 i; i < N; i++) {
            if (!isS[i]) continue;
            fairbind.claimRefund(ns[i]);
            o.refunded++;
        }
        _log("  refunds paid", o.refunded);

        // Past releaseBlock and retainUntil of every purchase.
        hv.roll(DELTA_J + p.deferBlocks + 1);
        uint256 ownerBeforeRelease = token.balanceOf(SELLER_OWNER);
        for (uint256 i; i < N; i++) {
            if (isS[i]) continue;
            try fairbind.releasePurchase(ns[i]) {
                o.released++;
            } catch {
                o.releaseReverts++;
            }
        }
        o.releasedAmount = token.balanceOf(SELLER_OWNER) - ownerBeforeRelease;
        _log("  releasePurchase succeeded", o.released);
        _log("  releasePurchase reverted", o.releaseReverts);
        _log("  amount released to seller owner", o.releasedAmount);

        // Buyers of every other unsampled purchase present their receipts.
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        if (bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN)) {
            uint256 u;
            for (uint256 i; i < N; i++) {
                if (isS[i]) continue;
                if (u++ % 2 == 1) continue;
                FairBindCore.FairBindReceipt memory r = _receipt(ns[i]);
                fairbind.claimRefund(ns[i], r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(ns[i]));
                o.claimed++;
            }
            hv.roll(uint256(bond.claimUntilBlock) + 1);
            uint256 lockedBefore = fairbind.getLockedForfeit();
            fairbind.forfeitUnclaimed(bondId);
            o.forfeited = fairbind.getLockedForfeit() - lockedBefore;
        }
        _log("  frozen-pool claims paid", o.claimed);
        _log("  forfeited remainder", o.forfeited);

        o.sellerNet = int256(token.balanceOf(SELLER_OWNER)) - int256(ownerStart) - int256(uint256(p.sellerPenalty));
        o.buyerUnrecovered = buyerStart - token.balanceOf(buyer);
        _logInt("  seller net (released minus bond lost)", o.sellerNet);
        _log("  buyer unrecovered", o.buyerUnrecovered);
        // Forfeited remainder and deducted share stay locked (ADR 0022).
        require(token.balanceOf(REWARD_POOL) == poolStart, "C nothing to the verifier pool");
        require(fairbind.getLockedForfeit() - lockedStart >= o.forfeited, "C forfeiture locked");

        require(o.ownerDeltaAtSettle == 0, "C seller not paid at settle");
        require(o.heldAtSettle == N * G, "C contract holds all");
        require(o.refunded == o.sampled, "C refunds equal sampled");
        // Per-failure shares up to the limit sum to one penalty; nothing after the sanction (ADR 0018).
        require(o.penalty == p.sellerPenalty, "C one penalty over the failure window");
    }

    /// Current rule: no unsampled cheated sale reaches the seller.
    function test_C1_freezeHoldsUnsampledSales() public {
        Outcome memory o = _run("C1 bond-level freeze, enforcementBlocks = judgment delay");
        require(o.released == 0 && o.releasedAmount == 0, "C1 nothing released");
        require(o.releaseReverts == N - o.sampled, "C1 every unsampled release refused");
        require(o.claimed == (N - o.sampled + 1) / 2, "C1 claims paid");
        require(o.forfeited == (N - o.sampled - o.claimed) * G, "C1 remainder forfeited");
        require(o.buyerUnrecovered == (N - o.sampled - o.claimed) * G, "C1 buyer loss is the unclaimed part");
        require(o.sellerNet < 0, "C1 expected negative net");
    }

    /// Pre-ADR 0012 rule on the mutation build: unsampled cheated sales are
    /// released to the seller after deferBlocks. Documents the old defect.
    function test_C1_preFreezeRule_releasesUnsampledSales() public {
        disableFreeze = true;
        Outcome memory o = _run("C1 mutation build without freeze (pre-ADR 0012 rule)");
        require(o.released == N - o.sampled, "C1-old unsampled released");
        require(o.releasedAmount == (N - o.sampled) * G, "C1-old released amount");
        require(o.buyerUnrecovered == (N - o.sampled) * G, "C1-old buyer loss");
        require(o.sellerNet > 0, "C1-old expected positive net at the freeze-mode bond");
    }

    /// The short enforcement window admitted before is now rejected at profile creation.
    function test_C2_shortEnforcementRejected() public {
        // The admission rule is the production build's; the override build skips it.
        FairBindCore.ServiceProfileInput memory p = _profileFor(30_000);
        p.freezeOnInitialFail = false;
        _deploy(p);
        FairBindCore.ServiceProfileInput memory shortWindow = _profileFor(10);
        shortWindow.freezeOnInitialFail = false;
        shortWindow.parameterHash = keccak256("short");
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(PROFILE + 1, shortWindow);
        _logStr("C2 enforcementBlocks = 10 rejected: shorter than the judgment delay");
    }
}
