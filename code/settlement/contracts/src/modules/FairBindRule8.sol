// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { FairBindDesign2 } from "../FairBindDesign2.sol";
import { IRandomness } from "../randomness/IRandomness.sol";
import { IVrfRandomness } from "../randomness/IVrfRandomness.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { Rule8Shared } from "./Rule8Shared.sol";
import { Rule8Store } from "./Rule8Store.sol";

/// Extension module 8 (rule edition 8, v0.3): the rule 8 terms of a profile,
/// the profile-level seal and its checkpoint-shortage end, and the closing of
/// profile epochs that holds verifier exits (rule D2-35).
contract FairBindRule8 is Rule8Shared {
    uint8 public constant MODULE_KIND = 18;

    bytes32 internal constant RULE8_TERMS_DOMAIN = keccak256("fairbind/rule8-terms/v1");

    event Rule8TermsSet(uint32 indexed profileId, bytes32 termsHash);
    event ProfileEpochSealed(uint32 indexed profileId, uint24 indexed epoch, bytes32 randomness, uint64 version);
    event ProfileEpochFailed(uint32 indexed profileId, uint24 indexed epoch);
    event ProfileEpochsClosed(uint32 indexed profileId, uint24 closedBelow);
    event AnchorEquivocation(uint32 indexed sellerId, uint24 indexed epoch, bytes32 firstHash, bytes32 secondHash);
    event PoolFunded(uint32 indexed profileId, address indexed from, uint256 amount);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        Rule8Shared(token, gov, guard, treasury, rewardPool)
    { }

    // ------------------------------------------------------------- terms

    /// Fixes the rule 8 terms of a profile that has never been active, once.
    /// A profile with batch terms is not admitted (its sample cases open in
    /// batches that this edition does not cover yet).
    function setRule8Terms(uint32 profileId, Rule8Store.Input calldata x) external onlyDelegateCall onlyGovernance {
        if (profiles[profileId].profileId == 0) revert UnknownProfile();
        if (profiles[profileId].active || profileActivated[profileId]) revert InvalidTransition();
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        Rule8Store.Terms storage t = r8.terms[profileId];
        if (t.on || _batched(profileId)) revert InvalidTransition();
        if (x.termsHash != rule8TermsHash(profileId, x)) revert InvalidConfiguration();
        if (x.unitLog2 > 16) revert InvalidConfiguration();
        _admitPath(profileId, x);
        t.on = true;
        t.unitLog2 = x.unitLog2;
        t.bulkSig = x.bulkSig;
        t.heldWindow = x.heldWindow;
        t.winBlocks = x.winBlocks;
        t.buyerWindow = x.buyerWindow;
        t.cAnchor = x.cAnchor;
        t.cCase = x.cCase;
        t.cR0 = x.cR0;
        t.cR1 = x.cR1;
        t.cEp = x.cEp;
        t.termsHash = x.termsHash;
        uint256 n = x.callFees.length;
        if (n > Rule8Store.FEE_KINDS) revert InvalidConfiguration();
        for (uint256 i = 1; i < n; i++) r8.callFees[profileId][uint8(i)] = x.callFees[i];
        r8.profileList.push(profileId);
        emit Rule8TermsSet(profileId, x.termsHash);
    }

    /// The judgment path of a rule 8 profile (rule D2-40): the profile picks
    /// its attempt count m in {1, 2, 3} (maxAssignments) and its window
    /// lengths (its deadline configuration), and every rule 8 profile keeps
    /// the appeals, the review and the tiebreak, so appeal windows and the
    /// appeal deposit cannot be zero (rule D2-40 (b); a profile without
    /// appeals is not admitted). The window length T_win(m) must cover the
    /// profile's own failure path: T_win >= L_F(m) + kappa_bar, with L_F(m)
    /// the judgment delay of the profile check under its m and windows and
    /// kappa_bar its marginBlocks (rule D2-40 (c)); D_bar_w is a term of
    /// T_win the contract does not see. A buyer window w_b of zero is
    /// refused (rule D2-13 check 7).
    function _admitPath(uint32 profileId, Rule8Store.Input calldata x) private view {
        ServiceProfileInput storage p = profiles[profileId].parameters;
        DeadlineConfig storage d = deadlineConfigs[p.deadlineConfigId];
        uint16 m = p.maxAssignments;
        if (m == 0 || m > 3) revert InvalidConfiguration();
        if (d.appealBlocks == 0 || p.appealDeposit == 0) revert InvalidConfiguration();
        if (x.winBlocks < rule8MinWindow(profileId) || x.buyerWindow == 0) revert InvalidConfiguration();
        // The held window H_N >= (T_epoch - 1) + T_win(m) (rule D2-13 (1), D2-42 (b)).
        if (uint256(x.heldWindow) < uint256(p.epochBlocks) - 1 + x.winBlocks) revert InvalidConfiguration();
    }

    /// The shortest window T_win(m) the profile admits: L_F(m) + marginBlocks.
    function rule8MinWindow(uint32 profileId) public view returns (uint256) {
        ServiceProfileInput storage p = profiles[profileId].parameters;
        DeadlineConfig storage d = deadlineConfigs[p.deadlineConfigId];
        return _judgmentDelay(p.epochBlocks, p.beaconDelayBlocks, p.maxAssignments, d) + p.marginBlocks;
    }

    /// termsHash of an input, as setRule8Terms checks it.
    function rule8TermsHash(uint32 profileId, Rule8Store.Input calldata x) public pure returns (bytes32) {
        Rule8Store.Input memory m = x;
        m.termsHash = 0;
        return keccak256(abi.encode(RULE8_TERMS_DOMAIN, profileId, m));
    }

    // ---------------------------------------------------- profile seal

    /// The seal of profile epoch e (rule D2-35 (a)): anyone may call it once
    /// the SAMPLE value of the epoch is on chain. It writes the value and the
    /// checkpoint of block A_e to the profile epoch record. Every seller epoch
    /// anchored by A_e is sealed by it; there is no seal per seller epoch
    /// and no verifier exit is delayed per seller.
    function sealProfile(uint32 profileId, uint24 epoch) external onlyDelegateCall {
        Rule8Store.ProfileEpoch storage pe = _openProfileEpoch(profileId, epoch);
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint64 a = _anchorDeadline(profile, epoch);
        uint256 randomBlock = uint256(a) + 1 + _valueDelay(profile);
        if (block.number <= randomBlock) revert DeadlineNotReached();
        bytes32 randomness;
        IRandomness source = _sourceAt(a);
        if (address(source) == address(0)) {
            randomness = blockhash(randomBlock);
        } else if (SamplingStore.layout().randomness.vrf) {
            randomness = _sampleValue(IVrfRandomness(address(source)), profileId, a);
        } else {
            bool ready;
            (ready, randomness) = source.valueOf(a);
            if (!ready) randomness = bytes32(0);
        }
        if (randomness == bytes32(0)) revert InvalidRandomnessWindow();
        uint64 version = _checkpointAt(profileId, a);
        if (version == 0) revert ServiceClassUnavailable();
        VerifierCheckpoint storage checkpoint = verifierCheckpoints[profileId][version];
        if (checkpoint.verifierIds.length < profile.minVerifiers) revert ServiceClassUnavailable();
        pe.randomness = randomness;
        pe.setHash = checkpoint.setHash;
        pe.weight = checkpoint.totalEffectiveWeight;
        pe.version = version;
        pe.state = Rule8Store.PE_SEALED;
        emit ProfileEpochSealed(profileId, epoch, randomness, version);
        _fee(profileId, Rule8Store.FEE_SEAL);
    }

    /// The checkpoint shortage of profile epoch e, confirmed once for the
    /// profile (rule D2-35 (c)): after A_e, when the checkpoint of block A_e
    /// is missing or holds fewer than minVerifiers verifiers. Every seller
    /// epoch of the profile epoch ends without a seller failure.
    function timeoutSealProfile(uint32 profileId, uint24 epoch) external onlyDelegateCall {
        Rule8Store.ProfileEpoch storage pe = _openProfileEpoch(profileId, epoch);
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint64 a = _anchorDeadline(profile, epoch);
        if (block.number <= a) revert DeadlineNotReached();
        uint64 version = _checkpointAt(profileId, a);
        if (version != 0 && verifierCheckpoints[profileId][version].verifierIds.length >= profile.minVerifiers) {
            revert InvalidTransition();
        }
        pe.state = Rule8Store.PE_FAILED;
        emit ProfileEpochFailed(profileId, epoch);
        _fee(profileId, Rule8Store.FEE_SEAL_TIMEOUT);
    }

    function _openProfileEpoch(uint32 profileId, uint24 epoch)
        private
        view
        returns (Rule8Store.ProfileEpoch storage pe)
    {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[profileId].on) revert InvalidTransition();
        pe = r8.profileEpochs[profileId][epoch];
        if (pe.state != Rule8Store.PE_NONE) revert InvalidTransition();
    }

    // ---------------------------------------- signed anchor (revision 2)

    /// The seller-signed anchor (rule D2-36): anyone may submit, within the
    /// anchor window, the seller's EIP-712 signature over the anchor content
    /// together with the full (nonce, leaf) list. The contract computes the
    /// root from the list and takes the anchor only when the computed root,
    /// root0 and count are the signed ones and the count is the epoch's
    /// settlement count. The submitter is paid c_anchor from the profile fee
    /// pool in the same transaction (rule D2-36 (e)). The seller's own
    /// unsigned anchor stays open to the seller owner.
    function anchorSigned(
        Rule8Store.AnchorContent calldata c,
        FairBindMerkle.ReceiptEntry[] calldata entries,
        bytes calldata sellerSig
    ) external onlyDelegateCall nonReentrant {
        SellerView storage seller = sellers[c.sellerId].viewData;
        if (seller.status == uint8(SellerStatus.NONE) || seller.status == uint8(SellerStatus.EXITED)) {
            revert SellerInactive();
        }
        uint32 profileId = seller.profileId;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[profileId].on || c.profileId != profileId) revert InvalidTransition();
        if (c.publicationHash == bytes32(0)) revert InvalidConfiguration();
        uint32 count = c.count;
        if (count == 0 || count != epochPurchaseCount[c.sellerId][c.epoch] || entries.length != count) {
            revert CountMismatch();
        }
        AnchorView storage record = anchors[c.sellerId][c.epoch];
        if (record.state != uint8(EpochState.NONE)) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint256 base = _anchorBase(profile, c.epoch);
        uint256 deadline = base + deadlineConfigs[profile.deadlineConfigId].anchorBlocks;
        if (block.number < base) revert AnchorTooEarly();
        if (block.number > deadline) revert AnchorWindowClosed();
        if (!FairBindMerkle.strictlyAscending(entries)) revert EntriesNotAscending();
        bytes32 root = FairBindMerkle.computeRoot(entries);
        if (root == bytes32(0) || root != c.root || c.root0 != root) revert InvalidProof();
        if (c.units != 1 || c.unitsHash != keccak256(abi.encode(root, c.root0))) revert InvalidProof();
        bytes32 structHash = _anchorStructHash(c);
        if (!_sellerSigned(c.sellerId, profileId, structHash, sellerSig)) revert InvalidSignature();
        ExchangeStore.mark();
        r8.sellerEpochs[c.sellerId][c.epoch].content = structHash;
        _finishAnchor(c.sellerId, c.epoch, record, profile, deadline, root, c.publicationHash, count);
        emit SignedAnchor(c.sellerId, c.epoch, msg.sender, structHash);
        _r8PayFee(profileId, msg.sender, r8.terms[profileId].cAnchor);
    }

    /// Two anchor contents of the same seller epoch, both signed with the
    /// seller's signing key, whose (root0, count) differ are a confirmed
    /// failure of the seller (rule D2-37): s_f is the first sale of that
    /// seller epoch, handled as a missed anchor is (freeze from the epoch's
    /// first block, one counted failure). Only for an EOA signing key (rule
    /// D2-37 (d)), and only from the opening of the anchor window until the
    /// release cursor passes the epoch (rule D2-37 (c)). Two contents that
    /// differ only in root, publicationHash, K or U are no equivocation.
    function proveAnchorEquivocation(
        Rule8Store.AnchorContent calldata a,
        bytes calldata sigA,
        Rule8Store.AnchorContent calldata b,
        bytes calldata sigB
    ) external onlyDelegateCall nonReentrant {
        if (a.sellerId != b.sellerId || a.profileId != b.profileId || a.epoch != b.epoch) revert InvalidProof();
        if (a.root0 == b.root0 && a.count == b.count) revert InvalidProof();
        uint32 sellerId = a.sellerId;
        SellerView storage seller = sellers[sellerId].viewData;
        uint32 profileId = seller.profileId;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[profileId].on || a.profileId != profileId) revert InvalidTransition();
        if (seller.signingKey.code.length != 0) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        if (block.number < _anchorBase(profile, a.epoch) || r8.cursor[sellerId] > a.epoch) revert InvalidTransition();
        if (epochFailureCounted[sellerId][a.epoch]) revert AlreadyFinalized();
        bytes32 ha = _anchorStructHash(a);
        bytes32 hb = _anchorStructHash(b);
        if (!_sellerSigned(sellerId, profileId, ha, sigA) || !_sellerSigned(sellerId, profileId, hb, sigB)) {
            revert InvalidSignature();
        }
        epochFailureCounted[sellerId][a.epoch] = true;
        emit AnchorEquivocation(sellerId, a.epoch, ha, hb);
        _confirmFailure(sellerId, bytes32(0), true, _epochStart(profile, a.epoch));
    }

    /// The EIP-712 digest of an anchor content under the profile's domain.
    function anchorDigest(Rule8Store.AnchorContent calldata c) external view onlyDelegateCall returns (bytes32) {
        return _typed(c.profileId, _anchorStructHash(c));
    }

    // ------------------------------------------------- fee pool (rule D2-38)

    /// Anyone may add to the profile fee pool.
    function fundPool(uint32 profileId, uint256 amount) external onlyDelegateCall nonReentrant {
        if (!Rule8Store.layout().terms[profileId].on || amount == 0) revert InvalidTransition();
        _transferFrom(msg.sender, amount);
        Rule8Store.layout().pool[profileId] += amount;
        emit PoolFunded(profileId, msg.sender, amount);
    }

    /// Pays owed fees from the pool in the order they were written (rule
    /// D2-38 (d)), at most `max` of them. A call that pays none reverts.
    function payOwedFees(uint32 profileId, uint256 max) external onlyDelegateCall nonReentrant {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        Rule8Store.Owed[] storage q = r8.owed[profileId];
        uint256 head = r8.owedHead[profileId];
        uint256 start = head;
        while (head < q.length && head - start < max) {
            Rule8Store.Owed storage o = q[head];
            if (r8.pool[profileId] < o.amount) break;
            r8.pool[profileId] -= o.amount;
            _transfer(o.to, o.amount);
            emit R8FeePaid(profileId, o.to, o.amount);
            delete q[head];
            head++;
        }
        if (head == start) revert InvalidTransition();
        r8.owedHead[profileId] = head;
    }

    // ----------------------------------------------- profile epoch closing

    /// Moves the profile's lowest open epoch up over the epochs that are
    /// closed (rule D2-35 (d) 1): the epoch is over, so no seller epoch can
    /// open in it any more, and every seller epoch with sales in it has been
    /// passed by its seller's release cursor. Anyone may call it; at most
    /// `steps` epochs are looked at. A call that closes nothing reverts.
    function closeProfileEpochs(uint32 profileId, uint24 steps) external onlyDelegateCall {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.terms[profileId].on) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[profileId].parameters;
        uint24 e = r8.closedBelow[profileId];
        uint24 start = e;
        for (uint24 i; i < steps; i++) {
            if (block.number < _epochStart(profile, e + 1)) break;
            if (r8.openSellerEpochs[profileId][e] != 0 || r8.openOtherCases[profileId][e] != 0) break;
            e++;
        }
        if (e == start) revert InvalidTransition();
        r8.closedBelow[profileId] = e;
        emit ProfileEpochsClosed(profileId, e);
        _fee(profileId, Rule8Store.FEE_CLOSE);
    }

    /// Notes the end of a counted case outside the sample cases (rule D2-35
    /// (d) 1 (ii)): anyone may call it once the case is at an end state; the
    /// case then no longer holds its profile epoch open.
    function noteCaseEnded(bytes32 nonce) external onlyDelegateCall {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.otherCounted[nonce]) revert InvalidTransition();
        uint8 s = cases[nonce].state;
        if (s != uint8(CaseState.DELIVERED) && s != uint8(CaseState.UNSERVED) && s != uint8(CaseState.INCONCLUSIVE)
            && s != uint8(CaseState.FINAL)) revert InvalidTransition();
        r8.otherCounted[nonce] = false;
        PurchaseView storage p = purchases[nonce];
        r8.openOtherCases[p.profileId][p.epoch]--;
        _fee(p.profileId, Rule8Store.FEE_CLOSE);
    }

    function getOpenOtherCases(uint32 profileId, uint24 epoch) external view onlyDelegateCall returns (uint32) {
        return Rule8Store.layout().openOtherCases[profileId][epoch];
    }

    // ------------------------------------------------------------- views

    function getRule8Terms(uint32 profileId) external view onlyDelegateCall returns (Rule8Store.Terms memory) {
        return Rule8Store.layout().terms[profileId];
    }

    function getProfileEpoch(uint32 profileId, uint24 epoch)
        external
        view
        onlyDelegateCall
        returns (Rule8Store.ProfileEpoch memory pe, uint32 openSellerEpochs)
    {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        return (r8.profileEpochs[profileId][epoch], r8.openSellerEpochs[profileId][epoch]);
    }

    function getClosedBelow(uint32 profileId) external view onlyDelegateCall returns (uint24) {
        return Rule8Store.layout().closedBelow[profileId];
    }

    function getFeePool(uint32 profileId) external view onlyDelegateCall returns (uint256 pool, uint256 owedCount, uint256 owedHead) {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        return (r8.pool[profileId], r8.owed[profileId].length, r8.owedHead[profileId]);
    }

    /// Whether the purchase was paid by the batch payment of its seller
    /// epoch (rule D2-39 (c)): its seller epoch was paid as a batch, it was
    /// not left out for a separate release, it is still DEFERRED or
    /// RELEASABLE, and it is a sale. The batch pays in one transfer and
    /// leaves the purchase records as they are; the core reads this through
    /// a static call.
    function r8Paid(bytes32 nonce) external view onlyDelegateCall returns (bool) {
        PurchaseView storage purchase = purchases[nonce];
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.sellerEpochs[purchase.sellerId][purchase.epoch].paid) return false;
        if (r8.itemFlag[nonce] != 0) return false;
        uint8 s = purchase.financialState;
        if (s != uint8(FinancialState.DEFERRED) && s != uint8(FinancialState.RELEASABLE)) return false;
        return _r8Sale(nonce, purchase.profileId, purchase.sellerId, purchase.epoch);
    }

    // ------------------------------------------------------------- hooks

    /// Calls of the modules into rule 8 (ADR 0032 hooks): the fee of a
    /// required call, the copy of a profile seal (plain, for seal, and for a
    /// checkpoint shortage), the held count of a purchase that left the held
    /// state, a WRONG_DELIVERY dispute, and the verifier exit check.
    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op == HOOK_R8_FEE) {
            _fee(uint32(arg >> 8), uint8(arg));
        } else if (op == HOOK_R8_MAT) {
            _r8Materialize(uint32(arg >> 24), uint24(arg));
        } else if (op == HOOK_R8_SEAL) {
            if (_r8Materialize(uint32(arg >> 24), uint24(arg)) == uint8(EpochState.ANCHORED)) revert InvalidTransition();
        } else if (op == HOOK_R8_SEAL_FAIL) {
            if (_r8Materialize(uint32(arg >> 24), uint24(arg)) != uint8(EpochState.EPOCH_FAILED)) revert InvalidTransition();
        } else if (op == HOOK_R8_LEFT) {
            _r8Left(bytes32(arg));
        } else if (op == HOOK_R8_WRONG) {
            _r8Wrong(bytes32(arg));
        } else if (op == HOOK_R8_EXIT) {
            if (_r8ExitHeld(verifiers[uint32(arg)])) revert ExitNotReady();
        } else if (op == HOOK_R8_SUSPEND) {
            // The suspension ends the episode; its held count starts again
            // from zero (rule D2-42 (a), (g)).
            Rule8Store.Layout storage r8 = Rule8Store.layout();
            r8.held[uint32(arg)] = 0;
            r8.episodeFloor[uint32(arg)] = uint64(block.number);
        } else if (op == HOOK_R8_FEE_ONCE) {
            // A profile-level call is paid once per profile and epoch (or
            // anchor deadline).
            bytes32 key = keccak256(abi.encode(arg));
            Rule8Store.Layout storage r8 = Rule8Store.layout();
            if (!r8.feeOnce[key]) {
                r8.feeOnce[key] = true;
                _fee(uint32(arg >> 64), uint8(arg >> 128));
            }
        } else {
            _unknownHook();
        }
    }

    function hookOps() external pure returns (uint256) {
        return (1 << HOOK_R8_FEE) | (1 << HOOK_R8_MAT) | (1 << HOOK_R8_SEAL) | (1 << HOOK_R8_SEAL_FAIL)
            | (1 << HOOK_R8_LEFT) | (1 << HOOK_R8_WRONG) | (1 << HOOK_R8_EXIT) | (1 << HOOK_R8_SUSPEND)
            | (1 << HOOK_R8_FEE_ONCE);
    }

    /// A purchase of a rule 8 profile left the held state, paid or marked
    /// for refund: the held count of its seller's episode drops by one
    /// (rule D2-42 (a), (g)). A purchase of an epoch the cursor already
    /// passed was counted out by the pass, unless it was left out of the
    /// batch for a separate release. A purchase of an earlier episode is not
    /// counted.
    function _r8Left(bytes32 nonce) private {
        PurchaseView storage purchase = purchases[nonce];
        // The hook runs before the new state is written: only a purchase
        // still held (DEFERRED, HELD or RELEASABLE) leaves the count.
        uint8 old = purchase.financialState;
        if (old != uint8(FinancialState.DEFERRED) && old != uint8(FinancialState.HELD)
            && old != uint8(FinancialState.RELEASABLE)) return;
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        uint32 sellerId = purchase.sellerId;
        if (purchase.settledBlock <= r8.episodeFloor[sellerId]) return;
        Rule8Store.SellerEpoch storage se = r8.sellerEpochs[sellerId][purchase.epoch];
        if (!se.passed) {
            se.left++;
        } else if (r8.itemFlag[nonce] == 0) {
            return;
        }
        if (r8.held[sellerId] != 0) r8.held[sellerId]--;
    }

    /// A WRONG_DELIVERY dispute holds its profile epoch open until its end is
    /// noted (rule D2-35 (d) 1 (ii)); the seller epoch takes its value from
    /// the profile seal.
    function _r8Wrong(bytes32 nonce) private {
        PurchaseView storage purchase = purchases[nonce];
        _r8Materialize(purchase.sellerId, purchase.epoch);
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (!r8.otherCounted[nonce]) {
            r8.otherCounted[nonce] = true;
            r8.openOtherCases[purchase.profileId][purchase.epoch]++;
        }
    }

    /// Rule 8 (rule D2-35 (d) 2): an exit requested in block r is final only
    /// once every profile epoch e with A_e < r of every rule 8 profile of the
    /// verifier's classes is closed, that is when the lowest open epoch of
    /// each such profile has A_e >= r. A request in block A_e does not hold
    /// epoch e (the checkpoint is the state at the end of its block).
    function _r8ExitHeld(VerifierView storage verifier) private view returns (bool) {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        uint256 n = r8.profileList.length;
        uint64 r = r8.exitRequested[verifier.verifierId];
        // A removal, or a request before the first rule 8 profile, counts
        // from the verifier's exit-eligible block.
        if (r == 0) r = verifier.exitEligibleBlock;
        for (uint256 i; i < n; i++) {
            uint32 p = r8.profileList[i];
            ServiceProfileInput storage profile = profiles[p].parameters;
            if ((verifier.classBitmap >> profile.classId) & 1 == 0) continue;
            if (_anchorDeadline(profile, r8.closedBelow[p]) < r) return true;
        }
        return false;
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](18);
        s[0] = this.setRule8Terms.selector;
        s[1] = this.rule8TermsHash.selector;
        s[2] = this.sealProfile.selector;
        s[3] = this.timeoutSealProfile.selector;
        s[4] = this.closeProfileEpochs.selector;
        s[5] = this.getRule8Terms.selector;
        s[6] = this.getProfileEpoch.selector;
        s[7] = this.getClosedBelow.selector;
        s[8] = this.anchorSigned.selector;
        s[9] = this.proveAnchorEquivocation.selector;
        s[10] = this.anchorDigest.selector;
        s[11] = this.fundPool.selector;
        s[12] = this.payOwedFees.selector;
        s[13] = this.getFeePool.selector;
        s[14] = this.rule8MinWindow.selector;
        s[15] = this.noteCaseEnded.selector;
        s[16] = this.getOpenOtherCases.selector;
        s[17] = this.r8Paid.selector;
    }
}
