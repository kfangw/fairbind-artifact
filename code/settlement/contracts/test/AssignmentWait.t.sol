// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { TEST_BEACON_DELAY_BLOCKS } from "./TestProfileConstants.sol";
import { FairBindCore } from "../src/FairBindCore.sol";
import { Impl1bBase } from "./Design2Impl1b.t.sol";

interface BlockVm {
    function getBlockNumber() external view returns (uint256);
}

/// ADR 0028: a sampled case whose initial assignment search is exhausted
/// waits for the next checkpoint instead of ending as a protocol
/// INCONCLUSIVE, and is redrawn with a value fixed after that checkpoint.
///
/// The profile gives every verifier an exposure fraction of 10%: with a bond
/// of 10 USDC the room at the checkpoint is (10 - 1) * 0.1 = 0.9 USDC, below
/// the case liability of 1.01 USDC, so every initial search of the first
/// checkpoint is exhausted. A top-up of 10 USDC gives a verifier 1.9 USDC of
/// room, one case.
contract AssignmentWaitTest is Impl1bBase {
    bytes32 internal constant REDRAW_HASH = keccak256("redraw hash");
    uint256 internal constant LIABILITY = G + 1_000_000;
    uint8 internal constant INITIAL = uint8(FairBindCore.JudgmentStage.INITIAL);
    uint8 internal constant WAITING = uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT);
    BlockVm internal constant bv = BlockVm(address(uint160(uint256(keccak256("hevm cheat code")))));

    /// The current block through the cheatcode: under via_ir a test function
    /// may read a stale block.number after vm.roll.
    function _now() internal view returns (uint256) {
        return bv.getBlockNumber();
    }

    function _waitProfile() internal pure returns (FairBindCore.ServiceProfileInput memory p) {
        p = _sampledProfile(20);
        p.verifierExposurePpm = 100_000;
    }

    /// Settles `count` purchases of value G in epoch 0, anchors and seals the
    /// epoch on checkpoint 1, and opens every sample case.
    function _waiting(uint256 count) internal returns (bytes32[] memory ns) {
        _deploy(_waitProfile());
        hv.roll(10);
        ns = new bytes32[](count);
        for (uint256 i; i < count; i++) ns[i] = _purchase(G);
        _anchorAndSeal(ns, BEACON);
        for (uint256 i; i < count; i++) fairbind.openSample(ns[i]);
    }

    /// Tops up the given verifiers by 10 USDC and writes a checkpoint one block
    /// later; returns its version and its redraw block.
    function _newerCheckpoint(uint32[] memory ids) internal returns (uint64 version, uint256 randomBlock) {
        for (uint256 i; i < ids.length; i++) fairbind.topUpVerifierBond(ids[i], 10_000_000);
        hv.roll(_now() + 1);
        version = fairbind.checkpointVerifierTree(PROFILE);
        (uint64 checkpointBlock,,,,) = fairbind.getVerifierCheckpoint(PROFILE, version);
        require(checkpointBlock == _now(), "checkpoint written in this block");
        randomBlock = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
    }

    function _all() internal pure returns (uint32[] memory ids) {
        ids = new uint32[](14);
        for (uint256 i; i < 14; i++) ids[i] = uint32(i + 1);
    }

    function _one(uint32 id) internal pure returns (uint32[] memory ids) {
        ids = new uint32[](1);
        ids[0] = id;
    }

    /// The verifier the search of (value, nonce, stage, attempt) picks on
    /// checkpoint `version`, with the contract's rule: rounds 0 to 13, skip a
    /// verifier already in `taken` or whose room is below the liability; zero
    /// when the search is exhausted.
    function _drawn(bytes32 value, bytes32 n, uint8 stage, uint8 attempt, uint64 version, uint32[] memory taken)
        internal
        view
        returns (uint32)
    {
        (, uint32[] memory ids, uint96[] memory weights, uint256 total,) = fairbind.getVerifierCheckpoint(PROFILE, version);
        uint96[] memory room = fairbind.getCheckpointHeadroom(PROFILE, version);
        for (uint32 round; round < 14; round++) {
            uint256 ticket = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, n, stage, attempt, round)))
                % total;
            uint256 cumulative;
            uint256 at;
            for (at = 0; at < ids.length; at++) {
                cumulative += weights[at];
                if (ticket < cumulative) break;
            }
            bool skip = room[at] < LIABILITY;
            for (uint256 j; j < taken.length; j++) if (taken[j] == ids[at]) skip = true;
            if (!skip) return ids[at];
        }
        return 0;
    }

    function _none() internal pure returns (uint32[] memory) {
        return new uint32[](0);
    }

    /// Puts the sample receipt on chain before its deadline, which falls long
    /// before any redraw block.
    function _postReceipt(bytes32 n) internal {
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        fairbind.submitSampleReceipt(n, r, _sig(SELLER_KEY, fairbind.receiptDigest(r)), _proof(n));
    }

    /// (a) The exhausted first search leaves the case waiting: no keeper serve
    /// request, no INCONCLUSIVE, no deadline, no assignment, attempt 0, and the
    /// purchase held. releasePurchase refuses it after every release condition.
    function test_exhaustedFirstAssignmentWaitsAndHoldsThePurchase() public {
        bytes32 n = _waiting(1)[0];
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == WAITING, "waiting");
        require(c.requesterRole == uint8(FairBindCore.RequesterRole.NONE) && c.finalVerdict == 0, "no keeper path");
        require(c.assignedVerifierId == 0 && c.judgeDue == 0 && c.attempt == 0, "no assignment, no deadline");
        require(fairbind.getAssignments(n).length == 0, "nothing locked");
        FairBindCore.AssignmentWait memory w = fairbind.getAssignmentWait(n);
        require(w.checkpointVersion == 1 && w.searchBlock == _now() && w.redraws == 0, "wait record");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.HELD), "held");
        require(fairbind.purchaseState(n) == uint8(FairBindCore.FinancialState.HELD), "held view");
        // The receipt obligation of the sample case still runs (rule D2-17).
        require(fairbind.getSampleReceiptDue(n) != 0, "receipt deadline running");
        hv.roll(200_000);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(n);
        require(fairbind.getCase(n).state == WAITING, "still waiting");
    }

    /// (b) No redraw without a checkpoint written after the search: a call on
    /// the same checkpoint reverts, also after a checkpoint call that only
    /// reproduces it.
    function test_redrawBeforeANewerCheckpointReverts() public {
        bytes32 n = _waiting(1)[0];
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.assignVerifier(n);
        hv.roll(_now() + 5_000);
        require(fairbind.checkpointVerifierTree(PROFILE) == 1, "unchanged table, same version");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.assignVerifier(n);
        require(fairbind.getAssignmentWait(n).redraws == 0, "nothing recorded");
    }

    /// (c) After a newer checkpoint and its redraw block, anyone redraws: the
    /// case is assigned on the newer checkpoint's room and the judgment
    /// deadline starts at that block. Before the redraw block the call reverts.
    function test_redrawAfterANewerCheckpointAssignsAndStartsTheJudgeDeadline() public {
        bytes32 n = _waiting(1)[0];
        _postReceipt(n);
        (uint64 version, uint256 rb) = _newerCheckpoint(_all());
        require(version == 2, "newer checkpoint");
        hv.roll(rb);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.assignVerifier(n);
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        uint256 before = gasleft();
        hv.prank(address(0xD00D));
        fairbind.assignVerifier(n);
        _log("assignVerifier redraw gas (call frame)", before - gasleft());
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.JUDGING), "judging");
        require(c.assignedVerifierId == _drawn(REDRAW_HASH, n, INITIAL, 0, 2, _none()), "drawn on the newer checkpoint");
        require(c.judgeDue == _now() + 600, "deadline from the redraw");
        require(c.attempt == 0 && c.randomness == REDRAW_HASH, "inputs");
        FairBindCore.AssignmentWait memory w = fairbind.getAssignmentWait(n);
        require(w.checkpointVersion == 2 && w.redraws == 1 && w.randomness == REDRAW_HASH, "wait record");
        require(fairbind.getVerifier(c.assignedVerifierId).lockedLiability == LIABILITY, "liability locked");
        _judge(n, uint8(FairBindCore.Verdict.PASS));
        require(fairbind.getCase(n).state == uint8(FairBindCore.CaseState.INITIAL_VERDICT), "judged");
    }

    /// (d) The redraw depends on the hash of the block beaconDelayBlocks + 1
    /// after the newer checkpoint, which does not exist when that checkpoint is
    /// written, and on nothing the checkpoint writer can pick after seeing it:
    /// two hashes give two verifiers, the epoch value gives neither, and a
    /// further checkpoint written after the hash is known changes nothing.
    function test_redrawValueIsFixedOnlyAfterTheNewerCheckpoint() public {
        bytes32 n = _waiting(1)[0];
        (, uint256 rb) = _newerCheckpoint(_all());
        require(rb > _now() + TEST_BEACON_DELAY_BLOCKS, "value block after the checkpoint block");
        // Two hashes of the redraw block that pick different verifiers.
        bytes32 h1 = REDRAW_HASH;
        bytes32 h2;
        for (uint256 i; h2 == 0; i++) {
            bytes32 h = keccak256(abi.encode("other", i));
            if (_drawn(h, n, INITIAL, 0, 2, _none()) != _drawn(h1, n, INITIAL, 0, 2, _none())) h2 = h;
        }
        uint32 epochPick = _drawn(BEACON, n, INITIAL, 0, 2, _none());
        hv.roll(rb + 1);
        uint256 snap = sv.snapshotState();
        hv.setBlockhash(rb, h1);
        // A further checkpoint written once the hash is public is not used.
        fairbind.topUpVerifierBond(1, 1_000_000);
        require(fairbind.checkpointVerifierTree(PROFILE) == 3, "later checkpoint");
        fairbind.assignVerifier(n);
        uint32 first = fairbind.getCase(n).assignedVerifierId;
        require(fairbind.getAssignmentWait(n).checkpointVersion == 2, "the first newer checkpoint");
        sv.revertToState(snap);
        hv.setBlockhash(rb, h2);
        fairbind.assignVerifier(n);
        uint32 second = fairbind.getCase(n).assignedVerifierId;
        require(first == _drawn(h1, n, INITIAL, 0, 2, _none()), "first hash");
        require(second == _drawn(h2, n, INITIAL, 0, 2, _none()), "second hash");
        require(first != second, "the draw follows the redraw block hash");
        _log("verifier the epoch value would pick", epochPick);
        _log("verifier picked with the first hash", first);
        _log("verifier picked with the second hash", second);
    }

    /// A redraw value the chain no longer serves cannot be used: the newer
    /// checkpoint counts as searched and the case waits for the next one.
    function test_aRedrawHashNoLongerServedWaitsForTheNextCheckpoint() public {
        bytes32 n = _waiting(1)[0];
        (, uint256 rb) = _newerCheckpoint(_all());
        hv.roll(rb + 257);
        fairbind.assignVerifier(n);
        FairBindCore.AssignmentWait memory w = fairbind.getAssignmentWait(n);
        require(fairbind.getCase(n).state == WAITING, "still waiting");
        require(w.checkpointVersion == 2 && w.redraws == 1 && w.searchBlock == _now(), "version 2 searched");
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.assignVerifier(n);
    }

    /// (e) Waiting consumes no assignment: after a wait, an exhausted redraw
    /// and a successful one, the case still has all maxAssignments (3)
    /// attempts, later attempts draw from the redraw value on the redraw's
    /// checkpoint, and only the third timeout takes the keeper serve path.
    function test_waitingDoesNotConsumeMaxAssignments() public {
        bytes32 n = _waiting(1)[0];
        // A newer checkpoint where nobody has room (a fifteenth verifier with
        // the minimum bond and no room): the redraw is exhausted.
        hv.roll(_now() + 1);
        fairbind.registerVerifier(uint256(1) << 1, hv.addr(1015), 1_000_000);
        require(fairbind.checkpointVerifierTree(PROFILE) == 2, "version 2 has no room");
        uint256 rb2 = _now() + 1 + TEST_BEACON_DELAY_BLOCKS;
        hv.roll(rb2 + 1);
        hv.setBlockhash(rb2, REDRAW_HASH);
        fairbind.assignVerifier(n);
        require(fairbind.getCase(n).state == WAITING && fairbind.getCase(n).attempt == 0, "waits again at attempt 0");
        require(fairbind.getAssignmentWait(n).redraws == 1, "one redraw");
        (uint64 v3, uint256 rb3) = _newerCheckpoint(_all());
        require(v3 == 3, "version 3");
        hv.roll(rb3 + 1);
        hv.setBlockhash(rb3, REDRAW_HASH);
        fairbind.assignVerifier(n);
        uint32[] memory taken = new uint32[](3);
        for (uint8 attempt; attempt < 3; attempt++) {
            FairBindCore.CaseView memory c = fairbind.getCase(n);
            require(c.attempt == attempt && c.state == uint8(FairBindCore.CaseState.JUDGING), "attempt assigned");
            uint32[] memory before = new uint32[](attempt);
            for (uint256 j; j < attempt; j++) before[j] = taken[j];
            require(c.assignedVerifierId == _drawn(REDRAW_HASH, n, INITIAL, attempt, 3, before), "redraw value, version 3");
            taken[attempt] = c.assignedVerifierId;
            hv.roll(uint256(c.judgeDue) + 1);
            fairbind.timeoutJudge(n);
        }
        require(fairbind.getAssignments(n).length == 3, "three assignments after waiting");
        FairBindCore.CaseView memory last = fairbind.getCase(n);
        require(last.state == uint8(FairBindCore.CaseState.PUBLISHING)
            && last.requesterRole == uint8(FairBindCore.RequesterRole.KEEPER), "final timeout keeps the keeper path");
    }

    /// (f) A buyer dispute keeps the old exhaustion rule: its initial search
    /// ends INCONCLUSIVE and never waits.
    function test_disputeExhaustionStillEndsInconclusive() public {
        _deploy(_waitProfile());
        hv.roll(10);
        bytes32 n = _purchase(G);
        FairBindCore.FairBindReceipt memory r = _receipt(n);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.roll(80);
        hv.prank(buyer);
        fairbind.dispute(n, uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = n;
        _anchorAndSeal(ns, BEACON);
        fairbind.assignVerifier(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.INCONCLUSIVE), "dispute ends INCONCLUSIVE");
        require(fairbind.getAssignmentWait(n).checkpointVersion == 0, "never waited");
    }

    /// (f) A review stage keeps the old exhaustion rule: after a redraw on a
    /// checkpoint where only the initial verifier has room, the seller's
    /// appeal cannot be assigned and upholds the initial FAIL (rule D2-15).
    /// The review searches the redraw's checkpoint.
    function test_reviewExhaustionAfterARedrawUpholdsTheInitialFail() public {
        bytes32 n = _waiting(1)[0];
        _postReceipt(n);
        uint32 x = 5;
        (, uint256 rb) = _newerCheckpoint(_one(x));
        bytes32 h;
        for (uint256 i; h == 0; i++) {
            bytes32 candidate = keccak256(abi.encode("reaches x", i));
            if (_drawn(candidate, n, INITIAL, 0, 2, _none()) == x) h = candidate;
        }
        hv.roll(rb + 1);
        hv.setBlockhash(rb, h);
        fairbind.assignVerifier(n);
        require(fairbind.getCase(n).assignedVerifierId == x, "the only verifier with room");
        _judge(n, uint8(FairBindCore.Verdict.FAIL));
        token.mint(SELLER_OWNER, DEPOSIT);
        hv.prank(SELLER_OWNER);
        fairbind.appeal(n);
        uint64 reviewBlock = fairbind.getCase(n).randomBlock;
        hv.roll(uint256(reviewBlock) + 1);
        hv.setBlockhash(reviewBlock, keccak256("review"));
        fairbind.sealReviewRandomness(n);
        FairBindCore.CaseView memory c = fairbind.getCase(n);
        require(c.state == uint8(FairBindCore.CaseState.FINAL) && c.finalVerdict == uint8(FairBindCore.Verdict.FAIL),
            "review exhaustion upholds the FAIL");
        require(fairbind.getPurchase(n).financialState == uint8(FairBindCore.FinancialState.REFUNDABLE), "refundable");
    }

    /// A confirmed failure of the seller while a case waits freezes the
    /// account; the waiting purchase stays held (no claim, no release) until
    /// its own case ends, and a later PASS inside the claim window makes it
    /// claimable from the frozen pool (rule D2-20 (c)).
    function test_aFailureWhileWaitingFreezesAndTheWaitingPurchaseIsClaimableOnceJudged() public {
        bytes32[] memory ns = _waiting(2);
        bytes32 fraud = ns[0];
        bytes32 held = ns[1];
        _postReceipt(held);
        hv.roll(uint256(fairbind.getSampleReceiptDue(fraud)) + 1);
        fairbind.timeoutSampleReceipt(fraud);
        require(fairbind.getCase(fraud).state == uint8(FairBindCore.CaseState.UNSERVED), "waiting case ends UNSERVED");
        uint32 bond = fairbind.getSeller(sellerId).bondId;
        require(fairbind.getBond(bond).freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "claim window open");
        require(fairbind.purchaseState(held) == uint8(FairBindCore.FinancialState.HELD), "waiting purchase held");
        FairBindCore.FairBindReceipt memory r = _receipt(held);
        bytes memory sig = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.claimRefund(held, r, sig, _proof(held));
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.releasePurchase(held);
        (, uint256 rb) = _newerCheckpoint(_all());
        hv.roll(rb + 1);
        hv.setBlockhash(rb, REDRAW_HASH);
        fairbind.assignVerifier(held);
        _judge(held, uint8(FairBindCore.Verdict.PASS));
        uint64 gate = fairbind.getCase(held).randomBlock;
        hv.roll(uint256(gate) + 1);
        hv.setBlockhash(gate, keccak256("gate"));
        fairbind.finalizeCase(held);
        require(fairbind.purchaseState(held) == uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE), "claimable");
        uint256 balance = token.balanceOf(buyer);
        fairbind.claimRefund(held, r, sig, _proof(held));
        require(token.balanceOf(buyer) == balance + G, "buyer paid from the frozen pool");
    }
}
