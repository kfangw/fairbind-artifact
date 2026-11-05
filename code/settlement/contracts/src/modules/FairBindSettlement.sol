// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;
import { FairBindCore } from "../FairBindCore.sol";
import { FairBindDesign2 } from "../FairBindDesign2.sol";
import { FairBindMerkle } from "../FairBindMerkle.sol";
import { SamplingStore } from "./SamplingStore.sol";
import { BatchStore } from "./BatchStore.sol";
import { ExchangeStore } from "./ExchangeStore.sol";
import { Rule8Store } from "./Rule8Store.sol";

contract FairBindSettlement is FairBindCore {
    address private immutable moduleSelf = address(this);
    uint8 public constant MODULE_KIND = 2;
    modifier onlyDelegateCall() {
        if (address(this) == moduleSelf) revert Unauthorized();
        _;
    }
    constructor(address token, address gov, address guard, address treasury, address rewardPool)
        FairBindCore(token, gov, guard, treasury, rewardPool)
    { }

    /// Gas given to one item of a settlement batch (rule D2-34 (d)): the
    /// item's settlement, its token transfer and the payer's authorization
    /// check, an ERC-1271 answer included, run within it.
    uint256 public constant ITEM_GAS_MAX = 600_000;
    /// Gas the batch frame spends around one item call (encoding, the call,
    /// the result and the skip event); the remaining-gas check adds it.
    uint256 internal constant ITEM_FRAME_GAS = 12_000;

    /// Transient flag of a running settlement batch: its self calls of
    /// `settle` run inside the batch's reentrancy lock.
    bytes32 internal constant BATCH_FLAG = keccak256("fairbind.settlement.batch.v1");

    /// One settlement. Called by a settlement batch through the router it
    /// runs inside the batch's lock and leaves the cost mark to the batch.
    function settle(
        uint32 sellerId,
        uint32 profileId,
        bytes32 claimsHash,
        bytes16 idempotencyKey,
        bytes32 requestHash,
        TransferAuthorization calldata authorization,
        bytes calldata paymentSignature
    ) external onlyDelegateCall returns (bytes32 nonce, bytes32 keyId) {
        bool item = _batchItem();
        if (!item) {
            if (entered != 1) revert InvalidConfiguration();
            entered = 2;
            _markCost();
        }
        (nonce, keyId) =
            _settle(sellerId, profileId, claimsHash, idempotencyKey, requestHash, authorization, paymentSignature);
        if (!item) entered = 1;
    }

    /// Whether this call is an item of a running batch: a self call of the
    /// router while the batch flag is set.
    function _batchItem() private view returns (bool flag) {
        if (msg.sender != address(this)) return false;
        bytes32 slot = BATCH_FLAG;
        assembly ("memory-safe") {
            flag := tload(slot)
        }
    }

    /// Settlement batch (rule D2-34): anyone may call it, and the items may
    /// belong to different sellers and accounts. Each item runs as `settle`
    /// in a self call given ITEM_GAS_MAX gas; an item that reverts leaves no
    /// state and is skipped with a SettlementSkipped event, and the others
    /// settle. Before each item the batch checks that the call can be given
    /// ITEM_GAS_MAX in full (EIP-150 included) and reverts as a whole when
    /// it cannot, so that the caller's gas limit cannot make an item fail.
    /// The state and Settled events it leaves are those of the same `settle`
    /// transactions in item order, the skipped ones reverted.
    function settleBatch(SettleItem[] calldata items) external onlyDelegateCall nonReentrant returns (uint256 settled) {
        _markCost();
        bytes32 slot = BATCH_FLAG;
        assembly ("memory-safe") {
            tstore(slot, 1)
        }
        for (uint256 i; i < items.length; i++) {
            if (!_itemGasOk(gasleft())) revert BatchGasShort();
            (bool ok, bytes4 reason) = _runItem(items[i]);
            if (ok) {
                settled++;
            } else {
                _onItemFailure(reason);
                emit SettlementSkipped(i, items[i].authorization.nonce, reason);
            }
        }
        assembly ("memory-safe") {
            tstore(slot, 0)
        }
    }

    /// Runs one item in a self call with ITEM_GAS_MAX gas and returns whether
    /// it settled and the selector of its revert. The call's memory is
    /// released afterwards, so every item costs the same frame gas. A
    /// mutation build of the tests overrides it.
    function _runItem(SettleItem calldata item) internal virtual returns (bool ok, bytes4 reason) {
        uint256 start;
        assembly ("memory-safe") {
            start := mload(0x40)
        }
        bytes memory data = abi.encodeCall(
            this.settle,
            (
                item.sellerId,
                item.profileId,
                item.claimsHash,
                item.idempotencyKey,
                item.requestHash,
                item.authorization,
                item.paymentSignature
            )
        );
        assembly ("memory-safe") {
            ok := call(ITEM_GAS_MAX, address(), 0, add(data, 0x20), mload(data), 0, 0)
            if and(iszero(ok), gt(returndatasize(), 3)) {
                returndatacopy(0, 0, 4)
                reason := and(mload(0), shl(224, 0xffffffff))
            }
            mstore(0x40, start)
        }
    }

    /// Whether the next item can be given ITEM_GAS_MAX in full: a call
    /// passes at most 63/64 of the gas left. A mutation build overrides it.
    function _itemGasOk(uint256 left) internal view virtual returns (bool) {
        return left >= ITEM_GAS_MAX * 64 / 63 + ITEM_FRAME_GAS;
    }

    /// A failed item is skipped. A mutation build of the tests overrides it.
    function _onItemFailure(bytes4) internal virtual { }

    /// Marks the transaction as one whose fixed share is counted (rule D2-33
    /// (e') 2, D2-34 (g)). A mutation build of the tests overrides it.
    function _markCost() internal virtual {
        ExchangeStore.mark();
    }

    function _settle(
        uint32 sellerId,
        uint32 profileId,
        bytes32 claimsHash,
        bytes16 idempotencyKey,
        bytes32 requestHash,
        TransferAuthorization calldata authorization,
        bytes calldata paymentSignature
    ) private returns (bytes32 nonce, bytes32 keyId) {
        if (newSettlementsPaused) revert Paused();
        SellerView storage seller = sellers[sellerId].viewData;
        if (seller.status == uint8(SellerStatus.SUSPENDED)) revert SellerIsSuspended();
        if (seller.status != uint8(SellerStatus.ACTIVE)) revert SellerInactive();
        if (seller.profileId != profileId) revert ProfileMismatch();
        if (seller.claimsHash != claimsHash) revert ClaimsMismatch();
        ServiceProfileView storage profile = profiles[profileId];
        if (!profile.active) revert InactiveProfile();
        if (!_profileAvailable(profileId)) revert ServiceClassUnavailable();
        if (authorization.to != address(this) || authorization.from == address(0)) {
            revert AuthorizationMismatch();
        }
        if (
            block.timestamp <= authorization.validAfter
                || block.timestamp >= authorization.validBefore
        ) revert AuthorizationExpired();
        // Under a profile with tiers the cap is the account's own value cap in
        // this block, checked before the bucket is touched (ADR 0024).
        bool tiered = profileTerms[profileId].tiers.length != 0;
        uint256 cap = tiered ? bondTerms[seller.bondId].sampleScaleValue : profile.parameters.maxPurchaseValue;
        if (authorization.value == 0 || authorization.value > cap) {
            revert ValueTooLarge();
        }
        keyId = _deriveKeyId(sellerId, authorization.from, idempotencyKey);
        nonce = _deriveNonce(
            sellerId, profileId, claimsHash, authorization.from, idempotencyKey, requestHash
        );
        if (authorization.nonce != nonce) revert NonceMismatch();
        if (_keyUsed(keyId)) revert KeyAlreadyUsed();
        // A nonce is used exactly when its purchase exists (settledBlock != 0); no separate flag is written.
        if (_purchaseExists(purchases[nonce])) revert NonceAlreadyUsed();
        BondView storage bond = bonds[seller.bondId];
        // An open claim window admits settlements only after a reinstatement
        // reopened the account, and only after freezeBlock: they are outside
        // the frozen window and are tracked apart until it closes (ADR 0021).
        ClaimReentry storage late = claimReentries[seller.bondId];
        bool reopened = bond.freezeState == uint8(FreezeState.CLAIM_OPEN) && late.reopened
            && block.number > bond.freezeBlock;
        (uint256 unitBond, uint256 bucketCapacity, uint256 refillRate,,) = _unitTerms(bond, profile.parameters);
        if (
            bond.status != uint8(BondStatus.ACTIVE) || bond.sanctioned
                || bond.balance < unitBond
                || bond.freezeState == uint8(FreezeState.FROZEN)
                || (bond.freezeState == uint8(FreezeState.CLAIM_OPEN) && !reopened)
                || freezeTriggers[seller.bondId].count != 0
        ) revert BondNotActive();
        // The bucket of _consumeBucket with the unit terms read above, so that they are read once.
        {
            uint256 bucket = bond.bucketBalancePpm
                + uint256(block.number - bond.bucketUpdatedBlock) * refillRate * bond.scaleFactor;
            uint256 bucketCap = bucketCapacity * bond.scaleFactor * PPM;
            if (bucket > bucketCap) bucket = bucketCap;
            if (bucket < PPM) revert RateLimitExceeded();
            bond.bucketBalancePpm = bucket - PPM;
            bond.bucketUpdatedBlock = uint64(block.number);
        }
        purchaseForKey[keyId] = nonce;
        _receiveWithAuthorization(authorization, paymentSignature);
        uint24 epoch = _epoch(profile.parameters);
        DeadlineConfig storage deadlines = deadlineConfigs[profile.parameters.deadlineConfigId];
        uint64 retainUntil = uint64(block.number + profile.parameters.retentionBlocks);
        // Neither the nonce nor claimsHash is written per purchase (journal J3b): the
        // nonce is the mapping key, and claimsHash is the account's claims hash, which is
        // set once at registration and equal to the one checked above. Both are filled in
        // by getPurchase; the record exists exactly when settledBlock is not zero. The
        // fields are written one by one in slot order so that the two slots are not touched.
        PurchaseView storage purchase = purchases[nonce];
        purchase.keyId = keyId;
        purchase.sellerId = sellerId;
        purchase.profileId = profileId;
        purchase.buyer = authorization.from;
        purchase.value = authorization.value;
        purchase.requestHash = requestHash;
        purchase.epoch = epoch;
        purchase.settledBlock = uint64(block.number);
        purchase.responseDue = uint64(block.number + deadlines.responseBlocks);
        purchase.claimUntil = uint64(block.number + deadlines.responseBlocks + deadlines.claimBlocks);
        purchase.releaseBlock = uint64(block.number + profile.parameters.deferBlocks);
        purchase.retainUntil = retainUntil;
        purchase.financialState = uint8(FinancialState.DEFERRED);
        if (tiered) settledSamplePpm[nonce] = FairBindDesign2.samplePpm(authorization.value, cap);
        // The first entry after an empty deferred balance is the earliest one
        // it holds (ADR 0030).
        if (bond.deferredBalance == 0) deferredFloor[seller.bondId] = uint64(block.number);
        bond.deferredBalance += authorization.value;
        if (reopened) late.deferredBalance += authorization.value;
        uint32 index = epochPurchaseCount[sellerId][epoch]++;
        if (_r8On(profileId)) {
            _r8Settled(nonce, sellerId, profileId, epoch, index, cap);
            _r8Held(sellerId, profileId, bucketCapacity * bond.scaleFactor, refillRate * bond.scaleFactor);
        }
        if (epochRetainUntil[sellerId][epoch] < retainUntil) {
            epochRetainUntil[sellerId][epoch] = retainUntil;
        }
        if (_batched(profileId)) _settleBatched(nonce);
        else if (_exchangeMode(profileId) == ExchangeStore.MODE_PROOF) _settleProof(nonce, authorization.validAfter);
        emit Settled(
            nonce,
            keyId,
            sellerId,
            seller.bondId,
            profileId,
            authorization.from,
            authorization.value,
            epoch,
            requestHash,
            claimsHash
        );
    }

    /// Settlement under rule edition 8. The first sale of a seller epoch
    /// opens it in its profile epoch: the profile epoch is not closed before
    /// the seller's release cursor passes it (rule D2-35 (d) 1).
    /// The settlement also extends the accumulator of its release unit
    /// (rule D2-39 (b) 2, (n)): A_{a,E,k} <- H(A_{a,E,k} || nonce || payer
    /// || v || cap), k the settlement's index in the seller epoch divided by
    /// the unit size; a full unit leaves its slot and the next settlement
    /// starts the next one from zero.
    function _r8Settled(bytes32 nonce, uint32 sellerId, uint32 profileId, uint24 epoch, uint32 index, uint256 cap)
        private
    {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        if (index == 0) r8.openSellerEpochs[profileId][epoch]++;
        uint256 k = uint256(index) >> r8.terms[profileId].unitLog2;
        PurchaseView storage p = purchases[nonce];
        mapping(uint256 => bytes32) storage acc = r8.unitAcc[sellerId][epoch];
        acc[k] = keccak256(abi.encode(acc[k], nonce, p.buyer, p.value, cap));
    }

    /// The held settlement cap (rule D2-42): n_h, the settlements of the
    /// seller's episode neither paid nor refunded, must stay below N_h =
    /// ceil(q_S + r_S * H_N), q_S and r_S the account's bucket capacity and
    /// refill (in settlements and settlements per block), H_N the profile's
    /// held window. At n_h >= N_h the settlement reverts, as one above the
    /// value cap does.
    function _r8Held(uint32 sellerId, uint32 profileId, uint256 q, uint256 rPpm) private {
        Rule8Store.Layout storage r8 = Rule8Store.layout();
        uint256 nh = (q * PPM + rPpm * r8.terms[profileId].heldWindow + PPM - 1) / PPM;
        uint32 held = r8.held[sellerId];
        if (held >= nh) revert HeldSettlementCap();
        r8.held[sellerId] = held + 1;
    }

    /// Settlement under batch terms. The seller's first sale of the epoch makes
    /// the epoch block seller proofs of the account until its sampling is
    /// decided (ADR 0034). Under a proportional appeal deposit the account's
    /// held total, here its deferred balance, updates its high marks after
    /// keeping the mark at the end of the previous block once per block
    /// (ADR 0033). A side-gain profile admits the sale only when the epoch's
    /// recorded opening count reaches minVerifiers and the side-gain deposit
    /// covers one more open sale at the account's recent cap (ADR 0035).
    function _settleBatched(bytes32 nonce) private {
        PurchaseView storage purchase = purchases[nonce];
        uint32 sellerId = purchase.sellerId;
        uint32 profileId = purchase.profileId;
        uint24 epoch = purchase.epoch;
        uint32 bondId = sellers[sellerId].viewData.bondId;
        uint256 held = bonds[bondId].deferredBalance;
        BatchStore.Layout storage l = BatchStore.layout();
        BatchStore.Terms storage t = l.terms[profileId];
        if (!l.epochCounted[sellerId][epoch]) {
            l.epochCounted[sellerId][epoch] = true;
            l.proofAccounts[bondId].unsealedEpochs++;
        }
        ServiceProfileInput storage p = profiles[profileId].parameters;
        if (t.depositPpm != 0) {
            BatchStore.HeldMark storage m = l.held[bondId];
            uint256 w = p.deferBlocks;
            if (m.snapBlock != block.number) {
                m.snap = uint96(_heldHigh(m, block.number - 1, w));
                m.snapBlock = uint64(block.number);
            }
            uint256 k = block.number / w;
            if (k != m.window) {
                m.prev = k == uint256(m.window) + 1 ? m.cur : m.last;
                m.cur = m.last;
                m.window = uint32(k);
            }
            if (held > m.cur) m.cur = uint96(held);
            m.last = uint96(held);
        }
        if (t.sideGainPpm != 0) {
            if (l.epochOpenCount[profileId][epoch] < p.minVerifiers) revert ServiceClassUnavailable();
            BatchStore.SideGain storage g = l.sideGain[bondId];
            if (!_sideGainCovered(g.deposit, _sideGainUnit(bondId, profileId), g.open)) revert InsufficientSellerBond();
            g.open++;
            l.sideGainOpen[nonce] = true;
        }
    }

    /// Settlement under a proof profile (ADR 0037). The buyer's validAfter is
    /// the purchase's reference time; a validAfter more than refWindow
    /// seconds before this block is refused (rule D2-29 (c)). The seller's
    /// first sale of the epoch makes the epoch block the seller's proofs on
    /// frozen entries until its sampling is decided.
    function _settleProof(bytes32 nonce, uint256 validAfter) private {
        PurchaseView storage purchase = purchases[nonce];
        ExchangeStore.Layout storage x = ExchangeStore.layout();
        if (!_referenceTimeOk(validAfter, x.terms[purchase.profileId].refWindow)) revert AuthorizationExpired();
        x.records[nonce].refTime = uint64(validAfter);
        BatchStore.Layout storage l = BatchStore.layout();
        uint32 sellerId = purchase.sellerId;
        uint24 epoch = purchase.epoch;
        if (!l.epochCounted[sellerId][epoch]) {
            l.epochCounted[sellerId][epoch] = true;
            l.proofAccounts[sellers[sellerId].viewData.bondId].unsealedEpochs++;
        }
    }

    /// Whether the idempotency key already settled. A mutation build of the
    /// tests overrides it.
    function _keyUsed(bytes32 keyId) internal view virtual returns (bool) {
        return purchaseForKey[keyId] != bytes32(0);
    }

    /// Whether validAfter lies at most refWindow seconds before this block.
    /// A mutation build of the tests overrides it.
    function _referenceTimeOk(uint256 validAfter, uint256 refWindow) internal view virtual returns (bool) {
        return block.timestamp - validAfter <= refWindow;
    }

    /// Whether the side-gain deposit covers one unit per open sale and one
    /// for this sale (ADR 0035). A mutation build of the tests overrides it.
    function _sideGainCovered(uint256 deposit, uint256 unit, uint256 open) internal pure virtual returns (bool) {
        return deposit >= unit * (open + 1);
    }

    /// Whether a unit of `length` entries is the unit the epoch count and
    /// the unit size fix: every unit but the last is full and the last holds
    /// the rest, so the units add up to the count. Every production build:
    /// equality. A mutation build of the tests overrides it.
    function _unitLengthOk(uint256 length, uint256 expected) internal pure virtual returns (bool) {
        return length == expected;
    }

    /// Largest unit: 2^13 = 8192 entries, the largest power of two below the
    /// 11,742 entries one 30,000,000-gas transaction holds (rule D2-19, 13.9).
    uint8 public constant MAX_UNIT_LOG2 = 13;

    event AnchorUnitPosted(
        uint32 indexed sellerId, uint24 indexed epoch, uint32 unit, uint8 unitLog2, bytes32 root, bytes32 publicationHash
    );

    /// Split anchor (journal J3). The epoch's (nonce, receiptLeaf) list, strictly
    /// ascending as for `anchor`, is posted in units of 2^unitLog2 entries (the last
    /// unit holds the rest), unit 0 first, each unit in its own transaction and all
    /// inside the anchor window. Unit u holds the entries at global positions
    /// [u * 2^unitLog2, ...). The epoch is anchored by the transaction that posts
    /// the last unit; its root is the merkle-v1 root of the whole list, so every
    /// proof, omission proof and receipt check that exists for `anchor` works on
    /// a split epoch unchanged. An epoch whose units are incomplete at the
    /// deadline ends through timeoutAnchor like an unanchored one.
    function anchorUnit(
        uint32 sellerId,
        uint24 epoch,
        uint32 unit,
        uint8 unitLog2,
        FairBindMerkle.ReceiptEntry[] calldata entries,
        bytes32 publicationHash
    ) external onlyDelegateCall {
        SellerView storage seller = sellers[sellerId].viewData;
        if (msg.sender != seller.owner) revert Unauthorized();
        if (seller.status == uint8(SellerStatus.NONE) || seller.status == uint8(SellerStatus.EXITED)) {
            revert SellerInactive();
        }
        if (publicationHash == bytes32(0)) revert InvalidConfiguration();
        uint32 total = epochPurchaseCount[sellerId][epoch];
        if (total == 0) revert CountMismatch();
        AnchorView storage record = anchors[sellerId][epoch];
        if (record.state != uint8(EpochState.NONE)) revert InvalidTransition();
        ServiceProfileInput storage profile = profiles[seller.profileId].parameters;
        uint256 base = _anchorBase(profile, epoch);
        uint256 deadline = base + deadlineConfigs[profile.deadlineConfigId].anchorBlocks;
        if (block.number < base) revert AnchorTooEarly();
        if (block.number > deadline) revert AnchorWindowClosed();
        SamplingStore.UnitAnchor storage u = SamplingStore.layout().units[sellerId][epoch];
        if (unit != u.roots.length) revert InvalidTransition();
        if (unit == 0) {
            if (unitLog2 > MAX_UNIT_LOG2) revert SamplingStore.UnitTooLarge();
        } else if (unitLog2 != u.unitLog2) {
            revert InvalidConfiguration();
        }
        uint256 size = uint256(1) << unitLog2;
        uint256 start = uint256(unit) * size;
        if (start >= total) revert CountMismatch();
        // The unit's size is fixed by the epoch count; the cap check is this equality.
        uint256 expected = total - start < size ? total - start : size;
        if (!_unitLengthOk(entries.length, expected)) revert CountMismatch();
        if (!FairBindMerkle.strictlyAscending(entries)) revert EntriesNotAscending();
        bytes32 subRoot = FairBindMerkle.computeRoot(entries);
        // An anchor unit counts the fixed share of a measured cost in its transaction (ADR 0037).
        ExchangeStore.mark();
        // One unit holds the whole list (journal J4): the epoch is recorded as by
        // the one-transaction anchor, with the unit's root and publication hash and
        // no unit record. getAnchorUnits is then empty and verifyUnitMember checks
        // unit 0 against the anchor root.
        if (unit == 0 && expected == total && _singleUnitDirect()) {
            if (subRoot == bytes32(0)) revert InvalidConfiguration();
            _finishAnchor(sellerId, epoch, record, profile, deadline, subRoot, publicationHash, total);
            return;
        }
        if (unit != 0 && uint256(entries[0].nonce) <= uint256(u.tail)) revert EntriesNotAscending();
        u.roots.push(subRoot);
        emit AnchorUnitPosted(sellerId, epoch, unit, unitLog2, subRoot, publicationHash);
        if (unit == 0) {
            u.unitLog2 = unitLog2;
            u.pubAcc = publicationHash;
        }
        if (start + expected < total) {
            if (unit != 0) u.pubAcc = _publicationStep(u.pubAcc, publicationHash);
            u.tail = entries[expected - 1].nonce;
            return;
        }
        // The last unit: the accumulator stays at the units before it, and `tail`
        // takes the last unit's publication hash in place of the nonce.
        bytes32 pub = publicationHash;
        if (unit != 0) {
            pub = _publicationStep(u.pubAcc, publicationHash);
            u.tail = publicationHash;
        }
        _finishAnchor(sellerId, epoch, record, profile, deadline, _combinedRoot(u, total), pub, total);
    }

    /// One fold of the publication accumulator (journal J4). Order matters and
    /// every earlier unit counts; mutation builds replace it in tests.
    function _publicationStep(bytes32 acc, bytes32 publicationHash) internal pure virtual returns (bytes32) {
        return keccak256(abi.encodePacked(acc, publicationHash));
    }

    /// Whether a single unit takes the one-transaction anchor path (journal J4);
    /// a mutation build turns it off in tests.
    function _singleUnitDirect() internal pure virtual returns (bool) {
        return true;
    }

    /// merkle-v1 root of the whole list from the unit roots. A last unit with
    /// fewer than 2^unitLog2 entries is lifted to the unit height by pairing
    /// its root with itself, which is what the whole-list tree does to its
    /// last node at those levels; with one unit the unit root is the root.
    function _combinedRoot(SamplingStore.UnitAnchor storage u, uint32 total) private view returns (bytes32) {
        bytes32[] memory level = u.roots;
        uint256 n = level.length;
        if (n == 1) return level[0];
        uint256 size = uint256(1) << u.unitLog2;
        uint256 width = total - (n - 1) * size;
        uint256 height;
        for (; width > 1; width = (width + 1) >> 1) height++;
        for (; height < u.unitLog2; height++) {
            level[n - 1] = FairBindMerkle.nodeHash(level[n - 1], level[n - 1]);
        }
        while (n > 1) {
            uint256 next = (n + 1) >> 1;
            for (uint256 i; i < next; i++) {
                bytes32 left = level[2 * i];
                bytes32 right = 2 * i + 1 < n ? level[2 * i + 1] : left;
                level[i] = FairBindMerkle.nodeHash(left, right);
            }
            n = next;
        }
        return level[0];
    }

    /// Puts the receipt of a sample case and its inclusion proof in the
    /// anchored epoch on chain, within serveBlocks of the case opening (ADR 0024).
    function submitSampleReceipt(
        bytes32 nonce,
        FairBindReceipt calldata receipt,
        bytes calldata receiptSignature,
        ReceiptProof calldata proof
    ) external onlyDelegateCall {
        uint64 due = sampleReceiptDue[nonce];
        if (due == 0) revert InvalidTransition();
        if (block.number > due) revert DeadlinePassed();
        PurchaseView storage p = purchases[nonce];
        bytes32 leaf = _validateReceipt(p, nonce, receipt, receiptSignature);
        if (!_receiptProofValid(anchors[p.sellerId][p.epoch], receipt, leaf, proof)) revert InvalidProof();
        sampleReceiptDue[nonce] = 0;
        emit SampleReceiptRecorded(nonce);
    }

    /// Public progress call: a sample case whose receipt and inclusion proof
    /// are not on chain by their deadline ends UNSERVED, a confirmed failure of
    /// the seller (ADR 0024).
    function timeoutSampleReceipt(bytes32 nonce) external onlyDelegateCall nonReentrant {
        uint64 due = sampleReceiptDue[nonce];
        uint8 state = cases[nonce].state;
        if (
            due == 0 || state == uint8(CaseState.FINAL) || state == uint8(CaseState.INCONCLUSIVE)
                || state == uint8(CaseState.UNSERVED)
        ) revert InvalidTransition();
        if (block.number <= due) revert DeadlineNotReached();
        sampleReceiptDue[nonce] = 0;
        _sellerFailure(nonce, RefundSource.UNSERVED);
    }
}
