// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../src/FairBindCore.sol";
import { FairBindVrf } from "../src/randomness/FairBindVrf.sol";
import { BatchStore } from "../src/modules/BatchStore.sol";
import { BatchBase } from "./BatchBase.sol";
import { IBatchedFairBind } from "./BatchInterfaces.sol";
import { CurrentStateBatch, OrderTicketBatch, NoMoveBatch, MoveAllBatch } from "./BatchMutants.sol";

/// ADR 0032: batch terms and their admission check, checkpoints of fixed
/// blocks, batch membership and the batch value, verifier slots and queues
/// ordered by batch, account rank, account permutation and ticket, queue
/// moves after a verifier's own exit request, the late first assignment and
/// the exits of unanswered values.
contract BatchAssignmentTest is BatchBase {
    uint32 internal constant PROFILE_B = 4;
    uint8 internal constant QUEUED = uint8(FairBindCore.CaseState.QUEUED);
    uint8 internal constant BATCHED = uint8(FairBindCore.CaseState.BATCHED);
    uint8 internal constant JUDGING = uint8(FairBindCore.CaseState.JUDGING);

    function setTermsExternal(uint32 id, BatchStore.Terms memory t) external {
        fb.setBatchTerms(id, t);
    }

    function _setTermsOk(uint32 id, BatchStore.Terms memory t, bool rehash) internal returns (bool) {
        if (rehash) t.termsHash = _batchTermsHash(id, t, address(vrf));
        (bool ok,) = address(this).call(abi.encodeCall(this.setTermsExternal, (id, t)));
        return ok;
    }

    // ------------------------------------------------------- admission

    /// The admission check: D_V + 1 <= assignDelay, keeperSlack <= T_V,
    /// epochBlocks >= D_S + T_V, slotValue at least the largest cap, a
    /// matching commitment, and terms only once on a profile never active.
    function test_batchTermsAdmission() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        FairBindCore.ServiceProfileInput memory p = _batchProfile();
        fairbind.createServiceProfile(PROFILE_B, p);
        BatchStore.Terms memory t = _defaultTerms();
        t.assignDelay = D_V;
        require(!_setTermsOk(PROFILE_B, t, true), "assignDelay below D_V + 1");
        t = _defaultTerms();
        t.keeperSlack = T_V + 1;
        require(!_setTermsOk(PROFILE_B, t, true), "T_V below the keeper slack");
        t = _defaultTerms();
        t.slotValue = uint96(p.maxPurchaseValue - 1);
        require(!_setTermsOk(PROFILE_B, t, true), "slot value below the largest cap");
        t = _defaultTerms();
        t.contestBlocks = 5;
        require(!_setTermsOk(PROFILE_B, t, true), "contest without audit");
        t = _defaultTerms();
        t.termsHash = keccak256("other");
        require(!_setTermsOk(PROFILE_B, t, false), "commitment");
        require(!_setTermsOk(PROFILE, _defaultTerms(), true), "a profile that was active");
        t = _defaultTerms();
        t.termsHash = _batchTermsHash(PROFILE_B, t, address(vrf));
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fb.setBatchTerms(PROFILE_B, t);
        // epochBlocks against D_S + T_V = 31.
        p.epochBlocks = 30;
        fairbind.createServiceProfile(5, p);
        require(!_setTermsOk(5, _defaultTerms(), true), "T_epoch below D_S + T_V");
        p.epochBlocks = 31;
        fairbind.createServiceProfile(6, p);
        require(_setTermsOk(6, _defaultTerms(), true), "T_epoch = D_S + T_V is admitted");
        // The boundaries are admitted, once.
        t = _defaultTerms();
        t.assignDelay = D_V + 1;
        t.keeperSlack = T_V;
        require(_setTermsOk(PROFILE_B, t, true), "boundary terms");
        require(!_setTermsOk(PROFILE_B, t, true), "terms are set once");
        require(fb.getBatchTerms(PROFILE_B).batched, "stored");
    }

    /// With a request-based source the floor of beaconDelayBlocks is D_S;
    /// without one it stays the block-hash floor.
    function test_beaconFloorFollowsTheSource() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        FairBindCore.ServiceProfileInput memory p = _batchProfile();
        p.beaconDelayBlocks = D_V + 1;
        fairbind.createServiceProfile(5, p);
        p.beaconDelayBlocks = D_V;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(6, p);
        _deploy(_productionProfile());
        p.beaconDelayBlocks = D_V + 1;
        hv.expectRevert(FairBindCore.InvalidProfile.selector);
        fairbind.createServiceProfile(7, p);
    }

    /// Batch terms need a request-based source; the extension modules are
    /// installed once, by governance, in kind order; the hook entry point is
    /// not routed.
    function test_extensionsAndSourceRequirements() public {
        _deploy(_productionProfile());
        bytes memory args = abi.encode(address(token), address(this), address(0xA11CE), TREASURY, REWARD_POOL);
        address[] memory exts = _extensions(args);
        fb = IBatchedFairBind(address(fairbind));
        (exts[0], exts[1]) = (exts[1], exts[0]);
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        fb.setExtensions(exts);
        (exts[0], exts[1]) = (exts[1], exts[0]);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fb.setExtensions(exts);
        fb.setExtensions(exts);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.setExtensions(exts);
        fairbind.createServiceProfile(PROFILE_B, _batchProfile());
        BatchStore.Terms memory t = _defaultTerms();
        hv.expectRevert(FairBindCore.InvalidConfiguration.selector);
        fb.setBatchTerms(PROFILE_B, t);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.hook(1, 0);
    }

    // ------------------------------------------------------ checkpoints

    /// The checkpoint of epoch 0 records the state at A = 700 whenever it is
    /// written: a verifier that asked to exit before A is out, one that asked
    /// after A is in, a top-up and a class change after A do not count.
    function _checkpointKeepsTheStateAtA(string memory artifact) internal returns (bool) {
        batchArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(650);
        fairbind.requestVerifierExit(3);
        hv.roll(702);
        fairbind.requestVerifierExit(4);
        fairbind.topUpVerifierBond(5, 10_000_000);
        fairbind.setVerifierClasses(6, uint256(1) << 2);
        hv.roll(705);
        hv.prank(KEEPER);
        uint64 version = fb.checkpointAt(PROFILE, 0);
        (uint64 at, uint32[] memory ids, uint96[] memory weights,,) = fairbind.getVerifierCheckpoint(PROFILE, version);
        bool has3;
        bool has4;
        bool has6;
        bool w5;
        for (uint256 i; i < ids.length; i++) {
            if (ids[i] == 3) has3 = true;
            if (ids[i] == 4) has4 = true;
            if (ids[i] == 6) has6 = true;
            if (ids[i] == 5) w5 = weights[i] == 10_000_000;
        }
        return at == 700 && ids.length == 13 && !has3 && has4 && has6 && w5;
    }

    function test_checkpointKeepsTheStateOfTheAnchorDeadline() public {
        require(_checkpointKeepsTheStateAtA(batchArtifact), "state at A");
    }

    function test_checkpointOfTheCurrentStateIsCaught() public {
        adminArtifact = "BatchMutants.sol:CurrentStateBatch";
        require(!_checkpointKeepsTheStateAtA(batchArtifact), "mutation caught");
    }

    /// A batched epoch seals only with the checkpoint of its anchor deadline;
    /// without it the epoch waits; the ordinary checkpoint is closed; a
    /// repeated write returns the same version; none before A.
    function test_sealTakesOnlyTheCheckpointOfItsAnchorDeadline() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](2);
        ns[0] = _purchase(G);
        ns[1] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        hv.roll(700);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.checkpointAt(PROFILE, 0);
        hv.roll(701);
        hv.prank(KEEPER);
        fairbind.requestSampleValue(PROFILE, 0);
        _fulfill(_sampleId(0));
        hv.roll(713);
        hv.expectRevert(FairBindCore.ServiceClassUnavailable.selector);
        fairbind.seal(sellerId, 0);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutSeal(sellerId, 0);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fairbind.checkpointVerifierTree(PROFILE);
        hv.prank(KEEPER);
        uint64 version = fb.checkpointAt(PROFILE, 0);
        require(fb.checkpointAt(PROFILE, 0) == version, "the same version");
        hv.prank(KEEPER);
        fairbind.seal(sellerId, 0);
        require(fairbind.getAnchor(sellerId, 0).sortitionVersion == version, "sealed on the checkpoint of A");
    }

    /// An epoch without the checkpoint of its anchor deadline ends as a
    /// checkpoint shortage only once a later checkpoint makes it unwritable.
    function test_epochWithoutItsCheckpointEndsOnceALaterOneExists() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(310);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(1, sellerId, SELLER_OWNER, ns);
        hv.roll(1001);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fairbind.timeoutSeal(sellerId, 1);
        hv.roll(1301);
        hv.prank(KEEPER);
        fb.checkpointAt(PROFILE, 2);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.checkpointAt(PROFILE, 1);
        hv.prank(KEEPER);
        fairbind.timeoutSeal(sellerId, 1);
        require(fairbind.getAnchor(sellerId, 1).state == uint8(FairBindCore.EpochState.EPOCH_FAILED), "shortage");
    }

    // ------------------------------------------------- membership, ranks

    function _verifierOf(bytes32 caseId) internal view returns (uint32) {
        BatchStore.Entry memory en = fb.getBatchEntry(caseId);
        if (en.verifier != 0) return en.verifier;
        return fairbind.getCase(caseId).assignedVerifierId;
    }

    /// Sample cases opened by C_e and a dispute opened in the batch's blocks
    /// join batch 0; ranks follow the first tickets within the account; a
    /// case opened after C_e takes a late value and the next rank.
    function test_batchMembershipRanksAndTheLateCase() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](4);
        for (uint256 i; i < 4; i++) ns[i] = _purchase(G);
        hv.roll(100);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[3]);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(ns[3], uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        require(_state(ns[3]) == BATCHED && fb.batchOf(PROFILE, 100) == 0, "the dispute joins batch 0");
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(ns[0]);
        _openSample(ns[1]);
        require(_state(ns[0]) == BATCHED && _state(ns[1]) == BATCHED, "waiting for the batch value");
        (,,,,, bytes32[] memory list) = fb.getBatch(PROFILE, 0);
        require(list.length == 3 && list[0] == ns[3] && list[1] == ns[0] && list[2] == ns[1], "batch list");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fb.requestAssignValue(PROFILE, 0);
        bytes32 value = _assignBatch(0);
        (,, uint64 version, bool assigned,,) = fb.getBatch(PROFILE, 0);
        require(assigned, "assigned");
        uint32 bondId = _bondOfSeller(sellerId);
        // Ranks: the account's three cases by first ticket.
        bytes32[3] memory ids = [ns[3], ns[0], ns[1]];
        for (uint256 i; i < 3; i++) {
            uint256 ti = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, ids[i], uint8(1), uint8(0), uint32(0))));
            uint32 rank = 1;
            for (uint256 j; j < 3; j++) {
                uint256 tj = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), value, ids[j], uint8(1), uint8(0), uint32(0))));
                if (tj < ti) rank++;
            }
            BatchStore.Entry memory en = fb.getBatchEntry(ids[i]);
            require(en.rank == rank && en.key == _keyCopy(0, rank, value, bondId, ids[i], 1), "rank and key");
            require(_verifierOf(ids[i]) == _candidate(version, value, ids[i], 1, 0, 0), "round-0 candidate");
            uint8 st = _state(ids[i]);
            require(st == QUEUED || st == JUDGING, "queued or started");
        }
        // The late case.
        hv.roll(1200);
        _openSample(ns[2]);
        BatchStore.Entry memory late = fb.getBatchEntry(ns[2]);
        require(late.late && late.rank == 4 && late.lateBlock == 1200 && _state(ns[2]) == BATCHED, "late, rank 4");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.RequestTooEarly.selector);
        fb.requestLateValue(ns[2]);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.assignLate(ns[2]);
        hv.roll(1201);
        hv.prank(KEEPER);
        fb.requestLateValue(ns[2]);
        bytes32 own = _fulfill(_lateId(ns[2], 1200));
        hv.prank(KEEPER);
        fb.assignLate(ns[2]);
        late = fb.getBatchEntry(ns[2]);
        uint256 mask = type(uint136).max;
        uint256 t0 = uint256(keccak256(abi.encode(keccak256("fairbind/verifier/v1"), own, ns[2], uint8(1), uint8(0), uint32(0))));
        require(late.key == ((_keyCopy(0, 4, value, bondId, ns[2], 1) & ~mask) | (t0 >> 120)), "late key");
        require(_verifierOf(ns[2]) == _candidate(version, own, ns[2], 1, 0, 0), "late candidate from its own value");
    }

    // ----------------------------------------------- decoys and order

    /// Seller A's three cases get the same candidates whether they are
    /// opened alone or after seller B's six decoys and in reverse order.
    function _candidatesIgnoreOrderAndDecoys(string memory artifact) internal returns (bool) {
        batchArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        _addSellerB();
        hv.roll(10);
        bytes32[] memory a = new bytes32[](3);
        bytes32[] memory b = new bytes32[](6);
        for (uint256 i; i < 3; i++) a[i] = _purchase(G);
        for (uint256 i; i < 6; i++) b[i] = _purchaseOf(sellerB, G);
        _anchorOf(0, sellerId, SELLER_OWNER, a);
        _anchorOf(0, sellerB, SELLER_B_OWNER, b);
        _sealOf(0, _sellers2());
        uint256 snap = sw.snapshotState();
        hv.roll(800);
        for (uint256 i; i < 3; i++) {
            _openSample(a[i]);
        }
        _assignBatch(0);
        uint32[3] memory alone;
        for (uint256 i; i < 3; i++) alone[i] = _verifierOf(a[i]);
        sw.revertToState(snap);
        hv.roll(800);
        for (uint256 i; i < 6; i++) {
            _openSample(b[i]);
        }
        for (uint256 i = 3; i > 0; i--) {
            _openSample(a[i - 1]);
        }
        _assignBatch(0);
        for (uint256 i; i < 3; i++) {
            if (_verifierOf(a[i]) != alone[i]) return false;
        }
        return true;
    }

    function test_firstCandidatesIgnoreOpeningOrderAndDecoys() public {
        require(_candidatesIgnoreOrderAndDecoys(batchArtifact), "same candidates");
    }

    function test_ticketsFromTheOpeningOrderAreCaught() public {
        require(!_candidatesIgnoreOrderAndDecoys("BatchMutants.sol:OrderTicketBatch"), "mutation caught");
    }

    /// One case of seller A and six decoys of seller B at a verifier with one
    /// slot: within the batch the queue alternates between accounts, so at
    /// most one decoy (B's rank-1 case) comes before A's rank-1 case.
    function test_decoysOfAnotherAccountDelayByOneTurn() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        _deployBatched(_batchProfile(), t, _heavyFirstBonds());
        _addSellerB();
        hv.roll(10);
        bytes32[] memory a = new bytes32[](1);
        bytes32[] memory b = new bytes32[](6);
        a[0] = _purchase(G);
        for (uint256 i; i < 6; i++) b[i] = _purchaseOf(sellerB, G);
        _anchorOf(0, sellerId, SELLER_OWNER, a);
        _anchorOf(0, sellerB, SELLER_B_OWNER, b);
        _sealOf(0, _sellers2());
        hv.roll(800);
        for (uint256 i; i < 6; i++) {
            _openSample(b[i]);
        }
        _openSample(a[0]);
        _assignBatch(0);
        uint32 u = _verifierOf(a[0]);
        bytes32[] memory q = fb.getQueue(u);
        uint256 ahead;
        bool started = _state(a[0]) == JUDGING;
        for (uint256 i; i < q.length && !started; i++) {
            if (q[i] == a[0]) break;
            ahead++;
        }
        // When A's case waits, the case u judges is the one case ahead of it.
        require(started || ahead == 0, "at most one decoy ahead");
        require(fb.getBatchEntry(a[0]).rank == 1, "A's case has rank 1");
        // Every queue is in key order.
        for (uint32 v = 1; v <= 14; v++) {
            q = fb.getQueue(v);
            for (uint256 i = 1; i < q.length; i++) {
                require(fb.getBatchEntry(q[i - 1]).key < fb.getBatchEntry(q[i]).key, "key order");
            }
        }
    }

    // ------------------------------------------------------ slots, starts

    /// Eight cases with verifier 1 heavy: every verifier with cases judges
    /// one at a time (verifier 1 has one slot, the others none and start one
    /// by the exception), the rest wait in key order with their liability
    /// reserved, and the end of the judged case starts the next head in the
    /// same transaction.
    function _slotsScenario(uint96 slotValue, uint256 expectSlots) internal returns (bytes32[] memory ns) {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = slotValue;
        _deployBatched(_batchProfile(), t, _heavyFirstBonds());
        hv.roll(10);
        ns = new bytes32[](8);
        for (uint256 i; i < 8; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        _assignBatch(0);
        (, uint256 slots1) = fb.getSlots(1);
        (, uint256 slots2) = fb.getSlots(2);
        require(slots1 == expectSlots && slots2 == 0, "slot counts");
        for (uint32 u = 1; u <= 14; u++) {
            uint256 mine;
            uint256 judging;
            uint256 lowest = type(uint256).max;
            bytes32 lowestId;
            for (uint256 i; i < 8; i++) {
                if (_verifierOf(ns[i]) != u) continue;
                mine++;
                uint256 k = fb.getBatchEntry(ns[i]).key;
                if (k < lowest) {
                    lowest = k;
                    lowestId = ns[i];
                }
                if (_state(ns[i]) == JUDGING) judging++;
            }
            if (mine == 0) continue;
            require(judging == 1 && _state(lowestId) == JUDGING, "the lowest key judges");
            (BatchStore.Slots memory s,) = fb.getSlots(u);
            require(s.active == 1 && s.queued == mine - 1, "one judging, the rest queued");
            if (u == 1) require(s.reserved == (mine - 1) * (G + 1_000_000), "reservations");
        }
    }

    /// The judging case keeps its slot through its initial verdict; the
    /// transaction that ends it starts the next head.
    function _nextStartsOnVerdict(bytes32[] memory ns) internal {
        bytes32[] memory q = fb.getQueue(1);
        require(q.length >= 2, "verifier 1 has a queue");
        bytes32 started;
        for (uint256 i; i < 8; i++) {
            if (_verifierOf(ns[i]) == 1 && _state(ns[i]) == JUDGING) started = ns[i];
        }
        _judgeBatched(started, uint8(FairBindCore.Verdict.PASS));
        require(_state(q[0]) == QUEUED && fb.getQueue(1).length == q.length, "the slot is held through the verdict");
        FairBindCore.CaseView memory c = fairbind.getCase(started);
        hv.roll(uint256(c.randomBlock) + 1);
        hv.setBlockhash(c.randomBlock, keccak256("gate"));
        fairbind.finalizeCase(started);
        require(_state(started) == uint8(FairBindCore.CaseState.FINAL), "ended");
        require(_state(q[0]) == JUDGING && fairbind.getCase(q[0]).assignedVerifierId == 1, "the end starts the head");
        require(fb.getQueue(1).length == q.length - 1, "left the queue");
    }

    function test_oneSlotStartsTheHeadAndTheVerdictStartsTheNext() public {
        bytes32[] memory ns = _slotsScenario(30_000_000, 1);
        _nextStartsOnVerdict(ns);
    }

    function test_withoutSlotsOneCaseStartsByTheException() public {
        bytes32[] memory ns = _slotsScenario(60_000_000, 0);
        _nextStartsOnVerdict(ns);
    }

    /// Verifier 1 (one slot) holds its judgment to the deadline: its queued
    /// cases stay with it. The late penalty leaves it no slot; the timed-out
    /// case moves to its next attempt elsewhere, and the head starts by the
    /// exception, still at verifier 1. The penalty records no departure.
    function test_holdingAJudgmentOrAPenaltyMovesNoQueuedCase() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        uint128[] memory bonds = _heavyFirstBonds();
        bonds[0] = 63_000_000;
        _deployBatched(_batchProfile(), t, bonds);
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](8);
        for (uint256 i; i < 8; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        _assignBatch(0);
        bytes32[] memory q = fb.getQueue(1);
        require(q.length >= 2, "two queued at verifier 1");
        bytes32 x;
        for (uint256 i; i < 8; i++) {
            if (_verifierOf(ns[i]) == 1 && _state(ns[i]) == JUDGING) x = ns[i];
        }
        hv.roll(uint256(fairbind.getCase(x).judgeDue) + 1);
        for (uint256 i; i < q.length; i++) require(fb.getBatchEntry(q[i]).verifier == 1, "still queued at verifier 1");
        hv.prank(KEEPER);
        fairbind.timeoutJudge(x);
        (BatchStore.Slots memory s, uint256 slots) = fb.getSlots(1);
        require(slots == 0 && s.departed == 0, "no slot left, no departure");
        require(_verifierOf(x) != 1 && fairbind.getCase(x).attempt == 1, "next attempt elsewhere");
        require(_state(q[0]) == JUDGING && fairbind.getCase(q[0]).assignedVerifierId == 1, "head starts by the exception");
        for (uint256 i = 1; i < q.length; i++) require(fb.getBatchEntry(q[i]).verifier == 1, "the rest stay");
    }

    // --------------------------------------------- own exit and transfers

    function transferExternal(bytes32 caseId) external {
        fb.transferQueued(caseId);
    }

    /// Verifier 1 asks to exit after batch 0's value was fixed and before
    /// batch 1's. Its batch-0 cases stay (a transfer is refused); a batch-1
    /// case whose round-0 ticket names it moves to a later round. Its queue
    /// and reservations block the exit and a full withdrawal.
    function _exitMovesOnlyLaterCases(string memory artifact) internal returns (bool) {
        batchArtifact = artifact;
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        _deployBatched(_batchProfile(), t, _heavyFirstBonds());
        hv.roll(10);
        bytes32[] memory e0 = new bytes32[](4);
        for (uint256 i; i < 4; i++) e0[i] = _purchase(G);
        hv.roll(310);
        bytes32[] memory e1 = new bytes32[](4);
        for (uint256 i; i < 4; i++) e1[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, e0);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(e0);
        _anchorOf(1, sellerId, SELLER_OWNER, e1);
        _sealOf(1, _sellers1());
        hv.roll(1050);
        _openAll(e1);
        _assignBatch(0);
        bytes32[] memory q0 = fb.getQueue(1);
        require(q0.length != 0, "batch 0 queued at verifier 1");
        hv.roll(1150);
        fairbind.requestVerifierExit(1);
        (BatchStore.Slots memory s,) = fb.getSlots(1);
        require(s.departed == 1150, "departure block");
        bytes32 value1 = _assignBatch(1);
        (,, uint64 version1,,,) = fb.getBatch(PROFILE, 1);
        bool moved;
        for (uint256 i; i < 4; i++) {
            if (_candidate(version1, value1, e1[i], 1, 0, 0) != 1) continue;
            BatchStore.Entry memory en = fb.getBatchEntry(e1[i]);
            if (_verifierOf(e1[i]) == 1 || en.round == 0) return false;
            moved = true;
        }
        require(moved, "a batch-1 case named verifier 1");
        for (uint256 i; i < q0.length; i++) {
            if (fb.getBatchEntry(q0[i]).verifier != 1) return false;
        }
        (bool transferred,) = address(this).call(abi.encodeCall(this.transferExternal, (q0[0])));
        if (transferred) return false;
        hv.roll(_now() + 1);
        hv.expectRevert(FairBindCore.ExitNotReady.selector);
        fairbind.finalizeVerifierExit(1);
        uint128 all = uint128(fairbind.getVerifier(1).bond);
        hv.expectRevert(FairBindCore.InsufficientVerifierBond.selector);
        fb.withdrawVerifierBond(1, all);
        return true;
    }

    function test_ownExitMovesOnlyCasesFixedAfterIt() public {
        require(_exitMovesOnlyLaterCases(batchArtifact), "only later cases move");
    }

    function test_exitThatMovesNothingIsCaught() public {
        require(!_exitMovesOnlyLaterCases("BatchMutants.sol:NoMoveBatch"), "mutation caught");
    }

    function test_exitThatMovesEarlierCasesIsCaught() public {
        require(!_exitMovesOnlyLaterCases("BatchMutants.sol:MoveAllBatch"), "mutation caught");
    }

    /// A withdrawal is limited by the queue's reservations; one that leaves
    /// no slot records the departure block.
    function test_withdrawalLeavingNoSlotRecordsTheDeparture() public {
        BatchStore.Terms memory t = _defaultTerms();
        t.slotValue = 30_000_000;
        _deployBatched(_batchProfile(), t, _heavyFirstBonds());
        hv.roll(50);
        fb.withdrawVerifierBond(1, 30_000_000);
        (BatchStore.Slots memory s, uint256 slots) = fb.getSlots(1);
        require(slots == 1 && s.departed == 0, "still one slot");
        hv.roll(60);
        fb.withdrawVerifierBond(1, 10_000_000);
        (s, slots) = fb.getSlots(1);
        require(slots == 0 && s.departed == 60, "no slot: departure recorded");
        (uint96 bond,,) = fb.verifierStateAt(1, 55);
        require(bond == 70_000_000, "state history");
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.Unauthorized.selector);
        fb.withdrawVerifierBond(1, 1);
    }

    // ----------------------------------------------- release clock pause

    /// A queued sample case pauses its account's release clock until it
    /// starts. A build whose queue leaves the clock running is caught.
    function _queuedCasesPause(string memory artifact) internal returns (bool) {
        batchArtifact = artifact;
        _slotsScenario(30_000_000, 1);
        uint32 bondId = _bondOfSeller(sellerId);
        uint256 queued;
        for (uint32 u = 1; u <= 14; u++) queued += fb.getQueue(u).length;
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        require(queued != 0, "a queue");
        if (waiting != queued) return false;
        uint64 before = fairbind.pausedSince(bondId, 10);
        hv.roll(_now() + 50);
        return fairbind.pausedSince(bondId, 10) == before + 50;
    }

    function test_queuedSampleCasesPauseTheReleaseClock() public {
        require(_queuedCasesPause(batchArtifact), "paused blocks");
    }

    function test_queueThatLeavesTheClockRunningIsCaught() public {
        require(!_queuedCasesPause("BatchMutants.sol:QueueNoPauseBatch"), "mutation caught");
    }

    /// Two sample cases wait for a batch value requested at 1113 (C = 1112,
    /// C + assignDelay = 1132). The keeper marks it late only at 1140; the
    /// account counts as paused from 1133. A build that pauses from the
    /// call is caught. The value then comes at 1150 and the batch is
    /// assigned at 1152: both cases start at once and the pause ends there.
    function _lateBatchValuePausesFrom1133(string memory artifact) internal returns (bool) {
        adminArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](2);
        for (uint256 i; i < 2; i++) ns[i] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
        hv.roll(1140);
        hv.prank(KEEPER);
        fb.markAssignLate(PROFILE, 0);
        uint32 bondId = _bondOfSeller(sellerId);
        if (fairbind.pausedSince(bondId, 1100) != 7) return false;
        hv.roll(1150);
        _fulfill(_assignId(0));
        hv.roll(1152);
        hv.prank(KEEPER);
        fb.assignBatch(PROFILE, 0);
        require(_state(ns[0]) == JUDGING && _state(ns[1]) == JUDGING, "both start");
        hv.roll(1160);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        return waiting == 0 && fairbind.pausedSince(bondId, 1100) == 1152 - 1133;
    }

    function test_lateBatchValuePausesFromItsBound() public {
        require(_lateBatchValuePausesFrom1133(adminArtifact), "paused from C + assignDelay + 1");
    }

    function test_lateBatchPauseFromTheCallIsCaught() public {
        require(!_lateBatchValuePausesFrom1133("BatchMutants.sol:LateStartNowAdmin"), "mutation caught");
    }

    /// Without a mark, a batch value stored after C + assignDelay still
    /// pauses the account from 1133, up to the assignment.
    function test_unmarkedLateBatchValuePausesAtAssignment() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
        hv.roll(1140);
        _fulfill(_assignId(0));
        hv.roll(1145);
        hv.prank(KEEPER);
        fb.assignBatch(PROFILE, 0);
        hv.roll(1150);
        require(fairbind.pausedSince(_bondOfSeller(sellerId), 1100) == 1145 - 1133, "paused from 1133 to the assignment");
    }

    function timeoutAssignExternal() external {
        fb.timeoutAssignValue(PROFILE, 0);
    }

    /// The exit of an unanswered batch value opens only after the first
    /// request + D_V + T_V (1113 + 30). A build that opens it after D_V is
    /// caught.
    function _exitWaitsForTheSlack(string memory artifact) internal returns (bool) {
        adminArtifact = artifact;
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openAll(ns);
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
        hv.roll(1124);
        (bool early,) = address(this).call(abi.encodeCall(this.timeoutAssignExternal, ()));
        if (early) return false;
        hv.roll(1143);
        (early,) = address(this).call(abi.encodeCall(this.timeoutAssignExternal, ()));
        if (early) return false;
        hv.roll(1144);
        (bool ok,) = address(this).call(abi.encodeCall(this.timeoutAssignExternal, ()));
        return ok && _state(ns[0]) == uint8(FairBindCore.CaseState.INCONCLUSIVE);
    }

    function test_exitOpensAfterTheResponseBoundAndTheSlack() public {
        require(_exitWaitsForTheSlack(adminArtifact), "exit after D_V + T_V");
    }

    function test_exitWithoutTheSlackIsCaught() public {
        require(!_exitWaitsForTheSlack("BatchMutants.sol:EarlyExitAdmin"), "mutation caught");
    }

    // ------------------------------------------------- unanswered values

    /// The batch value is late past C_e + assignDelay: from the keeper's call
    /// the batch's sample cases pause their account. Unanswered past the
    /// first request + D_V + T_V, the sample cases end without a verdict and
    /// without a count, the account is suspended and frozen from the
    /// earliest sale with its claim window open, and the batch's dispute
    /// ends as a progress failure.
    function test_lateBatchValuePausesAndItsExitEndsWithoutCount() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](3);
        for (uint256 i; i < 3; i++) ns[i] = _purchase(G);
        hv.roll(100);
        FairBindCore.FairBindReceipt memory r = _receipt(ns[2]);
        bytes memory rs = _sig(SELLER_KEY, fairbind.receiptDigest(r));
        hv.prank(buyer);
        fairbind.dispute(ns[2], uint8(FairBindCore.CaseTrigger.WRONG_DELIVERY), r, rs);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(800);
        _openSample(ns[0]);
        _openSample(ns[1]);
        hv.roll(1113);
        hv.prank(KEEPER);
        fb.requestAssignValue(PROFILE, 0);
        hv.roll(1132);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.markAssignLate(PROFILE, 0);
        hv.roll(1133);
        hv.prank(KEEPER);
        fb.markAssignLate(PROFILE, 0);
        uint32 bondId = _bondOfSeller(sellerId);
        (uint32 waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == 2, "the two sample cases pause");
        hv.roll(1143);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.timeoutAssignValue(PROFILE, 0);
        hv.roll(1144);
        hv.prank(KEEPER);
        fb.timeoutAssignValue(PROFILE, 0);
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.INCONCLUSIVE), "no verdict");
        require(_state(ns[2]) == uint8(FairBindCore.CaseState.INCONCLUSIVE), "the dispute ends as a progress failure");
        (waiting,,) = fairbind.getReleaseClock(bondId);
        require(waiting == 0, "pause ended");
        FairBindCore.BondView memory b = fairbind.getBond(bondId);
        require(b.failureCount == 0 && b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "no count, claim window");
        require(fairbind.getSeller(sellerId).status == uint8(FairBindCore.SellerStatus.SUSPENDED), "suspended");
        FairBindCore.FreezeSpan[] memory spans = fairbind.getFreezeSpans(bondId);
        require(spans.length == 1 && spans[0].from == 10, "frozen from the earliest sale");
        _fulfill(_assignId(0));
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.InvalidTransition.selector);
        fb.assignBatch(PROFILE, 0);
        _buildTree(ns);
        _claimWith(ns[0], _proof(ns[0]));
        require(fairbind.getPurchase(ns[0]).financialState == uint8(FairBindCore.FinancialState.REFUNDED), "claimed");
    }

    /// A late case whose AUX value never comes exits the same way.
    function test_lateValueExitEndsWithoutCount() public {
        _deployBatched(_batchProfile(), _defaultTerms(), _equalBonds());
        hv.roll(10);
        bytes32[] memory ns = new bytes32[](1);
        ns[0] = _purchase(G);
        _anchorOf(0, sellerId, SELLER_OWNER, ns);
        _sealOf(0, _sellers1());
        hv.roll(1200);
        _openSample(ns[0]);
        hv.roll(1201);
        hv.prank(KEEPER);
        fb.requestLateValue(ns[0]);
        hv.roll(1231);
        hv.prank(KEEPER);
        hv.expectRevert(FairBindCore.DeadlineNotReached.selector);
        fb.timeoutLateValue(ns[0]);
        hv.roll(1232);
        hv.prank(KEEPER);
        fb.timeoutLateValue(ns[0]);
        require(_state(ns[0]) == uint8(FairBindCore.CaseState.INCONCLUSIVE), "no verdict");
        FairBindCore.BondView memory b = fairbind.getBond(_bondOfSeller(sellerId));
        require(b.failureCount == 0 && b.freezeState == uint8(FairBindCore.FreezeState.CLAIM_OPEN), "no count");
    }
}
