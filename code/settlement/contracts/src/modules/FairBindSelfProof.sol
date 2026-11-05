// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { ExchangeShared } from "./ExchangeShared.sol";

/// Extension module 7 (ADR 0037): the seller's proof on a frozen entry of a
/// proof profile (rule D2-32). The entry's confirmed PASS proof (prove) is
/// the proof; it holds the entry from the buyer's claim, and the entry is
/// paid to the seller once the hold period and the receipt-binding window
/// T_rcpt are over. A confirmed failure of the purchase voids it.
contract FairBindSelfProof is ExchangeShared {
    uint8 public constant MODULE_KIND = 17;

    event SelfProofSet(bytes32 indexed nonce, uint8 state);

    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        ExchangeShared(token, gov, guard, treasury, rewardPool)
    { }

    // ------------------------------------------------ the seller's proof

    /// The seller proves its frozen entry with the purchase's confirmed PASS
    /// proof (rule D2-32 (a)); prove carries the proof when the purchase has
    /// none yet.
    function selfProve(bytes32 nonce) external onlyDelegateCall nonReentrant {
        PurchaseView storage p = purchases[nonce];
        if (_exchangeMode(p.profileId) != ExchangeStore.MODE_PROOF || !ExchangeStore.layout().records[nonce].proven) {
            revert ProofNotAllowed();
        }
        if (msg.sender != sellers[p.sellerId].viewData.owner) revert Unauthorized();
        _selfProof(nonce);
    }

    /// The seller's proof on an entry of its open claim window (rule D2-25
    /// (b) as D2-32 reads it, with B_p = 0): once per entry, before a claim.
    /// It is confirmed now when the entry's epoch is sampled, its sample case
    /// (if any) has ended and every sample case and epoch of the account is
    /// decided, and reserved otherwise. The entry is held from the claim.
    function _selfProof(bytes32 nonce) private {
        PurchaseView storage p = purchases[nonce];
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        uint32 bondId = sellers[p.sellerId].viewData.bondId;
        BondView storage b = bonds[bondId];
        uint8 fs = p.financialState;
        if (r.selfState != 0 || !_bound(nonce)) revert ProofNotAllowed();
        if (
            b.freezeState != uint8(FreezeState.CLAIM_OPEN) || block.number > b.claimUntilBlock
                || !_inFreezeSpans(bondId, p.settledBlock) || _forfeitedEntry(p)
                || (fs != uint8(FinancialState.DEFERRED) && fs != uint8(FinancialState.RELEASABLE))
        ) revert ClaimWindowNotOpen();
        _setFinancialState(nonce, FinancialState.HELD);
        if (_selfReady(nonce)) {
            r.selfState = ExchangeStore.SELF_CONFIRMED;
        } else {
            r.selfState = ExchangeStore.SELF_RESERVED;
            BatchStore.layout().proofAccounts[bondId].pending++;
        }
        emit SelfProofSet(nonce, r.selfState);
    }

    /// The order condition of the seller's proof (rule D2-25 (b)). A
    /// mutation build of the tests overrides it.
    function _selfReady(bytes32 nonce) internal view virtual returns (bool) {
        PurchaseView storage p = purchases[nonce];
        AnchorView storage a = anchors[p.sellerId][p.epoch];
        if (a.state != uint8(EpochState.SEALED)) return false;
        ServiceProfileInput storage profile = profiles[p.profileId].parameters;
        if (block.number <= a.sealDeadline + deadlineConfigs[profile.deadlineConfigId].openBlocks) return false;
        BatchStore.ProofAccount storage acc = BatchStore.layout().proofAccounts[sellers[p.sellerId].viewData.bondId];
        if (acc.openSamples != 0 || acc.unsealedEpochs != 0) return false;
        (bool eligible,) = _sampleStatus(p, nonce);
        return !eligible || cases[nonce].state == uint8(CaseState.FINAL);
    }

    /// A reserved proof whose conditions now hold is confirmed.
    function activateSelfProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        if (r.selfState != ExchangeStore.SELF_RESERVED || !_selfReady(nonce)) revert InvalidTransition();
        r.selfState = ExchangeStore.SELF_CONFIRMED;
        BatchStore.layout().proofAccounts[_bondOf(nonce)].pending--;
        emit SelfProofSet(nonce, r.selfState);
    }

    /// A reserved proof whose conditions can never hold (its epoch failed or
    /// passed M without a value) ends; the entry returns to the claim window
    /// from this block and the proof does not count as the entry's one.
    function voidSelfProof(bytes32 nonce) external onlyDelegateCall nonReentrant {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        PurchaseView storage p = purchases[nonce];
        uint8 es = anchors[p.sellerId][p.epoch].state;
        bool never = es == uint8(EpochState.EPOCH_FAILED) || (es == uint8(EpochState.ANCHORED) && _deadlinePassed(p.sellerId, p.epoch));
        if (r.selfState != ExchangeStore.SELF_RESERVED || !never) revert InvalidTransition();
        r.selfState = 0;
        BatchStore.layout().proofAccounts[_bondOf(nonce)].pending--;
        _setFinancialState(nonce, FinancialState.DEFERRED);
        BondView storage b = bonds[_bondOf(nonce)];
        uint64 until = uint64(block.number + profiles[p.profileId].parameters.claimWindowBlocks);
        if (b.claimUntilBlock < until) b.claimUntilBlock = until;
        emit SelfProofSet(nonce, 0);
    }

    /// Pays the seller an entry its confirmed proof holds, once the release
    /// rules of releasePurchase hold and the receipt-binding window T_rcpt is
    /// over: more than retentionBlocks unpaused blocks since settlement, so
    /// that a binding failure proved by retainUntil still voids the proof
    /// (rule D2-32 (c)).
    function releaseSelfProven(bytes32 nonce) external onlyDelegateCall nonReentrant {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        PurchaseView storage p = purchases[nonce];
        if (
            r.selfState != ExchangeStore.SELF_CONFIRMED || p.financialState != uint8(FinancialState.HELD)
                || r.disputeState == ExchangeStore.DISPUTE_OPEN
        ) revert InvalidTransition();
        AnchorView storage a = anchors[p.sellerId][p.epoch];
        if (a.state != uint8(EpochState.SEALED)) revert InvalidTransition();
        uint256 age = block.number - _pausedSince(_bondOf(nonce), p.settledBlock);
        if (
            block.number <= p.claimUntil
                || block.number <= a.sealDeadline + deadlineConfigs[profiles[p.profileId].parameters.deadlineConfigId].openBlocks
                || age < p.releaseBlock || !_bindingWindowOver(age, p.retainUntil)
        ) revert DeadlineNotReached();
        r.selfState = ExchangeStore.SELF_RELEASED;
        _setFinancialState(nonce, FinancialState.RELEASED);
        _transfer(sellers[p.sellerId].viewData.owner, p.value);
        emit Released(nonce, p.sellerId, p.value);
    }

    /// Whether the receipt-binding window is over at effective block `age`.
    /// A mutation build of the tests overrides it.
    function _bindingWindowOver(uint256 age, uint256 retainUntil) internal pure virtual returns (bool) {
        return age > retainUntil;
    }

    /// A confirmed failure of the purchase voids the seller's proof on it
    /// and ends a reservation (rule D2-25 (e)).
    function _voidSelf(bytes32 nonce) private {
        ExchangeStore.Record storage r = ExchangeStore.layout().records[nonce];
        uint8 st = r.selfState;
        if (st == ExchangeStore.SELF_RESERVED) {
            BatchStore.layout().proofAccounts[_bondOf(nonce)].pending--;
            r.selfState = 0;
        } else if (st == ExchangeStore.SELF_CONFIRMED) {
            r.selfState = ExchangeStore.SELF_INVALID;
        } else {
            return;
        }
        emit SelfProofSet(nonce, r.selfState);
    }

    function hook(uint256 op, uint256 arg) external onlyHook {
        if (op != HOOK_PASS_FAILURE) _unknownHook();
        _voidSelf(bytes32(arg));
    }

    function hookOps() external pure returns (uint256) {
        return 1 << HOOK_PASS_FAILURE;
    }

    function selectors() external pure returns (bytes4[] memory s) {
        s = new bytes4[](5);
        s[0] = this.selfProve.selector;
        s[1] = this.activateSelfProof.selector;
        s[2] = this.voidSelfProof.selector;
        s[3] = this.releaseSelfProven.selector;
        s[4] = this.selfProofReady.selector;
    }

    function selfProofReady(bytes32 nonce) external view onlyDelegateCall returns (bool) {
        return _selfReady(nonce);
    }
}

