// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { BatchStore } from "./BatchStore.sol";

/// Bond accounts, seller registrations under them, and the frozen-pool
/// lifecycle: freeze, release on overturn, receipt claims and forfeiture.
contract FairBindBond is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 9;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    function registerBond(uint32 profileId, uint128 amount)
        external
        onlyDelegateCall
        nonReentrant
        returns (uint32 bondId)
    {
        // A profile with tiers needs the account's value cap and tier (ADR 0024).
        if (profileTerms[profileId].tiers.length != 0) revert InvalidConfiguration();
        bondId = _openBond(profileId, amount, 0, 0);
    }

    /// Registers a bond account under a profile with tiers, with the value cap
    /// and the sales tier its seller chose (ADR 0024).
    function registerBondWithTerms(uint32 profileId, uint128 amount, uint96 sampleScaleValue, uint8 tier)
        external
        onlyDelegateCall
        nonReentrant
        returns (uint32 bondId)
    {
        _checkTerms(profileId, sampleScaleValue, tier);
        bondId = _openBond(profileId, amount, sampleScaleValue, tier);
    }

    function _openBond(uint32 profileId, uint128 amount, uint96 sampleScaleValue, uint8 tier) private returns (uint32 bondId) {
        if (newSettlementsPaused) revert Paused();
        ServiceProfileView storage profile = profiles[profileId];
        if (!profile.active) revert InactiveProfile();
        bondId = nextBondId++;
        BondView storage b = bonds[bondId];
        b.bondId = bondId;
        b.profileId = profileId;
        b.owner = msg.sender;
        b.balance = amount;
        b.status = uint8(BondStatus.ACTIVE);
        // Every entry of the account settles from this block on (ADR 0030).
        deferredFloor[bondId] = uint64(block.number);
        if (sampleScaleValue != 0) {
            bondTerms[bondId].sampleScaleValue = sampleScaleValue;
            bondTerms[bondId].tier = tier;
        }
        (uint256 unitBond, uint256 capacity,,,) = _unitTerms(b, profile.parameters);
        if (amount < unitBond) revert InsufficientSellerBond();
        _rescale(b, profile.parameters);
        // A new bond starts with a full bucket at its scale.
        b.bucketBalancePpm = capacity * b.scaleFactor * PPM;
        _transferFrom(msg.sender, amount);
        emit BondRegistered(bondId, profileId, msg.sender, amount, b.scaleFactor);
        if (sampleScaleValue != 0) emit BondTermsSet(bondId, sampleScaleValue, tier, unitBond);
    }

    /// Changes the value cap or the sales tier of a bond account (design 2
    /// rule D2-14). Leaving a cap or a limit keeps it as the recent peak for
    /// retentionBlocks: until then the unit bond and each deduction use the
    /// higher cap and a new failure window uses the higher limit. The balance
    /// must cover one unit bond at the new terms before they apply; the scale
    /// is then recomputed from the balance, and a drop is kept as the recent
    /// scale high (ADR 0022). The new terms apply from this transaction.
    function setBondTerms(uint32 bondId, uint96 sampleScaleValue, uint8 tier) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (b.status != uint8(BondStatus.ACTIVE) || b.sanctioned) revert BondNotActive();
        _checkTerms(b.profileId, sampleScaleValue, tier);
        ServiceProfileInput storage profile = profiles[b.profileId].parameters;
        SalesTier[] storage tiers = profileTerms[b.profileId].tiers;
        BondTerms storage t = bondTerms[bondId];
        // The bucket is brought current under the old terms.
        b.bucketBalancePpm = _refilledBucket(b, profile);
        b.bucketUpdatedBlock = uint64(block.number);
        uint64 until = uint64(block.number + profile.retentionBlocks);
        if (sampleScaleValue < t.sampleScaleValue) {
            t.peakCap = uint96(_recentCap(bondId, t));
            t.peakUntil = until;
        }
        if (_tierSanctionLimit(tiers[tier]) < _tierSanctionLimit(tiers[t.tier])) {
            t.peakLimit = _recentSanctionLimit(b);
            t.peakLimitUntil = until;
        }
        t.sampleScaleValue = sampleScaleValue;
        t.tier = tier;
        (uint256 unitBond,,,,) = _unitTerms(b, profile);
        uint32 limit = _tierSanctionLimit(tiers[tier]);
        if (b.balance < unitBond) revert InsufficientSellerBond();
        _rescale(b, profile);
        if (b.failureCount != 0 && block.number <= uint256(b.failureWindowStart) + profile.failureWindowBlocks) {
            if (b.scaleFactor > failureWindowScale[bondId]) failureWindowScale[bondId] = b.scaleFactor;
            if (limit > t.windowLimit) t.windowLimit = limit;
        }
        emit BondTermsSet(bondId, sampleScaleValue, tier, unitBond);
    }

    function _checkTerms(uint32 profileId, uint96 sampleScaleValue, uint8 tier) private view {
        ProfileTerms storage pt = profileTerms[profileId];
        if (tier >= pt.tiers.length) revert InvalidConfiguration();
        uint256 n = pt.valueCaps.length;
        for (uint256 i; i < n; i++) {
            if (pt.valueCaps[i] == sampleScaleValue) return;
        }
        revert ValueTooLarge();
    }

    /// Only the account owner may top up (ADR 0022). A top-up that raises the
    /// scale factor while a failure window is open raises the window's scale,
    /// and with it the threshold and the window's total deduction.
    function topUpBond(uint32 bondId, uint128 amount) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (b.status != uint8(BondStatus.ACTIVE)) revert BondNotActive();
        ServiceProfileInput storage profile = profiles[b.profileId].parameters;
        b.balance += amount;
        _rescale(b, profile);
        if (
            b.failureCount != 0 && block.number <= uint256(b.failureWindowStart) + profile.failureWindowBlocks
                && b.scaleFactor > failureWindowScale[bondId]
        ) failureWindowScale[bondId] = b.scaleFactor;
        _transferFrom(msg.sender, amount);
    }

    function requestBondExit(uint32 bondId) external onlyDelegateCall {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (b.status != uint8(BondStatus.ACTIVE)) revert BondNotActive();
        b.status = uint8(BondStatus.EXITING);
        b.exitEligibleBlock = uint64(block.number + profiles[b.profileId].parameters.retentionBlocks);
        emit BondExitRequested(bondId, b.exitEligibleBlock);
    }

    function finalizeBondExit(uint32 bondId) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (
            b.status != uint8(BondStatus.EXITING) || block.number < b.exitEligibleBlock
                || b.registrations != 0 || b.deferredBalance != 0
                || b.freezeState == uint8(FreezeState.FROZEN)
                || b.freezeState == uint8(FreezeState.CLAIM_OPEN)
        ) revert ExitNotReady();
        // The exit lock of retentionBlocks counts unpaused blocks since the
        // request (design 2 rule D2-21, ADR 0029).
        uint256 requested = b.exitEligibleBlock - profiles[b.profileId].parameters.retentionBlocks;
        if (block.number - _pausedSince(bondId, requested) < b.exitEligibleBlock) revert ExitNotReady();
        uint256 amount = b.balance;
        b.balance = 0;
        b.scaleFactor = 0;
        b.bucketBalancePpm = 0;
        b.status = uint8(BondStatus.EXITED);
        _transfer(b.owner, amount);
        emit BondExited(bondId, b.owner, amount);
    }

    function registerSeller(uint32 bondId, uint32 profileId, address signingKey, bytes32 claimsHash)
        external
        onlyDelegateCall
        returns (uint32 sellerId)
    {
        if (newSettlementsPaused) revert Paused();
        BondView storage b = bonds[bondId];
        if (msg.sender != b.owner) revert Unauthorized();
        if (b.profileId != profileId) revert BondMismatch();
        ServiceProfileView storage profile = profiles[profileId];
        if (
            b.status != uint8(BondStatus.ACTIVE) || b.sanctioned
                || b.balance < _unitBond(b)
                || b.freezeState == uint8(FreezeState.FROZEN)
                || b.freezeState == uint8(FreezeState.CLAIM_OPEN)
        ) revert BondNotActive();
        if (!profile.active) revert InactiveProfile();
        if (!_profileAvailable(profileId)) revert ServiceClassUnavailable();
        if (signingKey == address(0) || claimsHash == bytes32(0)) revert ZeroAddress();
        sellerId = nextSellerId++;
        b.registrations++;
        SellerView storage seller = sellers[sellerId].viewData;
        seller.sellerId = sellerId;
        seller.profileId = profileId;
        seller.owner = msg.sender;
        seller.signingKey = signingKey;
        seller.claimsHash = claimsHash;
        seller.bondId = bondId;
        seller.status = uint8(SellerStatus.ACTIVE);
        emit SellerRegistered(sellerId, bondId, profileId, msg.sender, signingKey, claimsHash);
    }

    function requestSellerExit(uint32 sellerId) external onlyDelegateCall {
        SellerView storage seller = sellers[sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        if (
            seller.status != uint8(SellerStatus.ACTIVE) && seller.status != uint8(SellerStatus.SUSPENDED)
                && seller.status != uint8(SellerStatus.SANCTIONED)
        ) revert SellerInactive();
        seller.status = uint8(SellerStatus.EXITING);
        seller.exitEligibleBlock =
            uint64(block.number + profiles[seller.profileId].parameters.retentionBlocks);
        emit SellerExitRequested(sellerId, seller.exitEligibleBlock);
    }

    function finalizeSellerExit(uint32 sellerId) external onlyDelegateCall {
        SellerView storage seller = sellers[sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        // An exiting registration stays until its bond account's frozen pool is
        // closed and no initial FAIL of the account is pending: exit never ends
        // the freeze, the claim window or the deduction of a failure.
        BondView storage b = bonds[seller.bondId];
        if (seller.status != uint8(SellerStatus.EXITING) || block.number < seller.exitEligibleBlock
            || b.freezeState == uint8(FreezeState.FROZEN) || b.freezeState == uint8(FreezeState.CLAIM_OPEN)
            || freezeTriggers[seller.bondId].count != 0) {
            revert ExitNotReady();
        }
        seller.status = uint8(SellerStatus.EXITED);
        b.registrations--;
        emit SellerExited(sellerId, seller.owner, 0);
    }

    /// Returns a suspended seller to ACTIVE once its bond account is not
    /// FROZEN, is not sanctioned, has no initial FAIL pending, and again covers
    /// one seller penalty. The claim window may still be open (ADR 0021): the
    /// account then reopens for settlement, and what it settles from now on is
    /// outside the frozen window until the next confirmed failure moves the
    /// window over it.
    function reinstateSeller(uint32 sellerId) external onlyDelegateCall {
        SellerView storage seller = sellers[sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        if (seller.status != uint8(SellerStatus.SUSPENDED)) revert InvalidTransition();
        BondView storage b = bonds[seller.bondId];
        if (
            b.sanctioned || b.freezeState == uint8(FreezeState.FROZEN)
                || freezeTriggers[seller.bondId].count != 0
                || b.balance < _unitBond(b)
        ) revert ReinstateConditionsUnmet();
        if (b.freezeState == uint8(FreezeState.CLAIM_OPEN)) claimReentries[seller.bondId].reopened = true;
        seller.status = uint8(SellerStatus.ACTIVE);
        emit SellerReinstated(sellerId, seller.bondId, uint64(block.number));
    }

    /// Public progress call: freezes the bond account of a seller whose case
    /// holds an initial FAIL that has not yet become final, under a profile
    /// that freezes at the initial FAIL.
    function freezeSellerDeferred(bytes32 triggerNonce) external onlyDelegateCall {
        CaseView storage c = cases[triggerNonce];
        if (c.initialVerdict != uint8(Verdict.FAIL) || _caseTerminal(c.state)) revert InvalidTransition();
        PurchaseView storage purchase = purchases[triggerNonce];
        if (!profiles[purchase.profileId].parameters.freezeOnInitialFail) revert InvalidTransition();
        BondView storage b = _bondOf(purchase);
        if (b.freezeState == uint8(FreezeState.FROZEN) || b.freezeState == uint8(FreezeState.CLAIM_OPEN)) {
            revert InvalidTransition();
        }
        _freezePending(purchases[triggerNonce].sellerId, triggerNonce);
    }

    /// Public progress call: a freeze whose trigger case ended without a
    /// failure moves to the earliest trigger still pending, or is cleared when
    /// none is left (ADR 0015).
    function releaseFrozen(uint32 bondId) external onlyDelegateCall {
        BondView storage b = bonds[bondId];
        if (b.freezeState != uint8(FreezeState.FROZEN)) revert InvalidTransition();
        CaseView storage c = cases[b.freezeNonce];
        if (!_caseTerminal(c.state)) revert DeadlineNotReached();
        if (c.state == uint8(CaseState.UNSERVED) || c.finalVerdict == uint8(Verdict.FAIL)) revert InvalidTransition();
        _releaseTrigger(b.freezeNonce);
    }

    /// Pays a buyer of an unreleased entry in an open claim window its own
    /// purchase amount against a seller-signed receipt, and an inclusion proof
    /// when the epoch was anchored.
    function claimRefund(
        bytes32 nonce,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        ReceiptProof calldata proof
    ) external onlyDelegateCall nonReentrant {
        PurchaseView storage purchase = purchases[nonce];
        if (!_purchaseExists(purchase)) revert InvalidTransition();
        BondView storage b = _bondOf(purchase);
        if (b.freezeState != uint8(FreezeState.CLAIM_OPEN) || block.number > b.claimUntilBlock) {
            revert ClaimWindowNotOpen();
        }
        // Only an entry of the frozen window is claimable: entries settled
        // before the start of its span keep their schedule (ADR 0030), and
        // entries settled after a reinstatement are outside it (ADR 0021).
        if (!_inFreezeSpans(b.bondId, purchase.settledBlock) || _forfeitedEntry(purchase)) revert ReceiptOutOfWindow();
        uint8 state = purchase.financialState;
        if (state == uint8(FinancialState.REFUNDED)) revert AlreadyClaimed();
        if (state != uint8(FinancialState.DEFERRED) && state != uint8(FinancialState.RELEASABLE)) {
            revert InvalidTransition();
        }
        bytes32 leaf = _validateReceipt(purchase, nonce, receipt, receiptSignature);
        AnchorView storage record = anchors[purchase.sellerId][purchase.epoch];
        if (
            (record.state == uint8(EpochState.ANCHORED) || record.state == uint8(EpochState.SEALED))
                && !_receiptProofValid(record, receipt, leaf, proof)
        ) revert InvalidProof();
        ClaimReentry storage late = claimReentries[b.bondId];
        if ((b.deferredBalance - late.deferredBalance) - (b.encumbered - late.encumbered) < purchase.value) {
            revert PoolExhausted();
        }
        _payDeposits(nonce);
        _setFinancialState(nonce, FinancialState.REFUNDED);
        refundSources[nonce] = uint8(RefundSource.FROZEN_POOL);
        b.claimedTotal += purchase.value;
        _transfer(purchase.buyer, purchase.value);
        emit FrozenClaimPaid(b.bondId, purchase.sellerId, nonce, purchase.buyer, purchase.value);
        emit Refunded(nonce, purchase.buyer, purchase.value, uint8(RefundSource.FROZEN_POOL));
    }

    /// Public progress call: after the claim window, forfeits the unclaimed
    /// remainder of the frozen window and locks it in the contract (ADR 0022).
    /// Entries settled after a reinstatement during the window are outside it
    /// and keep their schedule (ADR 0021), and so do entries settled before
    /// the start of the window's span (ADR 0030). UnclaimedForfeited reports
    /// the amount with zero destination amounts; a forfeiture is not a penalty
    /// of one actor and emits no Slashed.
    ///
    /// The remainder is taken as one sum when the window is one span and the
    /// deferred balance holds no entry settled before it; the sum is then the
    /// unencumbered deferred balance outside the entries settled after a
    /// reinstatement. Otherwise the window closes itemized: each unclaimed
    /// entry of its spans is forfeited and locked when releasePurchase next
    /// touches it (ADR 0030).
    function forfeitUnclaimed(uint32 bondId) external onlyDelegateCall nonReentrant {
        BondView storage b = bonds[bondId];
        if (b.freezeState != uint8(FreezeState.CLAIM_OPEN)) revert InvalidTransition();
        if (block.number <= b.claimUntilBlock) revert DeadlineNotReached();
        // The window stays open while a seller proof of the account is undecided (ADR 0034).
        if (BatchStore.layout().proofAccounts[bondId].pending != 0) revert DeadlineNotReached();
        FreezeSpan[] storage spans = freezeSpans[bondId];
        uint256 n = spans.length;
        bool itemized = n != 1 || itemizedPending[bondId] || deferredFloor[bondId] < spans[0].from;
        ForfeitWindow[] storage windows = forfeitWindows[bondId];
        for (uint256 i; i < n; i++) windows.push(ForfeitWindow(spans[i].from, spans[i].through, itemized));
        delete freezeSpans[bondId];
        b.forfeitedThrough = b.freezeBlock;
        b.freezeState = uint8(FreezeState.CLAIM_CLOSED);
        uint256 amount;
        if (itemized) {
            itemizedPending[bondId] = true;
        } else {
            ClaimReentry storage late = claimReentries[bondId];
            amount = (b.deferredBalance - late.deferredBalance) - (b.encumbered - late.encumbered);
            b.deferredBalance -= amount;
            if (b.deferredBalance == 0) _deferredEmptied(bondId);
        }
        delete claimReentries[bondId];
        _lockForfeit(bondId, b.freezeNonce, amount);
    }

    function _unitBond(BondView storage b) private view returns (uint256 unitBond) {
        (unitBond,,,,) = _unitTerms(b, profiles[b.profileId].parameters);
    }

    function _caseTerminal(uint8 state) private pure returns (bool) {
        return state == uint8(CaseState.FINAL) || state == uint8(CaseState.INCONCLUSIVE)
            || state == uint8(CaseState.UNSERVED) || state == uint8(CaseState.DELIVERED);
    }

    // The omission proof, moved here from the recovery module to keep it
    // within the EIP-170 code size limit (rule edition 8 work); the router
    // delegates it to this module.

    /// Omission of a settled purchase from its epoch's anchored list. Anyone
    /// can prove it from the public list alone: the anchor requires strictly
    /// ascending nonces, so two adjacent entries whose nonces bracket the
    /// purchase's nonce (or the first or last entry, at the ends) show that
    /// the nonce is not in the list. No receipt or signature is needed.
    function proveOmission(
        bytes32 nonce,
        FairBindMerkle.ReceiptEntry calldata left,
        ReceiptProof calldata leftProof,
        FairBindMerkle.ReceiptEntry calldata right,
        ReceiptProof calldata rightProof,
        uint8 boundary
    ) external onlyDelegateCall nonReentrant {
        PurchaseView storage purchase = purchases[nonce];
        if (nonce == bytes32(0) || !_purchaseExists(purchase)) revert InvalidProof();
        AnchorView storage anchorRecord = anchors[purchase.sellerId][purchase.epoch];
        if (anchorRecord.root == bytes32(0) || block.number > purchase.retainUntil) {
            revert InvalidProof();
        }
        if (boundary == uint8(ProofBoundary.INTERIOR)) {
            if (
                leftProof.index + 1 != rightProof.index || left.nonce >= nonce || nonce >= right.nonce
                    || !_entryProofValid(anchorRecord, left, leftProof)
                    || !_entryProofValid(anchorRecord, right, rightProof)
            ) revert InvalidProof();
        } else if (boundary == uint8(ProofBoundary.LOWER)) {
            if (
                rightProof.index != 0 || nonce >= right.nonce
                    || !_entryProofValid(anchorRecord, right, rightProof)
            ) revert InvalidProof();
        } else if (boundary == uint8(ProofBoundary.UPPER)) {
            if (
                leftProof.index + 1 != anchorRecord.count || left.nonce >= nonce
                    || !_entryProofValid(anchorRecord, left, leftProof)
            ) revert InvalidProof();
        } else {
            revert InvalidProof();
        }
        _sellerFailure(nonce, RefundSource.OMISSION);
    }

    function _entryProofValid(
        AnchorView storage anchorRecord,
        FairBindMerkle.ReceiptEntry calldata entry,
        ReceiptProof calldata proof
    ) private view returns (bool) {
        if (proof.count != anchorRecord.count) return false;
        return FairBindMerkle.verify(
            anchorRecord.root, entry.nonce, entry.receiptLeaf, proof.index, proof.count, proof.siblings
        );
    }

}
