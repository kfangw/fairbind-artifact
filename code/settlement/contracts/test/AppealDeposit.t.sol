// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";
import { CurrentHeldProof } from "./BatchMutants.sol";

/// ADR 0033: a buyer's appeal of an initial PASS under a proportional deposit
/// pays max(d0, ceil(phi * H)), H the high mark of the account's held total
/// at the end of the previous block, within the buyer's limit; a failed
/// appeal pays the seller d0 and locks the rest. Here phi = 1000 (depositPpm
/// 1e9) and d0 = 5 USDC, so one purchase of 0.01 USDC adds 10 USDC.
contract AppealDepositTest is BatchBase {
    uint256 internal constant D0 = 5_000_000;

    function _terms() internal pure returns (BatchStore.Terms memory t) {
        t = _defaultTerms();
        t.depositPpm = 1_000_000_000;
    }

    /// Two purchases of epoch 0 judged in batch 0; the first gets a PASS.
    function _passed() internal returns (bytes32[] memory ns) {
        _deployBatched(_batchProfile(), _terms(), _equalBonds());
        hv.roll(10);
        ns = new bytes32[](2);
        ns[0] = _purchase(G);
        ns[1] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        _assignBatch(0);
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.JUDGING), "started");
        _judgeBatched(ns[0], uint8(FairBindCore.Verdict.PASS));
        hv.roll(_now() + 1);
    }

    function appealExternal(bytes32 n, uint256 limit) external {
        hv.prank(buyer);
        fb.appealWithLimit(n, limit);
    }

    /// A settlement in the appeal's block does not raise the deposit: the
    /// appeal reads the mark at the end of the previous block (20 USDC for a
    /// held total of 0.02 USDC). A build that reads the current mark asks 30
    /// USDC and exceeds the buyer's limit.
    function _sameBlockSettlementKeepsTheDeposit(string memory artifact) internal returns (bool) {
        depositArtifact = artifact;
        bytes32[] memory ns = _passed();
        (uint256 d, uint256 high) = fb.appealDepositOf(ns[0]);
        require(d == 20_000_000 && high == 2 * G, "deposit before");
        _purchase(G);
        uint256 before = token.balanceOf(buyer);
        (bool ok,) = address(this).call(abi.encodeCall(this.appealExternal, (ns[0], 20_000_000)));
        if (!ok) return false;
        return before - token.balanceOf(buyer) == 20_000_000 && fairbind.getReview(ns[0]).deposit == 20_000_000;
    }

    function test_sameBlockSettlementDoesNotRaiseTheDeposit() public {
        require(_sameBlockSettlementKeepsTheDeposit(depositArtifact), "previous block");
    }

    function test_depositOfTheCurrentBlockIsCaught() public {
        require(!_sameBlockSettlementKeepsTheDeposit("BatchMutants.sol:CurrentHeldProof"), "mutation caught");
    }

    /// The limit: one unit below the deposit reverts, the deposit itself
    /// passes. The fixed appeal is closed to a buyer's PASS appeal; the
    /// seller's appeal of a FAIL keeps the fixed deposit.
    function test_limitAndTheFixedPaths() public {
        bytes32[] memory ns = _passed();
        hv.prank(buyer);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.appeal(ns[0]);
        hv.prank(buyer);
        hv.expectRevert(bytes4(keccak256("DepositAboveLimit()")));
        fb.appealWithLimit(ns[0], 20_000_000 - 1);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fb.appealWithLimit(ns[0], 20_000_000);
        hv.prank(buyer);
        fb.appealWithLimit(ns[0], 20_000_000);
        if (_state(ns[1]) != uint8(FairBindCore.CaseState.JUDGING)) return;
        _judgeBatched(ns[1], uint8(FairBindCore.Verdict.FAIL));
        uint256 before = token.balanceOf(SELLER_OWNER);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(ns[1]);
        require(before - token.balanceOf(SELLER_OWNER) == D0, "fixed deposit for the seller");
    }

    /// The review agrees with the PASS: the appeal fails, the seller gets d0
    /// and the 15 USDC above it is locked. A build that pays the seller the
    /// whole deposit locks nothing.
    function _failedAppealLocksTheRest(string memory artifact) internal returns (bool) {
        judgmentArtifact = artifact;
        bytes32[] memory ns = _passed();
        hv.prank(buyer);
        fb.appealWithLimit(ns[0], 20_000_000);
        _reviewValueOf(ns[0]);
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.PARTY_REVIEW), "review started");
        uint256 seller0 = token.balanceOf(SELLER_OWNER);
        uint256 locked0 = fairbind.getLockedForfeit();
        _judgeBatched(ns[0], uint8(FairBindCore.Verdict.PASS));
        return token.balanceOf(SELLER_OWNER) - seller0 == D0 && fairbind.getLockedForfeit() - locked0 == 15_000_000;
    }

    function test_failedAppealPaysTheFixedDepositAndLocksTheRest() public {
        require(_failedAppealLocksTheRest(judgmentArtifact), "d0 to the seller, the rest locked");
    }

    function test_excessPaidToTheSellerIsCaught() public {
        require(!_failedAppealLocksTheRest("BatchMutants.sol:ExcessToSellerJudgment"), "mutation caught");
    }

    /// The review and the tiebreak overturn the PASS: the buyer gets the
    /// whole deposit back (with the initial verifier's wrong-verdict penalty).
    function test_wonAppealReturnsTheWholeDeposit() public {
        bytes32[] memory ns = _passed();
        hv.prank(buyer);
        fb.appealWithLimit(ns[0], 20_000_000);
        _reviewValueOf(ns[0]);
        _judgeBatched(ns[0], uint8(FairBindCore.Verdict.FAIL));
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.TIEBREAK), "tiebreak");
        _reviewValueOf(ns[0]);
        uint256 buyer0 = token.balanceOf(buyer);
        _judgeBatched(ns[0], uint8(FairBindCore.Verdict.FAIL));
        uint256 penalty = fairbind.getServiceProfile(PROFILE).parameters.verifierWrongPenalty;
        require(token.balanceOf(buyer) - buyer0 == 20_000_000 + penalty, "whole deposit back");
    }

    /// The mark keeps the window's peak after the held total falls: a refund
    /// lowers the total to 0.02 USDC, the deposit stays at the 0.03 peak.
    function test_markKeepsThePeakAfterTheTotalFalls() public {
        _deployBatched(_batchProfile(), _terms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(G);
        _unserved(ns[2]);
        fairbind.claimRefund(ns[2]);
        require(fairbind.getBond(_bondOfSeller(sellerId)).deferredBalance == 2 * G, "total fell");
        hv.roll(_now() + 1);
        (uint256 d, uint256 high) = fb.appealDepositOf(ns[0]);
        require(high == 3 * G && d == 30_000_000, "peak kept");
        // The next fixed window still sees the previous window's peak.
        hv.roll(40_001);
        (d, high) = fb.appealDepositOf(ns[0]);
        require(high == 3 * G, "previous window");
    }
}
