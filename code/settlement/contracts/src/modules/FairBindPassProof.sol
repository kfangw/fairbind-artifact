// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { IUniquePriceUpdates } from "../oracle/IUniquePriceUpdates.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { ExchangeShared } from "./ExchangeShared.sol";

/// Extension module 6 (ADR 0037): the judgment of a proof profile. A sample
/// case or a buyer's dispute waits T_p for a PASS proof that the contract
/// checks itself: the key and ciphertext the buyer signed for, decrypted and
/// unpadded to the response, and the one signed update of the registered
/// feed that is the first published at or after the buyer's validAfter.
/// Without one, or once the update shows no input in the window, it fails.
/// A sample case's failure is a confirmed failure; a dispute's is the
/// purchase's refund alone. The same proof releases a frozen entry after the
/// receipt-binding window (the seller's proof, rule D2-32).
contract FairBindPassProof is ExchangeShared {
    uint8 public constant MODULE_KIND = 16;

    /// prove flag: an early FAIL.
    uint8 internal constant FLAG_FAIL = 2;

    event ProofCaseOpened(bytes32 indexed nonce, uint64 due);
    event ProofDisputeOpened(bytes32 indexed nonce, uint8 kind, uint64 due);
    event PassProven(bytes32 indexed nonce, bytes32 ek, int64 price, uint256 publishTime);
    event ProofFailed(bytes32 indexed nonce, bool absent);
    event ProofDisputeEnded(bytes32 indexed nonce, bool passed, uint256 sellerShare, uint256 cost);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        ExchangeShared(token, gov, guard, treasury, rewardPool)
    { }

    // ------------------------------------------------------------ opening

    /// Opens the sample case of a bound, sampled purchase of a proof profile.
    /// Anyone may call it. The case waits T_p for a PASS proof; a purchase
    /// that already has a confirmed PASS proof passes at once. A purchase a
    /// dispute refunded keeps its refund and still opens its case.
    function openProofSample(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Terms storage t = _terms(p.profileId);
        if (t.mode != ExchangeStore.MODE_PROOF || p.settledBlock == 0 || _forfeitedEntry(p)) revert InvalidTransition();
        if (!_bound(nonce)) revert NotBound();
        CaseView storage c = cases[nonce];
        uint8 fs = p.financialState;
        if (
            c.state != uint8(CaseState.NONE)
                || (fs != uint8(FinancialState.DEFERRED) && fs != uint8(FinancialState.HELD) && !_refundedEarly(nonce))
        ) revert InvalidTransition();
        (bool eligible, bool known) = _sampleStatus(p, nonce);
        if (!known || !eligible) revert NotSampled();
        if (fs == uint8(FinancialState.DEFERRED)) _setFinancialState(nonce, FinancialState.HELD);
        c.nonce = nonce;
        c.caseOpenedBlock = uint64(block.number);
        c.trigger = uint8(CaseTrigger.SAMPLE);
        c.stage = uint8(JudgmentStage.INITIAL);
        c.state = uint8(CaseState.PROOF_WAIT);
        c.judgeDue = uint64(block.number + t.proofBlocks);
        c.randomness = anchors[p.sellerId][p.epoch].randomness;
        // The open sample case blocks the seller's proofs of the account.
        BatchStore.Layout storage l = BatchStore.layout();
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        BatchStore.Entry storage en = l.entries[nonce];
        en.counted = true;
        en.bondId = bondId;
        l.proofAccounts[bondId].openSamples++;
        emit CaseOpened(nonce, uint8(CaseTrigger.SAMPLE), address(0), p.value);
        emit ProofCaseOpened(nonce, c.judgeDue);
        if (ExchangeStore.layout().records[nonce].proven) _samplePass(nonce);
    }

    /// The buyer's dispute of a purchase of a proof profile, by its claim
    /// deadline, with the dispute deposit d0: NON_DELIVERY (the key
    /// dispute: no key, or a key or plaintext that does not match) or
    /// WRONG_DELIVERY. It waits T_p for a PASS proof (rule D2-29 (g)); a
    /// purchase with a confirmed PASS proof passes at once.
    function openProofDispute(bytes32 nonce, uint8 kind) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        if (p.settledBlock == 0 || msg.sender != p.buyer) revert Unauthorized();
        ExchangeStore.Terms storage t = _terms(p.profileId);
        if (t.mode != ExchangeStore.MODE_PROOF) revert InvalidTransition();
        if (kind != uint8(CaseTrigger.NON_DELIVERY) && kind != uint8(CaseTrigger.WRONG_DELIVERY)) revert InvalidTransition();
        if (block.number > p.claimUntil) revert ClaimWindowClosed();
        uint8 fs = p.financialState;
        if (
            fs == uint8(FinancialState.REFUNDABLE) || fs == uint8(FinancialState.REFUNDED)
                || fs == uint8(FinancialState.RELEASED) || _forfeitedEntry(p)
        ) revert AlreadyFinalized();
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        if (r.disputeState != 0) revert InvalidTransition();
        uint256 d0 = profiles[p.profileId].parameters.disputeDeposit;
        _transferFrom(msg.sender, d0);
        r.disputeKind = kind;
        r.disputeState = ExchangeStore.DISPUTE_OPEN;
        r.disputeDue = uint64(block.number + t.proofBlocks);
        r.disputeDeposit = uint64(d0);
        if (fs == uint8(FinancialState.DEFERRED) || fs == uint8(FinancialState.RELEASABLE)) {
            _setFinancialState(nonce, FinancialState.HELD);
        }
        emit CaseOpened(nonce, kind, msg.sender, p.value);
        emit ProofDisputeOpened(nonce, kind, r.disputeDue);
        // The seller spent nothing on this dispute: its measured share is zero.
        if (r.proven) _disputePass(nonce, 0, 0);
    }

    // -------------------------------------------------------------- proof

    /// A PASS proof (rule D2-29 (b), D2-33 (d')). Anyone may carry it. The
    /// call data must be the canonical encoding of the arguments. Checks:
    /// keccak256 of ct, of ek, of tag || Dec_ek(ct) and the purchase's
    /// receipt leaf hash to the purchase's h_n; the plaintext unpads; the
    /// update is the first of the registered feed published at or after the
    /// buyer's validAfter and at most max_skew later; the response is within
    /// the profile's tolerance of its price. Any mismatch reverts. With
    /// FLAG_FAIL the proof shows the opposite on the canonical input and ends
    /// the open cases as FAIL before their deadline.
    function prove(bytes32 nonce, uint8 flags, ExchangeStore.PassProof calldata q) external onlyDelegateCall nonReentrant {
        uint256 g0 = gasleft();
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Terms storage t = _terms(p.profileId);
        if (t.mode != ExchangeStore.MODE_PROOF || p.settledBlock == 0) revert InvalidTransition();
        bytes memory xhat = abi.encodeWithSelector(msg.sig, nonce, flags, q);
        if (xhat.length != msg.data.length) revert NonCanonical();
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        bool sampleOpen = cases[nonce].state == uint8(CaseState.PROOF_WAIT) && block.number <= cases[nonce].judgeDue;
        bool disputeOpen = r.disputeState == ExchangeStore.DISPUTE_OPEN && block.number <= r.disputeDue;
        bool fail = flags & FLAG_FAIL != 0;
        // A purchase without an open case may take a PASS proof for the
        // seller's proof on its frozen entry (selfProve).
        if (flags & ~FLAG_FAIL != 0 || (fail ? !(sampleOpen || disputeOpen) : r.proven)) revert ProofNotAllowed();
        (uint256 excluded, bytes memory pt, uint256 len) = _checkBundle(nonce, t, r, q);
        (bool pass, int64 price, uint256 publishTime) = _evaluate(t, r.refTime, q.update, pt, len);
        if (fail) {
            if (pass) revert InvalidProof();
            emit ProofFailed(nonce, false);
            _failOpen(nonce, sampleOpen, disputeOpen);
            return;
        }
        if (!pass) revert ProofNotPass();
        r.proven = true;
        emit PassProven(nonce, q.ek, price, publishTime);
        if (sampleOpen) _samplePass(nonce);
        if (disputeOpen) {
            uint256 cost;
            if (r.disputeKind == uint8(CaseTrigger.NON_DELIVERY)) {
                // A seller signature checked through ERC-1271 is the seller's
                // own cost: its gas and bytes are left out (rule D2-33 (e') 2).
                if (excluded != 0) {
                    uint256 cut = (q.sellerSig.length + 31) & ~uint256(31);
                    assembly ("memory-safe") {
                        mstore(xhat, sub(mload(xhat), cut))
                    }
                }
                cost = _measuredCost(t, g0, excluded, xhat);
            }
            _disputePass(nonce, cost, cost);
        }
    }

    /// The purchase's h_n against the proof's bundle; posts the receipt
    /// signature first when the proof carries one (rule D2-33 (e')).
    /// Returns the gas of a seller signature checked through ERC-1271, the
    /// plaintext and the length of the response in it.
    function _checkBundle(
        bytes32 nonce,
        ExchangeStore.Terms storage t,
        ExchangeStore.Record storage r,
        ExchangeStore.PassProof calldata q
    ) private returns (uint256 excluded, bytes memory pt, uint256 len) {
        if (q.ct.length != uint256(t.padLength) + 32) revert InvalidProof();
        pt = _decrypt(q.ek, nonce, q.ct);
        bytes32 ctHash = keccak256(q.ct);
        bytes32 ekHash = keccak256(abi.encode(q.ek));
        bytes32 rHash = _responseCommit(t.tag, pt);
        bytes32 leaf = _proofLeaf(nonce, rHash, _commitment(t, r.refTime), q.issuedAt);
        bytes32 h = _bundleHash(ctHash, ekHash, rHash, leaf);
        if (q.buyerSig.length != 0) excluded = _postInProof(nonce, t, ctHash, ekHash, rHash, leaf, h, q);
        bytes32 stored = ExchangeStore.layout().bundles[nonce];
        if (stored == 0 || uint256(stored) & ~uint256(1) != uint256(h)) revert InvalidProof();
        len = _unpad(pt);
    }

    /// Posts the receipt signature a PASS proof carries, as postReceipt would.
    function _postInProof(
        bytes32 nonce,
        ExchangeStore.Terms storage t,
        bytes32 ctHash,
        bytes32 ekHash,
        bytes32 rHash,
        bytes32 leaf,
        bytes32 h,
        ExchangeStore.PassProof calldata q
    ) private returns (uint256 excluded) {
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        if (x.bundles[nonce] != 0) revert InvalidTransition();
        if (block.number > _anchorDeadline(profiles[p.profileId].parameters, p.epoch)) revert DeadlinePassed();
        address seller = sellers[p.sellerId].viewData.signingKey;
        (bool ok,) = _signedBy(
            p.buyer, _receiptSignatureDigest(p.profileId, seller, nonce, ctHash, ekHash, rHash, leaf), q.buyerSig, t.g1271, 0
        );
        if (!ok) revert InvalidSignature();
        bytes32 postDigest = _typed(p.profileId, keccak256(abi.encode(POST_TYPEHASH, nonce, ctHash, ekHash, rHash, leaf)));
        (ok, excluded) = _signedBy(seller, postDigest, q.sellerSig, t.g1271, t.sigLimit);
        if (!ok) revert InvalidSignature();
        x.bundles[nonce] = h;
    }

    /// The canonical input and the predicate (rule D2-29 (b) 3 to 7, D2-30
    /// (a)): the verifier returns the first update of the registered feed
    /// published at or after the reference time; it is the canonical input
    /// when published at most max_skew later. The response r, an unsigned
    /// decimal string, passes when |r - price| <= toleranceAbs +
    /// tolerancePpm * |price| / 1e6 at the feed's exponent. No input in the
    /// window, or a response that does not parse, is no PASS.
    function _evaluate(ExchangeStore.Terms storage t, uint64 refTime, bytes calldata update, bytes memory pt, uint256 len)
        private
        returns (bool pass, int64 price, uint256 publishTime)
    {
        IUniquePriceUpdates.Price memory pr = _canonicalInput(t, refTime, update);
        price = pr.price;
        publishTime = pr.publishTime;
        if (publishTime > uint256(refTime) + t.maxSkew || pr.expo > 0 || pr.expo < -18) return (false, price, publishTime);
        (bool ok, uint256 value) = _parseDecimal(pt, len, uint32(-pr.expo));
        if (!ok) return (false, price, publishTime);
        uint256 ref = price >= 0 ? uint256(int256(price)) : uint256(-int256(price));
        if (price < 0) return (false, price, publishTime);
        uint256 diff = value > ref ? value - ref : ref - value;
        pass = diff * PPM <= uint256(t.toleranceAbs) * PPM + uint256(t.tolerancePpm) * ref;
    }

    /// The first update of the registered feed at or after the reference
    /// time, from the profile's verifier. Its window bound is checked by the
    /// caller, so that the same call shows an absent input.
    function _canonicalInput(ExchangeStore.Terms storage t, uint64 refTime, bytes calldata update)
        internal
        virtual
        returns (IUniquePriceUpdates.Price memory)
    {
        bytes[] memory data = new bytes[](1);
        data[0] = update;
        bytes32[] memory ids = new bytes32[](1);
        ids[0] = t.feedId;
        IUniquePriceUpdates.PriceFeed[] memory feeds =
            IUniquePriceUpdates(t.verifier).parsePriceFeedUpdatesUnique(data, ids, refTime, type(uint64).max);
        if (feeds.length != 1 || feeds[0].id != t.feedId) revert InvalidProof();
        return feeds[0].price;
    }

    /// The response pt[32 .. 32 + len) as an unsigned decimal with at most
    /// `decimals` fraction digits, scaled by 10^decimals.
    function _parseDecimal(bytes memory pt, uint256 len, uint32 decimals) private pure returns (bool ok, uint256 v) {
        if (len == 0 || len > 40) return (false, 0);
        uint256 frac;
        bool dot;
        for (uint256 i = 32; i < 32 + len; i++) {
            uint8 ch = uint8(pt[i]);
            if (ch == 0x2e) {
                if (dot) return (false, 0);
                dot = true;
                continue;
            }
            if (ch < 48 || ch > 57) return (false, 0);
            v = v * 10 + (ch - 48);
            if (dot) frac++;
        }
        if (frac > decimals) return (false, 0);
        v *= 10 ** (decimals - frac);
        ok = true;
    }

    /// An absent input (rule D2-31 (b)(c)): the first update of the feed at
    /// or after the reference time was published more than max_skew later,
    /// so no PASS proof exists. Anyone may show it to end the open sample
    /// case and dispute of the purchase as FAIL before their deadline.
    function proveAbsence(bytes32 nonce, bytes calldata update) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Terms storage t = _terms(p.profileId);
        if (t.mode != ExchangeStore.MODE_PROOF || p.settledBlock == 0) revert InvalidTransition();
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        bool sampleOpen = cases[nonce].state == uint8(CaseState.PROOF_WAIT) && block.number <= cases[nonce].judgeDue;
        bool disputeOpen = r.disputeState == ExchangeStore.DISPUTE_OPEN && block.number <= r.disputeDue;
        if (!(sampleOpen || disputeOpen)) revert ProofNotAllowed();
        IUniquePriceUpdates.Price memory pr = _canonicalInput(t, r.refTime, update);
        if (pr.publishTime <= uint256(r.refTime) + t.maxSkew) revert InvalidProof();
        emit ProofFailed(nonce, true);
        _failOpen(nonce, sampleOpen, disputeOpen);
    }

    /// Ends, past its deadline without a PASS proof, the open sample case
    /// (a confirmed failure) or the dispute (the refund) of the purchase.
    function timeoutProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        bool sampleLate = cases[nonce].state == uint8(CaseState.PROOF_WAIT) && block.number > cases[nonce].judgeDue;
        bool disputeLate = r.disputeState == ExchangeStore.DISPUTE_OPEN && block.number > r.disputeDue;
        if (!(sampleLate || disputeLate)) revert DeadlineNotReached();
        _failOpen(nonce, sampleLate, disputeLate);
    }

    function _failOpen(bytes32 nonce, bool sample, bool dispute) private {
        if (sample) _sampleFail(nonce);
        if (dispute) _disputeFail(nonce);
    }

    // ---------------------------------------------------------- outcomes

    function _samplePass(bytes32 nonce) private {
        CaseView storage c = cases[nonce];
        c.state = uint8(CaseState.FINAL);
        c.initialVerdict = uint8(Verdict.PASS);
        c.finalVerdict = uint8(Verdict.PASS);
        c.judgeDue = 0;
        _sampleEnded(nonce);
        _releaseTrigger(nonce);
        _recordJudged(nonce, uint8(Verdict.PASS));
        _unhold(nonce);
        emit CaseFinalized(nonce, uint8(Verdict.PASS), purchases[nonce].financialState);
    }

    /// A sample case without a PASS proof: a confirmed failure of the seller
    /// tied to the purchase (rule D2-29 (f)), refunding the purchase unless a
    /// dispute refunded it already.
    function _sampleFail(bytes32 nonce) private {
        CaseView storage c = cases[nonce];
        PurchaseView storage p = purchases[nonce];
        c.state = uint8(CaseState.FINAL);
        c.initialVerdict = uint8(Verdict.FAIL);
        c.finalVerdict = uint8(Verdict.FAIL);
        c.judgeDue = 0;
        _sampleEnded(nonce);
        if (!_refundDue(nonce)) {
            _setFinancialState(nonce, FinancialState.REFUNDABLE);
            refundSources[nonce] = uint8(RefundSource.FINAL_FAIL);
        }
        // The failure voids the seller's proof on the purchase (rule D2-25 (e)).
        _hook(HOOK_PASS_FAILURE, uint256(nonce));
        _confirmFailure(p.sellerId, nonce, true, p.settledBlock);
        _recordJudged(nonce, uint8(Verdict.FAIL));
        emit CaseFinalized(nonce, uint8(Verdict.FAIL), p.financialState);
    }

    /// A dispute with a PASS proof. The key dispute pays the seller its
    /// measured cost, at most c_key, and the rest of the deposit back to the
    /// buyer; the other dispute pays the seller the whole deposit (rule
    /// D2-24 (d), D2-33 (e')).
    function _disputePass(bytes32 nonce, uint256 measured, uint256 cost) private {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        PurchaseView storage p = purchases[nonce];
        uint256 deposit = r.disputeDeposit;
        uint256 share = deposit;
        if (r.disputeKind == uint8(CaseTrigger.NON_DELIVERY)) share = _keyShare(measured, _terms(p.profileId).keyCap, deposit);
        r.disputeState = ExchangeStore.DISPUTE_PASSED;
        r.disputeDeposit = 0;
        if (share != 0) _transfer(sellers[p.sellerId].viewData.owner, share);
        if (deposit > share) _transfer(p.buyer, deposit - share);
        emit ProofDisputeEnded(nonce, true, share, cost);
        _unhold(nonce);
    }

    /// The seller's share of a key dispute: min(c_key, measured), at most the
    /// deposit. A mutation build of the tests overrides it.
    function _keyShare(uint256 measured, uint256 cap, uint256 deposit) internal pure virtual returns (uint256 share) {
        share = measured < cap ? measured : cap;
        if (share > deposit) share = deposit;
    }

    /// A dispute without a PASS proof: the deposit goes back and the purchase
    /// is refunded once, without a confirmed failure (rule D2-29 (g)). Its
    /// sample case, open or not yet open, stays.
    function _disputeFail(bytes32 nonce) private {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        PurchaseView storage p = purchases[nonce];
        uint256 deposit = r.disputeDeposit;
        r.disputeState = ExchangeStore.DISPUTE_FAILED;
        r.disputeDeposit = 0;
        if (deposit != 0) _transfer(p.buyer, deposit);
        if (!_refundDue(nonce) && p.financialState != uint8(FinancialState.RELEASED) && !_forfeitedEntry(p)) {
            _setFinancialState(nonce, FinancialState.REFUNDABLE);
            refundSources[nonce] = uint8(RefundSource.DISPUTE_REFUND);
            r.early = true;
        }
        emit ProofDisputeEnded(nonce, false, 0, 0);
    }

    /// A held entry that nothing holds any more returns to its schedule.
    function _unhold(bytes32 nonce) private {
        PurchaseView storage p = purchases[nonce];
        if (p.financialState != uint8(FinancialState.HELD)) return;
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        if (
            cases[nonce].state == uint8(CaseState.PROOF_WAIT) || r.disputeState == ExchangeStore.DISPUTE_OPEN
                || r.selfState == ExchangeStore.SELF_RESERVED || r.selfState == ExchangeStore.SELF_CONFIRMED
        ) return;
        _setFinancialState(nonce, FinancialState.RELEASABLE);
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](5);
        s[0] = this.openProofSample.selector;
        s[1] = this.openProofDispute.selector;
        s[2] = this.prove.selector;
        s[3] = this.proveAbsence.selector;
        s[4] = this.timeoutProof.selector;
    }

    function hookOps() external pure returns (uint256) {
        return 0;
    }
}
