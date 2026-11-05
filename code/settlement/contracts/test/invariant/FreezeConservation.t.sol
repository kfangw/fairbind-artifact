// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../../src/FairBindCore.sol";
import { ReproBase } from "../repro/ReproBase.sol";

/// Conservation of a frozen bond account, and the mutation test that shows
/// the leak the freeze closes. One purchase of a seller is judged FAIL through
/// a buyer dispute; every other purchase of the same bond account is then
/// either claimed with its receipt, forfeited, or (on the mutation build
/// without the freeze) released to the seller.
contract FreezeConservationTest is ReproBase {
    uint256 internal constant G = 10_000;

    struct Totals {
        uint256 total;
        uint256 toSeller;
        uint256 toBuyer;
        uint256 forfeited;
        uint256 claims;
        uint256 unsampledOthers;
        uint256 deducted;
        uint256 sinks;
    }

    function _scenario(uint256 k, uint256 claimMask) internal returns (Totals memory t) {
        FairBindCore.ServiceProfileInput memory p = _baseProfile();
        p.recheckPpm = 0;
        _deploy(p);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](k);
        for (uint256 i; i < k; i++) ns[i] = _purchase(G);
        t.total = k * G;
        _buildTree(ns);
        hv.roll(600);
        hv.prank(SELLER_OWNER);
        fairbind.anchor(sellerId, 0, _treeEntries(), uint32(k), keccak256("publication"));
        hv.roll(BEACON_BLOCK + 1);
        hv.setBlockhash(BEACON_BLOCK, keccak256(abi.encode("beacon", k, claimMask)));
        fairbind.seal(sellerId, 0);

        uint256 ownerStart = token.balanceOf(SELLER_OWNER);
        uint256 buyerStart = token.balanceOf(buyer);
        uint256 sinkStart = token.balanceOf(REWARD_POOL) + token.balanceOf(TREASURY);
        uint256 lockedStart = fairbind.getLockedForfeit();
        uint256 bondStart = fairbind.getBond(fairbind.getSeller(sellerId).bondId).balance;

        // The buyer of the first purchase disputes it and the verifier fails it.
        FairBindCore.FairBindReceipt memory r = _receipt(ns[0]);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(ns[0], uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        fairbind.assignVerifier(ns[0]);
        _judge(ns[0], 2);
        hv.roll(uint256(fairbind.getReview(ns[0]).appealUntil) + 1);
        fairbind.finalizeCase(ns[0]);
        fairbind.claimRefund(ns[0]);

        uint32 bondId = fairbind.getSeller(sellerId).bondId;
        FairBindCore.BondView memory bond = fairbind.getBond(bondId);
        if (bond.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN)) {
            for (uint256 i = 1; i < k; i++) {
                if ((claimMask >> i) & 1 == 0) continue;
                FairBindCore.FairBindReceipt memory ri = _receipt(ns[i]);
                fairbind.claimRefund(ns[i], ri, _sig(SELLER_KEY, fairbind.receiptDigest(ri)), _proof(ns[i]));
                t.claims++;
            }
            hv.roll(uint256(bond.claimUntilBlock) + 1);
            fairbind.forfeitUnclaimed(bondId);
        }
        hv.roll(10 + p.deferBlocks + 1);
        for (uint256 i = 1; i < k; i++) {
            (bool sampled,) = fairbind.isSampled(ns[i]);
            if (!sampled) t.unsampledOthers++;
            try fairbind.releasePurchase(ns[i]) { } catch { }
        }
        t.toSeller = token.balanceOf(SELLER_OWNER) - ownerStart;
        // The dispute deposit returns with the refund; only principal remains.
        t.toBuyer = token.balanceOf(buyer) - buyerStart;
        // The confirmed failure also deducted one share of the seller penalty
        // from the bond (ADR 0018); it is not part of the frozen pool. Both the
        // share and the forfeited remainder stay locked in the contract (ADR
        // 0022), so the external sinks receive nothing.
        t.deducted = bondStart - fairbind.getBond(bondId).balance;
        t.forfeited = fairbind.getLockedForfeit() - lockedStart - t.deducted;
        t.sinks = token.balanceOf(REWARD_POOL) + token.balanceOf(TREASURY) - sinkStart;
    }

    /// forge-config: default.fuzz.runs = 8
    function testFuzz_frozenPoolIsConservedAndNeverPaidToTheSeller(uint8 kSeed, uint16 claimMask) public {
        uint256 k = 2 + uint256(kSeed) % 9;
        Totals memory t = _scenario(k, claimMask);
        require(t.toSeller == 0, "no principal reaches the failing seller");
        // The refund of the judged purchase, the receipt claims, and the
        // forfeiture cover every purchase exactly once.
        require(t.toBuyer == (1 + t.claims) * G, "each claim paid once");
        require(t.toBuyer + t.forfeited == t.total, "pool conserved");
        require(t.deducted == uint256(10_000_000) / 3, "one share of the penalty deducted from the bond");
        require(t.sinks == 0, "forfeiture and deduction stay locked in the contract");
    }

    /// Mutation build: with the freeze switched off, the unsampled purchases of
    /// the failing seller are released to it (the pre-ADR 0012 rule).
    /// forge-config: default.fuzz.runs = 8
    function testFuzz_mutationWithoutFreezeLeaksToTheSeller(uint8 kSeed) public {
        disableFreeze = true;
        uint256 k = 2 + uint256(kSeed) % 9;
        Totals memory t = _scenario(k, 0);
        require(t.toSeller == t.unsampledOthers * G, "pre-freeze rule releases unsampled sales");
        require(t.toBuyer == G, "only the judged buyer is refunded");
    }
}
