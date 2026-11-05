// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { BatchShared } from "./BatchShared.sol";

/// Extension module 0 (ADR 0032): the first assignment of a batch and of a
/// late case, verifier slots and queues ordered by batch, account rank,
/// account permutation and ticket, the start of queued cases, queue moves
/// after a verifier's own exit request or withdrawal, the verifiers' state
/// history, and the pause of a late AUX value (ADR 0036).
contract FairBindBatch is BatchShared {
    uint8 public constant MODULE_KIND = 11;

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        BatchShared(token, gov, guard, treasury, rewardPool)
    { }

    event CaseBatched(bytes32 indexed caseId, uint32 indexed profileId, uint24 batch, bool late);
    event BatchAssigned(uint32 indexed profileId, uint24 indexed epoch, bytes32 value, uint64 valueBlock, uint32 cases);
    event CaseQueued(bytes32 indexed caseId, uint32 indexed verifierId, uint32 round, uint256 key);
    event CaseStarted(bytes32 indexed caseId, uint32 indexed verifierId);
    event QueueTransferred(bytes32 indexed caseId, uint32 indexed verifierId, uint32 round);
    event ValueWaitPaused(bytes32 indexed nonce, uint64 from);

    // ------------------------------------------------------ batch value

    /// Keeper call: once the batch value is stored, makes the first
    /// assignment of every case of the batch. Each account's cases are ranked
    /// by their first ticket; every case is placed in its candidate's queue,
    /// and each queue then starts its head cases while its verifier has a
    /// free slot, or one when it judges nothing.
    function assignBatch(uint32 profileId, uint24 epoch) external onlyDelegateCall nonReentrant {
        if (!_batched(profileId)) revert InvalidTransition();
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Batch storage b = l.batches[profileId][epoch];
        if (b.assigned || b.exited) revert InvalidTransition();
        uint256 close = _batchClose(profiles[profileId].parameters, epoch);
        if (block.number <= close) revert DeadlineNotReached();
        IVrfRandomness vrf = _vrf();
        bytes32 id = _assignId(profileId, epoch);
        (bool ready, bytes32 value) = vrf.valueOf(id);
        if (!ready) revert DeadlineNotReached();
        (, uint64 delivered,) = vrf.requestTimes(id);
        b.value = value;
        b.valueBlock = delivered;
        b.checkpointVersion = _batchVersion(profileId, epoch);
        b.assigned = true;
        uint256 n = b.cases.length;
        bytes32[] memory ids = new bytes32[](n);
        uint256[] memory sortKey = new uint256[](n);
        uint256 m;
        for (uint256 i; i < n; i++) {
            bytes32 caseId = b.cases[i];
            if (!_waitsForBatch(caseId)) continue;
            BatchStore.Entry storage en = l.entries[caseId];
            _valueArrived(en, close + l.terms[profileId].assignDelay, delivered);
            uint256 t0 = uint256(keccak256(abi.encode(ASSIGN_DOMAIN, value, caseId, _stageOf(caseId), uint8(0), uint32(0))));
            // Order by account, then by first ticket; insertion keeps it sorted.
            uint256 k = (uint256(en.bondId) << 224) | (t0 >> 32);
            uint256 j = m;
            while (j != 0 && sortKey[j - 1] > k) {
                sortKey[j] = sortKey[j - 1];
                ids[j] = ids[j - 1];
                j--;
            }
            sortKey[j] = k;
            ids[j] = caseId;
            m++;
        }
        uint32[] memory touched = new uint32[](m);
        uint256 touchedCount;
        uint32 rank;
        uint32 lastBond;
        for (uint256 i; i < m; i++) {
            BatchStore.Entry storage en = l.entries[ids[i]];
            rank = en.bondId == lastBond && i != 0 ? rank + 1 : 1;
            lastBond = en.bondId;
            en.rank = rank;
            _setKey(en, epoch, rank, value, ids[i]);
            en.fixedBlock = delivered;
            if (en.kind == KIND_PURCHASE) cases[ids[i]].randomness = value;
            uint32 u = _place(ids[i], 0);
            if (u == 0) {
                _exhausted(ids[i]);
                continue;
            }
            uint256 c;
            while (c < touchedCount && touched[c] != u) c++;
            if (c == touchedCount) touched[touchedCount++] = u;
        }
        for (uint256 i; i < touchedCount; i++) _startHeads(touched[i]);
        emit BatchAssigned(profileId, epoch, value, delivered, uint32(m));
    }

    /// Keeper call: the first assignment of a late case with its AUX value.
    /// Its batch and rank stay as fixed at its opening; the permutation is
    /// the batch's when the batch was assigned, else the AUX value's.
    function assignLate(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[nonce];
        if (!en.late || cases[nonce].state != uint8(CaseState.BATCHED)) revert NotRegistered();
        IVrfRandomness vrf = _vrf();
        bytes32 id = keccak256(abi.encode(VRF_AUX, _lateInput(nonce, en.lateBlock)));
        (bool ready, bytes32 value) = vrf.valueOf(id);
        if (!ready) revert DeadlineNotReached();
        (, uint64 delivered,) = vrf.requestTimes(id);
        _valueArrived(en, uint256(en.lateBlock) + vrf.delayBlocks(), delivered);
        BatchStore.Batch storage b = l.batches[purchases[nonce].profileId][en.batch];
        _setKey(en, en.batch, en.rank, b.assigned ? b.value : value, nonce);
        // The permutation took the batch value; the ticket is this case's own.
        en.key = (en.key & ~uint256(type(uint136).max))
            | (uint256(keccak256(abi.encode(ASSIGN_DOMAIN, value, nonce, uint8(JudgmentStage.INITIAL), uint8(0), uint32(0)))) >> 120);
        en.fixedBlock = delivered;
        cases[nonce].randomness = value;
        uint32 u = _place(nonce, 0);
        if (u == 0) _exhausted(nonce);
        else _startHeads(u);
    }

    // ------------------------------------------------- queue moves, funds

    /// Keeper call: moves a queued case whose verifier asked to exit, or
    /// withdrew to no slot, in a block before the case's candidate was fixed,
    /// to the next round of the same ticket. Cases fixed earlier stay.
    function transferQueued(bytes32 caseId) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        uint32 u = en.verifier;
        if (u == 0) revert InvalidTransition();
        if (!_moves(l.slots[u].departed, en.fixedBlock)) revert InvalidTransition();
        _unlink(caseId, u);
        emit QueueTransferred(caseId, u, en.round);
        uint32 next = _place(caseId, en.round + 1);
        if (next == 0) _exhausted(caseId);
        else _startHeads(next);
    }

    /// The verifier withdraws part of its bond. The rest must cover its queue
    /// reservations and penalty reserves, and its locked liability at the
    /// exposure of the slot profile. A withdrawal that leaves no slot moves,
    /// from this block, the cases whose candidate is fixed later.
    function withdrawVerifierBond(uint32 verifierId, uint128 amount) external onlyDelegateCall nonReentrant {
        VerifierView storage v = verifiers[verifierId];
        if (msg.sender != v.owner) revert Unauthorized();
        if (v.status != uint8(VerifierStatus.ACTIVE) && v.status != uint8(VerifierStatus.EXITING)) revert VerifierInactive();
        if (amount == 0 || amount > v.bond) revert InvalidConfiguration();
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Slots storage sl = l.slots[verifierId];
        uint256 rest = v.bond - amount;
        uint256 penalties = verifierCapital[verifierId].reservedPenalties;
        if (rest < uint256(sl.reserved) + penalties) revert InsufficientVerifierBond();
        if (v.lockedLiability != 0) {
            uint256 fraction = profiles[l.slotProfile].parameters.verifierExposurePpm;
            if ((rest - penalties) * fraction < v.lockedLiability * PPM) revert InsufficientVerifierBond();
        }
        _noteVerifier(verifierId);
        v.bond = rest;
        if (sl.departed == 0 && _slotCount(verifierId) == 0) sl.departed = uint64(block.number);
        _transfer(v.owner, amount);
        emit VerifierBondChanged(verifierId, v.bond);
    }

    /// Keeper call: the AUX value a waiting sample case needs (its late first
    /// assignment or its review stage) is missing past its registration
    /// block + D_S. The case pauses its account from the block after that
    /// bound until the value is used or the case exits.
    function markValueLate(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[nonce];
        if (en.paused || en.kind != KIND_PURCHASE || cases[nonce].trigger != uint8(CaseTrigger.SAMPLE)) revert InvalidTransition();
        uint64 t;
        bytes32 id;
        if (en.late && cases[nonce].state == uint8(CaseState.BATCHED)) {
            t = en.lateBlock;
            id = keccak256(abi.encode(VRF_AUX, _lateInput(nonce, t)));
        } else {
            BatchStore.ReviewUse storage u = _reviewWaitingUse(nonce);
            t = u.registered;
            id = _reviewUseId(nonce, u);
        }
        IVrfRandomness vrf = _vrf();
        uint256 due = uint256(t) + vrf.delayBlocks();
        if (block.number <= due) revert DeadlineNotReached();
        (bool ready,) = vrf.valueOf(id);
        if (ready) revert InvalidTransition();
        en.paused = true;
        uint256 from = _lateStart(due);
        _pauseFrom(_bondOf(nonce), from);
        emit ValueWaitPaused(nonce, uint64(from));
    }

    // --------------------------------------------------------------- hooks

    /// Hook operations of this module: enqueue, slot freed, case leaves,
    /// start heads, note a verifier, sample case ended, join and place a
    /// seller proof's case.
    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op == HOOK_ENQUEUE) {
            bytes32 nonce = bytes32(arg);
            if (BatchStore.layout().entries[nonce].kind == 0) {
                _join(nonce);
                return;
            }
            _placeAndStart(nonce);
        } else if (op == HOOK_SLOT_FREED) {
            BatchStore.layout().slots[uint32(arg)].active--;
            _startHeads(uint32(arg));
        } else if (op == HOOK_CASE_LEAVES) {
            BatchStore.Entry storage en = BatchStore.layout().entries[bytes32(arg)];
            if (en.verifier != 0) _unlink(bytes32(arg), en.verifier);
            if (en.paused) {
                en.paused = false;
                _clockWaitEnds(bytes32(arg));
            }
        } else if (op == HOOK_START_HEADS) {
            _startHeads(uint32(arg));
        } else if (op == HOOK_NOTE) {
            _note(uint32(arg));
        } else if (op == HOOK_SAMPLE_ENDED) {
            _sampleEnd(bytes32(arg));
        } else if (op == HOOK_JOIN_PROOF) {
            _joinProof(bytes32(arg));
        } else if (op == HOOK_PLACE_PROOF) {
            _placeAndStart(_proofCase(bytes32(arg)));
        } else {
            _unknownHook();
        }
    }

    function hookOps() external pure returns (uint256) {
        return (1 << HOOK_ENQUEUE) | (1 << HOOK_SLOT_FREED) | (1 << HOOK_CASE_LEAVES) | (1 << HOOK_START_HEADS)
            | (1 << HOOK_NOTE) | (1 << HOOK_SAMPLE_ENDED) | (1 << HOOK_JOIN_PROOF) | (1 << HOOK_PLACE_PROOF);
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](14);
        s[0] = this.assignBatch.selector;
        s[1] = this.assignLate.selector;
        s[2] = this.transferQueued.selector;
        s[3] = this.withdrawVerifierBond.selector;
        s[4] = this.getBatchTerms.selector;
        s[5] = this.getBatch.selector;
        s[6] = this.getBatchEntry.selector;
        s[7] = this.getQueue.selector;
        s[8] = this.getSlots.selector;
        s[9] = this.verifierStateAt.selector;
        s[10] = this.batchClose.selector;
        s[11] = this.batchOf.selector;
        s[12] = this.proofCaseId.selector;
        s[13] = this.markValueLate.selector;
    }

    function _placeAndStart(bytes32 caseId) private {
        uint32 u = _place(caseId, 0);
        if (u == 0) _exhausted(caseId);
        else _startHeads(u);
    }

    /// Keeps the verifier's state before a change in this block.
    function _note(uint32 id) private {
        BatchStore.VState[] storage h = BatchStore.layout().history[id];
        uint256 n = h.length;
        if (n != 0 && h[n - 1].endBlock == block.number) return;
        VerifierView storage v = verifiers[id];
        h.push(BatchStore.VState(uint64(block.number), uint96(v.bond), v.status, uint64(v.classBitmap)));
    }

    /// A counted sample case ended.
    function _sampleEnd(bytes32 nonce) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[nonce];
        en.counted = false;
        l.proofAccounts[en.bondId].openSamples--;
        if (l.sideGainOpen[nonce]) {
            l.sideGainOpen[nonce] = false;
            l.sideGain[en.bondId].open--;
        }
    }

    /// A seller proof's judgment case joins the batch of this block.
    function _joinProof(bytes32 nonce) private {
        bytes32 caseId = _proofCase(nonce);
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        PurchaseView storage purchase = purchases[nonce];
        uint24 e = _batchOf(profiles[purchase.profileId].parameters, block.number);
        en.kind = KIND_PROOF;
        en.ref = nonce;
        en.bondId = sellers[purchase.sellerId].viewData.bondId;
        en.batch = e;
        l.batches[purchase.profileId][e].cases.push(caseId);
        l.batchCount[purchase.profileId][e][en.bondId]++;
        l.proofs[nonce].state = BatchStore.P_BATCHED;
        emit CaseBatched(caseId, purchase.profileId, e, false);
    }

    // ------------------------------------------------------------ placing

    /// A case of a batched profile is opened: a sample case joins the batch
    /// of its epoch when it opens by the batch's close, and waits for a late
    /// value otherwise, with the rank after the account's cases of the batch;
    /// a dispute joins the batch of its opening block.
    function _join(bytes32 nonce) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[nonce];
        CaseView storage c = cases[nonce];
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        uint32 bondId = sellers[purchase.sellerId].viewData.bondId;
        en.kind = KIND_PURCHASE;
        en.ref = nonce;
        en.bondId = bondId;
        uint24 e;
        bool late;
        if (c.trigger == uint8(CaseTrigger.SAMPLE)) {
            e = purchase.epoch;
            en.counted = true;
            l.proofAccounts[bondId].openSamples++;
            late = block.number > _batchClose(profile, e);
        } else {
            e = _batchOf(profile, block.number);
        }
        en.batch = e;
        if (late) {
            en.late = true;
            en.lateBlock = uint64(block.number);
            en.rank = ++l.batchCount[purchase.profileId][e][bondId];
        } else {
            l.batches[purchase.profileId][e].cases.push(nonce);
            l.batchCount[purchase.profileId][e][bondId]++;
        }
        c.state = uint8(CaseState.BATCHED);
        emit CaseBatched(nonce, purchase.profileId, e, late);
    }

    function _stageOf(bytes32 caseId) private view returns (uint8) {
        return BatchStore.layout().entries[caseId].kind == KIND_PROOF ? 0 : cases[caseId].stage;
    }

    /// key = batch (24 bits) | rank (32) | account permutation place (64) |
    /// first ticket, high 136 bits.
    function _setKey(BatchStore.Entry storage en, uint24 e, uint32 rank, bytes32 permValue, bytes32 caseId) private {
        uint256 perm = uint64(uint256(keccak256(abi.encode(PERMUTATION_DOMAIN, permValue, en.bondId))));
        uint256 t0 = uint256(keccak256(abi.encode(ASSIGN_DOMAIN, permValue, caseId, _stageOf(caseId), uint8(0), uint32(0))));
        en.key = (uint256(e) << 232) | (uint256(rank) << 200) | (perm << 136) | (t0 >> 120);
    }

    struct Draw {
        bytes32 value;
        uint64 version;
        uint64 fixedBlock;
        uint8 stage;
        uint8 attempt;
        uint32 profileId;
        uint256 liability;
    }

    /// The value, checkpoint and fixing block the case's current stage and
    /// attempt draw from: the batch value (or the late value) for the first
    /// stage, the redraw value and its checkpoint after a wait, the review
    /// value for later stages; a seller proof draws from its batch.
    function _draw(bytes32 caseId) private view returns (Draw memory d) {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        PurchaseView storage purchase = purchases[en.ref];
        d.profileId = purchase.profileId;
        d.liability = purchase.value + profiles[d.profileId].parameters.maxReviewCost;
        if (en.kind == KIND_PROOF) {
            BatchStore.Batch storage b = l.batches[d.profileId][en.batch];
            d.value = b.value;
            d.version = b.checkpointVersion;
            d.fixedBlock = b.valueBlock;
            d.attempt = l.proofs[en.ref].attempt;
            return d;
        }
        CaseView storage c = cases[caseId];
        d.stage = c.stage;
        d.attempt = c.attempt;
        AssignmentWait storage wait = assignmentWaits[caseId];
        d.version = wait.checkpointVersion;
        bool waited = d.version != 0;
        if (!waited) {
            BatchStore.Batch storage b = l.batches[d.profileId][en.batch];
            d.version = b.assigned ? b.checkpointVersion : _batchVersion(d.profileId, en.batch);
        }
        if (d.stage != uint8(JudgmentStage.INITIAL)) {
            d.value = c.randomness;
            d.fixedBlock = c.randomBlock;
        } else if (waited) {
            d.value = wait.randomness;
            SamplingStore.RedrawUse storage use = SamplingStore.layout().redrawUses[caseId];
            (, d.fixedBlock,) = _vrf().requestTimes(
                keccak256(abi.encode(VRF_AUX, _redrawInput(caseId, use.redraw, use.registeredBlock)))
            );
        } else {
            d.value = c.randomness;
            d.fixedBlock = en.fixedBlock;
        }
    }

    /// Searches the case's checkpoint from `startRound`: each round's ticket
    /// names a verifier; one that already took part in the case is skipped,
    /// and so is one whose own exit request or withdrawal came in a block
    /// before the candidate was fixed (the case moves to the next round).
    /// The first other verifier gets the case in its queue. Returns zero when
    /// every round is used.
    function _place(bytes32 caseId, uint32 startRound) private returns (uint32) {
        Draw memory d = _draw(caseId);
        VerifierCheckpoint storage cp = verifierCheckpoints[d.profileId][d.version];
        uint256 total = cp.totalEffectiveWeight;
        if (total == 0) return 0;
        BatchStore.Layout storage l = BatchStore.layout();
        uint32 rounds = profiles[d.profileId].parameters.minVerifiers;
        for (uint32 round = startRound; round < rounds; round++) {
            uint256 ticket = uint256(keccak256(abi.encode(ASSIGN_DOMAIN, d.value, _ticketCase(caseId), d.stage, d.attempt, round))) % total;
            (uint32 u,) = _ticketVerifier(cp, ticket);
            if (caseParticipation[caseId][u]) continue;
            if (_moves(l.slots[u].departed, d.fixedBlock)) {
                emit QueueTransferred(caseId, u, round);
                continue;
            }
            caseParticipation[caseId][u] = true;
            _enqueue(caseId, u, round, d.liability, d.fixedBlock);
            return u;
        }
        return 0;
    }

    /// The case identifier a ticket draws for. Every production build: the
    /// case itself, so a case's candidates depend on its value alone. A
    /// mutation build of the tests overrides it.
    function _ticketCase(bytes32 caseId) internal view virtual returns (bytes32) {
        return caseId;
    }

    /// Whether a case whose candidate was fixed in block fixedBlock leaves a
    /// verifier that asked to exit, or withdrew to no slot, in block
    /// departed: only when that block came first. A mutation build of the
    /// tests overrides it.
    function _moves(uint64 departed, uint64 fixedBlock) internal pure virtual returns (bool) {
        return departed != 0 && departed < fixedBlock;
    }

    /// Every round was used: a first-stage sample case waits for the next
    /// checkpoint (ADR 0028), another case ends as a progress failure, a
    /// seller proof ends without a verdict.
    function _exhausted(bytes32 caseId) private {
        BatchStore.Entry storage en = BatchStore.layout().entries[caseId];
        if (en.kind == KIND_PROOF) {
            _hook(HOOK_PROOF_EXIT, uint256(en.ref));
            return;
        }
        CaseView storage c = cases[caseId];
        if (c.stage == uint8(JudgmentStage.INITIAL) && c.trigger == uint8(CaseTrigger.SAMPLE)) {
            Draw memory d = _draw(caseId);
            _waitForCheckpoint(caseId, d.version);
            return;
        }
        _hook(HOOK_PROGRESS, uint256(caseId));
    }

    /// Puts the case in u's queue in key order and reserves for it the lower
    /// of its liability and u's unreserved bond. A waiting sample case pauses
    /// its account's release clock until it starts.
    function _enqueue(bytes32 caseId, uint32 u, uint32 round, uint256 liability, uint64 fixedBlock) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        BatchStore.Slots storage sl = l.slots[u];
        en.verifier = u;
        en.round = round;
        en.fixedBlock = fixedBlock;
        uint256 bond = verifiers[u].bond;
        uint256 free = bond > sl.reserved ? bond - sl.reserved : 0;
        uint256 reserve = liability < free ? liability : free;
        en.reserve = uint96(reserve);
        sl.reserved += uint96(reserve);
        sl.queued++;
        bytes32 at = sl.tail;
        while (at != bytes32(0) && l.entries[at].key > en.key) at = l.entries[at].prev;
        en.prev = at;
        if (at == bytes32(0)) {
            en.next = sl.head;
            sl.head = caseId;
        } else {
            en.next = l.entries[at].next;
            l.entries[at].next = caseId;
        }
        if (en.next == bytes32(0)) sl.tail = caseId;
        else l.entries[en.next].prev = caseId;
        if (en.kind == KIND_PROOF) {
            l.proofs[en.ref].state = BatchStore.P_QUEUED;
        } else {
            CaseView storage c = cases[caseId];
            c.state = uint8(CaseState.QUEUED);
            if (_queuePauses(c) && !en.paused) {
                en.paused = true;
                _clockWaitStarts(caseId);
            }
        }
        emit CaseQueued(caseId, u, round, en.key);
    }

    /// Whether a queued case pauses its account's release clock: a sample
    /// case and its review stages. A mutation build of the tests overrides it.
    function _queuePauses(CaseView storage c) internal view virtual returns (bool) {
        return c.trigger == uint8(CaseTrigger.SAMPLE);
    }

    /// Takes the case out of u's queue and frees its reservation.
    function _unlink(bytes32 caseId, uint32 u) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Entry storage en = l.entries[caseId];
        BatchStore.Slots storage sl = l.slots[u];
        if (en.prev == bytes32(0)) sl.head = en.next;
        else l.entries[en.prev].next = en.next;
        if (en.next == bytes32(0)) sl.tail = en.prev;
        else l.entries[en.next].prev = en.prev;
        en.prev = bytes32(0);
        en.next = bytes32(0);
        sl.reserved -= en.reserve;
        en.reserve = 0;
        sl.queued--;
        en.verifier = 0;
    }

    /// Starts u's head cases while u judges fewer than its slots, and one
    /// when it judges none whatever its slots or state.
    function _startHeads(uint32 u) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Slots storage sl = l.slots[u];
        while (sl.head != bytes32(0)) {
            if (sl.active != 0 && sl.active >= _slotCount(u)) return;
            bytes32 caseId = sl.head;
            BatchStore.Entry storage en = l.entries[caseId];
            _unlink(caseId, u);
            sl.active++;
            if (en.paused) {
                en.paused = false;
                _clockWaitEnds(caseId);
            }
            if (en.kind == KIND_PROOF) _startProof(en.ref, u);
            else _startCase(caseId, u);
            emit CaseStarted(caseId, u);
        }
    }

    /// The assignment write of a started purchase case: the liability is
    /// locked and the judgment window opens now.
    function _startCase(bytes32 nonce, uint32 u) private {
        CaseView storage c = cases[nonce];
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        uint256 liability = purchase.value + profile.maxReviewCost;
        uint256 reserve = _lock(u, liability, profile);
        assignmentHistory[nonce].push(AssignmentData(u, c.stage, c.attempt, 0, false, false, false, false, bytes32(0), liability, reserve));
        assignmentLiability[nonce] = liability;
        c.assignedVerifierId = u;
        c.judgeDue = uint64(block.number + deadlineConfigs[profile.deadlineConfigId].judgeBlocks);
        c.state = c.stage == uint8(JudgmentStage.INITIAL) ? uint8(CaseState.JUDGING)
            : c.stage == uint8(JudgmentStage.PARTY) ? uint8(CaseState.PARTY_REVIEW)
            : c.stage == uint8(JudgmentStage.AUTO) ? uint8(CaseState.AUTO_REVIEW)
            : uint8(CaseState.TIEBREAK);
        emit VerifierAssigned(nonce, c.stage, c.attempt, u, c.judgeDue);
    }

    /// A seller proof's judgment starts with verifier u.
    function _startProof(bytes32 nonce, uint32 u) private {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        PurchaseView storage purchase = purchases[nonce];
        ServiceProfileInput storage profile = profiles[purchase.profileId].parameters;
        _lock(u, purchase.value + profile.maxReviewCost, profile);
        pr.state = BatchStore.P_JUDGING;
        pr.verifier = u;
        pr.judgeDue = uint64(block.number + deadlineConfigs[profile.deadlineConfigId].judgeBlocks);
    }

    /// Locks the liability and the penalty reserve of one started judgment.
    function _lock(uint32 u, uint256 liability, ServiceProfileInput storage profile) private returns (uint256 reserve) {
        VerifierView storage verifier = verifiers[u];
        VerifierCapital storage capital = verifierCapital[u];
        reserve = profile.verifierLatePenalty > profile.verifierWrongPenalty
            ? profile.verifierLatePenalty : profile.verifierWrongPenalty;
        uint256 cap = verifier.lockedLiability == 0 ? profile.verifierBondCap
            : _effectiveBond(capital.conservativeCap, profile.verifierBondCap);
        uint32 fraction = verifier.lockedLiability == 0 || profile.verifierExposurePpm < capital.conservativeFraction
            ? profile.verifierExposurePpm : capital.conservativeFraction;
        capital.reservedPenalties += reserve;
        capital.conservativeCap = cap;
        capital.conservativeFraction = fraction;
        verifier.lockedLiability += liability;
    }

    // --------------------------------------------------------------- views

    function getBatchTerms(uint32 profileId) external view onlyDelegateCall returns (BatchStore.Terms memory) {
        return BatchStore.layout().terms[profileId];
    }

    function getBatch(uint32 profileId, uint24 epoch)
        external
        view
        onlyDelegateCall
        returns (bytes32 value, uint64 valueBlock, uint64 checkpointVersion, bool assigned, bool exited, bytes32[] memory list)
    {
        BatchStore.Batch storage b = BatchStore.layout().batches[profileId][epoch];
        return (b.value, b.valueBlock, b.checkpointVersion, b.assigned, b.exited, b.cases);
    }

    function getBatchEntry(bytes32 caseId) external view onlyDelegateCall returns (BatchStore.Entry memory) {
        return BatchStore.layout().entries[caseId];
    }

    function getQueue(uint32 verifierId) external view onlyDelegateCall returns (bytes32[] memory list) {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Slots storage sl = l.slots[verifierId];
        list = new bytes32[](sl.queued);
        bytes32 at = sl.head;
        for (uint256 i; at != bytes32(0); i++) {
            list[i] = at;
            at = l.entries[at].next;
        }
    }

    function getSlots(uint32 verifierId) external view onlyDelegateCall returns (BatchStore.Slots memory s, uint256 slots) {
        return (BatchStore.layout().slots[verifierId], _slotCount(verifierId));
    }

    function verifierStateAt(uint32 verifierId, uint64 x) external view onlyDelegateCall returns (uint96, uint8, uint64) {
        return _stateAt(verifierId, x);
    }

    function batchClose(uint32 profileId, uint24 epoch) external view onlyDelegateCall returns (uint256) {
        return _batchClose(profiles[profileId].parameters, epoch);
    }

    function batchOf(uint32 profileId, uint64 atBlock) external view onlyDelegateCall returns (uint24) {
        return _batchOf(profiles[profileId].parameters, atBlock);
    }

    function proofCaseId(bytes32 nonce) external pure returns (bytes32) {
        return _proofCase(nonce);
    }
}
