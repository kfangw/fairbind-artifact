// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { BatchStore } from "./BatchStore.sol";
import { BatchShared } from "./BatchShared.sol";

/// Extension module 2 (ADR 0034): seller proofs on frozen entries with their
/// reservation, audit, contest and judgment, the release of proven entries,
/// and the compensation pool of forfeited proof bonds; the pause of an
/// epoch's late sampling value (ADR 0036).
contract FairBindProof is BatchShared {
    uint8 public constant MODULE_KIND = 13;

    bytes32 internal constant AUDIT_DOMAIN = keccak256("fairbind/audit/v1");
    bytes32 internal constant PROOF_VERDICT_TYPEHASH =
        keccak256("FairBindProofVerdict(bytes32 nonce,uint8 attempt,uint32 verifierId,uint8 verdict,bytes32 evidenceHash)");
    uint256 internal constant INDEX_SCALE = 1e18;

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        BatchShared(token, gov, guard, treasury, rewardPool)
    { }

    error ProofsOff();
    error ProofNotAllowed();
    event ProofSubmitted(bytes32 indexed nonce, uint256 bond, bytes32 evidenceHash, bool reserved);
    event ProofOpened(bytes32 indexed nonce, uint64 auditBlock);
    event ProofAuditDrawn(bytes32 indexed nonce, bool audited, uint64 contestUntil);
    event ProofContested(bytes32 indexed nonce, address indexed contester, uint256 deposit);
    event ProofJudged(bytes32 indexed nonce, uint32 indexed verifierId, uint8 verdict);
    event ProofEnded(bytes32 indexed nonce, uint8 state);
    event CompensationAdded(uint32 indexed bondId, uint256 amount);
    event CompensationDistributed(uint32 indexed bondId, uint256 amount, uint256 weight);
    event CompensationPaid(bytes32 indexed nonce, address indexed buyer, uint256 amount);
    event SideGainChanged(uint32 indexed bondId, uint256 deposit);
    event SampleWaitPaused(uint32 indexed sellerId, uint24 indexed epoch, uint64 from);

    /// The seller proves a frozen entry of its open claim window with the
    /// signed receipt, its inclusion in the anchor, a non-zero predicate
    /// commitment and the evidence envelope, and locks the proof bond
    /// ceil(v * (1 - x1) / x1), x1 = auditPpm * p0, apart from its bond. The
    /// entry is held and cannot be claimed until the proof ends. When the
    /// entry's epoch is sampled, its own sample case and every sample case
    /// of the account are decided and the sampling of every epoch of the
    /// account is decided, the proof opens: its audit use is registered in
    /// this block. Otherwise it is reserved and opens later by
    /// activateProof. One proof per entry.
    function submitProof(
        bytes32 nonce,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        ReceiptProof calldata proof,
        bytes calldata evidence
    ) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        if (!_purchaseExists(p)) revert InvalidTransition();
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Terms storage t = l.terms[p.profileId];
        if (!t.batched || t.auditPpm == 0) revert ProofNotAllowed();
        SellerView storage seller = sellers[p.sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        uint32 bondId = seller.bondId;
        BatchStore.ProofAccount storage acc = l.proofAccounts[bondId];
        if (acc.offSince != 0 || p.settledBlock <= acc.onSince) revert ProofsOff();
        BatchStore.Proof storage pr = l.proofs[nonce];
        if (pr.state != 0) revert ProofNotAllowed();
        BondView storage b = bonds[bondId];
        uint8 fs = p.financialState;
        if (
            b.freezeState != uint8(FreezeState.CLAIM_OPEN) || block.number > b.claimUntilBlock
                || !_inFreezeSpans(bondId, p.settledBlock) || _forfeitedEntry(p)
                || (fs != uint8(FinancialState.DEFERRED) && fs != uint8(FinancialState.RELEASABLE))
        ) revert ClaimWindowNotOpen();
        bytes32 leaf = _validateReceipt(p, nonce, receipt, receiptSignature);
        AnchorView storage a = anchors[p.sellerId][p.epoch];
        if (a.root == bytes32(0) || !_receiptProofValid(a, receipt, leaf, proof)) revert InvalidProof();
        if (receipt.predicateCommitment == bytes32(0)) revert InvalidReceipt();
        if (evidence.length == 0 || evidence.length > profiles[p.profileId].parameters.maxEvidenceBytes) {
            revert EvidenceTooLarge();
        }
        uint256 bond = _proofBond(p.value, p.profileId);
        pr.bond = uint96(bond);
        pr.evidenceHash = keccak256(evidence);
        _transferFrom(msg.sender, bond);
        _setFinancialState(nonce, FinancialState.HELD);
        acc.pending++;
        bool ready = _proofReady(nonce);
        emit ProofSubmitted(nonce, bond, pr.evidenceHash, !ready);
        if (ready) _openProof(pr, nonce);
        else pr.state = BatchStore.P_RESERVED;
    }

    /// Keeper call: a reserved proof whose conditions now hold opens; its
    /// audit use is registered in this block.
    function activateProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_RESERVED || !_proofReady(nonce)) revert InvalidTransition();
        _openProof(pr, nonce);
    }

    /// Ends a reserved proof whose conditions can no longer hold: its epoch
    /// failed, or passed its sampling deadline without a value. The bond goes
    /// back, the entry returns to the claim window from this block, and the
    /// proof does not count as the entry's one proof.
    function voidReservation(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_RESERVED || !_epochNeverDecides(nonce)) revert InvalidTransition();
        _returnBond(pr, nonce);
        _toClaimWindow(nonce, 0);
    }

    function requestAuditValue(bytes32 nonce) external onlyDelegateCall {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_OPEN) revert NotRegistered();
        if (block.number <= pr.auditBlock) revert RequestTooEarly();
        _vrf().request(VRF_AUX, _auditInput(nonce, pr.auditBlock), 0);
    }

    /// Keeper call: draws the audit with the proof's AUX value. An audited
    /// proof's judgment joins the batch of this block. An unaudited one is
    /// open to contest for contestBlocks, or confirmed at once when contest
    /// is off.
    function drawAudit(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Proof storage pr = l.proofs[nonce];
        if (pr.state != BatchStore.P_OPEN) revert NotRegistered();
        (bool ready, bytes32 value) = _vrf().valueOf(keccak256(abi.encode(VRF_AUX, _auditInput(nonce, pr.auditBlock))));
        if (!ready) revert DeadlineNotReached();
        BatchStore.Terms storage t = l.terms[purchases[nonce].profileId];
        uint256 draw = uint256(keccak256(abi.encode(AUDIT_DOMAIN, value, nonce)));
        bool audited = t.auditPpm == PPM || draw < _probabilityThreshold(t.auditPpm);
        if (audited) {
            pr.audited = true;
            emit ProofAuditDrawn(nonce, true, 0);
            _hook(HOOK_JOIN_PROOF, uint256(nonce));
        } else if (t.contestBlocks != 0) {
            pr.state = BatchStore.P_CONTEST;
            pr.contestUntil = uint64(block.number + t.contestBlocks);
            emit ProofAuditDrawn(nonce, false, pr.contestUntil);
        } else {
            emit ProofAuditDrawn(nonce, false, 0);
            _confirm(pr, nonce);
        }
    }

    /// The exit of an unanswered audit value: the proof ends without a
    /// verdict, its bond goes back, the entry returns to the claim window
    /// from this block, and the proof counts as the entry's one proof.
    function timeoutAuditValue(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_OPEN) revert NotRegistered();
        IVrfRandomness vrf = _vrf();
        (uint64 requested, uint64 delivered,) = vrf.requestTimes(keccak256(abi.encode(VRF_AUX, _auditInput(nonce, pr.auditBlock))));
        if (requested == 0 || delivered != 0) revert InvalidTransition();
        if (block.number <= uint256(requested) + vrf.responseBlocks() + vrf.deadlineSlackBlocks()) revert DeadlineNotReached();
        _exitProof(nonce);
    }

    /// Anyone contests an unaudited proof within its window with a deposit
    /// of the entry's value; the proof's judgment joins the batch of this block.
    function contestProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_CONTEST) revert InvalidTransition();
        if (block.number > pr.contestUntil) revert DeadlinePassed();
        uint256 deposit = purchases[nonce].value;
        pr.contested = true;
        pr.contester = msg.sender;
        pr.contestDeposit = uint96(deposit);
        _transferFrom(msg.sender, deposit);
        emit ProofContested(nonce, msg.sender, deposit);
        _hook(HOOK_JOIN_PROOF, uint256(nonce));
    }

    /// An unaudited proof without a contest is confirmed after its window.
    function confirmProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_CONTEST) revert InvalidTransition();
        if (block.number <= pr.contestUntil) revert DeadlineNotReached();
        _confirm(pr, nonce);
    }

    /// The assigned verifier's verdict on the proof: the predicate recomputed
    /// on the evidence envelope. PASS confirms the proof (a contest deposit
    /// is locked). FAIL forfeits the proof bond, pays the contester its
    /// deposit and min(bond, deposit), puts the rest in the account's
    /// compensation pool and counts one failure without a new freeze,
    /// deduction or suspension. INCONCLUSIVE forfeits the bond to the pool,
    /// returns the contest deposit and counts nothing. After FAIL or
    /// INCONCLUSIVE the entry returns to the claim window from this block.
    function judgeProof(bytes32 nonce, uint8 verdict, bytes calldata signature) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Proof storage pr = l.proofs[nonce];
        if (pr.state != BatchStore.P_JUDGING) revert InvalidTransition();
        if (block.number > pr.judgeDue) revert DeadlinePassed();
        if (verdict == uint8(Verdict.NONE) || verdict > uint8(Verdict.INCONCLUSIVE)) revert InvalidConfiguration();
        uint32 u = pr.verifier;
        if (_recover(_proofVerdictDigest(nonce, pr.attempt, u, verdict, pr.evidenceHash), signature) != verifiers[u].signingKey) {
            revert InvalidSignature();
        }
        emit ProofJudged(nonce, u, verdict);
        _releaseJudge(nonce, pr, 0);
        PurchaseView storage p = purchases[nonce];
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        address contester = pr.contester;
        uint256 deposit = pr.contestDeposit;
        pr.contestDeposit = 0;
        if (verdict == uint8(Verdict.PASS)) {
            if (deposit != 0) lockedForfeit += deposit;
            _confirm(pr, nonce);
            return;
        }
        uint256 forfeited = pr.bond;
        pr.bond = 0;
        uint256 share;
        if (verdict == uint8(Verdict.FAIL)) {
            share = deposit < forfeited ? deposit : forfeited;
            _countProofFailure(bondId);
        }
        if (deposit + share != 0) _transfer(contester, deposit + share);
        _addCompensation(bondId, forfeited - share);
        _endPending(bondId);
        pr.state = verdict == uint8(Verdict.FAIL) ? BatchStore.P_FAILED : BatchStore.P_INCONCLUSIVE;
        emit ProofEnded(nonce, pr.state);
        _toClaimWindow(nonce, bondId);
    }

    /// A judgment past its deadline is replaced: the verifier pays the late
    /// penalty and the next attempt takes the next verifier of the batch's
    /// draw. After maxAssignments attempts the proof ends without a verdict.
    function timeoutProofJudge(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        if (pr.state != BatchStore.P_JUDGING) revert InvalidTransition();
        if (block.number <= pr.judgeDue) revert DeadlineNotReached();
        ServiceProfileInput storage profile = profiles[purchases[nonce].profileId].parameters;
        _releaseJudge(nonce, pr, profile.verifierLatePenalty);
        if (uint256(pr.attempt) + 1 >= profile.maxAssignments) {
            _exitProof(nonce);
            return;
        }
        pr.attempt++;
        pr.state = BatchStore.P_BATCHED;
        _hook(HOOK_PLACE_PROOF, uint256(nonce));
    }

    /// The seller is paid a proven entry once its effective age reaches the
    /// hold period and the release rules of releasePurchase hold.
    function releaseProven(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        PurchaseView storage p = purchases[nonce];
        if (pr.state != BatchStore.P_CONFIRMED || p.financialState != uint8(FinancialState.HELD) || _buyerRecoveryOpen(nonce)) {
            revert InvalidTransition();
        }
        AnchorView storage a = anchors[p.sellerId][p.epoch];
        if (a.state != uint8(EpochState.SEALED)) revert InvalidTransition();
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        if (
            block.number <= p.claimUntil
                || block.number <= a.sealDeadline + deadlineConfigs[profiles[p.profileId].parameters.deadlineConfigId].openBlocks
                || block.number < p.retainUntil || block.number - _pausedSince(bondId, p.settledBlock) < p.releaseBlock
        ) revert DeadlineNotReached();
        _payDeposits(nonce);
        _setFinancialState(nonce, FinancialState.RELEASED);
        _transfer(sellers[p.sellerId].viewData.owner, p.value);
        emit Released(nonce, p.sellerId, p.value);
    }

    /// Hook operations of this module: a confirmed failure of a purchase
    /// (one operation per refund source) and a proof ending without a verdict.
    /// Keeper call: an anchored epoch of a batched profile has no sampling
    /// value it takes past A + D_S. The seller's account pauses from the
    /// block after A + D_S until the epoch is sealed or fails, or, outside a
    /// side-gain profile, until M has passed and noteSampleDeadline is called.
    function markSampleLate(uint32 sellerId, uint24 epoch) external onlyDelegateCall nonReentrant {
        AnchorView storage a = anchors[sellerId][epoch];
        BatchStore.Layout storage l = BatchStore.layout();
        if (a.state != uint8(EpochState.ANCHORED) || !l.terms[a.profileId].batched || l.samplePaused[sellerId][epoch]) {
            revert InvalidTransition();
        }
        IVrfRandomness vrf = _vrfAt(a.anchoredBlock);
        if (address(vrf) == address(0)) revert InvalidTransition();
        uint64 deadline = _anchorDeadline(profiles[a.profileId].parameters, epoch);
        uint256 due = uint256(deadline) + vrf.delayBlocks();
        if (block.number <= due) revert DeadlineNotReached();
        if (_sampleValue(vrf, a.profileId, deadline) != bytes32(0)) revert InvalidTransition();
        if (l.terms[a.profileId].sideGainPpm == 0) {
            if (block.number > _sampleDeadline(vrf, deadline)) revert DeadlinePassed();
        } else if (_repeatedSampleValue(vrf, a.profileId, deadline) != bytes32(0)) {
            revert InvalidTransition();
        }
        l.samplePaused[sellerId][epoch] = true;
        uint256 from = _lateStart(due);
        _pauseFrom(sellers[sellerId].viewData.bondId, from);
        emit SampleWaitPaused(sellerId, epoch, uint64(from));
    }

    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op >= HOOK_FAILURE && op < HOOK_FAILURE + 8) {
            _failure(bytes32(arg), uint8(op - HOOK_FAILURE));
        } else if (op == HOOK_PROOF_EXIT) {
            _exitProof(bytes32(arg));
        } else if (op == HOOK_SAMPLE_RESUME) {
            // The epoch's sampling is decided: its late-value pause ends (ADR 0036).
            uint32 sellerId = uint32(arg >> 24);
            BatchStore.layout().samplePaused[sellerId][uint24(arg)] = false;
            _pauseEnd(sellers[sellerId].viewData.bondId);
        } else {
            _unknownHook();
        }
    }

    function hookOps() external pure returns (uint256) {
        return (uint256(0xff) << HOOK_FAILURE) | (1 << HOOK_PROOF_EXIT) | (1 << HOOK_SAMPLE_RESUME);
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](20);
        s[0] = this.submitProof.selector;
        s[1] = this.activateProof.selector;
        s[2] = this.voidReservation.selector;
        s[3] = this.requestAuditValue.selector;
        s[4] = this.drawAudit.selector;
        s[5] = this.timeoutAuditValue.selector;
        s[6] = this.contestProof.selector;
        s[7] = this.confirmProof.selector;
        s[8] = this.judgeProof.selector;
        s[9] = this.timeoutProofJudge.selector;
        s[10] = this.releaseProven.selector;
        s[11] = this.distributeCompensation.selector;
        s[12] = this.claimCompensation.selector;
        s[13] = this.proofVerdictDigest.selector;
        s[14] = this.getProof.selector;
        s[15] = this.getProofAccount.selector;
        s[16] = this.getPool.selector;
        s[17] = this.proofBondOf.selector;
        s[18] = this.proofReady.selector;
        s[19] = this.markSampleLate.selector;
    }

    // ------------------------------------------------------------ hooks

    /// A confirmed failure of the purchase: an undecided proof on it ends and
    /// its bond goes back (a reservation does not count as the entry's
    /// proof); a confirmed proof is void and its entry leaves the pool's
    /// shares, keeping what it accrued. A sample case's failure under a
    /// side-gain profile deducts one side-gain unit (ADR 0035).
    function _failure(bytes32 nonce, uint8 source) private {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Proof storage pr = l.proofs[nonce];
        PurchaseView storage p = purchases[nonce];
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        uint8 st = pr.state;
        if (st == BatchStore.P_CONFIRMED) {
            pr.state = BatchStore.P_INVALID;
            _dropShare(l, bondId, nonce, p.value);
            emit ProofEnded(nonce, BatchStore.P_INVALID);
        } else if (st != 0 && st < BatchStore.P_CONFIRMED) {
            if (st == BatchStore.P_QUEUED || st == BatchStore.P_BATCHED) {
                _hook(HOOK_CASE_LEAVES, uint256(_proofCase(nonce)));
            } else if (st == BatchStore.P_JUDGING) {
                _releaseJudge(nonce, pr, 0);
            }
            _refundContest(pr);
            bool reserved = st == BatchStore.P_RESERVED;
            _returnBond(pr, nonce);
            if (!reserved) pr.state = BatchStore.P_ENDED;
            emit ProofEnded(nonce, pr.state);
        }
        if (
            l.terms[p.profileId].sideGainPpm != 0 && cases[nonce].trigger == uint8(CaseTrigger.SAMPLE)
                && (source == uint8(RefundSource.FINAL_FAIL) || source == uint8(RefundSource.UNSERVED))
        ) {
            BatchStore.SideGain storage g = l.sideGain[bondId];
            uint256 cut = _sideGainUnit(bondId, p.profileId);
            if (cut > g.deposit) cut = g.deposit;
            g.deposit -= uint128(cut);
            lockedForfeit += cut;
            emit SideGainChanged(bondId, g.deposit);
        }
    }

    // ------------------------------------------------------ compensation

    /// Keeper call: distributes the account's pool over the entries released
    /// by confirmed proofs, in proportion to their value, once no proof or
    /// reservation of the account is undecided. With no such entry the pool
    /// waits, and is locked once the account's bond has exited.
    function distributeCompensation(uint32 bondId) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Pool storage pool = l.pools[_poolOf(bondId)];
        if (pool.balance == 0 || l.proofAccounts[bondId].pending != 0) revert InvalidTransition();
        if (pool.weight == 0) {
            if (bonds[bondId].status != uint8(BondStatus.EXITED)) revert InvalidTransition();
            lockedForfeit += pool.balance;
            pool.balance = 0;
            return;
        }
        uint256 delta = pool.balance * INDEX_SCALE / pool.weight;
        uint256 paid = delta * pool.weight / INDEX_SCALE;
        pool.index += delta;
        pool.balance -= paid;
        emit CompensationDistributed(bondId, paid, pool.weight);
    }

    /// Pays the buyer of a proven entry its share of the distributions so far.
    function claimCompensation(bytes32 nonce) external onlyDelegateCall nonReentrant {
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Share storage s = l.shares[nonce];
        PurchaseView storage p = purchases[nonce];
        BatchStore.Pool storage pool = l.pools[_poolOf(sellers[p.sellerId].viewData.bondId)];
        uint256 amount = s.accrued;
        if (l.proofs[nonce].weighted) amount += p.value * (pool.index - s.entryIndex) / INDEX_SCALE;
        if (amount == 0) revert InvalidTransition();
        s.accrued = 0;
        s.entryIndex = pool.index;
        _transfer(p.buyer, amount);
        emit CompensationPaid(nonce, p.buyer, amount);
    }

    /// Proof bond ceil(v * (1 - x1) / x1), x1 = auditPpm * p0 in ppm.
    function _proofBond(uint256 value, uint32 profileId) internal view returns (uint256) {
        ProfileTerms storage pt = profileTerms[profileId];
        uint256 p0 = pt.tiers.length != 0 ? pt.detectFloorPpm : profiles[profileId].parameters.effectivePpm;
        uint256 x1 = uint256(BatchStore.layout().terms[profileId].auditPpm) * p0 / PPM;
        if (x1 == 0) revert InvalidConfiguration();
        return (value * (PPM - x1) + x1 - 1) / x1;
    }

    /// The conditions under which a proof opens: the entry's epoch is sealed
    /// and past its batch close, its sample case (if sampled) has ended, no
    /// sample case of the account is open, and every epoch in which the
    /// account sold has its sampling decided.
    function _proofReady(bytes32 nonce) internal view virtual returns (bool) {
        PurchaseView storage p = purchases[nonce];
        AnchorView storage a = anchors[p.sellerId][p.epoch];
        if (a.state != uint8(EpochState.SEALED)) return false;
        ServiceProfileInput storage profile = profiles[p.profileId].parameters;
        if (block.number <= a.sealDeadline + deadlineConfigs[profile.deadlineConfigId].openBlocks) return false;
        BatchStore.ProofAccount storage acc = BatchStore.layout().proofAccounts[sellers[p.sellerId].viewData.bondId];
        if (acc.openSamples != 0 || acc.unsealedEpochs != 0) return false;
        (bool eligible,) = _sampleStatus(p, nonce);
        if (!eligible) return true;
        uint8 cs = cases[nonce].state;
        return cs == uint8(CaseState.FINAL) || cs == uint8(CaseState.INCONCLUSIVE) || cs == uint8(CaseState.DELIVERED);
    }

    /// Whether the entry's epoch can never have its sampling decided.
    function _epochNeverDecides(bytes32 nonce) internal view returns (bool) {
        PurchaseView storage p = purchases[nonce];
        uint8 es = anchors[p.sellerId][p.epoch].state;
        if (es == uint8(EpochState.EPOCH_FAILED)) return true;
        return es == uint8(EpochState.ANCHORED) && _deadlinePassed(p.sellerId, p.epoch);
    }

    function _openProof(BatchStore.Proof storage pr, bytes32 nonce) internal {
        pr.state = BatchStore.P_OPEN;
        pr.auditBlock = uint64(block.number);
        emit ProofOpened(nonce, pr.auditBlock);
    }

    /// The proof is confirmed: its bond goes back and the entry takes a share
    /// of the account's compensation pool from now on.
    function _confirm(BatchStore.Proof storage pr, bytes32 nonce) internal {
        BatchStore.Layout storage l = BatchStore.layout();
        PurchaseView storage p = purchases[nonce];
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        uint256 bond = pr.bond;
        pr.bond = 0;
        pr.state = BatchStore.P_CONFIRMED;
        pr.weighted = true;
        BatchStore.Pool storage pool = l.pools[_poolOf(bondId)];
        pool.weight += p.value;
        l.shares[nonce].entryIndex = pool.index;
        _endPending(bondId);
        if (bond != 0) _transfer(sellers[p.sellerId].viewData.owner, bond);
        emit ProofEnded(nonce, BatchStore.P_CONFIRMED);
    }

    function _dropShare(BatchStore.Layout storage l, uint32 bondId, bytes32 nonce, uint256 value) internal {
        BatchStore.Pool storage pool = l.pools[_poolOf(bondId)];
        BatchStore.Share storage s = l.shares[nonce];
        s.accrued += value * (pool.index - s.entryIndex) / INDEX_SCALE;
        s.entryIndex = pool.index;
        pool.weight -= value;
        l.proofs[nonce].weighted = false;
    }

    function _addCompensation(uint32 bondId, uint256 amount) internal {
        if (amount == 0) return;
        BatchStore.layout().pools[_poolOf(bondId)].balance += amount;
        emit CompensationAdded(bondId, amount);
    }

    /// The pool an account's forfeited proof bonds go to and its proven
    /// entries share. Every production build: the account's own. A mutation
    /// build of the tests overrides it.
    function _poolOf(uint32 bondId) internal pure virtual returns (uint32) {
        return bondId;
    }

    function _endPending(uint32 bondId) internal {
        BatchStore.layout().proofAccounts[bondId].pending--;
    }

    /// The proof bond goes back to the seller; the proof stops being undecided.
    function _returnBond(BatchStore.Proof storage pr, bytes32 nonce) internal {
        PurchaseView storage p = purchases[nonce];
        uint256 bond = pr.bond;
        pr.bond = 0;
        bool reserved = pr.state == BatchStore.P_RESERVED;
        if (reserved) pr.state = 0;
        _endPending(sellers[p.sellerId].viewData.bondId);
        if (bond != 0) _transfer(sellers[p.sellerId].viewData.owner, bond);
    }

    function _refundContest(BatchStore.Proof storage pr) internal {
        uint256 deposit = pr.contestDeposit;
        if (deposit == 0) return;
        pr.contestDeposit = 0;
        _transfer(pr.contester, deposit);
    }

    /// Ends a proof without a verdict: bond and contest deposit go back, the
    /// entry returns to the claim window, the proof counts as the entry's one.
    function _exitProof(bytes32 nonce) internal {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        _refundContest(pr);
        _returnBond(pr, nonce);
        pr.state = BatchStore.P_ENDED;
        emit ProofEnded(nonce, BatchStore.P_ENDED);
        _toClaimWindow(nonce, 0);
    }

    /// The entry returns to the frozen window and its claim period runs
    /// again from this block.
    function _toClaimWindow(bytes32 nonce, uint32) internal {
        PurchaseView storage p = purchases[nonce];
        if (p.financialState != uint8(FinancialState.HELD)) return;
        _setFinancialState(nonce, FinancialState.DEFERRED);
        BondView storage b = bonds[sellers[p.sellerId].viewData.bondId];
        uint64 until = uint64(block.number + profiles[p.profileId].parameters.claimWindowBlocks);
        if (b.claimUntilBlock < until) b.claimUntilBlock = until;
    }

    /// Frees the verifier of the proof's judgment, with a late penalty when
    /// given, and lets its queue start.
    function _releaseJudge(bytes32 nonce, BatchStore.Proof storage pr, uint256 penalty) internal {
        uint32 u = pr.verifier;
        pr.verifier = 0;
        ServiceProfileInput storage profile = profiles[purchases[nonce].profileId].parameters;
        VerifierView storage v = verifiers[u];
        VerifierCapital storage capital = verifierCapital[u];
        uint256 reserve = profile.verifierLatePenalty > profile.verifierWrongPenalty
            ? profile.verifierLatePenalty : profile.verifierWrongPenalty;
        v.lockedLiability -= purchases[nonce].value + profile.maxReviewCost;
        capital.reservedPenalties -= reserve;
        if (v.lockedLiability == 0) {
            capital.conservativeCap = 0;
            capital.conservativeFraction = 0;
        }
        if (penalty != 0) {
            _noteVerifier(u);
            if (penalty > v.bond) penalty = v.bond;
            v.bond -= penalty;
            if (v.strikes < type(uint16).max) v.strikes++;
            if (v.strikes >= profile.strikeLimit
                && (v.status == uint8(VerifierStatus.ACTIVE) || v.status == uint8(VerifierStatus.EXITING))) {
                v.status = uint8(VerifierStatus.REMOVED);
            }
            _transfer(penaltyTreasury, penalty);
            emit Slashed(2, u, nonce, penaltyTreasury, penalty, 2);
        }
        _hook(HOOK_SLOT_FREED, u);
    }

    /// One failure of the account, counted in its failure window without a
    /// freeze, deduction or suspension.
    function _countProofFailure(uint32 bondId) internal {
        BondView storage b = bonds[bondId];
        ServiceProfileInput storage profile = profiles[b.profileId].parameters;
        if (b.failureCount == 0 || block.number > uint256(b.failureWindowStart) + profile.failureWindowBlocks) {
            b.failureCount = 0;
            b.failureWindowStart = uint64(block.number);
        }
        b.failureCount++;
    }

    function _proofVerdictDigest(bytes32 nonce, uint8 attempt, uint32 verifierId, uint8 verdict, bytes32 evidenceHash)
        internal
        view
        returns (bytes32)
    {
        bytes32 h = keccak256(abi.encode(PROOF_VERDICT_TYPEHASH, nonce, attempt, verifierId, verdict, evidenceHash));
        bytes32 domain = keccak256(abi.encode(EIP712_DOMAIN_TYPEHASH, keccak256("FairBind"), keccak256("1"), block.chainid, address(this)));
        return keccak256(abi.encodePacked(hex"1901", domain, h));
    }

    // ------------------------------------------------------------- views

    function proofVerdictDigest(bytes32 nonce, uint8 verdict) external view onlyDelegateCall returns (bytes32) {
        BatchStore.Proof storage pr = BatchStore.layout().proofs[nonce];
        return _proofVerdictDigest(nonce, pr.attempt, pr.verifier, verdict, pr.evidenceHash);
    }

    function getProof(bytes32 nonce) external view onlyDelegateCall returns (BatchStore.Proof memory) {
        return BatchStore.layout().proofs[nonce];
    }

    function getProofAccount(uint32 bondId) external view onlyDelegateCall returns (BatchStore.ProofAccount memory) {
        return BatchStore.layout().proofAccounts[bondId];
    }

    function getPool(uint32 bondId) external view onlyDelegateCall returns (BatchStore.Pool memory) {
        return BatchStore.layout().pools[_poolOf(bondId)];
    }

    function proofBondOf(bytes32 nonce) external view onlyDelegateCall returns (uint256) {
        PurchaseView storage p = purchases[nonce];
        return _proofBond(p.value, p.profileId);
    }

    function proofReady(bytes32 nonce) external view onlyDelegateCall returns (bool) {
        return _proofReady(nonce);
    }
}
