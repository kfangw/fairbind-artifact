// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { MockEIP3009Token } from "../MockEIP3009Token.sol";
import { FixedBondBaseline } from "./FixedBondBaseline.sol";
import { ReproBase } from "./ReproBase.sol";

/// Case B: a calculating cheater against a fixed bond whose judgment window
/// does not block sales. Sampling is a fixed schedule (every 5th sale), not
/// randomness, so every number below is exact.
///
/// Ordering per block: the cheater's sales first, then every judgment that is
/// due in that block.
contract ReproB_FixedBondBaseline is ReproBase {
    uint256 internal constant G = 1;
    uint256 internal constant LAMBDA = 5;
    uint256 internal constant DELTA_J = 100;
    uint256 internal constant SAMPLE_EVERY = 5;
    address internal constant SELLER = address(0x5E1);
    address internal constant CHEAT_BUYER = address(0xB1);

    struct Outcome {
        uint256 sales;
        uint256 revenue;
        uint256 slashed;
        uint256 slashCount;
        uint256 failCount;
        uint256 lastSaleBlock;
        int256 net;
    }

    function _run(uint256 bondAmount) internal returns (Outcome memory o) {
        MockEIP3009Token t = new MockEIP3009Token();
        FixedBondBaseline base =
            new FixedBondBaseline(t, SELLER, TREASURY, G, SAMPLE_EVERY, DELTA_J);
        t.mint(SELLER, bondAmount);
        hv.startPrank(SELLER);
        t.approve(address(base), type(uint256).max);
        base.postBond(bondAmount);
        hv.stopPrank();
        t.mint(CHEAT_BUYER, 1_000_000);
        hv.prank(CHEAT_BUYER);
        t.approve(address(base), type(uint256).max);

        uint256 sellerStart = t.balanceOf(SELLER);
        uint256 nextDue = 1; // next sale id whose judgment is pending
        for (uint256 b = 1; b <= 1 + 2 * DELTA_J + 1; b++) {
            hv.roll(b);
            for (uint256 k; k < LAMBDA && !base.banned(); k++) {
                hv.prank(CHEAT_BUYER);
                base.buy();
                o.lastSaleBlock = b;
            }
            // Judge every sampled sale that is due in this block, in sale order.
            while (nextDue <= base.saleCount() && base.saleBlock(nextDue) + DELTA_J <= b) {
                if (base.isSampled(nextDue)) base.judge(nextDue, true);
                nextDue++;
            }
        }
        o.sales = base.saleCount();
        o.revenue = t.balanceOf(SELLER) - sellerStart;
        o.slashed = t.balanceOf(TREASURY);
        o.slashCount = base.slashCount();
        o.failCount = base.failCount();
        o.net = int256(o.revenue) - int256(o.slashed);
    }

    function _report(string memory tag, uint256 bondAmount, Outcome memory o) internal view {
        _logStr(tag);
        _log("  bond B", bondAmount);
        _log("  sales total", o.sales);
        _log("  last sale block", o.lastSaleBlock);
        _log("  seller revenue (g units)", o.revenue);
        _log("  slashed amount", o.slashed);
        _log("  slash count", o.slashCount);
        _log("  FAIL verdicts recorded", o.failCount);
        _logInt("  cheater net gain", o.net);
    }

    function test_B1_fixedBondCheaterNetGain() public {
        Outcome memory o = _run(100);
        _report("B1 fixed bond B=100, LAMBDA=5, DELTA_J=100, pi=1/5 schedule", 100, o);
        // Expected: 505 sales (= LAMBDA*DELTA_J + 1/p), one slash of 100, net 405.
        require(o.sales == LAMBDA * DELTA_J + SAMPLE_EVERY, "B1 sales");
        require(o.slashCount == 1 && o.slashed == 100, "B1 single slash");
        require(o.net == int256(LAMBDA * DELTA_J * G + SAMPLE_EVERY * G) - 100, "B1 net");
    }

    function test_B2_bondSweepAroundBreakEven() public {
        uint256[3] memory bonds = [uint256(504), 505, 506];
        for (uint256 i; i < 3; i++) {
            Outcome memory o = _run(bonds[i]);
            _report("B2 sweep", bonds[i], o);
            require(o.net == int256(505) - int256(bonds[i]), "B2 net");
        }
    }
}
