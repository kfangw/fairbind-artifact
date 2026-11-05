// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { ExchangeShared } from "./ExchangeShared.sol";

/// Extension module 5 (ADR 0037): the terms of receipt-signature and proof
/// profiles with their admission checks, the posting of receipt signatures,
/// the match with the anchor, the refund of unbound purchases, the key
/// disclosure of a receipt-signature vote profile's non-delivery dispute, and
/// the seller's share of the deposit of a delivered non-delivery dispute.
contract FairBindExchange is ExchangeShared {
    uint8 public constant MODULE_KIND = 15;

    bytes32 internal constant EXCHANGE_TERMS_DOMAIN = keccak256("fairbind/exchange-terms/v1");
    bytes32 internal constant SOURCE_SET_DOMAIN = keccak256("fairbind/source-set/v1");
    bytes32 internal constant POLICY_DOMAIN = keccak256("fairbind/tolerance-policy/v1");
    /// Call data one transaction may carry, less an envelope margin.
    uint256 internal constant TX_DATA_CAP = 120_000;

    event ExchangeTermsSet(uint32 indexed profileId, uint8 mode, bytes32 termsHash);
    event ExchangeTermsRequired();
    event ReceiptSignaturePosted(bytes32 indexed nonce, bytes32 bundleHash);
    event ReceiptSignatureSkipped(bytes32 indexed nonce, uint8 reason);
    event AnchorMatched(bytes32 indexed nonce);
    event UnboundRefund(bytes32 indexed nonce);
    event KeyDisclosed(bytes32 indexed nonce, bytes32 ek, uint256 cost);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        ExchangeShared(token, gov, guard, treasury, rewardPool)
    { }

    // ------------------------------------------------------------- terms

    /// Fixes the terms of a profile that has never been active, once. A vote
    /// profile takes receipt signatures unless receiptSigOff is set; with it
    /// set the terms only turn on measured costs for the delivered share of
    /// the profile's non-delivery dispute. A profile whose terms are never
    /// set keeps the rules before ADR 0037. The admission checks of rule D2-13:
    /// (1) c_key = keyGas * gasPriceCap + keyBytes * l1PriceCap <=
    /// maxPublicationCost, the largest PASS proof fits one transaction and
    /// its gas the profile's block share; (2) T_bundle + T_key + the dispute
    /// slack fit before the last block a dispute opens; (3) T_bundle + the
    /// posting slack + d_conf <= T_anchor; (4) c_pub = pubGas * gasPriceCap +
    /// pubBytes * l1PriceCap <= maxPublicationCost (c_pub = c_key under
    /// receipt signatures); and delta_ref >= delta_fresh + max_skew + the
    /// settlement delay; (6) T_keep = retentionBlocks >= F_max = bindWindow
    /// > 0 for every mode. Check (7) depends on the randomness source and
    /// runs at activation. maxPublicationCost <= disputeDeposit holds by the
    /// profile check. termsHash commits to every input.
    function setExchangeTerms(uint32 profileId, ExchangeStore.Input calldata x) external onlyDelegateCall onlyGovernance {
        ServiceProfileView storage profile = profiles[profileId];
        if (profile.profileId == 0) revert UnknownProfile();
        ExchangeStore.Terms storage t = _terms(profileId);
        if (profile.active || profileActivated[profileId] || t.termsHash != 0) revert InvalidTransition();
        ExchangeStore.Input memory m = x;
        m.termsHash = 0;
        bytes32 h = keccak256(abi.encode(EXCHANGE_TERMS_DOMAIN, profileId, m));
        if (
            h != x.termsHash || x.mode > ExchangeStore.INPUT_PROOF || x.priceCap == 0
                || (x.mode == ExchangeStore.INPUT_PROOF && x.receiptSigOff)
        ) revert InvalidProfile();
        uint8 mode = x.mode == ExchangeStore.INPUT_PROOF ? ExchangeStore.MODE_PROOF
            : x.receiptSigOff ? ExchangeStore.MODE_NONE : ExchangeStore.MODE_VOTE_SIG;
        _admit(profile.parameters, x, profileId, mode);
        if (!_keepCoversWindow(profile.parameters, x)) revert InvalidProfile();
        t.mode = mode;
        t.costOn = true;
        t.priceCap = x.priceCap;
        t.gFixTx = x.gFixTx;
        t.gFixCall = x.gFixCall;
        t.bEnv = x.bEnv;
        t.proofBlocks = x.proofBlocks;
        t.keyCap = x.keyCap;
        t.bundleBlocks = x.bundleBlocks;
        t.keyBlocks = x.keyBlocks;
        t.refWindow = x.refWindow;
        t.maxSkew = x.maxSkew;
        t.g1271 = x.g1271;
        t.verifier = x.verifier;
        t.padLength = x.padLength;
        t.sigLimit = x.sigLimit;
        t.tolerancePpm = x.tolerancePpm;
        t.feedId = x.feedId;
        t.tag = x.tag;
        t.toleranceAbs = x.toleranceAbs;
        if (mode == ExchangeStore.MODE_PROOF) {
            t.sourceSetHash = keccak256(abi.encode(SOURCE_SET_DOMAIN, x.verifier, x.feedId));
            t.policyHash = keccak256(abi.encode(POLICY_DOMAIN, x.tolerancePpm, x.toleranceAbs, x.maxSkew));
        }
        t.bindWindow = x.bindWindow;
        t.bindSlack = x.bindSlack;
        t.termsHash = h;
        emit ExchangeTermsSet(profileId, mode, h);
    }

    /// Admission check (6) of rule D2-13 (c): the exits wait T_keep =
    /// retentionBlocks raw blocks, at least the binding proof window F_max,
    /// which may not be empty. A mutation build of the tests overrides it.
    function _keepCoversWindow(ServiceProfileInput storage p, ExchangeStore.Input calldata x)
        internal
        view
        virtual
        returns (bool)
    {
        return x.bindWindow != 0 && p.retentionBlocks >= x.bindWindow;
    }

    /// Deployment setting of the evaluation setting (rule 8.2 row 23): from
    /// this call on, a profile activates only with exchange terms, so that
    /// no vote profile runs without them. Governance, once, one way.
    function requireExchangeTerms() external onlyDelegateCall onlyGovernance {
        ExchangeStore.layout().termsRequired = true;
        emit ExchangeTermsRequired();
    }

    /// The admission checks of setExchangeTerms. A mutation build of the
    /// tests overrides it.
    function _admit(ServiceProfileInput storage p, ExchangeStore.Input calldata x, uint32 profileId, uint8 mode)
        internal
        view
        virtual
    {
        uint256 cap = p.maxPublicationCost;
        if (mode == ExchangeStore.MODE_NONE) {
            // (4) for a vote profile without receipt signatures.
            if (uint256(x.pubGas) * x.gasPriceCap + uint256(x.pubBytes) * x.l1PriceCap > cap) revert InvalidProfile();
            return;
        }
        BatchStore.Terms storage b = BatchStore.layout().terms[profileId];
        // Receipt signatures exclude the side-gain grade; proofs exclude
        // verifier assignment (rules D2-33 (h), D2-28 (c)).
        if (b.sideGainPpm != 0 || (mode == ExchangeStore.MODE_PROOF && b.batched)) revert InvalidProfile();
        // (1) and, under receipt signatures, (4) with c_pub = c_key.
        if (
            x.keyCap != uint256(x.keyGas) * x.gasPriceCap + uint256(x.keyBytes) * x.l1PriceCap || x.keyCap > cap
                || x.keyGas > x.blockGasShare || x.padLength == 0 || x.tag == 0 || x.g1271 == 0
        ) revert InvalidProfile();
        DeadlineConfig storage d = deadlineConfigs[p.deadlineConfigId];
        // (2) and (3).
        if (
            uint256(x.bundleBlocks) + x.keyBlocks + x.disputeSlack >= uint256(d.responseBlocks) + d.claimBlocks
                || uint256(x.bundleBlocks) + x.postSlack + x.confirmBlocks > d.anchorBlocks
        ) revert InvalidProfile();
        if (mode != ExchangeStore.MODE_PROOF) return;
        // The largest PASS proof: selector, nonce, flags, offset, the six
        // heads of the proof, and ct, the update message and two signatures
        // with their length words.
        uint256 sig = x.sigLimit > 65 ? x.sigLimit : 65;
        uint256 size = 4 + 32 * 9 + 4 * 32 + _ceil32(uint256(x.padLength) + 32) + _ceil32(x.maxUpdateBytes) + 2 * _ceil32(sig);
        if (
            size > TX_DATA_CAP || x.proofBlocks == 0 || x.verifier.code.length == 0 || x.feedId == 0
                || x.maxUpdateBytes == 0
                || uint256(x.refWindow) < uint256(x.freshWindow) + x.maxSkew + x.settleSlack
        ) revert InvalidProfile();
    }

    function _ceil32(uint256 n) private pure returns (uint256) {
        return (n + 31) & ~uint256(31);
    }

    // ------------------------------------------------------------ posting

    /// The seller posts one receipt signature with its posting signature over
    /// the bundle (rule D2-33 (b)).
    function postReceipt(ExchangeStore.Post calldata post, bytes calldata sellerSig) external onlyDelegateCall nonReentrant {
        ExchangeStore.mark();
        bytes32 digest = _typed(
            purchases[post.nonce].profileId,
            keccak256(abi.encode(POST_TYPEHASH, post.nonce, post.ctHash, post.ekHash, post.rHash, post.leaf))
        );
        (uint32 sellerId, ExchangeStore.Terms storage t) = _postSeller(post.nonce, digest, sellerSig);
        _postItem(sellerId, t, post);
    }

    /// The seller posts the receipt signatures of several of its purchases in
    /// one transaction with one posting signature over the list (rule D2-33
    /// (g) (b) 2): keccak256 of the concatenated (nonce, H(ct), h_ek, h_r,
    /// leaf) and their count, under a type of its own. A nonce whose purchase
    /// does not exist, whose slot is filled, whose anchor deadline passed or
    /// whose buyer signature does not hold is skipped; a purchase of another
    /// seller reverts the whole call.
    function postReceipts(ExchangeStore.Post[] calldata posts, bytes calldata sellerSig) external onlyDelegateCall nonReentrant {
        ExchangeStore.mark();
        uint256 n = posts.length;
        bytes memory list = new bytes(160 * n);
        bytes32 first;
        for (uint256 i; i < n; i++) {
            ExchangeStore.Post calldata q = posts[i];
            if (first == 0 && purchases[q.nonce].settledBlock != 0) first = q.nonce;
            assembly ("memory-safe") {
                calldatacopy(add(add(list, 0x20), mul(i, 160)), q, 160)
            }
        }
        if (first == 0) revert InvalidTransition();
        bytes32 digest = _typed(purchases[first].profileId, keccak256(abi.encode(POST_LIST_TYPEHASH, keccak256(list), n)));
        (uint32 sellerId, ExchangeStore.Terms storage t) = _postSeller(first, digest, sellerSig);
        for (uint256 i; i < n; i++) _postItem(sellerId, t, posts[i]);
    }

    /// The seller of the posting and its terms, after the posting signature
    /// checked against the seller's registered signing key.
    function _postSeller(bytes32 nonce, bytes32 digest, bytes calldata sellerSig)
        private
        view
        returns (uint32 sellerId, ExchangeStore.Terms storage t)
    {
        PurchaseView storage p = purchases[nonce];
        sellerId = p.sellerId;
        if (sellerId == 0) revert InvalidTransition();
        t = _terms(p.profileId);
        if (t.mode == ExchangeStore.MODE_NONE) revert InvalidTransition();
        if (!_postingSignatureOk(sellerId, digest, sellerSig, t)) revert InvalidSignature();
    }

    /// Whether the posting signature is that of the seller's registered
    /// signing key (ecrecover first, then ERC-1271 within g_1271 and L_sig).
    /// A mutation build of the tests overrides it.
    function _postingSignatureOk(uint32 sellerId, bytes32 digest, bytes calldata sig, ExchangeStore.Terms storage t)
        internal
        view
        virtual
        returns (bool ok)
    {
        (ok,) = _signedBy(sellers[sellerId].viewData.signingKey, digest, sig, t.g1271, t.sigLimit);
    }

    function _postItem(uint32 sellerId, ExchangeStore.Terms storage t, ExchangeStore.Post calldata q) private {
        PurchaseView storage p = purchases[q.nonce];
        uint8 reason = _postBlocked(sellerId, p, q.nonce);
        if (reason == 0) {
            bytes32 digest = _receiptSignatureDigest(
                p.profileId, sellers[sellerId].viewData.signingKey, q.nonce, q.ctHash, q.ekHash, q.rHash, q.leaf
            );
            (bool ok,) = _signedBy(p.buyer, digest, q.buyerSig, t.g1271, 0);
            if (!ok) reason = 4;
        }
        _record(q.nonce, reason, _bundleHash(q.ctHash, q.ekHash, q.rHash, q.leaf));
    }

    /// Why a nonce is skipped: 1 no purchase, 2 slot filled, 3 past the anchor
    /// deadline; a purchase of another seller reverts. Zero: none.
    function _postBlocked(uint32 sellerId, PurchaseView storage p, bytes32 nonce) private view returns (uint8) {
        if (p.settledBlock == 0) return 1;
        if (p.sellerId != sellerId) revert BondMismatch();
        if (!_slotFree(nonce)) return 2;
        if (block.number > _anchorDeadline(profiles[p.profileId].parameters, p.epoch)) return 3;
        return 0;
    }

    /// Whether the nonce has no posted signature. A mutation build of the
    /// tests overrides it.
    function _slotFree(bytes32 nonce) internal view virtual returns (bool) {
        return ExchangeStore.layout().bundles[nonce] == 0;
    }

    function _record(bytes32 nonce, uint8 reason, bytes32 h) private {
        if (reason != 0) {
            emit ReceiptSignatureSkipped(nonce, reason);
            return;
        }
        ExchangeStore.layout().bundles[nonce] = h;
        emit ReceiptSignaturePosted(nonce, h);
    }

    // ----------------------------------------------------- anchor matches

    /// Matches posted receipt signatures with their anchored leaves by the
    /// anchor deadline A_e (rule D2-33 (b), (g) 1): for each, the preimage of
    /// h_n with the leaf, and the leaf's merkle-v1 path in the unit that
    /// holds the nonce. Anyone may call it. A purchase matched by A_e is a
    /// sale; any other is refunded (refundUnbound).
    function matchAnchor(ExchangeStore.Match[] calldata matches) external onlyDelegateCall {
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        for (uint256 i; i < matches.length; i++) {
            ExchangeStore.Match calldata m = matches[i];
            PurchaseView storage p = purchases[m.nonce];
            if (p.settledBlock == 0) revert InvalidTransition();
            if (!_matchInTime(p)) revert DeadlinePassed();
            bytes32 stored = x.bundles[m.nonce];
            if (stored == 0 || uint256(stored) & 1 == 1 || _bundleHash(m.ctHash, m.ekHash, m.rHash, m.leaf) != stored) {
                revert InvalidProof();
            }
            if (!_inUnit(p, m)) revert InvalidProof();
            x.bundles[m.nonce] = bytes32(uint256(stored) | 1);
            emit AnchorMatched(m.nonce);
        }
    }

    /// Whether a match of the purchase is still in time: by its epoch's
    /// anchor deadline. A mutation build of the tests overrides it.
    function _matchInTime(PurchaseView storage p) internal view virtual returns (bool) {
        return block.number <= _anchorDeadline(profiles[p.profileId].parameters, p.epoch);
    }

    /// The leaf is the entry of the nonce in the unit `m.unit` of its epoch:
    /// the anchor root for an epoch anchored as one unit, the unit's root
    /// (with the unit's length from the epoch count) for a split anchor.
    function _inUnit(PurchaseView storage p, ExchangeStore.Match calldata m) private view returns (bool) {
        AnchorView storage record = anchors[p.sellerId][p.epoch];
        SamplingStore.UnitAnchor storage u = SamplingStore.layout().units[p.sellerId][p.epoch];
        uint256 n = u.roots.length;
        if (n == 0) {
            if (m.unit != 0 || record.state == uint8(EpochState.NONE) || record.root == bytes32(0)) return false;
            return FairBindMerkle.verify(record.root, m.nonce, m.leaf, m.position, record.count, m.siblings);
        }
        if (m.unit >= n) return false;
        uint256 size = uint256(1) << u.unitLog2;
        uint256 left = uint256(epochPurchaseCount[p.sellerId][p.epoch]) - uint256(m.unit) * size;
        return FairBindMerkle.verify(u.roots[m.unit], m.nonce, m.leaf, m.position, uint32(left < size ? left : size), m.siblings);
    }

    /// Refunds a purchase of a receipt-signature profile that is not bound by
    /// its anchor deadline: it is no sale (rule D2-33 (c)). Once only; a
    /// purchase a dispute refunded is not refunded again. No failure counts.
    function refundUnbound(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        if (p.settledBlock == 0 || _exchangeMode(p.profileId) == ExchangeStore.MODE_NONE || _bound(nonce)) {
            revert InvalidTransition();
        }
        if (block.number <= _anchorDeadline(profiles[p.profileId].parameters, p.epoch)) revert DeadlineNotReached();
        uint8 fs = p.financialState;
        if (
            (fs != uint8(FinancialState.DEFERRED) && fs != uint8(FinancialState.RELEASABLE) && fs != uint8(FinancialState.HELD))
                || _forfeitedEntry(p)
        ) revert AlreadyFinalized();
        _setFinancialState(nonce, FinancialState.REFUNDABLE);
        refundSources[nonce] = uint8(RefundSource.UNBOUND);
        // Later case ends leave the refund as it is.
        ExchangeStore.layout().records[nonce].early = true;
        emit UnboundRefund(nonce);
    }

    // --------------------------------------- key disclosure (vote profile)

    /// The seller ends the buyer's non-delivery dispute of a receipt-signature
    /// vote profile by disclosing the key (rule D2-33 (f)): within the serve
    /// deadline of the dispute's current step, ek and ct that, with the
    /// posted leaf, hash to the purchase's h_n and decrypt to a padded
    /// response. The dispute (or the buyer recovery when `recovery`) ends as
    /// delivered; the call's measured cost adds to the seller's share.
    function discloseKey(bytes32 nonce, bool recovery, bytes32 ek, bytes calldata ct, bytes32 leaf)
        external
        onlyDelegateCall
        nonReentrant
    {
        uint256 g0 = gasleft();
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Terms storage t = _terms(p.profileId);
        if (t.mode != ExchangeStore.MODE_VOTE_SIG) revert InvalidTransition();
        if (msg.sender != sellers[p.sellerId].viewData.owner) revert Unauthorized();
        CaseView storage c = recovery ? buyerRecoveries[nonce] : cases[nonce];
        if (!recovery && (c.requesterRole != uint8(RequesterRole.BUYER) || c.trigger != uint8(CaseTrigger.NON_DELIVERY))) {
            revert InvalidTransition();
        }
        uint8 st = c.state;
        uint64 due = st == uint8(CaseState.SERVE_WAIT) ? c.serveDue
            : st == uint8(CaseState.SERVE_CONFIRM) ? c.challengeUntil
            : st == uint8(CaseState.PUBLISHING) ? c.publishDue : 0;
        if (due == 0) revert InvalidTransition();
        if (block.number > due) revert DeadlinePassed();
        if (ct.length != uint256(t.padLength) + 32) revert InvalidProof();
        bytes memory pt = _decrypt(ek, nonce, ct);
        bytes32 h = _bundleHash(keccak256(ct), keccak256(abi.encode(ek)), _responseCommit(t.tag, pt), leaf);
        if (uint256(ExchangeStore.layout().bundles[nonce]) & ~uint256(1) != uint256(h) || h == 0) revert InvalidProof();
        _unpad(pt);
        if (recovery) _completeBuyerDelivery(nonce);
        else _completeDelivery(nonce);
        uint256 before = ExchangeStore.layout().ladders[nonce].cost + ExchangeStore.layout().ladders[nonce].recoveryCost;
        _ladderCost(nonce, recovery, g0, abi.encodeWithSelector(msg.sig, nonce, recovery, ek, ct, leaf));
        emit KeyDisclosed(
            nonce, ek, ExchangeStore.layout().ladders[nonce].cost + ExchangeStore.layout().ladders[nonce].recoveryCost - before
        );
    }

    // ---------------------------------------------------------- deposits

    /// The deposits of an entry whose non-delivery dispute (or buyer
    /// recovery) ended as delivered under measured costs, at the entry's end
    /// without a refund (rule D2-24 (d') 1 2): the seller takes the sum of
    /// the measured costs of its calls, at most maxPublicationCost; the rest
    /// goes back to the buyer under receipt signatures and is locked
    /// otherwise. An inconclusive case returns the dispute deposit.
    function _ladderPay(bytes32 nonce) private {
        PurchaseView storage p = purchases[nonce];
        uint256 deposit = disputeDeposits[nonce];
        uint256 recovery = buyerRecoveryDeposits[nonce];
        disputeDeposits[nonce] = 0;
        buyerRecoveryDeposits[nonce] = 0;
        CaseView storage c = cases[nonce];
        uint256 toBuyer;
        if (
            deposit != 0 && (c.state == uint8(CaseState.INCONCLUSIVE)
                || (c.state == uint8(CaseState.FINAL) && c.finalVerdict == uint8(Verdict.INCONCLUSIVE)))
        ) {
            toBuyer = deposit;
            deposit = 0;
        }
        ExchangeStore.Ladder storage lad = ExchangeStore.layout().ladders[nonce];
        uint256 cap = profiles[p.profileId].parameters.maxPublicationCost;
        uint256 rest;
        if (lad.delivered && deposit != 0) {
            uint256 share = _ladderShare(lad.cost, cap, deposit);
            rest += deposit - share;
            deposit = share;
        }
        if (lad.recoveryDelivered && recovery != 0) {
            uint256 share = _ladderShare(lad.recoveryCost, cap, recovery);
            rest += recovery - share;
            recovery = share;
        }
        if (rest != 0) {
            if (_exchangeMode(p.profileId) == ExchangeStore.MODE_VOTE_SIG) {
                toBuyer += rest;
            } else {
                lockedForfeit += rest;
                emit DepositResolved(nonce, 5, address(this), rest);
            }
        }
        if (toBuyer != 0) _transfer(p.buyer, toBuyer);
        if (deposit + recovery != 0) _transfer(sellers[p.sellerId].viewData.owner, deposit + recovery);
        emit DepositResolved(nonce, 6, sellers[p.sellerId].viewData.owner, deposit + recovery);
    }

    /// The seller's share min(cap, measured), at most the deposit. A mutation
    /// build of the tests overrides it.
    function _ladderShare(uint256 measured, uint256 cap, uint256 deposit) internal pure virtual returns (uint256 share) {
        share = measured < cap ? measured : cap;
        if (share > deposit) share = deposit;
    }

    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op != HOOK_LADDER_PAY) _unknownHook();
        _ladderPay(bytes32(arg));
    }

    function hookOps() external pure returns (uint256) {
        return 1 << HOOK_LADDER_PAY;
    }

    // ------------------------------------------------------------- views

    function getExchangeTerms(uint32 profileId) external view onlyDelegateCall returns (ExchangeStore.Terms memory) {
        return _terms(profileId);
    }

    function getExchangeRecord(bytes32 nonce)
        external
        view
        onlyDelegateCall
        returns (bytes32 bundle, ExchangeStore.Record memory record, ExchangeStore.Ladder memory ladder)
    {
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        return (x.bundles[nonce], x.records[nonce], x.ladders[nonce]);
    }

    function receiptSignatureDigest(bytes32 nonce, bytes32 ctHash, bytes32 ekHash, bytes32 rHash, bytes32 leaf)
        external
        view
        onlyDelegateCall
        returns (bytes32)
    {
        PurchaseView storage p = purchases[nonce];
        return _receiptSignatureDigest(p.profileId, sellers[p.sellerId].viewData.signingKey, nonce, ctHash, ekHash, rHash, leaf);
    }

    function postDigest(ExchangeStore.Post calldata post) external view onlyDelegateCall returns (bytes32) {
        return _typed(
            purchases[post.nonce].profileId,
            keccak256(abi.encode(POST_TYPEHASH, post.nonce, post.ctHash, post.ekHash, post.rHash, post.leaf))
        );
    }

    function postListDigest(uint32 profileId, bytes32 listHash, uint256 count) external view onlyDelegateCall returns (bytes32) {
        return _typed(profileId, keccak256(abi.encode(POST_LIST_TYPEHASH, listHash, count)));
    }

    /// The predicate commitment a proof profile's receipt of `nonce` carries.
    function proofCommitment(bytes32 nonce) external view onlyDelegateCall returns (bytes32) {
        PurchaseView storage p = purchases[nonce];
        return _commitment(_terms(p.profileId), ExchangeStore.layout().records[nonce].refTime);
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](14);
        s[0] = this.setExchangeTerms.selector;
        s[1] = this.postReceipt.selector;
        s[2] = this.postReceipts.selector;
        s[3] = this.matchAnchor.selector;
        s[4] = this.refundUnbound.selector;
        s[5] = this.discloseKey.selector;
        s[6] = this.getExchangeTerms.selector;
        s[7] = this.getExchangeRecord.selector;
        s[8] = this.receiptSignatureDigest.selector;
        s[9] = this.postDigest.selector;
        s[10] = this.postListDigest.selector;
        s[11] = this.proofCommitment.selector;
        s[12] = this.exchangeTermsHash.selector;
        s[13] = this.requireExchangeTerms.selector;
    }

    /// termsHash of an input, as setExchangeTerms checks it.
    function exchangeTermsHash(uint32 profileId, ExchangeStore.Input calldata x) external pure returns (bytes32) {
        ExchangeStore.Input memory m = x;
        m.termsHash = 0;
        return keccak256(abi.encode(EXCHANGE_TERMS_DOMAIN, profileId, m));
    }
}
