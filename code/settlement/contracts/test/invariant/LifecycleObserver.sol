// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBind } from "../../src/FairBind.sol";
import { FairBindCore } from "../../src/FairBindCore.sol";
import { Inv } from "./InvariantBase.sol";

interface InvToken {
    function balanceOf(address account) external view returns (uint256);
}

/// Ghost state of the stateful suite. The handler brackets every action with
/// begin() and end(); end() compares the contract with independent models of
/// the bond bucket, the failure and judged counters and the slash, and checks
/// the transition rules that need the state before and after one action. The
/// check* views hold the state invariants read by the invariant functions.
contract LifecycleObserver {
    uint8 internal constant F_DEFERRED = uint8(FairBindCore.FinancialState.DEFERRED);
    uint8 internal constant F_HELD = uint8(FairBindCore.FinancialState.HELD);
    uint8 internal constant F_REFUNDABLE = uint8(FairBindCore.FinancialState.REFUNDABLE);
    uint8 internal constant F_REFUNDED = uint8(FairBindCore.FinancialState.REFUNDED);
    uint8 internal constant F_RELEASABLE = uint8(FairBindCore.FinancialState.RELEASABLE);
    uint8 internal constant F_RELEASED = uint8(FairBindCore.FinancialState.RELEASED);
    uint8 internal constant F_FORFEITED = uint8(FairBindCore.FinancialState.FORFEITED);
    uint8 internal constant F_FROZEN_CLAIMABLE = uint8(FairBindCore.FinancialState.FROZEN_CLAIMABLE);
    uint8 internal constant Z_FROZEN = uint8(FairBindCore.FreezeState.FROZEN);
    uint8 internal constant Z_OPEN = uint8(FairBindCore.FreezeState.CLAIM_OPEN);
    uint8 internal constant S_ACTIVE = uint8(FairBindCore.SellerStatus.ACTIVE);
    uint8 internal constant S_SUSPENDED = uint8(FairBindCore.SellerStatus.SUSPENDED);
    uint8 internal constant S_SANCTIONED = uint8(FairBindCore.SellerStatus.SANCTIONED);

    // Coverage counters recorded by the observer; the handler uses 1 to 52.
    uint8 internal constant H_INCONCLUSIVE_FREEZE = 200;
    uint8 internal constant H_SANCTION = 201;
    uint8 internal constant H_OVERTURN = 202;
    uint8 internal constant H_WINDOW_MOVED = 203;
    /// A seller-appealed review that could not progress upheld the initial
    /// FAIL (rule D2-15, ADR 0024).
    uint8 internal constant H_UPHELD = 204;

    struct Bucket {
        uint256 level;
        uint64 updated;
        uint32 scale;
    }

    struct Counters {
        uint32 failures;
        uint64 failureStart;
        uint32 windowScale;
        bool sanctioned;
        uint32 judged;
        uint32 inconclusive;
        uint64 judgedStart;
    }

    FairBind public immutable fb;
    InvToken public immutable token;
    bool public immutable freezeEnabled;
    /// Profile flag: the freeze lands at the initial FAIL (pending triggers)
    /// or only at the confirmed failure (ADR 0020).
    bool public immutable freezeOnInitialFail;
    address public writer;

    uint256 internal immutable capacity;
    uint256 internal immutable refill;
    uint256 internal immutable penalty;
    uint256 internal immutable failureLimit;
    /// Failures per unit of scale at which a window sanctions; zero is none
    /// (design 2 terms with sanctionLimit = 0, ADR 0027).
    uint256 internal immutable sanctionLimit;
    uint256 internal immutable failureWindow;
    uint256 internal immutable judgedWindow;
    uint256 internal immutable maxInconclusivePpm;
    uint256 internal immutable claimWindow;
    uint256 internal immutable retention;
    uint256 internal immutable epochOrigin;
    uint256 internal immutable epochBlocks;

    uint32[] public bondIds;
    uint32[] public sellerIds;
    mapping(uint32 => uint32) public bondOfSeller;
    mapping(uint32 => uint32) public registrationsOf;
    bytes32[] public nonces;
    uint256[] public epochKeys;
    mapping(uint256 => bool) internal epochSeen;
    mapping(uint256 => uint8) internal lastAnchor;
    mapping(bytes32 => uint8) internal lastState;
    mapping(bytes32 => uint8) internal lastStored;
    mapping(bytes32 => uint8) internal lastCase;
    mapping(bytes32 => uint8) internal lastInitial;
    // Model of the pending initial-FAIL triggers (ADR 0015): a case that has
    // shown an initial FAIL and has not reached a terminal state.
    mapping(bytes32 => bool) internal pendingTrigger;
    mapping(uint32 => uint32) public pendingTriggers;
    mapping(uint32 => uint256) public settledTotal;
    mapping(uint32 => Bucket) internal bucket;
    mapping(uint32 => Counters) internal model;
    mapping(uint32 => uint64) public lastConfirm;
    /// Model of the narrow freeze (ADR 0030): every confirmed failure of a
    /// bond account at block t tied to settlement block c holds the entries
    /// settled in [c, t]. The windows are kept for the whole run, so that the
    /// negative invariant can check every release against every confirmed
    /// failure. c is the settlement block of the purchase the failure refunds,
    /// the first block of the epoch of a missed anchor, or the settlement
    /// block of the first inconclusive sale of an inconclusive window above
    /// its threshold.
    mapping(uint32 => uint64[]) internal confFrom;
    mapping(uint32 => uint64[]) internal confThrough;
    /// Spans [s, t] that an initial FAIL adds under freezeOnInitialFail (ADR
    /// 0030 decision 1): s is the settlement block of its purchase and t the
    /// block of the freeze. Recorded only when the account was not in an open
    /// claim window, where an initial FAIL adds no span.
    mapping(uint32 => uint64[]) internal initFrom;
    mapping(uint32 => uint64[]) internal initThrough;
    /// Block at which the account's current freeze began (FROZEN or
    /// CLAIM_OPEN from a state that was neither). The spans of the open freeze
    /// are the model windows recorded since then.
    mapping(uint32 => uint64) public episodeStart;
    /// Settlement block of the first inconclusive sale of the bond's current
    /// judged window (the model of inconclusiveFloor).
    mapping(uint32 => uint64) internal incFloor;
    /// Entries whose forfeiture has been counted in newForfeit (ADR 0030: an
    /// entry of an itemized window counts when releasePurchase sweeps it).
    mapping(bytes32 => bool) internal forfeitCounted;
    mapping(uint32 => uint256) public slashes;
    /// Forfeitures and per-failure deductions the contract must hold locked
    /// (ADR 0022).
    uint256 public lockedExpected;
    /// Model of the recent scale high of each bond account (ADR 0022).
    mapping(uint32 => FairBindCore.ScaleHigh) internal high;

    /// Model of the release clock of each bond account (ADR 0029): the
    /// number of its cases in WAITING_ASSIGNMENT, and its pauses [start, end)
    /// with end zero while one is open. syncWaits updates it whenever a wait
    /// may have begun or ended, before the block moves.
    mapping(uint32 => uint256) public modelWaiting;
    mapping(uint32 => uint64[]) internal pauseStarts;
    mapping(uint32 => uint64[]) internal pauseEnds;

    mapping(uint8 => uint256) public violations;
    mapping(uint8 => string) public firstViolation;
    mapping(uint8 => uint256) public hits;

    // Snapshot of one action.
    mapping(uint32 => FairBindCore.BondView) internal pre;
    /// Scale factor the contract holds as the action's deductions proceed.
    mapping(uint32 => uint32) internal curScale;
    mapping(uint32 => uint8) internal preSeller;
    mapping(uint32 => uint256) internal topUps;
    mapping(uint32 => uint256) internal newForfeit;
    mapping(uint32 => bool) internal lateForfeit;
    mapping(uint32 => uint256) internal expectedSlash;
    mapping(uint32 => uint32) internal sanctionedBy;
    uint256 internal prePool;
    uint256 internal preTreasury;
    uint256[15] internal preVerifierBond;
    uint32[] internal counted;
    uint32[] internal confirmed;
    /// Start c of the freeze of each entry of `confirmed` (ADR 0030).
    uint64[] internal confirmedFrom;
    uint32[] internal initialFails;
    /// Settlement block of the purchase of each entry of `initialFails`, and
    /// of the trigger of a successful freezeSellerDeferred.
    uint32[] internal initialBonds;
    uint64[] internal initialFrom;
    uint32[] internal judgedSellers;
    uint8[] internal judgedResults;
    bytes32[] internal judgedNonces;

    constructor(FairBind fairbind, address tokenAddress, bool freeze) {
        fb = fairbind;
        token = InvToken(tokenAddress);
        freezeEnabled = freeze;
        writer = msg.sender;
        FairBindCore.ServiceProfileInput memory p = Inv.profile();
        freezeOnInitialFail = p.freezeOnInitialFail;
        capacity = p.bucketCapacity;
        refill = p.refillPpmPerBlock;
        penalty = p.sellerPenalty;
        failureLimit = p.failureLimit;
        sanctionLimit = Inv.sanctionLimit();
        failureWindow = p.failureWindowBlocks;
        judgedWindow = p.inconclusiveWindowBlocks;
        maxInconclusivePpm = p.maxInconclusivePpm;
        claimWindow = p.claimWindowBlocks;
        retention = p.retentionBlocks;
        epochOrigin = p.epochOrigin;
        epochBlocks = p.epochBlocks;
    }

    modifier onlyWriter() {
        require(msg.sender == writer, "writer");
        _;
    }

    function setWriter(address handler) external onlyWriter {
        writer = handler;
    }

    // ------------------------------------------------------------ registration

    function addBond(uint32 bondId) external onlyWriter {
        bondIds.push(bondId);
        FairBindCore.BondView memory b = fb.getBond(bondId);
        bucket[bondId] = Bucket(b.bucketBalancePpm, b.bucketUpdatedBlock, b.scaleFactor);
    }

    function addSeller(uint32 sellerId) external onlyWriter {
        uint32 bondId = fb.getSeller(sellerId).bondId;
        sellerIds.push(sellerId);
        bondOfSeller[sellerId] = bondId;
        registrationsOf[bondId]++;
        preSeller[sellerId] = fb.getSeller(sellerId).status;
    }

    function recordSettle(bytes32 nonce) external onlyWriter {
        FairBindCore.PurchaseView memory p = fb.getPurchase(nonce);
        nonces.push(nonce);
        settledTotal[bondOfSeller[p.sellerId]] += p.value;
        uint256 ek = (uint256(p.sellerId) << 24) | p.epoch;
        if (!epochSeen[ek]) {
            epochSeen[ek] = true;
            epochKeys.push(ek);
        }
        _consume(bondOfSeller[p.sellerId]);
    }

    function noteTopUp(uint32 bondId, uint256 amount) external onlyWriter {
        topUps[bondId] += amount;
    }

    function hit(uint8 branch) external onlyWriter {
        hits[branch]++;
    }

    function flag(uint8 category, string calldata what) external onlyWriter {
        _flag(category, what);
    }

    function _flag(uint8 category, string memory what) internal {
        if (violations[category] == 0) firstViolation[category] = what;
        violations[category]++;
    }

    function nonceCount() external view returns (uint256) {
        return nonces.length;
    }

    function epochCount() external view returns (uint256) {
        return epochKeys.length;
    }

    function sellerCount() external view returns (uint256) {
        return sellerIds.length;
    }

    function bondCount() external view returns (uint256) {
        return bondIds.length;
    }

    // ------------------------------------------------------------ bucket model

    /// The model level of the shared bucket of a bond account at this block.
    function modelLevel(uint32 bondId) public view returns (uint256) {
        Bucket memory k = bucket[bondId];
        uint256 cap = capacity * k.scale * Inv.PPM;
        uint256 level = k.level + (block.number - k.updated) * refill * k.scale;
        return level > cap ? cap : level;
    }

    function _consume(uint32 bondId) internal {
        uint256 level = modelLevel(bondId);
        if (level < Inv.PPM) {
            _flag(Inv.C_BUCKET, string.concat("settlement admitted with the model bucket below one unit, bond ",
                Inv.toString(bondId), " block ", Inv.toString(block.number)));
            level = Inv.PPM;
        }
        bucket[bondId] = Bucket(level - Inv.PPM, uint64(block.number), bucket[bondId].scale);
    }

    function _rescale(uint32 bondId, uint32 scale) internal {
        uint256 level = modelLevel(bondId);
        uint256 cap = capacity * scale * Inv.PPM;
        bucket[bondId] = Bucket(level > cap ? cap : level, uint64(block.number), scale);
    }

    // ------------------------------------------------------- release clock

    function syncWaits() external onlyWriter {
        _syncWaits();
    }

    /// Counts the waiting cases of every bond account and opens or closes its
    /// model pause in this block when the count leaves or reaches zero. A
    /// pause that ended in this block is reopened; one that began in this
    /// block and ends in it is dropped.
    function _syncWaits() internal {
        uint256[] memory counts = new uint256[](bondIds.length);
        for (uint256 j; j < nonces.length; j++) {
            bytes32 n = nonces[j];
            if (fb.getCase(n).state != uint8(FairBindCore.CaseState.WAITING_ASSIGNMENT)) continue;
            uint32 owner = bondOfSeller[fb.getPurchase(n).sellerId];
            for (uint256 i; i < bondIds.length; i++) if (bondIds[i] == owner) counts[i]++;
        }
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            uint256 count = counts[i];
            uint256 before = modelWaiting[b];
            modelWaiting[b] = count;
            uint64 t = uint64(block.number);
            uint64[] storage starts = pauseStarts[b];
            uint64[] storage ends = pauseEnds[b];
            if (before == 0 && count != 0) {
                if (ends.length != 0 && ends[ends.length - 1] == t) {
                    ends[ends.length - 1] = 0;
                } else {
                    starts.push(t);
                    ends.push(0);
                }
            } else if (before != 0 && count == 0) {
                if (starts[starts.length - 1] == t) {
                    starts.pop();
                    ends.pop();
                } else {
                    ends[ends.length - 1] = t;
                }
            }
        }
    }

    /// Model of the paused blocks of the account from block `from` through
    /// the block before this one: the blocks u with from <= u < block.number
    /// in which a case of the account waited.
    function pausedSince(uint32 b, uint256 from) public view returns (uint256 total) {
        uint64[] storage starts = pauseStarts[b];
        uint64[] storage ends = pauseEnds[b];
        for (uint256 i; i < starts.length; i++) {
            uint256 lo = starts[i] > from ? starts[i] : from;
            uint256 hi = ends[i] == 0 ? block.number : ends[i];
            if (hi > lo) total += hi - lo;
        }
    }

    /// The contract's release clock of every account equals the model: its
    /// waiting cases, its paused blocks so far, and the paused blocks since
    /// the settlement of each live entry.
    function _checkClocks() internal {
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            (uint32 waiting,, uint64 total) = fb.getReleaseClock(b);
            if (waiting != modelWaiting[b] || total != pausedSince(b, 0)) {
                _flag(Inv.C_PAUSE, string.concat("release clock differs from the model, bond ", Inv.toString(b),
                    " waiting ", Inv.toString(waiting), "/", Inv.toString(modelWaiting[b]),
                    " paused ", Inv.toString(total), "/", Inv.toString(pausedSince(b, 0)),
                    " block ", Inv.toString(block.number)));
            }
        }
        for (uint256 j; j < nonces.length; j++) {
            FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
            uint32 b = bondOfSeller[p.sellerId];
            if (fb.pausedSince(b, p.settledBlock) != pausedSince(b, p.settledBlock)) {
                _flag(Inv.C_PAUSE, string.concat("paused blocks since a settlement differ from the model, nonce ",
                    Inv.hex32(nonces[j]), " block ", Inv.toString(block.number)));
            }
        }
    }

    /// The hold of retentionBlocks that began at `start` still runs: at most
    /// that many unpaused blocks have passed (ADR 0029).
    function _held(uint32 b, uint256 start, uint256 t) internal view returns (bool) {
        return t - pausedSince(b, start) <= start + retention;
    }

    // -------------------------------------------------------- action bracketing

    function begin() external onlyWriter {
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            pre[b] = fb.getBond(b);
            curScale[b] = pre[b].scaleFactor;
            topUps[b] = 0;
            newForfeit[b] = 0;
            lateForfeit[b] = false;
            expectedSlash[b] = 0;
            sanctionedBy[b] = 0;
        }
        for (uint256 i; i < sellerIds.length; i++) preSeller[sellerIds[i]] = fb.getSeller(sellerIds[i]).status;
        prePool = token.balanceOf(Inv.REWARD_POOL);
        preTreasury = token.balanceOf(Inv.TREASURY);
        for (uint32 v = 1; v <= Inv.VERIFIER_COUNT; v++) preVerifierBond[v] = fb.getVerifier(v).bond;
        delete counted;
        delete confirmed;
        delete confirmedFrom;
        delete initialFails;
        delete initialBonds;
        delete initialFrom;
        delete judgedSellers;
        delete judgedResults;
        delete judgedNonces;
    }

    function end(uint8 kind, bytes32 subject) external onlyWriter {
        _syncWaits();
        _checkClocks();
        _scanEpochs();
        _scanPurchases(kind, subject);
        if (kind == Inv.K_FREEZE && subject != 0) {
            // freezeSellerDeferred freezes from its trigger's purchase; it is
            // refused on an account already frozen.
            FairBindCore.PurchaseView memory fp = fb.getPurchase(subject);
            uint32 fbond = bondOfSeller[fp.sellerId];
            if (pre[fbond].freezeState != Z_FROZEN && pre[fbond].freezeState != Z_OPEN) {
                initialBonds.push(fbond);
                initialFrom.push(fp.settledBlock);
            }
        }
        if (kind == Inv.K_TERMS) _applyTerms(uint32(uint256(subject)));
        _applyCounters();
        _checkBonds();
        _checkMoney();
        _checkSellers(kind, subject);
    }

    function _scanEpochs() internal {
        for (uint256 i; i < epochKeys.length; i++) {
            uint256 ek = epochKeys[i];
            uint32 seller = uint32(ek >> 24);
            FairBindCore.AnchorView memory a = fb.getAnchor(seller, uint24(ek));
            uint8 failed = uint8(FairBindCore.EpochState.EPOCH_FAILED);
            if (a.state == failed && lastAnchor[ek] != failed && a.anchoredBlock == 0) {
                // timeoutAnchor: a missed anchor is a counted seller failure;
                // its freeze starts at the first block of the epoch.
                counted.push(seller);
                confirmed.push(seller);
                confirmedFrom.push(uint64(epochOrigin + uint256(uint24(ek)) * epochBlocks));
            }
            lastAnchor[ek] = a.state;
        }
    }

    function _scanPurchases(uint8 kind, bytes32 subject) internal {
        for (uint256 i; i < nonces.length; i++) {
            bytes32 n = nonces[i];
            FairBindCore.PurchaseView memory p = fb.getPurchase(n);
            uint8 s = fb.purchaseState(n);
            uint8 prev = lastState[n];
            uint32 b = bondOfSeller[p.sellerId];
            if ((prev == F_REFUNDED || prev == F_RELEASED || prev == F_FORFEITED) && s != prev) {
                _flag(Inv.C_TERMINAL, string.concat("terminal state ", Inv.toString(prev), " became ",
                    Inv.toString(s), " nonce ", Inv.hex32(n), " block ", Inv.toString(block.number)));
            }
            if (p.financialState == F_REFUNDABLE && lastStored[n] != F_REFUNDABLE) {
                if (kind == Inv.K_CLAIM_EPOCH && subject == n) {
                    // A refund of a failed epoch counts nothing more; an epoch
                    // without an anchor still keeps the claim window open.
                    if (fb.getAnchor(p.sellerId, p.epoch).anchoredBlock == 0) {
                        confirmed.push(p.sellerId);
                        confirmedFrom.push(uint64(epochOrigin + uint256(p.epoch) * epochBlocks));
                    }
                } else {
                    counted.push(p.sellerId);
                    confirmed.push(p.sellerId);
                    confirmedFrom.push(p.settledBlock);
                }
            }
            // An entry leaves the deferred balance by forfeiture when its
            // window closes as one sum, or, in a window closed itemized, when
            // releasePurchase sweeps it (ADR 0030).
            if (s == F_FORFEITED && !forfeitCounted[n] && _forfeitDone(b, p)) {
                forfeitCounted[n] = true;
                newForfeit[b] += p.value;
                if (p.settledBlock > pre[b].forfeitedThrough) lateForfeit[b] = true;
            }
            if (s == F_RELEASED && prev != F_RELEASED && !(kind == Inv.K_RELEASE && subject == n)) {
                _flag(Inv.C_RELEASE, string.concat("entry released outside releasePurchase, nonce ", Inv.hex32(n)));
            }
            FairBindCore.CaseView memory c = fb.getCase(n);
            uint8 fin = uint8(FairBindCore.CaseState.FINAL);
            // Only sampled cases enter the judged and inconclusive counts (ADR 0017),
            // and a stalled seller appeal that upholds the initial FAIL is not a
            // judged case (ADR 0024).
            if (c.state == fin && lastCase[n] != fin && c.trigger == uint8(FairBindCore.CaseTrigger.SAMPLE)
                && !_upheldStall(n, c)) {
                judgedSellers.push(p.sellerId);
                judgedResults.push(c.finalVerdict);
                judgedNonces.push(n);
            }
            uint8 failV = uint8(FairBindCore.Verdict.FAIL);
            // Rule D2-15: a seller-appealed review against an initial FAIL never
            // ends as a protocol INCONCLUSIVE; when it cannot progress the
            // initial FAIL is final (ADR 0024).
            if (c.state == uint8(FairBindCore.CaseState.INCONCLUSIVE) && lastCase[n] != c.state
                && c.reviewPath == 1 && c.initialVerdict == failV) {
                _flag(Inv.C_APPEAL, string.concat("seller-appealed review that could not progress ended INCONCLUSIVE, nonce ",
                    Inv.hex32(n), " block ", Inv.toString(block.number)));
            }
            if (c.state == fin && lastCase[n] != fin && _upheldStall(n, c)) hits[H_UPHELD]++;
            if (c.initialVerdict == failV && lastInitial[n] != failV) {
                initialFails.push(p.sellerId);
                initialBonds.push(b);
                initialFrom.push(p.settledBlock);
            }
            if (freezeEnabled && freezeOnInitialFail) {
                bool terminal = c.state == fin || c.state == uint8(FairBindCore.CaseState.INCONCLUSIVE)
                    || c.state == uint8(FairBindCore.CaseState.UNSERVED) || c.state == uint8(FairBindCore.CaseState.DELIVERED);
                if (!pendingTrigger[n] && c.initialVerdict == failV && !terminal) {
                    pendingTrigger[n] = true;
                    pendingTriggers[b]++;
                } else if (pendingTrigger[n] && terminal) {
                    pendingTrigger[n] = false;
                    pendingTriggers[b]--;
                }
            }
            lastState[n] = s;
            lastStored[n] = p.financialState;
            lastCase[n] = c.state;
            lastInitial[n] = c.initialVerdict;
        }
    }

    /// A FINAL(FAIL) of a seller-appealed review that ended without a verdict
    /// of its last stage: every assignment of the stage timed out or was
    /// voided, or the stage never got one (ADR 0024).
    function _upheldStall(bytes32 n, FairBindCore.CaseView memory c) internal view returns (bool) {
        uint8 failV = uint8(FairBindCore.Verdict.FAIL);
        if (c.reviewPath != 1 || c.initialVerdict != failV || c.finalVerdict != failV) return false;
        FairBindCore.AssignmentData[] memory list = fb.getAssignments(n);
        if (list.length == 0) return true;
        FairBindCore.AssignmentData memory last = list[list.length - 1];
        return last.stage != c.stage || last.verdict == 0;
    }

    /// Replays the failure-window, sanction, per-failure deduction and
    /// judged-window rules on the events of this action and compares the bond
    /// counters. A window opens at the bond's scale factor n (at least one)
    /// and sanctions at n * failureLimit (ADR 0021). n is read before the
    /// opening failure's deduction and raised to the highest scale the account
    /// left through a drop within retentionBlocks; a top-up that raises the
    /// scale factor while the window is open raises n (ADR 0022). Every
    /// counted failure deducts sellerPenalty / failureLimit; the failure that
    /// reaches the limit deducts the remainder, so that one window's
    /// deductions sum to n * sellerPenalty (ADR 0018).
    function _applyCounters() internal {
        uint64 t = uint64(block.number);
        for (uint256 i; i < counted.length; i++) {
            uint32 b = bondOfSeller[counted[i]];
            Counters storage m = model[b];
            uint256 left = pre[b].balance + topUps[b] - expectedSlash[b];
            // The unit bond in the block of the failure: the profile's
            // sellerPenalty, or k * b(V*) under design 2 terms, where V* can
            // expire while the handler moves the block inside an action.
            uint256 unit = fb.unitBond(b);
            if (m.failures == 0 || t > uint256(m.failureStart) + failureWindow) {
                m.failures = 0;
                m.failureStart = t;
                // The scale factor the account holds, read before this
                // failure's deduction.
                uint256 scale = curScale[b];
                FairBindCore.ScaleHigh storage h = high[b];
                if (h.scale > scale && _held(b, h.dropBlock, t)) scale = h.scale;
                m.windowScale = uint32(scale > 1 ? scale : 1);
            }
            m.failures++;
            if (m.sanctioned) continue;
            uint256 limit = uint256(m.windowScale) * failureLimit;
            uint256 share = unit / failureLimit;
            if (sanctionLimit != 0 && m.failures >= uint256(m.windowScale) * sanctionLimit) {
                share = uint256(m.windowScale) * unit - (limit - 1) * share;
                m.sanctioned = true;
                sanctionedBy[b] = counted[i];
            }
            uint256 cut = share < left ? share : left;
            uint256 after_ = (left - cut) / unit;
            // Under design 2 terms only the base tier scales; the suite opens
            // every account in it.
            _noteDrop(b, curScale[b], after_, t);
            curScale[b] = uint32(after_);
            expectedSlash[b] += cut;
        }
        // A top-up is its own action: raise an open window to the new scale.
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            if (topUps[b] == 0) continue;
            Counters storage m = model[b];
            uint256 scale = (pre[b].balance + topUps[b] - expectedSlash[b]) / fb.unitBond(b);
            if (m.failures != 0 && t <= uint256(m.failureStart) + failureWindow && scale > m.windowScale) {
                m.windowScale = uint32(scale);
            }
        }
        for (uint256 i; i < judgedSellers.length; i++) {
            uint32 b = bondOfSeller[judgedSellers[i]];
            Counters storage m = model[b];
            if (m.judged == 0 || t > uint256(m.judgedStart) + judgedWindow) {
                m.judged = 0;
                m.inconclusive = 0;
                m.judgedStart = t;
            }
            m.judged++;
            if (judgedResults[i] == uint8(FairBindCore.Verdict.INCONCLUSIVE)) {
                // The freeze of the window starts at its first inconclusive sale (ADR 0030).
                if (m.inconclusive == 0) incFloor[b] = fb.getPurchase(judgedNonces[i]).settledBlock;
                m.inconclusive++;
                if (uint256(m.inconclusive) * Inv.PPM > maxInconclusivePpm * m.judged) {
                    confirmed.push(judgedSellers[i]);
                    confirmedFrom.push(incFloor[b]);
                    hits[H_INCONCLUSIVE_FREEZE]++;
                }
            }
        }
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            FairBindCore.BondView memory post = fb.getBond(b);
            Counters storage m = model[b];
            if (post.failureCount != m.failures || post.failureWindowStart != m.failureStart
                || (m.failures != 0 && fb.getFailureWindowScale(b) != m.windowScale)
                || post.sanctioned != m.sanctioned || post.judgedCount != m.judged
                || post.inconclusiveCount != m.inconclusive || post.inconclusiveWindowStart != m.judgedStart) {
                _flag(Inv.C_COUNTERS, string.concat("bond counters differ from the model, bond ", Inv.toString(b),
                    " failures ", Inv.toString(post.failureCount), "/", Inv.toString(m.failures),
                    " judged ", Inv.toString(post.judgedCount), "/", Inv.toString(m.judged),
                    " inconclusive ", Inv.toString(post.inconclusiveCount), "/", Inv.toString(m.inconclusive),
                    string.concat(" start ", Inv.toString(post.failureWindowStart), "/", Inv.toString(m.failureStart),
                    " scale ", Inv.toString(fb.getFailureWindowScale(b)), "/", Inv.toString(m.windowScale),
                    " sanctioned ", post.sanctioned ? "1" : "0", "/", m.sanctioned ? "1" : "0"),
                    " block ", Inv.toString(block.number)));
                // Resynchronise so that one divergence is reported once.
                m.failures = post.failureCount;
                m.failureStart = post.failureWindowStart;
                m.windowScale = fb.getFailureWindowScale(b);
                m.sanctioned = post.sanctioned;
                m.judged = post.judgedCount;
                m.inconclusive = post.inconclusiveCount;
                m.judgedStart = post.inconclusiveWindowStart;
            }
            FairBindCore.ScaleHigh memory got = fb.getRecentScaleHigh(b);
            if (got.scale != high[b].scale || got.dropBlock != high[b].dropBlock) {
                _flag(Inv.C_COUNTERS, string.concat("recent scale high differs from the model, bond ", Inv.toString(b),
                    " scale ", Inv.toString(got.scale), "/", Inv.toString(high[b].scale)));
                high[b] = got;
            }
        }
    }

    /// A change of design 2 terms recomputes the scale factor from the balance:
    /// a drop is kept as the recent scale high, and a rise during an open
    /// failure window raises the window's scale (ADR 0024).
    function _applyTerms(uint32 b) internal {
        uint64 t = uint64(block.number);
        FairBindCore.BondView memory post = fb.getBond(b);
        _noteDrop(b, pre[b].scaleFactor, post.scaleFactor, t);
        Counters storage m = model[b];
        if (m.failures != 0 && t <= uint256(m.failureStart) + failureWindow && post.scaleFactor > m.windowScale) {
            m.windowScale = post.scaleFactor;
        }
    }

    /// A deduction that lowers the scale factor keeps the higher of the level
    /// it left and a recorded level that is still recent, and restamps the
    /// block (ADR 0022).
    function _noteDrop(uint32 b, uint256 before, uint256 afterDrop, uint64 t) internal {
        if (afterDrop >= before) return;
        FairBindCore.ScaleHigh storage h = high[b];
        if (before > h.scale || !_held(b, h.dropBlock, t)) h.scale = uint32(before);
        h.dropBlock = t;
    }

    /// Records the window [c, t] of each confirmed failure of the bond in this
    /// action and checks that the contract holds every unreleased entry of it
    /// (ADR 0030): after a confirmed failure the claim window is open and each
    /// such entry reads FROZEN_CLAIMABLE, or FORFEITED when an earlier closed
    /// window already took it.
    function _recordWindows(uint32 b, uint64 t) internal {
        for (uint256 i; i < confirmed.length; i++) {
            if (bondOfSeller[confirmed[i]] != b) continue;
            uint64 c = confirmedFrom[i];
            confFrom[b].push(c);
            confThrough[b].push(t);
            if (!freezeEnabled) continue;
            for (uint256 j; j < nonces.length; j++) {
                FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
                if (bondOfSeller[p.sellerId] != b || p.settledBlock < c || p.settledBlock > t) continue;
                if (p.financialState != F_DEFERRED && p.financialState != F_RELEASABLE) continue;
                uint8 v = fb.purchaseState(nonces[j]);
                if (v != F_FROZEN_CLAIMABLE && v != F_FORFEITED) {
                    _flag(Inv.C_STATUS, string.concat("entry settled at block ", Inv.toString(p.settledBlock),
                        " outside the freeze of a confirmed failure tied to block ", Inv.toString(c),
                        " bond ", Inv.toString(b), " block ", Inv.toString(t)));
                }
            }
            // The other side (ADR 0030, rule Narrow Freeze): an unreleased
            // entry settled before c keeps its schedule. It may be held only
            // by another model window: claimable when a window of the open
            // freeze holds it, forfeited when any window of the run does.
            for (uint256 j; j < nonces.length; j++) {
                FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
                if (bondOfSeller[p.sellerId] != b || p.settledBlock >= c) continue;
                if (p.financialState != F_DEFERRED && p.financialState != F_RELEASABLE) continue;
                uint8 v = fb.purchaseState(nonces[j]);
                bool wide = (v == F_FROZEN_CLAIMABLE && !_inWindows(b, p.settledBlock, episodeStart[b]))
                    || (v == F_FORFEITED && !_inWindows(b, p.settledBlock, 0));
                if (wide) {
                    _flag(Inv.C_STATUS, string.concat("entry settled at block ", Inv.toString(p.settledBlock),
                        " before the start ", Inv.toString(c), " of a confirmed failure was frozen (state ",
                        Inv.toString(v), ") bond ", Inv.toString(b), " block ", Inv.toString(t)));
                }
            }
        }
    }

    /// Records the span [s, t] of each initial FAIL of the bond in this action
    /// that froze the account: under freezeOnInitialFail, when the account was
    /// not in an open claim window before the action and is frozen after it.
    function _recordInitial(uint32 b, uint64 t) internal {
        for (uint256 i; i < initialBonds.length; i++) {
            if (initialBonds[i] != b) continue;
            initFrom[b].push(initialFrom[i]);
            initThrough[b].push(t);
        }
    }

    /// Whether a model window recorded at or after block `since` holds
    /// settlement block s: a confirmed failure's [c, t] or an initial FAIL's
    /// [s, t].
    function _inWindows(uint32 b, uint64 s, uint64 since) internal view returns (bool) {
        uint64[] storage from = confFrom[b];
        for (uint256 i; i < from.length; i++) {
            uint64 through = confThrough[b][i];
            if (through >= since && s >= from[i] && s <= through) return true;
        }
        from = initFrom[b];
        for (uint256 i; i < from.length; i++) {
            uint64 through = initThrough[b][i];
            if (through >= since && s >= from[i] && s <= through) return true;
        }
        return false;
    }

    /// The model of the frozen window of the account's open freeze: whether
    /// a window recorded since the freeze began holds settlement block s. The
    /// handler reads this, not the contract's spans, to decide whether a
    /// release may be refused or a frozen claim must succeed.
    function heldByModel(uint32 b, uint64 s) external view returns (bool) {
        return _inWindows(b, s, episodeStart[b]);
    }

    /// The block of a confirmed failure of the bond whose window [c, t] holds
    /// settlement block s, or zero (ADR 0030).
    function confirmedWindowOf(uint32 b, uint64 s) external view returns (uint64) {
        uint64[] storage from = confFrom[b];
        for (uint256 i; i < from.length; i++) {
            if (s >= from[i] && s <= confThrough[b][i]) return confThrough[b][i];
        }
        return 0;
    }

    /// Whether an unencumbered unreleased entry of the bond, not taken by a
    /// closed window, was settled at or before block `through` (the last
    /// confirmed failure, so not after a reinstatement) outside the model
    /// window of the open freeze. The window must then close itemized: a
    /// forfeiture of one sum would take that entry (ADR 0030). In a correct
    /// build such an entry lies before the first span or between two spans,
    /// so the contract itemizes.
    function unheldThrough(uint32 b, uint64 through) external view returns (bool) {
        for (uint256 j; j < nonces.length; j++) {
            FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
            if (bondOfSeller[p.sellerId] != b || p.settledBlock > through) continue;
            if (p.financialState != F_DEFERRED && p.financialState != F_RELEASABLE) continue;
            if (fb.purchaseState(nonces[j]) == F_FORFEITED) continue;
            if (_inWindows(b, p.settledBlock, episodeStart[b])) continue;
            return true;
        }
        return false;
    }

    /// Whether a forfeited entry has left the deferred balance: always, unless
    /// its closed window is itemized and releasePurchase has not swept it yet
    /// (ADR 0030).
    function _forfeitDone(uint32 b, FairBindCore.PurchaseView memory p) internal view returns (bool) {
        if (p.financialState == F_FORFEITED) return true;
        FairBindCore.ForfeitWindow[] memory w = fb.getForfeitWindows(b);
        for (uint256 i; i < w.length; i++) {
            if (p.settledBlock >= w[i].from && p.settledBlock <= w[i].through) return !w[i].itemized;
        }
        return true;
    }

    function _isConfirmed(uint32 bondId) internal view returns (bool) {
        for (uint256 i; i < confirmed.length; i++) if (bondOfSeller[confirmed[i]] == bondId) return true;
        return false;
    }

    function _sellerIn(uint32[] storage list, uint32 sellerId) internal view returns (bool) {
        for (uint256 i; i < list.length; i++) if (list[i] == sellerId) return true;
        return false;
    }

    function _checkBonds() internal {
        uint64 t = uint64(block.number);
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            FairBindCore.BondView memory post = fb.getBond(b);
            FairBindCore.BondView storage p0 = pre[b];
            string memory tag = string.concat(" bond ", Inv.toString(b), " block ", Inv.toString(t));
            if (post.balance != p0.balance + topUps[b] - expectedSlash[b]) {
                _flag(Inv.C_COUNTERS, string.concat("bond balance ", Inv.toString(post.balance), " expected ",
                    Inv.toString(p0.balance + topUps[b] - expectedSlash[b]), tag));
            }
            if (post.sanctioned && !p0.sanctioned) {
                slashes[b]++;
                hits[H_SANCTION]++;
                if (slashes[b] > 1) _flag(Inv.C_COUNTERS, string.concat("bond slashed twice", tag));
            }
            bool conf = _isConfirmed(b);
            bool wasHeld = p0.freezeState == Z_FROZEN || p0.freezeState == Z_OPEN;
            bool isHeld = post.freezeState == Z_FROZEN || post.freezeState == Z_OPEN;
            if (isHeld && !wasHeld) episodeStart[b] = t;
            if (freezeEnabled && freezeOnInitialFail && isHeld && p0.freezeState != Z_OPEN) _recordInitial(b, t);
            if (freezeEnabled) {
                if (post.freezeState == Z_OPEN && p0.freezeState != Z_OPEN && !conf) {
                    _flag(Inv.C_STATUS, string.concat("claim window opened without a final failure", tag));
                }
                if (conf && post.freezeState != Z_OPEN) {
                    _flag(Inv.C_STATUS, string.concat("final failure left the claim window closed", tag));
                }
                if (conf && post.claimUntilBlock < uint256(t) + claimWindow) {
                    _flag(Inv.C_STATUS, string.concat("claim window shorter than claimWindowBlocks", tag));
                }
                // A confirmed failure during an open claim window moves the
                // frozen window to its block (ADR 0021).
                if (conf && p0.freezeState == Z_OPEN) {
                    if (post.freezeBlock != t) {
                        _flag(Inv.C_STATUS, string.concat("confirmed failure in an open claim window left freezeBlock at ",
                            Inv.toString(post.freezeBlock), tag));
                    } else if (p0.freezeBlock != t) {
                        hits[H_WINDOW_MOVED]++;
                    }
                }
            } else if (post.freezeState != 0) {
                _flag(Inv.C_STATUS, string.concat("mutation build froze a bond account", tag));
            }
            if (conf) {
                lastConfirm[b] = t;
                _recordWindows(b, t);
            }
            bool overturned = p0.freezeState == Z_FROZEN && post.freezeState != Z_FROZEN && post.freezeState != Z_OPEN;
            if (overturned) {
                hits[H_OVERTURN]++;
                if (lateForfeit[b]) _flag(Inv.C_FORFEIT, string.concat("overturned freeze forfeited an entry", tag));
                if (pendingTriggers[b] != 0) {
                    _flag(Inv.C_STATUS, string.concat("freeze released while an initial FAIL is pending", tag));
                }
            }
            if (freezeEnabled && fb.getFreezeTriggers(b).count != pendingTriggers[b]) {
                _flag(Inv.C_STATUS, string.concat("pending trigger count ", Inv.toString(fb.getFreezeTriggers(b).count),
                    " differs from the model ", Inv.toString(pendingTriggers[b]), tag));
            }
            uint256 f = post.forfeitedTotal - p0.forfeitedTotal;
            if (f != newForfeit[b]) {
                _flag(Inv.C_FORFEIT, string.concat("forfeited total grew by ", Inv.toString(f),
                    " but entries forfeited sum to ", Inv.toString(newForfeit[b]), tag));
            }
            if (post.scaleFactor != bucket[b].scale) _rescale(b, post.scaleFactor);
        }
    }

    function _checkMoney() internal {
        uint256 f;
        uint256 slash;
        for (uint256 i; i < bondIds.length; i++) {
            f += fb.getBond(bondIds[i]).forfeitedTotal - pre[bondIds[i]].forfeitedTotal;
            slash += expectedSlash[bondIds[i]];
        }
        uint256 verifierLoss;
        for (uint32 v = 1; v <= Inv.VERIFIER_COUNT; v++) {
            uint256 now_ = fb.getVerifier(v).bond;
            if (now_ < preVerifierBond[v]) verifierLoss += preVerifierBond[v] - now_;
        }
        uint256 r = token.balanceOf(Inv.REWARD_POOL) - prePool;
        uint256 t = token.balanceOf(Inv.TREASURY) - preTreasury;
        // Forfeitures and deductions stay locked in the contract (ADR 0022):
        // the verifier pool receives nothing and the treasury only verifier
        // penalties.
        lockedExpected += f + slash;
        string memory tag = string.concat(" forfeited ", Inv.toString(f), " block ", Inv.toString(block.number));
        if (r != 0) _flag(Inv.C_FORFEIT, string.concat("verifier pool received ", Inv.toString(r), tag));
        if (t > verifierLoss) {
            _flag(Inv.C_FORFEIT, string.concat("treasury received ", Inv.toString(t), " above the verifier penalties ",
                Inv.toString(verifierLoss), tag));
        }
        if (fb.getLockedForfeit() != lockedExpected) {
            _flag(Inv.C_FORFEIT, string.concat("locked total ", Inv.toString(fb.getLockedForfeit()), " expected ",
                Inv.toString(lockedExpected), tag));
        }
    }

    function _checkSellers(uint8 kind, bytes32 subject) internal {
        uint32 freezeSeller = kind == Inv.K_FREEZE ? fb.getPurchase(subject).sellerId : 0;
        for (uint256 i; i < sellerIds.length; i++) {
            uint32 sid = sellerIds[i];
            FairBindCore.SellerView memory s = fb.getSeller(sid);
            uint8 was = preSeller[sid];
            string memory tag = string.concat(" seller ", Inv.toString(sid), " block ", Inv.toString(block.number));
            if (s.bondId != bondOfSeller[sid]) _flag(Inv.C_BUCKET, string.concat("registration changed bond", tag));
            if (was == s.status) continue;
            if (was == S_SANCTIONED) {
                _flag(Inv.C_STATUS, string.concat("sanctioned seller left SANCTIONED", tag));
            } else if (s.status == S_SANCTIONED) {
                if (sanctionedBy[s.bondId] != sid) {
                    _flag(Inv.C_STATUS, string.concat("seller sanctioned without reaching the failure limit", tag));
                }
            } else if (was == S_ACTIVE && s.status == S_SUSPENDED) {
                bool byInitialFail = freezeOnInitialFail && (_sellerIn(initialFails, sid) || freezeSeller == sid);
                if (!_sellerIn(confirmed, sid) && !byInitialFail) {
                    _flag(Inv.C_STATUS, string.concat("seller suspended without a failure of its own", tag));
                }
            } else if (was == S_SUSPENDED && s.status == S_ACTIVE) {
                FairBindCore.BondView storage p0 = pre[s.bondId];
                bool overturn = p0.freezeState == Z_FROZEN && fb.getBond(s.bondId).freezeState != Z_FROZEN
                    && s.suspendedAtBlock >= p0.freezeBlock;
                bool reinstated = kind == Inv.K_REINSTATE && uint32(uint256(subject)) == sid;
                if (!overturn && !reinstated) {
                    _flag(Inv.C_STATUS, string.concat("seller reactivated without reinstatement or overturn", tag));
                }
                if (pendingTriggers[s.bondId] != 0) {
                    _flag(Inv.C_STATUS, string.concat("seller reactivated while an initial FAIL is pending", tag));
                }
            } else {
                _flag(Inv.C_STATUS, string.concat("unexpected seller transition ", Inv.toString(was), " to ",
                    Inv.toString(s.status), tag));
            }
        }
    }

    // --------------------------------------------------------- state invariants

    /// Deferred-ledger conservation of every bond account: deferred (including
    /// held, refundable and frozen) + refunded + released + forfeited equals
    /// the value settled against the account; the stored totals match the sum
    /// of the entries.
    function checkLedger() external view returns (bool, string memory) {
        uint256 held;
        for (uint256 i; i < bondIds.length; i++) {
            uint32 b = bondIds[i];
            FairBindCore.BondView memory bond = fb.getBond(b);
            (uint256 deferred, uint256 encumbered, uint256 frozen, uint256 refunded, uint256 released, uint256 forfeited)
                = _sums(b, bond);
            string memory tag = string.concat(" bond ", Inv.toString(b));
            if (deferred != bond.deferredBalance) {
                return (false, string.concat("deferred entries ", Inv.toString(deferred), " != deferredBalance ",
                    Inv.toString(bond.deferredBalance), tag));
            }
            if (encumbered != bond.encumbered) {
                return (false, string.concat("held and refundable entries ", Inv.toString(encumbered),
                    " != encumbered ", Inv.toString(bond.encumbered), tag));
            }
            if (forfeited != bond.forfeitedTotal) {
                return (false, string.concat("forfeited entries ", Inv.toString(forfeited), " != forfeitedTotal ",
                    Inv.toString(bond.forfeitedTotal), tag));
            }
            if (deferred + refunded + released + forfeited != settledTotal[b]) {
                return (false, string.concat("deferred+refunded+released+forfeited ",
                    Inv.toString(deferred + refunded + released + forfeited), " != settled ",
                    Inv.toString(settledTotal[b]), tag));
            }
            bool isFrozen = bond.freezeState == Z_FROZEN || bond.freezeState == Z_OPEN;
            if (!isFrozen && frozen != 0) return (false, string.concat("frozen entries without a freeze", tag));
            // Entries settled after freezeBlock during an open claim window are
            // outside the frozen window and tracked apart (ADR 0021).
            (uint256 lateDeferred, uint256 lateEncumbered) = _late(b, bond);
            FairBindCore.ClaimReentry memory re = fb.getClaimReentry(b);
            if (re.deferredBalance != lateDeferred || re.encumbered != lateEncumbered) {
                return (false, string.concat("entries settled after the frozen window ",
                    Inv.toString(lateDeferred), "/", Inv.toString(lateEncumbered), " != re-entry totals ",
                    Inv.toString(re.deferredBalance), "/", Inv.toString(re.encumbered), tag));
            }
            if (bond.freezeState != Z_OPEN && (re.reopened || re.deferredBalance != 0)) {
                return (false, string.concat("re-entry state outside an open claim window", tag));
            }
            uint256 windowPool = (bond.deferredBalance - lateDeferred) - (bond.encumbered - lateEncumbered);
            if (pool(b) != (isFrozen ? windowPool : 0)) {
                return (false, string.concat("frozen pool view differs from the ledger", tag));
            }
            held += bond.balance + bond.deferredBalance;
        }
        for (uint32 v = 1; v <= Inv.VERIFIER_COUNT; v++) held += fb.getVerifier(v).bond;
        // Conservation includes the locked forfeitures and deductions (ADR 0022).
        held += fb.getLockedForfeit();
        if (token.balanceOf(address(fb)) < held) return (false, "contract holds less than bonds plus deferred funds");
        return (true, "");
    }

    function pool(uint32 b) internal view returns (uint256) {
        return fb.getFrozenPool(b).poolBalance;
    }

    /// Deferred and encumbered value of the entries settled after freezeBlock
    /// while the claim window is open.
    function _late(uint32 b, FairBindCore.BondView memory bond) internal view returns (uint256 d, uint256 e) {
        if (bond.freezeState != Z_OPEN) return (0, 0);
        for (uint256 j; j < nonces.length; j++) {
            FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
            if (bondOfSeller[p.sellerId] != b || p.settledBlock <= bond.freezeBlock) continue;
            uint8 st = p.financialState;
            if (st == F_REFUNDED || st == F_RELEASED || st == F_FORFEITED) continue;
            d += p.value;
            if (st == F_HELD || st == F_REFUNDABLE) e += p.value;
        }
    }

    function _sums(uint32 b, FairBindCore.BondView memory bond)
        internal
        view
        returns (uint256 deferred, uint256 encumbered, uint256 frozen, uint256 refunded, uint256 released, uint256 forfeited)
    {
        for (uint256 j; j < nonces.length; j++) {
            FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[j]);
            if (bondOfSeller[p.sellerId] != b) continue;
            uint8 s = fb.purchaseState(nonces[j]);
            uint8 st = p.financialState;
            if (s == F_FORFEITED && _forfeitDone(b, p)) forfeited += p.value;
            else if (st == F_REFUNDED) refunded += p.value;
            else if (st == F_RELEASED) released += p.value;
            else {
                deferred += p.value;
                if (st == F_HELD || st == F_REFUNDABLE) encumbered += p.value;
                if ((bond.freezeState == Z_FROZEN || bond.freezeState == Z_OPEN) && p.settledBlock <= bond.freezeBlock) {
                    frozen += p.value;
                }
            }
        }
    }

    /// No verifier is assigned twice to one case.
    function checkParticipation() external view returns (bool, string memory) {
        for (uint256 i; i < nonces.length; i++) {
            FairBindCore.AssignmentData[] memory list = fb.getAssignments(nonces[i]);
            for (uint256 a; a < list.length; a++) {
                for (uint256 c = a + 1; c < list.length; c++) {
                    if (list[a].verifierId == list[c].verifierId) {
                        return (false, string.concat("verifier ", Inv.toString(list[a].verifierId),
                            " assigned twice, nonce ", Inv.hex32(nonces[i])));
                    }
                }
            }
        }
        return (true, "");
    }

    /// Locked liability and reserved penalties equal the unreleased
    /// assignments, and every assignment fit the verifier's liability room in
    /// the checkpoint of its epoch (decision 126, ADR 0025). Liability may
    /// exceed the verifier's current exposure limit: room is read at the
    /// checkpoint block, not when the case opens.
    function checkLiability() external view returns (bool, string memory) {
        uint256[15] memory locked;
        uint256[15] memory reserved;
        for (uint256 i; i < nonces.length; i++) {
            FairBindCore.AssignmentData[] memory list = fb.getAssignments(nonces[i]);
            if (list.length == 0) continue;
            FairBindCore.PurchaseView memory p = fb.getPurchase(nonces[i]);
            uint64 version = fb.getAnchor(p.sellerId, p.epoch).sortitionVersion;
            // A case that waited is assigned on the checkpoint of a redraw, a
            // version after the epoch's up to its last search (ADR 0028).
            uint64 last = fb.getAssignmentWait(nonces[i]).checkpointVersion;
            if (last < version) last = version;
            for (uint256 a; a < list.length; a++) {
                bool fits;
                for (uint64 v = version; v <= last && !fits; v++) fits = _fits(p.profileId, v, list[a]);
                if (!fits) {
                    return (false, string.concat("assignment without checkpoint room, verifier ",
                        Inv.toString(list[a].verifierId), " nonce ", Inv.hex32(nonces[i])));
                }
                if (list[a].released) continue;
                locked[list[a].verifierId] += list[a].liability;
                reserved[list[a].verifierId] += list[a].penaltyReserve;
            }
        }
        for (uint32 v = 1; v <= Inv.VERIFIER_COUNT; v++) {
            FairBindCore.VerifierView memory vv = fb.getVerifier(v);
            FairBindCore.VerifierCapital memory cap = fb.getVerifierCapital(v);
            string memory tag = string.concat(" verifier ", Inv.toString(v));
            if (vv.lockedLiability != locked[v]) return (false, string.concat("locked liability differs", tag));
            if (cap.reservedPenalties != reserved[v]) return (false, string.concat("reserved penalties differ", tag));
        }
        return (true, "");
    }

    function _fits(uint32 profileId, uint64 version, FairBindCore.AssignmentData memory a)
        internal
        view
        returns (bool)
    {
        (, uint32[] memory ids,,,) = fb.getVerifierCheckpoint(profileId, version);
        uint96[] memory room = fb.getCheckpointHeadroom(profileId, version);
        for (uint256 j; j < ids.length; j++) if (ids[j] == a.verifierId) return a.liability <= room[j];
        return false;
    }

    /// Every registration of a bond account reads the same bucket, equal to
    /// the model; registrations never change bond; the registration count
    /// matches.
    function checkBucket() external view returns (bool, string memory) {
        for (uint256 i; i < sellerIds.length; i++) {
            uint32 sid = sellerIds[i];
            uint32 b = bondOfSeller[sid];
            FairBindCore.SellerQuote memory q = fb.quoteSeller(sid);
            if (q.bondId != b) return (false, string.concat("seller changed bond ", Inv.toString(sid)));
            if (q.bucketBalancePpm != modelLevel(b)) {
                return (false, string.concat("bucket of seller ", Inv.toString(sid), " reads ",
                    Inv.toString(q.bucketBalancePpm), " model ", Inv.toString(modelLevel(b))));
            }
        }
        for (uint256 i; i < bondIds.length; i++) {
            if (fb.getBond(bondIds[i]).registrations != registrationsOf[bondIds[i]]) {
                return (false, string.concat("registration count differs, bond ", Inv.toString(bondIds[i])));
            }
        }
        return (true, "");
    }

    /// Stored counters equal the models, the verifier pool received nothing and
    /// the locked total equals every forfeiture and deduction (ADR 0022).
    function checkCounters() external view returns (bool, string memory) {
        if (token.balanceOf(Inv.REWARD_POOL) != 0) return (false, "verifier pool received a forfeiture");
        if (fb.getLockedForfeit() != lockedExpected) return (false, "locked total differs from the model");
        for (uint256 i; i < bondIds.length; i++) {
            if (slashes[bondIds[i]] > 1) return (false, "bond slashed twice");
        }
        return (true, "");
    }
}
